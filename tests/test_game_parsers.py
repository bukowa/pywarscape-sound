"""Hermetic unit tests for game-specific SoundBank HIRC parsers (Attila vs Rome II)."""

from src.bnk.bank import HircChunk
from src.bnk.models import AkAttenuationCurve, CAkAction, CAkGenericHirc
from src.bnk.parser_attila import parse_attila_hirc_object
from src.bnk.parser_rome2 import CAkAttenuationV88, parse_rome2_hirc_object
from src.bnk.stream import ByteReader, ByteWriter


def test_parse_attila_hirc_object():
    """Attila parser delegates to standard Wwise v112 AST."""
    action = CAkAction.create_play(id=501, target_id=601)
    raw = action.to_bytes()

    reader = ByteReader(raw)
    parsed = parse_attila_hirc_object(reader)

    assert isinstance(parsed, CAkAction)
    assert parsed.id == 501
    assert parsed.target_id == 601
    assert parsed.to_bytes() == raw


def test_parse_rome2_v88_attenuation():
    """Rome II parser handles legacy 5-curve, 4-float cone attenuation."""
    att = CAkAttenuationV88(
        id=701,
        cone_enabled=1,
        cone_params=(30.0, 90.0, -6.0, 0.0),
        curve_to_use=[0, 1, 2, 3, 4],
        curves=[AkAttenuationCurve(scaling=0, points=[(0.0, 0.0, 4), (100.0, -1.0, 4)])],
    )
    raw = att.to_bytes()

    reader = ByteReader(raw)
    parsed = parse_rome2_hirc_object(reader)

    assert isinstance(parsed, CAkAttenuationV88)
    assert parsed.id == 701
    assert parsed.cone_enabled == 1
    assert parsed.cone_params == (30.0, 90.0, -6.0, 0.0)
    assert parsed.curve_to_use == [0, 1, 2, 3, 4]
    assert len(parsed.curves) == 1
    assert parsed.to_bytes() == raw


def test_parse_rome2_generic_fallback():
    """Rome II parser preserves unmodeled legacy object records bit-exact."""
    dummy_body = b"\xde\xad\xbe\xef\x01\x02\x03\x04"
    w = ByteWriter()
    w.write_u8(99)  # unmodeled type
    w.write_u32(4 + len(dummy_body))
    w.write_u32(801)
    w.write_bytes(dummy_body)
    raw = w.get_bytes()

    reader = ByteReader(raw)
    parsed = parse_rome2_hirc_object(reader)

    assert isinstance(parsed, CAkGenericHirc)
    assert parsed.id == 801
    assert parsed.obj_type == 99
    assert parsed.raw_body == dummy_body
    assert parsed.to_bytes() == raw


def test_hirc_chunk_version_routing():
    """HircChunk.read dynamically routes between Rome II (<=88) and Attila (v112)."""
    # Create an object payload
    action = CAkAction.create_play(id=111, target_id=222)
    obj_raw = action.to_bytes()

    w = ByteWriter()
    w.write_u32(1)
    w.write_bytes(obj_raw)
    chunk_raw = w.get_bytes()

    # Read with version=88 (Rome II)
    r_rome = ByteReader(chunk_raw)
    chunk_rome = HircChunk.read(r_rome, version=88)
    assert len(chunk_rome.objects) == 1
    assert chunk_rome.objects[0].id == 111

    # Read with version=112 (Attila)
    r_attila = ByteReader(chunk_raw)
    chunk_attila = HircChunk.read(r_attila, version=112)
    assert len(chunk_attila.objects) == 1
    assert chunk_attila.objects[0].id == 111
