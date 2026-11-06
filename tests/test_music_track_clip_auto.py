from src.bnk.models import CAkMusicTrack, parse_hirc_object
from src.bnk.stream import ByteReader


def test_music_track_with_word_swapped_clip_automations():
    """
    Verifies that CAkMusicTrack can deserialize real-world mod tracks where the
    clip automation count is formatted as big-endian / word-swapped 0x00000100 (256)
    while the actual payload contains 1 automation item with 3 points.
    """
    raw_track_hex = (
        "0ba0000000c3e4be0e00010000000100040002ecff9d39ecff9d3900000000000100000000"
        "000000ecff9d390000000000000000000000000000000000000000000000004fc1cb2978c9"
        "114101000000000100000000000000000000030000000000000000000000090000004cfc10"
        "430000000004000000ef6e1143000000000400000000000000000000e88cdd2d000000c000"
        "000100000000000000000000002c010000"
    )
    raw_bytes = bytes.fromhex(raw_track_hex)
    reader = ByteReader(raw_bytes)

    # Must parse cleanly without EOFError
    track = parse_hirc_object(reader)
    assert isinstance(track, CAkMusicTrack)
    assert track.id == 247391427
    assert len(track.clip_automations) == 1
    assert len(track.clip_automations[0].points) == 3
    assert track.node_base_params.direct_parent_id == 769494248
    assert track.track_type == 0
    assert track.look_ahead_time == 300
