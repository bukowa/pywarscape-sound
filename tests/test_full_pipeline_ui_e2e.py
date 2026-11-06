"""
Full End-to-End UI Pipeline Integration Test Suite.

Simulates the entire user modding journey end-to-end through real PySide6 widgets:
1. App Boot & Launcher: MainWindow initialized in LAUNCHER screen mode.
2. Project Creation & Open: Project created with isolated GameCache and loaded into shell.
3. Workspace Transition: Shell transitions to WORKSPACE mode, tree and docks synchronize.
4. SoundBank Exploration: Bank selected, tree hierarchy populated with container and sounds.
5. Reference Following: Inspector panel used to jump from child sound to parent container,
   followed by back-navigation verifying tree selection sync.
6. Audio Replacement: Target sound selected, sound library WAV selected, btn_apply clicked.
   Verifies AST stream promotion, loose WEM staging on disk, and coordinator tracking.
7. Atomic Undo / Redo: act_undo triggers byte-for-byte rollback; act_redo restores modification.
8. Project Lifecycle Persistence: Project closed (shell returns to LAUNCHER), reopened from disk,
   verifying modified banks and staged WEMs persist.
9. Mod Pack Compilation: Build Mod Pack triggered via MainWindow, verifying valid PFH4 pack
   archive containing the modified SoundBank and staged .wem.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from src.bnk.bank import BkhdChunk, DataChunk, DidxChunk, DidxEntry, HircChunk, SoundBank
from src.bnk.models import CAkRanSeqCntr, CAkSound
from src.compiler.pfh4_pack import read_pfh4_index, read_pfh4_pack_type
from src.ui.shell.store import ShellStore
from src.ui.shell.view import MainWindow
from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.storage import ProjectStorage
from tests.support.factories import make_synthetic_wav


def test_full_pipeline_ui_e2e(qapp, qtbot, tmp_path: Path, monkeypatch):
    """
    Executes the complete user workflow from project boot to pack compilation.
    Zero mocks, 100% real domain models, stores, and PySide6 widgets.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData"))

    # -------------------------------------------------------------------------
    # Setup: Synthetic SoundBank & Game Cache
    # -------------------------------------------------------------------------
    vanilla_wav = make_synthetic_wav(tmp_path / "vanilla.wav")
    wav_bytes = vanilla_wav.read_bytes()

    # battle_units.bnk:
    # - Container 100 (CAkRanSeqCntr) containing child Sound 101
    # - Sound 101 (CAkSound) referencing embedded WEM 50001 (stream_type=0)
    bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        didx=DidxChunk(
            entries=[
                DidxEntry(file_id=50001, offset=0, size=len(wav_bytes)),
            ]
        ),
        data=DataChunk(data=wav_bytes),
        hirc=HircChunk(
            objects=[
                CAkRanSeqCntr(id=100, children=[101]),
                CAkSound(id=101, source_id=50001, file_id=50001, stream_type=0),
            ]
        ),
    )

    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    (cache_dir / "battle_units.bnk").write_bytes(bank.to_bytes())
    (cache_dir / "event_data.dat").write_bytes(b"\x00" * 32)
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)
    assert cache.is_valid() is True

    # -------------------------------------------------------------------------
    # Phase 1: App Boot & Launcher
    # -------------------------------------------------------------------------
    shell_store = ShellStore()
    window = MainWindow(shell_store, settings_file=tmp_path / "settings.json")
    qtbot.addWidget(window)

    assert window.stacked_widget.currentIndex() == 0  # Launcher page
    assert not window.act_close_project.isEnabled()
    assert not window.act_build_pack.isEnabled()
    assert not window.act_undo.isEnabled()

    # -------------------------------------------------------------------------
    # Phase 2: Project Creation & Open
    # -------------------------------------------------------------------------
    proj_dir = tmp_path / "FullPipelineMod"
    project = ProjectStorage.create_project(
        proj_dir, name="FullPipelineMod", game=GameType.ATTILA, cache=cache
    )
    # Configure output pack path to prevent interactive PackSettingsDialog modal
    output_pack_file = proj_dir / "FullPipelineMod.pack"
    project.set_output_pack_path(output_pack_file)
    assert proj_dir.is_dir()
    assert (proj_dir / "project.json").is_file()

    # Open project in Shell via store
    shell_store.open_project(project)

    # -------------------------------------------------------------------------
    # Phase 3: Workspace Transition
    # -------------------------------------------------------------------------
    assert window.stacked_widget.currentIndex() == 1  # Workspace view
    assert "FullPipelineMod" in window.windowTitle()
    assert window.act_close_project.isEnabled() is True
    assert window.act_build_pack.isEnabled() is True

    # -------------------------------------------------------------------------
    # Phase 4: SoundBank Exploration & Reference Following
    # -------------------------------------------------------------------------
    bv_store = window.bank_viewer_store
    bv_view = window.bank_viewer_view

    # Select the bank
    bv_store.select_bank("battle_units.bnk")
    assert bv_store.state.selected_bank_name == "battle_units.bnk"

    # Select child Sound node
    bv_store.select_node("hirc:101")
    assert bv_store.state.selected_node_key == "hirc:101"
    assert bv_store.state.can_navigate_back is False

    # Verify inspector panel shows parent container 100 in combo_parents
    assert bv_view.inspector_panel.combo_parents.count() >= 2
    # Select parent in combo to jump
    bv_view.inspector_panel.combo_parents.setCurrentIndex(1)
    assert bv_store.state.selected_node_key == "hirc:100"
    assert bv_store.state.can_navigate_back is True

    # Navigate back to Sound 101
    bv_store.navigate_back()
    assert bv_store.state.selected_node_key == "hirc:101"
    assert bv_store.state.can_navigate_forward is True

    # -------------------------------------------------------------------------
    # Phase 5: Audio Replacement via Audio Sources Dock
    # -------------------------------------------------------------------------
    # Setup custom sound library
    lib_dir = tmp_path / "user_audio"
    custom_wav = make_synthetic_wav(lib_dir / "custom_sword.wav")
    window.audio_sources_store.add_library(lib_dir, "Weapons")

    # Target sound 101 in BankTreeWidget
    item101 = bv_view._items_by_key.get("hirc:101")
    assert item101 is not None
    bv_view.tree_widget.setCurrentItem(item101)
    item101.setSelected(True)
    bv_view._on_tree_selection_changed()

    assert window.audio_sources_view.lbl_target_summary.text() == "1 target selected"
    assert len(window.audio_sources_store.state.targets) == 1

    # Select custom WAV and click Apply
    window.audio_sources_store.select_files([str(custom_wav)])
    assert window.audio_sources_view.btn_apply.isEnabled() is True
    qtbot.mouseClick(window.audio_sources_view.btn_apply, Qt.MouseButton.LeftButton)

    # Verify AST mutation & WEM staging
    assert "battle_units.bnk" in project.manifest.modified_banks
    assert len(project.manifest.staged_wems) == 1
    staged_id = project.manifest.staged_wems[0]
    staged_path = project.audio_dir / f"{staged_id}.wem"
    assert staged_path.is_file()

    # Verify CAkSound was promoted to streamed (stream_type=2)
    saved_bytes = (project.audio_dir / "battle_units.bnk").read_bytes()
    saved_bank = SoundBank.from_bytes(saved_bytes)
    mutated_sound = next(obj for obj in saved_bank.hirc.objects if obj.id == 101)
    assert isinstance(mutated_sound, CAkSound)
    assert mutated_sound.source_id == staged_id
    assert mutated_sound.stream_type == 2

    # -------------------------------------------------------------------------
    # Phase 6: Atomic Undo / Redo
    # -------------------------------------------------------------------------
    assert window.coordinator.can_undo is True
    assert window.act_undo.isEnabled() is True

    # Trigger Undo
    window.act_undo.trigger()
    assert "battle_units.bnk" not in project.manifest.modified_banks
    assert len(project.manifest.staged_wems) == 0
    assert not staged_path.is_file()

    # Verify AST reverted to vanilla embedded (stream_type=0, source_id=50001)
    entry = bv_store.session.get_loaded_entry("battle_units.bnk")
    assert entry is not None
    reverted_sound = next(obj for obj in entry[0].hirc.objects if obj.id == 101)
    assert reverted_sound.source_id == 50001
    assert reverted_sound.stream_type == 0

    # Trigger Redo
    assert window.coordinator.can_redo is True
    assert window.act_redo.isEnabled() is True
    window.act_redo.trigger()

    assert "battle_units.bnk" in project.manifest.modified_banks
    assert len(project.manifest.staged_wems) == 1
    assert staged_path.is_file()

    # -------------------------------------------------------------------------
    # Phase 7: Project Save, Close, and Reopen Persistence
    # -------------------------------------------------------------------------
    # Close project -> returns to launcher
    shell_store.close_project()
    assert window.stacked_widget.currentIndex() == 0
    assert not window.act_close_project.isEnabled()

    # Reopen project from disk
    reopened_proj = ProjectStorage.open_project(proj_dir, cache=cache)
    shell_store.open_project(reopened_proj)
    assert window.stacked_widget.currentIndex() == 1
    assert "battle_units.bnk" in reopened_proj.manifest.modified_banks
    assert staged_id in reopened_proj.manifest.staged_wems
    assert staged_path.is_file()

    # -------------------------------------------------------------------------
    # Phase 8: Mod Pack Compilation & Verification
    # -------------------------------------------------------------------------
    window._on_build_pack_triggered()

    output_pack = Path(reopened_proj.manifest.output_pack_path)
    assert output_pack.is_file()

    # Verify PFH4 pack type and index contents
    pack_type = read_pfh4_pack_type(output_pack)
    assert pack_type in (3, 4)  # PT_MOD or PT_MOVIE

    entries = read_pfh4_index(output_pack)
    entry_paths = [e.path.replace("\\", "/") for e in entries]
    assert "audio/battle_units.bnk" in entry_paths
    assert f"audio/{staged_id}.wem" in entry_paths
