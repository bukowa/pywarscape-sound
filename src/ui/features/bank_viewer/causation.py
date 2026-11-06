"""Pure deterministic state transitions and decision logic for SoundBank Viewer."""

from collections.abc import Mapping
from dataclasses import replace
from typing import assert_never

from src.engine.metadata_fields import NodeMetadata, merge_node_metadata
from src.ui.features.bank_viewer.columns import (
    requires_wem_metadata,
    toggle_visible_columns,
)
from src.ui.features.bank_viewer.state import (
    AvailableBanksDiscovered,
    BankCacheInvalidated,
    BankParsedSuccessfully,
    BankParseFailed,
    BankSearchQuerySet,
    BankSelectionRequested,
    BankTreeData,
    BankViewerReset,
    BankViewerState,
    BankWemMetadataResolved,
    FilterModifiedOnlyToggled,
    HircTreeNode,
    HistoryLocation,
    JumpToNodeRequested,
    LoadBankIntent,
    LogStatusIntent,
    MultiNodeSelectionRequested,
    NavigateHistoryBackRequested,
    NavigateHistoryForwardRequested,
    NodeDetailsResolved,
    NodeSelectionRequested,
    ResolveBankWemMetadataIntent,
    ResolveNodeDetailsIntent,
    TreeColumnToggled,
    TreeModifiedFilterToggled,
    TreeOverlayToggled,
    TreeSearchQuerySet,
    ViewerCachesInvalidated,
    ViewerEvent,
    ViewerIntent,
)


def _push_location_history(
    history: tuple[HistoryLocation, ...],
    current_index: int,
    new_loc: HistoryLocation,
    max_history: int = 100,
) -> tuple[tuple[HistoryLocation, ...], int]:
    """Appends or updates location in navigation history, truncating forward branches."""
    if 0 <= current_index < len(history):
        curr = history[current_index]
        # If user selects a node in a bank whose current location had node_key=None,
        # replace the empty bank entry with the node entry
        if (
            curr.bank_name is not None
            and new_loc.bank_name is not None
            and curr.bank_name.lower() == new_loc.bank_name.lower()
            and curr.node_key is None
            and new_loc.node_key is not None
        ):
            updated = list(history[: current_index + 1])
            updated[current_index] = new_loc
            return tuple(updated), current_index

        # If already at this exact location, no-op
        if (
            curr.bank_name == new_loc.bank_name
            or (
                curr.bank_name
                and new_loc.bank_name
                and curr.bank_name.lower() == new_loc.bank_name.lower()
            )
        ) and curr.node_key == new_loc.node_key:
            return history, current_index

    trimmed = history[: current_index + 1] if current_index >= 0 else ()
    new_history = (*trimmed, new_loc)
    if len(new_history) > max_history:
        new_history = new_history[-max_history:]
    return new_history, len(new_history) - 1


def _find_cached_bank(
    cached_banks: Mapping[str, BankTreeData], bank_name: str
) -> BankTreeData | None:
    cached = cached_banks.get(bank_name)
    if cached is not None:
        return cached
    target_lower = bank_name.lower()
    for k, v in cached_banks.items():
        if k.lower() == target_lower:
            return v
    return None


def _on_bank_selection(
    state: BankViewerState, event: BankSelectionRequested
) -> tuple[BankViewerState, tuple[ViewerIntent, ...]]:
    bank_name = event.bank_name
    new_loc = HistoryLocation(bank_name=bank_name, node_key=None)
    new_hist, new_idx = _push_location_history(
        state.navigation_history, state.history_index, new_loc
    )
    cached = _find_cached_bank(state.cached_banks, bank_name)
    if cached is not None:
        new_state = replace(
            state,
            selected_bank_name=bank_name,
            root_keys=cached.root_keys,
            nodes_by_key=cached.nodes_by_key,
            wem_metadata_loaded=cached.wem_metadata_loaded,
            selected_node_key=None,
            selected_node_keys=(),
            navigation_history=new_hist,
            history=new_hist,
            history_index=new_idx,
            ensure_tree_visible=False,
            is_loading=False,
            status_message=f"Loaded {bank_name} (cached)",
        )
        if requires_wem_metadata(new_state.visible_columns) and not cached.wem_metadata_loaded:
            return new_state, (ResolveBankWemMetadataIntent(bank_name=bank_name),)
        return new_state, ()

    new_state = replace(
        state,
        selected_bank_name=bank_name,
        root_keys=(),
        nodes_by_key={},
        wem_metadata_loaded=False,
        selected_node_key=None,
        selected_node_keys=(),
        navigation_history=new_hist,
        history=new_hist,
        history_index=new_idx,
        ensure_tree_visible=False,
        is_loading=True,
        status_message=f"Loading {bank_name}...",
    )
    return new_state, (LoadBankIntent(bank_name=bank_name),)


def _on_bank_parsed(
    state: BankViewerState, event: BankParsedSuccessfully
) -> tuple[BankViewerState, tuple[ViewerIntent, ...]]:
    bank_name = event.bank_name
    roots = event.root_keys
    nodes = event.nodes_by_key
    details = event.details_by_key

    cached_entry = BankTreeData(
        bank_name=bank_name,
        root_keys=roots,
        nodes_by_key=nodes,
        wem_metadata_loaded=False,
    )
    new_cached = {**state.cached_banks, bank_name: cached_entry}

    if not state.navigation_history:
        new_hist = (HistoryLocation(bank_name=bank_name, node_key=None),)
        new_idx = 0
    else:
        new_hist = state.navigation_history
        new_idx = state.history_index

    is_same_bank = bool(
        state.selected_bank_name and state.selected_bank_name.lower() == bank_name.lower()
    )
    sel_node = state.selected_node_key if is_same_bank else None
    if is_same_bank and state.selected_node_keys:
        preserved_keys = tuple(k for k in state.selected_node_keys if k in nodes)
        sel_nodes = preserved_keys if preserved_keys else ((sel_node,) if sel_node else ())
    else:
        sel_nodes = (sel_node,) if sel_node else ()

    new_state = replace(
        state,
        selected_bank_name=bank_name,
        cached_banks=new_cached,
        root_keys=roots,
        nodes_by_key=nodes,
        wem_metadata_loaded=False,
        details_by_key=dict(details),
        selected_node_key=sel_node,
        selected_node_keys=sel_nodes,
        navigation_history=new_hist,
        history=new_hist,
        history_index=new_idx,
        ensure_tree_visible=True if sel_node else False,
        is_loading=False,
        status_message=f"Loaded {bank_name}",
    )
    intents: list[ViewerIntent] = []
    if sel_node and sel_node not in details:
        intents.append(ResolveNodeDetailsIntent(bank_name=bank_name, node_key=sel_node))
    if requires_wem_metadata(new_state.visible_columns):
        intents.append(ResolveBankWemMetadataIntent(bank_name=bank_name))
    return new_state, tuple(intents)


def _on_node_selection(
    state: BankViewerState, event: NodeSelectionRequested
) -> tuple[BankViewerState, tuple[ViewerIntent, ...]]:
    node_key = event.node_key
    if not node_key:
        return replace(
            state, selected_node_key=None, selected_node_keys=(), ensure_tree_visible=False
        ), ()

    if node_key == state.selected_node_key and state.selected_node_keys == (node_key,):
        return replace(state, ensure_tree_visible=False), ()

    new_loc = HistoryLocation(bank_name=state.selected_bank_name, node_key=node_key)
    new_hist, new_idx = _push_location_history(
        state.navigation_history, state.history_index, new_loc
    )
    new_state = replace(
        state,
        selected_node_key=node_key,
        selected_node_keys=(node_key,),
        navigation_history=new_hist,
        history=new_hist,
        history_index=new_idx,
        ensure_tree_visible=False,
    )
    if node_key in state.details_by_key:
        return new_state, ()

    target_bank = state.selected_bank_name or ""
    return new_state, (ResolveNodeDetailsIntent(bank_name=target_bank, node_key=node_key),)


def _on_multi_node_selection(
    state: BankViewerState, event: MultiNodeSelectionRequested
) -> tuple[BankViewerState, tuple[ViewerIntent, ...]]:
    node_keys = event.node_keys
    primary_key = event.primary_key
    effective_primary = (
        primary_key
        if (primary_key and primary_key in node_keys)
        else (node_keys[0] if node_keys else None)
    )
    if not effective_primary:
        return replace(
            state, selected_node_key=None, selected_node_keys=(), ensure_tree_visible=False
        ), ()

    if node_keys == state.selected_node_keys and effective_primary == state.selected_node_key:
        return replace(state, ensure_tree_visible=False), ()

    new_loc = HistoryLocation(bank_name=state.selected_bank_name, node_key=effective_primary)
    new_hist, new_idx = _push_location_history(
        state.navigation_history, state.history_index, new_loc
    )
    new_state = replace(
        state,
        selected_node_key=effective_primary,
        selected_node_keys=node_keys,
        navigation_history=new_hist,
        history=new_hist,
        history_index=new_idx,
        ensure_tree_visible=False,
    )
    if effective_primary in state.details_by_key:
        return new_state, ()

    target_bank = state.selected_bank_name or ""
    return new_state, (ResolveNodeDetailsIntent(bank_name=target_bank, node_key=effective_primary),)


def _on_jump_to_node(
    state: BankViewerState, event: JumpToNodeRequested
) -> tuple[BankViewerState, tuple[ViewerIntent, ...]]:
    node_key = event.node_key
    req_bank = event.bank_name
    if not node_key:
        return replace(
            state, selected_node_key=None, selected_node_keys=(), ensure_tree_visible=False
        ), ()

    actual_node_key = node_key
    target_bank = req_bank or state.selected_bank_name
    if "::" in node_key and req_bank is None:
        parts = node_key.split("::", 1)
        if parts[0]:
            target_bank = parts[0]
        actual_node_key = parts[1]

    new_loc = HistoryLocation(bank_name=target_bank, node_key=actual_node_key)
    new_hist, new_idx = _push_location_history(
        state.navigation_history, state.history_index, new_loc
    )

    if target_bank and (
        state.selected_bank_name is None or target_bank.lower() != state.selected_bank_name.lower()
    ):
        cached = _find_cached_bank(state.cached_banks, target_bank)
        roots = cached.root_keys if cached else ()
        nodes = cached.nodes_by_key if cached else {}
        wem_loaded = cached.wem_metadata_loaded if cached else False

        new_state = replace(
            state,
            selected_bank_name=target_bank,
            root_keys=roots,
            nodes_by_key=nodes,
            wem_metadata_loaded=wem_loaded,
            selected_node_key=actual_node_key,
            selected_node_keys=(actual_node_key,),
            navigation_history=new_hist,
            history=new_hist,
            history_index=new_idx,
            ensure_tree_visible=True,
            is_loading=True if cached is None else False,
            status_message=f"Loading {target_bank}..."
            if cached is None
            else f"Loaded {target_bank} (cached)",
        )
        return new_state, (LoadBankIntent(bank_name=target_bank),)

    new_state = replace(
        state,
        selected_node_key=actual_node_key,
        selected_node_keys=(actual_node_key,),
        navigation_history=new_hist,
        history=new_hist,
        history_index=new_idx,
        ensure_tree_visible=True,
    )
    if actual_node_key in state.details_by_key:
        return new_state, ()

    eff_bank = target_bank or ""
    return new_state, (ResolveNodeDetailsIntent(bank_name=eff_bank, node_key=actual_node_key),)


def _on_navigate_history(
    state: BankViewerState, target_idx: int
) -> tuple[BankViewerState, tuple[ViewerIntent, ...]]:
    target_loc = state.navigation_history[target_idx]

    if target_loc.bank_name and (
        state.selected_bank_name is None
        or target_loc.bank_name.lower() != state.selected_bank_name.lower()
    ):
        cached = _find_cached_bank(state.cached_banks, target_loc.bank_name)
        roots = cached.root_keys if cached else ()
        nodes = cached.nodes_by_key if cached else {}
        wem_loaded = cached.wem_metadata_loaded if cached else False

        new_state = replace(
            state,
            selected_bank_name=target_loc.bank_name,
            root_keys=roots,
            nodes_by_key=nodes,
            wem_metadata_loaded=wem_loaded,
            selected_node_key=target_loc.node_key,
            selected_node_keys=(target_loc.node_key,) if target_loc.node_key else (),
            history_index=target_idx,
            ensure_tree_visible=True if target_loc.node_key else False,
            is_loading=True if cached is None else False,
            status_message=f"Loading {target_loc.bank_name}..."
            if cached is None
            else f"Loaded {target_loc.bank_name} (cached)",
        )
        return new_state, (LoadBankIntent(bank_name=target_loc.bank_name),)

    new_state = replace(
        state,
        selected_node_key=target_loc.node_key,
        selected_node_keys=(target_loc.node_key,) if target_loc.node_key else (),
        history_index=target_idx,
        ensure_tree_visible=True if target_loc.node_key else False,
    )
    if not target_loc.node_key or target_loc.node_key in state.details_by_key:
        return new_state, ()
    target_bank = state.selected_bank_name or ""
    return new_state, (
        ResolveNodeDetailsIntent(bank_name=target_bank, node_key=target_loc.node_key),
    )


def _on_bank_wem_metadata_resolved(
    state: BankViewerState, event: BankWemMetadataResolved
) -> tuple[BankViewerState, tuple[ViewerIntent, ...]]:
    def _merge_nodes(
        nodes: Mapping[str, HircTreeNode], meta_map: Mapping[str, NodeMetadata]
    ) -> dict[str, HircTreeNode]:
        updated = dict(nodes)
        for k, extra_meta in meta_map.items():
            if k in updated:
                updated[k] = replace(
                    updated[k],
                    metadata=merge_node_metadata(updated[k].metadata, extra_meta),
                )
        return updated

    target_lower = event.bank_name.lower()
    new_cached = dict(state.cached_banks)
    for k, v in state.cached_banks.items():
        if k.lower() == target_lower:
            new_cached[k] = replace(
                v,
                nodes_by_key=_merge_nodes(v.nodes_by_key, event.metadata_by_key),
                wem_metadata_loaded=True,
            )
            break

    is_same = bool(state.selected_bank_name and state.selected_bank_name.lower() == target_lower)
    if is_same:
        new_nodes = _merge_nodes(state.nodes_by_key, event.metadata_by_key)
        new_state = replace(
            state,
            cached_banks=new_cached,
            nodes_by_key=new_nodes,
            wem_metadata_loaded=True,
        )
    else:
        new_state = replace(state, cached_banks=new_cached)

    return new_state, ()


def reconcile_viewer(
    state: BankViewerState,
    event: ViewerEvent,
) -> tuple[BankViewerState, tuple[ViewerIntent, ...]]:
    """Pure state transition decision core for SoundBank Viewer."""
    match event:
        case AvailableBanksDiscovered(banks=banks):
            return replace(state, available_banks=banks), ()

        case BankSearchQuerySet(query=query):
            return replace(state, bank_search_query=query), ()

        case FilterModifiedOnlyToggled(enabled=enabled):
            return replace(state, filter_modified_only=enabled), ()

        case BankSelectionRequested():
            return _on_bank_selection(state, event)

        case BankParsedSuccessfully():
            return _on_bank_parsed(state, event)

        case BankParseFailed(bank_name=bank_name, error=err):
            msg = f"Failed to load {bank_name}: {err}"
            return replace(state, is_loading=False, status_message=msg), (
                LogStatusIntent(message=msg),
            )

        case TreeSearchQuerySet(query=query):
            return replace(state, tree_search_query=query), ()

        case TreeModifiedFilterToggled(filter_modified_only=filtered):
            return replace(state, filter_tree_modified_only=filtered), ()

        case TreeOverlayToggled(overlay=ov, enabled=enabled):
            target = (
                (set(state.active_overlays) | {ov})
                if enabled
                else (set(state.active_overlays) - {ov})
            )
            return replace(state, active_overlays=frozenset(target)), ()

        case TreeColumnToggled(column=col, visible=visible):
            new_cols = toggle_visible_columns(state.visible_columns, col, visible)
            new_state = replace(state, visible_columns=new_cols)
            if (
                requires_wem_metadata(new_cols)
                and new_state.selected_bank_name
                and not new_state.is_loading
                and new_state.nodes_by_key
                and not new_state.wem_metadata_loaded
            ):
                return new_state, (
                    ResolveBankWemMetadataIntent(bank_name=new_state.selected_bank_name),
                )
            return new_state, ()

        case NodeSelectionRequested():
            return _on_node_selection(state, event)

        case MultiNodeSelectionRequested():
            return _on_multi_node_selection(state, event)

        case JumpToNodeRequested():
            return _on_jump_to_node(state, event)

        case NavigateHistoryBackRequested():
            if not state.can_navigate_back:
                return state, ()
            return _on_navigate_history(state, state.history_index - 1)

        case NavigateHistoryForwardRequested():
            if not state.can_navigate_forward:
                return state, ()
            return _on_navigate_history(state, state.history_index + 1)

        case NodeDetailsResolved(node_key=node_key, details=details):
            new_details = {**state.details_by_key, node_key: details}
            return replace(state, details_by_key=new_details), ()

        case BankWemMetadataResolved():
            return _on_bank_wem_metadata_resolved(state, event)

        case BankCacheInvalidated(bank_name=bank_name):
            new_cache = {
                k: v for k, v in state.cached_banks.items() if k.lower() != bank_name.lower()
            }
            return replace(state, cached_banks=new_cache), ()

        case ViewerCachesInvalidated():
            return (
                replace(
                    state,
                    cached_banks={},
                    root_keys=(),
                    nodes_by_key={},
                    details_by_key={},
                    selected_node_key=None,
                    selected_node_keys=(),
                    selected_bank_name=None,
                    wem_metadata_loaded=False,
                ),
                (),
            )

        case BankViewerReset():
            return (
                BankViewerState(
                    active_overlays=state.active_overlays,
                    visible_columns=state.visible_columns,
                ),
                (),
            )

        case _ as unreachable:
            assert_never(unreachable)
