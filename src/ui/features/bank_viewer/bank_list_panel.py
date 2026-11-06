"""Pure PySide6 projection widget for the SoundBank list panel."""

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.features.bank_viewer.state import BankListItem, BankStatus
from src.ui.theme import (
    BTN_STYLE_SECONDARY,
    CHECKBOX_STYLE,
    COLOR_BG_INPUT,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    INPUT_STYLE,
)


class BankListPanel(QWidget):
    """Panel displaying soundbank list, search input, filter toggle, and open action."""

    bank_selected = Signal(str)
    search_changed = Signal(str)
    modified_toggled = Signal(bool)
    open_file_clicked = Signal()
    bank_revert_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rendered_banks: tuple[BankListItem, ...] = ()
        self._init_ui()
        self._wire_signals()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        hdr_row = QHBoxLayout()
        self.lbl_title = QLabel("SOUNDBANKS")
        self.lbl_title.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-weight: bold; font-size: 11px;"
        )
        hdr_row.addWidget(self.lbl_title)
        hdr_row.addStretch()
        self.lbl_count = QLabel("0 banks")
        self.lbl_count.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        hdr_row.addWidget(self.lbl_count)
        layout.addLayout(hdr_row)

        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("Filter soundbanks (.bnk)...")
        self.edit_search.setStyleSheet(INPUT_STYLE)
        layout.addWidget(self.edit_search)

        self.chk_modified_only = QCheckBox("Show Modified Only")
        self.chk_modified_only.setStyleSheet(CHECKBOX_STYLE)
        layout.addWidget(self.chk_modified_only)

        self.table_banks = QTableWidget(0, 3)
        self.table_banks.setHorizontalHeaderLabels(["SoundBank", "Status", "Size"])
        tbl_hdr = self.table_banks.horizontalHeader()
        tbl_hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        tbl_hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        tbl_hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        tbl_hdr.setStretchLastSection(True)
        self.table_banks.setColumnWidth(0, 160)
        self.table_banks.setColumnWidth(1, 80)
        self.table_banks.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_banks.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_banks.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_banks.setStyleSheet(
            f"QTableWidget {{ background-color: {COLOR_BG_INPUT}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; color: {COLOR_TEXT_PRIMARY}; font-size: 11px; }} "
            f"QHeaderView::section {{ background-color: {COLOR_BG_PANEL}; color: {COLOR_TEXT_SECONDARY}; "
            f"font-weight: bold; border: 1px solid {COLOR_BORDER}; padding: 3px; }}"
        )
        self.table_banks.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self.table_banks, 1)

        self.btn_open_file = QPushButton("Open .bnk File...")
        self.btn_open_file.setStyleSheet(BTN_STYLE_SECONDARY)
        layout.addWidget(self.btn_open_file)

    def _wire_signals(self) -> None:
        self.edit_search.textChanged.connect(self.search_changed.emit)
        self.chk_modified_only.toggled.connect(self.modified_toggled.emit)
        self.btn_open_file.clicked.connect(self.open_file_clicked.emit)
        self.table_banks.itemSelectionChanged.connect(self._on_table_selection)
        self.table_banks.customContextMenuRequested.connect(self._on_context_menu)

    def _on_context_menu(self, pos) -> None:
        row = self.table_banks.rowAt(pos.y())
        if row < 0 or row >= len(self._rendered_banks):
            return
        bank_item = self._rendered_banks[row]
        menu = QMenu(self)
        act_revert = menu.addAction(f"Revert '{bank_item.name}' to Baseline...")
        act_revert.setEnabled(bank_item.status == BankStatus.MODIFIED)
        chosen = menu.exec(self.table_banks.viewport().mapToGlobal(pos))
        if chosen == act_revert:
            self.bank_revert_requested.emit(bank_item.name)

    def _on_table_selection(self) -> None:
        row = self.table_banks.currentRow()
        if row >= 0:
            item = self.table_banks.item(row, 0)
            if item:
                self.bank_selected.emit(item.text())

    def render_banks(self, banks: Sequence[BankListItem], selected_name: str | None) -> None:
        """Projects bank list descriptors onto table with signal blocking and diffing."""
        self.lbl_count.setText(f"{len(banks)} banks")

        self.table_banks.blockSignals(True)
        banks_tuple = tuple(banks)
        if getattr(self, "_rendered_banks", None) != banks_tuple:
            self._rendered_banks = banks_tuple
            self.table_banks.setRowCount(len(banks))
            for row, b in enumerate(banks):
                n_item = QTableWidgetItem(b.name)
                s_item = QTableWidgetItem(b.status.value)
                sz_item = QTableWidgetItem(b.display_size)
                self.table_banks.setItem(row, 0, n_item)
                self.table_banks.setItem(row, 1, s_item)
                self.table_banks.setItem(row, 2, sz_item)

        if selected_name:
            clean_sel = selected_name.lower()
            current_row = self.table_banks.currentRow()
            current_item = self.table_banks.item(current_row, 0) if current_row >= 0 else None
            if current_item is None or current_item.text().lower() != clean_sel:
                for row, b in enumerate(banks):
                    if b.name.lower() == clean_sel:
                        self.table_banks.selectRow(row)
                        break
        elif self.table_banks.currentRow() >= 0:
            self.table_banks.clearSelection()

        self.table_banks.blockSignals(False)
