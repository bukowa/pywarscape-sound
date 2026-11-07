"""
Engine capability matrix and SoundBank category classification.
Provides pure querying of supported modder operations per HIRC node type and bank taxonomy.
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True, kw_only=True)
class ActionCapability:
    """Capability specification for a single action on a node type."""

    action: str
    status: Literal["supported", "disabled"]
    reason: str = ""

    @property
    def is_supported(self) -> bool:
        return self.status == "supported"


@dataclass(frozen=True, slots=True, kw_only=True)
class NodeCapabilities:
    """Capabilities across all actions for a specific HIRC node type."""

    node_type: str
    actions: tuple[ActionCapability, ...]

    def get(self, action: str) -> ActionCapability:
        for a in self.actions:
            if a.action == action:
                return a
        return ActionCapability(
            action=action,
            status="disabled",
            reason=f"Action '{action}' is not defined for node type '{self.node_type}'.",
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class BankGroupSpec:
    """Specification of a high-level SoundBank classification group."""

    id: str
    label: str
    collapsed_by_default: bool
    sub_groups: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityMatrix:
    """Complete capability contract across all node types and bank groups."""

    actions: tuple[str, ...]
    node_capabilities: tuple[NodeCapabilities, ...]
    bank_groups: tuple[BankGroupSpec, ...]


@functools.cache
def get_capability_matrix() -> CapabilityMatrix:
    """Loads and returns the cached CapabilityMatrix parsed from capability_matrix.json."""
    matrix_path = Path(__file__).parent / "capability_matrix.json"
    with open(matrix_path, encoding="utf-8") as f:
        data = json.load(f)

    actions = tuple(data["actions"])

    node_caps_list: list[NodeCapabilities] = []
    for node_type, action_map in data["node_types"].items():
        action_caps = tuple(
            ActionCapability(
                action=act,
                status=action_map[act]["status"],
                reason=action_map[act]["reason"],
            )
            for act in actions
            if act in action_map
        )
        node_caps_list.append(NodeCapabilities(node_type=node_type, actions=action_caps))

    bank_groups = tuple(
        BankGroupSpec(
            id=bg["id"],
            label=bg["label"],
            collapsed_by_default=bg["collapsed_by_default"],
            sub_groups=tuple(bg.get("sub_groups", ())),
        )
        for bg in data["bank_groups"]
    )

    return CapabilityMatrix(
        actions=actions,
        node_capabilities=tuple(node_caps_list),
        bank_groups=bank_groups,
    )


def capabilities_for_node(node_type: str) -> NodeCapabilities:
    """Returns the NodeCapabilities for the requested node type, or disabled fallback if unknown."""
    matrix = get_capability_matrix()
    for nc in matrix.node_capabilities:
        if nc.node_type == node_type:
            return nc
    fallback_actions = tuple(
        ActionCapability(
            action=action,
            status="disabled",
            reason=f"Node type '{node_type}' is unknown or not supported.",
        )
        for action in matrix.actions
    )
    return NodeCapabilities(node_type=node_type, actions=fallback_actions)


def query_capability(node_type: str, action: str) -> ActionCapability:
    """Queries capability status and reason for a specific node type and action."""
    return capabilities_for_node(node_type).get(action)


def classify_bank_group(
    bank_name: str, *, has_hirc: bool = True, has_didx: bool = False
) -> tuple[str, str | None]:
    """
    Classifies a SoundBank into one of six standard bank groups and an optional subgroup.

    Categories:
    - "Music & Movies"
    - "Campaign & UI"
    - "Battle SFX & Environment"
    - "Battle Voice Orders" (with subgroups: "Barbarian", "Eastern", "Nomad", "Roman")
    - "Raw Audio Data Banks"
    - "System & Empty Stubs"
    """
    clean = Path(bank_name).stem.lower()

    # 1. System & Empty Stubs (exact bank stubs and bus/init system banks)
    if clean in ("init", "global_bus", "battle_music", "frontend_data"):
        return ("System & Empty Stubs", None)
    if not has_hirc and not has_didx:
        return ("System & Empty Stubs", None)

    # 2. Raw Audio Data Banks (DIDX + DATA payload containers)
    if clean.endswith("_data"):
        return ("Raw Audio Data Banks", None)
    if has_didx and not has_hirc:
        return ("Raw Audio Data Banks", None)

    # 3. Music & Movies
    if clean.startswith(("global_music", "global_movies")):
        return ("Music & Movies", None)

    # 4. Battle Voice Orders
    if clean.startswith("battle_vo_orders"):
        rest = clean[len("battle_vo_orders") :].strip("_")
        if rest.startswith("barbarian"):
            return ("Battle Voice Orders", "Barbarian")
        if rest.startswith("eastern"):
            return ("Battle Voice Orders", "Eastern")
        if rest.startswith("nomad"):
            return ("Battle Voice Orders", "Nomad")
        if rest.startswith("roman"):
            return ("Battle Voice Orders", "Roman")
        return ("Battle Voice Orders", None)

    # 5. Campaign & UI
    if clean.startswith(("campaign", "frontend")) or clean in (
        "global",
        "global_prologue",
        "global_ui",
    ):
        return ("Campaign & UI", None)

    # 6. Battle SFX & Environment
    if clean.startswith("battle"):
        return ("Battle SFX & Environment", None)

    # Fallback heuristic if unknown bank name is provided
    return ("Campaign & UI", None)
