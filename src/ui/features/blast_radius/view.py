"""PySide6 modal dialog presenting blast radius impact and audio replacement choices."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
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

from src.ui.features.blast_radius.state import (
    BlastRadiusAction,
    BlastRadiusMode,
    BlastRadiusState,
)
from src.ui.features.blast_radius.store import BlastRadiusStore
from src.ui.theme import (
    BTN_STYLE_PRIMARY,
    BTN_STYLE_SECONDARY,
    COLOR_BG_BASE,
    COLOR_BG_INPUT,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
)


class BlastRadiusDialog(QDialog):
    """Lightweight modal confirmation dialog for shared WEM blast radius and embedded promotion."""

    def __init__(self, store: BlastRadiusStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Audio Replacement Confirmation")
        self.setMinimumWidth(620)
        self.setMinimumHeight(360)
        self._init_ui()
        self.store.subscribe(self.render)
        self.store.on_close_requested(self._on_close_requested)
        self.render(self.store.state)

    def _init_ui(self) -> None:
        self.setStyleSheet(
            f"QDialog {{ background-color: {COLOR_BG_BASE}; color: {COLOR_TEXT_PRIMARY}; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Header & Notice Banner
        self.banner_card = QFrame()
        self.banner_card.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_PANEL}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; padding: 8px; }}"
        )
        b_layout = QVBoxLayout(self.banner_card)
        b_layout.setContentsMargins(6, 6, 6, 6)
        b_layout.setSpacing(4)

        self.lbl_title = QLabel("Shared Audio Source Detected")
        self.lbl_title.setStyleSheet(f"color: {COLOR_WARNING}; font-size: 13px; font-weight: bold;")
        b_layout.addWidget(self.lbl_title)

        self.lbl_description = QLabel("")
        self.lbl_description.setWordWrap(True)
        self.lbl_description.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: 11px;")
        b_layout.addWidget(self.lbl_description)

        layout.addWidget(self.banner_card)

        # Impact Table Header
        self.lbl_table_header = QLabel("Affected Referencing Nodes:")
        self.lbl_table_header.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-weight: bold;"
        )
        layout.addWidget(self.lbl_table_header)

        # 5-Column Impact Table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Bank", "Node ID", "Node Name", "Type", "Audio Mode"])
        hdr = self.table.horizontalHeader()
        for col in range(5):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)
        self.table.setColumnWidth(0, 140)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 90)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setStyleSheet(
            f"QTableWidget {{ background-color: {COLOR_BG_INPUT}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; color: {COLOR_TEXT_PRIMARY}; font-size: 11px; }} "
            f"QTableWidget::item {{ padding: 4px 6px; }} "
            f"QHeaderView::section {{ background-color: {COLOR_BG_PANEL}; color: {COLOR_TEXT_SECONDARY}; "
            f"font-weight: bold; border: 1px solid {COLOR_BORDER}; padding: 4px; }}"
        )
        layout.addWidget(self.table, 1)

        # Action Buttons Row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_cancel.clicked.connect(lambda: self.store.choose_action(BlastRadiusAction.CANCEL))
        btn_row.addWidget(self.btn_cancel)

        btn_row.addStretch()

        self.btn_overwrite = QPushButton("Replace Everywhere / Overwrite")
        self.btn_overwrite.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_overwrite.clicked.connect(
            lambda: self.store.choose_action(BlastRadiusAction.OVERWRITE)
        )
        btn_row.addWidget(self.btn_overwrite)

        self.btn_isolate = QPushButton("Isolate / Fork (This Node Only)")
        self.btn_isolate.setStyleSheet(BTN_STYLE_PRIMARY)
        self.btn_isolate.clicked.connect(
            lambda: self.store.choose_action(BlastRadiusAction.ISOLATE)
        )
        btn_row.addWidget(self.btn_isolate)

        layout.addLayout(btn_row)

    def _on_close_requested(self, action: BlastRadiusAction) -> None:
        if action in (BlastRadiusAction.ISOLATE, BlastRadiusAction.OVERWRITE):
            self.accept()
        else:
            self.reject()

    def render(self, state: BlastRadiusState) -> None:
        """Projects BlastRadiusState into dialog controls with strict signal blocking."""
        self.table.blockSignals(True)
        try:
            if state.mode == BlastRadiusMode.PROMOTION_NOTICE:
                self.lbl_title.setText("Promote Embedded Audio to Streamed")
                self.lbl_description.setText(
                    f"WEM {state.wem_id} is currently embedded inside '{state.target_bank_name}' "
                    f"(DATA/DIDX chunks). Replacing this audio will promote Sound {state.target_node_id} "
                    f"to Streamed mode (stream_type = 2) and stage a loose .wem file in the workspace."
                )
                self.btn_isolate.setVisible(False)
                self.btn_overwrite.setText("Proceed (Promote to Streamed)")
                self.btn_overwrite.setStyleSheet(BTN_STYLE_PRIMARY)
            else:
                self.lbl_title.setText(
                    f"Shared Audio Source — {len(state.items)} Referencing Nodes"
                )
                self.lbl_description.setText(
                    f"WEM {state.wem_id} is referenced by {len(state.items)} nodes across loaded SoundBanks. "
                    f"Choose 'Isolate / Fork' to allocate a new unique WEM ID for Sound {state.target_node_id} only, "
                    f"or 'Replace Everywhere / Overwrite' to update the shared audio for all referencing nodes."
                )
                self.btn_isolate.setVisible(True)
                self.btn_overwrite.setText("Replace Everywhere / Overwrite")
                self.btn_overwrite.setStyleSheet(BTN_STYLE_SECONDARY)

            self.lbl_table_header.setText(f"Affected Referencing Nodes ({len(state.items)}):")
            self.table.setRowCount(len(state.items))
            for row, item in enumerate(state.items):
                mode_label = "Embedded (DATA/DIDX)" if item.is_embedded else "Streamed (Loose .wem)"
                self.table.setItem(row, 0, QTableWidgetItem(item.bank_name))
                self.table.setItem(row, 1, QTableWidgetItem(str(item.node_id)))
                self.table.setItem(row, 2, QTableWidgetItem(item.node_name))
                self.table.setItem(row, 3, QTableWidgetItem(item.node_type))
                self.table.setItem(row, 4, QTableWidgetItem(mode_label))
        finally:
            self.table.blockSignals(False)

    def exec(self) -> BlastRadiusAction:  # type: ignore[override]
        """Executes the modal dialog and returns the selected BlastRadiusAction."""
        super().exec()
        return self.store.state.chosen_action or BlastRadiusAction.CANCEL
