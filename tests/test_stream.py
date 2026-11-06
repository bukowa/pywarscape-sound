import pytest

from src.bnk.stream import ByteReader, ByteWriter


def test_reader_primitives_and_struct():
    writer = ByteWriter()
    writer.write_struct("<IBf", 123456, 42, 3.14)
    writer.write_bytes(b"TEST")
    writer.pad_to(16, 0x00)
    data = writer.get_bytes()
    assert len(data) % 16 == 0

    reader = ByteReader(data)
    u32, u8, f32 = reader.read_struct("<IBf")
    assert u32 == 123456
    assert u8 == 42
    assert abs(f32 - 3.14) < 1e-5
    assert reader.read_fourcc() == "TEST"


def test_reader_slice_bounds():
    reader = ByteReader(b"\x01\x02\x03\x04\x05")
    sub = reader.read_slice(3)
    assert sub.read_bytes(3) == b"\x01\x02\x03"
    with pytest.raises(EOFError):
        sub.read_u8()
    assert reader.read_bytes(2) == b"\x04\x05"


def test_reader_bounds_error():
    reader = ByteReader(b"\x01\x02")
    assert reader.read_u16() == 0x0201
    with pytest.raises(EOFError):
        reader.read_u8()
    with pytest.raises(EOFError):
        reader.read_bytes(1)
    with pytest.raises(EOFError):
        reader.read_struct("<I")


def test_writer_primitives():
    w = ByteWriter()
    w.write_u8(1)
    w.write_i8(-1)
    w.write_u16(0x1234)
    w.write_i16(-200)
    w.write_u32(0x12345678)
    w.write_i32(-50000)
    w.write_u64(0x1122334455667788)
    w.write_i64(-999999999)
    w.write_f32(1.5)
    w.write_f64(2.75)
    assert w.length == len(w.get_bytes())

    r = ByteReader(w.get_bytes())
    assert r.read_u8() == 1
    assert r.read_i8() == -1
    assert r.read_u16() == 0x1234
    assert r.read_i16() == -200
    assert r.read_u32() == 0x12345678
    assert r.read_i32() == -50000
    assert r.read_u64() == 0x1122334455667788
    assert r.read_i64() == -999999999
    assert r.read_f32() == 1.5
    assert r.read_f64() == 2.75
    assert r.remaining == 0
