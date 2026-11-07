"""Pure PySide6 data-driven projection view for SoundBank viewing."""

import json
import logging

from PySide6.QtCore import QEvent, QItemSelectionModel, QModelIndex, QObject, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QKeySequence,
    QMouseEvent,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.engine.metadata_fields import Provenance
from src.ui.features.bank_viewer.bank_list_panel import BankListPanel
from src.ui.features.bank_viewer.columns import (
    COLUMN_SPECS,
    COLUMN_SPECS_BY_ID,
    DEFAULT_VISIBLE_COLUMNS,
    HighlightScope,
    TreeColumn,
)
from src.ui.features.bank_viewer.inspector_panel import InspectorPanel
from src.ui.features.bank_viewer.overlays import (
    DEFAULT_ACTIVE_OVERLAYS,
    OVERLAY_SPECS,
    TreeOverlay,
)
from src.ui.features.bank_viewer.state import BankViewerState, HircTreeNode
from src.ui.features.bank_viewer.store import BankViewerStore
from src.ui.menu import CheckableMenu
from src.ui.theme import (
    BTN_STYLE_SECONDARY,
    CHECKBOX_STYLE,
    COLOR_BG_INPUT,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_STATUS_MODIFIED,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    INPUT_STYLE,
)

logger = logging.getLogger(__name__)

_ROLE_NODE_KEY = Qt.ItemDataRole.UserRole + 1
_ROLE_IS_LAZY = Qt.ItemDataRole.UserRole + 2
_DEFAULT_EXPANDED_GROUPS = {"group:chunks", "group:hierarchy", "group:categories"}


class _MouseNavFilter(QObject):
    """Filters mouse back/forward button events within this viewer window."""

    def __init__(self, view: "BankViewerView") -> None:
        super().__init__(view)
        self._view = view

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        try:
            if event.type() == QEvent.Type.MouseButtonPress:
                if isinstance(event, QMouseEvent):
                    # Only handle if event occurred inside this viewer's top-level window
                    if isinstance(watched, QWidget) and watched.window() == self._view.window():
                        if event.button() == Qt.MouseButton.BackButton:
                            if self._view.store.state.can_navigate_back:
                                self._view.store.navigate_back()
                            return True
                        elif event.button() == Qt.MouseButton.ForwardButton:
                            if self._view.store.state.can_navigate_forward:
                                self._view.store.navigate_forward()
                            return True
            return super().eventFilter(watched, event)
        except KeyboardInterrupt:
            app = QApplication.instance()
            if app is not None:
                app.quit()
            return False


class BankTreeWidget(QTreeWidget):
    """QTreeWidget supporting multi-selection and drag-and-drop audio source ingestion."""

    source_dropped = Signal(tuple, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat("application/x-audio-editor-source"):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasFormat("application/x-audio-editor-source"):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if event.mimeData().hasFormat("application/x-audio-editor-source"):
            raw_bytes = event.mimeData().data("application/x-audio-editor-source")
            try:
                parsed = json.loads(bytes(raw_bytes.data()).decode("utf-8"))
                if isinstance(parsed, list):
                    paths = tuple(str(p) for p in parsed)
                elif isinstance(parsed, str):
                    paths = (parsed,)
                else:
                    paths = ()
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
                paths = ()

            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            item = self.itemAt(pos)
            target_key = item.data(0, _ROLE_NODE_KEY) if item else ""
            if not target_key and (curr := self.currentItem()) is not None:
                target_key = curr.data(0, _ROLE_NODE_KEY) or ""

            self.source_dropped.emit(paths, target_key)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class BankViewerView(QWidget):
    """Three-pane data-driven SoundBank viewer displaying bank list, tree, and inspector."""

    source_dropped = Signal(tuple, str)

    def __init__(self, store: BankViewerStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._expanded_keys: set[str] = set(_DEFAULT_EXPANDED_GROUPS)
        self._rendered_bank_name: str | None = None
        self._rendered_root_keys: tuple[str, ...] = ()
        self._rendered_tree_search_query: str = ""
        self._rendered_filter_modified_only: bool = False
        self._rendered_active_overlays: frozenset[TreeOverlay] = DEFAULT_ACTIVE_OVERLAYS
        self._rendered_visible_columns: tuple[TreeColumn, ...] = DEFAULT_VISIBLE_COLUMNS
        self._column_widths: dict[TreeColumn, int] = {s.id: s.default_width for s in COLUMN_SPECS}
        self._current_nodes: dict[str, HircTreeNode] = {}
        self._items_by_key: dict[str, QTreeWidgetItem] = {}
        self._all_items_by_key: dict[str, list[QTreeWidgetItem]] = {}
        self._init_ui()
        self._wire_signals()

        self._mouse_filter = _MouseNavFilter(self)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._mouse_filter)

        self.store.subscribe(self.render)
        self.render(self.store.state)

    def closeEvent(self, event) -> None:
        app = QApplication.instance()
        if app is not None and hasattr(self, "_mouse_filter"):
            app.removeEventFilter(self._mouse_filter)
        super().closeEvent(event)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(4)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)

        # 1. Left Pane: Bank Browser
        self.bank_list_panel = BankListPanel()
        self.splitter.addWidget(self.bank_list_panel)

        # 2. Middle Pane: Hierarchy Tree
        tree_pane = QWidget()
        tree_layout = QVBoxLayout(tree_pane)
        tree_layout.setContentsMargins(4, 4, 4, 4)
        tree_layout.setSpacing(6)

        tree_hdr_row = QHBoxLayout()
        self.lbl_tree_bank_name = QLabel("No Bank Selected")
        self.lbl_tree_bank_name.setStyleSheet(
            f"color: {COLOR_TEXT_PRIMARY}; font-weight: bold; font-size: 12px;"
        )
        tree_hdr_row.addWidget(self.lbl_tree_bank_name)
        tree_hdr_row.addStretch()
        self.lbl_tree_status = QLabel("")
        self.lbl_tree_status.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        tree_hdr_row.addWidget(self.lbl_tree_status)
        tree_layout.addLayout(tree_hdr_row)

        self.edit_tree_search = QLineEdit()
        self.edit_tree_search.setPlaceholderText("Filter hierarchy (ID, name, type)...")
        self.edit_tree_search.setStyleSheet(INPUT_STYLE)
        tree_layout.addWidget(self.edit_tree_search)

        opts_row = QHBoxLayout()
        opts_row.setContentsMargins(0, 0, 0, 0)
        opts_row.setSpacing(8)

        # Overlays menu dropdown
        self.btn_overlays = QPushButton("Overlays")
        self.btn_overlays.setStyleSheet(BTN_STYLE_SECONDARY)
        self.overlays_menu = CheckableMenu(self)
        self.overlay_actions: dict[TreeOverlay, QAction] = {}
        for ospec in OVERLAY_SPECS:
            act = QAction(ospec.label, self)
            act.setCheckable(True)
            act.setChecked(ospec.id in self._rendered_active_overlays)
            act.setToolTip(ospec.description)
            act.toggled.connect(lambda checked, o=ospec.id: self.store.set_tree_overlay(o, checked))
            self.overlays_menu.addAction(act)
            self.overlay_actions[ospec.id] = act
        self.btn_overlays.setMenu(self.overlays_menu)
        opts_row.addWidget(self.btn_overlays)

        # Columns menu dropdown
        self.btn_columns = QPushButton("Columns")
        self.btn_columns.setStyleSheet(BTN_STYLE_SECONDARY)
        self.columns_menu = CheckableMenu(self)
        self.column_actions: dict[TreeColumn, QAction] = {}
        for cspec in COLUMN_SPECS:
            act = QAction(cspec.header, self)
            act.setCheckable(True)
            act.setChecked(cspec.id in self._rendered_visible_columns)
            if not cspec.hideable:
                act.setEnabled(False)
                act.setChecked(True)
            act.toggled.connect(
                lambda checked, c=cspec.id: self.store.set_tree_column_visible(c, checked)
            )
            self.columns_menu.addAction(act)
            self.column_actions[cspec.id] = act
        self.btn_columns.setMenu(self.columns_menu)
        opts_row.addWidget(self.btn_columns)

        self.chk_show_modified_only = QCheckBox("Show Modified Only")
        self.chk_show_modified_only.setChecked(False)
        self.chk_show_modified_only.setStyleSheet(CHECKBOX_STYLE)
        opts_row.addWidget(self.chk_show_modified_only)

        opts_row.addStretch()
        tree_layout.addLayout(opts_row)

        self.tree_widget = BankTreeWidget()
        self.tree_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree_widget.setAcceptDrops(True)
        self.tree_widget.setUniformRowHeights(True)
        self.tree_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._apply_tree_columns(self._rendered_visible_columns)
        thdr = self.tree_widget.header()
        thdr.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        thdr.customContextMenuRequested.connect(self._on_header_context_menu)
        self.tree_widget.setStyleSheet(
            f"QTreeWidget {{ background-color: {COLOR_BG_INPUT}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; color: {COLOR_TEXT_PRIMARY}; font-size: 11px; }} "
            f"QHeaderView::section {{ background-color: {COLOR_BG_PANEL}; color: {COLOR_TEXT_SECONDARY}; "
            f"font-weight: bold; border: 1px solid {COLOR_BORDER}; padding: 3px; }}"
        )
        tree_layout.addWidget(self.tree_widget, 1)
        self.splitter.addWidget(tree_pane)

        # 3. Right Pane: Property Inspector
        insp_scroll = QScrollArea()
        insp_scroll.setWidgetResizable(True)
        insp_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.inspector_panel = InspectorPanel()
        insp_scroll.setWidget(self.inspector_panel)
        self.splitter.addWidget(insp_scroll)

        self.splitter.setSizes([260, 440, 360])
        main_layout.addWidget(self.splitter)

    @property
    def table_banks(self):
        return self.bank_list_panel.table_banks

    @property
    def lbl_bank_count(self):
        return self.bank_list_panel.lbl_count

    @property
    def edit_bank_search(self):
        return self.bank_list_panel.edit_search

    @property
    def chk_modified_only(self):
        return self.bank_list_panel.chk_modified_only

    @property
    def btn_open_file(self):
        return self.bank_list_panel.btn_open_file

    def _on_header_context_menu(self, pos) -> None:
        self.columns_menu.exec(self.tree_widget.header().mapToGlobal(pos))

    def _apply_tree_columns(
        self,
        visible_columns: tuple[TreeColumn, ...],
        prev_columns: tuple[TreeColumn, ...] = (),
    ) -> None:
        if prev_columns:
            last_idx = len(prev_columns) - 1
            for idx, col_id in enumerate(prev_columns):
                if idx < last_idx:
                    w = self.tree_widget.columnWidth(idx)
                    if w > 0:
                        self._column_widths[col_id] = w

        self.tree_widget.setColumnCount(len(visible_columns))
        headers = [COLUMN_SPECS_BY_ID[c].header for c in visible_columns]
        self.tree_widget.setHeaderLabels(headers)

        thdr = self.tree_widget.header()
        for idx in range(len(visible_columns)):
            thdr.setSectionResizeMode(idx, QHeaderView.ResizeMode.Interactive)
        thdr.setStretchLastSection(True)

        if len(visible_columns) == 1:
            col_id = visible_columns[0]
            w = self._column_widths.get(col_id, COLUMN_SPECS_BY_ID[col_id].default_width)
            self.tree_widget.setColumnWidth(0, w)
        else:
            for idx in range(len(visible_columns) - 1):
                col_id = visible_columns[idx]
                w = self._column_widths.get(col_id, COLUMN_SPECS_BY_ID[col_id].default_width)
                self.tree_widget.setColumnWidth(idx, w)

    def _wire_signals(self) -> None:
        self.bank_list_panel.bank_selected.connect(self.store.select_bank)
        self.bank_list_panel.search_changed.connect(self.store.set_bank_search_query)
        self.bank_list_panel.modified_toggled.connect(self.store.toggle_filter_modified_only)
        self.bank_list_panel.open_file_clicked.connect(self._on_open_file_clicked)
        self.bank_list_panel.bank_revert_requested.connect(self._on_bank_revert_requested)

        self.edit_tree_search.textChanged.connect(self.store.set_tree_search_query)
        self.chk_show_modified_only.toggled.connect(self.store.set_tree_modified_filter)
        self.tree_widget.source_dropped.connect(self.source_dropped.emit)
        self.tree_widget.itemSelectionChanged.connect(self._on_tree_selection_changed)
        self.tree_widget.itemExpanded.connect(self._on_tree_item_expanded)
        self.tree_widget.itemCollapsed.connect(self._on_tree_item_collapsed)
        self.tree_widget.customContextMenuRequested.connect(self._on_tree_context_menu)

        self.inspector_panel.navigate_back.connect(self.store.navigate_back)
        self.inspector_panel.navigate_forward.connect(self.store.navigate_forward)
        self.inspector_panel.jump_requested.connect(self.store.jump_to_node)
        self.inspector_panel.reference_media_requested.connect(self._on_reference_media)
        self.inspector_panel.export_sound_requested.connect(self._on_export_sound)
        self.inspector_panel.export_media_requested.connect(self._on_export_media)
        self.inspector_panel.revert_media_requested.connect(self._on_wem_revert_requested)

        self._shortcut_back = QShortcut(QKeySequence(Qt.Modifier.ALT | Qt.Key.Key_Left), self)
        self._shortcut_back.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._shortcut_back.activated.connect(self._on_shortcut_back)

        self._shortcut_forward = QShortcut(QKeySequence(Qt.Modifier.ALT | Qt.Key.Key_Right), self)
        self._shortcut_forward.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._shortcut_forward.activated.connect(self._on_shortcut_forward)

        self._shortcut_undo = QShortcut(QKeySequence.StandardKey.Undo, self)
        self._shortcut_undo.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._shortcut_undo.activated.connect(self._on_shortcut_undo)

        self._shortcut_redo = QShortcut(QKeySequence.StandardKey.Redo, self)
        self._shortcut_redo.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._shortcut_redo.activated.connect(self._on_shortcut_redo)

    def _on_shortcut_undo(self) -> None:
        if self.store.can_undo_mutation:
            self.store.undo_mutation()
        elif self.store.state.can_navigate_back:
            self.store.navigate_back()

    def _on_shortcut_redo(self) -> None:
        if self.store.can_redo_mutation:
            self.store.redo_mutation()
        elif self.store.state.can_navigate_forward:
            self.store.navigate_forward()

    def _on_shortcut_back(self) -> None:
        if self.store.state.can_navigate_back:
            self.store.navigate_back()

    def _on_shortcut_forward(self) -> None:
        if self.store.state.can_navigate_forward:
            self.store.navigate_forward()

    def _on_open_file_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open SoundBank", "", "SoundBanks (*.bnk);;All Files (*)"
        )
        if path:
            self.store.load_bank_file(path)

    def _on_reference_media(self, sound_id: int, target_wem_id: int) -> None:
        self.store.reference_sound_media(sound_id, target_wem_id)

    def _on_export_sound(self, sound_id: int) -> None:
        selected_keys = self.store.state.selected_node_keys
        target_key = f"hirc:{sound_id}"
        if len(selected_keys) == 1 and next(iter(selected_keys)).startswith(f"hirc:{sound_id}:"):
            target_key = next(iter(selected_keys))
        if len(selected_keys) > 1 and (
            target_key in selected_keys
            or any(k.startswith(f"hirc:{sound_id}:") for k in selected_keys)
        ):
            self._export_batch_nodes(list(selected_keys))
        else:
            self._export_single_node(target_key, default_filename=f"{sound_id}.wav")

    def _on_export_media(self, wem_id: int) -> None:
        selected_keys = self.store.state.selected_node_keys
        target_key = f"media:{wem_id}"
        if len(selected_keys) > 1 and target_key in selected_keys:
            self._export_batch_nodes(list(selected_keys))
        else:
            self._export_single_node(target_key, default_filename=f"{wem_id}.wav")

    def _export_single_node(self, node_key: str, default_filename: str = "export.wav") -> None:
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Audio to WAV",
            default_filename,
            "WAV Files (*.wav);;All Files (*.*)",
        )
        if not save_path:
            return
        try:
            self.store.export_node_to_wav(node_key, save_path)
        except (ValueError, FileNotFoundError, RuntimeError, OSError) as exc:
            logger.warning("Export failed for node '%s': %s", node_key, exc)
            QMessageBox.warning(self, "Export Failed", f"Could not export audio: {exc}")

    def _export_batch_nodes(self, node_keys: list[str]) -> None:
        export_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Directory to Export WAV Files",
        )
        if not export_dir:
            return
        try:
            count = self.store.export_nodes_to_directory(node_keys, export_dir)
            QMessageBox.information(
                self,
                "Export Complete",
                f"Exported {count} audio file{'s' if count != 1 else ''} to:\n{export_dir}",
            )
        except (ValueError, FileNotFoundError, RuntimeError, OSError) as exc:
            logger.warning("Batch export failed: %s", exc)
            QMessageBox.warning(self, "Export Failed", f"Batch export failed: {exc}")

    def _on_tree_context_menu(self, pos) -> None:
        item = self.tree_widget.itemAt(pos)
        if item is None:
            return
        key = item.data(0, _ROLE_NODE_KEY)
        if not key:
            return

        selected_items = self.tree_widget.selectedItems()
        selected_keys = [
            it.data(0, _ROLE_NODE_KEY) for it in selected_items if it.data(0, _ROLE_NODE_KEY)
        ]
        if len(selected_keys) > 1 and key in selected_keys:
            menu = QMenu(self)
            act_export_batch = menu.addAction(f"Export {len(selected_keys)} Selected to WAV...")
            chosen = menu.exec(self.tree_widget.viewport().mapToGlobal(pos))
            if chosen == act_export_batch:
                self._export_batch_nodes(selected_keys)
            return

        if key.startswith("media:"):
            try:
                wem_id = int(key.removeprefix("media:"))
            except ValueError:
                return

            self.store.select_node(key)
            menu = QMenu(self)
            act_export = menu.addAction("Export to WAV...")
            act_revert = None
            if self.store.is_wem_modified(wem_id):
                act_revert = menu.addAction("Revert Audio to Baseline")

            chosen = menu.exec(self.tree_widget.viewport().mapToGlobal(pos))
            if chosen == act_export:
                self._on_export_media(wem_id)
            elif chosen == act_revert:
                self._on_wem_revert_requested(wem_id)
            return

        if not key.startswith("hirc:"):
            return
        node = self._current_nodes.get(key)
        if node is None or node.type_str != "Sound":
            return

        self.store.select_node(key)
        try:
            sound_id = int(key.removeprefix("hirc:"))
        except ValueError:
            return

        menu = QMenu(self)
        act_export = menu.addAction("Export to WAV...")
        act_ref = menu.addAction("Reference Media ID...")

        act_revert = None
        revert_target_wem: int | None = None
        entry = self.store.session.get_loaded_entry(self.store.state.selected_bank_name or "")
        if entry is not None:
            _, g_idx, _ = entry
            hirc_obj = g_idx.objects_by_id.get(sound_id)
            if hirc_obj is not None:
                mid = getattr(hirc_obj, "source_id", 0) or getattr(hirc_obj, "file_id", 0)
                if mid and self.store.is_wem_modified(mid):
                    act_revert = menu.addAction("Revert Audio to Baseline")
                    revert_target_wem = mid

        chosen = menu.exec(self.tree_widget.viewport().mapToGlobal(pos))
        if chosen == act_export:
            self._on_export_sound(sound_id)
        elif chosen == act_ref:
            self.inspector_panel.sound_view._current_sound_id = sound_id
            self.inspector_panel.sound_view._on_reference_clicked()
        elif chosen == act_revert and revert_target_wem is not None:
            self._on_wem_revert_requested(revert_target_wem)

    def _on_bank_revert_requested(self, bank_name: str) -> None:
        reply = QMessageBox.question(
            self,
            "Revert SoundBank",
            f"Are you sure you want to revert '{bank_name}' to baseline?\n\n"
            "This will discard all changes for this SoundBank and delete its unshared audio replacements.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.store.revert_bank(bank_name)

    def _on_wem_revert_requested(self, wem_id: int) -> None:
        reply = QMessageBox.question(
            self,
            "Revert Audio",
            f"Are you sure you want to revert WEM {wem_id} to original audio?\n\n"
            "This will remove the staged loose audio replacement.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.store.revert_wem(wem_id)

    def _on_tree_selection_changed(self, *args) -> None:
        selected_items = self.tree_widget.selectedItems()
        keys: list[str] = []
        for it in selected_items:
            k = it.data(0, _ROLE_NODE_KEY)
            if k:
                keys.append(k)
        keys_tuple = tuple(keys)

        current = self.tree_widget.currentItem()
        current_key = current.data(0, _ROLE_NODE_KEY) if current else None
        if current_key not in keys_tuple:
            current_key = keys_tuple[0] if keys_tuple else None

        if len(keys_tuple) > 1:
            self.store.select_nodes(keys_tuple, primary_key=current_key)
        elif len(keys_tuple) == 1:
            self.store.select_node(keys_tuple[0])
        else:
            self.store.select_node(None)

    def _on_tree_item_expanded(self, item: QTreeWidgetItem) -> None:
        key = item.data(0, _ROLE_NODE_KEY)
        if key:
            self._expanded_keys.add(key)
        first_child = item.child(0)
        if (
            item.childCount() == 1
            and first_child is not None
            and first_child.data(0, _ROLE_IS_LAZY)
        ):
            item.takeChild(0)
            node = self._current_nodes.get(key)
            if node:
                self.tree_widget.setUpdatesEnabled(False)
                try:
                    for ckey in node.child_keys:
                        cnode = self._current_nodes.get(ckey)
                        if cnode:
                            if self._rendered_filter_modified_only and not (
                                cnode.is_modified or cnode.has_modified_children
                            ):
                                continue
                            self._create_tree_item(item, cnode, node, {key, ckey})
                finally:
                    self.tree_widget.setUpdatesEnabled(True)

    def _on_tree_item_collapsed(self, item: QTreeWidgetItem) -> None:
        key = item.data(0, _ROLE_NODE_KEY)
        if key in self._expanded_keys:
            self._expanded_keys.remove(key)

    def _make_row(
        self,
        parent: QTreeWidgetItem | None,
        node: HircTreeNode,
        parent_node: HircTreeNode | None,
        *,
        is_direct_match: bool = False,
    ) -> QTreeWidgetItem:
        cells = [
            COLUMN_SPECS_BY_ID[col].cell(node, parent_node, self._rendered_active_overlays)
            for col in self._rendered_visible_columns
        ]
        item = QTreeWidgetItem(cells)
        item.setData(0, _ROLE_NODE_KEY, node.key)

        if node.key not in self._items_by_key:
            self._items_by_key[node.key] = item
        self._all_items_by_key.setdefault(node.key, []).append(item)

        for idx, col in enumerate(self._rendered_visible_columns):
            spec = COLUMN_SPECS_BY_ID[col]
            if (
                cells[idx]
                and spec.cell_provenance(node, parent_node, self._rendered_active_overlays)
                == Provenance.HEURISTIC
            ):
                item.setForeground(idx, QBrush(QColor(COLOR_TEXT_MUTED)))
                item.setToolTip(idx, "Inferred (heuristic)")

        if TreeOverlay.HIGHLIGHT_MODIFIED in self._rendered_active_overlays:
            mod_brush = QBrush(QColor(COLOR_STATUS_MODIFIED))
            for idx, col in enumerate(self._rendered_visible_columns):
                spec = COLUMN_SPECS_BY_ID[col]
                match spec.highlight_scope:
                    case HighlightScope.SELF_OR_DESCENDANT:
                        if node.is_modified or node.has_modified_children:
                            item.setForeground(idx, mod_brush)
                    case HighlightScope.SELF_ONLY:
                        if node.is_modified:
                            item.setForeground(idx, mod_brush)
                    case HighlightScope.NONE:
                        pass

        if is_direct_match:
            f0 = item.font(0)
            f0.setBold(True)
            item.setFont(0, f0)
            if TreeColumn.ID in self._rendered_visible_columns:
                id_idx = self._rendered_visible_columns.index(TreeColumn.ID)
                item.setFont(id_idx, f0)

        if parent is None:
            self.tree_widget.addTopLevelItem(item)
        else:
            parent.addChild(item)

        return item

    def _create_tree_item(
        self,
        parent: QTreeWidgetItem | None,
        node: HircTreeNode,
        parent_node: HircTreeNode | None,
        visited: set[str],
    ) -> QTreeWidgetItem:
        item = self._make_row(parent, node, parent_node, is_direct_match=False)

        if node.child_keys:
            is_expanded = node.key in self._expanded_keys
            if is_expanded:
                item.setExpanded(True)
                for ckey in node.child_keys:
                    if ckey not in visited:
                        visited.add(ckey)
                        cnode = self._current_nodes.get(ckey)
                        if cnode:
                            if self._rendered_filter_modified_only and not (
                                cnode.is_modified or cnode.has_modified_children
                            ):
                                continue
                            self._create_tree_item(item, cnode, node, visited)
            else:
                ph = QTreeWidgetItem(
                    ["Loading..."] + [""] * (len(self._rendered_visible_columns) - 1)
                )
                ph.setData(0, _ROLE_IS_LAZY, True)
                item.addChild(ph)
        return item

    def _create_filtered_tree_item(
        self,
        parent: QTreeWidgetItem | None,
        node: HircTreeNode,
        parent_node: HircTreeNode | None,
        visited: set[str],
        direct_matches: set[str],
        matching_ancestors: set[str],
        has_matching_ancestor: bool,
    ) -> QTreeWidgetItem:
        is_direct_match = node.key in direct_matches
        item = self._make_row(parent, node, parent_node, is_direct_match=is_direct_match)

        is_path_to_match = node.key in matching_ancestors
        if is_path_to_match or is_direct_match:
            item.setExpanded(True)

        effective_has_match_ancestor = has_matching_ancestor or is_direct_match
        if effective_has_match_ancestor and node.child_keys:
            item.setExpanded(True)

        if node.child_keys:
            for ckey in node.child_keys:
                if ckey in visited:
                    continue
                cnode = self._current_nodes.get(ckey)
                if not cnode:
                    continue
                if self._rendered_filter_modified_only and not (
                    cnode.is_modified or cnode.has_modified_children
                ):
                    continue

                child_visible = (
                    effective_has_match_ancestor
                    or ckey in direct_matches
                    or ckey in matching_ancestors
                )
                if child_visible:
                    new_visited = set(visited)
                    new_visited.add(ckey)
                    self._create_filtered_tree_item(
                        item,
                        cnode,
                        node,
                        new_visited,
                        direct_matches,
                        matching_ancestors,
                        has_matching_ancestor=effective_has_match_ancestor,
                    )
        return item

    def _update_tree_selection(
        self,
        selected_key: str | None,
        selected_keys: tuple[str, ...] = (),
        ensure_visible: bool = False,
    ) -> None:
        target_keys = set(selected_keys)
        if selected_key and not target_keys:
            target_keys = {selected_key}

        if not target_keys:
            self.tree_widget.blockSignals(True)
            self.tree_widget.setCurrentIndex(QModelIndex())
            self.tree_widget.clearSelection()
            self.tree_widget.blockSignals(False)
            return

        # Always expand ancestors so lazy children are created in _items_by_key.
        # This is needed regardless of ensure_visible — programmatic selection
        # (e.g. select_node("hirc:301")) must find items under collapsed categories.
        keys_needing_expansion = set()
        if selected_key and self._items_by_key.get(selected_key) is None:
            keys_needing_expansion.add(selected_key)
        for k in target_keys:
            if self._items_by_key.get(k) is None:
                keys_needing_expansion.add(k)

        if keys_needing_expansion:
            # Build parent_map once for all keys
            parent_map: dict[str, str] = {}
            for pkey, pnode in self._current_nodes.items():
                for ckey in pnode.child_keys:
                    parent_map[ckey] = pkey

            for expand_key in keys_needing_expansion:
                ancestors = []
                visited_ancestors: set[str] = set()
                curr = expand_key
                while curr in parent_map and curr not in visited_ancestors:
                    visited_ancestors.add(curr)
                    p = parent_map[curr]
                    ancestors.append(p)
                    curr = p

                # Expand ancestors top-down so lazy children are generated
                for anc in reversed(ancestors):
                    aitem = self._items_by_key.get(anc)
                    if aitem is not None:
                        if not aitem.isExpanded():
                            aitem.setExpanded(True)
                            self._on_tree_item_expanded(aitem)

        self.tree_widget.blockSignals(True)
        try:
            current_selected = {
                it.data(0, _ROLE_NODE_KEY)
                for it in self.tree_widget.selectedItems()
                if it.data(0, _ROLE_NODE_KEY)
            }
            if current_selected != target_keys:
                self.tree_widget.clearSelection()
                for k in target_keys:
                    all_matches = self._all_items_by_key.get(k)
                    if all_matches:
                        for it in all_matches:
                            it.setSelected(True)
                    else:
                        it = self._items_by_key.get(k)
                        if it is not None:
                            it.setSelected(True)

            if selected_key:
                curr_item = self.tree_widget.currentItem()
                if curr_item is not None and curr_item.data(0, _ROLE_NODE_KEY) == selected_key:
                    primary_item = curr_item
                else:
                    primary_item = self._items_by_key.get(selected_key)

                if primary_item is not None and primary_item != self.tree_widget.currentItem():
                    self.tree_widget.setCurrentItem(
                        primary_item, 0, QItemSelectionModel.SelectionFlag.NoUpdate
                    )

                if ensure_visible and primary_item is not None:
                    parent = primary_item.parent()
                    while parent is not None:
                        if not parent.isExpanded():
                            parent.setExpanded(True)
                        parent = parent.parent()
                    self.tree_widget.scrollToItem(primary_item)
        finally:
            self.tree_widget.blockSignals(False)

    def keyPressEvent(self, event) -> None:
        """Handles Alt+Left (Back) and Alt+Right (Forward) navigation shortcuts."""
        if event.modifiers() == Qt.KeyboardModifier.AltModifier:
            if event.key() == Qt.Key.Key_Left:
                if self.store.state.can_navigate_back:
                    self.store.navigate_back()
                    event.accept()
                    return
            elif event.key() == Qt.Key.Key_Right:
                if self.store.state.can_navigate_forward:
                    self.store.navigate_forward()
                    event.accept()
                    return
        super().keyPressEvent(event)

    def render(self, state: BankViewerState) -> None:
        """Projects state onto all widget surfaces with strict signal blocking."""
        # 1. Update Bank List Panel
        self.bank_list_panel.render_banks(state.filtered_banks, state.selected_bank_name)

        # 2. Update Hierarchy Tree
        bank_title = state.selected_bank_name or "No Bank Selected"
        self.lbl_tree_bank_name.setText(bank_title)
        self.lbl_tree_status.setText(state.status_message or "")

        # Update options menus and filter
        self.btn_overlays.setText(f"Overlays ({len(state.active_overlays)})")
        for ov, act in self.overlay_actions.items():
            act.blockSignals(True)
            act.setChecked(ov in state.active_overlays)
            act.blockSignals(False)

        self.btn_columns.setText(f"Columns ({len(state.visible_columns)})")
        for col, act in self.column_actions.items():
            act.blockSignals(True)
            act.setChecked(col in state.visible_columns)
            act.blockSignals(False)

        self.chk_show_modified_only.blockSignals(True)
        self.chk_show_modified_only.setChecked(state.filter_tree_modified_only)
        self.chk_show_modified_only.blockSignals(False)

        cols_changed = state.visible_columns != self._rendered_visible_columns
        tree_dirty = (
            state.selected_bank_name != self._rendered_bank_name
            or state.root_keys != self._rendered_root_keys
            or state.tree_search_query != self._rendered_tree_search_query
            or state.filter_tree_modified_only != self._rendered_filter_modified_only
            or state.active_overlays != self._rendered_active_overlays
            or cols_changed
            or state.nodes_by_key != self._current_nodes
        )
        if tree_dirty:
            if cols_changed:
                self._apply_tree_columns(state.visible_columns, self._rendered_visible_columns)
            if state.selected_bank_name != self._rendered_bank_name:
                self._expanded_keys = set(_DEFAULT_EXPANDED_GROUPS)
            self._rendered_bank_name = state.selected_bank_name
            self._rendered_root_keys = state.root_keys
            self._rendered_tree_search_query = state.tree_search_query
            self._rendered_filter_modified_only = state.filter_tree_modified_only
            self._rendered_active_overlays = state.active_overlays
            self._rendered_visible_columns = state.visible_columns
            self._render_tree(state)
        else:
            self._update_tree_selection(
                state.selected_node_key,
                selected_keys=state.selected_node_keys,
                ensure_visible=state.ensure_tree_visible,
            )

        # 3. Update Inspector
        self.inspector_panel.render_navigation_state(
            state.can_navigate_back, state.can_navigate_forward
        )
        selected_count = (
            len(state.selected_node_keys)
            if len(state.selected_node_keys) > 1
            else (1 if state.selected_node_key else 0)
        )
        self.inspector_panel.render_details(
            state.selected_node_details, selected_count=selected_count
        )

    @staticmethod
    def _node_matches_filter(
        node: HircTreeNode,
        q: str,
        active_overlays: frozenset[TreeOverlay],
        visible_columns: tuple[TreeColumn, ...],
        parent_nodes: tuple[HircTreeNode | None, ...] = (None,),
    ) -> bool:
        if not q:
            return True
        if node.key.startswith("group:") or node.key.startswith("cat:"):
            return False
        q_lower = q.lower()
        if (
            q_lower in node.label.lower()
            or q_lower in node.id_str.lower()
            or q_lower in node.type_str.lower()
            or q_lower in node.details.lower()
            or (node.friendly_label is not None and q_lower in node.friendly_label.lower())
            or (node.friendly_details is not None and q_lower in node.friendly_details.lower())
        ):
            return True

        for col_id in visible_columns:
            spec = COLUMN_SPECS_BY_ID[col_id]
            if not spec.searchable:
                continue
            for pnode in parent_nodes:
                text = spec.cell(node, pnode, active_overlays)
                if q_lower in text.lower():
                    return True
        return False

    def _render_tree(self, state: BankViewerState) -> None:
        """Renders tree nodes with lazy expansion and query filtering."""
        self.tree_widget.blockSignals(True)
        self.tree_widget.setUpdatesEnabled(False)
        try:
            self.tree_widget.clear()
            self._items_by_key.clear()
            self._all_items_by_key.clear()
            self._current_nodes = dict(state.nodes_by_key)
            if not state.nodes_by_key:
                return

            q = state.tree_search_query.strip().lower()
            if q:
                parent_map: dict[str, list[str]] = {}
                for pkey, pnode in state.nodes_by_key.items():
                    for ckey in pnode.child_keys:
                        parent_map.setdefault(ckey, []).append(pkey)

                direct_matches: set[str] = set()
                for key, node in state.nodes_by_key.items():
                    pnodes = tuple(
                        state.nodes_by_key.get(pkey)
                        for pkey in parent_map.get(key, ())
                        if pkey in state.nodes_by_key
                    )
                    parent_nodes: tuple[HircTreeNode | None, ...] = (None, *pnodes)
                    if self._node_matches_filter(
                        node,
                        q,
                        state.active_overlays,
                        state.visible_columns,
                        parent_nodes=parent_nodes,
                    ):
                        if self._rendered_filter_modified_only and not (
                            node.is_modified or node.has_modified_children
                        ):
                            continue
                        direct_matches.add(key)

                matching_ancestors: set[str] = set()
                queue = list(direct_matches)
                while queue:
                    curr = queue.pop()
                    for pkey in parent_map.get(curr, ()):
                        if pkey not in matching_ancestors:
                            matching_ancestors.add(pkey)
                            queue.append(pkey)

                for rkey in state.root_keys:
                    if rkey in matching_ancestors or rkey in direct_matches:
                        rnode = state.nodes_by_key.get(rkey)
                        if rnode:
                            self._create_filtered_tree_item(
                                None,
                                rnode,
                                None,
                                {rkey},
                                direct_matches,
                                matching_ancestors,
                                has_matching_ancestor=False,
                            )
            else:
                for rkey in state.root_keys:
                    rnode = state.nodes_by_key.get(rkey)
                    if rnode:
                        if self._rendered_filter_modified_only and not (
                            rnode.is_modified or rnode.has_modified_children
                        ):
                            continue
                        self._create_tree_item(None, rnode, None, {rkey})

            self._update_tree_selection(
                state.selected_node_key,
                selected_keys=state.selected_node_keys,
                ensure_visible=state.ensure_tree_visible,
            )
        finally:
            self.tree_widget.setUpdatesEnabled(True)
            self.tree_widget.blockSignals(False)
