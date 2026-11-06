"""Tests for PySide6 ProjectWizardView data-driven projection widget."""

from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QFileDialog

from src.ui.features.project_wizard.state import WizardStep
from src.ui.features.project_wizard.store import ProjectWizardStore
from src.ui.features.project_wizard.view import ProjectWizardView
from src.workspace.game import GameType


def test_view_initial_render(qapp, tmp_path: Path):
    with patch("src.workspace.cache.GameCache.is_valid", return_value=True):
        store = ProjectWizardStore(default_location=str(tmp_path))
        view = ProjectWizardView(store)

    assert view.stacked_widget.currentIndex() == 0
    assert view.edit_name.text() == "MyAudioMod"
    assert view.combo_game.currentText() == "Attila"
    assert view.edit_location.text() == str(tmp_path)
    assert view.btn_next.isEnabled() is True  # Name and fresh default location are populated

    # When user clears location, Next should be disabled
    view.edit_location.setText("")
    assert view.btn_next.isEnabled() is False


def test_view_existing_project_failsafe(qapp, tmp_path: Path):
    existing_dir = tmp_path / "ExistingMod"
    existing_dir.mkdir(parents=True)

    with patch("src.workspace.cache.GameCache.is_valid", return_value=True):
        store = ProjectWizardStore(default_location=str(tmp_path))
        view = ProjectWizardView(store)
    view.show()

    # Change name to existing mod
    view.edit_name.setText("ExistingMod")
    assert store.state.is_target_dir_available is False
    assert view.btn_next.isEnabled() is False
    assert view.btn_skip.isEnabled() is False
    assert view.lbl_target_status.isVisible() is True
    assert "already exists" in view.lbl_target_status.text().lower()

    # Changing to unique name enables buttons and hides warning
    view.edit_name.setText("UniqueMod")
    assert store.state.is_target_dir_available is True
    assert view.btn_next.isEnabled() is True
    assert view.btn_skip.isEnabled() is True
    assert view.lbl_target_status.isVisible() is False


def test_view_state_projection(qapp, tmp_path: Path):
    with patch("src.workspace.cache.GameCache.is_valid", return_value=True):
        store = ProjectWizardStore()
        view = ProjectWizardView(store)

        store.set_project_name("UpdatedMod")
        assert view.edit_name.text() == "UpdatedMod"

        store.set_selected_game(GameType.ROME_2)
        assert view.combo_game.currentText() == "Rome II"

        store.set_project_location(str(tmp_path))
        assert view.edit_location.text() == str(tmp_path)
        assert view.btn_next.isEnabled() is True


def test_view_user_inputs_update_store(qapp, tmp_path: Path):
    store = ProjectWizardStore()
    view = ProjectWizardView(store)

    view.edit_name.setText("TypedMod")
    assert store.state.project_name == "TypedMod"

    view.combo_game.setCurrentText("Rome II")
    assert store.state.selected_game == GameType.ROME_2

    view.edit_location.setText(str(tmp_path))
    assert store.state.project_location == str(tmp_path)


def test_view_browse_location(qapp, tmp_path: Path):
    store = ProjectWizardStore()
    view = ProjectWizardView(store)

    chosen_dir = tmp_path / "workspaces"
    chosen_dir.mkdir(parents=True)

    with patch.object(QFileDialog, "getExistingDirectory", return_value=str(chosen_dir)):
        view.btn_browse_location.click()

    assert store.state.project_location == str(chosen_dir)
    assert view.edit_location.text() == str(chosen_dir)


def test_view_step_transitions_and_navigation(qapp, tmp_path: Path):
    store = ProjectWizardStore()
    store.set_project_location(str(tmp_path))
    store.set_project_name("MultiStepMod")
    view = ProjectWizardView(store)

    # Click Next -> moves to Step 2 (Mod Packs)
    view.btn_next.click()
    assert store.state.step == WizardStep.MOD_PACKS
    assert view.stacked_widget.currentIndex() == 1

    # Click Back -> returns to Step 1 (Setup)
    view.btn_back_mod_packs.click()
    assert store.state.step == WizardStep.SETUP
    assert view.stacked_widget.currentIndex() == 0


def test_view_mod_packs_page_interactions(qapp, tmp_path: Path):
    store = ProjectWizardStore()
    store.set_project_location(str(tmp_path))
    store.set_project_name("PackMod")
    store.go_to_step(WizardStep.MOD_PACKS)
    view = ProjectWizardView(store)

    from src.compiler.pfh4_pack import write_pfh4_movie_pack

    pack1 = tmp_path / "first.pack"
    write_pfh4_movie_pack(pack1, {})
    pack2 = tmp_path / "second.pack"
    write_pfh4_movie_pack(pack2, {})

    # Add pack1 via file dialog
    with patch.object(
        QFileDialog, "getOpenFileNames", return_value=([str(pack1)], "Pack Files (*.pack)")
    ):
        view.btn_add_pack.click()

    assert len(store.state.mod_packs) == 1
    assert view.list_packs.count() == 1
    assert "first.pack" in view.list_packs.item(0).text()

    # Add pack2
    with patch.object(
        QFileDialog, "getOpenFileNames", return_value=([str(pack2)], "Pack Files (*.pack)")
    ):
        view.btn_add_pack.click()

    assert len(store.state.mod_packs) == 2
    assert view.list_packs.count() == 2

    # Select second item and move UP
    view.list_packs.setCurrentRow(1)
    view.btn_move_up.click()
    assert store.state.mod_packs[0].filename == "second.pack"
    assert view.list_packs.currentRow() == 0

    # Move DOWN
    view.btn_move_down.click()
    assert store.state.mod_packs[0].filename == "first.pack"
    assert view.list_packs.currentRow() == 1

    # Remove item
    view.btn_remove_pack.click()
    assert len(store.state.mod_packs) == 1
    assert view.list_packs.count() == 1

    # Toggle DB tables checkbox
    view.chk_import_db.setChecked(False)
    assert store.state.import_db_tables is False


def test_view_add_multiple_mod_packs(qapp, tmp_path: Path):
    """Verify selecting multiple .pack files at once in the file dialog adds all of them in order."""
    store = ProjectWizardStore()
    store.set_project_location(str(tmp_path))
    store.set_project_name("MultiPackMod")
    store.go_to_step(WizardStep.MOD_PACKS)
    view = ProjectWizardView(store)

    from src.compiler.pfh4_pack import write_pfh4_movie_pack

    pack1 = tmp_path / "alpha.pack"
    pack2 = tmp_path / "beta.pack"
    pack3 = tmp_path / "gamma.pack"
    write_pfh4_movie_pack(pack1, {})
    write_pfh4_movie_pack(pack2, {})
    write_pfh4_movie_pack(pack3, {})

    with patch.object(
        QFileDialog,
        "getOpenFileNames",
        return_value=([str(pack1), str(pack2), str(pack3)], "Pack Files (*.pack)"),
    ):
        view.btn_add_pack.click()

    assert len(store.state.mod_packs) == 3
    assert [m.filename for m in store.state.mod_packs] == ["alpha.pack", "beta.pack", "gamma.pack"]
    assert view.list_packs.count() == 3


def test_view_signals_cancel(qapp, tmp_path: Path):
    store = ProjectWizardStore()
    view = ProjectWizardView(store)

    cancelled = []
    view.cancelled.connect(lambda: cancelled.append(True))
    view.btn_cancel.click()
    assert len(cancelled) == 1


def test_view_signals_skip_to_finish(qapp, tmp_path: Path):
    store = ProjectWizardStore()
    store.set_project_location(str(tmp_path))
    store.set_project_name("SkippedFromView")
    view = ProjectWizardView(store)

    created_signals = []
    view.project_created.connect(lambda p: created_signals.append(p))

    view.btn_skip.click()
    assert len(created_signals) == 1
    assert created_signals[0].manifest.name == "SkippedFromView"
    assert (tmp_path / "SkippedFromView" / "project.json").is_file()


def test_view_signals_create_and_ingest(qapp, tmp_path: Path):
    store = ProjectWizardStore()
    store.set_project_location(str(tmp_path))
    store.set_project_name("CreatedFromView")
    store.go_to_step(WizardStep.MOD_PACKS)
    view = ProjectWizardView(store)

    created_signals = []
    view.project_created.connect(lambda p: created_signals.append(p))

    view.btn_create_ingest.click()
    assert len(created_signals) == 1
    assert created_signals[0].manifest.name == "CreatedFromView"


def test_view_cache_readiness_display(qapp, tmp_path: Path):
    """Verify that cache status is displayed and game path / build buttons are removed."""
    store = ProjectWizardStore(default_location=str(tmp_path))
    # Explicitly set cache as invalid
    store._update_state(is_cache_valid=False)

    view = ProjectWizardView(store)
    assert (
        "not built" in view.lbl_cache_status.text().lower()
        or "project hub" in view.lbl_cache_status.text().lower()
    )
    assert not hasattr(view, "edit_game_path")
    assert not hasattr(view, "btn_build_cache")

    # When cache is valid, status says ready
    store._update_state(is_cache_valid=True)
    assert "ready" in view.lbl_cache_status.text().lower()
