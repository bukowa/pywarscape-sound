"""
Pure Functional Core for Audio Transport & Auditioning.

Part of Phase 3 (/causation) in the Spec-Driven Functional Pipeline.
Contains pure deterministic decision logic and state transitions.
ZERO Qt imports, ZERO I/O, ZERO mutable state, ZERO side effects.
"""

from __future__ import annotations

import dataclasses

from src.ui.features.audio_transport.structs import (
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


def reconcile_transport(
    state: TransportState,
    event: TransportEvent,
) -> tuple[TransportState, tuple[TransportEffectIntent, ...]]:
    """
    Pure state evolution function mapping (state, event) -> (new_state, intents).
    Implements the transition matrix with zero side effects.
    """
    match event:
        case TrackSelected(track=track):
            if track is None:
                new_state = dataclasses.replace(
                    state,
                    status=PlaybackStatus.IDLE,
                    active_track=None,
                    position_ms=Millisecond(0),
                    error_message=None,
                )
                return new_state, (StopAudioIntent(),)

            if state.auto_play:
                new_state = dataclasses.replace(
                    state,
                    status=PlaybackStatus.PLAYING,
                    active_track=track,
                    position_ms=Millisecond(0),
                    error_message=None,
                )
                return new_state, (
                    LoadAndPlayAudioIntent(
                        track=track,
                        loop=state.loop,
                        start_position_ms=Millisecond(0),
                    ),
                )
            else:
                new_state = dataclasses.replace(
                    state,
                    status=PlaybackStatus.READY,
                    active_track=track,
                    position_ms=Millisecond(0),
                    error_message=None,
                )
                return new_state, (StopAudioIntent(),)

        case PlayRequested():
            if state.status == PlaybackStatus.READY and state.active_track is not None:
                new_state = dataclasses.replace(
                    state,
                    status=PlaybackStatus.PLAYING,
                    error_message=None,
                )
                return new_state, (
                    LoadAndPlayAudioIntent(
                        track=state.active_track,
                        loop=state.loop,
                        start_position_ms=state.position_ms,
                    ),
                )
            if state.status == PlaybackStatus.PAUSED:
                new_state = dataclasses.replace(
                    state,
                    status=PlaybackStatus.PLAYING,
                    error_message=None,
                )
                return new_state, (ResumeAudioIntent(),)
            return state, ()

        case PauseRequested():
            if state.status == PlaybackStatus.PLAYING:
                new_state = dataclasses.replace(state, status=PlaybackStatus.PAUSED)
                return new_state, (PauseAudioIntent(),)
            return state, ()

        case StopRequested():
            if state.status in (PlaybackStatus.PLAYING, PlaybackStatus.PAUSED):
                new_state = dataclasses.replace(
                    state,
                    status=PlaybackStatus.READY,
                    position_ms=Millisecond(0),
                    error_message=None,
                )
                return new_state, (StopAudioIntent(),)
            return state, ()

        case SeekRequested(position_ms=pos):
            max_ms = (
                state.active_track.duration_ms
                if state.active_track and state.active_track.duration_ms > 0
                else None
            )
            val = int(pos)
            if val < 0:
                val = 0
            elif max_ms is not None and val > int(max_ms):
                val = int(max_ms)

            clamped_ms = Millisecond(val)
            new_state = dataclasses.replace(state, position_ms=clamped_ms)
            return new_state, (SeekAudioIntent(position_ms=clamped_ms),)

        case VolumeChanged(volume=vol):
            clamped_vol = VolumeRatio(max(0.0, min(1.0, float(vol))))
            new_state = dataclasses.replace(state, volume=clamped_vol)
            return new_state, (SetVolumeIntent(volume=clamped_vol),)

        case AutoPlayToggled():
            new_state = dataclasses.replace(state, auto_play=not state.auto_play)
            return new_state, ()

        case LoopToggled():
            new_state = dataclasses.replace(state, loop=not state.loop)
            return new_state, ()

        case PlaybackProgressUpdated(position_ms=pos):
            if state.status == PlaybackStatus.PLAYING:
                new_state = dataclasses.replace(state, position_ms=pos)
                return new_state, ()
            return state, ()

        case PlaybackFinished():
            if state.loop:
                new_state = dataclasses.replace(state, position_ms=Millisecond(0))
                return new_state, ()
            new_state = dataclasses.replace(
                state,
                status=PlaybackStatus.READY,
                position_ms=Millisecond(0),
            )
            return new_state, (StopAudioIntent(),)

        case PlaybackFailed(reason=reason):
            new_state = dataclasses.replace(
                state,
                status=PlaybackStatus.READY,
                position_ms=Millisecond(0),
                error_message=reason,
            )
            return new_state, (StopAudioIntent(),)

        case _:
            return state, ()
