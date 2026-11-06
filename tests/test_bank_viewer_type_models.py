from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk, DidxChunk, DidxEntry
from src.bnk.models import (
    AkMusicTrackSource,
    CAkAction,
    CAkEvent,
    CAkMusicTrack,
    CAkRanSeqCntr,
    CAkSound,
)
from src.engine.graph import BankGraphIndex
from src.ui.features.bank_viewer.builder import (
    build_details_for_node,
    build_tree_and_details_from_bank,
)
from src.ui.features.bank_viewer.state import BankViewerState, HistoryLocation, InspectorViewType


def test_inspector_view_type_categorization():
    bank = SoundBank(header=BkhdChunk(bank_id=100), hirc=HircChunk())
    sound = CAkSound(id=101, source_id=999, stream_type=2)
    cntr = CAkRanSeqCntr(id=102, children=[101])
    event = CAkEvent(id=103, actions=[104])
    action = CAkAction(id=104, id_ext=102)
    music = CAkMusicTrack(id=105)
    bank.hirc.objects = [sound, cntr, event, action, music]
    graph = BankGraphIndex.build(bank)

    det_sound = build_details_for_node(bank, graph, "hirc:101")
    assert det_sound is not None
    assert det_sound.view_type == InspectorViewType.SOUND

    det_cntr = build_details_for_node(bank, graph, "hirc:102")
    assert det_cntr is not None
    assert det_cntr.view_type == InspectorViewType.CONTAINER
    assert any(ref.key == "hirc:101" for ref in det_cntr.child_references)

    det_event = build_details_for_node(bank, graph, "hirc:103")
    assert det_event is not None
    assert det_event.view_type == InspectorViewType.EVENT_ACTION

    det_action = build_details_for_node(bank, graph, "hirc:104")
    assert det_action is not None
    assert det_action.view_type == InspectorViewType.EVENT_ACTION

    det_music = build_details_for_node(bank, graph, "hirc:105")
    assert det_music is not None
    assert det_music.view_type == InspectorViewType.MUSIC


def test_media_inspector_details_references():
    bank = SoundBank(
        header=BkhdChunk(bank_id=200),
        didx=DidxChunk(entries=[DidxEntry(file_id=5001, offset=0, size=1024)]),
        hirc=HircChunk(),
    )
    sound = CAkSound(id=201, source_id=5001, stream_type=0)
    bank.hirc.objects = [sound]
    graph = BankGraphIndex.build(bank)

    _, _, details = build_tree_and_details_from_bank(bank, graph)
    media_det = details.get("media:5001")
    assert media_det is not None
    assert media_det.view_type == InspectorViewType.MEDIA
    assert any(ref.key == "hirc:201" for ref in media_det.parent_references)


def test_bank_viewer_state_navigation_properties():
    loc1 = HistoryLocation(bank_name="a.bnk", node_key="hirc:1")
    loc2 = HistoryLocation(bank_name="a.bnk", node_key="hirc:2")
    state = BankViewerState(navigation_history=(loc1, loc2), history_index=1)
    assert state.can_navigate_back is True
    assert state.can_navigate_forward is False

    state_start = BankViewerState(navigation_history=(loc1, loc2), history_index=0)
    assert state_start.can_navigate_back is False
    assert state_start.can_navigate_forward is True


def test_music_track_multi_source_media_reference():
    bank = SoundBank(
        header=BkhdChunk(bank_id=300),
        didx=DidxChunk(
            entries=[
                DidxEntry(file_id=8001, offset=0, size=1024),
                DidxEntry(file_id=8002, offset=1024, size=2048),
            ]
        ),
        hirc=HircChunk(),
    )
    track = CAkMusicTrack(
        id=301,
        sources=[
            AkMusicTrackSource(source_id=8001),
            AkMusicTrackSource(source_id=8002),
        ],
    )
    bank.hirc.objects = [track]
    graph = BankGraphIndex.build(bank)

    _, _, details = build_tree_and_details_from_bank(bank, graph)
    media_det1 = details.get("media:8001")
    media_det2 = details.get("media:8002")

    assert media_det1 is not None
    assert any(ref.key == "hirc:301" for ref in media_det1.parent_references)

    assert media_det2 is not None
    assert any(ref.key == "hirc:301" for ref in media_det2.parent_references)
