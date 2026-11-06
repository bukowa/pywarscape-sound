"""Mod pack health diagnostics and soundbank auto-repair engine.

Provides headless inspection of Audiokinetic Wwise SoundBanks and PFH4 mod pack
archives to detect binary corruptions, byte-alignment issues, and word-swapped
automation structures that induce runtime engine crashes (CTD).
"""

import re
import struct
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from src.bnk.bank import SoundBank, repair_extracted_bnk_bytes
from src.bnk.models import AkMusicTrackSource, AkTrackSrcInfo
from src.bnk.stream import ByteReader


class IssueSeverity(Enum):
    """Severity classification for diagnostic issues."""

    CRITICAL_CRASH = "critical_crash"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class HealthIssue:
    """Diagnostic health defect or anomaly detected in a mod pack or SoundBank."""

    issue_id: str
    file_path: str
    object_id: int | None
    title: str
    description: str
    severity: IssueSeverity
    can_autofix: bool
    fix_description: str | None = None


@dataclass(frozen=True, slots=True)
class PackHealthReport:
    """Diagnostic health assessment report for a mod pack archive."""

    pack_name: str
    issues: tuple[HealthIssue, ...] = ()
    has_critical_issues: bool = field(init=False)
    all_fixable: bool = field(init=False)

    def __init__(
        self,
        pack_name: str,
        issues: Sequence[HealthIssue] = (),
        has_critical_issues: bool | None = None,
        all_fixable: bool | None = None,
    ) -> None:
        issue_tuple = tuple(issues)
        object.__setattr__(self, "pack_name", pack_name)
        object.__setattr__(self, "issues", issue_tuple)
        if has_critical_issues is None:
            has_critical_issues = any(
                i.severity == IssueSeverity.CRITICAL_CRASH for i in issue_tuple
            )
        object.__setattr__(self, "has_critical_issues", has_critical_issues)
        if all_fixable is None:
            all_fixable = len(issue_tuple) > 0 and all(i.can_autofix for i in issue_tuple)
        object.__setattr__(self, "all_fixable", all_fixable)


def sanitize_stid_name(raw_name: str | bytes) -> str:
    """Extracts a valid clean SoundBank name, stripping null bytes and non-ASCII binary garbage."""
    if isinstance(raw_name, bytes):
        text = raw_name.split(b"\x00")[0].decode("latin1", errors="replace")
    else:
        text = raw_name.split("\x00")[0]

    match = re.match(r"^[a-zA-Z0-9_\- ]+", text)
    if match:
        return match.group(0).rstrip()
    return text


class PackHealthScanner:
    """Headless diagnostic scanner for Audiokinetic Wwise SoundBanks and mod packs."""

    @classmethod
    def scan_soundbank(cls, bnk_name: str, bnk_bytes: bytes) -> tuple[HealthIssue, ...]:
        """Inspects SoundBank binary bytes for structural corruptions and word-swapped fields."""
        cleaned_data = repair_extracted_bnk_bytes(bnk_bytes)
        if len(cleaned_data) < 8 or cleaned_data[:4] != b"BKHD":
            return (
                HealthIssue(
                    issue_id="bnk_invalid_header",
                    file_path=bnk_name,
                    object_id=None,
                    title="Invalid SoundBank Header",
                    description="Binary payload does not start with standard Wwise BKHD chunk header.",
                    severity=IssueSeverity.CRITICAL_CRASH,
                    can_autofix=False,
                    fix_description=None,
                ),
            )

        issues: list[HealthIssue] = []
        reader = ByteReader(cleaned_data)

        while reader.remaining >= 8:
            tag = reader.read_bytes(4).decode("latin1", errors="replace")
            chunk_len = reader.read_u32()
            if chunk_len > reader.remaining:
                issues.append(
                    HealthIssue(
                        issue_id="bnk_truncated_chunk",
                        file_path=bnk_name,
                        object_id=None,
                        title="Truncated SoundBank Chunk",
                        description=(
                            f"Chunk '{tag}' declares length {chunk_len} bytes but only "
                            f"{reader.remaining} bytes remain in stream."
                        ),
                        severity=IssueSeverity.CRITICAL_CRASH,
                        can_autofix=False,
                        fix_description=None,
                    )
                )
                break
            chunk_reader = reader.read_slice(chunk_len)

            if tag == "HIRC":
                try:
                    obj_count = chunk_reader.read_u32()
                except Exception:
                    obj_count = 0

                for _ in range(obj_count):
                    if chunk_reader.remaining < 5:
                        break
                    obj_type = chunk_reader.read_u8()
                    obj_len = chunk_reader.read_u32()
                    if obj_len > chunk_reader.remaining:
                        break
                    sub = chunk_reader.read_slice(obj_len)
                    try:
                        obj_id = sub.read_u32()

                        if obj_type == 11:  # CAkMusicTrack
                            sub.read_u8()  # flags
                            num_sources = sub.read_u32()
                            for _ in range(num_sources):
                                AkMusicTrackSource.read(sub)

                            num_playlist = sub.read_u32()
                            for _ in range(num_playlist):
                                AkTrackSrcInfo.read(sub)

                            if num_playlist > 0:
                                sub.read_u32()  # num_sub_track

                            num_clip_auto = sub.read_u32()
                            if num_clip_auto * 12 > sub.remaining:
                                is_swapped = False
                                recovered_count = 0
                                if (num_clip_auto & 0xFF) == 0 and 0 < (
                                    num_clip_auto >> 8
                                ) * 12 <= sub.remaining:
                                    is_swapped = True
                                    recovered_count = num_clip_auto >> 8
                                elif (
                                    0
                                    < ((num_clip_auto >> 16) | ((num_clip_auto & 0xFFFF) << 16))
                                    * 12
                                    <= sub.remaining
                                ):
                                    is_swapped = True
                                    recovered_count = (num_clip_auto >> 16) | (
                                        (num_clip_auto & 0xFFFF) << 16
                                    )

                                if is_swapped:
                                    issues.append(
                                        HealthIssue(
                                            issue_id="ca_track_clip_auto_swapped",
                                            file_path=bnk_name,
                                            object_id=obj_id,
                                            title="Word-Swapped Clip Automation Count",
                                            description=(
                                                f"Music track {obj_id} has word-swapped clip automation count "
                                                f"(raw: 0x{num_clip_auto:08x}, expected: {recovered_count}), "
                                                f"inducing memory fault and crash to desktop on playback."
                                            ),
                                            severity=IssueSeverity.CRITICAL_CRASH,
                                            can_autofix=True,
                                            fix_description=(
                                                f"Re-serialize track header to canonical Wwise count = {recovered_count}"
                                            ),
                                        )
                                    )
                    except (ValueError, IndexError, EOFError, RuntimeError, struct.error, OSError):
                        continue

            elif tag == "STID":
                try:
                    _ui_type, count = chunk_reader.read_struct("<II")
                    for _ in range(count):
                        bank_id = chunk_reader.read_u32()
                        name_len = chunk_reader.read_u8()
                        name_bytes = chunk_reader.read_bytes(name_len)
                        if b"\x00" in name_bytes:
                            clean_str = sanitize_stid_name(name_bytes)
                            issues.append(
                                HealthIssue(
                                    issue_id="stid_corrupted_string",
                                    file_path=bnk_name,
                                    object_id=bank_id,
                                    title="Corrupted STID Bank Name String",
                                    description=(
                                        f"SoundBank ID {bank_id} has un-terminated or embedded null bytes in "
                                        f"STID string table entry."
                                    ),
                                    severity=IssueSeverity.WARNING,
                                    can_autofix=True,
                                    fix_description=f"Truncate STID bank name to valid clean string '{clean_str}'",
                                )
                            )
                except (ValueError, IndexError, EOFError, struct.error, OSError):
                    pass

        return tuple(issues)

    @classmethod
    def scan_pack(cls, pack_path: str | Path) -> PackHealthReport:
        """Inspects all SoundBanks contained within a PFH4 pack archive."""
        pack_path = Path(pack_path)
        if not pack_path.is_file():
            return PackHealthReport(pack_name=pack_path.name, issues=())

        from src.compiler.pfh4_pack import extract_pfh4_file, read_pfh4_index

        try:
            entries = read_pfh4_index(pack_path)
        except Exception as e:
            return PackHealthReport(
                pack_name=pack_path.name,
                issues=(
                    HealthIssue(
                        issue_id="pfh_index_corrupt",
                        file_path=pack_path.name,
                        object_id=None,
                        title="Corrupted Pack Index",
                        description=f"Failed parsing PFH4 pack index: {e}",
                        severity=IssueSeverity.CRITICAL_CRASH,
                        can_autofix=False,
                        fix_description=None,
                    ),
                ),
            )

        issues: list[HealthIssue] = []
        for entry in entries:
            norm_path = entry.path.replace("\\", "/")
            if norm_path.lower().endswith(".bnk"):
                try:
                    data = extract_pfh4_file(pack_path, entry)
                    bank_issues = cls.scan_soundbank(norm_path, data)
                    issues.extend(bank_issues)
                except Exception as ex:
                    issues.append(
                        HealthIssue(
                            issue_id="bnk_read_failure",
                            file_path=norm_path,
                            object_id=None,
                            title="SoundBank Read Failure",
                            description=f"Failed extracting or parsing SoundBank: {ex}",
                            severity=IssueSeverity.CRITICAL_CRASH,
                            can_autofix=False,
                            fix_description=None,
                        )
                    )

        return PackHealthReport(pack_name=pack_path.name, issues=issues)


class RepairStrategyRegistry:
    """Executes safe AST re-serialization and binary normalization repairs."""

    @classmethod
    def repair_bank(
        cls,
        bnk_name: str,
        bnk_bytes: bytes,
        issue_ids: set[str] | None = None,
    ) -> bytes:
        """Repairs fixable structural anomalies by deserializing into typed AST and re-serializing."""
        bank = SoundBank.from_bytes(bnk_bytes)

        if bank.stid and (issue_ids is None or "stid_corrupted_string" in issue_ids):
            cleaned_names: dict[int, str] = {}
            for bid, name in bank.stid.bank_names.items():
                if "\x00" in name:
                    cleaned_names[bid] = sanitize_stid_name(name)
                else:
                    cleaned_names[bid] = name
            bank.stid.bank_names = cleaned_names

        return bank.to_bytes()
