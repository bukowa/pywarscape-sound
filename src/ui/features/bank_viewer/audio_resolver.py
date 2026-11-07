"""
Resolves playable AudioTrack structures from SoundBank nodes and media items.

Part of the SoundBank Viewer and Audio Transport integration.
Pure headless domain resolver: ZERO Qt imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.bnk.bank import SoundBank, repair_extracted_bnk_bytes
from src.bnk.models import CAkMusicTrack, CAkSound, HircObject
from src.engine.ports import AssetResolverPort
from src.models import AudioCatalogEntry
from src.ui.features.audio_transport.structs import AudioSourceId, AudioTrack

if TYPE_CHECKING:
    from src.engine.graph import BankGraphIndex


def resolve_node_audio_track(
    bank: SoundBank,
    node_key: str,
    resolver: AssetResolverPort | None = None,
    graph_index: BankGraphIndex | None = None,
    companion_cache: dict[int, SoundBank] | None = None,
) -> AudioTrack | None:
    """Resolves an AudioTrack struct for playback if the node represents audio."""
    # 1. Media leaf: media:<id>, media:embedded:<id>, or media:streamed:<id>
    if node_key.startswith("media:"):
        try:
            parts = node_key.split(":")
            mid = int(parts[-1])
            # Project overlay staged loose WEMs always take priority over vanilla embedded data
            p = resolver.resolve_wem_path(mid) if resolver else None
            if p:
                return AudioTrack(
                    source_id=AudioSourceId(mid),
                    title=f"WEM {mid} (Streamed)",
                    file_path=str(p),
                )
            raw = _get_embedded_media_bytes(bank, mid)
            if raw:
                return AudioTrack(
                    source_id=AudioSourceId(mid),
                    title=f"WEM {mid} (Embedded)",
                    embedded_bytes=raw,
                )
        except (OSError, ValueError, KeyError, IndexError, RuntimeError):
            pass
        return None

    # 2. HIRC object: hirc:<id> or hirc:<id>:src:<idx>
    if node_key.startswith("hirc:"):
        try:
            parts = node_key.split(":")
            hid = int(parts[1])
            src_idx: int | None = int(parts[3]) if len(parts) >= 4 and parts[2] == "src" else None
            obj: HircObject | None = None
            if graph_index is not None:
                obj = graph_index.objects_by_id.get(hid)
            elif bank.hirc is not None:
                for candidate in bank.hirc.objects:
                    if candidate.id == hid:
                        obj = candidate
                        break

            if isinstance(obj, CAkSound):
                return _resolve_sound_object(
                    obj=obj,
                    current_bank=bank,
                    resolver=resolver,
                    companion_cache=companion_cache,
                )
            elif isinstance(obj, CAkMusicTrack):
                return _resolve_music_track_object(
                    obj=obj,
                    current_bank=bank,
                    resolver=resolver,
                    companion_cache=companion_cache,
                    source_index=src_idx,
                )
        except (OSError, ValueError, KeyError, IndexError, RuntimeError, AttributeError):
            pass
        return None

    return None


def _resolve_sound_object(
    obj: CAkSound,
    current_bank: SoundBank,
    resolver: AssetResolverPort | None,
    companion_cache: dict[int, SoundBank] | None,
) -> AudioTrack | None:
    """Resolves AudioTrack for a CAkSound object (streamed or embedded)."""
    wid = getattr(obj, "source_id", 0) or getattr(obj, "file_id", 0)
    is_streamed = getattr(obj, "stream_type", 2) == 2

    # Check project overlay first: staged replacements always override vanilla embedded audio
    if resolver is not None and (proj := getattr(resolver, "project", None)) is not None:
        if wid in getattr(proj.manifest, "staged_wems", ()):
            staged_path = resolver.resolve_wem_path(wid)
            if staged_path:
                return AudioTrack(
                    source_id=AudioSourceId(wid),
                    title=f"{obj.id} ({wid}.wem)",
                    file_path=str(staged_path),
                )

    # A. Streamed media
    if is_streamed:
        p = resolver.resolve_wem_path(wid) if resolver else None
        if p:
            return AudioTrack(
                source_id=AudioSourceId(wid),
                title=f"{obj.id} ({wid}.wem)",
                file_path=str(p),
            )

    # B. Embedded media: check current bank DATA chunk first
    raw = _get_embedded_media_bytes(current_bank, wid)
    if raw:
        return AudioTrack(
            source_id=AudioSourceId(wid),
            title=f"{obj.id} ({wid}.wem)",
            embedded_bytes=raw,
        )

    # C. Cross-bank embedded media in Companion Data Bank
    comp_bank_id = getattr(obj, "file_id", 0)
    cur_bank_id = getattr(current_bank.header, "bank_id", 0) if current_bank.header else 0
    if comp_bank_id and comp_bank_id != cur_bank_id and resolver is not None:
        comp_bank = _get_or_load_companion_bank(comp_bank_id, resolver, companion_cache)
        if comp_bank is not None:
            raw = _get_embedded_media_bytes(comp_bank, wid)
            if raw:
                return AudioTrack(
                    source_id=AudioSourceId(wid),
                    title=f"{obj.id} ({wid}.wem)",
                    embedded_bytes=raw,
                )

    # D. Fallback: loose .wem
    p = resolver.resolve_wem_path(wid) if resolver else None
    if p:
        return AudioTrack(
            source_id=AudioSourceId(wid),
            title=f"{obj.id} ({wid}.wem)",
            file_path=str(p),
        )
    return None


def _resolve_music_track_object(
    obj: CAkMusicTrack,
    current_bank: SoundBank,
    resolver: AssetResolverPort | None,
    companion_cache: dict[int, SoundBank] | None,
    source_index: int | None = None,
) -> AudioTrack | None:
    """Resolves AudioTrack for a CAkMusicTrack object or specific sub-track source."""
    if source_index is not None and 0 <= source_index < len(obj.sources):
        wid = obj.sources[source_index].source_id
        title = f"{obj.id} Sub-track {source_index + 1} ({wid}.wem)"
    else:
        wid = obj.sources[0].source_id if obj.sources else getattr(obj, "source_id", 0)
        title = f"{obj.id} ({wid}.wem)"

    if not wid:
        return None

    # Loose .wem lookup first for music tracks
    p = resolver.resolve_wem_path(wid) if resolver else None
    if p:
        return AudioTrack(
            source_id=AudioSourceId(wid),
            title=title,
            file_path=str(p),
        )

    # Check embedded in current bank
    raw = _get_embedded_media_bytes(current_bank, wid)
    if raw:
        return AudioTrack(
            source_id=AudioSourceId(wid),
            title=title,
            embedded_bytes=raw,
        )

    return None


def _get_or_load_companion_bank(
    bank_id: int,
    resolver: AssetResolverPort,
    cache: dict[int, SoundBank] | None = None,
) -> SoundBank | None:
    """Loads and caches companion SoundBank bytes for cross-bank media resolution."""
    if cache is not None and bank_id in cache:
        return cache[bank_id]
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


def _get_embedded_media_bytes(bank: SoundBank, media_id: int) -> bytes | None:
    """Retrieves raw byte slice for embedded media file from DATA chunk."""
    if not bank.didx or not bank.data:
        return None
    for entry in bank.didx.entries:
        if entry.file_id == media_id:
            return bank.data.data[entry.offset : entry.offset + entry.size]
    return None


def resolve_catalog_entry_audio_track(
    entry: AudioCatalogEntry,
    session: Any,
) -> AudioTrack | None:
    """Resolves an AudioTrack for audition playback from an AudioCatalogEntry."""
    mid = entry.wem_id
    resolver: AssetResolverPort | None = getattr(session, "resolver", None)

    # 1. Staged loose WEMs or streamed files on disk
    if resolver is not None:
        p = resolver.resolve_wem_path(mid)
        if p and p.is_file():
            return AudioTrack(
                source_id=AudioSourceId(mid),
                title=entry.display_name or f"WEM {mid} (Streamed)",
                file_path=str(p),
            )

    # 2. Embedded in SoundBank DATA chunk
    if entry.is_embedded and entry.source_bank:
        bank: SoundBank | None = None
        if hasattr(session, "get_loaded_bank"):
            bank = session.get_loaded_bank(entry.source_bank)
        if bank is None and resolver is not None:
            raw_bank = resolver.resolve_bank_bytes(entry.source_bank)
            if raw_bank:
                try:
                    repaired = repair_extracted_bnk_bytes(raw_bank)
                    bank = SoundBank.from_bytes(repaired)
                except (OSError, ValueError, KeyError, IndexError, RuntimeError):
                    pass
        if bank is not None:
            raw = _get_embedded_media_bytes(bank, mid)
            if raw:
                return AudioTrack(
                    source_id=AudioSourceId(mid),
                    title=entry.display_name or f"WEM {mid} (Embedded)",
                    embedded_bytes=raw,
                )

    # 3. Fallback to resolver byte stream
    if resolver is not None:
        raw = resolver.resolve_wem_bytes(mid)
        if raw:
            return AudioTrack(
                source_id=AudioSourceId(mid),
                title=entry.display_name or f"WEM {mid}",
                embedded_bytes=raw,
            )

    return None
