"""Headless unit tests for ProjectWizardStore and ProjectWizardState."""

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from src.ui.features.project_wizard.state import WizardStep
from src.ui.features.project_wizard.store import ProjectWizardStore
from src.workspace.game import GameType


def test_no_qt_imports():
    """Verify state and store contain ZERO Qt imports via AST analysis."""
    pkg_dir = Path(__file__).parents[1] / "src" / "ui" / "features" / "project_wizard"
    for py_file in (pkg_dir / "state.py", pkg_dir / "store.py"):
        if not py_file.is_file():
            pytest.fail(f"File {py_file} not found")
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


def test_initial_state():
    store = ProjectWizardStore()
    state = store.state
    assert state.step == WizardStep.SETUP
    assert state.selected_game == GameType.ATTILA
    assert state.project_name == "MyAudioMod"
    assert state.project_location == str(Path.cwd() / "projects")
    assert state.mod_packs == ()
    assert state.import_db_tables is True
    assert state.progress_percentage == 0.0
    assert state.is_working is False
    assert state.status_message is None
    assert state.created_project is None


def test_custom_and_fallback_default_location(tmp_path: Path):
    # Explicit custom location
    custom_dir = tmp_path / "custom_workspace"
    store = ProjectWizardStore(default_location=str(custom_dir))
    assert store.state.project_location == str(custom_dir)

    # Empty string falls back to current dir projects dir
    empty_store = ProjectWizardStore(default_location="   ")
    assert empty_store.state.project_location == str(Path.cwd() / "projects")


def test_state_immutability():
    store = ProjectWizardStore()
    with pytest.raises(FrozenInstanceError):
        store.state.project_name = "NewName"  # type: ignore


def test_setters_and_subscriber_notification():
    store = ProjectWizardStore()
    notifications = []
    store.subscribe(lambda s: notifications.append(s))

    store.set_project_name("CustomMod")
    assert store.state.project_name == "CustomMod"

    store.set_project_location("/path/to/projects")
    assert store.state.project_location == "/path/to/projects"

    store.set_import_db_tables(False)
    assert store.state.import_db_tables is False

    assert len(notifications) == 3


def test_set_selected_game_triggers_detection(tmp_path: Path):
    detected_dir = tmp_path / "DetectedRome2"
    detected_dir.mkdir()

    with (
        patch(
            "src.workspace.game_detector.GameDetector.detect_game_install",
            return_value=detected_dir,
        ),
        patch(
            "src.workspace.game_detector.GameDetector.validate_game_dir",
            return_value=(True, "Valid"),
        ),
    ):
        store = ProjectWizardStore()
        store.set_selected_game(GameType.ROME_2)

        assert store.state.selected_game == GameType.ROME_2
        assert store.state.game_path == str(detected_dir)
        assert store.state.is_game_path_valid is True


def test_set_game_path_validation(tmp_path: Path):
    store = ProjectWizardStore()

    # Invalid path
    store.set_game_path(str(tmp_path / "nonexistent"))
    assert store.state.is_game_path_valid is False
    assert "not exist" in store.state.game_path_validation_msg.lower()

    # Mocked valid path
    with patch(
        "src.workspace.game_detector.GameDetector.validate_game_dir",
        return_value=(True, "Valid game directory"),
    ):
        store.set_game_path(str(tmp_path))
        assert store.state.is_game_path_valid is True
        assert store.state.game_path_validation_msg == "Valid game directory"


def test_mod_pack_management(tmp_path: Path):
    store = ProjectWizardStore()

    pack1 = tmp_path / "mod1.pack"
    pack1.write_bytes(b"PFH4" + b"\x00" * 20)
    pack2 = tmp_path / "mod2.pack"
    pack2.write_bytes(b"PFH4" + b"\x00" * 30)

    # Add pack 1
    assert store.add_mod_pack(str(pack1)) is True
    assert len(store.state.mod_packs) == 1
    assert store.state.mod_packs[0].filename == "mod1.pack"

    # Reject duplicate
    assert store.add_mod_pack(str(pack1)) is False
    assert len(store.state.mod_packs) == 1

    # Reject non-pack or nonexistent
    assert store.add_mod_pack(str(tmp_path / "not_pack.txt")) is False
    assert store.add_mod_pack(str(tmp_path / "missing.pack")) is False

    # Add pack 2
    assert store.add_mod_pack(str(pack2)) is True
    assert len(store.state.mod_packs) == 2
    assert store.state.mod_packs[1].filename == "mod2.pack"

    # Reorder (move down pack 1)
    assert store.move_mod_pack(0, direction=1) is True
    assert store.state.mod_packs[0].filename == "mod2.pack"
    assert store.state.mod_packs[1].filename == "mod1.pack"

    # Reorder bounds
    assert store.move_mod_pack(0, direction=-1) is False
    assert store.move_mod_pack(1, direction=1) is False

    # Remove pack
    assert store.remove_mod_pack(0) is True
    assert len(store.state.mod_packs) == 1
    assert store.state.mod_packs[0].filename == "mod1.pack"


def test_step_navigation_validation(tmp_path: Path):
    store = ProjectWizardStore(default_location=str(tmp_path))

    # Cannot advance to MOD_PACKS without location
    store.set_project_location("")
    assert store.go_to_step(WizardStep.MOD_PACKS) is False
    assert "location cannot be empty" in (store.state.status_message or "").lower()

    # Valid name and location
    store.set_project_location(str(tmp_path))
    store.set_project_name("ValidName")
    assert store.go_to_step(WizardStep.MOD_PACKS) is True
    assert store.state.step == WizardStep.MOD_PACKS

    # Can go back to SETUP anytime
    assert store.go_to_step(WizardStep.SETUP) is True
    assert store.state.step == WizardStep.SETUP


def test_existing_project_directory_validation(tmp_path: Path):
    existing_dir = tmp_path / "ExistingProject"
    existing_dir.mkdir(parents=True)

    store = ProjectWizardStore(default_location=str(tmp_path))
    store.set_project_name("ExistingProject")

    assert store.state.is_target_dir_available is False
    assert "already exists" in store.state.target_dir_validation_msg.lower()

    # Attempting to go to next step fails
    assert store.go_to_step(WizardStep.MOD_PACKS) is False
    assert "already exists" in (store.state.status_message or "").lower()

    # Attempting to skip / create fails
    assert store.skip_to_finish() is None
    assert store.create_project_and_ingest() is None

    # Changing to unique project name restores availability
    store.set_project_name("FreshProject")
    assert store.state.is_target_dir_available is True
    assert store.state.target_dir_validation_msg == ""
    assert store.go_to_step(WizardStep.MOD_PACKS) is True


def test_skip_to_finish(tmp_path: Path):
    store = ProjectWizardStore()
    store.set_project_location(str(tmp_path))
    store.set_project_name("SkippedVanillaMod")

    project = store.skip_to_finish()
    assert project is not None
    assert project.manifest.name == "SkippedVanillaMod"
    assert (tmp_path / "SkippedVanillaMod" / "project.json").is_file()
    assert store.state.created_project == project
    assert store.state.step == WizardStep.PROGRESS


def test_create_project_and_ingest(tmp_path: Path):
    store = ProjectWizardStore()
    store.set_project_location(str(tmp_path))
    store.set_project_name("ModWithDeps")

    # Create synthetic pack
    from src.compiler.pfh4_pack import write_pfh4_movie_pack

    pack_path = tmp_path / "base.pack"
    write_pfh4_movie_pack(
        pack_path,
        {"audio/custom_bank.bnk": b"BKHD" + b"\x00" * 20},
    )
    store.add_mod_pack(str(pack_path))

    progress_reports = []
    project = store.create_project_and_ingest(
        progress_cb=lambda text, pct: progress_reports.append((text, pct))
    )

    assert project is not None
    assert project.manifest.name == "ModWithDeps"
    assert len(project.manifest.dependencies) == 1
    assert project.manifest.dependencies[0].name == "base.pack"
    assert store.state.created_project == project
    assert store.state.progress_percentage == 1.0
    assert len(progress_reports) >= 1
