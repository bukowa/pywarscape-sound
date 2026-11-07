"""
In-memory Audio Converter and Resampler.
Provides high-fidelity headless audio format conversion and resampling to
Audiokinetic Wwise compliant 0xFFFE PCM .wem containers and standard 16-bit PCM WAV assets
using PyAV (libavcodec / libswresample).
"""

from __future__ import annotations

import io
import struct
from pathlib import Path
from typing import Any

import av

from src.bnk.wem import (
    WemFormatTag,
    parse_wem_header,
    validate_wem_bytes,
)

_SENTINEL: Any = object()


def _build_pcm_wem_container(pcm_data: bytes, sample_rate: int, channels: int) -> bytes:
    """Wraps raw 16-bit PCM bytes into an Audiokinetic Wwise compliant 0xFFFE container."""
    block_align = channels * 2
    avg_bytes_per_sec = sample_rate * block_align
    channel_mask = 4 if channels == 1 else 3
    subformat_pcm = b"\x01\x00\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
    fmt_payload = (
        struct.pack(
            "<HHIIHHHHI",
            WemFormatTag.EXTENSIBLE,
            channels,
            sample_rate,
            avg_bytes_per_sec,
            block_align,
            16,  # wBitsPerSample
            22,  # cbSize
            16,  # wValidBitsPerSample
            channel_mask,
        )
        + subformat_pcm
    )
    fmt_chunk = b"fmt " + struct.pack("<I", len(fmt_payload)) + fmt_payload
    data_pad = len(pcm_data) & 1
    data_chunk = (
        b"data" + struct.pack("<I", len(pcm_data)) + pcm_data + (b"\x00" if data_pad else b"")
    )
    riff_len = 4 + len(fmt_chunk) + len(data_chunk)
    return b"RIFF" + struct.pack("<I", riff_len) + b"WAVE" + fmt_chunk + data_chunk


class AudioConverter:
    """
    In-memory audio decoder, resampler, and container builder.
    Utilizes PyAV for high-performance zero-subprocess audio decoding and resampling.
    """

    @classmethod
    def convert_to_pcm_wav_bytes(
        cls,
        input_source: str | Path | bytes,
        sample_rate: int | None = _SENTINEL,
        channels: int | None = _SENTINEL,
        *,
        target_sample_rate: int | None = None,
        target_channels: int | None = None,
    ) -> tuple[bytes, float]:
        """
        Decodes any supported audio format (WAV, MP3, OGG, FLAC, AAC, etc.)
        and resamples into standard 16-bit PCM WAV bytes at the requested sample rate and channel layout.

        Args:
            input_source: File path (str or Path) or raw audio bytes buffer.
            sample_rate: Target sample rate in Hz (None preserves input clamped to [8000, 48000]).
            channels: Number of audio channels, 1 for mono or 2 for stereo (None preserves input clamped to 1 or 2).
            target_sample_rate: Keyword alias for sample_rate.
            target_channels: Keyword alias for channels.

        Returns:
            Tuple of (pcm_wav_bytes, duration_ms).

        Raises:
            TypeError: If input_source is not str, Path, or bytes.
            FileNotFoundError: If input file path does not exist on disk.
            ValueError: If input source is empty, contains no audio streams, or contains no samples.
        """
        if not isinstance(input_source, (str, Path, bytes)):
            raise TypeError(
                f"Expected input_source to be str, Path, or bytes, got {type(input_source).__name__}"
            )

        if target_sample_rate is not None:
            sample_rate = target_sample_rate
        if target_channels is not None:
            channels = target_channels
        if sample_rate is _SENTINEL:
            sample_rate = 32000
        if channels is _SENTINEL:
            channels = 1

        # Resolve container source
        source_target: str | io.BytesIO
        if isinstance(input_source, bytes):
            if not input_source:
                raise ValueError("Input audio byte buffer is empty.")
            source_target = io.BytesIO(input_source)
        else:
            file_path = Path(input_source)
            if not file_path.is_file():
                raise FileNotFoundError(f"Source audio file not found: {input_source}")
            source_target = str(file_path.resolve())

        in_container = av.open(source_target)
        assert isinstance(in_container, av.container.InputContainer)
        out_container: av.container.OutputContainer | None = None

        try:
            if not in_container.streams.audio:
                raise ValueError(f"No audio streams found in source: {input_source}")

            in_stream = in_container.streams.audio[0]

            # Determine effective sample rate (None preserves input clamped to [8000, 48000])
            if sample_rate is None:
                raw_rate = getattr(in_stream, "rate", None) or 32000
                eff_sample_rate = max(8000, min(48000, int(raw_rate)))
            else:
                eff_sample_rate = int(sample_rate)
                if eff_sample_rate <= 0:
                    raise ValueError(f"Invalid sample_rate: {eff_sample_rate}")

            # Determine effective channels (None preserves input clamped to 1 or 2)
            if channels is None:
                raw_ch = getattr(in_stream, "channels", None) or 1
                eff_channels = 2 if int(raw_ch) >= 2 else 1
            else:
                eff_channels = int(channels)
                if eff_channels not in (1, 2):
                    raise ValueError(
                        f"Unsupported target_channels: {eff_channels}. Only mono (1) and stereo (2) are supported."
                    )

            layout_str = "mono" if eff_channels == 1 else "stereo"

            resampler = av.AudioResampler(
                format="s16",
                layout=layout_str,
                rate=eff_sample_rate,
            )

            out_io = io.BytesIO()
            out_container = av.open(out_io, mode="w", format="wav")
            out_stream = out_container.add_stream(
                "pcm_s16le",
                rate=eff_sample_rate,
                layout=layout_str,
            )

            total_samples = 0

            # Decode and resample all audio frames
            for frame in in_container.decode(in_stream):
                resampled_frames = resampler.resample(frame)
                if resampled_frames:
                    for rf in resampled_frames:
                        total_samples += rf.samples
                        for packet in out_stream.encode(rf):
                            out_container.mux(packet)

            # Flush resampler filter graph
            flushed_frames = resampler.resample(None)
            if flushed_frames:
                for rf in flushed_frames:
                    total_samples += rf.samples
                    for packet in out_stream.encode(rf):
                        out_container.mux(packet)

            # Flush encoder buffer
            for packet in out_stream.encode(None):
                out_container.mux(packet)

            out_container.close()
            out_container = None

            if total_samples == 0:
                raise ValueError("Audio source contains no valid audio frames or samples.")

            duration_ms = (total_samples / eff_sample_rate) * 1000.0
            wav_bytes = out_io.getvalue()
            return wav_bytes, duration_ms

        finally:
            if out_container is not None:
                try:
                    out_container.close()
                except (av.FFmpegError, OSError, RuntimeError):
                    pass
            in_container.close()

    @classmethod
    def convert_to_wem_bytes(
        cls,
        input_source: str | Path | bytes,
        sample_rate: int | None = _SENTINEL,
        channels: int | None = _SENTINEL,
        *,
        target_sample_rate: int | None = None,
        target_channels: int | None = None,
    ) -> tuple[bytes, float]:
        """
        Converts any audio file or byte buffer into an Audiokinetic Wwise compliant
        0xFFFE PCM .wem container. Supports pass-through for existing valid .wem assets.

        Args:
            input_source: File path (str or Path) or raw audio bytes buffer.
            sample_rate: Target sample rate in Hz (None preserves input clamped to [8000, 48000]).
            channels: Target channels, 1 for mono or 2 for stereo (None preserves input clamped to 1 or 2).
            target_sample_rate: Keyword alias for sample_rate.
            target_channels: Keyword alias for channels.

        Returns:
            Tuple of (wem_bytes, duration_ms).
        """
        if target_sample_rate is not None:
            sample_rate = target_sample_rate
        if target_channels is not None:
            channels = target_channels
        if sample_rate is _SENTINEL:
            sample_rate = 32000
        if channels is _SENTINEL:
            channels = 1

        # Pass-through fast path for existing .wem files
        if isinstance(input_source, (str, Path)):
            p = Path(input_source)
            if p.suffix.lower() == ".wem":
                if not p.is_file():
                    raise FileNotFoundError(f"Source audio file not found: {input_source}")
                data = p.read_bytes()
                valid, errors = validate_wem_bytes(data)
                if not valid:
                    raise ValueError(
                        f"File {p.name} is not a valid Wwise WEM container: {', '.join(errors)}"
                    )
                hdr = parse_wem_header(data)
                is_vorbis = hdr.format_tag == WemFormatTag.VORBIS
                is_conforming_pcm = (
                    hdr.format_tag in (WemFormatTag.EXTENSIBLE, WemFormatTag.PCM, 0xFFFE, 0x0001)
                    and (sample_rate is None or hdr.sample_rate == sample_rate)
                    and (channels is None or hdr.channels == channels)
                )
                if (
                    is_vorbis
                    and (sample_rate is None or hdr.sample_rate == sample_rate)
                    and (channels is None or hdr.channels == channels)
                ) or is_conforming_pcm:
                    duration_ms = (
                        float(hdr.duration_ms)
                        if hdr.duration_ms > 0
                        else (
                            (hdr.data_size / hdr.avg_bytes_per_sec * 1000.0)
                            if hdr.avg_bytes_per_sec > 0
                            else 0.0
                        )
                    )
                    return data, duration_ms

        # Pass-through fast path for pre-compiled WEM byte buffers:
        if (
            isinstance(input_source, bytes)
            and len(input_source) >= 12
            and input_source.startswith(b"RIFF")
        ):
            try:
                valid, errors = validate_wem_bytes(input_source)
                if valid:
                    hdr = parse_wem_header(input_source)
                    is_vorbis = hdr.format_tag == WemFormatTag.VORBIS
                    is_conforming_pcm = (
                        hdr.format_tag
                        in (WemFormatTag.EXTENSIBLE, WemFormatTag.PCM, 0xFFFE, 0x0001)
                        and (sample_rate is None or hdr.sample_rate == sample_rate)
                        and (channels is None or hdr.channels == channels)
                    )
                    if (
                        is_vorbis
                        and (sample_rate is None or hdr.sample_rate == sample_rate)
                        and (channels is None or hdr.channels == channels)
                    ) or is_conforming_pcm:
                        duration_ms = (
                            float(hdr.duration_ms)
                            if hdr.duration_ms > 0
                            else (
                                (hdr.data_size / hdr.avg_bytes_per_sec * 1000.0)
                                if hdr.avg_bytes_per_sec > 0
                                else 0.0
                            )
                        )
                        return input_source, duration_ms
            except (ValueError, IndexError, struct.error, OSError):
                pass

        # Resample input source to PCM WAV in memory
        wav_bytes, duration_ms = cls.convert_to_pcm_wav_bytes(
            input_source,
            sample_rate=sample_rate,
            channels=channels,
        )

        # Extract PCM data, actual sample rate, and channels from the decoded WAV
        pcm_data = b""
        actual_sr = 32000
        actual_ch = 1
        offset = 12
        while offset + 8 <= len(wav_bytes):
            cid = wav_bytes[offset : offset + 4]
            csz = struct.unpack_from("<I", wav_bytes, offset + 4)[0]
            pay_start = offset + 8
            pay_end = pay_start + csz
            if cid == b"fmt " and csz >= 16:
                _, actual_ch = struct.unpack_from("<HH", wav_bytes, pay_start)
                actual_sr, _ = struct.unpack_from("<II", wav_bytes, pay_start + 4)
            elif cid == b"data":
                pcm_data = wav_bytes[pay_start:pay_end]
            offset = pay_end + (csz & 1)

        # Wrap into Wwise compliant 0xFFFE PCM container
        wem_bytes = _build_pcm_wem_container(
            pcm_data,
            sample_rate=actual_sr,
            channels=actual_ch,
        )

        valid, errors = validate_wem_bytes(wem_bytes)
        if not valid:
            raise ValueError(f"Failed to generate valid WEM container: {', '.join(errors)}")

        return wem_bytes, duration_ms

    @classmethod
    def convert_to_wem_file(
        cls,
        input_source: str | Path | bytes,
        output_path: str | Path,
        sample_rate: int | None = None,
        channels: int | None = None,
        *,
        target_sample_rate: int | None = None,
        target_channels: int | None = None,
    ) -> tuple[Path, float]:
        """
        Converts any audio input and writes Audiokinetic Wwise compliant .wem file to disk.

        Args:
            input_source: File path (str or Path) or raw audio bytes buffer.
            output_path: Destination .wem file path.
            sample_rate: Target sample rate in Hz (None preserves input clamped to [8000, 48000]).
            channels: Target channels, 1 for mono or 2 for stereo (None preserves input clamped to 1 or 2).
            target_sample_rate: Keyword alias for sample_rate.
            target_channels: Keyword alias for channels.

        Returns:
            Tuple of (output_file_path, duration_ms).
        """
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        wem_bytes, duration_ms = cls.convert_to_wem_bytes(
            input_source=input_source,
            sample_rate=sample_rate,
            channels=channels,
            target_sample_rate=target_sample_rate,
            target_channels=target_channels,
        )
        out_p.write_bytes(wem_bytes)
        return out_p, duration_ms
