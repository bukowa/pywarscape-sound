"""Dedicated property inspector view for container nodes (RanSeqCntr & SwitchCntr)."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
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

from src.ui.features.bank_viewer.state import NodeInspectorDetails
from src.ui.theme import (
    BTN_STYLE_SECONDARY,
    COLOR_BG_INPUT,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
)

_ROLE_TARGET_KEY = Qt.ItemDataRole.UserRole + 1


class ContainerInspectorView(QWidget):
    """Dedicated inspector view for container nodes displaying playlist/routing and children."""

    jump_requested = Signal(str)
    append_variation_requested = Signal(int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_container_id: int | None = None
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

        self.sc_title = QLabel("Container Routing")
        self.sc_title.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-weight: bold;"
        )
        sc_layout.addWidget(self.sc_title)

        primary_row = QHBoxLayout()
        self.lbl_primary = QLabel("Group: -")
        self.lbl_primary.setStyleSheet(
            f"color: {COLOR_TEXT_PRIMARY}; font-size: 11px; font-weight: bold;"
        )
        primary_row.addWidget(self.lbl_primary)

        self.lbl_secondary = QLabel("Default: -")
        self.lbl_secondary.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        primary_row.addWidget(self.lbl_secondary)
        primary_row.addStretch()
        sc_layout.addLayout(primary_row)

        info_row = QHBoxLayout()
        self.lbl_items = QLabel("Routes: -")
        self.lbl_items.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: 11px;")
        info_row.addWidget(self.lbl_items)

        self.lbl_children_count = QLabel("Children: -")
        self.lbl_children_count.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        info_row.addWidget(self.lbl_children_count)
        info_row.addStretch()
        sc_layout.addLayout(info_row)

        self.btn_add_variation = QPushButton("Add Variation WAV...")
        self.btn_add_variation.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_add_variation.clicked.connect(self._on_add_variation_clicked)
        self.btn_add_variation.setVisible(False)
        sc_layout.addWidget(self.btn_add_variation)

        layout.addWidget(self.summary_card)

        # Primary Routing / Playlist Table
        self.lbl_routing_header = QLabel("Routing Matrix (Double-click to navigate)")
        self.lbl_routing_header.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-weight: bold;"
        )
        layout.addWidget(self.lbl_routing_header)

        self.routing_table = QTableWidget(0, 4)
        self.routing_table.setHorizontalHeaderLabels(
            ["State / Value", "Target Object", "Type", "Default"]
        )
        r_hdr = self.routing_table.horizontalHeader()
        r_hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        r_hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        r_hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        r_hdr.setStretchLastSection(True)
        self.routing_table.setColumnWidth(0, 95)
        self.routing_table.setColumnWidth(1, 140)
        self.routing_table.setColumnWidth(2, 80)
        self.routing_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.routing_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.routing_table.cellDoubleClicked.connect(self._on_routing_cell_double_clicked)
        self.routing_table.setStyleSheet(
            f"QTableWidget {{ background-color: {COLOR_BG_INPUT}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; color: {COLOR_TEXT_PRIMARY}; font-size: 11px; }} "
            f"QTableWidget::item {{ padding: 3px 6px; }} "
            f"QHeaderView::section {{ background-color: {COLOR_BG_PANEL}; color: {COLOR_TEXT_SECONDARY}; "
            f"font-weight: bold; border: 1px solid {COLOR_BORDER}; padding: 3px; }}"
        )
        layout.addWidget(self.routing_table, 1)

        # Children Items Table
        self.lbl_children_header = QLabel("Direct Children (Double-click to navigate)")
        self.lbl_children_header.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-weight: bold;"
        )
        layout.addWidget(self.lbl_children_header)

        self.child_table = QTableWidget(0, 3)
        self.child_table.setHorizontalHeaderLabels(["ID", "Name / Alias", "Type"])
        c_hdr = self.child_table.horizontalHeader()
        c_hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        c_hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        c_hdr.setStretchLastSection(True)
        self.child_table.setColumnWidth(0, 85)
        self.child_table.setColumnWidth(1, 150)
        self.child_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.child_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.child_table.cellDoubleClicked.connect(self._on_child_cell_double_clicked)
        self.child_table.setStyleSheet(
            f"QTableWidget {{ background-color: {COLOR_BG_INPUT}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; color: {COLOR_TEXT_PRIMARY}; font-size: 11px; }} "
            f"QTableWidget::item {{ padding: 3px 6px; }} "
            f"QHeaderView::section {{ background-color: {COLOR_BG_PANEL}; color: {COLOR_TEXT_SECONDARY}; "
            f"font-weight: bold; border: 1px solid {COLOR_BORDER}; padding: 3px; }}"
        )
        layout.addWidget(self.child_table, 1)

    def _on_routing_cell_double_clicked(self, row: int, _col: int) -> None:
        item = self.routing_table.item(row, 0)
        if item is not None:
            target_key = item.data(_ROLE_TARGET_KEY)
            if target_key:
                self.jump_requested.emit(target_key)

    def _on_child_cell_double_clicked(self, row: int, _col: int) -> None:
        item = self.child_table.item(row, 0)
        if item is not None:
            target_key = item.data(_ROLE_TARGET_KEY)
            if target_key:
                self.jump_requested.emit(target_key)

    def _on_add_variation_clicked(self) -> None:
        if self._current_container_id is None:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Audio File for Variation",
            "",
            "Audio Files (*.wav *.mp3 *.ogg *.flac);;All Files (*.*)",
        )
        if file_path:
            self.append_variation_requested.emit(self._current_container_id, file_path)

    def render(self, details: NodeInspectorDetails | None) -> None:
        """Projects container details with strict signal blocking."""
        self.routing_table.blockSignals(True)
        self.child_table.blockSignals(True)

        if details is None:
            self._current_container_id = None
            self.btn_add_variation.setVisible(False)
            self.sc_title.setText("Container Routing")
            self.lbl_primary.setText("Group: -")
            self.lbl_secondary.setText("Default: -")
            self.lbl_items.setText("Routes / Items: -")
            self.lbl_children_count.setText("Children: -")
            self.routing_table.setRowCount(0)
            self.child_table.setRowCount(0)
            self.lbl_routing_header.setVisible(False)
            self.routing_table.setVisible(False)
            self.routing_table.blockSignals(False)
            self.child_table.blockSignals(False)
            return

        self._current_container_id = details.object_id
        is_ran_seq = details.ran_seq_semantics is not None and details.object_type == "RanSeqCntr"
        self.btn_add_variation.setVisible(is_ran_seq)

        c_count = str(len(details.child_references))
        self.lbl_children_count.setText(f"Children: {c_count}")

        # 1. Switch Container Semantics
        if details.switch_semantics is not None:
            sem = details.switch_semantics
            self.sc_title.setText("Switch Container Routing")
            self.lbl_primary.setText(f"Switch Group: {sem.group_name}")
            self.lbl_secondary.setText(f"Default: {sem.default_switch_name}")
            self.lbl_items.setText(f"Routes: {len(sem.routes)}")

            self.lbl_routing_header.setText(f"Switch Routing Matrix ({len(sem.routes)} routes)")
            self.lbl_routing_header.setVisible(True)
            self.routing_table.setVisible(True)
            self.routing_table.setColumnCount(4)
            self.routing_table.setHorizontalHeaderLabels(
                ["State / Value", "Target Object", "Type", "Default"]
            )
            self.routing_table.setRowCount(len(sem.routes))

            for row, route in enumerate(sem.routes):
                sw_item = QTableWidgetItem(route.switch_name)
                sw_item.setData(_ROLE_TARGET_KEY, route.target_key)
                tgt_item = QTableWidgetItem(route.target_name)
                tgt_item.setData(_ROLE_TARGET_KEY, route.target_key)
                type_item = QTableWidgetItem(route.target_type)
                type_item.setData(_ROLE_TARGET_KEY, route.target_key)
                def_str = "Yes" if route.is_default else ""
                def_item = QTableWidgetItem(def_str)
                def_item.setData(_ROLE_TARGET_KEY, route.target_key)

                self.routing_table.setItem(row, 0, sw_item)
                self.routing_table.setItem(row, 1, tgt_item)
                self.routing_table.setItem(row, 2, type_item)
                self.routing_table.setItem(row, 3, def_item)

        # 2. Random / Sequence Container Semantics
        elif details.ran_seq_semantics is not None:
            r_sem = details.ran_seq_semantics
            self.sc_title.setText("Random / Sequence Configuration")
            self.lbl_primary.setText(f"Mode: {r_sem.mode_str}")
            self.lbl_secondary.setText(f"Loops: {r_sem.loop_count}")
            self.lbl_items.setText(f"Playlist Items: {len(r_sem.playlist)}")

            self.lbl_routing_header.setText(f"Playlist ({len(r_sem.playlist)} items)")
            self.lbl_routing_header.setVisible(True)
            self.routing_table.setVisible(True)
            self.routing_table.setColumnCount(5)
            self.routing_table.setHorizontalHeaderLabels(
                ["#", "Target Object", "Type", "Weight", "Prob %"]
            )
            self.routing_table.setRowCount(len(r_sem.playlist))

            for row, item in enumerate(r_sem.playlist):
                idx_item = QTableWidgetItem(str(item.index))
                idx_item.setData(_ROLE_TARGET_KEY, item.target_key)
                tgt_item = QTableWidgetItem(item.target_name)
                tgt_item.setData(_ROLE_TARGET_KEY, item.target_key)
                type_item = QTableWidgetItem(item.target_type)
                type_item.setData(_ROLE_TARGET_KEY, item.target_key)
                wt_item = QTableWidgetItem(str(item.weight))
                wt_item.setData(_ROLE_TARGET_KEY, item.target_key)
                pct_item = QTableWidgetItem(f"{item.weight_percent:.1f}%")
                pct_item.setData(_ROLE_TARGET_KEY, item.target_key)

                self.routing_table.setItem(row, 0, idx_item)
                self.routing_table.setItem(row, 1, tgt_item)
                self.routing_table.setItem(row, 2, type_item)
                self.routing_table.setItem(row, 3, wt_item)
                self.routing_table.setItem(row, 4, pct_item)

        else:
            # Fallback for unspecialized container nodes
            p_count = "-"
            for p in details.properties:
                if "Items" in p.label or "Routes" in p.label:
                    p_count = p.value
            self.sc_title.setText("Container Routing")
            self.lbl_primary.setText("Group: -")
            self.lbl_secondary.setText("Default: -")
            self.lbl_items.setText(f"Playlist / Routes: {p_count}")
            self.lbl_routing_header.setVisible(False)
            self.routing_table.setVisible(False)
            self.routing_table.setRowCount(0)

        # 3. Direct Children Table (Common to all containers)
        children = details.child_references
        self.child_table.setRowCount(len(children))
        for row, child in enumerate(children):
            jump_key = f"{child.bank_name}::{child.key}" if child.bank_name else child.key
            id_item = QTableWidgetItem(child.id_str)
            id_item.setData(_ROLE_TARGET_KEY, jump_key)
            name_item = QTableWidgetItem(child.label)
            name_item.setData(_ROLE_TARGET_KEY, jump_key)
            type_item = QTableWidgetItem(child.type_str)
            type_item.setData(_ROLE_TARGET_KEY, jump_key)
            self.child_table.setItem(row, 0, id_item)
            self.child_table.setItem(row, 1, name_item)
            self.child_table.setItem(row, 2, type_item)

        self.routing_table.blockSignals(False)
        self.child_table.blockSignals(False)
