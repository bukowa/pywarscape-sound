"""Headless cross-store coordinator orchestrating Shell, BankViewer, and Transport stores."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from src.engine.ontology import (
    BatchItem,
    MediaNodeTarget,
    MusicTrackTarget,
    MutationBatch,
    MutationTarget,
    ReplacementScope,
    SilentStubSource,
    SoundNodeTarget,
)
from src.models import AudioCatalogEntry
from src.ui.features.audio_sources.state import AudioEnhanceSettings
from src.ui.features.audio_sources.store import AudioSourcesStore
from src.ui.features.audio_transport.store import AudioTransportStore
from src.ui.features.audio_transport.structs import (
    AudioSourceId,
    AudioTrack,
    PlaybackStatus,
    TransportState,
)
from src.ui.features.bank_viewer.audio_resolver import resolve_catalog_entry_audio_track
from src.ui.features.bank_viewer.state import BankViewerState
from src.ui.features.bank_viewer.store import BankViewerStore
from src.ui.features.blast_radius.store import check_replacement_branch
from src.ui.shell.state import ScreenMode, ShellState
from src.ui.shell.store import ShellStore
from src.workspace.project import AudioProject


class WorkspaceCoordinator:
    """Headless coordinator orchestrating cross-store interactions between Shell, BankViewer, and Transport."""

    def __init__(
        self,
        shell_store: ShellStore,
        bank_viewer_store: BankViewerStore,
        transport_store: AudioTransportStore,
        audio_sources_store: AudioSourcesStore | None = None,
        audio_sources_transport_store: AudioTransportStore | None = None,
        async_preview: bool = True,
        confirm_replacement_scope: Callable[[MutationTarget], tuple[bool, ReplacementScope]]
        | None = None,
    ) -> None:
        self.shell_store = shell_store
        self.bank_viewer_store = bank_viewer_store
        self.transport_store = transport_store
        self.audio_sources_store = audio_sources_store
        self.audio_sources_transport_store = audio_sources_transport_store or transport_store
        self.async_preview = async_preview
        self.confirm_replacement_scope = confirm_replacement_scope

        self._active_project: AudioProject | None = None
        self._last_selected_bank_name: str | None = None
        self._last_selected_node_key: str | None = None
        self._last_selected_node_keys: tuple[str, ...] = ()
        self._last_selected_node_details: object = None
        self._cached_base_wav: tuple[str, str, bytes] | None = None
        self._enhance_preview_seq: int = 0
        self._preview_thread: threading.Thread | None = None

        if self.audio_sources_store is not None:
            self.audio_sources_store.on_batch_ready(self._handle_audio_sources_batch)
            self.audio_sources_store.on_enhance_ready(self._handle_audio_sources_enhance)
            self.audio_sources_store.on_preview_file(self._handle_audio_sources_preview)
            self.audio_sources_store.on_preview_game_audio(self._handle_audio_sources_game_preview)
            self.audio_sources_store.on_preview_enhance(self._handle_audio_sources_enhance_preview)
            self.audio_sources_store.on_clear_preview(self._handle_audio_sources_clear_preview)
            self.audio_sources_store.on_load_game_audio(self._handle_load_game_audio)

        if self.audio_sources_transport_store is not self.transport_store:
            self.transport_store.subscribe(self._on_main_transport_state_changed)
            self.audio_sources_transport_store.subscribe(self._on_sources_transport_state_changed)

        self.shell_store.subscribe(self._on_shell_state_changed)
        self.bank_viewer_store.subscribe(self._on_bank_viewer_state_changed)

        # Synchronize with initial state if shell already has an active project or mode
        self._on_shell_state_changed(self.shell_store.state)

    def _on_main_transport_state_changed(self, state: TransportState) -> None:
        """When main bank transport starts playing, stops audio sources audition to prevent overlap."""
        if state.status == PlaybackStatus.PLAYING:
            if self.audio_sources_transport_store.state.status == PlaybackStatus.PLAYING:
                self.audio_sources_transport_store.stop()

    def _on_sources_transport_state_changed(self, state: TransportState) -> None:
        """When audio sources transport starts playing, stops main bank transport to prevent overlap."""
        if state.status == PlaybackStatus.PLAYING:
            if self.transport_store.state.status == PlaybackStatus.PLAYING:
                self.transport_store.stop()

    def _on_shell_state_changed(self, shell_state: ShellState) -> None:
        """Handles transitions between launcher and workspace screen modes."""
        if shell_state.screen_mode == ScreenMode.WORKSPACE:
            if shell_state.active_project != self._active_project:
                self._cached_base_wav = None
                self._active_project = shell_state.active_project
                if shell_state.active_project is not None:
                    self.bank_viewer_store.load_project(shell_state.active_project)
                    if self.audio_sources_store is not None:
                        self.audio_sources_store.set_project(shell_state.active_project)
        elif shell_state.screen_mode == ScreenMode.LAUNCHER:
            self._cached_base_wav = None
            self.transport_store.select_track(None)
            if self.audio_sources_transport_store is not self.transport_store:
                self.audio_sources_transport_store.select_track(None)
            self._last_selected_bank_name = None
            self._last_selected_node_key = None
            self._last_selected_node_keys = ()
            self._last_selected_node_details = None
            if self._active_project is not None:
                self._active_project = None
                self.bank_viewer_store.reset()
                if self.audio_sources_store is not None:
                    self.audio_sources_store.set_project(None)
                    self.audio_sources_store.set_targets(())

    def _on_bank_viewer_state_changed(self, bv_state: BankViewerState) -> None:
        """Synchronizes bank viewer selection with global audio transport and Audio Sources targets."""
        if (
            bv_state.selected_bank_name != self._last_selected_bank_name
            or bv_state.selected_node_key != self._last_selected_node_key
        ):
            self._cached_base_wav = None

        if bv_state.selected_bank_name != self._last_selected_bank_name:
            self._last_selected_bank_name = bv_state.selected_bank_name
            self._last_selected_node_key = None
            self._last_selected_node_keys = ()
            self._last_selected_node_details = None
            self.transport_store.select_track(None)

        track = self.bank_viewer_store.resolve_audio_track(bv_state.selected_node_key)
        keys_changed = (
            bv_state.selected_node_keys != self._last_selected_node_keys
            or bv_state.selected_node_key != self._last_selected_node_key
        )

        if (
            bv_state.selected_node_key != self._last_selected_node_key
            or bv_state.selected_node_details != self._last_selected_node_details
            or track != self.transport_store.state.active_track
        ):
            self._last_selected_node_key = bv_state.selected_node_key
            self._last_selected_node_details = bv_state.selected_node_details
            if self.audio_sources_transport_store is not self.transport_store:
                if self.audio_sources_transport_store.state.status == PlaybackStatus.PLAYING:
                    self.audio_sources_transport_store.stop()
            self.transport_store.select_track(track)

        # Synchronize targets with audio_sources_store
        if self.audio_sources_store is not None and keys_changed:
            self._last_selected_node_keys = bv_state.selected_node_keys
            targets = self._resolve_targets_from_selection(bv_state)
            self.audio_sources_store.set_targets(targets)

    def _find_parent_segment_id(self, bank_name: str, track_id: int) -> int | None:
        """Finds the parent CAkMusicSegment ID for a CAkMusicTrack using BankGraphIndex and bank AST."""
        entry = self.bank_viewer_store.session.get_loaded_entry(bank_name)
        if entry is None:
            return None
        bank, graph_index, _ = entry

        # 1. Query graph_index parent mapping
        parents: list[Any] = []
        get_parents_fn = getattr(graph_index, "get_parents", None)
        if callable(get_parents_fn):
            parents = get_parents_fn(track_id)
        elif hasattr(graph_index, "get_parent_ids"):
            parents = graph_index.get_parent_ids(track_id)
        elif hasattr(graph_index, "parent_map"):
            parents = graph_index.parent_map.get(track_id, [])

        for p in parents:
            if isinstance(p, int):
                p_obj = graph_index.objects_by_id.get(p)
                if p_obj is None and bank.hirc is not None:
                    for obj in bank.hirc.objects:
                        if obj.id == p:
                            p_obj = obj
                            break
                if p_obj is not None:
                    if (
                        getattr(p_obj, "obj_type", None) == 10
                        or p_obj.__class__.__name__ == "CAkMusicSegment"
                    ):
                        return p
            else:
                if getattr(p, "obj_type", None) == 10 or p.__class__.__name__ == "CAkMusicSegment":
                    return getattr(p, "id", None)

        # 2. Fallback: inspect bank.hirc.objects directly if graph_index didn't find segment
        if bank.hirc is not None:
            for obj in bank.hirc.objects:
                if (
                    getattr(obj, "obj_type", None) == 10
                    or obj.__class__.__name__ == "CAkMusicSegment"
                ):
                    child_ids = getattr(obj, "child_ids", None) or []
                    if track_id in child_ids:
                        return obj.id

        return None

    def _is_music_track(self, bank_name: str, hirc_id: int, node: Any | None) -> bool:
        """Determines if a HIRC ID corresponds to a CAkMusicTrack."""
        if node is not None:
            return node.type_str in ("MusicTrack", "MusicTrackSource", "SubTrack")

        entry = self.bank_viewer_store.session.get_loaded_entry(bank_name)
        bank = entry[0] if entry is not None else self.bank_viewer_store.get_loaded_bank(bank_name)
        if bank is not None:
            obj: Any = None
            if entry is not None:
                graph_index = entry[1]
                obj = graph_index.objects_by_id.get(hirc_id)
            if obj is None and bank.hirc is not None:
                for o in bank.hirc.objects:
                    if o.id == hirc_id:
                        obj = o
                        break
            if obj is not None:
                return (
                    getattr(obj, "obj_type", None) == 11
                    or obj.__class__.__name__ == "CAkMusicTrack"
                )
            return False

        return False

    def _resolve_targets_from_selection(
        self, bv_state: BankViewerState
    ) -> tuple[MutationTarget, ...]:
        """Resolves target descriptors from selected nodes in BankViewerState."""
        if not bv_state.selected_bank_name:
            return ()
        bank_name = bv_state.selected_bank_name
        keys = bv_state.selected_node_keys or (
            (bv_state.selected_node_key,) if bv_state.selected_node_key else ()
        )
        targets: list[MutationTarget] = []
        for key in keys:
            if not key:
                continue
            if key.startswith("media:"):
                try:
                    wem_id = int(key.removeprefix("media:"))
                    targets.append(MediaNodeTarget(bank_name=bank_name, wem_id=wem_id))
                except ValueError:
                    pass
            elif key.startswith("hirc:"):
                # Sub-track node syntax: "hirc:<track_id>:src:<source_index>"
                parts = key.split(":")
                if len(parts) == 4 and parts[2] == "src":
                    try:
                        track_id = int(parts[1])
                        source_index = int(parts[3])
                    except ValueError:
                        continue

                    node = bv_state.nodes_by_key.get(key) or bv_state.nodes_by_key.get(
                        f"hirc:{track_id}"
                    )
                    if not self._is_music_track(bank_name, track_id, node):
                        continue

                    parent_seg_id = self._find_parent_segment_id(bank_name, track_id)
                    targets.append(
                        MusicTrackTarget(
                            bank_name=bank_name,
                            track_id=track_id,
                            parent_segment_id=parent_seg_id,
                            source_index=source_index,
                        )
                    )
                    continue

                # Standard HIRC node syntax: "hirc:<id>"
                node = bv_state.nodes_by_key.get(key)
                if node is not None and node.type_str not in ("Sound", "MusicTrack"):
                    continue
                try:
                    raw_id = node.id_str if (node and node.id_str) else key.removeprefix("hirc:")
                    hirc_id = int(raw_id)
                    if self._is_music_track(bank_name, hirc_id, node):
                        parent_seg_id = self._find_parent_segment_id(bank_name, hirc_id)
                        targets.append(
                            MusicTrackTarget(
                                bank_name=bank_name,
                                track_id=hirc_id,
                                parent_segment_id=parent_seg_id,
                                source_index=0,
                            )
                        )
                    else:
                        targets.append(SoundNodeTarget(bank_name=bank_name, sound_id=hirc_id))
                except ValueError:
                    pass
        return tuple(targets)

    def _handle_audio_sources_batch(self, batch: MutationBatch) -> None:
        """Applies mutation batch to session, updates AudioSources outcome, and refreshes touched banks."""
        self._cached_base_wav = None
        session = self.bank_viewer_store.session
        # Preserve view-state continuity for currently inspected bank and nodes BEFORE mutating and loading
        sel_bank = self.bank_viewer_store.state.selected_bank_name
        sel_key = self.bank_viewer_store.state.selected_node_key
        sel_keys = self.bank_viewer_store.state.selected_node_keys

        if self.confirm_replacement_scope is not None or self.async_preview:
            confirm_fn = self.confirm_replacement_scope or (
                lambda target: check_replacement_branch(
                    session,
                    target.bank_name,
                    target,
                    prompt_on_embedded_unshared=False,
                )
            )
            updated_items: list[BatchItem] = []
            for item in batch.items:
                if isinstance(item.target, (SoundNodeTarget, MusicTrackTarget)) and not isinstance(
                    item.source, SilentStubSource
                ):
                    proceed, chosen_scope = confirm_fn(item.target)
                    if not proceed:
                        continue
                    item = replace(item, scope=chosen_scope)
                updated_items.append(item)

            if not updated_items and bool(batch.items):
                return
            batch = replace(batch, items=tuple(updated_items))

        outcome = session.apply_batch(batch)
        if self.audio_sources_store is not None:
            self.audio_sources_store.receive_batch_outcome(outcome)

        if outcome.applied > 0 and self.bank_viewer_store.project is not None:
            self.bank_viewer_store.load_project(self.bank_viewer_store.project)
            for b_name in outcome.touched_banks:
                entry = session.get_loaded_entry(b_name)
                if entry is not None:
                    bank, _, diff_res = entry
                    self.bank_viewer_store.load_soundbank_instance(
                        b_name, bank, diff_result=diff_res
                    )

            # Restore view-state selection continuity
            if sel_bank and sel_bank in outcome.touched_banks:
                if len(sel_keys) > 1:
                    self.bank_viewer_store.select_nodes(sel_keys, primary_key=sel_key)
                elif sel_key:
                    self.bank_viewer_store.select_node(sel_key)
                if sel_key:
                    self.bank_viewer_store._resolve_node_details(sel_bank, sel_key)

    def _handle_audio_sources_enhance(
        self,
        targets: tuple[MutationTarget, ...],
        settings: AudioEnhanceSettings,
    ) -> None:
        """Applies configured audio enhancements to targets via WorkspaceSession."""
        from src.ui.features.audio_sources.causation import build_modifier_chain

        self._cached_base_wav = None
        session = self.bank_viewer_store.session
        sel_bank = self.bank_viewer_store.state.selected_bank_name
        sel_key = self.bank_viewer_store.state.selected_node_key
        sel_keys = self.bank_viewer_store.state.selected_node_keys

        chain = build_modifier_chain(settings)
        outcome = session.apply_audio_enhancements(targets, chain)
        if self.audio_sources_store is not None:
            self.audio_sources_store.receive_batch_outcome(outcome)

        if outcome.applied > 0 and self.bank_viewer_store.project is not None:
            self.bank_viewer_store.load_project(self.bank_viewer_store.project)
            for b_name in outcome.touched_banks:
                entry = session.get_loaded_entry(b_name)
                if entry is not None:
                    bank, _, diff_res = entry
                    self.bank_viewer_store.load_soundbank_instance(
                        b_name, bank, diff_result=diff_res
                    )

            if sel_bank and sel_bank in outcome.touched_banks:
                if len(sel_keys) > 1:
                    self.bank_viewer_store.select_nodes(sel_keys, primary_key=sel_key)
                elif sel_key:
                    self.bank_viewer_store.select_node(sel_key)
                if sel_key:
                    self.bank_viewer_store._resolve_node_details(sel_bank, sel_key)

    def _handle_audio_sources_preview(self, file_path: Path) -> None:
        """Selects an audition track in audio sources transport store for an external audio file."""
        track = AudioTrack(
            source_id=AudioSourceId(0),
            title=file_path.name,
            file_path=str(file_path),
        )
        if self.audio_sources_transport_store is not self.transport_store:
            if self.transport_store.state.status == PlaybackStatus.PLAYING:
                self.transport_store.stop()
        self.audio_sources_transport_store.select_track(track)

    def _handle_audio_sources_game_preview(self, entry: AudioCatalogEntry) -> None:
        """Resolves audition track in audio sources transport store for a game audio asset."""
        session = self.bank_viewer_store.session
        track = resolve_catalog_entry_audio_track(entry, session)
        if track is not None:
            if self.audio_sources_transport_store is not self.transport_store:
                if self.transport_store.state.status == PlaybackStatus.PLAYING:
                    self.transport_store.stop()
            self.audio_sources_transport_store.select_track(track)

    def wait_for_preview(self, timeout: float = 5.0) -> None:
        """Blocks until any in-flight background preview synthesis finishes (useful for testing)."""
        if self._preview_thread is not None and self._preview_thread.is_alive():
            self._preview_thread.join(timeout=timeout)

    def _handle_audio_sources_enhance_preview(
        self,
        target: MutationTarget,
        settings: AudioEnhanceSettings,
    ) -> None:
        """Resolves target sound from bank, applies configured DSP modifiers, and cues in audio sources transport."""
        from src.compiler.audio_modifiers import apply_modifiers_to_wav_bytes
        from src.engine.audio_export import resolve_node_wav_bytes
        from src.engine.ontology import MediaNodeTarget, MusicTrackTarget, SoundNodeTarget
        from src.ui.features.audio_sources.causation import build_modifier_chain

        session = self.bank_viewer_store.session
        if not target.bank_name:
            return

        entry = session.get_loaded_entry(target.bank_name)
        if entry is None:
            return
        bank, graph_index, _ = entry

        # Determine node key for audio extraction
        if isinstance(target, SoundNodeTarget):
            node_key = f"hirc:{target.sound_id}"
            target_label = f"Sound {target.sound_id}"
            src_id = target.sound_id
        elif isinstance(target, MediaNodeTarget):
            node_key = f"media:{target.wem_id}"
            target_label = f"WEM {target.wem_id}"
            src_id = target.wem_id
        elif isinstance(target, MusicTrackTarget):
            node_key = f"hirc:{target.track_id}"
            target_label = f"Track {target.track_id}"
            src_id = target.track_id
        else:
            return

        self._enhance_preview_seq += 1
        seq = self._enhance_preview_seq

        def _worker() -> None:
            cached = self._cached_base_wav
            if cached is not None and cached[0] == target.bank_name and cached[1] == node_key:
                wav_bytes = cached[2]
            else:
                try:
                    wav_bytes = resolve_node_wav_bytes(
                        bank,
                        node_key,
                        resolver=session.resolver,
                        graph_index=graph_index,
                    )
                except (ValueError, FileNotFoundError, RuntimeError, OSError):
                    return
                self._cached_base_wav = (target.bank_name, node_key, wav_bytes)

            if seq != self._enhance_preview_seq:
                return

            chain = build_modifier_chain(settings)
            if chain.is_empty():
                preview_wav = wav_bytes
            else:
                try:
                    preview_wav = apply_modifiers_to_wav_bytes(wav_bytes, chain)
                except Exception:
                    preview_wav = wav_bytes

            if seq != self._enhance_preview_seq:
                return

            parts = []
            if settings.gain_enabled and settings.gain_db != 0.0:
                parts.append(f"{settings.gain_db:+.1f} dB")
            if settings.normalize_enabled:
                parts.append(f"Norm {settings.target_peak_db:.1f} dBFS")
            if settings.match_loudness_enabled:
                parts.append(f"RMS {settings.target_rms_db:.1f} dBFS")

            mod_desc = f"({', '.join(parts)})" if parts else "(Original)"
            title = f"Enhance Preview: {target_label} {mod_desc}"

            track = AudioTrack(
                source_id=AudioSourceId(src_id),
                title=title,
                embedded_bytes=preview_wav,
            )

            if self.audio_sources_transport_store is not self.transport_store:
                if self.transport_store.state.status == PlaybackStatus.PLAYING:
                    self.transport_store.stop()
            self.audio_sources_transport_store.select_track(track)

        if self.async_preview:
            t = threading.Thread(target=_worker, daemon=True)
            self._preview_thread = t
            t.start()
        else:
            _worker()

    def _handle_audio_sources_clear_preview(self) -> None:
        """Clears the active audition track in the audio sources transport player."""
        self.audio_sources_transport_store.select_track(None)

    def _handle_load_game_audio(self) -> None:
        """Populates game audio catalog entries in AudioSourcesStore from the active soundbank."""
        if self.audio_sources_store is None:
            return

        bank_name = self.bank_viewer_store.state.selected_bank_name
        if not bank_name:
            avail = self.bank_viewer_store.state.available_banks
            bank_name = avail[0].name if avail else None

        if hasattr(bank_name, "name"):
            bank_name = bank_name.name

        if not isinstance(bank_name, str) or not bank_name:
            return

        try:
            _, catalog_provider = (
                self.bank_viewer_store.session.build_local_and_global_catalog_providers(bank_name)
            )
            entries = catalog_provider()
            self.audio_sources_store.set_game_audio_entries(entries)
        except (ValueError, KeyError, IndexError, RuntimeError, OSError):
            pass

    @property
    def can_undo(self) -> bool:
        """True if either an audio mutation or navigation history entry can be undone."""
        return bool(
            self.bank_viewer_store.can_undo_mutation
            or self.bank_viewer_store.state.can_navigate_back
        )

    @property
    def can_redo(self) -> bool:
        """True if either an audio mutation or navigation history entry can be redone."""
        return bool(
            self.bank_viewer_store.can_redo_mutation
            or self.bank_viewer_store.state.can_navigate_forward
        )

    @property
    def undo_status_tip(self) -> str:
        """Status tip describing the target of the undo operation."""
        if self.bank_viewer_store.can_undo_mutation:
            return "Undo last audio mutation"
        return "Undo last selection or view navigation"

    @property
    def redo_status_tip(self) -> str:
        """Status tip describing the target of the redo operation."""
        if self.bank_viewer_store.can_redo_mutation:
            return "Redo last audio mutation"
        return "Redo last selection or view navigation"

    def trigger_undo(self) -> None:
        """Triggers audio mutation undo if available, falling back to history navigation back."""
        self._cached_base_wav = None
        if self.bank_viewer_store.can_undo_mutation:
            self.bank_viewer_store.undo_mutation()
        elif self.bank_viewer_store.state.can_navigate_back:
            self.bank_viewer_store.navigate_back()

    def trigger_redo(self) -> None:
        """Triggers audio mutation redo if available, falling back to history navigation forward."""
        self._cached_base_wav = None
        if self.bank_viewer_store.can_redo_mutation:
            self.bank_viewer_store.redo_mutation()
        elif self.bank_viewer_store.state.can_navigate_forward:
            self.bank_viewer_store.navigate_forward()

    @property
    def active_project(self) -> AudioProject | None:
        """Returns the active AudioProject workspace instance if loaded."""
        return self._active_project

    def reload_project_dependencies(self) -> None:
        """
        Hot-reloads dependencies for the active project.
        Re-indexes metadata catalog, updates AssetResolver, refreshes available soundbanks,
        and clears preview caches across BankViewer and AudioSources stores.
        """
        if self._active_project is None:
            return

        proj = self._active_project
        self._cached_base_wav = None

        # 1. Clear session AST/WEM caches and viewer tree projections
        self.bank_viewer_store.session.reload_dependencies()
        self.bank_viewer_store.invalidate_caches()

        # 2. Refresh BankViewerStore project and available banks
        selected_bank = self.bank_viewer_store.state.selected_bank_name
        self.bank_viewer_store.load_project(proj)

        # 2. If a bank was currently selected, re-select it with fresh metadata
        if selected_bank and any(
            b.name == selected_bank for b in self.bank_viewer_store.state.available_banks
        ):
            self.bank_viewer_store.select_bank(selected_bank)

        # 3. Refresh AudioSourcesStore project and game audio catalog
        if self.audio_sources_store is not None:
            self.audio_sources_store.set_project(proj)
            self._handle_load_game_audio()

    def compile_mod_pack(
        self,
        output_path: Path | str | None = None,
        pack_type: int = 3,
    ) -> Path:
        """Compiles the active project into a PFH4 Mod pack (default PT_MOD = 3)."""
        if self._active_project is None:
            raise RuntimeError("Cannot compile pack: no active project.")
        return self._active_project.compile_mod_pack(
            output_path=output_path,
            pack_type=pack_type,
        )

    def compile_movie_pack(
        self,
        output_path: Path | str | None = None,
        pack_type: int = 3,
    ) -> Path:
        """Alias for compile_mod_pack (defaults to PT_MOD = 3)."""
        return self.compile_mod_pack(output_path=output_path, pack_type=pack_type)
