"""
Pure PySide6 projection widget displaying registered Sound Libraries.
Provides library list table, selection dispatch, and Add/Rename/Remove actions.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.features.audio_sources.state import LibraryRow
from src.ui.theme import (
    BTN_STYLE_SECONDARY,
    COLOR_BG_INPUT,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
)


class LibrariesTableWidget(QWidget):
    """Widget managing sound libraries table and management buttons."""

    library_selected = Signal(object)  # Optional[str]
    add_requested = Signal(str)  # chosen_dir_path
    rename_requested = Signal(str, str)  # library_id, new_name
    remove_requested = Signal(str)  # library_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()
        self._wire_signals()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Path", "Files", "Status"])
        hdr = self.table.horizontalHeader()
        for i in range(4):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)

        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 160)
        self.table.setColumnWidth(2, 50)
        self.table.setColumnWidth(3, 70)

        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setStyleSheet(
            f"QTableWidget {{ background-color: {COLOR_BG_INPUT}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; color: {COLOR_TEXT_PRIMARY}; font-size: 11px; }} "
            f"QHeaderView::section {{ background-color: {COLOR_BG_PANEL}; color: {COLOR_TEXT_SECONDARY}; "
            f"font-weight: bold; border: 1px solid {COLOR_BORDER}; padding: 3px; }}"
        )
        layout.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.btn_add = QPushButton("Add...")
        self.btn_add.setStyleSheet(BTN_STYLE_SECONDARY)
        btn_row.addWidget(self.btn_add)

        self.btn_rename = QPushButton("Rename...")
        self.btn_rename.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_rename.setEnabled(False)
        btn_row.addWidget(self.btn_rename)

        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_remove.setEnabled(False)
        btn_row.addWidget(self.btn_remove)

        layout.addLayout(btn_row)

    def _wire_signals(self) -> None:
        self.table.itemSelectionChanged.connect(self._on_table_selection)
        self.btn_add.clicked.connect(self._on_add_clicked)
        self.btn_rename.clicked.connect(self._on_rename_clicked)
        self.btn_remove.clicked.connect(self._on_remove_clicked)

    def _on_table_selection(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            item = self.table.item(row, 0)
            if item:
                lib_id = item.data(Qt.ItemDataRole.UserRole)
                self.btn_rename.setEnabled(True)
                self.btn_remove.setEnabled(True)
                self.library_selected.emit(lib_id)
                return
        self.btn_rename.setEnabled(False)
        self.btn_remove.setEnabled(False)
        self.library_selected.emit(None)

    def _on_add_clicked(self) -> None:
        chosen_dir = QFileDialog.getExistingDirectory(self, "Select Sound Library Directory")
        if chosen_dir:
            self.add_requested.emit(chosen_dir)

    def _on_rename_clicked(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if not item:
            return
        lib_id = item.data(Qt.ItemDataRole.UserRole)
        current_name = item.text()
        new_name, ok = QInputDialog.getText(
            self, "Rename Sound Library", "New library name:", text=current_name
        )
        if ok and new_name.strip():
            self.rename_requested.emit(lib_id, new_name.strip())

    def _on_remove_clicked(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if not item:
            return
        lib_id = item.data(Qt.ItemDataRole.UserRole)
        self.remove_requested.emit(lib_id)

    def render_libraries(self, libraries: Sequence[LibraryRow], selected_id: str | None) -> None:
        """Renders library rows and updates selection with strict signal blocking."""
        self.table.blockSignals(True)
        self.table.setRowCount(len(libraries))

        selected_row: int | None = None
        for row_idx, lib in enumerate(libraries):
            name_item = QTableWidgetItem(lib.name)
            name_item.setData(Qt.ItemDataRole.UserRole, lib.id)
            path_item = QTableWidgetItem(lib.path)
            files_item = QTableWidgetItem(str(lib.file_count))
            status_item = QTableWidgetItem("Available" if lib.is_available else "Missing")

            self.table.setItem(row_idx, 0, name_item)
            self.table.setItem(row_idx, 1, path_item)
            self.table.setItem(row_idx, 2, files_item)
            self.table.setItem(row_idx, 3, status_item)

            if selected_id is not None and lib.id == selected_id:
                selected_row = row_idx

        if selected_row is not None:
            self.table.selectRow(selected_row)
            self.btn_rename.setEnabled(True)
            self.btn_remove.setEnabled(True)
        else:
            self.table.clearSelection()
            self.btn_rename.setEnabled(False)
            self.btn_remove.setEnabled(False)

        self.table.blockSignals(False)
