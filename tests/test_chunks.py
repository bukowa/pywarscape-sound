from src.bnk.chunks import BkhdChunk, DataChunk, DidxChunk, DidxEntry, StidChunk, WemHeader
from src.bnk.stream import ByteReader, ByteWriter


def test_bkhd_roundtrip():
    bkhd = BkhdChunk(
        version=112,
        bank_id=12345,
        language_id=0,
        feedback_in_bank=0,
        project_id=1,
        padding=b"\x00" * 8,
    )
    encoded = bkhd.to_bytes()
    decoded = BkhdChunk.read(ByteReader(encoded))
    assert decoded.version == 112
    assert decoded.bank_id == 12345
    assert decoded.to_bytes() == encoded


def test_didx_and_data_alignment():
    entries = [
        DidxEntry(file_id=101, offset=0, size=24),
        DidxEntry(file_id=102, offset=32, size=18),
    ]
    didx = DidxChunk(entries=entries)
    encoded = didx.to_bytes()
    decoded = DidxChunk.read(ByteReader(encoded))
    assert len(decoded.entries) == 2
    assert decoded.entries[0].file_id == 101

    data = DataChunk(b"\xaa" * 24 + b"\x00" * 8 + b"\xbb" * 18)
    assert data.extract(0, 24) == b"\xaa" * 24
    assert data.extract(32, 18) == b"\xbb" * 18

    # Test align and append
    dc = DataChunk()
    off1, sz1 = dc.align_and_append(b"\x11" * 10)
    assert off1 == 0
    assert sz1 == 10
    off2, sz2 = dc.align_and_append(b"\x22" * 5)
    assert off2 == 16
    assert sz2 == 5
    assert len(dc.data) == 21
    assert dc.extract(16, 5) == b"\x22" * 5


def test_stid_roundtrip():
    stid = StidChunk(bank_names={1001: "bank_one", 1002: "bank_two"})
    encoded = stid.to_bytes()
    decoded = StidChunk.read(ByteReader(encoded))
    assert decoded.bank_names[1001] == "bank_one"
    assert decoded.bank_names[1002] == "bank_two"
    assert decoded.to_bytes() == encoded


def test_wem_header_reading():
    # Construct a minimal RIFF WAVE buffer
    w = ByteWriter()
    w.write_bytes(b"RIFF")
    w.write_u32(4 + 8 + 16 + 8 + 100)  # riff size
    w.write_bytes(b"WAVE")
    # fmt chunk
    w.write_bytes(b"fmt ")
    w.write_u32(16)
    w.write_struct("<HHIIHH", 0xFFFF, 2, 44100, 176400, 4, 16)
    # data chunk
    w.write_bytes(b"data")
    w.write_u32(100)
    w.write_bytes(b"\x00" * 100)

    raw = w.get_bytes()
    wem = WemHeader.read(ByteReader(raw))
    assert wem.format_code == 0xFFFF
    assert wem.channels == 2
    assert wem.sample_rate == 44100
    assert wem.avg_bytes_per_sec == 176400
    assert wem.block_align == 4
    assert wem.bits_per_sample == 16
    assert wem.data_size == 100
    assert wem.data_offset == 44
    assert abs(wem.duration_ms - (100 / 176400 * 1000.0)) < 1e-4
