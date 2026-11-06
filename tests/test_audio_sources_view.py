"""
Tests for AudioSourcesStore and AudioSourcesView projection.
Verifies data-driven rendering, signal blocking, store intents, and UI interactions.
"""

from pathlib import Path

from PySide6.QtCore import Qt

from src.engine.ontology import (
    ExternalFileSource,
    SilentStubSource,
    SoundNodeTarget,
)
from src.ui.features.audio_sources.state import (
    ApplyMode,
    AudioSourcesTab,
)
from src.ui.features.audio_sources.store import AudioSourcesStore
from src.ui.features.audio_sources.view import AudioSourcesView
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject
from src.workspace.sound_library import LibraryFileEntry


def test_audio_sources_view_render_and_signal_blocking(qtbot, tmp_path: Path):
    store = AudioSourcesStore()
    view = AudioSourcesView(store)
    qtbot.addWidget(view)

    # Assert initial state renders target summary
    assert "No target selected" in view.lbl_target_summary.text()
    assert not view.btn_apply.isEnabled()

    # Set targets
    target = SoundNodeTarget(bank_name="battle.bnk", sound_id=101)
    store.set_targets((target,))
    assert "1 target selected" in view.lbl_target_summary.text()

    # Set multiple targets
    target2 = SoundNodeTarget(bank_name="battle.bnk", sound_id=102)
    store.set_targets((target, target2))
    assert "2 targets selected" in view.lbl_target_summary.text()


def test_audio_sources_store_project_and_libraries(tmp_path: Path):
    proj_dir = tmp_path / "mod_proj"
    manifest = ProjectManifest(name="test_mod", game="attila")
    project = AudioProject(root_dir=proj_dir, manifest=manifest)

    lib_dir = tmp_path / "my_sounds"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "horn.wav").write_bytes(b"RIFF dummy wav data")

    store = AudioSourcesStore()
    store.set_project(project)
    assert len(store.state.libraries) == 0

    # Add library
    store.add_library(lib_dir, name="My Sounds")
    assert len(store.state.libraries) == 1
    lib_row = store.state.libraries[0]
    assert lib_row.name == "My Sounds"
    assert lib_row.file_count == 1
    assert lib_row.is_available is True

    # Library was selected and files scanned
    assert store.state.selected_library_id == lib_row.id
    assert len(store.state.files) == 1
    assert store.state.files[0].rel_path == "horn.wav"

    # Rename library
    store.rename_library(lib_row.id, "Epic Sounds")
    assert store.state.libraries[0].name == "Epic Sounds"

    # Remove library
    store.remove_library(lib_row.id)
    assert len(store.state.libraries) == 0
    assert store.state.selected_library_id is None
    assert len(store.state.files) == 0


def test_audio_sources_store_file_selection_and_preview(tmp_path: Path):
    store = AudioSourcesStore()
    preview_calls: list[Path] = []
    store.on_preview_file(preview_calls.append)

    test_wav = tmp_path / "voice.wav"
    test_wav.write_bytes(b"wav")

    # Single selection triggers preview intent
    store.select_files((test_wav,))
    assert len(preview_calls) == 1
    assert preview_calls[0] == test_wav

    # Multiple selection clears preview intent
    store.select_files((test_wav, tmp_path / "voice2.wav"))
    assert len(preview_calls) == 1


def test_audio_sources_store_apply_batch(tmp_path: Path):
    store = AudioSourcesStore()
    batch_calls = []
    store.on_batch_ready(batch_calls.append)

    target1 = SoundNodeTarget(bank_name="b.bnk", sound_id=1)
    target2 = SoundNodeTarget(bank_name="b.bnk", sound_id=2)
    store.set_targets((target1, target2))

    file1 = tmp_path / "f1.wav"
    file2 = tmp_path / "f2.wav"
    store.select_files((file1, file2))

    # Apply ALL mode
    store.apply(ApplyMode.ALL)
    assert len(batch_calls) == 1
    batch = batch_calls[0]
    assert len(batch.items) == 2
    assert batch.items[0].source == ExternalFileSource(file_path=file1)
    assert batch.items[1].source == ExternalFileSource(file_path=file1)

    # Apply DISTRIBUTE mode
    store.apply(ApplyMode.DISTRIBUTE)
    assert len(batch_calls) == 2
    batch2 = batch_calls[1]
    assert len(batch2.items) == 2
    assert batch2.items[0].source == ExternalFileSource(file_path=file1)
    assert batch2.items[1].source == ExternalFileSource(file_path=file2)


def test_audio_sources_store_apply_silence():
    store = AudioSourcesStore()
    batch_calls = []
    store.on_batch_ready(batch_calls.append)

    target = SoundNodeTarget(bank_name="b.bnk", sound_id=10)
    store.set_targets((target,))

    store.apply_silence()
    assert len(batch_calls) == 1
    batch = batch_calls[0]
    assert len(batch.items) == 1
    assert batch.items[0].target == target
    assert isinstance(batch.items[0].source, SilentStubSource)


def test_audio_sources_view_tab_switching(qtbot):
    store = AudioSourcesStore()
    view = AudioSourcesView(store)
    qtbot.addWidget(view)

    # Store updates view tabs
    store.set_active_tab(AudioSourcesTab.GAME_AUDIO)
    assert view.tabs.currentIndex() == AudioSourcesTab.GAME_AUDIO.value

    # View tab change updates store
    view.tabs.setCurrentIndex(AudioSourcesTab.ENHANCE.value)
    assert store.state.active_tab == AudioSourcesTab.ENHANCE


def test_audio_sources_view_button_interactions(qtbot, tmp_path: Path):
    store = AudioSourcesStore()
    view = AudioSourcesView(store)
    qtbot.addWidget(view)

    batch_calls = []
    store.on_batch_ready(batch_calls.append)

    target = SoundNodeTarget(bank_name="b.bnk", sound_id=1)
    file_path = tmp_path / "sound.wav"
    file_path.write_bytes(b"wav")

    store.set_targets((target,))
    store.select_files((file_path,))

    assert view.btn_apply.isEnabled()
    qtbot.mouseClick(view.btn_apply, Qt.MouseButton.LeftButton)
    assert len(batch_calls) == 1


def test_audio_sources_view_batch_outcome_display(qtbot):
    store = AudioSourcesStore()
    view = AudioSourcesView(store)
    qtbot.addWidget(view)

    from src.engine.ontology import BatchOutcome

    outcome = BatchOutcome(applied=3, rejections=(), touched_banks=("b.bnk",))
    store.receive_batch_outcome(outcome)

    assert "Applied 3 change(s)" in view.lbl_status.text()


def test_audio_sources_view_libraries_and_files_interaction(qtbot, tmp_path: Path):
    proj_dir = tmp_path / "mod_proj"
    manifest = ProjectManifest(name="test_mod", game="attila")
    project = AudioProject(root_dir=proj_dir, manifest=manifest)

    lib_dir = tmp_path / "sfx"
    lib_dir.mkdir(parents=True, exist_ok=True)
    wav1 = lib_dir / "bow_fire.wav"
    wav2 = lib_dir / "bow_reload.wav"
    wav1.write_bytes(b"wav1")
    wav2.write_bytes(b"wav2")

    store = AudioSourcesStore()
    view = AudioSourcesView(store)
    qtbot.addWidget(view)

    store.set_project(project)
    store.add_library(lib_dir, name="SFX")

    assert view.libraries_widget.table.rowCount() == 1
    assert view.files_widget.table.rowCount() == 2

    # Filter files
    view.files_widget.edit_filter.setText("fire")
    assert view.files_widget.table.rowCount() == 1

    # Select file row in view
    view.files_widget.table.selectRow(0)
    assert len(store.state.selected_file_paths) == 1
    assert store.state.selected_file_paths[0].name == "bow_fire.wav"


def test_audio_sources_game_audio_tab(qtbot):
    from src.models import AudioCatalogEntry

    store = AudioSourcesStore()
    view = AudioSourcesView(store)
    qtbot.addWidget(view)

    entries = (
        AudioCatalogEntry(
            wem_id=12345,
            source_bank="unit_vo.bnk",
            display_name="Charge Shout",
            category="Voiceover",
        ),
        AudioCatalogEntry(
            wem_id=67890,
            source_bank="weapons.bnk",
            display_name="Sword Swing",
            category="SFX",
        ),
    )
    view.tab_game_audio.set_entries(entries)
    assert view.tab_game_audio.table.rowCount() == 2

    # Search filter
    view.tab_game_audio.edit_search.setText("Sword")
    assert view.tab_game_audio.table.rowCount() == 1


def test_audio_sources_view_with_transport_store(qtbot):
    from src.ui.features.audio_transport import AudioTransportStore

    sources_store = AudioSourcesStore()
    transport_store = AudioTransportStore()
    view = AudioSourcesView(sources_store, transport_store=transport_store)
    qtbot.addWidget(view)

    assert hasattr(view, "transport_bar")
    assert view.transport_bar is not None
    assert view.transport_bar.compact is True


def test_audio_sources_large_library_virtualized_performance(qtbot, tmp_path: Path):
    """Verifies that FilesTableWidget handles 10,000+ files with zero lag, instant filtering, and fast selection."""
    import time

    store = AudioSourcesStore()
    view = AudioSourcesView(store)
    qtbot.addWidget(view)

    # Generate 10,000 synthetic entries
    entries = tuple(
        LibraryFileEntry(
            library_id="lib1",
            rel_path=f"folder_{i % 50}/audio_track_{i:05d}.wav",
            abs_path=tmp_path / f"audio_track_{i:05d}.wav",
            size_bytes=1024 * (i % 100 + 1),
        )
        for i in range(10000)
    )

    from src.ui.features.audio_sources.causation import FilesLoaded

    t0 = time.perf_counter()
    store.dispatch(FilesLoaded(files=entries))
    t1 = time.perf_counter()

    # Viewport rendering must be virtually instant (< 0.1s for 10,000 items)
    assert (t1 - t0) < 0.1
    assert view.files_widget.table.rowCount() == 10000
    assert "10000 file(s)" in view.files_widget.lbl_count.text()

    # Live search filtering across 10,000 items must be sub-second
    t0_filter = time.perf_counter()
    view.files_widget.edit_filter.setText("audio_track_0004")
    t1_filter = time.perf_counter()
    assert (t1_filter - t0_filter) < 0.1
    assert view.files_widget.table.rowCount() >= 1

    # Row selection in virtual table
    view.files_widget.table.selectRow(0)
    assert len(store.state.selected_file_paths) == 1


def test_enhance_tab_controls_and_interaction(qtbot):
    from src.ui.features.audio_sources.state import AudioEnhanceSettings
    from src.ui.features.audio_sources.widgets.enhance_tab import EnhanceTab

    tab = EnhanceTab()
    qtbot.addWidget(tab)

    # 1. Initial state: controls disabled, apply and mute disabled
    assert not tab.btn_apply.isEnabled()
    assert not tab.btn_mute.isEnabled()
    assert not tab.slider_gain.isEnabled()
    assert not tab.spin_gain.isEnabled()
    assert not tab.spin_normalize.isEnabled()
    assert not tab.spin_rms.isEnabled()

    # 2. Render with targets: mute becomes enabled, apply still disabled (no active mod)
    tab.render_enhance(has_targets=True, settings=AudioEnhanceSettings(), target_count=2)
    assert "2 targets selected" in tab.lbl_targets_info.text()
    assert tab.btn_mute.isEnabled()
    assert not tab.btn_apply.isEnabled()

    # 3. Toggle Gain: slider and spinbox enabled; with non-zero gain, apply enables
    tab.chk_gain.setChecked(True)
    assert tab.slider_gain.isEnabled()
    assert tab.spin_gain.isEnabled()

    # Slider -> Spinbox sync
    tab.slider_gain.setValue(35)  # 3.5 dB
    assert tab.spin_gain.value() == 3.5
    assert tab.btn_apply.isEnabled()

    # Spinbox -> Slider sync
    tab.spin_gain.setValue(-6.0)
    assert tab.slider_gain.value() == -60

    # Preset button click
    tab.btn_gain_p3.click()
    assert tab.spin_gain.value() == 3.0
    assert tab.slider_gain.value() == 30

    # 4. Toggle Normalization
    tab.chk_normalize.setChecked(True)
    assert tab.spin_normalize.isEnabled()
    tab.btn_norm_safe.click()
    assert tab.spin_normalize.value() == -3.0

    # 5. Toggle Loudness matching
    tab.chk_loudness.setChecked(True)
    assert tab.spin_rms.isEnabled()
    assert tab.spin_max_boost.isEnabled()

    # 6. Verify get_settings matches
    settings = tab.get_settings()
    assert settings.gain_enabled is True
    assert settings.gain_db == 3.0
    assert settings.normalize_enabled is True
    assert settings.target_peak_db == -3.0
    assert settings.match_loudness_enabled is True

    # 7. Apply button signal emission
    applied_settings = []
    tab.apply_requested.connect(lambda s: applied_settings.append(s))
    tab.btn_apply.click()
    assert len(applied_settings) == 1
    assert applied_settings[0].gain_db == 3.0

    # 8. Mute button signal emission
    mute_called = []
    tab.mute_requested.connect(lambda: mute_called.append(True))
    tab.btn_mute.click()
    assert len(mute_called) == 1


def test_audio_sources_view_enhance_tab_integration(qtbot):
    from src.engine.ontology import SoundNodeTarget
    from src.ui.features.audio_sources.state import AudioEnhanceSettings

    store = AudioSourcesStore()
    view = AudioSourcesView(store)
    qtbot.addWidget(view)

    # 1. Switch to Enhance tab (tab index 2)
    view.tabs.setCurrentIndex(2)
    assert store.state.active_tab == AudioSourcesTab.ENHANCE

    # 2. Select targets via store
    target1 = SoundNodeTarget(bank_name="test.bnk", sound_id=111)
    target2 = SoundNodeTarget(bank_name="test.bnk", sound_id=222)
    store.set_targets((target1, target2))
    assert "2 targets selected" in view.tab_enhance.lbl_targets_info.text()
    assert view.tab_enhance.btn_mute.isEnabled()
    # Initially no modifiers active, so tab Apply is disabled until a modifier is enabled
    assert view.tab_enhance.btn_apply.isEnabled() is False

    # Critical requirement: dock bottom "Apply to Selected" must be grayed out on Enhance tab
    assert view.btn_apply.isEnabled() is False
    assert view.btn_distribute.isEnabled() is False

    # Clicking dock bottom Apply button does nothing on Enhance tab
    batch_calls = []
    store.on_batch_ready(batch_calls.append)
    qtbot.mouseClick(view.btn_apply, Qt.MouseButton.LeftButton)
    assert len(batch_calls) == 0

    # 3. Enhance tab settings modified updates store state and enables tab Apply
    view.tab_enhance.chk_gain.setChecked(True)
    view.tab_enhance.spin_gain.setValue(4.5)
    assert store.state.enhance_settings.gain_enabled is True
    assert store.state.enhance_settings.gain_db == 4.5
    assert view.tab_enhance.btn_apply.isEnabled() is True

    # 4. Only Apply button inside Enhance tab applies enhancements
    enhance_payloads = []
    store.on_enhance_ready(lambda targets, settings: enhance_payloads.append((targets, settings)))
    view.tab_enhance.btn_apply.click()
    assert len(enhance_payloads) == 1
    targets, settings = enhance_payloads[0]
    assert len(targets) == 2
    assert settings.gain_db == 4.5


def test_audio_sources_view_bottom_apply_grayed_out_on_enhance_tab(qtbot, tmp_path: Path):
    """
    Verifies that the bottom 'Apply to Selected' button is dynamically grayed out
    whenever the Enhance tab is active, and only re-enables on Libraries/Game Audio tabs
    with valid sources selected.
    """
    from src.engine.ontology import SoundNodeTarget
    from src.models import AudioCatalogEntry

    store = AudioSourcesStore()
    view = AudioSourcesView(store)
    qtbot.addWidget(view)

    target = SoundNodeTarget(bank_name="test.bnk", sound_id=101)
    store.set_targets((target,))

    # Setup source audio file
    dummy_wav = tmp_path / "sound.wav"
    dummy_wav.write_bytes(b"RIFF dummy")
    store.select_files((dummy_wav,))

    # 1. On Libraries tab: has targets + has files -> bottom Apply is enabled
    view.tabs.setCurrentIndex(AudioSourcesTab.LIBRARIES.value)
    assert view.btn_apply.isEnabled() is True
    assert view.btn_distribute.isEnabled() is True

    # 2. Switch to Enhance tab -> bottom Apply & Distribute MUST be grayed out
    view.tabs.setCurrentIndex(AudioSourcesTab.ENHANCE.value)
    assert view.btn_apply.isEnabled() is False
    assert view.btn_distribute.isEnabled() is False
    assert view.tab_enhance.btn_mute.isEnabled() is True
    # When a modifier is enabled, Enhance tab's own Apply Enhancements button enables
    view.tab_enhance.chk_gain.setChecked(True)
    view.tab_enhance.spin_gain.setValue(2.0)
    assert view.tab_enhance.btn_apply.isEnabled() is True
    # Bottom Apply MUST remain grayed out even with modifier enabled
    assert view.btn_apply.isEnabled() is False
    assert view.btn_distribute.isEnabled() is False

    # 3. Switch to Game Audio tab with entry -> bottom Apply is enabled
    view.tabs.setCurrentIndex(AudioSourcesTab.GAME_AUDIO.value)
    cat_entry = AudioCatalogEntry(
        wem_id=500,
        source_bank="game.bnk",
        display_name="Sword Swing",
        category="Battle",
    )
    store.select_game_audio_entry(cat_entry)
    assert view.btn_apply.isEnabled() is True
    assert view.btn_distribute.isEnabled() is False

    # 4. Switch back to Enhance tab -> bottom Apply MUST be grayed out again
    view.tabs.setCurrentIndex(AudioSourcesTab.ENHANCE.value)
    assert view.btn_apply.isEnabled() is False
    assert view.btn_distribute.isEnabled() is False
    assert view.tab_enhance.btn_apply.isEnabled() is True

    # 5. Clear targets -> all buttons disabled
    store.set_targets(())
    assert view.btn_apply.isEnabled() is False
    assert view.btn_distribute.isEnabled() is False
    assert view.tab_enhance.btn_apply.isEnabled() is False
    assert view.tab_enhance.btn_preview.isEnabled() is False
    assert view.tab_enhance.btn_mute.isEnabled() is False


def test_enhance_tab_preview_button_and_transport_trigger(qtbot):
    """Verifies that the Preview Audio button in Enhance tab cues and plays enhanced audio in the bottom transport."""
    from src.engine.ontology import SoundNodeTarget
    from src.ui.features.audio_transport.store import AudioTransportStore

    store = AudioSourcesStore()
    transport_store = AudioTransportStore()
    view = AudioSourcesView(store, transport_store=transport_store)
    qtbot.addWidget(view)

    # 1. No target -> Preview button disabled
    assert view.tab_enhance.btn_preview.isEnabled() is False

    # 2. Select target -> Preview button enabled
    target = SoundNodeTarget(bank_name="test.bnk", sound_id=101)
    store.set_targets((target,))
    view.tabs.setCurrentIndex(AudioSourcesTab.ENHANCE.value)
    assert view.tab_enhance.btn_preview.isEnabled() is True

    # 3. Clicking Preview Audio dispatches enhance preview request
    preview_payloads = []
    store.on_preview_enhance(lambda tgt, s: preview_payloads.append((tgt, s)))

    view.tab_enhance.chk_gain.setChecked(True)
    view.tab_enhance.spin_gain.setValue(3.5)
    view.tab_enhance.btn_preview.click()

    assert len(preview_payloads) >= 1
    tgt, settings = preview_payloads[-1]
    assert tgt == target
    assert settings.gain_db == 3.5
