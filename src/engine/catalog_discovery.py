"""
Catalog Discovery Service for SoundBanks and Workspace Projects.

Discovers, enriches, and indexes available audio assets (embedded in DATA chunks,
streamed loose .wem files, and cross-bank assets) into a unified catalog for the
Smart Audio Replacer and mutation pipelines.
"""

from __future__ import annotations

from typing import Any

from src.bnk.bank import SoundBank
from src.bnk.models import CAkMusicTrack, CAkSound
from src.engine.catalog.structs import CatalogScope
from src.engine.graph import resolve_hash_name
from src.engine.ports import AudioProjectPort
from src.models import AudioCatalogEntry


def _categorize_bank(bank_name: str) -> str:
    """Infers high-level audio category from SoundBank filename."""
    lower = bank_name.lower()
    if any(k in lower for k in ("music", "theme", "mx_")):
        return "Music"
    if any(k in lower for k in ("vo_", "speech", "dialogue", "voice", "advisor", "general")):
        return "Voiceover"
    if any(k in lower for k in ("ui_", "frontend", "interface", "click")):
        return "UI"
    if any(
        k in lower
        for k in ("battle", "war", "weapon", "combat", "siege", "blood", "missile", "arrow")
    ):
        return "Battle"
    if any(k in lower for k in ("ambient", "env_", "weather", "water", "wind")):
        return "Environment"
    return "General"


def _discover_bank_embedded(
    bank: SoundBank,
    bank_name: str,
    seen: set[tuple[int, str]],
    entries: list[AudioCatalogEntry],
) -> None:
    """Discovers embedded media in current bank DIDX entries."""
    if bank.didx is not None and getattr(bank.didx, "entries", None):
        for entry in bank.didx.entries:
            wem_id = entry.file_id
            if wem_id <= 0:
                continue
            key = (wem_id, bank_name)
            if key not in seen:
                seen.add(key)
                entries.append(
                    AudioCatalogEntry(
                        wem_id=wem_id,
                        source_bank=bank_name,
                        is_embedded=True,
                        display_name=f"WEM {wem_id}",
                        category=_categorize_bank(bank_name),
                    )
                )


def _discover_bank_streamed(
    bank: SoundBank,
    bank_name: str,
    sound_db: Any | None,
    seen: set[tuple[int, str]],
    entries: list[AudioCatalogEntry],
) -> None:
    """Discovers streamed media referenced in current bank HIRC objects."""
    if bank.hirc is not None and getattr(bank.hirc, "objects", None):
        for obj in bank.hirc.objects:
            if isinstance(obj, CAkSound):
                wid = getattr(obj, "source_id", 0) or getattr(obj, "file_id", 0)
                is_streamed = getattr(obj, "stream_type", 2) == 2
                if wid > 0 and is_streamed:
                    key = (wid, bank_name)
                    if key not in seen:
                        seen.add(key)
                        resolved = resolve_hash_name(wid, bank, sound_db=sound_db)
                        display_name = resolved if resolved else f"WEM {wid}"
                        entries.append(
                            AudioCatalogEntry(
                                wem_id=wid,
                                source_bank=bank_name,
                                is_embedded=False,
                                display_name=display_name,
                                category=_categorize_bank(bank_name),
                            )
                        )
            elif isinstance(obj, CAkMusicTrack):
                sources = getattr(obj, "sources", [])
                if sources:
                    for src in sources:
                        wid = getattr(src, "source_id", 0) or getattr(src, "file_id", 0)
                        is_streamed = getattr(src, "stream_type", 2) == 2
                        if wid > 0 and is_streamed:
                            key = (wid, bank_name)
                            if key not in seen:
                                seen.add(key)
                                resolved = resolve_hash_name(wid, bank, sound_db=sound_db)
                                display_name = resolved if resolved else f"WEM {wid}"
                                entries.append(
                                    AudioCatalogEntry(
                                        wem_id=wid,
                                        source_bank=bank_name,
                                        is_embedded=False,
                                        display_name=display_name,
                                        category="Music",
                                    )
                                )
                else:
                    wid = getattr(obj, "source_id", 0) or getattr(obj, "file_id", 0)
                    if wid > 0:
                        key = (wid, bank_name)
                        if key not in seen:
                            seen.add(key)
                            resolved = resolve_hash_name(wid, bank, sound_db=sound_db)
                            display_name = resolved if resolved else f"WEM {wid}"
                            entries.append(
                                AudioCatalogEntry(
                                    wem_id=wid,
                                    source_bank=bank_name,
                                    is_embedded=False,
                                    display_name=display_name,
                                    category="Music",
                                )
                            )


def _discover_project_overlay(
    project: AudioProjectPort,
    bank: SoundBank,
    bank_name: str,
    sound_db: Any | None,
    seen: set[tuple[int, str]],
    entries: list[AudioCatalogEntry],
) -> None:
    """Discovers staged loose WEMs and other banks in project overlay pack_root/audio/."""
    audio_dir = getattr(project, "audio_dir", None)
    if audio_dir is None or not audio_dir.is_dir():
        return

    # Staged loose WEMs
    for p in sorted(audio_dir.glob("*.wem")):
        try:
            wid = int(p.stem)
            key = (wid, "Project (Loose)")
            if key not in seen:
                seen.add(key)
                resolved = resolve_hash_name(wid, bank, sound_db=sound_db)
                display_name = resolved if resolved else f"WEM {wid} (Staged)"
                entries.append(
                    AudioCatalogEntry(
                        wem_id=wid,
                        source_bank="Project (Loose)",
                        is_embedded=False,
                        display_name=display_name,
                        category="General",
                    )
                )
        except (ValueError, TypeError):
            continue

    # Other SoundBanks in project overlay
    for other_path in sorted(audio_dir.glob("*.bnk")):
        if other_path.name.lower() == bank_name.lower():
            continue
        try:
            other_bank = SoundBank.from_bytes(other_path.read_bytes())
            other_name = other_path.name

            # DIDX in other bank
            if other_bank.didx is not None and other_bank.didx.entries:
                for entry in other_bank.didx.entries:
                    wid = entry.file_id
                    if wid <= 0:
                        continue
                    key = (wid, other_name)
                    if key not in seen:
                        seen.add(key)
                        entries.append(
                            AudioCatalogEntry(
                                wem_id=wid,
                                source_bank=other_name,
                                is_embedded=True,
                                display_name=f"WEM {wid}",
                                category=_categorize_bank(other_name),
                            )
                        )

            # Streamed in other bank
            if other_bank.hirc is not None and other_bank.hirc.objects:
                for obj in other_bank.hirc.objects:
                    if isinstance(obj, CAkSound):
                        wid = getattr(obj, "source_id", 0) or getattr(obj, "file_id", 0)
                        if wid > 0 and getattr(obj, "stream_type", 2) == 2:
                            key = (wid, other_name)
                            if key not in seen:
                                seen.add(key)
                                resolved = resolve_hash_name(wid, other_bank, sound_db=sound_db)
                                display_name = resolved if resolved else f"WEM {wid}"
                                entries.append(
                                    AudioCatalogEntry(
                                        wem_id=wid,
                                        source_bank=other_name,
                                        is_embedded=False,
                                        display_name=display_name,
                                        category=_categorize_bank(other_name),
                                    )
                                )
        except (OSError, ValueError, KeyError, IndexError, RuntimeError):
            continue


def _discover_project_manifest_wems(
    project: AudioProjectPort,
    bank: SoundBank,
    sound_db: Any | None,
    seen: set[tuple[int, str]],
    entries: list[AudioCatalogEntry],
) -> None:
    """Discovers staged WEM IDs declared in project manifest."""
    manifest = getattr(project, "manifest", None)
    if manifest is None:
        return
    staged_wems = getattr(manifest, "staged_wems", None)
    if staged_wems:
        for wid in sorted(staged_wems):
            key = (wid, "Project (Staged)")
            if key not in seen:
                seen.add(key)
                resolved = resolve_hash_name(wid, bank, sound_db=sound_db)
                display_name = resolved if resolved else f"WEM {wid} (Staged)"
                entries.append(
                    AudioCatalogEntry(
                        wem_id=wid,
                        source_bank="Project (Staged)",
                        is_embedded=False,
                        display_name=display_name,
                        category="General",
                    )
                )


def _discover_game_cache_wems(
    project: AudioProjectPort,
    bank: SoundBank,
    sound_db: Any | None,
    seen: set[tuple[int, str]],
    entries: list[AudioCatalogEntry],
) -> None:
    """Discovers vanilla loose WEMs indexed in GameCache."""
    cache = getattr(project, "cache", None)
    if cache is None:
        return
    if hasattr(cache, "get_loose_wem_catalog"):
        try:
            for entry in cache.get_loose_wem_catalog(sound_db=sound_db):
                key = (entry.wem_id, entry.source_bank)
                if key not in seen:
                    seen.add(key)
                    entries.append(entry)
        except (OSError, ValueError, KeyError, IndexError, RuntimeError):
            pass
    elif hasattr(cache, "list_wems"):
        try:
            cached_wems = cache.list_wems()
            for wid in cached_wems:
                key = (wid, "Vanilla (Loose)")
                if key not in seen:
                    seen.add(key)
                    resolved = resolve_hash_name(wid, bank, sound_db=sound_db)
                    display_name = resolved if resolved else f"WEM {wid}"
                    entries.append(
                        AudioCatalogEntry(
                            wem_id=wid,
                            source_bank="Vanilla (Loose)",
                            is_embedded=False,
                            display_name=display_name,
                            category="General",
                        )
                    )
        except (OSError, ValueError, KeyError, IndexError, RuntimeError):
            pass


def build_audio_catalog_for_bank(
    bank: SoundBank,
    bank_name: str,
    project: AudioProjectPort | None = None,
    sound_db: Any | None = None,
    scope: CatalogScope = CatalogScope.FULL_LIBRARY,
) -> tuple[AudioCatalogEntry, ...]:
    """
    Scans a SoundBank and optional AudioProject environment to assemble a comprehensive
    catalog of reusable audio assets (embedded DIDX slices, streamed loose WEMs, and cross-bank media).

    Deduplicates entries by (wem_id, source_bank).
    """
    entries: list[AudioCatalogEntry] = []
    seen: set[tuple[int, str]] = set()

    _discover_bank_embedded(bank, bank_name, seen, entries)
    _discover_bank_streamed(bank, bank_name, sound_db, seen, entries)

    if scope == CatalogScope.LOCAL_BANK_ONLY or project is None:
        return tuple(entries)

    _discover_project_overlay(project, bank, bank_name, sound_db, seen, entries)
    _discover_project_manifest_wems(project, bank, sound_db, seen, entries)
    _discover_game_cache_wems(project, bank, sound_db, seen, entries)

    return tuple(entries)
