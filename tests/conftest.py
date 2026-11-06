"""
Pytest configuration for test suite execution.
Ensures headless audio and UI environments during test runs.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject
from tests.support.factories import skip_or_fail_missing_asset

__all__ = ["qapp", "skip_or_fail_missing_asset", "test_project"]

# Mute physical audio output during tests by routing pygame/SDL to the dummy audio driver.
if os.environ.get("PYTEST_ENABLE_AUDIO") != "1":
    os.environ["SDL_AUDIODRIVER"] = "dummy"

# Ensure Qt tests default to headless offscreen rendering
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def test_project(tmp_path: Path) -> AudioProject:
    manifest = ProjectManifest(
        name="TestMod",
        game="attila",
        description="Test Mod Description",
    )
    return AudioProject(root_dir=tmp_path / "test_mod", manifest=manifest)
