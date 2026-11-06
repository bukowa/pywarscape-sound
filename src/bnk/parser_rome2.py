"""Dedicated SoundBank HIRC parser for Total War: Rome II.

Rome II is a dual-generation Wwise game:
- Modern banks use Wwise v112 (same as Total War: Attila).
- Legacy release banks use Wwise v88 (2013), featuring 5-curve attenuation,
  32-bit media stream types, and legacy RTPC parameter IDs.

This parser handles typed deserialization for Rome II specific structures and
guarantees 100% bit-exact roundtrip preservation across all Rome II banks.
"""

import struct
from dataclasses import dataclass, field
from typing import Self

from src.bnk.models import (
    HIRC_TYPE_MAP,
    AkAttenuationCurve,
    AkRtpcEntry,
    CAkAttenuation,
    CAkGenericHirc,
    HircObject,
)
from src.bnk.stream import ByteReader, ByteWriter


@dataclass(slots=True)
class CAkAttenuationV88(HircObject):
    """CAkAttenuation (Type 14) for Wwise v88 with 5 curves and 4-float cone."""

    obj_type: int = 14
    cone_enabled: int = 0
    cone_params: tuple[float, float, float, float] | None = None
    curve_to_use: list[int] = field(default_factory=lambda: [0] * 5)
    curves: list[AkAttenuationCurve] = field(default_factory=list)
    rtpcs: list[AkRtpcEntry] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        cone_enabled = reader.read_u8()
        cone_params = None
        if cone_enabled != 0:
            c0, c1, c2, c3 = reader.read_struct("<ffff")
            cone_params = (c0, c1, c2, c3)
        curve_to_use = list(reader.read_bytes(5))
        num_curves = reader.read_u8()
        curves = [AkAttenuationCurve.read(reader) for _ in range(num_curves)]
        rtpcs = AkRtpcEntry.read_list(reader) if reader.remaining > 0 else []
        return cls(
            id=obj_id,
            obj_type=14,
            cone_enabled=cone_enabled,
            cone_params=cone_params,
            curve_to_use=curve_to_use,
            curves=curves,
            rtpcs=rtpcs,
        )

    def write_body(self, writer: ByteWriter) -> None:
        writer.write_u8(self.cone_enabled)
        if self.cone_enabled != 0:
            if self.cone_params:
                writer.write_struct("<ffff", *self.cone_params[:4])
            else:
                writer.write_struct("<ffff", 0.0, 0.0, 0.0, 0.0)
        for c in self.curve_to_use[:5]:
            writer.write_u8(c)
        for _ in range(5 - len(self.curve_to_use)):
            writer.write_u8(0)
        writer.write_u8(len(self.curves))
        for curve in self.curves:
            curve.write(writer)
        if self.rtpcs:
            AkRtpcEntry.write_list(writer, self.rtpcs)


def _parse_rome2_attenuation(reader: ByteReader, obj_id: int) -> HircObject | None:
    """Tries parsing attenuation using v88 or v112 schemas with bit-exact verification."""
    start_off = reader.offset

    # Try v88 layout
    try:
        reader.seek(start_off)
        att_v88 = CAkAttenuationV88.read(reader, obj_id)
        if reader.remaining == 0:
            w = ByteWriter()
            att_v88.write_body(w)
            reader.seek(start_off)
            if w.get_bytes() == reader.read_remaining():
                return att_v88
    except (struct.error, ValueError, EOFError):
        pass

    # Try standard v112 layout
    try:
        reader.seek(start_off)
        att_v112 = CAkAttenuation.read(reader, obj_id)
        if reader.remaining == 0:
            w = ByteWriter()
            att_v112.write_body(w)
            reader.seek(start_off)
            if w.get_bytes() == reader.read_remaining():
                return att_v112
    except (struct.error, ValueError, EOFError):
        pass

    reader.seek(start_off)
    return None


def parse_rome2_hirc_object(reader: ByteReader) -> HircObject:
    """Parses a single HIRC object record for Rome II (supporting both v88 and v112)."""
    obj_type = reader.read_u8()
    section_len = reader.read_u32()
    sub_reader = reader.read_slice(section_len)
    obj_id = sub_reader.read_u32()

    # 1. Specialized distance attenuation handling
    if obj_type == 14:
        att = _parse_rome2_attenuation(sub_reader, obj_id)
        if att is not None:
            return att

    # 2. Standard typed parser if it round-trips bit-exact
    cls = HIRC_TYPE_MAP.get(obj_type)
    if cls is not None:
        try:
            sub_reader.seek(4)
            obj = cls.read(sub_reader, obj_id)
            if sub_reader.remaining == 0:
                w = ByteWriter()
                obj.write_body(w)
                sub_reader.seek(4)
                if w.get_bytes() == sub_reader.read_remaining():
                    return obj
        except (struct.error, ValueError, EOFError):
            pass

    # 3. Fallback to bit-exact generic preservation
    sub_reader.seek(4)
    raw_body = sub_reader.read_remaining()
    return CAkGenericHirc(id=obj_id, obj_type=obj_type, raw_body=raw_body)
