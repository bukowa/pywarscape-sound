"""Application Shell package for Audio Editor v3."""

from src.ui.shell.coordinator import WorkspaceCoordinator
from src.ui.shell.state import ScreenMode, ShellState
from src.ui.shell.store import ShellStore
from src.ui.shell.view import MainWindow

__all__ = ["MainWindow", "ScreenMode", "ShellState", "ShellStore", "WorkspaceCoordinator"]
