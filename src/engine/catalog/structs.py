"""
Pure immutable data ontology and algebraic state definitions for audio catalog discovery and filtering.
Strictly follows the 5 Laws of Data Design with zero Qt imports or mutable state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from src.models import AudioCatalogEntry

# -----------------------------------------------------------------------------
# 1. Enums and Primitives
# -----------------------------------------------------------------------------


class CatalogScope(Enum):
    """Scope of catalog discovery to perform."""

    LOCAL_BANK_ONLY = auto()  # Embedded DIDX + HIRC of active bank (<1ms)
    FULL_LIBRARY = auto()  # Local + Project Overlay + Cached Loose WEMs


class CatalogScopeFilter(Enum):
    """Predefined scope filter labels available in the replacer UI."""

    ALL = "All Categories"
    THIS_BANK = "This Bank"
    OTHER_BANKS = "Other Banks"


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogFilterSpec:
    """Filter parameters applied to catalog entries."""

    query: str = ""
    scope_or_category: str = "All Categories"
    current_bank_name: str = ""


# -----------------------------------------------------------------------------
# 2. Algebraic State Machine (Lifecycle Sum Types)
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogUnloaded:
    """Initial state: global catalog has not been requested."""

    local_entries: tuple[AudioCatalogEntry, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogLoading:
    """Global catalog discovery is in progress."""

    local_entries: tuple[AudioCatalogEntry, ...] = field(default_factory=tuple)
    scope: CatalogScope = CatalogScope.FULL_LIBRARY


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogLoaded:
    """Catalog is loaded and ready for queries."""

    all_entries: tuple[AudioCatalogEntry, ...]
    filtered_entries: tuple[AudioCatalogEntry, ...]
    categories: tuple[str, ...]
    filter_spec: CatalogFilterSpec = field(default_factory=CatalogFilterSpec)


@dataclass(frozen=True, slots=True, kw_only=True)
class CatalogError:
    """Catalog discovery encountered an error."""

    error_message: str
    local_entries: tuple[AudioCatalogEntry, ...] = field(default_factory=tuple)


type CatalogState = CatalogUnloaded | CatalogLoading | CatalogLoaded | CatalogError


# -----------------------------------------------------------------------------
# 3. Events & Commands
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class RequestLibraryLoadEvent:
    """User requested switching to library view."""

    scope: CatalogScope = CatalogScope.FULL_LIBRARY


@dataclass(frozen=True, slots=True, kw_only=True)
class LibraryLoadedEvent:
    """Discovery completed with raw entries."""

    entries: tuple[AudioCatalogEntry, ...]
    current_bank_name: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class FilterChangedEvent:
    """Search or category filter updated."""

    filter_spec: CatalogFilterSpec


@dataclass(frozen=True, slots=True, kw_only=True)
class LibraryLoadFailedEvent:
    """Discovery failed."""

    error_message: str


type CatalogEvent = (
    RequestLibraryLoadEvent | LibraryLoadedEvent | FilterChangedEvent | LibraryLoadFailedEvent
)


# -----------------------------------------------------------------------------
# 4. Effect Intents
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class LoadFullLibraryIntent:
    """Intent for Imperative Shell to fetch full library entries (cached/async)."""

    current_bank_name: str


type CatalogEffectIntent = LoadFullLibraryIntent
