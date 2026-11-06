"""Pure Audiokinetic Wwise v112 SoundBank Baseline Diffing Engine."""

from __future__ import annotations

from dataclasses import dataclass

from src.bnk.bank import SoundBank
from src.bnk.models import HircObject


@dataclass(frozen=True, slots=True)
class BankDiffResult:
    """Immutable diff summary between an active SoundBank and its vanilla baseline."""

    modified_object_ids: frozenset[int] = frozenset()
    added_object_ids: frozenset[int] = frozenset()
    removed_object_ids: frozenset[int] = frozenset()
    modified_media_ids: frozenset[int] = frozenset()

    @property
    def all_modified_object_ids(self) -> frozenset[int]:
        """Union of modified and newly added HIRC object IDs."""
        return self.modified_object_ids | self.added_object_ids

    @property
    def is_modified(self) -> bool:
        """True if any HIRC object or embedded media differs from baseline."""
        return bool(
            self.modified_object_ids
            or self.added_object_ids
            or self.removed_object_ids
            or self.modified_media_ids
        )


def _extract_media_slices(bank: SoundBank) -> dict[int, bytes | int]:
    """
    Extracts embedded media representation from DIDX and DATA chunks.
    Returns mapping of file_id -> slice bytes (if DATA present) or size.
    """
    if not bank.didx or not bank.didx.entries:
        return {}

    entries: dict[int, bytes | int] = {}
    data_bytes = bank.data.data if bank.data is not None else None

    for entry in bank.didx.entries:
        if data_bytes is not None and entry.offset + entry.size <= len(data_bytes):
            entries[entry.file_id] = data_bytes[entry.offset : entry.offset + entry.size]
        else:
            entries[entry.file_id] = entry.size
    return entries


def diff_soundbanks(
    active: SoundBank,
    baseline: SoundBank | None,
) -> BankDiffResult:
    """
    Computes deterministic AST and media deltas between active and baseline SoundBank.
    If baseline is None, all active objects and media are marked as added/modified.
    """
    if baseline is None:
        active_hirc_ids = (
            frozenset(obj.id for obj in active.hirc.objects) if active.hirc else frozenset()
        )
        active_media_ids = (
            frozenset(e.file_id for e in active.didx.entries) if active.didx else frozenset()
        )
        return BankDiffResult(
            added_object_ids=active_hirc_ids,
            modified_media_ids=active_media_ids,
        )

    # 1. Diff HIRC Objects
    active_objects: dict[int, HircObject] = {}
    if active.hirc and active.hirc.objects:
        active_objects = {obj.id: obj for obj in active.hirc.objects}

    baseline_objects: dict[int, HircObject] = {}
    if baseline.hirc and baseline.hirc.objects:
        baseline_objects = {obj.id: obj for obj in baseline.hirc.objects}

    all_obj_ids = set(active_objects.keys()) | set(baseline_objects.keys())
    modified_objs: set[int] = set()
    added_objs: set[int] = set()
    removed_objs: set[int] = set()

    for oid in all_obj_ids:
        in_active = oid in active_objects
        in_base = oid in baseline_objects

        if in_active and not in_base:
            added_objs.add(oid)
        elif in_base and not in_active:
            removed_objs.add(oid)
        else:
            act_obj = active_objects[oid]
            base_obj = baseline_objects[oid]
            if type(act_obj) is not type(base_obj) or act_obj.to_bytes() != base_obj.to_bytes():
                modified_objs.add(oid)

    # 2. Diff DIDX / Embedded Media
    active_media = _extract_media_slices(active)
    baseline_media = _extract_media_slices(baseline)

    modified_media: set[int] = set()
    all_media_ids = set(active_media.keys()) | set(baseline_media.keys())

    for fid in all_media_ids:
        in_active = fid in active_media
        in_base = fid in baseline_media

        if (
            (in_active and not in_base)
            or (in_base and not in_active)
            or active_media[fid] != baseline_media[fid]
        ):
            modified_media.add(fid)

    return BankDiffResult(
        modified_object_ids=frozenset(modified_objs),
        added_object_ids=frozenset(added_objs),
        removed_object_ids=frozenset(removed_objs),
        modified_media_ids=frozenset(modified_media),
    )
