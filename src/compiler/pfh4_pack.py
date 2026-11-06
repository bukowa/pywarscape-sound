"""
Pure-Python Total War PFH4 Pack reader and Mod .pack compiler for v3.
Provides standalone reading of PFH4 archives and generation of PT_MOD (and PT_MOVIE) .pack files.
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

PFH4_MAGIC = b"PFH4"
PFH5_MAGIC = b"PFH5"

PT_BOOT = 0
PT_RELEASE = 1
PT_PATCH = 2
PT_MOD = 3
PT_MOVIE = 4

MASK_ENCRYPTED_DATA = 0x10
MASK_HAS_FILE_TIMESTAMPS = 0x20
MASK_HAS_EXTENDED_HEADER = 0x40

PFH4_KEY = 0x8FEB2A6740A6920E


@dataclass(slots=True, frozen=True)
class PfhEntry:
    path: str
    size: int
    offset: int
    is_encrypted: bool = False


def decrypt_pfh4_stream(data: bytes) -> bytes:
    """Decrypts or encrypts a PFH4 stream using CA's 64-bit keystream cipher."""
    orig_len = len(data)
    pad = (8 - (orig_len % 8)) % 8
    buf = bytearray(data) + bytearray(pad)
    chunks = len(buf) // 8

    for i in range(chunks):
        off = i * 8
        k_ca = (((~off) & 0xFFFFFFFF) * PFH4_KEY) & 0xFFFFFFFFFFFFFFFF
        val = struct.unpack_from("<Q", buf, off)[0]
        struct.pack_into("<Q", buf, off, val ^ k_ca)

    return bytes(buf[:orig_len])


def normalize_pack_path(virtual_path: str) -> str:
    """Normalizes an internal pack virtual path to backslashes and validates safety."""
    norm = virtual_path.replace("/", "\\").strip().strip("\\")
    parts = [p for p in norm.split("\\") if p]
    if not parts or any(p in (".", "..") for p in parts):
        raise ValueError(f"Invalid pack entry path: {virtual_path!r}")
    return "\\".join(parts)


def read_pfh4_index(pack_path: str | Path) -> list[PfhEntry]:
    """Reads the index of a PFH4 (or uncompressed PFH5) pack archive."""
    p = Path(pack_path)
    with open(p, "rb") as f:
        hdr = f.read(28)
        if len(hdr) < 28:
            raise ValueError(f"Pack file too small for PFH header ({len(hdr)} bytes)")
        magic, mask, dep_count, dep_size, file_count, index_size, _ = struct.unpack(
            "<4sIIIIII", hdr
        )
        if magic not in (PFH4_MAGIC, PFH5_MAGIC, b"PFH0", b"PFH2", b"PFH3"):
            raise ValueError(f"Unsupported PFH magic: {magic!r}")

        ext_hdr_size = 256 if (magic == PFH4_MAGIC and (mask & MASK_HAS_EXTENDED_HEADER)) else 0
        if ext_hdr_size > 0:
            f.seek(28 + ext_hdr_size)
        if dep_size > 0:
            f.seek(28 + ext_hdr_size + dep_size)

        index_bytes = f.read(index_size)
        if len(index_bytes) < index_size:
            raise ValueError("Truncated PFH file index")

        data_start = 28 + ext_hdr_size + dep_size + index_size
        offset = 0
        has_file_ts = bool(mask & MASK_HAS_FILE_TIMESTAMPS)
        is_encrypted = bool(mask & MASK_ENCRYPTED_DATA)
        is_pfh5 = magic == PFH5_MAGIC

        raw_entries: list[tuple[str, int]] = []
        for _ in range(file_count):
            if offset + 4 > len(index_bytes):
                raise ValueError("Premature end of file index reading file size")
            (f_size,) = struct.unpack_from("<I", index_bytes, offset)
            offset += 4

            if is_pfh5:
                if offset >= len(index_bytes):
                    raise ValueError("Premature end of PFH5 index reading compression flag")
                (is_comp,) = struct.unpack_from("<B", index_bytes, offset)
                offset += 1
                if is_comp != 0:
                    raise ValueError("Compressed PFH5 archives are not supported")

            if has_file_ts:
                offset += 4

            z_pos = index_bytes.find(b"\x00", offset)
            if z_pos < 0:
                raise ValueError("Unterminated file path in PFH index")
            entry_path = index_bytes[offset:z_pos].decode("utf-8", errors="replace")
            offset = z_pos + 1
            raw_entries.append((entry_path, f_size))

        cur_data_off = data_start
        entries: list[PfhEntry] = []
        for e_path, e_size in raw_entries:
            entries.append(
                PfhEntry(
                    path=e_path,
                    size=e_size,
                    offset=cur_data_off,
                    is_encrypted=is_encrypted,
                )
            )
            cur_data_off += e_size
        return entries


def extract_pfh4_file(pack_path: str | Path, entry: PfhEntry) -> bytes:
    """Streams and extracts a single file from a PFH pack at entry.offset, decrypting if encrypted."""
    with open(pack_path, "rb") as f:
        f.seek(entry.offset)
        data = f.read(entry.size)
        if len(data) < entry.size:
            raise EOFError(
                f"Corrupted or truncated pack: expected {entry.size} bytes for '{entry.path}', got {len(data)}"
            )
        if entry.is_encrypted:
            data = decrypt_pfh4_stream(data)
        return data


def read_pfh4_pack_type(pack_path: str | Path) -> int:
    """Reads the pack type (e.g. PT_MOVIE = 4, PT_MOD = 3) from a PFH pack header."""
    p = Path(pack_path)
    with open(p, "rb") as f:
        hdr = f.read(28)
        if len(hdr) < 28:
            raise ValueError(f"Pack file too small for PFH header ({len(hdr)} bytes)")
        magic, mask, _, _, _, _, _ = struct.unpack("<4sIIIIII", hdr)
        if magic not in (PFH4_MAGIC, PFH5_MAGIC, b"PFH0", b"PFH2", b"PFH3"):
            raise ValueError(f"Unsupported PFH magic: {magic!r}")
        return mask & 0x0F


def format_user_script_entry(pack_name: str) -> str:
    """Formats a Total War user.script.txt entry for a mod pack (PT_MOD)."""
    clean_name = Path(pack_name).name
    return f'mod "{clean_name}";\r\n'


def write_pfh4_pack(
    output_path: str | Path,
    files: dict[str, bytes] | Sequence[tuple[str, bytes]],
    pack_type: int = PT_MOD,
    timestamp: int = 0,
) -> Path:
    """Builds and writes a Total War PFH4 pack (default PT_MOD = 3) containing files."""
    raw_items = list(files.items()) if isinstance(files, dict) else list(files)
    normalized: list[tuple[str, bytes]] = []
    seen = set()

    for path_str, data in raw_items:
        norm_path = normalize_pack_path(path_str)
        key = norm_path.lower()
        if key in seen:
            raise ValueError(f"Duplicate entry path in pack: {norm_path!r}")
        seen.add(key)
        normalized.append((norm_path, bytes(data)))

    normalized.sort(key=lambda item: item[0].lower())

    idx_buf = bytearray()
    for norm_path, payload in normalized:
        idx_buf.extend(struct.pack("<I", len(payload)))
        idx_buf.extend(norm_path.encode("utf-8") + b"\x00")

    hdr = struct.pack(
        "<4sIIIIII",
        PFH4_MAGIC,
        pack_type,
        0,
        0,
        len(normalized),
        len(idx_buf),
        timestamp,
    )

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with open(out_p, "wb") as f:
        f.write(hdr)
        f.write(idx_buf)
        for _, payload in normalized:
            f.write(payload)
    return out_p


def write_pfh4_mod_pack(
    output_path: str | Path,
    files: dict[str, bytes] | Sequence[tuple[str, bytes]],
    timestamp: int = 0,
) -> Path:
    """Builds and writes a Total War PFH4 Mod pack (PT_MOD = 3) containing files."""
    return write_pfh4_pack(output_path, files, pack_type=PT_MOD, timestamp=timestamp)


def write_pfh4_movie_pack(
    output_path: str | Path,
    files: dict[str, bytes] | Sequence[tuple[str, bytes]],
    timestamp: int = 0,
) -> Path:
    """Builds and writes a Total War PFH4 Movie pack (PT_MOVIE = 4) containing files."""
    return write_pfh4_pack(output_path, files, pack_type=PT_MOVIE, timestamp=timestamp)
