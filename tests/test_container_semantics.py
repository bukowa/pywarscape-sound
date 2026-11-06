"""Unit tests verifying rich semantic extraction and routing resolution for HIRC containers."""

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.database import SoundDatabase, fnv1_32
from src.bnk.models import AkPlaylistItem, CAkRanSeqCntr, CAkSound, CAkSwitchCntr
from src.engine.graph import BankGraphIndex
from src.ui.features.bank_viewer.builder import (
    _get_object_summary,
    build_details_for_node,
)


def test_switch_container_semantics() -> None:
    """Verifies complete routing transparency for CAkSwitchCntr with SoundDatabase resolution."""
    sound_db = SoundDatabase()
    sound_db.add_switch_group("rain_intensity", ["light", "medium", "heavy", "none"])

    group_id = fnv1_32("rain_intensity")
    default_switch = fnv1_32("medium")
    switch_map = {
        fnv1_32("light"): [20236167],
        fnv1_32("medium"): [71115871],
        fnv1_32("heavy"): [1044587686],
        fnv1_32("none"): [71115871],
    }

    cntr = CAkSwitchCntr(
        id=648180848,
        group_type=1,
        group_id=group_id,
        default_switch=default_switch,
        children=[20236167, 71115871, 1044587686],
        switch_map=switch_map,
    )
    children = [
        CAkSound(id=20236167),
        CAkSound(id=71115871),
        CAkSound(id=1044587686),
    ]
    bank = SoundBank(hirc=HircChunk(objects=[cntr, *children]))
    graph_index = BankGraphIndex.build(bank)
    node_key = "hirc:648180848"

    details = build_details_for_node(
        bank,
        graph_index,
        node_key,
        sound_db=sound_db,
    )

    assert details is not None
    assert details.object_id == 648180848
    assert details.object_type == "SwitchCntr"

    # Semantic routing validation
    sem = details.switch_semantics
    assert sem is not None
    assert sem.group_id == 2520241501
    assert sem.default_switch_id == 2849147824
    assert sem.group_name == "rain_intensity"
    assert sem.default_switch_name == "medium"

    # 4 routes mapped across 3 unique children
    assert len(sem.routes) == 4
    route_map = {r.switch_name.lower(): r for r in sem.routes}

    assert "light" in route_map
    assert "medium" in route_map
    assert "heavy" in route_map
    assert "none" in route_map

    assert route_map["light"].target_id == 20236167
    assert route_map["medium"].target_id == 71115871
    assert route_map["medium"].is_default is True
    assert route_map["heavy"].target_id == 1044587686
    assert route_map["none"].target_id == 71115871

    # Direct structural children: exactly 3
    assert len(details.child_references) == 3
    child_ids = {int(c.id_str) for c in details.child_references}
    assert child_ids == {20236167, 71115871, 1044587686}

    # Hierarchy tree summary label
    obj = graph_index.objects_by_id[648180848]
    tname, summary = _get_object_summary(obj)
    assert tname == "SwitchCntr"
    assert summary == "3 children (4 routes)"


def test_ran_seq_container_semantics() -> None:
    """Verifies playlist, weight percentages, and mode calculation for CAkRanSeqCntr."""
    bank = SoundBank()
    cntr = CAkRanSeqCntr(
        id=555001,
        children=[101, 102],
        playlist=[
            AkPlaylistItem(play_id=101, weight=75),
            AkPlaylistItem(play_id=102, weight=25),
        ],
        mode=0,
        random_mode=1,
    )
    bank.hirc = HircChunk(objects=[cntr])

    graph_index = BankGraphIndex.build(bank)
    details = build_details_for_node(bank, graph_index, "hirc:555001")

    assert details is not None
    sem = details.ran_seq_semantics
    assert sem is not None
    assert sem.mode_str == "Random (Shuffle)"
    assert len(sem.playlist) == 2

    p1 = sem.playlist[0]
    assert p1.play_id == 101
    assert p1.weight == 75
    assert p1.weight_percent == 75.0

    p2 = sem.playlist[1]
    assert p2.play_id == 102
    assert p2.weight == 25
    assert p2.weight_percent == 25.0

    tname, summary = _get_object_summary(cntr)
    assert tname == "RanSeqCntr"
    assert summary == "2 children (2 items)"
