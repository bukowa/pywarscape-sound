"""
Behavioral Transition Matrix and Unit Tests for Audio Mutation Planner.
Tests try_plan_audio_replacement across all equivalence partitions using real SoundBank instances.
"""

from dataclasses import dataclass
from pathlib import Path

import pytest

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk
from src.bnk.models import (
    AkMusicMarker,
    AkMusicTrackSource,
    AkTrackSrcInfo,
    CAkMusicSegment,
    CAkMusicTrack,
    CAkSound,
    HircObject,
    NodeBaseParams,
)
from src.bnk.wem import build_silent_pcm_wem_bytes
from src.engine.ontology import (
    AudioMutationPlan,
    AudioReplacementSource,
    BatchItem,
    CopyMediaBytesIntent,
    CrossBankCloneSource,
    ExistingMediaReferenceSource,
    ExternalFileSource,
    MarkBankModifiedIntent,
    MediaNodeTarget,
    MusicTrackTarget,
    MutationBatch,
    MutationTarget,
    PlanRejection,
    ReplacementScope,
    SilentStubSource,
    SoundNodeTarget,
    StageLooseWemIntent,
    StageMasterAudioIntent,
    SyncMusicTimelineIntent,
    UpdateMusicTrackNodeIntent,
    UpdateSoundNodeIntent,
    WemId,
)
from src.engine.planner import (
    allocate_unique_wem_id,
    plan_audio_replacement,
    plan_batch,
    try_plan_audio_replacement,
)


def _make_bank(objects: list[HircObject] | None = None) -> SoundBank:
    return SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=list(objects) if objects else []),
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class TransitionCase:
    name: str
    bank: SoundBank
    target: MutationTarget
    source: AudioReplacementSource
    external_file_exists: bool = True
    scope: ReplacementScope = ReplacementScope.OVERWRITE
    forked_wem_id: WemId | None = None
    expected: AudioMutationPlan | PlanRejection


_SOUND_NORMAL = CAkSound(
    id=204996993,
    obj_type=2,
    plugin_id=0x00040001,
    stream_type=2,
    source_id=174224638,
    file_id=174224638,
    node_base_params=NodeBaseParams(),
)

_SOUND_PROCEDURAL = CAkSound(
    id=300000001,
    obj_type=2,
    plugin_id=0x00020002,
    stream_type=0,
    source_id=0,
    file_id=0,
    node_base_params=NodeBaseParams(),
)

_BANK_WITH_NORMAL = _make_bank([_SOUND_NORMAL])
_BANK_WITH_PROCEDURAL = _make_bank([_SOUND_PROCEDURAL])
_EMPTY_BANK = _make_bank([])


CASES: tuple[TransitionCase, ...] = (
    TransitionCase(
        name="sound_node_external_file",
        bank=_BANK_WITH_NORMAL,
        target=SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=204996993),
        source=ExternalFileSource(file_path=Path("source_audio/custom_shout.wav")),
        external_file_exists=True,
        expected=AudioMutationPlan(
            description="Replace Sound 204996993 with external file custom_shout.wav (WEM 174224638)",
            target=SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=204996993),
            source=ExternalFileSource(file_path=Path("source_audio/custom_shout.wav")),
            effects=(
                StageMasterAudioIntent(
                    source_path=Path("source_audio/custom_shout.wav"),
                    destination_rel_path="source_audio/custom_shout.wav",
                    wem_id=174224638,
                ),
                UpdateSoundNodeIntent(
                    bank_name="battle_rain.bnk",
                    sound_id=204996993,
                    new_stream_type=2,
                    new_source_id=174224638,
                    new_file_id=174224638,
                ),
                MarkBankModifiedIntent(bank_name="battle_rain.bnk"),
            ),
        ),
    ),
    TransitionCase(
        name="sound_node_existing_media_reference",
        bank=_BANK_WITH_NORMAL,
        target=SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=204996993),
        source=ExistingMediaReferenceSource(wem_id=987654321),
        expected=AudioMutationPlan(
            description="Retarget Sound 204996993 to existing media 987654321",
            target=SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=204996993),
            source=ExistingMediaReferenceSource(wem_id=987654321),
            effects=(
                UpdateSoundNodeIntent(
                    bank_name="battle_rain.bnk",
                    sound_id=204996993,
                    new_stream_type=2,
                    new_source_id=987654321,
                    new_file_id=987654321,
                ),
                MarkBankModifiedIntent(bank_name="battle_rain.bnk"),
            ),
        ),
    ),
    TransitionCase(
        name="sound_node_silent_stub",
        bank=_BANK_WITH_NORMAL,
        target=SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=204996993),
        source=SilentStubSource(stub_wem_id=1),
        expected=AudioMutationPlan(
            description="Mute Sound 204996993 with silent stub 1",
            target=SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=204996993),
            source=SilentStubSource(stub_wem_id=1),
            effects=(
                UpdateSoundNodeIntent(
                    bank_name="battle_rain.bnk",
                    sound_id=204996993,
                    new_stream_type=2,
                    new_source_id=1,
                    new_file_id=1,
                ),
                MarkBankModifiedIntent(bank_name="battle_rain.bnk"),
            ),
        ),
    ),
    TransitionCase(
        name="media_node_external_file",
        bank=_EMPTY_BANK,
        target=MediaNodeTarget(bank_name="battle_rain.bnk", wem_id=555123),
        source=ExternalFileSource(file_path=Path("source_audio/ambient.wav")),
        external_file_exists=True,
        expected=AudioMutationPlan(
            description="Replace Media WEM 555123 with external file ambient.wav",
            target=MediaNodeTarget(bank_name="battle_rain.bnk", wem_id=555123),
            source=ExternalFileSource(file_path=Path("source_audio/ambient.wav")),
            effects=(
                StageMasterAudioIntent(
                    source_path=Path("source_audio/ambient.wav"),
                    destination_rel_path="source_audio/ambient.wav",
                    wem_id=555123,
                ),
            ),
        ),
    ),
    TransitionCase(
        name="media_node_existing_media_reference",
        bank=_EMPTY_BANK,
        target=MediaNodeTarget(bank_name="battle_rain.bnk", wem_id=555123),
        source=ExistingMediaReferenceSource(wem_id=888777, source_bank="common.bnk"),
        expected=AudioMutationPlan(
            description="Replace Media WEM 555123 with library media 888777",
            target=MediaNodeTarget(bank_name="battle_rain.bnk", wem_id=555123),
            source=ExistingMediaReferenceSource(wem_id=888777, source_bank="common.bnk"),
            effects=(
                CopyMediaBytesIntent(
                    target_wem_id=555123,
                    source_wem_id=888777,
                    source_bank_name="common.bnk",
                ),
            ),
        ),
    ),
    TransitionCase(
        name="media_node_silent_stub",
        bank=_EMPTY_BANK,
        target=MediaNodeTarget(bank_name="battle_rain.bnk", wem_id=555123),
        source=SilentStubSource(stub_wem_id=1),
        expected=AudioMutationPlan(
            description="Mute Media WEM 555123 with silent stub",
            target=MediaNodeTarget(bank_name="battle_rain.bnk", wem_id=555123),
            source=SilentStubSource(stub_wem_id=1),
            effects=(
                StageLooseWemIntent(
                    wem_id=555123,
                    wem_bytes=build_silent_pcm_wem_bytes(duration_ms=50, sample_rate=32000),
                ),
            ),
        ),
    ),
    TransitionCase(
        name="rejection_sound_not_found",
        bank=_EMPTY_BANK,
        target=SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=999999),
        source=SilentStubSource(),
        expected=PlanRejection(
            code="SOUND_NOT_FOUND",
            reason="Sound 999999 not found in bank battle_rain.bnk",
        ),
    ),
    TransitionCase(
        name="rejection_procedural_sound",
        bank=_BANK_WITH_PROCEDURAL,
        target=SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=300000001),
        source=SilentStubSource(),
        expected=PlanRejection(
            code="PROCEDURAL_SOUND",
            reason="Cannot replace procedural plugin sound 300000001",
        ),
    ),
    TransitionCase(
        name="rejection_file_not_found",
        bank=_BANK_WITH_NORMAL,
        target=SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=204996993),
        source=ExternalFileSource(file_path=Path("non_existent_audio.wav")),
        external_file_exists=False,
        expected=PlanRejection(
            code="FILE_NOT_FOUND",
            reason="External audio file not found: non_existent_audio.wav",
        ),
    ),
    TransitionCase(
        name="sound_node_isolate_explicit_forked_wem",
        bank=_BANK_WITH_NORMAL,
        target=SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=204996993),
        source=ExternalFileSource(file_path=Path("source_audio/custom_shout.wav")),
        external_file_exists=True,
        scope=ReplacementScope.ISOLATE,
        forked_wem_id=888999,
        expected=AudioMutationPlan(
            description="Isolate and replace Sound 204996993 with external file custom_shout.wav (forked WEM 888999)",
            target=SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=204996993),
            source=ExternalFileSource(file_path=Path("source_audio/custom_shout.wav")),
            effects=(
                StageMasterAudioIntent(
                    source_path=Path("source_audio/custom_shout.wav"),
                    destination_rel_path="source_audio/custom_shout.wav",
                    wem_id=888999,
                ),
                UpdateSoundNodeIntent(
                    bank_name="battle_rain.bnk",
                    sound_id=204996993,
                    new_stream_type=2,
                    new_source_id=888999,
                    new_file_id=888999,
                ),
                MarkBankModifiedIntent(bank_name="battle_rain.bnk"),
            ),
        ),
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_try_plan_audio_replacement(case: TransitionCase) -> None:
    actual = try_plan_audio_replacement(
        bank=case.bank,
        target=case.target,
        source=case.source,
        scope=case.scope,
        forked_wem_id=case.forked_wem_id,
        external_file_exists=case.external_file_exists,
    )
    assert actual == case.expected


def test_plan_external_file_replacement(tmp_path: Path):
    audio_file = tmp_path / "custom_shout.wav"
    audio_file.write_bytes(b"RIFFdummydata")

    sound = CAkSound(
        id=204996993,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=2,
        source_id=174224638,
        file_id=174224638,
        node_base_params=NodeBaseParams(),
    )
    bank = _make_bank([sound])

    target = SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=204996993)
    source = ExternalFileSource(file_path=audio_file)

    plan = plan_audio_replacement(bank=bank, target=target, source=source)

    assert plan.target == target
    assert plan.source == source
    assert len(plan.effects) >= 3

    # Check stage master audio
    stage_master = next(e for e in plan.effects if isinstance(e, StageMasterAudioIntent))
    assert stage_master.source_path == audio_file
    assert stage_master.destination_rel_path == "source_audio/custom_shout.wav"

    # Check update sound node
    update_node = next(e for e in plan.effects if isinstance(e, UpdateSoundNodeIntent))
    assert update_node.bank_name == "battle_rain.bnk"
    assert update_node.sound_id == 204996993
    assert update_node.new_stream_type == 2
    assert update_node.new_file_id == stage_master.wem_id

    # Check mark bank modified
    assert any(
        isinstance(e, MarkBankModifiedIntent) and e.bank_name == "battle_rain.bnk"
        for e in plan.effects
    )


def test_plan_existing_media_reference():
    sound = CAkSound(
        id=204996993,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=0,  # Originally embedded
        source_id=55555,
        file_id=55555,
        node_base_params=NodeBaseParams(),
    )
    bank = _make_bank([sound])

    target = SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=204996993)
    source = ExistingMediaReferenceSource(wem_id=987654321)

    plan = plan_audio_replacement(bank=bank, target=target, source=source)

    # Should NOT stage any master audio or loose WEM files
    assert not any(isinstance(e, StageMasterAudioIntent) for e in plan.effects)
    assert not any(isinstance(e, StageLooseWemIntent) for e in plan.effects)

    # Must update node to streamed with target WEM ID
    update_node = next(e for e in plan.effects if isinstance(e, UpdateSoundNodeIntent))
    assert update_node.sound_id == 204996993
    assert update_node.new_stream_type == 2
    assert update_node.new_source_id == 987654321
    assert update_node.new_file_id == 987654321


def test_plan_silent_stub_mute():
    sound = CAkSound(
        id=204996993,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=2,
        source_id=174224638,
        file_id=174224638,
        node_base_params=NodeBaseParams(),
    )
    bank = _make_bank([sound])

    target = SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=204996993)
    source = SilentStubSource(stub_wem_id=1)

    plan = plan_audio_replacement(bank=bank, target=target, source=source)

    update_node = next(e for e in plan.effects if isinstance(e, UpdateSoundNodeIntent))
    assert update_node.sound_id == 204996993
    assert update_node.new_stream_type == 2
    assert update_node.new_source_id == 1
    assert update_node.new_file_id == 1
    assert any(isinstance(e, MarkBankModifiedIntent) for e in plan.effects)


def test_plan_missing_sound_raises():
    bank = _make_bank([])
    target = SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=999999)
    source = SilentStubSource()

    with pytest.raises(KeyError, match="not found in bank"):
        plan_audio_replacement(bank=bank, target=target, source=source)


def test_plan_missing_external_file_raises():
    sound = CAkSound(id=100, obj_type=2, node_base_params=NodeBaseParams())
    bank = _make_bank([sound])
    target = SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=100)
    source = ExternalFileSource(file_path=Path("non_existent_audio.wav"))

    with pytest.raises(FileNotFoundError):
        plan_audio_replacement(bank=bank, target=target, source=source)


def test_plan_procedural_sound_raises():
    sound = CAkSound(
        id=300000001,
        obj_type=2,
        plugin_id=0x00020002,
        stream_type=0,
        source_id=0,
        file_id=0,
        node_base_params=NodeBaseParams(),
    )
    bank = _make_bank([sound])
    target = SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=300000001)
    source = SilentStubSource()

    with pytest.raises(ValueError, match="Cannot replace procedural plugin sound"):
        plan_audio_replacement(bank=bank, target=target, source=source)


def test_allocate_unique_wem_id_empty_set_default():
    wid = allocate_unique_wem_id(set())
    assert wid == 100001
    assert 100000 < wid <= 0x7FFFFFFF


def test_allocate_unique_wem_id_valid_preferred_seed():
    preferred = 174224638
    wid = allocate_unique_wem_id(set(), preferred_seed=preferred)
    assert wid == preferred


def test_allocate_unique_wem_id_colliding_preferred_seed():
    colliding = 174224638
    existing = {colliding}
    wid = allocate_unique_wem_id(existing, preferred_seed=colliding)
    assert wid != colliding
    assert wid not in existing
    assert 100000 < wid <= 0x7FFFFFFF


def test_allocate_unique_wem_id_invalid_seed_clamped():
    for bad_seed in (None, 0, -100, 50, 100000, 0x80000000):
        wid = allocate_unique_wem_id(set(), preferred_seed=bad_seed)
        assert 100000 < wid <= 0x7FFFFFFF


def test_allocate_unique_wem_id_dense_cluster():
    cluster = set(range(100000, 100100))
    wid = allocate_unique_wem_id(cluster, preferred_seed=100001)
    assert wid not in cluster
    assert 100000 < wid <= 0x7FFFFFFF


def test_allocate_unique_wem_id_bulk_uniqueness():
    allocated: set[int] = set()
    for _ in range(500):
        val = allocate_unique_wem_id(allocated)
        assert val not in allocated
        assert 100000 < val <= 0x7FFFFFFF
        allocated.add(val)
    assert len(allocated) == 500


def test_plan_isolate_allocates_unique_wem_and_leaves_siblings(tmp_path: Path):
    audio_file = tmp_path / "custom.wav"
    audio_file.write_bytes(b"RIFFdummydata")

    shared_wem = 174224638
    sound1 = CAkSound(
        id=101,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=0,
        source_id=shared_wem,
        file_id=shared_wem,
        node_base_params=NodeBaseParams(),
    )
    sound2 = CAkSound(
        id=102,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=0,
        source_id=shared_wem,
        file_id=shared_wem,
        node_base_params=NodeBaseParams(),
    )
    bank = _make_bank([sound1, sound2])

    target = SoundNodeTarget(bank_name="test.bnk", sound_id=101)
    source = ExternalFileSource(file_path=audio_file)

    plan = plan_audio_replacement(
        bank=bank,
        target=target,
        source=source,
        scope=ReplacementScope.ISOLATE,
    )

    # 1. Staged WEM must not equal the shared WEM
    stage_master = next(e for e in plan.effects if isinstance(e, StageMasterAudioIntent))
    assert stage_master.wem_id != shared_wem
    assert 100000 < stage_master.wem_id <= 0x7FFFFFFF

    # 2. Only sound1 is mutated
    updates = [e for e in plan.effects if isinstance(e, UpdateSoundNodeIntent)]
    assert len(updates) == 1
    assert updates[0].sound_id == 101
    assert updates[0].new_source_id == stage_master.wem_id
    assert updates[0].new_file_id == stage_master.wem_id
    assert updates[0].new_stream_type == 2


def test_plan_overwrite_promotes_embedded_siblings(tmp_path: Path):
    audio_file = tmp_path / "custom.wav"
    audio_file.write_bytes(b"RIFFdummydata")

    shared_wem = 174224638
    sound1 = CAkSound(
        id=101,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=0,  # embedded
        source_id=shared_wem,
        file_id=shared_wem,
        node_base_params=NodeBaseParams(),
    )
    sound2 = CAkSound(
        id=102,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=0,  # embedded
        source_id=shared_wem,
        file_id=shared_wem,
        node_base_params=NodeBaseParams(),
    )
    sound3 = CAkSound(
        id=103,
        obj_type=2,
        plugin_id=0x00010001,  # already streamed and already PCM
        stream_type=2,
        source_id=shared_wem,
        file_id=shared_wem,
        node_base_params=NodeBaseParams(),
    )
    bank = _make_bank([sound1, sound2, sound3])

    target = SoundNodeTarget(bank_name="test.bnk", sound_id=101)
    source = ExternalFileSource(file_path=audio_file)

    plan = plan_audio_replacement(
        bank=bank,
        target=target,
        source=source,
        scope=ReplacementScope.OVERWRITE,
    )

    stage_master = next(e for e in plan.effects if isinstance(e, StageMasterAudioIntent))
    assert stage_master.wem_id == shared_wem

    updates = [e for e in plan.effects if isinstance(e, UpdateSoundNodeIntent)]
    updated_sound_ids = {u.sound_id for u in updates}

    # sound1 (target) and sound2 (embedded sibling) must be updated to stream_type = 2
    assert 101 in updated_sound_ids
    assert 102 in updated_sound_ids
    # sound3 is already streamed, so does not need an UpdateSoundNodeIntent
    assert 103 not in updated_sound_ids
    assert len(updates) == 2


def test_plan_batch_respects_batch_item_scope(tmp_path: Path):
    audio_file = tmp_path / "custom.wav"
    audio_file.write_bytes(b"RIFFdummydata")

    sound = CAkSound(
        id=101,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=2,
        source_id=55555,
        file_id=55555,
        node_base_params=NodeBaseParams(),
    )
    bank = _make_bank([sound])

    target = SoundNodeTarget(bank_name="test.bnk", sound_id=101)
    source = ExternalFileSource(file_path=audio_file)

    batch = MutationBatch(
        description="Isolate batch",
        items=(
            BatchItem(
                target=target,
                source=source,
                scope=ReplacementScope.ISOLATE,
                forked_wem_id=777888,
            ),
        ),
    )

    batch_plan = plan_batch(banks={"test.bnk": bank}, batch=batch)
    assert len(batch_plan.plans) == 1
    assert not batch_plan.rejections

    plan = batch_plan.plans[0]
    stage_master = next(e for e in plan.effects if isinstance(e, StageMasterAudioIntent))
    assert stage_master.wem_id == 777888


def test_plan_overwrite_streamed_vorbis_sound_updates_plugin_id_to_pcm(tmp_path: Path):
    audio_file = tmp_path / "custom.wav"
    audio_file.write_bytes(b"RIFFdummydata")

    sound = CAkSound(
        id=201,
        obj_type=2,
        plugin_id=0x00040001,  # Vorbis
        stream_type=2,  # Streamed
        source_id=99999,
        file_id=99999,
        node_base_params=NodeBaseParams(),
    )
    bank = _make_bank([sound])
    target = SoundNodeTarget(bank_name="test.bnk", sound_id=201)
    source = ExternalFileSource(file_path=audio_file)

    plan = plan_audio_replacement(
        bank=bank,
        target=target,
        source=source,
        scope=ReplacementScope.OVERWRITE,
    )
    updates = [e for e in plan.effects if isinstance(e, UpdateSoundNodeIntent)]
    assert len(updates) == 1
    assert updates[0].sound_id == 201
    assert updates[0].new_plugin_id == 0x00010001
    assert updates[0].new_stream_type == 2
    assert any(isinstance(e, MarkBankModifiedIntent) for e in plan.effects)


def test_plan_music_track_isolate(tmp_path: Path):
    audio_file = tmp_path / "track_custom.wav"
    audio_file.write_bytes(b"RIFFdummydata")

    seg = CAkMusicSegment(
        id=3001,
        child_ids=[3002],
        duration=10000.0,
        markers=[
            AkMusicMarker(id=1, position=0.0, name="<Entry>"),
            AkMusicMarker(id=2, position=10000.0, name="<Exit>"),
        ],
    )
    track = CAkMusicTrack(
        id=3002,
        sources=[
            AkMusicTrackSource(
                plugin_id=0x00040001,
                stream_type=2,
                source_id=11111,
                file_id=11111,
            ),
            AkMusicTrackSource(
                plugin_id=0x00040001,
                stream_type=2,
                source_id=22222,
                file_id=22222,
            ),
        ],
        playlist=[
            AkTrackSrcInfo(track_id=3002, source_id=11111, src_duration=10000.0),
            AkTrackSrcInfo(track_id=3002, source_id=22222, src_duration=10000.0),
        ],
    )
    bank = _make_bank([seg, track])
    target = MusicTrackTarget(bank_name="test.bnk", track_id=3002, source_index=1)
    source = ExternalFileSource(file_path=audio_file)

    plan = plan_audio_replacement(
        bank=bank,
        target=target,
        source=source,
        scope=ReplacementScope.ISOLATE,
        forked_wem_id=555444,
    )
    assert not isinstance(plan, PlanRejection)
    stage = next(e for e in plan.effects if isinstance(e, StageMasterAudioIntent))
    assert stage.wem_id == 555444
    track_update = next(e for e in plan.effects if isinstance(e, UpdateMusicTrackNodeIntent))
    assert track_update.track_id == 3002
    assert track_update.source_index == 1
    assert track_update.new_source_id == 555444
    assert track_update.new_plugin_id == 0x00010001
    timeline_sync = next(e for e in plan.effects if isinstance(e, SyncMusicTimelineIntent))
    assert timeline_sync.track_id == 3002
    assert timeline_sync.parent_segment_id == 3001
    assert any(isinstance(e, MarkBankModifiedIntent) for e in plan.effects)


def test_plan_music_track_overwrite_with_siblings(tmp_path: Path):
    audio_file = tmp_path / "track_custom.wav"
    audio_file.write_bytes(b"RIFFdummydata")

    shared_wem = 888111
    seg = CAkMusicSegment(id=4001, child_ids=[4002, 4003], duration=8000.0)
    track1 = CAkMusicTrack(
        id=4002,
        sources=[
            AkMusicTrackSource(
                plugin_id=0x00040001, stream_type=2, source_id=shared_wem, file_id=shared_wem
            )
        ],
        playlist=[AkTrackSrcInfo(track_id=4002, source_id=shared_wem, src_duration=8000.0)],
    )
    track2 = CAkMusicTrack(
        id=4003,
        sources=[
            AkMusicTrackSource(
                plugin_id=0x00040001, stream_type=2, source_id=shared_wem, file_id=shared_wem
            )
        ],
        playlist=[AkTrackSrcInfo(track_id=4003, source_id=shared_wem, src_duration=8000.0)],
    )
    sibling_sound = CAkSound(
        id=4004,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=2,
        source_id=shared_wem,
        file_id=shared_wem,
        node_base_params=NodeBaseParams(),
    )
    bank = _make_bank([seg, track1, track2, sibling_sound])
    target = MusicTrackTarget(bank_name="test.bnk", track_id=4002, source_index=0)
    source = ExternalFileSource(file_path=audio_file)

    plan = plan_audio_replacement(
        bank=bank,
        target=target,
        source=source,
        scope=ReplacementScope.OVERWRITE,
    )
    assert not isinstance(plan, PlanRejection)
    stage = next(e for e in plan.effects if isinstance(e, StageMasterAudioIntent))
    assert stage.wem_id == shared_wem

    track_updates = [e for e in plan.effects if isinstance(e, UpdateMusicTrackNodeIntent)]
    assert {u.track_id for u in track_updates} == {4002, 4003}
    for u in track_updates:
        assert u.new_plugin_id == 0x00010001

    sound_updates = [e for e in plan.effects if isinstance(e, UpdateSoundNodeIntent)]
    assert len(sound_updates) == 1
    assert sound_updates[0].sound_id == 4004
    assert sound_updates[0].new_plugin_id == 0x00010001


def test_plan_music_track_silent_stub():
    seg = CAkMusicSegment(id=5001, child_ids=[5002], duration=6000.0)
    track = CAkMusicTrack(
        id=5002,
        sources=[
            AkMusicTrackSource(plugin_id=0x00040001, stream_type=2, source_id=123, file_id=123)
        ],
        playlist=[AkTrackSrcInfo(track_id=5002, source_id=123, src_duration=6000.0)],
    )
    bank = _make_bank([seg, track])
    target = MusicTrackTarget(bank_name="test.bnk", track_id=5002, source_index=0)
    source = SilentStubSource(stub_wem_id=999900)

    plan = plan_audio_replacement(
        bank=bank,
        target=target,
        source=source,
        scope=ReplacementScope.OVERWRITE,
    )
    assert not isinstance(plan, PlanRejection)
    loose = next(e for e in plan.effects if isinstance(e, StageLooseWemIntent))
    assert loose.wem_id == 999900
    timeline = next(e for e in plan.effects if isinstance(e, SyncMusicTimelineIntent))
    assert timeline.new_duration_ms == 50.0


def test_plan_music_track_rejections():
    seg = CAkMusicSegment(id=6001, child_ids=[6002])
    track = CAkMusicTrack(
        id=6002,
        sources=[AkMusicTrackSource(source_id=10, file_id=10)],
    )
    bank = _make_bank([seg, track])

    # 1. Missing track
    rej1 = try_plan_audio_replacement(
        bank=bank,
        target=MusicTrackTarget(bank_name="test.bnk", track_id=999999),
        source=SilentStubSource(stub_wem_id=1),
    )
    assert isinstance(rej1, PlanRejection)
    assert rej1.code == "TARGET_NOT_FOUND"
    with pytest.raises(KeyError):
        plan_audio_replacement(
            bank=bank,
            target=MusicTrackTarget(bank_name="test.bnk", track_id=999999),
            source=SilentStubSource(stub_wem_id=1),
        )

    # 2. Out-of-bounds source_index
    rej2 = try_plan_audio_replacement(
        bank=bank,
        target=MusicTrackTarget(bank_name="test.bnk", track_id=6002, source_index=5),
        source=SilentStubSource(stub_wem_id=1),
    )
    assert isinstance(rej2, PlanRejection)
    assert rej2.code == "SOURCE_NOT_FOUND"
    with pytest.raises(IndexError):
        plan_audio_replacement(
            bank=bank,
            target=MusicTrackTarget(bank_name="test.bnk", track_id=6002, source_index=5),
            source=SilentStubSource(stub_wem_id=1),
        )

    # 3. CrossBankCloneSource unsupported
    rej3 = try_plan_audio_replacement(
        bank=bank,
        target=MusicTrackTarget(bank_name="test.bnk", track_id=6002, source_index=0),
        source=CrossBankCloneSource(source_bank_name="other.bnk", source_node_id=100),
    )
    assert isinstance(rej3, PlanRejection)
    assert rej3.code == "UNSUPPORTED_SOURCE"
    with pytest.raises(NotImplementedError):
        plan_audio_replacement(
            bank=bank,
            target=MusicTrackTarget(bank_name="test.bnk", track_id=6002, source_index=0),
            source=CrossBankCloneSource(source_bank_name="other.bnk", source_node_id=100),
        )


def test_plan_with_reserved_wem_ids_avoids_collisions(tmp_path: Path):
    audio_file = tmp_path / "custom.wav"
    audio_file.write_bytes(b"RIFFdummydata")

    sound = CAkSound(
        id=701,
        obj_type=2,
        plugin_id=0x00010001,
        stream_type=2,
        source_id=100,
        file_id=100,
        node_base_params=NodeBaseParams(),
    )
    bank = _make_bank([sound])
    target = SoundNodeTarget(bank_name="test.bnk", sound_id=701)
    source = ExternalFileSource(file_path=audio_file)

    # Next pseudo-random seed or ID might be 101. Let's reserve a large set of IDs including candidates.
    reserved = {100, 101, 102, 103, 104, 105}
    plan = plan_audio_replacement(
        bank=bank,
        target=target,
        source=source,
        scope=ReplacementScope.ISOLATE,
        reserved_wem_ids=reserved,
    )
    assert not isinstance(plan, PlanRejection)
    stage = next(e for e in plan.effects if isinstance(e, StageMasterAudioIntent))
    assert stage.wem_id not in reserved
