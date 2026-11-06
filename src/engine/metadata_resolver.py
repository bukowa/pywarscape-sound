"""
Extensible game metadata resolution pipeline for SoundBank AST and media nodes.

Provides a pluggable provider architecture (Layer 2) that enriches low-level
Wwise HIRC objects and embedded/streamed WEM media with human-readable game
names (units, events, projectiles, explosions, combat materials) from Total War
databases and event_data.dat with zero Qt dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from src.bnk.models import (
    CAkAction,
    CAkDialogueEvent,
    CAkEvent,
    CAkMusicTrack,
    CAkRanSeqCntr,
    CAkSound,
    CAkSwitchCntr,
    HircObject,
)
from src.engine.graph import BankGraphIndex, resolve_hash_name
from src.engine.metadata_fields import Provenance
from src.models.hashing import KNOWN_HASH_NAMES

if TYPE_CHECKING:
    from src.bnk.bank import SoundBank
    from src.models.catalog import AudioMetadataCatalog

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# 1. Domain Structs
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NodeMetadataInfo:
    """Rich domain metadata resolved for a bank tree node or media ID."""

    friendly_label: str | None = None
    category: str | None = None
    entity_names: tuple[str, ...] = ()
    friendly_details: str | None = None
    event_name: str | None = None
    provenance: Provenance = Provenance.DATABASE


@dataclass(slots=True)
class ResolutionContext:
    """Shared contextual state and lookup indices for metadata resolution."""

    bank_name: str = ""
    sound_db: Any | None = None
    catalog: AudioMetadataCatalog | None = None
    media_referencing_sounds: dict[int, list[int]] = field(default_factory=dict)
    event_names_by_object_id: dict[int, str] = field(default_factory=dict)


# -----------------------------------------------------------------------------
# 2. Provider Protocol
# -----------------------------------------------------------------------------


class NodeMetadataProvider(Protocol):
    """Protocol for pluggable node metadata enrichment providers."""

    def resolve_hirc(
        self,
        obj: HircObject,
        bank: SoundBank,
        graph_index: BankGraphIndex,
        ctx: ResolutionContext,
    ) -> NodeMetadataInfo | None:
        """Resolves rich domain metadata for a HIRC AST object."""
        ...

    def resolve_media(
        self,
        wem_id: int,
        bank: SoundBank,
        graph_index: BankGraphIndex,
        ctx: ResolutionContext,
    ) -> NodeMetadataInfo | None:
        """Resolves rich domain metadata for a loose or embedded WEM media ID."""
        ...


# -----------------------------------------------------------------------------
# 3. Built-in Providers
# -----------------------------------------------------------------------------


class SoundDatabaseProvider:
    """Resolves event names, switch groups, and states using SoundDatabase and known hashes."""

    def resolve_hirc(
        self,
        obj: HircObject,
        bank: SoundBank,
        graph_index: BankGraphIndex,
        ctx: ResolutionContext,
    ) -> NodeMetadataInfo | None:
        name: str | None = None
        category: str | None = None

        if isinstance(obj, CAkEvent):
            name = self._resolve_name(obj.id, bank, ctx.sound_db)
            category = "Event"
            if name:
                ctx.event_names_by_object_id[obj.id] = name
        elif isinstance(obj, CAkDialogueEvent):
            name = self._resolve_name(obj.id, bank, ctx.sound_db)
            category = "Dialogue"
        elif isinstance(obj, CAkSwitchCntr):
            sw_name = self._resolve_name(obj.group_id, bank, ctx.sound_db)
            if sw_name:
                name = f"Switch: {sw_name}"
            category = "Switch"
        elif isinstance(obj, CAkMusicTrack):
            wid = obj.sources[0].source_id if obj.sources else getattr(obj, "source_id", 0)
            if wid:
                resolved = self._resolve_name(wid, bank, ctx.sound_db)
                if resolved:
                    name = resolved
            category = "Music"

        if not name and not category:
            return None

        return NodeMetadataInfo(
            friendly_label=name,
            category=category,
            event_name=name if isinstance(obj, CAkEvent) else None,
        )

    def resolve_media(
        self,
        wem_id: int,
        bank: SoundBank,
        graph_index: BankGraphIndex,
        ctx: ResolutionContext,
    ) -> NodeMetadataInfo | None:
        resolved = self._resolve_name(wem_id, bank, ctx.sound_db)
        if resolved:
            return NodeMetadataInfo(
                friendly_label=resolved,
                category="Audio Media",
                friendly_details=f"WEM {wem_id} ({resolved})",
            )
        return None

    def _resolve_name(self, hash_id: int, bank: SoundBank, sound_db: Any | None) -> str | None:
        if not hash_id:
            return None
        if hash_id in KNOWN_HASH_NAMES:
            return KNOWN_HASH_NAMES[hash_id]
        if sound_db is not None and hasattr(sound_db, "resolve_hash"):
            try:
                res = sound_db.resolve_hash(hash_id)
                if res:
                    return str(res).strip()
            except (KeyError, IndexError, ValueError, AttributeError):
                pass
        if bank.stid is not None:
            st = bank.stid.bank_names.get(hash_id)
            if st:
                return st.strip()
        return None


def _collect_switch_context(
    node_id: int,
    graph_index: BankGraphIndex,
    bank: SoundBank,
    sound_db: Any | None,
) -> dict[str, str]:
    """Ascends parent_map to discover active switch choices governing this node branch."""
    switches: dict[str, str] = {}
    visited: set[int] = set()
    queue = [node_id]
    while queue:
        curr = queue.pop(0)
        if curr in visited:
            continue
        visited.add(curr)
        for p in graph_index.parent_map.get(curr, []):
            p_obj = graph_index.objects_by_id.get(p)
            if isinstance(p_obj, CAkSwitchCntr):
                grp_name = resolve_hash_name(p_obj.group_id, bank, sound_db=sound_db)
                if grp_name:
                    for sw_id, nids in p_obj.switch_map.items():
                        if curr in nids:
                            sw_name = resolve_hash_name(sw_id, bank, sound_db=sound_db)
                            if sw_name:
                                switches[grp_name] = sw_name
            if p not in visited:
                queue.append(p)
    return switches


class GameCatalogProvider:
    """Enriches events with Total War DB entities (units, projectiles, explosions, materials)."""

    def resolve_hirc(
        self,
        obj: HircObject,
        bank: SoundBank,
        graph_index: BankGraphIndex,
        ctx: ResolutionContext,
    ) -> NodeMetadataInfo | None:
        if not ctx.catalog:
            return None

        event_name = ctx.event_names_by_object_id.get(obj.id)
        if not event_name and isinstance(obj, CAkEvent):
            event_name = resolve_hash_name(obj.id, bank, sound_db=ctx.sound_db)

        if not event_name:
            # Check if object is a switch container with bound materials/units
            if isinstance(obj, CAkSwitchCntr) and obj.group_id:
                grp_name = resolve_hash_name(obj.group_id, bank, sound_db=ctx.sound_db)
                if grp_name:
                    mats = ctx.catalog.get_materials_for_switch_group(grp_name)
                    if mats:
                        mat_names = tuple(m.material_key for m in mats)
                        return NodeMetadataInfo(
                            category="Material SFX",
                            entity_names=mat_names,
                            friendly_details=f"{len(mat_names)} material{'s' if len(mat_names) != 1 else ''}",
                        )

            # Check if object is a RanSeqCntr targeted by a switch container route (e.g. selected_catafractarii)
            if isinstance(obj, CAkRanSeqCntr):
                sw_name = graph_index.resolve_label(obj, sound_db=ctx.sound_db)
                if sw_name and not sw_name.startswith("RanSeqCntr_"):
                    switches = _collect_switch_context(obj.id, graph_index, bank, ctx.sound_db)
                    b_name = (ctx.bank_name or "").lower()
                    used_bank_name_heuristic = False
                    culture = switches.get("VO_CULTURE")
                    if not culture:
                        for cand_cult in ("barbarian", "eastern", "roman", "nomad"):
                            if cand_cult in b_name:
                                culture = cand_cult
                                used_bank_name_heuristic = True
                                break

                    actor = (switches.get("VO_BATTLE_ACTOR") or "").lower()
                    if not actor:
                        if "_inf" in b_name:
                            actor = "inf"
                            used_bank_name_heuristic = True
                        elif "_mtd" in b_name or "_cav" in b_name:
                            actor = "mtd"
                            used_bank_name_heuristic = True
                        elif "_artillery" in b_name:
                            actor = "artillery"
                            used_bank_name_heuristic = True

                    allowed_cats = None
                    if actor.startswith("inf"):
                        allowed_cats = ("inf_melee", "inf_ranged")
                    elif actor.startswith("mtd") or actor.startswith("cav"):
                        allowed_cats = ("cavalry",)
                    elif actor.startswith("art"):
                        allowed_cats = ("artillery",)

                    units = ctx.catalog.get_units_for_order_switch(
                        sw_name,
                        voiceover_culture=culture,
                        allowed_categories=allowed_cats,
                    )
                    if units:
                        u_keys = tuple(u.key for u in units)
                        cats = sorted({u.category for u in units if u.category})
                        cats_str = f" · {', '.join(cats[:3])}" if cats else ""
                        return NodeMetadataInfo(
                            friendly_label=f"{sw_name} [Units]",
                            category="Units",
                            entity_names=u_keys,
                            friendly_details=f"{len(u_keys)} units{cats_str}",
                            provenance=(
                                Provenance.HEURISTIC
                                if used_bank_name_heuristic
                                else Provenance.DATABASE
                            ),
                        )
            return None

        # 1. Projectiles linked to event
        projectiles = ctx.catalog.get_projectiles_for_event(event_name)
        if projectiles:
            p_keys = tuple(p.key for p in projectiles)
            return NodeMetadataInfo(
                friendly_label=event_name,
                category="Projectiles",
                entity_names=p_keys,
                friendly_details=f"{len(p_keys)} projectile{'s' if len(p_keys) != 1 else ''}",
                event_name=event_name,
            )

        # 2. Explosions linked to event
        explosions = ctx.catalog.get_explosions_for_event(event_name)
        if explosions:
            e_keys = tuple(e.key for e in explosions)
            return NodeMetadataInfo(
                friendly_label=event_name,
                category="Explosions",
                entity_names=e_keys,
                friendly_details=f"{len(e_keys)} explosion{'s' if len(e_keys) != 1 else ''}",
                event_name=event_name,
            )

        return None

    def resolve_media(
        self,
        wem_id: int,
        bank: SoundBank,
        graph_index: BankGraphIndex,
        ctx: ResolutionContext,
    ) -> NodeMetadataInfo | None:
        return None


class GraphHierarchyProvider:
    """Propagates parent event/container metadata down to leaf CAkSound and embedded WEM nodes."""

    def resolve_hirc(
        self,
        obj: HircObject,
        bank: SoundBank,
        graph_index: BankGraphIndex,
        ctx: ResolutionContext,
    ) -> NodeMetadataInfo | None:
        if isinstance(obj, CAkSound):
            parent_event = self._find_ancestor_event_name(obj.id, graph_index, bank, ctx)
            wid = getattr(obj, "source_id", 0) or getattr(obj, "file_id", 0)
            if parent_event:
                return NodeMetadataInfo(
                    friendly_label=f"{parent_event} [Sound]",
                    category="Sound",
                    friendly_details=f"Event: {parent_event} • Media: {wid}",
                    event_name=parent_event,
                )
            if wid:
                resolved_wem = resolve_hash_name(wid, bank, sound_db=ctx.sound_db)
                if resolved_wem:
                    return NodeMetadataInfo(
                        friendly_label=resolved_wem,
                        category="Sound",
                        friendly_details=f"Media: {resolved_wem} ({wid})",
                    )
        elif isinstance(obj, CAkRanSeqCntr):
            parent_event = self._find_ancestor_event_name(obj.id, graph_index, bank, ctx)
            if parent_event:
                count = len(obj.children)
                return NodeMetadataInfo(
                    friendly_label=f"{parent_event} (Container)",
                    category="Container",
                    friendly_details=f"Event: {parent_event} • {count} variations",
                    event_name=parent_event,
                )
        return None

    def resolve_media(
        self,
        wem_id: int,
        bank: SoundBank,
        graph_index: BankGraphIndex,
        ctx: ResolutionContext,
    ) -> NodeMetadataInfo | None:
        # Check referencing sounds for this WEM
        ref_sound_ids = ctx.media_referencing_sounds.get(wem_id, [])
        if not ref_sound_ids:
            return None

        event_names: list[str] = []
        for sid in ref_sound_ids:
            ev = self._find_ancestor_event_name(sid, graph_index, bank, ctx)
            if ev and ev not in event_names:
                event_names.append(ev)

        if event_names:
            primary_ev = event_names[0]
            count_str = f" (+{len(event_names) - 1} refs)" if len(event_names) > 1 else ""
            return NodeMetadataInfo(
                friendly_label=f"{primary_ev} [WEM {wem_id}]",
                category="Embedded WEM",
                friendly_details=f"Ref by: {primary_ev}{count_str}",
                event_name=primary_ev,
            )

        return None

    def _find_ancestor_event_name(
        self,
        object_id: int,
        graph_index: BankGraphIndex,
        bank: SoundBank,
        ctx: ResolutionContext,
    ) -> str | None:
        """Ascends parent_map to locate the root CAkEvent governing this node."""
        visited: set[int] = set()
        queue = [object_id]

        while queue:
            curr = queue.pop(0)
            if curr in visited:
                continue
            visited.add(curr)

            if curr in ctx.event_names_by_object_id:
                return ctx.event_names_by_object_id[curr]

            obj = graph_index.objects_by_id.get(curr)
            if isinstance(obj, CAkEvent):
                ev_name = resolve_hash_name(obj.id, bank, sound_db=ctx.sound_db)
                if ev_name:
                    ctx.event_names_by_object_id[obj.id] = ev_name
                    return ev_name

            if isinstance(obj, CAkAction):
                # An action's parents might be events
                for p in graph_index.parent_map.get(curr, []):
                    if p not in visited:
                        queue.append(p)
            else:
                for p in graph_index.parent_map.get(curr, []):
                    if p not in visited:
                        queue.append(p)

        return None


# -----------------------------------------------------------------------------
# 4. Composite Metadata Resolver
# -----------------------------------------------------------------------------


_GENERIC_CATEGORIES = frozenset(
    {"Event", "Dialogue", "Switch", "Sound", "Container", "Music", "Audio Media", "Embedded WEM"}
)


class CompositeMetadataResolver:
    """
    Unified composite query facade combining multiple metadata providers.
    Provides fast O(1) cached lookups per bank.
    """

    def __init__(
        self,
        providers: tuple[NodeMetadataProvider, ...] | None = None,
    ) -> None:
        self.providers: tuple[NodeMetadataProvider, ...] = providers or (
            SoundDatabaseProvider(),
            GameCatalogProvider(),
            GraphHierarchyProvider(),
        )
        self._hirc_cache: dict[tuple[int, int], NodeMetadataInfo | None] = {}
        self._media_cache: dict[tuple[int, int], NodeMetadataInfo | None] = {}

    def resolve_hirc_node(
        self,
        obj: HircObject,
        bank: SoundBank,
        graph_index: BankGraphIndex,
        ctx: ResolutionContext,
    ) -> NodeMetadataInfo | None:
        """Resolves enriched metadata across all registered providers, merging results."""
        cache_key = (id(bank), obj.id)
        if cache_key in self._hirc_cache:
            return self._hirc_cache[cache_key]

        merged_label: str | None = None
        merged_cat: str | None = None
        merged_entities: list[str] = []
        merged_details: str | None = None
        merged_event: str | None = None
        details_provenance: Provenance | None = None
        label_provenance: Provenance | None = None

        for provider in self.providers:
            try:
                info = provider.resolve_hirc(obj, bank, graph_index, ctx)
                if info is not None:
                    if not merged_label and info.friendly_label:
                        merged_label = info.friendly_label
                        label_provenance = info.provenance
                    if info.category:
                        if not merged_cat or (
                            merged_cat in _GENERIC_CATEGORIES
                            and info.category not in _GENERIC_CATEGORIES
                        ):
                            merged_cat = info.category
                    if info.entity_names:
                        merged_entities.extend(info.entity_names)
                    if not merged_details and info.friendly_details:
                        merged_details = info.friendly_details
                        details_provenance = info.provenance
                    if not merged_event and info.event_name:
                        merged_event = info.event_name
            except Exception as e:
                logger.debug(
                    "Provider %s failed for HIRC %s: %s", type(provider).__name__, obj.id, e
                )
                continue

        if not any((merged_label, merged_cat, merged_entities, merged_details, merged_event)):
            self._hirc_cache[cache_key] = None
            return None

        final_provenance = (
            details_provenance
            if (merged_details is not None and details_provenance is not None)
            else (label_provenance if label_provenance is not None else Provenance.DATABASE)
        )
        result = NodeMetadataInfo(
            friendly_label=merged_label,
            category=merged_cat,
            entity_names=tuple(dict.fromkeys(merged_entities)),
            friendly_details=merged_details,
            event_name=merged_event,
            provenance=final_provenance,
        )
        self._hirc_cache[cache_key] = result
        return result

    def resolve_media_node(
        self,
        wem_id: int,
        bank: SoundBank,
        graph_index: BankGraphIndex,
        ctx: ResolutionContext,
    ) -> NodeMetadataInfo | None:
        """Resolves enriched metadata for a loose or embedded WEM media ID across providers."""
        cache_key = (id(bank), wem_id)
        if cache_key in self._media_cache:
            return self._media_cache[cache_key]

        merged_label: str | None = None
        merged_cat: str | None = None
        merged_entities: list[str] = []
        merged_details: str | None = None
        merged_event: str | None = None
        details_provenance: Provenance | None = None
        label_provenance: Provenance | None = None

        for provider in self.providers:
            try:
                info = provider.resolve_media(wem_id, bank, graph_index, ctx)
                if info is not None:
                    if not merged_label and info.friendly_label:
                        merged_label = info.friendly_label
                        label_provenance = info.provenance
                    if info.category:
                        if not merged_cat or (
                            merged_cat in _GENERIC_CATEGORIES
                            and info.category not in _GENERIC_CATEGORIES
                        ):
                            merged_cat = info.category
                    if info.entity_names:
                        merged_entities.extend(info.entity_names)
                    if not merged_details and info.friendly_details:
                        merged_details = info.friendly_details
                        details_provenance = info.provenance
                    if not merged_event and info.event_name:
                        merged_event = info.event_name
            except Exception as e:
                logger.debug(
                    "Provider %s failed for media %s: %s", type(provider).__name__, wem_id, e
                )
                continue

        if not any((merged_label, merged_cat, merged_entities, merged_details, merged_event)):
            self._media_cache[cache_key] = None
            return None

        final_provenance = (
            details_provenance
            if (merged_details is not None and details_provenance is not None)
            else (label_provenance if label_provenance is not None else Provenance.DATABASE)
        )
        result = NodeMetadataInfo(
            friendly_label=merged_label,
            category=merged_cat,
            entity_names=tuple(dict.fromkeys(merged_entities)),
            friendly_details=merged_details,
            event_name=merged_event,
            provenance=final_provenance,
        )
        self._media_cache[cache_key] = result
        return result
