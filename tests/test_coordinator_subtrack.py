"""Tests for WorkspaceCoordinator sub-track and music track target resolution."""

from pathlib import Path

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk
from src.bnk.models import AkMusicTrackSource, CAkMusicSegment, CAkMusicTrack, CAkSound
from src.engine.ontology import (
    BatchItem,
    ExternalFileSource,
    MusicTrackTarget,
    MutationBatch,
    ReplacementScope,
    SoundNodeTarget,
)
from src.ui.features.audio_sources.store import AudioSourcesStore
from src.ui.features.audio_transport.store import AudioTransportStore
from src.ui.features.bank_viewer.store import BankViewerStore
from src.ui.shell.coordinator import WorkspaceCoordinator
from src.ui.shell.store import ShellStore
from tests.support.factories import make_synthetic_wav
from tests.test_e2e_wem_blast_radius import _create_synthetic_bank, _setup_test_project_and_session


def test_coordinator_resolves_music_track_and_subtrack_targets():
    """Verify selecting hirc:<track_id> and hirc:<track_id>:src:1 resolves to MusicTrackTarget with parent segment and source index."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    sources_store = AudioSourcesStore()

    coordinator = WorkspaceCoordinator(
        shell_store,
        bv_store,
        transport_store,
        audio_sources_store=sources_store,
    )

    track = CAkMusicTrack(id=2001, obj_type=11)
    segment = CAkMusicSegment(id=3001, obj_type=10, child_ids=[2001])
    bank = SoundBank(
        header=BkhdChunk(bank_id=999, version=112),
        hirc=HircChunk(objects=[segment, track]),
    )

    bv_store.load_soundbank_instance("music.bnk", bank)
    bv_store.select_bank("music.bnk")

    # 1. Select track root node: "hirc:<track_id>"
    bv_store.select_node("hirc:2001")
    assert len(sources_store.state.targets) == 1
    expected_root = MusicTrackTarget(
        bank_name="music.bnk",
        track_id=2001,
        parent_segment_id=3001,
        source_index=0,
    )
    assert sources_store.state.targets[0] == expected_root

    # 2. Select sub-track source node: "hirc:<track_id>:src:1"
    bv_store.select_node("hirc:2001:src:1")
    assert len(sources_store.state.targets) == 1
    expected_subtrack = MusicTrackTarget(
        bank_name="music.bnk",
        track_id=2001,
        parent_segment_id=3001,
        source_index=1,
    )
    assert sources_store.state.targets[0] == expected_subtrack

    # 3. Multi-selection of both root and sub-track
    bv_store.select_nodes(("hirc:2001", "hirc:2001:src:1"), primary_key="hirc:2001")
    assert len(sources_store.state.targets) == 2
    assert sources_store.state.targets == (expected_root, expected_subtrack)


def test_coordinator_subtrack_on_non_music_track_rejected():
    """Verify sub-track node key on a CAkSound object is rejected, while standard key emits SoundNodeTarget."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    sources_store = AudioSourcesStore()

    WorkspaceCoordinator(
        shell_store,
        bv_store,
        transport_store,
        audio_sources_store=sources_store,
    )

    sound = CAkSound(id=1001, obj_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=888, version=112),
        hirc=HircChunk(objects=[sound]),
    )

    bv_store.load_soundbank_instance("sfx.bnk", bank)
    bv_store.select_bank("sfx.bnk")

    # Sub-track syntax on CAkSound should NOT resolve as MusicTrackTarget
    bv_store.select_node("hirc:1001:src:1")
    assert sources_store.state.targets == ()

    # Standard hirc key resolves as SoundNodeTarget
    bv_store.select_node("hirc:1001")
    assert len(sources_store.state.targets) == 1
    assert sources_store.state.targets[0] == SoundNodeTarget(bank_name="sfx.bnk", sound_id=1001)


def test_coordinator_music_track_without_parent_segment():
    """Verify selecting a CAkMusicTrack with no parent CAkMusicSegment resolves parent_segment_id as None."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    sources_store = AudioSourcesStore()

    WorkspaceCoordinator(
        shell_store,
        bv_store,
        transport_store,
        audio_sources_store=sources_store,
    )

    track = CAkMusicTrack(id=4001, obj_type=11)
    bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        hirc=HircChunk(objects=[track]),
    )

    bv_store.load_soundbank_instance("orphan.bnk", bank)
    bv_store.select_bank("orphan.bnk")

    bv_store.select_node("hirc:4001:src:2")
    assert len(sources_store.state.targets) == 1
    assert sources_store.state.targets[0] == MusicTrackTarget(
        bank_name="orphan.bnk",
        track_id=4001,
        parent_segment_id=None,
        source_index=2,
    )


def test_bank_viewer_store_mute_nodes_music_track_and_subtrack(tmp_path: Path):
    """Verify BankViewerStore.mute_nodes mutes CAkMusicTrack root and sub-track nodes via silent stubs."""
    track = CAkMusicTrack(
        id=2001,
        obj_type=11,
        sources=[
            AkMusicTrackSource(plugin_id=0x00040001, stream_type=2, source_id=101),
            AkMusicTrackSource(plugin_id=0x00040001, stream_type=2, source_id=102),
        ],
    )
    bank = SoundBank(
        header=BkhdChunk(bank_id=555, version=112),
        hirc=HircChunk(objects=[track]),
    )
    project, _ = _setup_test_project_and_session(tmp_path, {"music.bnk": bank})
    bv_store = BankViewerStore(project=project)
    bv_store.select_bank("music.bnk")

    # 1. Mute sub-track: "hirc:2001:src:1"
    res = bv_store.mute_nodes(["hirc:2001:src:1"])
    assert res is True
    entry = bv_store.session.get_loaded_entry("music.bnk")
    assert entry is not None
    loaded_bank = entry[0]
    t = next(o for o in loaded_bank.hirc.objects if o.id == 2001)
    assert t.sources[1].source_id == 1  # muted to stub
    assert t.sources[0].source_id == 101  # untouched

    # 2. Mute root track: "hirc:2001"
    res2 = bv_store.mute_nodes(["hirc:2001"])
    assert res2 is True
    entry2 = bv_store.session.get_loaded_entry("music.bnk")
    assert entry2 is not None
    t2 = next(o for o in entry2[0].hirc.objects if o.id == 2001)
    assert t2.sources[0].source_id == 1  # muted to stub


def test_coordinator_confirm_replacement_scope_isolate(tmp_path: Path):
    """Verify WorkspaceCoordinator with confirm_replacement_scope honours ReplacementScope.ISOLATE."""
    bank = _create_synthetic_bank(bank_id=1001, sounds=[(101, 50001, 2), (102, 50001, 2)])
    project, _ = _setup_test_project_and_session(tmp_path, {"shared.bnk": bank})

    shell_store = ShellStore()
    bv_store = BankViewerStore(project=project)
    bv_store.session.resolve_and_parse_bank("shared.bnk")
    transport_store = AudioTransportStore()
    sources_store = AudioSourcesStore()

    confirmed_targets: list[SoundNodeTarget] = []

    def confirm_scope(target: object) -> tuple[bool, ReplacementScope]:
        if isinstance(target, SoundNodeTarget):
            confirmed_targets.append(target)
        return (True, ReplacementScope.ISOLATE)

    coordinator = WorkspaceCoordinator(
        shell_store,
        bv_store,
        transport_store,
        audio_sources_store=sources_store,
        confirm_replacement_scope=confirm_scope,
    )

    new_wav = make_synthetic_wav(tmp_path / "custom.wav")
    source = ExternalFileSource(file_path=new_wav)
    target = SoundNodeTarget(bank_name="shared.bnk", sound_id=101)
    batch = MutationBatch(
        description="Isolate replace 101",
        items=(BatchItem(target=target, source=source),),
    )

    coordinator._handle_audio_sources_batch(batch)

    assert len(confirmed_targets) == 1
    assert confirmed_targets[0] == target

    entry = bv_store.session.get_loaded_entry("shared.bnk")
    assert entry is not None
    loaded_bank = entry[0]
    s101 = next(o for o in loaded_bank.hirc.objects if o.id == 101)
    s102 = next(o for o in loaded_bank.hirc.objects if o.id == 102)

    # 101 isolated to new forked WEM ID, 102 retains shared WEM ID
    assert s101.file_id != 50001
    assert s102.file_id == 50001


def test_coordinator_confirm_replacement_scope_overwrite(tmp_path: Path):
    """Verify WorkspaceCoordinator with confirm_replacement_scope honours ReplacementScope.OVERWRITE."""
    bank = _create_synthetic_bank(bank_id=1001, sounds=[(101, 50001, 2), (102, 50001, 2)])
    project, _ = _setup_test_project_and_session(tmp_path, {"shared.bnk": bank})

    shell_store = ShellStore()
    bv_store = BankViewerStore(project=project)
    bv_store.session.resolve_and_parse_bank("shared.bnk")
    transport_store = AudioTransportStore()
    sources_store = AudioSourcesStore()

    confirmed_targets: list[SoundNodeTarget] = []

    def confirm_scope(target: object) -> tuple[bool, ReplacementScope]:
        if isinstance(target, SoundNodeTarget):
            confirmed_targets.append(target)
        return (True, ReplacementScope.OVERWRITE)

    coordinator = WorkspaceCoordinator(
        shell_store,
        bv_store,
        transport_store,
        audio_sources_store=sources_store,
        confirm_replacement_scope=confirm_scope,
    )

    new_wav = make_synthetic_wav(tmp_path / "custom_overwrite.wav")
    source = ExternalFileSource(file_path=new_wav)
    target = SoundNodeTarget(bank_name="shared.bnk", sound_id=101)
    batch = MutationBatch(
        description="Overwrite replace 101",
        items=(BatchItem(target=target, source=source),),
    )

    coordinator._handle_audio_sources_batch(batch)

    assert len(confirmed_targets) == 1
    entry = bv_store.session.get_loaded_entry("shared.bnk")
    assert entry is not None
    loaded_bank = entry[0]
    s101 = next(o for o in loaded_bank.hirc.objects if o.id == 101)
    s102 = next(o for o in loaded_bank.hirc.objects if o.id == 102)

    # Both retain 50001, which is now overwritten in project
    assert s101.file_id == 50001
    assert s102.file_id == 50001
    assert (project.audio_dir / "50001.wem").exists()


def test_coordinator_confirm_replacement_scope_cancel(tmp_path: Path):
    """Verify WorkspaceCoordinator with confirm_replacement_scope aborts when proceed is False."""
    bank = _create_synthetic_bank(bank_id=1001, sounds=[(101, 50001, 2), (102, 50001, 2)])
    project, _ = _setup_test_project_and_session(tmp_path, {"shared.bnk": bank})

    shell_store = ShellStore()
    bv_store = BankViewerStore(project=project)
    bv_store.session.resolve_and_parse_bank("shared.bnk")
    transport_store = AudioTransportStore()
    sources_store = AudioSourcesStore()

    confirmed_targets: list[SoundNodeTarget] = []

    def confirm_scope(target: object) -> tuple[bool, ReplacementScope]:
        if isinstance(target, SoundNodeTarget):
            confirmed_targets.append(target)
        return (False, ReplacementScope.OVERWRITE)

    coordinator = WorkspaceCoordinator(
        shell_store,
        bv_store,
        transport_store,
        audio_sources_store=sources_store,
        confirm_replacement_scope=confirm_scope,
    )

    new_wav = make_synthetic_wav(tmp_path / "custom_cancel.wav")
    source = ExternalFileSource(file_path=new_wav)
    target = SoundNodeTarget(bank_name="shared.bnk", sound_id=101)
    batch = MutationBatch(
        description="Cancelled replace 101",
        items=(BatchItem(target=target, source=source),),
    )

    coordinator._handle_audio_sources_batch(batch)

    assert len(confirmed_targets) == 1
    # Bank was untouched and nothing was modified
    assert bv_store.session.can_undo_mutation is False
    entry = bv_store.session.get_loaded_entry("shared.bnk")
    assert entry is not None
    loaded_bank = entry[0]
    s101 = next(o for o in loaded_bank.hirc.objects if o.id == 101)
    assert s101.file_id == 50001
