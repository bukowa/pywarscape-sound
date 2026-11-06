"""Dedicated property inspector view for embedded WEM media items."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.features.bank_viewer.state import NodeInspectorDetails
from src.ui.theme import (
    BTN_STYLE_SECONDARY,
    COLOR_BG_INPUT,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
)

_ROLE_TARGET_KEY = Qt.ItemDataRole.UserRole + 1


class MediaInspectorView(QWidget):
    """Dedicated inspector view for embedded WEM audio files in DIDX and DATA chunks."""

    jump_requested = Signal(str)
    export_requested = Signal(int)
    revert_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_wem_id: int | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Media Info Card
        self.info_card = QFrame()
        self.info_card.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_PANEL}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; padding: 6px; }}"
        )
        ic_layout = QVBoxLayout(self.info_card)
        ic_layout.setContentsMargins(6, 6, 6, 6)
        ic_layout.setSpacing(4)

        title_row = QHBoxLayout()
        ic_title = QLabel("Embedded Media Metadata")
        ic_title.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-weight: bold;"
        )
        title_row.addWidget(ic_title)
        title_row.addStretch()

        self.badge_embedded = QLabel("EMBEDDED")
        self.badge_embedded.setStyleSheet(
            f"background-color: {COLOR_WARNING}; color: {COLOR_BG_INPUT}; "
            f"font-size: 10px; font-weight: bold; border-radius: 3px; padding: 2px 6px;"
        )
        title_row.addWidget(self.badge_embedded)
        ic_layout.addLayout(title_row)

        meta_row = QHBoxLayout()
        self.lbl_file_id = QLabel("WEM ID: -")
        self.lbl_file_id.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: 11px;")
        meta_row.addWidget(self.lbl_file_id)

        self.lbl_size = QLabel("Size: -")
        self.lbl_size.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        meta_row.addWidget(self.lbl_size)
        meta_row.addStretch()
        ic_layout.addLayout(meta_row)

        origin_row = QHBoxLayout()
        self.lbl_origin = QLabel("Source Origin: -")
        self.lbl_origin.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px;")
        self.lbl_origin.setWordWrap(True)
        origin_row.addWidget(self.lbl_origin)
        ic_layout.addLayout(origin_row)

        # Action Buttons Row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.btn_export = QPushButton("Export WAV...")
        self.btn_export.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._on_export_clicked)
        btn_row.addWidget(self.btn_export)

        self.btn_revert = QPushButton("Revert Audio to Original...")
        self.btn_revert.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_revert.setEnabled(False)
        self.btn_revert.clicked.connect(self._on_revert_clicked)
        btn_row.addWidget(self.btn_revert)

        ic_layout.addLayout(btn_row)
        layout.addWidget(self.info_card)

        # Referencing Sounds Card & Table
        self.lbl_refs = QLabel("Referencing Sounds (0) — Double-click to navigate")
        self.lbl_refs.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-weight: bold;"
        )
        layout.addWidget(self.lbl_refs)

        self.ref_table = QTableWidget(0, 4)
        self.ref_table.setHorizontalHeaderLabels(["HIRC ID", "Name / Alias", "Type", "Bank"])
        hdr = self.ref_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)
        self.ref_table.setColumnWidth(0, 85)
        self.ref_table.setColumnWidth(1, 140)
        self.ref_table.setColumnWidth(2, 85)
        self.ref_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.ref_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.ref_table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.ref_table.setStyleSheet(
            f"QTableWidget {{ background-color: {COLOR_BG_INPUT}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; color: {COLOR_TEXT_PRIMARY}; font-size: 11px; }} "
            f"QTableWidget::item {{ padding: 3px 6px; }} "
            f"QHeaderView::section {{ background-color: {COLOR_BG_PANEL}; color: {COLOR_TEXT_SECONDARY}; "
            f"font-weight: bold; border: 1px solid {COLOR_BORDER}; padding: 3px; }}"
        )
        layout.addWidget(self.ref_table, 1)

    def _on_export_clicked(self) -> None:
        if self._current_wem_id is not None:
            self.export_requested.emit(self._current_wem_id)

    def _on_revert_clicked(self) -> None:
        if self._current_wem_id is not None:
            self.revert_requested.emit(self._current_wem_id)

    def _on_cell_double_clicked(self, row: int, _col: int) -> None:
        item = self.ref_table.item(row, 0)
        if item is not None:
            target_key = item.data(_ROLE_TARGET_KEY)
            if target_key:
                self.jump_requested.emit(target_key)

    def render_details(self, details: NodeInspectorDetails | None, selected_count: int = 1) -> None:
        """Alias for render() supporting direct detail rendering."""
        self.render(details, selected_count=selected_count)

    def render(self, details: NodeInspectorDetails | None, selected_count: int = 1) -> None:
        """Projects media details and referencing sound list with strict signal blocking."""
        self.ref_table.blockSignals(True)
        if details is None:
            self._current_wem_id = None
            self.lbl_file_id.setText("WEM ID: -")
            self.lbl_size.setText("Size: -")
            self.lbl_origin.setText("Source Origin: -")
            self.lbl_refs.setText("Referencing Sounds (0) — Double-click to navigate")
            self.btn_export.setEnabled(False)
            self.btn_revert.setEnabled(False)
            self.btn_export.setText("Export WAV...")
            self.ref_table.setRowCount(0)
            self.ref_table.blockSignals(False)
            return

        self._current_wem_id = details.object_id
        has_id = details.object_id is not None
        self.btn_export.setEnabled(has_id)

        if selected_count > 1:
            self.btn_export.setText(f"Export WAV ({selected_count})...")
        else:
            self.btn_export.setText("Export WAV...")

        fid_str = str(details.object_id) if has_id else "-"
        size_str = "-"
        for p in details.properties:
            if p.label == "Size":
                size_str = p.value

        origin = getattr(details, "source_origin", "")
        if not origin:
            for p in details.properties:
                if p.label == "Source Origin":
                    origin = p.value
                    break
        origin_str = origin or "Vanilla Game Cache"
        self.lbl_origin.setText(f"Source: {origin_str}")
        is_overlay = "project overlay" in origin_str.lower()
        self.btn_revert.setEnabled(has_id and is_overlay)

        self.lbl_file_id.setText(f"WEM ID: {fid_str}")
        self.lbl_size.setText(f"Size: {size_str}")

        refs = details.audio_references if details.audio_references else details.parent_references
        ref_count = details.audio_reference_count if details.audio_reference_count else len(refs)
        self.lbl_refs.setText(f"Referencing Sounds ({ref_count}) — Double-click to navigate")
        self.ref_table.setRowCount(len(refs))
        for row, ref in enumerate(refs):
            jump_key = f"{ref.bank_name}::{ref.key}" if ref.bank_name else ref.key
            id_item = QTableWidgetItem(ref.id_str)
            id_item.setData(_ROLE_TARGET_KEY, jump_key)
            name_item = QTableWidgetItem(ref.label)
            name_item.setData(_ROLE_TARGET_KEY, jump_key)
            type_item = QTableWidgetItem(ref.type_str)
            type_item.setData(_ROLE_TARGET_KEY, jump_key)
            bank_item = QTableWidgetItem(ref.bank_name or "-")
            bank_item.setData(_ROLE_TARGET_KEY, jump_key)
            self.ref_table.setItem(row, 0, id_item)
            self.ref_table.setItem(row, 1, name_item)
            self.ref_table.setItem(row, 2, type_item)
            self.ref_table.setItem(row, 3, bank_item)
        self.ref_table.blockSignals(False)
