from pathlib import Path

import pytest

from src.bnk.wem import (
    WemFormatTag,
    build_pcm_wem_from_wav_bytes,
    build_silent_pcm_wem_bytes,
    parse_wem_file,
    parse_wem_header,
    repair_extracted_wem_bytes,
    validate_wem_bytes,
)


def test_build_silent_pcm_wem():
    silent = build_silent_pcm_wem_bytes(duration_ms=50)
    is_valid, errors = validate_wem_bytes(silent)
    assert is_valid is True
    assert errors == []

    header = parse_wem_header(silent)
    assert header.format_tag == WemFormatTag.EXTENSIBLE
    assert header.sample_rate == 32000
    assert header.channels == 1
    assert 45.0 <= header.duration_ms <= 55.0


def test_parse_wem_file(tmp_path: Path):
    silent = build_silent_pcm_wem_bytes(duration_ms=100)
    file_path = tmp_path / "123.wem"
    file_path.write_bytes(silent)

    header = parse_wem_file(file_path)
    assert header.sample_rate == 32000
    assert header.channels == 1
    assert 90.0 <= header.duration_ms <= 110.0


def test_validate_invalid_wem():
    is_valid, errors = validate_wem_bytes(b"NOT_A_RIFF_HEADER")
    assert is_valid is False
    assert len(errors) > 0

    with pytest.raises(ValueError):
        parse_wem_header(b"RIFF\x00\x00\x00\x00WAVEfmt ")


def test_build_pcm_wem_from_raw_pcm():
    raw_pcm = b"\x00\x00" * 320  # 320 samples @ 32kHz = 10ms
    wem_bytes = build_pcm_wem_from_wav_bytes(raw_pcm, target_sample_rate=32000, target_channels=1)
    is_valid, errors = validate_wem_bytes(wem_bytes)
    assert is_valid is True
    header = parse_wem_header(wem_bytes)
    assert header.sample_rate == 32000
    assert header.channels == 1
    assert 9.0 <= header.duration_ms <= 11.0


def test_repair_extracted_wem_bytes():
    import struct

    # 1. Non-RIFF or too short bytes are untouched
    assert repair_extracted_wem_bytes(b"short") == b"short"
    assert repair_extracted_wem_bytes(b"NOT_A_RIFF_WEM_1234") == b"NOT_A_RIFF_WEM_1234"

    # 2. Already compliant WEM is returned unchanged
    clean = build_silent_pcm_wem_bytes(duration_ms=50)
    assert repair_extracted_wem_bytes(clean) == clean

    # 3. Simulate legacy archive encryption keystream defect on valid WEM
    orig_len = len(clean)
    pad = (8 - (orig_len % 8)) % 8
    buf = bytearray(clean) + bytearray(pad)
    chunks = len(buf) // 8
    data_key = 0x8FEB2A6740A6920E

    for i in range(chunks):
        off = i * 8
        k_ca = (((~off) & 0xFFFFFFFF) * data_key) & 0xFFFFFFFFFFFFFFFF
        if orig_len % 8 == 0 and i == chunks - 1:
            val = struct.unpack_from("<Q", buf, off)[0]
            struct.pack_into("<Q", buf, off, val ^ k_ca)
        elif i < orig_len // 8:
            k_tool = (((~off) & 0xFFFFFFFFFFFFFFFF) * data_key) & 0xFFFFFFFFFFFFFFFF
            diff = k_ca ^ k_tool
            val = struct.unpack_from("<Q", buf, off)[0]
            struct.pack_into("<Q", buf, off, val ^ diff)

    defective_payload = bytes(buf[:orig_len])
    assert defective_payload != clean
    # Defective header has obfuscated chunk id instead of fmt
    assert defective_payload[12:16] != b"fmt "

    # Repair restores exact bit-for-bit bytes
    repaired = repair_extracted_wem_bytes(defective_payload)
    assert repaired == clean

    # Automatic transparent repair in parse_wem_header
    hdr = parse_wem_header(defective_payload)
    assert hdr.sample_rate == 32000
    assert hdr.channels == 1
