"""Headless domain façade managing SoundBank ASTs, layered asset resolution, and mutations."""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from typing import Any

from src.bnk.bank import SoundBank
from src.bnk.chunks import scan_didx_media_ids
from src.bnk.models import CAkMusicTrack, CAkSound
from src.bnk.wem import build_silent_pcm_wem_bytes
from src.compiler.audio_modifiers import AudioModifierChain
from src.engine.catalog.structs import CatalogScope
from src.engine.catalog_discovery import build_audio_catalog_for_bank
from src.engine.diff import BankDiffResult, diff_soundbanks
from src.engine.effectuator import execute_mutation_plan
from src.engine.graph import BankGraphIndex
from src.engine.ontology import (
    AudioMutationPlan,
    BankBatchSnapshot,
    BatchItem,
    BatchOutcome,
    BatchPlan,
    CopyMediaBytesIntent,
    ExistingMediaReferenceSource,
    ExternalFileSource,
    MarkBankModifiedIntent,
    MediaNodeTarget,
    MediaTargetSnapshot,
    MusicTrackTarget,
    MutationBatch,
    MutationRecord,
    MutationTarget,
    MutationTransaction,
    ReplacementScope,
    SoundNodeTarget,
    StageLooseWemIntent,
    StageMasterAudioIntent,
    SyncMusicTimelineIntent,
    UpdateMusicTrackNodeIntent,
    UpdateSoundNodeIntent,
    WemReference,
)
from src.engine.planner import (
    collect_bank_wem_ids,
    find_music_track_in_bank,
    find_parent_segment_in_bank,
    find_sound_in_bank,
    plan_batch,
)
from src.engine.ports import AssetResolverPort, AudioProjectPort

logger = logging.getLogger(__name__)

__all__ = ["BatchOutcome", "WorkspaceSession"]

_COMPANION_LOGIC_BANKS: dict[str, tuple[str, ...]] = {
    "music_data.bnk": ("global_music.bnk",),
    "animation_blood_data.bnk": ("battle_animation.bnk", "campaign_animation.bnk"),
    "animation_bodyfall_data.bnk": ("battle_animation.bnk", "campaign_animation.bnk"),
    "animation_footstep_foley_data.bnk": ("battle_animation.bnk", "campaign_animation.bnk"),
    "animation_misc_data.bnk": ("battle_animation.bnk", "campaign_animation.bnk"),
    "animation_siege_data.bnk": ("battle_animation.bnk", "campaign_animation.bnk"),
    "animation_weapon_data.bnk": ("battle_animation.bnk", "campaign_animation.bnk"),
    "projectiles_explosion_data.bnk": ("battle_projectiles.bnk",),
    "projectiles_fire_data.bnk": ("battle_projectiles.bnk",),
    "projectiles_fire_group_data.bnk": ("battle_projectiles.bnk",),
    "projectiles_hit_tree_data.bnk": ("battle_projectiles.bnk",),
    "projectiles_idle_data.bnk": ("battle_projectiles.bnk",),
    "projectiles_impact_data.bnk": ("battle_projectiles.bnk",),
    "projectiles_incoming_data.bnk": ("battle_projectiles.bnk",),
    "projectiles_inflight_data.bnk": ("battle_projectiles.bnk",),
    "group_melee_data.bnk": ("battle.bnk",),
    "group_movement_data.bnk": ("battle.bnk",),
    "group_sound_data.bnk": ("battle.bnk",),
    "lfe_data.bnk": ("battle.bnk",),
    "vocalisations_data.bnk": ("battle_vocalisations.bnk", "campaign_vocalisations.bnk"),
    "environment_data.bnk": ("battle_environment.bnk",),
    "rain_data.bnk": ("battle_rain.bnk",),
    "battle_data.bnk": ("battle.bnk",),
    "battle_ui_data.bnk": ("battle_ui.bnk",),
    "campaign_data.bnk": ("campaign.bnk",),
    "campaign_ui_data.bnk": ("campaign_ui.bnk",),
    "global_ui_data.bnk": ("global_ui.bnk",),
    "global_bus_data.bnk": ("global_bus.bnk",),
}


def _resolve_companion_logic_banks(bank_name: str) -> tuple[str, ...]:
    """Resolves companion HIRC logic SoundBank names for a given SoundBank name."""
    b_lower = bank_name.lower()
    if not b_lower.endswith(".bnk"):
        b_lower += ".bnk"
    if b_lower in _COMPANION_LOGIC_BANKS:
        return _COMPANION_LOGIC_BANKS[b_lower]
    if b_lower.endswith("_data.bnk"):
        stem = b_lower.removesuffix("_data.bnk")
        return (f"{stem}.bnk",)
    return ()


def _node_key_for_target(target: Any) -> str:
    if isinstance(target, SoundNodeTarget):
        return f"hirc:{target.sound_id}"
    elif isinstance(target, MusicTrackTarget):
        return (
            f"hirc:{target.track_id}:src:{target.source_index}"
            if target.source_index > 0
            else f"hirc:{target.track_id}"
        )
    elif isinstance(target, MediaNodeTarget):
        return f"media:{target.wem_id}"
    return (getattr(target, "sound_id", None) and f"hirc:{target.sound_id}") or ""


def _extract_bank_media_ids(bank: SoundBank) -> set[int]:
    """Collects all embedded and referenced media/WEM IDs from SoundBank AST."""
    media_ids: set[int] = set()
    if bank.didx and bank.didx.entries:
        media_ids.update(e.file_id for e in bank.didx.entries)
    if bank.hirc and bank.hirc.objects:
        for obj in bank.hirc.objects:
            if isinstance(obj, CAkSound):
                wid = getattr(obj, "source_id", 0) or getattr(obj, "file_id", 0)
                if wid > 0:
                    media_ids.add(wid)
            elif isinstance(obj, CAkMusicTrack):
                if hasattr(obj, "sources") and obj.sources:
                    for s in obj.sources:
                        sid = getattr(s, "source_id", 0) or getattr(s, "file_id", 0)
                        if sid > 0:
                            media_ids.add(sid)
                else:
                    sid = getattr(obj, "source_id", 0) or getattr(obj, "file_id", 0)
                    if sid > 0:
                        media_ids.add(sid)
    return media_ids


class WorkspaceSession:
    """Domain façade managing SoundBank ASTs, mutation undo/redo stacks, and layered asset resolution."""

    def __init__(
        self,
        project: AudioProjectPort | None = None,
        sound_db: Any | None = None,
    ) -> None:
        self._project: AudioProjectPort | None = project
        self._sound_db: Any | None = sound_db
        self._resolver: AssetResolverPort | None = (
            getattr(project, "resolver", None) if project is not None else None
        )
        self._loaded_banks: dict[str, tuple[SoundBank, BankGraphIndex, BankDiffResult | None]] = {}
        self._companion_banks: dict[int, SoundBank] = {}
        self._mutation_undo_stack: list[Any] = []
        self._mutation_redo_stack: list[Any] = []
        self._wem_cache: dict[int, bytes] = {}
        self._bank_media_ids_cache: dict[str, frozenset[int]] = {}
        self._unopened_scanned_for_refs: bool = False
        self._global_wem_to_banks: dict[int, set[str]] | None = None
        self._baseline_reserved_wem_ids: set[int] | None = None

    @property
    def project(self) -> AudioProjectPort | None:
        """Active AudioProject workspace instance."""
        return self._project

    @property
    def sound_db(self) -> Any | None:
        """Active SoundDatabase instance, lazy-loaded from resolver if available."""
        if self._sound_db is not None:
            return self._sound_db
        if self._resolver is not None:
            try:
                data = self._resolver.resolve_database_bytes()
                if data:
                    from src.bnk.database import SoundDatabase

                    self._sound_db = SoundDatabase.from_bytes(data)
                    return self._sound_db
            except (OSError, ValueError, KeyError, RuntimeError) as e:
                logger.debug("Failed to lazy load SoundDatabase: %s", e)
        return None

    @sound_db.setter
    def sound_db(self, value: Any | None) -> None:
        """Explicitly assigns or resets active SoundDatabase."""
        self._sound_db = value

    @property
    def resolver(self) -> AssetResolverPort | None:
        """Active layered AssetResolver instance."""
        return self._resolver

    @resolver.setter
    def resolver(self, value: AssetResolverPort | None) -> None:
        """Explicitly assigns or resets layered AssetResolver."""
        self._resolver = value

    @property
    def loaded_banks(
        self,
    ) -> Mapping[str, tuple[SoundBank, BankGraphIndex, BankDiffResult | None]]:
        """Active loaded soundbanks mapped by bank name."""
        return MappingProxyType(self._loaded_banks)

    @property
    def companion_banks(self) -> dict[int, SoundBank]:
        """In-memory cache for companion banks referenced during graph resolution."""
        return self._companion_banks

    @property
    def undo_history(self) -> tuple[MutationRecord, ...]:
        """Sequence of mutation records in the undo stack."""
        records: list[MutationRecord] = []
        for entry in self._mutation_undo_stack:
            if isinstance(entry, MutationRecord):
                records.append(entry)
            elif hasattr(entry, "records"):
                records.extend(entry.records)
        return tuple(records)

    @property
    def redo_history(self) -> tuple[MutationRecord, ...]:
        """Sequence of mutation records in the redo stack."""
        records: list[MutationRecord] = []
        for entry in self._mutation_redo_stack:
            if isinstance(entry, MutationRecord):
                records.append(entry)
            elif hasattr(entry, "records"):
                records.extend(entry.records)
        return tuple(records)

    def push_mutation_record(self, record: MutationRecord) -> None:
        """Pushes a mutation record to the undo stack and clears redo history."""
        self._mutation_undo_stack.append(record)
        self._mutation_redo_stack.clear()

    @property
    def wem_cache(self) -> Mapping[int, bytes]:
        """Immutable view of cached WEM byte buffers."""
        return MappingProxyType(self._wem_cache)

    def cache_wem(self, wem_id: int, data: bytes) -> None:
        """Stores WEM bytes into in-memory cache."""
        self._wem_cache[wem_id] = data

    @property
    def can_undo_mutation(self) -> bool:
        """True if there are audio mutations in the undo stack and project is active."""
        return len(self._mutation_undo_stack) > 0 and self._project is not None

    @property
    def can_redo_mutation(self) -> bool:
        """True if there are audio mutations in the redo stack and project is active."""
        return len(self._mutation_redo_stack) > 0 and self._project is not None

    def compile_mod_pack(
        self,
        output_path: Path | str | None = None,
        pack_type: int = 3,
    ) -> Path:
        """Compiles the active project workspace into a Total War PFH4 Mod pack (default PT_MOD = 3)."""
        if self._project is None:
            raise RuntimeError("Cannot compile mod pack without an active project.")
        return self._project.compile_mod_pack(output_path=output_path, pack_type=pack_type)

    def compile_movie_pack(
        self,
        output_path: Path | str | None = None,
        pack_type: int = 3,
    ) -> Path:
        """Alias for compile_mod_pack (defaults to PT_MOD = 3)."""
        return self.compile_mod_pack(output_path=output_path, pack_type=pack_type)

    def register_in_user_script(self, pack_name: str | None = None) -> Path | None:
        """Registers the mod pack in user.script.txt for game startup."""
        if self._project is None:
            return None
        return self._project.register_in_user_script(pack_name=pack_name)

    def set_project(self, project: AudioProjectPort | None) -> None:
        """Sets the active project and initializes its layered asset resolver."""
        self._project = project
        self._sound_db = None
        self._resolver = getattr(project, "resolver", None) if project is not None else None
        self._unopened_scanned_for_refs = False
        self._global_wem_to_banks = None
        self._baseline_reserved_wem_ids = None

    def reset(self) -> None:
        """Clears project reference, resolver, loaded bank ASTs, and mutation history stacks."""
        self._project = None
        self._resolver = None
        self._sound_db = None
        self._loaded_banks.clear()
        self._companion_banks.clear()
        self._mutation_undo_stack.clear()
        self._mutation_redo_stack.clear()
        self._wem_cache.clear()
        self._bank_media_ids_cache.clear()
        self._unopened_scanned_for_refs = False
        self._global_wem_to_banks = None
        self._baseline_reserved_wem_ids = None

    def clear(self) -> None:
        """Alias for reset()."""
        self.reset()

    def get_loaded_entry(
        self, bank_name: str
    ) -> tuple[SoundBank, BankGraphIndex, BankDiffResult | None] | None:
        """Returns the loaded SoundBank tuple (AST, graph index, diff result) for the specified bank name if loaded."""
        return self._loaded_banks.get(bank_name.lower())

    def get_loaded_bank(self, bank_name: str) -> SoundBank | None:
        """Returns the loaded SoundBank AST for the specified bank name if loaded."""
        entry = self.get_loaded_entry(bank_name)
        if entry is not None:
            return entry[0]
        return None

    def get_staged_wems(self) -> set[int] | None:
        """Returns the set of staged WEM IDs recorded in the active project manifest, or None."""
        if self._project is not None and hasattr(self._project, "manifest"):
            return set(getattr(self._project.manifest, "staged_wems", []))
        return None

    def reload_dependencies(self) -> None:
        """Evicts cached SoundBanks and WEMs when dependencies are added, removed, or reordered."""
        self._loaded_banks.clear()
        self._companion_banks.clear()
        self._wem_cache.clear()
        self._bank_media_ids_cache.clear()
        self._sound_db = None
        self._unopened_scanned_for_refs = False
        self._global_wem_to_banks = None
        self._baseline_reserved_wem_ids = None
        if self._project is not None:
            self._resolver = getattr(self._project, "resolver", None)

    def get_bank_media_ids(self, bank_name: str) -> frozenset[int]:
        """Returns set of embedded and referenced WEM IDs in bank."""
        clean = (bank_name if bank_name.lower().endswith(".bnk") else f"{bank_name}.bnk").lower()
        if clean in self._bank_media_ids_cache:
            return self._bank_media_ids_cache[clean]

        for k, entry in self._loaded_banks.items():
            k_clean = (k if k.lower().endswith(".bnk") else f"{k}.bnk").lower()
            if k_clean == clean:
                bank, g_idx, _ = entry
                ids: set[int] = set()
                if bank.didx is not None:
                    ids.update(e.file_id for e in bank.didx.entries)
                if g_idx is not None and getattr(g_idx, "wem_references", None):
                    ids.update(g_idx.wem_references.keys())
                res = frozenset(ids)
                self._bank_media_ids_cache[clean] = res
                return res

        if self._resolver is not None:
            path = self._resolver.resolve_bank_path(clean)
            if path is not None and path.is_file():
                didx_ids = scan_didx_media_ids(path)
                cached_ids: frozenset[int] = frozenset()
                if (
                    not didx_ids
                    and self._project is not None
                    and getattr(self._project, "cache", None) is not None
                ):
                    cached_ids = self._project.cache.get_bank_media_ids(clean)

                media_ids = didx_ids or cached_ids
                staged = self.get_staged_wems() or set()
                if media_ids and (not staged or bool(media_ids & staged)):
                    res = media_ids
                else:
                    try:
                        bank_bytes = path.read_bytes()
                        bank = SoundBank.from_bytes(bank_bytes)
                        res = frozenset(_extract_bank_media_ids(bank))
                    except Exception:
                        res = media_ids
                self._bank_media_ids_cache[clean] = res
                return res

        if self._project is not None and getattr(self._project, "cache", None) is not None:
            res = self._project.cache.get_bank_media_ids(clean)
            if res:
                self._bank_media_ids_cache[clean] = res
                return res

        return frozenset()

    def is_wem_modified(self, wem_id: int | str) -> bool:
        """Returns True if the specified WEM ID is staged in project overlay."""
        if self._resolver is not None:
            return self._resolver.is_wem_modified(wem_id)
        if self._project is not None and hasattr(self._project, "manifest"):
            try:
                wid = int(str(wem_id).removesuffix(".wem"))
                if (
                    self._project.audio_dir.is_dir()
                    and (self._project.audio_dir / f"{wid}.wem").is_file()
                ):
                    return True
                return wid in self._project.manifest.staged_wems
            except (ValueError, TypeError):
                return False
        return False

    def revert_bank(self, bank_name: str) -> tuple[int, int]:
        """
        Reverts modified SoundBank and its unshared staged loose WEMs to baseline.
        Evicts from in-memory AST cache and clears WEM cache.
        Returns tuple (banks_reverted_count, wems_reverted_count).
        """
        if self._project is None:
            return (0, 0)
        res = self._project.revert_bank_completely(
            bank_name,
            all_banks_media_provider=self.get_bank_media_ids,
        )
        clean = (bank_name if bank_name.lower().endswith(".bnk") else f"{bank_name}.bnk").lower()
        self._loaded_banks = {
            k: v
            for k, v in self._loaded_banks.items()
            if (k if k.lower().endswith(".bnk") else f"{k}.bnk").lower() != clean
        }
        self._wem_cache.clear()
        return res

    def revert_wem(self, wem_id: int | str) -> bool:
        """
        Reverts loose .wem file and evicts from in-memory cache.
        Also restores any HIRC nodes across loaded/modified banks referencing wem_id to baseline.
        Returns True if reverted.
        """
        try:
            wid = int(str(wem_id).removesuffix(".wem"))
        except (ValueError, TypeError):
            return False

        res = False
        if self._project is not None:
            res = self._project.revert_wem_completely(wid)
        self._wem_cache.pop(wid, None)

        candidate_bank_names: set[str] = set(self._loaded_banks.keys())
        if self._project is not None and hasattr(self._project, "manifest"):
            for b in getattr(self._project.manifest, "modified_banks", ()):
                candidate_bank_names.add(b.lower())

        nodes_restored = False
        for b_name in candidate_bank_names:
            entry = self.get_loaded_entry(b_name)
            if entry is None:
                try:
                    entry = self.resolve_and_parse_bank(b_name)
                except (
                    FileNotFoundError,
                    ValueError,
                    KeyError,
                    IndexError,
                    RuntimeError,
                    OSError,
                    EOFError,
                ):
                    continue
            bank = entry[0]

            baseline_bytes = (
                self._resolver.resolve_baseline_bank_bytes(b_name)
                if self._resolver is not None
                else None
            )
            if not baseline_bytes:
                continue

            try:
                base_bank = SoundBank.from_bytes(baseline_bytes)
            except (
                FileNotFoundError,
                ValueError,
                KeyError,
                IndexError,
                RuntimeError,
                OSError,
                EOFError,
            ):
                continue

            if (
                not bank.hirc
                or not bank.hirc.objects
                or not base_bank.hirc
                or not base_bank.hirc.objects
            ):
                continue

            base_objs_by_id = {o.id: o for o in base_bank.hirc.objects}
            bank_updated = False

            for idx, obj in enumerate(list(bank.hirc.objects)):
                needs_restore = False
                if isinstance(obj, CAkSound):
                    s_wid = getattr(obj, "source_id", 0) or getattr(obj, "file_id", 0)
                    if s_wid == wid:
                        needs_restore = True
                    elif obj.id in base_objs_by_id:
                        base_s = base_objs_by_id[obj.id]
                        if isinstance(base_s, CAkSound):
                            base_swid = getattr(base_s, "source_id", 0) or getattr(
                                base_s, "file_id", 0
                            )
                            if base_swid == wid:
                                needs_restore = True
                elif isinstance(obj, CAkMusicTrack):
                    if hasattr(obj, "sources") and obj.sources:
                        for s in obj.sources:
                            swid = getattr(s, "source_id", 0) or getattr(s, "file_id", 0)
                            if swid == wid:
                                needs_restore = True
                                break
                    if not needs_restore and obj.id in base_objs_by_id:
                        base_t = base_objs_by_id[obj.id]
                        if (
                            isinstance(base_t, CAkMusicTrack)
                            and hasattr(base_t, "sources")
                            and base_t.sources
                        ):
                            for s in base_t.sources:
                                swid = getattr(s, "source_id", 0) or getattr(s, "file_id", 0)
                                if swid == wid:
                                    needs_restore = True
                                    break

                if needs_restore and obj.id in base_objs_by_id:
                    base_o = base_objs_by_id[obj.id]
                    bank.hirc.objects[idx] = copy.deepcopy(base_o)
                    bank_updated = True
                    nodes_restored = True

                    if isinstance(base_o, CAkMusicTrack):
                        parent_seg_curr = find_parent_segment_in_bank(bank, base_o.id)
                        if parent_seg_curr is not None:
                            parent_seg_base = find_parent_segment_in_bank(base_bank, base_o.id)
                            if parent_seg_base is not None:
                                base_tracks = {
                                    o.id: o
                                    for o in base_bank.hirc.objects
                                    if isinstance(o, CAkMusicTrack)
                                }
                                curr_tracks = {
                                    o.id: o
                                    for o in bank.hirc.objects
                                    if isinstance(o, CAkMusicTrack)
                                }
                                other_differs = False
                                for child_id in getattr(parent_seg_base, "child_ids", ()):
                                    if child_id != base_o.id:
                                        if child_id in curr_tracks and child_id in base_tracks:
                                            if curr_tracks[child_id] != base_tracks[child_id]:
                                                other_differs = True
                                                break
                                if not other_differs:
                                    for s_idx, o in enumerate(bank.hirc.objects):
                                        if o.id == parent_seg_curr.id:
                                            bank.hirc.objects[s_idx] = copy.deepcopy(
                                                parent_seg_base
                                            )
                                            break

            if bank_updated:
                struct_diff = diff_soundbanks(bank, base_bank)
                if self._project is not None:
                    if not struct_diff.is_modified:
                        self._project.revert_bank(b_name)
                    else:
                        self._project.save_bank(b_name, bank.to_bytes())
                diff_res = self.compute_bank_diff(b_name, bank)
                self.index_soundbank(b_name, bank, diff_result=diff_res)

        return res or nodes_restored

    def revert_node_to_baseline(self, bank_name: str, node_key: str) -> bool:
        """
        Reverts a single HIRC or media node in a SoundBank to its baseline state.
        Restores HIRC AST, cleans up unshared loose WEMs, and reconciles project storage.
        Returns True if reverted successfully.
        """
        if not bank_name or not node_key:
            return False

        if node_key.startswith("media:"):
            try:
                wid = int(node_key.removeprefix("media:"))
            except (ValueError, TypeError):
                return False
            return self.revert_wem(wid)

        if not node_key.startswith("hirc:"):
            return False

        parts = node_key.split(":")
        try:
            obj_id = int(parts[1])
        except (ValueError, IndexError):
            return False

        entry = self.get_loaded_entry(bank_name)
        if entry is None:
            try:
                entry = self.resolve_and_parse_bank(bank_name)
            except (
                FileNotFoundError,
                ValueError,
                KeyError,
                IndexError,
                RuntimeError,
                OSError,
                EOFError,
            ):
                return False

        bank = entry[0]
        if self._resolver is None:
            return False

        baseline_bytes = self._resolver.resolve_baseline_bank_bytes(bank_name)
        if baseline_bytes is None:
            return False

        try:
            base_bank = SoundBank.from_bytes(baseline_bytes)
        except (
            FileNotFoundError,
            ValueError,
            KeyError,
            IndexError,
            RuntimeError,
            OSError,
            EOFError,
        ):
            return False

        if (
            not bank.hirc
            or not bank.hirc.objects
            or not base_bank.hirc
            or not base_bank.hirc.objects
        ):
            return False

        curr_idx = -1
        curr_obj = None
        for idx, o in enumerate(bank.hirc.objects):
            if o.id == obj_id:
                curr_idx = idx
                curr_obj = o
                break
        if curr_obj is None or curr_idx < 0:
            return False

        base_obj = None
        for o in base_bank.hirc.objects:
            if o.id == obj_id:
                base_obj = o
                break
        if base_obj is None:
            return False

        # Record any WEM IDs referenced by the current object BEFORE reverting
        old_wems: set[int] = set()
        base_wems: set[int] = set()
        if isinstance(curr_obj, CAkSound):
            w = getattr(curr_obj, "source_id", 0) or getattr(curr_obj, "file_id", 0)
            if w > 0:
                old_wems.add(w)
        elif isinstance(curr_obj, CAkMusicTrack):
            if hasattr(curr_obj, "sources") and curr_obj.sources:
                for s in curr_obj.sources:
                    w = getattr(s, "source_id", 0) or getattr(s, "file_id", 0)
                    if w > 0:
                        old_wems.add(w)

        if isinstance(base_obj, CAkSound):
            w = getattr(base_obj, "source_id", 0) or getattr(base_obj, "file_id", 0)
            if w > 0:
                base_wems.add(w)
        elif isinstance(base_obj, CAkMusicTrack):
            if hasattr(base_obj, "sources") and base_obj.sources:
                for s in base_obj.sources:
                    w = getattr(s, "source_id", 0) or getattr(s, "file_id", 0)
                    if w > 0:
                        base_wems.add(w)

        bank.hirc.objects[curr_idx] = copy.deepcopy(base_obj)

        if isinstance(base_obj, CAkMusicTrack):
            parent_seg_curr = find_parent_segment_in_bank(bank, base_obj.id)
            if parent_seg_curr is not None:
                parent_seg_base = find_parent_segment_in_bank(base_bank, base_obj.id)
                if parent_seg_base is not None:
                    base_tracks = {
                        o.id: o for o in base_bank.hirc.objects if isinstance(o, CAkMusicTrack)
                    }
                    curr_tracks = {
                        o.id: o for o in bank.hirc.objects if isinstance(o, CAkMusicTrack)
                    }
                    other_differs = False
                    for child_id in getattr(parent_seg_base, "child_ids", ()):
                        if child_id != base_obj.id:
                            if child_id in curr_tracks and child_id in base_tracks:
                                if curr_tracks[child_id] != base_tracks[child_id]:
                                    other_differs = True
                                    break
                    if not other_differs:
                        for s_idx, o in enumerate(bank.hirc.objects):
                            if o.id == parent_seg_curr.id:
                                bank.hirc.objects[s_idx] = copy.deepcopy(parent_seg_base)
                                break

        staged = self.get_staged_wems() or set()
        for wid in old_wems:
            if wid in staged and (
                wid not in base_wems or not self.get_cross_bank_wem_references(wid)
            ):
                still_referenced = False
                for b_k, (b_ast, _, d_res) in self._loaded_banks.items():
                    if b_k == bank_name.lower():
                        continue
                    if d_res and d_res.is_modified and wid in _extract_bank_media_ids(b_ast):
                        still_referenced = True
                        break
                if not still_referenced:
                    if self._project is not None:
                        self._project.revert_wem_completely(wid)
                    self._wem_cache.pop(wid, None)

        struct_diff = diff_soundbanks(bank, base_bank)
        if self._project is not None:
            if not struct_diff.is_modified:
                self._project.revert_bank(bank_name)
            else:
                self._project.save_bank(bank_name, bank.to_bytes())

        diff_res = self.compute_bank_diff(bank_name, bank)
        self.index_soundbank(bank_name, bank, diff_result=diff_res)
        return True

    def compute_bank_diff(self, bank_name: str, bank: SoundBank) -> BankDiffResult | None:
        """Computes diff between bank and baseline (vanilla cache or dependency)."""
        if self._resolver is None:
            return None
        baseline_bytes = self._resolver.resolve_baseline_bank_bytes(bank_name)
        base_diff: BankDiffResult | None = None
        if baseline_bytes:
            try:
                base_bank = SoundBank.from_bytes(baseline_bytes)
                base_diff = diff_soundbanks(bank, base_bank)
            except (ValueError, KeyError, IndexError, RuntimeError, OSError):
                base_diff = None

        # Include any staged loose WEMs overriding this bank's media (embedded or streamed)
        staged = self.get_staged_wems() or set()
        bank_media_ids = _extract_bank_media_ids(bank)
        staged_in_bank = staged & bank_media_ids
        if staged_in_bank:
            existing_media = base_diff.modified_media_ids if base_diff else frozenset()
            new_media = existing_media | staged_in_bank
            if base_diff is not None:
                base_diff = replace(base_diff, modified_media_ids=new_media)
            else:
                base_diff = BankDiffResult(modified_media_ids=new_media)

        return base_diff

    def index_soundbank(
        self,
        bank_name: str,
        bank: SoundBank,
        diff_result: BankDiffResult | None = None,
    ) -> tuple[SoundBank, BankGraphIndex, BankDiffResult | None]:
        """Directly indexes a SoundBank AST, constructs its BankGraphIndex, and caches it."""
        graph_index = BankGraphIndex.build(bank)
        entry = (bank, graph_index, diff_result)
        self._loaded_banks[bank_name.lower()] = entry
        return entry

    def resolve_and_parse_bank(
        self, bank_name: str
    ) -> tuple[SoundBank, BankGraphIndex, BankDiffResult | None]:
        """Resolves bank raw bytes from project overlay/cache or disk, parses AST, computes diff, and indexes."""
        cached_entry = self.get_loaded_entry(bank_name)
        if cached_entry is not None:
            return cached_entry

        data: bytes | None = None
        if self._resolver is not None:
            data = self._resolver.resolve_bank_bytes(bank_name)
        elif self._project is not None and hasattr(self._project, "resolver"):
            data = self._project.resolver.resolve_bank_bytes(bank_name)
        elif Path(bank_name).is_file():
            data = Path(bank_name).read_bytes()

        if data is None:
            raise FileNotFoundError(f"SoundBank '{bank_name}' could not be resolved.")

        bank = SoundBank.from_bytes(data)
        diff_res = self.compute_bank_diff(bank_name, bank)
        return self.index_soundbank(bank_name, bank, diff_result=diff_res)

    def _discover_all_project_bank_names(self) -> list[str]:
        """Discovers all SoundBank filenames across project overlay, active dependencies, and GameCache."""
        if self._project is None:
            return []
        bank_names: set[str] = set()

        # 1. Project audio directory
        audio_dir = getattr(self._project, "audio_dir", None)
        if audio_dir is not None and isinstance(audio_dir, Path):
            try:
                if audio_dir.is_dir():
                    for f in audio_dir.iterdir():
                        if f.is_file() and f.suffix.lower() == ".bnk":
                            bank_names.add(f.name.lower())
            except (OSError, PermissionError):
                pass

        # 2. Manifest modified banks and dependencies
        manifest = getattr(self._project, "manifest", None)
        if manifest is not None:
            for b in getattr(manifest, "modified_banks", ()):
                clean = b.lower() if b.lower().endswith(".bnk") else f"{b.lower()}.bnk"
                bank_names.add(clean)

            get_dep_dir = getattr(self._project, "get_dependency_dir", None)
            if callable(get_dep_dir) and hasattr(manifest, "dependencies"):
                for dep in getattr(manifest, "dependencies", ()):
                    try:
                        dep_audio = get_dep_dir(dep.name) / "audio"
                        if dep_audio.is_dir():
                            for f in dep_audio.iterdir():
                                if f.is_file() and f.suffix.lower() == ".bnk":
                                    bank_names.add(f.name.lower())
                    except (OSError, PermissionError):
                        pass

        # 3. GameCache
        cache = getattr(self._project, "cache", None)
        if cache is None and self._resolver is not None:
            cache = getattr(self._resolver, "cache", None)
        if cache is not None:
            try:
                list_banks_fn = getattr(cache, "list_banks", None)
                if callable(list_banks_fn):
                    for b in list_banks_fn():
                        clean = b.lower() if b.lower().endswith(".bnk") else f"{b.lower()}.bnk"
                        bank_names.add(clean)
            except (OSError, PermissionError):
                pass

        return sorted(bank_names)

    def get_cross_bank_wem_references(self, wem_id: int) -> tuple[WemReference, ...]:
        """Returns all HIRC node references to wem_id across loaded and discovered SoundBanks."""
        if not wem_id or wem_id <= 0:
            return ()

        if not self._unopened_scanned_for_refs and self._project is not None:
            self._unopened_scanned_for_refs = True
            if self._global_wem_to_banks is None:
                self._global_wem_to_banks = {}
                try:
                    for b_name in self._discover_all_project_bank_names():
                        try:
                            m_ids = self.get_bank_media_ids(b_name)
                            for mid in m_ids:
                                self._global_wem_to_banks.setdefault(mid, set()).add(b_name)
                        except (OSError, ValueError, KeyError, IndexError, RuntimeError):
                            pass
                except (OSError, ValueError, KeyError, IndexError, RuntimeError):
                    pass

        if self._global_wem_to_banks is not None:
            candidate_banks = set(self._global_wem_to_banks.get(wem_id, set()))
            for b in list(candidate_banks) + list(self._loaded_banks.keys()):
                for comp in _resolve_companion_logic_banks(b):
                    candidate_banks.add(comp)

            for b_name in candidate_banks:
                clean = b_name.lower()
                if clean not in self._loaded_banks:
                    try:
                        self.resolve_and_parse_bank(b_name)
                    except (
                        FileNotFoundError,
                        ValueError,
                        KeyError,
                        IndexError,
                        RuntimeError,
                        OSError,
                    ):
                        pass

        refs: list[WemReference] = []
        for b_name, (bank, graph_index, _) in self._loaded_banks.items():
            hirc_ids = graph_index.get_wem_referencing_hirc_ids(wem_id)
            for hid in hirc_ids:
                obj = graph_index.objects_by_id.get(hid)
                if obj is not None:
                    tname = type(obj).__name__.removeprefix("CAk")
                    lbl = graph_index.resolve_label(obj, sound_db=self._sound_db)
                    if not lbl:
                        lbl = f"{tname}_{hid}"

                    st = 2
                    if isinstance(obj, CAkSound):
                        st = getattr(obj, "stream_type", 2)
                    elif isinstance(obj, CAkMusicTrack):
                        if hasattr(obj, "sources") and obj.sources:
                            for s in obj.sources:
                                sid = getattr(s, "source_id", 0) or getattr(s, "file_id", 0)
                                if sid == wem_id:
                                    st = getattr(s, "stream_type", 2)
                                    break
                    else:
                        st = getattr(obj, "stream_type", 2)

                    is_in_didx = (
                        bank.didx is not None
                        and bool(bank.didx.entries)
                        and any(e.file_id == wem_id for e in bank.didx.entries)
                    )
                    is_emb = (st != 2) or is_in_didx

                    refs.append(
                        WemReference(
                            bank_name=b_name,
                            node_id=hid,
                            node_name=lbl,
                            node_type=tname,
                            node_key=f"hirc:{hid}",
                            stream_type=st,
                            is_embedded=is_emb,
                        )
                    )
        return tuple(refs)

    def get_wem_reference_count(self, wem_id: int) -> int:
        """Returns total number of referencing nodes for wem_id across loaded SoundBanks."""
        return len(self.get_cross_bank_wem_references(wem_id))

    def _collect_reserved_wem_ids(self) -> set[int]:
        """Collects all known WEM IDs across all loaded banks, discovered project banks, and loose files."""
        if self._baseline_reserved_wem_ids is None:
            baseline: set[int] = set()
            if self._project is not None:
                # 1. Bank media IDs from all discovered project banks
                for b_name in self._discover_all_project_bank_names():
                    try:
                        baseline.update(self.get_bank_media_ids(b_name))
                    except (OSError, ValueError, KeyError, IndexError, RuntimeError):
                        pass

                # 2. Loose .wem files in project audio_dir
                audio_dir = getattr(self._project, "audio_dir", None)
                if audio_dir is not None and isinstance(audio_dir, Path):
                    try:
                        if audio_dir.is_dir():
                            for f in audio_dir.iterdir():
                                if f.is_file() and f.suffix.lower() == ".wem" and f.stem.isdigit():
                                    baseline.add(int(f.stem))
                    except (OSError, PermissionError):
                        pass

                # 3. Loose .wem files in active dependencies
                manifest = getattr(self._project, "manifest", None)
                get_dep_dir = getattr(self._project, "get_dependency_dir", None)
                if (
                    manifest is not None
                    and callable(get_dep_dir)
                    and hasattr(manifest, "dependencies")
                ):
                    for dep in getattr(manifest, "dependencies", ()):
                        try:
                            dep_audio = get_dep_dir(dep.name) / "audio"
                            if dep_audio.is_dir():
                                for f in dep_audio.iterdir():
                                    if (
                                        f.is_file()
                                        and f.suffix.lower() == ".wem"
                                        and f.stem.isdigit()
                                    ):
                                        baseline.add(int(f.stem))
                        except (OSError, PermissionError):
                            pass

                # 4. Loose .wem files in cache
                cache = getattr(self._project, "cache", None)
                if cache is None and self._resolver is not None:
                    cache = getattr(self._resolver, "cache", None)
                if cache is not None:
                    list_wems_fn = getattr(cache, "list_wems", None)
                    if callable(list_wems_fn):
                        try:
                            baseline.update(list_wems_fn())
                        except (OSError, PermissionError):
                            pass
                    cache_dir = getattr(cache, "cache_dir", None)
                    if cache_dir is not None and isinstance(cache_dir, Path):
                        try:
                            if cache_dir.is_dir():
                                for f in cache_dir.iterdir():
                                    if (
                                        f.is_file()
                                        and f.suffix.lower() == ".wem"
                                        and f.stem.isdigit()
                                    ):
                                        baseline.add(int(f.stem))
                        except (OSError, PermissionError):
                            pass

            self._baseline_reserved_wem_ids = baseline

        reserved: set[int] = set(self._baseline_reserved_wem_ids)
        for _, entry in self._loaded_banks.items():
            bank, graph_index, _ = entry
            reserved.update(graph_index.wem_references.keys())
            reserved.update(collect_bank_wem_ids(bank))
        if self._project is not None:
            list_fn = getattr(self._project, "list_staged_wems", None)
            if callable(list_fn):
                try:
                    wems = list_fn()
                    if isinstance(wems, (set, list, tuple)):
                        reserved.update(wems)
                except Exception:
                    logger.debug("Failed to list staged wems from project", exc_info=True)
            manifest = getattr(self._project, "manifest", None)
            if manifest is not None and hasattr(manifest, "staged_wems"):
                staged = getattr(manifest, "staged_wems", ())
                if isinstance(staged, (set, list, tuple)):
                    reserved.update(staged)
        return reserved

    def preview_batch(self, batch: MutationBatch) -> BatchPlan:
        """Plans a batch of audio mutations without performing disk I/O or AST mutations."""
        banks: dict[str, SoundBank] = {}
        for item in batch.items:
            b_name = item.target.bank_name
            if b_name not in banks:
                entry = self.get_loaded_entry(b_name)
                if entry is not None:
                    banks[b_name] = entry[0]
                else:
                    try:
                        entry = self.resolve_and_parse_bank(b_name)
                        banks[b_name] = entry[0]
                    except (
                        FileNotFoundError,
                        ValueError,
                        KeyError,
                        IndexError,
                        RuntimeError,
                        OSError,
                    ):
                        pass
        return plan_batch(
            banks=banks,
            batch=batch,
            reserved_wem_ids=self._collect_reserved_wem_ids(),
        )

    def _preload_batch_banks(self, batch: MutationBatch) -> dict[str, SoundBank]:
        """Preloads and parses all SoundBanks targeted by items in a mutation batch."""
        banks: dict[str, SoundBank] = {}
        for item in batch.items:
            b_name = item.target.bank_name
            if b_name not in banks:
                entry = self.get_loaded_entry(b_name)
                if entry is not None:
                    banks[b_name] = entry[0]
                else:
                    try:
                        entry = self.resolve_and_parse_bank(b_name)
                        banks[b_name] = entry[0]
                    except (
                        FileNotFoundError,
                        ValueError,
                        KeyError,
                        IndexError,
                        RuntimeError,
                        OSError,
                    ):
                        pass
        return banks

    def _find_sibling_promotion_plans(
        self,
        batch: MutationBatch,
        batch_plan: BatchPlan,
        banks: dict[str, SoundBank],
    ) -> list[AudioMutationPlan]:
        """Finds cross-bank sibling sound and music track nodes referencing overwritten WEMs to promote to streamed."""
        sibling_plans: list[AudioMutationPlan] = []
        for item, plan in zip(batch.items, batch_plan.plans):
            if item.scope == ReplacementScope.OVERWRITE:
                target_wems: set[int] = set()
                for eff in plan.effects:
                    if isinstance(eff, (StageMasterAudioIntent, StageLooseWemIntent)):
                        target_wems.add(eff.wem_id)
                    elif isinstance(eff, CopyMediaBytesIntent):
                        target_wems.add(eff.target_wem_id)

                # Cross-bank promotion: when MediaNodeTarget is on a *_data.bnk, try loading companion logic bank(s)
                for companion_name in _resolve_companion_logic_banks(item.target.bank_name):
                    if self.get_loaded_entry(companion_name) is None:
                        try:
                            self.resolve_and_parse_bank(companion_name)
                        except (
                            FileNotFoundError,
                            ValueError,
                            KeyError,
                            IndexError,
                            RuntimeError,
                            OSError,
                        ):
                            pass

                for wid in target_wems:
                    cross_refs = self.get_cross_bank_wem_references(wid)
                    for ref in cross_refs:
                        if ref.bank_name.lower() != item.target.bank_name.lower():
                            already_targeted = any(
                                p.target.bank_name.lower() == ref.bank_name.lower()
                                and (
                                    getattr(p.target, "sound_id", None) == ref.node_id
                                    or getattr(p.target, "track_id", None) == ref.node_id
                                )
                                for p in batch_plan.plans
                            ) or any(
                                p.target.bank_name.lower() == ref.bank_name.lower()
                                and (
                                    getattr(p.target, "sound_id", None) == ref.node_id
                                    or getattr(p.target, "track_id", None) == ref.node_id
                                )
                                for p in sibling_plans
                            )
                            if not already_targeted:
                                loaded_entry = self.get_loaded_entry(ref.bank_name)
                                if loaded_entry is not None:
                                    ref_bank = loaded_entry[0]
                                    track_obj = find_music_track_in_bank(ref_bank, ref.node_id)
                                    if track_obj is not None:
                                        for s_idx, src in enumerate(track_obj.sources):
                                            s_wid = getattr(src, "source_id", 0) or getattr(
                                                src, "file_id", 0
                                            )
                                            if s_wid == wid and (
                                                src.stream_type != 2
                                                or getattr(src, "plugin_id", 0x00040001)
                                                != 0x00010001
                                            ):
                                                if ref.bank_name not in banks:
                                                    banks[ref.bank_name] = ref_bank
                                                parent_seg = find_parent_segment_in_bank(
                                                    ref_bank, track_obj.id
                                                )
                                                sibling_plans.append(
                                                    AudioMutationPlan(
                                                        description=(
                                                            f"Promote MusicTrack {ref.node_id} source {s_idx} "
                                                            f"in {ref.bank_name} to streamed PCM (shared WEM {wid})"
                                                        ),
                                                        target=MusicTrackTarget(
                                                            bank_name=ref.bank_name,
                                                            track_id=ref.node_id,
                                                            source_index=s_idx,
                                                        ),
                                                        source=ExistingMediaReferenceSource(
                                                            wem_id=wid
                                                        ),
                                                        effects=(
                                                            UpdateMusicTrackNodeIntent(
                                                                bank_name=ref.bank_name,
                                                                track_id=ref.node_id,
                                                                source_index=s_idx,
                                                                new_stream_type=2,
                                                                new_source_id=wid,
                                                                new_file_id=wid,
                                                                new_plugin_id=0x00010001,
                                                            ),
                                                            SyncMusicTimelineIntent(
                                                                bank_name=ref.bank_name,
                                                                track_id=ref.node_id,
                                                                new_duration_ms=0.0,
                                                                source_index=s_idx,
                                                                parent_segment_id=(
                                                                    parent_seg.id
                                                                    if parent_seg
                                                                    else None
                                                                ),
                                                            ),
                                                            MarkBankModifiedIntent(
                                                                bank_name=ref.bank_name
                                                            ),
                                                        ),
                                                    )
                                                )
                                    else:
                                        sound_obj = find_sound_in_bank(ref_bank, ref.node_id)
                                        if sound_obj is not None and (
                                            sound_obj.stream_type != 2
                                            or getattr(sound_obj, "plugin_id", 0x00040001)
                                            != 0x00010001
                                        ):
                                            if ref.bank_name not in banks:
                                                banks[ref.bank_name] = ref_bank
                                            sibling_plans.append(
                                                AudioMutationPlan(
                                                    description=f"Promote Sound {ref.node_id} in {ref.bank_name} to streamed PCM (shared WEM {wid})",
                                                    target=SoundNodeTarget(
                                                        bank_name=ref.bank_name,
                                                        sound_id=ref.node_id,
                                                    ),
                                                    source=ExistingMediaReferenceSource(wem_id=wid),
                                                    effects=(
                                                        UpdateSoundNodeIntent(
                                                            bank_name=ref.bank_name,
                                                            sound_id=ref.node_id,
                                                            new_stream_type=2,
                                                            new_source_id=wid,
                                                            new_file_id=wid,
                                                            new_plugin_id=0x00010001,
                                                        ),
                                                        MarkBankModifiedIntent(
                                                            bank_name=ref.bank_name
                                                        ),
                                                    ),
                                                )
                                            )
        return sibling_plans

    def _collect_batch_snapshots(
        self,
        all_plans: Sequence[AudioMutationPlan],
        banks: dict[str, SoundBank],
        touched_banks: Sequence[str],
    ) -> tuple[dict[str, BankBatchSnapshot], dict[int, bytes]]:
        """Collects pre-mutation snapshots of banks, media files, and overwritten loose WEMs."""
        if self._project is None:
            return {}, {}

        bank_snapshots: dict[str, BankBatchSnapshot] = {}
        for b_name in touched_banks:
            bank = banks[b_name]
            bank_plans = [p for p in all_plans if p.target.bank_name == b_name]
            is_pure_media = all(isinstance(p.target, MediaNodeTarget) for p in bank_plans)
            was_modified = b_name.lower() in [
                b.lower() for b in getattr(self._project.manifest, "modified_banks", [])
            ]
            before_bank_bytes = bank.to_bytes()

            media_snapshots: list[MediaTargetSnapshot] = []
            if is_pure_media:
                for p in bank_plans:
                    if isinstance(p.target, MediaNodeTarget):
                        media_wid = p.target.wem_id
                        wem_file = self._project.audio_dir / f"{media_wid}.wem"
                        media_was_staged = (
                            media_wid in getattr(self._project.manifest, "staged_wems", [])
                            or wem_file.is_file()
                        )
                        media_before_bytes = wem_file.read_bytes() if wem_file.is_file() else b""
                        media_snapshots.append(
                            MediaTargetSnapshot(
                                wem_id=media_wid,
                                was_staged=media_was_staged,
                                before_bytes=media_before_bytes,
                            )
                        )

            bank_snapshots[b_name] = BankBatchSnapshot(
                bank_name=b_name,
                is_pure_media=is_pure_media,
                before_bank_bytes=before_bank_bytes,
                was_modified=was_modified,
                media_snapshots=tuple(media_snapshots),
            )

        overwritten_wem_snapshots: dict[int, bytes] = {}
        for plan in all_plans:
            for eff in plan.effects:
                wid: int | None = None
                if isinstance(eff, (StageMasterAudioIntent, StageLooseWemIntent)):
                    wid = eff.wem_id
                elif isinstance(eff, CopyMediaBytesIntent):
                    wid = eff.target_wem_id
                if wid is not None and wid not in overwritten_wem_snapshots:
                    wem_path = self._project.audio_dir / f"{wid}.wem"
                    if wem_path.is_file():
                        overwritten_wem_snapshots[wid] = wem_path.read_bytes()

        return bank_snapshots, overwritten_wem_snapshots

    def _execute_plans(
        self,
        plans: Sequence[AudioMutationPlan],
        banks: dict[str, SoundBank],
    ) -> int:
        """Executes a sequence of audio mutation plans in memory and on disk without persisting banks."""
        if self._project is None:
            return 0
        applied_count = 0
        for plan in plans:
            bank = banks[plan.target.bank_name]
            result = execute_mutation_plan(
                plan=plan,
                project=self._project,
                bank=bank,
                resolver=self._resolver,
                persist=False,
            )
            if result.success:
                applied_count += 1
        return applied_count

    def _commit_mutation_records(
        self,
        all_plans: Sequence[AudioMutationPlan],
        banks: dict[str, SoundBank],
        touched_banks: Sequence[str],
        bank_snapshots: dict[str, BankBatchSnapshot],
        overwritten_wem_snapshots: dict[int, bytes],
        before_staged_wems_all: set[int],
    ) -> list[MutationRecord]:
        """Finalizes AST saves, indexes, caches, and builds undo MutationRecords."""
        if self._project is None:
            return []

        after_staged_wems_all = set(getattr(self._project.manifest, "staged_wems", []))
        batch_newly_staged = set(after_staged_wems_all - before_staged_wems_all)

        records: list[MutationRecord] = []
        for b_name in touched_banks:
            bank = banks[b_name]
            snapshot = bank_snapshots[b_name]
            bank_plans = [p for p in all_plans if p.target.bank_name == b_name]

            bank_target_wems: set[int] = set()
            for p in bank_plans:
                for eff in p.effects:
                    if isinstance(eff, (StageMasterAudioIntent, StageLooseWemIntent)):
                        bank_target_wems.add(eff.wem_id)
                    elif isinstance(eff, CopyMediaBytesIntent):
                        bank_target_wems.add(eff.target_wem_id)

            bank_overwritten = tuple(
                (wid, overwritten_wem_snapshots[wid])
                for wid in sorted(bank_target_wems)
                if wid in overwritten_wem_snapshots
            )
            bank_staged_wems = tuple(
                sorted(
                    (batch_newly_staged | set(overwritten_wem_snapshots.keys())) & bank_target_wems
                )
            )
            batch_newly_staged -= set(bank_staged_wems)

            staged_bytes_list: list[tuple[int, bytes]] = []
            for wid in bank_staged_wems:
                wem_file = self._project.audio_dir / f"{wid}.wem"
                if wem_file.is_file():
                    data = wem_file.read_bytes()
                    staged_bytes_list.append((wid, data))
                    self._wem_cache[wid] = data

            if not snapshot.is_pure_media:
                after_bank_bytes = bank.to_bytes()
                self._project.save_bank(b_name, after_bank_bytes)
                all_node_keys = tuple(_node_key_for_target(p.target) for p in bank_plans)
                record = MutationRecord(
                    bank_name=b_name,
                    node_key=all_node_keys[0] if all_node_keys else "",
                    description=bank_plans[0].description if bank_plans else "",
                    before_bank_bytes=snapshot.before_bank_bytes,
                    after_bank_bytes=after_bank_bytes,
                    staged_wem_ids=bank_staged_wems,
                    was_bank_originally_modified=snapshot.was_modified,
                    staged_wem_bytes=tuple(staged_bytes_list),
                    node_keys=all_node_keys,
                    overwritten_wem_bytes=bank_overwritten,
                    kind="bank",
                )
                diff_res = self.compute_bank_diff(b_name, bank)
                self.index_soundbank(b_name, bank, diff_result=diff_res)
                records.append(record)
            else:
                for plan in bank_plans:
                    assert isinstance(plan.target, MediaNodeTarget)
                    media_wid = plan.target.wem_id
                    node_key = f"media:{media_wid}"
                    wem_file = self._project.audio_dir / f"{media_wid}.wem"
                    after_wem_bytes = wem_file.read_bytes() if wem_file.is_file() else b""
                    self._wem_cache[media_wid] = after_wem_bytes
                    snap = snapshot.get_media_snapshot(media_wid)
                    before_bytes = snap.before_bytes if snap is not None else b""
                    was_staged = snap.was_staged if snap is not None else False
                    record = MutationRecord(
                        bank_name=b_name,
                        node_key=node_key,
                        description=plan.description,
                        before_bank_bytes=before_bytes,
                        after_bank_bytes=b"",
                        staged_wem_ids=(media_wid,),
                        was_bank_originally_modified=was_staged,
                        staged_wem_bytes=((media_wid, after_wem_bytes),),
                        node_keys=(node_key,),
                        kind="media",
                    )
                    records.append(record)
                diff_res = self.compute_bank_diff(b_name, bank)
                self.index_soundbank(b_name, bank, diff_result=diff_res)

        if batch_newly_staged and records:
            extra_wems = tuple(sorted(batch_newly_staged))
            extra_bytes: list[tuple[int, bytes]] = []
            for wid in extra_wems:
                wem_file = self._project.audio_dir / f"{wid}.wem"
                if wem_file.is_file():
                    data = wem_file.read_bytes()
                    extra_bytes.append((wid, data))
                    self._wem_cache[wid] = data
            first = records[0]
            records[0] = replace(
                first,
                staged_wem_ids=first.staged_wem_ids + extra_wems,
                staged_wem_bytes=first.staged_wem_bytes + tuple(extra_bytes),
            )

        if hasattr(self._project, "manifest") and hasattr(self._project.manifest, "save"):
            self._project.manifest.save(self._project.manifest_path)

        return records

    def apply_batch(self, batch: MutationBatch) -> BatchOutcome:
        """Plans and applies a batch of audio mutations across soundbanks atomically."""
        if self._project is None or not batch.items:
            return BatchOutcome(applied=0, rejections=(), touched_banks=())

        banks = self._preload_batch_banks(batch)
        batch_plan = plan_batch(
            banks=banks,
            batch=batch,
            reserved_wem_ids=self._collect_reserved_wem_ids(),
        )
        if not batch_plan.plans:
            return BatchOutcome(applied=0, rejections=batch_plan.rejections, touched_banks=())

        sibling_plans = self._find_sibling_promotion_plans(batch, batch_plan, banks)
        all_plans = list(batch_plan.plans) + sibling_plans

        touched_banks: list[str] = []
        for plan in all_plans:
            b_name = plan.target.bank_name
            if b_name not in touched_banks:
                touched_banks.append(b_name)

        bank_snapshots, overwritten_wem_snapshots = self._collect_batch_snapshots(
            all_plans=all_plans,
            banks=banks,
            touched_banks=touched_banks,
        )
        before_staged_wems_all = set(getattr(self._project.manifest, "staged_wems", []))

        applied_count = self._execute_plans(batch_plan.plans, banks)
        self._execute_plans(sibling_plans, banks)

        if applied_count == 0:
            return BatchOutcome(applied=0, rejections=batch_plan.rejections, touched_banks=())

        records = self._commit_mutation_records(
            all_plans=all_plans,
            banks=banks,
            touched_banks=touched_banks,
            bank_snapshots=bank_snapshots,
            overwritten_wem_snapshots=overwritten_wem_snapshots,
            before_staged_wems_all=before_staged_wems_all,
        )

        txn_node_keys = tuple(
            k for r in records for k in (r.node_keys or ((r.node_key,) if r.node_key else ()))
        )
        txn = MutationTransaction(
            description=batch.description,
            records=tuple(records),
            node_keys=txn_node_keys,
        )
        self._mutation_undo_stack.append(txn)
        self._mutation_redo_stack.clear()

        return BatchOutcome(
            applied=applied_count,
            rejections=batch_plan.rejections,
            touched_banks=tuple(touched_banks),
        )

    def apply_sound_mutation(
        self,
        bank_name: str,
        sound_id: int,
        source: Any,
        scope: ReplacementScope = ReplacementScope.OVERWRITE,
        forked_wem_id: int | None = None,
    ) -> tuple[SoundBank, BankDiffResult | None, str] | None:
        """Plans and executes a sound node mutation, updating undo history and session cache."""
        target = SoundNodeTarget(bank_name=bank_name, sound_id=sound_id)
        batch = MutationBatch(
            description=f"Mutate sound {sound_id} in {bank_name} ({scope.value})",
            items=(
                BatchItem(
                    target=target,
                    source=source,
                    scope=scope,
                    forked_wem_id=forked_wem_id,
                ),
            ),
        )
        outcome = self.apply_batch(batch)
        if outcome.applied > 0:
            entry = self.get_loaded_entry(bank_name)
            if entry is not None:
                bank, _, diff_res = entry
                return (bank, diff_res, f"hirc:{sound_id}")
        return None

    def apply_media_mutation(
        self, bank_name: str, wem_id: int, source: Any
    ) -> tuple[SoundBank, BankDiffResult | None, str] | None:
        """Plans and executes an embedded or loose media replacement, updating undo history and session cache."""
        target = MediaNodeTarget(bank_name=bank_name, wem_id=wem_id)
        batch = MutationBatch(
            description=f"Mutate media WEM {wem_id} in {bank_name}",
            items=(BatchItem(target=target, source=source),),
        )
        outcome = self.apply_batch(batch)
        if outcome.applied > 0:
            entry = self.get_loaded_entry(bank_name)
            if entry is not None:
                bank, _, diff_res = entry
                return (bank, diff_res, f"media:{wem_id}")
        return None

    def apply_audio_enhancements(
        self,
        targets: Sequence[MutationTarget],
        modifier_chain: AudioModifierChain,
    ) -> BatchOutcome:
        """
        Applies an AudioModifierChain in-place to target nodes, staging modified WAV and WEM assets.
        Records an atomic transaction in undo history.
        """
        if not self._project or not targets:
            return BatchOutcome(applied=0, rejections=(), touched_banks=())

        from src.compiler.audio_modifiers import apply_modifiers_to_wav_bytes
        from src.engine.audio_export import resolve_node_wav_bytes

        items: list[BatchItem] = []
        source_audio_dir = self._project.source_audio_dir
        source_audio_dir.mkdir(parents=True, exist_ok=True)

        for target in targets:
            entry = self.get_loaded_entry(target.bank_name)
            if entry is None:
                continue
            bank, graph_index, _ = entry

            node_key: str
            if isinstance(target, MediaNodeTarget):
                node_key = f"media:{target.wem_id}"
            elif isinstance(target, SoundNodeTarget):
                node_key = f"hirc:{target.sound_id}"
            elif isinstance(target, MusicTrackTarget):
                track = find_music_track_in_bank(bank, target.track_id)
                if track is not None and 0 <= target.source_index < len(track.sources):
                    src_desc = track.sources[target.source_index]
                    target_wem = getattr(src_desc, "source_id", 0) or getattr(
                        src_desc, "file_id", 0
                    )
                    node_key = f"media:{target_wem}"
                else:
                    node_key = f"hirc:{target.track_id}"
            else:
                continue

            try:
                wav_bytes = resolve_node_wav_bytes(
                    bank,
                    node_key,
                    resolver=self._resolver,
                    graph_index=graph_index,
                    companion_cache=self._companion_banks,
                )
            except (ValueError, FileNotFoundError, RuntimeError, OSError):
                continue

            modified_wav = apply_modifiers_to_wav_bytes(wav_bytes, modifier_chain)
            temp_filename = f"enhanced_{_node_key_for_target(target).replace(':', '_')}.wav"
            temp_path = source_audio_dir / temp_filename
            temp_path.write_bytes(modified_wav)

            items.append(BatchItem(target=target, source=ExternalFileSource(file_path=temp_path)))

        if not items:
            return BatchOutcome(applied=0, rejections=(), touched_banks=())

        batch = MutationBatch(
            description=f"Enhance {len(items)} audio target(s)",
            items=tuple(items),
        )
        return self.apply_batch(batch)

    def undo_mutation(self) -> tuple[tuple[str, ...], str | None] | None:
        """Reverses the last applied audio mutation transaction."""
        if not self.can_undo_mutation or self._project is None:
            return None

        entry = self._mutation_undo_stack.pop()
        if isinstance(entry, MutationRecord):
            txn = MutationTransaction(description=entry.description, records=(entry,))
        else:
            txn = entry

        try:
            for record in reversed(txn.records):
                if record.is_media:
                    for wid in record.staged_wem_ids:
                        if record.was_bank_originally_modified:
                            self._project.stage_wem(wid, record.before_bank_bytes)
                        else:
                            self._project.revert_wem(wid)

                    bank_tuple = self.get_loaded_entry(record.bank_name)
                    if bank_tuple:
                        bank = bank_tuple[0]
                    else:
                        bank = self.resolve_and_parse_bank(record.bank_name)[0]
                    diff_res = self.compute_bank_diff(record.bank_name, bank)
                    self.index_soundbank(record.bank_name, bank, diff_result=diff_res)
                else:
                    bank = SoundBank.from_bytes(record.before_bank_bytes)
                    overwritten_dict = dict(record.overwritten_wem_bytes)
                    for wid in record.staged_wem_ids:
                        if wid in overwritten_dict:
                            self._project.stage_wem(wid, overwritten_dict[wid])
                            self._wem_cache[wid] = overwritten_dict[wid]
                        else:
                            wem_file = self._project.audio_dir / f"{wid}.wem"
                            if wem_file.is_file() and wid not in self._wem_cache:
                                self._wem_cache[wid] = wem_file.read_bytes()
                            self._project.revert_wem(wid)

                    if not record.was_bank_originally_modified:
                        self._project.revert_bank(record.bank_name)
                    else:
                        self._project.save_bank(record.bank_name, record.before_bank_bytes)

                    diff_res = self.compute_bank_diff(record.bank_name, bank)
                    self.index_soundbank(record.bank_name, bank, diff_result=diff_res)

            if hasattr(self._project, "manifest") and hasattr(self._project.manifest, "save"):
                self._project.manifest.save(self._project.manifest_path)

            self._mutation_redo_stack.append(txn)
            primary_bank = txn.records[0].bank_name if txn.records else ""
            unique_banks = list(dict.fromkeys(r.bank_name for r in txn.records))
            if primary_bank in unique_banks and len(unique_banks) > 1:
                unique_banks.remove(primary_bank)
                unique_banks.append(primary_bank)
            touched = tuple(unique_banks)
            primary_key = txn.records[0].node_key if txn.records else None
            return (touched, primary_key)
        except Exception:
            logger.exception("Failed to undo audio mutation")
            self._mutation_undo_stack.append(entry)
            return None

    @property
    def last_undone_node_keys(self) -> tuple[str, ...]:
        """Node keys affected by the most recent undo operation."""
        if not self._mutation_redo_stack:
            return ()
        return self._mutation_redo_stack[-1].all_node_keys

    @property
    def last_redone_node_keys(self) -> tuple[str, ...]:
        """Node keys affected by the most recent redo operation."""
        if not self._mutation_undo_stack:
            return ()
        return self._mutation_undo_stack[-1].all_node_keys

    def redo_mutation(self) -> tuple[tuple[str, ...], str | None] | None:
        """Re-applies the last undone audio mutation transaction."""
        if not self.can_redo_mutation or self._project is None:
            return None

        entry = self._mutation_redo_stack.pop()
        if isinstance(entry, MutationRecord):
            txn = MutationTransaction(description=entry.description, records=(entry,))
        else:
            txn = entry

        try:
            for record in txn.records:
                if record.is_media:
                    wem_dict = dict(record.staged_wem_bytes)
                    for wid in record.staged_wem_ids:
                        data = wem_dict.get(wid) or self._wem_cache.get(wid)
                        if data:
                            self._project.stage_wem(wid, data)
                        elif (self._project.audio_dir / f"{wid}.wem").is_file():
                            if wid not in self._project.manifest.staged_wems:
                                self._project.manifest.staged_wems.append(wid)

                    bank_tuple = self.get_loaded_entry(record.bank_name)
                    if bank_tuple:
                        bank = bank_tuple[0]
                    else:
                        bank = self.resolve_and_parse_bank(record.bank_name)[0]
                    diff_res = self.compute_bank_diff(record.bank_name, bank)
                    self.index_soundbank(record.bank_name, bank, diff_result=diff_res)
                else:
                    bank = SoundBank.from_bytes(record.after_bank_bytes)
                    wem_dict = dict(record.staged_wem_bytes)
                    for wid in record.staged_wem_ids:
                        data = wem_dict.get(wid) or self._wem_cache.get(wid)
                        if data:
                            self._project.stage_wem(wid, data)
                        elif wid == 1:
                            self._project.stage_wem(
                                1, build_silent_pcm_wem_bytes(duration_ms=50, sample_rate=32000)
                            )
                        elif (self._project.audio_dir / f"{wid}.wem").is_file():
                            if wid not in self._project.manifest.staged_wems:
                                self._project.manifest.staged_wems.append(wid)

                    self._project.save_bank(record.bank_name, record.after_bank_bytes)

                    diff_res = self.compute_bank_diff(record.bank_name, bank)
                    self.index_soundbank(record.bank_name, bank, diff_result=diff_res)

            if hasattr(self._project, "manifest") and hasattr(self._project.manifest, "save"):
                self._project.manifest.save(self._project.manifest_path)

            self._mutation_undo_stack.append(txn)
            primary_bank = txn.records[0].bank_name if txn.records else ""
            unique_banks = list(dict.fromkeys(r.bank_name for r in txn.records))
            if primary_bank in unique_banks and len(unique_banks) > 1:
                unique_banks.remove(primary_bank)
                unique_banks.append(primary_bank)
            touched = tuple(unique_banks)
            primary_key = txn.records[0].node_key if txn.records else None
            return (touched, primary_key)
        except Exception:
            logger.exception("Failed to redo audio mutation")
            self._mutation_redo_stack.append(entry)
            return None

    @staticmethod
    def extract_sound_wem_id(sound: Any) -> int:
        """Extracts the underlying WEM ID from a CAkSound object."""
        if hasattr(sound, "bank_source_data"):
            bsd = sound.bank_source_data
            if hasattr(bsd, "media_information"):
                return int(getattr(bsd.media_information, "source_id", 0))
        return int(getattr(sound, "source_id", 0) or getattr(sound, "file_id", 0))

    def build_local_and_global_catalog_providers(
        self, bank_name: str
    ) -> tuple[tuple[Any, ...], Callable[[], Sequence[Any]]]:
        """Builds local bank catalog items and lazy global library catalog provider for replacement dialog."""
        bank_name = str(getattr(bank_name, "name", bank_name))
        if not isinstance(bank_name, str) or not bank_name:
            return ((), lambda: ())

        bank = self.get_loaded_bank(bank_name)
        if bank is None:
            try:
                entry = self.resolve_and_parse_bank(bank_name)
                bank = entry[0]
            except Exception:
                return ((), lambda: ())
        if bank is None:
            return ((), lambda: ())

        local_catalog = tuple(
            build_audio_catalog_for_bank(
                bank=bank,
                bank_name=bank_name,
                project=self._project,
                sound_db=self._sound_db,
                scope=CatalogScope.LOCAL_BANK_ONLY,
            )
        )

        def catalog_provider() -> Sequence[Any]:
            return build_audio_catalog_for_bank(
                bank=bank,
                bank_name=bank_name,
                project=self._project,
                sound_db=self._sound_db,
                scope=CatalogScope.FULL_LIBRARY,
            )

        return (local_catalog, catalog_provider)
