"""Mod project workspace lifecycle, storage, and layered asset resolution."""

from __future__ import annotations

import logging
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.workspace.cache import GameCache
from src.workspace.manifest import ProjectManifest, SoundLibraryRef
from src.workspace.sound_library import encode_library_path, resolve_library_root

if TYPE_CHECKING:
    from src.models.catalog import AudioMetadataCatalog
    from src.workspace.resolver import AssetResolver

logger = logging.getLogger(__name__)


class AudioProject:
    """Mod project workspace directory and file layout on disk."""

    def __init__(
        self,
        root_dir: Path | str,
        manifest: ProjectManifest,
        cache: GameCache | None = None,
    ) -> None:
        self.root_dir = Path(root_dir)
        self.manifest = manifest
        self.cache = cache or GameCache(manifest.game)

    @property
    def pack_root(self) -> Path:
        return self.root_dir / "pack_root"

    @property
    def audio_dir(self) -> Path:
        return self.root_dir / "pack_root" / "audio"

    @property
    def source_audio_dir(self) -> Path:
        return self.root_dir / "source_audio"

    @property
    def db_dir(self) -> Path:
        return self.root_dir / "db"

    @property
    def dependencies_dir(self) -> Path:
        return self.root_dir / "dependencies"

    @property
    def manifest_path(self) -> Path:
        return self.root_dir / "project.json"

    @property
    def resolver(self) -> AssetResolver:
        from src.workspace.resolver import AssetResolver

        return AssetResolver(self, self.cache)

    def get_dependency_dir(self, pack_name: str) -> Path:
        """Returns absolute path to a specific dependency's unpacked directory."""
        return self.dependencies_dir / pack_name

    def save_manifest(self) -> None:
        """Persists current in-memory manifest to project manifest.json."""
        self.root_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.root_dir / "project.json.tmp"
        tmp_path.write_text(self.manifest.to_json(indent=2), encoding="utf-8")
        tmp_path.replace(self.manifest_path)

    def add_sound_library(self, path: Path | str, name: str | None = None) -> SoundLibraryRef:
        """Registers a new sound library folder in the project manifest."""
        chosen_path = Path(path)
        encoded = encode_library_path(self.root_dir, chosen_path)
        target_root = resolve_library_root(
            self.root_dir, SoundLibraryRef(id="probe", name="probe", path=encoded)
        )

        for existing in self.manifest.sound_libraries:
            if (
                existing.path == encoded
                or resolve_library_root(self.root_dir, existing) == target_root
            ):
                raise ValueError(f"Sound library path already registered: {encoded}")

        if name is None:
            lib_name = chosen_path.name or target_root.name or "Sound Library"
        else:
            lib_name = name.strip()

        lib_id = f"lib_{uuid.uuid4().hex[:8]}"
        ref = SoundLibraryRef(id=lib_id, name=lib_name, path=encoded)
        self.manifest.sound_libraries.append(ref)
        self.save_manifest()
        return ref

    def remove_sound_library(self, library_id: str) -> bool:
        """Removes a sound library reference by id from the manifest."""
        for lib in self.manifest.sound_libraries:
            if lib.id == library_id:
                self.manifest.sound_libraries.remove(lib)
                self.save_manifest()
                return True
        return False

    def rename_sound_library(self, library_id: str, new_name: str) -> bool:
        """Renames a sound library reference by id."""
        for idx, lib in enumerate(self.manifest.sound_libraries):
            if lib.id == library_id:
                updated = SoundLibraryRef(id=lib.id, name=new_name, path=lib.path)
                self.manifest.sound_libraries[idx] = updated
                self.save_manifest()
                return True
        return False

    def list_sound_libraries(self) -> tuple[SoundLibraryRef, ...]:
        """Returns all registered sound libraries as an immutable tuple."""
        return tuple(self.manifest.sound_libraries)

    def stage_source_audio(self, src_path: Path | str, wem_id: int) -> str:
        """Copies external audio source into source_audio/ and records relative path."""
        self.source_audio_dir.mkdir(parents=True, exist_ok=True)
        src = Path(src_path).resolve()
        dest = (self.source_audio_dir / Path(src_path).name).resolve()
        if src != dest:
            shutil.copy2(src, dest)
        rel_posix = f"source_audio/{dest.name}"
        self.manifest.source_audio[int(wem_id)] = rel_posix
        self.save_manifest()
        return rel_posix

    def get_source_audio_path(self, wem_id: int | str) -> Path | None:
        """Resolves absolute path to master source audio file if present."""
        wid = int(str(wem_id).removesuffix(".wem"))
        rel = self.manifest.source_audio.get(wid)
        if rel is None:
            return None
        p = self.root_dir / rel
        return p if p.is_file() else None

    def stage_wem(self, wem_id: int | str, data: bytes) -> Path:
        """Writes loose/streamed .wem file into pack_root/audio/ and tracks in manifest."""
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        wid = int(str(wem_id).removesuffix(".wem"))
        out_path = self.audio_dir / f"{wid}.wem"
        out_path.write_bytes(data)
        if wid not in self.manifest.staged_wems:
            self.manifest.staged_wems.append(wid)
            self.save_manifest()
        return out_path

    def revert_wem(self, wem_id: int | str) -> bool:
        """Removes loose .wem file from pack_root/audio/ and unregisters from manifest."""
        wid = int(str(wem_id).removesuffix(".wem"))
        if wid not in self.manifest.staged_wems:
            return False
        self.manifest.staged_wems.remove(wid)
        wem_file = self.audio_dir / f"{wid}.wem"
        if wem_file.is_file():
            wem_file.unlink()
        self.save_manifest()
        return True

    def save_bank(self, bank_name: str, data: bytes) -> Path:
        """Writes modified .bnk into pack_root/audio/ and tracks normalized name in modified_banks."""
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        clean = (bank_name if bank_name.lower().endswith(".bnk") else f"{bank_name}.bnk").lower()
        out_path = self.audio_dir / clean
        out_path.write_bytes(data)
        if clean not in self.manifest.modified_banks:
            self.manifest.modified_banks.append(clean)
            self.save_manifest()
        return out_path

    def revert_bank(self, bank_name: str) -> bool:
        """Removes modified bank from pack_root/audio/ and unmarks from manifest."""
        clean = (bank_name if bank_name.lower().endswith(".bnk") else f"{bank_name}.bnk").lower()
        matching = [b for b in self.manifest.modified_banks if b.lower() == clean]
        if not matching:
            return False

        for b in matching:
            self.manifest.modified_banks.remove(b)
            bank_file = self.audio_dir / b
            if bank_file.is_file():
                bank_file.unlink()
        self.save_manifest()
        return True

    def save_database(self, data: bytes) -> Path:
        """Writes modified event_data.dat to pack_root/audio/ and flags in manifest."""
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.audio_dir / "event_data.dat"
        out_path.write_bytes(data)
        self.manifest.has_custom_event_db = True
        self.save_manifest()
        return out_path

    def revert_database(self) -> bool:
        """Deletes modified event_data.dat and unsets manifest flag."""
        if not self.manifest.has_custom_event_db:
            return False
        db_file = self.audio_dir / "event_data.dat"
        if db_file.is_file():
            db_file.unlink()
        self.manifest.has_custom_event_db = False
        return True

    def reconcile_manifest_with_disk(self) -> bool:
        """
        Synchronizes project.json with physical files in pack_root/audio/.
        Adds missing physical .bnk, loose .wem, and event_data.dat to manifest;
        prunes manifest entries whose files have been removed from disk.
        Returns True if any changes were made and saved.
        """
        modified = False
        if not self.audio_dir.is_dir():
            if self.manifest.modified_banks:
                self.manifest.modified_banks.clear()
                modified = True
            if self.manifest.staged_wems:
                self.manifest.staged_wems.clear()
                modified = True
            if self.manifest.has_custom_event_db:
                self.manifest.has_custom_event_db = False
                modified = True
            if self.manifest.source_audio:
                self.manifest.source_audio.clear()
                modified = True
            if modified:
                self.save_manifest()
            return modified

        physical_banks: set[str] = set()
        physical_wems: set[int] = set()
        has_physical_event_db = False

        for f in self.audio_dir.iterdir():
            if not f.is_file() or f.name.endswith(".tmp"):
                continue
            name_lower = f.name.lower()
            if name_lower.endswith(".bnk"):
                physical_banks.add(f.name.lower())
            elif name_lower.endswith(".wem"):
                stem = f.stem
                if stem.isdigit():
                    physical_wems.add(int(stem))
            elif name_lower == "event_data.dat":
                has_physical_event_db = True

        # Reconcile modified_banks
        current_banks_lower = {b.lower(): b for b in self.manifest.modified_banks}
        new_banks = [b for b in self.manifest.modified_banks if b.lower() in physical_banks]
        if len(new_banks) != len(self.manifest.modified_banks):
            modified = True
        for pb in sorted(physical_banks):
            if pb not in current_banks_lower:
                new_banks.append(pb)
                modified = True
        if modified or new_banks != self.manifest.modified_banks:
            self.manifest.modified_banks = new_banks
            modified = True

        # Reconcile staged_wems
        current_wems_set = set(self.manifest.staged_wems)
        new_wems = [w for w in self.manifest.staged_wems if w in physical_wems]
        if len(new_wems) != len(self.manifest.staged_wems):
            modified = True
        for pw in sorted(physical_wems):
            if pw not in current_wems_set:
                new_wems.append(pw)
                modified = True
        if modified or new_wems != self.manifest.staged_wems:
            self.manifest.staged_wems = new_wems
            modified = True

        # Reconcile source_audio: prune entries whose WEM is no longer staged on disk
        for wid in list(self.manifest.source_audio.keys()):
            if wid not in physical_wems:
                src_rel = self.manifest.source_audio.pop(wid)
                src_file = self.root_dir / src_rel
                if src_file.is_file() and not any(
                    r == src_rel for r in self.manifest.source_audio.values()
                ):
                    try:
                        src_file.unlink()
                    except OSError:
                        pass
                modified = True

        # Reconcile event_data.dat
        if self.manifest.has_custom_event_db != has_physical_event_db:
            self.manifest.has_custom_event_db = has_physical_event_db
            modified = True

        if modified:
            self.save_manifest()
        return modified

    def revert_bank_completely(
        self,
        bank_name: str,
        all_banks_media_provider: Callable[[str], frozenset[int]] | None = None,
    ) -> tuple[int, int]:
        """
        Reverts modified SoundBank and its unshared staged loose WEMs to baseline.
        Deletes physical .bnk from pack_root/audio/, unregisters from modified_banks and custom_names.
        Deletes staged WEMs in this bank unless also referenced by another currently modified bank.
        Returns tuple (banks_reverted_count, wems_reverted_count).
        """
        clean = (bank_name if bank_name.lower().endswith(".bnk") else f"{bank_name}.bnk").lower()
        bank_was_modified = False

        # 1. Query media IDs for this bank BEFORE unlinking from disk, so overlay DIDX is captured
        media_provider = all_banks_media_provider or self.cache.get_bank_media_ids
        this_bank_media = set(media_provider(clean))
        if hasattr(self, "cache") and self.cache is not None:
            this_bank_media.update(self.cache.get_bank_media_ids(clean))

        # 2. Delete physical .bnk and unregister from manifest
        bank_file = self.audio_dir / clean
        if bank_file.is_file():
            bank_file.unlink()
            bank_was_modified = True
        elif self.audio_dir.is_dir():
            for f in self.audio_dir.iterdir():
                if f.name.lower() == clean and f.is_file():
                    f.unlink()
                    bank_was_modified = True
                    break

        matching_banks = [b for b in self.manifest.modified_banks if b.lower() == clean]
        if matching_banks:
            self.manifest.modified_banks = [
                b for b in self.manifest.modified_banks if b.lower() != clean
            ]
            bank_was_modified = True

        stem = clean.removesuffix(".bnk")
        for k in list(self.manifest.custom_names.keys()):
            k_lower = k.lower()
            if k_lower in (clean, stem) or k_lower.removesuffix(".bnk") == stem:
                del self.manifest.custom_names[k]
                bank_was_modified = True

        # 3. Identify staged loose WEMs belonging to this bank
        staged_in_this_bank = [w for w in self.manifest.staged_wems if w in this_bank_media]

        # 4. Check if any other modified banks also reference these WEMs (in overlay or baseline)
        other_modified_banks = [b for b in self.manifest.modified_banks if b.lower() != clean]
        other_modified_media: set[int] = set()
        for ob in other_modified_banks:
            other_modified_media.update(media_provider(ob))
            if hasattr(self, "cache") and self.cache is not None:
                other_modified_media.update(self.cache.get_bank_media_ids(ob))

        wems_reverted = 0
        for wid in staged_in_this_bank:
            if wid not in other_modified_media:
                if self.revert_wem_completely(wid):
                    wems_reverted += 1

        if bank_was_modified or wems_reverted > 0:
            self.save_manifest()
            return (1, wems_reverted)

        return (0, 0)

    def revert_wem_completely(self, wem_id: int | str) -> bool:
        """Removes loose .wem file, unregisters from manifest, and cleans orphaned source audio."""
        wid = int(str(wem_id).removesuffix(".wem"))
        reverted = False
        if wid in self.manifest.staged_wems:
            self.manifest.staged_wems = [w for w in self.manifest.staged_wems if int(w) != wid]
            reverted = True
        wem_file = self.audio_dir / f"{wid}.wem"
        if wem_file.is_file():
            wem_file.unlink()
            reverted = True

        if wid in self.manifest.source_audio:
            src_rel = self.manifest.source_audio.pop(wid)
            src_file = self.root_dir / src_rel
            if src_file.is_file() and not any(
                r == src_rel for r in self.manifest.source_audio.values()
            ):
                try:
                    src_file.unlink()
                except OSError:
                    pass
            reverted = True

        if reverted:
            self.save_manifest()
        return reverted

    # -------------------------------------------------------------------------
    # Mod Pack Compilation
    # -------------------------------------------------------------------------

    def resolve_default_pack_path(self) -> Path:
        """Resolves the default output pack destination inside the project root directory."""
        if self.manifest.output_pack_path:
            return Path(self.manifest.output_pack_path).resolve()
        return (self.root_dir / f"{self.manifest.name}.pack").resolve()

    def resolve_game_data_pack_path(self) -> Path | None:
        """Resolves the target path inside the game data directory if detected."""
        try:
            from src.workspace.game_detector import GameDetector

            detected = GameDetector.detect_game_install(self.manifest.game)
            if detected and (detected / "data").is_dir():
                return (detected / "data" / f"{self.manifest.name}.pack").resolve()
        except (OSError, ValueError):
            pass
        return None

    def copy_pack_to_game_data(self, pack_path: Path | None = None) -> Path | None:
        """Copies compiled .pack file to detected game data directory if available."""
        src = pack_path or self.resolve_default_pack_path()
        if not src.is_file():
            return None
        game_dest = self.resolve_game_data_pack_path()
        if game_dest is None:
            return None
        import shutil

        game_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, game_dest)
        return game_dest

    def set_output_pack_path(self, output_path: Path | str) -> Path:
        """Sets and persists the project's target output pack file destination."""
        dest = Path(output_path).resolve()
        self.manifest.output_pack_path = str(dest)
        self.save_manifest()
        return dest

    def validate_preflight(self) -> object:
        """Runs pre-flight verification on staged audio assets in pack_root/audio/."""
        from src.workspace.health import PackHealthScanner

        return PackHealthScanner.validate_project_preflight(self)

    def compile_mod_pack(
        self,
        output_path: Path | str | None = None,
        pack_type: int = 3,
        *,
        validate: bool = False,
    ) -> Path:
        """Compiles all staged audio files from pack_root/audio/ into a Total War PFH4 Mod pack (default PT_MOD = 3).

        Updates manifest.output_pack_path if a custom output path is provided.
        Returns the absolute Path of the created .pack file.
        """
        from src.compiler.pfh4_pack import write_pfh4_pack

        self.reconcile_manifest_with_disk()

        if validate:
            from src.workspace.health import PackHealthReport, PackPreflightError

            report = self.validate_preflight()
            if isinstance(report, PackHealthReport) and report.has_critical_issues:
                first = next(
                    i
                    for i in report.issues
                    if getattr(getattr(i, "severity", None), "value", "") == "critical_crash"
                )
                raise PackPreflightError(
                    f"Mod pack pre-flight validation failed: {first.title} ({first.description})",
                    report,
                )

        if output_path is not None:
            dest = self.set_output_pack_path(output_path)
        elif self.manifest.output_pack_path:
            dest = Path(self.manifest.output_pack_path).resolve()
        else:
            dest = self.resolve_default_pack_path()
            self.manifest.output_pack_path = str(dest)
            self.save_manifest()

        dest.parent.mkdir(parents=True, exist_ok=True)

        files_to_pack: dict[str, bytes] = {}
        if self.audio_dir.is_dir():
            for f in self.audio_dir.iterdir():
                if f.is_file() and not f.name.endswith(".tmp"):
                    rel_posix = f"audio/{f.name}"
                    files_to_pack[rel_posix] = f.read_bytes()

        write_pfh4_pack(dest, files_to_pack, pack_type=pack_type)
        return dest

    def compile_movie_pack(
        self,
        output_path: Path | str | None = None,
        pack_type: int = 3,
        *,
        validate: bool = False,
    ) -> Path:
        """Alias for compile_mod_pack (defaults to PT_MOD = 3)."""
        return self.compile_mod_pack(
            output_path=output_path, pack_type=pack_type, validate=validate
        )

    def register_in_user_script(self, pack_name: str | None = None) -> Path | None:
        """
        Appends the mod pack entry to Total War's user.script.txt in %APPDATA%
        so the game engine mounts the mod pack on startup.
        """
        from src.compiler.pfh4_pack import format_user_script_entry
        from src.workspace.game import resolve_user_script_path

        script_path = resolve_user_script_path(self.manifest.game)
        if script_path is None:
            return None

        script_path.parent.mkdir(parents=True, exist_ok=True)
        target_name = (
            Path(pack_name).name
            if pack_name
            else (
                Path(self.manifest.output_pack_path).name
                if self.manifest.output_pack_path
                else f"{self.manifest.name}.pack"
            )
        )
        entry_line = format_user_script_entry(target_name)

        existing_content = ""
        if script_path.is_file():
            try:
                existing_content = script_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass

        if f'mod "{target_name}";' not in existing_content:
            with open(script_path, "a", encoding="utf-8") as f:
                if existing_content and not existing_content.endswith("\n"):
                    f.write("\n")
                f.write(entry_line)

        return script_path

    # -------------------------------------------------------------------------
    # Database Table Staging & Metadata Catalog
    # -------------------------------------------------------------------------

    @staticmethod
    def normalize_table_name(table_name: str) -> str:
        """Normalizes table identifiers to clean canonical table keys."""
        clean = table_name.lower().strip()
        if clean.endswith(".tsv"):
            clean = clean[:-4]
        if clean.endswith(".bin"):
            clean = clean[:-4]
        if clean.endswith("_tables"):
            clean = clean[:-7]
        return clean

    def stage_db_table(self, table_name: str, data: bytes) -> Path:
        """Writes a binary or TSV database table into db/<table_name>_tables/<table_name>."""
        clean = self.normalize_table_name(table_name)
        target_dir = self.db_dir / f"{clean}_tables"
        target_dir.mkdir(parents=True, exist_ok=True)

        target_file = target_dir / clean
        target_file.write_bytes(data)

        if clean not in self.manifest.staged_db_tables:
            self.manifest.staged_db_tables.append(clean)
        return target_file

    def revert_db_table(self, table_name: str) -> bool:
        """Removes a staged database table and unregisters from manifest."""
        clean = self.normalize_table_name(table_name)
        if clean not in self.manifest.staged_db_tables:
            return False

        self.manifest.staged_db_tables.remove(clean)
        target_dir = self.db_dir / f"{clean}_tables"
        target_file = target_dir / clean

        if target_file.is_file():
            target_file.unlink()

        # Clean up directory if empty
        if target_dir.is_dir() and not any(target_dir.iterdir()):
            target_dir.rmdir()

        return True

    def list_db_tables(self) -> list[str]:
        """Returns sorted list of staged database table names."""
        return sorted(list(set(self.manifest.staged_db_tables)))

    def load_metadata_catalog(self) -> AudioMetadataCatalog:
        """
        Loads and indexes the AudioMetadataCatalog with layered multi-table composition.
        Aggregates across GameCache, active dependencies in priority order, and project db_dir.
        """
        from src.models.catalog import AudioMetadataCatalog
        from src.models.parser import (
            find_all_table_files,
            parse_audio_explosions,
            parse_audio_projectiles,
            parse_culture_junctions,
            parse_land_units,
            parse_main_units_voiceover,
            parse_material_sfx,
            parse_melee_weapons,
            parse_unit_armour_types,
            parse_unit_shield_types,
        )

        db_dirs: list[Path] = []
        if self.cache is not None and self.cache.db_dir.is_dir():
            db_dirs.append(self.cache.db_dir)

        # Dependencies layered from lowest precedence (higher priority number) to highest (priority 0)
        # so later layers override earlier layers in cascading updates.
        sorted_deps = sorted(self.manifest.dependencies, key=lambda d: d.priority, reverse=True)
        for dep in sorted_deps:
            dep_db = self.get_dependency_dir(dep.name) / "db"
            if dep_db.is_dir():
                db_dirs.append(dep_db)

        if self.db_dir.is_dir():
            db_dirs.append(self.db_dir)

        def _normalize_file_key(file_path: Path) -> str:
            name = file_path.name.lower()
            if name.endswith((".tsv", ".bin")):
                name = name[:-4]
            return name

        def _resolve_table_files(table_key: str) -> list[Path]:
            resolved_by_filename: dict[str, tuple[int, Path]] = {}
            for layer_idx, d in enumerate(db_dirs):
                for p in find_all_table_files(d, table_key):
                    fkey = _normalize_file_key(p)
                    if fkey in resolved_by_filename:
                        old_idx, old_p = resolved_by_filename[fkey]
                        logger.debug(
                            "Table file '%s' from %s (layer %d) overrides %s (layer %d)",
                            p.name,
                            p.parent,
                            layer_idx,
                            old_p,
                            old_idx,
                        )
                    resolved_by_filename[fkey] = (layer_idx, p)

            sorted_survivors = sorted(resolved_by_filename.values(), key=lambda item: item[0])
            return [path for _, path in sorted_survivors]

        # 1. Resolve material tables
        armour_files = _resolve_table_files("unit_armour_types")
        shield_files = _resolve_table_files("unit_shield_types")
        weapon_files = _resolve_table_files("melee_weapons")

        armour_map: dict[str, str] = {}
        for f in armour_files:
            armour_map.update(parse_unit_armour_types(f))

        shield_map: dict[str, str] = {}
        for f in shield_files:
            shield_map.update(parse_unit_shield_types(f))

        weapon_map: dict[str, str] = {}
        for f in weapon_files:
            weapon_map.update(parse_melee_weapons(f))

        # 1b. Resolve main units voiceover
        main_units_files = _resolve_table_files("main_units")
        vo_map: dict[str, str] = {}
        for f in main_units_files:
            vo_map.update(parse_main_units_voiceover(f))

        # 2. Resolve land units
        land_units_files = _resolve_table_files("land_units")
        units: dict[str, Any] = {}
        for f in land_units_files:
            units.update(
                parse_land_units(
                    f,
                    armour_materials=armour_map,
                    shield_materials=shield_map,
                    weapon_materials=weapon_map,
                    voiceover_cultures=vo_map,
                )
            )

        # 3. Resolve cultures, projectiles, explosions
        cult_files = _resolve_table_files("subculture_religion_voiceover_junctions")
        cultures_dict: dict[tuple[str, str], Any] = {}
        for f in cult_files:
            for c in parse_culture_junctions(f):
                cultures_dict[(c.subculture.lower(), c.religion.lower())] = c
        cultures = list(cultures_dict.values())

        proj_files = _resolve_table_files("audio_projectiles")
        projectiles: dict[str, Any] = {}
        for f in proj_files:
            projectiles.update(parse_audio_projectiles(f))

        exp_files = _resolve_table_files("audio_explosions")
        explosions: dict[str, Any] = {}
        for f in exp_files:
            explosions.update(parse_audio_explosions(f))

        # 4. Resolve materials across all material files with layered overriding
        materials_dict: dict[tuple[str, str], Any] = {}
        for f in armour_files:
            for m in parse_material_sfx(armour_path=f):
                materials_dict[(m.category.lower(), m.material_key.lower())] = m
        for f in shield_files:
            for m in parse_material_sfx(shield_path=f):
                materials_dict[(m.category.lower(), m.material_key.lower())] = m
        for f in weapon_files:
            for m in parse_material_sfx(weapon_path=f):
                materials_dict[(m.category.lower(), m.material_key.lower())] = m
        materials = list(materials_dict.values())

        return AudioMetadataCatalog(
            units=units,
            cultures=cultures,
            projectiles=projectiles,
            explosions=explosions,
            materials=materials,
        )
