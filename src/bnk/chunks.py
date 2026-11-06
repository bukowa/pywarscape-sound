"""Audiokinetic Wwise v112 SoundBank chunk headers and RIFF media structures."""

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from src.bnk.stream import ByteReader, ByteWriter


@dataclass(slots=True)
class BkhdChunk:
    """BKHD (Bank Header) chunk for Wwise SoundBank v112."""

    version: int = 112
    bank_id: int = 0
    language_id: int = 0
    feedback_in_bank: int = 0
    project_id: int = 0
    padding: bytes = b""

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        version, bank_id, language_id, feedback_in_bank, project_id = reader.read_struct("<IIIII")
        padding = reader.read_remaining()
        return cls(
            version=version,
            bank_id=bank_id,
            language_id=language_id,
            feedback_in_bank=feedback_in_bank,
            project_id=project_id,
            padding=padding,
        )

    def write(self, writer: ByteWriter) -> None:
        writer.write_struct(
            "<IIIII",
            self.version,
            self.bank_id,
            self.language_id,
            self.feedback_in_bank,
            self.project_id,
        )
        if self.padding:
            writer.write_bytes(self.padding)

    def to_bytes(self) -> bytes:
        writer = ByteWriter()
        self.write(writer)
        return writer.get_bytes()


@dataclass(slots=True)
class DidxEntry:
    """DIDX media index entry pointing to embedded WEM media in DATA chunk."""

    file_id: int
    offset: int
    size: int


@dataclass(slots=True)
class DidxChunk:
    """DIDX (Data Index) chunk containing lookup table for embedded audio files."""

    entries: list[DidxEntry] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        entries: list[DidxEntry] = []
        while reader.remaining >= 12:
            file_id, offset, size = reader.read_struct("<III")
            entries.append(DidxEntry(file_id=file_id, offset=offset, size=size))
        return cls(entries=entries)

    def write(self, writer: ByteWriter) -> None:
        for entry in self.entries:
            writer.write_struct("<III", entry.file_id, entry.offset, entry.size)

    def to_bytes(self) -> bytes:
        writer = ByteWriter()
        self.write(writer)
        return writer.get_bytes()


@dataclass(slots=True)
class DataChunk:
    """DATA chunk storing raw 16-byte aligned embedded audio files."""

    data: bytes = b""

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        return cls(data=reader.read_remaining())

    def write(self, writer: ByteWriter) -> None:
        writer.write_bytes(self.data)

    def to_bytes(self) -> bytes:
        return self.data

    def extract(self, offset: int, size: int) -> bytes:
        return self.data[offset : offset + size]

    def align_and_append(self, media_bytes: bytes) -> tuple[int, int]:
        rem = len(self.data) % 16
        pad = (16 - rem) % 16 if rem != 0 else 0
        offset = len(self.data) + pad
        self.data = self.data + (b"\x00" * pad) + media_bytes
        return (offset, len(media_bytes))


@dataclass(slots=True)
class StidChunk:
    """STID (SoundBank ID and Name Table) chunk."""

    bank_names: dict[int, str] = field(default_factory=dict)
    ui_type: int = 1
    trailing_bytes: bytes = b""

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        ui_type, count = reader.read_struct("<II")
        bank_names: dict[int, str] = {}
        for _ in range(count):
            bank_id = reader.read_u32()
            name_len = reader.read_u8()
            name = reader.read_bytes(name_len).decode("latin1")
            bank_names[bank_id] = name
        trailing = reader.read_remaining()
        return cls(bank_names=bank_names, ui_type=ui_type, trailing_bytes=trailing)

    def write(self, writer: ByteWriter) -> None:
        writer.write_struct("<II", self.ui_type, len(self.bank_names))
        for bank_id, name in self.bank_names.items():
            encoded = name.encode("latin1")
            writer.write_u32(bank_id)
            writer.write_u8(len(encoded))
            writer.write_bytes(encoded)
        if self.trailing_bytes:
            writer.write_bytes(self.trailing_bytes)

    def to_bytes(self) -> bytes:
        writer = ByteWriter()
        self.write(writer)
        return writer.get_bytes()


@dataclass(slots=True)
class WemHeader:
    """Minimal pure-Python RIFF/WAVE header inspector for .wem audio streams."""

    format_code: int = 0
    channels: int = 0
    sample_rate: int = 0
    avg_bytes_per_sec: int = 0
    block_align: int = 0
    bits_per_sample: int = 0
    data_size: int = 0
    data_offset: int = 0
    duration_ms: float = 0.0

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        fourcc = reader.read_fourcc()
        if fourcc != "RIFF":
            raise ValueError(f"Expected RIFF header, got {fourcc}")
        _riff_size = reader.read_u32()
        wave_fourcc = reader.read_fourcc()
        if wave_fourcc != "WAVE":
            raise ValueError(f"Expected WAVE chunk, got {wave_fourcc}")

        format_code = 0
        channels = 0
        sample_rate = 0
        avg_bytes_per_sec = 0
        block_align = 0
        bits_per_sample = 0
        data_size = 0
        data_offset = 0

        while reader.remaining >= 8:
            tag = reader.read_fourcc()
            size = reader.read_u32()
            if tag == "fmt ":
                sub = reader.read_slice(size)
                (
                    format_code,
                    channels,
                    sample_rate,
                    avg_bytes_per_sec,
                    block_align,
                    bits_per_sample,
                ) = sub.read_struct("<HHIIHH")
            elif tag == "data":
                data_size = size
                data_offset = reader.offset
                reader.skip(size)
            else:
                reader.skip(size)

        duration_ms = 0.0
        if avg_bytes_per_sec > 0 and data_size > 0:
            duration_ms = (data_size / avg_bytes_per_sec) * 1000.0

        return cls(
            format_code=format_code,
            channels=channels,
            sample_rate=sample_rate,
            avg_bytes_per_sec=avg_bytes_per_sec,
            block_align=block_align,
            bits_per_sample=bits_per_sample,
            data_size=data_size,
            data_offset=data_offset,
            duration_ms=duration_ms,
        )


def scan_didx_media_ids(path: Path | str) -> frozenset[int]:
    """Fast header-only scan of BKHD + DIDX chunks to extract embedded WEM IDs without full AST overhead."""
    p = Path(path)
    try:
        with open(p, "rb") as f:
            data = f.read(65536)
            pos = 0
            while pos + 8 <= len(data):
                tag = data[pos : pos + 4]
                chunk_len = struct.unpack_from("<I", data, pos + 4)[0]
                pos += 8
                if tag == b"DIDX":
                    chunk_data = data[pos : pos + chunk_len]
                    if len(chunk_data) < chunk_len:
                        f.seek(pos)
                        chunk_data = f.read(chunk_len)
                    ids: set[int] = set()
                    for i in range(0, len(chunk_data) - 11, 12):
                        file_id = struct.unpack_from("<I", chunk_data, i)[0]
                        ids.add(file_id)
                    return frozenset(ids)
                if tag in (b"DATA", b"HIRC"):
                    return frozenset()
                pos += chunk_len
    except OSError:
        return frozenset()
    return frozenset()
