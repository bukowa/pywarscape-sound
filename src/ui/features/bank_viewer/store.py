"""Headless observable store managing SoundBank Viewer state and I/O effects."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, assert_never

from src.bnk.bank import SoundBank
from src.engine.diff import BankDiffResult
from src.engine.metadata_resolver import CompositeMetadataResolver
from src.engine.ontology import ReplacementScope
from src.engine.ports import AssetResolverPort
from src.engine.session import WorkspaceSession
from src.engine.wem_metadata import resolve_bank_wem_metadata
from src.ui.features.audio_transport.structs import AudioTrack
from src.ui.features.bank_viewer.audio_resolver import resolve_node_audio_track
from src.ui.features.bank_viewer.builder import (
    build_details_for_node,
    build_tree_and_details_from_bank,
)
from src.ui.features.bank_viewer.causation import reconcile_viewer
from src.ui.features.bank_viewer.columns import TreeColumn
from src.ui.features.bank_viewer.overlays import TreeOverlay
from src.ui.features.bank_viewer.state import (
    AvailableBanksDiscovered,
    BankCacheInvalidated,
    BankListItem,
    BankModificationKind,
    BankParsedSuccessfully,
    BankParseFailed,
    BankSearchQuerySet,
    BankSelectionRequested,
    BankStatus,
    BankViewerReset,
    BankViewerState,
    BankWemMetadataResolved,
    FilterModifiedOnlyToggled,
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

logger = logging.getLogger(__name__)


class BankViewerStore:
    """Headless state management and Imperative Shell for the SoundBank Viewer."""

    def __init__(
        self,
        project: Any | None = None,
        sound_db: Any | None = None,
        metadata_catalog: Any | None = None,
    ) -> None:
        self._session = WorkspaceSession(project=project, sound_db=sound_db)
        self._metadata_catalog = metadata_catalog
        self._metadata_resolver = CompositeMetadataResolver()
        self._subscribers: list[Callable[[BankViewerState], None]] = []
        self._state = BankViewerState()

        if project is not None:
            self.load_project(project)

    @property
    def session(self) -> WorkspaceSession:
        """Active WorkspaceSession domain façade."""
        return self._session

    @property
    def state(self) -> BankViewerState:
        """Current immutable state snapshot."""
        return self._state

    @property
    def project(self) -> Any | None:
        """Active AudioProject workspace instance."""
        return self._session.project

    @property
    def _project(self) -> Any | None:
        return self._session.project

    @_project.setter
    def _project(self, value: Any | None) -> None:
        self._session.set_project(value)

    @property
    def sound_db(self) -> Any | None:
        """Active SoundDatabase instance."""
        return self._session.sound_db

    @property
    def metadata_catalog(self) -> Any | None:
        """Active or cached AudioMetadataCatalog instance."""
        if self._metadata_catalog is not None:
            return self._metadata_catalog
        if self._session.project is not None and hasattr(
            self._session.project, "load_metadata_catalog"
        ):
            try:
                self._metadata_catalog = self._session.project.load_metadata_catalog()
                return self._metadata_catalog
            except (OSError, ValueError, KeyError, RuntimeError) as e:
                logger.debug("Failed to load metadata catalog: %s", e)
                return None
        return None

    @metadata_catalog.setter
    def metadata_catalog(self, value: Any | None) -> None:
        self._metadata_catalog = value

    @property
    def resolver(self) -> AssetResolverPort | None:
        """Active layered AssetResolver instance."""
        return self._session.resolver

    def get_loaded_bank(self, bank_name: str) -> SoundBank | None:
        """Returns the loaded SoundBank AST for the specified bank name if loaded."""
        return self._session.get_loaded_bank(bank_name)

    def subscribe(self, callback: Callable[[BankViewerState], None]) -> None:
        """Register a state listener."""
        self._subscribers.append(callback)

    def _dispatch(self, event: ViewerEvent) -> None:
        """Observe event -> Run pure causation -> Apply effects sandwich."""
        new_state, intents = reconcile_viewer(self._state, event)
        self._state = new_state
        for callback in self._subscribers:
            try:
                callback(self._state)
            except Exception:
                logger.exception("BankViewerStore subscriber callback raised unhandled exception")
                raise

        for intent in intents:
            self._apply_intent(intent)

    def _apply_intent(self, intent: ViewerIntent) -> None:
        """Execute effect intents via exhaustive pattern matching."""
        match intent:
            case LoadBankIntent(bank_name=bank_name):
                self._load_bank_data(bank_name)

            case ResolveNodeDetailsIntent(bank_name=bank_name, node_key=node_key):
                self._resolve_node_details(bank_name, node_key)

            case ResolveBankWemMetadataIntent(bank_name=bank_name):
                self._resolve_bank_wem_metadata(bank_name)

            case LogStatusIntent():
                pass

            case _ as unreachable:
                assert_never(unreachable)

    def _load_bank_data(self, bank_name: str) -> None:
        """Reads and parses SoundBank bytes into graph and projection models."""
        try:
            cached_entry = self._session.get_loaded_entry(bank_name)
            staged_wems = self._session.get_staged_wems()
            if cached_entry is not None:
                bank, graph_index, diff_res = cached_entry
                roots, nodes, details = build_tree_and_details_from_bank(
                    bank,
                    graph_index,
                    sound_db=self.sound_db,
                    diff_result=diff_res,
                    staged_wems=staged_wems,
                    bank_name=bank_name,
                    cross_bank_wem_refs_provider=self._session.get_cross_bank_wem_references,
                    metadata_catalog=self.metadata_catalog,
                    metadata_resolver=self._metadata_resolver,
                    asset_resolver=self.resolver,
                )
                self._dispatch(
                    BankParsedSuccessfully(
                        bank_name=bank_name,
                        root_keys=roots,
                        nodes_by_key=nodes,
                        details_by_key=details,
                    )
                )
                return

            bank, graph_index, diff_res = self._session.resolve_and_parse_bank(bank_name)
            roots, nodes, details = build_tree_and_details_from_bank(
                bank,
                graph_index,
                sound_db=self.sound_db,
                diff_result=diff_res,
                staged_wems=staged_wems,
                bank_name=bank_name,
                cross_bank_wem_refs_provider=self._session.get_cross_bank_wem_references,
                metadata_catalog=self.metadata_catalog,
                metadata_resolver=self._metadata_resolver,
                asset_resolver=self.resolver,
            )
            self._dispatch(
                BankParsedSuccessfully(
                    bank_name=bank_name,
                    root_keys=roots,
                    nodes_by_key=nodes,
                    details_by_key=details,
                )
            )
        except Exception as e:
            self._dispatch(BankParseFailed(bank_name=bank_name, error=str(e)))

    def _compute_bank_diff(self, bank_name: str, bank: SoundBank) -> BankDiffResult | None:
        """Computes diff between bank and baseline (vanilla cache / dependency)."""
        return self._session.compute_bank_diff(bank_name, bank)

    def _resolve_node_details(self, bank_name: str, node_key: str) -> None:
        """Resolves property inspector details on-demand for a single node."""
        cached_entry = self._session.get_loaded_entry(bank_name)
        if cached_entry is None:
            return
        bank, graph_index, _ = cached_entry
        details = build_details_for_node(
            bank,
            graph_index,
            node_key,
            sound_db=self.sound_db,
            bank_name=bank_name,
            cross_bank_wem_refs_provider=self._session.get_cross_bank_wem_references,
            metadata_catalog=self.metadata_catalog,
            metadata_resolver=self._metadata_resolver,
            staged_wems=self._session.get_staged_wems(),
            asset_resolver=self.resolver,
        )
        if details is not None:
            self._dispatch(NodeDetailsResolved(node_key=node_key, details=details))

    def _resolve_bank_wem_metadata(self, bank_name: str) -> None:
        """Resolves lazy WEM audio stream header metadata for audio-bearing nodes in the bank."""
        cached_entry = self._session.get_loaded_entry(bank_name)
        if cached_entry is None:
            return
        bank, _, _ = cached_entry
        meta_map = resolve_bank_wem_metadata(bank, resolver=self.resolver)
        self._dispatch(BankWemMetadataResolved(bank_name=bank_name, metadata_by_key=meta_map))

    def load_soundbank_instance(
        self,
        bank_name: str,
        bank: SoundBank,
        diff_result: BankDiffResult | None = None,
    ) -> None:
        """Directly indexes an in-memory SoundBank AST into viewer projection state."""
        try:
            bank, graph_index, diff_result = self._session.index_soundbank(
                bank_name, bank, diff_result=diff_result
            )
            staged_wems = self._session.get_staged_wems()
            roots, nodes, details = build_tree_and_details_from_bank(
                bank,
                graph_index,
                sound_db=self.sound_db,
                diff_result=diff_result,
                staged_wems=staged_wems,
                bank_name=bank_name,
                cross_bank_wem_refs_provider=self._session.get_cross_bank_wem_references,
                metadata_catalog=self.metadata_catalog,
                metadata_resolver=self._metadata_resolver,
                asset_resolver=self.resolver,
            )
            self._dispatch(
                BankParsedSuccessfully(
                    bank_name=bank_name,
                    root_keys=roots,
                    nodes_by_key=nodes,
                    details_by_key=details,
                )
            )
        except Exception as e:
            self._dispatch(BankParseFailed(bank_name=bank_name, error=str(e)))

    # -------------------------------------------------------------------------
    # Public Intent Handlers (Dispatched by UI or Caller)
    # -------------------------------------------------------------------------

    def set_available_banks(self, banks: tuple[BankListItem, ...]) -> None:
        """Sets the discovered soundbanks directly."""
        self._dispatch(AvailableBanksDiscovered(banks=banks))

    def load_project(self, project: Any) -> None:
        """Discovers SoundBanks in project overlay and game cache, calculating multi-factor modification status."""
        self._session.set_project(project)
        self._metadata_catalog = None
        self._metadata_resolver = CompositeMetadataResolver()

        # Collect staged loose WEMs
        staged_wems: set[int] = set()
        if hasattr(project, "manifest") and hasattr(project.manifest, "staged_wems"):
            staged_wems = set(int(w) for w in project.manifest.staged_wems)

        # 1. Overlay modified banks (on disk in pack_root/audio/ or in manifest)
        overlay_bank_names: set[str] = set()
        if hasattr(project, "audio_dir") and project.audio_dir.is_dir():
            for f in project.audio_dir.iterdir():
                if f.is_file() and f.name.lower().endswith(".bnk"):
                    overlay_bank_names.add(f.name.lower())
        if hasattr(project, "manifest") and hasattr(project.manifest, "modified_banks"):
            for b in project.manifest.modified_banks:
                b_clean = (b if b.lower().endswith(".bnk") else f"{b}.bnk").lower()
                overlay_bank_names.add(b_clean)

        # 2. Dependency banks
        dep_banks_map: dict[str, tuple[str, Path, int]] = {}
        if hasattr(project, "manifest") and hasattr(project.manifest, "dependencies"):
            sorted_deps = sorted(project.manifest.dependencies, key=lambda d: d.priority)
            for dep in sorted_deps:
                dep_audio_dir = project.get_dependency_dir(dep.name) / "audio"
                if dep_audio_dir.is_dir():
                    for f in dep_audio_dir.iterdir():
                        if f.is_file() and f.name.lower().endswith(".bnk"):
                            b_lower = f.name.lower()
                            if b_lower not in dep_banks_map:
                                dep_banks_map[b_lower] = (f.name, f, f.stat().st_size)

        # 3. Vanilla cache banks
        cache_banks_map: dict[str, tuple[str, Path | None, int]] = {}
        if hasattr(project, "cache") and project.cache is not None:
            for b in project.cache.list_banks():
                b_lower = b.lower()
                p = project.cache.get_bank_path(b)
                sz = p.stat().st_size if p and p.is_file() else 0
                cache_banks_map[b_lower] = (b, p, sz)

        # Assemble all unique bank names in priority order:
        all_bank_names: list[str] = []
        seen: set[str] = set()
        for b in sorted(overlay_bank_names):
            if b not in seen:
                all_bank_names.append(b)
                seen.add(b)
        for b in dep_banks_map:
            if b not in seen:
                all_bank_names.append(b)
                seen.add(b)
        for b in cache_banks_map:
            if b not in seen:
                all_bank_names.append(b)
                seen.add(b)

        records: list[BankListItem] = []
        for b_clean in all_bank_names:
            has_overlay_bnk = b_clean in overlay_bank_names
            bank_media_ids = self._session.get_bank_media_ids(b_clean)
            has_staged_media = bool(staged_wems and (bank_media_ids & staged_wems))

            if has_overlay_bnk:
                p = project.audio_dir / b_clean
                if not p.is_file() and hasattr(project, "audio_dir") and project.audio_dir.is_dir():
                    for f in project.audio_dir.iterdir():
                        if f.name.lower() == b_clean and f.is_file():
                            p = f
                            break
                sz = p.stat().st_size if p.is_file() else 0
                bank_display_name = b_clean
                bank_path = str(p)
            elif b_clean in dep_banks_map:
                bank_display_name, dep_path, sz = dep_banks_map[b_clean]
                bank_path = str(dep_path)
            elif b_clean in cache_banks_map:
                bank_display_name, cache_path, sz = cache_banks_map[b_clean]
                bank_path = str(cache_path) if cache_path else ""
            else:
                bank_display_name = b_clean
                bank_path = ""
                sz = 0

            if has_overlay_bnk and has_staged_media:
                status = BankStatus.MODIFIED
                kind = BankModificationKind.FULL
            elif has_overlay_bnk:
                status = BankStatus.MODIFIED
                kind = BankModificationKind.STRUCTURE
            elif has_staged_media:
                status = BankStatus.MODIFIED
                kind = BankModificationKind.AUDIO
            elif b_clean in dep_banks_map:
                status = BankStatus.DEPENDENCY
                kind = BankModificationKind.NONE
            else:
                status = BankStatus.VANILLA
                kind = BankModificationKind.NONE

            records.append(
                BankListItem(
                    name=bank_display_name,
                    status=status,
                    size_bytes=sz,
                    path=bank_path,
                    modification_kind=kind,
                )
            )

        self.set_available_banks(tuple(records))

    def get_staged_wems(self) -> frozenset[int]:
        """Returns frozenset of staged WEM IDs recorded in the active project manifest."""
        staged = self._session.get_staged_wems()
        return frozenset(staged) if staged else frozenset()

    def is_wem_modified(self, wem_id: int | str) -> bool:
        """Returns True if the specified WEM ID is staged in the project overlay."""
        return self._session.is_wem_modified(wem_id)

    def revert_bank(self, bank_name: str) -> tuple[int, int]:
        """Reverts modified SoundBank and its unshared loose WEMs to baseline."""
        prev_bank = self._state.selected_bank_name
        res = self._session.revert_bank(bank_name)
        self._dispatch(BankCacheInvalidated(bank_name=bank_name))
        if self._session.project is not None:
            self.load_project(self._session.project)
        if prev_bank and prev_bank.lower() == bank_name.lower():
            if any(b.name.lower() == bank_name.lower() for b in self._state.available_banks):
                self.select_bank(bank_name)
            else:
                self._dispatch(ViewerCachesInvalidated())
        return res

    def revert_wem(self, wem_id: int | str) -> bool:
        """Reverts loose .wem audio file and refreshes project and active bank."""
        wid = int(str(wem_id).removesuffix(".wem"))
        prev_node = self._state.selected_node_key
        res = self._session.revert_wem(wid)
        if self._state.selected_bank_name:
            self._dispatch(BankCacheInvalidated(bank_name=self._state.selected_bank_name))
        if self._session.project is not None:
            self.load_project(self._session.project)
        if self._state.selected_bank_name:
            self.select_bank(self._state.selected_bank_name)
            if prev_node:
                self.select_node(prev_node)
        return res

    def invalidate_caches(self) -> None:
        """Wipes all cached parsed bank trees and details."""
        self._dispatch(ViewerCachesInvalidated())

    def reset(self) -> None:
        """Resets the store back to initial blank state and clears memory cache."""
        self._session.reset()
        self._metadata_catalog = None
        self._metadata_resolver = CompositeMetadataResolver()
        self._dispatch(BankViewerReset())

    def load_bank_file(self, path: Path | str) -> None:
        """Opens and views a loose .bnk file directly from disk."""
        target = Path(path)
        if not target.is_file():
            self._dispatch(BankParseFailed(bank_name=target.name, error="File does not exist"))
            return
        try:
            data = target.read_bytes()
            bank = SoundBank.from_bytes(data)
            self.load_soundbank_instance(target.name, bank)
        except Exception as e:
            self._dispatch(BankParseFailed(bank_name=target.name, error=str(e)))

    def select_bank(self, bank_name: str) -> None:
        """Select a SoundBank to load and view."""
        self._dispatch(BankSelectionRequested(bank_name=bank_name))

    def set_bank_search_query(self, query: str) -> None:
        """Filter the SoundBank list."""
        self._dispatch(BankSearchQuerySet(query=query))

    def toggle_filter_modified_only(self, enabled: bool) -> None:
        """Toggle modified-only bank filter."""
        self._dispatch(FilterModifiedOnlyToggled(enabled=enabled))

    def set_tree_search_query(self, query: str) -> None:
        """Filter the HIRC hierarchy tree."""
        self._dispatch(TreeSearchQuerySet(query=query))

    def select_node(self, node_key: str | None) -> None:
        """Select a node in the hierarchy/chunk tree."""
        self._dispatch(NodeSelectionRequested(node_key=node_key))

    def select_nodes(self, node_keys: tuple[str, ...], primary_key: str | None = None) -> None:
        """Selects multiple nodes in the hierarchy/chunk tree."""
        self._dispatch(MultiNodeSelectionRequested(node_keys=node_keys, primary_key=primary_key))

    def jump_to_node(self, node_key: str, bank_name: str | None = None) -> None:
        """Jump to a specific node from an interactive reference link."""
        self._dispatch(JumpToNodeRequested(node_key=node_key, bank_name=bank_name))

    def navigate_back(self) -> None:
        """Navigate back to previously visited node in history."""
        self._dispatch(NavigateHistoryBackRequested())

    def navigate_forward(self) -> None:
        """Navigate forward to next visited node in history."""
        self._dispatch(NavigateHistoryForwardRequested())

    def set_tree_modified_filter(self, enabled: bool) -> None:
        """Toggles hierarchy tree filtering to show only modified nodes."""
        self._dispatch(TreeModifiedFilterToggled(filter_modified_only=enabled))

    def set_tree_overlay(self, overlay: TreeOverlay, enabled: bool) -> None:
        """Toggles an active hierarchy tree visual overlay."""
        self._dispatch(TreeOverlayToggled(overlay=overlay, enabled=enabled))

    def set_tree_column_visible(self, column: TreeColumn, visible: bool) -> None:
        """Toggles visibility of a hierarchy tree column."""
        self._dispatch(TreeColumnToggled(column=column, visible=visible))

    def resolve_audio_track(self, node_key: str | None) -> AudioTrack | None:
        """Resolves AudioTrack struct for playback if node is an audio leaf."""
        if not node_key or not self.state.selected_bank_name:
            return None
        bank_tuple = self._session.get_loaded_entry(self.state.selected_bank_name)
        if not bank_tuple:
            return None
        bank, graph_index, _ = bank_tuple
        return resolve_node_audio_track(
            bank,
            node_key,
            self.resolver,
            graph_index=graph_index,
            companion_cache=self._session.companion_banks,
        )

    # -------------------------------------------------------------------------
    # Audio Replacement & Mutation Actions
    # -------------------------------------------------------------------------

    @property
    def can_undo_mutation(self) -> bool:
        """True if there are audio mutations in the undo stack."""
        return self._session.can_undo_mutation

    @property
    def can_redo_mutation(self) -> bool:
        """True if there are audio mutations in the redo stack."""
        return self._session.can_redo_mutation

    def _apply_sound_mutation(
        self,
        sound_id: int,
        source: Any,
        scope: ReplacementScope = ReplacementScope.OVERWRITE,
    ) -> bool:
        """Plans and executes a sound node mutation, refreshing diff, tree, and project state."""
        if not self.state.selected_bank_name or self.project is None:
            return False
        bank_name = self.state.selected_bank_name
        res = self._session.apply_sound_mutation(bank_name, sound_id, source, scope=scope)
        if res is not None:
            bank, diff_res, node_key = res
            self.load_project(self.project)
            self.load_soundbank_instance(bank_name, bank, diff_result=diff_res)
            self._resolve_node_details(bank_name, node_key)
            self.select_node(node_key)
            return True
        return False

    def _apply_media_mutation(self, wem_id: int, source: Any) -> bool:
        """Plans and executes an embedded or loose media replacement, staging loose WEM assets."""
        if not self.state.selected_bank_name or self.project is None:
            return False
        bank_name = self.state.selected_bank_name
        res = self._session.apply_media_mutation(bank_name, wem_id, source)
        if res is not None:
            bank, diff_res, node_key = res
            self.load_project(self.project)
            self.load_soundbank_instance(bank_name, bank, diff_result=diff_res)
            self._resolve_node_details(bank_name, node_key)
            self.select_node(node_key)
            return True
        return False

    def mute_media(self, wem_id: int) -> bool:
        """Mutes embedded media WEM using silent PCM stub."""
        from src.engine.ontology import SilentStubSource

        return self._apply_media_mutation(wem_id, SilentStubSource(stub_wem_id=wem_id))

    def undo_mutation(self) -> bool:
        """Reverses the last applied sound or media mutation."""
        if not self.can_undo_mutation or self.project is None:
            return False

        res = self._session.undo_mutation()
        if res is not None:
            touched_banks, node_key = res
            all_keys = self._session.last_undone_node_keys
            self.load_project(self.project)
            for b_name in touched_banks:
                entry = self._session.get_loaded_entry(b_name)
                if entry is not None:
                    bank, _, diff_res = entry
                    self.load_soundbank_instance(b_name, bank, diff_result=diff_res)
            if all_keys and touched_banks:
                primary_bank = touched_banks[0]
                if len(all_keys) > 1:
                    self.select_nodes(all_keys, primary_key=all_keys[0])
                else:
                    self.select_node(all_keys[0])
                self._resolve_node_details(primary_bank, all_keys[0])
            elif node_key and touched_banks:
                primary_bank = touched_banks[0]
                self._resolve_node_details(primary_bank, node_key)
                self.select_node(node_key)
            return True
        return False

    def redo_mutation(self) -> bool:
        """Re-applies the last undone sound or media mutation."""
        if not self.can_redo_mutation or self.project is None:
            return False

        res = self._session.redo_mutation()
        if res is not None:
            touched_banks, node_key = res
            all_keys = self._session.last_redone_node_keys
            self.load_project(self.project)
            for b_name in touched_banks:
                entry = self._session.get_loaded_entry(b_name)
                if entry is not None:
                    bank, _, diff_res = entry
                    self.load_soundbank_instance(b_name, bank, diff_result=diff_res)
            if all_keys and touched_banks:
                primary_bank = touched_banks[-1]
                if len(all_keys) > 1:
                    self.select_nodes(all_keys, primary_key=all_keys[-1])
                else:
                    self.select_node(all_keys[-1])
                self._resolve_node_details(primary_bank, all_keys[-1])
            elif node_key and touched_banks:
                primary_bank = touched_banks[-1]
                self._resolve_node_details(primary_bank, node_key)
                self.select_node(node_key)
            return True
        return False

    def replace_sound_audio(
        self,
        sound_id: int,
        file_path: Path | str,
        scope: ReplacementScope = ReplacementScope.OVERWRITE,
    ) -> bool:
        """Replaces audio for sound node with an external file and stages assets."""
        from src.engine.ontology import ExternalFileSource

        return self._apply_sound_mutation(
            sound_id, ExternalFileSource(file_path=Path(file_path)), scope=scope
        )

    def mute_sound(self, sound_id: int) -> bool:
        """Mutes sound node using standard silent 1.wem stub."""
        from src.engine.ontology import SilentStubSource

        return self._apply_sound_mutation(sound_id, SilentStubSource(stub_wem_id=1))

    def mute_nodes(self, node_keys: Sequence[str]) -> bool:
        """Mutes multiple sound or media nodes using silent stubs in an atomic transaction."""
        from src.engine.ontology import (
            BatchItem,
            MediaNodeTarget,
            MusicTrackTarget,
            MutationBatch,
            SilentStubSource,
            SoundNodeTarget,
        )

        if not self.state.selected_bank_name or self.project is None or not node_keys:
            return False

        bank_name = self.state.selected_bank_name
        items: list[BatchItem] = []
        for key in node_keys:
            if not key:
                continue
            if key.startswith("media:"):
                try:
                    wem_id = int(key.removeprefix("media:"))
                    target = MediaNodeTarget(bank_name=bank_name, wem_id=wem_id)
                    items.append(
                        BatchItem(target=target, source=SilentStubSource(stub_wem_id=wem_id))
                    )
                except ValueError:
                    pass
            elif key.startswith("hirc:"):
                try:
                    node = self.state.nodes_by_key.get(key)
                    raw_id = node.id_str if (node and node.id_str) else key.removeprefix("hirc:")
                    hirc_id = int(raw_id)
                    if node and node.type_str == "MusicTrack":
                        target = MusicTrackTarget(bank_name=bank_name, track_id=hirc_id)
                    else:
                        target = SoundNodeTarget(bank_name=bank_name, sound_id=hirc_id)
                    items.append(BatchItem(target=target, source=SilentStubSource(stub_wem_id=1)))
                except ValueError:
                    pass

        if not items:
            return False

        batch = MutationBatch(
            description=f"Mute {len(items)} selected node(s) in {bank_name}",
            items=tuple(items),
        )
        outcome = self._session.apply_batch(batch)
        if outcome.applied > 0:
            self.load_project(self.project)
            for b_name in outcome.touched_banks:
                entry = self._session.get_loaded_entry(b_name)
                if entry is not None:
                    bank, _, diff_res = entry
                    self.load_soundbank_instance(b_name, bank, diff_result=diff_res)
            primary_key = node_keys[0]
            if len(node_keys) > 1:
                self.select_nodes(tuple(node_keys), primary_key=primary_key)
            else:
                self.select_node(primary_key)
            self._resolve_node_details(bank_name, primary_key)
            return True
        return False

    def reference_sound_media(self, sound_id: int, target_wem_id: int) -> bool:
        """Retargets sound node to an existing media ID."""
        from src.engine.ontology import ExistingMediaReferenceSource

        return self._apply_sound_mutation(
            sound_id, ExistingMediaReferenceSource(wem_id=target_wem_id)
        )

    def apply_sound_mutation(
        self,
        sound_id: int,
        source: Any,
        scope: ReplacementScope = ReplacementScope.OVERWRITE,
    ) -> bool:
        """Public interface for applying a sound node audio replacement."""
        return self._apply_sound_mutation(sound_id, source, scope=scope)

    def apply_media_mutation(self, wem_id: int, source: Any) -> bool:
        """Public interface for applying an embedded or loose media replacement."""
        return self._apply_media_mutation(wem_id, source)

    def extract_sound_wem_id(self, sound: Any) -> int:
        """Extracts the underlying WEM ID from a CAkSound object."""
        return self._session.extract_sound_wem_id(sound)

    def build_local_and_global_catalog_providers(
        self, bank_name: str
    ) -> tuple[tuple[Any, ...], Callable[[], Sequence[Any]]]:
        """Builds local bank catalog items and lazy global library catalog provider for replacement dialog."""
        return self._session.build_local_and_global_catalog_providers(bank_name)

    def export_node_to_wav(self, node_key: str, destination: Path | str) -> Path:
        """Exports audio from a bank node to a WAV file on disk."""
        from src.engine.audio_export import export_node_to_wav

        if not self.state.selected_bank_name:
            raise RuntimeError("No soundbank currently selected.")
        bank_name = self.state.selected_bank_name
        bank_entry = self._session.get_loaded_entry(bank_name)
        if bank_entry is None:
            raise RuntimeError(f"SoundBank '{bank_name}' is not loaded.")
        bank, graph_index, _ = bank_entry
        return export_node_to_wav(
            bank,
            node_key,
            Path(destination),
            resolver=self.resolver,
            graph_index=graph_index,
            companion_cache=self._session.companion_banks,
        )

    def export_nodes_to_directory(self, node_keys: Sequence[str], output_dir: Path | str) -> int:
        """Batch-exports multiple bank nodes to WAV files in a directory."""
        from src.engine.audio_export import export_nodes_to_directory

        if not self.state.selected_bank_name:
            raise RuntimeError("No soundbank currently selected.")
        bank_name = self.state.selected_bank_name
        bank_entry = self._session.get_loaded_entry(bank_name)
        if bank_entry is None:
            raise RuntimeError(f"SoundBank '{bank_name}' is not loaded.")
        bank, graph_index, _ = bank_entry
        return export_nodes_to_directory(
            bank,
            node_keys,
            Path(output_dir),
            resolver=self.resolver,
            graph_index=graph_index,
            companion_cache=self._session.companion_banks,
        )
