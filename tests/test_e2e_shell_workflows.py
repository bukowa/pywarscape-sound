"""
End-to-End Shell Workflows and Cross-Component Seam Integration Tests.

Validates the complete user-facing workflows across modal dialog boundaries:
1. First-Time Project Onboarding: Launcher -> ProjectWizardView dialog -> Project Creation -> Workspace Mode.
2. First-Time Pack Build Modal: Pressing Ctrl+B with unset path -> PackSettingsDialog modal -> Presets -> Compilation.
3. In-App Dependency Ingestion & Hot Reload: Menu -> Manage Mod Dependencies... -> Ingest pack -> Live Bank Viewer update.
4. Returning User Recent Projects Roundtrip: Project close -> Recent projects double-click -> Workspace re-entry.
5. Spacebar Auditioning & QLineEdit Focus Guard: Space toggles playback when tree focused, but types ' ' when editing text.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit

from src.bnk.bank import BkhdChunk, DataChunk, DidxChunk, DidxEntry, HircChunk, SoundBank
from src.bnk.models import CAkSound
from src.compiler.pfh4_pack import (
    PT_MOD,
    read_pfh4_index,
    read_pfh4_pack_type,
    write_pfh4_movie_pack,
)
from src.ui.features.audio_transport.structs import PlaybackStatus
from src.ui.features.project_wizard.view import ProjectWizardView
from src.ui.shell.dependency_manager_dialog import DependencyManagerDialog
from src.ui.shell.pack_settings_dialog import PackSettingsDialog
from src.ui.shell.store import ShellStore
from src.ui.shell.view import MainWindow
from src.workspace.cache import GameCache
from src.workspace.dependencies import DependencyManager
from src.workspace.game import GameType
from src.workspace.storage import ProjectStorage
from tests.support.factories import make_synthetic_wav


def _create_synthetic_bank(bank_id: int, sound_id: int, source_id: int) -> SoundBank:
    """Helper creating a minimal valid SoundBank with a single CAkSound node."""
    sound = CAkSound(id=sound_id, source_id=source_id, stream_type=2)
    return SoundBank(
        header=BkhdChunk(bank_id=bank_id, version=112),
        hirc=HircChunk(objects=[sound]),
    )


def test_e2e_project_wizard_onboarding_to_workspace(qapp, qtbot, tmp_path: Path, monkeypatch):
    """
    User Journey 1: First-time modder onboarding.
    1. MainWindow boots into LAUNCHER mode (Page 0).
    2. User triggers 'New Project...' action (or Ctrl+N).
    3. ProjectWizardView modal dialog appears.
    4. User fills in project name & location, clicks 'Skip / Vanilla Project'.
    5. Dialog accepts and MainWindow automatically transitions to ScreenMode.WORKSPACE (Page 1)
       with project manifest, directory layout, and menu actions enabled.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData"))
    monkeypatch.setattr("src.workspace.cache.GameCache.is_valid", lambda self: True)

    # 1. Setup synthetic game cache
    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    synthetic_bank = _create_synthetic_bank(bank_id=101, sound_id=1001, source_id=50001)
    (cache_dir / "battle.bnk").write_bytes(synthetic_bank.to_bytes())
    (cache_dir / "event_data.dat").write_bytes(b"\x00" * 32)
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)
    assert cache.is_valid()

    # 2. Launch MainWindow in Launcher mode
    shell_store = ShellStore()
    window = MainWindow(shell_store, settings_file=tmp_path / "settings.json")
    qtbot.addWidget(window)

    assert window.stacked_widget.currentIndex() == 0  # Launcher page
    assert not window.act_close_project.isEnabled()
    assert not window.act_build_pack.isEnabled()

    # 3. Intercept modal QDialog.exec to simulate user driving the ProjectWizardView
    target_mod_name = "OnboardingMod"
    projects_root = tmp_path / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)

    def _handle_wizard_dialog(dlg: QDialog) -> QDialog.DialogCode:
        wiz_view = dlg.findChild(ProjectWizardView)
        assert wiz_view is not None
        wiz_view.store.set_project_location(str(projects_root))
        wiz_view.store.set_project_name(target_mod_name)
        wiz_view.store.set_game(GameType.ATTILA)
        assert wiz_view.btn_skip.isEnabled() is True
        wiz_view.btn_skip.click()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", lambda self: _handle_wizard_dialog(self))

    # 4. Trigger 'New Project...'
    window.act_new_project.trigger()

    # 5. Assert seamless transition to Workspace
    assert window.stacked_widget.currentIndex() == 1  # Workspace view
    assert target_mod_name in window.windowTitle()
    assert window.act_close_project.isEnabled() is True
    assert window.act_build_pack.isEnabled() is True

    # 6. Verify filesystem persistence
    created_proj_dir = projects_root / target_mod_name
    assert created_proj_dir.is_dir()
    assert (created_proj_dir / "project.json").is_file()
    assert (created_proj_dir / "pack_root" / "audio").is_dir()


def test_e2e_first_time_pack_build_modal_flow(qapp, qtbot, tmp_path: Path, monkeypatch):
    """
    User Journey 2: First-time mod pack export.
    1. Active project has modified banks but output_pack_path is empty.
    2. Modder triggers 'Build Mod Pack' (Ctrl+B).
    3. MainWindow detects missing destination and opens PackSettingsDialog modal.
    4. Modder clicks 'Set to Project Folder' preset and clicks 'Build Mod Pack Now'.
    5. Pack compiles cleanly to the project folder, PackSettingsDialog closes,
       and MainWindow status bar displays compilation feedback.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData"))
    monkeypatch.setattr("src.workspace.cache.GameCache.is_valid", lambda self: True)

    # 1. Setup project with modified bank and unset output_pack_path
    proj_dir = tmp_path / "FirstBuildMod"
    project = ProjectStorage.create_project(proj_dir, name="FirstBuildMod", game=GameType.ATTILA)
    bank_bytes = _create_synthetic_bank(bank_id=777, sound_id=101, source_id=50001).to_bytes()
    project.save_bank("custom_voice.bnk", bank_bytes)
    assert not project.manifest.output_pack_path

    # 2. Open project in MainWindow
    shell_store = ShellStore()
    window = MainWindow(shell_store, settings_file=tmp_path / "settings.json")
    qtbot.addWidget(window)
    shell_store.open_project(project)

    assert window.stacked_widget.currentIndex() == 1
    assert window.act_build_pack.isEnabled() is True

    # 3. Intercept PackSettingsDialog.exec to simulate preset selection and build
    expected_pack = proj_dir / "FirstBuildMod.pack"
    dialog_invoked = False

    def _handle_pack_settings(dlg: PackSettingsDialog) -> QDialog.DialogCode:
        nonlocal dialog_invoked
        dialog_invoked = True
        # Click Project Folder preset
        dlg.btn_project_dir_preset.click()
        assert dlg.txt_pack_path.text() == str(expected_pack)
        # Click Build Mod Pack Now
        dlg.btn_build_now.click()
        dlg.accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(PackSettingsDialog, "exec", lambda self: _handle_pack_settings(self))

    # 4. Trigger Build Mod Pack action
    window.act_build_pack.trigger()

    # 5. Verify modal interaction and pack compilation
    assert dialog_invoked is True
    assert expected_pack.is_file()
    assert "Compiled mod pack: FirstBuildMod.pack" in window.status_bar.currentMessage()
    assert project.manifest.output_pack_path == str(expected_pack)

    # 6. Verify pack contents
    assert read_pfh4_pack_type(expected_pack) == PT_MOD
    entries = [e.path.replace("\\", "/") for e in read_pfh4_index(expected_pack)]
    assert "audio/custom_voice.bnk" in entries


def test_e2e_dependency_dialog_live_hot_reload(qapp, qtbot, tmp_path: Path, monkeypatch):
    """
    User Journey 3: In-app dependency ingestion & live Bank Viewer refresh.
    1. Active project is open with vanilla battle bank.
    2. Modder opens menu 'File -> Manage Mod Dependencies...'.
    3. Ingests an external overhaul pack containing a new soundbank 'overhaul_music.bnk'.
    4. Closes the dialog; coordinator reloads dependencies live.
    5. MainWindow's BankViewerView table immediately displays the new bank.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData"))
    monkeypatch.setattr("src.workspace.cache.GameCache.is_valid", lambda self: True)

    # 1. Setup vanilla cache
    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    vanilla_bank = _create_synthetic_bank(bank_id=101, sound_id=1, source_id=1)
    (cache_dir / "vanilla_battle.bnk").write_bytes(vanilla_bank.to_bytes())
    (cache_dir / "event_data.dat").write_bytes(b"\x00" * 32)
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)

    proj_dir = tmp_path / "DepReloadMod"
    project = ProjectStorage.create_project(
        proj_dir, name="DepReloadMod", game=GameType.ATTILA, cache=cache
    )

    # 2. Open project in MainWindow
    shell_store = ShellStore()
    window = MainWindow(shell_store, settings_file=tmp_path / "settings.json")
    qtbot.addWidget(window)
    shell_store.open_project(project)

    # Initially only vanilla_battle.bnk is available
    available_banks = [b.name for b in window.bank_viewer_store.state.available_banks]
    assert "vanilla_battle.bnk" in available_banks
    assert "overhaul_music.bnk" not in available_banks

    # 3. Create synthetic external overhaul mod pack
    overhaul_pack_path = tmp_path / "overhaul.pack"
    overhaul_bank = _create_synthetic_bank(bank_id=202, sound_id=2, source_id=2)
    write_pfh4_movie_pack(
        overhaul_pack_path,
        {"audio/overhaul_music.bnk": overhaul_bank.to_bytes()},
    )

    # 4. Intercept DependencyManagerDialog.exec to ingest the pack
    def _handle_dep_dialog(dlg: DependencyManagerDialog) -> QDialog.DialogCode:
        dep_mgr = DependencyManager(dlg.project)
        plan = dep_mgr.plan_import(overhaul_pack_path)
        dep_mgr.execute_import(plan)
        dlg._has_changes = True
        dlg._refresh_table()
        dlg.accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(DependencyManagerDialog, "exec", lambda self: _handle_dep_dialog(self))

    # 5. Trigger 'Manage Mod Dependencies...'
    window.act_manage_dependencies.trigger()

    # 6. Verify BankViewerView immediately reflects the imported bank
    updated_banks = [b.name for b in window.bank_viewer_store.state.available_banks]
    assert "overhaul_music.bnk" in updated_banks

    # Verify table item count in view
    table = window.bank_viewer_view.table_banks
    bank_names_in_table = [table.item(r, 0).text() for r in range(table.rowCount())]
    assert "overhaul_music.bnk" in bank_names_in_table

    # Select the newly imported bank
    window.bank_viewer_store.select_bank("overhaul_music.bnk")
    assert window.bank_viewer_store.state.selected_bank_name == "overhaul_music.bnk"


def test_e2e_recent_projects_double_click_roundtrip(qapp, qtbot, tmp_path: Path, monkeypatch):
    """
    User Journey 4: Returning modder reopening project from Launcher.
    1. Create Project Alpha on disk.
    2. MainWindow loads Project Alpha, then closes it via File -> Close Project.
    3. MainWindow returns to Launcher page (currentIndex == 0).
    4. Project Alpha appears in recent projects list.
    5. Double-clicking recent list item re-opens Project Alpha and transitions to Workspace.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData"))
    monkeypatch.setattr("src.workspace.cache.GameCache.is_valid", lambda self: True)

    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    synthetic_bank = _create_synthetic_bank(bank_id=101, sound_id=1, source_id=1)
    (cache_dir / "battle.bnk").write_bytes(synthetic_bank.to_bytes())
    (cache_dir / "event_data.dat").write_bytes(b"\x00" * 32)
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)

    proj_dir = tmp_path / "ProjectAlpha"
    project = ProjectStorage.create_project(
        proj_dir, name="ProjectAlpha", game=GameType.ATTILA, cache=cache
    )

    # 1. Launch MainWindow and record project in recent cache
    settings_file = tmp_path / "settings.json"
    shell_store = ShellStore()
    window = MainWindow(shell_store, settings_file=settings_file)
    qtbot.addWidget(window)

    window.hub_store.open_existing_project(str(proj_dir))
    shell_store.open_project(project)
    assert window.stacked_widget.currentIndex() == 1  # Workspace

    # 2. Close active project
    window.act_close_project.trigger()
    assert window.stacked_widget.currentIndex() == 0  # Launcher

    # 3. Verify item in recent list
    recent_list = window.hub_view.recent_list
    assert recent_list.count() >= 1
    recent_item = recent_list.item(0)
    assert "ProjectAlpha" in recent_item.text()

    # 4. Simulate double-click on recent project item
    window.hub_view._on_recent_item_double_clicked(recent_item)

    # 5. Assert MainWindow re-entered Workspace mode with ProjectAlpha
    assert window.stacked_widget.currentIndex() == 1  # Workspace
    assert "ProjectAlpha" in window.windowTitle()
    assert window.act_close_project.isEnabled() is True


def test_e2e_spacebar_playback_and_line_edit_focus_guard(qapp, qtbot, tmp_path: Path, monkeypatch):
    """
    User Journey 5: Spacebar auditioning shortcut and QLineEdit focus protection.
    1. Select an audio node in Bank Viewer; Spacebar toggles Play/Pause when hierarchy tree is focused.
    2. Focus a QLineEdit (edit_tree_search); Spacebar enters a space character ' '
       without toggling the audio transport.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData"))
    monkeypatch.setattr("src.workspace.cache.GameCache.is_valid", lambda self: True)

    wav_path = make_synthetic_wav(tmp_path / "audition.wav")
    wav_bytes = wav_path.read_bytes()

    # 1. Setup project with a bank containing embedded audio
    proj_dir = tmp_path / "TransportTestMod"
    project = ProjectStorage.create_project(proj_dir, name="TransportTestMod", game=GameType.ATTILA)
    bank = SoundBank(
        header=BkhdChunk(version=112, bank_id=10),
        didx=DidxChunk(entries=[DidxEntry(file_id=9002, offset=0, size=len(wav_bytes))]),
        data=DataChunk(data=wav_bytes),
        hirc=HircChunk(objects=[CAkSound(id=102, source_id=9002, stream_type=0)]),
    )
    project.save_bank("test_audio.bnk", bank.to_bytes())

    shell_store = ShellStore()
    window = MainWindow(shell_store, settings_file=tmp_path / "settings.json")
    qtbot.addWidget(window)
    window.show()

    # Open project and select node to resolve and cue audio
    shell_store.open_project(project)
    window.bank_viewer_store.select_bank("test_audio.bnk")
    window.bank_viewer_store.select_node("hirc:102")

    # With auto_play enabled by default, selecting the sound node cues and starts playback
    assert window.transport_store.state.status == PlaybackStatus.PLAYING

    # 2. Tree widget focused: Spacebar triggers Pause
    window.bank_viewer_view.tree_widget.setFocus()
    assert not isinstance(QApplication.focusWidget(), QLineEdit)

    space_press = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Space,
        Qt.KeyboardModifier.NoModifier,
        " ",
    )
    window.keyPressEvent(space_press)
    assert window.transport_store.state.status == PlaybackStatus.PAUSED

    # Spacebar triggers Play
    window.keyPressEvent(space_press)
    assert window.transport_store.state.status == PlaybackStatus.PLAYING

    # Spacebar triggers Pause again before text edit test
    window.keyPressEvent(space_press)
    assert window.transport_store.state.status == PlaybackStatus.PAUSED

    # 3. QLineEdit focused: Spacebar does NOT toggle audio transport
    search_edit = window.bank_viewer_view.edit_tree_search
    monkeypatch.setattr(QApplication, "focusWidget", lambda: search_edit)

    # Trigger space keypress on window with QLineEdit focused
    window.keyPressEvent(space_press)

    # Assert audio transport remains paused (did not toggle to PLAYING)
    assert window.transport_store.state.status == PlaybackStatus.PAUSED

    # Direct key input to search edit types a space character
    qtbot.keyClick(search_edit, Qt.Key.Key_Space)
    assert search_edit.text() == " "
