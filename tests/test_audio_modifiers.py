"""Tests for generic audio modifier protocol and built-in modifiers."""

import math

from src.compiler.audio_modifiers import (
    AudioModifierChain,
    GainModifier,
    MatchReferenceLoudnessModifier,
    PeakNormalizeModifier,
    _floats_to_pcm_bytes,
    _samples_to_floats,
    analyze_samples,
    apply_modifiers_to_wav_bytes,
    calculate_peak_db,
    calculate_rms_db,
)


def _sine_wave(
    freq: float = 440.0, duration: float = 0.1, sr: int = 32000, amplitude: float = 0.5
) -> list[float]:
    count = int(sr * duration)
    return [amplitude * math.sin(2 * math.pi * freq * i / sr) for i in range(count)]


class TestAnalysisFunctions:
    def test_calculate_peak_db_silence(self):
        silence = [0.0] * 1000
        assert calculate_peak_db(silence) <= -90.0

    def test_calculate_peak_db_full_scale(self):
        full = [1.0] * 100
        assert abs(calculate_peak_db(full) - 0.0) < 0.01

    def test_calculate_peak_db_half(self):
        half = [0.5] * 100
        assert abs(calculate_peak_db(half) - (-6.02)) < 0.1

    def test_calculate_rms_db_sine(self):
        sine = _sine_wave(amplitude=1.0)
        rms = calculate_rms_db(sine)
        # RMS of a sine at amplitude 1.0 is 1/sqrt(2) ≈ -3.01 dBFS
        assert abs(rms - (-3.01)) < 0.2

    def test_calculate_rms_db_silence(self):
        silence = [0.0] * 1000
        assert calculate_rms_db(silence) <= -90.0

    def test_analyze_samples_empty(self):
        result = analyze_samples([])
        assert result.peak_db <= -90.0
        assert result.rms_db <= -90.0
        assert result.is_clipping is False

    def test_analyze_samples_clipping(self):
        clipped = [1.0, -1.0, 0.5]
        result = analyze_samples(clipped)
        assert result.is_clipping is True

    def test_analyze_samples_no_clipping(self):
        clean = _sine_wave(amplitude=0.8)
        result = analyze_samples(clean)
        assert result.is_clipping is False
        assert result.peak_db < 0.0
        assert result.rms_db < result.peak_db


class TestPCMConversion:
    def test_roundtrip_16bit(self):
        original = _sine_wave(amplitude=0.5, duration=0.01)
        pcm = _floats_to_pcm_bytes(original)
        recovered = _samples_to_floats(pcm)
        assert len(recovered) == len(original)
        for a, b in zip(original, recovered):
            assert abs(a - b) < 0.001

    def test_clipping_protection(self):
        over = [1.5, -1.5, 0.0]
        pcm = _floats_to_pcm_bytes(over)
        recovered = _samples_to_floats(pcm)
        assert all(abs(s) <= 1.0 for s in recovered)


class TestGainModifier:
    def test_zero_gain_is_identity(self):
        samples = _sine_wave()
        mod = GainModifier(gain_db=0.0)
        result = mod.process(samples, 32000)
        assert result is samples

    def test_positive_gain_increases_amplitude(self):
        samples = _sine_wave(amplitude=0.1)
        mod = GainModifier(gain_db=6.0)
        result = mod.process(samples, 32000)
        assert calculate_peak_db(result) > calculate_peak_db(samples)

    def test_negative_gain_decreases_amplitude(self):
        samples = _sine_wave(amplitude=0.5)
        mod = GainModifier(gain_db=-6.0)
        result = mod.process(samples, 32000)
        assert calculate_peak_db(result) < calculate_peak_db(samples)

    def test_gain_clips_at_unity(self):
        samples = _sine_wave(amplitude=0.9)
        mod = GainModifier(gain_db=20.0)
        result = mod.process(samples, 32000)
        assert max(abs(s) for s in result) <= 1.0


class TestPeakNormalizeModifier:
    def test_normalizes_quiet_audio(self):
        quiet = _sine_wave(amplitude=0.1)
        mod = PeakNormalizeModifier(target_peak_db=-1.0)
        result = mod.process(quiet, 32000)
        result_peak = calculate_peak_db(result)
        assert abs(result_peak - (-1.0)) < 0.3

    def test_normalizes_loud_audio(self):
        loud = _sine_wave(amplitude=0.95)
        mod = PeakNormalizeModifier(target_peak_db=-6.0)
        result = mod.process(loud, 32000)
        result_peak = calculate_peak_db(result)
        assert abs(result_peak - (-6.0)) < 0.3

    def test_silence_unchanged(self):
        silence = [0.0] * 1000
        mod = PeakNormalizeModifier(target_peak_db=-1.0)
        result = mod.process(silence, 32000)
        assert all(s == 0.0 for s in result)


class TestMatchReferenceLoudnessModifier:
    def test_matches_reference_loudness(self):
        reference = _sine_wave(amplitude=0.3)
        ref_rms = calculate_rms_db(reference)

        quiet_replacement = _sine_wave(amplitude=0.05)
        quiet_rms = calculate_rms_db(quiet_replacement)
        assert quiet_rms < ref_rms - 5.0

        mod = MatchReferenceLoudnessModifier(target_rms_db=ref_rms)
        result = mod.process(quiet_replacement, 32000)
        result_rms = calculate_rms_db(result)
        # After loudness matching + soft limiter, result should be much closer to reference
        # than the original quiet replacement was (limiter may reduce slightly below target)
        assert abs(result_rms - ref_rms) < 4.0
        assert result_rms > quiet_rms + 5.0  # Must be significantly louder than original

    def test_does_not_clip_when_boosting(self):
        reference = _sine_wave(amplitude=0.8)
        ref_rms = calculate_rms_db(reference)

        quiet = _sine_wave(amplitude=0.05)
        mod = MatchReferenceLoudnessModifier(target_rms_db=ref_rms)
        result = mod.process(quiet, 32000)
        assert max(abs(s) for s in result) <= 1.0

    def test_respects_max_boost_limit(self):
        quiet = _sine_wave(amplitude=0.001)
        quiet_rms = calculate_rms_db(quiet)
        mod = MatchReferenceLoudnessModifier(target_rms_db=-5.0, max_boost_db=6.0)
        result = mod.process(quiet, 32000)
        result_rms = calculate_rms_db(result)
        assert result_rms < quiet_rms + 7.0

    def test_silence_unchanged(self):
        silence = [0.0] * 1000
        mod = MatchReferenceLoudnessModifier(target_rms_db=-14.0)
        result = mod.process(silence, 32000)
        assert all(s == 0.0 for s in result)


class TestAudioModifierChain:
    def test_empty_chain_is_identity(self):
        samples = _sine_wave()
        chain = AudioModifierChain()
        result = chain.process(samples, 32000)
        assert result is samples
        assert chain.is_empty()

    def test_single_modifier_chain(self):
        samples = _sine_wave(amplitude=0.1)
        chain = AudioModifierChain(modifiers=(GainModifier(gain_db=6.0),))
        result = chain.process(samples, 32000)
        assert calculate_peak_db(result) > calculate_peak_db(samples)
        assert not chain.is_empty()

    def test_chained_gain_then_normalize(self):
        samples = _sine_wave(amplitude=0.1)
        chain = AudioModifierChain(
            modifiers=(
                GainModifier(gain_db=3.0),
                PeakNormalizeModifier(target_peak_db=-1.0),
            )
        )
        result = chain.process(samples, 32000)
        assert abs(calculate_peak_db(result) - (-1.0)) < 0.3

    def test_match_loudness_then_peak_normalize(self):
        reference = _sine_wave(amplitude=0.4)
        ref_rms = calculate_rms_db(reference)

        quiet = _sine_wave(amplitude=0.05)
        chain = AudioModifierChain(
            modifiers=(
                MatchReferenceLoudnessModifier(target_rms_db=ref_rms),
                PeakNormalizeModifier(target_peak_db=-1.0),
            )
        )
        result = chain.process(quiet, 32000)
        assert abs(calculate_peak_db(result) - (-1.0)) < 0.3
        assert max(abs(s) for s in result) <= 1.0


class TestApplyModifiersToWavBytes:
    def test_empty_chain_returns_same_bytes(self):
        import io
        import wave

        samples = _sine_wave(amplitude=0.5)
        raw_pcm = _floats_to_pcm_bytes(samples)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(32000)
            wf.writeframes(raw_pcm)
        wav_bytes = buf.getvalue()

        result = apply_modifiers_to_wav_bytes(wav_bytes, AudioModifierChain())
        assert result == wav_bytes

    def test_gain_and_normalize_applied_to_wav(self):
        import io
        import wave

        samples = _sine_wave(amplitude=0.1)
        raw_pcm = _floats_to_pcm_bytes(samples)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(32000)
            wf.writeframes(raw_pcm)
        wav_bytes = buf.getvalue()

        chain = AudioModifierChain(
            modifiers=(
                GainModifier(gain_db=6.0),
                PeakNormalizeModifier(target_peak_db=-1.0),
            )
        )
        result_wav = apply_modifiers_to_wav_bytes(wav_bytes, chain)
        with wave.open(io.BytesIO(result_wav), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getframerate() == 32000
            res_frames = wf.readframes(wf.getnframes())
            res_floats = _samples_to_floats(res_frames)
            assert abs(calculate_peak_db(res_floats) - (-1.0)) < 0.3

    def test_match_loudness_applied_to_wav(self):
        import io
        import wave

        samples = _sine_wave(amplitude=0.05)
        raw_pcm = _floats_to_pcm_bytes(samples)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(32000)
            wf.writeframes(raw_pcm)
        wav_bytes = buf.getvalue()

        chain = AudioModifierChain(modifiers=(MatchReferenceLoudnessModifier(target_rms_db=-12.0),))
        result_wav = apply_modifiers_to_wav_bytes(wav_bytes, chain)
        with wave.open(io.BytesIO(result_wav), "rb") as wf:
            res_frames = wf.readframes(wf.getnframes())
            res_floats = _samples_to_floats(res_frames)
            assert calculate_rms_db(res_floats) > calculate_rms_db(samples) + 5.0

    def test_custom_modifier_fallback(self):
        import io
        import wave

        class CustomInvertModifier:
            def process(self, samples: list[float], sample_rate: int) -> list[float]:
                return [-s for s in samples]

        samples = [0.5, -0.5, 0.25]
        raw_pcm = _floats_to_pcm_bytes(samples)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(32000)
            wf.writeframes(raw_pcm)
        wav_bytes = buf.getvalue()

        chain = AudioModifierChain(modifiers=(CustomInvertModifier(),))
        result_wav = apply_modifiers_to_wav_bytes(wav_bytes, chain)
        with wave.open(io.BytesIO(result_wav), "rb") as wf:
            res_frames = wf.readframes(wf.getnframes())
            res_floats = _samples_to_floats(res_frames)
            assert res_floats[0] < 0.0
            assert res_floats[1] > 0.0

    def test_benchmark_3min_audio_gain_performance(self):
        import io
        import time
        import wave

        # 3 minutes of 32kHz stereo audio = 180s * 32000 * 2 = 11,520,000 samples
        sr = 32000
        n_samples = sr * 2 * 180
        raw = b"\x00\x08" * n_samples
        bio = io.BytesIO()
        with wave.open(bio, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(raw)
        wav_bytes = bio.getvalue()

        chain = AudioModifierChain(modifiers=(GainModifier(gain_db=3.0),))
        t0 = time.perf_counter()
        result_wav = apply_modifiers_to_wav_bytes(wav_bytes, chain)
        elapsed = time.perf_counter() - t0

        # Must execute in under 5.0s under parallel test load and coverage tracing instead of 7.5s-15s (unoptimized path)
        assert elapsed < 5.0, f"3-minute stereo audio took too long: {elapsed:.3f}s"
        assert len(result_wav) == len(wav_bytes)
