"""State models for the Project Wizard feature slice in Audio Editor v3."""

from dataclasses import dataclass
from enum import Enum

from src.workspace.game import GameType
from src.workspace.project import AudioProject


class WizardStep(str, Enum):
    """Active step in the multi-step project onboarding wizard."""

    SETUP = "setup"
    MOD_PACKS = "mod_packs"
    PROGRESS = "progress"


@dataclass(frozen=True, slots=True)
class ModPackEntry:
    """Descriptor for a selected base mod pack file."""

    path: str
    filename: str
    size_bytes: int
    repaired_files: tuple[tuple[str, bytes], ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectWizardState:
    """Single source of truth for the Project Wizard feature slice."""

    # Wizard navigation
    step: WizardStep = WizardStep.SETUP

    # Step 1: Game & Project Configuration
    selected_game: GameType = GameType.ATTILA
    game_path: str = ""
    is_game_path_valid: bool = False
    game_path_validation_msg: str = ""
    is_cache_valid: bool = False
    project_name: str = "MyAudioMod"
    project_location: str = ""
    is_target_dir_available: bool = True
    target_dir_validation_msg: str = ""

    # Step 2: Base Mod Packs
    mod_packs: tuple[ModPackEntry, ...] = ()
    import_db_tables: bool = True

    # Step 3: Ingestion Progress & Status
    progress_percentage: float = 0.0
    progress_text: str = ""
    is_working: bool = False
    status_message: str | None = None
    created_project: AudioProject | None = None


# ==============================================================================
# Events & Commands
# ==============================================================================


@dataclass(frozen=True, slots=True)
class WizardStepTransitionRequested:
    """Request navigation to a target wizard step."""

    step: WizardStep


@dataclass(frozen=True, slots=True)
class WizardGameValidationUpdated:
    """Update game installation directory validation state."""

    selected_game: GameType
    game_path: str
    is_game_path_valid: bool
    game_path_validation_msg: str
    is_cache_valid: bool


@dataclass(frozen=True, slots=True)
class WizardProjectNameUpdated:
    """Update draft mod project name and destination availability."""

    project_name: str
    is_target_dir_available: bool
    target_dir_validation_msg: str


@dataclass(frozen=True, slots=True)
class WizardProjectLocationUpdated:
    """Update draft mod project destination directory and availability."""

    project_location: str
    is_target_dir_available: bool
    target_dir_validation_msg: str


@dataclass(frozen=True, slots=True)
class WizardImportDbTablesToggled:
    """Toggle whether database tables are ingested alongside audio files."""

    enabled: bool


@dataclass(frozen=True, slots=True)
class WizardModPackAdded:
    """Append a validated external .pack dependency."""

    entry: ModPackEntry


@dataclass(frozen=True, slots=True)
class WizardModPackRemoved:
    """Remove a mod pack at the specified index."""

    index: int


@dataclass(frozen=True, slots=True)
class WizardModPackMoved:
    """Reorder a mod pack (-1 for UP, +1 for DOWN)."""

    index: int
    direction: int


@dataclass(frozen=True, slots=True)
class WizardStatusMessageSet:
    """Update the status or error message banner."""

    status_message: str | None


@dataclass(frozen=True, slots=True)
class WizardWorkProgressUpdated:
    """Update work status, progress percentage, and created project reference."""

    step: WizardStep
    is_working: bool
    progress_percentage: float
    progress_text: str
    status_message: str | None = None
    is_cache_valid: bool | None = None
    created_project: AudioProject | None = None


type ProjectWizardEvent = (
    WizardStepTransitionRequested
    | WizardGameValidationUpdated
    | WizardProjectNameUpdated
    | WizardProjectLocationUpdated
    | WizardImportDbTablesToggled
    | WizardModPackAdded
    | WizardModPackRemoved
    | WizardModPackMoved
    | WizardStatusMessageSet
    | WizardWorkProgressUpdated
)


# ==============================================================================
# Effect Intents
# ==============================================================================


@dataclass(frozen=True, slots=True)
class NoOpProjectWizardIntent:
    """Empty intent placeholder when no side effects are required."""

    pass


type ProjectWizardIntent = NoOpProjectWizardIntent
