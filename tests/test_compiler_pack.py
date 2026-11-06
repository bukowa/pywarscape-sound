from pathlib import Path

import pytest

from src.compiler.pfh4_pack import (
    MASK_ENCRYPTED_DATA,
    PFH4_MAGIC,
    PT_RELEASE,
    decrypt_pfh4_stream,
    extract_pfh4_file,
    normalize_pack_path,
    read_pfh4_index,
    write_pfh4_movie_pack,
)


def test_pfh4_pack_roundtrip(tmp_path: Path):
    pack_file = tmp_path / "test_mod.pack"
    files = {
        "audio/test.bnk": b"BKHD\x04\x00\x00\x00\x70\x00\x00\x00",
        "audio/123.wem": b"RIFF\x04\x00\x00\x00WAVE",
    }
    write_pfh4_movie_pack(pack_file, files)
    assert pack_file.is_file()

    entries = read_pfh4_index(pack_file)
    assert len(entries) == 2
    paths = {e.path.replace("\\", "/") for e in entries}
    assert paths == {"audio/test.bnk", "audio/123.wem"}

    for e in entries:
        norm = e.path.replace("\\", "/")
        data = extract_pfh4_file(pack_file, e)
        assert data == files[norm]


def test_invalid_pfh4_header(tmp_path: Path):
    corrupt = tmp_path / "corrupt.pack"
    corrupt.write_bytes(b"INVALID_HEADER_BYTES_1234567890")
    with pytest.raises(ValueError):
        read_pfh4_index(corrupt)


def test_normalize_pack_path():
    assert normalize_pack_path("audio/test.bnk") == "audio\\test.bnk"
    assert normalize_pack_path("audio\\test.bnk") == "audio\\test.bnk"
    with pytest.raises(ValueError):
        normalize_pack_path("../escaped.txt")


def test_extract_truncated_payload(tmp_path: Path):
    pack_file = tmp_path / "truncated.pack"
    files = {
        "audio/test.bnk": b"A" * 100,
    }
    write_pfh4_movie_pack(pack_file, files)
    entries = read_pfh4_index(pack_file)
    assert len(entries) == 1

    # Truncate pack file so it cuts off the payload halfway
    full_data = pack_file.read_bytes()
    truncated_data = full_data[:-50]
    pack_file.write_bytes(truncated_data)

    with pytest.raises(EOFError, match="Corrupted or truncated pack"):
        extract_pfh4_file(pack_file, entries[0])


def test_encrypted_pfh4_pack_extraction(tmp_path: Path):
    import struct

    pack_file = tmp_path / "encrypted.pack"
    plaintext = b"BKHD\x1c\x00\x00\x00p\x00\x00\x00\x01\x02\x03\x04HelloEncryptedTotalWarSoundBank"
    encrypted_payload = decrypt_pfh4_stream(plaintext)
    assert encrypted_payload != plaintext

    norm_path = "audio\\test_encrypted.bnk"
    idx_buf = bytearray()
    idx_buf.extend(struct.pack("<I", len(encrypted_payload)))
    idx_buf.extend(norm_path.encode("utf-8") + b"\x00")

    hdr = struct.pack(
        "<4sIIIIII",
        PFH4_MAGIC,
        PT_RELEASE | MASK_ENCRYPTED_DATA,
        0,
        0,
        1,
        len(idx_buf),
        0,
    )

    pack_file.write_bytes(hdr + idx_buf + encrypted_payload)

    # 1. Verify index detection
    entries = read_pfh4_index(pack_file)
    assert len(entries) == 1
    assert entries[0].is_encrypted is True

    # 2. Verify native stream decryption on extraction
    decrypted = extract_pfh4_file(pack_file, entries[0])
    assert decrypted == plaintext


def test_write_pfh4_mod_pack_default_type(tmp_path: Path):
    from src.compiler.pfh4_pack import (
        PT_MOD,
        read_pfh4_pack_type,
        write_pfh4_mod_pack,
        write_pfh4_pack,
    )

    # 1. write_pfh4_mod_pack creates PT_MOD (type 3)
    mod_pack = tmp_path / "mod_pack.pack"
    write_pfh4_mod_pack(mod_pack, {"audio/test.bnk": b"DATA"})
    assert read_pfh4_pack_type(mod_pack) == PT_MOD

    # 2. write_pfh4_pack defaults to PT_MOD (type 3)
    default_pack = tmp_path / "default_pack.pack"
    write_pfh4_pack(default_pack, {"audio/test.bnk": b"DATA"})
    assert read_pfh4_pack_type(default_pack) == PT_MOD
