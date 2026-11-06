"""Default key-value properties view for chunks and unspecialized HIRC objects."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHeaderView,
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
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
)


class DefaultInspectorView(QWidget):
    """Fallback interactive properties table for chunks and unspecialized nodes."""

    jump_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.prop_table = QTableWidget(0, 2)
        self.prop_table.setHorizontalHeaderLabels(["Property", "Value"])
        hdr = self.prop_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)
        self.prop_table.setColumnWidth(0, 140)
        self.prop_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.prop_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.prop_table.setStyleSheet(
            f"QTableWidget {{ background-color: {COLOR_BG_INPUT}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; color: {COLOR_TEXT_PRIMARY}; font-size: 11px; }} "
            f"QTableWidget::item {{ padding: 3px 6px; }} "
            f"QHeaderView::section {{ background-color: {COLOR_BG_PANEL}; color: {COLOR_TEXT_SECONDARY}; "
            f"font-weight: bold; border: 1px solid {COLOR_BORDER}; padding: 3px; }}"
        )
        layout.addWidget(self.prop_table)

    def render(self, details: NodeInspectorDetails | None) -> None:
        """Renders key-value properties with strict signal blocking."""
        self.prop_table.blockSignals(True)
        if details is None or not details.properties:
            self.prop_table.setRowCount(0)
            self.prop_table.blockSignals(False)
            return

        self.prop_table.setRowCount(len(details.properties))
        for row, prop in enumerate(details.properties):
            p_item = QTableWidgetItem(prop.label)
            v_item = QTableWidgetItem(prop.value)
            self.prop_table.setItem(row, 0, p_item)
            self.prop_table.setItem(row, 1, v_item)
        self.prop_table.blockSignals(False)
