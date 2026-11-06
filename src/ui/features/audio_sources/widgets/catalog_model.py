"""Virtualized high-performance Qt TableModel and TableView for AudioCatalogEntry.

Provides O(1) viewport-only rendering with customizable columns, sorting, and heuristic provenance styling.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    Qt,
    Signal,
)
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QHeaderView, QTableView, QWidget

from src.engine.metadata_fields import Provenance
from src.models import AudioCatalogEntry
from src.ui.columns import format_duration_ms
from src.ui.features.audio_sources.columns import (
    CATALOG_COLUMN_SPECS,
    CATALOG_COLUMN_SPECS_BY_ID,
    DEFAULT_VISIBLE_CATALOG_COLUMNS,
    CatalogColumn,
    toggle_visible_catalog_columns,
)
from src.ui.menu import CheckableMenu
from src.ui.theme import (
    COLOR_ACCENT,
    COLOR_BG_INPUT,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_BRIGHT,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
)

TABLE_STYLE = f"""
QTableView {{
    background-color: {COLOR_BG_INPUT};
    color: {COLOR_TEXT_PRIMARY};
    gridline-color: {COLOR_BORDER};
    border: 1px solid {COLOR_BORDER};
    border-radius: 4px;
    selection-background-color: {COLOR_ACCENT};
    selection-color: {COLOR_TEXT_BRIGHT};
}}
QTableView::item:selected {{
    background-color: {COLOR_ACCENT};
    color: {COLOR_TEXT_BRIGHT};
}}
QHeaderView::section {{
    background-color: {COLOR_BG_PANEL};
    color: {COLOR_TEXT_SECONDARY};
    padding: 4px 8px;
    border: 1px solid {COLOR_BORDER};
    font-weight: bold;
    font-size: 11px;
}}
"""


class _ColumnsDescriptor:
    """Descriptor supporting both class-level default and instance-level visible headers."""

    def __get__(
        self,
        instance: AudioCatalogTableModel | None,
        owner: type[AudioCatalogTableModel] | None = None,
    ) -> tuple[str, ...]:
        if instance is None:
            return tuple(
                CATALOG_COLUMN_SPECS_BY_ID[c].header for c in DEFAULT_VISIBLE_CATALOG_COLUMNS
            )
        return tuple(CATALOG_COLUMN_SPECS_BY_ID[c].header for c in instance._visible_columns)


class AudioCatalogTableModel(QAbstractTableModel):
    """Virtualized, memory-efficient table model for audio catalog entries."""

    COLUMNS = _ColumnsDescriptor()

    def __init__(
        self,
        entries: Sequence[AudioCatalogEntry] = (),
        visible_columns: Sequence[CatalogColumn] | None = None,
        duration_resolver: Callable[[int], float | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._entries: tuple[AudioCatalogEntry, ...] = tuple(entries)
        if visible_columns is None:
            self._visible_columns: tuple[CatalogColumn, ...] = DEFAULT_VISIBLE_CATALOG_COLUMNS
        else:
            col_set = set(visible_columns) | {s.id for s in CATALOG_COLUMN_SPECS if not s.hideable}
            self._visible_columns = tuple(s.id for s in CATALOG_COLUMN_SPECS if s.id in col_set)
        self._duration_resolver = duration_resolver
        self._duration_cache: dict[int, float | None] = {}
        self._sort_column: int | None = None
        self._sort_order: Qt.SortOrder = Qt.SortOrder.AscendingOrder

    @property
    def visible_columns(self) -> tuple[CatalogColumn, ...]:
        return self._visible_columns

    def set_duration_resolver(
        self, duration_resolver: Callable[[int], float | None] | None
    ) -> None:
        """Sets an optional resolver for lazy loose WEM duration lookups."""
        self._duration_resolver = duration_resolver
        self._duration_cache.clear()
        if CatalogColumn.DURATION in self._visible_columns and len(self._entries) > 0:
            top_left = self.index(0, 0)
            bottom_right = self.index(len(self._entries) - 1, len(self._visible_columns) - 1)
            self.dataChanged.emit(top_left, bottom_right)

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._entries)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return len(self._visible_columns)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self._visible_columns):
                col_id = self._visible_columns[section]
                spec = CATALOG_COLUMN_SPECS_BY_ID.get(col_id)
                if spec is not None:
                    return spec.header
        return None

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._entries)):
            return None

        entry = self._entries[index.row()]
        col_idx = index.column()
        if not (0 <= col_idx < len(self._visible_columns)):
            return None

        col_id = self._visible_columns[col_idx]
        spec = CATALOG_COLUMN_SPECS_BY_ID.get(col_id)
        if spec is None:
            return None

        if role == Qt.ItemDataRole.DisplayRole:
            if col_id == CatalogColumn.DURATION:
                dur = entry.duration_ms
                if dur <= 0 and self._duration_resolver is not None:
                    if entry.wem_id in self._duration_cache:
                        cached = self._duration_cache[entry.wem_id]
                        if cached is not None and cached > 0:
                            dur = cached
                    else:
                        resolved = self._duration_resolver(entry.wem_id)
                        self._duration_cache[entry.wem_id] = resolved
                        if resolved is not None and resolved > 0:
                            dur = resolved
                if dur > 0:
                    return format_duration_ms(dur)
                return ""
            return spec.cell(entry)

        elif role == Qt.ItemDataRole.ForegroundRole:
            if spec.cell_provenance(entry) == Provenance.HEURISTIC:
                return QBrush(QColor(COLOR_TEXT_MUTED))
            return None

        elif role == Qt.ItemDataRole.ToolTipRole:
            if spec.cell_provenance(entry) == Provenance.HEURISTIC:
                return "Inferred (heuristic)"
            return None

        elif role == Qt.ItemDataRole.UserRole:
            return entry

        return None

    def set_entries(self, entries: Sequence[AudioCatalogEntry]) -> None:
        """Atomically updates displayed entries with zero item allocations."""
        self.beginResetModel()
        self._entries = tuple(entries)
        self.endResetModel()

    def set_visible_columns(self, columns: Sequence[CatalogColumn]) -> None:
        """Updates visible columns and resets model."""
        self.beginResetModel()
        col_set = set(columns) | {s.id for s in CATALOG_COLUMN_SPECS if not s.hideable}
        self._visible_columns = tuple(s.id for s in CATALOG_COLUMN_SPECS if s.id in col_set)
        self.endResetModel()

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """Sorts entries by the specified column index."""
        if not (0 <= column < len(self._visible_columns)):
            return
        col_id = self._visible_columns[column]
        spec = CATALOG_COLUMN_SPECS_BY_ID.get(col_id)
        if spec is None or spec.sort_key is None:
            return

        self.layoutAboutToBeChanged.emit()
        self._sort_column = column
        self._sort_order = order
        sort_key = spec.sort_key
        reverse = order == Qt.SortOrder.DescendingOrder

        def _sort_entry(e: AudioCatalogEntry) -> Any:
            if col_id == CatalogColumn.DURATION and e.duration_ms <= 0:
                cached = self._duration_cache.get(e.wem_id)
                if cached is not None and cached > 0:
                    return cached
            return sort_key(e)

        self._entries = tuple(sorted(self._entries, key=_sort_entry, reverse=reverse))
        self.layoutChanged.emit()

    def entry_at(self, row: int) -> AudioCatalogEntry | None:
        """Returns typed AudioCatalogEntry for a given visible model row."""
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None


class AudioCatalogTableView(QTableView):
    """Specialized QTableView wired to AudioCatalogTableModel with standard styling."""

    columns_changed = Signal(tuple)

    def __init__(
        self,
        parent: QWidget | None = None,
        visible_columns: Sequence[CatalogColumn] | None = None,
        duration_resolver: Callable[[int], float | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._catalog_model = AudioCatalogTableModel(
            parent=self,
            visible_columns=visible_columns,
            duration_resolver=duration_resolver,
        )
        self.setModel(self._catalog_model)
        self.setStyleSheet(TABLE_STYLE)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.verticalHeader().setVisible(False)

        header = self.horizontalHeader()
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._on_header_context_menu)

        self._apply_column_widths()
        self.setSortingEnabled(True)

    def _apply_column_widths(self) -> None:
        header = self.horizontalHeader()
        cols = self._catalog_model.visible_columns
        for idx, col in enumerate(cols):
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.Interactive)
            spec = CATALOG_COLUMN_SPECS_BY_ID.get(col)
            if spec is not None:
                self.setColumnWidth(idx, spec.default_width)
        header.setStretchLastSection(True)

    def _on_header_context_menu(self, pos: QPoint) -> None:
        menu = self.create_columns_menu()
        header = self.horizontalHeader()
        menu.exec(header.mapToGlobal(pos))

    def create_columns_menu(self, parent: QWidget | None = None) -> CheckableMenu:
        """Creates a checkable columns context menu for selecting visible catalog columns."""
        menu = CheckableMenu("Columns", parent or self)
        visible = set(self._catalog_model.visible_columns)
        for spec in CATALOG_COLUMN_SPECS:
            action = menu.addAction(spec.header)
            action.setCheckable(True)
            action.setChecked(spec.id in visible)
            if not spec.hideable:
                action.setEnabled(False)
            else:
                action.toggled.connect(
                    lambda checked, col=spec.id: self.set_column_visible(col, checked)
                )
        return menu

    @property
    def catalog_model(self) -> AudioCatalogTableModel:
        return self._catalog_model

    @property
    def visible_columns(self) -> tuple[CatalogColumn, ...]:
        return self._catalog_model.visible_columns

    def set_column_visible(self, column: CatalogColumn, visible: bool) -> None:
        new_cols = toggle_visible_catalog_columns(
            self._catalog_model.visible_columns, column, visible
        )
        self.set_visible_columns(new_cols)

    def set_visible_columns(self, columns: Sequence[CatalogColumn]) -> None:
        self._catalog_model.set_visible_columns(columns)
        self._apply_column_widths()
        self.columns_changed.emit(self._catalog_model.visible_columns)

    def set_duration_resolver(
        self, duration_resolver: Callable[[int], float | None] | None
    ) -> None:
        self._catalog_model.set_duration_resolver(duration_resolver)

    def rowCount(self) -> int:
        """Convenience helper returning the count of rows currently in the model."""
        return self._catalog_model.rowCount()

    def selected_entry(self) -> AudioCatalogEntry | None:
        """Returns the currently selected AudioCatalogEntry, or None."""
        sel = self.selectionModel()
        if sel is None:
            return None
        rows = sel.selectedRows()
        if not rows:
            return None
        return self._catalog_model.entry_at(rows[0].row())
