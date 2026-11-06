"""Headless observable store managing Application Shell state and transitions."""

from collections.abc import Callable
from pathlib import Path

from src.ui.shell.causation import reconcile_shell
from src.ui.shell.state import (
    ProjectClosed,
    ProjectOpened,
    ShellEvent,
    ShellState,
    StatusMessageSet,
)
from src.workspace.project import AudioProject
from src.workspace.storage import ProjectStorage


class ShellStore:
    """Headless state manager and coordinator for the Application Shell."""

    def __init__(self, initial_state: ShellState | None = None) -> None:
        self._state = initial_state or ShellState()
        self._subscribers: list[Callable[[ShellState], None]] = []

    @property
    def state(self) -> ShellState:
        """Current immutable shell state."""
        return self._state

    def subscribe(self, callback: Callable[[ShellState], None]) -> None:
        """Register state listener."""
        self._subscribers.append(callback)

    def _dispatch(self, event: ShellEvent) -> None:
        """Observe -> Decide -> Apply sandwich."""
        new_state, _ = reconcile_shell(self._state, event)
        self._state = new_state
        for callback in list(self._subscribers):
            callback(self._state)

    def open_project(self, project: AudioProject) -> None:
        """Set an active AudioProject in the workspace."""
        self._dispatch(ProjectOpened(project=project))

    def close_project(self) -> None:
        """Close current workspace and return to project launcher."""
        self._dispatch(ProjectClosed())

    def set_status_message(self, message: str | None) -> None:
        """Update status bar text."""
        self._dispatch(StatusMessageSet(message=message))

    def open_project_by_path(self, path: Path | str) -> AudioProject | None:
        """Loads project from disk and transitions to workspace."""
        try:
            target = Path(path)
            project = ProjectStorage.open_project(target)
            self.open_project(project)
            return project
        except Exception as e:
            self.set_status_message(f"Failed to open project: {e}")
            return None
