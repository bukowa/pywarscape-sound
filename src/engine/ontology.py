"""
Pure immutable data ontology for all audio replacement and mutation workflows.
Follows strict algebraic state modeling with zero I/O or mutable state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Literal

# -----------------------------------------------------------------------------
# 1. Domain Primitive Identifiers & Enums
# -----------------------------------------------------------------------------

type WemId = int
type HircId = int
type BankName = str


class AudioStreamMode(Enum):
    """Wwise audio streaming mode representation."""

    EMBEDDED = 0  # In DATA chunk via DIDX
    PREFETCH = 1  # Prefetched in bank, remainder streamed
    STREAMED = 2  # Pure loose/streamed .wem file (recommended modding mode)


class ReplacementScope(str, Enum):
    """Blast radius scope for audio replacement operations."""

    OVERWRITE = "overwrite"  # Overwrite shared WEM asset on disk
    ISOLATE = "isolate"  # Allocate new unique WEM ID for target node only


# -----------------------------------------------------------------------------
# 2. Replacement Sources (Discriminated Union / Sum Type)
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class ExternalFileSource:
    """Modder-supplied raw audio file (WAV, MP3, OGG, FLAC)."""

    file_path: Path
    custom_alias: str | None = None
    target_sample_rate: int | None = None
    target_channels: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ExistingMediaReferenceSource:
    """Reference to an existing WEM ID already present in GameCache or Dependencies."""

    wem_id: WemId
    source_bank: BankName | None = None  # Informational provenance


@dataclass(frozen=True, slots=True, kw_only=True)
class CrossBankCloneSource:
    """Cloning a full HIRC node subtree from another SoundBank."""

    source_bank_name: BankName
    source_node_id: HircId
    clone_media: bool = False  # True = copy loose WEM; False = reference same WEM ID


@dataclass(frozen=True, slots=True, kw_only=True)
class SilentStubSource:
    """Mutes the sound using the standard 50ms silent Vorbis/PCM stub."""

    stub_wem_id: WemId = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class NodeParamsSource:
    """Slot-local NodeBaseParams property overrides (Volume dB = PropID 0, Pitch cents = PropID 2)."""

    volume_db: float | None = None
    pitch_cents: float | None = None


type AudioReplacementSource = (
    ExternalFileSource
    | ExistingMediaReferenceSource
    | CrossBankCloneSource
    | SilentStubSource
    | NodeParamsSource
)


# -----------------------------------------------------------------------------
# 3. Mutation Target Descriptors
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class SoundNodeTarget:
    """Targeting an existing CAkSound object."""

    bank_name: BankName
    sound_id: HircId


@dataclass(frozen=True, slots=True, kw_only=True)
class MusicTrackTarget:
    """Targeting a CAkMusicTrack and its parent CAkMusicSegment."""

    bank_name: BankName
    track_id: HircId
    source_index: int = 0
    parent_segment_id: HircId | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ContainerVariationTarget:
    """Targeting a variation slot inside CAkRanSeqCntr or CAkSwitchCntr."""

    bank_name: BankName
    container_id: HircId
    variation_sound_id: HircId | None = None  # None = Append new variation


@dataclass(frozen=True, slots=True, kw_only=True)
class MediaNodeTarget:
    """Targeting an embedded WEM or loose media entry."""

    bank_name: BankName
    wem_id: WemId


type MutationTarget = (
    SoundNodeTarget | MusicTrackTarget | ContainerVariationTarget | MediaNodeTarget
)


# -----------------------------------------------------------------------------
# 4. Effect Intents (Data as Actions / Pure Imperative Shell Dispatch)
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class StageMasterAudioIntent:
    """Intent to copy uncompressed audio into project source_audio/."""

    source_path: Path
    destination_rel_path: str  # e.g. "source_audio/my_shout.wav"
    wem_id: WemId


@dataclass(frozen=True, slots=True, kw_only=True)
class StageLooseWemIntent:
    """Intent to write encoded .wem bytes to pack_root/audio/<wem_id>.wem."""

    wem_id: WemId
    wem_bytes: bytes


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateSoundNodeIntent:
    """Intent to update CAkSound HIRC parameters in memory."""

    bank_name: BankName
    sound_id: HircId
    new_stream_type: int = 2
    new_source_id: WemId
    new_file_id: WemId
    new_plugin_id: int = 0x00010001


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateMusicTrackNodeIntent:
    """Intent to update a CAkMusicTrack source descriptor and clip source ID in memory."""

    bank_name: BankName
    track_id: HircId
    source_index: int = 0
    new_stream_type: int = 2
    new_source_id: WemId
    new_file_id: WemId
    new_plugin_id: int = 0x00010001


@dataclass(frozen=True, slots=True, kw_only=True)
class SyncMusicTimelineIntent:
    """Intent to update CAkMusicTrack and CAkMusicSegment durations."""

    bank_name: BankName
    track_id: HircId
    new_duration_ms: float
    source_index: int = 0
    parent_segment_id: HircId | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class AppendVariationIntent:
    """Intent to create or link a new CAkSound node into a CAkRanSeqCntr playlist."""

    bank_name: BankName
    container_id: HircId
    child_sound_id: HircId
    wem_id: WemId = 0
    plugin_id: int = 0x00010001
    weight: int = 50000


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateNodeParamsIntent:
    """Intent to update slot-local NodeBaseParams properties (PropID 0 = Volume, PropID 2 = Pitch)."""

    bank_name: BankName
    node_id: HircId
    volume_db: float | None = None
    pitch_cents: float | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class MarkBankModifiedIntent:
    """Intent to record modified bank state in project manifest."""

    bank_name: BankName


@dataclass(frozen=True, slots=True, kw_only=True)
class CopyMediaBytesIntent:
    """Intent to copy existing resolved WEM bytes to a target loose WEM ID."""

    target_wem_id: WemId
    source_wem_id: WemId
    source_bank_name: BankName | None = None


type AudioMutationEffectIntent = (
    StageMasterAudioIntent
    | StageLooseWemIntent
    | UpdateSoundNodeIntent
    | UpdateMusicTrackNodeIntent
    | SyncMusicTimelineIntent
    | AppendVariationIntent
    | MarkBankModifiedIntent
    | CopyMediaBytesIntent
    | UpdateNodeParamsIntent
)


# -----------------------------------------------------------------------------
# 5. Atomic Mutation Plan (Result of Causation / Decision Logic)
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class PlanRejection:
    """Pure domain rejection returned when an audio replacement plan cannot be constructed."""

    code: str
    reason: str


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioMutationPlan:
    """
    A verified, atomic recipe of effect intents produced by the functional core.
    Can be inspected, verified, executed, or reversed (Undo/Redo) with zero side-effects.
    """

    description: str
    target: MutationTarget
    source: AudioReplacementSource
    effects: tuple[AudioMutationEffectIntent, ...] = ()


# -----------------------------------------------------------------------------
# 7. Mutation Undo / Redo Record & Snapshots
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MediaTargetSnapshot:
    """Pre-mutation state snapshot for a single media target."""

    wem_id: int
    was_staged: bool
    before_bytes: bytes


@dataclass(frozen=True, slots=True)
class BankBatchSnapshot:
    """Pre-mutation state snapshot for a soundbank within a batch operation."""

    bank_name: str
    is_pure_media: bool
    before_bank_bytes: bytes
    was_modified: bool
    media_snapshots: tuple[MediaTargetSnapshot, ...] = ()

    def get_media_snapshot(self, wem_id: int) -> MediaTargetSnapshot | None:
        """Finds media target snapshot matching wem_id, or None."""
        for snap in self.media_snapshots:
            if snap.wem_id == wem_id:
                return snap
        return None


@dataclass(frozen=True, slots=True)
class MutationRecord:
    """
    Snapshot of an audio bank mutation for undo/redo state restoration.
    Enforces deterministic reversing and re-applying of HIRC mutations and loose assets.
    """

    bank_name: str
    node_key: str
    description: str
    before_bank_bytes: bytes
    after_bank_bytes: bytes
    staged_wem_ids: tuple[int, ...] = ()
    was_bank_originally_modified: bool = False
    staged_wem_bytes: tuple[tuple[int, bytes], ...] = ()
    node_keys: tuple[str, ...] = ()
    overwritten_wem_bytes: tuple[tuple[int, bytes], ...] = ()
    kind: Literal["bank", "media"] = "bank"

    @property
    def is_media(self) -> bool:
        """Returns True if this mutation records a media-only replacement."""
        return self.kind == "media" or self.node_key.startswith("media:")


# -----------------------------------------------------------------------------
# 8. Batch Mutation & Transaction Structs
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BatchItem:
    """A single audio replacement directive pairing a target node with a source audio asset."""

    target: MutationTarget
    source: AudioReplacementSource
    scope: ReplacementScope = ReplacementScope.OVERWRITE
    forked_wem_id: WemId | None = None


@dataclass(frozen=True, slots=True)
class MutationBatch:
    """A collection of replacement directives to be planned and applied as an atomic operation."""

    description: str
    items: tuple[BatchItem, ...] = ()


@dataclass(frozen=True, slots=True)
class BatchPlan:
    """Result of planning a batch of mutations, separating successful plans from rejections."""

    plans: tuple[AudioMutationPlan, ...] = ()
    rejections: tuple[tuple[BatchItem, PlanRejection], ...] = ()


@dataclass(frozen=True, slots=True)
class MutationTransaction:
    """An atomic multi-bank undo/redo unit aggregating individual bank mutation records."""

    description: str
    records: tuple[MutationRecord, ...] = ()
    node_keys: tuple[str, ...] = ()

    @property
    def all_node_keys(self) -> tuple[str, ...]:
        """Aggregate tuple of all node keys touched across records in this transaction."""
        if self.node_keys:
            return self.node_keys
        keys: list[str] = []
        for r in self.records:
            if r.node_keys:
                for k in r.node_keys:
                    if k not in keys:
                        keys.append(k)
            elif r.node_key and r.node_key not in keys:
                keys.append(r.node_key)
        return tuple(keys)


@dataclass(frozen=True, slots=True)
class BatchOutcome:
    """Outcome of applying a MutationBatch through WorkspaceSession."""

    applied: int
    rejections: tuple[tuple[BatchItem, PlanRejection], ...] = ()
    touched_banks: tuple[str, ...] = ()


# -----------------------------------------------------------------------------
# 9. Cross-Bank WEM Reference Descriptors
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class WemReference:
    """Descriptor for a HIRC node referencing an audio WEM source ID."""

    bank_name: str
    node_id: int
    node_name: str
    node_type: str  # e.g. "Sound", "MusicTrack", "Embedded Media"
    node_key: str  # "hirc:<id>" or "media:<id>"
    stream_type: int  # 0=embedded, 1=prefetch, 2=streamed
    is_embedded: bool  # True if stream_type != 2 or present in DIDX
