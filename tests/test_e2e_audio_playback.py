"""
End-to-End Integration Tests for UI Clicking, Selection, Cross-Bank Media Resolution, and Audio Playback.

Verifies the complete vertical pipeline:
MainWindow -> BankList Selection -> Hierarchy Tree Selection ->
Cross-Bank Media Extraction (Structure Banks vs Companion Data Banks) ->
Audio Transport State -> UI Bar Updates (Labels, Buttons, Sliders).
"""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk, DataChunk, DidxChunk, DidxEntry
from src.bnk.database import SoundDatabase, fnv1_32
from src.bnk.models import AkMusicTrackSource, CAkAction, CAkEvent, CAkMusicTrack, CAkSound
from src.bnk.wem import build_silent_pcm_wem_bytes
from src.engine.graph import BankGraphIndex
from src.ui.features.audio_transport.structs import PlaybackStatus
from src.ui.features.bank_viewer.audio_resolver import resolve_node_audio_track
from src.ui.shell.store import ShellStore
from src.ui.shell.view import MainWindow
from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.storage import ProjectStorage


def _create_e2e_game_cache(cache_dir: Path) -> GameCache:
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 1. battle_environment.bnk (structure bank)
    env_sound1 = CAkSound(
        id=354158907,
        source_id=348341853,
        file_id=fnv1_32("environment_data"),
        stream_type=0,
    )
    env_sound2 = CAkSound(
        id=185784154,
        source_id=209171097,
        file_id=fnv1_32("environment_data"),
        stream_type=0,
    )
    battle_env_bank = SoundBank(
        header=BkhdChunk(version=112, bank_id=fnv1_32("battle_environment")),
        hirc=HircChunk(objects=[env_sound1, env_sound2]),
    )
    (cache_dir / "battle_environment.bnk").write_bytes(battle_env_bank.to_bytes())

    # 2. environment_data.bnk (companion data bank)
    env_data_bank = SoundBank(
        header=BkhdChunk(version=112, bank_id=fnv1_32("environment_data")),
        didx=DidxChunk(),
        data=DataChunk(),
    )
    for fid in (348341853, 209171097):
        wem = build_silent_pcm_wem_bytes(duration_ms=5000, sample_rate=32000)
        offset, size = env_data_bank.data.align_and_append(wem)
        env_data_bank.didx.entries.append(DidxEntry(file_id=fid, offset=offset, size=size))
    (cache_dir / "environment_data.bnk").write_bytes(env_data_bank.to_bytes())

    # 3. animation_footstep_foley_data.bnk
    foley_bank = SoundBank(
        header=BkhdChunk(version=112, bank_id=fnv1_32("animation_footstep_foley_data")),
        didx=DidxChunk(),
        data=DataChunk(),
    )
    foley_wem = build_silent_pcm_wem_bytes(duration_ms=2000, sample_rate=32000)
    offset, size = foley_bank.data.align_and_append(foley_wem)
    foley_bank.didx.entries.append(DidxEntry(file_id=1524473, offset=offset, size=size))
    (cache_dir / "animation_footstep_foley_data.bnk").write_bytes(foley_bank.to_bytes())

    # 4. event_data.dat
    (cache_dir / "event_data.dat").write_bytes(SoundDatabase().to_bytes())

    return GameCache(GameType.ATTILA, cache_dir=cache_dir)


def test_audio_resolver_hirc_sound_and_music_tracks(tmp_path: Path):
    """Hermetic unit tests verifying audio resolver on all HIRC audio node permutations."""
    # 1. Streamed Sound
    snd_streamed = CAkSound(id=101, source_id=9001, stream_type=2)
    bank_streamed = SoundBank(
        header=BkhdChunk(version=112, bank_id=10),
        hirc=HircChunk(objects=[snd_streamed]),
    )
    graph_streamed = BankGraphIndex.build(bank_streamed)

    # Without resolver, cannot find file
    assert resolve_node_audio_track(bank_streamed, "hirc:101", graph_index=graph_streamed) is None

    # 2. Embedded Sound in current bank
    snd_embedded = CAkSound(id=102, source_id=9002, stream_type=0)
    bank_embedded = SoundBank(
        header=BkhdChunk(version=112, bank_id=11),
        didx=DidxChunk(entries=[DidxEntry(file_id=9002, offset=0, size=12)]),
        data=DataChunk(data=b"EMBEDDED_WEM"),
        hirc=HircChunk(objects=[snd_embedded]),
    )
    graph_embedded = BankGraphIndex.build(bank_embedded)
    track_embedded = resolve_node_audio_track(bank_embedded, "hirc:102", graph_index=graph_embedded)
    assert track_embedded is not None
    assert track_embedded.source_id == 9002
    assert track_embedded.embedded_bytes == b"EMBEDDED_WEM"

    # 3. Non-audio nodes must cleanly resolve to None
    ev = CAkEvent(id=200, actions=[201])
    act = CAkAction.create_play(id=201, target_id=102)
    bank_nodes = SoundBank(
        header=BkhdChunk(version=112, bank_id=12),
        hirc=HircChunk(objects=[ev, act]),
    )
    graph_nodes = BankGraphIndex.build(bank_nodes)
    assert resolve_node_audio_track(bank_nodes, "hirc:200", graph_index=graph_nodes) is None
    assert resolve_node_audio_track(bank_nodes, "hirc:201", graph_index=graph_nodes) is None
    assert resolve_node_audio_track(bank_nodes, "chunk:BKHD", graph_index=graph_nodes) is None
    assert resolve_node_audio_track(bank_nodes, "group:chunks", graph_index=graph_nodes) is None

    # 4. Music Track
    m_src = AkMusicTrackSource(source_id=9003)
    mtrk = CAkMusicTrack(id=300, sources=[m_src])
    bank_music = SoundBank(
        header=BkhdChunk(version=112, bank_id=13),
        didx=DidxChunk(entries=[DidxEntry(file_id=9003, offset=0, size=11)]),
        data=DataChunk(data=b"MUSIC_BYTES"),
        hirc=HircChunk(objects=[mtrk]),
    )
    graph_music = BankGraphIndex.build(bank_music)
    track_music = resolve_node_audio_track(bank_music, "hirc:300", graph_index=graph_music)
    assert track_music is not None
    assert track_music.source_id == 9003
    assert track_music.embedded_bytes == b"MUSIC_BYTES"


def test_e2e_audio_playback_structure_bank_companion_media(qapp, qtbot, tmp_path: Path):
    """
    Full End-to-End Test:
    Simulates user clicking 'battle_environment.bnk' in bank table,
    then selecting HIRC node 'Sound (WEM 348341853)' (id=354158907).
    Asserts cross-bank resolution from 'environment_data.bnk',
    automatic audio playback, transport status, and UI widget updates.
    """
    cache = _create_e2e_game_cache(tmp_path / "cache" / "audio")

    proj_dir = tmp_path / "E2EAudioTestMod"
    proj = ProjectStorage.create_project(proj_dir, name="E2EAudioTestMod", game=GameType.ATTILA)
    proj.cache = cache

    shell_store = ShellStore()
    window = MainWindow(shell_store)
    qtbot.addWidget(window)

    # 1. Open Project
    shell_store.open_project(proj)
    assert window.stacked_widget.currentIndex() == 1

    # 2. Select battle_environment.bnk
    window.bank_viewer_store.select_bank("battle_environment.bnk")
    assert window.bank_viewer_store.state.selected_bank_name == "battle_environment.bnk"
    assert "battle_environment.bnk" in window.bank_viewer_view.lbl_tree_bank_name.text()

    # 3. Select Sound (WEM 348341853) HIRC node (id=354158907)
    target_node_key = "hirc:354158907"
    window.bank_viewer_store.select_node(target_node_key)

    # 4. Verify Node Selection & Property Inspector Population
    assert window.bank_viewer_store.state.selected_node_key == target_node_key
    details = window.bank_viewer_store.state.details_by_key.get(target_node_key)
    assert details is not None
    assert details.object_id == 354158907
    assert details.object_type == "Sound"

    # 5. Verify Cross-Bank Audio Resolution into Transport State
    active_track = window.transport_store.state.active_track
    assert active_track is not None
    assert active_track.source_id == 348341853
    assert active_track.embedded_bytes is not None
    assert len(active_track.embedded_bytes) > 0
    assert active_track.embedded_bytes[:4] == b"RIFF"

    # 6. Verify Auto Play triggered playback
    assert window.transport_store.state.status == PlaybackStatus.PLAYING
    assert window.transport_bar.lbl_track.text() == "354158907 (348341853.wem)"
    assert window.transport_bar.lbl_time.text() == "00:00 / 00:05"
    assert window.transport_bar.btn_stop.isEnabled()
    assert window.transport_bar.btn_play.isEnabled()

    # 7. Test UI Transport Controls: Stop Button Click
    qtbot.mouseClick(window.transport_bar.btn_stop, Qt.MouseButton.LeftButton)
    assert window.transport_store.state.status == PlaybackStatus.READY
    assert not window.transport_bar.btn_stop.isEnabled()
    assert window.transport_bar.btn_play.isEnabled()

    # 8. Test UI Transport Controls: Play Button Click
    qtbot.mouseClick(window.transport_bar.btn_play, Qt.MouseButton.LeftButton)
    assert window.transport_store.state.status == PlaybackStatus.PLAYING
    assert window.transport_bar.btn_stop.isEnabled()

    # Stop audio before cleanup
    window.transport_store.stop()


def test_e2e_audio_playback_embedded_bank_direct_media(qapp, qtbot, tmp_path: Path):
    """
    Full End-to-End Test for direct in-bank DIDX embedded media:
    Selects 'animation_footstep_foley_data.bnk',
    selects DIDX embedded media 'media:1524473',
    asserts playback and transport bar synchronization.
    """
    cache = _create_e2e_game_cache(tmp_path / "cache" / "audio")

    proj_dir = tmp_path / "E2EFootstepMod"
    proj = ProjectStorage.create_project(proj_dir, name="E2EFootstepMod", game=GameType.ATTILA)
    proj.cache = cache

    shell_store = ShellStore()
    window = MainWindow(shell_store)
    qtbot.addWidget(window)

    shell_store.open_project(proj)
    window.bank_viewer_store.select_bank("animation_footstep_foley_data.bnk")

    # Select embedded WEM in DIDX table
    window.bank_viewer_store.select_node("media:1524473")

    active_track = window.transport_store.state.active_track
    assert active_track is not None
    assert active_track.source_id == 1524473
    assert active_track.embedded_bytes is not None
    assert window.transport_store.state.status == PlaybackStatus.PLAYING
    assert "1524473" in window.transport_bar.lbl_track.text()

    window.transport_store.stop()


def test_e2e_audio_playback_track_switch_halts_previous_and_autoplay_toggle(
    qapp, qtbot, tmp_path: Path
):
    """
    End-to-End integration test proving:
    1. Selecting a track while another is playing halts the previous track (only 1 mixer channel busy).
    2. Selecting a track with auto_play=True, toggling auto_play to False, and selecting another track
       halts previous playback completely (0 busy channels, READY state).
    """
    import pygame

    cache = _create_e2e_game_cache(tmp_path / "cache" / "audio")

    proj_dir = tmp_path / "E2ETrackSwitchMod"
    proj = ProjectStorage.create_project(proj_dir, name="E2ETrackSwitchMod", game=GameType.ATTILA)
    proj.cache = cache

    shell_store = ShellStore()
    window = MainWindow(shell_store)
    qtbot.addWidget(window)

    shell_store.open_project(proj)
    window.bank_viewer_store.select_bank("battle_environment.bnk")

    # 1. Select first track with auto_play=True -> starts playing
    assert window.transport_store.state.auto_play is True
    window.bank_viewer_store.select_node("hirc:354158907")
    assert window.transport_store.state.status == PlaybackStatus.PLAYING
    assert window.transport_store.state.active_track.source_id == 348341853

    busy_channels = sum(
        1 for i in range(pygame.mixer.get_num_channels()) if pygame.mixer.Channel(i).get_busy()
    )
    assert busy_channels == 1

    # 2. Select second track while first is playing -> halts previous track, only 1 channel busy
    window.bank_viewer_store.select_node("hirc:185784154")
    assert window.transport_store.state.status == PlaybackStatus.PLAYING
    assert window.transport_store.state.active_track.source_id == 209171097

    busy_channels = sum(
        1 for i in range(pygame.mixer.get_num_channels()) if pygame.mixer.Channel(i).get_busy()
    )
    assert busy_channels == 1

    # 3. Toggle auto_play to False via UI click while track is still playing
    window.transport_bar.chk_autoplay.click()
    assert window.transport_store.state.auto_play is False
    assert not window.transport_bar.chk_autoplay.isChecked()
    assert window.transport_store.state.status == PlaybackStatus.PLAYING

    # 4. Select another track -> halts previous playback completely (0 busy channels, READY state)
    window.bank_viewer_store.select_node("hirc:354158907")
    assert window.transport_store.state.status == PlaybackStatus.READY
    assert window.transport_store.state.active_track.source_id == 348341853
    assert window.transport_store.state.position_ms == 0
    assert pygame.mixer.get_busy() is False

    busy_channels = sum(
        1 for i in range(pygame.mixer.get_num_channels()) if pygame.mixer.Channel(i).get_busy()
    )
    assert busy_channels == 0
    assert not window.transport_bar.btn_stop.isEnabled()
    assert window.transport_bar.btn_play.isEnabled()

    window.transport_store.stop()
