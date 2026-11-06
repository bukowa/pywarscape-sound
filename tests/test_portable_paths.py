"""Tests for portable application path resolution and isolated state storage."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.ui.features.project_hub.store import ProjectHubStore
from src.workspace.game import GameType
from src.workspace.paths import (
    get_app_root,
    get_cache_dir,
    get_log_file_path,
    get_recent_projects_path,
    get_settings_path,
)
from src.workspace.storage import ProjectStorage


def test_get_app_root_dev_mode():
    """In development mode, get_app_root() resolves to repository root."""
    root = get_app_root()
    assert root.is_dir()
    assert (root / "app.py").is_file()
    assert (root / "pyproject.toml").is_file()


def test_get_app_root_frozen_mode(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """When frozen (packaged standalone bundle), get_app_root() resolves to executable's parent."""
    fake_exe = tmp_path / "bin" / "PyWarscapeSound.exe"
    fake_exe.parent.mkdir(parents=True, exist_ok=True)
    fake_exe.touch()

    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", str(fake_exe))
    monkeypatch.delenv("AUDIO_EDITOR_PORTABLE_DIR", raising=False)
    monkeypatch.delenv("AUDIO_EDITOR_DATA_DIR", raising=False)

    root = get_app_root()
    assert root == fake_exe.parent


def test_get_app_root_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """AUDIO_EDITOR_PORTABLE_DIR takes highest precedence."""
    custom_root = tmp_path / "custom_app_dir"
    custom_root.mkdir()

    monkeypatch.setenv("AUDIO_EDITOR_PORTABLE_DIR", str(custom_root))
    assert get_app_root() == custom_root.resolve()


def test_settings_and_recent_projects_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Settings and recent projects files resolve inside get_app_root() by default."""
    monkeypatch.setenv("AUDIO_EDITOR_PORTABLE_DIR", str(tmp_path))

    assert get_settings_path() == (tmp_path / "settings.json").resolve()
    assert get_recent_projects_path() == (tmp_path / "recent_projects.json").resolve()

    # Individual env overrides
    custom_settings = tmp_path / "alt_settings.json"
    custom_recent = tmp_path / "alt_recent.json"
    monkeypatch.setenv("AUDIO_EDITOR_SETTINGS_FILE", str(custom_settings))
    monkeypatch.setenv("AUDIO_EDITOR_RECENT_PROJECTS_FILE", str(custom_recent))

    assert get_settings_path() == custom_settings.resolve()
    assert get_recent_projects_path() == custom_recent.resolve()


def test_cache_and_log_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Cache and log paths resolve inside get_app_root() by default."""
    monkeypatch.setenv("AUDIO_EDITOR_PORTABLE_DIR", str(tmp_path))

    assert get_cache_dir() == (tmp_path / ".cache").resolve()
    assert get_cache_dir("attila") == (tmp_path / ".cache" / "attila" / "audio").resolve()
    assert get_log_file_path() == (tmp_path / "app.log").resolve()

    # Log env override
    custom_log = tmp_path / "custom.log"
    monkeypatch.setenv("AUDIO_EDITOR_LOG_FILE", str(custom_log))
    assert get_log_file_path() == custom_log.resolve()


def test_project_hub_store_uses_portable_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """ProjectHubStore defaults to portable recent_projects.json without touching user home."""
    monkeypatch.setenv("AUDIO_EDITOR_PORTABLE_DIR", str(tmp_path))

    store = ProjectHubStore()
    assert store._cache_file == (tmp_path / "recent_projects.json").resolve()
    assert store.state.recent_projects == ()

    # Create project and verify it saves inside tmp_path / recent_projects.json
    proj_dir = tmp_path / "PortableMod"
    ProjectStorage.create_project(proj_dir, name="PortableMod", game=GameType.ATTILA)

    from unittest.mock import patch

    with patch("src.workspace.cache.GameCache.is_valid", return_value=True):
        store.open_project_by_path(str(proj_dir))

    assert (tmp_path / "recent_projects.json").is_file()
    assert len(store.state.recent_projects) == 1
    assert store.state.recent_projects[0].name == "PortableMod"


def test_zero_path_home_in_v3_production_code():
    """Static check verifying zero Path.home() calls exist in v3 production code."""
    repo_root = Path(__file__).resolve().parents[1]
    v3_dir = repo_root / "src"
    violations: list[str] = []

    for py_file in v3_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and node.func.attr == "home":
                    violations.append(f"{py_file.relative_to(repo_root)}:{node.lineno}")

    assert not violations, f"Forbidden Path.home() found in v3 production code: {violations}"
