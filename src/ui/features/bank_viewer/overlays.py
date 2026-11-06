"""Headless registry and resolution helpers for hierarchy tree overlays.

Provides pure overlay specifications and text/provenance formatting helpers
for the SoundBank Viewer with zero Qt dependencies.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from src.engine.metadata_fields import Provenance

if TYPE_CHECKING:
    from src.ui.features.bank_viewer.state import HircTreeNode


class TreeOverlay(StrEnum):
    """Hierarchy tree overlay identifiers."""

    GAME_NAMES = "game_names"
    HIGHLIGHT_MODIFIED = "highlight_modified"
    MODIFIED_TAG = "modified_tag"


@dataclass(frozen=True, slots=True, kw_only=True)
class OverlaySpec:
    """Specification describing an interactive hierarchy tree overlay."""

    id: TreeOverlay
    label: str
    description: str
    default_enabled: bool = True


OVERLAY_SPECS: tuple[OverlaySpec, ...] = (
    OverlaySpec(
        id=TreeOverlay.GAME_NAMES,
        label="Game Names",
        description="Show resolved Total War event, switch, and entity names instead of raw Wwise labels",
    ),
    OverlaySpec(
        id=TreeOverlay.HIGHLIGHT_MODIFIED,
        label="Highlight Modified",
        description="Color modified nodes and their ancestor containers",
    ),
    OverlaySpec(
        id=TreeOverlay.MODIFIED_TAG,
        label="Modified [MOD] Tag",
        description="Prefix modified nodes' Details cell with [MOD]",
    ),
)

OVERLAY_SPECS_BY_ID: Mapping[TreeOverlay, OverlaySpec] = MappingProxyType(
    {s.id: s for s in OVERLAY_SPECS}
)

DEFAULT_ACTIVE_OVERLAYS: frozenset[TreeOverlay] = frozenset(
    s.id for s in OVERLAY_SPECS if s.default_enabled
)


def resolve_node_label(node: HircTreeNode, overlays: frozenset[TreeOverlay]) -> str:
    """Resolves primary display label for a tree node based on active overlays."""
    if TreeOverlay.GAME_NAMES in overlays:
        return node.friendly_label or node.label
    return node.label


def resolve_node_details(
    node: HircTreeNode, overlays: frozenset[TreeOverlay]
) -> tuple[str, Provenance]:
    """Resolves details string and provenance for a tree node based on active overlays."""
    if TreeOverlay.GAME_NAMES in overlays and node.friendly_details:
        base = node.friendly_details
        prov = node.friendly_details_provenance
    else:
        base = node.details
        prov = Provenance.BINARY

    if TreeOverlay.MODIFIED_TAG in overlays and node.is_modified:
        text = f"[MOD] {base}" if base else "[MOD]"
    else:
        text = base

    return text, prov
