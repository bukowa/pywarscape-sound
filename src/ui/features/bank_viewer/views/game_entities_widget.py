"""Collapsible game entities inspector section and table model for unit/projectile metadata."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from src.ui.features.bank_viewer.state import GameEntitiesSection, GameEntityEntry
from src.ui.theme import (
    COLOR_BG_INPUT,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    INPUT_STYLE,
)


class GameEntitiesTableModel(QAbstractTableModel):
    """Virtual table model projecting unit/projectile game entities with fast filtering."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: tuple[GameEntityEntry, ...] = ()
        self._filtered: list[GameEntityEntry] = []
        self._entity_type: str = "entities"
        self._filter_query: str = ""

    def set_data(self, entries: tuple[GameEntityEntry, ...], entity_type: str) -> None:
        self.beginResetModel()
        self._entries = entries
        self._entity_type = entity_type
        self._apply_filter_locked()
        self.endResetModel()

    def set_filter(self, query: str) -> None:
        q = query.strip().lower()
        if q == self._filter_query:
            return
        self.beginResetModel()
        self._filter_query = q
        self._apply_filter_locked()
        self.endResetModel()

    def _apply_filter_locked(self) -> None:
        if not self._filter_query:
            self._filtered = list(self._entries)
            return
        q = self._filter_query
        self._filtered = [
            e
            for e in self._entries
            if q in e.key.lower()
            or q in e.category.lower()
            or q in e.unit_class.lower()
            or q in e.extra.lower()
        ]

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._filtered)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        if self._entity_type == "units":
            return 3
        if self._entity_type in ("projectiles", "explosions"):
            return 2
        return 2

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> str | None:
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        if self._entity_type == "units":
            headers = ["Unit Key", "Category", "Class"]
            return headers[section] if section < len(headers) else None
        if self._entity_type in ("projectiles", "explosions"):
            headers = ["Entity Key", "Details"]
            return headers[section] if section < len(headers) else None
        headers = ["Key", "Extra"]
        return headers[section] if section < len(headers) else None

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> str | None:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        row = index.row()
        if row < 0 or row >= len(self._filtered):
            return None
        entry = self._filtered[row]
        col = index.column()

        if self._entity_type == "units":
            if col == 0:
                return entry.key
            if col == 1:
                return entry.category
            if col == 2:
                return entry.unit_class
        elif self._entity_type in ("projectiles", "explosions"):
            if col == 0:
                return entry.key
            if col == 1:
                return entry.extra
        else:
            if col == 0:
                return entry.key
            if col == 1:
                return entry.extra or entry.category
        return None


class GameEntitiesWidget(QWidget):
    """Collapsible panel hosting a searchable table of associated game database entities."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._is_collapsed: bool = False
        self._current_section: GameEntitiesSection | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Header button / toggle bar
        self.btn_toggle = QPushButton("▼ Game Entities (0)")
        self.btn_toggle.setCheckable(False)
        self.btn_toggle.setStyleSheet(
            f"QPushButton {{ background-color: {COLOR_BG_PANEL}; color: {COLOR_TEXT_SECONDARY}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 4px; padding: 5px 8px; "
            f"text-align: left; font-size: 11px; font-weight: bold; }} "
            f"QPushButton:hover {{ background-color: {COLOR_BG_INPUT}; color: {COLOR_TEXT_PRIMARY}; }}"
        )
        self.btn_toggle.clicked.connect(self._toggle_collapsed)
        layout.addWidget(self.btn_toggle)

        # Collapsible Content Frame
        self.content_frame = QFrame()
        self.content_frame.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_PANEL}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; }}"
        )
        content_layout = QVBoxLayout(self.content_frame)
        content_layout.setContentsMargins(6, 6, 6, 6)
        content_layout.setSpacing(6)

        # Filter bar
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(4)

        self.edit_filter = QLineEdit()
        self.edit_filter.setPlaceholderText("Filter entities (e.g. cav, spear)...")
        self.edit_filter.setStyleSheet(INPUT_STYLE)
        self.edit_filter.textChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.edit_filter, 1)

        self.lbl_count = QLabel("0 items")
        self.lbl_count.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 10px;")
        filter_row.addWidget(self.lbl_count)
        content_layout.addLayout(filter_row)

        # Table View
        self.model = GameEntitiesTableModel(self)
        self.table_view = QTableView()
        self.table_view.setModel(self.model)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table_view.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.verticalHeader().setDefaultSectionSize(22)
        self.table_view.setMinimumHeight(120)
        self.table_view.setMaximumHeight(260)

        thdr = self.table_view.horizontalHeader()
        thdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        thdr.setStretchLastSection(True)

        self.table_view.setStyleSheet(
            f"QTableView {{ background-color: {COLOR_BG_INPUT}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 3px; color: {COLOR_TEXT_PRIMARY}; font-size: 11px; }} "
            f"QTableView::item {{ padding: 2px 4px; }} "
            f"QHeaderView::section {{ background-color: {COLOR_BG_PANEL}; color: {COLOR_TEXT_SECONDARY}; "
            f"font-weight: bold; border: 1px solid {COLOR_BORDER}; padding: 3px; }}"
        )
        content_layout.addWidget(self.table_view)

        layout.addWidget(self.content_frame)
        self.setVisible(False)

    def _toggle_collapsed(self) -> None:
        self._is_collapsed = not self._is_collapsed
        self.content_frame.setVisible(not self._is_collapsed)
        self._update_toggle_label()

    def _update_toggle_label(self) -> None:
        arrow = "▶" if self._is_collapsed else "▼"
        if self._current_section is not None:
            lbl = f"{arrow} Game Entities ({self._current_section.total_count} {self._current_section.entity_type})"
        else:
            lbl = f"{arrow} Game Entities"
        self.btn_toggle.setText(lbl)

    def _on_filter_changed(self, text: str) -> None:
        self.model.set_filter(text)
        filtered_cnt = self.model.rowCount()
        total_cnt = len(self.model._entries)
        if text.strip():
            self.lbl_count.setText(f"{filtered_cnt} of {total_cnt}")
        else:
            self.lbl_count.setText(f"{total_cnt} items")

    def render(self, section: GameEntitiesSection | None) -> None:
        """Projects game entities section into the table."""
        self._current_section = section
        if section is None or not section.entries:
            self.setVisible(False)
            self.model.set_data((), "entities")
            return

        self.setVisible(True)
        self.edit_filter.blockSignals(True)
        self.edit_filter.clear()
        self.edit_filter.setPlaceholderText(
            f"Filter {section.entity_type} (key, category, class)..."
        )
        self.edit_filter.blockSignals(False)

        self.model.set_data(section.entries, section.entity_type)
        self.lbl_count.setText(f"{len(section.entries)} items")

        # Column widths
        if section.entity_type == "units":
            self.table_view.setColumnWidth(0, 160)
            self.table_view.setColumnWidth(1, 80)
            self.table_view.setColumnWidth(2, 90)
        elif section.entity_type in ("projectiles", "explosions"):
            self.table_view.setColumnWidth(0, 160)

        self._update_toggle_label()
