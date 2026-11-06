"""
Pure PySide6 projection widget for audio enhancements and loudness processing.
Provides interactive controls for gain trim, peak normalization, RMS matching, and muting.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.ui.features.audio_sources.state import AudioEnhanceSettings
from src.ui.theme import (
    BTN_STYLE_PRESET,
    BTN_STYLE_PRIMARY,
    BTN_STYLE_SECONDARY,
    CHECKBOX_STYLE,
    COLOR_ACCENT,
    COLOR_BG_INPUT,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_BRIGHT,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
)

_SPIN_STYLE = (
    f"QDoubleSpinBox {{ "
    f"background-color: {COLOR_BG_INPUT}; "
    f"color: {COLOR_TEXT_PRIMARY}; "
    f"border: 1px solid {COLOR_BORDER}; "
    f"border-radius: 3px; "
    f"padding: 2px 4px; "
    f"font-size: 11px; "
    f"}} "
    f"QDoubleSpinBox:focus {{ "
    f"border: 1px solid {COLOR_ACCENT}; "
    f"}}"
)

_CARD_STYLE = (
    f"QFrame {{ "
    f"background-color: {COLOR_BG_PANEL}; "
    f"border: 1px solid {COLOR_BORDER}; "
    f"border-radius: 4px; "
    f"padding: 6px; "
    f"}}"
)

_PRESET_BTN_STYLE = BTN_STYLE_PRESET


class EnhanceTab(QWidget):
    """Interactive control tab for DSP audio enhancements and quick muting."""

    settings_changed = Signal(object)
    preview_requested = Signal(object)
    apply_requested = Signal(object)
    mute_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._has_targets = False
        self._target_count = 0
        self._init_ui()
        self._wire_signals()

    def _init_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(4)

        # Scroll area for compact docks
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # 1. Header Card
        card_header = QFrame()
        card_header.setStyleSheet(_CARD_STYLE)
        ch_layout = QVBoxLayout(card_header)
        ch_layout.setContentsMargins(6, 6, 6, 6)
        ch_layout.setSpacing(2)

        lbl_title = QLabel("Audio Enhancements")
        lbl_title.setStyleSheet(
            f"color: {COLOR_TEXT_PRIMARY}; font-weight: bold; font-size: 12px; border: none;"
        )
        ch_layout.addWidget(lbl_title)

        lbl_desc = QLabel(
            "Apply in-place DSP modifiers (gain, normalization, loudness matching) or silence to selected targets."
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px; border: none;")
        ch_layout.addWidget(lbl_desc)

        self.lbl_targets_info = QLabel("No targets selected")
        self.lbl_targets_info.setStyleSheet(
            f"color: {COLOR_WARNING}; font-size: 11px; font-weight: bold; border: none;"
        )
        ch_layout.addWidget(self.lbl_targets_info)
        layout.addWidget(card_header)

        # 2. Gain Trim Card
        self.card_gain = QFrame()
        self.card_gain.setStyleSheet(_CARD_STYLE)
        cg_layout = QVBoxLayout(self.card_gain)
        cg_layout.setContentsMargins(6, 6, 6, 6)
        cg_layout.setSpacing(6)

        self.chk_gain = QCheckBox("Gain Adjustment")
        self.chk_gain.setStyleSheet(CHECKBOX_STYLE)
        cg_layout.addWidget(self.chk_gain)

        slider_row = QHBoxLayout()
        slider_row.setSpacing(6)

        self.slider_gain = QSlider(Qt.Orientation.Horizontal)
        self.slider_gain.setRange(-240, 240)  # -24.0 dB to +24.0 dB (in 0.1 dB increments)
        self.slider_gain.setValue(0)
        self.slider_gain.setEnabled(False)
        slider_row.addWidget(self.slider_gain, 1)

        self.spin_gain = QDoubleSpinBox()
        self.spin_gain.setStyleSheet(_SPIN_STYLE)
        self.spin_gain.setRange(-24.0, 24.0)
        self.spin_gain.setSingleStep(0.5)
        self.spin_gain.setDecimals(1)
        self.spin_gain.setSuffix(" dB")
        self.spin_gain.setValue(0.0)
        self.spin_gain.setEnabled(False)
        slider_row.addWidget(self.spin_gain)
        cg_layout.addLayout(slider_row)

        presets_gain = QHBoxLayout()
        presets_gain.setSpacing(4)
        self.btn_gain_m6 = QPushButton("-6 dB")
        self.btn_gain_m3 = QPushButton("-3 dB")
        self.btn_gain_zero = QPushButton("0 dB")
        self.btn_gain_p3 = QPushButton("+3 dB")
        self.btn_gain_p6 = QPushButton("+6 dB")
        for b in (
            self.btn_gain_m6,
            self.btn_gain_m3,
            self.btn_gain_zero,
            self.btn_gain_p3,
            self.btn_gain_p6,
        ):
            b.setStyleSheet(_PRESET_BTN_STYLE)
            presets_gain.addWidget(b)
        cg_layout.addLayout(presets_gain)
        layout.addWidget(self.card_gain)

        # 3. Peak Normalization Card
        self.card_norm = QFrame()
        self.card_norm.setStyleSheet(_CARD_STYLE)
        cn_layout = QVBoxLayout(self.card_norm)
        cn_layout.setContentsMargins(6, 6, 6, 6)
        cn_layout.setSpacing(6)

        self.chk_normalize = QCheckBox("Peak Normalization")
        self.chk_normalize.setStyleSheet(CHECKBOX_STYLE)
        cn_layout.addWidget(self.chk_normalize)

        lbl_norm_hint = QLabel("Scales audio so peak transient reaches target ceiling.")
        lbl_norm_hint.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 10px; border: none;")
        cn_layout.addWidget(lbl_norm_hint)

        norm_row = QHBoxLayout()
        norm_row.setSpacing(6)
        lbl_peak = QLabel("Target Peak:")
        lbl_peak.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; border: none;")
        norm_row.addWidget(lbl_peak)

        self.spin_normalize = QDoubleSpinBox()
        self.spin_normalize.setStyleSheet(_SPIN_STYLE)
        self.spin_normalize.setRange(-24.0, 0.0)
        self.spin_normalize.setSingleStep(0.1)
        self.spin_normalize.setDecimals(1)
        self.spin_normalize.setSuffix(" dBFS")
        self.spin_normalize.setValue(-1.0)
        self.spin_normalize.setEnabled(False)
        norm_row.addWidget(self.spin_normalize)
        norm_row.addStretch()
        cn_layout.addLayout(norm_row)

        presets_norm = QHBoxLayout()
        presets_norm.setSpacing(4)
        self.btn_norm_max = QPushButton("-0.1 dB (Peak)")
        self.btn_norm_std = QPushButton("-1.0 dB (Standard)")
        self.btn_norm_safe = QPushButton("-3.0 dB (Safe)")
        for b in (self.btn_norm_max, self.btn_norm_std, self.btn_norm_safe):
            b.setStyleSheet(_PRESET_BTN_STYLE)
            presets_norm.addWidget(b)
        cn_layout.addLayout(presets_norm)
        layout.addWidget(self.card_norm)

        # 4. Loudness Matching (RMS) Card
        self.card_loudness = QFrame()
        self.card_loudness.setStyleSheet(_CARD_STYLE)
        cl_layout = QVBoxLayout(self.card_loudness)
        cl_layout.setContentsMargins(6, 6, 6, 6)
        cl_layout.setSpacing(6)

        self.chk_loudness = QCheckBox("Match Loudness (RMS)")
        self.chk_loudness.setStyleSheet(CHECKBOX_STYLE)
        cl_layout.addWidget(self.chk_loudness)

        lbl_loudness_hint = QLabel(
            "Matches perceived energy with soft limiter to prevent clipping."
        )
        lbl_loudness_hint.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 10px; border: none;"
        )
        cl_layout.addWidget(lbl_loudness_hint)

        loud_row = QHBoxLayout()
        loud_row.setSpacing(6)
        lbl_rms = QLabel("Target RMS:")
        lbl_rms.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; border: none;")
        loud_row.addWidget(lbl_rms)

        self.spin_rms = QDoubleSpinBox()
        self.spin_rms.setStyleSheet(_SPIN_STYLE)
        self.spin_rms.setRange(-36.0, -6.0)
        self.spin_rms.setSingleStep(0.5)
        self.spin_rms.setDecimals(1)
        self.spin_rms.setSuffix(" dBFS")
        self.spin_rms.setValue(-14.0)
        self.spin_rms.setEnabled(False)
        loud_row.addWidget(self.spin_rms)

        lbl_boost = QLabel("Max Boost:")
        lbl_boost.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; border: none;")
        loud_row.addWidget(lbl_boost)

        self.spin_max_boost = QDoubleSpinBox()
        self.spin_max_boost.setStyleSheet(_SPIN_STYLE)
        self.spin_max_boost.setRange(1.0, 24.0)
        self.spin_max_boost.setSingleStep(0.5)
        self.spin_max_boost.setDecimals(1)
        self.spin_max_boost.setSuffix(" dB")
        self.spin_max_boost.setValue(12.0)
        self.spin_max_boost.setEnabled(False)
        loud_row.addWidget(self.spin_max_boost)
        loud_row.addStretch()
        cl_layout.addLayout(loud_row)
        layout.addWidget(self.card_loudness)

        # 5. Quick Mute Card
        card_mute = QFrame()
        card_mute.setStyleSheet(_CARD_STYLE)
        cm_layout = QVBoxLayout(card_mute)
        cm_layout.setContentsMargins(6, 6, 6, 6)
        cm_layout.setSpacing(4)

        lbl_mute_title = QLabel("Mute Target(s)")
        lbl_mute_title.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-weight: bold; font-size: 11px; border: none;"
        )
        cm_layout.addWidget(lbl_mute_title)

        lbl_mute_desc = QLabel("Replaces selected sound nodes with standard 50ms silent stub.")
        lbl_mute_desc.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 10px; border: none;")
        cm_layout.addWidget(lbl_mute_desc)

        self.btn_mute = QPushButton("Mute Node(s)")
        self.btn_mute.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_mute.setEnabled(False)
        cm_layout.addWidget(self.btn_mute)
        layout.addWidget(card_mute)

        # 6. Action Buttons: Preview & Apply
        action_bar = QHBoxLayout()
        action_bar.setSpacing(6)

        self.btn_preview = QPushButton("Preview Audio")
        self.btn_preview.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_preview.setEnabled(False)
        self.btn_preview.setFixedHeight(30)
        action_bar.addWidget(self.btn_preview, 1)

        self.btn_apply = QPushButton("Apply Enhancements to Selected")
        self.btn_apply.setStyleSheet(BTN_STYLE_PRIMARY)
        self.btn_apply.setEnabled(False)
        self.btn_apply.setFixedHeight(30)
        action_bar.addWidget(self.btn_apply, 2)

        layout.addLayout(action_bar)

        layout.addStretch()
        scroll_area.setWidget(content)
        root_layout.addWidget(scroll_area)

    def _wire_signals(self) -> None:
        self.chk_gain.toggled.connect(self._on_gain_toggled)
        self.slider_gain.valueChanged.connect(self._on_slider_gain_changed)
        self.slider_gain.sliderReleased.connect(self._on_settings_modified)
        self.spin_gain.valueChanged.connect(self._on_spin_gain_changed)

        self.btn_gain_m6.clicked.connect(lambda: self.spin_gain.setValue(-6.0))
        self.btn_gain_m3.clicked.connect(lambda: self.spin_gain.setValue(-3.0))
        self.btn_gain_zero.clicked.connect(lambda: self.spin_gain.setValue(0.0))
        self.btn_gain_p3.clicked.connect(lambda: self.spin_gain.setValue(3.0))
        self.btn_gain_p6.clicked.connect(lambda: self.spin_gain.setValue(6.0))

        self.chk_normalize.toggled.connect(self._on_normalize_toggled)
        self.spin_normalize.valueChanged.connect(self._on_settings_modified)
        self.btn_norm_max.clicked.connect(lambda: self.spin_normalize.setValue(-0.1))
        self.btn_norm_std.clicked.connect(lambda: self.spin_normalize.setValue(-1.0))
        self.btn_norm_safe.clicked.connect(lambda: self.spin_normalize.setValue(-3.0))

        self.chk_loudness.toggled.connect(self._on_loudness_toggled)
        self.spin_rms.valueChanged.connect(self._on_settings_modified)
        self.spin_max_boost.valueChanged.connect(self._on_settings_modified)

        self.btn_mute.clicked.connect(self.mute_requested.emit)
        self.btn_preview.clicked.connect(self._on_preview_clicked)
        self.btn_apply.clicked.connect(self._on_apply_clicked)

    def _on_gain_toggled(self, checked: bool) -> None:
        self.slider_gain.setEnabled(checked)
        self.spin_gain.setEnabled(checked)
        self._on_settings_modified()

    def _on_slider_gain_changed(self, value: int) -> None:
        float_val = value / 10.0
        self.spin_gain.blockSignals(True)
        self.spin_gain.setValue(float_val)
        self.spin_gain.blockSignals(False)
        if not self.slider_gain.isSliderDown():
            self._on_settings_modified()

    def _on_spin_gain_changed(self, value: float) -> None:
        int_val = int(round(value * 10))
        self.slider_gain.blockSignals(True)
        self.slider_gain.setValue(int_val)
        self.slider_gain.blockSignals(False)
        self._on_settings_modified()

    def _on_normalize_toggled(self, checked: bool) -> None:
        self.spin_normalize.setEnabled(checked)
        self._on_settings_modified()

    def _on_loudness_toggled(self, checked: bool) -> None:
        self.spin_rms.setEnabled(checked)
        self.spin_max_boost.setEnabled(checked)
        self._on_settings_modified()

    def _on_settings_modified(self) -> None:
        settings = self.get_settings()
        self.settings_changed.emit(settings)
        self._update_apply_enablement()

    def _on_preview_clicked(self) -> None:
        self.preview_requested.emit(self.get_settings())

    def _on_apply_clicked(self) -> None:
        self.apply_requested.emit(self.get_settings())

    def _update_apply_enablement(self) -> None:
        has_active_mods = (
            (self.chk_gain.isChecked() and self.spin_gain.value() != 0.0)
            or self.chk_normalize.isChecked()
            or self.chk_loudness.isChecked()
        )
        self.btn_preview.setEnabled(self._has_targets)
        self.btn_apply.setEnabled(self._has_targets and has_active_mods)
        self.btn_mute.setEnabled(self._has_targets)

    def get_settings(self) -> AudioEnhanceSettings:
        """Collects current UI settings into an immutable AudioEnhanceSettings."""
        return AudioEnhanceSettings(
            gain_enabled=self.chk_gain.isChecked(),
            gain_db=self.spin_gain.value(),
            normalize_enabled=self.chk_normalize.isChecked(),
            target_peak_db=self.spin_normalize.value(),
            match_loudness_enabled=self.chk_loudness.isChecked(),
            target_rms_db=self.spin_rms.value(),
            max_boost_db=self.spin_max_boost.value(),
        )

    def render_enhance(
        self,
        has_targets: bool,
        settings: AudioEnhanceSettings,
        target_count: int = 0,
    ) -> None:
        """Projects target state and settings snapshot onto UI with strict signal blocking."""
        self._has_targets = has_targets
        self._target_count = target_count

        if target_count == 0:
            self.lbl_targets_info.setText("No targets selected")
            self.lbl_targets_info.setStyleSheet(
                f"color: {COLOR_WARNING}; font-size: 11px; font-weight: bold; border: none;"
            )
        elif target_count == 1:
            self.lbl_targets_info.setText("1 target selected")
            self.lbl_targets_info.setStyleSheet(
                f"color: {COLOR_TEXT_BRIGHT}; font-size: 11px; font-weight: bold; border: none;"
            )
        else:
            self.lbl_targets_info.setText(f"{target_count} targets selected")
            self.lbl_targets_info.setStyleSheet(
                f"color: {COLOR_TEXT_BRIGHT}; font-size: 11px; font-weight: bold; border: none;"
            )

        # Block signals during programmatic update
        self.chk_gain.blockSignals(True)
        self.slider_gain.blockSignals(True)
        self.spin_gain.blockSignals(True)
        self.chk_normalize.blockSignals(True)
        self.spin_normalize.blockSignals(True)
        self.chk_loudness.blockSignals(True)
        self.spin_rms.blockSignals(True)
        self.spin_max_boost.blockSignals(True)

        self.chk_gain.setChecked(settings.gain_enabled)
        self.slider_gain.setEnabled(settings.gain_enabled)
        self.spin_gain.setEnabled(settings.gain_enabled)
        self.slider_gain.setValue(int(round(settings.gain_db * 10)))
        self.spin_gain.setValue(settings.gain_db)

        self.chk_normalize.setChecked(settings.normalize_enabled)
        self.spin_normalize.setEnabled(settings.normalize_enabled)
        self.spin_normalize.setValue(settings.target_peak_db)

        self.chk_loudness.setChecked(settings.match_loudness_enabled)
        self.spin_rms.setEnabled(settings.match_loudness_enabled)
        self.spin_max_boost.setEnabled(settings.match_loudness_enabled)
        self.spin_rms.setValue(settings.target_rms_db)
        self.spin_max_boost.setValue(settings.max_boost_db)

        self.chk_gain.blockSignals(False)
        self.slider_gain.blockSignals(False)
        self.spin_gain.blockSignals(False)
        self.chk_normalize.blockSignals(False)
        self.spin_normalize.blockSignals(False)
        self.chk_loudness.blockSignals(False)
        self.spin_rms.blockSignals(False)
        self.spin_max_boost.blockSignals(False)

        self._update_apply_enablement()

    def render_silence(self, has_targets: bool) -> None:
        """Compatibility alias for tests calling render_silence."""
        self._has_targets = has_targets
        self._update_apply_enablement()
