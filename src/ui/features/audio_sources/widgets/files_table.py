"""
Pure PySide6 projection widget displaying audio files inside the selected Sound Library.
High-performance virtualized QTableView backed by QAbstractTableModel with O(1) viewport rendering.
Supports search filtering, multi-selection, and drag-and-drop replacement dispatch.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QItemSelection,
    QItemSelectionModel,
    QMimeData,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from src.ui.theme import (
    COLOR_ACCENT,
    COLOR_BG_INPUT,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_BRIGHT,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    INPUT_STYLE,
)
from src.workspace.sound_library import LibraryFileEntry


def _format_size(size_bytes: int) -> str:
    """Formats raw byte count into human-readable B, KB, or MB."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024.0:.1f} KB"
    return f"{size_bytes / (1024.0 * 1024.0):.1f} MB"


TABLE_STYLE = f"""
QTableView {{
    background-color: {COLOR_BG_INPUT};
    color: {COLOR_TEXT_PRIMARY};
    gridline-color: {COLOR_BORDER};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    selection-background-color: {COLOR_ACCENT};
    selection-color: {COLOR_TEXT_BRIGHT};
    font-size: 11px;
}}
QTableView::item:selected {{
    background-color: {COLOR_ACCENT};
    color: {COLOR_TEXT_BRIGHT};
}}
QHeaderView::section {{
    background-color: {COLOR_BG_PANEL};
    color: {COLOR_TEXT_SECONDARY};
    padding: 3px 6px;
    border: 1px solid {COLOR_BORDER};
    font-weight: bold;
    font-size: 11px;
}}
"""


class LibraryFilesTableModel(QAbstractTableModel):
    """Virtualized, memory-efficient table model for library audio file entries."""

    COLUMNS = ("Name", "Folder", "Size")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: tuple[LibraryFileEntry, ...] = ()
        self._filtered_entries: tuple[LibraryFileEntry, ...] = ()
        self._filter_text: str = ""

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._filtered_entries)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return len(self.COLUMNS)

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ):
        if not index.isValid() or not (0 <= index.row() < len(self._filtered_entries)):
            return None

        entry = self._filtered_entries[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return os.path.basename(entry.rel_path)
            elif col == 1:
                folder = os.path.dirname(entry.rel_path).replace("\\", "/")
                return folder if folder != "." else ""
            elif col == 2:
                return _format_size(entry.size_bytes)
        elif role == Qt.ItemDataRole.UserRole:
            return str(entry.abs_path)

        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self.COLUMNS):
                return self.COLUMNS[section]
        return None

    def set_entries(self, entries: Sequence[LibraryFileEntry], filter_text: str) -> None:
        """Atomically updates displayed entries with instant in-memory filtering."""
        clean = filter_text.strip().lower()
        if clean:
            filtered = tuple(e for e in entries if clean in e.rel_path.lower())
        else:
            filtered = tuple(entries)

        self.beginResetModel()
        self._entries = tuple(entries)
        self._filtered_entries = filtered
        self._filter_text = filter_text
        self.endResetModel()

    def entry_at(self, row: int) -> LibraryFileEntry | None:
        """Returns typed LibraryFileEntry for a given visible model row."""
        if 0 <= row < len(self._filtered_entries):
            return self._filtered_entries[row]
        return None

    @property
    def filtered_entries(self) -> tuple[LibraryFileEntry, ...]:
        return self._filtered_entries


class DraggableFilesTable(QTableView):
    """Virtualized QTableView supporting drag start with application/x-audio-editor-source payload."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._files_model = LibraryFilesTableModel(parent=self)
        self.setModel(self._files_model)
        self.setStyleSheet(TABLE_STYLE)
        self.setDragEnabled(True)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)

        hdr = self.horizontalHeader()
        for i in range(3):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)

        self.setColumnWidth(0, 180)
        self.setColumnWidth(1, 140)

    @property
    def files_model(self) -> LibraryFilesTableModel:
        return self._files_model

    def rowCount(self) -> int:
        """Convenience helper returning count of currently visible rows."""
        return self._files_model.rowCount()

    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        selected_rows = sorted(set(idx.row() for idx in self.selectedIndexes()))
        paths: list[str] = []
        for r in selected_rows:
            entry = self._files_model.entry_at(r)
            if entry is not None:
                paths.append(str(entry.abs_path))

        if not paths:
            return

        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setData(
            "application/x-audio-editor-source",
            json.dumps(paths).encode("utf-8"),
        )
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction)


class FilesTableWidget(QWidget):
    """Widget managing audio files table with live search and drag-and-drop support."""

    files_selected = Signal(tuple)  # tuple[Path, ...]
    filter_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._is_updating_ui = False
        self._last_files: tuple[LibraryFileEntry, ...] = ()
        self._last_filter: str = ""
        self._init_ui()
        self._wire_signals()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(6)

        self.edit_filter = QLineEdit()
        self.edit_filter.setPlaceholderText("Filter audio files...")
        self.edit_filter.setStyleSheet(INPUT_STYLE)
        hdr_row.addWidget(self.edit_filter, 1)

        self.lbl_count = QLabel("0 files")
        self.lbl_count.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        hdr_row.addWidget(self.lbl_count)

        layout.addLayout(hdr_row)

        self.table = DraggableFilesTable(self)
        layout.addWidget(self.table, 1)

    def _wire_signals(self) -> None:
        sel_model = self.table.selectionModel()
        if sel_model is not None:
            sel_model.selectionChanged.connect(self._on_table_selection)
        self.table.clicked.connect(self._on_table_clicked)
        self.table.doubleClicked.connect(self._on_table_clicked)
        self.edit_filter.textChanged.connect(self.filter_changed.emit)

    def _on_table_clicked(self, index: QModelIndex) -> None:
        entry = self.table.files_model.entry_at(index.row())
        if entry is not None:
            self.files_selected.emit((entry.abs_path,))

    def _on_table_selection(self) -> None:
        if self._is_updating_ui:
            return
        sel_model = self.table.selectionModel()
        if sel_model is None:
            return
        selected_rows = sorted(set(idx.row() for idx in sel_model.selectedRows()))
        paths: list[Path] = []
        for r in selected_rows:
            entry = self.table.files_model.entry_at(r)
            if entry is not None:
                paths.append(entry.abs_path)
        self.files_selected.emit(tuple(paths))

    def render_files(
        self,
        files: Sequence[LibraryFileEntry],
        filter_text: str,
        selected_paths: Sequence[Path],
    ) -> None:
        """Filters and populates files table with zero redundant allocations."""
        clean_filter = filter_text.strip().lower()

        # Update search box text with signal blocking
        self.edit_filter.blockSignals(True)
        if self.edit_filter.text() != filter_text:
            self.edit_filter.setText(filter_text)
        self.edit_filter.blockSignals(False)

        # Update model entries if collection or filter changed
        files_tuple = tuple(files)
        if files_tuple != self._last_files or clean_filter != self._last_filter:
            self._last_files = files_tuple
            self._last_filter = clean_filter
            self.table.files_model.set_entries(files_tuple, clean_filter)
            self.lbl_count.setText(f"{self.table.files_model.rowCount()} file(s)")

        # Synchronize selection if changed from outside
        sel_model = self.table.selectionModel()
        if sel_model is None:
            return

        selected_tuple = tuple(selected_paths)
        current_selected = tuple(
            entry.abs_path
            for r in sorted(set(idx.row() for idx in sel_model.selectedRows()))
            if (entry := self.table.files_model.entry_at(r)) is not None
        )

        if current_selected != selected_tuple:
            self._is_updating_ui = True
            try:
                sel_model.clearSelection()
                if selected_tuple:
                    sel_set = set(selected_tuple)
                    selection = QItemSelection()
                    for r, entry in enumerate(self.table.files_model.filtered_entries):
                        if entry.abs_path in sel_set:
                            idx_l = self.table.files_model.index(r, 0)
                            idx_r = self.table.files_model.index(r, 2)
                            selection.select(idx_l, idx_r)
                    sel_model.select(selection, QItemSelectionModel.SelectionFlag.Select)
            finally:
                self._is_updating_ui = False
