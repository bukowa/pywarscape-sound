"""
Tests for Wave 4 Engine & Inspector Controls:
- Task 13: NodeBaseParams Volume (PropID 0) & Pitch (PropID 2) tuning via NodeParamsSource & UpdateNodeParamsIntent
- Task 14: CAkRanSeqCntr Sound Pool Variation via ContainerVariationTarget & AppendVariationIntent
- Round-trip serialization bit-exactness
- WorkspaceSession transactional undo/redo
- SoundInspectorView and ContainerInspectorView UI behavior
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk
from src.bnk.models import (
    AkMusicTrackSource,
    AkPlaylistItem,
    CAkMusicTrack,
    CAkRanSeqCntr,
    CAkSound,
    CAkSwitchCntr,
    NodeBaseParams,
)
from src.bnk.wem import build_silent_pcm_wem_bytes
from src.engine.effectuator import execute_mutation_plan
from src.engine.ontology import (
    AppendVariationIntent,
    BatchItem,
    BatchOutcome,
    ContainerVariationTarget,
    ExistingMediaReferenceSource,
    ExternalFileSource,
    MarkBankModifiedIntent,
    MusicTrackTarget,
    MutationBatch,
    NodeParamsSource,
    PlanRejection,
    SilentStubSource,
    SoundNodeTarget,
    StageMasterAudioIntent,
    UpdateNodeParamsIntent,
)
from src.engine.planner import (
    plan_audio_replacement,
    plan_batch,
    try_plan_audio_replacement,
)
from src.engine.session import WorkspaceSession
from src.ui.features.bank_viewer.inspector_panel import InspectorPanel
from src.ui.features.bank_viewer.state import (
    InspectorProperty,
    NodeInspectorDetails,
    RanSeqContainerSemantics,
    SwitchContainerSemantics,
)
from src.ui.features.bank_viewer.views.container_view import ContainerInspectorView
from src.ui.features.bank_viewer.views.sound_view import SoundInspectorView
from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.resolver import AssetResolver
from src.workspace.storage import ProjectStorage
from tests.support.factories import make_synthetic_wav


def _make_test_bank(objects: list | None = None) -> SoundBank:
    return SoundBank(
        header=BkhdChunk(bank_id=101, version=112),
        hirc=HircChunk(objects=list(objects) if objects else []),
    )


# -----------------------------------------------------------------------------
# Task 13: NodeBaseParams Volume & Pitch Tuning (Engine)
# -----------------------------------------------------------------------------


def test_plan_sound_node_params_tuning():
    sound = CAkSound(id=2001, node_base_params=NodeBaseParams(props={0: -3.0}))
    bank = _make_test_bank([sound])
    target = SoundNodeTarget(bank_name="test_bank.bnk", sound_id=2001)
    source = NodeParamsSource(volume_db=-6.5, pitch_cents=120.0)

    plan = plan_audio_replacement(bank=bank, target=target, source=source)

    assert plan.target == target
    assert plan.source == source
    assert len(plan.effects) == 2
    intent = plan.effects[0]
    assert isinstance(intent, UpdateNodeParamsIntent)
    assert intent.bank_name == "test_bank.bnk"
    assert intent.node_id == 2001
    assert intent.volume_db == -6.5
    assert intent.pitch_cents == 120.0
    assert isinstance(plan.effects[1], MarkBankModifiedIntent)


def test_plan_music_track_node_params_tuning():
    track = CAkMusicTrack(
        id=4001,
        sources=[AkMusicTrackSource(source_id=5001, file_id=5001)],
        node_base_params=NodeBaseParams(),
    )
    bank = _make_test_bank([track])
    target = MusicTrackTarget(bank_name="music_bank.bnk", track_id=4001)
    source = NodeParamsSource(volume_db=-12.0, pitch_cents=-300.0)

    plan = plan_audio_replacement(bank=bank, target=target, source=source)

    assert len(plan.effects) == 2
    intent = plan.effects[0]
    assert isinstance(intent, UpdateNodeParamsIntent)
    assert intent.node_id == 4001
    assert intent.volume_db == -12.0
    assert intent.pitch_cents == -300.0


def test_plan_container_node_params_tuning():
    cntr = CAkRanSeqCntr(id=6001, node_base_params=NodeBaseParams())
    bank = _make_test_bank([cntr])
    target = ContainerVariationTarget(bank_name="cntr_bank.bnk", container_id=6001)
    source = NodeParamsSource(volume_db=3.0, pitch_cents=50.0)

    plan = plan_audio_replacement(bank=bank, target=target, source=source)

    assert len(plan.effects) == 2
    intent = plan.effects[0]
    assert isinstance(intent, UpdateNodeParamsIntent)
    assert intent.node_id == 6001
    assert intent.volume_db == 3.0
    assert intent.pitch_cents == 50.0


def test_plan_container_variation_delegation_tuning():
    child_sound = CAkSound(id=2002, node_base_params=NodeBaseParams())
    cntr = CAkRanSeqCntr(id=6002, children=[2002], node_base_params=NodeBaseParams())
    bank = _make_test_bank([child_sound, cntr])
    target = ContainerVariationTarget(
        bank_name="cntr_bank.bnk", container_id=6002, variation_sound_id=2002
    )
    source = NodeParamsSource(volume_db=-4.5, pitch_cents=0.0)

    plan = plan_audio_replacement(bank=bank, target=target, source=source)

    intent = plan.effects[0]
    assert isinstance(intent, UpdateNodeParamsIntent)
    assert intent.node_id == 2002
    assert intent.volume_db == -4.5


def test_execute_update_node_params_override_and_clear(tmp_path: Path):
    sound = CAkSound(id=2003, node_base_params=NodeBaseParams(props={0: -2.0, 2: 50.0}))
    bank = _make_test_bank([sound])

    proj_dir = tmp_path / "proj"
    project = ProjectStorage.create_project(proj_dir, name="TestTuning", game=GameType.ATTILA)

    # 1. Update with non-zero volume & pitch
    target = SoundNodeTarget(bank_name="test.bnk", sound_id=2003)
    source1 = NodeParamsSource(volume_db=-9.5, pitch_cents=250.0)
    plan1 = plan_audio_replacement(bank=bank, target=target, source=source1)
    res1 = execute_mutation_plan(plan=plan1, project=project, bank=bank)

    assert res1.success is True
    assert sound.node_base_params.props[0] == -9.5
    assert sound.node_base_params.props[2] == 250.0

    # Bit-exact round-trip check
    bank_bytes = bank.to_bytes()
    bank_rt = SoundBank.from_bytes(bank_bytes)
    assert bank_rt.to_bytes() == bank_bytes

    # 2. Reset volume and pitch to 0.0 (clears props)
    source2 = NodeParamsSource(volume_db=0.0, pitch_cents=0.0)
    plan2 = plan_audio_replacement(bank=bank, target=target, source=source2)
    res2 = execute_mutation_plan(plan=plan2, project=project, bank=bank)

    assert res2.success is True
    assert 0 not in sound.node_base_params.props
    assert 2 not in sound.node_base_params.props

    # Bit-exact round-trip check after clearing
    bank_bytes2 = bank.to_bytes()
    bank_rt2 = SoundBank.from_bytes(bank_bytes2)
    assert bank_rt2.to_bytes() == bank_bytes2


def test_execute_update_node_params_errors(tmp_path: Path):
    sound = CAkSound(id=2004, node_base_params=NodeBaseParams())
    bank = _make_test_bank([sound])
    proj_dir = tmp_path / "proj"
    project = ProjectStorage.create_project(proj_dir, name="TestErrors", game=GameType.ATTILA)

    # Missing node
    plan_missing = try_plan_audio_replacement(
        bank,
        SoundNodeTarget(bank_name="test.bnk", sound_id=9999),
        NodeParamsSource(volume_db=-5.0),
        external_file_exists=True,
    )
    assert isinstance(plan_missing, PlanRejection)
    assert plan_missing.code == "SOUND_NOT_FOUND"


# -----------------------------------------------------------------------------
# Task 14: CAkRanSeqCntr Sound Pool Variation (Engine)
# -----------------------------------------------------------------------------


def test_plan_append_variation_external_file(tmp_path: Path):
    wav_path = tmp_path / "variation.wav"
    make_synthetic_wav(wav_path, duration_s=0.2)

    sound1 = CAkSound(id=1001, node_base_params=NodeBaseParams(override_bus_id=42))
    cntr = CAkRanSeqCntr(
        id=3001,
        children=[1001],
        playlist=[AkPlaylistItem(play_id=1001, weight=50000)],
        node_base_params=NodeBaseParams(),
    )
    bank = _make_test_bank([sound1, cntr])

    target = ContainerVariationTarget(bank_name="pool.bnk", container_id=3001)
    source = ExternalFileSource(file_path=wav_path)

    plan = plan_audio_replacement(bank=bank, target=target, source=source)

    assert len(plan.effects) == 3
    stage_eff = plan.effects[0]
    append_eff = plan.effects[1]
    mark_eff = plan.effects[2]

    assert isinstance(stage_eff, StageMasterAudioIntent)
    assert stage_eff.source_path == wav_path
    assert isinstance(append_eff, AppendVariationIntent)
    assert append_eff.bank_name == "pool.bnk"
    assert append_eff.container_id == 3001
    assert append_eff.child_sound_id != 1001
    assert append_eff.child_sound_id != append_eff.wem_id
    assert append_eff.wem_id == stage_eff.wem_id
    assert isinstance(mark_eff, MarkBankModifiedIntent)


def test_plan_append_variation_existing_media_and_silent_stub():
    sound1 = CAkSound(id=1001, node_base_params=NodeBaseParams())
    cntr = CAkRanSeqCntr(
        id=3002,
        children=[1001],
        playlist=[AkPlaylistItem(play_id=1001, weight=50000)],
        node_base_params=NodeBaseParams(),
    )
    bank = _make_test_bank([sound1, cntr])
    target = ContainerVariationTarget(bank_name="pool.bnk", container_id=3002)

    # 1. ExistingMediaReferenceSource
    plan_media = plan_audio_replacement(
        bank=bank, target=target, source=ExistingMediaReferenceSource(wem_id=777888)
    )
    assert len(plan_media.effects) == 2
    app_media = plan_media.effects[0]
    assert isinstance(app_media, AppendVariationIntent)
    assert app_media.wem_id == 777888

    # 2. SilentStubSource
    plan_stub = plan_audio_replacement(
        bank=bank, target=target, source=SilentStubSource(stub_wem_id=1)
    )
    assert len(plan_stub.effects) == 2
    app_stub = plan_stub.effects[0]
    assert isinstance(app_stub, AppendVariationIntent)
    assert app_stub.wem_id == 1


def test_plan_append_variation_missing_container_or_file(tmp_path: Path):
    sound1 = CAkSound(id=1001, node_base_params=NodeBaseParams())
    sw_cntr = CAkSwitchCntr(id=3003, node_base_params=NodeBaseParams())
    bank = _make_test_bank([sound1, sw_cntr])

    # 1. Container does not exist
    rej1 = try_plan_audio_replacement(
        bank,
        ContainerVariationTarget(bank_name="pool.bnk", container_id=9999),
        ExistingMediaReferenceSource(wem_id=100),
        external_file_exists=True,
    )
    assert isinstance(rej1, PlanRejection)
    assert rej1.code == "CONTAINER_NOT_FOUND"

    # 2. Container is SwitchCntr (not RanSeqCntr)
    rej2 = try_plan_audio_replacement(
        bank,
        ContainerVariationTarget(bank_name="pool.bnk", container_id=3003),
        ExistingMediaReferenceSource(wem_id=100),
        external_file_exists=True,
    )
    assert isinstance(rej2, PlanRejection)
    assert rej2.code == "CONTAINER_NOT_FOUND"

    # 3. File not found
    cntr = CAkRanSeqCntr(id=3004, node_base_params=NodeBaseParams())
    bank2 = _make_test_bank([cntr])
    rej3 = try_plan_audio_replacement(
        bank2,
        ContainerVariationTarget(bank_name="pool.bnk", container_id=3004),
        ExternalFileSource(file_path=tmp_path / "non_existent.wav"),
        external_file_exists=False,
    )
    assert isinstance(rej3, PlanRejection)
    assert rej3.code == "FILE_NOT_FOUND"


def test_plan_batch_reserves_variation_ids(tmp_path: Path):
    wav1 = tmp_path / "var1.wav"
    wav2 = tmp_path / "var2.wav"
    make_synthetic_wav(wav1, duration_s=0.1)
    make_synthetic_wav(wav2, duration_s=0.1)

    sound1 = CAkSound(id=1001, node_base_params=NodeBaseParams())
    cntr = CAkRanSeqCntr(
        id=3005,
        children=[1001],
        playlist=[AkPlaylistItem(play_id=1001, weight=50000)],
        node_base_params=NodeBaseParams(),
    )
    bank = _make_test_bank([sound1, cntr])

    target = ContainerVariationTarget(bank_name="pool.bnk", container_id=3005)
    batch = MutationBatch(
        description="Append two variations",
        items=(
            BatchItem(target=target, source=ExternalFileSource(file_path=wav1)),
            BatchItem(target=target, source=ExternalFileSource(file_path=wav2)),
        ),
    )

    batch_plan = plan_batch(
        banks={"pool.bnk": bank},
        batch=batch,
        external_files_exist={wav1: True, wav2: True},
    )

    assert len(batch_plan.plans) == 2
    assert len(batch_plan.rejections) == 0

    p1, p2 = batch_plan.plans
    eff1 = next(e for e in p1.effects if isinstance(e, AppendVariationIntent))
    eff2 = next(e for e in p2.effects if isinstance(e, AppendVariationIntent))

    # Child sound IDs and WEM IDs must be distinct across items in the batch
    assert eff1.child_sound_id != eff2.child_sound_id
    assert eff1.wem_id != eff2.wem_id


def test_execute_append_variation_ast_mutation_and_round_trip(tmp_path: Path):
    wav_path = tmp_path / "new_var.wav"
    make_synthetic_wav(wav_path, duration_s=0.15)

    orig_nb = NodeBaseParams(override_bus_id=99, direct_parent_id=3006, props={0: -1.5})
    sound1 = CAkSound(id=1001, node_base_params=orig_nb)
    cntr = CAkRanSeqCntr(
        id=3006,
        children=[1001],
        playlist=[AkPlaylistItem(play_id=1001, weight=50000)],
        node_base_params=NodeBaseParams(),
    )
    bank = _make_test_bank([sound1, cntr])

    proj_dir = tmp_path / "proj"
    project = ProjectStorage.create_project(proj_dir, name="TestVariation", game=GameType.ATTILA)

    target = ContainerVariationTarget(bank_name="pool.bnk", container_id=3006)
    source = ExternalFileSource(file_path=wav_path)
    plan = plan_audio_replacement(bank=bank, target=target, source=source)

    res = execute_mutation_plan(plan=plan, project=project, bank=bank)
    assert res.success is True

    # Check that new sound was created with cloned node_base_params
    new_sound_eff = next(e for e in plan.effects if isinstance(e, AppendVariationIntent))
    new_sound = next((o for o in bank.hirc.objects if o.id == new_sound_eff.child_sound_id), None)
    assert isinstance(new_sound, CAkSound)
    assert new_sound.node_base_params.override_bus_id == 99
    assert new_sound.node_base_params.direct_parent_id == 3006
    assert new_sound.node_base_params.props[0] == -1.5
    assert new_sound.stream_type == 2

    # Check container has updated children and playlist
    assert new_sound_eff.child_sound_id in cntr.children
    assert len(cntr.children) == 2
    assert len(cntr.playlist) == 2
    assert cntr.playlist[-1].play_id == new_sound_eff.child_sound_id
    assert cntr.playlist[-1].weight == 50000

    # Ensure new sound was inserted right before cntr
    cntr_idx = bank.hirc.objects.index(cntr)
    new_sound_idx = bank.hirc.objects.index(new_sound)
    assert new_sound_idx == cntr_idx - 1

    # Bit-exact serialization round-trip verification
    bank_bytes = bank.to_bytes()
    bank_rt = SoundBank.from_bytes(bank_bytes)
    assert bank_rt.to_bytes() == bank_bytes


# -----------------------------------------------------------------------------
# WorkspaceSession Transactional Undo / Redo
# -----------------------------------------------------------------------------


def test_session_undo_redo_node_params_and_variation(tmp_path: Path):
    # Setup vanilla bank
    s1 = CAkSound(
        id=1001,
        source_id=12345,
        file_id=12345,
        stream_type=2,
        node_base_params=NodeBaseParams(props={0: -3.0}),
    )
    cntr = CAkRanSeqCntr(
        id=3007,
        children=[1001],
        playlist=[AkPlaylistItem(play_id=1001, weight=50000)],
        node_base_params=NodeBaseParams(),
    )
    vanilla_bank = _make_test_bank([s1, cntr])
    vanilla_bytes = vanilla_bank.to_bytes()

    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "battle.bnk").write_bytes(vanilla_bytes)
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)

    proj_dir = tmp_path / "project"
    project = ProjectStorage.create_project(proj_dir, name="SessionTest", game=GameType.ATTILA)
    project.cache = cache

    resolver = AssetResolver(project=project, cache=cache)
    session = WorkspaceSession(project=project)
    session.resolver = resolver
    session.resolve_and_parse_bank("battle.bnk")
    loaded_bank = session.get_loaded_bank("battle.bnk")
    assert loaded_bank is not None

    # 1. Apply NodeParamsSource tuning
    tune_target = SoundNodeTarget(bank_name="battle.bnk", sound_id=1001)
    tune_batch = MutationBatch(
        description="Tune volume",
        items=(
            BatchItem(
                target=tune_target, source=NodeParamsSource(volume_db=-10.0, pitch_cents=100.0)
            ),
        ),
    )
    outcome1: BatchOutcome = session.apply_batch(tune_batch)
    assert outcome1.applied == 1

    tuned_sound = next(o for o in loaded_bank.hirc.objects if o.id == 1001)
    assert tuned_sound.node_base_params.props[0] == -10.0
    assert tuned_sound.node_base_params.props[2] == 100.0

    # Undo tuning
    assert session.can_undo_mutation
    session.undo_mutation()

    undone_bank = session.get_loaded_bank("battle.bnk")
    undone_sound = next(o for o in undone_bank.hirc.objects if o.id == 1001)
    assert undone_sound.node_base_params.props[0] == -3.0
    assert 2 not in undone_sound.node_base_params.props

    # Redo tuning
    assert session.can_redo_mutation
    session.redo_mutation()

    redone_bank = session.get_loaded_bank("battle.bnk")
    redone_sound = next(o for o in redone_bank.hirc.objects if o.id == 1001)
    assert redone_sound.node_base_params.props[0] == -10.0
    assert redone_sound.node_base_params.props[2] == 100.0

    # 2. Apply AppendVariationIntent
    wav_path = tmp_path / "pool_var.wav"
    make_synthetic_wav(wav_path, duration_s=0.1)

    var_target = ContainerVariationTarget(bank_name="battle.bnk", container_id=3007)
    var_batch = MutationBatch(
        description="Add pool variation",
        items=(BatchItem(target=var_target, source=ExternalFileSource(file_path=wav_path)),),
    )
    outcome2: BatchOutcome = session.apply_batch(var_batch)
    assert outcome2.applied == 1

    current_bank = session.get_loaded_bank("battle.bnk")
    current_cntr = next(o for o in current_bank.hirc.objects if o.id == 3007)
    assert len(current_cntr.children) == 2
    assert len(current_cntr.playlist) == 2

    # Undo variation addition
    session.undo_mutation()

    undone_cntr_bank = session.get_loaded_bank("battle.bnk")
    undone_cntr = next(o for o in undone_cntr_bank.hirc.objects if o.id == 3007)
    assert len(undone_cntr.children) == 1
    assert len(undone_cntr.playlist) == 1

    # Redo variation addition
    session.redo_mutation()

    redone_cntr_bank = session.get_loaded_bank("battle.bnk")
    redone_cntr = next(o for o in redone_cntr_bank.hirc.objects if o.id == 3007)
    assert len(redone_cntr.children) == 2
    assert len(redone_cntr.playlist) == 2


# -----------------------------------------------------------------------------
# Task 13 & 14: UI Inspector Controls
# -----------------------------------------------------------------------------


def test_sound_inspector_view_tuning_controls(qapp: QApplication):
    view = SoundInspectorView()

    # Initial state
    assert view.spin_volume.value() == 0.0
    assert view.spin_pitch.value() == 0.0
    assert not view.btn_apply_tuning.isEnabled()

    # Render with details containing Volume and Pitch properties
    details = NodeInspectorDetails(
        node_key="hirc:2049",
        object_id=2049,
        hex_id="0x00000801",
        object_type="Sound",
        name="battle_rain_heavy",
        properties=(
            InspectorProperty(category="Parameters", label="Volume (dB)", value="-6.5 dB"),
            InspectorProperty(category="Parameters", label="Pitch (cents)", value="150.0 cents"),
        ),
    )
    view.render(details)

    assert view.spin_volume.value() == -6.5
    assert view.spin_pitch.value() == 150.0
    assert view.btn_apply_tuning.isEnabled()

    # Test signal emission on Apply Tuning click
    emitted: list[tuple[int, float, float]] = []
    view.node_params_changed.connect(lambda sid, v, p: emitted.append((sid, v, p)))

    view.spin_volume.setValue(-12.0)
    view.spin_pitch.setValue(-200.0)
    view.btn_apply_tuning.click()

    assert len(emitted) == 1
    assert emitted[0] == (2049, -12.0, -200.0)

    # Render None resets controls and disables button
    view.render(None)
    assert view.spin_volume.value() == 0.0
    assert view.spin_pitch.value() == 0.0
    assert not view.btn_apply_tuning.isEnabled()


def test_container_inspector_view_add_variation_button(qapp: QApplication):
    view = ContainerInspectorView()

    # Initially hidden
    assert view.btn_add_variation.isHidden()

    # Render with Switch container (button should remain hidden)
    sw_details = NodeInspectorDetails(
        node_key="hirc:3001",
        object_id=3001,
        hex_id="0x00000BB9",
        object_type="SwitchCntr",
        name="terrain_switch",
        switch_semantics=SwitchContainerSemantics(
            group_id=1,
            group_name="Terrain",
            group_type=0,
            default_switch_id=2,
            default_switch_name="Grass",
        ),
    )
    view.render(sw_details)
    assert view.btn_add_variation.isHidden()

    # Render with RanSeq container (button should become visible)
    ran_seq_details = NodeInspectorDetails(
        node_key="hirc:3002",
        object_id=3002,
        hex_id="0x00000BBA",
        object_type="RanSeqCntr",
        name="shout_random_pool",
        ran_seq_semantics=RanSeqContainerSemantics(
            mode_str="Random",
            loop_count=1,
            transition_time_ms=1000.0,
            avoid_repeat_count=1,
        ),
    )
    view.render(ran_seq_details)
    assert not view.btn_add_variation.isHidden()

    # Test signal emission
    emitted: list[tuple[int, str]] = []
    view.append_variation_requested.connect(lambda cid, path: emitted.append((cid, path)))

    # Trigger programmatically
    view.append_variation_requested.emit(3002, "C:/audio/variation3.wav")
    assert len(emitted) == 1
    assert emitted[0] == (3002, "C:/audio/variation3.wav")

    # Render None hides button
    view.render(None)
    assert view.btn_add_variation.isHidden()


def test_inspector_panel_signal_forwarding(qapp: QApplication):
    panel = InspectorPanel()

    node_params_emitted: list[tuple[int, float, float]] = []
    append_var_emitted: list[tuple[int, str]] = []

    panel.node_params_changed.connect(lambda sid, v, p: node_params_emitted.append((sid, v, p)))
    panel.append_variation_requested.connect(
        lambda cid, path: append_var_emitted.append((cid, path))
    )

    # Forwarding sound_view node_params_changed
    panel.sound_view.node_params_changed.emit(1001, -3.0, 50.0)
    assert len(node_params_emitted) == 1
    assert node_params_emitted[0] == (1001, -3.0, 50.0)

    # Forwarding container_view append_variation_requested
    panel.container_view.append_variation_requested.emit(3001, "test.wav")
    assert len(append_var_emitted) == 1
    assert append_var_emitted[0] == (3001, "test.wav")
