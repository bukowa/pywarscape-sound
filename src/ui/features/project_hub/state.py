"""State models for the Project Hub feature slice in Audio Editor v3."""

from dataclasses import dataclass

from src.workspace.game import GameType


@dataclass(frozen=True, slots=True)
class RecentProjectItem:
    """Immutable metadata descriptor for a recently opened mod project."""

    name: str
    path: str
    game: str
    last_opened: str


@dataclass(frozen=True, slots=True)
class ProjectHubState:
    """Single source of truth for Project Hub view state."""

    recent_projects: tuple[RecentProjectItem, ...] = ()
    selected_game: GameType = GameType.ATTILA
    new_project_name: str = "MyAudioMod"
    new_project_location: str = ""
    status_message: str | None = None
    loaded_project_path: str | None = None
    game_path: str = ""
    is_game_path_valid: bool = False
    game_path_validation_msg: str | None = None
    is_cache_valid: bool = False
    cache_status_msg: str | None = None
    is_building_cache: bool = False
    cache_progress_text: str | None = None
    cache_progress_percentage: float = 0.0


# ==============================================================================
# Events & Commands
# ==============================================================================


@dataclass(frozen=True, slots=True)
class NewProjectNameSet:
    """Update draft mod project name."""

    name: str


@dataclass(frozen=True, slots=True)
class NewProjectLocationSet:
    """Update draft mod project parent location directory."""

    location: str


@dataclass(frozen=True, slots=True)
class SelectedGameChanged:
    """Update target Total War game engine."""

    game: GameType


@dataclass(frozen=True, slots=True)
class GamePathEvaluated:
    """Installation directory path validation result."""

    game_path: str
    is_game_path_valid: bool
    game_path_validation_msg: str | None
    is_cache_valid: bool
    cache_status_msg: str | None


@dataclass(frozen=True, slots=True)
class CacheBuildStarted:
    """Cache extraction process initiated."""

    pass


@dataclass(frozen=True, slots=True)
class CacheBuildProgressUpdated:
    """Cache extraction progress update."""

    progress_text: str
    progress_percentage: float


@dataclass(frozen=True, slots=True)
class CacheBuildFinished:
    """Cache extraction process completed or terminated with error."""

    is_cache_valid: bool
    cache_status_msg: str
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectOpenedSuccessfully:
    """Project opened or created and added to recent projects list."""

    recent_projects: tuple[RecentProjectItem, ...]
    loaded_project_path: str


@dataclass(frozen=True, slots=True)
class ProjectActionFailed:
    """Project creation, opening, or cache validation failed with an error message."""

    status_message: str


type ProjectHubEvent = (
    NewProjectNameSet
    | NewProjectLocationSet
    | SelectedGameChanged
    | GamePathEvaluated
    | CacheBuildStarted
    | CacheBuildProgressUpdated
    | CacheBuildFinished
    | ProjectOpenedSuccessfully
    | ProjectActionFailed
)


# ==============================================================================
# Effect Intents
# ==============================================================================


@dataclass(frozen=True, slots=True)
class NoOpProjectHubIntent:
    """Empty intent placeholder when no side effects are required."""

    pass


type ProjectHubIntent = NoOpProjectHubIntent
