"""
Unit and integration tests for Wave 1:
- Task 1: Complete 28 *_data.bnk -> Companion Logic Bank Map & Sibling Promotion
- Task 2: Cross-Bank WEM Reference Discovery Across Unopened Banks
- Task 3: Global WEM ID Collision Avoidance & Baseline Caching
- Task 4: True Per-Slot AST + Media Revert & revert_wem Cascade
- Task 8: Sub-Track WAV Export Support
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.bnk.bank import BkhdChunk, DataChunk, DidxChunk, DidxEntry, HircChunk, SoundBank
from src.bnk.models import (
    AkMusicTrackSource,
    AkTrackSrcInfo,
    CAkMusicSegment,
    CAkMusicTrack,
    CAkSound,
    HircObject,
)
from src.engine.audio_export import (
    _extract_wem_id_from_key,
    _extract_wem_info_from_key,
    export_nodes_to_directory,
)
from src.engine.ontology import (
    BatchItem,
    ExternalFileSource,
    MediaNodeTarget,
    MusicTrackTarget,
    MutationBatch,
    ReplacementScope,
    SoundNodeTarget,
)
from src.engine.session import (
    _COMPANION_LOGIC_BANKS,
    WorkspaceSession,
    _resolve_companion_logic_banks,
)
from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.manifest import DependencyPackInfo
from src.workspace.project import AudioProject
from src.workspace.storage import ProjectStorage
from tests.support.factories import make_synthetic_wav


def _build_test_bank(
    bank_id: int,
    sounds: list[tuple[int, int, int]],  # (sound_id, wem_id, stream_type)
    music_tracks: list[tuple[int, list[tuple[int, int]]]]
    | None = None,  # (track_id, [(wem_id, stream_type)])
    music_segments: list[tuple[int, list[int], float]]
    | None = None,  # (segment_id, [track_ids], duration_ms)
) -> SoundBank:
    hirc_objs: list[HircObject] = []
    didx_entries: list[DidxEntry] = []
    data_buffer = bytearray()
    dummy_payload = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"

    for sound_id, wem_id, st in sounds:
        if st == 0:
            offset = len(data_buffer)
            data_buffer.extend(dummy_payload)
            didx_entries.append(DidxEntry(file_id=wem_id, offset=offset, size=len(dummy_payload)))
            hirc_objs.append(
                CAkSound(
                    id=sound_id,
                    source_id=wem_id,
                    file_id=bank_id,
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
                    file_id=bank_id,
                    stream_type=2,
                    file_offset=0,
                    in_memory_media_size=0,
                )
            )

    if music_tracks:
        for track_id, sources in music_tracks:
            track_sources = [
                AkMusicTrackSource(
                    plugin_id=0x00010001 if st == 2 else 0x00040001,
                    stream_type=st,
                    source_id=wid,
                    file_id=bank_id,
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

    if music_segments:
        for seg_id, child_track_ids, dur in music_segments:
            hirc_objs.append(
                CAkMusicSegment(
                    id=seg_id,
                    child_ids=list(child_track_ids),
                    duration=dur,
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


def _setup_session_environment(
    tmp_path: Path,
    banks: dict[str, SoundBank],
) -> tuple[AudioProject, WorkspaceSession]:
    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "event_data.dat").write_bytes(b"\x00" * 32)

    for b_name, bank in banks.items():
        (cache_dir / b_name).write_bytes(bank.to_bytes())

    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)
    proj_dir = tmp_path / "Wave1Project"
    project = ProjectStorage.create_project(proj_dir, name="Wave1Project", game=GameType.ATTILA)
    project.cache = cache
    session = WorkspaceSession(project=project)
    return project, session


# =============================================================================
# Task 1: Complete 28 *_data.bnk -> Companion Logic Bank Map & Sibling Promotion
# =============================================================================


def test_companion_logic_banks_mapping_and_resolution():
    assert len(_COMPANION_LOGIC_BANKS) == 28

    # Multi-companion banks
    assert _resolve_companion_logic_banks("animation_blood_data.bnk") == (
        "battle_animation.bnk",
        "campaign_animation.bnk",
    )
    assert _resolve_companion_logic_banks("vocalisations_data.bnk") == (
        "battle_vocalisations.bnk",
        "campaign_vocalisations.bnk",
    )

    # Single-companion banks
    assert _resolve_companion_logic_banks("music_data.bnk") == ("global_music.bnk",)
    assert _resolve_companion_logic_banks("battle_data.bnk") == ("battle.bnk",)
    assert _resolve_companion_logic_banks("projectiles_fire_data.bnk") == (
        "battle_projectiles.bnk",
    )

    # Case-insensitive resolution
    assert _resolve_companion_logic_banks("ANIMATION_BLOOD_DATA.BNK") == (
        "battle_animation.bnk",
        "campaign_animation.bnk",
    )
    assert _resolve_companion_logic_banks("music_data") == ("global_music.bnk",)

    # Fallback for unmapped *_data.bnk
    assert _resolve_companion_logic_banks("mod_custom_data.bnk") == ("mod_custom.bnk",)

    # Non-data bank returns empty tuple
    assert _resolve_companion_logic_banks("battle.bnk") == ()


def test_sibling_promotion_loads_companion_logic_banks(tmp_path: Path):
    # Setup data bank with embedded WEM 5001
    data_bank = _build_test_bank(
        bank_id=1,
        sounds=[(10, 5001, 0)],
    )
    # Companion 1: battle_animation.bnk references WEM 5001 as embedded
    battle_anim = _build_test_bank(
        bank_id=2,
        sounds=[(101, 5001, 0)],
    )
    # Companion 2: campaign_animation.bnk references WEM 5001 as embedded
    campaign_anim = _build_test_bank(
        bank_id=3,
        sounds=[(202, 5001, 0)],
    )

    banks = {
        "animation_blood_data.bnk": data_bank,
        "battle_animation.bnk": battle_anim,
        "campaign_animation.bnk": campaign_anim,
    }
    project, session = _setup_session_environment(tmp_path, banks)

    # Only load data bank into session initially
    session.resolve_and_parse_bank("animation_blood_data.bnk")
    assert "battle_animation.bnk" not in session.loaded_banks
    assert "campaign_animation.bnk" not in session.loaded_banks

    # Mutate WEM 5001 in data bank with OVERWRITE scope
    wav_path = make_synthetic_wav(tmp_path / "new_5001.wav")
    batch = MutationBatch(
        description="Overwrite shared WEM 5001 in animation_blood_data",
        items=(
            BatchItem(
                target=MediaNodeTarget(bank_name="animation_blood_data.bnk", wem_id=5001),
                source=ExternalFileSource(file_path=wav_path),
                scope=ReplacementScope.OVERWRITE,
            ),
        ),
    )

    plan = session.preview_batch(batch)
    assert len(plan.plans) > 0 and len(plan.rejections) == 0

    outcome = session.apply_batch(batch)
    assert outcome.applied > 0

    # Both companion logic banks should have been discovered, loaded, and touched
    assert "battle_animation.bnk" in outcome.touched_banks
    assert "campaign_animation.bnk" in outcome.touched_banks

    # Verify both companions were promoted to streamed (stream_type == 2)
    entry_b = session.get_loaded_entry("battle_animation.bnk")
    assert entry_b is not None
    sound_b = next(o for o in entry_b[0].hirc.objects if isinstance(o, CAkSound) and o.id == 101)
    assert sound_b.stream_type == 2

    entry_c = session.get_loaded_entry("campaign_animation.bnk")
    assert entry_c is not None
    sound_c = next(o for o in entry_c[0].hirc.objects if isinstance(o, CAkSound) and o.id == 202)
    assert sound_c.stream_type == 2


# =============================================================================
# Task 2: Cross-Bank WEM Reference Discovery Across Unopened Banks
# =============================================================================


def test_cross_bank_wem_reference_discovery_unopened_banks(tmp_path: Path):
    bank_a = _build_test_bank(
        bank_id=10,
        sounds=[(1001, 7777, 2)],
    )
    bank_b = _build_test_bank(
        bank_id=20,
        sounds=[(2002, 7777, 2)],
    )
    bank_c = _build_test_bank(
        bank_id=30,
        sounds=[(3003, 9999, 2)],
    )

    banks = {
        "bank_a.bnk": bank_a,
        "bank_b.bnk": bank_b,
        "bank_c.bnk": bank_c,
    }
    project, session = _setup_session_environment(tmp_path, banks)

    # Initially NO banks are loaded in session
    assert len(session.loaded_banks) == 0
    assert not session._unopened_scanned_for_refs

    # Discover all project bank names includes all 3 banks from cache
    discovered = session._discover_all_project_bank_names()
    assert "bank_a.bnk" in discovered
    assert "bank_b.bnk" in discovered
    assert "bank_c.bnk" in discovered

    # Query cross-bank references for WEM 7777 across unopened banks
    refs = session.get_cross_bank_wem_references(7777)

    # Should discover both bank_a and bank_b, parse them, and find both referencing nodes
    assert len(refs) == 2
    bank_names_in_refs = {r.bank_name.lower() for r in refs}
    assert bank_names_in_refs == {"bank_a.bnk", "bank_b.bnk"}
    node_ids = {r.node_id for r in refs}
    assert node_ids == {1001, 2002}

    # bank_c should NOT be loaded since it does not reference WEM 7777
    assert "bank_c.bnk" not in session.loaded_banks

    # Reset clears lazy discovery flag and global index
    session.reset()
    assert not session._unopened_scanned_for_refs
    assert session._global_wem_to_banks is None


# =============================================================================
# Task 3: Global WEM ID Collision Avoidance & Baseline Caching
# =============================================================================


def test_global_wem_id_collision_avoidance(tmp_path: Path):
    cache_bank = _build_test_bank(
        bank_id=100,
        sounds=[(1, 100001, 0)],
    )
    banks = {"cache_bank.bnk": cache_bank}
    project, session = _setup_session_environment(tmp_path, banks)

    # 1. Loose .wem in project audio directory
    (project.audio_dir / "200002.wem").write_bytes(b"PROJECT_WEM")

    # 2. Bank in active dependency
    dep_dir = project.get_dependency_dir("dep1.pack") / "audio"
    dep_dir.mkdir(parents=True)
    dep_bank = _build_test_bank(bank_id=200, sounds=[(2, 300003, 0)])
    (dep_dir / "dep_bank.bnk").write_bytes(dep_bank.to_bytes())
    (dep_dir / "400004.wem").write_bytes(b"DEP_LOOSE_WEM")

    project.manifest.dependencies = [
        DependencyPackInfo(name="dep1.pack", source_path="/dep1", priority=0),
    ]

    # Collect reserved IDs
    reserved = session._collect_reserved_wem_ids()

    assert 100001 in reserved  # from cache bank
    assert 200002 in reserved  # from project loose wem
    assert 300003 in reserved  # from dependency bank
    assert 400004 in reserved  # from dependency loose wem

    # Baseline cache is memoized
    assert session._baseline_reserved_wem_ids is not None
    assert session._baseline_reserved_wem_ids == reserved

    # Invalidate on reload_dependencies
    session.reload_dependencies()
    assert session._baseline_reserved_wem_ids is None


# =============================================================================
# Task 4: True Per-Slot AST + Media Revert & revert_wem Cascade
# =============================================================================


def test_revert_node_to_baseline_sound_slot(tmp_path: Path):
    base_bank = _build_test_bank(
        bank_id=50,
        sounds=[(501, 1111, 0), (502, 2222, 0)],
    )
    banks = {"battle.bnk": base_bank}
    project, session = _setup_session_environment(tmp_path, banks)
    session.resolve_and_parse_bank("battle.bnk")

    # Mutate sound 501 with ISOLATE scope (allocates new loose WEM)
    wav_path = make_synthetic_wav(tmp_path / "new_501.wav")
    outcome = session.apply_sound_mutation(
        bank_name="battle.bnk",
        sound_id=501,
        source=ExternalFileSource(file_path=wav_path),
        scope=ReplacementScope.ISOLATE,
        forked_wem_id=9999,
    )
    assert outcome is not None

    # Verify sound 501 is modified to WEM 9999, sound 502 unchanged
    entry = session.get_loaded_entry("battle.bnk")
    assert entry is not None
    s501 = next(o for o in entry[0].hirc.objects if isinstance(o, CAkSound) and o.id == 501)
    assert s501.source_id == 9999
    assert s501.stream_type == 2
    assert 9999 in project.manifest.staged_wems
    assert (project.audio_dir / "9999.wem").is_file()

    # Revert ONLY slot hirc:501 to baseline
    success = session.revert_node_to_baseline("battle.bnk", "hirc:501")
    assert success

    # Verify sound 501 is restored to baseline embedded Vorbis (source_id=1111, stream_type=0)
    entry_rev = session.get_loaded_entry("battle.bnk")
    assert entry_rev is not None
    s501_rev = next(o for o in entry_rev[0].hirc.objects if isinstance(o, CAkSound) and o.id == 501)
    assert s501_rev.source_id == 1111
    assert s501_rev.stream_type == 0

    # Unreferenced staged WEM 9999 should be completely cleaned up
    assert 9999 not in project.manifest.staged_wems
    assert not (project.audio_dir / "9999.wem").is_file()

    # Since all nodes are now identical to baseline, battle.bnk should be reverted completely
    assert not (project.audio_dir / "battle.bnk").is_file()
    assert "battle.bnk" not in [b.lower() for b in project.manifest.modified_banks]


def test_revert_node_to_baseline_music_track_and_segment(tmp_path: Path):
    base_bank = _build_test_bank(
        bank_id=60,
        sounds=[],
        music_tracks=[(601, [(6601, 2)])],
        music_segments=[(6001, [601], 5000.0)],
    )
    banks = {"global_music.bnk": base_bank}
    project, session = _setup_session_environment(tmp_path, banks)
    session.resolve_and_parse_bank("global_music.bnk")

    # Mutate music track 601
    wav_path = make_synthetic_wav(tmp_path / "new_track.wav", duration_s=10.0)
    batch = MutationBatch(
        description="Mutate track 601",
        items=(
            BatchItem(
                target=MusicTrackTarget(bank_name="global_music.bnk", track_id=601, source_index=0),
                source=ExternalFileSource(file_path=wav_path),
                scope=ReplacementScope.ISOLATE,
                forked_wem_id=7701,
            ),
        ),
    )
    outcome = session.apply_batch(batch)
    assert outcome.applied > 0

    entry = session.get_loaded_entry("global_music.bnk")
    assert entry is not None
    seg = next(o for o in entry[0].hirc.objects if isinstance(o, CAkMusicSegment) and o.id == 6001)
    assert seg.duration > 5000.0  # updated duration

    # Revert music track slot hirc:601:src:0 to baseline
    reverted = session.revert_node_to_baseline("global_music.bnk", "hirc:601:src:0")
    assert reverted

    # Verify track and parent segment duration restored to 5000.0 ms
    entry_rev = session.get_loaded_entry("global_music.bnk")
    assert entry_rev is not None
    seg_rev = next(
        o for o in entry_rev[0].hirc.objects if isinstance(o, CAkMusicSegment) and o.id == 6001
    )
    assert seg_rev.duration == 5000.0


def test_revert_wem_restores_referencing_hirc_nodes(tmp_path: Path):
    base_bank = _build_test_bank(
        bank_id=70,
        sounds=[(701, 3333, 0)],  # baseline is embedded Vorbis (stream_type=0)
    )
    banks = {"battle.bnk": base_bank}
    project, session = _setup_session_environment(tmp_path, banks)

    # Modify battle.bnk so sound 701 is promoted to stream_type=2 / PCM
    modified_bank = _build_test_bank(
        bank_id=70,
        sounds=[(701, 3333, 2)],  # modified to streamed PCM
    )
    # Keep base didx and data so only HIRC differs
    from dataclasses import replace

    modified_bank = replace(modified_bank, didx=base_bank.didx, data=base_bank.data)
    project.save_bank("battle.bnk", modified_bank.to_bytes())
    project.stage_wem(3333, b"PCM_WEM_DATA")

    # Load modified bank into session
    session.resolve_and_parse_bank("battle.bnk")

    entry = session.get_loaded_entry("battle.bnk")
    assert entry is not None
    s701 = next(o for o in entry[0].hirc.objects if isinstance(o, CAkSound) and o.id == 701)
    assert s701.stream_type == 2
    assert (project.audio_dir / "3333.wem").is_file()

    # Call revert_wem(3333)
    reverted = session.revert_wem(3333)
    assert reverted

    # Loose .wem should be deleted
    assert not (project.audio_dir / "3333.wem").is_file()
    assert 3333 not in project.manifest.staged_wems

    # Sound 701 in bank AST should be restored to baseline stream_type=0
    entry_rev = session.get_loaded_entry("battle.bnk")
    assert entry_rev is not None
    s701_rev = next(o for o in entry_rev[0].hirc.objects if isinstance(o, CAkSound) and o.id == 701)
    assert s701_rev.stream_type == 0

    # Since all nodes are now identical to baseline, battle.bnk should be reverted
    assert not (project.audio_dir / "battle.bnk").is_file()
    assert "battle.bnk" not in [b.lower() for b in project.manifest.modified_banks]


def test_revert_node_and_wem_synthetic_resilience():
    # Calling revert_node_to_baseline or revert_wem on nonexistent bank/wem returns gracefully
    session = WorkspaceSession()
    assert not session.revert_node_to_baseline("", "")
    assert not session.revert_node_to_baseline("missing.bnk", "hirc:999")
    assert not session.revert_wem("invalid")
    assert not session.revert_wem(999999)


# =============================================================================
# Task 8: Sub-Track WAV Export Support
# =============================================================================


def test_sub_track_wav_export_info_and_batch_export(tmp_path: Path):
    bank = _build_test_bank(
        bank_id=80,
        sounds=[(801, 8881, 2)],
        music_tracks=[(802, [(9991, 2), (9992, 2)])],
    )

    # 1. Sound node
    wid, comp = _extract_wem_info_from_key(bank, "hirc:801")
    assert wid == 8881
    assert comp == 0

    # 2. MusicTrack default source 0
    wid, comp = _extract_wem_info_from_key(bank, "hirc:802")
    assert wid == 9991

    # 3. MusicTrack sub-track src:0 and src:1
    wid0, _ = _extract_wem_info_from_key(bank, "hirc:802:src:0")
    wid1, _ = _extract_wem_info_from_key(bank, "hirc:802:src:1")
    assert wid0 == 9991
    assert wid1 == 9992

    # 4. Out-of-bounds source index falls back to source 0
    wid_oob, _ = _extract_wem_info_from_key(bank, "hirc:802:src:99")
    assert wid_oob == 9991

    # 5. Media key
    assert _extract_wem_id_from_key(bank, "media:7777") == 7777
