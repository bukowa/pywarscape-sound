"""
Unit tests for Audio Sources data-driven state transitions and batch planning.
Mock-free, deterministic causation proofs verifying ApplyMode and reconcile behaviors.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from src.engine.ontology import (
    BatchItem,
    BatchOutcome,
    ExternalFileSource,
    MusicTrackTarget,
    PlanRejection,
    SilentStubSource,
    SoundNodeTarget,
)
from src.ui.features.audio_sources.causation import (
    ApplyBatchIntent,
    ApplyEnhanceIntent,
    ApplyRequested,
    BatchOutcomeReceived,
    ClearPreviewIntent,
    EnhancePreviewRequested,
    EnhanceRequested,
    EnhanceSettingsChanged,
    FileSelectionChanged,
    FilesLoaded,
    FilterChanged,
    LibrariesLoaded,
    LibrarySelected,
    LoadGameAudioCatalogIntent,
    PlayEnhancePreviewIntent,
    PlayGameAudioPreviewIntent,
    PlayPreviewIntent,
    ScanLibraryIntent,
    SilenceRequested,
    TabChanged,
    TargetsChanged,
    build_batch,
    build_modifier_chain,
    reconcile,
)
from src.ui.features.audio_sources.state import (
    ApplyMode,
    AudioEnhanceSettings,
    AudioSourcesState,
    AudioSourcesTab,
    LibraryRow,
)
from src.workspace.sound_library import LibraryFileEntry

# -----------------------------------------------------------------------------
# 1. build_batch Tests
# -----------------------------------------------------------------------------


def test_distribute_count_mismatch_rejected():
    targets = (
        SoundNodeTarget(bank_name="b.bnk", sound_id=1),
        SoundNodeTarget(bank_name="b.bnk", sound_id=2),
    )
    sources = (ExternalFileSource(file_path=Path("s1.wav")),)
    batch, error = build_batch(targets, sources, mode=ApplyMode.DISTRIBUTE)
    assert batch is None
    assert error is not None
    assert "Count mismatch" in error


def test_distribute_matching_success():
    targets = (
        SoundNodeTarget(bank_name="b.bnk", sound_id=1),
        SoundNodeTarget(bank_name="b.bnk", sound_id=2),
    )
    sources = (
        ExternalFileSource(file_path=Path("s1.wav")),
        ExternalFileSource(file_path=Path("s2.wav")),
    )
    batch, error = build_batch(targets, sources, mode=ApplyMode.DISTRIBUTE)
    assert error is None
    assert batch is not None
    assert len(batch.items) == 2
    assert batch.items[0].target == targets[0]
    assert batch.items[0].source == sources[0]
    assert batch.items[1].target == targets[1]
    assert batch.items[1].source == sources[1]


def test_apply_all_mode_success():
    targets = (
        SoundNodeTarget(bank_name="b.bnk", sound_id=1),
        SoundNodeTarget(bank_name="b.bnk", sound_id=2),
    )
    sources = (ExternalFileSource(file_path=Path("s1.wav")),)
    batch, error = build_batch(targets, sources, mode=ApplyMode.ALL)
    assert error is None
    assert batch is not None
    assert len(batch.items) == 2
    assert batch.items[0].source == sources[0]
    assert batch.items[1].source == sources[0]


def test_apply_all_multiple_sources_uses_first():
    targets = (
        SoundNodeTarget(bank_name="b.bnk", sound_id=1),
        SoundNodeTarget(bank_name="b.bnk", sound_id=2),
    )
    sources = (
        ExternalFileSource(file_path=Path("s1.wav")),
        ExternalFileSource(file_path=Path("s2.wav")),
    )
    batch, error = build_batch(targets, sources, mode=ApplyMode.ALL)
    assert error is None
    assert batch is not None
    assert len(batch.items) == 2
    assert batch.items[0].source == sources[0]
    assert batch.items[1].source == sources[0]


def test_build_batch_empty_targets():
    targets = ()
    sources = (ExternalFileSource(file_path=Path("s1.wav")),)
    batch, error = build_batch(targets, sources, mode=ApplyMode.ALL)
    assert batch is None
    assert error is not None
    assert "target" in error.lower()


def test_build_batch_empty_sources():
    targets = (SoundNodeTarget(bank_name="b.bnk", sound_id=1),)
    sources = ()
    batch, error = build_batch(targets, sources, mode=ApplyMode.ALL)
    assert batch is None
    assert error is not None
    assert "source" in error.lower()


# -----------------------------------------------------------------------------
# 2. reconcile Transition Tests
# -----------------------------------------------------------------------------


def test_reconcile_tab_changed():
    state = AudioSourcesState()
    # Switching to Enhance tab produces no intents
    new_state, intents = reconcile(state, TabChanged(tab=AudioSourcesTab.ENHANCE))
    assert new_state.active_tab == AudioSourcesTab.ENHANCE
    assert intents == ()

    # Switching to Game Audio with empty entries requests load
    game_state, game_intents = reconcile(state, TabChanged(tab=AudioSourcesTab.GAME_AUDIO))
    assert game_state.active_tab == AudioSourcesTab.GAME_AUDIO
    assert len(game_intents) == 1
    assert isinstance(game_intents[0], LoadGameAudioCatalogIntent)


def test_reconcile_libraries_loaded():
    state = AudioSourcesState()
    rows = (
        LibraryRow(id="lib_1", name="Voices", path="audio/voices", file_count=5),
        LibraryRow(id="lib_2", name="SFX", path="audio/sfx", file_count=10),
    )
    new_state, intents = reconcile(state, LibrariesLoaded(libraries=rows))
    assert new_state.libraries == rows
    assert intents == ()


def test_reconcile_library_selected_emits_scan():
    state = AudioSourcesState(selected_library_id="old_lib")
    new_state, intents = reconcile(state, LibrarySelected(library_id="lib_1"))
    assert new_state.selected_library_id == "lib_1"
    assert new_state.files == ()
    assert new_state.selected_file_paths == ()
    assert intents == (ScanLibraryIntent(library_id="lib_1"),)


def test_reconcile_library_deselected():
    state = AudioSourcesState(selected_library_id="lib_1")
    new_state, intents = reconcile(state, LibrarySelected(library_id=None))
    assert new_state.selected_library_id is None
    assert intents == ()


def test_reconcile_files_loaded():
    state = AudioSourcesState()
    entries = (
        LibraryFileEntry(
            library_id="lib_1",
            rel_path="a.wav",
            abs_path=Path("C:/audio/a.wav"),
            size_bytes=1024,
        ),
    )
    new_state, intents = reconcile(state, FilesLoaded(files=entries))
    assert new_state.files == entries
    assert new_state.selected_file_paths == ()
    assert intents == ()


def test_reconcile_filter_changed():
    state = AudioSourcesState()
    new_state, intents = reconcile(state, FilterChanged(filter_text="archer"))
    assert new_state.filter_text == "archer"
    assert intents == ()


def test_reconcile_file_selection_changed_single_emits_preview():
    state = AudioSourcesState()
    target_path = Path("C:/audio/a.wav")
    new_state, intents = reconcile(state, FileSelectionChanged(selected_file_paths=(target_path,)))
    assert new_state.selected_file_paths == (target_path,)
    assert intents == (PlayPreviewIntent(file_path=target_path),)


def test_reconcile_file_selection_changed_multiple_no_preview():
    state = AudioSourcesState()
    paths = (Path("C:/audio/a.wav"), Path("C:/audio/b.wav"))
    new_state, intents = reconcile(state, FileSelectionChanged(selected_file_paths=paths))
    assert new_state.selected_file_paths == paths
    assert intents == ()


def test_reconcile_targets_changed():
    state = AudioSourcesState()
    targets = (SoundNodeTarget(bank_name="b.bnk", sound_id=123),)
    new_state, intents = reconcile(state, TargetsChanged(targets=targets))
    assert new_state.targets == targets
    assert intents == ()


def test_reconcile_apply_requested_success():
    target = SoundNodeTarget(bank_name="b.bnk", sound_id=1)
    file_path = Path("C:/audio/hero.wav")
    state = AudioSourcesState(
        targets=(target,),
        selected_file_paths=(file_path,),
    )
    new_state, intents = reconcile(state, ApplyRequested(mode=ApplyMode.ALL))
    assert len(intents) == 1
    intent = intents[0]
    assert isinstance(intent, ApplyBatchIntent)
    assert len(intent.batch.items) == 1
    assert intent.batch.items[0].target == target
    assert isinstance(intent.batch.items[0].source, ExternalFileSource)
    assert intent.batch.items[0].source.file_path == file_path


def test_reconcile_apply_requested_no_targets():
    state = AudioSourcesState(
        targets=(),
        selected_file_paths=(Path("a.wav"),),
    )
    new_state, intents = reconcile(state, ApplyRequested(mode=ApplyMode.ALL))
    assert intents == ()
    assert new_state.status_message is not None
    assert "No target" in new_state.status_message


def test_reconcile_apply_requested_no_sources():
    state = AudioSourcesState(
        targets=(SoundNodeTarget(bank_name="b.bnk", sound_id=1),),
        selected_file_paths=(),
    )
    new_state, intents = reconcile(state, ApplyRequested(mode=ApplyMode.ALL))
    assert intents == ()
    assert new_state.status_message is not None
    assert "No source" in new_state.status_message


def test_reconcile_apply_requested_distribute_mismatch():
    state = AudioSourcesState(
        targets=(
            SoundNodeTarget(bank_name="b.bnk", sound_id=1),
            SoundNodeTarget(bank_name="b.bnk", sound_id=2),
        ),
        selected_file_paths=(Path("a.wav"),),
    )
    new_state, intents = reconcile(state, ApplyRequested(mode=ApplyMode.DISTRIBUTE))
    assert intents == ()
    assert new_state.status_message is not None
    assert "Count mismatch" in new_state.status_message


def test_reconcile_silence_requested_success():
    target = SoundNodeTarget(bank_name="b.bnk", sound_id=99)
    state = AudioSourcesState(targets=(target,))
    new_state, intents = reconcile(state, SilenceRequested())
    assert len(intents) == 1
    intent = intents[0]
    assert isinstance(intent, ApplyBatchIntent)
    assert len(intent.batch.items) == 1
    assert intent.batch.items[0].target == target
    assert isinstance(intent.batch.items[0].source, SilentStubSource)


def test_reconcile_silence_requested_no_targets():
    state = AudioSourcesState(targets=())
    new_state, intents = reconcile(state, SilenceRequested())
    assert intents == ()
    assert new_state.status_message is not None
    assert "No target" in new_state.status_message


def test_reconcile_game_audio_flow():
    from src.engine.ontology import ExistingMediaReferenceSource
    from src.models import AudioCatalogEntry
    from src.ui.features.audio_sources.causation import (
        GameAudioEntriesLoaded,
        GameAudioEntrySelected,
        LoadGameAudioCatalogIntent,
    )

    # 1. Switching to Game Audio tab with empty catalog requests load
    state = AudioSourcesState(game_audio_entries=())
    new_state, intents = reconcile(state, TabChanged(tab=AudioSourcesTab.GAME_AUDIO))
    assert new_state.active_tab == AudioSourcesTab.GAME_AUDIO
    assert len(intents) == 1
    assert isinstance(intents[0], LoadGameAudioCatalogIntent)

    # 2. Entries loaded updates state
    entry = AudioCatalogEntry(
        wem_id=555,
        source_bank="unit.bnk",
        is_embedded=True,
        display_name="Voice_Attack",
    )
    new_state2, intents2 = reconcile(new_state, GameAudioEntriesLoaded(entries=(entry,)))
    assert new_state2.game_audio_entries == (entry,)
    assert intents2 == ()

    # 3. Entry selected
    new_state3, intents3 = reconcile(new_state2, GameAudioEntrySelected(entry=entry))
    assert new_state3.selected_game_audio_entry == entry
    assert len(intents3) == 1
    assert isinstance(intents3[0], PlayGameAudioPreviewIntent)
    assert intents3[0].entry == entry

    # 3b. Deselect entry clears preview track
    desel_state, desel_intents = reconcile(new_state3, GameAudioEntrySelected(entry=None))
    assert desel_state.selected_game_audio_entry is None
    assert desel_intents == (ClearPreviewIntent(),)

    # 4. Apply in Game Audio mode builds ExistingMediaReferenceSource batch
    target1 = SoundNodeTarget(bank_name="b.bnk", sound_id=101)
    target2 = SoundNodeTarget(bank_name="b.bnk", sound_id=102)
    state_with_targets = replace(new_state3, targets=(target1, target2))

    new_state4, intents4 = reconcile(state_with_targets, ApplyRequested(mode=ApplyMode.ALL))
    assert len(intents4) == 1
    assert isinstance(intents4[0], ApplyBatchIntent)
    batch = intents4[0].batch
    assert len(batch.items) == 2
    assert isinstance(batch.items[0].source, ExistingMediaReferenceSource)
    assert batch.items[0].source.wem_id == 555
    assert batch.items[0].source.source_bank == "unit.bnk"


def test_reconcile_unknown_event():
    class UnknownEvent:
        pass

    state = AudioSourcesState()
    with pytest.raises(AssertionError):
        reconcile(state, UnknownEvent())  # type: ignore


def test_build_modifier_chain_all_combinations():
    from src.compiler.audio_modifiers import (
        GainModifier,
        MatchReferenceLoudnessModifier,
        PeakNormalizeModifier,
    )

    # 1. Empty / all disabled
    chain_empty = build_modifier_chain(AudioEnhanceSettings())
    assert len(chain_empty.modifiers) == 0

    # 2. Gain with 0 dB ignored
    chain_zero_gain = build_modifier_chain(AudioEnhanceSettings(gain_enabled=True, gain_db=0.0))
    assert len(chain_zero_gain.modifiers) == 0

    # 3. Active Gain
    chain_gain = build_modifier_chain(AudioEnhanceSettings(gain_enabled=True, gain_db=3.5))
    assert len(chain_gain.modifiers) == 1
    assert isinstance(chain_gain.modifiers[0], GainModifier)
    assert chain_gain.modifiers[0].gain_db == 3.5

    # 4. Normalize
    chain_norm = build_modifier_chain(
        AudioEnhanceSettings(normalize_enabled=True, target_peak_db=-1.5)
    )
    assert len(chain_norm.modifiers) == 1
    assert isinstance(chain_norm.modifiers[0], PeakNormalizeModifier)
    assert chain_norm.modifiers[0].target_peak_db == -1.5

    # 5. Loudness matching
    chain_loud = build_modifier_chain(
        AudioEnhanceSettings(match_loudness_enabled=True, target_rms_db=-16.0, max_boost_db=9.0)
    )
    assert len(chain_loud.modifiers) == 1
    assert isinstance(chain_loud.modifiers[0], MatchReferenceLoudnessModifier)
    assert chain_loud.modifiers[0].target_rms_db == -16.0
    assert chain_loud.modifiers[0].max_boost_db == 9.0

    # 6. Combined chain preserves order: Gain -> Loudness -> Peak Normalize
    chain_all = build_modifier_chain(
        AudioEnhanceSettings(
            gain_enabled=True,
            gain_db=-2.0,
            normalize_enabled=True,
            target_peak_db=-0.5,
            match_loudness_enabled=True,
            target_rms_db=-14.0,
            max_boost_db=12.0,
        )
    )
    assert len(chain_all.modifiers) == 3
    assert isinstance(chain_all.modifiers[0], GainModifier)
    assert isinstance(chain_all.modifiers[1], MatchReferenceLoudnessModifier)
    assert isinstance(chain_all.modifiers[2], PeakNormalizeModifier)


def test_reconcile_enhance_events_and_intents():
    target = SoundNodeTarget(bank_name="sfx.bnk", sound_id=4001)
    state = AudioSourcesState(
        active_tab=AudioSourcesTab.ENHANCE,
        targets=(target,),
    )

    # 1. EnhanceSettingsChanged updates state and emits PlayEnhancePreviewIntent
    new_settings = AudioEnhanceSettings(gain_enabled=True, gain_db=4.0)
    s2, intents2 = reconcile(state, EnhanceSettingsChanged(settings=new_settings))
    assert s2.enhance_settings == new_settings
    assert intents2 == (PlayEnhancePreviewIntent(target=target, settings=new_settings),)

    # EnhancePreviewRequested also emits PlayEnhancePreviewIntent
    s_prev, intents_prev = reconcile(s2, EnhancePreviewRequested(settings=new_settings))
    assert intents_prev == (PlayEnhancePreviewIntent(target=target, settings=new_settings),)

    # 2. EnhanceRequested produces ApplyEnhanceIntent
    s3, intents3 = reconcile(s2, EnhanceRequested(settings=new_settings))
    assert len(intents3) == 1
    assert isinstance(intents3[0], ApplyEnhanceIntent)
    assert intents3[0].targets == (target,)
    assert intents3[0].settings == new_settings

    # 3. ApplyRequested on ENHANCE tab is ignored (dock Apply button is disabled on Enhance tab)
    s4, intents4 = reconcile(s2, ApplyRequested(mode=ApplyMode.ALL))
    assert intents4 == ()


def test_batch_applied_with_rejection_surfaces_exact_reason():
    """Verify BatchOutcomeReceived with PlanRejection produces status_message containing the exact rejection reason."""
    state = AudioSourcesState()
    target = MusicTrackTarget(bank_name="music.bnk", track_id=5001)
    source = ExternalFileSource(file_path=Path("track.wav"))
    item = BatchItem(target=target, source=source)
    rejection = PlanRejection(
        code="UNSUPPORTED_TARGET",
        reason="Planning not implemented for target type MusicTrackTarget",
    )
    outcome = BatchOutcome(
        applied=0,
        rejections=((item, rejection),),
        touched_banks=(),
    )

    next_state, intents = reconcile(state, BatchOutcomeReceived(outcome=outcome))
    assert intents == ()
    assert next_state.status_message is not None
    assert "Planning not implemented for target type MusicTrackTarget" in next_state.status_message
    assert next_state.status_message == (
        "Applied 0 change(s) (1 rejected: Planning not implemented for target type MusicTrackTarget)"
    )


def test_batch_applied_multiple_rejections_deduplicates_reasons():
    """Verify multiple rejections with identical reasons are deduplicated in status_message."""
    state = AudioSourcesState()
    target1 = MusicTrackTarget(bank_name="music.bnk", track_id=5001)
    target2 = MusicTrackTarget(bank_name="music.bnk", track_id=5002)
    source = ExternalFileSource(file_path=Path("track.wav"))
    item1 = BatchItem(target=target1, source=source)
    item2 = BatchItem(target=target2, source=source)
    rej1 = PlanRejection(code="UNSUPPORTED_TARGET", reason="Target not supported")
    rej2 = PlanRejection(code="UNSUPPORTED_TARGET", reason="Target not supported")
    outcome = BatchOutcome(applied=0, rejections=((item1, rej1), (item2, rej2)))

    next_state, _ = reconcile(state, BatchOutcomeReceived(outcome=outcome))
    assert next_state.status_message == "Applied 0 change(s) (2 rejected: Target not supported)"
