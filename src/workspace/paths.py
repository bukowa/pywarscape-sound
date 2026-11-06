"""Portable application directory and persistent configuration path resolution."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ENV_PORTABLE_DIR = "AUDIO_EDITOR_PORTABLE_DIR"
_ENV_DATA_DIR = "AUDIO_EDITOR_DATA_DIR"
_ENV_SETTINGS_FILE = "AUDIO_EDITOR_SETTINGS_FILE"
_ENV_RECENT_PROJECTS_FILE = "AUDIO_EDITOR_RECENT_PROJECTS_FILE"
_ENV_LOG_FILE = "AUDIO_EDITOR_LOG_FILE"
_ENV_CACHE_DIR = "AUDIO_EDITOR_CACHE_DIR"


def get_app_root() -> Path:
    """
    Returns the portable application root directory.

    In frozen/packaged runtime (PyInstaller bundle), this is the directory
    containing the executable. In development, this is the repository root.
    Can be overridden via AUDIO_EDITOR_PORTABLE_DIR or AUDIO_EDITOR_DATA_DIR.
    """
    env_dir = os.environ.get(_ENV_PORTABLE_DIR) or os.environ.get(_ENV_DATA_DIR)
    if env_dir:
        return Path(env_dir).resolve()

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    # Development source tree: v3/workspace/paths.py -> parents[2] is repo root
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root


def get_settings_path() -> Path:
    """Returns absolute path to the portable settings.json configuration file."""
    env_path = os.environ.get(_ENV_SETTINGS_FILE)
    if env_path:
        return Path(env_path).resolve()
    return get_app_root() / "settings.json"


def get_recent_projects_path() -> Path:
    """Returns absolute path to the portable recent_projects.json file."""
    env_path = os.environ.get(_ENV_RECENT_PROJECTS_FILE)
    if env_path:
        return Path(env_path).resolve()
    return get_app_root() / "recent_projects.json"


def get_log_file_path() -> Path:
    """Returns absolute path to the application log file."""
    env_path = os.environ.get(_ENV_LOG_FILE)
    if env_path:
        return Path(env_path).resolve()
    return get_app_root() / "app.log"


def get_cache_dir(game_type: str | None = None) -> Path:
    """Returns absolute path to the portable vanilla game cache directory."""
    env_path = os.environ.get(_ENV_CACHE_DIR)
    base = Path(env_path).resolve() if env_path else get_app_root() / ".cache"
    if game_type is not None:
        return base / str(game_type) / "audio"
    return base
