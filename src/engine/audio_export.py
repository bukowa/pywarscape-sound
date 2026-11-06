"""Audio extraction pipeline for exporting SoundBank audio to WAV files.

Layer 2 module: zero Qt (PySide6) imports.
Resolves playable audio from bank nodes and exports decoded WAV to disk.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from src.bnk.bank import SoundBank, repair_extracted_bnk_bytes
from src.bnk.models import CAkMusicTrack, CAkSound
from src.deps.player import decode_wem_to_wav_bytes
from src.engine.ports import AssetResolverPort

if TYPE_CHECKING:
    from src.engine.graph import BankGraphIndex

logger = logging.getLogger(__name__)


def _get_or_load_companion_bank(
    bank_id: int,
    resolver: AssetResolverPort | None,
    cache: dict[int, SoundBank] | None,
) -> SoundBank | None:
    """Loads and caches companion SoundBank bytes for cross-bank media resolution."""
    if cache is not None and bank_id in cache:
        return cache[bank_id]
    if resolver is None:
        return None
    bytes_data = resolver.resolve_bank_bytes_by_id(bank_id)
    if not bytes_data:
        return None
    try:
        repaired = repair_extracted_bnk_bytes(bytes_data)
        loaded = SoundBank.from_bytes(repaired)
        if cache is not None:
            cache[bank_id] = loaded
        return loaded
    except (OSError, ValueError, KeyError, IndexError, RuntimeError):
        return None


def _resolve_wem_bytes(
    bank: SoundBank,
    wem_id: int,
    resolver: AssetResolverPort | None = None,
    companion_bank_id: int = 0,
    companion_cache: dict[int, SoundBank] | None = None,
) -> bytes | None:
    """Resolves raw WEM bytes from project overlay, resolver, or embedded bank DATA."""
    # 1. Project overlay staged loose WEM
    if resolver is not None:
        wem_path = resolver.resolve_wem_path(wem_id)
        if wem_path:
            return Path(wem_path).read_bytes()
        wem_bytes = resolver.resolve_wem_bytes(wem_id)
        if wem_bytes:
            return wem_bytes

    # 2. Embedded in bank DATA chunk
    data_chunk = getattr(bank, "data", getattr(bank, "data_chunk", None))
    if bank.didx and data_chunk:
        for entry in bank.didx.entries:
            if entry.file_id == wem_id:
                offset = entry.offset
                size = getattr(entry, "size", getattr(entry, "length", 0))
                return data_chunk.data[offset : offset + size]

    # 3. Embedded in companion SoundBank DATA chunk
    cur_bank_id = getattr(bank.header, "bank_id", 0) if bank.header else 0
    if companion_bank_id and companion_bank_id != cur_bank_id and resolver is not None:
        comp_bank = _get_or_load_companion_bank(companion_bank_id, resolver, companion_cache)
        if comp_bank is not None:
            comp_data = getattr(comp_bank, "data", getattr(comp_bank, "data_chunk", None))
            if comp_bank.didx and comp_data:
                for entry in comp_bank.didx.entries:
                    if entry.file_id == wem_id:
                        offset = entry.offset
                        size = getattr(entry, "size", getattr(entry, "length", 0))
                        return comp_data.data[offset : offset + size]

    return None


def resolve_node_wav_bytes(
    bank: SoundBank,
    node_key: str,
    resolver: AssetResolverPort | None = None,
    graph_index: BankGraphIndex | None = None,
    companion_cache: dict[int, SoundBank] | None = None,
) -> bytes:
    """
    Resolves and decodes a bank node's audio into 16-bit PCM WAV bytes in memory.

    Raises:
        ValueError: If the node has no playable audio source.
        FileNotFoundError: If audio source data cannot be resolved.
    """
    wem_id, comp_bank_id = _extract_wem_info_from_key(bank, node_key, graph_index)
    if wem_id is None or wem_id <= 0:
        raise ValueError(f"No audio source found for node key '{node_key}'")

    raw_bytes = _resolve_wem_bytes(
        bank,
        wem_id,
        resolver=resolver,
        companion_bank_id=comp_bank_id,
        companion_cache=companion_cache,
    )
    if raw_bytes is None and resolver is not None:
        wem_path = resolver.resolve_wem_path(wem_id)
        if wem_path:
            raw_bytes = Path(wem_path).read_bytes()
    if raw_bytes is None:
        raise FileNotFoundError(f"Could not resolve audio data for WEM ID {wem_id}")

    return decode_wem_to_wav_bytes(raw_bytes)


def export_node_to_wav(
    bank: SoundBank,
    node_key: str,
    destination: Path,
    resolver: AssetResolverPort | None = None,
    graph_index: BankGraphIndex | None = None,
    companion_cache: dict[int, SoundBank] | None = None,
) -> Path:
    """
    Exports a single bank node's audio to a WAV file on disk.

    Args:
        bank: The parsed SoundBank AST.
        node_key: Node key (e.g. 'hirc:12345' or 'media:67890').
        destination: Target .wav file path.
        resolver: Optional layered asset resolver for streamed/staged WEMs.
        graph_index: Optional pre-built graph index for HIRC object lookups.
        companion_cache: Optional cache for companion SoundBanks.

    Returns:
        Path to the written .wav file.

    Raises:
        ValueError: If the node has no playable audio.
        FileNotFoundError: If audio source data cannot be resolved.
    """
    wav_bytes = resolve_node_wav_bytes(
        bank,
        node_key,
        resolver=resolver,
        graph_index=graph_index,
        companion_cache=companion_cache,
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(wav_bytes)
    return destination


def export_nodes_to_directory(
    bank: SoundBank,
    node_keys: Sequence[str],
    output_dir: Path,
    resolver: AssetResolverPort | None = None,
    graph_index: BankGraphIndex | None = None,
    companion_cache: dict[int, SoundBank] | None = None,
) -> int:
    """
    Batch-exports multiple node keys to WAV files in a directory.

    Files are named by WEM ID or node key. Returns count of successfully exported files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    exported = 0

    for key in node_keys:
        try:
            wem_id, _ = _extract_wem_info_from_key(bank, key, graph_index)
            if wem_id is None or wem_id <= 0:
                logger.warning("Skipping node '%s': no audio source.", key)
                continue

            filename = f"{wem_id}.wav"
            dest = output_dir / filename
            export_node_to_wav(
                bank,
                key,
                dest,
                resolver=resolver,
                graph_index=graph_index,
                companion_cache=companion_cache,
            )
            exported += 1
        except (ValueError, FileNotFoundError, RuntimeError, OSError) as exc:
            logger.warning("Failed to export node '%s': %s", key, exc)

    return exported


def _extract_wem_info_from_key(
    bank: SoundBank,
    node_key: str,
    graph_index: BankGraphIndex | None = None,
) -> tuple[int | None, int]:
    """Extracts (wem_id, companion_bank_id) from a node key string."""
    if node_key.startswith("media:"):
        try:
            parts = node_key.split(":")
            return int(parts[-1]), 0
        except (ValueError, IndexError):
            return None, 0

    if node_key.startswith("hirc:"):
        try:
            hid = int(node_key.split(":")[1])
        except (ValueError, IndexError):
            return None, 0

        obj = None
        if graph_index is not None:
            obj = graph_index.objects_by_id.get(hid)
        elif bank.hirc is not None:
            for candidate in bank.hirc.objects:
                if candidate.id == hid:
                    obj = candidate
                    break

        if isinstance(obj, CAkSound):
            source_id = getattr(obj, "source_id", 0)
            file_id = getattr(obj, "file_id", 0)
            cur_bank_id = getattr(bank.header, "bank_id", 0) if bank.header else 0
            comp_bank_id = file_id if file_id and file_id != cur_bank_id else 0
            wid = source_id or file_id
            return (wid if wid else None), comp_bank_id
        elif isinstance(obj, CAkMusicTrack):
            if hasattr(obj, "sources") and obj.sources:
                src = obj.sources[0]
                wid = getattr(src, "source_id", 0) or getattr(src, "file_id", 0)
                return (wid if wid else None), 0

    return None, 0


def _extract_wem_id_from_key(
    bank: SoundBank,
    node_key: str,
    graph_index: BankGraphIndex | None = None,
) -> int | None:
    """Extracts the WEM/source audio ID from a node key string."""
    wid, _ = _extract_wem_info_from_key(bank, node_key, graph_index)
    return wid
