import pytest

from src.bnk.models import (
    AkPlaylistItem,
    CAkAction,
    CAkActorMixer,
    CAkAttenuation,
    CAkEvent,
    CAkLayerCntr,
    CAkMusicTrack,
    CAkRanSeqCntr,
    CAkSound,
    CAkSwitchCntr,
    parse_hirc_object,
)
from src.bnk.stream import ByteReader, ByteWriter
from tests.support.factories import skip_or_fail_missing_asset


def test_sound_object_framing_and_roundtrip():
    sound = CAkSound(
        id=99901,
        source_id=12345,
        file_id=12345,
        stream_type=2,
    )
    raw = sound.to_bytes()
    assert len(raw) >= 9
    reader = ByteReader(raw)
    parsed = parse_hirc_object(reader)
    assert isinstance(parsed, CAkSound)
    assert parsed.id == 99901
    assert parsed.source_id == 12345
    assert parsed.stream_type == 2
    assert parsed.to_bytes() == raw


def test_event_and_action_roundtrip():
    event = CAkEvent(id=2001, actions=[3001, 3002])
    raw_event = event.to_bytes()
    parsed_event = parse_hirc_object(ByteReader(raw_event))
    assert isinstance(parsed_event, CAkEvent)
    assert parsed_event.actions == [3001, 3002]
    assert parsed_event.to_bytes() == raw_event

    action = CAkAction.create_play(id=3001, target_id=99901, bank_id=500)
    raw_action = action.to_bytes()
    parsed_action = parse_hirc_object(ByteReader(raw_action))
    assert isinstance(parsed_action, CAkAction)
    assert parsed_action.id_ext == 99901
    assert parsed_action.to_bytes() == raw_action


def test_bounded_slice_protects_bounds():
    writer = ByteWriter()
    writer.write_u8(2)  # Type 2: Sound
    writer.write_u32(8)  # only 8 bytes payload (too short for sound)
    writer.write_u32(1001)
    writer.write_bytes(b"\x00" * 4)
    reader = ByteReader(writer.get_bytes())
    with pytest.raises(EOFError):
        parse_hirc_object(reader)


def test_random_sequence_container_roundtrip():
    container = CAkRanSeqCntr(
        id=5001,
        children=[101, 102, 103],
    )
    raw = container.to_bytes()
    parsed = parse_hirc_object(ByteReader(raw))
    assert isinstance(parsed, CAkRanSeqCntr)
    assert parsed.id == 5001
    assert parsed.children == [101, 102, 103]
    assert parsed.to_bytes() == raw


def test_synthetic_hirc_objects_roundtrip_all_types():
    """Hermetic comprehensive verification: round-trip serialization across multiple HIRC types."""
    objects = [
        CAkSound(id=1001, plugin_id=0x40001, stream_type=2, source_id=2001, file_id=2001),
        CAkAction.create_play(id=1002, target_id=1001),
        CAkEvent(id=1003, actions=[1002]),
        CAkRanSeqCntr(
            id=1004,
            children=[1001],
            playlist=[AkPlaylistItem(play_id=1001, weight=50)],
        ),
        CAkSwitchCntr(
            id=1005,
            group_type=1,
            group_id=999,
            default_switch=888,
            children=[1001],
            switch_map={888: [1001]},
        ),
        CAkActorMixer(id=1006, children=[1001, 1004]),
        CAkLayerCntr(id=1007, children=[1001]),
        CAkAttenuation(id=1008),
    ]

    for obj in objects:
        raw = obj.to_bytes()
        parsed = parse_hirc_object(ByteReader(raw))
        assert type(parsed) is type(obj), f"Mismatch type for {type(obj).__name__}"
        assert parsed.id == obj.id, f"ID mismatch for {type(obj).__name__}"
        assert parsed.to_bytes() == raw, f"Bit-exact round-trip failed for {type(obj).__name__}"


@pytest.mark.assets
def test_real_hirc_chunks_roundtrip():
    import glob
    import os
    import struct

    banks = glob.glob(os.path.join(".cache", "attila", "audio", "*.bnk"))
    if not banks:
        skip_or_fail_missing_asset("No cached banks found")

    tested_objects = 0
    # Test banks that contain HIRC chunks
    for b in banks:
        with open(b, "rb") as f:
            data = f.read()
        idx = 0
        while idx < len(data):
            fourcc = data[idx : idx + 4]
            if len(fourcc) < 4:
                break
            chunk_len = struct.unpack_from("<I", data, idx + 4)[0]
            chunk_data = data[idx + 8 : idx + 8 + chunk_len]
            idx += 8 + chunk_len
            if fourcc == b"HIRC":
                r = ByteReader(chunk_data)
                count = r.read_u32()
                for _ in range(count):
                    obj_start = r.offset
                    r.read_u8()
                    obj_len = r.read_u32()
                    expected_raw = chunk_data[obj_start : obj_start + 5 + obj_len]
                    r.seek(obj_start)
                    parsed = parse_hirc_object(r)
                    assert parsed.to_bytes() == expected_raw
                    tested_objects += 1
        if tested_objects > 1000:
            break

    assert tested_objects > 1000


def test_hirc_framing_and_robustness():
    from src.bnk.models import (
        ActionParams,
        AkMusicTrackSource,
        AkTrackSrcInfo,
    )

    # 1. ActionParams invalid category fails fast
    with pytest.raises(ValueError, match="Unsupported action category"):
        ActionParams.from_bytes(b"\x00\x00\x00\x00", action_type=0xFE01)

    # 2. AkMusicTrackSource with stream_type != 2 and file_offset=None writes 4-byte 0
    src = AkMusicTrackSource(plugin_id=1, stream_type=0, source_id=10, file_id=20, file_offset=None)
    w = ByteWriter()
    src.write(w)
    r = ByteReader(w.get_bytes())
    read_back = AkMusicTrackSource.read(r)
    assert read_back.file_offset == 0
    assert r.remaining == 0

    # 3. CAkMusicTrack with playlist non-empty and num_sub_track=None writes 1
    track = CAkMusicTrack(
        id=99,
        sources=[src],
        playlist=[AkTrackSrcInfo(track_id=1)],
        num_sub_track=None,
    )
    raw_track = track.to_bytes()
    r = ByteReader(raw_track)
    parsed_track = parse_hirc_object(r)
    assert isinstance(parsed_track, CAkMusicTrack)
    assert parsed_track.num_sub_track == 1

    # 4. CAkAttenuation with cone_enabled=1 and cone_params=None writes 5 zero floats
    atten = CAkAttenuation(id=55, cone_enabled=1, cone_params=None)
    raw_atten = atten.to_bytes()
    r = ByteReader(raw_atten)
    parsed_atten = parse_hirc_object(r)
    assert isinstance(parsed_atten, CAkAttenuation)
    assert parsed_atten.cone_enabled == 1
    assert parsed_atten.cone_params == (0.0, 0.0, 0.0, 0.0, 0.0)
