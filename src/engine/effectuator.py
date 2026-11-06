"""
Imperative Shell for applying AudioMutationPlans to AudioProject and SoundBanks.
Dispatches effect intents to disk I/O, audio conversion, and AST mutations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, assert_never

from src.bnk.models import CAkSound
from src.bnk.wem import build_silent_pcm_wem_bytes
from src.compiler.converter import AudioConverter
from src.engine.ontology import (
    AppendVariationIntent,
    AudioMutationPlan,
    CopyMediaBytesIntent,
    MarkBankModifiedIntent,
    StageLooseWemIntent,
    StageMasterAudioIntent,
    SyncMusicTimelineIntent,
    UpdateSoundNodeIntent,
)
from src.engine.planner import find_sound_in_bank
from src.engine.ports import AudioProjectPort


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

    try:
        for intent in plan.effects:
            match intent:
                case StageMasterAudioIntent():
                    # 1. Stage master uncompressed audio in source_audio/
                    project.stage_source_audio(src_path=intent.source_path, wem_id=intent.wem_id)

                    # 2. Convert audio to 32kHz Mono Vorbis/PCM WEM and stage in pack_root/audio/
                    wem_bytes, _ = AudioConverter.convert_to_wem_bytes(
                        input_source=intent.source_path,
                        target_sample_rate=32000,
                        target_channels=1,
                    )
                    project.stage_wem(wem_id=intent.wem_id, data=wem_bytes)

                case StageLooseWemIntent():
                    project.stage_wem(wem_id=intent.wem_id, data=intent.wem_bytes)

                case UpdateSoundNodeIntent():
                    sound = find_sound_in_bank(bank, intent.sound_id)
                    if isinstance(sound, CAkSound):
                        sound.stream_type = intent.new_stream_type
                        sound.source_id = intent.new_source_id
                        sound.file_id = intent.new_file_id
                        sound.file_offset = 0
                        sound.in_memory_media_size = 0

                    # Ensure silent 1.wem stub exists on disk if muting
                    if intent.new_source_id == 1:
                        silent_path = project.audio_dir / "1.wem"
                        if not silent_path.is_file() or 1 not in project.manifest.staged_wems:
                            silent_bytes = build_silent_pcm_wem_bytes(
                                duration_ms=50, sample_rate=32000
                            )
                            project.stage_wem(1, silent_bytes)

                case CopyMediaBytesIntent():
                    raw_bytes = None
                    if resolver is not None and hasattr(resolver, "resolve_wem_bytes"):
                        raw_bytes = resolver.resolve_wem_bytes(intent.source_wem_id)
                    if raw_bytes is None and hasattr(bank, "get_media_data"):
                        raw_bytes = bank.get_media_data(intent.source_wem_id)
                    if raw_bytes is not None:
                        project.stage_wem(wem_id=intent.target_wem_id, data=raw_bytes)
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
                    errors.append(
                        f"Effect intent SyncMusicTimelineIntent not yet supported: {intent}"
                    )

                case AppendVariationIntent():
                    errors.append(
                        f"Effect intent AppendVariationIntent not yet supported: {intent}"
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
