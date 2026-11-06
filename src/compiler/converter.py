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

import av

from src.bnk.wem import (
    WemFormatTag,
    build_pcm_wem_from_wav_bytes,
    parse_wem_header,
    validate_wem_bytes,
)


class AudioConverter:
    """
    In-memory audio decoder, resampler, and container builder.
    Utilizes PyAV for high-performance zero-subprocess audio decoding and resampling.
    """

    @classmethod
    def convert_to_pcm_wav_bytes(
        cls,
        input_source: str | Path | bytes,
        target_sample_rate: int = 32000,
        target_channels: int = 1,
    ) -> tuple[bytes, float]:
        """
        Decodes any supported audio format (WAV, MP3, OGG, FLAC, AAC, etc.)
        and resamples into standard 16-bit PCM WAV bytes at the requested sample rate and channel layout.

        Args:
            input_source: File path (str or Path) or raw audio bytes buffer.
            target_sample_rate: Target sample rate in Hz (default: 32,000 Hz).
            target_channels: Number of audio channels, 1 for mono or 2 for stereo (default: 1).

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

        if target_channels not in (1, 2):
            raise ValueError(
                f"Unsupported target_channels: {target_channels}. Only mono (1) and stereo (2) are supported."
            )

        layout_str = "mono" if target_channels == 1 else "stereo"

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

            resampler = av.AudioResampler(
                format="s16",
                layout=layout_str,
                rate=target_sample_rate,
            )

            out_io = io.BytesIO()
            out_container = av.open(out_io, mode="w", format="wav")
            out_stream = out_container.add_stream(
                "pcm_s16le",
                rate=target_sample_rate,
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

            duration_ms = (total_samples / target_sample_rate) * 1000.0
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
        target_sample_rate: int = 32000,
        target_channels: int = 1,
    ) -> tuple[bytes, float]:
        """
        Converts any audio file or byte buffer into an Audiokinetic Wwise compliant
        0xFFFE PCM .wem container. Supports pass-through for existing valid .wem assets.

        Args:
            input_source: File path (str or Path) or raw audio bytes buffer.
            target_sample_rate: Target sample rate in Hz (default: 32,000 Hz).
            target_channels: Target channels (default: 1 for mono).

        Returns:
            Tuple of (wem_bytes, duration_ms).
        """
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
        # - Native Wwise Vorbis (0xFFFF)
        # - Conforming PCM (0xFFFE / 0x0001) matching target sample rate and channels
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
                        and hdr.sample_rate == target_sample_rate
                        and hdr.channels == target_channels
                    )
                    if is_vorbis or is_conforming_pcm:
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
            target_sample_rate=target_sample_rate,
            target_channels=target_channels,
        )

        # Wrap into Wwise compliant 0xFFFE PCM container
        wem_bytes = build_pcm_wem_from_wav_bytes(
            wav_bytes,
            target_sample_rate=target_sample_rate,
            target_channels=target_channels,
        )

        valid, errors = validate_wem_bytes(wem_bytes)
        if not valid:
            raise ValueError(f"Failed to generate valid WEM container: {', '.join(errors)}")

        return wem_bytes, duration_ms
