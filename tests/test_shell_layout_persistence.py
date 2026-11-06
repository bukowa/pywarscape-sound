"""Tests for UI tool layout persistence to gitignored settings.json."""

import json
from pathlib import Path

import pytest

from src.ui.shell.store import ShellStore
from src.ui.shell.view import MainWindow
from src.workspace.game import GameType
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject


def _create_dummy_project(tmp_path: Path, name: str = "TestLayoutMod") -> AudioProject:
    proj_dir = tmp_path / name
    proj_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = proj_dir / "pack_root" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    manifest = ProjectManifest(name=name, game=GameType.ATTILA)
    return AudioProject(root_dir=proj_dir, manifest=manifest)


def test_settings_json_is_in_gitignore():
    """Verify settings.json is explicitly in .gitignore."""
    repo_root = Path(__file__).resolve().parents[1]
    gitignore_path = repo_root / ".gitignore"
    assert gitignore_path.is_file(), ".gitignore must exist in repo root"
    content = gitignore_path.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines()]
    assert "settings.json" in lines, "settings.json must be present in .gitignore"


def test_settings_file_created_and_persisted_on_close(qapp, tmp_path: Path):
    """Verify window layout is persisted to custom settings.json on closeEvent."""
    settings_file = tmp_path / "settings.json"
    assert not settings_file.exists()

    shell_store = ShellStore()
    window = MainWindow(shell_store, settings_file=settings_file)
    window.close()

    assert settings_file.is_file()
    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert "ui_layout" in data
    layout = data["ui_layout"]
    assert "geometry" in layout
    assert "state" in layout
    assert "bank_viewer_splitter" in layout
    assert "audio_sources_splitter" in layout


def test_existing_settings_preserved_when_saving_layout(qapp, tmp_path: Path):
    """Verify existing user settings like attila_path are never overwritten."""
    settings_file = tmp_path / "settings.json"
    original_data = {
        "attila_path": "C:/Games/Total War Attila",
        "rome2_path": "C:/Games/Total War Rome II",
        "wwise_cli": "C:/Wwise/bin/WwiseCLI.exe",
    }
    settings_file.write_text(json.dumps(original_data, indent=2), encoding="utf-8")

    shell_store = ShellStore()
    window = MainWindow(shell_store, settings_file=settings_file)
    window.close()

    data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert data["attila_path"] == "C:/Games/Total War Attila"
    assert data["rome2_path"] == "C:/Games/Total War Rome II"
    assert data["wwise_cli"] == "C:/Wwise/bin/WwiseCLI.exe"
    assert "ui_layout" in data
    assert "geometry" in data["ui_layout"]


def test_workspace_dock_layout_restored_across_sessions(qapp, tmp_path: Path):
    """Verify that toggling Audio Sources dock in workspace persists across sessions."""
    settings_file = tmp_path / "settings.json"
    proj = _create_dummy_project(tmp_path, "SessionMod")

    # Session 1: Open project, hide Audio Sources dock, close window
    shell_store_1 = ShellStore()
    window_1 = MainWindow(shell_store_1, settings_file=settings_file)
    shell_store_1.open_project(proj)

    # In workspace, Audio Sources is open by default; hide it
    assert not window_1.audio_sources_dock.isHidden()
    window_1.audio_sources_dock.hide()
    assert window_1.audio_sources_dock.isHidden()

    window_1.close()

    # Session 2: Launch with same settings_file
    shell_store_2 = ShellStore()
    window_2 = MainWindow(shell_store_2, settings_file=settings_file)

    # In launcher, docks remain hidden
    assert window_2.audio_sources_dock.isHidden()

    # Open project into workspace
    shell_store_2.open_project(proj)

    # In workspace, Audio Sources dock is restored to hidden!
    assert window_2.audio_sources_dock.isHidden()

    window_2.close()


def test_splitter_states_restored_across_sessions(qapp, tmp_path: Path):
    """Verify splitters in bank viewer and audio sources restore their exact sizes."""
    settings_file = tmp_path / "settings.json"
    proj = _create_dummy_project(tmp_path, "SplitterMod")

    # Session 1: Open project, adjust splitter sizes, close window
    shell_store_1 = ShellStore()
    window_1 = MainWindow(shell_store_1, settings_file=settings_file)
    shell_store_1.open_project(proj)

    window_1.bank_viewer_view.splitter.setSizes([320, 500, 420])
    window_1.audio_sources_view.splitter.setSizes([180, 310])
    expected_bv_sizes = window_1.bank_viewer_view.splitter.sizes()
    expected_as_sizes = window_1.audio_sources_view.splitter.sizes()

    window_1.close()

    # Session 2: Open project and check restored splitter sizes
    shell_store_2 = ShellStore()
    window_2 = MainWindow(shell_store_2, settings_file=settings_file)
    shell_store_2.open_project(proj)

    assert window_2.bank_viewer_view.splitter.sizes() == expected_bv_sizes
    assert window_2.audio_sources_view.splitter.sizes() == expected_as_sizes

    window_2.close()


def test_dock_layout_saved_on_project_close_before_launcher(qapp, tmp_path: Path):
    """Verify closing project preserves workspace dock state and does not overwrite with hidden docks."""
    settings_file = tmp_path / "settings.json"
    proj = _create_dummy_project(tmp_path, "CloseProjMod")

    shell_store = ShellStore()
    window = MainWindow(shell_store, settings_file=settings_file)
    shell_store.open_project(proj)

    # In workspace, hide Audio Sources
    window.audio_sources_dock.hide()
    assert window.audio_sources_dock.isHidden()

    # Close project (back to launcher)
    shell_store.close_project()
    assert window.stacked_widget.currentIndex() == 0  # Launcher

    # Close application from launcher
    window.close()

    # Verify settings.json saved the workspace state (with audio sources hidden)
    shell_store_2 = ShellStore()
    window_2 = MainWindow(shell_store_2, settings_file=settings_file)
    shell_store_2.open_project(proj)

    assert window_2.audio_sources_dock.isHidden()
    window_2.close()


def test_window_normal_geometry_restored_without_forced_maximized(qapp, tmp_path: Path):
    """Verify that a windowed (non-maximized) geometry is remembered and not forced full screen."""
    settings_file = tmp_path / "settings.json"

    # Session 1: Resize window to 1100x750 (normal, not maximized)
    shell_store_1 = ShellStore()
    window_1 = MainWindow(shell_store_1, settings_file=settings_file)
    window_1.show()
    window_1.resize(1100, 750)
    window_1.close()

    # Session 2: Launch and verify has_restored_geometry is True and window is not maximized
    shell_store_2 = ShellStore()
    window_2 = MainWindow(shell_store_2, settings_file=settings_file)
    assert window_2.has_restored_geometry is True

    if window_2.has_restored_geometry:
        window_2.show()
    else:
        window_2.showMaximized()

    assert not window_2.isMaximized()
    assert window_2.size().height() == 750
    window_2.close()


def test_window_maximized_geometry_restored(qapp, tmp_path: Path):
    """Verify that a maximized window geometry is preserved and restored as maximized."""
    settings_file = tmp_path / "settings.json"

    # Session 1: Maximize window
    shell_store_1 = ShellStore()
    window_1 = MainWindow(shell_store_1, settings_file=settings_file)
    window_1.showMaximized()
    window_1.close()

    # Session 2: Launch and verify restored as maximized
    shell_store_2 = ShellStore()
    window_2 = MainWindow(shell_store_2, settings_file=settings_file)
    assert window_2.has_restored_geometry is True

    if window_2.has_restored_geometry:
        window_2.show()
    else:
        window_2.showMaximized()

    assert window_2.isMaximized()
    window_2.close()
