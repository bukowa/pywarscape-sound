import io
import math
import struct
import wave
from pathlib import Path

import av
import pytest

from src.bnk.wem import build_silent_pcm_wem_bytes, parse_wem_header, validate_wem_bytes
from src.compiler.converter import AudioConverter


def _make_test_wav_bytes(
    sample_rate: int = 44100, channels: int = 2, duration_s: float = 0.2
) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        frames = bytearray()
        for i in range(int(sample_rate * duration_s)):
            val = int(32767.0 * 0.5 * math.sin(2.0 * math.pi * 440.0 * i / sample_rate))
            frames.extend(struct.pack("<hh" if channels == 2 else "<h", *([val] * channels)))
        wf.writeframes(frames)
    return buf.getvalue()


def _make_test_flac_bytes(
    sample_rate: int = 44100, channels: int = 1, duration_s: float = 0.2
) -> bytes:
    buf = io.BytesIO()
    out = av.open(buf, mode="w", format="flac")
    layout = "mono" if channels == 1 else "stereo"
    stream = out.add_stream("flac", rate=sample_rate, layout=layout)
    total_samples = int(sample_rate * duration_s)
    frame = av.AudioFrame(format="s16", layout=layout, samples=total_samples)
    frame.rate = sample_rate
    raw = bytearray()
    for i in range(total_samples):
        val = int(32767.0 * 0.4 * math.sin(2.0 * math.pi * 880.0 * i / sample_rate))
        raw.extend(struct.pack("<hh" if channels == 2 else "<h", *([val] * channels)))
    frame.planes[0].update(raw)
    for p in stream.encode(frame):
        out.mux(p)
    for p in stream.encode(None):
        out.mux(p)
    out.close()
    return buf.getvalue()


def _make_test_mp3_bytes(sample_rate: int = 44100, duration_s: float = 0.2) -> bytes:
    buf = io.BytesIO()
    out = av.open(buf, mode="w", format="mp3")
    stream = out.add_stream("mp3", rate=sample_rate, layout="mono")
    # MP3 standard frames (1152 samples)
    frame_samples = 1152
    num_frames = max(1, int(sample_rate * duration_s / frame_samples))
    for f_idx in range(num_frames):
        frame = av.AudioFrame(format="s16p", layout="mono", samples=frame_samples)
        frame.rate = sample_rate
        raw = bytearray()
        for i in range(frame_samples):
            t = (f_idx * frame_samples + i) / sample_rate
            val = int(32767.0 * 0.3 * math.sin(2.0 * math.pi * 440.0 * t))
            raw.extend(struct.pack("<h", val))
        frame.planes[0].update(raw)
        for p in stream.encode(frame):
            out.mux(p)
    for p in stream.encode(None):
        out.mux(p)
    out.close()
    return buf.getvalue()


def _make_test_ogg_bytes(sample_rate: int = 48000, duration_s: float = 0.2) -> bytes:
    buf = io.BytesIO()
    out = av.open(buf, mode="w", format="ogg")
    stream = out.add_stream("opus", rate=sample_rate, layout="mono")
    total_samples = int(sample_rate * duration_s)
    # Opus frame size 960 (20ms at 48kHz)
    frame_size = 960
    num_frames = max(1, total_samples // frame_size)
    for _ in range(num_frames):
        frame = av.AudioFrame(format="s16", layout="mono", samples=frame_size)
        frame.rate = sample_rate
        raw = bytearray()
        for i in range(frame_size):
            val = int(32767.0 * 0.4 * math.sin(2.0 * math.pi * 440.0 * i / sample_rate))
            raw.extend(struct.pack("<h", val))
        frame.planes[0].update(raw)
        for p in stream.encode(frame):
            out.mux(p)
    for p in stream.encode(None):
        out.mux(p)
    out.close()
    return buf.getvalue()


def test_convert_wav_bytes_to_wem():
    wav_bytes = _make_test_wav_bytes(sample_rate=48000, channels=2, duration_s=0.25)
    wem_bytes, duration_ms = AudioConverter.convert_to_wem_bytes(wav_bytes)
    assert len(wem_bytes) > 0
    assert abs(duration_ms - 250.0) < 25.0
    valid, errors = validate_wem_bytes(wem_bytes)
    assert valid is True, f"Validation errors: {errors}"
    hdr = parse_wem_header(wem_bytes)
    assert hdr.sample_rate == 32000
    assert hdr.channels == 1
    assert hdr.format_tag == 0xFFFE


def test_convert_to_pcm_wav_bytes():
    wav_bytes = _make_test_wav_bytes(sample_rate=44100, channels=1, duration_s=0.1)
    pcm_wav, duration_ms = AudioConverter.convert_to_pcm_wav_bytes(
        wav_bytes, target_sample_rate=32000
    )
    assert len(pcm_wav) > 44
    assert pcm_wav.startswith(b"RIFF")
    assert abs(duration_ms - 100.0) < 15.0


def test_convert_from_file_path(tmp_path: Path):
    wav_path = tmp_path / "sample.wav"
    wav_bytes = _make_test_wav_bytes(sample_rate=44100, channels=1, duration_s=0.15)
    wav_path.write_bytes(wav_bytes)

    # Test with Path
    pcm_wav, duration_ms = AudioConverter.convert_to_pcm_wav_bytes(
        wav_path, target_sample_rate=32000
    )
    assert pcm_wav.startswith(b"RIFF")
    assert abs(duration_ms - 150.0) < 20.0

    # Test with str
    wem_bytes, duration_ms_wem = AudioConverter.convert_to_wem_bytes(str(wav_path))
    assert len(wem_bytes) > 0
    assert abs(duration_ms_wem - 150.0) < 20.0
    valid, errors = validate_wem_bytes(wem_bytes)
    assert valid is True, f"Validation errors: {errors}"


def test_convert_flac_input():
    flac_bytes = _make_test_flac_bytes(sample_rate=44100, channels=1, duration_s=0.2)
    wem_bytes, duration_ms = AudioConverter.convert_to_wem_bytes(flac_bytes)
    assert len(wem_bytes) > 0
    assert abs(duration_ms - 200.0) < 25.0
    valid, errors = validate_wem_bytes(wem_bytes)
    assert valid is True, f"Validation errors: {errors}"
    hdr = parse_wem_header(wem_bytes)
    assert hdr.sample_rate == 32000
    assert hdr.channels == 1


def test_convert_mp3_input():
    mp3_bytes = _make_test_mp3_bytes(sample_rate=44100, duration_s=0.2)
    pcm_wav, duration_ms = AudioConverter.convert_to_pcm_wav_bytes(
        mp3_bytes, target_sample_rate=32000
    )
    assert len(pcm_wav) > 44
    assert pcm_wav.startswith(b"RIFF")
    assert duration_ms > 100.0


def test_convert_stereo_target():
    wav_bytes = _make_test_wav_bytes(sample_rate=44100, channels=1, duration_s=0.1)
    pcm_wav, duration_ms = AudioConverter.convert_to_pcm_wav_bytes(
        wav_bytes, target_sample_rate=32000, target_channels=2
    )
    with wave.open(io.BytesIO(pcm_wav), "rb") as wf:
        assert wf.getnchannels() == 2
        assert wf.getframerate() == 32000
        assert wf.getsampwidth() == 2


def test_convert_existing_wem_passthrough(tmp_path: Path):
    silent_wem = build_silent_pcm_wem_bytes(duration_ms=100, sample_rate=32000)
    wem_path = tmp_path / "sound.wem"
    wem_path.write_bytes(silent_wem)

    result_bytes, duration_ms = AudioConverter.convert_to_wem_bytes(wem_path)
    assert result_bytes == silent_wem
    assert abs(duration_ms - 100.0) < 10.0


def test_invalid_input_handling(tmp_path: Path):
    with pytest.raises(ValueError):
        AudioConverter.convert_to_pcm_wav_bytes(b"")

    with pytest.raises(FileNotFoundError):
        AudioConverter.convert_to_pcm_wav_bytes(tmp_path / "nonexistent.wav")

    with pytest.raises(TypeError):
        AudioConverter.convert_to_pcm_wav_bytes(12345)  # type: ignore


def test_convert_ogg_bytes_to_wem():
    ogg_bytes = _make_test_ogg_bytes(sample_rate=48000, duration_s=0.2)
    wem_bytes, duration_ms = AudioConverter.convert_to_wem_bytes(ogg_bytes)
    assert len(wem_bytes) > 0
    assert duration_ms > 100.0
    valid, errors = validate_wem_bytes(wem_bytes)
    assert valid is True, f"Validation errors: {errors}"
    hdr = parse_wem_header(wem_bytes)
    assert hdr.sample_rate == 32000
    assert hdr.channels == 1
    assert hdr.format_tag == 0xFFFE


def test_convert_pcm_wem_byte_buffer_passthrough():
    silent_wem = build_silent_pcm_wem_bytes(duration_ms=150, sample_rate=32000)
    result_bytes, duration_ms = AudioConverter.convert_to_wem_bytes(silent_wem)
    assert result_bytes == silent_wem
    assert abs(duration_ms - 150.0) < 10.0
