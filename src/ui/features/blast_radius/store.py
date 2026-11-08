"""Headless store and workflow branching controller for Blast Radius confirmation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, assert_never

from src.bnk.models import CAkMusicTrack, CAkSound
from src.engine.metadata_resolver import CompositeMetadataResolver, ResolutionContext
from src.engine.ontology import MusicTrackTarget, ReplacementScope, SoundNodeTarget
from src.engine.session import WorkspaceSession
from src.ui.features.blast_radius.causation import reconcile_blast_radius
from src.ui.features.blast_radius.state import (
    BlastRadiusAction,
    BlastRadiusEvent,
    BlastRadiusImpactItem,
    BlastRadiusIntent,
    BlastRadiusMode,
    BlastRadiusState,
    ChooseActionRequested,
    CloseDialogIntent,
)

logger = logging.getLogger(__name__)


class BlastRadiusStore:
    """Headless state management and Imperative Shell for the Blast Radius dialog."""

    def __init__(self, initial_state: BlastRadiusState | None = None) -> None:
        self._state = initial_state or BlastRadiusState()
        self._subscribers: list[Callable[[BlastRadiusState], None]] = []
        self._close_listeners: list[Callable[[BlastRadiusAction], None]] = []

    @property
    def state(self) -> BlastRadiusState:
        """Current immutable state snapshot."""
        return self._state

    def subscribe(self, callback: Callable[[BlastRadiusState], None]) -> None:
        """Register a state listener."""
        self._subscribers.append(callback)

    def on_close_requested(self, callback: Callable[[BlastRadiusAction], None]) -> None:
        """Register a listener notified when CloseDialogIntent is dispatched."""
        self._close_listeners.append(callback)

    def choose_action(self, action: BlastRadiusAction) -> None:
        """Dispatch user choice of Overwrite, Isolate/Fork, or Cancel."""
        self._dispatch(ChooseActionRequested(action=action))

    def _dispatch(self, event: BlastRadiusEvent) -> None:
        new_state, intents = reconcile_blast_radius(self._state, event)
        self._state = new_state
        for callback in self._subscribers:
            try:
                callback(self._state)
            except Exception:
                logger.exception("BlastRadiusStore subscriber raised unhandled exception")
                raise

        for intent in intents:
            self._apply_intent(intent)

    def _apply_intent(self, intent: BlastRadiusIntent) -> None:
        match intent:
            case CloseDialogIntent(action=action):
                for listener in self._close_listeners:
                    listener(action)

            case _ as unreachable:
                assert_never(unreachable)


def check_replacement_branch(
    session: WorkspaceSession,
    bank_name: str,
    sound_id: int | SoundNodeTarget | MusicTrackTarget,
    parent_widget: Any | None = None,
    source_index: int = 0,
    prompt_on_embedded_unshared: bool = True,
) -> tuple[bool, ReplacementScope]:
    """
    Evaluates the blast radius and stream type of a target sound or music track node before replacement:
    - Branch A (unshared streamed, <= 1 ref and stream_type == 2): returns (True, OVERWRITE) immediately.
    - Branch B (unshared embedded, <= 1 ref and embedded): shows Promotion Notice dialog.
    - Branch C (shared WEM, > 1 ref across loaded banks): shows Blast Radius confirmation dialog.
    """
    if isinstance(sound_id, MusicTrackTarget):
        bank_name = sound_id.bank_name
        source_index = sound_id.source_index
        target_node_id = sound_id.track_id
    elif isinstance(sound_id, SoundNodeTarget):
        bank_name = sound_id.bank_name
        target_node_id = sound_id.sound_id
    else:
        target_node_id = int(sound_id)

    entry = session.get_loaded_entry(bank_name)
    if entry is None:
        try:
            entry = session.resolve_and_parse_bank(bank_name)
        except (FileNotFoundError, ValueError, KeyError, IndexError, RuntimeError, OSError):
            return (True, ReplacementScope.OVERWRITE)

    bank, graph_index, _ = entry
    obj = graph_index.objects_by_id.get(target_node_id)
    if obj is None and bank.hirc:
        for h_obj in bank.hirc.objects:
            if h_obj.id == target_node_id:
                obj = h_obj
                break

    if obj is None:
        return (True, ReplacementScope.OVERWRITE)

    wem_id = 0
    st = 2
    if isinstance(obj, CAkMusicTrack):
        if hasattr(obj, "sources") and obj.sources and 0 <= source_index < len(obj.sources):
            src_desc = obj.sources[source_index]
            wem_id = getattr(src_desc, "source_id", 0) or getattr(src_desc, "file_id", 0)
            st = getattr(src_desc, "stream_type", 2)
    elif isinstance(obj, CAkSound):
        wem_id = session.extract_sound_wem_id(obj)
        st = getattr(obj, "stream_type", 2)
    else:
        return (True, ReplacementScope.OVERWRITE)

    if wem_id <= 0:
        return (True, ReplacementScope.OVERWRITE)

    is_in_didx = (
        bank.didx is not None
        and bool(bank.didx.entries)
        and any(e.file_id == wem_id for e in bank.didx.entries)
    )
    is_embedded = (st != 2) or is_in_didx

    refs = session.get_cross_bank_wem_references(wem_id)
    ref_count = len(refs)

    # Branch A: Unshared streamed -> replace immediately without modal confirmation
    if ref_count <= 1 and (not is_embedded or not prompt_on_embedded_unshared):
        return (True, ReplacementScope.OVERWRITE)

    resolver = CompositeMetadataResolver()
    enriched_items: list[BlastRadiusImpactItem] = []
    for r in refs:
        node_name = r.node_name
        r_entry = session.get_loaded_entry(r.bank_name)
        if r_entry is not None:
            r_bank, r_graph_index, _ = r_entry
            r_obj = r_graph_index.objects_by_id.get(r.node_id)
            if r_obj is None and r_bank.hirc:
                for ho in r_bank.hirc.objects:
                    if ho.id == r.node_id:
                        r_obj = ho
                        break
            if r_obj is not None:
                ctx = ResolutionContext(
                    bank_name=r.bank_name,
                    sound_db=getattr(session, "sound_db", None),
                )
                meta = resolver.resolve_hirc_node(r_obj, r_bank, r_graph_index, ctx)
                if meta:
                    ctx_label = meta.event_name or meta.switch_path or meta.friendly_label
                    if ctx_label and ctx_label not in node_name:
                        node_name = f"{node_name} ({ctx_label})"

        enriched_items.append(
            BlastRadiusImpactItem(
                bank_name=r.bank_name,
                node_id=r.node_id,
                node_name=node_name,
                node_type=r.node_type,
                stream_type=r.stream_type,
                is_embedded=r.is_embedded,
                node_key=r.node_key,
            )
        )
    impact_items = tuple(enriched_items)

    mode = (
        BlastRadiusMode.PROMOTION_NOTICE if ref_count <= 1 else BlastRadiusMode.SHARED_CONFIRMATION
    )
    init_state = BlastRadiusState(
        mode=mode,
        target_bank_name=bank_name,
        target_node_id=target_node_id,
        wem_id=wem_id,
        items=impact_items,
    )
    store = BlastRadiusStore(init_state)

    from src.ui.features.blast_radius.view import BlastRadiusDialog

    dialog = BlastRadiusDialog(store, parent=parent_widget)
    result = dialog.exec()
    chosen = result if isinstance(result, BlastRadiusAction) else store.state.chosen_action

    if mode == BlastRadiusMode.PROMOTION_NOTICE:
        if chosen in (BlastRadiusAction.OVERWRITE, BlastRadiusAction.ISOLATE):
            return (True, ReplacementScope.OVERWRITE)
        return (False, ReplacementScope.OVERWRITE)

    if chosen == BlastRadiusAction.ISOLATE:
        return (True, ReplacementScope.ISOLATE)
    if chosen == BlastRadiusAction.OVERWRITE:
        return (True, ReplacementScope.OVERWRITE)
    return (False, ReplacementScope.OVERWRITE)
