import ast
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from src.ui.features.project_hub.state import ProjectHubState
from src.ui.features.project_hub.store import ProjectHubStore
from src.workspace.game import GameType
from src.workspace.storage import ProjectStorage


def test_no_qt_imports():
    """Verify that state and store have ZERO Qt dependencies."""
    pkg_dir = Path(__file__).parents[1] / "src" / "ui" / "features" / "project_hub"
    for py_file in (pkg_dir / "state.py", pkg_dir / "store.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("PySide"), (
                        f"Qt import {alias.name} in {py_file.name}"
                    )
                    assert not alias.name.startswith("PyQt"), (
                        f"Qt import {alias.name} in {py_file.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert not node.module.startswith("PySide"), (
                        f"Qt import {node.module} in {py_file.name}"
                    )
                    assert not node.module.startswith("PyQt"), (
                        f"Qt import {node.module} in {py_file.name}"
                    )


def test_store_init_empty(tmp_path: Path):
    cache_file = tmp_path / "recent.json"
    store = ProjectHubStore(cache_file=cache_file)
    assert store.state.recent_projects == ()
    assert store.state.selected_game == GameType.ATTILA
    assert store.state.new_project_name == "MyAudioMod"
    assert store.state.new_project_location == ""
    assert store.state.status_message is None
    assert store.state.loaded_project_path is None


def test_store_init_default_cache():
    store = ProjectHubStore()
    assert isinstance(store.state, ProjectHubState)
    assert store.state.selected_game == GameType.ATTILA


def test_store_validation_empty_name(tmp_path: Path):
    store = ProjectHubStore(cache_file=tmp_path / "recent.json")
    store.set_new_project_location(str(tmp_path))
    store.set_new_project_name("   ")
    project = store.create_project()
    assert project is None
    assert "cannot be empty" in (store.state.status_message or "").lower()


def test_store_validation_empty_location(tmp_path: Path):
    store = ProjectHubStore(cache_file=tmp_path / "recent.json")
    store.set_new_project_name("ValidName")
    store.set_new_project_location("   ")
    project = store.create_project()
    assert project is None
    assert "cannot be empty" in (store.state.status_message or "").lower()


def test_store_create_project_success(tmp_path: Path):
    cache_file = tmp_path / "recent.json"
    store = ProjectHubStore(cache_file=cache_file)
    store.set_new_project_location(str(tmp_path))
    store.set_new_project_name("AwesomeMod")
    store.set_selected_game(GameType.ATTILA)

    notifications: list[ProjectHubState] = []
    store.subscribe(lambda s: notifications.append(s))

    project = store.create_project()
    assert project is not None
    assert project.manifest.name == "AwesomeMod"
    assert (tmp_path / "AwesomeMod" / "project.json").is_file()
    assert store.state.loaded_project_path == str((tmp_path / "AwesomeMod").resolve())
    assert len(store.state.recent_projects) == 1
    assert store.state.recent_projects[0].name == "AwesomeMod"
    assert store.state.recent_projects[0].path == str((tmp_path / "AwesomeMod").resolve())
    assert store.state.recent_projects[0].game == "attila"
    assert cache_file.is_file()
    assert len(notifications) >= 1
    assert notifications[-1] == store.state


def test_store_open_project_by_path(tmp_path: Path):
    cache_file = tmp_path / "recent.json"
    store = ProjectHubStore(cache_file=cache_file)
    store.set_new_project_location(str(tmp_path))
    store.set_new_project_name("ExistingMod")
    created = store.create_project()
    assert created is not None

    # Re-open with a fresh store instance
    fresh_store = ProjectHubStore(cache_file=cache_file)
    assert len(fresh_store.state.recent_projects) == 1
    with patch("src.workspace.cache.GameCache.is_valid", return_value=True):
        opened = fresh_store.open_project_by_path(str(tmp_path / "ExistingMod"))
    assert opened is not None
    assert opened.manifest.name == "ExistingMod"
    assert fresh_store.state.loaded_project_path == str((tmp_path / "ExistingMod").resolve())


def test_store_open_invalid_path(tmp_path: Path):
    store = ProjectHubStore(cache_file=tmp_path / "recent.json")
    opened = store.open_project_by_path(str(tmp_path / "non_existent"))
    assert opened is None
    assert "failed to open" in (store.state.status_message or "").lower()


def test_store_corrupted_cache_resilience(tmp_path: Path):
    cache_file = tmp_path / "corrupted.json"
    cache_file.write_text("{invalid json", encoding="utf-8")
    store = ProjectHubStore(cache_file=cache_file)
    assert store.state.recent_projects == ()


def test_store_nonexistent_cached_paths_resilience(tmp_path: Path):
    cache_file = tmp_path / "recent_ghosts.json"
    cache_file.write_text(
        json.dumps(
            [
                {
                    "name": "GhostProject",
                    "path": str(tmp_path / "does_not_exist"),
                    "game": "attila",
                    "last_opened": "2026-10-29T00:00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    store = ProjectHubStore(cache_file=cache_file)
    assert store.state.recent_projects == ()


def test_store_recent_projects_deduplication_and_limit(tmp_path: Path):
    cache_file = tmp_path / "recent.json"
    store = ProjectHubStore(cache_file=cache_file)
    store.set_new_project_location(str(tmp_path))

    # Create 12 distinct projects
    for i in range(12):
        name = f"Mod_{i:02d}"
        store.set_new_project_name(name)
        proj = store.create_project()
        assert proj is not None

    # Limit to 10 most recent
    assert len(store.state.recent_projects) == 10
    # Newest should be index 0
    assert store.state.recent_projects[0].name == "Mod_11"
    assert store.state.recent_projects[1].name == "Mod_10"
    assert store.state.recent_projects[9].name == "Mod_02"

    # Re-opening an earlier project (e.g. Mod_02) moves it to index 0 without duplicates
    with patch("src.workspace.cache.GameCache.is_valid", return_value=True):
        opened = store.open_project_by_path(str(tmp_path / "Mod_02"))
    assert opened is not None
    assert len(store.state.recent_projects) == 10
    assert store.state.recent_projects[0].name == "Mod_02"
    assert store.state.recent_projects[1].name == "Mod_11"


def test_store_setters_and_immutability(tmp_path: Path):
    store = ProjectHubStore(cache_file=tmp_path / "recent.json")
    store.set_new_project_name("NewName")
    assert store.state.new_project_name == "NewName"

    store.set_new_project_location("/some/path")
    assert store.state.new_project_location == "/some/path"

    store.set_selected_game(GameType.ROME_2)
    assert store.state.selected_game == GameType.ROME_2

    # String game type conversion
    store.set_selected_game("attila")  # type: ignore
    assert store.state.selected_game == GameType.ATTILA

    # Immutability
    with pytest.raises(FrozenInstanceError):
        store.state.new_project_name = "IllegalMutation"  # type: ignore


def test_game_cache_auto_detection(tmp_path: Path):
    """Verify set_selected_game auto-detects game directory when found."""
    mock_install = tmp_path / "Total War Attila"
    mock_install.mkdir()
    (mock_install / "attila.exe").write_bytes(b"dummy_exe")
    data_dir = mock_install / "data"
    data_dir.mkdir()
    (data_dir / "local_en.pack").write_bytes(b"dummy_pack")

    with patch(
        "src.workspace.game_detector.GameDetector.detect_game_install", return_value=mock_install
    ):
        store = ProjectHubStore(cache_file=tmp_path / "recent.json")
        store.set_selected_game(GameType.ATTILA)

    assert store.state.game_path == str(mock_install)
    assert store.state.is_game_path_valid is True


def test_set_game_path_validation(tmp_path: Path):
    """Verify manual game path setting and validation."""
    store = ProjectHubStore(cache_file=tmp_path / "recent.json")

    # Nonexistent path
    store.set_game_path(str(tmp_path / "nonexistent"))
    assert store.state.is_game_path_valid is False
    assert "not exist" in (store.state.game_path_validation_msg or "").lower()

    # Empty path
    store.set_game_path("   ")
    assert store.state.is_game_path_valid is False
    assert store.state.game_path == ""

    # Valid game directory
    mock_game = tmp_path / "AttilaGame"
    mock_game.mkdir()
    (mock_game / "attila.exe").write_bytes(b"exe")
    (mock_game / "data").mkdir()
    (mock_game / "data" / "local_en.pack").write_bytes(b"pack")

    store.set_game_path(str(mock_game))
    assert store.state.is_game_path_valid is True
    assert store.state.game_path == str(mock_game)


def test_build_cache_flow(tmp_path: Path):
    """Verify build_cache updates cache validity and reports progress."""
    store = ProjectHubStore(cache_file=tmp_path / "recent.json")
    store.set_game_path("")  # Ensure invalid path to test failure

    # When game path is invalid, build_cache fails fast
    assert store.build_cache() is False
    assert "invalid" in (store.state.status_message or "").lower()

    # Setup valid game path and mock cache extraction
    mock_game = tmp_path / "AttilaGame"
    mock_game.mkdir()
    (mock_game / "attila.exe").write_bytes(b"exe")
    (mock_game / "data").mkdir()
    (mock_game / "data" / "local_en.pack").write_bytes(b"pack")
    store.set_game_path(str(mock_game))

    progress_events = []

    def progress_cb(msg: str, pct: float) -> None:
        progress_events.append((msg, pct))

    with (
        patch("src.workspace.cache.GameCache.extract_from_game_packs", return_value=127),
        patch("src.workspace.cache.GameCache.is_valid", return_value=True),
    ):
        success = store.build_cache(progress_cb=progress_cb)

    assert success is True
    assert store.state.is_cache_valid is True
    assert store.state.is_building_cache is False
    assert store.state.cache_status_msg is not None
    assert "ready" in store.state.cache_status_msg.lower() or "127" in store.state.cache_status_msg


def test_open_project_blocked_when_cache_missing(tmp_path: Path):
    """Verify opening a project fails with clear error when game cache is not built."""
    proj_dir = tmp_path / "UncachedMod"
    ProjectStorage.create_project(proj_dir, name="UncachedMod", game=GameType.ATTILA)

    store = ProjectHubStore(cache_file=tmp_path / "recent.json")
    with patch("src.workspace.cache.GameCache.is_valid", return_value=False):
        project = store.open_project_by_path(str(proj_dir))

    assert project is None
    assert store.state.loaded_project_path is None
    assert store.state.status_message is not None
    assert "game cache is not built" in store.state.status_message.lower()


def test_open_project_success_when_cache_valid(tmp_path: Path):
    """Verify opening a project succeeds when game cache is valid."""
    proj_dir = tmp_path / "CachedMod"
    ProjectStorage.create_project(proj_dir, name="CachedMod", game=GameType.ATTILA)

    store = ProjectHubStore(cache_file=tmp_path / "recent.json")
    with patch("src.workspace.cache.GameCache.is_valid", return_value=True):
        project = store.open_project_by_path(str(proj_dir))

    assert project is not None
    assert project.manifest.name == "CachedMod"
    assert store.state.loaded_project_path == str(proj_dir.resolve())
    assert store.state.status_message is None
