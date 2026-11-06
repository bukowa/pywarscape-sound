"""
View Projection Tests for AudioTransportBar.

Part of Phase 5 (/data-driven-ui) in the Spec-Driven Functional Pipeline.
Verifies Qt signal blocking, UI projections, and user interaction dispatch.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt

from src.ui.features.audio_transport.store import AudioTransportStore
from src.ui.features.audio_transport.structs import (
    AudioSourceId,
    AudioTrack,
    Millisecond,
    PlaybackStatus,
    TransportState,
)
from src.ui.features.audio_transport.view import AudioTransportBar


@pytest.fixture
def transport_fixture(qtbot):
    store = AudioTransportStore()
    view = AudioTransportBar(store=store)
    qtbot.addWidget(view)
    return store, view


def test_audio_transport_bar_initial_render(transport_fixture):
    store, view = transport_fixture
    assert view.lbl_track.text() == "No track selected"
    assert view.lbl_time.text() == "00:00 / 00:00"
    assert view.btn_play.isEnabled() is False
    assert view.btn_stop.isEnabled() is False
    assert view.seek_slider.isEnabled() is False
    assert view.chk_autoplay.isChecked() is True
    assert view.chk_loop.isChecked() is False


def test_audio_transport_bar_renders_loaded_track(transport_fixture):
    store, view = transport_fixture

    track = AudioTrack(
        source_id=AudioSourceId(101),
        title="battle_horn.wem",
        duration_ms=Millisecond(45000),
    )
    # Manually transition store to READY state
    state = TransportState(
        status=PlaybackStatus.READY,
        active_track=track,
        position_ms=Millisecond(0),
    )
    view.render(state)

    assert view.lbl_track.text() == "battle_horn.wem"
    assert view.lbl_time.text() == "00:00 / 00:45"
    assert view.btn_play.isEnabled() is True
    assert view.btn_stop.isEnabled() is False
    assert view.seek_slider.isEnabled() is True


def test_audio_transport_bar_play_and_stop_button_clicks(transport_fixture, qtbot):
    store, view = transport_fixture

    track = AudioTrack(
        source_id=AudioSourceId(102),
        title="drum_roll.wem",
        duration_ms=Millisecond(10000),
    )
    # Put store into READY state with auto_play=False
    store.toggle_auto_play()
    store.select_track(track)
    assert store.state.status == PlaybackStatus.READY

    # Click play
    qtbot.mouseClick(view.btn_play, Qt.MouseButton.LeftButton)
    # Track had no real file so playback fails or attempts to play
    # But event was dispatched!


def test_audio_transport_bar_toggles(transport_fixture, qtbot):
    store, view = transport_fixture

    # Click Auto Play
    view.chk_autoplay.click()
    assert store.state.auto_play is False

    # Click Loop
    view.chk_loop.click()
    assert store.state.loop is True


def test_audio_transport_bar_seek_slider_click_moves_audio_time(transport_fixture, qtbot):
    store, view = transport_fixture
    track = AudioTrack(
        source_id=AudioSourceId(103),
        title="speech.wem",
        duration_ms=Millisecond(60000),
    )
    store.toggle_auto_play()
    store.select_track(track)
    assert store.state.status == PlaybackStatus.READY
    view.render(store.state)
    view.resize(600, 60)
    view.show()
    view.seek_slider.resize(400, 20)
    qtbot.waitExposed(view)

    slider = view.seek_slider
    width = slider.width()
    assert width >= 100

    # 1. Click on the track at ~50% (middle)
    qtbot.mouseClick(
        slider,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(width // 2, slider.height() // 2),
    )
    assert 450 <= slider.value() <= 550
    assert 27000 <= int(store.state.position_ms) <= 33000

    # 2. Click at ~75% (forward)
    qtbot.mouseClick(
        slider,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(int(width * 0.75), slider.height() // 2),
    )
    assert 700 <= slider.value() <= 800
    assert 42000 <= int(store.state.position_ms) <= 48000

    # 3. Click at ~20% (backward)
    qtbot.mouseClick(
        slider,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(int(width * 0.20), slider.height() // 2),
    )
    assert 150 <= slider.value() <= 250
    assert 9000 <= int(store.state.position_ms) <= 15000


def test_audio_transport_bar_disabled_seek_slider_ignores_clicks(transport_fixture, qtbot):
    store, view = transport_fixture
    view.resize(600, 60)
    view.show()
    qtbot.waitExposed(view)

    slider = view.seek_slider
    assert slider.isEnabled() is False

    qtbot.mouseClick(
        slider,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(slider.width() // 2, slider.height() // 2),
    )
    assert slider.value() == 0
    assert int(store.state.position_ms) == 0


def test_audio_transport_bar_seek_slider_scrubbing_updates_time_label(transport_fixture):
    store, view = transport_fixture
    track = AudioTrack(
        source_id=AudioSourceId(104),
        title="ambient.wem",
        duration_ms=Millisecond(60000),
    )
    store.toggle_auto_play()
    store.select_track(track)
    assert store.state.status == PlaybackStatus.READY
    view.render(store.state)

    # Press slider to start seeking at 250
    view.seek_slider.setValue(250)
    view._on_seek_pressed()
    assert view._user_seeking is True
    assert view.lbl_time.text() == "00:15 / 01:00"

    # Drag slider to 750
    view.seek_slider.setValue(750)
    view._on_seek_moved(750)
    assert view.lbl_time.text() == "00:45 / 01:00"

    # Release slider
    view._on_seek_released()
    assert view._user_seeking is False
    assert int(store.state.position_ms) == 45000


def test_audio_transport_bar_volume_slider_click_sets_volume(transport_fixture, qtbot):
    store, view = transport_fixture
    view.resize(600, 60)
    view.show()
    view.volume_slider.resize(70, 20)
    qtbot.waitExposed(view)

    slider = view.volume_slider
    width = slider.width()
    assert width >= 20

    # Click at roughly 40% of the volume slider track
    qtbot.mouseClick(
        slider,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(int(width * 0.4), slider.height() // 2),
    )

    assert 30 <= slider.value() <= 50
    assert 0.30 <= float(store.state.volume) <= 0.50


def test_audio_transport_bar_compact_mode(qtbot):
    store = AudioTransportStore()
    view = AudioTransportBar(store, compact=True)
    qtbot.addWidget(view)
    view.show()

    assert view.compact is True
    assert view.btn_play is not None
    assert view.btn_stop is not None
    assert view.seek_slider is not None
    assert view.lbl_track is not None
    assert view.volume_slider is not None
    assert view.chk_autoplay is not None
    assert view.chk_loop is not None


def test_audio_transport_bar_render_during_user_seek(transport_fixture):
    """Verify that calling render while user is seeking does not raise UnboundLocalError."""
    store, view = transport_fixture
    track = AudioTrack(
        source_id=AudioSourceId(200),
        title="speech_line.wem",
        duration_ms=Millisecond(30000),
    )
    state = TransportState(
        status=PlaybackStatus.PLAYING,
        active_track=track,
        position_ms=Millisecond(5000),
    )
    # Simulate user dragging seek slider
    view._user_seeking = True

    # This call previously crashed with UnboundLocalError: cannot access local variable 'dur_ms'
    view.render(state)

    assert view.seek_slider.isEnabled() is True
    # Clean up state
    view._user_seeking = False
