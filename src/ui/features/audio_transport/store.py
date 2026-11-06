"""
Imperative Shell (Store) for Audio Transport & Auditioning.

Part of Phase 4 (/effectuate) in the Spec-Driven Functional Pipeline.
Manages physical audio I/O, vgmstream decoding, pygame.mixer playback,
and routes state updates between causation and listeners.
ZERO Qt imports, ZERO domain logic.
"""

from __future__ import annotations

import io
import logging
import time
import wave
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, assert_never

if TYPE_CHECKING:
    import pygame

from src.deps.player import decode_wem_to_wav_bytes
from src.ui.features.audio_transport.causation import reconcile_transport
from src.ui.features.audio_transport.structs import (
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

logger = logging.getLogger(__name__)


class AudioTransportStore:
    """Imperative shell managing audio playback engine and state transitions."""

    def __init__(self, initial_state: TransportState | None = None) -> None:
        self._state = initial_state or TransportState()
        self._listeners: list[Callable[[TransportState], None]] = []

        # Backend playback hardware / buffer state
        self._current_wav_bytes: bytes | None = None
        self._active_sound: pygame.mixer.Sound | None = None
        self._active_channel: pygame.mixer.Channel | None = None
        self._play_start_time: float = 0.0
        self._paused_elapsed_ms: int = 0

    @property
    def state(self) -> TransportState:
        """Returns the immutable state snapshot."""
        return self._state

    def subscribe(self, listener: Callable[[TransportState], None]) -> Callable[[], None]:
        """Subscribes a listener callback to state changes."""
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def dispatch(self, event: TransportEvent) -> None:
        """Executes the observe -> decide -> apply sandwich."""
        new_state, intents = reconcile_transport(self._state, event)
        self._state = new_state
        self._apply_intents(intents)
        self._notify_listeners()

    # -----------------------------------------------------------------------
    # Public Command Conveniences
    # -----------------------------------------------------------------------

    def select_track(self, track: AudioTrack | None) -> None:
        """Binds a new track or clears current track."""
        self.dispatch(TrackSelected(track=track))

    def play(self) -> None:
        """Requests playback to start or resume."""
        self.dispatch(PlayRequested())

    def pause(self) -> None:
        """Requests playback to pause."""
        self.dispatch(PauseRequested())

    def stop(self) -> None:
        """Requests playback to halt."""
        self.dispatch(StopRequested())

    def seek(self, position_ms: int) -> None:
        """Requests seek to target millisecond offset."""
        self.dispatch(SeekRequested(position_ms=Millisecond(position_ms)))

    def set_volume(self, volume: float) -> None:
        """Sets master audition volume (0.0 to 1.0)."""
        self.dispatch(VolumeChanged(volume=VolumeRatio(volume)))

    def toggle_auto_play(self) -> None:
        """Toggles the auto-play switch."""
        self.dispatch(AutoPlayToggled())

    def toggle_loop(self) -> None:
        """Toggles the looping switch."""
        self.dispatch(LoopToggled())

    def tick(self) -> None:
        """Polled by clock timer to update position or detect completion."""
        if self._state.status != PlaybackStatus.PLAYING or not self._active_channel:
            return

        if not self._active_channel.get_busy():
            self.dispatch(PlaybackFinished())
            return

        elapsed_ms = int((time.monotonic() - self._play_start_time) * 1000)
        dur_ms = int(self._state.active_track.duration_ms) if self._state.active_track else 0
        if dur_ms > 0:
            elapsed_ms = (elapsed_ms % dur_ms) if self._state.loop else min(elapsed_ms, dur_ms)

        self.dispatch(PlaybackProgressUpdated(position_ms=Millisecond(elapsed_ms)))

    # -----------------------------------------------------------------------
    # Private Intent Actuator
    # -----------------------------------------------------------------------

    def _apply_intents(self, intents: tuple[TransportEffectIntent, ...]) -> None:
        """Exhaustively actuates all returned effect intents."""
        for intent in intents:
            match intent:
                case StopAudioIntent():
                    self._actuate_stop()
                case LoadAndPlayAudioIntent(track=trk, loop=lp, start_position_ms=start):
                    self._actuate_load_and_play(trk, lp, start)
                case PauseAudioIntent():
                    self._actuate_pause()
                case ResumeAudioIntent():
                    self._actuate_resume()
                case SeekAudioIntent(position_ms=pos_ms):
                    self._actuate_seek(pos_ms)
                case SetVolumeIntent(volume=vol):
                    self._actuate_set_volume(vol)
                case _ as unreachable:
                    assert_never(unreachable)

    def _actuate_stop(self) -> None:
        for target in (self._active_channel, self._active_sound):
            if target:
                try:
                    target.stop()
                except (RuntimeError, AttributeError, OSError):
                    pass
        self._active_channel = None
        self._active_sound = None

    def _actuate_load_and_play(self, track: AudioTrack, loop: bool, start_ms: Millisecond) -> None:
        self._actuate_stop()
        import pygame

        try:
            wem_source: str | bytes
            if track.file_path:
                wem_source = track.file_path
            elif track.embedded_bytes:
                wem_source = track.embedded_bytes
            else:
                raise ValueError("AudioTrack contains neither file_path nor embedded_bytes.")

            wav_bytes = decode_wem_to_wav_bytes(wem_source)
            self._current_wav_bytes = wav_bytes

            # Measure accurate duration from standard WAV header
            duration_ms = self._measure_wav_duration_ms(wav_bytes)
            if duration_ms > 0 and track.duration_ms != duration_ms:
                updated_track = replace(track, duration_ms=Millisecond(duration_ms))
                self._state = replace(self._state, active_track=updated_track)
                self._notify_listeners()

            if pygame.mixer.get_init() is None:
                pygame.mixer.init()

            target_wav = self._slice_wav_bytes(wav_bytes, int(start_ms))
            sound = pygame.mixer.Sound(file=io.BytesIO(target_wav))
            sound.set_volume(float(self._state.volume))

            loops = -1 if loop else 0
            channel = sound.play(loops=loops)
            self._active_sound = sound
            self._active_channel = channel
            self._play_start_time = time.monotonic() - (int(start_ms) / 1000.0)
        except Exception as e:
            self.dispatch(PlaybackFailed(reason=str(e)))

    def _actuate_pause(self) -> None:
        if self._active_channel:
            try:
                self._active_channel.pause()
                self._paused_elapsed_ms = int((time.monotonic() - self._play_start_time) * 1000)
            except (RuntimeError, AttributeError, OSError):
                pass

    def _actuate_resume(self) -> None:
        if self._active_channel:
            try:
                self._active_channel.unpause()
                self._play_start_time = time.monotonic() - (self._paused_elapsed_ms / 1000.0)
            except (RuntimeError, AttributeError, OSError):
                pass

    def _actuate_seek(self, position_ms: Millisecond) -> None:
        if self._state.status == PlaybackStatus.PLAYING and self._state.active_track:
            self._actuate_load_and_play(self._state.active_track, self._state.loop, position_ms)

    def _actuate_set_volume(self, volume: VolumeRatio) -> None:
        if self._active_sound:
            try:
                self._active_sound.set_volume(float(volume))
            except (RuntimeError, AttributeError, OSError):
                pass

    def _measure_wav_duration_ms(self, wav_bytes: bytes) -> int:
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                framerate = wf.getframerate()
                nframes = wf.getnframes()
                if framerate > 0:
                    return int(round((nframes / float(framerate)) * 1000))
        except (wave.Error, OSError, ValueError):
            pass
        return 0

    def _slice_wav_bytes(self, wav_bytes: bytes, start_ms: int) -> bytes:
        if start_ms <= 0:
            return wav_bytes
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                params = wf.getparams()
                framerate = wf.getframerate()
                total_frames = wf.getnframes()
                frame_offset = int((start_ms / 1000.0) * framerate)
                frame_offset = max(0, min(frame_offset, total_frames))
                wf.setpos(frame_offset)
                frames = wf.readframes(total_frames - frame_offset)

            out_buf = io.BytesIO()
            with wave.open(out_buf, "wb") as out_wf:
                out_wf.setparams(params)
                out_wf.setnframes(total_frames - frame_offset)
                out_wf.writeframes(frames)
            return out_buf.getvalue()
        except (wave.Error, OSError, ValueError):
            return wav_bytes

    def _notify_listeners(self) -> None:
        for listener in list(self._listeners):
            try:
                listener(self._state)
            except Exception:
                logger.exception("AudioTransportStore listener raised unhandled exception")
