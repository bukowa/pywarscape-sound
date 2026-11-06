"""Pure typed metadata fields and extraction for SoundBank HIRC and WEM audio objects.

Defines provenance classifications, pure typed metadata extraction, and metadata merging with zero I/O and zero exceptions.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import StrEnum

from src.bnk.models import CAkRanSeqCntr, HircObject
from src.bnk.wem import WemFormatTag, parse_wem_header


class Provenance(StrEnum):
    """Origin classification for extracted or resolved metadata."""

    BINARY = "binary"
    DATABASE = "database"
    HEURISTIC = "heuristic"


class MetadataField(StrEnum):
    """Identifier for typed node metadata attributes."""

    PLAYBACK_MODE = "playback_mode"
    AVOID_REPEAT = "avoid_repeat"
    PLAYLIST_WEIGHTS = "playlist_weights"
    DURATION_MS = "duration_ms"
    CHANNELS = "channels"
    SAMPLE_RATE = "sample_rate"
    CODEC = "codec"
    TRANSCRIPT = "transcript"


type MetadataScalar = int | float | str | tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class MetadataValue:
    """A typed metadata value with provenance tracking."""

    value: MetadataScalar
    provenance: Provenance = Provenance.BINARY


@dataclass(frozen=True, slots=True)
class NodeMetadata:
    """Immutable sequence of typed metadata attributes for an AST or media node."""

    entries: tuple[tuple[MetadataField, MetadataValue], ...] = ()

    def get(self, field: MetadataField) -> MetadataValue | None:
        """Returns the MetadataValue for the given field, or None if absent."""
        for f, v in self.entries:
            if f == field:
                return v
        return None

    def get_value(self, field: MetadataField) -> MetadataScalar | None:
        """Returns the scalar value for the given field, or None if absent."""
        mv = self.get(field)
        return mv.value if mv is not None else None


EMPTY_NODE_METADATA = NodeMetadata()


def extract_hirc_metadata(obj: HircObject) -> NodeMetadata:
    """Extracts typed binary metadata from a HIRC AST object."""
    if isinstance(obj, CAkRanSeqCntr):
        mode = getattr(obj, "mode", 0)
        rmode = getattr(obj, "random_mode", 0)
        mode_str = ("Shuffle" if rmode == 1 else "Random") if mode == 0 else "Sequence"
        avoid_repeat = int(getattr(obj, "avoid_repeat_count", 0))

        entries: list[tuple[MetadataField, MetadataValue]] = [
            (MetadataField.PLAYBACK_MODE, MetadataValue(mode_str, Provenance.BINARY)),
            (MetadataField.AVOID_REPEAT, MetadataValue(avoid_repeat, Provenance.BINARY)),
        ]

        playlist = getattr(obj, "playlist", ())
        if playlist:
            total_weight = sum(max(0, getattr(it, "weight", 0)) for it in playlist)
            shares: dict[str, float] = {}
            for it in playlist:
                ckey = f"hirc:{it.play_id}"
                w = max(0, getattr(it, "weight", 0))
                share = (w / total_weight) * 100.0 if total_weight > 0 else (100.0 / len(playlist))
                shares[ckey] = shares.get(ckey, 0.0) + share
            entries.append(
                (
                    MetadataField.PLAYLIST_WEIGHTS,
                    MetadataValue(tuple(shares.items()), Provenance.BINARY),
                )
            )

        return NodeMetadata(entries=tuple(entries))

    return EMPTY_NODE_METADATA


def format_wem_codec(format_tag: int, form_type: str = "WAVE") -> str:
    """Formats codec description string from Wwise format tag and form type."""
    if form_type == "XWMA":
        return "XWMA"
    if format_tag == WemFormatTag.VORBIS:
        return "Vorbis"
    if format_tag in (WemFormatTag.PCM, WemFormatTag.EXTENSIBLE):
        return "PCM"
    if format_tag == WemFormatTag.ADPCM:
        return "ADPCM"
    return f"0x{format_tag:04X}"


def extract_wem_header_metadata(data: bytes | bytearray | memoryview) -> NodeMetadata:
    """Pure extractor resolving duration, channels, sample rate, and codec from WEM header bytes."""
    if not data:
        return EMPTY_NODE_METADATA

    try:
        header = parse_wem_header(bytes(data))
    except (ValueError, EOFError, struct.error):
        return EMPTY_NODE_METADATA

    return NodeMetadata(
        entries=(
            (
                MetadataField.DURATION_MS,
                MetadataValue(round(header.duration_ms, 1), Provenance.BINARY),
            ),
            (
                MetadataField.CHANNELS,
                MetadataValue(int(header.channels), Provenance.BINARY),
            ),
            (
                MetadataField.SAMPLE_RATE,
                MetadataValue(int(header.sample_rate), Provenance.BINARY),
            ),
            (
                MetadataField.CODEC,
                MetadataValue(
                    format_wem_codec(header.format_tag, header.form_type),
                    Provenance.BINARY,
                ),
            ),
        )
    )


def merge_node_metadata(base: NodeMetadata, extra: NodeMetadata) -> NodeMetadata:
    """Purely merges extra metadata into base, replacing existing fields and appending new ones."""
    if not extra.entries:
        return base
    if not base.entries:
        return extra

    extra_map = {f: v for f, v in extra.entries}
    handled: set[MetadataField] = set()
    merged: list[tuple[MetadataField, MetadataValue]] = []

    for f, v in base.entries:
        if f in extra_map:
            merged.append((f, extra_map[f]))
            handled.add(f)
        else:
            merged.append((f, v))

    for f, v in extra.entries:
        if f not in handled:
            merged.append((f, v))

    return NodeMetadata(entries=tuple(merged))
