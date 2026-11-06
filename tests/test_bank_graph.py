"""Tests for src.engine.graph (Layer 2 Pure Engine SoundBank Graph)."""

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.models import (
    AkMusicTrackSource,
    AkPlaylistItem,
    AkTrackSrcInfo,
    CAkAction,
    CAkActorMixer,
    CAkEvent,
    CAkMusicSegment,
    CAkMusicTrack,
    CAkRanSeqCntr,
    CAkSound,
    CAkSwitchCntr,
)
from src.engine.graph import (
    BankGraphIndex,
    categorize_bank_objects,
    compute_root_objects,
    get_child_ids_for_object,
    resolve_hash_name,
    resolve_object_label,
)
from src.models.hashing import MASTER_EVENT_PLAY_BATTLE_VO_ORDERS


def test_child_ids_for_all_hierarchy_types():
    # Event -> Action
    ev = CAkEvent(id=10, actions=[101, 102])
    assert get_child_ids_for_object(ev) == [101, 102]

    # Action -> Target
    act = CAkAction.create_play(id=101, target_id=201)
    assert get_child_ids_for_object(act) == [201]

    # RanSeq -> Playlist & Children
    rs = CAkRanSeqCntr(
        id=201,
        children=[301],
        playlist=[AkPlaylistItem(play_id=302, weight=10000)],
    )
    assert set(get_child_ids_for_object(rs)) == {301, 302}

    # SwitchCntr -> Switch map & Children
    sw = CAkSwitchCntr(
        id=202,
        children=[401],
        switch_map={1001: [402, 403]},
    )
    assert set(get_child_ids_for_object(sw)) == {401, 402, 403}

    # MusicSegment -> Child IDs
    ms = CAkMusicSegment(id=501, child_ids=[601, 602])
    assert get_child_ids_for_object(ms) == [601, 602]

    # ActorMixer -> Children
    am = CAkActorMixer(id=701, children=[801, 802])
    assert get_child_ids_for_object(am) == [801, 802]

    # Sound (leaf) -> Empty
    snd = CAkSound(id=801)
    assert get_child_ids_for_object(snd) == []


def test_categorize_bank_objects():
    snd = CAkSound(id=1)
    ev = CAkEvent(id=2)
    act = CAkAction(id=3)
    rs = CAkRanSeqCntr(id=4)
    sw = CAkSwitchCntr(id=5)
    am = CAkActorMixer(id=6)

    bank = SoundBank(hirc=HircChunk(objects=[snd, ev, act, rs, sw, am]))
    cats = categorize_bank_objects(bank)

    assert cats["sounds"] == [snd]
    assert cats["events"] == [ev]
    assert cats["actions"] == [act]
    assert cats["ran_seq_cntrs"] == [rs]
    assert cats["switch_cntrs"] == [sw]
    assert cats["actor_mixers"] == [am]


def test_compute_root_objects():
    # Tree: Event (1) -> Action (2) -> Sound (3)
    # Plus unparented SwitchCntr (4) -> Sound (5)
    ev = CAkEvent(id=1, actions=[2])
    act = CAkAction.create_play(id=2, target_id=3)
    snd1 = CAkSound(id=3)
    sw = CAkSwitchCntr(id=4, children=[5])
    snd2 = CAkSound(id=5)

    bank = SoundBank(hirc=HircChunk(objects=[ev, act, snd1, sw, snd2]))
    roots = compute_root_objects(bank)

    root_ids = [r.id for r in roots]
    assert 1 in root_ids  # Event is natural root
    assert 4 in root_ids  # Unparented SwitchCntr is natural root
    assert 2 not in root_ids  # Action is child of Event
    assert 3 not in root_ids  # Sound is child of Action
    assert 5 not in root_ids  # Sound is child of SwitchCntr


def test_bidirectional_graph_index():
    ev = CAkEvent(id=10, actions=[20])
    act = CAkAction.create_play(id=20, target_id=30)
    snd = CAkSound(id=30)

    bank = SoundBank(hirc=HircChunk(objects=[ev, act, snd]))
    index = BankGraphIndex.build(bank)

    # O(1) child lookups
    assert index.get_child_ids(10) == [20]
    assert index.get_child_ids(20) == [30]
    assert index.get_child_ids(30) == []

    # O(1) parent lookups
    assert index.get_parent_ids(30) == [20]
    assert index.get_parent_ids(20) == [10]
    assert index.get_parent_ids(10) == []


def test_resolve_hash_name_and_label():
    bank = SoundBank()
    name = resolve_hash_name(MASTER_EVENT_PLAY_BATTLE_VO_ORDERS, bank)
    assert name == "Play_Battle_VO_Orders"

    # Sound label resolution
    snd = CAkSound(id=100, source_id=98765, stream_type=2)
    bank_with_snd = SoundBank(hirc=HircChunk(objects=[snd]))
    lbl = resolve_object_label(
        snd,
        bank_with_snd,
        name_resolver=lambda _: None,
    )
    assert "98765" in lbl or "Sound" in lbl


def test_bank_graph_wem_references_empty():
    """Verify empty bank or bank without audio leaves has empty WEM index."""
    bank = SoundBank()
    index = BankGraphIndex.build(bank)
    assert index.wem_references == {}
    assert index.get_wem_referencing_hirc_ids(12345) == []
    assert index.get_wem_referencing_hirc_ids(0) == []
    assert index.get_wem_referencing_hirc_ids(-1) == []


def test_bank_graph_wem_references_sound():
    """Verify CAkSound source and file IDs are properly indexed and shared WEMs map to all nodes."""
    snd1 = CAkSound(id=10, source_id=1001, stream_type=2)
    snd2 = CAkSound(id=20, source_id=1001, stream_type=0)  # Shared WEM
    snd3 = CAkSound(id=30, file_id=2002, source_id=0, stream_type=2)
    snd_empty = CAkSound(id=40, source_id=0, file_id=0)

    bank = SoundBank(hirc=HircChunk(objects=[snd1, snd2, snd3, snd_empty]))
    index = BankGraphIndex.build(bank)

    assert index.get_wem_referencing_hirc_ids(1001) == [10, 20]
    assert index.get_wem_referencing_hirc_ids(2002) == [30]
    assert index.get_wem_referencing_hirc_ids(9999) == []


def test_bank_graph_wem_references_music_track():
    """Verify CAkMusicTrack sources and playlist clips are indexed without duplicating node ID."""
    track1 = CAkMusicTrack(
        id=50,
        sources=[
            AkMusicTrackSource(source_id=3001, stream_type=2),
            AkMusicTrackSource(source_id=3002, stream_type=2),
        ],
    )
    track2 = CAkMusicTrack(
        id=60,
        playlist=[AkTrackSrcInfo(source_id=3001)],
    )
    # Track with repeated source references for the same WEM
    track3 = CAkMusicTrack(
        id=70,
        sources=[
            AkMusicTrackSource(source_id=4001),
            AkMusicTrackSource(source_id=4001),
        ],
        playlist=[
            AkTrackSrcInfo(source_id=4001),
            AkTrackSrcInfo(source_id=4001),
        ],
    )
    # Track with direct source
    track4 = CAkMusicTrack(
        id=80,
        sources=[AkMusicTrackSource(source_id=5001)],
        playlist=[],
    )

    bank = SoundBank(hirc=HircChunk(objects=[track1, track2, track3, track4]))
    index = BankGraphIndex.build(bank)

    assert index.get_wem_referencing_hirc_ids(3001) == [50, 60]
    assert index.get_wem_referencing_hirc_ids(3002) == [50]
    assert index.get_wem_referencing_hirc_ids(4001) == [70]  # Deduplicated: exactly 1 entry
    assert index.get_wem_referencing_hirc_ids(5001) == [80]


def test_bank_graph_get_wem_referencing_hirc_ids_returns_copy():
    """Verify modifying returned ID list does not mutate internal graph state."""
    snd = CAkSound(id=10, source_id=1001)
    bank = SoundBank(hirc=HircChunk(objects=[snd]))
    index = BankGraphIndex.build(bank)

    res = index.get_wem_referencing_hirc_ids(1001)
    assert res == [10]
    res.append(999)
    assert index.get_wem_referencing_hirc_ids(1001) == [10]
