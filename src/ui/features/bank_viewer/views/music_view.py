"""Dedicated property inspector view for music tracks and segments."""

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


class MusicInspectorView(QWidget):
    """Dedicated inspector view for CAkMusicTrack and CAkMusicSegment nodes."""

    jump_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Timing Card
        self.summary_card = QFrame()
        self.summary_card.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_PANEL}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; padding: 6px; }}"
        )
        sc_layout = QVBoxLayout(self.summary_card)
        sc_layout.setContentsMargins(6, 6, 6, 6)
        sc_layout.setSpacing(4)

        sc_title = QLabel("Music Middleware Metadata")
        sc_title.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-weight: bold;"
        )
        sc_layout.addWidget(sc_title)

        info_row = QHBoxLayout()
        self.lbl_source = QLabel("Source WEM: -")
        self.lbl_source.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: 11px;")
        info_row.addWidget(self.lbl_source)

        self.lbl_duration = QLabel("Duration: -")
        self.lbl_duration.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        info_row.addWidget(self.lbl_duration)
        info_row.addStretch()
        sc_layout.addLayout(info_row)
        layout.addWidget(self.summary_card)

        # Linked Tracks / Children Table
        lbl_tracks = QLabel("Tracks / Child Segments (Double-click to navigate)")
        lbl_tracks.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-weight: bold;"
        )
        layout.addWidget(lbl_tracks)

        self.tracks_table = QTableWidget(0, 3)
        self.tracks_table.setHorizontalHeaderLabels(["ID", "Name / Alias", "Type"])
        hdr = self.tracks_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)
        self.tracks_table.setColumnWidth(0, 85)
        self.tracks_table.setColumnWidth(1, 150)
        self.tracks_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tracks_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tracks_table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.tracks_table.setStyleSheet(
            f"QTableWidget {{ background-color: {COLOR_BG_INPUT}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; color: {COLOR_TEXT_PRIMARY}; font-size: 11px; }} "
            f"QTableWidget::item {{ padding: 3px 6px; }} "
            f"QHeaderView::section {{ background-color: {COLOR_BG_PANEL}; color: {COLOR_TEXT_SECONDARY}; "
            f"font-weight: bold; border: 1px solid {COLOR_BORDER}; padding: 3px; }}"
        )
        layout.addWidget(self.tracks_table, 1)

    def _on_cell_double_clicked(self, row: int, _col: int) -> None:
        item = self.tracks_table.item(row, 0)
        if item is not None:
            target_key = item.data(_ROLE_TARGET_KEY)
            if target_key:
                self.jump_requested.emit(target_key)

    def render(self, details: NodeInspectorDetails | None) -> None:
        """Projects music details with strict signal blocking."""
        self.tracks_table.blockSignals(True)
        if details is None:
            self.lbl_source.setText("Source WEM: -")
            self.lbl_duration.setText("Duration: -")
            self.tracks_table.setRowCount(0)
            self.tracks_table.blockSignals(False)
            return

        wem_str = "-"
        dur_str = "-"
        for p in details.properties:
            if "Source WEM" in p.label:
                wem_str = p.value
            elif "Duration" in p.label:
                dur_str = f"{p.value} ms"

        self.lbl_source.setText(f"Source WEM: {wem_str}")
        self.lbl_duration.setText(f"Duration: {dur_str}")

        tracks = details.child_references
        self.tracks_table.setRowCount(len(tracks))
        for row, track in enumerate(tracks):
            jump_key = f"{track.bank_name}::{track.key}" if track.bank_name else track.key
            id_item = QTableWidgetItem(track.id_str)
            id_item.setData(_ROLE_TARGET_KEY, jump_key)
            name_item = QTableWidgetItem(track.label)
            name_item.setData(_ROLE_TARGET_KEY, jump_key)
            type_item = QTableWidgetItem(track.type_str)
            type_item.setData(_ROLE_TARGET_KEY, jump_key)
            self.tracks_table.setItem(row, 0, id_item)
            self.tracks_table.setItem(row, 1, name_item)
            self.tracks_table.setItem(row, 2, type_item)
        self.tracks_table.blockSignals(False)
