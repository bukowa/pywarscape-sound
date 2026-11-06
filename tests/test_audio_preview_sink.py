"""
Unit and integration tests for AudioPreviewSink and SmartAudioReplacerDialog audio isolation.
"""

from __future__ import annotations

import ast
import struct
from pathlib import Path

import pytest

from src.deps.player import AudioPreviewSink
from src.ui.features.audio_sources.store import AudioSourcesStore
from src.ui.features.audio_sources.view import AudioSourcesView


def _build_minimal_pcm_wav() -> bytes:
    """Builds a minimal valid 44-byte standard RIFF PCM mono WAV file with 0 audio samples."""
    num_channels = 1
    sample_rate = 44100
    bits_per_sample = 16
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    data_size = 0
    riff_chunk_size = 36 + data_size
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        riff_chunk_size,
        b"WAVE",
        b"fmt ",
        16,
        1,  # PCM
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_size,
    )


def test_audio_preview_sink_initial_state_and_stop():
    sink = AudioPreviewSink()
    assert sink._active_channel is None
    assert sink._active_sound is None

    # Idempotent stop when idle
    sink.stop()
    assert sink._active_channel is None
    assert sink._active_sound is None


def test_audio_preview_sink_empty_inputs():
    sink = AudioPreviewSink()
    assert sink.play_wav_bytes(b"") is False
    assert sink.play_wem_bytes(b"") is False


def test_audio_preview_sink_invalid_payloads_do_not_raise():
    sink = AudioPreviewSink()
    # Random corrupted bytes should return False without unhandled exceptions
    corrupt = b"NOT_A_VALID_AUDIO_FILE_DATA_CORRUPT"
    assert sink.play_wav_bytes(corrupt) is False
    assert sink.play_wem_bytes(corrupt) is False


def test_audio_preview_sink_valid_wav_roundtrip():
    sink = AudioPreviewSink()
    wav_bytes = _build_minimal_pcm_wav()
    # play_wav_bytes may return True or False depending on audio hardware availability in headless CI,
    # but it must never crash or raise unhandled exceptions.
    result = sink.play_wav_bytes(wav_bytes)
    assert isinstance(result, bool)

    sink.stop()
    assert sink._active_channel is None
    assert sink._active_sound is None


def test_audio_sources_view_has_no_pygame(qapp):
    store = AudioSourcesStore()
    view = AudioSourcesView(store)
    assert not hasattr(view, "_active_channel") or view._active_channel is None
    assert not hasattr(view, "_active_sound") or view._active_sound is None
    view.close()


def test_audio_sources_ast_has_zero_pygame_imports():
    view_path = Path(__file__).parents[1] / "src" / "ui" / "features" / "audio_sources" / "view.py"
    tree = ast.parse(view_path.read_text(encoding="utf-8"), filename=str(view_path))
    pygame_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "pygame" in alias.name:
                    pygame_imports.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module and "pygame" in node.module:
                pygame_imports.append((node.lineno, node.module))

    assert not pygame_imports, f"Found pygame imports in audio_sources/view.py: {pygame_imports}"
