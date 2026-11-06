"""Pure column specifications and shared audio formatting helpers for tabular views.

Defines generic TableColumnSpec and headless audio formatting functions with zero Qt imports.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.engine.metadata_fields import Provenance


def format_duration_ms(duration_ms: float) -> str:
    """Formats duration in milliseconds as seconds (e.g. 0.05s) or mm:ss (e.g. 1:00)."""
    if duration_ms < 0:
        return ""
    sec = duration_ms / 1000.0
    if round(sec, 2) < 60.0:
        return f"{sec:.2f}s"
    total_sec = int(round(sec))
    return f"{total_sec // 60}:{total_sec % 60:02d}"


def format_sample_rate_khz(sample_rate: int) -> str:
    """Formats sample rate in Hz as kHz (e.g. 32 kHz, 44.1 kHz)."""
    if sample_rate <= 0:
        return ""
    khz = f"{sample_rate / 1000.0:.3f}".rstrip("0").rstrip(".")
    return f"{khz} kHz"


def format_channel_label(channels: int) -> str:
    """Formats channel count as Mono, Stereo, or Nch (e.g. 4ch)."""
    if channels <= 0:
        return ""
    if channels == 1:
        return "Mono"
    if channels == 2:
        return "Stereo"
    return f"{channels}ch"


@dataclass(frozen=True, slots=True, kw_only=True)
class TableColumnSpec[T_id, T_row]:
    """Generic specification describing a configurable table column."""

    id: T_id
    header: str
    default_visible: bool
    hideable: bool = True
    default_width: int = 100
    searchable: bool = True
    cell: Callable[[T_row], str]
    cell_provenance: Callable[[T_row], Provenance] = lambda _row: Provenance.BINARY
    sort_key: Callable[[T_row], Any] | None = None
