"""
End-to-End Opaque-Box Test Suite for Cross-Bank WEM Reference Indexing,
Hierarchy Navigation, and Blast Radius Audio Replacement (Features F1 through F7).

Test Design:
- Tier 1: Feature Coverage (Category-Partition Happy Paths for F1-F7)
- Tier 2: Boundary Value Analysis & Corner Cases (0 refs, 1 ref, 2 refs, 50 refs, extreme IDs, stream types)
- Tier 3: Cross-Feature Combinations (Pairwise: Single/Multi-Bank x Embedded/Streamed x Isolate/Overwrite x Undo/Redo)
- Tier 4: Real-World Workflows (Unit battle shout isolation, global sword impact overwrite)

Progressive Testability:
Each tier checks feature readiness from milestones M1, M2, and M3. As milestones complete,
tests execute their full behavioral assertions against active Layer 1-4 code.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.bnk.bank import BkhdChunk, DataChunk, DidxChunk, DidxEntry, HircChunk, SoundBank
from src.bnk.models import (
    AkMusicTrackSource,
    AkTrackSrcInfo,
    CAkMusicTrack,
    CAkSound,
    HircObject,
)
from src.engine.graph import BankGraphIndex
from src.engine.ontology import (
    BatchItem,
    ExternalFileSource,
    MutationBatch,
    SoundNodeTarget,
    StageMasterAudioIntent,
    UpdateSoundNodeIntent,
)
from src.engine.planner import plan_audio_replacement
from src.engine.session import WorkspaceSession
from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.project import AudioProject
from src.workspace.storage import ProjectStorage
from tests.support.factories import make_synthetic_wav

# -----------------------------------------------------------------------------
# Progressive Milestone Feature Gates
# -----------------------------------------------------------------------------

# M1 Gate: Engine Core (ReplacementScope, WemReference, allocate_unique_wem_id, session queries)
try:
    from src.engine.ontology import ReplacementScope, WemReference
    from src.engine.planner import allocate_unique_wem_id

    HAS_M1 = (
        hasattr(BankGraphIndex, "wem_references")
        or hasattr(BankGraphIndex, "get_wem_referencing_hirc_ids")
    ) and hasattr(WorkspaceSession, "get_cross_bank_wem_references")
except (ImportError, AttributeError):
    HAS_M1 = False
    ReplacementScope = None  # type: ignore[assignment, misc]
    WemReference = None  # type: ignore[assignment, misc]
    allocate_unique_wem_id = None  # type: ignore[assignment]

# M2 Gate: BankViewer Inspectors & Navigation
try:
    from src.ui.features.bank_viewer.state import (
        JumpToNodeRequested,
        NodeInspectorDetails,
        NodeReferenceSummary,
    )

    _sample_summary = NodeReferenceSummary(
        key="hirc:1", label="Test", id_str="1", type_str="Sound", bank_name="b.bnk"
    )
    _sample_jump = JumpToNodeRequested(node_key="hirc:1", bank_name="b.bnk")
    _sample_details = NodeInspectorDetails(node_key="hirc:1", name="Test", object_type="Sound")
    HAS_M2 = (
        hasattr(_sample_summary, "bank_name")
        and hasattr(_sample_jump, "bank_name")
        and hasattr(_sample_details, "audio_references")
    )
except (ImportError, TypeError, AttributeError):
    HAS_M2 = False

# M3 Gate: Blast Radius Dialog Feature Slice & Branching Controller Hook
try:
    import src.ui.features.blast_radius.causation as br_causation
    import src.ui.features.blast_radius.state as br_state
    import src.ui.features.blast_radius.store as br_store
    import src.ui.features.blast_radius.view as br_view

    # Resolve check_replacement_branch from blast_radius package or sound_view
    check_replacement_branch = getattr(br_store, "check_replacement_branch", None)
    if check_replacement_branch is None:
        try:
            import src.ui.features.blast_radius as br_pkg

            check_replacement_branch = getattr(br_pkg, "check_replacement_branch", None)
        except ImportError:
            pass
    if check_replacement_branch is None:
        try:
            from src.ui.features.bank_viewer.views.sound_view import (
                check_replacement_branch,
            )
        except ImportError:
            pass

    HAS_M3 = (
        hasattr(br_state, "BlastRadiusState")
        and hasattr(br_store, "BlastRadiusStore")
        and hasattr(br_view, "BlastRadiusDialog")
        and check_replacement_branch is not None
    )
except (ImportError, AttributeError):
    HAS_M3 = False
    check_replacement_branch = None  # type: ignore[assignment]


# -----------------------------------------------------------------------------
# Test Fixtures & Synthetic Audio Generation
# -----------------------------------------------------------------------------


def _create_synthetic_bank(
    bank_id: int,
    sounds: list[tuple[int, int, int]],  # (sound_id, wem_id, stream_type)
    music_tracks: list[tuple[int, list[tuple[int, int]]]]
    | None = None,  # (track_id, [(wem_id, stream_type)])
    embedded_wav_bytes: bytes | None = None,
) -> SoundBank:
    """
    Builds a valid SoundBank AST.
    stream_type: 0 = Embedded (in DATA chunk via DIDX), 2 = Streamed loose WEM.
    """
    hirc_objs: list[HircObject] = []
    didx_entries: list[DidxEntry] = []
    data_buffer = bytearray()

    dummy_payload = embedded_wav_bytes or b"RIFF....WAVEfmt \x10\x00\x00\x00data\x00\x00\x00\x00"

    for sound_id, wem_id, st_type in sounds:
        if st_type == 0:
            offset = len(data_buffer)
            data_buffer.extend(dummy_payload)
            didx_entries.append(DidxEntry(file_id=wem_id, offset=offset, size=len(dummy_payload)))
            hirc_objs.append(
                CAkSound(
                    id=sound_id,
                    source_id=wem_id,
                    file_id=wem_id,
                    stream_type=0,
                    file_offset=offset,
                    in_memory_media_size=len(dummy_payload),
                )
            )
        else:
            hirc_objs.append(
                CAkSound(
                    id=sound_id,
                    source_id=wem_id,
                    file_id=wem_id,
                    stream_type=2,
                    file_offset=0,
                    in_memory_media_size=0,
                )
            )

    if music_tracks:
        for track_id, sources in music_tracks:
            track_sources = [
                AkMusicTrackSource(
                    plugin_id=0x00040001,
                    stream_type=st,
                    source_id=wid,
                    file_id=wid,
                    file_offset=0 if st != 2 else None,
                    in_memory_media_size=len(dummy_payload) if st != 2 else 0,
                )
                for wid, st in sources
            ]
            playlist = [
                AkTrackSrcInfo(track_id=track_id, source_id=wid, src_duration=1000.0)
                for wid, _ in sources
            ]
            hirc_objs.append(
                CAkMusicTrack(
                    id=track_id,
                    sources=track_sources,
                    playlist=playlist,
                )
            )

    didx_chunk = DidxChunk(entries=didx_entries) if didx_entries else DidxChunk(entries=[])
    data_chunk = DataChunk(data=bytes(data_buffer)) if data_buffer else DataChunk(data=b"")

    return SoundBank(
        header=BkhdChunk(bank_id=bank_id, version=112),
        didx=didx_chunk,
        data=data_chunk,
        hirc=HircChunk(objects=hirc_objs),
    )


def _setup_test_project_and_session(
    tmp_path: Path,
    banks: dict[str, SoundBank],
    staged_wems: dict[int, bytes] | None = None,
) -> tuple[AudioProject, WorkspaceSession]:
    """Sets up an AudioProject workspace, GameCache, and initialized WorkspaceSession."""
    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "event_data.dat").write_bytes(b"\x00" * 32)

    for b_name, bank in banks.items():
        (cache_dir / b_name).write_bytes(bank.to_bytes())

    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)
    assert cache.is_valid()

    proj_dir = tmp_path / "TestBlastRadiusMod"
    project = ProjectStorage.create_project(
        proj_dir, name="TestBlastRadiusMod", game=GameType.ATTILA
    )
    project.cache = cache

    if staged_wems:
        for wid, w_bytes in staged_wems.items():
            wem_path = project.audio_dir / f"{wid}.wem"
            wem_path.write_bytes(w_bytes)
            if wid not in project.manifest.staged_wems:
                project.manifest.staged_wems.append(wid)
        ProjectStorage.save_project(project)

    session = WorkspaceSession(project=project)
    for b_name in banks:
        session.resolve_and_parse_bank(b_name)

    return project, session


# =============================================================================
# TIER 1: FEATURE COVERAGE (Category-Partition Happy Paths for F1-F7)
# =============================================================================


@pytest.mark.skipif(not HAS_M1, reason="Pending M1 (Engine Core): WemReference indexing")
def test_tier1_f1_single_bank_wem_indexing(tmp_path: Path):
    """
    Feature F1: Single-Bank WEM Reference Indexing.
    Verifies that two CAkSound nodes sharing WEM ID 50001 are indexed by BankGraphIndex
    and returned by WorkspaceSession cross-bank queries.
    """
    bank = _create_synthetic_bank(
        bank_id=1001,
        sounds=[(101, 50001, 0), (102, 50001, 0)],
    )
    project, session = _setup_test_project_and_session(tmp_path, {"battle_rome.bnk": bank})

    entry = session.get_loaded_entry("battle_rome.bnk")
    assert entry is not None
    _, graph_index, _ = entry

    # Verify BankGraphIndex inverted map
    ref_hirc_ids = getattr(graph_index, "wem_references", {}).get(50001)
    if ref_hirc_ids is None and hasattr(graph_index, "get_wem_referencing_hirc_ids"):
        ref_hirc_ids = graph_index.get_wem_referencing_hirc_ids(50001)
    assert ref_hirc_ids is not None
    assert set(ref_hirc_ids) == {101, 102}

    # Verify WorkspaceSession cross-bank queries
    refs = session.get_cross_bank_wem_references(50001)
    assert len(refs) == 2
    assert session.get_wem_reference_count(50001) == 2

    node_ids = {r.node_id for r in refs}
    assert node_ids == {101, 102}
    for r in refs:
        assert r.bank_name.lower() == "battle_rome.bnk"
        assert r.node_type == "Sound"
        assert r.is_embedded is True
        assert r.stream_type == 0


@pytest.mark.skipif(not HAS_M1, reason="Pending M1 (Engine Core): Cross-bank WEM indexing")
def test_tier1_f1_cross_bank_wem_indexing(tmp_path: Path):
    """
    Feature F1: Cross-Bank WEM Reference Indexing.
    Verifies that a WEM shared across two distinct SoundBanks is discovered across banks.
    """
    bank_a = _create_synthetic_bank(bank_id=1001, sounds=[(101, 50001, 0)])
    bank_b = _create_synthetic_bank(bank_id=1002, sounds=[(201, 50001, 2)])

    project, session = _setup_test_project_and_session(
        tmp_path,
        {"units.bnk": bank_a, "voices.bnk": bank_b},
    )

    refs = session.get_cross_bank_wem_references(50001)
    assert len(refs) == 2
    assert session.get_wem_reference_count(50001) == 2

    banks_found = {r.bank_name.lower() for r in refs}
    assert banks_found == {"units.bnk", "voices.bnk"}

    ref_map = {r.bank_name.lower(): r for r in refs}
    assert ref_map["units.bnk"].node_id == 101
    assert ref_map["units.bnk"].is_embedded is True
    assert ref_map["voices.bnk"].node_id == 201
    assert ref_map["voices.bnk"].is_embedded is False


@pytest.mark.skipif(not HAS_M1, reason="Pending M1 (Engine Core): allocate_unique_wem_id")
def test_tier1_f2_unique_wem_allocator():
    """
    Feature F2: Unique WEM ID Allocation.
    Verifies that allocate_unique_wem_id generates non-colliding positive 32-bit integers (> 100,000).
    """
    existing_ids = {50001, 50002, 100001, 100002, 100003}

    new_id = allocate_unique_wem_id(existing_ids)
    assert isinstance(new_id, int)
    assert new_id > 100000
    assert new_id <= 0x7FFFFFFF
    assert new_id not in existing_ids

    # Multiple allocations must not collide
    allocated = set(existing_ids)
    for _ in range(20):
        uid = allocate_unique_wem_id(allocated)
        assert uid not in allocated
        assert uid > 100000
        allocated.add(uid)


@pytest.mark.skipif(
    not HAS_M1, reason="Pending M1 (Engine Core): ReplacementScope planner overwrite"
)
def test_tier1_f2_planner_scope_overwrite(tmp_path: Path):
    """
    Feature F2: Audio Replacement Planning with ReplacementScope.OVERWRITE.
    Verifies that overwrite preserves the target's existing WEM ID.
    """
    sound = CAkSound(id=101, source_id=50001, file_id=50001, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=999, version=112),
        didx=DidxChunk(entries=[]),
        data=DataChunk(data=b""),
        hirc=HircChunk(objects=[sound]),
    )
    dummy_wav = make_synthetic_wav(tmp_path / "custom.wav")
    source = ExternalFileSource(file_path=dummy_wav)
    target = SoundNodeTarget(bank_name="test.bnk", sound_id=101)

    plan = plan_audio_replacement(
        bank=bank,
        target=target,
        source=source,
        scope=ReplacementScope.OVERWRITE,
        existing_wems={50001},
    )
    assert not isinstance(plan, Exception)

    # Must preserve 50001
    stage_intents = [e for e in plan.effects if isinstance(e, StageMasterAudioIntent)]
    assert len(stage_intents) == 1
    assert stage_intents[0].wem_id == 50001

    update_intents = [e for e in plan.effects if isinstance(e, UpdateSoundNodeIntent)]
    assert len(update_intents) == 1
    assert update_intents[0].new_source_id == 50001
    assert update_intents[0].new_file_id == 50001


@pytest.mark.skipif(not HAS_M1, reason="Pending M1 (Engine Core): ReplacementScope planner isolate")
def test_tier1_f2_planner_scope_isolate(tmp_path: Path):
    """
    Feature F2: Audio Replacement Planning with ReplacementScope.ISOLATE.
    Verifies that isolate generates a new distinct unique WEM ID for the target node.
    """
    sound = CAkSound(id=101, source_id=50001, file_id=50001, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=999, version=112),
        didx=DidxChunk(entries=[]),
        data=DataChunk(data=b""),
        hirc=HircChunk(objects=[sound]),
    )
    dummy_wav = make_synthetic_wav(tmp_path / "custom.wav")
    source = ExternalFileSource(file_path=dummy_wav)
    target = SoundNodeTarget(bank_name="test.bnk", sound_id=101)

    plan = plan_audio_replacement(
        bank=bank,
        target=target,
        source=source,
        scope=ReplacementScope.ISOLATE,
        existing_wems={50001},
    )
    assert not isinstance(plan, Exception)

    # Must allocate a NEW distinct WEM ID
    stage_intents = [e for e in plan.effects if isinstance(e, StageMasterAudioIntent)]
    assert len(stage_intents) == 1
    new_wem_id = stage_intents[0].wem_id
    assert new_wem_id != 50001
    assert new_wem_id > 100000

    update_intents = [e for e in plan.effects if isinstance(e, UpdateSoundNodeIntent)]
    assert len(update_intents) == 1
    assert update_intents[0].new_source_id == new_wem_id
    assert update_intents[0].new_file_id == new_wem_id


@pytest.mark.skipif(
    not HAS_M1, reason="Pending M1 (Engine Core): Atomic undo for streamed overwrite"
)
def test_tier1_f3_session_atomic_undo_redo_overwrite_streamed(tmp_path: Path):
    """
    Feature F3: Atomic Undo/Redo for Streamed WEM Overwrite.
    Verifies that overwriting an existing loose streamed WEM snapshots its prior bytes
    and restores them on undo.
    """
    orig_wem_bytes = b"ORIGINAL_STREAMED_WEM_BYTES_12345"
    bank = _create_synthetic_bank(bank_id=1001, sounds=[(101, 50001, 2)])

    project, session = _setup_test_project_and_session(
        tmp_path,
        {"battle.bnk": bank},
        staged_wems={50001: orig_wem_bytes},
    )

    wem_file = project.audio_dir / "50001.wem"
    assert wem_file.read_bytes() == orig_wem_bytes

    new_wav = make_synthetic_wav(tmp_path / "new_audio.wav")
    source = ExternalFileSource(file_path=new_wav)

    # Mutate with OVERWRITE scope
    batch = MutationBatch(
        description="Overwrite shared streamed audio",
        items=(
            BatchItem(
                target=SoundNodeTarget(bank_name="battle.bnk", sound_id=101),
                source=source,
                scope=ReplacementScope.OVERWRITE,
            ),
        ),
    )
    outcome = session.apply_batch(batch)
    assert outcome.applied == 1

    # Audio file on disk must be updated
    new_disk_bytes = wem_file.read_bytes()
    assert new_disk_bytes != orig_wem_bytes

    # Undo must restore exact prior loose bytes
    assert session.can_undo_mutation
    session.undo_mutation()
    assert wem_file.read_bytes() == orig_wem_bytes

    # Redo must re-apply the new bytes
    assert session.can_redo_mutation
    session.redo_mutation()
    assert wem_file.read_bytes() == new_disk_bytes


@pytest.mark.skipif(not HAS_M1, reason="Pending M1 (Engine Core): Atomic undo for isolate")
def test_tier1_f3_session_atomic_undo_redo_isolate(tmp_path: Path):
    """
    Feature F3: Atomic Undo/Redo for Audio Isolation / Fork.
    Verifies that isolate stages a new loose WEM and points the node to it; undo deletes
    the staged file and reverts AST, and redo restores it.
    """
    bank = _create_synthetic_bank(bank_id=1001, sounds=[(101, 50001, 0), (102, 50001, 0)])
    project, session = _setup_test_project_and_session(tmp_path, {"battle.bnk": bank})

    new_wav = make_synthetic_wav(tmp_path / "custom_shout.wav")
    source = ExternalFileSource(file_path=new_wav)

    batch = MutationBatch(
        description="Isolate Sound 101",
        items=(
            BatchItem(
                target=SoundNodeTarget(bank_name="battle.bnk", sound_id=101),
                source=source,
                scope=ReplacementScope.ISOLATE,
            ),
        ),
    )
    outcome = session.apply_batch(batch)
    assert outcome.applied == 1

    # Sound 101 must be updated to new WEM ID with stream_type=2
    bank_entry = session.get_loaded_entry("battle.bnk")
    assert bank_entry is not None
    s101 = next(obj for obj in bank_entry[0].hirc.objects if obj.id == 101)
    s102 = next(obj for obj in bank_entry[0].hirc.objects if obj.id == 102)

    forked_wid = s101.file_id
    assert forked_wid != 50001
    assert s101.stream_type == 2

    # Sibling node 102 remains unchanged
    assert s102.file_id == 50001
    assert s102.stream_type == 0

    forked_file = project.audio_dir / f"{forked_wid}.wem"
    assert forked_file.is_file()
    assert forked_wid in project.manifest.staged_wems

    # Undo: removes forked file and reverts AST
    session.undo_mutation()
    assert not forked_file.is_file()
    assert forked_wid not in project.manifest.staged_wems

    reverted_bank = session.get_loaded_entry("battle.bnk")[0]
    rs101 = next(obj for obj in reverted_bank.hirc.objects if obj.id == 101)
    assert rs101.file_id == 50001
    assert rs101.stream_type == 0

    # Redo: restores forked file and AST
    session.redo_mutation()
    assert forked_file.is_file()
    assert forked_wid in project.manifest.staged_wems


@pytest.mark.skipif(not HAS_M2, reason="Pending M2 (BankViewer): Referencing nodes display")
def test_tier1_f4_inspector_referencing_nodes_display(qapp, qtbot, tmp_path: Path):
    """
    Feature F4: BankViewer Referencing Nodes Display.
    Verifies that SoundInspectorView and MediaInspectorView populate referencing nodes
    with bank name, node ID, and type.
    """
    from src.ui.features.bank_viewer.views.media_view import MediaInspectorView
    from src.ui.features.bank_viewer.views.sound_view import SoundInspectorView

    ref_item_1 = NodeReferenceSummary(
        key="hirc:101",
        label="Roman_Legionary",
        id_str="101",
        type_str="Sound",
        bank_name="battle_rome.bnk",
    )
    ref_item_2 = NodeReferenceSummary(
        key="hirc:201",
        label="Praetorian_Guard",
        id_str="201",
        type_str="Sound",
        bank_name="battle_guard.bnk",
    )

    details = NodeInspectorDetails(
        node_key="hirc:101",
        name="Roman_Legionary",
        object_type="Sound",
        audio_references=(ref_item_1, ref_item_2),
        audio_reference_count=2,
        is_streamed=True,
    )

    sound_view = SoundInspectorView()
    qtbot.addWidget(sound_view)
    if hasattr(sound_view, "render_details"):
        sound_view.render_details(details)
    elif hasattr(sound_view, "render"):
        sound_view.render(details)

    # Verify table or reference label in sound_view
    if hasattr(sound_view, "ref_table"):
        assert sound_view.ref_table.rowCount() == 2
        assert sound_view.ref_table.columnCount() >= 4

    media_view = MediaInspectorView()
    qtbot.addWidget(media_view)
    if hasattr(media_view, "render_details"):
        media_view.render_details(details)
    elif hasattr(media_view, "render"):
        media_view.render(details)

    assert media_view.ref_table.rowCount() == 2


@pytest.mark.skipif(not HAS_M2, reason="Pending M2 (BankViewer): Cross-bank jump navigation")
def test_tier1_f4_cross_bank_jump_navigation(tmp_path: Path):
    """
    Feature F4: Cross-Bank Jump Navigation & History.
    Verifies that JumpToNodeRequested across banks updates selected bank and pushes history.
    """
    from src.ui.features.bank_viewer.causation import reconcile_viewer
    from src.ui.features.bank_viewer.state import (
        BankViewerState,
        HistoryLocation,
        JumpToNodeRequested,
        NavigateHistoryBackRequested,
    )

    init_state = BankViewerState(
        selected_bank_name="bank_a.bnk",
        selected_node_keys=("hirc:101",),
        history=(HistoryLocation(bank_name="bank_a.bnk", node_key="hirc:101"),),
        history_index=0,
    )

    # Jump to node in bank_b
    event = JumpToNodeRequested(node_key="hirc:201", bank_name="bank_b.bnk")
    new_state, intents = reconcile_viewer(init_state, event)

    assert new_state.selected_bank_name == "bank_b.bnk"
    assert "hirc:201" in new_state.selected_node_keys
    assert new_state.can_navigate_back is True

    # Navigate Back
    back_state, _ = reconcile_viewer(new_state, NavigateHistoryBackRequested())
    assert back_state.selected_bank_name == "bank_a.bnk"
    assert "hirc:101" in back_state.selected_node_keys


@pytest.mark.skipif(not HAS_M2, reason="Pending M2 (BankViewer): Streamed vs Embedded Indicators")
def test_tier1_f5_streamed_vs_embedded_indicators(tmp_path: Path):
    """
    Feature F5: Streamed vs Embedded Audio Indicators.
    Verifies that NodeInspectorDetails correctly reflects stream mode.
    """
    embedded_details = NodeInspectorDetails(
        node_key="hirc:101",
        name="EmbeddedSound",
        object_type="Sound",
        is_streamed=False,
    )
    assert embedded_details.is_streamed is False

    streamed_details = NodeInspectorDetails(
        node_key="hirc:102",
        name="StreamedSound",
        object_type="Sound",
        is_streamed=True,
    )
    assert streamed_details.is_streamed is True


@pytest.mark.skipif(not HAS_M3, reason="Pending M3 (Blast Radius): Dialog and Store")
def test_tier1_f6_blast_radius_dialog_and_store(qapp, qtbot):
    """
    Feature F6: Blast Radius Feature Slice & Dialog.
    Verifies state transitions, impact table rendering, and binary action choices.
    """
    from src.ui.features.blast_radius.causation import reconcile_blast_radius
    from src.ui.features.blast_radius.state import (
        BlastRadiusAction,
        BlastRadiusImpactItem,
        BlastRadiusMode,
        BlastRadiusState,
        ChooseActionRequested,
        CloseDialogIntent,
    )
    from src.ui.features.blast_radius.store import BlastRadiusStore
    from src.ui.features.blast_radius.view import BlastRadiusDialog

    items = (
        BlastRadiusImpactItem(
            bank_name="rome.bnk",
            node_id=101,
            node_name="Legionary",
            node_type="Sound",
            stream_type=0,
            is_embedded=True,
        ),
        BlastRadiusImpactItem(
            bank_name="guard.bnk",
            node_id=201,
            node_name="Praetorian",
            node_type="Sound",
            stream_type=2,
            is_embedded=False,
        ),
    )

    init_state = BlastRadiusState(
        mode=BlastRadiusMode.SHARED_CONFIRMATION,
        target_bank_name="rome.bnk",
        target_node_id=101,
        wem_id=50001,
        items=items,
    )

    # Causation test: Choose ISOLATE
    s_isolate, intents = reconcile_blast_radius(
        init_state, ChooseActionRequested(BlastRadiusAction.ISOLATE)
    )
    assert s_isolate.chosen_action == BlastRadiusAction.ISOLATE
    assert any(
        isinstance(i, CloseDialogIntent) and i.action == BlastRadiusAction.ISOLATE for i in intents
    )

    # Causation test: Choose OVERWRITE
    s_overwrite, intents = reconcile_blast_radius(
        init_state, ChooseActionRequested(BlastRadiusAction.OVERWRITE)
    )
    assert s_overwrite.chosen_action == BlastRadiusAction.OVERWRITE

    # View test: Dialog rendering
    store = BlastRadiusStore(init_state)
    dialog = BlastRadiusDialog(store)
    qtbot.addWidget(dialog)

    assert dialog.table.rowCount() == 2
    assert dialog.table.columnCount() == 5


@pytest.mark.skipif(not (HAS_M1 and HAS_M3), reason="Pending M1 & M3: Replacement branching hook")
def test_tier1_f7_replacement_branching_hook_branch_a(tmp_path: Path):
    """
    Feature F7: Branch A (Unshared Streamed).
    Replaces immediately without modal dialog.
    """
    bank = _create_synthetic_bank(bank_id=1001, sounds=[(101, 50001, 2)])
    project, session = _setup_test_project_and_session(tmp_path, {"test.bnk": bank})

    proceed, scope = check_replacement_branch(session=session, bank_name="test.bnk", sound_id=101)
    assert proceed is True
    assert scope == ReplacementScope.OVERWRITE


@pytest.mark.skipif(not (HAS_M1 and HAS_M3), reason="Pending M1 & M3: Replacement branching hook")
def test_tier1_f7_replacement_branching_hook_branch_b(qapp, qtbot, tmp_path: Path, monkeypatch):
    """
    Feature F7: Branch B (Unshared Embedded).
    Displays Promotion Notice dialog; proceeds with OVERWRITE on confirmation.
    """
    from src.ui.features.blast_radius.state import BlastRadiusAction
    from src.ui.features.blast_radius.view import BlastRadiusDialog

    bank = _create_synthetic_bank(bank_id=1001, sounds=[(101, 50001, 0)])
    project, session = _setup_test_project_and_session(tmp_path, {"test.bnk": bank})

    # Simulate user confirming promotion notice
    monkeypatch.setattr(BlastRadiusDialog, "exec", lambda self: BlastRadiusAction.OVERWRITE)

    proceed, scope = check_replacement_branch(session=session, bank_name="test.bnk", sound_id=101)
    assert proceed is True
    assert scope == ReplacementScope.OVERWRITE


@pytest.mark.skipif(not (HAS_M1 and HAS_M3), reason="Pending M1 & M3: Replacement branching hook")
def test_tier1_f7_replacement_branching_hook_branch_c(qapp, qtbot, tmp_path: Path, monkeypatch):
    """
    Feature F7: Branch C (Shared WEM).
    Displays Blast Radius dialog; returns ISOLATE on fork, OVERWRITE on overwrite, False on cancel.
    """
    from src.ui.features.blast_radius.state import BlastRadiusAction
    from src.ui.features.blast_radius.view import BlastRadiusDialog

    bank_a = _create_synthetic_bank(bank_id=1001, sounds=[(101, 50001, 0)])
    bank_b = _create_synthetic_bank(bank_id=1002, sounds=[(201, 50001, 2)])
    project, session = _setup_test_project_and_session(tmp_path, {"a.bnk": bank_a, "b.bnk": bank_b})

    # Choice 1: Fork / Isolate
    monkeypatch.setattr(BlastRadiusDialog, "exec", lambda self: BlastRadiusAction.ISOLATE)
    proceed, scope = check_replacement_branch(session=session, bank_name="a.bnk", sound_id=101)
    assert proceed is True
    assert scope == ReplacementScope.ISOLATE

    # Choice 2: Overwrite
    monkeypatch.setattr(BlastRadiusDialog, "exec", lambda self: BlastRadiusAction.OVERWRITE)
    proceed, scope = check_replacement_branch(session=session, bank_name="a.bnk", sound_id=101)
    assert proceed is True
    assert scope == ReplacementScope.OVERWRITE

    # Choice 3: Cancel
    monkeypatch.setattr(BlastRadiusDialog, "exec", lambda self: BlastRadiusAction.CANCEL)
    proceed, _ = check_replacement_branch(session=session, bank_name="a.bnk", sound_id=101)
    assert proceed is False


# =============================================================================
# TIER 2: BOUNDARY VALUE ANALYSIS (BVA) & CORNER CASES
# =============================================================================


@pytest.mark.skipif(not HAS_M1, reason="Pending M1 (Engine Core): WEM query boundaries")
def test_tier2_wem_references_zero_refs(tmp_path: Path):
    """
    BVA: Querying a WEM ID with 0 references returns empty tuple and count 0.
    """
    bank = _create_synthetic_bank(bank_id=1001, sounds=[(101, 50001, 2)])
    project, session = _setup_test_project_and_session(tmp_path, {"test.bnk": bank})

    refs = session.get_cross_bank_wem_references(999999)
    assert refs == ()
    assert session.get_wem_reference_count(999999) == 0


@pytest.mark.skipif(
    not HAS_M1, reason="Pending M1 (Engine Core): High fan-out WEM reference counting"
)
def test_tier2_wem_references_boundary_counts(tmp_path: Path):
    """
    BVA: Verifies reference boundaries at 1, 2, and high fan-out (50 referencing nodes).
    """
    # 50 sounds sharing WEM 77777 across 5 banks
    banks: dict[str, SoundBank] = {}
    for b_idx in range(5):
        b_name = f"bank_{b_idx}.bnk"
        sounds = [(b_idx * 100 + s_idx, 77777, 2) for s_idx in range(10)]
        banks[b_name] = _create_synthetic_bank(bank_id=1000 + b_idx, sounds=sounds)

    project, session = _setup_test_project_and_session(tmp_path, banks)

    count = session.get_wem_reference_count(77777)
    assert count == 50

    refs = session.get_cross_bank_wem_references(77777)
    assert len(refs) == 50


@pytest.mark.skipif(not HAS_M1, reason="Pending M1 (Engine Core): Extreme ID allocation boundaries")
def test_tier2_allocator_extreme_and_dense_ids():
    """
    BVA: Allocator behavior near 32-bit positive integer boundary and dense contiguous collision blocks.
    """
    # Near max 32-bit signed boundary
    dense_set = set(range(100000, 100500))
    dense_set.add(0x7FFFFFFF)

    allocated = allocate_unique_wem_id(dense_set, preferred_seed=100010)
    assert allocated not in dense_set
    assert 100000 < allocated <= 0x7FFFFFFF


@pytest.mark.skipif(not HAS_M1, reason="Pending M1 (Engine Core): Stream type boundary values")
def test_tier2_stream_types_boundary(tmp_path: Path):
    """
    BVA: Distinguishes stream_type 0 (embedded), 1 (prefetch), and 2 (streamed).
    """
    bank = _create_synthetic_bank(
        bank_id=1001,
        sounds=[(101, 50001, 0), (102, 50002, 2)],
    )
    # Add prefetch sound manually
    bank.hirc.objects.append(
        CAkSound(id=103, source_id=50003, file_id=50003, stream_type=1, file_offset=0)
    )

    project, session = _setup_test_project_and_session(tmp_path, {"test.bnk": bank})

    r_embed = session.get_cross_bank_wem_references(50001)[0]
    assert r_embed.stream_type == 0
    assert r_embed.is_embedded is True

    r_prefetch = session.get_cross_bank_wem_references(50003)[0]
    assert r_prefetch.stream_type == 1
    assert r_prefetch.is_embedded is True

    r_stream = session.get_cross_bank_wem_references(50002)[0]
    assert r_stream.stream_type == 2
    assert r_stream.is_embedded is False


@pytest.mark.skipif(not HAS_M1, reason="Pending M1 (Engine Core): Music track multiple sources")
def test_tier2_music_track_multiple_sources(tmp_path: Path):
    """
    Corner Case: CAkMusicTrack containing multiple sources referencing WEM IDs.
    """
    bank = _create_synthetic_bank(
        bank_id=1001,
        sounds=[],
        music_tracks=[(501, [(60001, 2), (60002, 2)])],
    )
    project, session = _setup_test_project_and_session(tmp_path, {"music.bnk": bank})

    ref_60001 = session.get_cross_bank_wem_references(60001)
    assert len(ref_60001) == 1
    assert ref_60001[0].node_id == 501
    assert ref_60001[0].node_type == "MusicTrack"

    ref_60002 = session.get_cross_bank_wem_references(60002)
    assert len(ref_60002) == 1
    assert ref_60002[0].node_id == 501


def test_tier2_empty_bank_indexing(tmp_path: Path):
    """
    Corner Case: SoundBank with empty HIRC and no DIDX entries indexes cleanly.
    """
    bank = SoundBank(
        header=BkhdChunk(bank_id=999, version=112),
        didx=DidxChunk(entries=[]),
        data=DataChunk(data=b""),
        hirc=HircChunk(objects=[]),
    )
    project, session = _setup_test_project_and_session(tmp_path, {"empty.bnk": bank})

    entry = session.get_loaded_entry("empty.bnk")
    assert entry is not None
    assert len(entry[1].get_root_objects()) == 0


def test_tier2_procedural_sound_rejection(tmp_path: Path):
    """
    Corner Case: Procedural tone generator (plugin_id & 0x0F == 2) rejected by planner.
    """
    sound = CAkSound(id=101, plugin_id=0x00020002, source_id=0, file_id=0, stream_type=0)
    bank = SoundBank(
        header=BkhdChunk(bank_id=999, version=112),
        didx=DidxChunk(entries=[]),
        data=DataChunk(data=b""),
        hirc=HircChunk(objects=[sound]),
    )
    dummy_wav = make_synthetic_wav(tmp_path / "custom.wav")
    source = ExternalFileSource(file_path=dummy_wav)
    target = SoundNodeTarget(bank_name="test.bnk", sound_id=101)

    with pytest.raises(ValueError, match=r"[Cc]annot replace procedural"):
        plan_audio_replacement(bank=bank, target=target, source=source)


# =============================================================================
# TIER 3: CROSS-FEATURE COMBINATIONS (Pairwise Matrix)
# =============================================================================


@pytest.mark.skipif(not HAS_M1, reason="Pending M1: Pairwise multi-bank embedded overwrite")
def test_tier3_pairwise_multibank_shared_embedded_overwrite(tmp_path: Path):
    """
    Pairwise Combination: Multi-Bank + Shared Embedded WEM + Overwrite + Undo/Redo.
    - Two banks share embedded WEM 50001.
    - User overwrites everywhere: loose 50001.wem staged, both banks promoted to stream_type=2.
    - Single undo restores both banks back to stream_type=0 and deletes loose WEM.
    """
    bank_a = _create_synthetic_bank(bank_id=1001, sounds=[(101, 50001, 0)])
    bank_b = _create_synthetic_bank(bank_id=1002, sounds=[(201, 50001, 0)])
    project, session = _setup_test_project_and_session(tmp_path, {"a.bnk": bank_a, "b.bnk": bank_b})

    new_wav = make_synthetic_wav(tmp_path / "shared_new.wav")
    source = ExternalFileSource(file_path=new_wav)

    batch = MutationBatch(
        description="Overwrite shared embedded across banks",
        items=(
            BatchItem(
                target=SoundNodeTarget(bank_name="a.bnk", sound_id=101),
                source=source,
                scope=ReplacementScope.OVERWRITE,
            ),
        ),
    )
    outcome = session.apply_batch(batch)
    assert outcome.applied == 1

    staged_file = project.audio_dir / "50001.wem"
    assert staged_file.is_file()

    # Both nodes must now be stream_type 2
    b_a = session.get_loaded_entry("a.bnk")[0]
    b_b = session.get_loaded_entry("b.bnk")[0]
    assert next(o for o in b_a.hirc.objects if o.id == 101).stream_type == 2
    assert next(o for o in b_b.hirc.objects if o.id == 201).stream_type == 2

    # Single Undo restores both banks to stream_type 0 and cleans up loose WEM
    session.undo_mutation()
    assert not staged_file.is_file()
    assert 50001 not in project.manifest.staged_wems

    rb_a = session.get_loaded_entry("a.bnk")[0]
    rb_b = session.get_loaded_entry("b.bnk")[0]
    assert next(o for o in rb_a.hirc.objects if o.id == 101).stream_type == 0
    assert next(o for o in rb_b.hirc.objects if o.id == 201).stream_type == 0


@pytest.mark.skipif(not HAS_M1, reason="Pending M1: Pairwise multi-bank embedded isolate")
def test_tier3_pairwise_multibank_shared_embedded_isolate(tmp_path: Path):
    """
    Pairwise Combination: Multi-Bank + Shared Embedded WEM + Isolate + Undo/Redo.
    - Two banks share embedded WEM 50001.
    - Target in Bank A isolated: gets new WEM ID, promoted to stream_type=2.
    - Sibling in Bank B is strictly untouched (remains 50001, stream_type=0).
    - Undo deletes isolated WEM and restores Bank A. Bank B was never modified.
    """
    bank_a = _create_synthetic_bank(bank_id=1001, sounds=[(101, 50001, 0)])
    bank_b = _create_synthetic_bank(bank_id=1002, sounds=[(201, 50001, 0)])
    project, session = _setup_test_project_and_session(tmp_path, {"a.bnk": bank_a, "b.bnk": bank_b})

    new_wav = make_synthetic_wav(tmp_path / "isolated.wav")
    source = ExternalFileSource(file_path=new_wav)

    batch = MutationBatch(
        description="Isolate target in bank A",
        items=(
            BatchItem(
                target=SoundNodeTarget(bank_name="a.bnk", sound_id=101),
                source=source,
                scope=ReplacementScope.ISOLATE,
            ),
        ),
    )
    outcome = session.apply_batch(batch)
    assert outcome.applied == 1

    b_a = session.get_loaded_entry("a.bnk")[0]
    b_b = session.get_loaded_entry("b.bnk")[0]

    s101 = next(o for o in b_a.hirc.objects if o.id == 101)
    s201 = next(o for o in b_b.hirc.objects if o.id == 201)

    assert s101.file_id != 50001
    assert s101.stream_type == 2
    assert s201.file_id == 50001
    assert s201.stream_type == 0

    assert "b.bnk" not in project.manifest.modified_banks

    session.undo_mutation()
    rb_a = session.get_loaded_entry("a.bnk")[0]
    assert next(o for o in rb_a.hirc.objects if o.id == 101).file_id == 50001


@pytest.mark.skipif(not HAS_M1, reason="Pending M1: Pairwise multi-bank streamed overwrite")
def test_tier3_pairwise_multibank_shared_streamed_overwrite(tmp_path: Path):
    """
    Pairwise Combination: Multi-Bank + Shared Streamed WEM + Overwrite.
    Pre-existing loose WEM overwritten; undo restores prior audio bytes.
    """
    orig_bytes = b"ORIGINAL_STREAMED_BYTES_AABBCC"
    bank_a = _create_synthetic_bank(bank_id=1001, sounds=[(101, 50001, 2)])
    bank_b = _create_synthetic_bank(bank_id=1002, sounds=[(201, 50001, 2)])
    project, session = _setup_test_project_and_session(
        tmp_path,
        {"a.bnk": bank_a, "b.bnk": bank_b},
        staged_wems={50001: orig_bytes},
    )

    wem_file = project.audio_dir / "50001.wem"
    assert wem_file.read_bytes() == orig_bytes

    new_wav = make_synthetic_wav(tmp_path / "overwrite.wav")
    source = ExternalFileSource(file_path=new_wav)

    batch = MutationBatch(
        description="Overwrite shared streamed",
        items=(
            BatchItem(
                target=SoundNodeTarget(bank_name="a.bnk", sound_id=101),
                source=source,
                scope=ReplacementScope.OVERWRITE,
            ),
        ),
    )
    session.apply_batch(batch)
    assert wem_file.read_bytes() != orig_bytes

    session.undo_mutation()
    assert wem_file.read_bytes() == orig_bytes


@pytest.mark.skipif(not HAS_M1, reason="Pending M1: Pairwise multi-bank streamed isolate")
def test_tier3_pairwise_multibank_shared_streamed_isolate(tmp_path: Path):
    """
    Pairwise Combination: Multi-Bank + Shared Streamed WEM + Isolate.
    Original loose WEM is untouched; target gets new WEM ID and file.
    """
    orig_bytes = b"ORIGINAL_STREAMED_BYTES_112233"
    bank_a = _create_synthetic_bank(bank_id=1001, sounds=[(101, 50001, 2)])
    bank_b = _create_synthetic_bank(bank_id=1002, sounds=[(201, 50001, 2)])
    project, session = _setup_test_project_and_session(
        tmp_path,
        {"a.bnk": bank_a, "b.bnk": bank_b},
        staged_wems={50001: orig_bytes},
    )

    wem_file_50001 = project.audio_dir / "50001.wem"

    new_wav = make_synthetic_wav(tmp_path / "fork.wav")
    source = ExternalFileSource(file_path=new_wav)

    batch = MutationBatch(
        description="Isolate target in bank A",
        items=(
            BatchItem(
                target=SoundNodeTarget(bank_name="a.bnk", sound_id=101),
                source=source,
                scope=ReplacementScope.ISOLATE,
            ),
        ),
    )
    session.apply_batch(batch)

    # Original loose WEM is 100% untouched
    assert wem_file_50001.read_bytes() == orig_bytes

    b_a = session.get_loaded_entry("a.bnk")[0]
    s101 = next(o for o in b_a.hirc.objects if o.id == 101)
    forked_id = s101.file_id
    assert forked_id != 50001
    assert (project.audio_dir / f"{forked_id}.wem").is_file()

    session.undo_mutation()
    assert not (project.audio_dir / f"{forked_id}.wem").is_file()
    assert wem_file_50001.read_bytes() == orig_bytes


@pytest.mark.skipif(not (HAS_M1 and HAS_M2), reason="Pending M1 & M2: Navigation + Mutation")
def test_tier3_pairwise_jump_navigate_then_isolate_and_undo(qapp, qtbot, tmp_path: Path):
    """
    Pairwise Combination: Jump Navigation across banks followed by Isolate Replacement & Undo.
    Verifies navigation history and active bank state remain fully consistent.
    """
    from src.ui.features.bank_viewer.causation import reconcile_viewer
    from src.ui.features.bank_viewer.state import (
        BankViewerState,
        HistoryLocation,
        JumpToNodeRequested,
        NavigateHistoryBackRequested,
    )

    bank_a = _create_synthetic_bank(bank_id=1001, sounds=[(101, 50001, 0)])
    bank_b = _create_synthetic_bank(bank_id=1002, sounds=[(201, 50001, 0)])
    project, session = _setup_test_project_and_session(tmp_path, {"a.bnk": bank_a, "b.bnk": bank_b})

    # Start in Bank A, jump to Bank B Sound 201
    state_0 = BankViewerState(
        selected_bank_name="a.bnk",
        selected_node_keys=("hirc:101",),
        history=(HistoryLocation(bank_name="a.bnk", node_key="hirc:101"),),
        history_index=0,
    )
    state_1, _ = reconcile_viewer(
        state_0, JumpToNodeRequested(node_key="hirc:201", bank_name="b.bnk")
    )
    assert state_1.selected_bank_name == "b.bnk"

    # Mutate in Bank B
    new_wav = make_synthetic_wav(tmp_path / "b_sound.wav")
    session.apply_batch(
        MutationBatch(
            description="Isolate Sound 201",
            items=(
                BatchItem(
                    target=SoundNodeTarget(bank_name="b.bnk", sound_id=201),
                    source=ExternalFileSource(file_path=new_wav),
                    scope=ReplacementScope.ISOLATE,
                ),
            ),
        )
    )

    # Navigate Back to Bank A
    state_back, _ = reconcile_viewer(state_1, NavigateHistoryBackRequested())
    assert state_back.selected_bank_name == "a.bnk"
    assert "hirc:101" in state_back.selected_node_keys

    # Undo mutation
    session.undo_mutation()
    b_b = session.get_loaded_entry("b.bnk")[0]
    assert next(o for o in b_b.hirc.objects if o.id == 201).file_id == 50001


# =============================================================================
# TIER 4: REAL-WORLD MODDER WORKLOADS (Scenario-Based End-to-End Tests)
# =============================================================================


@pytest.mark.skipif(
    not (HAS_M1 and HAS_M2 and HAS_M3), reason="Pending M1-M3: Scenario 1 full workflow"
)
def test_tier4_scenario_unit_battle_shout_isolate_workflow(
    qapp, qtbot, tmp_path: Path, monkeypatch
):
    """
    Tier 4 Scenario 1: Unit Battle Shout Replacement (Isolate Workflow).
    - Roman Legionary (Sound 1001) in battle_rome.bnk and Praetorian Guard (Sound 1002) in battle_guard.bnk
      share vanilla warcry WEM 70001.
    - Modder replaces Praetorian Guard's battle shout with a custom roar WAV.
    - Branch C triggers blast radius dialog. Modder clicks 'Isolate / Fork'.
    - Outcome: Praetorian Guard is assigned new unique WEM ID (stream_type 2).
      Roman Legionary strictly retains vanilla WEM 70001.
      Cross-bank reference counts reflect separation.
      Undo and Redo restore exact audio files and AST state.
    """
    from src.ui.features.blast_radius.state import BlastRadiusAction
    from src.ui.features.blast_radius.view import BlastRadiusDialog

    bank_rome = _create_synthetic_bank(bank_id=1001, sounds=[(1001, 70001, 0)])
    bank_guard = _create_synthetic_bank(bank_id=1002, sounds=[(1002, 70001, 0)])

    project, session = _setup_test_project_and_session(
        tmp_path,
        {"battle_rome.bnk": bank_rome, "battle_guard.bnk": bank_guard},
    )

    # 1. Initial State: WEM 70001 shared across 2 banks
    assert session.get_wem_reference_count(70001) == 2

    # 2. Modder chooses Isolate in Blast Radius Dialog
    monkeypatch.setattr(BlastRadiusDialog, "exec", lambda self: BlastRadiusAction.ISOLATE)

    proceed, scope = check_replacement_branch(
        session=session, bank_name="battle_guard.bnk", sound_id=1002
    )
    assert proceed is True
    assert scope == ReplacementScope.ISOLATE

    # 3. Apply the isolation mutation
    custom_roar = make_synthetic_wav(tmp_path / "praetorian_roar.wav")
    outcome = session.apply_batch(
        MutationBatch(
            description="Isolate Praetorian Guard battle roar",
            items=(
                BatchItem(
                    target=SoundNodeTarget(bank_name="battle_guard.bnk", sound_id=1002),
                    source=ExternalFileSource(file_path=custom_roar),
                    scope=scope,
                ),
            ),
        )
    )
    assert outcome.applied == 1

    # 4. Verify separation
    guard_bank = session.get_loaded_entry("battle_guard.bnk")[0]
    rome_bank = session.get_loaded_entry("battle_rome.bnk")[0]

    praetorian = next(o for o in guard_bank.hirc.objects if o.id == 1002)
    legionary = next(o for o in rome_bank.hirc.objects if o.id == 1001)

    forked_id = praetorian.file_id
    assert forked_id != 70001
    assert praetorian.stream_type == 2
    assert legionary.file_id == 70001
    assert legionary.stream_type == 0

    # Loose file staged
    assert (project.audio_dir / f"{forked_id}.wem").is_file()

    # Index reflects updated counts
    assert session.get_wem_reference_count(70001) == 1
    assert session.get_wem_reference_count(forked_id) == 1

    # 5. Undo verification
    session.undo_mutation()
    assert not (project.audio_dir / f"{forked_id}.wem").is_file()
    assert session.get_wem_reference_count(70001) == 2

    # 6. Redo verification
    session.redo_mutation()
    assert (project.audio_dir / f"{forked_id}.wem").is_file()
    assert session.get_wem_reference_count(forked_id) == 1


@pytest.mark.skipif(
    not (HAS_M1 and HAS_M2 and HAS_M3), reason="Pending M1-M3: Scenario 2 full workflow"
)
def test_tier4_scenario_global_sword_impact_overwrite_workflow(
    qapp, qtbot, tmp_path: Path, monkeypatch
):
    """
    Tier 4 Scenario 2: Global Sword Impact Replacement (Overwrite Workflow).
    - Shared sword impact WEM 88888 across 3 banks: infantry.bnk, cavalry.bnk, missile.bnk.
    - Modder replaces sound with enhanced metal clang.
    - Branch C triggers blast radius confirmation warning 3 banks will be affected.
    - Modder chooses 'Replace Everywhere / Overwrite'.
    - Outcome: Loose 88888.wem staged; all 3 banks updated/promoted to stream_type 2.
      Single undo restores all 3 banks in an atomic transaction.
    """
    from src.ui.features.blast_radius.state import BlastRadiusAction
    from src.ui.features.blast_radius.view import BlastRadiusDialog

    bank_inf = _create_synthetic_bank(bank_id=1001, sounds=[(101, 88888, 0)])
    bank_cav = _create_synthetic_bank(bank_id=1002, sounds=[(201, 88888, 0)])
    bank_mis = _create_synthetic_bank(bank_id=1003, sounds=[(301, 88888, 0)])

    project, session = _setup_test_project_and_session(
        tmp_path,
        {"infantry.bnk": bank_inf, "cavalry.bnk": bank_cav, "missile.bnk": bank_mis},
    )

    assert session.get_wem_reference_count(88888) == 3

    # Modder chooses Overwrite
    monkeypatch.setattr(BlastRadiusDialog, "exec", lambda self: BlastRadiusAction.OVERWRITE)

    proceed, scope = check_replacement_branch(
        session=session, bank_name="infantry.bnk", sound_id=101
    )
    assert proceed is True
    assert scope == ReplacementScope.OVERWRITE

    enhanced_clang = make_synthetic_wav(tmp_path / "metal_clang.wav")
    outcome = session.apply_batch(
        MutationBatch(
            description="Overwrite global sword impact",
            items=(
                BatchItem(
                    target=SoundNodeTarget(bank_name="infantry.bnk", sound_id=101),
                    source=ExternalFileSource(file_path=enhanced_clang),
                    scope=scope,
                ),
            ),
        )
    )
    assert outcome.applied == 1

    staged_file = project.audio_dir / "88888.wem"
    assert staged_file.is_file()

    # All 3 banks promoted to stream_type 2
    for b_name, s_id in [("infantry.bnk", 101), ("cavalry.bnk", 201), ("missile.bnk", 301)]:
        b = session.get_loaded_entry(b_name)[0]
        assert next(o for o in b.hirc.objects if o.id == s_id).stream_type == 2

    # Atomic undo restores all 3 banks
    session.undo_mutation()
    assert not staged_file.is_file()

    for b_name, s_id in [("infantry.bnk", 101), ("cavalry.bnk", 201), ("missile.bnk", 301)]:
        b = session.get_loaded_entry(b_name)[0]
        assert next(o for o in b.hirc.objects if o.id == s_id).stream_type == 0
