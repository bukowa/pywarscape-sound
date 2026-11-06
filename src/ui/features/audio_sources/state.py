"""
Pure immutable state model for the Audio Sources dock.
Follows strict algebraic data modeling with zero Qt imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src.engine.ontology import BatchOutcome, MutationTarget
from src.models import AudioCatalogEntry
from src.workspace.sound_library import LibraryFileEntry


class ApplyMode(Enum):
    """Audio replacement application strategy."""

    ALL = "all"
    DISTRIBUTE = "distribute"


class AudioSourcesTab(Enum):
    """Available primary tabs in the Audio Sources dock."""

    LIBRARIES = 0
    GAME_AUDIO = 1
    ENHANCE = 2


@dataclass(frozen=True, slots=True)
class AudioEnhanceSettings:
    """Configuration parameters for in-place audio enhancement modifiers."""

    gain_enabled: bool = False
    gain_db: float = 0.0
    normalize_enabled: bool = False
    target_peak_db: float = -1.0
    match_loudness_enabled: bool = False
    target_rms_db: float = -14.0
    max_boost_db: float = 12.0


@dataclass(frozen=True, slots=True)
class LibraryRow:
    """Row model representing a configured sound library."""

    id: str
    name: str
    path: str
    file_count: int = 0
    is_available: bool = True


@dataclass(frozen=True, slots=True)
class AudioSourcesState:
    """Immutable state snapshot for the Audio Sources dock."""

    active_tab: AudioSourcesTab = AudioSourcesTab.LIBRARIES
    libraries: tuple[LibraryRow, ...] = ()
    selected_library_id: str | None = None
    files: tuple[LibraryFileEntry, ...] = ()
    filter_text: str = ""
    selected_file_paths: tuple[Path, ...] = ()
    targets: tuple[MutationTarget, ...] = ()
    game_audio_entries: tuple[AudioCatalogEntry, ...] = ()
    selected_game_audio_entry: AudioCatalogEntry | None = None
    enhance_settings: AudioEnhanceSettings = AudioEnhanceSettings()
    last_outcome: BatchOutcome | None = None
    status_message: str | None = None


# -----------------------------------------------------------------------------
# Causation Events
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TabChanged:
    """User switched between Libraries, Game Audio, or Silence tabs."""

    tab: AudioSourcesTab


@dataclass(frozen=True, slots=True)
class LibrariesLoaded:
    """Sound libraries refreshed from project manifest."""

    libraries: tuple[LibraryRow, ...]


@dataclass(frozen=True, slots=True)
class LibrarySelected:
    """User selected a sound library folder row or cleared selection."""

    library_id: str | None


@dataclass(frozen=True, slots=True)
class FilesLoaded:
    """Audio files loaded for the currently active sound library."""

    files: tuple[LibraryFileEntry, ...]


@dataclass(frozen=True, slots=True)
class FilterChanged:
    """User entered text to filter the current audio file list."""

    filter_text: str


@dataclass(frozen=True, slots=True)
class FileSelectionChanged:
    """User selected one or more files in the active source view."""

    selected_file_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class TargetsChanged:
    """Active target hierarchy nodes updated from BankViewer selection."""

    targets: tuple[MutationTarget, ...]


@dataclass(frozen=True, slots=True)
class ApplyRequested:
    """User clicked Apply (ALL or DISTRIBUTE) to replace targets with sources."""

    mode: ApplyMode


@dataclass(frozen=True, slots=True)
class SilenceRequested:
    """User clicked Silence to mute selected target nodes with a silent stub."""


@dataclass(frozen=True, slots=True)
class EnhanceSettingsChanged:
    """User updated enhancement settings in the Enhance tab."""

    settings: AudioEnhanceSettings


@dataclass(frozen=True, slots=True)
class EnhancePreviewRequested:
    """User requested an audition preview of configured DSP enhancements in the Enhance tab."""

    settings: AudioEnhanceSettings


@dataclass(frozen=True, slots=True)
class EnhanceRequested:
    """User clicked Apply Enhancements in the Enhance tab."""

    settings: AudioEnhanceSettings


@dataclass(frozen=True, slots=True)
class BatchOutcomeReceived:
    """Batch mutation applied by session, updating last outcome state."""

    outcome: BatchOutcome


@dataclass(frozen=True, slots=True)
class GameAudioEntriesLoaded:
    """Catalog of reusable game audio assets loaded from game soundbanks."""

    entries: tuple[AudioCatalogEntry, ...]


@dataclass(frozen=True, slots=True)
class GameAudioEntrySelected:
    """User selected a game audio catalog entry."""

    entry: AudioCatalogEntry | None


type AudioSourcesEvent = (
    TabChanged
    | LibrariesLoaded
    | LibrarySelected
    | FilesLoaded
    | FilterChanged
    | FileSelectionChanged
    | TargetsChanged
    | ApplyRequested
    | SilenceRequested
    | EnhanceSettingsChanged
    | EnhancePreviewRequested
    | EnhanceRequested
    | BatchOutcomeReceived
    | GameAudioEntriesLoaded
    | GameAudioEntrySelected
)
