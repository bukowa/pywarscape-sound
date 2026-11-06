"""Audiokinetic Wwise v112 SoundBank parser, serializer, and orchestrator."""

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from src.bnk.chunks import BkhdChunk, DataChunk, DidxChunk, DidxEntry, StidChunk  # noqa: F401
from src.bnk.models import (
    CAkRanSeqCntr,
    CAkSound,
    CAkSwitchCntr,
    HircObject,
)
from src.bnk.parser_attila import parse_attila_hirc_object
from src.bnk.parser_rome2 import parse_rome2_hirc_object
from src.bnk.stream import ByteReader, ByteWriter


def repair_extracted_bnk_bytes(data: bytes) -> bytes:
    """Repairs SoundBank binary payloads that contain legacy archive encryption artifacts."""
    if len(data) < 8 or data[:4] != b"BKHD":
        return data

    raw_bkhd_len = struct.unpack_from("<I", data, 4)[0]
    if raw_bkhd_len > 1024 and (raw_bkhd_len ^ 0xC0AFB23E) <= 1024:
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


@dataclass(slots=True)
class HircChunk:
    """HIRC (Hierarchy) chunk containing typed object tree."""

    objects: list[HircObject] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader, version: int = 112) -> Self:
        count = reader.read_u32()
        objects: list[HircObject] = []
        parse_fn = parse_rome2_hirc_object if version <= 88 else parse_attila_hirc_object
        for _ in range(count):
            objects.append(parse_fn(reader))
        return cls(objects=objects)

    def write(self, writer: ByteWriter) -> None:
        writer.write_u32(len(self.objects))
        for obj in self.objects:
            writer.write_bytes(obj.to_bytes())

    def to_bytes(self) -> bytes:
        writer = ByteWriter()
        self.write(writer)
        return writer.get_bytes()


@dataclass(slots=True)
class SoundBank:
    """Root Wwise SoundBank (.bnk) Version 112 orchestrator."""

    header: BkhdChunk = field(default_factory=BkhdChunk)
    didx: DidxChunk | None = None
    data: DataChunk | None = None
    hirc: HircChunk | None = None
    stid: StidChunk | None = None
    chunk_order: list[str] = field(default_factory=list)
    custom_chunks: dict[str, bytes] = field(default_factory=dict)

    @classmethod
    def from_bytes(cls, data: bytes) -> Self:
        cleaned_data = repair_extracted_bnk_bytes(data)
        reader = ByteReader(cleaned_data)

        header = BkhdChunk()
        didx: DidxChunk | None = None
        data_chunk: DataChunk | None = None
        hirc: HircChunk | None = None
        stid: StidChunk | None = None
        chunk_order: list[str] = []
        custom_chunks: dict[str, bytes] = {}

        while reader.remaining >= 8:
            tag = reader.read_bytes(4).decode("latin1", errors="replace")
            chunk_len = reader.read_u32()
            sub_reader = reader.read_slice(chunk_len)
            chunk_order.append(tag)

            if tag == "BKHD":
                header = BkhdChunk.read(sub_reader)
            elif tag == "DIDX":
                didx = DidxChunk.read(sub_reader)
            elif tag == "DATA":
                data_chunk = DataChunk.read(sub_reader)
            elif tag == "HIRC":
                hirc = HircChunk.read(sub_reader, version=header.version)
            elif tag == "STID":
                stid = StidChunk.read(sub_reader)
            else:
                custom_chunks[tag] = sub_reader.read_remaining()

        return cls(
            header=header,
            didx=didx,
            data=data_chunk,
            hirc=hirc,
            stid=stid,
            chunk_order=chunk_order,
            custom_chunks=custom_chunks,
        )

    def to_bytes(self) -> bytes:
        writer = ByteWriter()
        order = list(self.chunk_order) if self.chunk_order else self._build_default_chunk_order()

        active_order: list[str] = []
        for tag in order:
            if (
                tag == "BKHD"
                or (tag == "DIDX" and self.didx is not None)
                or (tag == "DATA" and self.data is not None)
                or (tag == "HIRC" and self.hirc is not None)
                or (tag == "STID" and self.stid is not None)
                or tag in self.custom_chunks
            ):
                active_order.append(tag)

        # Reconcile added chunks not present in original order
        if self.didx is not None and "DIDX" not in active_order:
            idx = active_order.index("BKHD") + 1 if "BKHD" in active_order else 0
            active_order.insert(idx, "DIDX")
        if self.data is not None and "DATA" not in active_order:
            idx = (
                active_order.index("DIDX") + 1
                if "DIDX" in active_order
                else (active_order.index("BKHD") + 1 if "BKHD" in active_order else 0)
            )
            active_order.insert(idx, "DATA")
        for tag in self.custom_chunks:
            if tag not in active_order:
                active_order.append(tag)
        if self.hirc is not None and "HIRC" not in active_order:
            active_order.append("HIRC")
        if self.stid is not None and "STID" not in active_order:
            active_order.append("STID")

        for tag in active_order:
            writer.write_bytes(tag.encode("latin1"))
            if tag == "BKHD":
                payload = self.header.to_bytes()
            elif tag == "DIDX":
                payload = self.didx.to_bytes() if self.didx is not None else b""
            elif tag == "DATA":
                payload = self.data.to_bytes() if self.data is not None else b""
            elif tag == "HIRC":
                payload = self.hirc.to_bytes() if self.hirc is not None else b""
            elif tag == "STID":
                payload = self.stid.to_bytes() if self.stid is not None else b""
            else:
                payload = self.custom_chunks[tag]

            writer.write_u32(len(payload))
            writer.write_bytes(payload)

        return writer.get_bytes()

    def _build_default_chunk_order(self) -> list[str]:
        order = ["BKHD"]
        if self.didx is not None:
            order.append("DIDX")
        if self.data is not None:
            order.append("DATA")
        for tag in self.custom_chunks:
            if tag not in order and tag not in ("HIRC", "STID"):
                order.append(tag)
        if self.hirc is not None:
            order.append("HIRC")
        if self.stid is not None:
            order.append("STID")
        return order

    @classmethod
    def from_file(cls, path: str | Path) -> Self:
        with open(path, "rb") as f:
            data = f.read()
        return cls.from_bytes(data)

    def save(self, path: str | Path) -> None:
        data = self.to_bytes()
        with open(path, "wb") as f:
            f.write(data)

    # -------------------------------------------------------------------------
    # Object Lookups & Mutations
    # -------------------------------------------------------------------------

    @property
    def objects(self) -> dict[int, HircObject]:
        """Provides dictionary view of all HIRC objects indexed by ShortID."""
        if self.hirc is None:
            return {}
        return {obj.id: obj for obj in self.hirc.objects}

    def get_object(self, obj_id: int) -> HircObject | None:
        if not self.hirc:
            return None
        for obj in self.hirc.objects:
            if obj.id == obj_id:
                return obj
        return None

    def get_sound(self, sound_id: int) -> CAkSound | None:
        obj = self.get_object(sound_id)
        return obj if isinstance(obj, CAkSound) else None

    def get_ran_seq(self, ran_seq_id: int) -> CAkRanSeqCntr | None:
        obj = self.get_object(ran_seq_id)
        return obj if isinstance(obj, CAkRanSeqCntr) else None

    def get_switch_cntr(self, switch_id: int) -> CAkSwitchCntr | None:
        obj = self.get_object(switch_id)
        return obj if isinstance(obj, CAkSwitchCntr) else None

    def add_object(self, obj: HircObject) -> None:
        if self.hirc is None:
            self.hirc = HircChunk()
            if "HIRC" not in self.chunk_order:
                self.chunk_order.append("HIRC")

        # Replace existing object with same ID or append
        for i, existing in enumerate(self.hirc.objects):
            if existing.id == obj.id:
                self.hirc.objects[i] = obj
                return
        self.hirc.objects.append(obj)

    def add_sound(self, sound: CAkSound) -> None:
        self.add_object(sound)

    def add_ran_seq(self, ran_seq: CAkRanSeqCntr) -> None:
        self.add_object(ran_seq)

    def get_media_data(self, file_id: int) -> bytes | None:
        """Extracts raw WEM bytes for an embedded file ID from DIDX and DATA chunks."""
        if not self.didx or not self.data or not self.data.data:
            return None
        for entry in self.didx.entries:
            if entry.file_id == file_id:
                if entry.offset + entry.size <= len(self.data.data):
                    return self.data.data[entry.offset : entry.offset + entry.size]
        return None
