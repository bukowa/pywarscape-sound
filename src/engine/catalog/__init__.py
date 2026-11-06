"""Audio catalog discovery, caching, and virtual projection slice."""

from src.engine.catalog.causation import (
    evolve_catalog_state,
    extract_catalog_categories,
    filter_catalog_entries,
)
from src.engine.catalog.structs import (
    CatalogError,
    CatalogEvent,
    CatalogFilterSpec,
    CatalogLoaded,
    CatalogLoading,
    CatalogScope,
    CatalogScopeFilter,
    CatalogState,
    CatalogUnloaded,
    FilterChangedEvent,
    LibraryLoadedEvent,
    LibraryLoadFailedEvent,
    LoadFullLibraryIntent,
    RequestLibraryLoadEvent,
)

__all__ = [
    "CatalogError",
    "CatalogEvent",
    "CatalogFilterSpec",
    "CatalogLoaded",
    "CatalogLoading",
    "CatalogScope",
    "CatalogScopeFilter",
    "CatalogState",
    "CatalogUnloaded",
    "FilterChangedEvent",
    "LibraryLoadFailedEvent",
    "LibraryLoadedEvent",
    "LoadFullLibraryIntent",
    "RequestLibraryLoadEvent",
    "evolve_catalog_state",
    "extract_catalog_categories",
    "filter_catalog_entries",
]
