"""
Audiokinetic Wwise .wem Audio Container Parser and Generator.
Provides pure binary inspection and validation of RIFF/WAVE, Wwise Vorbis, and PCM headers,
plus conversion of WAV / raw PCM into compliant 0xFFFE PCM .wem containers.
"""

from __future__ import annotations

import array
import struct
import sys
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from src.bnk.stream import ByteReader


class WemFormatTag(IntEnum):
    """Supported Wwise audio format tags in RIFF WAVE headers."""

    PCM = 0x0001
    ADPCM = 0x0002
    EXTENSIBLE = 0xFFFE
    VORBIS = 0xFFFF


@dataclass(slots=True)
class WemVorbisInfo:
    """
    Audiokinetic Wwise Vorbis header extension (42 bytes at fmt+0x18).
    Total fmt chunk payload is 66 bytes when wFormatTag == 0xFFFF.
    """

    total_pcm_frames: int = 0
    loop_start_packet_offset: int = 0
    loop_end_packet_offset: int = 0
    loop_begin_extra: int = 0
    loop_end_extra: int = 0
    seek_table_size: int = 0
    vorbis_data_offset: int = 0
    max_packet_size: int = 0
    last_granule_extra: int = 0
    decode_alloc_size: int = 0
    decode_x64_alloc_size: int = 0
    hash_codebook: int = 0
    block_size_0_exp: int = 0
    block_size_1_exp: int = 0

    @classmethod
    def from_fmt_payload(cls, data: bytes) -> WemVorbisInfo:
        """Parses the 42-byte Wwise Vorbis extension starting at offset 0x18 of fmt payload."""
        if len(data) < 66:
            raise ValueError(f"Wwise Vorbis fmt chunk must be at least 66 bytes, got {len(data)}")

        reader = ByteReader(data[0x18:0x42])
        total_pcm_frames, loop_start_packet_offset, loop_end_packet_offset = reader.read_struct(
            "<III"
        )
        loop_begin_extra, loop_end_extra = reader.read_struct("<HH")
        seek_table_size, vorbis_data_offset = reader.read_struct("<II")
        max_packet_size, last_granule_extra = reader.read_struct("<HH")
        decode_alloc_size, decode_x64_alloc_size, hash_codebook = reader.read_struct("<III")
        block_size_0_exp, block_size_1_exp = reader.read_struct("<BB")

        return cls(
            total_pcm_frames=total_pcm_frames,
            loop_start_packet_offset=loop_start_packet_offset,
            loop_end_packet_offset=loop_end_packet_offset,
            loop_begin_extra=loop_begin_extra,
            loop_end_extra=loop_end_extra,
            seek_table_size=seek_table_size,
            vorbis_data_offset=vorbis_data_offset,
            max_packet_size=max_packet_size,
            last_granule_extra=last_granule_extra,
            decode_alloc_size=decode_alloc_size,
            decode_x64_alloc_size=decode_x64_alloc_size,
            hash_codebook=hash_codebook,
            block_size_0_exp=block_size_0_exp,
            block_size_1_exp=block_size_1_exp,
        )


@dataclass(slots=True)
class WemHeader:
    """Represents decoded header metadata for a Wwise .wem audio stream."""

    riff_size: int = 0
    form_type: str = "WAVE"
    format_tag: int = WemFormatTag.VORBIS
    channels: int = 1
    sample_rate: int = 32000
    avg_bytes_per_sec: int = 0
    block_align: int = 0
    bits_per_sample: int = 0
    extra_fmt_size: int = 0
    samples_per_block: int = 0
    channel_mask: int = 0
    data_offset: int = 0
    data_size: int = 0
    vorbis_info: WemVorbisInfo | None = None
    loop_start: int = 0
    loop_end: int = 0
    has_cue: bool = False
    has_smpl: bool = False
    has_seek: bool = False
    chunks: list[tuple[str, int, int]] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        """Calculates audio duration in milliseconds."""
        if self.vorbis_info and self.sample_rate > 0:
            return (self.vorbis_info.total_pcm_frames / self.sample_rate) * 1000.0
        elif self.avg_bytes_per_sec > 0:
            return (self.data_size / self.avg_bytes_per_sec) * 1000.0
        return 0.0


def repair_extracted_wem_bytes(data: bytes) -> bytes:
    """Repairs WEM audio container binary payloads that contain legacy archive encryption artifacts."""
    if len(data) < 16 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return data

    raw_riff_len = struct.unpack_from("<I", data, 4)[0]
    expected_len = len(data) - 8
    if (raw_riff_len ^ 0xC0AFB23E) == expected_len:
        orig_len = len(data)
        pad = (8 - (orig_len % 8)) % 8
        buf = bytearray(data) + bytearray(pad)
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
        return bytes(buf[:orig_len])

    return data


def parse_wem_header(data: bytes) -> WemHeader:
    """
    Parses a Wwise .wem file binary header, validating RIFF/WAVE chunks.
    Raises ValueError or EOFError if data is corrupt or non-compliant.
    """
    data = repair_extracted_wem_bytes(data)

    if len(data) < 12:
        raise ValueError(f"Data too short for RIFF header ({len(data)} bytes, minimum 12)")

    if data[:4] != b"RIFF":
        raise ValueError(f"Invalid container signature: {data[:4]!r}, expected b'RIFF'")

    reader = ByteReader(data)
    reader.skip(4)  # Skip RIFF
    riff_size = reader.read_u32()
    form_type = reader.read_bytes(4).decode("latin1", errors="replace")
    if form_type not in ("WAVE", "XWMA"):
        raise ValueError(f"Unsupported form type '{form_type}', expected 'WAVE' or 'XWMA'")

    offset = 12
    fmt_seen = False
    data_seen = False

    format_tag = 0
    channels = 0
    sample_rate = 0
    avg_bytes_per_sec = 0
    block_align = 0
    bits_per_sample = 0
    extra_fmt_size = 0
    samples_per_block = 0
    channel_mask = 0

    data_offset = 0
    data_size = 0
    vorbis_info: WemVorbisInfo | None = None
    loop_start = 0
    loop_end = 0
    has_cue = False
    has_smpl = False
    has_seek = False
    chunks: list[tuple[str, int, int]] = []

    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4].decode("latin1", errors="replace")
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
        payload_offset = offset + 8
        payload_end = payload_offset + chunk_size

        if payload_end > len(data):
            if chunk_id == "data" and fmt_seen:
                chunks.append((chunk_id, offset, len(data) - payload_offset))
                data_seen = True
                data_offset = payload_offset
                data_size = chunk_size
                break
            raise EOFError(
                f"Chunk '{chunk_id}' extends beyond file bounds (payload size {chunk_size}, available {len(data) - payload_offset})"
            )

        chunks.append((chunk_id, offset, chunk_size))
        chunk_data = data[payload_offset:payload_end]

        if chunk_id == "fmt ":
            fmt_seen = True
            if len(chunk_data) < 16:
                raise ValueError(f"Invalid 'fmt ' chunk size: {len(chunk_data)} bytes (minimum 16)")

            fmt_reader = ByteReader(chunk_data)
            format_tag, channels = fmt_reader.read_struct("<HH")
            sample_rate, avg_bytes_per_sec = fmt_reader.read_struct("<II")
            block_align, bits_per_sample = fmt_reader.read_struct("<HH")

            if len(chunk_data) >= 18:
                extra_fmt_size = fmt_reader.read_u16()

            if len(chunk_data) >= 24:
                samples_per_block = fmt_reader.read_u16()
                channel_mask = fmt_reader.read_u32()

            if format_tag == WemFormatTag.VORBIS and len(chunk_data) >= 66:
                try:
                    vorbis_info = WemVorbisInfo.from_fmt_payload(chunk_data)
                except (ValueError, IndexError):
                    pass

        elif chunk_id == "data":
            data_seen = True
            data_offset = payload_offset
            data_size = chunk_size

        elif chunk_id == "smpl":
            has_smpl = True
            if len(chunk_data) >= 52:
                smpl_reader = ByteReader(chunk_data)
                smpl_reader.skip(28)  # skip to num_sample_loops
                num_loops = smpl_reader.read_u32()
                if num_loops > 0 and len(chunk_data) >= 52:
                    smpl_reader.skip(4)  # skip sampler_data
                    smpl_reader.skip(8)  # skip cue_point_id, type
                    loop_start = smpl_reader.read_u32()
                    loop_end = smpl_reader.read_u32()

        elif chunk_id == "cue ":
            has_cue = True
        elif chunk_id == "seek":
            has_seek = True

        offset = payload_end
        if chunk_size & 1:
            offset += 1

    if not fmt_seen:
        raise ValueError("Missing 'fmt ' chunk in WAVE container")
    if not data_seen:
        raise ValueError("Missing 'data' chunk in WAVE container")

    return WemHeader(
        riff_size=riff_size,
        form_type=form_type,
        format_tag=format_tag,
        channels=channels,
        sample_rate=sample_rate,
        avg_bytes_per_sec=avg_bytes_per_sec,
        block_align=block_align,
        bits_per_sample=bits_per_sample,
        extra_fmt_size=extra_fmt_size,
        samples_per_block=samples_per_block,
        channel_mask=channel_mask,
        data_offset=data_offset,
        data_size=data_size,
        vorbis_info=vorbis_info,
        loop_start=loop_start,
        loop_end=loop_end,
        has_cue=has_cue,
        has_smpl=has_smpl,
        has_seek=has_seek,
        chunks=chunks,
    )


def parse_wem_file(file_path: Path | str) -> WemHeader:
    """Parses a Wwise .wem file from disk."""
    p = Path(file_path)
    return parse_wem_header(p.read_bytes())


def validate_wem_bytes(
    data: bytes,
    require_vorbis: bool = False,
    expected_sample_rate: int | None = None,
    expected_channels: int | None = None,
) -> tuple[bool, list[str]]:
    """
    Validates binary Wwise .wem file contents against engine sound pipeline specifications.
    Returns (is_valid, error_list).
    """
    data = repair_extracted_wem_bytes(data)
    errors: list[str] = []

    if len(data) < 12:
        errors.append(f"File too short ({len(data)} bytes, minimum 12 bytes required)")
        return False, errors

    if data[:4] != b"RIFF":
        errors.append(f"Invalid signature: {data[:4]!r}, must be b'RIFF'")

    form_type = data[8:12].decode("latin1", errors="replace")
    if form_type not in ("WAVE", "XWMA"):
        errors.append(f"Unsupported form type '{form_type}', expected 'WAVE' or 'XWMA'")

    try:
        header = parse_wem_header(data)
    except Exception as exc:
        errors.append(f"Header parsing failed: {exc}")
        return False, errors

    valid_tags = (
        WemFormatTag.PCM,
        WemFormatTag.ADPCM,
        WemFormatTag.EXTENSIBLE,
        WemFormatTag.VORBIS,
    )
    if header.format_tag not in valid_tags:
        errors.append(f"Unsupported format tag: 0x{header.format_tag:04X}")

    if not (1 <= header.channels <= 8):
        errors.append(f"Invalid channel count: {header.channels} (supported: 1..8)")

    if header.format_tag == WemFormatTag.VORBIS:
        if not header.vorbis_info:
            errors.append("Wwise Vorbis format tag 0xFFFF requires valid 42-byte extension header")
    elif require_vorbis:
        errors.append(f"Expected Wwise Vorbis codec (0xFFFF), got 0x{header.format_tag:04X}")

    if header.format_tag == WemFormatTag.ADPCM:
        expected_align = 36 * header.channels
        if header.block_align != expected_align:
            errors.append(
                f"Invalid ADPCM block alignment: {header.block_align}, expected {expected_align}"
            )

    if expected_sample_rate is not None and header.sample_rate != expected_sample_rate:
        errors.append(
            f"Sample rate mismatch: {header.sample_rate} Hz, expected {expected_sample_rate} Hz"
        )

    if expected_channels is not None and header.channels != expected_channels:
        errors.append(f"Channel count mismatch: {header.channels}, expected {expected_channels}")

    if header.loop_end > 0 and header.loop_start > header.loop_end:
        errors.append(
            f"Invalid loop points: loop_start ({header.loop_start}) > loop_end ({header.loop_end})"
        )

    if header.data_size <= 0:
        errors.append("Empty audio payload (data_size is 0)")

    return len(errors) == 0, errors


def build_pcm_wem_from_wav_bytes(
    wav_bytes: bytes,
    target_sample_rate: int = 32000,
    target_channels: int = 1,
) -> bytes:
    """
    Constructs an Audiokinetic Wwise compliant 0xFFFE PCM .wem container from raw PCM
    or standard WAV bytes.
    """
    src_rate = target_sample_rate
    src_channels = target_channels
    src_bits = 16
    fmt_tag = 1
    pcm_data: bytes = b""

    if wav_bytes.startswith(b"RIFF") and len(wav_bytes) >= 12 and wav_bytes[8:12] == b"WAVE":
        offset = 12
        while offset + 8 <= len(wav_bytes):
            cid = wav_bytes[offset : offset + 4]
            csz = struct.unpack_from("<I", wav_bytes, offset + 4)[0]
            pay_start = offset + 8
            pay_end = pay_start + csz
            if cid == b"fmt " and csz >= 16:
                fmt_tag, src_channels = struct.unpack_from("<HH", wav_bytes, pay_start)
                src_rate, _ = struct.unpack_from("<II", wav_bytes, pay_start + 4)
                _, src_bits = struct.unpack_from("<HH", wav_bytes, pay_start + 12)
            elif cid == b"data":
                pcm_data = wav_bytes[pay_start:pay_end]
            offset = pay_end + (csz & 1)
    else:
        pcm_data = wav_bytes

    if not pcm_data:
        pcm_data = b"\x00\x00" * 320

    samples_float: list[float] = []

    if src_bits == 16 and fmt_tag in (1, 0xFFFE):
        num_shorts = len(pcm_data) // 2
        shorts = struct.unpack_from(f"<{num_shorts}h", pcm_data)
        samples_float = [s / 32768.0 for s in shorts]
    elif src_bits == 8 and fmt_tag == 1:
        samples_float = [(b - 128) / 128.0 for b in pcm_data]
    elif src_bits == 24 and fmt_tag == 1:
        num_s24 = len(pcm_data) // 3
        for i in range(num_s24):
            b0, b1, b2 = pcm_data[i * 3 : i * 3 + 3]
            val = (b2 << 16) | (b1 << 8) | b0
            if val & 0x800000:
                val -= 0x1000000
            samples_float.append(val / 8388608.0)
    elif src_bits == 32 and fmt_tag == 3:  # IEEE float
        num_floats = len(pcm_data) // 4
        samples_float = list(struct.unpack_from(f"<{num_floats}f", pcm_data))
    elif src_bits == 32 and fmt_tag == 1:  # 32-bit int
        num_ints = len(pcm_data) // 4
        ints = struct.unpack_from(f"<{num_ints}i", pcm_data)
        samples_float = [val / 2147483648.0 for val in ints]
    else:
        num_shorts = len(pcm_data) // 2
        shorts = struct.unpack_from(f"<{num_shorts}h", pcm_data) if num_shorts > 0 else (0,)
        samples_float = [s / 32768.0 for s in shorts]

    # Downmix or adjust channels
    mono_samples: list[float] = []
    if src_channels > 1:
        num_frames = len(samples_float) // src_channels
        for f in range(num_frames):
            avg_val = sum(samples_float[f * src_channels + c] for c in range(src_channels)) / float(
                src_channels
            )
            mono_samples.append(avg_val)
    else:
        mono_samples = samples_float

    # Resample to target_sample_rate
    if src_rate != target_sample_rate and src_rate > 0 and len(mono_samples) > 1:
        in_len = len(mono_samples)
        out_len = int(round(in_len * (target_sample_rate / float(src_rate))))
        out_samples = [0.0] * out_len
        ratio = (in_len - 1) / float(max(1, out_len - 1))
        for i in range(out_len):
            src_pos = i * ratio
            idx0 = int(src_pos)
            idx1 = min(idx0 + 1, in_len - 1)
            frac = src_pos - idx0
            out_samples[i] = mono_samples[idx0] * (1.0 - frac) + mono_samples[idx1] * frac
        mono_samples = out_samples

    # Convert to 16-bit PCM shorts
    final_shorts = array.array("h")
    for s in mono_samples:
        clamped = max(-1.0, min(1.0, s))
        val = int(round(clamped * 32767.0))
        final_shorts.append(val)

    if sys.byteorder != "little":
        final_shorts.byteswap()
    out_pcm_data = final_shorts.tobytes()

    channels = target_channels
    sample_rate = target_sample_rate
    block_align = channels * 2
    avg_bytes_per_sec = sample_rate * block_align

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
            4 if channels == 1 else 3,  # dwChannelMask
        )
        + subformat_pcm
    )

    fmt_chunk = b"fmt " + struct.pack("<I", len(fmt_payload)) + fmt_payload
    data_pad = len(out_pcm_data) & 1
    data_chunk = (
        b"data"
        + struct.pack("<I", len(out_pcm_data))
        + out_pcm_data
        + (b"\x00" if data_pad else b"")
    )
    riff_len = 4 + len(fmt_chunk) + len(data_chunk)
    return b"RIFF" + struct.pack("<I", riff_len) + b"WAVE" + fmt_chunk + data_chunk


def build_silent_pcm_wem_bytes(duration_ms: int = 50, sample_rate: int = 32000) -> bytes:
    """Constructs an Audiokinetic Wwise compliant 0xFFFE PCM .wem container filled with silence."""
    num_frames = max(1, int(round(sample_rate * duration_ms / 1000.0)))
    raw_pcm = b"\x00\x00" * num_frames
    return build_pcm_wem_from_wav_bytes(raw_pcm, target_sample_rate=sample_rate, target_channels=1)
