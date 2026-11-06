"""Pure PySide6 projection widget for browsing Game Audio assets.

Embeds virtualized AudioCatalogTableView with live search filtering, column toggling, and sorting.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.models import AudioCatalogEntry
from src.ui.features.audio_sources.columns import (
    CATALOG_COLUMN_SPECS,
    CatalogColumn,
)
from src.ui.features.audio_sources.widgets.catalog_model import AudioCatalogTableView
from src.ui.menu import CheckableMenu
from src.ui.theme import BTN_STYLE_SECONDARY, COLOR_TEXT_MUTED, INPUT_STYLE


class GameAudioTab(QWidget):
    """Tab presenting game audio catalog assets with instant search filtering and column customization."""

    entry_selected = Signal(object)  # Optional[AudioCatalogEntry]

    def __init__(
        self,
        parent: QWidget | None = None,
        duration_resolver: Callable[[int], float | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._all_entries: tuple[AudioCatalogEntry, ...] = ()
        self._column_actions: dict[CatalogColumn, QAction] = {}
        self._init_ui(duration_resolver=duration_resolver)
        self._wire_signals()

    def _init_ui(self, duration_resolver: Callable[[int], float | None] | None = None) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(6)

        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("Search game audio catalog...")
        self.edit_search.setStyleSheet(INPUT_STYLE)
        hdr_row.addWidget(self.edit_search, 1)

        self.lbl_count = QLabel("0 entries")
        self.lbl_count.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        hdr_row.addWidget(self.lbl_count)

        self.table = AudioCatalogTableView(self, duration_resolver=duration_resolver)

        # Columns dropdown button
        self.btn_columns = QPushButton("Columns ▾")
        self.btn_columns.setStyleSheet(BTN_STYLE_SECONDARY)
        self._columns_menu = CheckableMenu(self)
        for spec in CATALOG_COLUMN_SPECS:
            act = QAction(spec.header, self._columns_menu)
            act.setCheckable(True)
            act.setChecked(spec.id in self.table.visible_columns)
            if not spec.hideable:
                act.setEnabled(False)
            else:
                act.toggled.connect(
                    lambda checked, col=spec.id: self.set_column_visible(col, checked)
                )
            self._columns_menu.addAction(act)
            self._column_actions[spec.id] = act
        self.btn_columns.setMenu(self._columns_menu)
        hdr_row.addWidget(self.btn_columns)

        layout.addLayout(hdr_row)
        layout.addWidget(self.table, 1)

    def _wire_signals(self) -> None:
        self.edit_search.textChanged.connect(self._on_search_changed)
        self.table.doubleClicked.connect(self._on_table_double_clicked)
        self.table.columns_changed.connect(self._sync_column_actions)
        sel_model = self.table.selectionModel()
        if sel_model is not None:
            sel_model.selectionChanged.connect(self._on_table_selection)

    def _sync_column_actions(self, visible_cols: tuple[CatalogColumn, ...]) -> None:
        vis_set = set(visible_cols)
        for col, act in self._column_actions.items():
            if act.isChecked() != (col in vis_set):
                act.blockSignals(True)
                act.setChecked(col in vis_set)
                act.blockSignals(False)

    def _on_table_double_clicked(self) -> None:
        entry = self.table.selected_entry()
        if entry is not None:
            self.entry_selected.emit(entry)

    def _on_search_changed(self, text: str) -> None:
        clean = text.strip().lower()
        if not clean:
            filtered = self._all_entries
        else:
            filtered = tuple(
                e
                for e in self._all_entries
                if clean in e.display_name.lower()
                or clean in e.source_bank.lower()
                or clean in str(e.wem_id)
                or clean in e.category.lower()
            )
        self.lbl_count.setText(f"{len(filtered)} entries")
        self.table.catalog_model.set_entries(filtered)

    def _on_table_selection(self) -> None:
        entry = self.table.selected_entry()
        self.entry_selected.emit(entry)

    @property
    def visible_columns(self) -> tuple[CatalogColumn, ...]:
        """Returns currently visible table columns."""
        return self.table.visible_columns

    def set_column_visible(self, column: CatalogColumn, visible: bool) -> None:
        """Shows or hides a specific catalog column."""
        self.table.set_column_visible(column, visible)

    def set_visible_columns(self, columns: Sequence[CatalogColumn]) -> None:
        """Sets the sequence of visible columns."""
        self.table.set_visible_columns(columns)

    def set_duration_resolver(
        self, duration_resolver: Callable[[int], float | None] | None
    ) -> None:
        """Sets an optional resolver for lazy WEM duration lookups."""
        self.table.set_duration_resolver(duration_resolver)

    def set_entries(self, entries: Sequence[AudioCatalogEntry]) -> None:
        """Sets game audio catalog entries and applies active search filter."""
        self._all_entries = tuple(entries)
        self._on_search_changed(self.edit_search.text())
