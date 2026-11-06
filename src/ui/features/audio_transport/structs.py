"""
Pure Immutable Data Ontology for Audio Transport & Auditioning.

Part of Phase 1 (/ontologize) in the Spec-Driven Functional Pipeline.
Defines domain vocabulary, frozen state entities, events, and effect intents.
ZERO Qt imports, ZERO I/O, ZERO side effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import NewType

# ---------------------------------------------------------------------------
# 1. Domain Vocabulary & Types
# ---------------------------------------------------------------------------

AudioSourceId = NewType("AudioSourceId", int)
Millisecond = NewType("Millisecond", int)
VolumeRatio = NewType("VolumeRatio", float)


class PlaybackStatus(str, Enum):
    """Discrete operational lifecycle states of the transport engine."""

    IDLE = "idle"  # No track loaded
    READY = "ready"  # Track loaded, cue at position 0, stopped
    PLAYING = "playing"  # Audio actively streaming / playing
    PAUSED = "paused"  # Audio stream paused at current position


# ---------------------------------------------------------------------------
# 2. State & Entity Structs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioTrack:
    """Resolvable, playable audio stream container."""

    source_id: AudioSourceId
    title: str
    file_path: str | None = None
    embedded_bytes: bytes | None = None
    duration_ms: Millisecond = Millisecond(0)


@dataclass(frozen=True, slots=True, kw_only=True)
class TransportState:
    """Pure, immutable snapshot of the audio transport engine."""

    status: PlaybackStatus = PlaybackStatus.IDLE
    active_track: AudioTrack | None = None
    position_ms: Millisecond = Millisecond(0)
    volume: VolumeRatio = VolumeRatio(1.0)
    auto_play: bool = True
    loop: bool = False
    error_message: str | None = None

    @property
    def can_play(self) -> bool:
        """Determines if the current track can transition to PLAYING."""
        return self.active_track is not None and self.status in (
            PlaybackStatus.READY,
            PlaybackStatus.PAUSED,
        )

    @property
    def can_pause(self) -> bool:
        """Determines if the active audio stream can be paused."""
        return self.status == PlaybackStatus.PLAYING

    @property
    def can_stop(self) -> bool:
        """Determines if active playback can be halted."""
        return self.status in (PlaybackStatus.PLAYING, PlaybackStatus.PAUSED)

    @property
    def progress_ratio(self) -> float:
        """Calculates playback completion from 0.0 to 1.0."""
        if self.active_track is None or self.active_track.duration_ms <= 0:
            return 0.0
        return max(0.0, min(1.0, float(self.position_ms) / float(self.active_track.duration_ms)))


# ---------------------------------------------------------------------------
# 3. Events / Commands (Incoming Stimuli)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class TrackSelected:
    """Dispatched when a tree or table node selection changes."""

    track: AudioTrack | None  # None when selecting a container without direct audio


@dataclass(frozen=True, slots=True, kw_only=True)
class PlayRequested:
    """Dispatched when user presses the Play button or Spacebar."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PauseRequested:
    """Dispatched when user presses the Pause button or Spacebar while playing."""


@dataclass(frozen=True, slots=True, kw_only=True)
class StopRequested:
    """Dispatched when user presses the Stop button."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SeekRequested:
    """Dispatched when user drags or releases the transport seek bar."""

    position_ms: Millisecond


@dataclass(frozen=True, slots=True, kw_only=True)
class VolumeChanged:
    """Dispatched when user adjusts the master audition volume slider."""

    volume: VolumeRatio


@dataclass(frozen=True, slots=True, kw_only=True)
class AutoPlayToggled:
    """Dispatched when user toggles the 'Auto Play' checkbox/switch."""


@dataclass(frozen=True, slots=True, kw_only=True)
class LoopToggled:
    """Dispatched when user toggles the 'Loop' checkbox/switch."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PlaybackProgressUpdated:
    """Dispatched periodically by the transport clock while playing."""

    position_ms: Millisecond


@dataclass(frozen=True, slots=True, kw_only=True)
class PlaybackFinished:
    """Dispatched when playback naturally reaches the end of the audio track."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PlaybackFailed:
    """Dispatched when audio decoding or hardware playback encounters an error."""

    reason: str


TransportEvent = (
    TrackSelected
    | PlayRequested
    | PauseRequested
    | StopRequested
    | SeekRequested
    | VolumeChanged
    | AutoPlayToggled
    | LoopToggled
    | PlaybackProgressUpdated
    | PlaybackFinished
    | PlaybackFailed
)


# ---------------------------------------------------------------------------
# 4. Effect Intents (Data as Actions)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class StopAudioIntent:
    """Halt audio playback and release playback channel."""


@dataclass(frozen=True, slots=True, kw_only=True)
class LoadAndPlayAudioIntent:
    """Decode and start playing the specified track."""

    track: AudioTrack
    loop: bool
    start_position_ms: Millisecond = Millisecond(0)


@dataclass(frozen=True, slots=True, kw_only=True)
class PauseAudioIntent:
    """Pause playback on the active audio channel."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ResumeAudioIntent:
    """Resume playback on the paused audio channel."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SeekAudioIntent:
    """Seek playback to a specific offset in milliseconds."""

    position_ms: Millisecond


@dataclass(frozen=True, slots=True, kw_only=True)
class SetVolumeIntent:
    """Update active channel gain."""

    volume: VolumeRatio


TransportEffectIntent = (
    StopAudioIntent
    | LoadAndPlayAudioIntent
    | PauseAudioIntent
    | ResumeAudioIntent
    | SeekAudioIntent
    | SetVolumeIntent
)
