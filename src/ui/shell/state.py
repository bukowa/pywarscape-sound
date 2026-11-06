"""Pure immutable data ontology for the Application Shell."""

from dataclasses import dataclass
from enum import Enum

from src.workspace.project import AudioProject


class ScreenMode(str, Enum):
    """Active primary screen mode in the application shell."""

    LAUNCHER = "launcher"
    WORKSPACE = "workspace"


@dataclass(frozen=True, slots=True, kw_only=True)
class ShellState:
    """Single source of truth for the top-level application shell."""

    screen_mode: ScreenMode = ScreenMode.LAUNCHER
    active_project: AudioProject | None = None
    window_title: str = "PyWarscape Sound"
    status_message: str | None = None

    @property
    def is_workspace_active(self) -> bool:
        """True when a project is open and active in the workspace."""
        return self.screen_mode == ScreenMode.WORKSPACE and self.active_project is not None


# ==============================================================================
# Events & Commands
# ==============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectOpened:
    """An AudioProject workspace was opened."""

    project: AudioProject


@dataclass(frozen=True, slots=True, kw_only=True)
class ProjectClosed:
    """The current project workspace was closed."""


@dataclass(frozen=True, slots=True, kw_only=True)
class StatusMessageSet:
    """Status message updated for display on status bar."""

    message: str | None


type ShellEvent = ProjectOpened | ProjectClosed | StatusMessageSet


# ==============================================================================
# Effect Intents
# ==============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class ShellLogIntent:
    """Request logging a message."""

    message: str


type ShellIntent = ShellLogIntent
