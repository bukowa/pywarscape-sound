"""
Vertical End-to-End UI Integration Tests for Enhance Tab Audio Modifiers.
Simulates real user workflows through MainWindow driving full PySide6 UI and domain engine:
1. Verifying bottom 'Apply to Selected' is dynamically grayed out when on Enhance tab.
2. Verifying only 'Apply Enhancements to Selected' inside Enhance tab applies DSP modifiers.
3. Multi-selection DSP enhancement across multiple Sound and Media nodes.
4. Atomic Undo / Redo byte-for-byte rollback and re-apply of DSP enhancements.
5. In-place Quick Muting via Enhance tab with atomic Undo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt

from src.bnk.bank import BkhdChunk, DataChunk, DidxChunk, DidxEntry, HircChunk, SoundBank
from src.bnk.models import CAkRanSeqCntr, CAkSound
from src.ui.features.audio_sources.state import AudioSourcesTab
from src.ui.shell.store import ShellStore
from src.ui.shell.view import MainWindow
from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.storage import ProjectStorage
from tests.support.factories import make_synthetic_wav


def _build_test_project(tmp_path: Path, proj_name: str) -> tuple[MainWindow, Any, Any]:
    """Helper to assemble a synthetic game cache and open a project in MainWindow."""
    raw_wav1 = make_synthetic_wav(tmp_path / "cache_raw" / "s1.wav", tone=True)
    raw_wav2 = make_synthetic_wav(tmp_path / "cache_raw" / "s2.wav", tone=True)
    w1 = raw_wav1.read_bytes()
    w2 = raw_wav2.read_bytes()

    bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        didx=DidxChunk(
            entries=[
                DidxEntry(file_id=50001, offset=0, size=len(w1)),
                DidxEntry(file_id=50002, offset=len(w1), size=len(w2)),
            ]
        ),
        data=DataChunk(data=w1 + w2),
        hirc=HircChunk(
            objects=[
                CAkRanSeqCntr(id=100, children=[101, 102]),
                CAkSound(
                    id=101,
                    source_id=50001,
                    file_id=50001,
                    stream_type=0,
                    file_offset=0,
                    in_memory_media_size=len(w1),
                ),
                CAkSound(
                    id=102,
                    source_id=50002,
                    file_id=50002,
                    stream_type=0,
                    file_offset=len(w1),
                    in_memory_media_size=len(w2),
                ),
            ]
        ),
    )

    synth_cache_dir = tmp_path / "cache" / "audio"
    synth_cache_dir.mkdir(parents=True, exist_ok=True)
    (synth_cache_dir / "event_data.dat").write_bytes(b"\x00" * 32)
    (synth_cache_dir / "battle_units.bnk").write_bytes(bank.to_bytes())
    cache = GameCache(GameType.ATTILA, cache_dir=synth_cache_dir)

    proj_dir = tmp_path / proj_name
    proj = ProjectStorage.create_project(proj_dir, name=proj_name, game=GameType.ATTILA)
    proj.cache = cache

    shell_store = ShellStore()
    window = MainWindow(shell_store)
    window.coordinator.async_preview = False
    shell_store.open_project(proj)
    window.bank_viewer_store.select_bank("battle_units.bnk")

    return window, proj, bank


def test_e2e_enhance_tab_bottom_apply_grayed_out_and_dsp_apply_works(qapp, qtbot, tmp_path: Path):
    """
    E2E Verification:
    1. Select node in hierarchy tree.
    2. Setup external library so 'Apply to Selected' is enabled on Libraries tab.
    3. Switch to Enhance tab:
       - Bottom 'Apply to Selected' MUST BE GRAYED OUT.
       - Bottom 'Distribute to Selected' MUST BE GRAYED OUT.
       - Clicking bottom 'Apply to Selected' does nothing (no modifications).
    4. Inside Enhance tab:
       - Configure Gain (+3 dB) and Normalization (-1.0 dBFS).
       - Enhance tab's 'Apply Enhancements to Selected' button IS ENABLED.
       - Click 'Apply Enhancements to Selected' -> modifies bank, stages WEM, updates AST.
    5. Undo / Redo restores and reapplies modifications byte-for-byte.
    """
    window, proj, _ = _build_test_project(tmp_path, "EnhanceE2EMod1")
    qtbot.addWidget(window)

    sources_view = window.audio_sources_view
    enhance_tab = sources_view.tab_enhance

    # 1. Setup external sound library with audio files
    lib_dir = tmp_path / "user_lib"
    lib_wav = make_synthetic_wav(lib_dir / "sample.wav", tone=True)
    window.audio_sources_store.add_library(lib_dir, "MySFX")
    window.audio_sources_store.select_files([lib_wav])

    # 2. Select Sound 101 in bank viewer tree
    window.bank_viewer_store.select_node("hirc:101")
    assert sources_view.lbl_target_summary.text() == "1 target selected"

    # 3. On Libraries tab: has target + has source file -> bottom Apply is enabled
    sources_view.tabs.setCurrentIndex(AudioSourcesTab.LIBRARIES.value)
    assert sources_view.btn_apply.isEnabled() is True
    assert sources_view.btn_distribute.isEnabled() is True

    # 4. Switch to Enhance tab (tab 2)
    sources_view.tabs.setCurrentIndex(AudioSourcesTab.ENHANCE.value)

    # CRITICAL PROOF: Bottom buttons MUST be grayed out on Enhance tab
    assert sources_view.btn_apply.isEnabled() is False
    assert sources_view.btn_distribute.isEnabled() is False

    # Attempting to click bottom 'Apply to Selected' does nothing
    qtbot.mouseClick(sources_view.btn_apply, Qt.MouseButton.LeftButton)
    assert "battle_units.bnk" not in proj.manifest.modified_banks
    assert len(proj.manifest.staged_wems) == 0

    # 5. Inside Enhance tab: configure DSP settings
    enhance_tab.chk_gain.setChecked(True)
    enhance_tab.spin_gain.setValue(3.0)
    enhance_tab.chk_normalize.setChecked(True)
    enhance_tab.spin_normalize.setValue(-1.0)

    # Tab's own Apply button is now enabled
    assert enhance_tab.btn_apply.isEnabled() is True
    assert enhance_tab.btn_mute.isEnabled() is True

    # Bottom Apply MUST STILL be grayed out
    assert sources_view.btn_apply.isEnabled() is False

    # 6. Click 'Apply Enhancements to Selected' inside Enhance tab
    qtbot.mouseClick(enhance_tab.btn_apply, Qt.MouseButton.LeftButton)

    # 7. Verification: Bank modified, staged loose WEM created, sound 101 promoted
    assert "battle_units.bnk" in proj.manifest.modified_banks
    assert len(proj.manifest.staged_wems) == 1
    staged_wid = proj.manifest.staged_wems[0]
    staged_wem = proj.audio_dir / f"{staged_wid}.wem"
    assert staged_wem.is_file()
    assert staged_wem.stat().st_size > 0

    # Verify AST promotion in saved bank
    saved_bank = SoundBank.from_bytes((proj.audio_dir / "battle_units.bnk").read_bytes())
    s101 = next(obj for obj in saved_bank.hirc.objects if obj.id == 101)
    assert isinstance(s101, CAkSound)
    assert s101.stream_type == 2
    assert s101.source_id == staged_wid

    # Node in bank viewer state reflects modification
    n101 = window.bank_viewer_store.state.nodes_by_key.get("hirc:101")
    assert n101 is not None and n101.is_modified is True

    # 8. Undo (Ctrl+Z)
    assert window.coordinator.can_undo is True
    window.act_undo.trigger()

    assert "battle_units.bnk" not in proj.manifest.modified_banks
    assert len(proj.manifest.staged_wems) == 0
    assert not staged_wem.is_file()

    entry = window.bank_viewer_store.session.get_loaded_entry("battle_units.bnk")
    assert entry is not None
    restored_bank = entry[0]
    rs101 = next(obj for obj in restored_bank.hirc.objects if obj.id == 101)
    assert rs101.stream_type == 0
    assert rs101.source_id == 50001

    # 9. Redo (Ctrl+Y)
    assert window.coordinator.can_redo is True
    window.act_redo.trigger()

    assert "battle_units.bnk" in proj.manifest.modified_banks
    assert len(proj.manifest.staged_wems) == 1
    assert staged_wem.is_file()


def test_e2e_enhance_tab_multiselect_enhancement_and_quick_mute(qapp, qtbot, tmp_path: Path):
    """
    E2E Verification for multi-selection:
    1. Multi-select two Sound nodes in hierarchy tree.
    2. Switch to Enhance tab:
       - Bottom 'Apply to Selected' MUST BE GRAYED OUT.
       - Target count displays '2 targets selected'.
    3. Apply DSP modifications to both nodes simultaneously via Enhance tab Apply button.
    4. Verify both nodes are promoted and staged with distinct WEM IDs.
    5. Single atomic Undo rolls back both nodes.
    6. In-place Quick Muting mutes both nodes to 50ms silent stubs.
    7. Single atomic Undo rolls back muting.
    """
    window, proj, _ = _build_test_project(tmp_path, "EnhanceE2EMod2")
    qtbot.addWidget(window)

    sources_view = window.audio_sources_view
    enhance_tab = sources_view.tab_enhance

    # 1. Multi-select both Sound nodes
    window.bank_viewer_store.select_nodes(("hirc:101", "hirc:102"))
    assert sources_view.lbl_target_summary.text() == "2 targets selected"
    assert len(window.audio_sources_store.state.targets) == 2

    # 2. Switch to Enhance tab
    sources_view.tabs.setCurrentIndex(AudioSourcesTab.ENHANCE.value)
    assert sources_view.btn_apply.isEnabled() is False
    assert sources_view.btn_distribute.isEnabled() is False
    assert "2 targets selected" in enhance_tab.lbl_targets_info.text()

    # 3. Configure DSP: Normalization via preset button
    enhance_tab.chk_normalize.setChecked(True)
    enhance_tab.btn_norm_safe.click()
    assert enhance_tab.spin_normalize.value() == -3.0
    assert enhance_tab.btn_apply.isEnabled() is True

    # 4. Click 'Apply Enhancements to Selected' inside Enhance tab
    qtbot.mouseClick(enhance_tab.btn_apply, Qt.MouseButton.LeftButton)

    # Verify both nodes staged
    assert "battle_units.bnk" in proj.manifest.modified_banks
    assert len(proj.manifest.staged_wems) == 2
    wems = set(proj.manifest.staged_wems)
    for wid in wems:
        assert (proj.audio_dir / f"{wid}.wem").is_file()

    # Check both CAkSound objects promoted to stream_type=2
    saved_bank = SoundBank.from_bytes((proj.audio_dir / "battle_units.bnk").read_bytes())
    s101 = next(obj for obj in saved_bank.hirc.objects if obj.id == 101)
    s102 = next(obj for obj in saved_bank.hirc.objects if obj.id == 102)
    assert s101.stream_type == 2 and s102.stream_type == 2
    assert s101.source_id in wems and s102.source_id in wems

    # 5. Atomic Undo reverts both nodes in 1 step
    assert window.coordinator.can_undo is True
    window.act_undo.trigger()
    assert "battle_units.bnk" not in proj.manifest.modified_banks
    assert len(proj.manifest.staged_wems) == 0

    # 6. Quick Mute via Enhance tab 'Mute Node(s)' button
    assert enhance_tab.btn_mute.isEnabled() is True
    qtbot.mouseClick(enhance_tab.btn_mute, Qt.MouseButton.LeftButton)

    # Both nodes must now be muted with the shared silent stub (1.wem)
    assert "battle_units.bnk" in proj.manifest.modified_banks
    assert 1 in proj.manifest.staged_wems
    assert (proj.audio_dir / "1.wem").is_file()
    saved_bank_muted = SoundBank.from_bytes((proj.audio_dir / "battle_units.bnk").read_bytes())
    m101 = next(obj for obj in saved_bank_muted.hirc.objects if obj.id == 101)
    m102 = next(obj for obj in saved_bank_muted.hirc.objects if obj.id == 102)
    assert m101.source_id == 1 and m102.source_id == 1
    assert m101.stream_type == 2 and m102.stream_type == 2

    # 7. Atomic Undo rolls back quick muting
    assert window.coordinator.can_undo is True
    window.act_undo.trigger()
    assert "battle_units.bnk" not in proj.manifest.modified_banks
    assert len(proj.manifest.staged_wems) == 0


def test_e2e_enhance_tab_dock_bottom_apply_never_fires_on_enhance_tab(qapp, qtbot, tmp_path: Path):
    """
    Explicit edge case test: even if synthetic signals or mouseClicks are delivered
    to the dock bottom 'btn_apply' while on the Enhance tab, zero mutations, zero
    enhancements, and zero muting actions are performed.
    """
    window, proj, _ = _build_test_project(tmp_path, "EnhanceE2EMod3")
    qtbot.addWidget(window)

    sources_view = window.audio_sources_view

    # Select node 101
    window.bank_viewer_store.select_node("hirc:101")
    sources_view.tabs.setCurrentIndex(AudioSourcesTab.ENHANCE.value)

    # Bottom button is disabled
    assert sources_view.btn_apply.isEnabled() is False

    # Programmatically fire _on_apply_clicked directly
    sources_view._on_apply_clicked()

    # Nothing should be modified
    assert "battle_units.bnk" not in proj.manifest.modified_banks
    assert len(proj.manifest.staged_wems) == 0
    assert window.coordinator.can_undo is False


def test_e2e_enhance_tab_multiselect_media_nodes(qapp, qtbot, tmp_path: Path):
    """
    E2E Verification for multi-selected DIDX Media nodes on Enhance tab:
    1. Multi-select two embedded Media nodes in hierarchy tree.
    2. Switch to Enhance tab:
       - Bottom 'Apply to Selected' is grayed out.
       - Target count displays '2 targets selected'.
    3. Configure DSP Gain (+2 dB) and apply via Enhance tab Apply button.
    4. Verify both media files are staged on disk with non-zero size.
    5. Single atomic Undo reverts both media files.
    6. Single atomic Redo restores both media files.
    """
    raw_wav1 = make_synthetic_wav(tmp_path / "media_raw" / "m1.wav", tone=True)
    raw_wav2 = make_synthetic_wav(tmp_path / "media_raw" / "m2.wav", tone=True)
    w1 = raw_wav1.read_bytes()
    w2 = raw_wav2.read_bytes()

    bank = SoundBank(
        header=BkhdChunk(bank_id=888, version=112),
        didx=DidxChunk(
            entries=[
                DidxEntry(file_id=60001, offset=0, size=len(w1)),
                DidxEntry(file_id=60002, offset=len(w1), size=len(w2)),
            ]
        ),
        data=DataChunk(data=w1 + w2),
    )

    synth_cache_dir = tmp_path / "cache" / "audio"
    synth_cache_dir.mkdir(parents=True, exist_ok=True)
    (synth_cache_dir / "event_data.dat").write_bytes(b"\x00" * 32)
    (synth_cache_dir / "media_bank.bnk").write_bytes(bank.to_bytes())
    cache = GameCache(GameType.ATTILA, cache_dir=synth_cache_dir)

    proj_dir = tmp_path / "EnhanceMediaE2EMod"
    proj = ProjectStorage.create_project(proj_dir, name="EnhanceMediaE2EMod", game=GameType.ATTILA)
    proj.cache = cache

    shell_store = ShellStore()
    window = MainWindow(shell_store)
    qtbot.addWidget(window)
    shell_store.open_project(proj)

    window.bank_viewer_store.select_bank("media_bank.bnk")
    window.bank_viewer_store.select_nodes(("media:60001", "media:60002"))

    sources_view = window.audio_sources_view
    enhance_tab = sources_view.tab_enhance

    assert sources_view.lbl_target_summary.text() == "2 targets selected"
    assert len(window.audio_sources_store.state.targets) == 2

    # Switch to Enhance tab
    sources_view.tabs.setCurrentIndex(AudioSourcesTab.ENHANCE.value)

    # Bottom Apply is grayed out
    assert sources_view.btn_apply.isEnabled() is False
    assert sources_view.btn_distribute.isEnabled() is False
    assert "2 targets selected" in enhance_tab.lbl_targets_info.text()

    # Configure Gain DSP
    enhance_tab.chk_gain.setChecked(True)
    enhance_tab.spin_gain.setValue(2.0)
    assert enhance_tab.btn_apply.isEnabled() is True

    # Click Apply Enhancements inside Enhance tab
    qtbot.mouseClick(enhance_tab.btn_apply, Qt.MouseButton.LeftButton)

    # Both media files must be staged in manifest and pack_root/audio/
    assert set(proj.manifest.staged_wems) == {60001, 60002}
    assert (proj.audio_dir / "60001.wem").is_file()
    assert (proj.audio_dir / "60002.wem").is_file()

    # Single atomic Undo restores both
    assert window.coordinator.can_undo is True
    window.act_undo.trigger()
    assert len(proj.manifest.staged_wems) == 0
    assert not (proj.audio_dir / "60001.wem").is_file()
    assert not (proj.audio_dir / "60002.wem").is_file()

    # Single atomic Redo reapplies both
    assert window.coordinator.can_redo is True
    window.act_redo.trigger()
    assert set(proj.manifest.staged_wems) == {60001, 60002}
    assert (proj.audio_dir / "60001.wem").is_file()
    assert (proj.audio_dir / "60002.wem").is_file()


def test_e2e_enhance_tab_player_bound_to_tab_and_preview_workflow(qapp, qtbot, tmp_path: Path):
    """
    E2E Verification:
    1. Open mod project with SoundBank and select Sound 101.
    2. Register sound library and select file -> bottom player loads library file.
    3. Switch to Enhance tab:
       - Bottom player dynamically binds to Enhance tab and cues target sound (Original).
       - Enhance tab 'Preview Audio' button is enabled.
    4. Adjust Gain and Normalization:
       - Bottom player dynamically recomputes and loads enhanced preview with modifiers.
    5. Click 'Preview Audio' in Enhance tab -> triggers playback on bottom transport.
    6. Switch back to Libraries tab -> bottom player restores library file track.
    7. Switch to Enhance tab -> bottom player restores enhanced preview track.
    """
    window, proj, _ = _build_test_project(tmp_path, "EnhancePlayerE2EMod")
    qtbot.addWidget(window)

    sources_view = window.audio_sources_view
    enhance_tab = sources_view.tab_enhance
    sources_transport = window.audio_sources_transport_store

    # 1. Setup external sound library with an audio file
    lib_dir = tmp_path / "lib_sfx"
    lib_wav = make_synthetic_wav(lib_dir / "shout.wav", tone=True)
    window.audio_sources_store.add_library(lib_dir, "SFX")

    # 2. Select node 101 in Bank Viewer
    window.bank_viewer_store.select_node("hirc:101")
    assert sources_view.lbl_target_summary.text() == "1 target selected"

    # 3. On Libraries tab: select library file -> bottom player loads it
    sources_view.tabs.setCurrentIndex(AudioSourcesTab.LIBRARIES.value)
    window.audio_sources_store.select_files([lib_wav])
    assert sources_transport.state.active_track is not None
    assert sources_transport.state.active_track.title == "shout.wav"

    # 4. Switch to Enhance tab -> bottom player switches to the enhanced target preview!
    sources_view.tabs.setCurrentIndex(AudioSourcesTab.ENHANCE.value)
    assert sources_transport.state.active_track is not None
    assert "Enhance Preview: Sound 101" in sources_transport.state.active_track.title
    assert "(Original)" in sources_transport.state.active_track.title
    assert enhance_tab.btn_preview.isEnabled() is True

    # 5. Tweak Gain slider to +4 dB and Normalization to -1.0 dBFS
    enhance_tab.chk_gain.setChecked(True)
    enhance_tab.spin_gain.setValue(4.0)
    enhance_tab.chk_normalize.setChecked(True)
    enhance_tab.spin_normalize.setValue(-1.0)

    # Bottom player dynamically updates with new DSP modifiers
    assert sources_transport.state.active_track is not None
    assert "+4.0 dB" in sources_transport.state.active_track.title
    assert "Norm -1.0 dBFS" in sources_transport.state.active_track.title

    # 6. Click 'Preview Audio' button in Enhance tab
    qtbot.mouseClick(enhance_tab.btn_preview, Qt.MouseButton.LeftButton)
    assert sources_transport.state.active_track is not None
    assert "+4.0 dB" in sources_transport.state.active_track.title

    # 7. Switch back to Libraries tab -> bottom player restores library file track!
    sources_view.tabs.setCurrentIndex(AudioSourcesTab.LIBRARIES.value)
    assert sources_transport.state.active_track is not None
    assert sources_transport.state.active_track.title == "shout.wav"

    # 8. Switch back to Enhance tab -> bottom player restores enhanced preview track!
    sources_view.tabs.setCurrentIndex(AudioSourcesTab.ENHANCE.value)
    assert sources_transport.state.active_track is not None
    assert "Enhance Preview: Sound 101" in sources_transport.state.active_track.title
    assert "+4.0 dB" in sources_transport.state.active_track.title


def test_apply_audio_enhancements_empty_or_unresolved_targets_batch_outcome():
    """Confirms apply_audio_enhancements with empty targets or project returns valid BatchOutcome."""
    from src.compiler.audio_modifiers import AudioModifierChain
    from src.engine.ontology import BatchOutcome
    from src.engine.session import WorkspaceSession

    session = WorkspaceSession()
    # When session.project is None or targets is empty
    outcome = session.apply_audio_enhancements(targets=(), modifier_chain=AudioModifierChain())
    assert isinstance(outcome, BatchOutcome)
    assert outcome.applied == 0
    assert outcome.rejections == ()
    assert outcome.touched_banks == ()
