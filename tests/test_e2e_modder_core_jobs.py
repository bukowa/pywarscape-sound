"""
End-to-End Modder Core Jobs & Engine Playability Gate (Task 16).

Drives MainWindow via qtbot through all 6 core modder workflows, validating
Layer 1-4 synchronization, transactional Undo/Redo bit-exactness, and compiled
PFH4 Movie pack engine playability through assert_pack_engine_playable:

1. Job 1: Replace a Campaign/Battle Song (CAkMusicTrack + CAkMusicSegment) & Compile Pack
2. Job 2: Replace & Export a Multi-Source Combat Transition Sub-Track (hirc:<id>:src:1)
3. Job 3: Replace an Embedded Sound in non-trivial *_data.bnk (projectiles_explosion_data.bnk -> battle_projectiles.bnk)
4. Job 4: Cross-Bank Unopened Shared Recording Detection & Isolate vs. Per-Slot Revert
5. Job 5: Parent Container Selection (CAkRanSeqCntr) & Drag-and-Drop Multi-File Distribution
6. Job 6: Slot-Local Volume/Pitch Tuning (NodeBaseParams) & Appending a Pool Variation (AppendVariationIntent)
"""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt

from src.bnk.bank import BkhdChunk, DataChunk, DidxChunk, DidxEntry, HircChunk, SoundBank
from src.bnk.models import (
    AkDecisionTree,
    AkMusicMarker,
    AkMusicRanSeqPlaylistItem,
    AkMusicTrackSource,
    AkMusicTransNodeParams,
    AkPlaylistItem,
    AkTrackSrcInfo,
    CAkAction,
    CAkEvent,
    CAkMusicRanSeqCntr,
    CAkMusicSegment,
    CAkMusicSwitchCntr,
    CAkMusicTrack,
    CAkRanSeqCntr,
    CAkSound,
    CAkSwitchCntr,
    DecisionTreeNode,
    NodeBaseParams,
)
from src.bnk.wem import WemFormatTag, WemHeader, build_silent_pcm_wem_bytes, parse_wem_header
from src.compiler.pfh4_pack import extract_pfh4_file, read_pfh4_index
from src.engine.ontology import (
    ExternalFileSource,
    ReplacementScope,
)
from src.models import AudioCatalogEntry
from src.ui.features.audio_sources.state import AudioSourcesTab
from src.ui.shell.store import ShellStore
from src.ui.shell.view import MainWindow
from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.health import PackPreflightError
from src.workspace.storage import ProjectStorage
from tests.support.factories import make_synthetic_wav


def extract_pfh4_pack(pack_path: str | Path) -> dict[str, bytes]:
    """Extracts all virtual files from a PFH4 pack into a dictionary."""
    entries = read_pfh4_index(pack_path)
    return {entry.path.replace("\\", "/"): extract_pfh4_file(pack_path, entry) for entry in entries}


def assert_pack_engine_playable(pack_path: Path) -> None:
    """Verifies that a compiled PFH4 Movie pack satisfies engine playability invariants:

    1. The pack file exists and contains valid entries.
    2. Every .bnk inside the pack parses cleanly via SoundBank.from_bytes(b) and
       round-trips bit-identically (bank.to_bytes() == b).
    3. Every .wem inside the pack has a valid RIFF/WAVE header (parse_wem_header),
       channels in (1, 2), sample_rate > 0, and data_size > 0.
    4. Every CAkSound and CAkMusicTrack source in any packed .bnk whose source_id
       is a packed .wem has:
       - stream_type == 2 (Streamed),
       - plugin_id == 0x00010001 (PCM) when .wem header format_tag in (0x0001, 0xFFFE, WemFormatTag.EXTENSIBLE),
       - plugin_id == 0x00040001 (Vorbis) when .wem header format_tag in (0xFFFF, WemFormatTag.VORBIS).
    5. For CAkMusicSegment, markers are in non-decreasing ascending order
       (markers[i].position <= markers[i+1].position) and if markers exist,
       markers[-1].position == pytest.approx(segment.duration).
    """
    assert pack_path.is_file(), f"Compiled pack file does not exist: {pack_path}"
    extracted = extract_pfh4_pack(pack_path)
    assert extracted, f"Pack archive {pack_path.name} contains no entries"

    packed_wems: dict[int, WemHeader] = {}
    packed_banks: dict[str, SoundBank] = {}

    for rel_path, data in extracted.items():
        lower_path = rel_path.lower()
        if lower_path.endswith(".bnk"):
            bank = SoundBank.from_bytes(data)
            assert bank.to_bytes() == data, f"Bank {rel_path} failed bit-exact round-trip"
            packed_banks[rel_path] = bank
        elif lower_path.endswith(".wem"):
            try:
                wem_id = int(Path(rel_path).stem)
            except ValueError:
                wem_id = -1
            header = parse_wem_header(data)
            assert header.form_type == "WAVE", (
                f"WEM {rel_path} form_type is {header.form_type}, expected WAVE"
            )
            assert header.channels in (1, 2), (
                f"WEM {rel_path} channels {header.channels} not 1 or 2"
            )
            assert header.sample_rate > 0, (
                f"WEM {rel_path} invalid sample rate {header.sample_rate}"
            )
            assert header.data_size > 0, f"WEM {rel_path} empty data payload {header.data_size}"
            if wem_id != -1:
                packed_wems[wem_id] = header

    for bank_path, bank in packed_banks.items():
        if not bank.hirc or not bank.hirc.objects:
            continue
        for obj in bank.hirc.objects:
            if isinstance(obj, CAkSound):
                if obj.source_id in packed_wems:
                    wem_hdr = packed_wems[obj.source_id]
                    assert obj.stream_type == 2, (
                        f"Bank {bank_path} sound {obj.id} stream_type is {obj.stream_type}, expected 2 (Streamed)"
                    )
                    if wem_hdr.format_tag in (0x0001, 0xFFFE, WemFormatTag.EXTENSIBLE):
                        assert obj.plugin_id == 0x00010001, (
                            f"Bank {bank_path} sound {obj.id} plugin_id is 0x{obj.plugin_id:08x}, expected 0x00010001"
                        )
                    elif wem_hdr.format_tag in (0xFFFF, WemFormatTag.VORBIS):
                        assert obj.plugin_id == 0x00040001, (
                            f"Bank {bank_path} sound {obj.id} plugin_id is 0x{obj.plugin_id:08x}, expected 0x00040001"
                        )
            elif isinstance(obj, CAkMusicTrack):
                for idx, src in enumerate(obj.sources):
                    if src.source_id in packed_wems:
                        wem_hdr = packed_wems[src.source_id]
                        assert src.stream_type == 2, (
                            f"Bank {bank_path} track {obj.id} source[{idx}] stream_type is {src.stream_type}, expected 2 (Streamed)"
                        )
                        if wem_hdr.format_tag in (0x0001, 0xFFFE, WemFormatTag.EXTENSIBLE):
                            assert src.plugin_id == 0x00010001, (
                                f"Bank {bank_path} track {obj.id} source[{idx}] plugin_id is 0x{src.plugin_id:08x}, expected 0x00010001"
                            )
                        elif wem_hdr.format_tag in (0xFFFF, WemFormatTag.VORBIS):
                            assert src.plugin_id == 0x00040001, (
                                f"Bank {bank_path} track {obj.id} source[{idx}] plugin_id is 0x{src.plugin_id:08x}, expected 0x00040001"
                            )
            elif isinstance(obj, CAkMusicSegment):
                if obj.markers:
                    for i in range(len(obj.markers) - 1):
                        assert obj.markers[i].position <= obj.markers[i + 1].position, (
                            f"Bank {bank_path} segment {obj.id} markers not sorted: {obj.markers[i].position} > {obj.markers[i + 1].position}"
                        )
                    assert obj.markers[-1].position == pytest.approx(obj.duration), (
                        f"Bank {bank_path} segment {obj.id} last marker position {obj.markers[-1].position} != duration {obj.duration}"
                    )


def _make_synthetic_stereo_wav(
    path: Path,
    duration_s: float = 0.5,
    sample_rate: int = 32000,
) -> Path:
    """Generates a valid 2-channel stereo PCM WAV file for testing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n_frames = int(duration_s * sample_rate)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00\x00\x00" * n_frames)
    return path


def _setup_e2e_project(
    tmp_path: Path,
    proj_name: str,
    banks: dict[str, SoundBank],
) -> tuple[MainWindow, Any, Path]:
    """Helper to assemble a synthetic game cache and open a project in MainWindow."""
    cache_dir = tmp_path / f"cache_{proj_name}" / "audio"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "event_data.dat").write_bytes(b"\x00" * 32)
    for b_name, b_obj in banks.items():
        (cache_dir / b_name).write_bytes(b_obj.to_bytes())

    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)
    proj_dir = tmp_path / proj_name
    project = ProjectStorage.create_project(
        proj_dir, name=proj_name, game=GameType.ATTILA, cache=cache
    )
    output_pack_path = proj_dir / f"{proj_name}.pack"
    project.set_output_pack_path(output_pack_path)

    shell_store = ShellStore()
    settings_file = tmp_path / f"settings_{proj_name}.json"
    window = MainWindow(shell_store, settings_file=settings_file)
    shell_store.open_project(project)
    return window, project, cache_dir


# =============================================================================
# Job 1: Replace a Campaign/Battle Song & Compile Pack
# =============================================================================


def test_job1_replace_campaign_battle_song_and_compile_pack(qtbot, tmp_path: Path, monkeypatch):
    """Job 1: Replace a Song (CAkMusicTrack + CAkMusicSegment) with stereo audio and compile playable pack."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData1"))

    # Construct global_music.bnk hierarchy:
    # SwitchCntr (1000) -> RanSeqCntr (1100) -> Segment (1200) -> Track (1300)
    tree = AkDecisionTree(nodes=[DecisionTreeNode(key=0, audio_node_id=1100, is_leaf=True)])
    sw = CAkMusicSwitchCntr(
        id=1000, trans_params=AkMusicTransNodeParams(children=[1100]), tree=tree
    )
    rs = CAkMusicRanSeqCntr(
        id=1100,
        trans_params=AkMusicTransNodeParams(children=[1200]),
        playlist=[AkMusicRanSeqPlaylistItem(segment_id=1200, playlist_item_id=1)],
    )
    seg = CAkMusicSegment(
        id=1200,
        child_ids=[1300],
        duration=5000.0,
        markers=[
            AkMusicMarker(id=1, position=0.0, name="<Entry>"),
            AkMusicMarker(id=2, position=2500.0, name="Cue_Battle"),
            AkMusicMarker(id=3, position=5000.0, name="<Exit>"),
        ],
    )
    trk = CAkMusicTrack(
        id=1300,
        sources=[
            AkMusicTrackSource(
                plugin_id=0x00040001,
                stream_type=2,
                source_id=30001,
                file_id=30001,
            )
        ],
        playlist=[AkTrackSrcInfo(track_id=1300, source_id=30001, src_duration=5000.0)],
    )
    bank = SoundBank(
        header=BkhdChunk(bank_id=901, version=112),
        hirc=HircChunk(objects=[sw, rs, seg, trk]),
    )

    window, project, cache_dir = _setup_e2e_project(tmp_path, "Job1Mod", {"global_music.bnk": bank})
    qtbot.addWidget(window)

    vanilla_bytes = (cache_dir / "global_music.bnk").read_bytes()

    # Select bank and MusicSegment node in tree
    bv_store = window.bank_viewer_store
    bv_view = window.bank_viewer_view
    bv_store.select_bank("global_music.bnk")
    bv_store.select_node("hirc:1200")

    item1200 = bv_view._items_by_key.get("hirc:1200")
    assert item1200 is not None
    bv_view.tree_widget.setCurrentItem(item1200)
    item1200.setSelected(True)
    bv_view._on_tree_selection_changed()

    assert window.audio_sources_view.lbl_target_summary.text() == "1 target selected"

    # Supply custom stereo WAV with duration 8.0s (8000ms)
    stereo_wav = _make_synthetic_stereo_wav(tmp_path / "song_stereo.wav", duration_s=8.0)
    window.audio_sources_store.select_files([str(stereo_wav)])
    assert window.audio_sources_view.btn_apply.isEnabled() is True
    qtbot.mouseClick(window.audio_sources_view.btn_apply, Qt.MouseButton.LeftButton)

    # Compile Movie Pack and verify engine playability
    window._on_build_pack_triggered()
    output_pack = Path(project.manifest.output_pack_path)
    assert output_pack.is_file()
    assert_pack_engine_playable(output_pack)

    # Verify stereo channels (2) are preserved in staged WEM
    assert len(project.manifest.staged_wems) == 1
    staged_wid = project.manifest.staged_wems[0]
    staged_wem_bytes = (project.audio_dir / f"{staged_wid}.wem").read_bytes()
    hdr = parse_wem_header(staged_wem_bytes)
    assert hdr.channels == 2
    assert hdr.format_tag in (0xFFFE, WemFormatTag.EXTENSIBLE)

    # Verify CAkMusicTrack updated to plugin_id 0x00010001 and stream_type 2
    entry = bv_store.session.get_loaded_entry("global_music.bnk")
    assert entry is not None
    mod_trk = next(
        o for o in entry[0].hirc.objects if isinstance(o, CAkMusicTrack) and o.id == 1300
    )
    assert mod_trk.sources[0].source_id == staged_wid
    assert mod_trk.sources[0].stream_type == 2
    assert mod_trk.sources[0].plugin_id == 0x00010001

    # Verify intermediate marker scaled proportionally (2500ms -> 4000ms for 8000ms song)
    mod_seg = next(
        o for o in entry[0].hirc.objects if isinstance(o, CAkMusicSegment) and o.id == 1200
    )
    assert mod_seg.duration == pytest.approx(8000.0)
    assert mod_seg.markers[0].position == 0.0
    assert mod_seg.markers[1].position == pytest.approx(4000.0)
    assert mod_seg.markers[2].position == pytest.approx(8000.0)

    # Verify Undo/Redo restores exact bytes
    mod_bytes = entry[0].to_bytes()
    assert window.act_undo.isEnabled() is True
    window.act_undo.trigger()
    assert bv_store.session.get_loaded_entry("global_music.bnk")[0].to_bytes() == vanilla_bytes

    assert window.act_redo.isEnabled() is True
    window.act_redo.trigger()
    assert bv_store.session.get_loaded_entry("global_music.bnk")[0].to_bytes() == mod_bytes


# =============================================================================
# Job 2: Replace & Export a Multi-Source Combat Transition Sub-Track
# =============================================================================


def test_job2_replace_and_export_multi_source_sub_track(qtbot, tmp_path: Path, monkeypatch):
    """Job 2: Replace hirc:<track_id>:src:1 on a 3-source CAkMusicTrack and export to WAV."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData2"))

    sources = [
        AkMusicTrackSource(
            plugin_id=0x00040001,
            stream_type=2,
            source_id=20001,
            file_id=20001,
        ),
        AkMusicTrackSource(
            plugin_id=0x00040001,
            stream_type=2,
            source_id=20002,
            file_id=20002,
        ),
        AkMusicTrackSource(
            plugin_id=0x00040001,
            stream_type=2,
            source_id=20003,
            file_id=20003,
        ),
    ]
    playlist = [
        AkTrackSrcInfo(track_id=2000, source_id=20001, src_duration=1000.0),
        AkTrackSrcInfo(track_id=2000, source_id=20002, src_duration=1000.0),
        AkTrackSrcInfo(track_id=2000, source_id=20003, src_duration=1000.0),
    ]
    trk = CAkMusicTrack(id=2000, sources=sources, playlist=playlist)
    seg = CAkMusicSegment(id=2001, child_ids=[2000], duration=1000.0)
    bank = SoundBank(
        header=BkhdChunk(bank_id=902, version=112),
        hirc=HircChunk(objects=[seg, trk]),
    )

    window, project, _ = _setup_e2e_project(tmp_path, "Job2Mod", {"global_music.bnk": bank})
    qtbot.addWidget(window)

    bv_store = window.bank_viewer_store
    bv_view = window.bank_viewer_view
    bv_store.select_bank("global_music.bnk")
    bv_store.select_node("hirc:2000:src:1")

    # Select sub-track source 1 in tree widget
    item_sub1 = bv_view._items_by_key.get("hirc:2000:src:1")
    assert item_sub1 is not None
    bv_view.tree_widget.setCurrentItem(item_sub1)
    item_sub1.setSelected(True)
    bv_view._on_tree_selection_changed()

    assert window.audio_sources_view.lbl_target_summary.text() == "1 target selected"

    # Apply replacement audio to sub-track 1
    sub_wav = make_synthetic_wav(tmp_path / "custom_sub1.wav", duration_s=1.2)
    window.audio_sources_store.select_files([str(sub_wav)])
    qtbot.mouseClick(window.audio_sources_view.btn_apply, Qt.MouseButton.LeftButton)

    # Verify sources[1] updated while sources[0] and sources[2] are untouched
    entry = bv_store.session.get_loaded_entry("global_music.bnk")
    assert entry is not None
    mod_trk = next(
        o for o in entry[0].hirc.objects if isinstance(o, CAkMusicTrack) and o.id == 2000
    )
    assert mod_trk.sources[0].source_id == 20001
    assert mod_trk.sources[0].plugin_id == 0x00040001
    assert mod_trk.sources[2].source_id == 20003
    assert mod_trk.sources[2].plugin_id == 0x00040001

    assert mod_trk.sources[1].source_id == 20002
    assert mod_trk.sources[1].plugin_id == 0x00010001
    assert mod_trk.sources[1].stream_type == 2
    assert (project.audio_dir / "20002.wem").is_file()
    assert not (project.audio_dir / "20001.wem").exists()
    assert not (project.audio_dir / "20003.wem").exists()

    # Export sub-track 1 to WAV and verify valid output
    out_wav = tmp_path / "exported_sub_1.wav"
    exported = bv_store.export_node_to_wav("hirc:2000:src:1", out_wav)
    assert exported == out_wav
    assert out_wav.is_file()
    with wave.open(str(out_wav), "rb") as wf:
        assert wf.getnchannels() in (1, 2)
        assert wf.getframerate() == 32000
        assert wf.getnframes() > 0

    # Compile Movie Pack and verify engine playability
    window._on_build_pack_triggered()
    output_pack = Path(project.manifest.output_pack_path)
    assert output_pack.is_file()
    assert_pack_engine_playable(output_pack)


# =============================================================================
# Job 3: Replace an Embedded Sound in non-trivial *_data.bnk Companion Bank
# =============================================================================


def test_job3_replace_embedded_sound_in_data_companion_bank(qtbot, tmp_path: Path, monkeypatch):
    """Job 3: Replace media:50001 in projectiles_explosion_data.bnk and verify battle_projectiles.bnk companion promotion."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData3"))

    dummy_payload = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    didx_entries = [DidxEntry(file_id=50001, offset=0, size=len(dummy_payload))]
    data_bank = SoundBank(
        header=BkhdChunk(bank_id=501, version=112),
        didx=DidxChunk(entries=didx_entries),
        data=DataChunk(data=dummy_payload),
    )
    sound = CAkSound(
        id=3001,
        source_id=50001,
        file_id=501,
        stream_type=0,
        plugin_id=0x00040001,
    )
    logic_bank = SoundBank(
        header=BkhdChunk(bank_id=502, version=112),
        hirc=HircChunk(objects=[sound]),
    )

    banks = {
        "projectiles_explosion_data.bnk": data_bank,
        "battle_projectiles.bnk": logic_bank,
    }
    window, project, _ = _setup_e2e_project(tmp_path, "Job3Mod", banks)
    qtbot.addWidget(window)

    bv_store = window.bank_viewer_store
    bv_view = window.bank_viewer_view
    bv_store.select_bank("projectiles_explosion_data.bnk")
    bv_store.select_node("media:50001")

    # Select media:50001 in tree widget
    item_media = bv_view._items_by_key.get("media:50001")
    assert item_media is not None
    bv_view.tree_widget.setCurrentItem(item_media)
    item_media.setSelected(True)
    bv_view._on_tree_selection_changed()

    assert window.audio_sources_view.lbl_target_summary.text() == "1 target selected"

    # Apply replacement audio
    new_wav = make_synthetic_wav(tmp_path / "explosion.wav", duration_s=0.5)
    window.audio_sources_store.select_files([str(new_wav)])
    qtbot.mouseClick(window.audio_sources_view.btn_apply, Qt.MouseButton.LeftButton)

    # Verify battle_projectiles.bnk automatically loaded and promoted to stream_type 2 / PCM
    entry_logic = bv_store.session.get_loaded_entry("battle_projectiles.bnk")
    assert entry_logic is not None
    promoted_sound = next(
        o for o in entry_logic[0].hirc.objects if isinstance(o, CAkSound) and o.id == 3001
    )
    assert promoted_sound.stream_type == 2
    assert promoted_sound.plugin_id == 0x00010001

    # Compile Movie Pack and verify engine playability
    window._on_build_pack_triggered()
    output_pack = Path(project.manifest.output_pack_path)
    assert output_pack.is_file()
    assert_pack_engine_playable(output_pack)


# =============================================================================
# Job 4: Cross-Bank Unopened Shared Recording Detection & Isolate vs. Revert
# =============================================================================


def test_job4_cross_bank_unopened_shared_recording_isolate_vs_revert(
    qtbot, tmp_path: Path, monkeypatch
):
    """Job 4: Discover unopened cross-bank WEM references, isolate Sound 101, then revert slot."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData4"))

    sound_a = CAkSound(
        id=101,
        source_id=70001,
        file_id=10,
        stream_type=0,
        plugin_id=0x00040001,
    )
    bank_a = SoundBank(
        header=BkhdChunk(bank_id=10, version=112),
        hirc=HircChunk(objects=[sound_a]),
    )

    sound_b = CAkSound(
        id=201,
        source_id=70001,
        file_id=20,
        stream_type=0,
        plugin_id=0x00040001,
    )
    bank_b = SoundBank(
        header=BkhdChunk(bank_id=20, version=112),
        hirc=HircChunk(objects=[sound_b]),
    )

    banks = {"bank_a.bnk": bank_a, "bank_b.bnk": bank_b}
    window, project, _ = _setup_e2e_project(tmp_path, "Job4Mod", banks)
    qtbot.addWidget(window)

    session = window.bank_viewer_store.session

    # bank_b is unopened; query cross-bank references for WEM 70001
    refs = session.get_cross_bank_wem_references(70001)
    ref_banks = {r.bank_name.lower() for r in refs}
    assert "bank_a.bnk" in ref_banks
    assert "bank_b.bnk" in ref_banks

    # Select bank_a.bnk and sound 101 in UI
    bv_store = window.bank_viewer_store
    bv_view = window.bank_viewer_view
    bv_store.select_bank("bank_a.bnk")
    bv_store.select_node("hirc:101")

    item101 = bv_view._items_by_key.get("hirc:101")
    assert item101 is not None
    bv_view.tree_widget.setCurrentItem(item101)
    item101.setSelected(True)
    bv_view._on_tree_selection_changed()

    # Configure coordinator to choose ISOLATE scope
    window.coordinator.confirm_replacement_scope = lambda target: (
        True,
        ReplacementScope.ISOLATE,
    )

    isolate_wav = make_synthetic_wav(tmp_path / "isolate.wav", duration_s=0.3)
    window.audio_sources_store.select_files([str(isolate_wav)])
    qtbot.mouseClick(window.audio_sources_view.btn_apply, Qt.MouseButton.LeftButton)

    # Verify Sound 101 isolated to a new WEM ID
    entry_a = bv_store.session.get_loaded_entry("bank_a.bnk")
    assert entry_a is not None
    s101_iso = next(o for o in entry_a[0].hirc.objects if isinstance(o, CAkSound) and o.id == 101)
    assert s101_iso.source_id != 70001
    isolated_wid = s101_iso.source_id
    assert isolated_wid in project.manifest.staged_wems
    assert (project.audio_dir / f"{isolated_wid}.wem").is_file()

    # Revert slot hirc:101 to baseline
    reverted = bv_store.revert_node("hirc:101")
    assert reverted is True

    # Verify Sound 101 restored to baseline 70001, stream_type 0, plugin_id 0x00040001
    entry_rev = bv_store.session.get_loaded_entry("bank_a.bnk")
    assert entry_rev is not None
    s101_rev = next(o for o in entry_rev[0].hirc.objects if isinstance(o, CAkSound) and o.id == 101)
    assert s101_rev.source_id == 70001
    assert s101_rev.stream_type == 0
    assert s101_rev.plugin_id == 0x00040001

    # Verify unreferenced isolated WEM was completely deleted
    assert isolated_wid not in project.manifest.staged_wems
    assert not (project.audio_dir / f"{isolated_wid}.wem").is_file()


# =============================================================================
# Job 5: Parent Container Selection & Drag-and-Drop Multi-File Distribution
# =============================================================================


def test_job5_parent_container_drag_and_drop_multi_file_distribution(
    qtbot, tmp_path: Path, monkeypatch
):
    """Job 5: Select CAkRanSeqCntr with 2 variations and distribute 2 dropped audio files across children."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData5"))

    sound1 = CAkSound(
        id=5001,
        source_id=50001,
        file_id=50001,
        stream_type=2,
        plugin_id=0x00040001,
    )
    sound2 = CAkSound(
        id=5002,
        source_id=50002,
        file_id=50002,
        stream_type=2,
        plugin_id=0x00040001,
    )
    cntr = CAkRanSeqCntr(
        id=5000,
        children=[5001, 5002],
        playlist=[
            AkPlaylistItem(play_id=5001, weight=50000),
            AkPlaylistItem(play_id=5002, weight=50000),
        ],
    )
    bank = SoundBank(
        header=BkhdChunk(bank_id=50, version=112),
        hirc=HircChunk(objects=[cntr, sound1, sound2]),
    )

    window, project, _ = _setup_e2e_project(tmp_path, "Job5Mod", {"ambient.bnk": bank})
    qtbot.addWidget(window)

    bv_store = window.bank_viewer_store
    bv_view = window.bank_viewer_view
    bv_store.select_bank("ambient.bnk")
    bv_store.select_node("hirc:5000")

    # Select container 5000 in tree widget
    item5000 = bv_view._items_by_key.get("hirc:5000")
    assert item5000 is not None
    bv_view.tree_widget.setCurrentItem(item5000)
    item5000.setSelected(True)
    bv_view._on_tree_selection_changed()

    # Verify Audio Sources dock targets both descendant sounds
    assert window.audio_sources_view.lbl_target_summary.text() == "2 targets selected"
    assert len(window.audio_sources_store.state.targets) == 2

    # Drop 2 distinct WAV files onto container row
    wav1 = make_synthetic_wav(tmp_path / "drop1.wav", duration_s=0.2)
    wav2 = make_synthetic_wav(tmp_path / "drop2.wav", duration_s=0.3)

    bv_view.tree_widget.source_dropped.emit((str(wav1), str(wav2)), "hirc:5000")

    # Verify both child sounds were updated with different staged WEMs
    entry = bv_store.session.get_loaded_entry("ambient.bnk")
    assert entry is not None
    mod_s1 = next(o for o in entry[0].hirc.objects if isinstance(o, CAkSound) and o.id == 5001)
    mod_s2 = next(o for o in entry[0].hirc.objects if isinstance(o, CAkSound) and o.id == 5002)
    assert mod_s1.source_id == 50001
    assert mod_s2.source_id == 50002
    assert mod_s1.source_id != mod_s2.source_id
    assert (project.audio_dir / f"{mod_s1.source_id}.wem").is_file()
    assert (project.audio_dir / f"{mod_s2.source_id}.wem").is_file()

    # Compile Movie Pack and verify engine playability
    window._on_build_pack_triggered()
    output_pack = Path(project.manifest.output_pack_path)
    assert output_pack.is_file()
    assert_pack_engine_playable(output_pack)


# =============================================================================
# Job 6: Slot-Local Volume/Pitch Tuning & Appending Pool Variation
# =============================================================================


def test_job6_slot_local_tuning_and_appending_pool_variation(qtbot, tmp_path: Path, monkeypatch):
    """Job 6: Volume/pitch tuning and container variation appending with exact Undo/Redo."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData6"))

    sound1 = CAkSound(
        id=6001,
        source_id=60001,
        file_id=60,
        stream_type=2,
        node_base_params=NodeBaseParams(props={0: 0.0, 2: 0.0}),
    )
    cntr = CAkRanSeqCntr(
        id=6000,
        children=[6001],
        playlist=[AkPlaylistItem(play_id=6001, weight=50000)],
        node_base_params=NodeBaseParams(),
    )
    bank = SoundBank(
        header=BkhdChunk(bank_id=60, version=112),
        hirc=HircChunk(objects=[sound1, cntr]),
    )
    vanilla_bytes = bank.to_bytes()

    window, project, _ = _setup_e2e_project(tmp_path, "Job6Mod", {"battle.bnk": bank})
    qtbot.addWidget(window)

    bv_store = window.bank_viewer_store
    bv_store.select_bank("battle.bnk")

    # 1. Update Volume (Prop 0) and Pitch (Prop 2)
    success_tune = bv_store.update_node_params(6001, -6.0, 200.0)
    assert success_tune is True

    entry_tune = bv_store.session.get_loaded_entry("battle.bnk")
    assert entry_tune is not None
    tuned_s = next(
        o for o in entry_tune[0].hirc.objects if isinstance(o, CAkSound) and o.id == 6001
    )
    assert tuned_s.node_base_params.props[0] == -6.0
    assert tuned_s.node_base_params.props[2] == 200.0

    # 2. Append new pool variation to container 6000
    custom_wav = make_synthetic_wav(tmp_path / "pool_new.wav", duration_s=0.25)
    success_var = bv_store.append_container_variation(6000, custom_wav)
    assert success_var is True

    entry_var = bv_store.session.get_loaded_entry("battle.bnk")
    assert entry_var is not None
    mod_cntr = next(
        o for o in entry_var[0].hirc.objects if isinstance(o, CAkRanSeqCntr) and o.id == 6000
    )
    assert len(mod_cntr.children) == 2
    assert len(mod_cntr.playlist) == 2

    new_sid = mod_cntr.children[1]
    new_sound = next(
        o for o in entry_var[0].hirc.objects if isinstance(o, CAkSound) and o.id == new_sid
    )
    assert new_sound.stream_type == 2
    assert (project.audio_dir / f"{new_sound.source_id}.wem").is_file()

    mod_bytes = entry_var[0].to_bytes()

    # 3. Undo both operations and verify byte-exact return to vanilla
    assert window.act_undo.isEnabled() is True
    window.act_undo.trigger()  # Undo append variation
    window.act_undo.trigger()  # Undo params update

    undone_entry = bv_store.session.get_loaded_entry("battle.bnk")
    assert undone_entry is not None
    assert undone_entry[0].to_bytes() == vanilla_bytes

    # 4. Redo both operations and verify byte-exact return to modified state
    assert window.act_redo.isEnabled() is True
    window.act_redo.trigger()  # Redo params update
    window.act_redo.trigger()  # Redo append variation

    redone_entry = bv_store.session.get_loaded_entry("battle.bnk")
    assert redone_entry is not None
    assert redone_entry[0].to_bytes() == mod_bytes

    # 5. Compile Movie Pack and verify engine playability
    window._on_build_pack_triggered()
    output_pack = Path(project.manifest.output_pack_path)
    assert output_pack.is_file()
    assert_pack_engine_playable(output_pack)


# =============================================================================
# Job 7: Event & Switch Container Branch Replacement & Pack Export
# =============================================================================


def test_job7_event_and_switch_cntr_branch_replacement_and_pack_export(
    qtbot, tmp_path: Path, monkeypatch
):
    """Job 7: Replace Sound 7010 under CAkSwitchCntr without altering Sound 7020 or switch structure."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData7"))

    sound_branch1 = CAkSound(
        id=7010,
        source_id=70010,
        file_id=70010,
        stream_type=2,
        plugin_id=0x00010001,
    )
    sound_branch2 = CAkSound(
        id=7020,
        source_id=70020,
        file_id=70020,
        stream_type=2,
        plugin_id=0x00010001,
    )
    sw_cntr = CAkSwitchCntr(
        id=7002,
        group_id=1,
        default_switch=1,
        children=[7010, 7020],
        switch_map={1: [7010], 2: [7020]},
    )
    action = CAkAction.create_play(id=7001, target_id=7002)
    event = CAkEvent(id=7000, actions=[7001])
    bank = SoundBank(
        header=BkhdChunk(bank_id=70, version=112),
        hirc=HircChunk(objects=[event, action, sw_cntr, sound_branch1, sound_branch2]),
    )
    vanilla_bytes = bank.to_bytes()

    window, project, cache_dir = _setup_e2e_project(
        tmp_path, "Job7Mod", {"battle_switches.bnk": bank}
    )
    (cache_dir / "70020.wem").write_bytes(
        build_silent_pcm_wem_bytes(duration_ms=100, sample_rate=32000)
    )
    qtbot.addWidget(window)

    bv_store = window.bank_viewer_store
    bv_view = window.bank_viewer_view
    bv_store.select_bank("battle_switches.bnk")
    bv_store.select_node("hirc:7010")

    item7010 = bv_view._items_by_key.get("hirc:7010")
    assert item7010 is not None
    bv_view.tree_widget.setCurrentItem(item7010)
    item7010.setSelected(True)
    bv_view._on_tree_selection_changed()

    new_branch_wav = make_synthetic_wav(tmp_path / "branch1.wav", duration_s=0.4)
    window.audio_sources_store.select_files([str(new_branch_wav)])
    qtbot.mouseClick(window.audio_sources_view.btn_apply, Qt.MouseButton.LeftButton)

    # Verify branch 1 updated, branch 2 untouched
    entry = bv_store.session.get_loaded_entry("battle_switches.bnk")
    assert entry is not None
    mod_s1 = next(o for o in entry[0].hirc.objects if isinstance(o, CAkSound) and o.id == 7010)
    mod_s2 = next(o for o in entry[0].hirc.objects if isinstance(o, CAkSound) and o.id == 7020)
    assert mod_s1.source_id == 70010
    assert mod_s2.source_id == 70020
    assert (project.audio_dir / "70010.wem").is_file()

    window._on_build_pack_triggered()
    output_pack = Path(project.manifest.output_pack_path)
    assert output_pack.is_file()
    assert_pack_engine_playable(output_pack)

    # Verify Undo/Redo
    assert window.act_undo.isEnabled() is True
    window.act_undo.trigger()
    assert bv_store.session.get_loaded_entry("battle_switches.bnk")[0].to_bytes() == vanilla_bytes
    assert not (project.audio_dir / "70010.wem").is_file()


# =============================================================================
# Job 8: Self-Contained Bank Media Node Replacement & Pack Export
# =============================================================================


def test_job8_self_contained_bank_media_node_replacement_and_pack_export(
    qtbot, tmp_path: Path, monkeypatch
):
    """Job 8: Replace media:80001 in a self-contained bank with embedded DATA chunk and promote CAkSound."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData8"))

    dummy_payload = build_silent_pcm_wem_bytes(duration_ms=60, sample_rate=32000)
    didx_entries = [DidxEntry(file_id=80001, offset=0, size=len(dummy_payload))]
    sound = CAkSound(
        id=8001,
        source_id=80001,
        file_id=80,
        stream_type=0,
        plugin_id=0x00040001,
    )
    bank = SoundBank(
        header=BkhdChunk(bank_id=80, version=112),
        didx=DidxChunk(entries=didx_entries),
        data=DataChunk(data=dummy_payload),
        hirc=HircChunk(objects=[sound]),
    )
    vanilla_bytes = bank.to_bytes()

    window, project, _ = _setup_e2e_project(tmp_path, "Job8Mod", {"surface_fx.bnk": bank})
    qtbot.addWidget(window)

    bv_store = window.bank_viewer_store
    bv_view = window.bank_viewer_view
    bv_store.select_bank("surface_fx.bnk")
    bv_store.select_node("media:80001")

    item_m80001 = bv_view._items_by_key.get("media:80001")
    assert item_m80001 is not None
    bv_view.tree_widget.setCurrentItem(item_m80001)
    item_m80001.setSelected(True)
    bv_view._on_tree_selection_changed()

    new_hit_wav = make_synthetic_wav(tmp_path / "custom_hit.wav", duration_s=0.3)
    window.audio_sources_store.select_files([str(new_hit_wav)])
    qtbot.mouseClick(window.audio_sources_view.btn_apply, Qt.MouseButton.LeftButton)

    # Verify same-bank sound 8001 was promoted to stream_type 2
    entry = bv_store.session.get_loaded_entry("surface_fx.bnk")
    assert entry is not None
    promoted_s = next(o for o in entry[0].hirc.objects if isinstance(o, CAkSound) and o.id == 8001)
    assert promoted_s.stream_type == 2
    assert promoted_s.plugin_id == 0x00010001
    assert "surface_fx.bnk" in project.manifest.modified_banks
    assert (project.audio_dir / "80001.wem").is_file()

    window._on_build_pack_triggered()
    output_pack = Path(project.manifest.output_pack_path)
    assert output_pack.is_file()
    assert_pack_engine_playable(output_pack)

    # Undo restores stream_type 0
    assert window.act_undo.isEnabled() is True
    window.act_undo.trigger()
    assert bv_store.session.get_loaded_entry("surface_fx.bnk")[0].to_bytes() == vanilla_bytes
    assert not (project.audio_dir / "80001.wem").is_file()


# =============================================================================
# Job 9: Cross-Bank Shared Overwrite Promotes Unopened Sibling Bank
# =============================================================================


def test_job9_cross_bank_shared_overwrite_promotes_unopened_sibling_bank(
    qtbot, tmp_path: Path, monkeypatch
):
    """Job 9: Overwrite shared WEM 90001 in bank_a.bnk, promoting unopened bank_b.bnk to stream_type 2."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData9"))

    sound_a = CAkSound(
        id=101,
        source_id=90001,
        file_id=90001,
        stream_type=0,
        plugin_id=0x00040001,
    )
    bank_a = SoundBank(
        header=BkhdChunk(bank_id=10, version=112),
        hirc=HircChunk(objects=[sound_a]),
    )

    sound_b = CAkSound(
        id=201,
        source_id=90001,
        file_id=90001,
        stream_type=0,
        plugin_id=0x00040001,
    )
    bank_b = SoundBank(
        header=BkhdChunk(bank_id=20, version=112),
        hirc=HircChunk(objects=[sound_b]),
    )

    banks = {"bank_a.bnk": bank_a, "bank_b.bnk": bank_b}
    window, project, _ = _setup_e2e_project(tmp_path, "Job9Mod", banks)
    qtbot.addWidget(window)

    bv_store = window.bank_viewer_store
    bv_view = window.bank_viewer_view
    bv_store.select_bank("bank_a.bnk")
    bv_store.select_node("hirc:101")

    item101 = bv_view._items_by_key.get("hirc:101")
    assert item101 is not None
    bv_view.tree_widget.setCurrentItem(item101)
    item101.setSelected(True)
    bv_view._on_tree_selection_changed()

    window.coordinator.confirm_replacement_scope = lambda target: (
        True,
        ReplacementScope.OVERWRITE,
    )

    shared_wav = make_synthetic_wav(tmp_path / "shared_hit.wav", duration_s=0.25)
    window.audio_sources_store.select_files([str(shared_wav)])
    qtbot.mouseClick(window.audio_sources_view.btn_apply, Qt.MouseButton.LeftButton)

    # Verify both bank_a and unopened bank_b were promoted and saved
    entry_a = bv_store.session.get_loaded_entry("bank_a.bnk")
    entry_b = bv_store.session.get_loaded_entry("bank_b.bnk")
    assert entry_a is not None
    assert entry_b is not None

    s101 = next(o for o in entry_a[0].hirc.objects if isinstance(o, CAkSound) and o.id == 101)
    s201 = next(o for o in entry_b[0].hirc.objects if isinstance(o, CAkSound) and o.id == 201)
    assert s101.stream_type == 2
    assert s201.stream_type == 2
    assert s101.plugin_id == 0x00010001
    assert s201.plugin_id == 0x00010001
    assert "bank_a.bnk" in project.manifest.modified_banks
    assert "bank_b.bnk" in project.manifest.modified_banks
    assert (project.audio_dir / "90001.wem").is_file()

    window._on_build_pack_triggered()
    output_pack = Path(project.manifest.output_pack_path)
    assert output_pack.is_file()
    assert_pack_engine_playable(output_pack)

    # Undo cleans up both
    assert window.act_undo.isEnabled() is True
    window.act_undo.trigger()
    assert bv_store.session.get_loaded_entry("bank_a.bnk")[0].to_bytes() == bank_a.to_bytes()
    assert bv_store.session.get_loaded_entry("bank_b.bnk")[0].to_bytes() == bank_b.to_bytes()


# =============================================================================
# Job 10: Game Audio Catalog Replacement & Pack Export
# =============================================================================


def test_job10_game_audio_catalog_replacement_and_pack_export(qtbot, tmp_path: Path, monkeypatch):
    """Job 10: Replace CAkSound with Vorbis WEM 44001 from Game Audio Catalog preserving codec parity."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData10"))

    # Vorbis WEM 44001 in ambient.bnk DATA chunk (format_tag 0xFFFF)
    vorbis_header = b"RIFF\x28\x00\x00\x00WAVEfmt \x10\x00\x00\x00\xff\xff\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x00\x00data\x04\x00\x00\x00TEST"
    didx = [DidxEntry(file_id=44001, offset=0, size=len(vorbis_header))]
    ambient_bank = SoundBank(
        header=BkhdChunk(bank_id=40, version=112),
        didx=DidxChunk(entries=didx),
        data=DataChunk(data=vorbis_header),
    )

    sound_target = CAkSound(
        id=9901,
        source_id=11001,
        file_id=90,
        stream_type=0,
        plugin_id=0x00010001,
    )
    battle_vo_bank = SoundBank(
        header=BkhdChunk(bank_id=90, version=112),
        hirc=HircChunk(objects=[sound_target]),
    )

    banks = {"ambient.bnk": ambient_bank, "battle_vo.bnk": battle_vo_bank}
    window, project, _ = _setup_e2e_project(tmp_path, "Job10Mod", banks)
    qtbot.addWidget(window)

    bv_store = window.bank_viewer_store
    bv_view = window.bank_viewer_view
    bv_store.select_bank("battle_vo.bnk")
    bv_store.select_node("hirc:9901")

    item9901 = bv_view._items_by_key.get("hirc:9901")
    assert item9901 is not None
    bv_view.tree_widget.setCurrentItem(item9901)
    item9901.setSelected(True)
    bv_view._on_tree_selection_changed()

    # Switch to Game Audio tab and apply catalog entry
    as_store = window.audio_sources_store
    as_store.set_active_tab(AudioSourcesTab.GAME_AUDIO)
    catalog_entry = AudioCatalogEntry(
        wem_id=44001,
        source_bank="ambient.bnk",
        display_name="Ambience_Forest_Day",
        event_name="Play_Ambience_Forest",
        is_embedded=True,
        metadata_tags=("ambient", "forest"),
    )
    as_store.select_game_audio_entry(catalog_entry)
    as_store.apply()

    # Verify WEM 44001 was staged and sound 9901 promoted to Vorbis plugin_id 0x00040001
    entry = bv_store.session.get_loaded_entry("battle_vo.bnk")
    assert entry is not None
    mod_s = next(o for o in entry[0].hirc.objects if isinstance(o, CAkSound) and o.id == 9901)
    assert mod_s.source_id == 44001
    assert mod_s.stream_type == 2
    assert mod_s.plugin_id == 0x00040001
    assert (project.audio_dir / "44001.wem").is_file()

    window._on_build_pack_triggered()
    output_pack = Path(project.manifest.output_pack_path)
    assert output_pack.is_file()
    assert_pack_engine_playable(output_pack)


# =============================================================================
# Job 11: Mute Workflow & Pre-Flight Export Guard
# =============================================================================


def test_job11_mute_workflow_and_preflight_export_guard(qtbot, tmp_path: Path, monkeypatch):
    """Job 11: Mute CAkSound with 1.wem, verify undo cleanup, and assert pre-flight guard blocks corrupt export."""
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData11"))

    sound = CAkSound(
        id=1101,
        source_id=55001,
        file_id=11,
        stream_type=2,
        plugin_id=0x00010001,
    )
    bank = SoundBank(
        header=BkhdChunk(bank_id=11, version=112),
        hirc=HircChunk(objects=[sound]),
    )

    window, project, cache_dir = _setup_e2e_project(tmp_path, "Job11Mod", {"battle_mute.bnk": bank})
    (cache_dir / "55001.wem").write_bytes(
        build_silent_pcm_wem_bytes(duration_ms=100, sample_rate=32000)
    )
    qtbot.addWidget(window)

    bv_store = window.bank_viewer_store
    bv_view = window.bank_viewer_view
    bv_store.select_bank("battle_mute.bnk")
    bv_store.select_node("hirc:1101")

    item1101 = bv_view._items_by_key.get("hirc:1101")
    assert item1101 is not None
    bv_view.tree_widget.setCurrentItem(item1101)
    item1101.setSelected(True)
    bv_view._on_tree_selection_changed()

    # Mute node via Silence button
    window.audio_sources_store.apply_silence()

    # Verify 1.wem staged and sound retargeted
    entry = bv_store.session.get_loaded_entry("battle_mute.bnk")
    assert entry is not None
    muted_s = next(o for o in entry[0].hirc.objects if isinstance(o, CAkSound) and o.id == 1101)
    assert muted_s.source_id == 1
    assert muted_s.stream_type == 2
    assert muted_s.plugin_id == 0x00010001
    assert 1 in project.manifest.staged_wems
    assert (project.audio_dir / "1.wem").is_file()

    window._on_build_pack_triggered()
    output_pack = Path(project.manifest.output_pack_path)
    assert output_pack.is_file()
    assert_pack_engine_playable(output_pack)

    # Undo cleans up 1.wem completely
    assert window.act_undo.isEnabled() is True
    window.act_undo.trigger()
    assert 1 not in project.manifest.staged_wems
    assert not (project.audio_dir / "1.wem").is_file()

    # Test Pre-Flight Export Guard blocking invalid exports
    # Inject an invalid non-audio file into pack_root/audio/
    (project.audio_dir / "stray_cheat.txt").write_text("ILLEGAL")
    with pytest.raises(PackPreflightError) as exc_info:
        project.compile_mod_pack(validate=True)
    assert "Invalid File in Audio Pack" in str(exc_info.value)
    (project.audio_dir / "stray_cheat.txt").unlink()
