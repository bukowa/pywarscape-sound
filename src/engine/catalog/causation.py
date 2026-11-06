"""
Pure Functional Core for Audio Catalog Discovery and Filtering.

Part of Phase 3 (/causation) in the Spec-Driven Functional Pipeline.
Contains pure deterministic decision logic and state transitions.
ZERO Qt imports, ZERO I/O, ZERO mutable state, ZERO side effects, ZERO logging.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum

from src.engine.catalog.structs import (
    CatalogEffectIntent,
    CatalogError,
    CatalogEvent,
    CatalogFilterSpec,
    CatalogLoaded,
    CatalogLoading,
    CatalogState,
    CatalogUnloaded,
    FilterChangedEvent,
    LibraryLoadedEvent,
    LibraryLoadFailedEvent,
    LoadFullLibraryIntent,
    RequestLibraryLoadEvent,
)
from src.models import AudioCatalogEntry

_EXCLUDED_CATEGORIES: frozenset[str] = frozenset(
    {
        "all categories",
        "this bank",
        "other banks",
        "general",
    }
)


def _entry_matches_filter(
    entry: AudioCatalogEntry,
    filter_spec: CatalogFilterSpec,
) -> bool:
    """Checks if an audio catalog entry satisfies both text search and scope filters."""
    # 1. Text search matching
    query = (filter_spec.query or "").strip().lower()
    if query:
        text_match = (
            query in (entry.display_name or "").lower()
            or query in (entry.source_bank or "").lower()
            or query in str(entry.wem_id)
            or any(query in (tag or "").lower() for tag in (entry.metadata_tags or ()))
        )
        if not text_match:
            return False

    # 2. Scope filter matching
    raw_scope = filter_spec.scope_or_category
    scope_str = raw_scope.value if isinstance(raw_scope, Enum) else str(raw_scope)
    scope_key = scope_str.strip().lower()

    if scope_key in ("all categories", ""):
        return True

    if scope_key == "this bank":
        cur_bank = (filter_spec.current_bank_name or "").strip().lower()
        return (entry.source_bank or "").strip().lower() == cur_bank

    if scope_key == "other banks":
        cur_bank = (filter_spec.current_bank_name or "").strip().lower()
        return (entry.source_bank or "").strip().lower() != cur_bank

    return (entry.category or "").strip().lower() == scope_key


def filter_catalog_entries(
    entries: tuple[AudioCatalogEntry, ...] | Sequence[AudioCatalogEntry],
    filter_spec: CatalogFilterSpec,
) -> tuple[AudioCatalogEntry, ...]:
    """Pure deterministic filter matching entries against text query and category/bank scope."""
    return tuple(entry for entry in entries if _entry_matches_filter(entry, filter_spec))


def extract_catalog_categories(
    entries: tuple[AudioCatalogEntry, ...] | Sequence[AudioCatalogEntry],
) -> tuple[str, ...]:
    """Discovers sorted unique non-default category names from catalog entries."""
    unique_categories = {
        entry.category.strip()
        for entry in entries
        if entry.category
        and entry.category.strip()
        and entry.category.strip().lower() not in _EXCLUDED_CATEGORIES
    }
    return tuple(sorted(unique_categories))


def evolve_catalog_state(
    state: CatalogState,
    event: CatalogEvent,
) -> tuple[CatalogState, tuple[CatalogEffectIntent, ...]]:
    """Pure state machine transition handling catalog lifecycle and filtering."""
    match (state, event):
        case (CatalogUnloaded(local_entries=local_entries), RequestLibraryLoadEvent(scope=scope)):
            return (
                CatalogLoading(
                    scope=scope,
                    local_entries=local_entries,
                ),
                (LoadFullLibraryIntent(current_bank_name=""),),
            )

        case (CatalogLoading(), LibraryLoadedEvent(entries=entries, current_bank_name=bank_name)):
            all_entries = tuple(entries) if not isinstance(entries, tuple) else entries
            filter_spec = CatalogFilterSpec(current_bank_name=bank_name)
            categories = extract_catalog_categories(all_entries)
            filtered = filter_catalog_entries(all_entries, filter_spec)
            return (
                CatalogLoaded(
                    all_entries=all_entries,
                    filtered_entries=filtered,
                    categories=categories,
                    filter_spec=filter_spec,
                ),
                (),
            )

        case (
            CatalogLoaded(all_entries=all_entries, categories=categories),
            FilterChangedEvent(filter_spec=filter_spec),
        ):
            filtered = filter_catalog_entries(all_entries, filter_spec)
            return (
                CatalogLoaded(
                    all_entries=all_entries,
                    filtered_entries=filtered,
                    categories=categories,
                    filter_spec=filter_spec,
                ),
                (),
            )

        case (
            CatalogLoading(local_entries=local_entries),
            LibraryLoadFailedEvent(error_message=error_msg),
        ):
            return (
                CatalogError(
                    error_message=error_msg,
                    local_entries=local_entries,
                ),
                (),
            )

        case _:
            return state, ()
