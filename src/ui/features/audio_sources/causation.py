"""
Pure deterministic causation and state transitions for the Audio Sources dock.
Implements the AXIOM Functional Core with zero I/O, zero Qt, and zero exceptions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, assert_never

from src.compiler.audio_modifiers import (
    AudioModifierChain,
    GainModifier,
    MatchReferenceLoudnessModifier,
    PeakNormalizeModifier,
)
from src.engine.ontology import (
    AudioReplacementSource,
    BatchItem,
    ExistingMediaReferenceSource,
    ExternalFileSource,
    MutationBatch,
    MutationTarget,
    SilentStubSource,
)
from src.models import AudioCatalogEntry
from src.ui.features.audio_sources.state import (
    ApplyMode,
    ApplyRequested,
    AudioEnhanceSettings,
    AudioSourcesEvent,
    AudioSourcesState,
    AudioSourcesTab,
    BatchOutcomeReceived,
    EnhancePreviewRequested,
    EnhanceRequested,
    EnhanceSettingsChanged,
    FileSelectionChanged,
    FilesLoaded,
    FilterChanged,
    GameAudioEntriesLoaded,
    GameAudioEntrySelected,
    LibrariesLoaded,
    LibraryRow,
    LibrarySelected,
    SilenceRequested,
    TabChanged,
    TargetsChanged,
)

# Re-export causation events
__all__ = [
    "ApplyBatchIntent",
    "ApplyEnhanceIntent",
    "ApplyMode",
    "ApplyRequested",
    "AudioEnhanceSettings",
    "AudioSourcesEvent",
    "AudioSourcesState",
    "AudioSourcesTab",
    "BatchOutcomeReceived",
    "ClearPreviewIntent",
    "EnhancePreviewRequested",
    "EnhanceRequested",
    "EnhanceSettingsChanged",
    "FileSelectionChanged",
    "FilesLoaded",
    "FilterChanged",
    "GameAudioEntriesLoaded",
    "GameAudioEntrySelected",
    "LibrariesLoaded",
    "LibraryRow",
    "LibrarySelected",
    "LoadGameAudioCatalogIntent",
    "PlayEnhancePreviewIntent",
    "PlayGameAudioPreviewIntent",
    "PlayPreviewIntent",
    "ScanLibraryIntent",
    "SilenceRequested",
    "TabChanged",
    "TargetsChanged",
    "build_batch",
    "build_modifier_chain",
    "reconcile",
]

# -----------------------------------------------------------------------------
# 1. Effect Intents (Outputs for Store Execution)
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LoadGameAudioCatalogIntent:
    """Instructs the store / coordinator to load game audio catalog entries."""


@dataclass(frozen=True, slots=True)
class ScanLibraryIntent:
    """Instructs the store to scan audio files inside a sound library directory."""

    library_id: str


@dataclass(frozen=True, slots=True)
class ApplyBatchIntent:
    """Instructs the store to execute an atomic MutationBatch via WorkspaceSession."""

    batch: MutationBatch


@dataclass(frozen=True, slots=True)
class ApplyEnhanceIntent:
    """Instructs the store / coordinator to apply audio enhancements in-place to targets."""

    targets: tuple[MutationTarget, ...]
    settings: AudioEnhanceSettings


@dataclass(frozen=True, slots=True)
class PlayPreviewIntent:
    """Instructs the store to route audio file playback to AudioTransport."""

    file_path: Path


@dataclass(frozen=True, slots=True)
class PlayGameAudioPreviewIntent:
    """Instructs the store / coordinator to route game audio asset playback to AudioTransport."""

    entry: AudioCatalogEntry


@dataclass(frozen=True, slots=True)
class PlayEnhancePreviewIntent:
    """Instructs the store / coordinator to audition target audio with DSP enhancements applied."""

    target: MutationTarget
    settings: AudioEnhanceSettings


@dataclass(frozen=True, slots=True)
class ClearPreviewIntent:
    """Instructs the store / coordinator to clear the active audition track in the transport player."""


# -----------------------------------------------------------------------------
# 3. Pure Helpers: build_batch & build_modifier_chain
# -----------------------------------------------------------------------------


def build_modifier_chain(settings: AudioEnhanceSettings) -> AudioModifierChain:
    """Constructs a deterministic AudioModifierChain from AudioEnhanceSettings."""
    mods = []
    if settings.gain_enabled and settings.gain_db != 0.0:
        mods.append(GainModifier(gain_db=settings.gain_db))
    if settings.match_loudness_enabled:
        mods.append(
            MatchReferenceLoudnessModifier(
                target_rms_db=settings.target_rms_db,
                max_boost_db=settings.max_boost_db,
            )
        )
    if settings.normalize_enabled:
        mods.append(PeakNormalizeModifier(target_peak_db=settings.target_peak_db))
    return AudioModifierChain(modifiers=tuple(mods))


def build_batch(
    targets: tuple[MutationTarget, ...],
    sources: tuple[AudioReplacementSource, ...],
    mode: ApplyMode,
) -> tuple[MutationBatch | None, str | None]:
    """
    Constructs an atomic MutationBatch pairing targets with sources.
    Returns (batch, None) on success, or (None, rejection_reason) on validation failure.
    """
    if not targets:
        return None, "No target nodes provided"
    if not sources:
        return None, "No audio sources provided"

    if mode == ApplyMode.ALL:
        first_source = sources[0]
        items = tuple(BatchItem(target=t, source=first_source) for t in targets)
        batch = MutationBatch(
            description=f"Apply audio to {len(targets)} target(s)",
            items=items,
        )
        return batch, None

    if mode == ApplyMode.DISTRIBUTE:
        if len(targets) != len(sources):
            return None, f"Count mismatch: {len(targets)} targets but {len(sources)} sources"
        items = tuple(BatchItem(target=t, source=s) for t, s in zip(targets, sources))
        batch = MutationBatch(
            description=f"Distribute {len(sources)} audio files across {len(targets)} target(s)",
            items=items,
        )
        return batch, None

    return None, f"Unsupported apply mode: {mode}"


# -----------------------------------------------------------------------------
# 4. Pure Function: reconcile
# -----------------------------------------------------------------------------


def reconcile(
    state: AudioSourcesState,
    event: AudioSourcesEvent,
) -> tuple[AudioSourcesState, tuple[Any, ...]]:
    """
    Pure state transition function (Functional Core).
    Computes the next state and required effect intents deterministically.
    """
    match event:
        case TabChanged(tab=tab):
            intents: list[Any] = []
            if tab == AudioSourcesTab.GAME_AUDIO and not state.game_audio_entries:
                intents.append(LoadGameAudioCatalogIntent())

            had_active_preview = (
                (
                    state.active_tab == AudioSourcesTab.LIBRARIES
                    and len(state.selected_file_paths) == 1
                )
                or (
                    state.active_tab == AudioSourcesTab.GAME_AUDIO
                    and state.selected_game_audio_entry is not None
                )
                or (state.active_tab == AudioSourcesTab.ENHANCE and bool(state.targets))
            )

            # Bind bottom player track to the newly active tab
            if tab == AudioSourcesTab.LIBRARIES:
                if len(state.selected_file_paths) == 1:
                    intents.append(PlayPreviewIntent(file_path=state.selected_file_paths[0]))
                elif had_active_preview:
                    intents.append(ClearPreviewIntent())
            elif tab == AudioSourcesTab.GAME_AUDIO:
                if state.selected_game_audio_entry is not None:
                    intents.append(
                        PlayGameAudioPreviewIntent(entry=state.selected_game_audio_entry)
                    )
                elif had_active_preview:
                    intents.append(ClearPreviewIntent())
            elif tab == AudioSourcesTab.ENHANCE:
                if state.targets:
                    intents.append(
                        PlayEnhancePreviewIntent(
                            target=state.targets[0],
                            settings=state.enhance_settings,
                        )
                    )
                elif had_active_preview:
                    intents.append(ClearPreviewIntent())

            return replace(state, active_tab=tab), tuple(intents)

        case GameAudioEntriesLoaded(entries=entries):
            return replace(state, game_audio_entries=entries), ()

        case GameAudioEntrySelected(entry=entry):
            preview_intents: tuple[Any, ...] = ()
            if entry is not None:
                preview_intents = (PlayGameAudioPreviewIntent(entry=entry),)
            elif state.selected_game_audio_entry is not None:
                preview_intents = (ClearPreviewIntent(),)
            return replace(state, selected_game_audio_entry=entry), preview_intents

        case LibrariesLoaded(libraries=libraries):
            return replace(state, libraries=libraries), ()

        case LibrarySelected(library_id=library_id):
            intents_lib: tuple[Any, ...] = ()
            if library_id:
                intents_lib = (ScanLibraryIntent(library_id=library_id),)
            return (
                replace(
                    state,
                    selected_library_id=library_id,
                    files=(),
                    selected_file_paths=(),
                ),
                intents_lib,
            )

        case FilesLoaded(files=files):
            return replace(state, files=files, selected_file_paths=()), ()

        case FilterChanged(filter_text=filter_text):
            return replace(state, filter_text=filter_text), ()

        case FileSelectionChanged(selected_file_paths=selected_file_paths):
            file_preview_intents: tuple[Any, ...] = ()
            if len(selected_file_paths) == 1:
                file_preview_intents = (PlayPreviewIntent(file_path=selected_file_paths[0]),)
            elif state.selected_file_paths:
                file_preview_intents = (ClearPreviewIntent(),)
            return replace(state, selected_file_paths=selected_file_paths), file_preview_intents

        case TargetsChanged(targets=targets):
            targets_intents: tuple[Any, ...] = ()
            if state.active_tab == AudioSourcesTab.ENHANCE:
                if targets:
                    targets_intents = (
                        PlayEnhancePreviewIntent(
                            target=targets[0],
                            settings=state.enhance_settings,
                        ),
                    )
                elif state.targets:
                    targets_intents = (ClearPreviewIntent(),)
            return replace(state, targets=targets), targets_intents

        case ApplyRequested(mode=mode):
            if not state.targets:
                return replace(state, status_message="No target nodes selected"), ()

            if state.active_tab == AudioSourcesTab.GAME_AUDIO:
                if not state.selected_game_audio_entry:
                    return replace(state, status_message="No game audio asset selected"), ()
                game_entry = state.selected_game_audio_entry
                game_sources = (
                    ExistingMediaReferenceSource(
                        wem_id=game_entry.wem_id,
                        source_bank=game_entry.source_bank,
                    ),
                )
                batch, error = build_batch(state.targets, game_sources, ApplyMode.ALL)
                if error:
                    return replace(state, status_message=error), ()
                if batch:
                    msg = f"Referencing game audio WEM {game_entry.wem_id} for {len(state.targets)} target(s)..."
                    return replace(state, status_message=msg), (ApplyBatchIntent(batch=batch),)
                return state, ()

            if state.active_tab == AudioSourcesTab.ENHANCE:
                return state, ()

            if not state.selected_file_paths:
                return replace(state, status_message="No source files selected"), ()

            sources = tuple(ExternalFileSource(file_path=p) for p in state.selected_file_paths)
            batch, error = build_batch(state.targets, sources, mode)
            if error:
                return replace(state, status_message=error), ()
            if batch:
                msg = f"Applying batch to {len(state.targets)} target(s)..."
                return replace(state, status_message=msg), (ApplyBatchIntent(batch=batch),)
            return state, ()

        case EnhanceSettingsChanged(settings=settings):
            intents_enh: tuple[Any, ...] = ()
            if state.targets and state.active_tab == AudioSourcesTab.ENHANCE:
                intents_enh = (
                    PlayEnhancePreviewIntent(
                        target=state.targets[0],
                        settings=settings,
                    ),
                )
            return replace(state, enhance_settings=settings), intents_enh

        case EnhancePreviewRequested(settings=settings):
            intents_prev: tuple[Any, ...] = ()
            if state.targets:
                intents_prev = (
                    PlayEnhancePreviewIntent(
                        target=state.targets[0],
                        settings=settings,
                    ),
                )
            return replace(state, enhance_settings=settings), intents_prev

        case EnhanceRequested(settings=settings):
            if not state.targets:
                return replace(state, status_message="No target nodes selected"), ()
            msg = f"Enhancing {len(state.targets)} target(s)..."
            return replace(state, status_message=msg, enhance_settings=settings), (
                ApplyEnhanceIntent(targets=state.targets, settings=settings),
            )

        case SilenceRequested():
            if not state.targets:
                return replace(state, status_message="No target nodes selected"), ()

            silence_sources = (SilentStubSource(),)
            batch, error = build_batch(state.targets, silence_sources, ApplyMode.ALL)
            if batch:
                msg = f"Muting {len(state.targets)} target(s)..."
                return replace(state, status_message=msg), (ApplyBatchIntent(batch=batch),)
            return state, ()

        case BatchOutcomeReceived(outcome=outcome):
            msg = f"Applied {outcome.applied} change(s)"
            if outcome.rejections:
                msg += f" ({len(outcome.rejections)} rejected)"
            return replace(state, last_outcome=outcome, status_message=msg), ()

        case _ as unreachable:
            assert_never(unreachable)
