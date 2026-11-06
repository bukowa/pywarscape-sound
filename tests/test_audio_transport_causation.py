"""
Behavioral Transition Matrix Proof for Audio Transport.

Part of Phase 2 (/table-prove) in the Spec-Driven Functional Pipeline.
Proves pure mathematical correctness of reconcile_transport.
ZERO Mocks, ZERO Monkeypatching, High-Signal Equivalence Classes.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.ui.features.audio_transport.causation import reconcile_transport
from src.ui.features.audio_transport.structs import (
    AudioSourceId,
    AudioTrack,
    AutoPlayToggled,
    LoadAndPlayAudioIntent,
    LoopToggled,
    Millisecond,
    PauseAudioIntent,
    PauseRequested,
    PlaybackFailed,
    PlaybackFinished,
    PlaybackProgressUpdated,
    PlaybackStatus,
    PlayRequested,
    ResumeAudioIntent,
    SeekAudioIntent,
    SeekRequested,
    SetVolumeIntent,
    StopAudioIntent,
    StopRequested,
    TrackSelected,
    TransportEffectIntent,
    TransportEvent,
    TransportState,
    VolumeChanged,
    VolumeRatio,
)

TRACK_1 = AudioTrack(
    source_id=AudioSourceId(1001),
    title="sword_hit_01.wem",
    file_path="audio/sword_hit_01.wem",
    duration_ms=Millisecond(2500),
)

TRACK_2 = AudioTrack(
    source_id=AudioSourceId(1002),
    title="shield_block_01.wem",
    embedded_bytes=b"RIFF...",
    duration_ms=Millisecond(1200),
)


@dataclass(frozen=True, slots=True, kw_only=True)
class TransitionCase:
    """Canonical test case representing a single state-machine transition."""

    id: str
    state: TransportState
    event: TransportEvent
    expected_state: TransportState
    expected_effects: tuple[TransportEffectIntent, ...]


CASES: tuple[TransitionCase, ...] = (
    # -----------------------------------------------------------------------
    # 1. Track Selection Equivalence Class
    # -----------------------------------------------------------------------
    TransitionCase(
        id="select_track_with_autoplay_on_starts_playing",
        state=TransportState(
            status=PlaybackStatus.IDLE,
            active_track=None,
            auto_play=True,
            loop=False,
        ),
        event=TrackSelected(track=TRACK_1),
        expected_state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(0),
            auto_play=True,
            loop=False,
            error_message=None,
        ),
        expected_effects=(
            LoadAndPlayAudioIntent(
                track=TRACK_1,
                loop=False,
                start_position_ms=Millisecond(0),
            ),
        ),
    ),
    TransitionCase(
        id="select_track_with_autoplay_off_enters_ready_state",
        state=TransportState(
            status=PlaybackStatus.IDLE,
            active_track=None,
            auto_play=False,
            loop=False,
        ),
        event=TrackSelected(track=TRACK_1),
        expected_state=TransportState(
            status=PlaybackStatus.READY,
            active_track=TRACK_1,
            position_ms=Millisecond(0),
            auto_play=False,
            loop=False,
            error_message=None,
        ),
        expected_effects=(StopAudioIntent(),),
    ),
    TransitionCase(
        id="select_container_with_no_audio_clears_track_to_idle",
        state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(1000),
            auto_play=True,
        ),
        event=TrackSelected(track=None),
        expected_state=TransportState(
            status=PlaybackStatus.IDLE,
            active_track=None,
            position_ms=Millisecond(0),
            auto_play=True,
            error_message=None,
        ),
        expected_effects=(StopAudioIntent(),),
    ),
    # -----------------------------------------------------------------------
    # 2. Play / Pause / Resume Equivalence Class
    # -----------------------------------------------------------------------
    TransitionCase(
        id="play_requested_from_ready_starts_playback",
        state=TransportState(
            status=PlaybackStatus.READY,
            active_track=TRACK_1,
            position_ms=Millisecond(0),
            loop=True,
        ),
        event=PlayRequested(),
        expected_state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(0),
            loop=True,
            error_message=None,
        ),
        expected_effects=(
            LoadAndPlayAudioIntent(
                track=TRACK_1,
                loop=True,
                start_position_ms=Millisecond(0),
            ),
        ),
    ),
    TransitionCase(
        id="play_requested_from_paused_resumes_playback",
        state=TransportState(
            status=PlaybackStatus.PAUSED,
            active_track=TRACK_1,
            position_ms=Millisecond(500),
        ),
        event=PlayRequested(),
        expected_state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(500),
            error_message=None,
        ),
        expected_effects=(ResumeAudioIntent(),),
    ),
    TransitionCase(
        id="play_requested_when_idle_absorbs_idempotently",
        state=TransportState(
            status=PlaybackStatus.IDLE,
            active_track=None,
        ),
        event=PlayRequested(),
        expected_state=TransportState(
            status=PlaybackStatus.IDLE,
            active_track=None,
        ),
        expected_effects=(),
    ),
    TransitionCase(
        id="play_requested_while_already_playing_absorbs_idempotently",
        state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(300),
        ),
        event=PlayRequested(),
        expected_state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(300),
        ),
        expected_effects=(),
    ),
    TransitionCase(
        id="pause_requested_while_playing_transitions_to_paused",
        state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(750),
        ),
        event=PauseRequested(),
        expected_state=TransportState(
            status=PlaybackStatus.PAUSED,
            active_track=TRACK_1,
            position_ms=Millisecond(750),
        ),
        expected_effects=(PauseAudioIntent(),),
    ),
    TransitionCase(
        id="pause_requested_while_ready_absorbs_idempotently",
        state=TransportState(
            status=PlaybackStatus.READY,
            active_track=TRACK_1,
            position_ms=Millisecond(0),
        ),
        event=PauseRequested(),
        expected_state=TransportState(
            status=PlaybackStatus.READY,
            active_track=TRACK_1,
            position_ms=Millisecond(0),
        ),
        expected_effects=(),
    ),
    # -----------------------------------------------------------------------
    # 3. Stop Equivalence Class
    # -----------------------------------------------------------------------
    TransitionCase(
        id="stop_requested_while_playing_resets_position_to_zero_and_ready",
        state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(1200),
        ),
        event=StopRequested(),
        expected_state=TransportState(
            status=PlaybackStatus.READY,
            active_track=TRACK_1,
            position_ms=Millisecond(0),
            error_message=None,
        ),
        expected_effects=(StopAudioIntent(),),
    ),
    TransitionCase(
        id="stop_requested_while_paused_resets_position_to_zero_and_ready",
        state=TransportState(
            status=PlaybackStatus.PAUSED,
            active_track=TRACK_1,
            position_ms=Millisecond(800),
        ),
        event=StopRequested(),
        expected_state=TransportState(
            status=PlaybackStatus.READY,
            active_track=TRACK_1,
            position_ms=Millisecond(0),
            error_message=None,
        ),
        expected_effects=(StopAudioIntent(),),
    ),
    TransitionCase(
        id="stop_requested_while_idle_absorbs_idempotently",
        state=TransportState(
            status=PlaybackStatus.IDLE,
            active_track=None,
            position_ms=Millisecond(0),
        ),
        event=StopRequested(),
        expected_state=TransportState(
            status=PlaybackStatus.IDLE,
            active_track=None,
            position_ms=Millisecond(0),
        ),
        expected_effects=(),
    ),
    # -----------------------------------------------------------------------
    # 4. Seeking & Boundary Clamping
    # -----------------------------------------------------------------------
    TransitionCase(
        id="seek_within_valid_bounds_updates_position_and_emits_intent",
        state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(200),
        ),
        event=SeekRequested(position_ms=Millisecond(1500)),
        expected_state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(1500),
        ),
        expected_effects=(SeekAudioIntent(position_ms=Millisecond(1500)),),
    ),
    TransitionCase(
        id="seek_exceeding_duration_clamps_to_duration",
        state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,  # duration 2500
            position_ms=Millisecond(200),
        ),
        event=SeekRequested(position_ms=Millisecond(9999)),
        expected_state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(2500),
        ),
        expected_effects=(SeekAudioIntent(position_ms=Millisecond(2500)),),
    ),
    TransitionCase(
        id="seek_negative_clamps_to_zero",
        state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(500),
        ),
        event=SeekRequested(position_ms=Millisecond(-100)),
        expected_state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(0),
        ),
        expected_effects=(SeekAudioIntent(position_ms=Millisecond(0)),),
    ),
    # -----------------------------------------------------------------------
    # 5. Volume Adjustments & Boundary Clamping
    # -----------------------------------------------------------------------
    TransitionCase(
        id="volume_changed_within_bounds_updates_state_and_emits_intent",
        state=TransportState(volume=VolumeRatio(1.0)),
        event=VolumeChanged(volume=VolumeRatio(0.65)),
        expected_state=TransportState(volume=VolumeRatio(0.65)),
        expected_effects=(SetVolumeIntent(volume=VolumeRatio(0.65)),),
    ),
    TransitionCase(
        id="volume_changed_exceeding_max_clamps_to_one",
        state=TransportState(volume=VolumeRatio(0.5)),
        event=VolumeChanged(volume=VolumeRatio(2.5)),
        expected_state=TransportState(volume=VolumeRatio(1.0)),
        expected_effects=(SetVolumeIntent(volume=VolumeRatio(1.0)),),
    ),
    TransitionCase(
        id="volume_changed_negative_clamps_to_zero",
        state=TransportState(volume=VolumeRatio(0.5)),
        event=VolumeChanged(volume=VolumeRatio(-0.5)),
        expected_state=TransportState(volume=VolumeRatio(0.0)),
        expected_effects=(SetVolumeIntent(volume=VolumeRatio(0.0)),),
    ),
    # -----------------------------------------------------------------------
    # 6. Toggles & Progress Updates
    # -----------------------------------------------------------------------
    TransitionCase(
        id="autoplay_toggled_flips_boolean",
        state=TransportState(auto_play=True),
        event=AutoPlayToggled(),
        expected_state=TransportState(auto_play=False),
        expected_effects=(),
    ),
    TransitionCase(
        id="loop_toggled_flips_boolean",
        state=TransportState(loop=False),
        event=LoopToggled(),
        expected_state=TransportState(loop=True),
        expected_effects=(),
    ),
    TransitionCase(
        id="playback_progress_updated_while_playing_updates_position",
        state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(100),
        ),
        event=PlaybackProgressUpdated(position_ms=Millisecond(350)),
        expected_state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(350),
        ),
        expected_effects=(),
    ),
    # -----------------------------------------------------------------------
    # 7. Natural Completion & Failure States
    # -----------------------------------------------------------------------
    TransitionCase(
        id="playback_finished_when_not_looping_resets_to_ready_at_zero",
        state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(2500),
            loop=False,
        ),
        event=PlaybackFinished(),
        expected_state=TransportState(
            status=PlaybackStatus.READY,
            active_track=TRACK_1,
            position_ms=Millisecond(0),
            loop=False,
        ),
        expected_effects=(StopAudioIntent(),),
    ),
    TransitionCase(
        id="playback_finished_when_looping_restarts_position_and_remains_playing",
        state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(2500),
            loop=True,
        ),
        event=PlaybackFinished(),
        expected_state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(0),
            loop=True,
        ),
        expected_effects=(),
    ),
    TransitionCase(
        id="playback_failed_records_error_and_resets_to_ready",
        state=TransportState(
            status=PlaybackStatus.PLAYING,
            active_track=TRACK_1,
            position_ms=Millisecond(500),
        ),
        event=PlaybackFailed(reason="Codec decode error in vgmstream"),
        expected_state=TransportState(
            status=PlaybackStatus.READY,
            active_track=TRACK_1,
            position_ms=Millisecond(0),
            error_message="Codec decode error in vgmstream",
        ),
        expected_effects=(StopAudioIntent(),),
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_reconcile_transport_transitions(case: TransitionCase) -> None:
    """Verifies that reconcile_transport satisfies the specification table."""
    actual_state, actual_effects = reconcile_transport(case.state, case.event)
    assert actual_state == case.expected_state
    assert actual_effects == case.expected_effects
