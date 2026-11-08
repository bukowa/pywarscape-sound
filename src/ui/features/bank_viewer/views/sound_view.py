"""Dedicated property inspector view for CAkSound nodes."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
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
    COLOR_SUCCESS,
    COLOR_TEXT_BRIGHT,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
)

_ROLE_TARGET_KEY = Qt.ItemDataRole.UserRole + 1


class SoundInspectorView(QWidget):
    """Dedicated inspector view for CAkSound nodes displaying audio media routing and parameters."""

    jump_requested = Signal(str)
    reference_media_requested = Signal(int, int)
    export_requested = Signal(int)
    node_params_changed = Signal(int, float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_sound_id: int | None = None
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Audio Source Card
        self.source_card = QFrame()
        self.source_card.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_PANEL}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; padding: 6px; }}"
        )
        sc_layout = QVBoxLayout(self.source_card)
        sc_layout.setContentsMargins(6, 6, 6, 6)
        sc_layout.setSpacing(6)

        title_row = QHBoxLayout()
        sc_title = QLabel("Audio Source")
        sc_title.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-weight: bold;"
        )
        title_row.addWidget(sc_title)
        title_row.addStretch()

        self.badge_stream_mode = QLabel("STREAMED")
        self.badge_stream_mode.setStyleSheet(
            f"background-color: {COLOR_SUCCESS}; color: {COLOR_TEXT_BRIGHT}; "
            f"font-size: 10px; font-weight: bold; border-radius: 3px; padding: 2px 6px;"
        )
        title_row.addWidget(self.badge_stream_mode)
        sc_layout.addLayout(title_row)

        stream_row = QHBoxLayout()
        self.lbl_stream_type = QLabel("Stream Type: -")
        self.lbl_stream_type.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: 11px;")
        stream_row.addWidget(self.lbl_stream_type)
        stream_row.addStretch()

        self.lbl_media_id = QLabel("Media ID: -")
        self.lbl_media_id.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        stream_row.addWidget(self.lbl_media_id)
        sc_layout.addLayout(stream_row)

        self.lbl_promotion_notice = QLabel(
            "Embedded in bank DATA/DIDX. Replacing audio will promote this node to "
            "Streamed (stream_type = 2) and stage a loose .wem file in the workspace."
        )
        self.lbl_promotion_notice.setWordWrap(True)
        self.lbl_promotion_notice.setStyleSheet(
            f"color: {COLOR_WARNING}; font-size: 10px; padding: 2px 0px;"
        )
        self.lbl_promotion_notice.setVisible(False)
        sc_layout.addWidget(self.lbl_promotion_notice)

        # Action Buttons Row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.btn_reference = QPushButton("Reference...")
        self.btn_reference.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_reference.setEnabled(False)
        self.btn_reference.clicked.connect(self._on_reference_clicked)
        btn_row.addWidget(self.btn_reference)

        self.btn_export = QPushButton("Export WAV...")
        self.btn_export.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._on_export_clicked)
        btn_row.addWidget(self.btn_export)

        sc_layout.addLayout(btn_row)

        # Tuning Controls Row (Volume dB & Pitch cents)
        tuning_row = QHBoxLayout()
        tuning_row.setSpacing(6)

        lbl_vol = QLabel("Vol:")
        lbl_vol.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px;")
        tuning_row.addWidget(lbl_vol)

        spin_style = (
            f"QDoubleSpinBox {{ background-color: {COLOR_BG_INPUT}; color: {COLOR_TEXT_PRIMARY}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 3px; font-size: 11px; padding: 2px 4px; }}"
        )

        self.spin_volume = QDoubleSpinBox()
        self.spin_volume.setStyleSheet(spin_style)
        self.spin_volume.setRange(-48.0, 24.0)
        self.spin_volume.setSingleStep(0.5)
        self.spin_volume.setSuffix(" dB")
        self.spin_volume.setValue(0.0)
        tuning_row.addWidget(self.spin_volume)

        lbl_pitch = QLabel("Pitch:")
        lbl_pitch.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px;")
        tuning_row.addWidget(lbl_pitch)

        self.spin_pitch = QDoubleSpinBox()
        self.spin_pitch.setStyleSheet(spin_style)
        self.spin_pitch.setRange(-2400.0, 2400.0)
        self.spin_pitch.setSingleStep(50.0)
        self.spin_pitch.setSuffix(" cents")
        self.spin_pitch.setValue(0.0)
        tuning_row.addWidget(self.spin_pitch)

        self.btn_apply_tuning = QPushButton("Apply Tuning")
        self.btn_apply_tuning.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_apply_tuning.setEnabled(False)
        self.btn_apply_tuning.clicked.connect(self._on_apply_tuning_clicked)
        tuning_row.addWidget(self.btn_apply_tuning)

        sc_layout.addLayout(tuning_row)
        layout.addWidget(self.source_card)

        # Audio References Section (Cross-Bank WEM References)
        self.lbl_refs = QLabel("Audio WEM References (0) — Double-click to navigate")
        self.lbl_refs.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; font-weight: bold;"
        )
        layout.addWidget(self.lbl_refs)

        self.ref_table = QTableWidget(0, 4)
        self.ref_table.setHorizontalHeaderLabels(["Bank", "HIRC ID", "Name / Alias", "Type"])
        rhdr = self.ref_table.horizontalHeader()
        rhdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        rhdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        rhdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        rhdr.setStretchLastSection(True)
        self.ref_table.setColumnWidth(0, 110)
        self.ref_table.setColumnWidth(1, 80)
        self.ref_table.setColumnWidth(2, 130)
        self.ref_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.ref_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.ref_table.cellDoubleClicked.connect(self._on_ref_double_clicked)
        self.ref_table.setStyleSheet(
            f"QTableWidget {{ background-color: {COLOR_BG_INPUT}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; color: {COLOR_TEXT_PRIMARY}; font-size: 11px; }} "
            f"QTableWidget::item {{ padding: 3px 6px; }} "
            f"QHeaderView::section {{ background-color: {COLOR_BG_PANEL}; color: {COLOR_TEXT_SECONDARY}; "
            f"font-weight: bold; border: 1px solid {COLOR_BORDER}; padding: 3px; }}"
        )
        layout.addWidget(self.ref_table, 1)

        # Properties Table
        self.prop_table = QTableWidget(0, 2)
        self.prop_table.setHorizontalHeaderLabels(["Parameter", "Value"])
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
        layout.addWidget(self.prop_table, 1)

    def _on_export_clicked(self) -> None:
        if self._current_sound_id is not None:
            self.export_requested.emit(self._current_sound_id)

    def _on_apply_tuning_clicked(self) -> None:
        if self._current_sound_id is not None:
            self.node_params_changed.emit(
                self._current_sound_id,
                self.spin_volume.value(),
                self.spin_pitch.value(),
            )

    def _on_reference_clicked(self) -> None:
        if self._current_sound_id is None:
            return
        val, ok = QInputDialog.getInt(
            self,
            "Reference Media ID",
            "Enter target WEM Media ID:",
            0,
            1,
            2147483647,
        )
        if ok:
            self.reference_media_requested.emit(self._current_sound_id, val)

    def _on_ref_double_clicked(self, row: int, _col: int) -> None:
        item = self.ref_table.item(row, 0)
        if item is not None:
            target_key = item.data(_ROLE_TARGET_KEY)
            if target_key:
                self.jump_requested.emit(target_key)

    def render_details(self, details: NodeInspectorDetails | None, selected_count: int = 1) -> None:
        """Alias for render() supporting direct detail rendering."""
        self.render(details, selected_count=selected_count)

    def render(self, details: NodeInspectorDetails | None, selected_count: int = 1) -> None:
        """Projects sound details with strict signal blocking."""
        self.prop_table.blockSignals(True)
        self.ref_table.blockSignals(True)
        if details is None:
            self._current_sound_id = None
            self.lbl_stream_type.setText("Stream Type: -")
            self.lbl_media_id.setText("Media ID: -")
            self.badge_stream_mode.setText("NONE")
            self.lbl_promotion_notice.setVisible(False)
            self.lbl_refs.setText("Audio WEM References (0) — Double-click to navigate")
            self.btn_reference.setEnabled(False)
            self.btn_export.setEnabled(False)
            self.btn_export.setText("Export WAV...")
            self.spin_volume.blockSignals(True)
            self.spin_pitch.blockSignals(True)
            self.spin_volume.setValue(0.0)
            self.spin_pitch.setValue(0.0)
            self.spin_volume.blockSignals(False)
            self.spin_pitch.blockSignals(False)
            self.btn_apply_tuning.setEnabled(False)
            self.ref_table.setRowCount(0)
            self.prop_table.setRowCount(0)
            self.ref_table.blockSignals(False)
            self.prop_table.blockSignals(False)
            return

        self._current_sound_id = details.object_id
        self.btn_reference.setEnabled(True)
        self.btn_export.setEnabled(True)

        vol = 0.0
        pitch = 0.0
        for p in details.properties:
            lbl = p.label.lower().strip()
            if "volume" in lbl or "prop 0" in lbl or "prop_0" in lbl or lbl == "0":
                try:
                    clean = p.value.lower().replace("db", "").strip()
                    vol = float(clean)
                except (ValueError, TypeError):
                    pass
            elif "pitch" in lbl or "prop 2" in lbl or "prop_2" in lbl or lbl == "2":
                try:
                    clean = p.value.lower().replace("cents", "").strip()
                    pitch = float(clean)
                except (ValueError, TypeError):
                    pass

        self.spin_volume.blockSignals(True)
        self.spin_pitch.blockSignals(True)
        self.spin_volume.setValue(vol)
        self.spin_pitch.setValue(pitch)
        self.spin_volume.blockSignals(False)
        self.spin_pitch.blockSignals(False)
        self.btn_apply_tuning.setEnabled(True)

        if selected_count > 1:
            self.btn_export.setText(f"Export WAV ({selected_count})...")
        else:
            self.btn_export.setText("Export WAV...")

        stream_val = "-"
        media_val = "-"
        for p in details.properties:
            if p.label == "Stream Type":
                stream_val = p.value
            elif p.label == "Source Media ID":
                media_val = p.value

        if stream_val == "-":
            stream_val = "Streamed (External)" if details.is_streamed else "Embedded (Bank)"
        if media_val == "-" and details.source_wem_id is not None:
            media_val = str(details.source_wem_id)

        self.lbl_stream_type.setText(f"Stream Type: {stream_val}")
        self.lbl_media_id.setText(f"Media ID: {media_val}")

        if details.is_streamed:
            self.badge_stream_mode.setText("STREAMED")
            self.badge_stream_mode.setStyleSheet(
                f"background-color: {COLOR_SUCCESS}; color: {COLOR_TEXT_BRIGHT}; "
                f"font-size: 10px; font-weight: bold; border-radius: 3px; padding: 2px 6px;"
            )
            self.lbl_promotion_notice.setVisible(False)
        else:
            self.badge_stream_mode.setText("EMBEDDED")
            self.badge_stream_mode.setStyleSheet(
                f"background-color: {COLOR_WARNING}; color: {COLOR_BG_INPUT}; "
                f"font-size: 10px; font-weight: bold; border-radius: 3px; padding: 2px 6px;"
            )
            self.lbl_promotion_notice.setVisible(True)

        refs = details.audio_references if details.audio_references else details.parent_references
        ref_count = details.audio_reference_count if details.audio_reference_count else len(refs)
        self.lbl_refs.setText(f"Audio WEM References ({ref_count}) — Double-click to navigate")
        self.ref_table.setRowCount(len(refs))
        for row, ref in enumerate(refs):
            jump_key = f"{ref.bank_name}::{ref.key}" if ref.bank_name else ref.key
            bank_item = QTableWidgetItem(ref.bank_name or "-")
            bank_item.setData(_ROLE_TARGET_KEY, jump_key)
            id_item = QTableWidgetItem(ref.id_str)
            id_item.setData(_ROLE_TARGET_KEY, jump_key)
            name_item = QTableWidgetItem(ref.label)
            name_item.setData(_ROLE_TARGET_KEY, jump_key)
            type_item = QTableWidgetItem(ref.type_str)
            type_item.setData(_ROLE_TARGET_KEY, jump_key)
            self.ref_table.setItem(row, 0, bank_item)
            self.ref_table.setItem(row, 1, id_item)
            self.ref_table.setItem(row, 2, name_item)
            self.ref_table.setItem(row, 3, type_item)

        self.prop_table.setRowCount(len(details.properties))
        for row, prop in enumerate(details.properties):
            self.prop_table.setItem(row, 0, QTableWidgetItem(prop.label))
            self.prop_table.setItem(row, 1, QTableWidgetItem(prop.value))

        self.ref_table.blockSignals(False)
        self.prop_table.blockSignals(False)
