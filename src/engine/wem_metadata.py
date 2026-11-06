"""Lazy WEM audio stream header inspection and SoundBank metadata resolution.

Provides fast sequential chunk scanning, loose file header inspection, and companion bank resolution with zero Qt imports.
"""

from __future__ import annotations

import struct
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.bnk.bank import SoundBank, repair_extracted_bnk_bytes
from src.bnk.models import CAkMusicTrack, CAkSound
from src.bnk.wem import repair_extracted_wem_bytes
from src.engine.metadata_fields import (
    EMPTY_NODE_METADATA,
    MetadataField,
    NodeMetadata,
    extract_wem_header_metadata,
)
from src.engine.ports import AssetResolverPort

_HEADER_PREFIX_BYTES = 1024


def _extract_from_slice(raw: bytes | bytearray | memoryview) -> NodeMetadata:
    """Extracts WEM metadata from raw bytes, falling back to full buffer if header prefix was insufficient."""
    meta = extract_wem_header_metadata(raw[:_HEADER_PREFIX_BYTES])
    if meta != EMPTY_NODE_METADATA or len(raw) <= _HEADER_PREFIX_BYTES:
        return meta
    return extract_wem_header_metadata(raw)


def _read_loose_file_header(path: Path) -> NodeMetadata:
    """Reads prefix of loose .wem file to extract header metadata, handling legacy archive encryption."""
    try:
        with path.open("rb") as f:
            prefix = f.read(_HEADER_PREFIX_BYTES)
            if len(prefix) < 12:
                return EMPTY_NODE_METADATA

            if len(prefix) >= 16 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WAVE":
                raw_riff_len = struct.unpack_from("<I", prefix, 4)[0]
                if raw_riff_len > 0x80000000:
                    full = prefix + f.read()
                    repaired = repair_extracted_wem_bytes(full)
                    return extract_wem_header_metadata(repaired)

            meta = extract_wem_header_metadata(prefix)
            if meta == EMPTY_NODE_METADATA and len(prefix) == _HEADER_PREFIX_BYTES:
                full = prefix + f.read()
                meta = extract_wem_header_metadata(full)
            return meta
    except (OSError, PermissionError, ValueError, struct.error):
        return EMPTY_NODE_METADATA


def _read_companion_bank_headers(
    bank_id: int,
    wem_ids: set[int],
    resolver: AssetResolverPort,
) -> dict[int, NodeMetadata]:
    """Reads WEM header metadata from a companion SoundBank via fast sequential scanning or fallback."""
    result: dict[int, NodeMetadata] = {}
    if not wem_ids:
        return result

    comp_path = None
    try:
        comp_path = resolver.resolve_bank_path_by_id(bank_id)
    except (OSError, PermissionError, ValueError, KeyError, AttributeError):
        pass

    if comp_path is not None:
        try:
            if comp_path.is_file():
                with comp_path.open("rb") as cf:
                    head = cf.read(8)
                    if len(head) == 8 and head[:4] == b"BKHD":
                        bkhd_sz = struct.unpack("<I", head[4:8])[0]
                        if bkhd_sz <= 1024:
                            bkhd_payload = cf.read(bkhd_sz)
                            if (
                                len(bkhd_payload) >= 4
                                and struct.unpack_from("<I", bkhd_payload, 0)[0] == 112
                            ):
                                didx_seen = False
                                data_base = 0
                                matched_entries: list[tuple[int, int, int]] = []
                                while True:
                                    ch = cf.read(8)
                                    if len(ch) < 8:
                                        break
                                    cid = ch[:4]
                                    csz = struct.unpack("<I", ch[4:8])[0]
                                    if cid == b"DIDX":
                                        didx_seen = True
                                        didx_data = cf.read(csz)
                                        for i in range(0, len(didx_data) - 11, 12):
                                            fid, foff, fsz = struct.unpack_from(
                                                "<III", didx_data, i
                                            )
                                            if fid in wem_ids:
                                                matched_entries.append((foff, fid, fsz))
                                    elif cid == b"DATA":
                                        data_base = cf.tell()
                                        break
                                    else:
                                        cf.seek(csz, 1)

                                if data_base > 0 and matched_entries:
                                    matched_entries.sort(key=lambda t: t[0])
                                    for foff, fid, fsz in matched_entries:
                                        cf.seek(data_base + foff)
                                        buf = cf.read(min(fsz, _HEADER_PREFIX_BYTES))
                                        meta = extract_wem_header_metadata(buf)
                                        if (
                                            meta == EMPTY_NODE_METADATA
                                            and fsz > _HEADER_PREFIX_BYTES
                                        ):
                                            cf.seek(data_base + foff)
                                            buf = cf.read(fsz)
                                            meta = extract_wem_header_metadata(buf)
                                        if meta.entries:
                                            result[fid] = meta
                                if didx_seen or data_base == 0:
                                    return result
        except (OSError, PermissionError, ValueError, struct.error):
            pass

    # Fallback path
    try:
        raw_bnk = resolver.resolve_bank_bytes_by_id(bank_id)
        if raw_bnk:
            repaired = repair_extracted_bnk_bytes(raw_bnk)
            comp_bank = SoundBank.from_bytes(repaired)
            if comp_bank.didx and comp_bank.data and comp_bank.data.data:
                d_mv = memoryview(comp_bank.data.data)
                for entry in comp_bank.didx.entries:
                    if entry.file_id in wem_ids:
                        slice_data = d_mv[entry.offset : entry.offset + entry.size]
                        meta = _extract_from_slice(slice_data)
                        if meta.entries:
                            result[entry.file_id] = meta
    except (
        OSError,
        PermissionError,
        ValueError,
        struct.error,
        KeyError,
        IndexError,
        RuntimeError,
    ):
        pass

    return result


def resolve_bank_wem_metadata(
    bank: SoundBank,
    resolver: AssetResolverPort | None = None,
) -> dict[str, NodeMetadata]:
    """Inspects all audio-bearing nodes in a SoundBank and returns resolved WEM header metadata."""
    didx_map: dict[int, tuple[int, int]] = {}
    if bank.didx and bank.didx.entries and bank.data and bank.data.data:
        didx_map = {entry.file_id: (entry.offset, entry.size) for entry in bank.didx.entries}

    cur_bank_id = bank.header.bank_id if bank.header else 0

    node_targets: dict[str, list[tuple]] = {}
    didx_wems: set[int] = set()
    companion_wems: dict[int, set[int]] = {}
    loose_wems: set[int] = set()

    # 1. Media nodes from DIDX
    if bank.didx and bank.didx.entries:
        for entry in bank.didx.entries:
            node_key = f"media:{entry.file_id}"
            if resolver is not None and resolver.is_wem_modified(entry.file_id):
                node_targets[node_key] = [("loose", entry.file_id), ("didx", entry.file_id)]
                loose_wems.add(entry.file_id)
                didx_wems.add(entry.file_id)
            else:
                node_targets[node_key] = [("didx", entry.file_id)]
                didx_wems.add(entry.file_id)

    # 2. HIRC objects
    if bank.hirc and bank.hirc.objects:
        for obj in bank.hirc.objects:
            if isinstance(obj, CAkSound):
                wid = getattr(obj, "source_id", 0) or getattr(obj, "file_id", 0)
                if wid > 0:
                    node_key = f"hirc:{obj.id}"
                    comp_id = getattr(obj, "file_id", 0)
                    has_comp = bool(comp_id and comp_id != cur_bank_id and resolver is not None)
                    in_didx = wid in didx_map

                    if resolver is not None and resolver.is_wem_modified(wid):
                        node_targets[node_key] = [("loose", wid)]
                        loose_wems.add(wid)
                    elif getattr(obj, "stream_type", 2) == 2:
                        t: list[tuple] = [("loose", wid)]
                        loose_wems.add(wid)
                        if in_didx:
                            t.append(("didx", wid))
                            didx_wems.add(wid)
                        if has_comp:
                            t.append(("companion", comp_id, wid))
                            companion_wems.setdefault(comp_id, set()).add(wid)
                        node_targets[node_key] = t
                    elif in_didx:
                        node_targets[node_key] = [("didx", wid)]
                        didx_wems.add(wid)
                    elif has_comp:
                        node_targets[node_key] = [("companion", comp_id, wid), ("loose", wid)]
                        companion_wems.setdefault(comp_id, set()).add(wid)
                        loose_wems.add(wid)
                    else:
                        node_targets[node_key] = [("loose", wid)]
                        loose_wems.add(wid)

            elif isinstance(obj, CAkMusicTrack):
                wid = obj.sources[0].source_id if obj.sources else getattr(obj, "source_id", 0)
                if wid > 0:
                    node_key = f"hirc:{obj.id}"
                    t_list: list[tuple] = []
                    if resolver is not None:
                        t_list.append(("loose", wid))
                        loose_wems.add(wid)
                    if wid in didx_map:
                        t_list.append(("didx", wid))
                        didx_wems.add(wid)
                    if t_list:
                        node_targets[node_key] = t_list

    # 3. Resolve current-bank DIDX slices
    didx_meta: dict[int, NodeMetadata] = {}
    if bank.data and bank.data.data:
        data_mv = memoryview(bank.data.data)
        for wid in didx_wems:
            if wid in didx_map:
                foff, fsz = didx_map[wid]
                if foff + fsz <= len(data_mv):
                    buf = data_mv[foff : foff + fsz]
                    meta = _extract_from_slice(buf)
                    if meta.entries:
                        didx_meta[wid] = meta

    # 4. Resolve companion banks
    companion_meta: dict[tuple[int, int], NodeMetadata] = {}
    if resolver is not None:
        for comp_bank_id, w_ids in companion_wems.items():
            comp_headers = _read_companion_bank_headers(comp_bank_id, w_ids, resolver)
            for cwid, cm in comp_headers.items():
                if cm.entries:
                    companion_meta[(comp_bank_id, cwid)] = cm

    # 5. Resolve loose WEMs
    loose_meta: dict[int, NodeMetadata] = {}
    if resolver is not None and loose_wems:
        loose_path_map: dict[int, Path | None] = {}
        for wid in loose_wems:
            try:
                loose_path_map[wid] = resolver.resolve_wem_path(wid)
            except (OSError, PermissionError, ValueError, KeyError, AttributeError):
                loose_path_map[wid] = None

        paths_to_read: dict[int, Path] = {}
        for wid, p in loose_path_map.items():
            if p is not None:
                try:
                    if p.is_file():
                        paths_to_read[wid] = p
                except (OSError, PermissionError):
                    pass

        if len(paths_to_read) > 32:
            with ThreadPoolExecutor(max_workers=min(16, len(paths_to_read))) as pool:
                future_to_wid = {
                    pool.submit(_read_loose_file_header, path): wid
                    for wid, path in paths_to_read.items()
                }
                for future in as_completed(future_to_wid):
                    wid = future_to_wid[future]
                    try:
                        m = future.result()
                        if m.entries:
                            loose_meta[wid] = m
                    except (OSError, PermissionError, ValueError, struct.error):
                        pass
        else:
            for wid, path in paths_to_read.items():
                m = _read_loose_file_header(path)
                if m.entries:
                    loose_meta[wid] = m

        for wid in loose_wems:
            if wid not in loose_meta:
                try:
                    raw = resolver.resolve_wem_bytes(wid)
                    if raw:
                        m = _extract_from_slice(raw)
                        if m.entries:
                            loose_meta[wid] = m
                except (
                    OSError,
                    PermissionError,
                    ValueError,
                    struct.error,
                    KeyError,
                    AttributeError,
                ):
                    pass

    # 6. Assemble node metadata results
    result: dict[str, NodeMetadata] = {}
    for node_key, targets in node_targets.items():
        for target in targets:
            kind = target[0]
            m = None
            if kind == "didx":
                m = didx_meta.get(target[1])
            elif kind == "companion":
                m = companion_meta.get((target[1], target[2]))
            elif kind == "loose":
                m = loose_meta.get(target[1])

            if m is not None and m.entries:
                result[node_key] = m
                break

    return result


def resolve_wem_duration_ms(
    wem_id: int,
    resolver: AssetResolverPort | None,
) -> float | None:
    """Inspects loose file header via resolver.resolve_wem_path(wem_id) and returns duration_ms if found."""
    if resolver is None:
        return None
    try:
        path = resolver.resolve_wem_path(wem_id)
        if path is not None and path.is_file():
            meta = _read_loose_file_header(path)
            mv = meta.get(MetadataField.DURATION_MS)
            if mv is not None and isinstance(mv.value, (int, float)):
                return float(mv.value)
        if hasattr(resolver, "resolve_wem_bytes"):
            raw = resolver.resolve_wem_bytes(wem_id)
            if raw:
                meta = _extract_from_slice(raw)
                mv = meta.get(MetadataField.DURATION_MS)
                if mv is not None and isinstance(mv.value, (int, float)):
                    return float(mv.value)
    except (OSError, PermissionError, ValueError, KeyError, AttributeError):
        pass
    return None
