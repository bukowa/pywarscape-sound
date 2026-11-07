"""Headless domain façade managing SoundBank ASTs, layered asset resolution, and mutations."""

from __future__ import annotations

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
    UpdateSoundNodeIntent,
    WemReference,
)
from src.engine.planner import plan_batch
from src.engine.ports import AssetResolverPort, AudioProjectPort

logger = logging.getLogger(__name__)

__all__ = ["BatchOutcome", "WorkspaceSession"]


def _node_key_for_target(target: Any) -> str:
    if isinstance(target, SoundNodeTarget):
        return f"hirc:{target.sound_id}"
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
        Returns True if reverted.
        """
        if self._project is None:
            return False
        wid = int(str(wem_id).removesuffix(".wem"))
        res = self._project.revert_wem_completely(wid)
        self._wem_cache.pop(wid, None)
        return res

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

    def get_cross_bank_wem_references(self, wem_id: int) -> tuple[WemReference, ...]:
        """Returns all HIRC node references to wem_id across all currently loaded SoundBanks."""
        if not wem_id or wem_id <= 0:
            return ()

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
        return plan_batch(banks=banks, batch=batch)

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
        """Finds cross-bank sibling sound nodes referencing overwritten WEMs to promote to streamed."""
        sibling_plans: list[AudioMutationPlan] = []
        for item, plan in zip(batch.items, batch_plan.plans):
            if item.scope == ReplacementScope.OVERWRITE:
                target_wems: set[int] = set()
                for eff in plan.effects:
                    if isinstance(eff, (StageMasterAudioIntent, StageLooseWemIntent)):
                        target_wems.add(eff.wem_id)
                    elif isinstance(eff, CopyMediaBytesIntent):
                        target_wems.add(eff.target_wem_id)

                for wid in target_wems:
                    cross_refs = self.get_cross_bank_wem_references(wid)
                    for ref in cross_refs:
                        if (
                            ref.is_embedded
                            and ref.bank_name.lower() != item.target.bank_name.lower()
                        ):
                            already_targeted = any(
                                p.target.bank_name.lower() == ref.bank_name.lower()
                                and getattr(p.target, "sound_id", None) == ref.node_id
                                for p in batch_plan.plans
                            )
                            if not already_targeted:
                                loaded_entry = self.get_loaded_entry(ref.bank_name)
                                if loaded_entry is not None:
                                    if ref.bank_name not in banks:
                                        banks[ref.bank_name] = loaded_entry[0]
                                    sibling_plans.append(
                                        AudioMutationPlan(
                                            description=f"Promote embedded Sound {ref.node_id} in {ref.bank_name} to streamed (shared WEM {wid})",
                                            target=SoundNodeTarget(
                                                bank_name=ref.bank_name, sound_id=ref.node_id
                                            ),
                                            source=ExistingMediaReferenceSource(wem_id=wid),
                                            effects=(
                                                UpdateSoundNodeIntent(
                                                    bank_name=ref.bank_name,
                                                    sound_id=ref.node_id,
                                                    new_stream_type=2,
                                                    new_source_id=wid,
                                                    new_file_id=wid,
                                                ),
                                                MarkBankModifiedIntent(bank_name=ref.bank_name),
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
        batch_plan = plan_batch(banks=banks, batch=batch)
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
            temp_filename = f"enhanced_{node_key.replace(':', '_')}.wav"
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
            touched = tuple(dict.fromkeys(r.bank_name for r in txn.records))
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
            touched = tuple(dict.fromkeys(r.bank_name for r in txn.records))
            primary_key = txn.records[-1].node_key if txn.records else None
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
