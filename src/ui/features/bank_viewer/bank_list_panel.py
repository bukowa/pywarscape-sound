"""Pure PySide6 projection widget for the SoundBank list panel."""

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.engine.capabilities import classify_bank_group, get_capability_matrix
from src.ui.features.bank_viewer.state import BankListItem, BankStatus
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


class BankListPanel(QWidget):
    """Panel displaying soundbank list grouped by parent category or flat table, with search and filter."""

    bank_selected = Signal(str)
    search_changed = Signal(str)
    modified_toggled = Signal(bool)
    open_file_clicked = Signal()
    bank_revert_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rendered_banks: tuple[BankListItem, ...] = ()
        self._bank_by_name: dict[str, BankListItem] = {}
        self._table_rows_by_bank: dict[str, int] = {}
        self._tree_items_by_bank: dict[str, QTreeWidgetItem] = {}
        self._group_expanded: dict[str, bool] = {}

        self._init_ui()
        self._wire_signals()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        hdr_row = QHBoxLayout()
        self.lbl_title = QLabel("SOUNDBANKS")
        self.lbl_title.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-weight: bold; font-size: 11px;"
        )
        hdr_row.addWidget(self.lbl_title)
        hdr_row.addStretch()

        self.btn_view_mode = QPushButton("Flat")
        self.btn_view_mode.setToolTip("Toggle between grouped tree and flat list view")
        self.btn_view_mode.setStyleSheet(
            f"QPushButton {{ background-color: transparent; color: {COLOR_TEXT_MUTED}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 3px; font-size: 10px; padding: 1px 5px; }} "
            f"QPushButton:hover {{ color: {COLOR_TEXT_PRIMARY}; background-color: {COLOR_BG_PANEL}; }}"
        )
        hdr_row.addWidget(self.btn_view_mode)

        self.lbl_count = QLabel("0 banks")
        self.lbl_count.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        hdr_row.addWidget(self.lbl_count)
        layout.addLayout(hdr_row)

        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("Filter soundbanks (.bnk)...")
        self.edit_search.setStyleSheet(INPUT_STYLE)
        layout.addWidget(self.edit_search)

        self.chk_modified_only = QCheckBox("Show Modified Only")
        self.chk_modified_only.setStyleSheet(CHECKBOX_STYLE)
        layout.addWidget(self.chk_modified_only)

        # 1. Grouped SoundBank Tree Widget
        self.tree_banks = QTreeWidget()
        self.tree_banks.setColumnCount(3)
        self.tree_banks.setHeaderLabels(["SoundBank", "Status", "Size"])
        tree_hdr = self.tree_banks.header()
        tree_hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        tree_hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        tree_hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        tree_hdr.setStretchLastSection(True)
        self.tree_banks.setColumnWidth(0, 160)
        self.tree_banks.setColumnWidth(1, 80)
        self.tree_banks.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self.tree_banks.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.tree_banks.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        self.tree_banks.setStyleSheet(
            f"QTreeWidget {{ background-color: {COLOR_BG_INPUT}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; color: {COLOR_TEXT_PRIMARY}; font-size: 11px; }} "
            f"QHeaderView::section {{ background-color: {COLOR_BG_PANEL}; color: {COLOR_TEXT_SECONDARY}; "
            f"font-weight: bold; border: 1px solid {COLOR_BORDER}; padding: 3px; }}"
        )
        self.tree_banks.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # 2. Flat SoundBank Table Widget (retained for backward compatibility and alternate view)
        self.table_banks = QTableWidget(0, 3)
        self.table_banks.setHorizontalHeaderLabels(["SoundBank", "Status", "Size"])
        tbl_hdr = self.table_banks.horizontalHeader()
        tbl_hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        tbl_hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        tbl_hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        tbl_hdr.setStretchLastSection(True)
        self.table_banks.setColumnWidth(0, 160)
        self.table_banks.setColumnWidth(1, 80)
        self.table_banks.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_banks.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_banks.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_banks.setStyleSheet(
            f"QTableWidget {{ background-color: {COLOR_BG_INPUT}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; color: {COLOR_TEXT_PRIMARY}; font-size: 11px; }} "
            f"QHeaderView::section {{ background-color: {COLOR_BG_PANEL}; color: {COLOR_TEXT_SECONDARY}; "
            f"font-weight: bold; border: 1px solid {COLOR_BORDER}; padding: 3px; }}"
        )
        self.table_banks.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # Stack to host grouped tree (index 0) and flat table (index 1)
        self.view_stack = QStackedWidget(self)
        self.view_stack.addWidget(self.tree_banks)
        self.view_stack.addWidget(self.table_banks)
        self.view_stack.setCurrentIndex(0)
        layout.addWidget(self.view_stack, 1)

        self.btn_open_file = QPushButton("Open .bnk File...")
        self.btn_open_file.setStyleSheet(BTN_STYLE_SECONDARY)
        layout.addWidget(self.btn_open_file)

    def _wire_signals(self) -> None:
        self.edit_search.textChanged.connect(self.search_changed.emit)
        self.chk_modified_only.toggled.connect(self.modified_toggled.emit)
        self.btn_open_file.clicked.connect(self.open_file_clicked.emit)
        self.btn_view_mode.clicked.connect(self._on_toggle_view_mode)

        # Flat table events
        self.table_banks.itemSelectionChanged.connect(self._on_table_selection)
        self.table_banks.customContextMenuRequested.connect(self._on_table_context_menu)

        # Group tree events
        self.tree_banks.itemSelectionChanged.connect(self._on_tree_selection)
        self.tree_banks.itemClicked.connect(self._on_tree_item_clicked)
        self.tree_banks.customContextMenuRequested.connect(self._on_tree_context_menu)
        self.tree_banks.itemExpanded.connect(self._on_tree_item_expanded)
        self.tree_banks.itemCollapsed.connect(self._on_tree_item_collapsed)

    def _on_toggle_view_mode(self) -> None:
        if self.view_stack.currentIndex() == 0:
            self.set_view_mode("flat")
        else:
            self.set_view_mode("tree")

    def set_view_mode(self, mode: str) -> None:
        """Sets view mode: 'tree' for grouped tree view, 'flat' for flat table view."""
        if mode == "flat":
            self.view_stack.setCurrentIndex(1)
            self.btn_view_mode.setText("Tree")
        else:
            self.view_stack.setCurrentIndex(0)
            self.btn_view_mode.setText("Flat")

    @property
    def is_tree_view(self) -> bool:
        return self.view_stack.currentIndex() == 0

    def _on_tree_item_expanded(self, item: QTreeWidgetItem) -> None:
        key = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if key:
            self._group_expanded[key] = True

    def _on_tree_item_collapsed(self, item: QTreeWidgetItem) -> None:
        key = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if key:
            self._group_expanded[key] = False

    def _on_table_context_menu(self, pos) -> None:
        row = self.table_banks.rowAt(pos.y())
        if row < 0 or row >= len(self._rendered_banks):
            return
        bank_item = self._rendered_banks[row]
        menu = QMenu(self)
        act_revert = menu.addAction(f"Revert '{bank_item.name}' to Baseline...")
        act_revert.setEnabled(bank_item.status == BankStatus.MODIFIED)
        chosen = menu.exec(self.table_banks.viewport().mapToGlobal(pos))
        if chosen == act_revert:
            self.bank_revert_requested.emit(bank_item.name)

    def _create_tree_context_menu(self, item: QTreeWidgetItem) -> tuple[QMenu, object] | None:
        """Constructs context menu for a tree item, or None if item is not a bank."""
        bank_name = item.data(0, Qt.ItemDataRole.UserRole)
        if not bank_name:
            return None
        bank_item = self._bank_by_name.get(bank_name.lower())
        if not bank_item:
            return None
        menu = QMenu(self)
        act_revert = menu.addAction(f"Revert '{bank_item.name}' to Baseline...")
        act_revert.setEnabled(bank_item.status == BankStatus.MODIFIED)
        return menu, act_revert

    def _on_tree_context_menu(self, pos) -> None:
        item = self.tree_banks.itemAt(pos)
        if not item:
            return
        res = self._create_tree_context_menu(item)
        if not res:
            return
        menu, act_revert = res
        bank_name = item.data(0, Qt.ItemDataRole.UserRole)
        chosen = menu.exec(self.tree_banks.viewport().mapToGlobal(pos))
        if chosen == act_revert and bank_name:
            self.bank_revert_requested.emit(bank_name)

    def _on_table_selection(self) -> None:
        row = self.table_banks.currentRow()
        if row >= 0:
            item = self.table_banks.item(row, 0)
            if item:
                bank_name = item.text()
                self._sync_tree_selection(bank_name)
                self.bank_selected.emit(bank_name)

    def _on_tree_selection(self) -> None:
        item = self.tree_banks.currentItem()
        if not item:
            return
        bank_name = item.data(0, Qt.ItemDataRole.UserRole)
        if bank_name:
            self._sync_table_selection(bank_name)
            self.bank_selected.emit(bank_name)

    def _on_tree_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        bank_name = item.data(0, Qt.ItemDataRole.UserRole)
        if bank_name:
            self._sync_table_selection(bank_name)
            self.bank_selected.emit(bank_name)

    def _sync_table_selection(self, bank_name: str) -> None:
        clean = bank_name.lower()
        row = self._table_rows_by_bank.get(clean)
        if row is not None and self.table_banks.currentRow() != row:
            self.table_banks.blockSignals(True)
            self.table_banks.selectRow(row)
            self.table_banks.blockSignals(False)

    def _sync_tree_selection(self, bank_name: str) -> None:
        clean = bank_name.lower()
        tree_item = self._tree_items_by_bank.get(clean)
        if tree_item is not None and self.tree_banks.currentItem() != tree_item:
            self.tree_banks.blockSignals(True)
            self.tree_banks.setCurrentItem(tree_item)
            p = tree_item.parent()
            while p:
                p.setExpanded(True)
                p = p.parent()
            self.tree_banks.scrollToItem(tree_item)
            self.tree_banks.blockSignals(False)

    def render_banks(self, banks: Sequence[BankListItem], selected_name: str | None) -> None:
        """Projects bank list descriptors onto grouped tree and flat table with signal blocking and diffing."""
        self.lbl_count.setText(f"{len(banks)} banks")

        self.table_banks.blockSignals(True)
        self.tree_banks.blockSignals(True)

        banks_tuple = tuple(banks)
        if getattr(self, "_rendered_banks", None) != banks_tuple:
            self._rendered_banks = banks_tuple
            self._bank_by_name = {b.name.lower(): b for b in banks}
            self._table_rows_by_bank = {b.name.lower(): i for i, b in enumerate(banks)}
            self._tree_items_by_bank = {}

            # 1. Update Flat Table
            self.table_banks.setRowCount(len(banks))
            for row, b in enumerate(banks):
                n_item = QTableWidgetItem(b.name)
                s_item = QTableWidgetItem(b.status.value)
                if b.status == BankStatus.MODIFIED:
                    s_item.setForeground(QColor(COLOR_STATUS_MODIFIED))
                sz_item = QTableWidgetItem(b.display_size)
                self.table_banks.setItem(row, 0, n_item)
                self.table_banks.setItem(row, 1, s_item)
                self.table_banks.setItem(row, 2, sz_item)

            # 2. Update Grouped Tree
            self.tree_banks.clear()
            is_searching = bool(self.edit_search.text().strip())

            matrix_groups = get_capability_matrix().bank_groups
            groups_order: list[str] = [g.label for g in matrix_groups]
            group_specs = {g.label: g for g in matrix_groups}

            # Group banks by category and subgroup
            grouped: dict[str, dict[str | None, list[BankListItem]]] = {}
            for b in banks:
                grp, sub = classify_bank_group(b.name)
                if grp not in grouped:
                    grouped[grp] = {}
                if sub not in grouped[grp]:
                    grouped[grp][sub] = []
                grouped[grp][sub].append(b)

            for grp in grouped:
                if grp not in groups_order:
                    groups_order.append(grp)

            for grp in groups_order:
                sub_dict = grouped.get(grp)
                if not sub_dict:
                    continue
                total_in_grp = sum(len(items) for items in sub_dict.values())
                if total_in_grp == 0:
                    continue

                count_str = f"{total_in_grp} banks" if total_in_grp != 1 else "1 bank"
                grp_item = QTreeWidgetItem([grp, "", count_str])
                gf = grp_item.font(0)
                gf.setBold(True)
                grp_item.setFont(0, gf)
                grp_item.setData(0, Qt.ItemDataRole.UserRole, None)
                grp_key = f"group:{grp}"
                grp_item.setData(0, Qt.ItemDataRole.UserRole + 1, grp_key)
                grp_item.setFlags(grp_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.tree_banks.addTopLevelItem(grp_item)

                spec = group_specs.get(grp)
                known_subgroups = spec.sub_groups if spec else ()

                # Direct children with sub is None
                for b in sub_dict.get(None, []):
                    leaf = QTreeWidgetItem([b.name, b.status.value, b.display_size])
                    leaf.setData(0, Qt.ItemDataRole.UserRole, b.name)
                    if b.status == BankStatus.MODIFIED:
                        leaf.setForeground(1, QColor(COLOR_STATUS_MODIFIED))
                    grp_item.addChild(leaf)
                    self._tree_items_by_bank[b.name.lower()] = leaf

                # Culture subgroups or other subgroups
                all_subgroups = list(known_subgroups)
                for sub in sub_dict:
                    if sub is not None and sub not in all_subgroups:
                        all_subgroups.append(sub)

                for sub in all_subgroups:
                    sub_banks = sub_dict.get(sub)
                    if not sub_banks:
                        continue
                    sub_count_str = f"{len(sub_banks)} banks" if len(sub_banks) != 1 else "1 bank"
                    sub_item = QTreeWidgetItem([sub, "", sub_count_str])
                    sf = sub_item.font(0)
                    sf.setBold(True)
                    sub_item.setFont(0, sf)
                    sub_item.setData(0, Qt.ItemDataRole.UserRole, None)
                    sub_key = f"subgroup:{grp}/{sub}"
                    sub_item.setData(0, Qt.ItemDataRole.UserRole + 1, sub_key)
                    sub_item.setFlags(sub_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    grp_item.addChild(sub_item)

                    for b in sub_banks:
                        leaf = QTreeWidgetItem([b.name, b.status.value, b.display_size])
                        leaf.setData(0, Qt.ItemDataRole.UserRole, b.name)
                        if b.status == BankStatus.MODIFIED:
                            leaf.setForeground(1, QColor(COLOR_STATUS_MODIFIED))
                        sub_item.addChild(leaf)
                        self._tree_items_by_bank[b.name.lower()] = leaf

                    sub_expanded = self._group_expanded.get(sub_key, True)
                    if is_searching:
                        sub_expanded = True
                    sub_item.setExpanded(sub_expanded)

                default_expanded = not spec.collapsed_by_default if spec else True
                grp_expanded = self._group_expanded.get(grp_key, default_expanded)
                if is_searching:
                    grp_expanded = True
                grp_item.setExpanded(grp_expanded)

        # Apply Selection
        if selected_name:
            clean_sel = selected_name.lower()
            # 1. Select in flat table
            row = self._table_rows_by_bank.get(clean_sel)
            if row is not None:
                current_row = self.table_banks.currentRow()
                if current_row != row:
                    self.table_banks.selectRow(row)
            elif self.table_banks.currentRow() >= 0:
                self.table_banks.clearSelection()

            # 2. Select in grouped tree
            tree_item = self._tree_items_by_bank.get(clean_sel)
            if tree_item is not None:
                if self.tree_banks.currentItem() != tree_item:
                    self.tree_banks.setCurrentItem(tree_item)
                    p = tree_item.parent()
                    while p:
                        p.setExpanded(True)
                        p = p.parent()
                    self.tree_banks.scrollToItem(tree_item)
            else:
                self.tree_banks.clearSelection()
        else:
            if self.table_banks.currentRow() >= 0:
                self.table_banks.clearSelection()
            self.tree_banks.clearSelection()

        self.table_banks.blockSignals(False)
        self.tree_banks.blockSignals(False)
