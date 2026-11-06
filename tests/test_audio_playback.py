import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.bnk.wem import build_silent_pcm_wem_bytes, repair_extracted_wem_bytes
from src.deps.player import (
    _run_vgmstream_decode,
    decode_wem_to_wav_bytes,
    play_wem_buffer,
    resolve_vgmstream_path,
)
from tests.support.factories import make_synthetic_wav, skip_or_fail_missing_asset


def test_resolve_vgmstream_path():
    vgmstream_path = resolve_vgmstream_path()
    assert vgmstream_path is not None
    assert vgmstream_path.is_file()
    assert vgmstream_path.name.lower().startswith("vgmstream-cli")


def test_resolve_vgmstream_path_frozen(tmp_path, monkeypatch):
    mock_bin = tmp_path / "vgmstream" / "vgmstream-cli.exe"
    mock_bin.parent.mkdir(parents=True)
    mock_bin.write_bytes(b"MZ")

    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys._MEIPASS", str(tmp_path), raising=False)

    resolved = resolve_vgmstream_path()
    assert resolved == mock_bin


@pytest.mark.assets
def test_decode_real_attila_wem_file_in_memory():
    sample_wem = Path(".cache/attila/audio/1000002818.wem")
    if not sample_wem.exists():
        skip_or_fail_missing_asset("Requires vanilla cache assets")

    # 1. Test decode from file path
    wav_bytes = decode_wem_to_wav_bytes(sample_wem)
    assert len(wav_bytes) > 44
    assert wav_bytes.startswith(b"RIFF")
    assert b"WAVE" in wav_bytes[:16]

    # 2. Test decode from raw bytes slice (ephemeral handling)
    raw_slice = sample_wem.read_bytes()
    wav_from_bytes = decode_wem_to_wav_bytes(raw_slice)
    assert wav_from_bytes == wav_bytes


@pytest.mark.assets
def test_decode_real_rome2_wem_file_in_memory():
    sample_wem = Path(".cache/rome_2/audio/1000051388.wem")
    if not sample_wem.exists():
        skip_or_fail_missing_asset("Requires vanilla cache assets")

    wav_bytes = decode_wem_to_wav_bytes(sample_wem)
    assert len(wav_bytes) > 44
    assert wav_bytes.startswith(b"RIFF")
    assert b"WAVE" in wav_bytes[:16]

    raw_slice = sample_wem.read_bytes()
    wav_from_bytes = decode_wem_to_wav_bytes(raw_slice)
    assert wav_from_bytes == wav_bytes


def test_decode_pcm_wem_pass_through():
    # Silent PCM 0xFFFE extensible container
    pcm_bytes = build_silent_pcm_wem_bytes(duration_ms=100, sample_rate=32000)

    # Subprocess should NOT be invoked for PCM pass-through
    with patch("subprocess.run") as mock_subproc:
        decoded = decode_wem_to_wav_bytes(pcm_bytes)
        assert decoded == pcm_bytes
        mock_subproc.assert_not_called()


def test_decode_nonexistent_file_raises():
    with pytest.raises(FileNotFoundError):
        decode_wem_to_wav_bytes(Path("nonexistent_path_to_audio_12345.wem"))


@pytest.mark.assets
def test_decode_legacy_encrypted_artifact_wem():
    sample_wem = Path(".cache/attila/audio/260275243.wem")
    if not sample_wem.exists():
        skip_or_fail_missing_asset("Requires vanilla cache assets")

    wav_bytes = decode_wem_to_wav_bytes(sample_wem)
    assert len(wav_bytes) > 44
    assert wav_bytes.startswith(b"RIFF")


def test_decode_subprocess_failure_raises_runtime_error(tmp_path: Path):
    corrupt_wem = tmp_path / "corrupt.wem"
    corrupt_wem.write_bytes(b"INVALID_HEADER_DATA_12345")

    with pytest.raises(RuntimeError) as exc_info:
        decode_wem_to_wav_bytes(corrupt_wem)

    assert "vgmstream-cli failed to decode" in str(exc_info.value)


def test_play_wem_buffer_playback():
    pcm_bytes = build_silent_pcm_wem_bytes(duration_ms=50, sample_rate=32000)
    channel = play_wem_buffer(pcm_bytes, volume=0.5)
    # Channel can be None if audio device is unavailable or returns pygame.mixer.Channel
    # Crucially, the function must execute without raising exceptions
    assert channel is None or hasattr(channel, "get_busy")


def test_test_environment_mutes_audio_playback():
    assert os.environ.get("SDL_AUDIODRIVER") == "dummy"


def test_decode_synthetic_wav_via_vgmstream(tmp_path: Path):
    """Hermetic test verifying that bundled vgmstream-cli executes and decodes audio."""
    wav_path = make_synthetic_wav(tmp_path / "synthetic.wav", duration_s=0.1, tone=True)
    decoded = _run_vgmstream_decode(wav_path)
    assert len(decoded) > 44
    assert decoded.startswith(b"RIFF")
    assert b"WAVE" in decoded[:16]


def test_repair_extracted_wem_bytes_synthetic():
    """Hermetic test verifying repair of synthetic corrupted and legacy encrypted audio payloads."""
    import struct

    # 1. Non-RIFF or too short bytes are untouched
    assert repair_extracted_wem_bytes(b"short") == b"short"
    assert repair_extracted_wem_bytes(b"NOT_A_RIFF_WEM_1234") == b"NOT_A_RIFF_WEM_1234"

    # 2. Already compliant WEM is returned unchanged
    clean = build_silent_pcm_wem_bytes(duration_ms=50)
    assert repair_extracted_wem_bytes(clean) == clean

    # 3. Simulate legacy keystream defect on valid WEM
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
    assert defective_payload[12:16] != b"fmt "

    repaired = repair_extracted_wem_bytes(defective_payload)
    assert repaired == clean
