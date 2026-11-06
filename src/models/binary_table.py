"""Native binary database table decoder for Total War game databases."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from src.models.db_schemas import get_table_schema

MAGIC_BINARY_DB = b"\xfd\xfe\xfc\xff"
MAGIC_EXTENDED_HEADER = b"\xfc\xfd\xfe\xff"


def is_binary_db_table(data: bytes) -> bool:
    """Checks whether byte buffer begins with Total War binary DB magic bytes."""
    return len(data) >= 4 and data[:4] == MAGIC_BINARY_DB


def _read_str_u8(data: bytes, offset: int) -> tuple[str, int]:
    if offset + 2 > len(data):
        raise ValueError("Buffer truncated while reading StringU8 length")
    length = struct.unpack("<H", data[offset : offset + 2])[0]
    end = offset + 2 + length
    if end > len(data):
        raise ValueError("Buffer truncated while reading StringU8 characters")
    raw = data[offset + 2 : end]
    try:
        val = raw.decode("utf-8")
    except UnicodeDecodeError:
        val = raw.decode("latin1", errors="replace")
    return val, end


def _read_opt_str_u8(data: bytes, offset: int) -> tuple[str | None, int]:
    if offset >= len(data):
        raise ValueError("Buffer truncated while reading OptionalStringU8 flag")
    flag = data[offset]
    offset += 1
    if flag == 0:
        return None, offset
    return _read_str_u8(data, offset)


def _read_str_u16(data: bytes, offset: int) -> tuple[str, int]:
    if offset + 2 > len(data):
        raise ValueError("Buffer truncated while reading StringU16 length")
    length = struct.unpack("<H", data[offset : offset + 2])[0]
    byte_len = length * 2
    end = offset + 2 + byte_len
    if end > len(data):
        raise ValueError("Buffer truncated while reading StringU16 characters")
    val = data[offset + 2 : end].decode("utf-16-le", errors="replace")
    return val, end


def _read_opt_str_u16(data: bytes, offset: int) -> tuple[str | None, int]:
    if offset >= len(data):
        raise ValueError("Buffer truncated while reading OptionalStringU16 flag")
    flag = data[offset]
    offset += 1
    if flag == 0:
        return None, offset
    return _read_str_u16(data, offset)


def decode_binary_table(
    data: bytes,
    table_name: str,
    schema_override: list[tuple[str, str]] | None = None,
) -> tuple[int, list[dict[str, Any]], int]:
    """
    Decodes a Total War binary DB table buffer into standardized record dictionaries.
    Returns: (version, rows, final_byte_offset).
    """
    if not is_binary_db_table(data):
        raise ValueError(f"Data is not a valid binary Total War database table for {table_name}")

    # 1. Unpack GUID
    if len(data) < 6:
        raise ValueError("Buffer too short to contain DB GUID length")
    guid_len = struct.unpack("<H", data[4:6])[0]
    offset = 6 + guid_len * 2
    if offset > len(data):
        raise ValueError("Buffer too short to contain DB GUID string")

    # 2. Check Extended Header vs Legacy Header
    if data[offset : offset + 4] == MAGIC_EXTENDED_HEADER:
        if offset + 13 > len(data):
            raise ValueError("Buffer truncated while reading extended DB header")
        version = struct.unpack("<I", data[offset + 4 : offset + 8])[0]
        # data[offset + 8] is extra byte
        row_count = struct.unpack("<I", data[offset + 9 : offset + 13])[0]
        offset += 13
    else:
        if offset + 5 > len(data):
            raise ValueError("Buffer truncated while reading legacy DB header")
        version = 0
        # data[offset] is extra byte
        row_count = struct.unpack("<I", data[offset + 1 : offset + 5])[0]
        offset += 5

    # 3. Retrieve schema
    fields = schema_override or get_table_schema(table_name, version)
    if not fields:
        raise ValueError(f"No schema definition found for table {table_name} version {version}")

    # 4. Unpack rows
    rows: list[dict[str, Any]] = []
    for _ in range(row_count):
        row_dict: dict[str, Any] = {}
        for f_name, f_type in fields:
            if f_type in ("StringU8", "String"):
                val, offset = _read_str_u8(data, offset)
            elif f_type in ("OptionalStringU8", "OptionalString"):
                val, offset = _read_opt_str_u8(data, offset)
            elif f_type == "StringU16":
                val, offset = _read_str_u16(data, offset)
            elif f_type == "OptionalStringU16":
                val, offset = _read_opt_str_u16(data, offset)
            elif f_type in ("I32", "Integer"):
                if offset + 4 > len(data):
                    raise ValueError(f"Buffer truncated on field {f_name}")
                val = struct.unpack("<i", data[offset : offset + 4])[0]
                offset += 4
            elif f_type in ("F32", "Float"):
                if offset + 4 > len(data):
                    raise ValueError(f"Buffer truncated on field {f_name}")
                val = struct.unpack("<f", data[offset : offset + 4])[0]
                offset += 4
            elif f_type in ("Boolean", "Bool"):
                if offset >= len(data):
                    raise ValueError(f"Buffer truncated on field {f_name}")
                val = bool(data[offset])
                offset += 1
            elif f_type in ("I64", "LongInteger"):
                if offset + 8 > len(data):
                    raise ValueError(f"Buffer truncated on field {f_name}")
                val = struct.unpack("<q", data[offset : offset + 8])[0]
                offset += 8
            elif f_type in ("I16", "ShortInteger"):
                if offset + 2 > len(data):
                    raise ValueError(f"Buffer truncated on field {f_name}")
                val = struct.unpack("<h", data[offset : offset + 2])[0]
                offset += 2
            else:
                raise ValueError(f"Unsupported schema field type '{f_type}' for {f_name}")
            row_dict[f_name] = val
        rows.append(row_dict)

    return version, rows, offset


def decode_binary_table_file(
    file_path: Path | str,
    table_name: str | None = None,
) -> list[dict[str, Any]]:
    """
    Reads a binary database table file from disk and decodes its records.
    If table_name is omitted, infers it from the filename or parent folder.
    """
    p = Path(file_path)
    data = p.read_bytes()

    if table_name is None:
        # Infer table name from file stem or parent directory
        name = p.stem.lower()
        if not name.endswith("_tables") and p.parent.name.lower().endswith("_tables"):
            name = p.parent.name.lower()
        table_name = name

    _, rows, _ = decode_binary_table(data, table_name)
    return rows
