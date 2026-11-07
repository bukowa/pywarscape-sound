"""
Conformance vector tests for engine capability matrix, taxonomy classification, and replacement planning.
Loads pure JSON vectors and validates core domain contracts.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import pytest

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk
from src.bnk.models import (
    AkDecisionTree,
    AkMusicMarker,
    AkMusicRanSeqPlaylistItem,
    AkMusicTrackSource,
    AkMusicTransitionRule,
    AkMusicTransNodeParams,
    AkTrackSrcInfo,
    CAkMusicRanSeqCntr,
    CAkMusicSegment,
    CAkMusicSwitchCntr,
    CAkMusicTrack,
    CAkSound,
    DecisionTreeNode,
    NodeBaseParams,
)
from src.engine.capabilities import (
    classify_bank_group,
    get_capability_matrix,
    query_capability,
)
from src.engine.graph import BankGraphIndex, get_child_ids_for_object
from src.engine.ontology import (
    AudioMutationPlan,
    ExternalFileSource,
    MusicTrackTarget,
    PlanRejection,
    ReplacementScope,
    SilentStubSource,
    SoundNodeTarget,
    UpdateMusicTrackNodeIntent,
    UpdateSoundNodeIntent,
)
from src.engine.planner import try_plan_audio_replacement
from src.models.hashing import KNOWN_HASH_NAMES
from src.ui.features.bank_viewer.builder import (
    build_details_for_node,
    build_tree_and_details_from_bank,
)
from tests.support.factories import skip_or_fail_missing_asset

VECTORS_DIR = Path(__file__).parent / "vectors"


def _load_json(rel_path: str) -> Any:
    with open(VECTORS_DIR / rel_path, encoding="utf-8") as f:
        return json.load(f)


# -----------------------------------------------------------------------------
# 1. Node Capability Vectors
# -----------------------------------------------------------------------------

NODE_CAPABILITY_VECTORS = _load_json("capabilities/node_capabilities.json")


@pytest.mark.parametrize(
    "vector",
    NODE_CAPABILITY_VECTORS,
    ids=[f"{v['node_type']}_{v['action']}" for v in NODE_CAPABILITY_VECTORS],
)
def test_node_capability_vectors(vector: dict[str, Any]) -> None:
    cap = query_capability(vector["node_type"], vector["action"])
    assert cap.status == vector["expected_status"]
    if vector["expected_status"] == "supported":
        assert cap.reason == ""
        assert cap.is_supported is True
    else:
        assert cap.is_supported is False
        if "expected_reason_contains" in vector:
            assert vector["expected_reason_contains"] in cap.reason


# -----------------------------------------------------------------------------
# 2. SoundBank Classification Vectors
# -----------------------------------------------------------------------------

BANK_GROUP_VECTORS = _load_json("capabilities/bank_groups.json")


@pytest.mark.parametrize(
    "vector",
    BANK_GROUP_VECTORS,
    ids=[v["bank_name"] for v in BANK_GROUP_VECTORS],
)
def test_bank_group_classification_vectors(vector: dict[str, Any]) -> None:
    group, subgroup = classify_bank_group(vector["bank_name"])
    assert group == vector["expected_group"]
    assert subgroup == vector["expected_subgroup"]


# -----------------------------------------------------------------------------
# 3. Audio Replacement Planning Vectors
# -----------------------------------------------------------------------------

PLAN_SOUND_REPLACE_VECTORS = _load_json("plan/sound_replace.json")


def _build_test_bank() -> SoundBank:
    sound = CAkSound(
        id=204996993,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=2,
        source_id=174224638,
        file_id=174224638,
        node_base_params=NodeBaseParams(),
    )
    return SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[sound]),
    )


@pytest.mark.parametrize(
    "vector",
    PLAN_SOUND_REPLACE_VECTORS,
    ids=[v["name"] for v in PLAN_SOUND_REPLACE_VECTORS],
)
def test_sound_replace_planning_vectors(vector: dict[str, Any]) -> None:
    bank = _build_test_bank()
    target_data = vector["target"]
    if target_data["type"] == "SoundNodeTarget":
        target = SoundNodeTarget(
            bank_name=target_data["bank_name"],
            sound_id=target_data["sound_id"],
        )
    elif target_data["type"] == "MusicTrackTarget":
        target = MusicTrackTarget(
            bank_name=target_data["bank_name"],
            track_id=target_data["track_id"],
            source_index=target_data.get("source_index", 0),
        )
    else:
        raise ValueError(f"Unsupported target type in test vector: {target_data['type']}")

    source_data = vector["source"]
    if source_data["type"] == "ExternalFileSource":
        source = ExternalFileSource(file_path=Path(source_data["file_path"]))
    elif source_data["type"] == "SilentStubSource":
        source = SilentStubSource(stub_wem_id=source_data.get("stub_wem_id", 1))
    else:
        raise ValueError(f"Unsupported source type in test vector: {source_data['type']}")

    scope = ReplacementScope.ISOLATE if vector["scope"] == "isolate" else ReplacementScope.OVERWRITE
    forked_wem_id = vector["forked_wem_id"]

    result = try_plan_audio_replacement(
        bank=bank,
        target=target,
        source=source,
        scope=scope,
        forked_wem_id=forked_wem_id,
        external_file_exists=True,
    )

    expected = vector["expected_result"]
    if expected["status"] == "plan":
        assert isinstance(result, AudioMutationPlan)
        assert result.description == expected["description"]
        assert len(result.effects) == expected["num_effects"]
        assert [type(e).__name__ for e in result.effects] == expected["effect_types"]
        for eff in result.effects:
            if isinstance(eff, UpdateSoundNodeIntent):
                assert eff.new_plugin_id == 0x00010001
    elif expected["status"] == "rejection":
        assert isinstance(result, PlanRejection)
        assert result.code == expected["rejection_code"]
        if expected.get("reason_non_empty"):
            assert len(result.reason.strip()) > 0
    else:
        raise ValueError(f"Unsupported expected status: {expected['status']}")


PLAN_MUSIC_REPLACE_VECTORS = _load_json("plan/music_replace.json")


def _build_music_test_bank() -> SoundBank:
    seg1 = CAkMusicSegment(
        id=50001,
        obj_type=10,
        child_ids=[10001],
        duration=120000.0,
        markers=[
            AkMusicMarker(id=1, position=0.0, name="<entry>"),
            AkMusicMarker(id=2, position=60000.0, name="verse"),
            AkMusicMarker(id=3, position=120000.0, name="<exit>"),
        ],
    )
    track1 = CAkMusicTrack(
        id=10001,
        obj_type=11,
        sources=[
            AkMusicTrackSource(source_id=20001, file_id=20001, stream_type=2, plugin_id=0x00040001),
        ],
        playlist=[
            AkTrackSrcInfo(track_id=10001, source_id=20001, play_at=0.0, src_duration=120000.0),
        ],
    )
    seg2 = CAkMusicSegment(
        id=50002,
        obj_type=10,
        child_ids=[10002],
        duration=60000.0,
        markers=[
            AkMusicMarker(id=1, position=0.0, name="<entry>"),
            AkMusicMarker(id=2, position=60000.0, name="<exit>"),
        ],
    )
    track2 = CAkMusicTrack(
        id=10002,
        obj_type=11,
        sources=[
            AkMusicTrackSource(source_id=20002, file_id=20002, stream_type=2, plugin_id=0x00040001),
            AkMusicTrackSource(source_id=20003, file_id=20003, stream_type=2, plugin_id=0x00040001),
        ],
        playlist=[
            AkTrackSrcInfo(track_id=10002, source_id=20002, play_at=0.0, src_duration=60000.0),
            AkTrackSrcInfo(track_id=10002, source_id=20003, play_at=0.0, src_duration=60000.0),
        ],
    )
    return SoundBank(
        header=BkhdChunk(bank_id=2, version=112),
        hirc=HircChunk(objects=[seg1, track1, seg2, track2]),
    )


@pytest.mark.parametrize(
    "vector",
    PLAN_MUSIC_REPLACE_VECTORS,
    ids=[v["name"] for v in PLAN_MUSIC_REPLACE_VECTORS],
)
def test_music_replace_planning_vectors(vector: dict[str, Any]) -> None:
    bank = _build_music_test_bank()
    target_data = vector["target"]
    target = MusicTrackTarget(
        bank_name=target_data["bank_name"],
        track_id=target_data["track_id"],
        source_index=target_data.get("source_index", 0),
    )

    source_data = vector["source"]
    source = ExternalFileSource(file_path=Path(source_data["file_path"]))
    scope = ReplacementScope.ISOLATE if vector["scope"] == "isolate" else ReplacementScope.OVERWRITE
    forked_wem_id = vector["forked_wem_id"]

    result = try_plan_audio_replacement(
        bank=bank,
        target=target,
        source=source,
        scope=scope,
        forked_wem_id=forked_wem_id,
        external_file_exists=True,
    )

    expected = vector["expected_result"]
    assert isinstance(result, AudioMutationPlan)
    assert result.description == expected["description"]
    assert len(result.effects) == expected["num_effects"]
    assert [type(e).__name__ for e in result.effects] == expected["effect_types"]

    music_intents = [e for e in result.effects if isinstance(e, UpdateMusicTrackNodeIntent)]
    assert len(music_intents) >= 1
    for mi in music_intents:
        assert mi.new_plugin_id == 0x00010001
        assert mi.new_stream_type == 2


# -----------------------------------------------------------------------------
# 4. Capability Matrix Completeness & Invariant Assertions
# -----------------------------------------------------------------------------


def test_capability_matrix_completeness() -> None:
    """
    Verifies completeness of capability_matrix.json:
    - Every defined action has valid status in ("supported", "disabled")
    - Every disabled action has a non-empty descriptive reason
    - Supported replace/mute on Sound has a working planner flow
    - 6 bank groups are defined with unique IDs and non-empty labels
    """
    matrix = get_capability_matrix()
    assert len(matrix.actions) >= 10
    assert len(matrix.node_capabilities) >= 19

    for nc in matrix.node_capabilities:
        assert len(nc.actions) == len(matrix.actions)
        for cap in nc.actions:
            assert cap.status in ("supported", "disabled")
            if cap.status == "disabled":
                assert cap.reason.strip() != "", (
                    f"Node {nc.node_type} action {cap.action} is disabled but has empty reason"
                )
            else:
                assert cap.reason == "", (
                    f"Node {nc.node_type} action {cap.action} is supported but has non-empty reason"
                )

    # Verify Sound replace and mute produce plans
    bank = _build_test_bank()
    sound_target = SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=204996993)

    replace_plan = try_plan_audio_replacement(
        bank=bank,
        target=sound_target,
        source=ExternalFileSource(file_path=Path("source_audio/custom.wav")),
        external_file_exists=True,
    )
    assert isinstance(replace_plan, AudioMutationPlan)

    mute_plan = try_plan_audio_replacement(
        bank=bank,
        target=sound_target,
        source=SilentStubSource(stub_wem_id=1),
        external_file_exists=True,
    )
    assert isinstance(mute_plan, AudioMutationPlan)

    # Bank groups invariants
    assert len(matrix.bank_groups) == 6
    group_ids = [bg.id for bg in matrix.bank_groups]
    assert len(set(group_ids)) == 6
    for bg in matrix.bank_groups:
        assert len(bg.label.strip()) > 0


# -----------------------------------------------------------------------------
# 5. Vanilla Game Banks Classification (@pytest.mark.assets)
# -----------------------------------------------------------------------------


@pytest.mark.assets
def test_all_126_vanilla_banks_classify_cleanly() -> None:
    """Verifies all 126 vanilla banks in .cache/attila/audio/ classify into the 6 groups."""
    cache_dir = Path(".cache/attila/audio")
    if not (cache_dir.is_dir() and any(cache_dir.glob("*.bnk"))):
        skip_or_fail_missing_asset("Attila game cache not available locally")

    bnk_files = sorted(cache_dir.glob("*.bnk"))
    assert len(bnk_files) >= 126

    matrix = get_capability_matrix()
    valid_groups = {bg.label for bg in matrix.bank_groups}

    classified_counts: dict[str, int] = {}
    for bnk in bnk_files:
        group, subgroup = classify_bank_group(bnk.name)
        assert group in valid_groups, f"Bank {bnk.name} classified into unknown group {group}"
        if group == "Battle Voice Orders" and subgroup is not None:
            assert subgroup in ("Barbarian", "Eastern", "Nomad", "Roman")
        classified_counts[group] = classified_counts.get(group, 0) + 1

    # In Attila, all 6 groups are represented
    assert len(classified_counts) == 6
    assert sum(classified_counts.values()) == len(bnk_files)


# -----------------------------------------------------------------------------
# 6. Music Graph & Hash Conformance Vectors
# -----------------------------------------------------------------------------

MUSIC_CONFORMANCE_VECTORS = _load_json("describe/music_graph_and_hashes.json")


def test_music_known_hash_resolutions() -> None:
    for item in MUSIC_CONFORMANCE_VECTORS["known_hash_resolutions"]:
        h = item["hash"]
        expected = item["expected_name"]
        assert h in KNOWN_HASH_NAMES, f"Hash {h} ({expected}) not in KNOWN_HASH_NAMES"
        assert KNOWN_HASH_NAMES[h] == expected


def test_music_graph_indexing_vectors() -> None:
    for case in MUSIC_CONFORMANCE_VECTORS["graph_indexing_cases"]:
        if "switch_cntr_id" in case:
            rules = []
            for r in case["trans_rules"]:
                trans_obj = struct.pack("<I", r["trans_seg_id"]) + b"\x00" * 26
                rules.append(
                    AkMusicTransitionRule(
                        alloc_trans_object_flag=r["alloc_flag"],
                        trans_object=trans_obj,
                    )
                )
            tp = AkMusicTransNodeParams(children=case["trans_children"], rules=rules)
            tree_nodes = [
                DecisionTreeNode(key=0, audio_node_id=lid, is_leaf=True)
                for lid in case["tree_leaf_ids"]
            ]
            tree = AkDecisionTree(nodes=tree_nodes)
            obj = CAkMusicSwitchCntr(
                id=case["switch_cntr_id"],
                trans_params=tp,
                tree=tree,
            )
            children = get_child_ids_for_object(obj)
            assert children == case["expected_children"]
        elif "ran_seq_cntr_id" in case:
            rules = []
            for r in case["trans_rules"]:
                trans_obj = struct.pack("<I", r["trans_seg_id"]) + b"\x00" * 26
                rules.append(
                    AkMusicTransitionRule(
                        alloc_trans_object_flag=r["alloc_flag"],
                        trans_object=trans_obj,
                    )
                )
            tp = AkMusicTransNodeParams(children=case["trans_children"], rules=rules)
            playlist = [
                AkMusicRanSeqPlaylistItem(
                    segment_id=it["segment_id"],
                    playlist_item_id=it["playlist_item_id"],
                )
                for it in case["playlist_items"]
            ]
            obj = CAkMusicRanSeqCntr(
                id=case["ran_seq_cntr_id"],
                trans_params=tp,
                playlist=playlist,
            )
            children = get_child_ids_for_object(obj)
            assert children == case["expected_children"]


def test_music_track_projection_vectors() -> None:
    proj_data = MUSIC_CONFORMANCE_VECTORS["multi_source_track_projection"]

    # 1. Multi-source track
    m_data = proj_data["multi_source_track"]
    m_track = CAkMusicTrack(
        id=m_data["id"],
        sources=[
            AkMusicTrackSource(source_id=s["source_id"], stream_type=s["stream_type"])
            for s in m_data["sources"]
        ],
        playlist=[
            AkTrackSrcInfo(source_id=p["source_id"], src_duration=p["src_duration"])
            for p in m_data["playlist"]
        ],
    )
    bank_multi = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[m_track]),
    )
    graph_multi = BankGraphIndex.build(bank_multi)
    _, nodes_multi, _ = build_tree_and_details_from_bank(bank_multi, graph_multi)

    parent_node = nodes_multi[f"hirc:{m_track.id}"]
    assert parent_node.child_keys == tuple(m_data["expected_child_keys"])
    assert len(parent_node.child_keys) == 3

    for idx, expected_key in enumerate(m_data["expected_child_keys"]):
        assert expected_key in nodes_multi
        sub_node = nodes_multi[expected_key]
        assert sub_node.type_str == "MusicTrack"
        assert f"Sub-track {idx + 1}" in sub_node.label
        expected_src_id = m_data["sources"][idx]["source_id"]
        assert str(expected_src_id) in sub_node.label

        # Verify inspection of sub-track
        sub_det = build_details_for_node(bank_multi, graph_multi, expected_key)
        assert sub_det is not None
        assert sub_det.source_wem_id == expected_src_id
        assert sub_det.object_type == "MusicTrack"

    # 2. Single-source track
    s_data = proj_data["single_source_track"]
    s_track = CAkMusicTrack(
        id=s_data["id"],
        sources=[
            AkMusicTrackSource(source_id=s["source_id"], stream_type=s["stream_type"])
            for s in s_data["sources"]
        ],
        playlist=[
            AkTrackSrcInfo(source_id=p["source_id"], src_duration=p["src_duration"])
            for p in s_data["playlist"]
        ],
    )
    bank_single = SoundBank(
        header=BkhdChunk(bank_id=2, version=112),
        hirc=HircChunk(objects=[s_track]),
    )
    graph_single = BankGraphIndex.build(bank_single)
    _, nodes_single, _ = build_tree_and_details_from_bank(bank_single, graph_single)

    single_node = nodes_single[f"hirc:{s_track.id}"]
    assert single_node.child_keys == ()


@pytest.mark.assets
def test_global_music_bnk_graph_and_hash_conformance() -> None:
    """Verifies global_music.bnk has 0 orphaned music segments and 100% decision-tree hash resolution."""
    bank_path = Path(".cache/attila/audio/global_music.bnk")
    if not bank_path.is_file():
        skip_or_fail_missing_asset("global_music.bnk not present in cache")

    bank = SoundBank.from_file(bank_path)
    idx = BankGraphIndex.build(bank)

    # 1. Zero orphaned CAkMusicSegment nodes
    music_segments = [o for o in bank.hirc.objects if isinstance(o, CAkMusicSegment)]
    assert len(music_segments) == 483
    orphaned_segments = [s for s in music_segments if not idx.get_parent_ids(s.id)]
    assert len(orphaned_segments) == 0

    # 2. 100% Decision-Tree Switch Group resolution (9/9)
    group_ids: set[int] = set()
    for o in bank.hirc.objects:
        if isinstance(o, CAkMusicSwitchCntr):
            for gid, _ in o.arguments:
                group_ids.add(gid)
    assert len(group_ids) == 9
    unresolved_groups = [gid for gid in group_ids if gid not in KNOWN_HASH_NAMES]
    assert len(unresolved_groups) == 0

    # 3. 100% Decision-Tree Branch Key resolution (29/29 non-zero keys)
    branch_keys: set[int] = set()
    for o in bank.hirc.objects:
        if isinstance(o, CAkMusicSwitchCntr):
            for node in o.tree.nodes:
                if node.key != 0:
                    branch_keys.add(node.key)
    assert len(branch_keys) == 29
    unresolved_keys = [k for k in branch_keys if k not in KNOWN_HASH_NAMES]
    assert len(unresolved_keys) == 0
