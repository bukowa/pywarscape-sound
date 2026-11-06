"""
Pure deterministic mutation planner (Functional Core).
Calculates and validates atomic AudioMutationPlans without performing disk I/O.
"""

from __future__ import annotations

from collections.abc import Collection, Container, Mapping
from pathlib import Path
from typing import Any, assert_never

from src.bnk.models import CAkSound
from src.bnk.wem import build_silent_pcm_wem_bytes
from src.engine.ontology import (
    AudioMutationEffectIntent,
    AudioMutationPlan,
    AudioReplacementSource,
    BatchItem,
    BatchPlan,
    ContainerVariationTarget,
    CopyMediaBytesIntent,
    CrossBankCloneSource,
    ExistingMediaReferenceSource,
    ExternalFileSource,
    MarkBankModifiedIntent,
    MediaNodeTarget,
    MusicTrackTarget,
    MutationBatch,
    MutationTarget,
    PlanRejection,
    ReplacementScope,
    SilentStubSource,
    SoundNodeTarget,
    StageLooseWemIntent,
    StageMasterAudioIntent,
    UpdateSoundNodeIntent,
    WemId,
)


def allocate_unique_wem_id(
    existing_ids: Container[int],
    preferred_seed: int | None = None,
) -> WemId:
    """
    Allocates a positive 32-bit WEM ID (100000 < ID <= 0x7FFFFFFF) guaranteed
    not to collide with existing_ids.

    If preferred_seed is provided and valid (100000 < seed <= 0x7FFFFFFF) and not
    in existing_ids, returns preferred_seed directly. Otherwise, deterministically
    steps through non-colliding candidates using a 31-bit LCG.
    """
    if preferred_seed is not None and 100000 < preferred_seed <= 0x7FFFFFFF:
        candidate = preferred_seed
    else:
        candidate = 100001

    while candidate in existing_ids or candidate <= 100000 or candidate > 0x7FFFFFFF:
        # Linear congruential generator step (Numerical Recipes)
        candidate = (candidate * 1664525 + 1013904223) & 0x7FFFFFFF
        if candidate <= 100000:
            candidate += 100001

    return candidate


def _collect_bank_wem_ids(bank: Any) -> set[int]:
    """Collects all WEM and HIRC object IDs currently present in a bank."""
    ids: set[int] = set()
    hirc = getattr(bank, "hirc", None)
    if hirc is not None:
        for obj in getattr(hirc, "objects", ()):
            obj_id = getattr(obj, "id", None)
            if obj_id is not None:
                ids.add(obj_id)
            if isinstance(obj, CAkSound):
                sid = getattr(obj, "source_id", 0)
                fid = getattr(obj, "file_id", 0)
                if sid > 0:
                    ids.add(sid)
                if fid > 0:
                    ids.add(fid)
            elif hasattr(obj, "sources") and obj.sources:
                for src in obj.sources:
                    sid = getattr(src, "source_id", 0)
                    fid = getattr(src, "file_id", 0)
                    if sid > 0:
                        ids.add(sid)
                    if fid > 0:
                        ids.add(fid)
    didx = getattr(bank, "didx", None)
    if didx is not None:
        for entry in getattr(didx, "entries", ()):
            fid = getattr(entry, "file_id", 0)
            if fid > 0:
                ids.add(fid)
    return ids


def _resolve_target_wem_id(sound: CAkSound) -> WemId:
    """Resolves an existing WEM ID or generates a valid positive 32-bit ID."""
    candidate = getattr(sound, "file_id", 0)
    if candidate > 1:
        return candidate
    # Generate deterministic positive 32-bit ID from sound ID
    gen_id = (sound.id ^ 0x5F3759DF) & 0x7FFFFFFF
    return gen_id if gen_id > 1 else 100001


def find_sound_in_bank(bank: Any, sound_id: int) -> CAkSound | None:
    """Finds a CAkSound in a SoundBank or bank-like structure."""
    if hasattr(bank, "get_sound"):
        sound = bank.get_sound(sound_id)
        if isinstance(sound, CAkSound):
            return sound
    hirc = getattr(bank, "hirc", None)
    if hirc is not None:
        for obj in getattr(hirc, "objects", ()):
            if getattr(obj, "id", None) == sound_id and isinstance(obj, CAkSound):
                return obj
    objects = getattr(bank, "objects", None)
    if isinstance(objects, dict):
        obj = objects.get(sound_id)
        if isinstance(obj, CAkSound):
            return obj
    if isinstance(bank, dict):
        obj = bank.get(sound_id)
        if isinstance(obj, CAkSound):
            return obj
    return None


def try_plan_audio_replacement(
    bank: Any,
    target: MutationTarget,
    source: AudioReplacementSource,
    *,
    scope: ReplacementScope = ReplacementScope.OVERWRITE,
    forked_wem_id: WemId | None = None,
    item: BatchItem | None = None,
    existing_wems: Collection[int] | None = None,
    external_file_exists: bool = True,
) -> AudioMutationPlan | PlanRejection:
    """
    Pure exception-free planner for audio replacement operations.
    Validates preconditions and produces an AudioMutationPlan or PlanRejection.
    Zero disk I/O and zero domain exceptions.
    """
    if item is not None:
        scope = item.scope
        if item.forked_wem_id is not None:
            forked_wem_id = item.forked_wem_id

    match target:
        case SoundNodeTarget():
            return _try_plan_sound_node_replacement(
                bank,
                target,
                source,
                scope=scope,
                forked_wem_id=forked_wem_id,
                item=item,
                existing_wems=existing_wems,
                external_file_exists=external_file_exists,
            )
        case MediaNodeTarget():
            return _try_plan_media_node_replacement(
                bank, target, source, external_file_exists=external_file_exists
            )
        case MusicTrackTarget() | ContainerVariationTarget():
            return PlanRejection(
                code="UNSUPPORTED_TARGET",
                reason=f"Planning not implemented for target type {type(target).__name__}",
            )
        case _ as unreachable:
            assert_never(unreachable)


def plan_batch(
    banks: Mapping[str, Any],
    batch: MutationBatch,
    *,
    external_files_exist: Mapping[Path, bool] | None = None,
) -> BatchPlan:
    """
    Pure exception-free planner for a batch of audio mutation operations.
    Performs deterministic encode-once file deduplication across targets and banks.
    Separates successful plans from rejections with zero disk I/O.
    """
    plans: list[AudioMutationPlan] = []
    rejections: list[tuple[BatchItem, PlanRejection]] = []
    seen_files: dict[Path, WemId] = {}

    for item in batch.items:
        bank = banks.get(item.target.bank_name)
        if bank is None:
            rejections.append(
                (
                    item,
                    PlanRejection(
                        code="BANK_NOT_LOADED",
                        reason=f"Bank {item.target.bank_name} not loaded",
                    ),
                )
            )
            continue

        effective_source = item.source
        canon_path: Path | None = None
        if isinstance(item.source, ExternalFileSource):
            canon_path = item.source.file_path.resolve()
            if canon_path in seen_files and item.forked_wem_id is None:
                effective_source = ExistingMediaReferenceSource(
                    wem_id=seen_files[canon_path],
                    source_bank=item.target.bank_name,
                )

        file_exists = True
        if isinstance(effective_source, ExternalFileSource):
            if external_files_exist is not None:
                if canon_path is None:
                    canon_path = effective_source.file_path.resolve()
                file_exists = external_files_exist.get(
                    effective_source.file_path,
                    external_files_exist.get(canon_path, True),
                )
            else:
                file_exists = effective_source.file_path.is_file()

        result = try_plan_audio_replacement(
            bank,
            item.target,
            effective_source,
            scope=item.scope,
            forked_wem_id=item.forked_wem_id,
            item=item,
            external_file_exists=file_exists,
        )
        if isinstance(result, PlanRejection):
            rejections.append((item, result))
        else:
            if isinstance(item.source, ExternalFileSource) and effective_source == item.source:
                if canon_path is None:
                    canon_path = item.source.file_path.resolve()
                for eff in result.effects:
                    if isinstance(eff, StageMasterAudioIntent):
                        seen_files[canon_path] = eff.wem_id
                        break
            plans.append(result)

    return BatchPlan(plans=tuple(plans), rejections=tuple(rejections))


def _try_plan_sound_node_replacement(
    bank: Any,
    target: SoundNodeTarget,
    source: AudioReplacementSource,
    *,
    scope: ReplacementScope = ReplacementScope.OVERWRITE,
    forked_wem_id: WemId | None = None,
    item: BatchItem | None = None,
    existing_wems: Collection[int] | None = None,
    external_file_exists: bool,
) -> AudioMutationPlan | PlanRejection:
    """Plans audio replacement for a CAkSound object supporting OVERWRITE and ISOLATE scopes."""
    if item is not None:
        scope = item.scope
        if item.forked_wem_id is not None:
            forked_wem_id = item.forked_wem_id

    sound = find_sound_in_bank(bank, target.sound_id)
    if sound is None:
        return PlanRejection(
            code="SOUND_NOT_FOUND",
            reason=f"Sound {target.sound_id} not found in bank {target.bank_name}",
        )

    plugin_id = getattr(sound, "plugin_id", 0)
    if (plugin_id & 0x0F) == 2 or (plugin_id >> 16) in (0x0065, 0x00C8):
        return PlanRejection(
            code="PROCEDURAL_SOUND",
            reason=f"Cannot replace procedural plugin sound {target.sound_id}",
        )

    match source:
        case ExternalFileSource():
            if not external_file_exists:
                return PlanRejection(
                    code="FILE_NOT_FOUND",
                    reason=f"External audio file not found: {source.file_path}",
                )

            dest_rel = f"source_audio/{source.file_path.name}"

            if scope == ReplacementScope.ISOLATE:
                if forked_wem_id is not None:
                    wem_id = forked_wem_id
                else:
                    existing_ids = _collect_bank_wem_ids(bank)
                    if existing_wems is not None:
                        existing_ids = existing_ids | set(existing_wems)
                    seed = _resolve_target_wem_id(sound)
                    wem_id = allocate_unique_wem_id(existing_ids, preferred_seed=seed)

                effects = (
                    StageMasterAudioIntent(
                        source_path=source.file_path,
                        destination_rel_path=dest_rel,
                        wem_id=wem_id,
                    ),
                    UpdateSoundNodeIntent(
                        bank_name=target.bank_name,
                        sound_id=target.sound_id,
                        new_stream_type=2,
                        new_source_id=wem_id,
                        new_file_id=wem_id,
                    ),
                    MarkBankModifiedIntent(bank_name=target.bank_name),
                )
                desc = (
                    f"Isolate and replace Sound {target.sound_id} with external file "
                    f"{source.file_path.name} (forked WEM {wem_id})"
                )
                return AudioMutationPlan(
                    description=desc,
                    target=target,
                    source=source,
                    effects=effects,
                )

            # scope == ReplacementScope.OVERWRITE
            wem_id = _resolve_target_wem_id(sound)
            effects_list: list[AudioMutationEffectIntent] = [
                StageMasterAudioIntent(
                    source_path=source.file_path,
                    destination_rel_path=dest_rel,
                    wem_id=wem_id,
                ),
                UpdateSoundNodeIntent(
                    bank_name=target.bank_name,
                    sound_id=target.sound_id,
                    new_stream_type=2,
                    new_source_id=wem_id,
                    new_file_id=wem_id,
                ),
            ]

            # Promote any other embedded sound nodes in this bank referencing the same WEM ID
            hirc = getattr(bank, "hirc", None)
            if hirc is not None:
                for obj in getattr(hirc, "objects", ()):
                    if isinstance(obj, CAkSound) and obj.id != target.sound_id:
                        wid = getattr(obj, "source_id", 0) or getattr(obj, "file_id", 0)
                        if wid == wem_id and getattr(obj, "stream_type", 2) != 2:
                            effects_list.append(
                                UpdateSoundNodeIntent(
                                    bank_name=target.bank_name,
                                    sound_id=obj.id,
                                    new_stream_type=2,
                                    new_source_id=wem_id,
                                    new_file_id=wem_id,
                                )
                            )

            effects_list.append(MarkBankModifiedIntent(bank_name=target.bank_name))
            desc = f"Replace Sound {target.sound_id} with external file {source.file_path.name} (WEM {wem_id})"
            return AudioMutationPlan(
                description=desc,
                target=target,
                source=source,
                effects=tuple(effects_list),
            )

        case ExistingMediaReferenceSource():
            effects = (
                UpdateSoundNodeIntent(
                    bank_name=target.bank_name,
                    sound_id=target.sound_id,
                    new_stream_type=2,
                    new_source_id=source.wem_id,
                    new_file_id=source.wem_id,
                ),
                MarkBankModifiedIntent(bank_name=target.bank_name),
            )
            desc = f"Retarget Sound {target.sound_id} to existing media {source.wem_id}"
            return AudioMutationPlan(
                description=desc,
                target=target,
                source=source,
                effects=effects,
            )

        case SilentStubSource():
            effects = (
                UpdateSoundNodeIntent(
                    bank_name=target.bank_name,
                    sound_id=target.sound_id,
                    new_stream_type=2,
                    new_source_id=source.stub_wem_id,
                    new_file_id=source.stub_wem_id,
                ),
                MarkBankModifiedIntent(bank_name=target.bank_name),
            )
            desc = f"Mute Sound {target.sound_id} with silent stub {source.stub_wem_id}"
            return AudioMutationPlan(
                description=desc,
                target=target,
                source=source,
                effects=effects,
            )

        case CrossBankCloneSource():
            return PlanRejection(
                code="UNSUPPORTED_SOURCE",
                reason="Unsupported source type CrossBankCloneSource for CAkSound",
            )

        case _ as unreachable:
            assert_never(unreachable)


def _try_plan_media_node_replacement(
    bank: Any,
    target: MediaNodeTarget,
    source: AudioReplacementSource,
    *,
    external_file_exists: bool,
) -> AudioMutationPlan | PlanRejection:
    """Plans audio replacement or muting for an embedded or loose media node."""
    match source:
        case ExternalFileSource():
            if not external_file_exists:
                return PlanRejection(
                    code="FILE_NOT_FOUND",
                    reason=f"External audio file not found: {source.file_path}",
                )

            dest_rel = f"source_audio/{source.file_path.name}"
            effects = (
                StageMasterAudioIntent(
                    source_path=source.file_path,
                    destination_rel_path=dest_rel,
                    wem_id=target.wem_id,
                ),
            )
            desc = f"Replace Media WEM {target.wem_id} with external file {source.file_path.name}"
            return AudioMutationPlan(
                description=desc,
                target=target,
                source=source,
                effects=effects,
            )

        case SilentStubSource():
            effects = (
                StageLooseWemIntent(
                    wem_id=target.wem_id,
                    wem_bytes=build_silent_pcm_wem_bytes(duration_ms=50, sample_rate=32000),
                ),
            )
            desc = f"Mute Media WEM {target.wem_id} with silent stub"
            return AudioMutationPlan(
                description=desc,
                target=target,
                source=source,
                effects=effects,
            )

        case ExistingMediaReferenceSource():
            effects = (
                CopyMediaBytesIntent(
                    target_wem_id=target.wem_id,
                    source_wem_id=source.wem_id,
                    source_bank_name=source.source_bank,
                ),
            )
            desc = f"Replace Media WEM {target.wem_id} with library media {source.wem_id}"
            return AudioMutationPlan(
                description=desc,
                target=target,
                source=source,
                effects=effects,
            )

        case CrossBankCloneSource():
            return PlanRejection(
                code="UNSUPPORTED_SOURCE",
                reason="Unsupported source type CrossBankCloneSource for MediaNodeTarget",
            )

        case _ as unreachable:
            assert_never(unreachable)


def plan_audio_replacement(
    bank: Any,
    target: MutationTarget,
    source: AudioReplacementSource,
    *,
    scope: ReplacementScope = ReplacementScope.OVERWRITE,
    forked_wem_id: WemId | None = None,
    existing_wems: Collection[int] | None = None,
) -> AudioMutationPlan:
    """
    Plans an audio replacement operation across a target node and replacement source.
    Validates preconditions and produces an immutable AudioMutationPlan.

    Raises:
        KeyError: If target node does not exist in bank.
        ValueError: If target node cannot accept audio replacement (e.g. procedural plugin).
        FileNotFoundError: If external audio file does not exist on disk.
        NotImplementedError: For unsupported target/source combinations.
    """
    ext_exists = source.file_path.is_file() if isinstance(source, ExternalFileSource) else True
    result = try_plan_audio_replacement(
        bank,
        target,
        source,
        scope=scope,
        forked_wem_id=forked_wem_id,
        existing_wems=existing_wems,
        external_file_exists=ext_exists,
    )
    if isinstance(result, PlanRejection):
        if result.code == "FILE_NOT_FOUND":
            raise FileNotFoundError(result.reason)
        if result.code == "SOUND_NOT_FOUND":
            raise KeyError(result.reason)
        if result.code == "PROCEDURAL_SOUND":
            raise ValueError(result.reason)
        if result.code in ("UNSUPPORTED_TARGET", "UNSUPPORTED_SOURCE"):
            raise NotImplementedError(result.reason)
        raise ValueError(result.reason)
    return result
