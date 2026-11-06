"""Dedicated property inspector view for CAkEvent and CAkAction nodes."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.features.bank_viewer.state import NodeInspectorDetails
from src.ui.theme import (
    COLOR_BG_INPUT,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
)

_ROLE_TARGET_KEY = Qt.ItemDataRole.UserRole + 1


class EventActionInspectorView(QWidget):
    """Dedicated inspector view for CAkEvent and CAkAction nodes."""

    jump_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Summary Card
        self.summary_card = QFrame()
        self.summary_card.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_PANEL}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; padding: 6px; }}"
        )
        sc_layout = QVBoxLayout(self.summary_card)
        sc_layout.setContentsMargins(6, 6, 6, 6)
        sc_layout.setSpacing(4)

        self.lbl_type_header = QLabel("Event / Action Configuration")
        self.lbl_type_header.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-weight: bold;"
        )
        sc_layout.addWidget(self.lbl_type_header)

        info_row = QHBoxLayout()
        self.lbl_info_primary = QLabel("Type: -")
        self.lbl_info_primary.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: 11px;")
        info_row.addWidget(self.lbl_info_primary)

        self.lbl_info_secondary = QLabel("Target: -")
        self.lbl_info_secondary.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        info_row.addWidget(self.lbl_info_secondary)
        info_row.addStretch()
        sc_layout.addLayout(info_row)
        layout.addWidget(self.summary_card)

        # Linked Targets / Actions Table
        self.lbl_table_header = QLabel("Linked Objects (Double-click to navigate)")
        self.lbl_table_header.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-weight: bold;"
        )
        layout.addWidget(self.lbl_table_header)

        self.targets_table = QTableWidget(0, 3)
        self.targets_table.setHorizontalHeaderLabels(["ID", "Name / Alias", "Type"])
        hdr = self.targets_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)
        self.targets_table.setColumnWidth(0, 85)
        self.targets_table.setColumnWidth(1, 150)
        self.targets_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.targets_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.targets_table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.targets_table.setStyleSheet(
            f"QTableWidget {{ background-color: {COLOR_BG_INPUT}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; color: {COLOR_TEXT_PRIMARY}; font-size: 11px; }} "
            f"QTableWidget::item {{ padding: 3px 6px; }} "
            f"QHeaderView::section {{ background-color: {COLOR_BG_PANEL}; color: {COLOR_TEXT_SECONDARY}; "
            f"font-weight: bold; border: 1px solid {COLOR_BORDER}; padding: 3px; }}"
        )
        layout.addWidget(self.targets_table, 1)

    def _on_cell_double_clicked(self, row: int, _col: int) -> None:
        item = self.targets_table.item(row, 0)
        if item is not None:
            target_key = item.data(_ROLE_TARGET_KEY)
            if target_key:
                self.jump_requested.emit(target_key)

    def render(self, details: NodeInspectorDetails | None) -> None:
        """Projects event/action details with strict signal blocking."""
        self.targets_table.blockSignals(True)
        if details is None:
            self.lbl_info_primary.setText("Type: -")
            self.lbl_info_secondary.setText("Target: -")
            self.targets_table.setRowCount(0)
            self.targets_table.blockSignals(False)
            return

        is_event = details.object_type == "Event"
        self.lbl_type_header.setText("Event Configuration" if is_event else "Action Configuration")
        self.lbl_table_header.setText("Actions" if is_event else "Action Targets")

        prim = "-"
        sec = "-"
        for p in details.properties:
            if "Action Count" in p.label or "Action Type" in p.label:
                prim = f"{p.label}: {p.value}"
            elif "Target ID" in p.label:
                sec = f"Target: {p.value}"

        self.lbl_info_primary.setText(prim)
        self.lbl_info_secondary.setText(sec)

        targets = details.child_references
        self.targets_table.setRowCount(len(targets))
        for row, tgt in enumerate(targets):
            jump_key = f"{tgt.bank_name}::{tgt.key}" if tgt.bank_name else tgt.key
            id_item = QTableWidgetItem(tgt.id_str)
            id_item.setData(_ROLE_TARGET_KEY, jump_key)
            name_item = QTableWidgetItem(tgt.label)
            name_item.setData(_ROLE_TARGET_KEY, jump_key)
            type_item = QTableWidgetItem(tgt.type_str)
            type_item.setData(_ROLE_TARGET_KEY, jump_key)
            self.targets_table.setItem(row, 0, id_item)
            self.targets_table.setItem(row, 1, name_item)
            self.targets_table.setItem(row, 2, type_item)
        self.targets_table.blockSignals(False)
