"""
Unit tests for batch mutation ontology and transactions.
Verifies immutability, slotted memory efficiency, and structural invariants.
"""

import wave
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk
from src.bnk.models import CAkSound, NodeBaseParams
from src.engine.ontology import (
    AudioMutationPlan,
    BatchItem,
    BatchPlan,
    ExistingMediaReferenceSource,
    ExternalFileSource,
    MutationBatch,
    MutationRecord,
    MutationTransaction,
    PlanRejection,
    SilentStubSource,
    SoundNodeTarget,
    StageMasterAudioIntent,
    UpdateSoundNodeIntent,
)
from src.engine.planner import plan_batch
from src.engine.session import WorkspaceSession
from src.workspace.project import AudioProject


def test_batch_ontology_immutability():
    target = SoundNodeTarget(bank_name="battle.bnk", sound_id=101)
    source = SilentStubSource(stub_wem_id=1)
    item = BatchItem(target=target, source=source)
    batch = MutationBatch(description="Mute 101", items=(item,))

    assert batch.description == "Mute 101"
    assert len(batch.items) == 1
    assert batch.items[0] == item


def test_batch_item_attributes_and_immutability():
    target = SoundNodeTarget(bank_name="battle.bnk", sound_id=101)
    source = SilentStubSource(stub_wem_id=1)

    # Keyword instantiation
    item_kw = BatchItem(target=target, source=source)
    assert item_kw.target == target
    assert item_kw.source == source

    # Positional instantiation
    item_pos = BatchItem(target, source)
    assert item_pos == item_kw

    # Frozen immutability
    with pytest.raises(FrozenInstanceError):
        item_kw.target = SoundNodeTarget(bank_name="other.bnk", sound_id=202)  # type: ignore

    # Slotted (no __dict__)
    assert not hasattr(item_kw, "__dict__")


def test_mutation_batch_defaults_and_immutability():
    # Default items empty tuple
    batch_default = MutationBatch(description="Empty Batch")
    assert batch_default.description == "Empty Batch"
    assert batch_default.items == ()

    target = SoundNodeTarget(bank_name="battle.bnk", sound_id=101)
    source = SilentStubSource(stub_wem_id=1)
    item = BatchItem(target=target, source=source)

    # Positional instantiation
    batch_pos = MutationBatch("Single Item Batch", (item,))
    assert batch_pos.description == "Single Item Batch"
    assert batch_pos.items == (item,)

    # Frozen immutability
    with pytest.raises(FrozenInstanceError):
        batch_pos.description = "New description"  # type: ignore

    # Slotted (no __dict__)
    assert not hasattr(batch_pos, "__dict__")


def test_batch_plan_defaults_and_immutability():
    # Defaults
    plan_default = BatchPlan()
    assert plan_default.plans == ()
    assert plan_default.rejections == ()

    target = SoundNodeTarget(bank_name="battle.bnk", sound_id=101)
    source = SilentStubSource(stub_wem_id=1)
    item = BatchItem(target=target, source=source)

    mutation_plan = AudioMutationPlan(
        description="Mute 101",
        target=target,
        source=source,
        effects=(),
    )
    rejection = PlanRejection(code="NOT_FOUND", reason="Node not found")

    # Positional instantiation
    bp_pos = BatchPlan((mutation_plan,), ((item, rejection),))
    assert bp_pos.plans == (mutation_plan,)
    assert bp_pos.rejections == ((item, rejection),)

    # Keyword instantiation
    bp_kw = BatchPlan(plans=(mutation_plan,), rejections=((item, rejection),))
    assert bp_kw == bp_pos

    # Frozen immutability
    with pytest.raises(FrozenInstanceError):
        bp_kw.plans = ()  # type: ignore

    # Slotted (no __dict__)
    assert not hasattr(bp_kw, "__dict__")


def test_mutation_transaction_defaults_and_immutability():
    # Default records empty tuple
    tx_default = MutationTransaction(description="Tx 1")
    assert tx_default.description == "Tx 1"
    assert tx_default.records == ()

    record = MutationRecord(
        bank_name="battle.bnk",
        node_key="sound:101",
        description="Replaced with silent stub",
        before_bank_bytes=b"old",
        after_bank_bytes=b"new",
    )

    # Keyword instantiation
    tx_kw = MutationTransaction(description="Tx with record", records=(record,))
    assert tx_kw.description == "Tx with record"
    assert tx_kw.records == (record,)

    # Positional instantiation
    tx_pos = MutationTransaction("Tx with record", (record,))
    assert tx_pos == tx_kw

    # Frozen immutability
    with pytest.raises(FrozenInstanceError):
        tx_kw.description = "New Tx"  # type: ignore

    # Slotted (no __dict__)
    assert not hasattr(tx_kw, "__dict__")


@pytest.fixture
def sample_wav(tmp_path: Path) -> Path:
    wav_file = tmp_path / "sample_voice.wav"
    num_samples = int(32000 * (50 / 1000.0))
    with wave.open(str(wav_file), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(32000)
        wf.writeframes(b"\x00\x00" * num_samples)
    return wav_file


@pytest.fixture
def mock_bank() -> SoundBank:
    sound1 = CAkSound(
        id=201,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=2,
        source_id=1001,
        file_id=1001,
        node_base_params=NodeBaseParams(),
    )
    sound2 = CAkSound(
        id=202,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=2,
        source_id=1002,
        file_id=1002,
        node_base_params=NodeBaseParams(),
    )
    return SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[sound1, sound2]),
    )


@pytest.fixture
def mock_bank2() -> SoundBank:
    sound3 = CAkSound(
        id=301,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=2,
        source_id=1003,
        file_id=1003,
        node_base_params=NodeBaseParams(),
    )
    return SoundBank(
        header=BkhdChunk(bank_id=2, version=112),
        hirc=HircChunk(objects=[sound3]),
    )


def test_plan_batch_encode_once_deduplication(
    sample_wav: Path, mock_bank: SoundBank, mock_bank2: SoundBank
):
    # Two targets in the same bank replaced by the SAME external file,
    # PLUS a third target in a different bank replaced by the same file
    target1 = SoundNodeTarget(bank_name="test.bnk", sound_id=201)
    target2 = SoundNodeTarget(bank_name="test.bnk", sound_id=202)
    target3 = SoundNodeTarget(bank_name="other.bnk", sound_id=301)
    source = ExternalFileSource(file_path=sample_wav)

    batch = MutationBatch(
        description="Replace 3 nodes across 2 banks",
        items=(
            BatchItem(target=target1, source=source),
            BatchItem(target=target2, source=source),
            BatchItem(target=target3, source=source),
        ),
    )

    batch_plan = plan_batch(banks={"test.bnk": mock_bank, "other.bnk": mock_bank2}, batch=batch)
    assert len(batch_plan.rejections) == 0
    assert len(batch_plan.plans) == 3

    plan1 = batch_plan.plans[0]
    plan2 = batch_plan.plans[1]
    plan3 = batch_plan.plans[2]

    # Plan 1 must contain StageMasterAudioIntent
    stage_intents = [e for e in plan1.effects if isinstance(e, StageMasterAudioIntent)]
    assert len(stage_intents) == 1
    allocated_wem_id = stage_intents[0].wem_id

    # Plan 2 (same bank) must NOT stage master audio; it must retarget to ExistingMediaReferenceSource
    assert not any(isinstance(e, StageMasterAudioIntent) for e in plan2.effects)
    assert isinstance(plan2.source, ExistingMediaReferenceSource)
    assert plan2.source.wem_id == allocated_wem_id

    # Plan 3 (different bank) must NOT stage master audio; it must retarget to ExistingMediaReferenceSource
    assert not any(isinstance(e, StageMasterAudioIntent) for e in plan3.effects)
    assert isinstance(plan3.source, ExistingMediaReferenceSource)
    assert plan3.source.wem_id == allocated_wem_id

    update_effects3 = [e for e in plan3.effects if isinstance(e, UpdateSoundNodeIntent)]
    assert len(update_effects3) == 1
    assert update_effects3[0].bank_name == "other.bnk"
    assert update_effects3[0].sound_id == 301
    assert update_effects3[0].new_source_id == allocated_wem_id
    assert update_effects3[0].new_file_id == allocated_wem_id


def test_plan_batch_partial_rejections_and_missing_bank(sample_wav: Path):
    sound_normal = CAkSound(
        id=201,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=2,
        source_id=1001,
        file_id=1001,
        node_base_params=NodeBaseParams(),
    )
    sound_procedural = CAkSound(
        id=300000001,
        obj_type=2,
        plugin_id=0x00020002,
        stream_type=0,
        source_id=0,
        file_id=0,
        node_base_params=NodeBaseParams(),
    )
    bank = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[sound_normal, sound_procedural]),
    )

    item_missing_bank = BatchItem(
        target=SoundNodeTarget(bank_name="unloaded.bnk", sound_id=101),
        source=SilentStubSource(),
    )
    item_procedural = BatchItem(
        target=SoundNodeTarget(bank_name="test.bnk", sound_id=300000001),
        source=SilentStubSource(),
    )
    item_sound_not_found = BatchItem(
        target=SoundNodeTarget(bank_name="test.bnk", sound_id=999999),
        source=SilentStubSource(),
    )
    item_valid = BatchItem(
        target=SoundNodeTarget(bank_name="test.bnk", sound_id=201),
        source=SilentStubSource(stub_wem_id=1),
    )

    batch = MutationBatch(
        description="Mixed batch",
        items=(item_missing_bank, item_procedural, item_sound_not_found, item_valid),
    )

    batch_plan = plan_batch(banks={"test.bnk": bank}, batch=batch)

    # Valid item produces plan
    assert len(batch_plan.plans) == 1
    assert batch_plan.plans[0].target.sound_id == 201

    # Rejected items
    assert len(batch_plan.rejections) == 3

    rej_item1, rej1 = batch_plan.rejections[0]
    assert rej_item1 == item_missing_bank
    assert rej1.code == "BANK_NOT_LOADED"
    assert "Bank unloaded.bnk not loaded" in rej1.reason

    rej_item2, rej2 = batch_plan.rejections[1]
    assert rej_item2 == item_procedural
    assert rej2.code == "PROCEDURAL_SOUND"

    rej_item3, rej3 = batch_plan.rejections[2]
    assert rej_item3 == item_sound_not_found
    assert rej3.code == "SOUND_NOT_FOUND"


def test_plan_batch_empty(mock_bank: SoundBank):
    batch = MutationBatch(description="Empty batch", items=())
    batch_plan = plan_batch(banks={"test.bnk": mock_bank}, batch=batch)

    assert batch_plan == BatchPlan(plans=(), rejections=())
    assert len(batch_plan.plans) == 0
    assert len(batch_plan.rejections) == 0


def test_plan_batch_external_files_exist_resolution(mock_bank: SoundBank, tmp_path: Path):
    file_raw = tmp_path / "mock_file.wav"
    target = SoundNodeTarget(bank_name="test.bnk", sound_id=201)
    source = ExternalFileSource(file_path=file_raw)
    batch = MutationBatch(
        description="Test file existence mapping",
        items=(BatchItem(target=target, source=source),),
    )

    # 1. Keyed by raw path with False -> rejection FILE_NOT_FOUND
    res_false_raw = plan_batch(
        banks={"test.bnk": mock_bank},
        batch=batch,
        external_files_exist={file_raw: False},
    )
    assert len(res_false_raw.rejections) == 1
    assert res_false_raw.rejections[0][1].code == "FILE_NOT_FOUND"

    # 2. Keyed by resolved path with False -> rejection FILE_NOT_FOUND
    res_false_canon = plan_batch(
        banks={"test.bnk": mock_bank},
        batch=batch,
        external_files_exist={file_raw.resolve(): False},
    )
    assert len(res_false_canon.rejections) == 1
    assert res_false_canon.rejections[0][1].code == "FILE_NOT_FOUND"

    # 3. Keyed by raw path with True (file doesn't exist on disk) -> produces plan
    assert not file_raw.exists()
    res_true = plan_batch(
        banks={"test.bnk": mock_bank},
        batch=batch,
        external_files_exist={file_raw: True},
    )
    assert len(res_true.plans) == 1
    assert len(res_true.rejections) == 0


def test_cross_bank_identical_file_deduplication(test_project: AudioProject, sample_wav: Path):
    session = WorkspaceSession(project=test_project)
    bank1 = SoundBank()
    bank1.add_sound(
        CAkSound(
            id=101, stream_type=2, source_id=1001, file_id=1001, node_base_params=NodeBaseParams()
        )
    )
    bank2 = SoundBank()
    bank2.add_sound(
        CAkSound(
            id=201, stream_type=2, source_id=2001, file_id=2001, node_base_params=NodeBaseParams()
        )
    )
    session.index_soundbank("bank1.bnk", bank1)
    session.index_soundbank("bank2.bnk", bank2)

    source = ExternalFileSource(file_path=sample_wav)
    batch = MutationBatch(
        description="Cross-bank batch",
        items=(
            BatchItem(target=SoundNodeTarget(bank_name="bank1.bnk", sound_id=101), source=source),
            BatchItem(target=SoundNodeTarget(bank_name="bank2.bnk", sound_id=201), source=source),
        ),
    )
    outcome = session.apply_batch(batch)
    assert outcome.applied == 2
    assert set(outcome.touched_banks) == {"bank1.bnk", "bank2.bnk"}
    assert session.can_undo_mutation is True

    # Exactly 1 WEM staged
    staged = test_project.manifest.staged_wems
    assert len(staged) == 1
    wem_id = staged[0]
    assert (test_project.audio_dir / f"{wem_id}.wem").is_file()

    # Revert all in one undo
    undo_res = session.undo_mutation()
    assert undo_res is not None
    touched, _ = undo_res
    assert set(touched) == {"bank1.bnk", "bank2.bnk"}
    assert not (test_project.audio_dir / f"{wem_id}.wem").is_file()


def test_preview_batch_dry_run_no_io(test_project: AudioProject, sample_wav: Path):
    session = WorkspaceSession(project=test_project)
    bank = SoundBank()
    bank.add_sound(
        CAkSound(
            id=101, stream_type=2, source_id=1001, file_id=1001, node_base_params=NodeBaseParams()
        )
    )
    session.index_soundbank("test.bnk", bank)

    source = ExternalFileSource(file_path=sample_wav)
    batch = MutationBatch(
        description="Dry run batch",
        items=(
            BatchItem(target=SoundNodeTarget(bank_name="test.bnk", sound_id=101), source=source),
            BatchItem(
                target=SoundNodeTarget(bank_name="unloaded.bnk", sound_id=999), source=source
            ),
        ),
    )
    batch_plan = session.preview_batch(batch)
    assert len(batch_plan.plans) == 1
    assert len(batch_plan.rejections) == 1
    assert batch_plan.rejections[0][1].code == "BANK_NOT_LOADED"

    # Zero disk writes or undo stack changes
    assert len(test_project.manifest.staged_wems) == 0
    assert len(test_project.manifest.modified_banks) == 0
    assert session.can_undo_mutation is False


def test_apply_batch_empty_and_partial_rejections(test_project: AudioProject, sample_wav: Path):
    session = WorkspaceSession(project=test_project)
    bank = SoundBank()
    bank.add_sound(
        CAkSound(
            id=101, stream_type=2, source_id=1001, file_id=1001, node_base_params=NodeBaseParams()
        )
    )
    session.index_soundbank("test.bnk", bank)

    # 1. Empty batch
    empty_outcome = session.apply_batch(MutationBatch(description="Empty", items=()))
    assert empty_outcome.applied == 0
    assert empty_outcome.rejections == ()
    assert empty_outcome.touched_banks == ()
    assert session.can_undo_mutation is False

    # 2. Partial rejection: 1 valid, 1 invalid target
    source = ExternalFileSource(file_path=sample_wav)
    partial_batch = MutationBatch(
        description="Partial batch",
        items=(
            BatchItem(target=SoundNodeTarget(bank_name="test.bnk", sound_id=101), source=source),
            BatchItem(target=SoundNodeTarget(bank_name="test.bnk", sound_id=99999), source=source),
        ),
    )
    outcome = session.apply_batch(partial_batch)
    assert outcome.applied == 1
    assert len(outcome.rejections) == 1
    assert outcome.rejections[0][1].code == "SOUND_NOT_FOUND"
    assert outcome.touched_banks == ("test.bnk",)
    assert session.can_undo_mutation is True

    # 3. All rejected batch
    all_rej_batch = MutationBatch(
        description="All rejected",
        items=(
            BatchItem(target=SoundNodeTarget(bank_name="missing.bnk", sound_id=1), source=source),
        ),
    )
    rej_outcome = session.apply_batch(all_rej_batch)
    assert rej_outcome.applied == 0
    assert len(rej_outcome.rejections) == 1
    assert rej_outcome.touched_banks == ()
