"""
Headless observable store for Audio Sources dock feature slice.
Implements the Imperative Shell (AXIOM Phase 2) with zero Qt imports.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from src.engine.ontology import BatchOutcome, MutationBatch, MutationTarget
from src.models import AudioCatalogEntry
from src.ui.features.audio_sources.causation import (
    ApplyBatchIntent,
    ApplyEnhanceIntent,
    ApplyRequested,
    BatchOutcomeReceived,
    ClearPreviewIntent,
    EnhancePreviewRequested,
    EnhanceRequested,
    EnhanceSettingsChanged,
    FileSelectionChanged,
    FilesLoaded,
    FilterChanged,
    GameAudioEntriesLoaded,
    GameAudioEntrySelected,
    LibrariesLoaded,
    LibrarySelected,
    LoadGameAudioCatalogIntent,
    PlayEnhancePreviewIntent,
    PlayGameAudioPreviewIntent,
    PlayPreviewIntent,
    ScanLibraryIntent,
    SilenceRequested,
    TabChanged,
    TargetsChanged,
    reconcile,
)
from src.ui.features.audio_sources.state import (
    ApplyMode,
    AudioEnhanceSettings,
    AudioSourcesState,
    AudioSourcesTab,
    LibraryRow,
)
from src.workspace.project import AudioProject
from src.workspace.sound_library import (
    LibraryFileEntry,
    is_library_available,
    scan_library,
)


class AudioSourcesStore:
    """Headless state store managing Sound Libraries, audio catalog, and batch intent dispatch."""

    def __init__(self) -> None:
        self._state: AudioSourcesState = AudioSourcesState()
        self._project: AudioProject | None = None
        self._scanned_libraries: dict[str, tuple[LibraryFileEntry, ...]] = {}
        self._subscribers: list[Callable[[AudioSourcesState], None]] = []
        self._batch_callbacks: list[Callable[[MutationBatch], None]] = []
        self._enhance_callbacks: list[
            Callable[[tuple[MutationTarget, ...], AudioEnhanceSettings], None]
        ] = []
        self._preview_callbacks: list[Callable[[Path], None]] = []
        self._preview_game_audio_callbacks: list[Callable[[AudioCatalogEntry], None]] = []
        self._preview_enhance_callbacks: list[
            Callable[[MutationTarget, AudioEnhanceSettings], None]
        ] = []
        self._clear_preview_callbacks: list[Callable[[], None]] = []
        self._load_catalog_callbacks: list[Callable[[], None]] = []

    @property
    def state(self) -> AudioSourcesState:
        """Returns the current immutable state snapshot."""
        return self._state

    @property
    def project(self) -> AudioProject | None:
        """Returns the active AudioProject, if set."""
        return self._project

    def subscribe(self, fn: Callable[[AudioSourcesState], None]) -> Callable[[], None]:
        """Registers a listener called on state changes and triggers initial render."""
        self._subscribers.append(fn)
        fn(self._state)

        def unsubscribe() -> None:
            if fn in self._subscribers:
                self._subscribers.remove(fn)

        return unsubscribe

    def on_batch_ready(self, cb: Callable[[MutationBatch], None]) -> None:
        """Registers a callback invoked when an atomic MutationBatch is ready to execute."""
        self._batch_callbacks.append(cb)

    def on_enhance_ready(
        self, cb: Callable[[tuple[MutationTarget, ...], AudioEnhanceSettings], None]
    ) -> None:
        """Registers a callback invoked when in-place audio enhancements should be applied."""
        self._enhance_callbacks.append(cb)

    def on_preview_file(self, cb: Callable[[Path], None]) -> None:
        """Registers a callback invoked when a single audio file is selected for audition."""
        self._preview_callbacks.append(cb)

    def on_preview_game_audio(self, cb: Callable[[AudioCatalogEntry], None]) -> None:
        """Registers a callback invoked when a game audio asset is selected for audition."""
        self._preview_game_audio_callbacks.append(cb)

    def on_preview_enhance(
        self, cb: Callable[[MutationTarget, AudioEnhanceSettings], None]
    ) -> None:
        """Registers a callback invoked when an enhanced target sound should be previewed."""
        self._preview_enhance_callbacks.append(cb)

    def on_clear_preview(self, cb: Callable[[], None]) -> None:
        """Registers a callback invoked when the audition track should be cleared."""
        self._clear_preview_callbacks.append(cb)

    def on_load_game_audio(self, cb: Callable[[], None]) -> None:
        """Registers a callback invoked when game audio catalog assets need to be loaded."""
        self._load_catalog_callbacks.append(cb)

    def preview_enhancements(self, settings: AudioEnhanceSettings) -> None:
        """Dispatches an explicit enhance preview request for currently active targets."""
        self.dispatch(EnhancePreviewRequested(settings=settings))

    def set_game_audio_entries(self, entries: Sequence[AudioCatalogEntry]) -> None:
        """Populates game audio catalog entries in state."""
        self.dispatch(GameAudioEntriesLoaded(entries=tuple(entries)))

    def select_game_audio_entry(self, entry: AudioCatalogEntry | None) -> None:
        """Selects a game audio catalog entry."""
        self.dispatch(GameAudioEntrySelected(entry=entry))

    def dispatch(self, event: Any) -> None:
        """Evolves state deterministically via causation and executes returned effect intents."""
        next_state, intents = reconcile(self._state, event)
        if next_state != self._state:
            self._state = next_state
            for subscriber in list(self._subscribers):
                subscriber(self._state)

        for intent in intents:
            self._execute_intent(intent)

    def _execute_intent(self, intent: Any) -> None:
        """Executes pure effect intents generated by causation transitions."""
        if isinstance(intent, ScanLibraryIntent):
            entries = self._scanned_libraries.get(intent.library_id)
            if entries is None and self._project is not None:
                for ref in self._project.list_sound_libraries():
                    if ref.id == intent.library_id:
                        entries = scan_library(self._project.root_dir, ref)
                        self._scanned_libraries[ref.id] = entries
                        break
            self.dispatch(FilesLoaded(files=entries or ()))
        elif isinstance(intent, ApplyBatchIntent):
            for cb in list(self._batch_callbacks):
                cb(intent.batch)
        elif isinstance(intent, ApplyEnhanceIntent):
            for cb in list(self._enhance_callbacks):
                cb(intent.targets, intent.settings)
        elif isinstance(intent, PlayPreviewIntent):
            for cb in list(self._preview_callbacks):
                cb(intent.file_path)
        elif isinstance(intent, PlayGameAudioPreviewIntent):
            for cb in list(self._preview_game_audio_callbacks):
                cb(intent.entry)
        elif isinstance(intent, PlayEnhancePreviewIntent):
            for cb in list(self._preview_enhance_callbacks):
                cb(intent.target, intent.settings)
        elif isinstance(intent, ClearPreviewIntent):
            for cb in list(self._clear_preview_callbacks):
                cb()
        elif isinstance(intent, LoadGameAudioCatalogIntent):
            for cb in list(self._load_catalog_callbacks):
                cb()

    def _load_libraries(self) -> None:
        """Scans registered libraries from project manifest and dispatches LibrariesLoaded."""
        if self._project is None:
            self._scanned_libraries.clear()
            self.dispatch(LibrariesLoaded(libraries=()))
            return

        rows: list[LibraryRow] = []
        for ref in self._project.list_sound_libraries():
            avail = is_library_available(self._project.root_dir, ref)
            if avail:
                if ref.id not in self._scanned_libraries:
                    self._scanned_libraries[ref.id] = scan_library(self._project.root_dir, ref)
                count = len(self._scanned_libraries[ref.id])
            else:
                count = 0
            rows.append(
                LibraryRow(
                    id=ref.id,
                    name=ref.name,
                    path=ref.path,
                    file_count=count,
                    is_available=avail,
                )
            )
        self.dispatch(LibrariesLoaded(libraries=tuple(rows)))

    def set_project(self, project: AudioProject | None) -> None:
        """Attaches an active AudioProject and loads registered sound libraries."""
        self._project = project
        self._scanned_libraries.clear()
        self._load_libraries()

    def set_targets(self, targets: Sequence[MutationTarget]) -> None:
        """Updates active target hierarchy nodes."""
        self.dispatch(TargetsChanged(targets=tuple(targets)))

    def set_active_tab(self, tab: AudioSourcesTab) -> None:
        """Switches active tab in Audio Sources dock."""
        self.dispatch(TabChanged(tab=tab))

    def add_library(self, dir_path: Path | str, name: str | None = None) -> None:
        """Registers a new sound library folder in the project and selects it."""
        if self._project is None:
            return
        ref = self._project.add_sound_library(dir_path, name)
        self._load_libraries()
        self.select_library(ref.id)

    def remove_library(self, library_id: str) -> None:
        """Removes a sound library folder from the project manifest."""
        if self._project is None:
            return
        self._scanned_libraries.pop(library_id, None)
        self._project.remove_sound_library(library_id)
        if self._state.selected_library_id == library_id:
            self.select_library(None)
        self._load_libraries()

    def rename_library(self, library_id: str, new_name: str) -> None:
        """Renames a registered sound library in the project manifest."""
        if self._project is None:
            return
        self._project.rename_sound_library(library_id, new_name)
        self._load_libraries()

    def select_library(self, library_id: str | None) -> None:
        """Selects a sound library row to display its contained audio files."""
        self.dispatch(LibrarySelected(library_id=library_id))

    def set_filter_text(self, text: str) -> None:
        """Updates search/filter query for audio files."""
        self.dispatch(FilterChanged(filter_text=text))

    def select_files(self, file_paths: Sequence[Path | str]) -> None:
        """Selects one or more audio files for replacement or preview."""
        paths = tuple(Path(p) if not isinstance(p, Path) else p for p in file_paths)
        self.dispatch(FileSelectionChanged(selected_file_paths=paths))

    def apply(self, mode: ApplyMode = ApplyMode.ALL) -> None:
        """Requests application of selected audio sources to target nodes."""
        self.dispatch(ApplyRequested(mode=mode))

    def apply_silence(self) -> None:
        """Requests muting selected target nodes with a silent stub."""
        self.dispatch(SilenceRequested())

    def set_enhance_settings(self, settings: AudioEnhanceSettings) -> None:
        """Updates in-place audio enhancement settings in state."""
        self.dispatch(EnhanceSettingsChanged(settings=settings))

    def apply_enhancements(self, settings: AudioEnhanceSettings | None = None) -> None:
        """Requests application of configured audio enhancements to target nodes."""
        s = settings if settings is not None else self._state.enhance_settings
        self.dispatch(EnhanceRequested(settings=s))

    def receive_batch_outcome(self, outcome: BatchOutcome) -> None:
        """Records mutation outcome received from WorkspaceSession."""
        self.dispatch(BatchOutcomeReceived(outcome=outcome))
