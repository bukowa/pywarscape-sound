from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from src.compiler.pfh4_pack import extract_pfh4_file, read_pfh4_index
from src.models.db_schemas import TABLE_SCHEMAS
from src.workspace.manifest import DependencyPackInfo
from src.workspace.storage import ProjectStorage

if TYPE_CHECKING:
    from src.workspace.project import AudioProject


class ConflictType(Enum):
    BANK_MODIFIED = "bank_modified"
    WEM_STAGED = "wem_staged"
    EVENT_DB_MODIFIED = "event_db_modified"


class ResolutionAction(Enum):
    KEEP_LOCAL = "keep_local"
    OVERWRITE_LOCAL = "overwrite_local"


@dataclass(slots=True)
class ImportConflict:
    virtual_path: str
    conflict_type: ConflictType
    local_size: int
    incoming_size: int
    resolution: ResolutionAction = ResolutionAction.KEEP_LOCAL


@dataclass(slots=True)
class ImportPlan:
    pack_name: str
    source_path: str
    priority: int
    sha256: str
    safe_audio_files: list[tuple[str, bytes]] = field(default_factory=list)
    safe_db_files: list[tuple[str, bytes]] = field(default_factory=list)
    conflicts: list[ImportConflict] = field(default_factory=list)
    conflict_payloads: dict[str, bytes] = field(default_factory=dict)


def _validate_pack_entry_path(virtual_path: str) -> str:
    """Validates pack entry path, rejecting traversal and absolute paths, and normalizes to POSIX."""
    if not virtual_path:
        raise ValueError("Pack entry path cannot be empty")
    if ":" in virtual_path or virtual_path.startswith("/") or virtual_path.startswith("\\"):
        raise ValueError(
            f"Pack entry path cannot be absolute or contain drive letter: {virtual_path!r}"
        )
    posix_path = virtual_path.replace("\\", "/").strip("/")
    parts = posix_path.split("/")
    if any(p in (".", "..") for p in parts):
        raise ValueError(f"Pack entry path cannot contain traversal (..): {virtual_path!r}")
    return posix_path


class DependencyManager:
    """Manages external mod pack dependencies and selective ingestion for an AudioProject."""

    def __init__(self, project: AudioProject) -> None:
        self.project = project

    def plan_import(self, pack_path: Path | str, priority: int | None = None) -> ImportPlan:
        """Inspects pack, extracts relevant entry metadata, and generates an ImportPlan."""
        p = Path(pack_path)
        if not p.is_file():
            raise FileNotFoundError(f"Pack file not found: {p}")

        # Compute SHA-256
        hasher = hashlib.sha256()
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        sha256_hex = hasher.hexdigest()

        # Determine priority
        if priority is None:
            existing = next(
                (d for d in self.project.manifest.dependencies if d.name.lower() == p.name.lower()),
                None,
            )
            if existing is not None:
                calc_priority = existing.priority
            else:
                calc_priority = (
                    max((d.priority for d in self.project.manifest.dependencies), default=-1) + 1
                )
        else:
            calc_priority = int(priority)

        entries = read_pfh4_index(p)
        safe_audio: list[tuple[str, bytes]] = []
        safe_db: list[tuple[str, bytes]] = []
        conflicts: list[ImportConflict] = []
        conflict_payloads: dict[str, bytes] = {}

        # Cache recognized DB tables from schemas
        from src.workspace.project import AudioProject as AP

        known_table_names = {name.lower() for name, _ in TABLE_SCHEMAS.keys()}
        known_table_keys = {AP.normalize_table_name(name) for name, _ in TABLE_SCHEMAS.keys()}

        for entry in entries:
            norm_posix = _validate_pack_entry_path(entry.path)
            lower_path = norm_posix.lower()

            # 1. Audio classification
            is_audio = (
                lower_path.startswith("audio/")
                or lower_path.endswith(".bnk")
                or lower_path.endswith(".wem")
                or lower_path.endswith("event_data.dat")
            )

            if is_audio:
                audio_vpath = (
                    norm_posix if lower_path.startswith("audio/") else f"audio/{norm_posix}"
                )
                data = extract_pfh4_file(p, entry)

                # SoundBank conflict check
                if audio_vpath.lower().endswith(".bnk"):
                    bank_filename = Path(audio_vpath).name.lower()
                    clean_bank = (
                        bank_filename if bank_filename.endswith(".bnk") else f"{bank_filename}.bnk"
                    )
                    is_bank_mod = any(
                        (b.lower() if b.lower().endswith(".bnk") else f"{b.lower()}.bnk")
                        == clean_bank
                        for b in self.project.manifest.modified_banks
                    )
                    if is_bank_mod:
                        local_file = self.project.audio_dir / clean_bank
                        local_sz = local_file.stat().st_size if local_file.is_file() else 0
                        if not local_file.is_file() and self.project.audio_dir.is_dir():
                            for f in self.project.audio_dir.iterdir():
                                if f.name.lower() == clean_bank and f.is_file():
                                    local_sz = f.stat().st_size
                                    break
                        conflict = ImportConflict(
                            virtual_path=audio_vpath,
                            conflict_type=ConflictType.BANK_MODIFIED,
                            local_size=local_sz,
                            incoming_size=len(data),
                            resolution=ResolutionAction.KEEP_LOCAL,
                        )
                        conflicts.append(conflict)
                        conflict_payloads[audio_vpath] = data
                        continue

                # Streamed / loose WEM conflict check
                elif audio_vpath.lower().endswith(".wem"):
                    try:
                        wid = int(Path(audio_vpath).stem)
                    except ValueError:
                        wid = None
                    if wid is not None and wid in self.project.manifest.staged_wems:
                        local_file = self.project.audio_dir / f"{wid}.wem"
                        local_sz = local_file.stat().st_size if local_file.is_file() else 0
                        conflict = ImportConflict(
                            virtual_path=audio_vpath,
                            conflict_type=ConflictType.WEM_STAGED,
                            local_size=local_sz,
                            incoming_size=len(data),
                            resolution=ResolutionAction.KEEP_LOCAL,
                        )
                        conflicts.append(conflict)
                        conflict_payloads[audio_vpath] = data
                        continue

                # Event Database conflict check
                elif Path(audio_vpath).name.lower() == "event_data.dat":
                    if self.project.manifest.has_custom_event_db:
                        local_file = self.project.audio_dir / "event_data.dat"
                        local_sz = local_file.stat().st_size if local_file.is_file() else 0
                        conflict = ImportConflict(
                            virtual_path=audio_vpath,
                            conflict_type=ConflictType.EVENT_DB_MODIFIED,
                            local_size=local_sz,
                            incoming_size=len(data),
                            resolution=ResolutionAction.KEEP_LOCAL,
                        )
                        conflicts.append(conflict)
                        conflict_payloads[audio_vpath] = data
                        continue

                # Safe audio file
                safe_audio.append((audio_vpath, data))
                continue

            # 2. Database table classification
            parts = norm_posix.split("/")
            if parts[0].lower() == "db" and len(parts) >= 2:
                table_dir = parts[1].lower()
                table_key = AP.normalize_table_name(table_dir)
                if table_dir in known_table_names or table_key in known_table_keys:
                    data = extract_pfh4_file(p, entry)
                    safe_db.append((norm_posix, data))

        return ImportPlan(
            pack_name=p.name,
            source_path=str(p),
            priority=calc_priority,
            sha256=sha256_hex,
            safe_audio_files=safe_audio,
            safe_db_files=safe_db,
            conflicts=conflicts,
            conflict_payloads=conflict_payloads,
        )

    def execute_import(
        self,
        plan: ImportPlan,
        resolutions: dict[str, ResolutionAction] | None = None,
    ) -> None:
        """Applies the import plan: extracts to dependencies/<name>/, applies conflict decisions, updates manifest, and saves project."""
        dep_dir = self.project.get_dependency_dir(plan.pack_name)
        if dep_dir.is_dir():
            shutil.rmtree(dep_dir)
        dep_dir.mkdir(parents=True, exist_ok=True)

        # 1. Extract safe audio files
        for vpath, data in plan.safe_audio_files:
            dest = dep_dir / vpath
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)

        # 2. Extract safe database tables
        for vpath, data in plan.safe_db_files:
            dest = dep_dir / vpath
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)

        # 3. Extract conflict files into dependencies/<name>/ (strictly read-only references)
        for conflict in plan.conflicts:
            vpath = conflict.virtual_path
            data = plan.conflict_payloads[vpath]
            dest = dep_dir / vpath
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)

        # 4. Register or update DependencyPackInfo in manifest
        all_audio = sorted(
            [vpath for vpath, _ in plan.safe_audio_files] + [c.virtual_path for c in plan.conflicts]
        )
        all_db = sorted([vpath for vpath, _ in plan.safe_db_files])
        now_iso = datetime.now(UTC).isoformat()

        existing_dep = next(
            (
                d
                for d in self.project.manifest.dependencies
                if d.name.lower() == plan.pack_name.lower()
            ),
            None,
        )
        if existing_dep is not None:
            existing_dep.name = plan.pack_name
            existing_dep.source_path = plan.source_path
            existing_dep.priority = plan.priority
            existing_dep.imported_at = now_iso
            existing_dep.sha256 = plan.sha256
            existing_dep.extracted_audio_files = all_audio
            existing_dep.extracted_db_tables = all_db
        else:
            self.project.manifest.dependencies.append(
                DependencyPackInfo(
                    name=plan.pack_name,
                    source_path=plan.source_path,
                    priority=plan.priority,
                    imported_at=now_iso,
                    sha256=plan.sha256,
                    extracted_audio_files=all_audio,
                    extracted_db_tables=all_db,
                )
            )

        ProjectStorage.save_project(self.project)

    def reorder_dependencies(self, new_order: list[str]) -> None:
        """Updates load order priorities across active dependencies in project manifest and saves project."""
        if len(new_order) != len(self.project.manifest.dependencies):
            raise ValueError(
                f"Expected {len(self.project.manifest.dependencies)} dependencies in new_order, got {len(new_order)}"
            )
        if len(set(name.lower() for name in new_order)) != len(new_order):
            raise ValueError("new_order cannot contain duplicate dependencies")

        active_map = {d.name.lower(): d for d in self.project.manifest.dependencies}
        for name in new_order:
            if name.lower() not in active_map:
                raise ValueError(f"Dependency '{name}' not found in project")

        priority_map = {name.lower(): idx for idx, name in enumerate(new_order)}
        for dep in self.project.manifest.dependencies:
            dep.priority = priority_map[dep.name.lower()]

        self.project.manifest.dependencies.sort(key=lambda d: d.priority)
        ProjectStorage.save_project(self.project)

    def remove_dependency(self, pack_name: str) -> None:
        """Unregisters dependency, removes dependencies/<pack_name>/ from disk, and saves project."""
        pack_lower = pack_name.lower()
        matched = [d for d in self.project.manifest.dependencies if d.name.lower() == pack_lower]
        if not matched:
            raise ValueError(f"Dependency '{pack_name}' not found in project")

        target_dep = matched[0]
        self.project.manifest.dependencies = [
            d for d in self.project.manifest.dependencies if d.name.lower() != pack_lower
        ]

        dep_dir = self.project.get_dependency_dir(target_dep.name)
        if dep_dir.is_dir():
            shutil.rmtree(dep_dir)

        ProjectStorage.save_project(self.project)
