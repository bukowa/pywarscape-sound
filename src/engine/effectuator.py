"""
Imperative Shell for applying AudioMutationPlans to AudioProject and SoundBanks.
Dispatches effect intents to disk I/O, audio conversion, and AST mutations.
"""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass
from typing import Any, assert_never

from src.bnk.models import AkPlaylistItem, CAkRanSeqCntr, CAkSound, NodeBaseParams
from src.bnk.wem import WemFormatTag, build_silent_pcm_wem_bytes, parse_wem_header
from src.compiler.converter import AudioConverter
from src.engine.ontology import (
    AppendVariationIntent,
    AudioMutationPlan,
    CopyMediaBytesIntent,
    ExternalFileSource,
    MarkBankModifiedIntent,
    StageLooseWemIntent,
    StageMasterAudioIntent,
    SyncMusicTimelineIntent,
    UpdateMusicTrackNodeIntent,
    UpdateNodeParamsIntent,
    UpdateSoundNodeIntent,
)
from src.engine.planner import (
    find_music_track_in_bank,
    find_parent_segment_in_bank,
    find_sound_in_bank,
)
from src.engine.ports import AudioProjectPort

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class ExecutionResult:
    """Result of executing an AudioMutationPlan."""

    success: bool
    description: str
    errors: tuple[str, ...] = ()


def execute_mutation_plan(
    plan: AudioMutationPlan,
    project: AudioProjectPort,
    bank: Any,
    resolver: Any | None = None,
    persist: bool = True,
) -> ExecutionResult:
    """
    Executes an AudioMutationPlan against an AudioProject workspace and SoundBank.
    Processes file staging, audio conversion, HIRC AST mutations, and manifest updates.
    """
    errors: list[str] = []
    staged_durations_ms: dict[int, float] = {}
    staged_plugin_ids: dict[int, int] = {}

    try:
        for intent in plan.effects:
            match intent:
                case StageMasterAudioIntent():
                    # 1. Stage master uncompressed audio in source_audio/
                    project.stage_source_audio(src_path=intent.source_path, wem_id=intent.wem_id)

                    # 2. Convert audio to Vorbis/PCM WEM and stage in pack_root/audio/
                    target_rate = (
                        plan.source.target_sample_rate
                        if isinstance(plan.source, ExternalFileSource)
                        else None
                    )
                    target_ch = (
                        plan.source.target_channels
                        if isinstance(plan.source, ExternalFileSource)
                        else None
                    )

                    wem_bytes, dur = AudioConverter.convert_to_wem_bytes(
                        input_source=intent.source_path,
                        sample_rate=target_rate,
                        channels=target_ch,
                    )
                    project.stage_wem(wem_id=intent.wem_id, data=wem_bytes)
                    staged_durations_ms[intent.wem_id] = dur
                    try:
                        hdr = parse_wem_header(wem_bytes)
                        pl_id = 0x00040001 if hdr.format_tag == WemFormatTag.VORBIS else 0x00010001
                    except Exception:
                        pl_id = 0x00010001
                    staged_plugin_ids[intent.wem_id] = pl_id

                case StageLooseWemIntent():
                    project.stage_wem(wem_id=intent.wem_id, data=intent.wem_bytes)
                    dur = 50.0
                    pl_id = 0x00010001
                    try:
                        hdr = parse_wem_header(intent.wem_bytes)
                        dur = (
                            float(hdr.duration_ms)
                            if hdr.duration_ms > 0
                            else (
                                (hdr.data_size / hdr.avg_bytes_per_sec * 1000.0)
                                if hdr.avg_bytes_per_sec > 0
                                else 50.0
                            )
                        )
                        pl_id = 0x00040001 if hdr.format_tag == WemFormatTag.VORBIS else 0x00010001
                    except Exception:
                        logger.debug(
                            "Failed to extract WEM header metadata for staged WEM %s",
                            intent.wem_id,
                            exc_info=True,
                        )
                    staged_durations_ms[intent.wem_id] = dur
                    staged_plugin_ids[intent.wem_id] = pl_id

                case UpdateSoundNodeIntent():
                    sound = find_sound_in_bank(bank, intent.sound_id)
                    if isinstance(sound, CAkSound):
                        sound.stream_type = intent.new_stream_type
                        sound.source_id = intent.new_source_id
                        sound.file_id = intent.new_file_id
                        sound.file_offset = 0
                        sound.in_memory_media_size = 0
                        sound.plugin_id = staged_plugin_ids.get(
                            intent.new_source_id, intent.new_plugin_id
                        )

                    # Ensure silent 1.wem stub exists on disk if muting
                    if intent.new_source_id == 1:
                        silent_path = project.audio_dir / "1.wem"
                        if not silent_path.is_file() or 1 not in project.manifest.staged_wems:
                            silent_bytes = build_silent_pcm_wem_bytes(
                                duration_ms=50, sample_rate=32000
                            )
                            project.stage_wem(1, silent_bytes)

                case UpdateMusicTrackNodeIntent():
                    track = find_music_track_in_bank(bank, intent.track_id)
                    if track is not None and 0 <= intent.source_index < len(track.sources):
                        src = track.sources[intent.source_index]
                        old_source_id = src.source_id
                        src.plugin_id = staged_plugin_ids.get(
                            intent.new_source_id, intent.new_plugin_id
                        )
                        src.stream_type = intent.new_stream_type
                        src.source_id = intent.new_source_id
                        src.file_id = intent.new_file_id
                        src.file_offset = None if intent.new_stream_type == 2 else 0
                        src.in_memory_media_size = 0

                        # Update track.playlist clips
                        if len(track.sources) == 1:
                            for clip in track.playlist:
                                clip.source_id = intent.new_source_id
                        else:
                            if (
                                intent.source_index < len(track.playlist)
                                and track.playlist[intent.source_index].source_id == old_source_id
                            ):
                                track.playlist[intent.source_index].source_id = intent.new_source_id
                            else:
                                for clip in track.playlist:
                                    if clip.source_id == old_source_id:
                                        clip.source_id = intent.new_source_id
                    else:
                        errors.append(
                            f"MusicTrack {intent.track_id} source {intent.source_index} not found in bank"
                        )

                case CopyMediaBytesIntent():
                    raw_bytes = None
                    if resolver is not None and hasattr(resolver, "resolve_wem_bytes"):
                        raw_bytes = resolver.resolve_wem_bytes(intent.source_wem_id)
                    if raw_bytes is None and hasattr(bank, "get_media_data"):
                        raw_bytes = bank.get_media_data(intent.source_wem_id)
                    if raw_bytes is not None:
                        project.stage_wem(wem_id=intent.target_wem_id, data=raw_bytes)
                        dur = 0.0
                        pl_id = 0x00010001
                        try:
                            hdr = parse_wem_header(raw_bytes)
                            dur = (
                                float(hdr.duration_ms)
                                if hdr.duration_ms > 0
                                else (
                                    (hdr.data_size / hdr.avg_bytes_per_sec * 1000.0)
                                    if hdr.avg_bytes_per_sec > 0
                                    else 0.0
                                )
                            )
                            pl_id = (
                                0x00040001 if hdr.format_tag == WemFormatTag.VORBIS else 0x00010001
                            )
                        except Exception:
                            logger.debug(
                                "Failed to extract WEM header metadata for copied WEM %s",
                                intent.target_wem_id,
                                exc_info=True,
                            )
                        staged_durations_ms[intent.target_wem_id] = dur
                        staged_plugin_ids[intent.target_wem_id] = pl_id
                    else:
                        errors.append(
                            f"Could not resolve source media bytes for WEM {intent.source_wem_id}"
                        )

                case MarkBankModifiedIntent():
                    clean = (
                        intent.bank_name
                        if intent.bank_name.lower().endswith(".bnk")
                        else f"{intent.bank_name}.bnk"
                    ).lower()
                    if hasattr(project, "manifest") and hasattr(project.manifest, "modified_banks"):
                        if clean not in project.manifest.modified_banks:
                            project.manifest.modified_banks.append(clean)

                    if persist:
                        # Save serialized bank into pack_root/audio/<bank>.bnk
                        if hasattr(bank, "to_bytes"):
                            bank_bytes = bank.to_bytes()
                            project.save_bank(intent.bank_name, bank_bytes)
                        if hasattr(project, "manifest") and hasattr(project.manifest, "save"):
                            project.manifest.save(project.manifest_path)

                case SyncMusicTimelineIntent():
                    track = find_music_track_in_bank(bank, intent.track_id)
                    duration_ms = intent.new_duration_ms
                    if (
                        duration_ms <= 0.0
                        and track
                        and 0 <= intent.source_index < len(track.sources)
                    ):
                        wem_id = track.sources[intent.source_index].source_id
                        duration_ms = staged_durations_ms.get(wem_id, 0.0)
                    if duration_ms <= 0.0:
                        duration_ms = 50.0

                    if track is not None:
                        if len(track.sources) == 1:
                            for clip in track.playlist:
                                clip.play_at = 0.0
                                clip.begin_trim_offset = 0.0
                                clip.end_trim_offset = 0.0
                                clip.src_duration = duration_ms
                        else:
                            if intent.source_index < len(track.playlist):
                                clip = track.playlist[intent.source_index]
                                clip.play_at = 0.0
                                clip.begin_trim_offset = 0.0
                                clip.end_trim_offset = 0.0
                                clip.src_duration = duration_ms

                    parent_seg = find_parent_segment_in_bank(
                        bank, intent.track_id, intent.parent_segment_id
                    )
                    if parent_seg is not None:
                        if track is not None and len(track.sources) > 1:
                            new_seg_ms = max(
                                (
                                    c.src_duration + c.end_trim_offset - c.begin_trim_offset
                                    for c in track.playlist
                                ),
                                default=duration_ms,
                            )
                        else:
                            new_seg_ms = duration_ms

                        if len(parent_seg.markers) >= 2:
                            entry_old = parent_seg.markers[0].position
                            exit_old = parent_seg.markers[-1].position
                            old_span = exit_old - entry_old
                            parent_seg.markers[0].position = 0.0
                            if len(parent_seg.markers) > 2:
                                for m in parent_seg.markers[1:-1]:
                                    if old_span > 0.0:
                                        ratio = max(
                                            0.0, min(1.0, (m.position - entry_old) / old_span)
                                        )
                                        m.position = ratio * new_seg_ms
                                    elif parent_seg.duration > 0.0:
                                        ratio = max(0.0, min(1.0, m.position / parent_seg.duration))
                                        m.position = ratio * new_seg_ms
                                    else:
                                        m.position = min(m.position, new_seg_ms)
                                parent_seg.markers[1:-1] = sorted(
                                    parent_seg.markers[1:-1], key=lambda x: x.position
                                )
                            parent_seg.markers[-1].position = new_seg_ms
                        elif len(parent_seg.markers) == 1:
                            parent_seg.markers[0].position = 0.0

                        parent_seg.duration = new_seg_ms

                case UpdateNodeParamsIntent():
                    obj = None
                    hirc = getattr(bank, "hirc", None)
                    if hirc is not None:
                        for o in getattr(hirc, "objects", ()):
                            if getattr(o, "id", None) == intent.node_id:
                                obj = o
                                break
                    if obj is None and hasattr(bank, "get_object"):
                        obj = bank.get_object(intent.node_id)
                    if obj is None and hasattr(bank, "objects") and isinstance(bank.objects, dict):
                        obj = bank.objects.get(intent.node_id)
                    if obj is None and isinstance(bank, dict):
                        obj = bank.get(intent.node_id)

                    if obj is None:
                        errors.append(f"Node {intent.node_id} not found in bank")
                    else:
                        nb = (
                            getattr(obj, "node_base_params", None)
                            or getattr(
                                getattr(obj, "music_node_params", None), "node_base_params", None
                            )
                            or getattr(getattr(obj, "trans_params", None), "node_base_params", None)
                        )
                        if nb is None:
                            errors.append(f"Node {intent.node_id} does not support NodeBaseParams")
                        else:
                            if intent.volume_db is not None:
                                if abs(intent.volume_db) < 1e-6:
                                    nb.props.pop(0, None)
                                else:
                                    nb.props[0] = float(intent.volume_db)
                            if intent.pitch_cents is not None:
                                if abs(intent.pitch_cents) < 1e-6:
                                    nb.props.pop(2, None)
                                else:
                                    nb.props[2] = float(intent.pitch_cents)
                            nb.props = dict(sorted(nb.props.items()))

                case AppendVariationIntent():
                    cntr = None
                    hirc = getattr(bank, "hirc", None)
                    if hirc is not None:
                        for o in getattr(hirc, "objects", ()):
                            if getattr(o, "id", None) == intent.container_id:
                                cntr = o
                                break
                    if cntr is None and hasattr(bank, "objects") and isinstance(bank.objects, dict):
                        cntr = bank.objects.get(intent.container_id)
                    if cntr is None and isinstance(bank, dict):
                        cntr = bank.get(intent.container_id)

                    if cntr is None or not isinstance(cntr, CAkRanSeqCntr):
                        errors.append(f"RanSeqCntr {intent.container_id} not found in bank")
                    else:
                        existing_sound = None
                        if hirc is not None:
                            for o in getattr(hirc, "objects", ()):
                                if getattr(o, "id", None) == intent.child_sound_id and isinstance(
                                    o, CAkSound
                                ):
                                    existing_sound = o
                                    break
                        if (
                            existing_sound is None
                            and hasattr(bank, "objects")
                            and isinstance(bank.objects, dict)
                        ):
                            s = bank.objects.get(intent.child_sound_id)
                            if isinstance(s, CAkSound):
                                existing_sound = s

                        if existing_sound is None:
                            first_child_sound = None
                            if hirc is not None:
                                for cid in cntr.children:
                                    for o in getattr(hirc, "objects", ()):
                                        if getattr(o, "id", None) == cid and isinstance(
                                            o, CAkSound
                                        ):
                                            first_child_sound = o
                                            break
                                    if first_child_sound is not None:
                                        break

                            if first_child_sound is not None and hasattr(
                                first_child_sound, "node_base_params"
                            ):
                                nb = copy.deepcopy(first_child_sound.node_base_params)
                            else:
                                nb = NodeBaseParams(direct_parent_id=cntr.id)
                            nb.direct_parent_id = cntr.id

                            pl_id = staged_plugin_ids.get(intent.wem_id, intent.plugin_id)
                            new_sound = CAkSound(
                                id=intent.child_sound_id,
                                obj_type=2,
                                plugin_id=pl_id,
                                stream_type=2,
                                source_id=intent.wem_id,
                                file_id=intent.wem_id,
                                file_offset=0,
                                in_memory_media_size=0,
                                source_bits=0,
                                plugin_params=b"",
                                node_base_params=nb,
                            )

                            if hirc is not None and hasattr(hirc, "objects"):
                                try:
                                    cntr_idx = hirc.objects.index(cntr)
                                    hirc.objects.insert(cntr_idx, new_sound)
                                except ValueError:
                                    hirc.objects.append(new_sound)
                            if hasattr(bank, "objects") and isinstance(bank.objects, dict):
                                bank.objects[intent.child_sound_id] = new_sound

                        if intent.child_sound_id not in cntr.children:
                            cntr.children.append(intent.child_sound_id)
                        cntr.playlist.append(
                            AkPlaylistItem(play_id=intent.child_sound_id, weight=intent.weight)
                        )

                case _ as unreachable:
                    assert_never(unreachable)

        if errors:
            return ExecutionResult(
                success=False,
                description=f"Failed to execute plan: {'; '.join(errors)}",
                errors=tuple(errors),
            )

        return ExecutionResult(
            success=True,
            description=plan.description,
            errors=tuple(errors),
        )

    except Exception as exc:
        return ExecutionResult(
            success=False,
            description=f"Failed to execute plan: {exc}",
            errors=(str(exc),),
        )
