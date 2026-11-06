"""Headless column definitions and cell extractors for hierarchy tree columns.

Defines customizable columns, widths, searchability, and pure cell extractors
for the SoundBank Viewer hierarchy tree with zero Qt dependencies.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from src.engine.metadata_fields import MetadataField, Provenance
from src.ui.columns import (
    format_channel_label,
    format_duration_ms,
    format_sample_rate_khz,
)
from src.ui.features.bank_viewer.overlays import (
    TreeOverlay,
    resolve_node_details,
    resolve_node_label,
)

if TYPE_CHECKING:
    from src.ui.features.bank_viewer.state import HircTreeNode


class TreeColumn(StrEnum):
    """Hierarchy tree column identifiers."""

    NAME = "name"
    ID = "id"
    TYPE = "type"
    DURATION = "duration"
    FORMAT = "format"
    VARIATION_PCT = "variation_pct"
    PLAYBACK_RULE = "playback_rule"
    DETAILS = "details"


class HighlightScope(StrEnum):
    """Visual scope for modification highlighting on columns."""

    NONE = "none"
    SELF_ONLY = "self_only"
    SELF_OR_DESCENDANT = "self_or_descendant"


@dataclass(frozen=True, slots=True, kw_only=True)
class ColumnSpec:
    """Specification describing a configurable hierarchy tree column."""

    id: TreeColumn
    header: str
    default_visible: bool
    hideable: bool
    default_width: int
    searchable: bool
    highlight_scope: HighlightScope
    cell: Callable[[HircTreeNode, HircTreeNode | None, frozenset[TreeOverlay]], str]
    cell_provenance: Callable[
        [HircTreeNode, HircTreeNode | None, frozenset[TreeOverlay]], Provenance
    ]


def _cell_duration(
    node: HircTreeNode,
    parent_node: HircTreeNode | None,
    overlays: frozenset[TreeOverlay],
) -> str:
    mv = node.metadata.get(MetadataField.DURATION_MS)
    if mv is not None and isinstance(mv.value, (int, float)):
        return format_duration_ms(float(mv.value))
    return ""


def _cell_format(
    node: HircTreeNode,
    parent_node: HircTreeNode | None,
    overlays: frozenset[TreeOverlay],
) -> str:
    parts: list[str] = []
    codec_mv = node.metadata.get(MetadataField.CODEC)
    if codec_mv is not None and str(codec_mv.value):
        parts.append(str(codec_mv.value))

    sr_mv = node.metadata.get(MetadataField.SAMPLE_RATE)
    if sr_mv is not None and isinstance(sr_mv.value, int):
        sr_lbl = format_sample_rate_khz(sr_mv.value)
        if sr_lbl:
            parts.append(sr_lbl)

    ch_mv = node.metadata.get(MetadataField.CHANNELS)
    if ch_mv is not None and isinstance(ch_mv.value, int):
        ch_lbl = format_channel_label(ch_mv.value)
        if ch_lbl:
            parts.append(ch_lbl)

    return " ".join(parts)


def _cell_variation_pct(
    node: HircTreeNode,
    parent_node: HircTreeNode | None,
    overlays: frozenset[TreeOverlay],
) -> str:
    if parent_node is None:
        return ""
    mv = parent_node.metadata.get(MetadataField.PLAYLIST_WEIGHTS)
    if mv is not None and isinstance(mv.value, tuple):
        for ckey, pct in mv.value:
            if ckey == node.key and isinstance(pct, (int, float)):
                return f"{pct:.1f}%"
    return ""


def _cell_playback_rule(
    node: HircTreeNode,
    parent_node: HircTreeNode | None,
    overlays: frozenset[TreeOverlay],
) -> str:
    mode_mv = node.metadata.get(MetadataField.PLAYBACK_MODE)
    if mode_mv is None:
        return ""
    mode_str = str(mode_mv.value)
    ar_mv = node.metadata.get(MetadataField.AVOID_REPEAT)
    if (
        mode_str in ("Random", "Shuffle")
        and ar_mv is not None
        and isinstance(ar_mv.value, int)
        and ar_mv.value > 0
    ):
        return f"{mode_str} (no-repeat {ar_mv.value})"
    return mode_str


COLUMN_SPECS: tuple[ColumnSpec, ...] = (
    ColumnSpec(
        id=TreeColumn.NAME,
        header="Hierarchy Tree",
        default_visible=True,
        hideable=False,
        default_width=260,
        searchable=True,
        highlight_scope=HighlightScope.SELF_OR_DESCENDANT,
        cell=lambda node, _parent, overlays: resolve_node_label(node, overlays),
        cell_provenance=lambda _node, _parent, _overlays: Provenance.BINARY,
    ),
    ColumnSpec(
        id=TreeColumn.ID,
        header="ID",
        default_visible=True,
        hideable=True,
        default_width=95,
        searchable=True,
        highlight_scope=HighlightScope.NONE,
        cell=lambda node, _parent, _overlays: node.id_str,
        cell_provenance=lambda _node, _parent, _overlays: Provenance.BINARY,
    ),
    ColumnSpec(
        id=TreeColumn.TYPE,
        header="Type",
        default_visible=True,
        hideable=True,
        default_width=110,
        searchable=True,
        highlight_scope=HighlightScope.SELF_OR_DESCENDANT,
        cell=lambda node, _parent, _overlays: node.type_str,
        cell_provenance=lambda _node, _parent, _overlays: Provenance.BINARY,
    ),
    ColumnSpec(
        id=TreeColumn.DURATION,
        header="Duration",
        default_visible=False,
        hideable=True,
        default_width=85,
        searchable=True,
        highlight_scope=HighlightScope.SELF_ONLY,
        cell=_cell_duration,
        cell_provenance=lambda _node, _parent, _overlays: Provenance.BINARY,
    ),
    ColumnSpec(
        id=TreeColumn.FORMAT,
        header="Format",
        default_visible=False,
        hideable=True,
        default_width=145,
        searchable=True,
        highlight_scope=HighlightScope.SELF_ONLY,
        cell=_cell_format,
        cell_provenance=lambda _node, _parent, _overlays: Provenance.BINARY,
    ),
    ColumnSpec(
        id=TreeColumn.VARIATION_PCT,
        header="Variation %",
        default_visible=False,
        hideable=True,
        default_width=90,
        searchable=True,
        highlight_scope=HighlightScope.SELF_ONLY,
        cell=_cell_variation_pct,
        cell_provenance=lambda _node, _parent, _overlays: Provenance.BINARY,
    ),
    ColumnSpec(
        id=TreeColumn.PLAYBACK_RULE,
        header="Playback Rule",
        default_visible=False,
        hideable=True,
        default_width=150,
        searchable=True,
        highlight_scope=HighlightScope.SELF_ONLY,
        cell=_cell_playback_rule,
        cell_provenance=lambda _node, _parent, _overlays: Provenance.BINARY,
    ),
    ColumnSpec(
        id=TreeColumn.DETAILS,
        header="Details",
        default_visible=True,
        hideable=True,
        default_width=200,
        searchable=True,
        highlight_scope=HighlightScope.SELF_ONLY,
        cell=lambda node, _parent, overlays: resolve_node_details(node, overlays)[0],
        cell_provenance=lambda node, _parent, overlays: resolve_node_details(node, overlays)[1],
    ),
)

COLUMN_SPECS_BY_ID: Mapping[TreeColumn, ColumnSpec] = MappingProxyType(
    {s.id: s for s in COLUMN_SPECS}
)

DEFAULT_VISIBLE_COLUMNS: tuple[TreeColumn, ...] = tuple(
    s.id for s in COLUMN_SPECS if s.default_visible
)


def toggle_visible_columns(
    current: tuple[TreeColumn, ...],
    column: TreeColumn,
    visible: bool,
) -> tuple[TreeColumn, ...]:
    """Pure helper returning a new visible columns tuple preserving canonical order."""
    spec = COLUMN_SPECS_BY_ID.get(column)
    if spec is None or (not visible and not spec.hideable):
        return current
    target_set = (set(current) | {column}) if visible else (set(current) - {column})
    target_set.add(TreeColumn.NAME)
    return tuple(s.id for s in COLUMN_SPECS if s.id in target_set)


WEM_HEADER_COLUMNS: frozenset[TreeColumn] = frozenset({TreeColumn.DURATION, TreeColumn.FORMAT})


def requires_wem_metadata(columns: Sequence[TreeColumn]) -> bool:
    """Returns True if any visible column requires lazy WEM audio stream header metadata."""
    return any(c in WEM_HEADER_COLUMNS for c in columns)
