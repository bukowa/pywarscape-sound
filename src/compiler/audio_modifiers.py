"""Generic composable audio modifier protocol and built-in modifiers.

Layer 1/2 boundary module: zero Qt (PySide6) imports.
Provides reusable audio processing building blocks used across replacement,
in-place adjustment, and export pipelines.

All processing operates on Python lists of float samples in [-1.0, 1.0] range.
No numpy dependency required — uses only stdlib math.
"""

from __future__ import annotations

import array
import io
import math
import struct
import sys
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


def _samples_to_floats(raw_pcm_bytes: bytes, sample_width: int = 2) -> list[float]:
    """Converts raw 16-bit signed PCM bytes to float samples in [-1.0, 1.0]."""
    if sample_width != 2:
        raise ValueError(f"Only 16-bit PCM (sample_width=2) is supported, got {sample_width}")
    count = len(raw_pcm_bytes) // 2
    samples = struct.unpack(f"<{count}h", raw_pcm_bytes[: count * 2])
    scale = 1.0 / 32768.0
    return [s * scale for s in samples]


def _floats_to_pcm_bytes(samples: Sequence[float], sample_width: int = 2) -> bytes:
    """Converts float samples in [-1.0, 1.0] to raw 16-bit signed PCM bytes."""
    if sample_width != 2:
        raise ValueError(f"Only 16-bit PCM (sample_width=2) is supported, got {sample_width}")
    clamped = [max(-1.0, min(1.0, s)) for s in samples]
    int_samples = [int(s * 32767) for s in clamped]
    return struct.pack(f"<{len(int_samples)}h", *int_samples)


def calculate_peak_db(samples: Sequence[float]) -> float:
    """Calculates absolute peak amplitude in dBFS from float samples."""
    if not samples:
        return -96.0
    max_val = max(abs(s) for s in samples)
    if max_val <= 1e-10:
        return -96.0
    return 20.0 * math.log10(max_val)


def calculate_rms_db(samples: Sequence[float]) -> float:
    """Calculates root-mean-square perceived energy in dBFS from float samples."""
    if not samples:
        return -96.0
    mean_sq = sum(s * s for s in samples) / len(samples)
    if mean_sq <= 1e-10:
        return -96.0
    return 20.0 * math.log10(math.sqrt(mean_sq))


@dataclass(frozen=True, slots=True)
class AudioAnalysisResult:
    """Loudness analysis result for a PCM audio buffer."""

    peak_db: float
    rms_db: float
    is_clipping: bool


def analyze_samples(samples: Sequence[float]) -> AudioAnalysisResult:
    """Analyzes float PCM samples and returns peak, RMS, and clipping status."""
    if not samples:
        return AudioAnalysisResult(peak_db=-96.0, rms_db=-96.0, is_clipping=False)
    peak = calculate_peak_db(samples)
    rms = calculate_rms_db(samples)
    is_clipping = any(abs(s) >= 1.0 for s in samples)
    return AudioAnalysisResult(peak_db=peak, rms_db=rms, is_clipping=is_clipping)


class AudioModifier(Protocol):
    """Generic interface for reusable sound modifiers."""

    def process(self, samples: list[float], sample_rate: int) -> list[float]:
        """Transforms float samples in [-1.0, 1.0] range and returns modified samples."""
        ...


@dataclass(frozen=True, slots=True)
class GainModifier:
    """Applies decibel gain trim (positive or negative)."""

    gain_db: float = 0.0

    def process(self, samples: list[float], sample_rate: int) -> list[float]:
        if self.gain_db == 0.0:
            return samples
        factor = 10.0 ** (self.gain_db / 20.0)
        return [max(-1.0, min(1.0, s * factor)) for s in samples]


@dataclass(frozen=True, slots=True)
class PeakNormalizeModifier:
    """Scales audio so loudest transient reaches target peak without clipping."""

    target_peak_db: float = -1.0

    def process(self, samples: list[float], sample_rate: int) -> list[float]:
        peak_db = calculate_peak_db(samples)
        if peak_db <= -90.0:
            return samples
        delta_db = self.target_peak_db - peak_db
        factor = 10.0 ** (delta_db / 20.0)
        return [max(-1.0, min(1.0, s * factor)) for s in samples]


@dataclass(frozen=True, slots=True)
class MatchReferenceLoudnessModifier:
    """
    Matches perceived RMS loudness to a reference target (e.g. the original vanilla sound).

    Calculates the gain delta between the current audio's RMS and the target_rms_db,
    applies it, and soft-limits peaks to prevent digital clipping.
    """

    target_rms_db: float
    max_boost_db: float = 12.0

    def process(self, samples: list[float], sample_rate: int) -> list[float]:
        current_rms = calculate_rms_db(samples)
        if current_rms <= -90.0:
            return samples

        delta_db = self.target_rms_db - current_rms
        clamped_delta = min(delta_db, self.max_boost_db)
        factor = 10.0 ** (clamped_delta / 20.0)
        scaled = [s * factor for s in samples]

        # Soft-knee limiter preventing digital overs
        peak = max(abs(s) for s in scaled) if scaled else 0.0
        if peak > 0.99:
            limit = 0.99 / peak
            scaled = [s * limit for s in scaled]
        return scaled


@dataclass(frozen=True, slots=True)
class AudioModifierChain:
    """Ordered pipeline of audio modifiers applied sequentially to a PCM buffer."""

    modifiers: tuple = ()

    def process(self, samples: list[float], sample_rate: int) -> list[float]:
        result = samples
        for mod in self.modifiers:
            result = mod.process(result, sample_rate)
        return result

    def is_empty(self) -> bool:
        return len(self.modifiers) == 0


def _build_gain_lut(factor: float) -> list[int]:
    """Pre-computes a 65,536-entry lookup table mapping signed 16-bit integers to scaled integers."""
    pos = [max(-32768, min(32767, int(round(i * factor)))) for i in range(32768)]
    neg = [max(-32768, min(32767, int(round(i * factor)))) for i in range(-32768, 0)]
    return pos + neg


def _apply_lut(arr: array.array, lut: list[int]) -> array.array:
    """Applies a 65,536-entry LUT to an array of 16-bit signed integers."""
    return array.array("h", [lut[s] for s in arr])


def apply_modifiers_to_wav_bytes(
    wav_bytes: bytes,
    modifier_chain: AudioModifierChain,
) -> bytes:
    """Applies an AudioModifierChain to standard 16-bit PCM WAV bytes and returns modified WAV bytes.

    Optimized for 16-bit signed PCM audio using array.array('h') and integer lookup tables (LUT)
    to avoid allocating millions of Python float objects on long audio tracks.
    """
    if modifier_chain.is_empty():
        return wav_bytes

    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        nchannels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())

    if sample_width != 2:
        raise ValueError(f"Only 16-bit PCM (sample_width=2) is supported, got {sample_width}")

    if not frames:
        return wav_bytes

    # Convert frames directly to 16-bit signed int array
    arr = array.array("h")
    arr.frombytes(frames)
    if sys.byteorder != "little":
        arr.byteswap()

    current = arr
    for mod in modifier_chain.modifiers:
        if isinstance(mod, GainModifier):
            if mod.gain_db == 0.0:
                continue
            factor = 10.0 ** (mod.gain_db / 20.0)
            lut = _build_gain_lut(factor)
            current = _apply_lut(current, lut)
        elif isinstance(mod, PeakNormalizeModifier):
            if not current:
                continue
            peak_int = max(abs(min(current)), abs(max(current)))
            if peak_int == 0:
                continue
            max_val = peak_int / 32768.0
            peak_db = 20.0 * math.log10(max_val) if max_val > 1e-10 else -96.0
            if peak_db <= -90.0:
                continue
            delta_db = mod.target_peak_db - peak_db
            factor = 10.0 ** (delta_db / 20.0)
            lut = _build_gain_lut(factor)
            current = _apply_lut(current, lut)
        elif isinstance(mod, MatchReferenceLoudnessModifier):
            if not current:
                continue
            mean_sq = sum(s * s for s in current) / (len(current) * 32768.0 * 32768.0)
            current_rms = 20.0 * math.log10(math.sqrt(mean_sq)) if mean_sq > 1e-10 else -96.0
            if current_rms <= -90.0:
                continue
            delta_db = mod.target_rms_db - current_rms
            clamped_delta = min(delta_db, mod.max_boost_db)
            factor = 10.0 ** (clamped_delta / 20.0)
            peak_int = max(abs(min(current)), abs(max(current)))
            scaled_peak = (peak_int / 32768.0) * factor
            limit = (0.99 / scaled_peak) if scaled_peak > 0.99 else 1.0
            final_factor = factor * limit
            lut = _build_gain_lut(final_factor)
            current = _apply_lut(current, lut)
        else:
            # Fall back to float processing for unknown custom modifier
            scale = 1.0 / 32768.0
            floats = [s * scale for s in current]
            modified_floats = mod.process(floats, sample_rate)
            clamped = [max(-1.0, min(1.0, s)) for s in modified_floats]
            current = array.array("h", [int(s * 32767) for s in clamped])

    if current is arr:
        # None of the modifiers changed the samples
        return wav_bytes

    if sys.byteorder != "little":
        current.byteswap()
    modified_frames = current.tobytes()

    out_io = io.BytesIO()
    with wave.open(out_io, "wb") as out_wf:
        out_wf.setnchannels(nchannels)
        out_wf.setsampwidth(sample_width)
        out_wf.setframerate(sample_rate)
        out_wf.writeframes(modified_frames)

    return out_io.getvalue()
