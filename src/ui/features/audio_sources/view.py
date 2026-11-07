"""
Pure PySide6 projection widget for the Audio Sources dock.
Implements Phase 5 (/data-driven-ui) with zero business logic and strict signal blocking.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.ui.features.audio_sources.state import (
    ApplyMode,
    AudioEnhanceSettings,
    AudioSourcesState,
    AudioSourcesTab,
)
from src.ui.features.audio_sources.store import AudioSourcesStore
from src.ui.features.audio_sources.widgets.enhance_tab import EnhanceTab
from src.ui.features.audio_sources.widgets.files_table import FilesTableWidget
from src.ui.features.audio_sources.widgets.game_audio_tab import GameAudioTab
from src.ui.features.audio_sources.widgets.libraries_table import LibrariesTableWidget
from src.ui.features.audio_transport import AudioTransportBar, AudioTransportStore
from src.ui.theme import (
    BTN_STYLE_PRIMARY,
    BTN_STYLE_SECONDARY,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
)


class AudioSourcesView(QWidget):
    """Audio Sources dock projection widget managing libraries, game audio, and batch actions."""

    def __init__(
        self,
        store: AudioSourcesStore,
        transport_store: AudioTransportStore | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._transport_store = transport_store
        self._init_ui()
        self._wire_signals()
        self._store.subscribe(self.render)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # 1. Target summary & status banner
        top_banner = QFrame()
        top_banner.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_PANEL}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; padding: 4px; }}"
        )
        banner_layout = QVBoxLayout(top_banner)
        banner_layout.setContentsMargins(6, 4, 6, 4)
        banner_layout.setSpacing(2)

        self.lbl_target_summary = QLabel("No target selected")
        self.lbl_target_summary.setStyleSheet(
            f"color: {COLOR_TEXT_PRIMARY}; font-weight: bold; font-size: 12px; border: none;"
        )
        banner_layout.addWidget(self.lbl_target_summary)

        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px; border: none;")
        banner_layout.addWidget(self.lbl_status)

        layout.addWidget(top_banner)

        # 2. Main tabs (Libraries, Game Audio, Silence)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(
            f"QTabWidget::pane {{ border: 1px solid {COLOR_BORDER}; background-color: {COLOR_BG_PANEL}; }} "
            f"QTabBar::tab {{ color: {COLOR_TEXT_SECONDARY}; padding: 6px 12px; }} "
            f"QTabBar::tab:selected {{ color: {COLOR_TEXT_PRIMARY}; font-weight: bold; }}"
        )

        # Tab 0: Libraries
        self.tab_libraries = QWidget()
        lib_layout = QVBoxLayout(self.tab_libraries)
        lib_layout.setContentsMargins(4, 4, 4, 4)
        lib_layout.setSpacing(4)

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)

        self.libraries_widget = LibrariesTableWidget()
        self.files_widget = FilesTableWidget()

        self.splitter.addWidget(self.libraries_widget)
        self.splitter.addWidget(self.files_widget)
        self.splitter.setSizes([140, 260])

        lib_layout.addWidget(self.splitter)
        self.tabs.addTab(self.tab_libraries, "Libraries")

        # Tab 1: Game Audio
        self.tab_game_audio = GameAudioTab()
        self.tabs.addTab(self.tab_game_audio, "Game Audio")

        # Tab 2: Enhance (replaces old Silence tab)
        self.tab_enhance = EnhanceTab()
        self.tabs.addTab(self.tab_enhance, "Enhance")

        layout.addWidget(self.tabs, 1)

        # 3. Action buttons
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(8)

        self.btn_apply = QPushButton("Apply to Selected")
        self.btn_apply.setStyleSheet(BTN_STYLE_PRIMARY)
        self.btn_apply.setEnabled(False)
        btn_bar.addWidget(self.btn_apply, 1)

        self.btn_distribute = QPushButton("Distribute to Selected")
        self.btn_distribute.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_distribute.setEnabled(False)
        btn_bar.addWidget(self.btn_distribute, 1)

        layout.addLayout(btn_bar)

        # 4. In-dock compact audio player
        if self._transport_store is not None:
            self.transport_bar = AudioTransportBar(self._transport_store, compact=True)
            layout.addWidget(self.transport_bar)

    def _wire_signals(self) -> None:
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.btn_apply.clicked.connect(self._on_apply_clicked)
        self.btn_distribute.clicked.connect(self._on_distribute_clicked)

        # Libraries tab wiring
        self.libraries_widget.library_selected.connect(self._store.select_library)
        self.libraries_widget.add_requested.connect(self._store.add_library)
        self.libraries_widget.rename_requested.connect(self._store.rename_library)
        self.libraries_widget.remove_requested.connect(self._store.remove_library)

        self.files_widget.files_selected.connect(self._store.select_files)
        self.files_widget.filter_changed.connect(self._store.set_filter_text)

        # Enhance tab wiring
        self.tab_enhance.mute_requested.connect(self._store.apply_silence)
        self.tab_enhance.settings_changed.connect(self._on_enhance_settings_changed)
        self.tab_enhance.preview_requested.connect(self._on_enhance_preview_clicked)
        self.tab_enhance.apply_requested.connect(self._on_enhance_apply_clicked)

        # Game Audio tab wiring
        self.tab_game_audio.entry_selected.connect(self._store.select_game_audio_entry)

    def _on_tab_changed(self, index: int) -> None:
        try:
            tab = AudioSourcesTab(index)
            self._store.set_active_tab(tab)
        except (ValueError, IndexError):
            pass

    def _on_enhance_settings_changed(self, settings: AudioEnhanceSettings) -> None:
        self._store.set_enhance_settings(settings)

    def _on_enhance_apply_clicked(self, settings: AudioEnhanceSettings) -> None:
        self._store.apply_enhancements(settings)

    def _on_enhance_preview_clicked(self, settings: AudioEnhanceSettings) -> None:
        self._store.preview_enhancements(settings)
        if self._transport_store is not None:
            self._transport_store.play()

    def _on_apply_clicked(self) -> None:
        if self._store.state.active_tab == AudioSourcesTab.ENHANCE:
            return
        self._store.apply(ApplyMode.ALL)

    def _on_distribute_clicked(self) -> None:
        if self._store.state.active_tab == AudioSourcesTab.ENHANCE:
            return
        self._store.apply(ApplyMode.DISTRIBUTE)

    def render(self, state: AudioSourcesState) -> None:
        """Projects state snapshot onto UI elements with strict signal blocking."""
        # Target summary label
        target_count = len(state.targets)
        if target_count == 0:
            self.lbl_target_summary.setText("No target selected")
        elif target_count == 1:
            self.lbl_target_summary.setText("1 target selected")
        else:
            self.lbl_target_summary.setText(f"{target_count} targets selected")

        # Status label
        status_text = state.status_message or ""
        self.lbl_status.setText(status_text)
        self.lbl_status.setToolTip(status_text)
        has_rejections = (
            state.last_outcome is not None and bool(state.last_outcome.rejections)
        ) or "rejected" in status_text.lower()
        status_color = COLOR_WARNING if has_rejections else COLOR_TEXT_MUTED
        self.lbl_status.setStyleSheet(f"color: {status_color}; font-size: 11px; border: none;")

        # Active tab
        self.tabs.blockSignals(True)
        if self.tabs.currentIndex() != state.active_tab.value:
            self.tabs.setCurrentIndex(state.active_tab.value)
        self.tabs.blockSignals(False)

        # Project child components
        self.libraries_widget.render_libraries(state.libraries, state.selected_library_id)
        self.files_widget.render_files(state.files, state.filter_text, state.selected_file_paths)
        if self.tab_game_audio._all_entries != state.game_audio_entries:
            self.tab_game_audio.set_entries(state.game_audio_entries)
        self.tab_enhance.render_enhance(
            target_count > 0, state.enhance_settings, target_count=target_count
        )

        # Action buttons enablement
        has_targets = target_count > 0
        if state.active_tab == AudioSourcesTab.LIBRARIES:
            has_sources = len(state.selected_file_paths) > 0
            self.btn_apply.setEnabled(has_targets and has_sources)
            self.btn_distribute.setEnabled(has_targets and has_sources)
        elif state.active_tab == AudioSourcesTab.GAME_AUDIO:
            has_cat_entry = state.selected_game_audio_entry is not None
            self.btn_apply.setEnabled(has_targets and has_cat_entry)
            self.btn_distribute.setEnabled(False)
        elif state.active_tab == AudioSourcesTab.ENHANCE:
            self.btn_apply.setEnabled(False)
            self.btn_distribute.setEnabled(False)
        else:
            self.btn_apply.setEnabled(False)
            self.btn_distribute.setEnabled(False)
