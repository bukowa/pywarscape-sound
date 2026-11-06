"""Headless unit tests for ShellStore."""

import ast
from pathlib import Path

from src.ui.shell.state import ScreenMode
from src.ui.shell.store import ShellStore
from src.workspace.game import GameType
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject


def test_no_qt_imports():
    """Verify shell state, causation, and store contain ZERO Qt imports via AST analysis."""
    pkg_dir = Path(__file__).parents[1] / "src" / "ui" / "shell"
    for py_file in (
        pkg_dir / "state.py",
        pkg_dir / "causation.py",
        pkg_dir / "store.py",
        pkg_dir / "coordinator.py",
    ):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(("PySide", "PyQt")), (
                        f"Qt import in {py_file.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert not node.module.startswith(("PySide", "PyQt")), (
                        f"Qt import in {py_file.name}"
                    )


def test_initial_state():
    store = ShellStore()
    assert store.state.screen_mode == ScreenMode.LAUNCHER
    assert store.state.active_project is None
    assert store.state.window_title == "PyWarscape Sound"
    assert store.state.is_workspace_active is False


def test_open_and_close_project():
    store = ShellStore()
    notifications = []
    store.subscribe(lambda s: notifications.append(s.screen_mode))

    proj = AudioProject(
        root_dir=Path("projects/MyMod"),
        manifest=ProjectManifest(name="MyMod", game=GameType.ATTILA),
    )

    store.open_project(proj)
    assert store.state.screen_mode == ScreenMode.WORKSPACE
    assert store.state.active_project == proj
    assert "MyMod" in store.state.window_title
    assert store.state.is_workspace_active is True

    store.close_project()
    assert store.state.screen_mode == ScreenMode.LAUNCHER
    assert store.state.active_project is None
    assert store.state.is_workspace_active is False
    assert notifications == [ScreenMode.WORKSPACE, ScreenMode.LAUNCHER]
