"""Tests for Project Wizard integration with Mod Pack Health scanning and repair staging."""

import ast
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QDialog, QFileDialog

from src.compiler.pfh4_pack import write_pfh4_movie_pack
from src.ui.features.pack_repair import PackRepairDialog
from src.ui.features.project_wizard.state import WizardStep
from src.ui.features.project_wizard.store import ProjectWizardStore
from src.ui.features.project_wizard.view import ProjectWizardView
from src.workspace.game import GameType
from src.workspace.health import RepairStrategyRegistry


def _synthesize_defective_pack(pack_path: Path) -> tuple[bytes, bytes]:
    """Helper creating a test pack with a word-swapped automation count defect."""
    raw_track_hex = (
        "0ba0000000c3e4be0e00010000000100040002ecff9d39ecff9d3900000000000100000000"
        "000000ecff9d390000000000000000000000000000000000000000000000004fc1cb2978c9"
        "114101000000000100000000000000000000030000000000000000000000090000004cfc10"
        "430000000004000000ef6e1143000000000400000000000000000000e88cdd2d000000c000"
        "000100000000000000000000002c010000"
    )
    bkhd = bytes.fromhex("424b484418000000700000000100000000000000000000002b00000000000000")
    hirc_body = bytes.fromhex("01000000") + bytes.fromhex(raw_track_hex)
    hirc = bytes.fromhex("48495243") + len(hirc_body).to_bytes(4, "little") + hirc_body
    bnk_bytes = bkhd + hirc

    write_pfh4_movie_pack(pack_path, {"audio/defective.bnk": bnk_bytes})
    repaired_bnk = RepairStrategyRegistry.repair_bank("defective.bnk", bnk_bytes)
    return bnk_bytes, repaired_bnk


def test_wizard_stores_and_applies_repaired_bank_payloads(tmp_path: Path):
    """Verify that ProjectWizardStore accepts repaired_files and stages them on project creation."""
    pack_path = tmp_path / "defective_music.pack"
    bnk_bytes, repaired_bnk = _synthesize_defective_pack(pack_path)

    store = ProjectWizardStore()
    store.set_project_name("RepairedSubmod")
    store.set_project_location(tmp_path)
    store.set_game(GameType.ATTILA)

    # Adding pack with repair map
    store.add_mod_pack(pack_path, repaired_files={"audio/defective.bnk": repaired_bnk})

    project = store.create_project_and_ingest()
    assert project is not None
    # Verified: Repaired bank is safely written into dependency storage, not user overlay
    dep_bank = project.get_dependency_dir(pack_path.name) / "audio" / "defective.bnk"
    assert dep_bank.is_file()
    assert dep_bank.read_bytes() == repaired_bnk
    assert "defective.bnk" not in project.manifest.modified_banks


def test_view_add_pack_with_issues_auto_fix(qapp, tmp_path: Path):
    """When a defective pack is added and user chooses Auto-Fix, repaired bank is staged."""
    pack_path = tmp_path / "auto_fix_mod.pack"
    bnk_bytes, repaired_bnk = _synthesize_defective_pack(pack_path)

    store = ProjectWizardStore()
    store.set_project_location(str(tmp_path))
    store.set_project_name("AutoFixProject")
    store.go_to_step(WizardStep.MOD_PACKS)
    view = ProjectWizardView(store)

    with (
        patch.object(
            QFileDialog, "getOpenFileNames", return_value=([str(pack_path)], "Pack Files (*.pack)")
        ),
        patch.object(PackRepairDialog, "exec", return_value=QDialog.DialogCode.Accepted),
    ):
        view.btn_add_pack.click()

    assert len(store.state.mod_packs) == 1
    entry = store.state.mod_packs[0]
    assert entry.filename == "auto_fix_mod.pack"
    repaired_map = dict(entry.repaired_files)
    assert "audio/defective.bnk" in repaired_map
    assert repaired_map["audio/defective.bnk"] == repaired_bnk

    # Test creating project stages the repaired bank in dependencies
    project = store.create_project_and_ingest()
    assert project is not None
    dep_bank = project.get_dependency_dir(pack_path.name) / "audio" / "defective.bnk"
    assert dep_bank.is_file()
    assert dep_bank.read_bytes() == repaired_bnk
    assert "defective.bnk" not in project.manifest.modified_banks


def test_view_add_pack_with_issues_ignore(qapp, tmp_path: Path):
    """When a defective pack is added and user chooses Ignore (10), pack is added without repairs."""
    pack_path = tmp_path / "ignore_mod.pack"
    _synthesize_defective_pack(pack_path)

    store = ProjectWizardStore()
    store.set_project_location(str(tmp_path))
    store.set_project_name("IgnoreProject")
    store.go_to_step(WizardStep.MOD_PACKS)
    view = ProjectWizardView(store)

    with (
        patch.object(
            QFileDialog, "getOpenFileNames", return_value=([str(pack_path)], "Pack Files (*.pack)")
        ),
        patch.object(PackRepairDialog, "exec", return_value=10),
    ):
        view.btn_add_pack.click()

    assert len(store.state.mod_packs) == 1
    entry = store.state.mod_packs[0]
    assert entry.filename == "ignore_mod.pack"
    assert len(entry.repaired_files) == 0


def test_view_add_pack_with_issues_cancel(qapp, tmp_path: Path):
    """When a defective pack is added and user cancels the repair dialog, pack is not added."""
    pack_path = tmp_path / "cancel_mod.pack"
    _synthesize_defective_pack(pack_path)

    store = ProjectWizardStore()
    store.set_project_location(str(tmp_path))
    store.set_project_name("CancelProject")
    store.go_to_step(WizardStep.MOD_PACKS)
    view = ProjectWizardView(store)

    with (
        patch.object(
            QFileDialog, "getOpenFileNames", return_value=([str(pack_path)], "Pack Files (*.pack)")
        ),
        patch.object(PackRepairDialog, "exec", return_value=QDialog.DialogCode.Rejected),
    ):
        view.btn_add_pack.click()

    assert len(store.state.mod_packs) == 0


def test_view_add_pack_without_issues_skips_dialog(qapp, tmp_path: Path):
    """A clean pack with zero issues does not show the repair dialog and is added immediately."""
    pack_path = tmp_path / "clean_mod.pack"
    bkhd = bytes.fromhex("424b484418000000700000000100000000000000000000002b00000000000000")
    hirc_body = bytes.fromhex("00000000")
    hirc = bytes.fromhex("48495243") + len(hirc_body).to_bytes(4, "little") + hirc_body
    write_pfh4_movie_pack(pack_path, {"audio/clean.bnk": bkhd + hirc})

    store = ProjectWizardStore()
    store.set_project_location(str(tmp_path))
    store.set_project_name("CleanProject")
    store.go_to_step(WizardStep.MOD_PACKS)
    view = ProjectWizardView(store)

    with (
        patch.object(
            QFileDialog, "getOpenFileNames", return_value=([str(pack_path)], "Pack Files (*.pack)")
        ),
        patch.object(PackRepairDialog, "exec") as mock_exec,
    ):
        view.btn_add_pack.click()
        mock_exec.assert_not_called()

    assert len(store.state.mod_packs) == 1
    assert store.state.mod_packs[0].filename == "clean_mod.pack"
    assert len(store.state.mod_packs[0].repaired_files) == 0


def test_no_qt_imports_in_wizard_state_and_store():
    """Verify state and store contain ZERO Qt imports via AST analysis."""
    pkg_dir = Path(__file__).parents[1] / "src" / "ui" / "features" / "project_wizard"
    for py_file in (pkg_dir / "state.py", pkg_dir / "store.py"):
        assert py_file.is_file()
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
