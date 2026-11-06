"""Tests for PySide6 ProjectHubView data-driven projection."""

from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QFileDialog

from src.ui.features.project_hub.store import ProjectHubStore
from src.ui.features.project_hub.view import ProjectHubView
from src.workspace.game import GameType
from src.workspace.storage import ProjectStorage


def test_view_initial_render(qapp, tmp_path: Path):
    """Verify initial UI projection from default store state."""
    store = ProjectHubStore(cache_file=tmp_path / "recent.json")
    view = ProjectHubView(store)

    assert view.recent_list.count() == 1
    assert "no recent projects found" in view.recent_list.item(0).text().lower()
    assert view.btn_create.text() == "New Project..."
    assert view.btn_open.text() == "Browse Project Folder..."
    assert view.status_label.text() == ""


def test_view_state_projection_no_signals(qapp, tmp_path: Path):
    """Verify changes to store state update UI widgets without feedback loops."""
    cache_file = tmp_path / "recent.json"
    store = ProjectHubStore(cache_file=cache_file)
    view = ProjectHubView(store)

    # Adding a project via store updates recent list
    proj_dir = tmp_path / "StoreMod"
    ProjectStorage.create_project(proj_dir, name="StoreMod", game=GameType.ATTILA)
    with patch("src.workspace.cache.GameCache.is_valid", return_value=True):
        store.open_project_by_path(str(proj_dir))

    assert view.recent_list.count() == 1
    assert "StoreMod" in view.recent_list.item(0).text()


def test_view_create_project_signal(qapp, tmp_path: Path):
    """Verify clicking create button triggers wizard dialog creation."""
    store = ProjectHubStore(cache_file=tmp_path / "recent.json")
    view = ProjectHubView(store)

    received_projects = []
    view.project_loaded.connect(lambda p: received_projects.append(p))

    # Mock open_wizard to simulate project creation directly
    proj_dir = tmp_path / "SignalProject"
    project = ProjectStorage.create_project(proj_dir, name="SignalProject", game=GameType.ATTILA)

    with patch.object(view, "open_wizard", side_effect=lambda: view.project_loaded.emit(project)):
        view.btn_create.click()

    assert len(received_projects) == 1
    assert received_projects[0].manifest.name == "SignalProject"


def test_view_open_project_signal(qapp, tmp_path: Path):
    """Verify double clicking a recent project item loads project and emits signal."""
    proj_dir = tmp_path / "ExistingMod"
    ProjectStorage.create_project(proj_dir, name="ExistingMod", game=GameType.ATTILA)

    cache_file = tmp_path / "recent.json"
    store = ProjectHubStore(cache_file=cache_file)
    with patch("src.workspace.cache.GameCache.is_valid", return_value=True):
        store.open_project_by_path(str(proj_dir))

    view = ProjectHubView(store)
    assert view.recent_list.count() == 1
    assert "ExistingMod" in view.recent_list.item(0).text()

    received_projects = []
    view.project_loaded.connect(lambda p: received_projects.append(p))

    with patch("src.workspace.cache.GameCache.is_valid", return_value=True):
        view._on_recent_item_double_clicked(view.recent_list.item(0))
    assert len(received_projects) == 1
    assert received_projects[0].manifest.name == "ExistingMod"


def test_view_browse_open_project(qapp, tmp_path: Path):
    """Verify clicking browse open project invokes file dialog and emits project_loaded."""
    proj_dir = tmp_path / "FolderMod"
    ProjectStorage.create_project(proj_dir, name="FolderMod", game=GameType.ROME_2)

    store = ProjectHubStore(cache_file=tmp_path / "recent.json")
    view = ProjectHubView(store)

    received_projects = []
    view.project_loaded.connect(lambda p: received_projects.append(p))

    with (
        patch.object(QFileDialog, "getExistingDirectory", return_value=str(proj_dir)),
        patch("src.workspace.cache.GameCache.is_valid", return_value=True),
    ):
        view.btn_open.click()

    assert len(received_projects) == 1
    assert received_projects[0].manifest.name == "FolderMod"


def test_view_game_cache_section_render(qapp, tmp_path: Path):
    """Verify Game Installation & Cache UI elements exist and render correctly."""
    store = ProjectHubStore(cache_file=tmp_path / "recent.json")
    view = ProjectHubView(store)

    assert hasattr(view, "combo_game")
    assert view.combo_game.count() == 2
    assert view.combo_game.itemText(0) == "Attila"
    assert view.combo_game.itemText(1) == "Rome II"

    assert hasattr(view, "edit_game_path")
    assert hasattr(view, "btn_browse_game")
    assert hasattr(view, "lbl_game_status")
    assert hasattr(view, "lbl_cache_status")
    assert hasattr(view, "btn_build_cache")
    assert hasattr(view, "progress_cache")
    assert hasattr(view, "lbl_cache_progress")


def test_view_browse_game_button(qapp, tmp_path: Path):
    """Verify clicking browse game directory updates game path in store."""
    store = ProjectHubStore(cache_file=tmp_path / "recent.json")
    view = ProjectHubView(store)

    mock_dir = tmp_path / "CustomGameDir"
    mock_dir.mkdir()

    with patch.object(QFileDialog, "getExistingDirectory", return_value=str(mock_dir)):
        view.btn_browse_game.click()

    assert store.state.game_path == str(mock_dir)


def test_view_build_cache_button_click(qapp, tmp_path: Path):
    """Verify clicking build cache button triggers store.build_cache."""
    store = ProjectHubStore(cache_file=tmp_path / "recent.json")
    view = ProjectHubView(store)

    with patch.object(store, "build_cache") as mock_build:
        view.btn_build_cache.click()
        assert mock_build.called


def test_view_open_project_with_invalid_cache_displays_warning(qapp, tmp_path: Path):
    """Verify double clicking a recent project with invalid cache shows error and does not emit."""
    proj_dir = tmp_path / "NeedsCacheMod"
    ProjectStorage.create_project(proj_dir, name="NeedsCacheMod", game=GameType.ATTILA)

    cache_file = tmp_path / "recent.json"
    store = ProjectHubStore(cache_file=cache_file)
    with patch("src.workspace.cache.GameCache.is_valid", return_value=True):
        store.open_project_by_path(str(proj_dir))

    view = ProjectHubView(store)
    received = []
    view.project_loaded.connect(lambda p: received.append(p))

    # Force invalid cache during user action
    with patch("src.workspace.cache.GameCache.is_valid", return_value=False):
        view._on_recent_item_double_clicked(view.recent_list.item(0))

    assert len(received) == 0
    assert "game cache is not built" in view.status_label.text().lower()


def test_view_status_message_display(qapp, tmp_path: Path):
    """Verify status messages in store are reflected in the status label."""
    store = ProjectHubStore(cache_file=tmp_path / "recent.json")
    view = ProjectHubView(store)

    store._update_state(status_message="Custom error message")
    assert "custom error message" in view.status_label.text().lower()


def test_view_wizard_launch(qapp, tmp_path: Path):
    """Verify ProjectHubView creates wizard dialog and integrates project_created."""
    cache_file = tmp_path / "recent.json"
    store = ProjectHubStore(cache_file=cache_file)
    view = ProjectHubView(store)

    assert hasattr(view, "btn_create")
    assert "project" in view.btn_create.text().lower()

    dialog, wiz_view = view.create_wizard_dialog()
    assert dialog is not None
    assert wiz_view is not None
    assert wiz_view.store.state.project_location == str(Path.cwd() / "projects")

    received_projects = []
    view.project_loaded.connect(lambda p: received_projects.append(p))

    proj_dir = tmp_path / "WizardCreatedMod"
    project = ProjectStorage.create_project(proj_dir, name="WizardCreatedMod", game=GameType.ATTILA)
    with patch("src.workspace.cache.GameCache.is_valid", return_value=True):
        wiz_view.project_created.emit(project)

    assert len(received_projects) == 1
    assert received_projects[0].manifest.name == "WizardCreatedMod"
    assert len(store.state.recent_projects) == 1
    assert store.state.recent_projects[0].name == "WizardCreatedMod"
