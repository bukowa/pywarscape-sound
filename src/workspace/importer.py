"""Asset ingestion service for importing individual banks, WEMs, and tables into project overlay."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from src.bnk.bank import repair_extracted_bnk_bytes
from src.bnk.wem import repair_extracted_wem_bytes
from src.compiler.pfh4_pack import extract_pfh4_file, read_pfh4_index

if TYPE_CHECKING:
    from src.workspace.project import AudioProject


class PartImporter:
    """Dedicated service for importing individual SoundBanks, loose WEMs, and DB tables into pack_root/audio/."""

    def __init__(self, project: AudioProject) -> None:
        self.project = project

    def import_bank(self, pack_path: Path | str, bank_name: str) -> Path:
        """
        Extracts and stages a SoundBank from an external pack into pack_root/audio/.
        Applies repair heuristics, registers in manifest.modified_banks, and saves project.
        """
        p = Path(pack_path)
        clean = (bank_name if bank_name.lower().endswith(".bnk") else f"{bank_name}.bnk").lower()
        entries = read_pfh4_index(p)
        matched_entry = None
        for entry in entries:
            norm = entry.path.replace("\\", "/").lower()
            if norm == f"audio/{clean}" or norm.endswith(f"/{clean}") or norm == clean:
                matched_entry = entry
                break
        if matched_entry is None:
            raise FileNotFoundError(f"SoundBank '{bank_name}' not found in pack '{p.name}'")

        data = extract_pfh4_file(p, matched_entry)
        data = repair_extracted_bnk_bytes(data)
        return self.project.save_bank(clean, data)

    def import_wem(self, pack_path: Path | str, wem_id: int | str) -> Path:
        """
        Extracts and stages a loose .wem file from an external pack into pack_root/audio/.
        Applies repair heuristics, registers in manifest.staged_wems, and saves project.
        """
        p = Path(pack_path)
        wid = int(str(wem_id).removesuffix(".wem"))
        target = f"{wid}.wem"
        entries = read_pfh4_index(p)
        matched_entry = None
        for entry in entries:
            norm = entry.path.replace("\\", "/").lower()
            if norm == f"audio/{target}" or norm.endswith(f"/{target}") or norm == target:
                matched_entry = entry
                break
        if matched_entry is None:
            raise FileNotFoundError(f"WEM '{wem_id}' not found in pack '{p.name}'")

        data = extract_pfh4_file(p, matched_entry)
        data = repair_extracted_wem_bytes(data)
        return self.project.stage_wem(wid, data)

    def import_database(self, pack_path: Path | str) -> Path:
        """
        Extracts event_data.dat from an external pack into pack_root/audio/.
        Registers in manifest.has_custom_event_db and saves project.
        """
        p = Path(pack_path)
        entries = read_pfh4_index(p)
        matched_entry = None
        for entry in entries:
            norm = entry.path.replace("\\", "/").lower()
            if (
                norm == "audio/event_data.dat"
                or norm.endswith("/event_data.dat")
                or norm == "event_data.dat"
            ):
                matched_entry = entry
                break
        if matched_entry is None:
            raise FileNotFoundError(f"event_data.dat not found in pack '{p.name}'")

        data = extract_pfh4_file(p, matched_entry)
        dest = self.project.save_database(data)
        self.project.save_manifest()
        return dest

    def import_db_table(self, pack_path: Path | str, table_rel_path: str) -> Path:
        """
        Extracts a database table file (e.g. db/battle_entities_tables/data) into project db_dir.
        """
        p = Path(pack_path)
        norm_target = table_rel_path.replace("\\", "/").lower()
        if not norm_target.startswith("db/"):
            norm_target = f"db/{norm_target}"

        entries = read_pfh4_index(p)
        matched_entry = None
        for entry in entries:
            norm = entry.path.replace("\\", "/").lower()
            if norm == norm_target:
                matched_entry = entry
                break
        if matched_entry is None:
            raise FileNotFoundError(
                f"Database table '{table_rel_path}' not found in pack '{p.name}'"
            )

        data = extract_pfh4_file(p, matched_entry)
        orig_parts = matched_entry.path.replace("\\", "/").split("/")
        rel_posix = "/".join(orig_parts[1:])  # strip db/
        dest = self.project.db_dir / rel_posix
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest
