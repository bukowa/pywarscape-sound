"""Pure projections from SoundBank AST and BankGraphIndex to viewer state nodes."""

import logging
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import replace
from typing import Any

logger = logging.getLogger(__name__)

from src.bnk.bank import SoundBank
from src.bnk.models import (
    CAkAction,
    CAkEvent,
    CAkMusicSegment,
    CAkMusicTrack,
    CAkRanSeqCntr,
    CAkSound,
    CAkSwitchCntr,
    HircObject,
)
from src.engine.diff import BankDiffResult
from src.engine.graph import BankGraphIndex
from src.engine.metadata_fields import Provenance, extract_hirc_metadata
from src.engine.metadata_resolver import CompositeMetadataResolver, ResolutionContext
from src.models.hashing import KNOWN_HASH_NAMES
from src.ui.features.bank_viewer.state import (
    GameEntitiesSection,
    GameEntityEntry,
    HircTreeNode,
    InspectorProperty,
    InspectorViewType,
    NodeInspectorDetails,
    NodeReferenceSummary,
    PlaylistItemEntry,
    RanSeqContainerSemantics,
    SwitchContainerSemantics,
    SwitchRouteEntry,
)


def _resolve_hash_name(val: int, sound_db: Any | None = None) -> str:
    """Resolves an integer FNV-1 hash to a human-readable name if known."""
    if val == 0:
        return "None"
    if sound_db is not None and hasattr(sound_db, "resolve_hash"):
        try:
            name = sound_db.resolve_hash(val)
            if name:
                return name
        except (ValueError, KeyError, IndexError, AttributeError):
            pass
    if val in KNOWN_HASH_NAMES:
        return KNOWN_HASH_NAMES[val]
    return f"0x{val:08X}"


def _get_object_summary(obj: HircObject) -> tuple[str, str]:
    """Generates concise type name and summary text for a HIRC node."""
    tname = type(obj).__name__.removeprefix("CAk")
    if isinstance(obj, CAkSound):
        st = "Streamed" if getattr(obj, "stream_type", 2) == 2 else "Embedded"
        wid = getattr(obj, "source_id", 0) or getattr(obj, "file_id", 0)
        return "Sound", f"Media: {wid} ({st})"
    if isinstance(obj, CAkAction):
        return "Action", f"Target -> {getattr(obj, 'target_id', 0)}"
    if isinstance(obj, CAkEvent):
        return "Event", f"{len(obj.actions)} actions"
    if isinstance(obj, CAkRanSeqCntr):
        return "RanSeqCntr", f"{len(obj.children)} children ({len(obj.playlist)} items)"
    if isinstance(obj, CAkSwitchCntr):
        return "SwitchCntr", f"{len(obj.children)} children ({len(obj.switch_map)} routes)"
    if isinstance(obj, CAkMusicTrack):
        wid = obj.sources[0].source_id if obj.sources else getattr(obj, "source_id", 0)
        return "MusicTrack", f"Track (WEM: {wid})"
    if isinstance(obj, CAkMusicSegment):
        return "MusicSegment", f"{len(getattr(obj, 'child_ids', []))} tracks"
    return tname, f"ID: {obj.id}"


def _build_game_entities_section(
    meta_info: Any | None,
    catalog: Any | None,
) -> GameEntitiesSection | None:
    """Builds a GameEntitiesSection from resolved NodeMetadataInfo and catalog lookups."""
    if meta_info is None or not meta_info.entity_names:
        return None
    category = meta_info.category or ""
    names = meta_info.entity_names

    if category == "Units" and catalog is not None:
        entries: list[GameEntityEntry] = []
        for key in names:
            unit = catalog.get_unit(key)
            if unit is not None:
                entries.append(
                    GameEntityEntry(
                        key=unit.key,
                        category=unit.category or "",
                        unit_class=unit.unit_class or "",
                    )
                )
            else:
                entries.append(GameEntityEntry(key=key))
        return GameEntitiesSection(
            entity_type="units",
            entries=tuple(entries),
            total_count=len(entries),
        )

    if category == "Projectiles" and catalog is not None:
        entries = []
        for key in names:
            proj = catalog.get_projectile(key)
            if proj is not None:
                extra_parts: list[str] = []
                if proj.fire_event:
                    extra_parts.append(f"fire={proj.fire_event}")
                if proj.impact_event:
                    extra_parts.append(f"impact={proj.impact_event}")
                entries.append(
                    GameEntityEntry(
                        key=proj.key,
                        extra=", ".join(extra_parts),
                    )
                )
            else:
                entries.append(GameEntityEntry(key=key))
        return GameEntitiesSection(
            entity_type="projectiles",
            entries=tuple(entries),
            total_count=len(entries),
        )

    if category == "Explosions" and catalog is not None:
        entries = []
        for key in names:
            expl = catalog.get_explosion(key)
            if expl is not None:
                extra_parts = []
                if expl.event:
                    extra_parts.append(expl.event)
                if expl.group_event:
                    extra_parts.append(expl.group_event)
                entries.append(
                    GameEntityEntry(
                        key=expl.key,
                        extra=", ".join(extra_parts),
                    )
                )
            else:
                entries.append(GameEntityEntry(key=key))
        return GameEntitiesSection(
            entity_type="explosions",
            entries=tuple(entries),
            total_count=len(entries),
        )

    if category == "Material SFX":
        entries = [GameEntityEntry(key=name) for name in names]
        return GameEntitiesSection(
            entity_type="materials",
            entries=tuple(entries),
            total_count=len(entries),
        )

    # Generic fallback for unknown categories
    entries = [GameEntityEntry(key=name) for name in names]
    return GameEntitiesSection(
        entity_type=category.lower() if category else "entities",
        entries=tuple(entries),
        total_count=len(entries),
    )


def _build_properties_for_object(
    obj: HircObject,
    graph_index: BankGraphIndex,
    sound_db: Any | None = None,
) -> tuple[InspectorProperty, ...]:
    """Builds formatted property list for the selected HIRC object."""
    props: list[InspectorProperty] = []

    # Common parameters
    props.extend(
        [
            InspectorProperty(category="Identity", label="HIRC ID", value=str(obj.id)),
            InspectorProperty(category="Identity", label="Hex ID", value=f"0x{obj.id:08X}"),
            InspectorProperty(
                category="Identity", label="Type", value=type(obj).__name__.removeprefix("CAk")
            ),
        ]
    )

    if isinstance(obj, CAkSound):
        st = "Streamed (External)" if getattr(obj, "stream_type", 2) == 2 else "Embedded (Bank)"
        wid = getattr(obj, "source_id", 0) or getattr(obj, "file_id", 0)
        props.append(InspectorProperty(category="Audio Source", label="Stream Type", value=st))
        props.append(
            InspectorProperty(category="Audio Source", label="Source Media ID", value=str(wid))
        )
        if hasattr(obj, "node_base_params"):
            nb = obj.node_base_params
            props.append(
                InspectorProperty(
                    category="Routing",
                    label="Output Bus ID",
                    value=str(getattr(nb, "override_bus_id", 0)),
                )
            )
            props.append(
                InspectorProperty(
                    category="Parameters",
                    label="Priority",
                    value=str(getattr(nb.adv_settings, "priority", 0)),
                )
            )

    elif isinstance(obj, CAkEvent):
        props.append(
            InspectorProperty(category="Event", label="Action Count", value=str(len(obj.actions)))
        )
        for idx, aid in enumerate(obj.actions):
            props.append(
                InspectorProperty(category="Actions", label=f"Action #{idx + 1}", value=str(aid))
            )

    elif isinstance(obj, CAkAction):
        props.append(
            InspectorProperty(
                category="Action", label="Action Type", value=f"0x{obj.action_type:04X}"
            )
        )
        props.append(
            InspectorProperty(
                category="Action", label="Target ID", value=str(getattr(obj, "target_id", 0))
            )
        )

    elif isinstance(obj, CAkRanSeqCntr):
        props.append(
            InspectorProperty(
                category="Container", label="Playlist Items", value=str(len(obj.playlist))
            )
        )
        props.append(
            InspectorProperty(
                category="Container", label="Direct Children", value=str(len(obj.children))
            )
        )
        mode_str = (
            "Random (Shuffle)"
            if getattr(obj, "mode", 0) == 0 and getattr(obj, "random_mode", 0) == 1
            else ("Random" if getattr(obj, "mode", 0) == 0 else "Sequence")
        )
        props.append(InspectorProperty(category="Container", label="Mode", value=mode_str))

    elif isinstance(obj, CAkSwitchCntr):
        props.append(
            InspectorProperty(category="Container", label="Group ID", value=str(obj.group_id))
        )
        default_sw = getattr(obj, "default_switch", getattr(obj, "default_id", 0))
        props.append(
            InspectorProperty(category="Container", label="Default Switch", value=str(default_sw))
        )
        grp_name = _resolve_hash_name(obj.group_id, sound_db=sound_db)
        if grp_name and not grp_name.startswith("0x"):
            props.append(
                InspectorProperty(category="Container", label="Switch Group", value=grp_name)
            )
        props.append(
            InspectorProperty(
                category="Container", label="Switch Routes", value=str(len(obj.switch_map))
            )
        )
        props.append(
            InspectorProperty(
                category="Container", label="Direct Children", value=str(len(obj.children))
            )
        )

    elif isinstance(obj, CAkMusicTrack):
        wid = obj.sources[0].source_id if obj.sources else getattr(obj, "source_id", 0)
        props.append(InspectorProperty(category="Music", label="Source WEM ID", value=str(wid)))
        props.append(
            InspectorProperty(
                category="Music", label="Track Type", value=str(getattr(obj, "track_type", 0))
            )
        )

    elif isinstance(obj, CAkMusicSegment):
        props.append(
            InspectorProperty(
                category="Music", label="Tracks", value=str(len(getattr(obj, "child_ids", [])))
            )
        )
        props.append(
            InspectorProperty(
                category="Music",
                label="Duration (ms)",
                value=f"{getattr(obj, 'duration', 0.0):.1f}",
            )
        )

    return tuple(props)


def _build_switch_semantics(
    obj: CAkSwitchCntr,
    graph_index: BankGraphIndex,
    sound_db: Any | None = None,
) -> SwitchContainerSemantics:
    """Constructs rich semantic descriptor for a CAkSwitchCntr node."""
    grp_name = _resolve_hash_name(obj.group_id, sound_db=sound_db)
    def_sw_id = getattr(obj, "default_switch", getattr(obj, "default_id", 0))
    def_sw_name = _resolve_hash_name(def_sw_id, sound_db=sound_db)

    routes: list[SwitchRouteEntry] = []
    for sw_id, target_ids in getattr(obj, "switch_map", {}).items():
        sw_name = _resolve_hash_name(sw_id, sound_db=sound_db)
        is_def = sw_id == def_sw_id
        for tid in target_ids:
            target_obj = graph_index.objects_by_id.get(tid)
            if target_obj is not None:
                t_lbl = (
                    graph_index.resolve_label(target_obj, sound_db=sound_db)
                    or f"{type(target_obj).__name__.removeprefix('CAk')}_{target_obj.id}"
                )
                t_type, _ = _get_object_summary(target_obj)
            else:
                t_lbl = f"Object_{tid}"
                t_type = "Unknown"
            routes.append(
                SwitchRouteEntry(
                    switch_id=sw_id,
                    switch_name=sw_name,
                    target_key=f"hirc:{tid}",
                    target_id=tid,
                    target_name=t_lbl,
                    target_type=t_type,
                    is_default=is_def,
                )
            )

    return SwitchContainerSemantics(
        group_id=obj.group_id,
        group_name=grp_name,
        group_type=getattr(obj, "group_type", 0),
        default_switch_id=def_sw_id,
        default_switch_name=def_sw_name,
        routes=tuple(routes),
    )


def _build_ran_seq_semantics(
    obj: CAkRanSeqCntr,
    graph_index: BankGraphIndex,
    sound_db: Any | None = None,
) -> RanSeqContainerSemantics:
    """Constructs rich semantic descriptor for a CAkRanSeqCntr node."""
    mode = getattr(obj, "mode", 0)
    rmode = getattr(obj, "random_mode", 0)
    if mode == 0:
        mode_str = "Random (Shuffle)" if rmode == 1 else "Random (Standard)"
    else:
        mode_str = "Sequence"

    total_weight = sum(getattr(item, "weight", 0) for item in getattr(obj, "playlist", []))
    playlist_entries: list[PlaylistItemEntry] = []
    for idx, item in enumerate(getattr(obj, "playlist", [])):
        pid = item.play_id
        target_obj = graph_index.objects_by_id.get(pid)
        if target_obj is not None:
            t_lbl = (
                graph_index.resolve_label(target_obj, sound_db=sound_db)
                or f"{type(target_obj).__name__.removeprefix('CAk')}_{target_obj.id}"
            )
            t_type, _ = _get_object_summary(target_obj)
        else:
            t_lbl = f"Object_{pid}"
            t_type = "Unknown"
        wt = getattr(item, "weight", 0)
        pct = (wt / total_weight * 100.0) if total_weight > 0 else 0.0
        playlist_entries.append(
            PlaylistItemEntry(
                index=idx + 1,
                play_id=pid,
                target_key=f"hirc:{pid}",
                target_name=t_lbl,
                target_type=t_type,
                weight=wt,
                weight_percent=round(pct, 1),
            )
        )

    return RanSeqContainerSemantics(
        mode_str=mode_str,
        loop_count=getattr(obj, "loop_count", 1),
        transition_time_ms=getattr(obj, "transition_time", 0.0),
        avoid_repeat_count=getattr(obj, "avoid_repeat_count", 0),
        playlist=tuple(playlist_entries),
    )


def resolve_inspector_view_type(obj: Any, node_key: str) -> InspectorViewType:
    """Maps AST object or node key to its canonical InspectorViewType."""
    if node_key.startswith("media:"):
        return InspectorViewType.MEDIA
    if isinstance(obj, CAkSound):
        return InspectorViewType.SOUND
    if isinstance(obj, (CAkRanSeqCntr, CAkSwitchCntr)):
        return InspectorViewType.CONTAINER
    if isinstance(obj, (CAkEvent, CAkAction)):
        return InspectorViewType.EVENT_ACTION
    if isinstance(obj, (CAkMusicTrack, CAkMusicSegment)):
        return InspectorViewType.MUSIC
    return InspectorViewType.DEFAULT


def _build_reference_summaries(
    keys: tuple[str, ...],
    graph_index: BankGraphIndex,
    sound_db: Any | None = None,
    bank_name: str = "",
) -> tuple[NodeReferenceSummary, ...]:
    summaries: list[NodeReferenceSummary] = []
    for k in keys:
        if not k.startswith("hirc:"):
            continue
        try:
            oid = int(k.removeprefix("hirc:"))
        except ValueError:
            continue
        o = graph_index.objects_by_id.get(oid)
        if o is None:
            continue
        lbl = (
            graph_index.resolve_label(o, sound_db=sound_db)
            or f"{type(o).__name__.removeprefix('CAk')}_{o.id}"
        )
        tname, _ = _get_object_summary(o)
        summaries.append(
            NodeReferenceSummary(
                key=k,
                label=lbl,
                id_str=str(o.id),
                type_str=tname,
                bank_name=bank_name,
            )
        )
    return tuple(summaries)


def _build_audio_references_for_wem(
    wem_id: int,
    graph_index: BankGraphIndex,
    sound_db: Any | None = None,
    bank_name: str = "",
    cross_bank_wem_refs_provider: Callable[[int], Sequence[Any]] | None = None,
) -> tuple[NodeReferenceSummary, ...]:
    if not wem_id or wem_id <= 0:
        return ()
    if cross_bank_wem_refs_provider is not None:
        cross_refs = cross_bank_wem_refs_provider(wem_id)
        if cross_refs:
            return tuple(
                NodeReferenceSummary(
                    key=r.node_key,
                    label=r.node_name,
                    id_str=str(r.node_id),
                    type_str=r.node_type,
                    bank_name=r.bank_name,
                )
                for r in cross_refs
            )
    ref_ids = graph_index.get_wem_referencing_hirc_ids(wem_id)
    ref_keys = tuple(f"hirc:{hid}" for hid in ref_ids)
    return _build_reference_summaries(ref_keys, graph_index, sound_db=sound_db, bank_name=bank_name)


def _resolve_media_origin(
    wem_id: int,
    staged_wems: Collection[int] | None = None,
    asset_resolver: Any | None = None,
) -> str:
    staged_set = set(staged_wems) if staged_wems else set()
    if wem_id in staged_set:
        return f"Project Overlay (pack_root/audio/{wem_id}.wem)"
    if asset_resolver is not None:
        try:
            resolved_p = asset_resolver.resolve_wem_path(wem_id)
            if resolved_p is not None:
                p_str = str(resolved_p).replace("\\", "/")
                if "pack_root/audio" in p_str:
                    return f"Project Overlay (pack_root/audio/{resolved_p.name})"
                if "dependencies/" in p_str:
                    parts = p_str.split("dependencies/")
                    dep_name = parts[1].split("/")[0] if len(parts) > 1 else "Unknown"
                    return f"Dependency ({dep_name})"
        except (OSError, ValueError, TypeError) as e:
            logger.debug("Failed to resolve media origin for wem %s: %s", wem_id, e)
    return "Vanilla Game Cache"


def _build_media_node_details(
    bank: SoundBank,
    graph_index: BankGraphIndex,
    node_key: str,
    wem_id: int,
    sound_db: Any | None = None,
    bank_name: str = "",
    cross_bank_wem_refs_provider: Callable[[int], Sequence[Any]] | None = None,
    staged_wems: frozenset[int] | set[int] | Sequence[int] | None = None,
    asset_resolver: Any | None = None,
) -> NodeInspectorDetails:
    audio_refs = _build_audio_references_for_wem(
        wem_id,
        graph_index,
        sound_db=sound_db,
        bank_name=bank_name,
        cross_bank_wem_refs_provider=cross_bank_wem_refs_provider,
    )
    entry_size = 0
    entry_offset = 0
    if bank.didx and bank.didx.entries:
        for e in bank.didx.entries:
            if e.file_id == wem_id:
                entry_size = e.size
                entry_offset = e.offset
                break
    sz_str = f"{entry_size / 1024:.1f} KB" if entry_size >= 1024 else f"{entry_size} B"
    origin_str = _resolve_media_origin(
        wem_id, staged_wems=staged_wems, asset_resolver=asset_resolver
    )
    return NodeInspectorDetails(
        node_key=node_key,
        name=f"WEM {wem_id}",
        object_type="Embedded Media",
        view_type=InspectorViewType.MEDIA,
        object_id=wem_id,
        hex_id=f"0x{wem_id:08X}",
        properties=(
            InspectorProperty(category="Media", label="WEM File ID", value=str(wem_id)),
            InspectorProperty(
                category="Media", label="Size", value=f"{entry_size} bytes ({sz_str})"
            ),
            InspectorProperty(category="Media", label="Offset in DATA", value=str(entry_offset)),
            InspectorProperty(category="Media", label="Source Origin", value=origin_str),
        ),
        parent_references=audio_refs,
        audio_references=audio_refs,
        audio_reference_count=len(audio_refs),
        is_streamed=False,
        source_wem_id=wem_id,
        source_origin=origin_str,
    )


def _resolve_hirc_audio_refs(
    obj: HircObject,
    bank: SoundBank,
    graph_index: BankGraphIndex,
    sound_db: Any | None = None,
    bank_name: str = "",
    cross_bank_wem_refs_provider: Callable[[int], Sequence[Any]] | None = None,
) -> tuple[tuple[NodeReferenceSummary, ...], bool, int | None]:
    """Resolves audio references, streaming mode, and source WEM ID for a HIRC node."""
    audio_refs: tuple[NodeReferenceSummary, ...] = ()
    is_streamed = True
    src_wem_id: int | None = None
    if isinstance(obj, CAkSound):
        st = getattr(obj, "stream_type", 2)
        wid = getattr(obj, "source_id", 0) or getattr(obj, "file_id", 0)
        src_wem_id = wid if wid > 0 else None
        is_in_didx = (
            bank.didx is not None
            and bool(bank.didx.entries)
            and any(e.file_id == wid for e in bank.didx.entries)
        )
        is_streamed = (st == 2) and not (st == 0 or (is_in_didx and st != 2))
        audio_refs = _build_audio_references_for_wem(
            wid,
            graph_index,
            sound_db=sound_db,
            bank_name=bank_name,
            cross_bank_wem_refs_provider=cross_bank_wem_refs_provider,
        )
    elif isinstance(obj, CAkMusicTrack):
        wid = obj.sources[0].source_id if obj.sources else getattr(obj, "source_id", 0)
        src_wem_id = wid if wid > 0 else None
        st = obj.sources[0].stream_type if obj.sources else 2
        is_streamed = st == 2
        audio_refs = _build_audio_references_for_wem(
            wid,
            graph_index,
            sound_db=sound_db,
            bank_name=bank_name,
            cross_bank_wem_refs_provider=cross_bank_wem_refs_provider,
        )
    return audio_refs, is_streamed, src_wem_id


def _build_hirc_node_details(
    obj: HircObject,
    bank: SoundBank,
    graph_index: BankGraphIndex,
    node_key: str,
    sound_db: Any | None = None,
    bank_name: str = "",
    cross_bank_wem_refs_provider: Callable[[int], Sequence[Any]] | None = None,
    metadata_catalog: Any | None = None,
    metadata_resolver: CompositeMetadataResolver | None = None,
) -> NodeInspectorDetails:
    parent_ids = graph_index.get_parent_ids(obj.id)
    parent_keys = tuple(f"hirc:{pid}" for pid in parent_ids if pid in graph_index.objects_by_id)
    child_ids = graph_index.get_child_ids(obj.id)
    child_keys = tuple(f"hirc:{cid}" for cid in child_ids if cid in graph_index.objects_by_id)

    lbl = (
        graph_index.resolve_label(obj, sound_db=sound_db)
        or f"{type(obj).__name__.removeprefix('CAk')}_{obj.id}"
    )
    tname, _ = _get_object_summary(obj)
    vtype = resolve_inspector_view_type(obj, node_key)
    parent_refs = _build_reference_summaries(
        parent_keys, graph_index, sound_db=sound_db, bank_name=bank_name
    )
    child_refs = _build_reference_summaries(
        child_keys, graph_index, sound_db=sound_db, bank_name=bank_name
    )

    audio_refs, is_streamed, src_wem_id = _resolve_hirc_audio_refs(
        obj=obj,
        bank=bank,
        graph_index=graph_index,
        sound_db=sound_db,
        bank_name=bank_name,
        cross_bank_wem_refs_provider=cross_bank_wem_refs_provider,
    )

    sw_semantics = None
    rs_semantics = None
    if isinstance(obj, CAkSwitchCntr):
        sw_semantics = _build_switch_semantics(obj, graph_index, sound_db=sound_db)
    elif isinstance(obj, CAkRanSeqCntr):
        rs_semantics = _build_ran_seq_semantics(obj, graph_index, sound_db=sound_db)

    game_entities: GameEntitiesSection | None = None
    if metadata_resolver is not None:
        res_ctx = ResolutionContext(
            bank_name=bank_name,
            sound_db=sound_db,
            catalog=metadata_catalog,
        )
        h_meta = metadata_resolver.resolve_hirc_node(obj, bank, graph_index, res_ctx)
        game_entities = _build_game_entities_section(h_meta, metadata_catalog)

    return NodeInspectorDetails(
        node_key=node_key,
        name=lbl,
        object_type=tname,
        view_type=vtype,
        object_id=obj.id,
        hex_id=f"0x{obj.id:08X}",
        properties=_build_properties_for_object(obj, graph_index, sound_db=sound_db),
        parent_keys=parent_keys,
        child_keys=child_keys,
        parent_references=parent_refs,
        child_references=child_refs,
        audio_references=audio_refs,
        audio_reference_count=len(audio_refs),
        is_streamed=is_streamed,
        source_wem_id=src_wem_id,
        switch_semantics=sw_semantics,
        ran_seq_semantics=rs_semantics,
        game_entities=game_entities,
    )


def build_details_for_node(
    bank: SoundBank,
    graph_index: BankGraphIndex,
    node_key: str,
    sound_db: Any | None = None,
    bank_name: str = "",
    cross_bank_wem_refs_provider: Callable[[int], Sequence[Any]] | None = None,
    metadata_catalog: Any | None = None,
    metadata_resolver: CompositeMetadataResolver | None = None,
    staged_wems: frozenset[int] | set[int] | Sequence[int] | None = None,
    asset_resolver: Any | None = None,
) -> NodeInspectorDetails | None:
    """Dynamically resolves and formats property details for a single selected node."""
    if node_key.startswith("media:"):
        try:
            wem_id = int(node_key.removeprefix("media:"))
        except ValueError:
            return None
        return _build_media_node_details(
            bank=bank,
            graph_index=graph_index,
            node_key=node_key,
            wem_id=wem_id,
            sound_db=sound_db,
            bank_name=bank_name,
            cross_bank_wem_refs_provider=cross_bank_wem_refs_provider,
            staged_wems=staged_wems,
            asset_resolver=asset_resolver,
        )

    if not node_key.startswith("hirc:"):
        return None
    try:
        obj_id = int(node_key.removeprefix("hirc:"))
    except ValueError:
        return None
    obj = graph_index.objects_by_id.get(obj_id)
    if obj is None:
        return None

    return _build_hirc_node_details(
        obj=obj,
        bank=bank,
        graph_index=graph_index,
        node_key=node_key,
        sound_db=sound_db,
        bank_name=bank_name,
        cross_bank_wem_refs_provider=cross_bank_wem_refs_provider,
        metadata_catalog=metadata_catalog,
        metadata_resolver=metadata_resolver,
    )


def _index_media_referencing_sounds(
    bank: SoundBank,
    graph_index: BankGraphIndex,
    sound_db: Any | None = None,
    bank_name: str = "",
) -> dict[int, list[NodeReferenceSummary]]:
    """Pre-indexes sounds and music tracks referencing media files."""
    media_referencing_sounds: dict[int, list[NodeReferenceSummary]] = {}
    if bank.hirc and bank.hirc.objects:
        for o in bank.hirc.objects:
            mids: list[int] = []
            if isinstance(o, CAkSound):
                mid = getattr(o, "source_id", 0) or getattr(o, "file_id", 0)
                if mid:
                    mids.append(mid)
            elif isinstance(o, CAkMusicTrack):
                if o.sources:
                    for s in o.sources:
                        sid = getattr(s, "source_id", 0) or getattr(s, "file_id", 0)
                        if sid:
                            mids.append(sid)
                elif getattr(o, "source_id", 0) or getattr(o, "file_id", 0):
                    mids.append(getattr(o, "source_id", 0) or getattr(o, "file_id", 0))
            if mids:
                o_lbl = (
                    graph_index.resolve_label(o, sound_db=sound_db)
                    or f"{type(o).__name__.removeprefix('CAk')}_{o.id}"
                )
                o_tname, _ = _get_object_summary(o)
                summary = NodeReferenceSummary(
                    key=f"hirc:{o.id}",
                    label=o_lbl,
                    id_str=str(o.id),
                    type_str=o_tname,
                    bank_name=bank_name,
                )
                for mid in mids:
                    media_referencing_sounds.setdefault(mid, []).append(summary)
    return media_referencing_sounds


def _build_didx_chunk(
    bank: SoundBank,
    graph_index: BankGraphIndex,
    nodes: dict[str, HircTreeNode],
    details: dict[str, NodeInspectorDetails],
    modified_media: frozenset[int],
    resolver: CompositeMetadataResolver,
    res_ctx: ResolutionContext,
    sound_db: Any | None = None,
    bank_name: str = "",
    cross_bank_wem_refs_provider: Callable[[int], Sequence[Any]] | None = None,
    media_referencing_sounds: dict[int, list[NodeReferenceSummary]] | None = None,
    staged_wems: Collection[int] | None = None,
    asset_resolver: Any | None = None,
) -> None:
    if not (bank.didx and bank.didx.entries):
        return
    didx_key = "chunk:DIDX"
    didx_child_keys: list[str] = []
    for entry in bank.didx.entries:
        m_key = f"media:{entry.file_id}"
        didx_child_keys.append(m_key)
        sz_str = f"{entry.size / 1024:.1f} KB" if entry.size >= 1024 else f"{entry.size} B"
        is_media_mod = entry.file_id in modified_media
        m_meta = resolver.resolve_media_node(entry.file_id, bank, graph_index, res_ctx)
        m_f_lbl = m_meta.friendly_label if m_meta else None
        m_f_det = m_meta.friendly_details if m_meta else None
        nodes[m_key] = HircTreeNode(
            key=m_key,
            label=f"WEM {entry.file_id}",
            id_str=str(entry.file_id),
            type_str="Embedded WEM",
            details=sz_str,
            child_keys=(),
            is_modified=is_media_mod,
            friendly_label=m_f_lbl,
            friendly_details=m_f_det,
            friendly_details_provenance=(m_meta.provenance if m_meta else Provenance.DATABASE),
        )
        if cross_bank_wem_refs_provider is not None:
            m_refs = _build_audio_references_for_wem(
                entry.file_id,
                graph_index,
                sound_db=sound_db,
                bank_name=bank_name,
                cross_bank_wem_refs_provider=cross_bank_wem_refs_provider,
            )
        else:
            m_refs = tuple((media_referencing_sounds or {}).get(entry.file_id, []))
        m_origin = _resolve_media_origin(
            entry.file_id, staged_wems=staged_wems, asset_resolver=asset_resolver
        )
        details[m_key] = NodeInspectorDetails(
            node_key=m_key,
            name=f"WEM {entry.file_id}",
            object_type="Embedded Media",
            view_type=InspectorViewType.MEDIA,
            object_id=entry.file_id,
            hex_id=f"0x{entry.file_id:08X}",
            properties=(
                InspectorProperty(category="Media", label="WEM File ID", value=str(entry.file_id)),
                InspectorProperty(
                    category="Media", label="Size", value=f"{entry.size} bytes ({sz_str})"
                ),
                InspectorProperty(
                    category="Media", label="Offset in DATA", value=str(entry.offset)
                ),
                InspectorProperty(category="Media", label="Source Origin", value=m_origin),
            ),
            parent_references=m_refs,
            audio_references=m_refs,
            audio_reference_count=len(m_refs),
            is_streamed=False,
            source_wem_id=entry.file_id,
            source_origin=m_origin,
        )
    nodes[didx_key] = HircTreeNode(
        key=didx_key,
        label="DIDX (Embedded Media)",
        id_str=f"{len(bank.didx.entries)} files",
        type_str="Chunk",
        details="Index Table",
        child_keys=tuple(didx_child_keys),
    )


def _build_chunks_section(
    bank: SoundBank,
    graph_index: BankGraphIndex,
    nodes: dict[str, HircTreeNode],
    details: dict[str, NodeInspectorDetails],
    modified_media: frozenset[int],
    resolver: CompositeMetadataResolver,
    res_ctx: ResolutionContext,
    sound_db: Any | None = None,
    bank_name: str = "",
    cross_bank_wem_refs_provider: Callable[[int], Sequence[Any]] | None = None,
    media_referencing_sounds: dict[int, list[NodeReferenceSummary]] | None = None,
    staged_wems: Collection[int] | None = None,
    asset_resolver: Any | None = None,
) -> None:
    chunk_children: list[str] = []

    # BKHD
    bkhd_key = "chunk:BKHD"
    chunk_children.append(bkhd_key)
    nodes[bkhd_key] = HircTreeNode(
        key=bkhd_key,
        label="BKHD (Header)",
        id_str=str(bank.header.bank_id),
        type_str="Chunk",
        details=f"v{bank.header.version}",
        child_keys=(),
    )
    details[bkhd_key] = NodeInspectorDetails(
        node_key=bkhd_key,
        name="BKHD (Header)",
        object_type="Chunk",
        view_type=InspectorViewType.DEFAULT,
        object_id=bank.header.bank_id,
        hex_id=f"0x{bank.header.bank_id:08X}",
        properties=(
            InspectorProperty(category="Header", label="Bank ID", value=str(bank.header.bank_id)),
            InspectorProperty(category="Header", label="Version", value=str(bank.header.version)),
            InspectorProperty(
                category="Header", label="Language ID", value=str(bank.header.language_id)
            ),
        ),
    )

    # DIDX (Embedded media)
    if bank.didx and bank.didx.entries:
        _build_didx_chunk(
            bank=bank,
            graph_index=graph_index,
            nodes=nodes,
            details=details,
            modified_media=modified_media,
            resolver=resolver,
            res_ctx=res_ctx,
            sound_db=sound_db,
            bank_name=bank_name,
            cross_bank_wem_refs_provider=cross_bank_wem_refs_provider,
            media_referencing_sounds=media_referencing_sounds,
            staged_wems=staged_wems,
            asset_resolver=asset_resolver,
        )
        chunk_children.append("chunk:DIDX")

    # HIRC summary
    if bank.hirc:
        hirc_key = "chunk:HIRC"
        chunk_children.append(hirc_key)
        nodes[hirc_key] = HircTreeNode(
            key=hirc_key,
            label="HIRC (Hierarchy)",
            id_str=f"{len(bank.hirc.objects)} objects",
            type_str="Chunk",
            details="Object Graph",
            child_keys=(),
        )

    nodes["group:chunks"] = HircTreeNode(
        key="group:chunks",
        label="Chunks",
        id_str="",
        type_str="Group",
        details=f"{len(chunk_children)} sections",
        child_keys=tuple(chunk_children),
    )


def _build_hirc_section(
    bank: SoundBank,
    graph_index: BankGraphIndex,
    nodes: dict[str, HircTreeNode],
    details: dict[str, NodeInspectorDetails],
    modified_objects: frozenset[int],
    resolver: CompositeMetadataResolver,
    res_ctx: ResolutionContext,
    sound_db: Any | None = None,
    bank_name: str = "",
    cross_bank_wem_refs_provider: Callable[[int], Sequence[Any]] | None = None,
    metadata_catalog: Any | None = None,
) -> None:
    hier_roots: list[str] = []
    if bank.hirc:
        for root in graph_index.get_root_objects():
            hier_roots.append(f"hirc:{root.id}")

        is_small = len(bank.hirc.objects) <= 50
        for obj in bank.hirc.objects:
            obj_key = f"hirc:{obj.id}"
            child_ids = graph_index.get_child_ids(obj.id)
            child_keys = tuple(
                f"hirc:{cid}" for cid in child_ids if cid in graph_index.objects_by_id
            )
            raw_lbl = f"{type(obj).__name__.removeprefix('CAk')}_{obj.id}"
            resolved_lbl = graph_index.resolve_label(obj, sound_db=sound_db)
            tname, summary = _get_object_summary(obj)
            is_obj_mod = obj.id in modified_objects
            h_meta = resolver.resolve_hirc_node(obj, bank, graph_index, res_ctx)
            h_f_lbl = (h_meta.friendly_label if h_meta else None) or (
                resolved_lbl if resolved_lbl != raw_lbl else None
            )
            h_f_det = h_meta.friendly_details if h_meta else None

            nodes[obj_key] = HircTreeNode(
                key=obj_key,
                label=raw_lbl,
                id_str=str(obj.id),
                type_str=tname,
                details=summary,
                child_keys=child_keys,
                is_modified=is_obj_mod,
                friendly_label=h_f_lbl,
                friendly_details=h_f_det,
                metadata=extract_hirc_metadata(obj),
                friendly_details_provenance=(h_meta.provenance if h_meta else Provenance.DATABASE),
            )

            if is_small:
                det = build_details_for_node(
                    bank,
                    graph_index,
                    obj_key,
                    sound_db=sound_db,
                    bank_name=bank_name,
                    cross_bank_wem_refs_provider=cross_bank_wem_refs_provider,
                    metadata_catalog=metadata_catalog,
                    metadata_resolver=resolver,
                )
                if det is not None:
                    details[obj_key] = det

    nodes["group:hierarchy"] = HircTreeNode(
        key="group:hierarchy",
        label="Hierarchy Tree",
        id_str="",
        type_str="Group",
        details=f"{len(hier_roots)} root nodes",
        child_keys=tuple(hier_roots),
    )


def _build_categories_section(
    graph_index: BankGraphIndex,
    nodes: dict[str, HircTreeNode],
) -> dict[str, list[HircObject]]:
    cat_children: list[str] = []
    categorized = graph_index.get_categorized_objects()
    for cat_name, objs in categorized.items():
        if not objs:
            continue
        cat_key = f"cat:{cat_name}"
        cat_children.append(cat_key)
        cat_obj_keys = tuple(f"hirc:{o.id}" for o in objs)
        nodes[cat_key] = HircTreeNode(
            key=cat_key,
            label=f"{cat_name.replace('_', ' ').title()} ({len(objs)})",
            id_str="",
            type_str="Category",
            details="",
            child_keys=cat_obj_keys,
        )

    nodes["group:categories"] = HircTreeNode(
        key="group:categories",
        label="All Objects by Type",
        id_str="",
        type_str="Group",
        details=f"{len(cat_children)} categories",
        child_keys=tuple(cat_children),
    )
    return categorized


def _propagate_modification_flags(
    nodes: dict[str, HircTreeNode],
    graph_index: BankGraphIndex,
    modified_media: frozenset[int],
    modified_objects: frozenset[int],
    categorized: Mapping[str, Sequence[HircObject]],
) -> None:
    has_mod_children_keys: set[str] = set()

    if modified_media:
        has_mod_children_keys.add("chunk:DIDX")
        has_mod_children_keys.add("group:chunks")

    if modified_objects:
        has_mod_children_keys.add("group:hierarchy")
        has_mod_children_keys.add("group:categories")

        queue = list(modified_objects)
        visited_hirc: set[int] = set()
        while queue:
            cid = queue.pop(0)
            for pid in graph_index.get_parent_ids(cid):
                if pid in graph_index.objects_by_id and pid not in visited_hirc:
                    visited_hirc.add(pid)
                    has_mod_children_keys.add(f"hirc:{pid}")
                    queue.append(pid)

        for cat_name, objs in categorized.items():
            if any(o.id in modified_objects for o in objs):
                has_mod_children_keys.add(f"cat:{cat_name}")

    for k in has_mod_children_keys:
        if k in nodes:
            nodes[k] = replace(nodes[k], has_modified_children=True)


def build_tree_and_details_from_bank(
    bank: SoundBank,
    graph_index: BankGraphIndex,
    sound_db: Any | None = None,
    diff_result: BankDiffResult | None = None,
    staged_wems: Collection[int] | None = None,
    bank_name: str = "",
    cross_bank_wem_refs_provider: Callable[[int], Sequence[Any]] | None = None,
    metadata_catalog: Any | None = None,
    metadata_resolver: CompositeMetadataResolver | None = None,
    asset_resolver: Any | None = None,
) -> tuple[tuple[str, ...], dict[str, HircTreeNode], dict[str, NodeInspectorDetails]]:
    """Transforms SoundBank AST and BankGraphIndex into pure immutable projection structures."""
    nodes: dict[str, HircTreeNode] = {}
    details: dict[str, NodeInspectorDetails] = {}

    modified_objects: frozenset[int] = (
        diff_result.all_modified_object_ids if diff_result else frozenset()
    )
    mod_media = set(diff_result.modified_media_ids) if diff_result else set()
    if staged_wems:
        mod_media.update(staged_wems)
    modified_media: frozenset[int] = frozenset(mod_media)

    media_referencing_sounds = _index_media_referencing_sounds(
        bank=bank,
        graph_index=graph_index,
        sound_db=sound_db,
        bank_name=bank_name,
    )

    resolver = metadata_resolver or CompositeMetadataResolver()
    res_ctx = ResolutionContext(
        bank_name=bank_name,
        sound_db=sound_db,
        catalog=metadata_catalog,
        media_referencing_sounds={
            mid: [int(s.id_str) for s in summaries if s.id_str.isdigit()]
            for mid, summaries in media_referencing_sounds.items()
        },
    )

    _build_chunks_section(
        bank=bank,
        graph_index=graph_index,
        nodes=nodes,
        details=details,
        modified_media=modified_media,
        resolver=resolver,
        res_ctx=res_ctx,
        sound_db=sound_db,
        bank_name=bank_name,
        cross_bank_wem_refs_provider=cross_bank_wem_refs_provider,
        media_referencing_sounds=media_referencing_sounds,
        staged_wems=staged_wems,
        asset_resolver=asset_resolver,
    )

    _build_hirc_section(
        bank=bank,
        graph_index=graph_index,
        nodes=nodes,
        details=details,
        modified_objects=modified_objects,
        resolver=resolver,
        res_ctx=res_ctx,
        sound_db=sound_db,
        bank_name=bank_name,
        cross_bank_wem_refs_provider=cross_bank_wem_refs_provider,
        metadata_catalog=metadata_catalog,
    )

    categorized = _build_categories_section(graph_index=graph_index, nodes=nodes)

    _propagate_modification_flags(
        nodes=nodes,
        graph_index=graph_index,
        modified_media=modified_media,
        modified_objects=modified_objects,
        categorized=categorized,
    )

    root_keys = ("group:chunks", "group:hierarchy", "group:categories")
    return root_keys, nodes, details
