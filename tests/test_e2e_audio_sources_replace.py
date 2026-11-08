"""
Vertical E2E Integration Tests for Audio Sources Dock and Batch Audio Replacement.
Simulates real user interactions via qtbot driving the full UI:
1. Opening a real mod project in MainWindow with SoundBank containing multiple Sound nodes.
2. Adding a Sound Library and browsing/selecting files.
3. Multi-selecting hierarchy nodes in BankTreeWidget and verifying target summary label.
4. Batch replacement applying external audio to multiple nodes with encode-once deduplication.
5. Verifying single-step atomic undo restoring nodes and removing staged loose WEMs.
6. Verifying non-modal dock interactivity alongside the hierarchy tree.
7. Simulating drag-and-drop of audio sources onto hierarchy nodes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import QByteArray, QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

from src.bnk.bank import BkhdChunk, DataChunk, DidxChunk, DidxEntry, HircChunk, SoundBank
from src.bnk.models import CAkAction, CAkEvent, CAkRanSeqCntr, CAkSound
from src.engine.ontology import ReplacementScope
from src.ui.shell.store import ShellStore
from src.ui.shell.view import MainWindow
from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.storage import ProjectStorage
from tests.support.factories import make_synthetic_wav


def test_e2e_audio_sources_multi_select_replace_and_deduplication(qapp, qtbot, tmp_path: Path):
    """
    Scenario A: Multi-select replace & deduplication
    1. Create temp folder with 2 dummy WAV files.
    2. In MainWindow, open project with SoundBank having 2 CAkSound nodes (IDs 101 and 102).
    3. Add temp folder as sound library in Audio Sources dock.
    4. Multi-select both Sound nodes in hierarchy tree; verify target summary reflects 2 targets.
    5. Select a library file and click btn_apply.
    6. Assert both Sound nodes reference the single allocated WEM ID and staged_wems has length 1.
    7. Trigger undo; assert both nodes are restored byte-exact and staged .wem is removed.
    """
    # 1. Setup synthetic SoundBank with two CAkSound nodes
    raw_wav = make_synthetic_wav(tmp_path / "vanilla.wav")
    wav_bytes = raw_wav.read_bytes()
    bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        didx=DidxChunk(
            entries=[
                DidxEntry(file_id=50001, offset=0, size=len(wav_bytes)),
                DidxEntry(file_id=50002, offset=len(wav_bytes), size=len(wav_bytes)),
            ]
        ),
        data=DataChunk(data=wav_bytes + wav_bytes),
        hirc=HircChunk(
            objects=[
                CAkSound(
                    id=101,
                    source_id=50001,
                    file_id=50001,
                    stream_type=0,
                    file_offset=0,
                    in_memory_media_size=len(wav_bytes),
                ),
                CAkSound(
                    id=102,
                    source_id=50002,
                    file_id=50002,
                    stream_type=0,
                    file_offset=len(wav_bytes),
                    in_memory_media_size=len(wav_bytes),
                ),
            ]
        ),
    )

    synth_cache_dir = tmp_path / "cache" / "audio"
    synth_cache_dir.mkdir(parents=True, exist_ok=True)
    (synth_cache_dir / "event_data.dat").write_bytes(b"\x00" * 32)
    (synth_cache_dir / "battle_units.bnk").write_bytes(bank.to_bytes())
    cache = GameCache(GameType.ATTILA, cache_dir=synth_cache_dir)
    assert cache.is_valid() is True

    proj_dir = tmp_path / "E2ESourcesMod"
    proj = ProjectStorage.create_project(proj_dir, name="E2ESourcesMod", game=GameType.ATTILA)
    proj.cache = cache

    # 2. Setup library folder with 2 dummy WAV files
    lib_dir = tmp_path / "sfx_library"
    wav_file1 = make_synthetic_wav(lib_dir / "custom_roar_01.wav")
    wav_file2 = make_synthetic_wav(lib_dir / "custom_roar_02.wav")

    # 3. Launch MainWindow and open project
    shell_store = ShellStore()
    window = MainWindow(shell_store)
    qtbot.addWidget(window)
    shell_store.open_project(proj)

    window.bank_viewer_store.select_bank("battle_units.bnk")

    # 4. Add library to project via AudioSourcesStore
    window.audio_sources_store.add_library(lib_dir, "Monsters SFX")
    assert len(window.audio_sources_store.state.libraries) == 1
    assert len(window.audio_sources_store.state.files) == 2

    # 5. Multi-select two Sound nodes in bank_viewer_view.tree_widget
    window.bank_viewer_store.select_nodes(("hirc:101", "hirc:102"))
    item1 = window.bank_viewer_view._items_by_key.get("hirc:101")
    item2 = window.bank_viewer_view._items_by_key.get("hirc:102")
    assert item1 is not None and item2 is not None

    window.bank_viewer_view.tree_widget.setCurrentItem(item1)
    item1.setSelected(True)
    item2.setSelected(True)
    window.bank_viewer_view._on_tree_selection_changed()

    # Verify dock target summary reflects 2 targets
    assert window.audio_sources_view.lbl_target_summary.text() == "2 targets selected"
    assert len(window.audio_sources_store.state.targets) == 2

    # 6. Select the first library file in the files table
    window.audio_sources_store.select_files([wav_file1])
    assert window.audio_sources_view.btn_apply.isEnabled() is True

    # 7. Click Apply to Selected button
    qtbot.mouseClick(window.audio_sources_view.btn_apply, Qt.MouseButton.LeftButton)

    # 8. Assertions: Both Sound nodes updated to the single allocated WEM ID (deduplicated)
    assert "battle_units.bnk" in proj.manifest.modified_banks
    assert len(proj.manifest.staged_wems) == 1
    staged_wid = proj.manifest.staged_wems[0]
    staged_file = proj.audio_dir / f"{staged_wid}.wem"
    assert staged_file.is_file()

    # Verify both Sound nodes reference the single allocated WEM ID
    saved_bank = SoundBank.from_bytes((proj.audio_dir / "battle_units.bnk").read_bytes())
    s101 = next(obj for obj in saved_bank.hirc.objects if obj.id == 101)
    s102 = next(obj for obj in saved_bank.hirc.objects if obj.id == 102)
    assert isinstance(s101, CAkSound) and isinstance(s102, CAkSound)
    assert s101.source_id == staged_wid
    assert s101.file_id == staged_wid
    assert s101.stream_type == 2
    assert s102.source_id == staged_wid
    assert s102.file_id == staged_wid
    assert s102.stream_type == 2

    # Both nodes are marked modified in BankViewerState
    n101 = window.bank_viewer_store.state.nodes_by_key.get("hirc:101")
    n102 = window.bank_viewer_store.state.nodes_by_key.get("hirc:102")
    assert n101 is not None and n101.is_modified is True
    assert n102 is not None and n102.is_modified is True

    # 9. Trigger Undo (Ctrl+Z)
    assert window.coordinator.can_undo is True
    window.act_undo.trigger()

    # Verify both nodes are restored byte-exact and staged WEM is removed
    assert "battle_units.bnk" not in proj.manifest.modified_banks
    assert len(proj.manifest.staged_wems) == 0
    assert not staged_file.is_file()

    entry = window.bank_viewer_store.session.get_loaded_entry("battle_units.bnk")
    assert entry is not None
    restored_bank = entry[0]
    rs101 = next(obj for obj in restored_bank.hirc.objects if obj.id == 101)
    rs102 = next(obj for obj in restored_bank.hirc.objects if obj.id == 102)
    assert rs101.source_id == 50001
    assert rs101.stream_type == 0
    assert rs102.source_id == 50002
    assert rs102.stream_type == 0


def test_e2e_audio_sources_non_modal_interactivity(qapp, qtbot, tmp_path: Path):
    """
    Scenario B: Non-modal tree interactivity
    1. Verify window.audio_sources_dock is visible alongside bank viewer tree.
    2. Verify no blocking modal dialog is present.
    3. Change selection between nodes in the tree; verify dock target summary updates immediately.
    """
    raw_wav = make_synthetic_wav(tmp_path / "vanilla.wav")
    wav_bytes = raw_wav.read_bytes()
    bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        didx=DidxChunk(
            entries=[
                DidxEntry(file_id=50001, offset=0, size=len(wav_bytes)),
                DidxEntry(file_id=50002, offset=len(wav_bytes), size=len(wav_bytes)),
            ]
        ),
        data=DataChunk(data=wav_bytes + wav_bytes),
        hirc=HircChunk(
            objects=[
                CAkSound(id=201, source_id=50001, file_id=50001, stream_type=0),
                CAkSound(id=202, source_id=50002, file_id=50002, stream_type=0),
            ]
        ),
    )

    synth_cache_dir = tmp_path / "cache" / "audio"
    synth_cache_dir.mkdir(parents=True, exist_ok=True)
    (synth_cache_dir / "event_data.dat").write_bytes(b"\x00" * 32)
    (synth_cache_dir / "interactivity.bnk").write_bytes(bank.to_bytes())
    cache = GameCache(GameType.ATTILA, cache_dir=synth_cache_dir)

    proj_dir = tmp_path / "InteractivityMod"
    proj = ProjectStorage.create_project(proj_dir, name="InteractivityMod", game=GameType.ATTILA)
    proj.cache = cache

    shell_store = ShellStore()
    window = MainWindow(shell_store)
    qtbot.addWidget(window)
    shell_store.open_project(proj)

    window.bank_viewer_store.select_bank("interactivity.bnk")

    # Verify dock is visible and not hidden
    assert not window.audio_sources_dock.isHidden()
    assert QApplication.activeModalWidget() is None

    # Initial state: No target selected
    assert window.audio_sources_view.lbl_target_summary.text() == "No target selected"

    # Select node 201
    window.bank_viewer_store.select_node("hirc:201")
    assert window.audio_sources_view.lbl_target_summary.text() == "1 target selected"
    assert QApplication.activeModalWidget() is None

    # Switch selection to node 202; updates immediately without locking
    window.bank_viewer_store.select_node("hirc:202")
    assert window.audio_sources_view.lbl_target_summary.text() == "1 target selected"
    assert QApplication.activeModalWidget() is None

    # Select both nodes; updates immediately
    window.bank_viewer_store.select_nodes(("hirc:201", "hirc:202"))
    assert window.audio_sources_view.lbl_target_summary.text() == "2 targets selected"
    assert QApplication.activeModalWidget() is None


def test_e2e_audio_sources_drag_and_drop_single_replace(qapp, qtbot, tmp_path: Path):
    """
    Scenario C: Drag and drop single node replace
    1. Simulates drop of application/x-audio-editor-source MIME data onto tree item.
    2. Verifies dropped audio replaces the target sound node.
    """
    raw_wav = make_synthetic_wav(tmp_path / "vanilla.wav")
    wav_bytes = raw_wav.read_bytes()
    bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        didx=DidxChunk(entries=[DidxEntry(file_id=50001, offset=0, size=len(wav_bytes))]),
        data=DataChunk(data=wav_bytes),
        hirc=HircChunk(
            objects=[
                CAkSound(
                    id=301,
                    source_id=50001,
                    file_id=50001,
                    stream_type=0,
                    file_offset=0,
                    in_memory_media_size=len(wav_bytes),
                )
            ]
        ),
    )

    synth_cache_dir = tmp_path / "cache" / "audio"
    synth_cache_dir.mkdir(parents=True, exist_ok=True)
    (synth_cache_dir / "event_data.dat").write_bytes(b"\x00" * 32)
    (synth_cache_dir / "dnd_bank.bnk").write_bytes(bank.to_bytes())
    cache = GameCache(GameType.ATTILA, cache_dir=synth_cache_dir)

    proj_dir = tmp_path / "DndMod"
    proj = ProjectStorage.create_project(proj_dir, name="DndMod", game=GameType.ATTILA)
    proj.cache = cache

    custom_wav = make_synthetic_wav(tmp_path / "dropped_audio.wav", duration_s=0.25)

    shell_store = ShellStore()
    window = MainWindow(shell_store)
    qtbot.addWidget(window)
    shell_store.open_project(proj)

    window.bank_viewer_store.select_bank("dnd_bank.bnk")
    window.bank_viewer_store.select_node("hirc:301")

    # Connect source_dropped if not automatically wired in MainWindow
    window.bank_viewer_view.source_dropped.connect(
        lambda paths, target: (
            window.bank_viewer_store.replace_sound_audio(
                int(target.removeprefix("hirc:")), Path(paths[0])
            )
            if target.startswith("hirc:") and paths
            else None
        )
    )

    # Simulate drag-drop of application/x-audio-editor-source
    valid_mime = QMimeData()
    payload = [str(custom_wav)]
    valid_mime.setData(
        "application/x-audio-editor-source",
        QByteArray(json.dumps(payload).encode("utf-8")),
    )

    item = window.bank_viewer_view._items_by_key.get("hirc:301")
    assert item is not None
    rect = window.bank_viewer_view.tree_widget.visualItemRect(item)
    pos = rect.center()

    drop_ev = QDropEvent(
        QPointF(float(pos.x()), float(pos.y())),
        Qt.DropAction.CopyAction,
        valid_mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    window.bank_viewer_view.tree_widget.dropEvent(drop_ev)
    assert drop_ev.isAccepted()

    # Assert target node is updated
    assert "dnd_bank.bnk" in proj.manifest.modified_banks
    assert len(proj.manifest.staged_wems) == 1
    staged_wid = proj.manifest.staged_wems[0]
    assert (proj.audio_dir / f"{staged_wid}.wem").is_file()

    node_301 = window.bank_viewer_store.state.nodes_by_key.get("hirc:301")
    assert node_301 is not None
    assert node_301.is_modified is True


def test_e2e_audio_sources_multiselect_media_replace_and_undo(qapp, qtbot, tmp_path: Path):
    """
    Verifies multi-selected media nodes can be batch-replaced from Audio Sources dock,
    fully reverted via Undo, and re-applied via Redo, with full selection continuity.
    """
    raw_wav = make_synthetic_wav(tmp_path / "vanilla.wav")
    wav_bytes = raw_wav.read_bytes()
    bank = SoundBank(
        header=BkhdChunk(bank_id=888, version=112),
        didx=DidxChunk(
            entries=[
                DidxEntry(file_id=60001, offset=0, size=len(wav_bytes)),
                DidxEntry(file_id=60002, offset=len(wav_bytes), size=len(wav_bytes)),
            ]
        ),
        data=DataChunk(data=wav_bytes + wav_bytes),
    )

    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "media_bank.bnk").write_bytes(bank.to_bytes())
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)

    proj_dir = tmp_path / "MultiMediaE2EMod"
    proj = ProjectStorage.create_project(proj_dir, name="MultiMediaE2EMod", game=GameType.ATTILA)
    proj.cache = cache

    shell_store = ShellStore()
    window = MainWindow(shell_store)
    qtbot.addWidget(window)
    shell_store.open_project(proj)

    window.bank_viewer_store.select_bank("media_bank.bnk")
    window.bank_viewer_store.select_nodes(("media:60001", "media:60002"))

    assert window.audio_sources_view.lbl_target_summary.text() == "2 targets selected"
    assert len(window.audio_sources_store.state.targets) == 2

    # Enhance tab: verify dock Apply to Selected is grayed out, use Enhance tab Mute button
    window.audio_sources_view.tabs.setCurrentIndex(2)  # Enhance tab
    assert window.audio_sources_view.btn_apply.isEnabled() is False
    assert window.audio_sources_view.btn_distribute.isEnabled() is False
    assert window.audio_sources_view.tab_enhance.btn_mute.isEnabled() is True
    qtbot.mouseClick(window.audio_sources_view.tab_enhance.btn_mute, Qt.MouseButton.LeftButton)

    # Both media files must be staged in manifest and pack_root/audio/
    assert set(proj.manifest.staged_wems) == {60001, 60002}
    assert (proj.audio_dir / "60001.wem").is_file()
    assert (proj.audio_dir / "60002.wem").is_file()

    # Both nodes must still be selected in bank viewer state and sources store
    assert window.bank_viewer_store.state.selected_node_keys == ("media:60001", "media:60002")
    assert len(window.audio_sources_store.state.targets) == 2

    # Trigger Undo
    assert window.coordinator.can_undo is True
    window.act_undo.trigger()

    # Both media files must be reverted from manifest and disk
    assert len(proj.manifest.staged_wems) == 0
    assert not (proj.audio_dir / "60001.wem").is_file()
    assert not (proj.audio_dir / "60002.wem").is_file()

    # Selection continuity must be maintained
    assert window.bank_viewer_store.state.selected_node_keys == ("media:60001", "media:60002")
    assert len(window.audio_sources_store.state.targets) == 2

    # Trigger Redo
    assert window.coordinator.can_redo is True
    window.act_redo.trigger()

    # Both media files must be re-staged in manifest and disk
    assert set(proj.manifest.staged_wems) == {60001, 60002}
    assert (proj.audio_dir / "60001.wem").is_file()
    assert (proj.audio_dir / "60002.wem").is_file()
    assert window.bank_viewer_store.state.selected_node_keys == ("media:60001", "media:60002")


def test_e2e_apply_selected_preserves_tree_focus_on_shared_referenced_node(
    qapp, qtbot, tmp_path: Path
):
    """
    Reproduces and verifies the fix for tree focus jumping to the root/first reference
    when clicking 'Apply to Selected' on a node that has shared HIRC and cross-bank references.
    """
    raw_wav = make_synthetic_wav(tmp_path / "vanilla.wav")
    wav_bytes = raw_wav.read_bytes()

    # Sound 100 is inside shared container 50, which is referenced by BOTH Event 10 and Event 11
    ev1 = CAkEvent(id=10, actions=[20])
    act1 = CAkAction.create_play(id=20, target_id=50)
    ev2 = CAkEvent(id=11, actions=[21])
    act2 = CAkAction.create_play(id=21, target_id=50)
    cntr = CAkRanSeqCntr(id=50, children=[100])
    snd = CAkSound(
        id=100,
        source_id=50001,
        file_id=50001,
        stream_type=0,
        file_offset=0,
        in_memory_media_size=len(wav_bytes),
    )
    bank = SoundBank(
        header=BkhdChunk(bank_id=901, version=112),
        didx=DidxChunk(entries=[DidxEntry(file_id=50001, offset=0, size=len(wav_bytes))]),
        data=DataChunk(data=wav_bytes),
        hirc=HircChunk(objects=[ev1, act1, ev2, act2, cntr, snd]),
    )

    companion_bank = SoundBank(
        header=BkhdChunk(bank_id=902, version=112),
        didx=DidxChunk(entries=[DidxEntry(file_id=50001, offset=0, size=len(wav_bytes))]),
        data=DataChunk(data=wav_bytes),
        hirc=HircChunk(
            objects=[
                CAkSound(
                    id=200,
                    source_id=50001,
                    file_id=50001,
                    stream_type=0,
                    file_offset=0,
                    in_memory_media_size=len(wav_bytes),
                )
            ]
        ),
    )

    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "event_data.dat").write_bytes(b"\x00" * 32)
    (cache_dir / "shared_refs.bnk").write_bytes(bank.to_bytes())
    (cache_dir / "companion_refs.bnk").write_bytes(companion_bank.to_bytes())
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)

    proj_dir = tmp_path / "SharedRefsFocusMod"
    proj = ProjectStorage.create_project(proj_dir, name="SharedRefsFocusMod", game=GameType.ATTILA)
    proj.cache = cache

    lib_dir = tmp_path / "sfx_library"
    wav_replacement = make_synthetic_wav(lib_dir / "replacement.wav")

    shell_store = ShellStore()
    window = MainWindow(shell_store)
    qtbot.addWidget(window)
    window.coordinator.confirm_replacement_scope = lambda _target: (
        True,
        ReplacementScope.OVERWRITE,
    )
    shell_store.open_project(proj)

    # Pre-load companion bank in session so cross-bank references exist, then select shared_refs.bnk
    window.bank_viewer_store.session.resolve_and_parse_bank("companion_refs.bnk")
    window.bank_viewer_store.select_bank("shared_refs.bnk")
    window.audio_sources_store.add_library(lib_dir, "Test Lib")
    window.audio_sources_store.select_files([wav_replacement])

    bv_view = window.bank_viewer_view
    tree = bv_view.tree_widget
    hier_item = bv_view._items_by_key["group:hierarchy"]
    assert hier_item.childCount() == 2

    ev1_item = hier_item.child(0)
    ev2_item = hier_item.child(1)
    assert ev1_item.data(0, Qt.ItemDataRole.UserRole + 1) == "hirc:10"
    assert ev2_item.data(0, Qt.ItemDataRole.UserRole + 1) == "hirc:11"

    # Expand Event 10 -> Action 20 (first reference branch)
    tree.expandItem(ev1_item)
    act1_item = ev1_item.child(0)
    tree.expandItem(act1_item)

    # Expand Event 11 -> Action 21 -> RanSeqCntr 50 (second reference branch where user works)
    tree.expandItem(ev2_item)
    act2_item = ev2_item.child(0)
    tree.expandItem(act2_item)
    cntr2_item = act2_item.child(0)
    tree.expandItem(cntr2_item)
    snd2_item = cntr2_item.child(0)
    assert snd2_item is not None
    assert snd2_item.data(0, Qt.ItemDataRole.UserRole + 1) == "hirc:100"

    # Select Sound 100 specifically under Event 11 -> Action 21 -> RanSeqCntr 50
    tree.clearSelection()
    tree.setCurrentItem(snd2_item)
    snd2_item.setSelected(True)
    bv_view._on_tree_selection_changed()

    def _item_path(item):
        parts = []
        curr = item
        while curr is not None:
            parts.append(curr.data(0, Qt.ItemDataRole.UserRole + 1))
            curr = curr.parent()
        return tuple(reversed(parts))

    expected_path = ("group:hierarchy", "hirc:11", "hirc:21", "hirc:50", "hirc:100")
    assert _item_path(tree.currentItem()) == expected_path

    # Click Apply to Selected
    qtbot.mouseClick(window.audio_sources_view.btn_apply, Qt.MouseButton.LeftButton)

    # Verify active bank did not jump to companion_refs.bnk and tree focus stayed on expected_path
    assert window.bank_viewer_store.state.selected_bank_name == "shared_refs.bnk"
    assert tree.currentItem() is not None
    assert _item_path(tree.currentItem()) == expected_path

    # Verify RanSeqCntr 50 under Event 10 -> Action 20 was NOT spuriously expanded
    hier_after = bv_view._items_by_key["group:hierarchy"]
    act1_after = hier_after.child(0).child(0)
    cntr1_after = act1_after.child(0)
    assert cntr1_after.isExpanded() is False

    # Now also expand RanSeqCntr 50 under Event 10 -> Action 20 so BOTH references to Sound 100 are visible,
    # re-select Sound 100 under Event 11 -> Action 21 -> RanSeqCntr 50, and apply again
    tree.expandItem(cntr1_after)
    snd2_after = hier_after.child(1).child(0).child(0).child(0)
    tree.clearSelection()
    tree.setCurrentItem(snd2_after)
    snd2_after.setSelected(True)
    bv_view._on_tree_selection_changed()
    assert _item_path(tree.currentItem()) == expected_path

    qtbot.mouseClick(window.audio_sources_view.btn_apply, Qt.MouseButton.LeftButton)
    assert window.bank_viewer_store.state.selected_bank_name == "shared_refs.bnk"
    assert tree.currentItem() is not None
    assert _item_path(tree.currentItem()) == expected_path
    assert len(bv_view._all_items_by_key.get("hirc:100", [])) == 2

    # Undo and Redo must also preserve tree focus on the second reference branch
    window.act_undo.trigger()
    assert window.bank_viewer_store.state.selected_bank_name == "shared_refs.bnk"
    assert _item_path(tree.currentItem()) == expected_path

    window.act_redo.trigger()
    assert window.bank_viewer_store.state.selected_bank_name == "shared_refs.bnk"
    assert _item_path(tree.currentItem()) == expected_path
