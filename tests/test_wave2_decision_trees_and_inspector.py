"""
Unit and integration tests for Wave 2: Decision Tree Resolution and Container/Music Inspector.
Tests multi-depth decision trees, label propagation, sub-track context inheritance, and inspector views.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QApplication

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk
from src.bnk.models import (
    AkDecisionTree,
    AkMusicRanSeqPlaylistItem,
    AkMusicTrackSource,
    AkTrackSrcInfo,
    CAkDialogueEvent,
    CAkMusicRanSeqCntr,
    CAkMusicSegment,
    CAkMusicSwitchCntr,
    CAkMusicTrack,
    CAkRanSeqCntr,
    CAkSound,
    DecisionTreeNode,
)
from src.engine.graph import BankGraphIndex
from src.engine.metadata_resolver import (
    CompositeMetadataResolver,
    GraphHierarchyProvider,
    ResolutionContext,
    SoundDatabaseProvider,
    resolve_decision_tree_paths,
)
from src.models.hashing import KNOWN_HASH_NAMES
from src.ui.features.bank_viewer.builder import (
    _build_decision_tree_semantics,
    _build_music_ran_seq_semantics,
    build_details_for_node,
    build_tree_and_details_from_bank,
    resolve_inspector_view_type,
)
from src.ui.features.bank_viewer.state import (
    InspectorProperty,
    InspectorViewType,
    NodeInspectorDetails,
    SwitchContainerSemantics,
    SwitchRouteEntry,
)
from src.ui.features.bank_viewer.views.container_view import ContainerInspectorView
from src.ui.features.bank_viewer.views.music_view import MusicInspectorView


class DummySoundDb:
    """Mock sound database mapping known hashes for tests."""

    def __init__(self, hash_map: dict[int, str] | None = None) -> None:
        self._map = hash_map or {}

    def resolve_hash(self, val: int) -> str | None:
        return self._map.get(val)


# -----------------------------------------------------------------------------
# 1. Multi-Depth Decision Tree Resolution Tests
# -----------------------------------------------------------------------------


def test_resolve_decision_tree_paths_single_depth() -> None:
    # 1 argument: game_mode (hash=1071299879), key=100 -> target 5001
    tree = AkDecisionTree(
        root=DecisionTreeNode(
            key=0,
            children=[
                DecisionTreeNode(key=100, audio_node_id=5001, is_leaf=True),
                DecisionTreeNode(key=0, audio_node_id=5002, is_leaf=True),
            ],
        ),
        max_depth=1,
    )
    obj = CAkMusicSwitchCntr(
        id=1001,
        arguments=[(1071299879, 0)],
        tree_depth=1,
        tree=tree,
    )
    bank = SoundBank(header=BkhdChunk(bank_id=1, version=112), hirc=HircChunk(objects=[obj]))
    sound_db = DummySoundDb({100: "campaign"})

    paths = resolve_decision_tree_paths(obj, bank, sound_db=sound_db)

    assert 5001 in paths
    assert paths[5001] == ["game_mode=campaign"]
    assert 5002 in paths
    # Single level with key 0 formats as "none"
    assert paths[5002] == ["game_mode=none"]


def test_resolve_decision_tree_paths_multi_depth() -> None:
    # 2 arguments: game_mode (1071299879) and music_culture (3464651813)
    # Branch 1: campaign (100) -> barbarian (1787064993) -> 6001
    # Branch 2: campaign (100) -> roman (2164288628) -> 6002
    # Branch 3: battle (200) -> wildcard (0) -> 6003
    child_barbarian = DecisionTreeNode(key=1787064993, audio_node_id=6001, is_leaf=True)
    child_roman = DecisionTreeNode(key=2164288628, audio_node_id=6002, is_leaf=True)
    child_wildcard = DecisionTreeNode(key=0, audio_node_id=6003, is_leaf=True)

    branch_campaign = DecisionTreeNode(
        key=100,
        children=[child_barbarian, child_roman],
        is_leaf=False,
    )
    branch_battle = DecisionTreeNode(
        key=200,
        children=[child_wildcard],
        is_leaf=False,
    )

    tree = AkDecisionTree(
        root=DecisionTreeNode(key=0, children=[branch_campaign, branch_battle]),
        max_depth=2,
    )
    obj = CAkMusicSwitchCntr(
        id=1002,
        arguments=[(1071299879, 0), (3464651813, 0)],
        tree_depth=2,
        tree=tree,
    )
    bank = SoundBank(header=BkhdChunk(bank_id=1, version=112), hirc=HircChunk(objects=[obj]))
    sound_db = DummySoundDb({100: "campaign", 200: "battle"})

    paths = resolve_decision_tree_paths(obj, bank, sound_db=sound_db)

    assert paths[6001] == ["game_mode=campaign > music_culture=barbarian"]
    assert paths[6002] == ["game_mode=campaign > music_culture=roman"]
    # Multi-level with key 0 formats as "*"
    assert paths[6003] == ["game_mode=battle > music_culture=*"]


def test_resolve_decision_tree_paths_flat_fallback() -> None:
    # Synthetic flat nodes without root.children
    tree = AkDecisionTree(
        root=DecisionTreeNode(key=0),
        nodes=[
            DecisionTreeNode(key=100, audio_node_id=7001, is_leaf=True),
        ],
    )
    obj = CAkDialogueEvent(
        id=2001,
        arguments=[(1071299879, 0)],
        tree_depth=1,
        tree=tree,
    )
    bank = SoundBank(header=BkhdChunk(bank_id=1, version=112), hirc=HircChunk(objects=[obj]))
    sound_db = DummySoundDb({100: "campaign"})

    paths = resolve_decision_tree_paths(obj, bank, sound_db=sound_db)
    assert paths[7001] == ["game_mode=campaign"]


def test_resolve_decision_tree_paths_edge_cases() -> None:
    bank = SoundBank(header=BkhdChunk(bank_id=1, version=112), hirc=HircChunk(objects=[]))
    # None tree
    assert resolve_decision_tree_paths(None, bank) == {}
    # Empty tree
    empty_obj = CAkMusicSwitchCntr(id=999, arguments=[], tree=AkDecisionTree())
    assert resolve_decision_tree_paths(empty_obj, bank) == {}
    # Tree depth greater than arguments length (no IndexError)
    deep_tree = AkDecisionTree(
        root=DecisionTreeNode(
            key=0,
            children=[
                DecisionTreeNode(
                    key=10,
                    children=[
                        DecisionTreeNode(key=20, audio_node_id=8888, is_leaf=True),
                    ],
                )
            ],
        ),
        max_depth=2,
    )
    partial_obj = CAkMusicSwitchCntr(
        id=998,
        arguments=[(1071299879, 0)],  # Only 1 argument for depth 2
        tree_depth=2,
        tree=deep_tree,
    )
    paths = resolve_decision_tree_paths(partial_obj, bank)
    assert 8888 in paths
    assert "game_mode=" in paths[8888][0]


# -----------------------------------------------------------------------------
# 2. Label Propagation and Sub-Track Context Inheritance Tests
# -----------------------------------------------------------------------------


def test_friendly_label_switch_path_prefixing() -> None:
    # Create parent switch container and child music segment
    child_seg = CAkMusicSegment(id=5001)
    leaf = DecisionTreeNode(key=100, audio_node_id=5001, is_leaf=True)
    tree = AkDecisionTree(
        root=DecisionTreeNode(
            key=0,
            children=[leaf],
        ),
        nodes=[leaf],
        max_depth=1,
    )
    parent_sw = CAkMusicSwitchCntr(
        id=1001,
        arguments=[(1071299879, 0)],
        tree_depth=1,
        tree=tree,
    )
    bank = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[parent_sw, child_seg]),
    )
    graph = BankGraphIndex.build(bank)
    sound_db = DummySoundDb({100: "campaign"})

    _, nodes, _ = build_tree_and_details_from_bank(bank, graph, sound_db=sound_db)

    seg_node = nodes["hirc:5001"]
    # h_f_lbl was None, so it gets prefixed with [switch_path]
    assert seg_node.friendly_label is not None
    assert "[game_mode=campaign]" in seg_node.friendly_label
    assert "MusicSegment_5001" in seg_node.friendly_label


def test_sub_track_context_inheritance() -> None:
    # Create multi-source music track child of switch container
    m_track = CAkMusicTrack(
        id=7001,
        sources=[
            AkMusicTrackSource(source_id=8001, stream_type=2),
            AkMusicTrackSource(source_id=8002, stream_type=2),
        ],
        playlist=[
            AkTrackSrcInfo(source_id=8001, src_duration=5000.0),
            AkTrackSrcInfo(source_id=8002, src_duration=6000.0),
        ],
    )
    leaf = DecisionTreeNode(key=100, audio_node_id=7001, is_leaf=True)
    tree = AkDecisionTree(
        root=DecisionTreeNode(
            key=0,
            children=[leaf],
        ),
        nodes=[leaf],
        max_depth=1,
    )
    parent_sw = CAkMusicSwitchCntr(
        id=1001,
        arguments=[(1071299879, 0)],
        tree_depth=1,
        tree=tree,
    )
    bank = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[parent_sw, m_track]),
    )
    graph = BankGraphIndex.build(bank)
    sound_db = DummySoundDb({100: "campaign"})

    _, nodes, _ = build_tree_and_details_from_bank(bank, graph, sound_db=sound_db)

    sub0 = nodes["hirc:7001:src:0"]
    sub1 = nodes["hirc:7001:src:1"]

    # Both sub-tracks inherit parent's switch details
    assert "Source WEM: 8001 | Switch: game_mode=campaign" in sub0.friendly_details
    assert "Source WEM: 8002 | Switch: game_mode=campaign" in sub1.friendly_details

    # Inspection details of sub-track inherit switch_path and Play Condition property
    resolver = CompositeMetadataResolver([GraphHierarchyProvider(), SoundDatabaseProvider()])
    sub_det = build_details_for_node(
        bank,
        graph,
        "hirc:7001:src:0",
        sound_db=sound_db,
        metadata_resolver=resolver,
    )
    assert sub_det is not None
    assert sub_det.switch_path == "game_mode=campaign"
    play_cond_props = [p for p in sub_det.properties if p.label == "Play Condition"]
    assert len(play_cond_props) == 1
    assert play_cond_props[0].value == "game_mode=campaign"


# -----------------------------------------------------------------------------
# 3. Inspector Views and Semantics Tests
# -----------------------------------------------------------------------------


def test_resolve_inspector_view_type_mapping() -> None:
    assert (
        resolve_inspector_view_type(CAkMusicSwitchCntr(id=1), "hirc:1")
        == InspectorViewType.CONTAINER
    )
    assert (
        resolve_inspector_view_type(CAkMusicRanSeqCntr(id=2), "hirc:2")
        == InspectorViewType.CONTAINER
    )
    assert (
        resolve_inspector_view_type(CAkDialogueEvent(id=3), "hirc:3") == InspectorViewType.CONTAINER
    )
    assert resolve_inspector_view_type(CAkMusicTrack(id=4), "hirc:4") == InspectorViewType.MUSIC
    assert resolve_inspector_view_type(CAkMusicSegment(id=5), "hirc:5") == InspectorViewType.MUSIC


def test_decision_tree_semantics_builder() -> None:
    # Build CAkMusicSwitchCntr with 2-level decision tree
    child_leaf = DecisionTreeNode(key=1787064993, audio_node_id=9001, is_leaf=True)
    branch = DecisionTreeNode(key=100, children=[child_leaf], is_leaf=False)
    tree = AkDecisionTree(root=DecisionTreeNode(key=0, children=[branch]), max_depth=2)

    sw_cntr = CAkMusicSwitchCntr(
        id=1001,
        arguments=[(1071299879, 0), (3464651813, 0)],
        tree_depth=2,
        tree=tree,
    )
    seg = CAkMusicSegment(id=9001)
    bank = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[sw_cntr, seg]),
    )
    graph = BankGraphIndex.build(bank)
    sound_db = DummySoundDb({100: "campaign"})

    sem = _build_decision_tree_semantics(sw_cntr, bank, graph, sound_db=sound_db)
    assert "game_mode" in sem.group_name
    assert "music_culture" in sem.group_name
    assert len(sem.routes) == 1
    route = sem.routes[0]
    assert route.target_id == 9001
    assert route.target_key == "hirc:9001"
    assert route.switch_name == "campaign > barbarian"


def test_music_ran_seq_semantics_builder() -> None:
    item1 = AkMusicRanSeqPlaylistItem(segment_id=5001, weight=60000, loop=2)
    item2 = AkMusicRanSeqPlaylistItem(segment_id=5002, weight=40000, loop=2)
    mrsc = CAkMusicRanSeqCntr(id=2001, playlist=[item1, item2])
    seg1 = CAkMusicSegment(id=5001)
    seg2 = CAkMusicSegment(id=5002)
    bank = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[mrsc, seg1, seg2]),
    )
    graph = BankGraphIndex.build(bank)

    r_sem = _build_music_ran_seq_semantics(mrsc, graph)
    assert len(r_sem.playlist) == 2
    assert r_sem.playlist[0].play_id == 5001
    assert r_sem.playlist[0].weight == 60000
    assert r_sem.playlist[0].weight_percent == 60.0
    assert r_sem.playlist[1].play_id == 5002
    assert r_sem.playlist[1].weight == 40000
    assert r_sem.playlist[1].weight_percent == 40.0


def test_music_inspector_view_play_condition(qapp: QApplication) -> None:
    view = MusicInspectorView()
    assert view.lbl_switch_context.text() == "Play Condition: -"

    # Render with switch_path
    details = NodeInspectorDetails(
        node_key="hirc:7001",
        name="Track_7001",
        object_type="MusicTrack",
        view_type=InspectorViewType.MUSIC,
        switch_path="game_mode=campaign > music_culture=barbarian",
    )
    view.render(details)
    assert (
        "Play Condition: game_mode=campaign > music_culture=barbarian"
        in view.lbl_switch_context.text()
    )

    # Clear render resets label
    view.render(None)
    assert view.lbl_switch_context.text() == "Play Condition: -"


def test_container_inspector_view_decision_tree_routes(qapp: QApplication) -> None:
    view = ContainerInspectorView()
    jump_keys: list[str] = []
    view.jump_requested.connect(jump_keys.append)

    sem = SwitchContainerSemantics(
        group_id=1071299879,
        group_name="game_mode, music_culture",
        group_type=0,
        default_switch_id=0,
        default_switch_name="None",
        routes=(
            SwitchRouteEntry(
                switch_id=100,
                switch_name="campaign > barbarian",
                target_key="hirc:9001",
                target_id=9001,
                target_name="MusicSegment_9001",
                target_type="MusicSegment",
            ),
        ),
    )
    details = NodeInspectorDetails(
        node_key="hirc:1001",
        name="MusicSwitchCntr_1001",
        object_type="MusicSwitchCntr",
        view_type=InspectorViewType.CONTAINER,
        switch_semantics=sem,
    )

    view.render(details)
    assert not view.routing_table.isHidden()
    assert view.routing_table.rowCount() == 1
    assert view.routing_table.item(0, 0).text() == "campaign > barbarian"
    assert view.routing_table.item(0, 1).text() == "MusicSegment_9001"

    # Double click routes to segment
    view.routing_table.cellDoubleClicked.emit(0, 0)
    assert jump_keys == ["hirc:9001"]
