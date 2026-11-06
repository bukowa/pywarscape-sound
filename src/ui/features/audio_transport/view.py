"""
PySide6 AudioTransportBar projection widget for audio auditioning.

Part of Phase 5 (/data-driven-ui) in the Spec-Driven Functional Pipeline.
Pure view projection: renders TransportState and dispatches user actions to store.
Zero business logic, zero direct disk I/O, strict Qt signal blocking.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from src.ui.features.audio_transport.store import AudioTransportStore
from src.ui.features.audio_transport.structs import PlaybackStatus, TransportState
from src.ui.theme import (
    BTN_STYLE_SECONDARY,
    CHECKBOX_STYLE,
    COLOR_ACCENT,
    COLOR_BG_INPUT,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    make_transport_icon,
)


def _format_time_ms(ms: int) -> str:
    """Formats millisecond timestamp into mm:ss display."""
    total_sec = max(0, ms // 1000)
    minutes = total_sec // 60
    seconds = total_sec % 60
    return f"{minutes:02d}:{seconds:02d}"


class ClickableSlider(QSlider):
    """QSlider that immediately jumps to clicked track position and supports dragging."""

    def mousePressEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            hr = self.style().subControlRect(
                QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self
            )
            if not hr.contains(ev.position().toPoint()):
                if self.orientation() == Qt.Orientation.Horizontal:
                    pos = ev.position().x() - (hr.width() / 2.0)
                    available = self.width() - hr.width()
                else:
                    pos = ev.position().y() - (hr.height() / 2.0)
                    available = self.height() - hr.height()
                if available > 0:
                    val = QStyle.sliderValueFromPosition(
                        self.minimum(),
                        self.maximum(),
                        int(round(pos)),
                        available,
                        self.invertedAppearance(),
                    )
                    self.setValue(val)
        super().mousePressEvent(ev)


class AudioTransportBar(QFrame):
    """Global transport bar providing playback controls, seeking, and audition toggles."""

    def __init__(
        self,
        store: AudioTransportStore | None = None,
        parent: QWidget | None = None,
        compact: bool = False,
    ) -> None:
        super().__init__(parent)
        self.store = store or AudioTransportStore()
        self.compact = compact
        self._user_seeking = False

        self._icon_play = make_transport_icon("play")
        self._icon_pause = make_transport_icon("pause")
        self._icon_stop = make_transport_icon("stop")

        self._init_ui()
        self._setup_timer()

        self.store.subscribe(self.render)
        self.render(self.store.state)

    def _init_ui(self) -> None:
        self.setObjectName("audioTransportBar")
        if self.compact:
            self._init_compact_ui()
        else:
            self._init_standard_ui()

    def _init_compact_ui(self) -> None:
        self.setMinimumHeight(60)
        self.setStyleSheet(
            f"QFrame#audioTransportBar {{ "
            f"background-color: {COLOR_BG_PANEL}; "
            f"border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; "
            f"}}"
        )

        v_layout = QVBoxLayout(self)
        v_layout.setContentsMargins(6, 4, 6, 4)
        v_layout.setSpacing(4)

        # Row 1: Play, Stop, Time, Track Title, AutoPlay
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(6)

        self.btn_play = QPushButton()
        self.btn_play.setIcon(self._icon_play)
        self.btn_play.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_play.setToolTip("Play / Pause")
        self.btn_play.setFixedSize(28, 24)
        self.btn_play.clicked.connect(self._on_play_pause_clicked)
        row1.addWidget(self.btn_play)

        self.btn_stop = QPushButton()
        self.btn_stop.setIcon(self._icon_stop)
        self.btn_stop.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_stop.setToolTip("Stop")
        self.btn_stop.setFixedSize(28, 24)
        self.btn_stop.clicked.connect(self.store.stop)
        row1.addWidget(self.btn_stop)

        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-family: monospace; font-size: 10px;"
        )
        row1.addWidget(self.lbl_time)

        self.lbl_track = QLabel("No track selected")
        self.lbl_track.setStyleSheet(
            f"color: {COLOR_TEXT_PRIMARY}; font-size: 10px; font-weight: bold;"
        )
        self.lbl_track.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        row1.addWidget(self.lbl_track, 1)

        self.chk_autoplay = QCheckBox("Auto")
        self.chk_autoplay.setStyleSheet(CHECKBOX_STYLE)
        self.chk_autoplay.setToolTip("Automatically play audio when selected")
        self.chk_autoplay.clicked.connect(self.store.toggle_auto_play)
        row1.addWidget(self.chk_autoplay)

        v_layout.addLayout(row1)

        # Row 2: Seek slider, Loop, Volume
        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(6)

        self.seek_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setValue(0)
        self.seek_slider.setEnabled(False)
        self.seek_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ border: 1px solid {COLOR_BORDER}; height: 4px; background: {COLOR_BG_INPUT}; border-radius: 2px; }} "
            f"QSlider::sub-page:horizontal {{ background: {COLOR_ACCENT}; border-radius: 2px; }} "
            f"QSlider::handle:horizontal {{ background: {COLOR_TEXT_PRIMARY}; border: 1px solid {COLOR_BORDER}; width: 10px; margin: -3px 0; border-radius: 5px; }} "
            f"QSlider::handle:horizontal:disabled {{ background: {COLOR_TEXT_MUTED}; }}"
        )
        self.seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self.seek_slider.sliderMoved.connect(self._on_seek_moved)
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        row2.addWidget(self.seek_slider, 1)

        self.chk_loop = QCheckBox("Loop")
        self.chk_loop.setStyleSheet(CHECKBOX_STYLE)
        self.chk_loop.setToolTip("Loop active audio stream")
        self.chk_loop.clicked.connect(self.store.toggle_loop)
        row2.addWidget(self.chk_loop)

        lbl_vol = QLabel("Vol:")
        lbl_vol.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 10px;")
        row2.addWidget(lbl_vol)

        self.volume_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(50)
        self.volume_slider.setToolTip("Audition Volume")
        self.volume_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ border: 1px solid {COLOR_BORDER}; height: 4px; background: {COLOR_BG_INPUT}; border-radius: 2px; }} "
            f"QSlider::sub-page:horizontal {{ background: {COLOR_ACCENT}; border-radius: 2px; }} "
            f"QSlider::handle:horizontal {{ background: {COLOR_TEXT_PRIMARY}; border: 1px solid {COLOR_BORDER}; width: 8px; margin: -2px 0; border-radius: 4px; }}"
        )
        self.volume_slider.valueChanged.connect(lambda val: self.store.set_volume(val / 100.0))
        row2.addWidget(self.volume_slider)

        v_layout.addLayout(row2)

    def _init_standard_ui(self) -> None:
        self.setObjectName("audioTransportBar")
        self.setMinimumHeight(56)
        self.setStyleSheet(
            f"QFrame#audioTransportBar {{ "
            f"background-color: {COLOR_BG_PANEL}; "
            f"border-top: 1px solid {COLOR_BORDER}; "
            f"}}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        # 1. Transport Buttons (Play/Pause, Stop)
        self.btn_play = QPushButton()
        self.btn_play.setIcon(self._icon_play)
        self.btn_play.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_play.setToolTip("Play / Pause")
        self.btn_play.setFixedWidth(36)
        self.btn_play.clicked.connect(self._on_play_pause_clicked)
        layout.addWidget(self.btn_play)

        self.btn_stop = QPushButton()
        self.btn_stop.setIcon(self._icon_stop)
        self.btn_stop.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_stop.setToolTip("Stop")
        self.btn_stop.setFixedWidth(36)
        self.btn_stop.clicked.connect(self.store.stop)
        layout.addWidget(self.btn_stop)

        # 2. Time Display Label
        self.lbl_time = QLabel("00:00 / 00:00")
        self.lbl_time.setFixedWidth(86)
        self.lbl_time.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-family: monospace; font-size: 11px;"
        )
        layout.addWidget(self.lbl_time)

        # 3. Center Section: Track Title & Seek Slider
        center_box = QVBoxLayout()
        center_box.setContentsMargins(0, 0, 0, 0)
        center_box.setSpacing(2)

        self.lbl_track = QLabel("No track selected")
        self.lbl_track.setStyleSheet(
            f"color: {COLOR_TEXT_PRIMARY}; font-size: 11px; font-weight: bold;"
        )
        self.lbl_track.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        center_box.addWidget(self.lbl_track)

        self.seek_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.setValue(0)
        self.seek_slider.setEnabled(False)
        self.seek_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ border: 1px solid {COLOR_BORDER}; height: 4px; background: {COLOR_BG_INPUT}; border-radius: 2px; }} "
            f"QSlider::sub-page:horizontal {{ background: {COLOR_ACCENT}; border-radius: 2px; }} "
            f"QSlider::handle:horizontal {{ background: {COLOR_TEXT_PRIMARY}; border: 1px solid {COLOR_BORDER}; width: 12px; margin: -4px 0; border-radius: 6px; }} "
            f"QSlider::handle:horizontal:disabled {{ background: {COLOR_TEXT_MUTED}; }}"
        )
        self.seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self.seek_slider.sliderMoved.connect(self._on_seek_moved)
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        center_box.addWidget(self.seek_slider)
        layout.addLayout(center_box, 1)

        # 4. Right Options: Auto Play, Loop, Volume
        self.chk_autoplay = QCheckBox("Auto Play")
        self.chk_autoplay.setStyleSheet(CHECKBOX_STYLE)
        self.chk_autoplay.setToolTip("Automatically play audio when a node is selected")
        self.chk_autoplay.clicked.connect(self.store.toggle_auto_play)
        layout.addWidget(self.chk_autoplay)

        self.chk_loop = QCheckBox("Loop")
        self.chk_loop.setStyleSheet(CHECKBOX_STYLE)
        self.chk_loop.setToolTip("Continuously repeat active audio stream")
        self.chk_loop.clicked.connect(self.store.toggle_loop)
        layout.addWidget(self.chk_loop)

        # Volume slider
        lbl_vol = QLabel("Vol:")
        lbl_vol.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(lbl_vol)

        self.volume_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(70)
        self.volume_slider.setToolTip("Audition Volume")
        self.volume_slider.setStyleSheet(
            f"QSlider::groove:horizontal {{ border: 1px solid {COLOR_BORDER}; height: 4px; background: {COLOR_BG_INPUT}; border-radius: 2px; }} "
            f"QSlider::sub-page:horizontal {{ background: {COLOR_ACCENT}; border-radius: 2px; }} "
            f"QSlider::handle:horizontal {{ background: {COLOR_TEXT_PRIMARY}; border: 1px solid {COLOR_BORDER}; width: 10px; margin: -3px 0; border-radius: 5px; }}"
        )
        self.volume_slider.valueChanged.connect(lambda val: self.store.set_volume(val / 100.0))
        layout.addWidget(self.volume_slider)

    def _setup_timer(self) -> None:
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self.store.tick)
        self._timer.start()

    def _on_play_pause_clicked(self) -> None:
        if self.store.state.status == PlaybackStatus.PLAYING:
            self.store.pause()
        else:
            self.store.play()

    def _update_seek_time_display(self) -> None:
        track = self.store.state.active_track
        dur_ms = int(track.duration_ms) if track else 0
        if dur_ms > 0:
            target_ms = int((self.seek_slider.value() / 1000.0) * dur_ms)
            self.lbl_time.setText(f"{_format_time_ms(target_ms)} / {_format_time_ms(dur_ms)}")

    def _on_seek_pressed(self) -> None:
        self._user_seeking = True
        self._update_seek_time_display()

    def _on_seek_moved(self, val: int) -> None:
        self._update_seek_time_display()

    def _on_seek_released(self) -> None:
        self._user_seeking = False
        track = self.store.state.active_track
        dur_ms = int(track.duration_ms) if track else 0
        if dur_ms > 0:
            ratio = self.seek_slider.value() / 1000.0
            target_ms = int(ratio * dur_ms)
            self.store.seek(target_ms)

    def render(self, state: TransportState) -> None:
        """Projects TransportState onto Qt controls with strict signal blocking."""
        self.blockSignals(True)
        try:
            # 1. Track Title
            if state.active_track:
                title = state.active_track.title
                if state.error_message:
                    title += f" [Error: {state.error_message}]"
            else:
                title = "No track selected"
            if self.lbl_track.text() != title:
                self.lbl_track.setText(title)

            # 2. Time Display
            dur_ms = int(state.active_track.duration_ms) if state.active_track else 0
            if not self._user_seeking:
                pos_ms = int(state.position_ms)
                time_str = f"{_format_time_ms(pos_ms)} / {_format_time_ms(dur_ms)}"
                if self.lbl_time.text() != time_str:
                    self.lbl_time.setText(time_str)

            # 3. Transport Buttons
            is_playing = state.status == PlaybackStatus.PLAYING
            self.btn_play.setIcon(self._icon_pause if is_playing else self._icon_play)
            self.btn_play.setEnabled(state.can_play or state.can_pause)
            self.btn_stop.setEnabled(state.can_stop)

            # 4. Seek Slider
            self.seek_slider.setEnabled(state.active_track is not None and dur_ms > 0)
            if not self._user_seeking and dur_ms > 0:
                slider_val = int(state.progress_ratio * 1000)
                if self.seek_slider.value() != slider_val:
                    self.seek_slider.blockSignals(True)
                    self.seek_slider.setValue(slider_val)
                    self.seek_slider.blockSignals(False)

            # 5. Toggles
            if self.chk_autoplay.isChecked() != state.auto_play:
                self.chk_autoplay.blockSignals(True)
                self.chk_autoplay.setChecked(state.auto_play)
                self.chk_autoplay.blockSignals(False)

            if self.chk_loop.isChecked() != state.loop:
                self.chk_loop.blockSignals(True)
                self.chk_loop.setChecked(state.loop)
                self.chk_loop.blockSignals(False)

            # 6. Volume
            vol_val = int(float(state.volume) * 100)
            if self.volume_slider.value() != vol_val:
                self.volume_slider.blockSignals(True)
                self.volume_slider.setValue(vol_val)
                self.volume_slider.blockSignals(False)
        finally:
            self.blockSignals(False)
