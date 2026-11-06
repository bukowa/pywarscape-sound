"""
Test object factories and synthetic audio generators.
Provides helpers for creating AudioProject instances and mock WAV files.
"""

from __future__ import annotations

import os
import struct
import wave
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

import pytest

from src.compiler.pfh4_pack import PT_MOD, write_pfh4_pack
from src.models.binary_table import MAGIC_BINARY_DB, MAGIC_EXTENDED_HEADER
from src.models.db_schemas import TABLE_SCHEMAS, get_table_schema
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject

PFH4_TYPE_MOD: int = PT_MOD


def skip_or_fail_missing_asset(reason: str) -> NoReturn:
    """Skips the test when external game/mod assets are absent, or fails if REQUIRE_GAME_DATA=1."""
    if os.environ.get("REQUIRE_GAME_DATA") == "1":
        pytest.fail(f"[REQUIRE_GAME_DATA=1] {reason}")
    pytest.skip(reason)


def make_synthetic_wav(
    path: Path,
    duration_s: float = 0.2,
    sample_rate: int = 32000,
    tone: bool = False,
) -> Path:
    """Generates a small valid mono PCM WAV file for testing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = int(duration_s * sample_rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        if tone:
            frames = bytearray()
            for i in range(n_frames):
                val = int(8000 * ((i % 100) / 50.0 - 1.0))
                frames.extend(val.to_bytes(2, "little", signed=True))
            wf.writeframes(bytes(frames))
        else:
            wf.writeframes(b"\x00\x00" * n_frames)
    return path


def make_audio_project(
    root_dir: Path,
    name: str = "TestMod",
    game: str = "attila",
    description: str = "Test Mod Description",
) -> AudioProject:
    """Creates a lightweight AudioProject instance for tests."""
    manifest = ProjectManifest(
        name=name,
        game=game,
        description=description,
    )
    return AudioProject(root_dir=root_dir, manifest=manifest)


def encode_binary_db_table(
    table_type: str,
    rows: list[dict[str, Any]],
    *,
    version: int | None = None,
    guid: str = "test-guid",
) -> bytes:
    """Encodes table rows into a Total War binary DB table payload matching TABLE_SCHEMAS."""
    clean_name = table_type.lower()
    if clean_name.endswith(".tsv"):
        clean_name = clean_name[:-4]
    if clean_name.endswith(".bin"):
        clean_name = clean_name[:-4]
    if not clean_name.endswith("_tables"):
        clean_name = f"{clean_name}_tables"

    if version is None:
        candidates = sorted([v for (t, v) in TABLE_SCHEMAS if t == clean_name], reverse=True)
        version = candidates[0] if candidates else 0

    fields = get_table_schema(clean_name, version)
    if not fields:
        raise ValueError(f"No schema definition found for table {table_type} version {version}")

    guid_bytes = guid.encode("utf-16-le")
    guid_len = len(guid_bytes) // 2

    if version == 0:
        hdr = (
            MAGIC_BINARY_DB
            + struct.pack("<H", guid_len)
            + guid_bytes
            + struct.pack("<BI", 1, len(rows))
        )
    else:
        hdr = (
            MAGIC_BINARY_DB
            + struct.pack("<H", guid_len)
            + guid_bytes
            + MAGIC_EXTENDED_HEADER
            + struct.pack("<IBI", version, 1, len(rows))
        )

    buf = bytearray(hdr)
    for row in rows:
        for f_name, f_type in fields:
            val = row.get(f_name)
            if f_type in ("StringU8", "String"):
                raw_bytes = str(val if val is not None else "").encode("utf-8")
                buf.extend(struct.pack("<H", len(raw_bytes)))
                buf.extend(raw_bytes)
            elif f_type in ("OptionalStringU8", "OptionalString"):
                if val is None:
                    buf.append(0)
                else:
                    raw_bytes = str(val).encode("utf-8")
                    buf.append(1)
                    buf.extend(struct.pack("<H", len(raw_bytes)))
                    buf.extend(raw_bytes)
            elif f_type == "StringU16":
                s_val = str(val if val is not None else "")
                raw_bytes = s_val.encode("utf-16-le")
                buf.extend(struct.pack("<H", len(s_val)))
                buf.extend(raw_bytes)
            elif f_type == "OptionalStringU16":
                if val is None:
                    buf.append(0)
                else:
                    s_val = str(val)
                    raw_bytes = s_val.encode("utf-16-le")
                    buf.append(1)
                    buf.extend(struct.pack("<H", len(s_val)))
                    buf.extend(raw_bytes)
            elif f_type in ("I32", "Integer"):
                buf.extend(struct.pack("<i", int(val if val is not None else 0)))
            elif f_type in ("F32", "Float"):
                buf.extend(struct.pack("<f", float(val if val is not None else 0.0)))
            elif f_type in ("Boolean", "Bool"):
                buf.append(1 if val else 0)
            elif f_type in ("I64", "LongInteger"):
                buf.extend(struct.pack("<q", int(val if val is not None else 0)))
            elif f_type in ("I16", "ShortInteger"):
                buf.extend(struct.pack("<h", int(val if val is not None else 0)))
            else:
                raise ValueError(f"Unsupported schema field type '{f_type}' for {f_name}")

    return bytes(buf)


def write_synthetic_pfh4_pack(
    pack_path: Path,
    files: dict[str, bytes] | Sequence[tuple[str, bytes]],
    *,
    pack_type: int = PFH4_TYPE_MOD,
) -> Path:
    """Builds and writes a synthetic PFH4 pack archive for arbitrary internal paths."""
    return write_pfh4_pack(pack_path, files, pack_type=pack_type)
