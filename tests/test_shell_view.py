"""Offscreen headless tests for v3 MainWindow shell."""

from pathlib import Path

import pytest

from src.ui.shell.coordinator import WorkspaceCoordinator
from src.ui.shell.store import ShellStore
from src.ui.shell.view import MainWindow
from src.workspace.game import GameType
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject


def test_shell_initial_render(qapp):
    store = ShellStore()
    window = MainWindow(store)

    assert window.windowTitle() == "PyWarscape Sound"
    assert window.stacked_widget.currentIndex() == 0  # Project Hub launcher
    assert not window.act_close_project.isEnabled()


def test_shell_main_window_has_zero_last_attributes(qapp):
    """Verify MainWindow has no _last_* tracking attributes, offloading state coordination to WorkspaceCoordinator."""
    store = ShellStore()
    window = MainWindow(store)

    last_attrs = [attr for attr in dir(window) if attr.startswith("_last_")]
    assert last_attrs == [], (
        f"Found forbidden _last_* tracking attributes on MainWindow: {last_attrs}"
    )
    assert hasattr(window, "coordinator")
    assert isinstance(window.coordinator, WorkspaceCoordinator)


def test_shell_transitions_to_workspace_on_project_opened(qapp, tmp_path: Path):
    store = ShellStore()
    window = MainWindow(store)

    proj_dir = tmp_path / "TestShellMod"
    proj_dir.mkdir()
    audio_dir = proj_dir / "pack_root" / "audio"
    audio_dir.mkdir(parents=True)
    manifest = ProjectManifest(name="TestShellMod", game=GameType.ATTILA)
    proj = AudioProject(root_dir=proj_dir, manifest=manifest)

    # Open project via store
    store.open_project(proj)

    assert window.stacked_widget.currentIndex() == 1  # Workspace view
    assert "TestShellMod" in window.windowTitle()
    assert window.act_close_project.isEnabled()
    assert window.bank_viewer_store.project is proj

    # Close project returns to launcher
    store.close_project()
    assert window.stacked_widget.currentIndex() == 0
    assert not window.act_close_project.isEnabled()
    assert window.bank_viewer_store.project is None


def test_shell_undo_redo_actions_delegated_to_coordinator(qapp):
    """Verify Edit -> Undo and Redo actions reflect coordinator state."""
    store = ShellStore()
    window = MainWindow(store)

    assert hasattr(window, "act_undo")
    assert hasattr(window, "act_redo")
    assert not window.act_undo.isEnabled()
    assert not window.act_redo.isEnabled()
    assert window.act_undo.statusTip() == window.coordinator.undo_status_tip
    assert window.act_redo.statusTip() == window.coordinator.redo_status_tip


def test_shell_build_pack_actions_and_dialog(qapp, tmp_path: Path, monkeypatch):
    """Verify Build Mod Pack action and PackSettingsDialog."""
    from src.ui.shell.pack_settings_dialog import PackSettingsDialog

    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData"))

    store = ShellStore()
    window = MainWindow(store)

    assert hasattr(window, "act_build_pack")
    assert hasattr(window, "act_build_and_copy")
    assert hasattr(window, "act_pack_settings")
    assert not window.act_build_pack.isEnabled()
    assert not window.act_build_and_copy.isEnabled()
    assert not window.act_pack_settings.isEnabled()

    proj_dir = tmp_path / "PackTestMod"
    proj_dir.mkdir()
    audio_dir = proj_dir / "pack_root" / "audio"
    audio_dir.mkdir(parents=True)
    (audio_dir / "battle.bnk").write_bytes(b"BKHD_TEST")

    output_pack = tmp_path / "output" / "PackTestMod.pack"
    manifest = ProjectManifest(
        name="PackTestMod",
        game=GameType.ATTILA,
        output_pack_path=str(output_pack),
    )
    proj = AudioProject(root_dir=proj_dir, manifest=manifest)

    # Open project
    store.open_project(proj)
    assert window.act_build_pack.isEnabled()
    assert window.act_build_and_copy.isEnabled()
    assert window.act_pack_settings.isEnabled()

    # Trigger build pack
    window._on_build_pack_triggered()
    assert output_pack.is_file()
    assert "Compiled mod pack: PackTestMod.pack" in window.status_bar.currentMessage()
    # Confirm user.script.txt was NEVER created or modified
    assert not (tmp_path / "FakeAppData").exists()

    # Test PackSettingsDialog
    dialog = PackSettingsDialog(proj, window)
    assert dialog.txt_pack_path.text() == str(output_pack)
    new_dest = tmp_path / "output" / "renamed.pack"
    dialog.txt_pack_path.setText(str(new_dest))
    dialog._on_save_only_clicked()
    assert proj.manifest.output_pack_path == str(new_dest)


def test_shell_status_bar_shows_modified_banks(qapp, tmp_path: Path):
    store = ShellStore()
    window = MainWindow(store)

    proj_dir = tmp_path / "ModStatusTest"
    proj_dir.mkdir()
    manifest = ProjectManifest(
        name="ModStatusTest",
        game=GameType.ATTILA,
        modified_banks=["battle.bnk", "campaign.bnk"],
    )
    proj = AudioProject(root_dir=proj_dir, manifest=manifest)

    store.open_project(proj)
    assert "2 modified banks" in window.status_bar.currentMessage()
