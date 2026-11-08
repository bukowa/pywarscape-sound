"""
Pure deterministic mutation planner (Functional Core).
Calculates and validates atomic AudioMutationPlans without performing disk I/O.
"""

from __future__ import annotations

from collections.abc import Collection, Container, Mapping
from pathlib import Path
from typing import Any, assert_never

from src.bnk.models import CAkMusicSegment, CAkMusicTrack, CAkRanSeqCntr, CAkSound
from src.bnk.wem import build_silent_pcm_wem_bytes
from src.engine.ontology import (
    AppendVariationIntent,
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
    NodeParamsSource,
    PlanRejection,
    ReplacementScope,
    SilentStubSource,
    SoundNodeTarget,
    StageLooseWemIntent,
    StageMasterAudioIntent,
    SyncMusicTimelineIntent,
    UpdateMusicTrackNodeIntent,
    UpdateNodeParamsIntent,
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


def collect_bank_wem_ids(bank: Any) -> set[int]:
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


def find_music_track_in_bank(bank: Any, track_id: int) -> CAkMusicTrack | None:
    """Finds a CAkMusicTrack in a SoundBank or bank-like structure."""
    if hasattr(bank, "get_music_track"):
        track = bank.get_music_track(track_id)
        if isinstance(track, CAkMusicTrack):
            return track
    hirc = getattr(bank, "hirc", None)
    if hirc is not None:
        for obj in getattr(hirc, "objects", ()):
            if getattr(obj, "id", None) == track_id and isinstance(obj, CAkMusicTrack):
                return obj
    objects = getattr(bank, "objects", None)
    if isinstance(objects, dict):
        obj = objects.get(track_id)
        if isinstance(obj, CAkMusicTrack):
            return obj
    if isinstance(bank, dict):
        obj = bank.get(track_id)
        if isinstance(obj, CAkMusicTrack):
            return obj
    return None


def find_parent_segment_in_bank(
    bank: Any, track_id: int, hint_segment_id: int | None = None
) -> CAkMusicSegment | None:
    """Finds the parent CAkMusicSegment for a given music track ID in a SoundBank."""
    hirc = getattr(bank, "hirc", None)
    if hirc is None:
        objects: list[Any] = []
        if isinstance(getattr(bank, "objects", None), dict):
            objects = list(bank.objects.values())
        elif isinstance(bank, dict):
            objects = list(bank.values())
    else:
        objects = getattr(hirc, "objects", ())

    if hint_segment_id is not None:
        for obj in objects:
            if getattr(obj, "id", None) == hint_segment_id and isinstance(obj, CAkMusicSegment):
                if not obj.child_ids or track_id in obj.child_ids:
                    return obj

    for obj in objects:
        if isinstance(obj, CAkMusicSegment) and track_id in getattr(obj, "child_ids", ()):
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
    reserved_wem_ids: set[int] | frozenset[int] | None = None,
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
                reserved_wem_ids=reserved_wem_ids,
                external_file_exists=external_file_exists,
            )
        case MusicTrackTarget():
            return _try_plan_music_track_replacement(
                bank,
                target,
                source,
                scope=scope,
                forked_wem_id=forked_wem_id,
                item=item,
                existing_wems=existing_wems,
                reserved_wem_ids=reserved_wem_ids,
                external_file_exists=external_file_exists,
            )
        case MediaNodeTarget():
            return _try_plan_media_node_replacement(
                bank, target, source, external_file_exists=external_file_exists
            )
        case ContainerVariationTarget():
            return _try_plan_container_variation(
                bank,
                target,
                source,
                scope=scope,
                forked_wem_id=forked_wem_id,
                item=item,
                existing_wems=existing_wems,
                reserved_wem_ids=reserved_wem_ids,
                external_file_exists=external_file_exists,
            )
        case _ as unreachable:
            assert_never(unreachable)


def plan_batch(
    banks: Mapping[str, Any],
    batch: MutationBatch,
    *,
    external_files_exist: Mapping[Path, bool] | None = None,
    reserved_wem_ids: set[int] | frozenset[int] | None = None,
) -> BatchPlan:
    """
    Pure exception-free planner for a batch of audio mutation operations.
    Performs deterministic encode-once file deduplication across targets and banks.
    Separates successful plans from rejections with zero disk I/O.
    """
    plans: list[AudioMutationPlan] = []
    rejections: list[tuple[BatchItem, PlanRejection]] = []
    seen_files: dict[Path, WemId] = {}
    working_reserved: set[int] = set(reserved_wem_ids) if reserved_wem_ids else set()

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
            reserved_wem_ids=working_reserved,
            external_file_exists=file_exists,
        )
        if isinstance(result, PlanRejection):
            rejections.append((item, result))
        else:
            for eff in result.effects:
                if isinstance(eff, (StageMasterAudioIntent, StageLooseWemIntent)):
                    working_reserved.add(eff.wem_id)
                elif isinstance(eff, (UpdateSoundNodeIntent, UpdateMusicTrackNodeIntent)):
                    working_reserved.add(eff.new_source_id)
                elif isinstance(eff, AppendVariationIntent):
                    working_reserved.add(eff.child_sound_id)
                    if eff.wem_id:
                        working_reserved.add(eff.wem_id)
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
    reserved_wem_ids: set[int] | frozenset[int] | None = None,
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
                    existing_ids = collect_bank_wem_ids(bank)
                    if existing_wems is not None:
                        existing_ids = existing_ids | set(existing_wems)
                    if reserved_wem_ids is not None:
                        existing_ids = existing_ids | set(reserved_wem_ids)
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
                        new_plugin_id=0x00010001,
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
            ]

            # Whenever sound is not streamed (stream_type != 2) OR plugin_id is not PCM (0x00010001),
            # emit UpdateSoundNodeIntent to promote/update to streamed PCM
            if (
                getattr(sound, "stream_type", 2) != 2
                or getattr(sound, "plugin_id", 0x00040001) != 0x00010001
            ):
                effects_list.append(
                    UpdateSoundNodeIntent(
                        bank_name=target.bank_name,
                        sound_id=target.sound_id,
                        new_stream_type=2,
                        new_source_id=wem_id,
                        new_file_id=wem_id,
                        new_plugin_id=0x00010001,
                    )
                )

            # Promote or update any other sound nodes in this bank referencing the same WEM ID
            hirc = getattr(bank, "hirc", None)
            if hirc is not None:
                for obj in getattr(hirc, "objects", ()):
                    if isinstance(obj, CAkSound) and obj.id != target.sound_id:
                        wid = getattr(obj, "source_id", 0) or getattr(obj, "file_id", 0)
                        if wid == wem_id and (
                            getattr(obj, "stream_type", 2) != 2
                            or getattr(obj, "plugin_id", 0x00040001) != 0x00010001
                        ):
                            effects_list.append(
                                UpdateSoundNodeIntent(
                                    bank_name=target.bank_name,
                                    sound_id=obj.id,
                                    new_stream_type=2,
                                    new_source_id=wem_id,
                                    new_file_id=wem_id,
                                    new_plugin_id=0x00010001,
                                )
                            )

            if any(isinstance(e, UpdateSoundNodeIntent) for e in effects_list):
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
                    new_plugin_id=0x00010001,
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
                    new_plugin_id=0x00010001,
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

        case NodeParamsSource():
            effects = (
                UpdateNodeParamsIntent(
                    bank_name=target.bank_name,
                    node_id=target.sound_id,
                    volume_db=source.volume_db,
                    pitch_cents=source.pitch_cents,
                ),
                MarkBankModifiedIntent(bank_name=target.bank_name),
            )
            desc = (
                f"Update node params for Sound {target.sound_id} "
                f"(volume: {source.volume_db} dB, pitch: {source.pitch_cents} cents)"
            )
            return AudioMutationPlan(
                description=desc,
                target=target,
                source=source,
                effects=effects,
            )

        case _ as unreachable:
            assert_never(unreachable)


def _try_plan_music_track_replacement(
    bank: Any,
    target: MusicTrackTarget,
    source: AudioReplacementSource,
    *,
    scope: ReplacementScope = ReplacementScope.OVERWRITE,
    forked_wem_id: WemId | None = None,
    item: BatchItem | None = None,
    existing_wems: Collection[int] | None = None,
    reserved_wem_ids: set[int] | frozenset[int] | None = None,
    external_file_exists: bool,
) -> AudioMutationPlan | PlanRejection:
    """Plans audio replacement for a CAkMusicTrack object supporting OVERWRITE and ISOLATE scopes."""
    if item is not None:
        scope = item.scope
        if item.forked_wem_id is not None:
            forked_wem_id = item.forked_wem_id

    track = find_music_track_in_bank(bank, target.track_id)
    if track is None:
        return PlanRejection(
            code="TARGET_NOT_FOUND",
            reason=f"MusicTrack {target.track_id} not found in {target.bank_name}",
        )

    if not track.sources or not (0 <= target.source_index < len(track.sources)):
        return PlanRejection(
            code="SOURCE_NOT_FOUND",
            reason=f"MusicTrack {target.track_id} has no source at index {target.source_index}",
        )

    src_desc = track.sources[target.source_index]
    target_wem_id = getattr(src_desc, "source_id", 0) or getattr(src_desc, "file_id", 0)
    parent_seg = find_parent_segment_in_bank(bank, track.id, target.parent_segment_id)
    parent_seg_id = parent_seg.id if parent_seg is not None else target.parent_segment_id

    match source:
        case CrossBankCloneSource():
            return PlanRejection(
                code="UNSUPPORTED_SOURCE",
                reason="Unsupported source type CrossBankCloneSource for CAkMusicTrack",
            )

        case ExternalFileSource():
            if not external_file_exists:
                return PlanRejection(
                    code="FILE_NOT_FOUND",
                    reason=f"External audio file not found: {source.file_path}",
                )

            dest_rel = f"source_audio/{source.file_path.name}"

            if scope == ReplacementScope.ISOLATE:
                if forked_wem_id is not None:
                    final_wem_id = forked_wem_id
                else:
                    existing_ids = collect_bank_wem_ids(bank)
                    if existing_wems is not None:
                        existing_ids = existing_ids | set(existing_wems)
                    if reserved_wem_ids is not None:
                        existing_ids = existing_ids | set(reserved_wem_ids)
                    final_wem_id = allocate_unique_wem_id(
                        existing_ids, preferred_seed=target_wem_id
                    )

                effects = (
                    StageMasterAudioIntent(
                        source_path=source.file_path,
                        destination_rel_path=dest_rel,
                        wem_id=final_wem_id,
                    ),
                    UpdateMusicTrackNodeIntent(
                        bank_name=target.bank_name,
                        track_id=track.id,
                        source_index=target.source_index,
                        new_stream_type=2,
                        new_source_id=final_wem_id,
                        new_file_id=final_wem_id,
                        new_plugin_id=0x00010001,
                    ),
                    SyncMusicTimelineIntent(
                        bank_name=target.bank_name,
                        track_id=track.id,
                        new_duration_ms=0.0,
                        source_index=target.source_index,
                        parent_segment_id=parent_seg_id,
                    ),
                    MarkBankModifiedIntent(bank_name=target.bank_name),
                )
                desc = (
                    f"Isolate and replace MusicTrack {target.track_id} source {target.source_index} with external file "
                    f"{source.file_path.name} (forked WEM {final_wem_id})"
                )
                return AudioMutationPlan(
                    description=desc,
                    target=target,
                    source=source,
                    effects=effects,
                )

            # scope == ReplacementScope.OVERWRITE
            final_wem_id = target_wem_id
            effects_list: list[AudioMutationEffectIntent] = [
                StageMasterAudioIntent(
                    source_path=source.file_path,
                    destination_rel_path=dest_rel,
                    wem_id=final_wem_id,
                ),
                UpdateMusicTrackNodeIntent(
                    bank_name=target.bank_name,
                    track_id=track.id,
                    source_index=target.source_index,
                    new_stream_type=2,
                    new_source_id=final_wem_id,
                    new_file_id=final_wem_id,
                    new_plugin_id=0x00010001,
                ),
                SyncMusicTimelineIntent(
                    bank_name=target.bank_name,
                    track_id=track.id,
                    new_duration_ms=0.0,
                    source_index=target.source_index,
                    parent_segment_id=parent_seg_id,
                ),
            ]

            # Update any other music track source or sound node in this bank sharing target_wem_id
            hirc = getattr(bank, "hirc", None)
            if hirc is not None:
                for obj in getattr(hirc, "objects", ()):
                    if isinstance(obj, CAkMusicTrack):
                        for s_idx, s in enumerate(obj.sources):
                            if obj.id == track.id and s_idx == target.source_index:
                                continue
                            s_wid = getattr(s, "source_id", 0) or getattr(s, "file_id", 0)
                            if s_wid == target_wem_id:
                                effects_list.append(
                                    UpdateMusicTrackNodeIntent(
                                        bank_name=target.bank_name,
                                        track_id=obj.id,
                                        source_index=s_idx,
                                        new_stream_type=2,
                                        new_source_id=final_wem_id,
                                        new_file_id=final_wem_id,
                                        new_plugin_id=0x00010001,
                                    )
                                )
                                other_seg = find_parent_segment_in_bank(bank, obj.id)
                                effects_list.append(
                                    SyncMusicTimelineIntent(
                                        bank_name=target.bank_name,
                                        track_id=obj.id,
                                        new_duration_ms=0.0,
                                        source_index=s_idx,
                                        parent_segment_id=other_seg.id if other_seg else None,
                                    )
                                )
                    elif isinstance(obj, CAkSound):
                        s_wid = getattr(obj, "source_id", 0) or getattr(obj, "file_id", 0)
                        if s_wid == target_wem_id:
                            effects_list.append(
                                UpdateSoundNodeIntent(
                                    bank_name=target.bank_name,
                                    sound_id=obj.id,
                                    new_stream_type=2,
                                    new_source_id=final_wem_id,
                                    new_file_id=final_wem_id,
                                    new_plugin_id=0x00010001,
                                )
                            )

            effects_list.append(MarkBankModifiedIntent(bank_name=target.bank_name))
            desc = (
                f"Replace MusicTrack {target.track_id} source {target.source_index} with external file "
                f"{source.file_path.name} (WEM {final_wem_id})"
            )
            return AudioMutationPlan(
                description=desc,
                target=target,
                source=source,
                effects=tuple(effects_list),
            )

        case SilentStubSource():
            final_wem_id = source.stub_wem_id
            effects = (
                StageLooseWemIntent(
                    wem_id=final_wem_id,
                    wem_bytes=build_silent_pcm_wem_bytes(duration_ms=50, sample_rate=32000),
                ),
                UpdateMusicTrackNodeIntent(
                    bank_name=target.bank_name,
                    track_id=track.id,
                    source_index=target.source_index,
                    new_stream_type=2,
                    new_source_id=final_wem_id,
                    new_file_id=final_wem_id,
                    new_plugin_id=0x00010001,
                ),
                SyncMusicTimelineIntent(
                    bank_name=target.bank_name,
                    track_id=track.id,
                    new_duration_ms=50.0,
                    source_index=target.source_index,
                    parent_segment_id=parent_seg_id,
                ),
                MarkBankModifiedIntent(bank_name=target.bank_name),
            )
            desc = f"Mute MusicTrack {target.track_id} source {target.source_index} with silent stub {final_wem_id}"
            return AudioMutationPlan(
                description=desc,
                target=target,
                source=source,
                effects=effects,
            )

        case ExistingMediaReferenceSource():
            if scope == ReplacementScope.ISOLATE:
                if forked_wem_id is not None:
                    final_wem_id = forked_wem_id
                else:
                    existing_ids = collect_bank_wem_ids(bank)
                    if existing_wems is not None:
                        existing_ids = existing_ids | set(existing_wems)
                    if reserved_wem_ids is not None:
                        existing_ids = existing_ids | set(reserved_wem_ids)
                    final_wem_id = allocate_unique_wem_id(
                        existing_ids, preferred_seed=target_wem_id
                    )
                effects_tuple = (
                    CopyMediaBytesIntent(source_wem_id=source.wem_id, target_wem_id=final_wem_id),
                    UpdateMusicTrackNodeIntent(
                        bank_name=target.bank_name,
                        track_id=track.id,
                        source_index=target.source_index,
                        new_stream_type=2,
                        new_source_id=final_wem_id,
                        new_file_id=final_wem_id,
                        new_plugin_id=0x00010001,
                    ),
                    SyncMusicTimelineIntent(
                        bank_name=target.bank_name,
                        track_id=track.id,
                        new_duration_ms=0.0,
                        source_index=target.source_index,
                        parent_segment_id=parent_seg_id,
                    ),
                    MarkBankModifiedIntent(bank_name=target.bank_name),
                )
            else:
                final_wem_id = source.wem_id
                effects_tuple = (
                    UpdateMusicTrackNodeIntent(
                        bank_name=target.bank_name,
                        track_id=track.id,
                        source_index=target.source_index,
                        new_stream_type=2,
                        new_source_id=final_wem_id,
                        new_file_id=final_wem_id,
                        new_plugin_id=0x00010001,
                    ),
                    SyncMusicTimelineIntent(
                        bank_name=target.bank_name,
                        track_id=track.id,
                        new_duration_ms=0.0,
                        source_index=target.source_index,
                        parent_segment_id=parent_seg_id,
                    ),
                    MarkBankModifiedIntent(bank_name=target.bank_name),
                )
            desc = f"Retarget MusicTrack {target.track_id} source {target.source_index} to existing media {source.wem_id}"
            return AudioMutationPlan(
                description=desc,
                target=target,
                source=source,
                effects=effects_tuple,
            )

        case CrossBankCloneSource():
            return PlanRejection(
                code="UNSUPPORTED_SOURCE",
                reason="Unsupported source type CrossBankCloneSource for CAkMusicTrack",
            )

        case NodeParamsSource():
            effects = (
                UpdateNodeParamsIntent(
                    bank_name=target.bank_name,
                    node_id=track.id,
                    volume_db=source.volume_db,
                    pitch_cents=source.pitch_cents,
                ),
                MarkBankModifiedIntent(bank_name=target.bank_name),
            )
            desc = (
                f"Update node params for MusicTrack {target.track_id} "
                f"(volume: {source.volume_db} dB, pitch: {source.pitch_cents} cents)"
            )
            return AudioMutationPlan(
                description=desc,
                target=target,
                source=source,
                effects=effects,
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

        case NodeParamsSource():
            return PlanRejection(
                code="UNSUPPORTED_SOURCE",
                reason="NodeParamsSource not supported for MediaNodeTarget",
            )

        case _ as unreachable:
            assert_never(unreachable)


def _try_plan_container_variation(
    bank: Any,
    target: ContainerVariationTarget,
    source: AudioReplacementSource,
    *,
    scope: ReplacementScope = ReplacementScope.OVERWRITE,
    forked_wem_id: WemId | None = None,
    item: BatchItem | None = None,
    existing_wems: Collection[int] | None = None,
    reserved_wem_ids: set[int] | frozenset[int] | None = None,
    external_file_exists: bool,
) -> AudioMutationPlan | PlanRejection:
    """Plans audio variation appending or node parameter override for a container."""
    if item is not None:
        scope = item.scope
        if item.forked_wem_id is not None:
            forked_wem_id = item.forked_wem_id

    if target.variation_sound_id is not None:
        return _try_plan_sound_node_replacement(
            bank,
            SoundNodeTarget(bank_name=target.bank_name, sound_id=target.variation_sound_id),
            source,
            scope=scope,
            forked_wem_id=forked_wem_id,
            item=item,
            existing_wems=existing_wems,
            reserved_wem_ids=reserved_wem_ids,
            external_file_exists=external_file_exists,
        )

    if isinstance(source, NodeParamsSource):
        effects = (
            UpdateNodeParamsIntent(
                bank_name=target.bank_name,
                node_id=target.container_id,
                volume_db=source.volume_db,
                pitch_cents=source.pitch_cents,
            ),
            MarkBankModifiedIntent(bank_name=target.bank_name),
        )
        desc = (
            f"Update node params for Container {target.container_id} "
            f"(volume: {source.volume_db} dB, pitch: {source.pitch_cents} cents)"
        )
        return AudioMutationPlan(
            description=desc,
            target=target,
            source=source,
            effects=effects,
        )

    cntr = None
    hirc = getattr(bank, "hirc", None)
    if hirc is not None:
        for o in getattr(hirc, "objects", ()):
            if getattr(o, "id", None) == target.container_id:
                cntr = o
                break
    if cntr is None and hasattr(bank, "objects") and isinstance(bank.objects, dict):
        cntr = bank.objects.get(target.container_id)
    if cntr is None and isinstance(bank, dict):
        cntr = bank.get(target.container_id)

    if cntr is None or not isinstance(cntr, CAkRanSeqCntr):
        return PlanRejection(
            code="CONTAINER_NOT_FOUND",
            reason=f"RanSeqCntr {target.container_id} not found in bank {target.bank_name}",
        )

    existing_ids = collect_bank_wem_ids(bank)
    if existing_wems is not None:
        existing_ids = existing_ids | set(existing_wems)
    if reserved_wem_ids is not None:
        existing_ids = existing_ids | set(reserved_wem_ids)

    hirc_ids: set[int] = set()
    if hirc is not None:
        for o in getattr(hirc, "objects", ()):
            oid = getattr(o, "id", None)
            if oid is not None:
                hirc_ids.add(oid)
    elif hasattr(bank, "objects") and isinstance(bank.objects, dict):
        hirc_ids.update(bank.objects.keys())
    elif isinstance(bank, dict):
        hirc_ids.update(bank.keys())

    all_used_ids = existing_ids | hirc_ids
    pref_seed = target.container_id + len(getattr(cntr, "children", ())) + 1
    child_sound_id = allocate_unique_wem_id(all_used_ids, preferred_seed=pref_seed)

    match source:
        case ExternalFileSource():
            if not external_file_exists:
                return PlanRejection(
                    code="FILE_NOT_FOUND",
                    reason=f"External audio file not found: {source.file_path}",
                )

            dest_rel = f"source_audio/{source.file_path.name}"
            if forked_wem_id is not None:
                wem_id = forked_wem_id
            else:
                wem_seed = child_sound_id + 1
                wem_id = allocate_unique_wem_id(
                    all_used_ids | {child_sound_id}, preferred_seed=wem_seed
                )

            effects = (
                StageMasterAudioIntent(
                    source_path=source.file_path,
                    destination_rel_path=dest_rel,
                    wem_id=wem_id,
                ),
                AppendVariationIntent(
                    bank_name=target.bank_name,
                    container_id=target.container_id,
                    child_sound_id=child_sound_id,
                    wem_id=wem_id,
                    plugin_id=0x00010001,
                ),
                MarkBankModifiedIntent(bank_name=target.bank_name),
            )
            desc = (
                f"Append new variation Sound {child_sound_id} (WEM {wem_id}) from "
                f"{source.file_path.name} to Container {target.container_id}"
            )
            return AudioMutationPlan(
                description=desc,
                target=target,
                source=source,
                effects=effects,
            )

        case ExistingMediaReferenceSource():
            effects = (
                AppendVariationIntent(
                    bank_name=target.bank_name,
                    container_id=target.container_id,
                    child_sound_id=child_sound_id,
                    wem_id=source.wem_id,
                    plugin_id=0x00010001,
                ),
                MarkBankModifiedIntent(bank_name=target.bank_name),
            )
            desc = (
                f"Append new variation Sound {child_sound_id} referencing WEM {source.wem_id} "
                f"to Container {target.container_id}"
            )
            return AudioMutationPlan(
                description=desc,
                target=target,
                source=source,
                effects=effects,
            )

        case SilentStubSource():
            effects = (
                AppendVariationIntent(
                    bank_name=target.bank_name,
                    container_id=target.container_id,
                    child_sound_id=child_sound_id,
                    wem_id=source.stub_wem_id,
                    plugin_id=0x00010001,
                ),
                MarkBankModifiedIntent(bank_name=target.bank_name),
            )
            desc = (
                f"Append silent variation Sound {child_sound_id} (WEM {source.stub_wem_id}) "
                f"to Container {target.container_id}"
            )
            return AudioMutationPlan(
                description=desc,
                target=target,
                source=source,
                effects=effects,
            )

        case CrossBankCloneSource():
            return PlanRejection(
                code="UNSUPPORTED_SOURCE",
                reason="Unsupported source type CrossBankCloneSource for ContainerVariationTarget",
            )

        case NodeParamsSource():
            return PlanRejection(
                code="UNEXPECTED_SOURCE",
                reason="NodeParamsSource unexpectedly reached variation branch",
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
    reserved_wem_ids: set[int] | frozenset[int] | None = None,
) -> AudioMutationPlan:
    """
    Plans an audio replacement operation across a target node and replacement source.
    Validates preconditions and produces an immutable AudioMutationPlan.

    Raises:
        KeyError: If target node does not exist in bank.
        IndexError: If target source index is out of bounds.
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
        reserved_wem_ids=reserved_wem_ids,
        external_file_exists=ext_exists,
    )
    if isinstance(result, PlanRejection):
        if result.code == "FILE_NOT_FOUND":
            raise FileNotFoundError(result.reason)
        if result.code in ("SOUND_NOT_FOUND", "TARGET_NOT_FOUND"):
            raise KeyError(result.reason)
        if result.code == "SOURCE_NOT_FOUND":
            raise IndexError(result.reason)
        if result.code == "PROCEDURAL_SOUND":
            raise ValueError(result.reason)
        if result.code in ("UNSUPPORTED_TARGET", "UNSUPPORTED_SOURCE"):
            raise NotImplementedError(result.reason)
        raise ValueError(result.reason)
    return result
