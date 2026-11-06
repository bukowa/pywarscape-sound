"""Headless column definitions and cell extractors for the Game Audio catalog table.

Defines customizable columns, widths, searchability, and pure cell extractors
for AudioCatalogEntry rows with zero Qt dependencies.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from src.engine.metadata_fields import Provenance
from src.ui.columns import TableColumnSpec, format_duration_ms

if TYPE_CHECKING:
    from src.models import AudioCatalogEntry


class CatalogColumn(StrEnum):
    """Game Audio catalog column identifiers."""

    NAME = "name"
    SOURCE_BANK = "source_bank"
    MEDIA_ID = "media_id"
    TYPE = "type"
    DURATION = "duration"
    CATEGORY = "category"


type CatalogColumnSpec = TableColumnSpec[CatalogColumn, AudioCatalogEntry]

CATALOG_COLUMN_SPECS: tuple[CatalogColumnSpec, ...] = (
    TableColumnSpec(
        id=CatalogColumn.NAME,
        header="Name / Label",
        default_visible=True,
        hideable=False,
        default_width=240,
        searchable=True,
        cell=lambda e: e.display_name,
        sort_key=lambda e: e.display_name.lower(),
    ),
    TableColumnSpec(
        id=CatalogColumn.SOURCE_BANK,
        header="Source Bank",
        default_visible=True,
        hideable=True,
        default_width=160,
        searchable=True,
        cell=lambda e: e.source_bank,
        sort_key=lambda e: e.source_bank.lower(),
    ),
    TableColumnSpec(
        id=CatalogColumn.MEDIA_ID,
        header="Media ID",
        default_visible=True,
        hideable=True,
        default_width=90,
        searchable=True,
        cell=lambda e: str(e.wem_id),
        sort_key=lambda e: e.wem_id,
    ),
    TableColumnSpec(
        id=CatalogColumn.TYPE,
        header="Type",
        default_visible=True,
        hideable=True,
        default_width=90,
        searchable=False,
        cell=lambda e: "Embedded" if e.is_embedded else "Streamed",
        sort_key=lambda e: 1 if e.is_embedded else 0,
    ),
    TableColumnSpec(
        id=CatalogColumn.DURATION,
        header="Duration",
        default_visible=False,
        hideable=True,
        default_width=85,
        searchable=False,
        cell=lambda e: format_duration_ms(e.duration_ms) if e.duration_ms > 0 else "",
        sort_key=lambda e: e.duration_ms,
    ),
    TableColumnSpec(
        id=CatalogColumn.CATEGORY,
        header="Category",
        default_visible=False,
        hideable=True,
        default_width=110,
        searchable=True,
        cell=lambda e: e.category,
        cell_provenance=lambda _e: Provenance.HEURISTIC,
        sort_key=lambda e: e.category.lower(),
    ),
)

CATALOG_COLUMN_SPECS_BY_ID: Mapping[CatalogColumn, CatalogColumnSpec] = MappingProxyType(
    {spec.id: spec for spec in CATALOG_COLUMN_SPECS}
)

DEFAULT_VISIBLE_CATALOG_COLUMNS: tuple[CatalogColumn, ...] = tuple(
    spec.id for spec in CATALOG_COLUMN_SPECS if spec.default_visible
)


def toggle_visible_catalog_columns(
    current: tuple[CatalogColumn, ...], column: CatalogColumn, visible: bool
) -> tuple[CatalogColumn, ...]:
    """Pure helper returning tuple preserving canonical CATALOG_COLUMN_SPECS order, keeping non-hideable columns visible."""
    spec = CATALOG_COLUMN_SPECS_BY_ID.get(column)
    if spec is not None and not spec.hideable:
        visible = True
    current_set = set(current)
    if visible:
        current_set.add(column)
    else:
        current_set.discard(column)
    current_set |= {s.id for s in CATALOG_COLUMN_SPECS if not s.hideable}
    return tuple(s.id for s in CATALOG_COLUMN_SPECS if s.id in current_set)
