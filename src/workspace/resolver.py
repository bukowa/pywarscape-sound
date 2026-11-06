from pathlib import Path
from typing import TYPE_CHECKING

from src.workspace.cache import GameCache

if TYPE_CHECKING:
    from src.workspace.project import AudioProject


class AssetResolver:
    """Layered virtual file system resolving assets across Project overlay and GameCache."""

    def __init__(self, project: "AudioProject", cache: GameCache | None = None) -> None:
        self.project = project
        self.cache = cache or project.cache

    def is_bank_modified(self, bank_name: str) -> bool:
        """Returns True if the SoundBank is recorded as modified in the project manifest."""
        clean_lower = bank_name.lower()
        if not clean_lower.endswith(".bnk"):
            clean_lower += ".bnk"
        return any(
            (b.lower() if b.lower().endswith(".bnk") else f"{b.lower()}.bnk") == clean_lower
            for b in self.project.manifest.modified_banks
        )

    def is_wem_modified(self, wem_id: int | str) -> bool:
        """Returns True if the loose WEM file is recorded as staged in the project manifest."""
        try:
            wid = int(str(wem_id).removesuffix(".wem"))
        except (ValueError, TypeError):
            return False
        return wid in self.project.manifest.staged_wems

    def resolve_bank_path(self, bank_name: str) -> Path | None:
        """Resolves SoundBank path: checks project overlay first, active dependencies, then GameCache."""
        if not bank_name:
            return None
        clean_lower = bank_name.lower()
        if not clean_lower.endswith(".bnk"):
            clean_lower += ".bnk"

        # 1. Check project overlay (Tier 1 physical disk)
        if self.project.audio_dir.is_dir():
            direct = self.project.audio_dir / clean_lower
            if direct.is_file():
                return direct
            for f in self.project.audio_dir.iterdir():
                if f.name.lower() == clean_lower and f.is_file():
                    return f
        for b in self.project.manifest.modified_banks:
            if b.lower() == clean_lower:
                p = self.project.audio_dir / b
                if p.is_file():
                    return p

        # 2. Check active dependencies in load order (priority 0 = highest precedence)
        sorted_deps = sorted(self.project.manifest.dependencies, key=lambda d: d.priority)
        for dep in sorted_deps:
            dep_audio_dir = self.project.get_dependency_dir(dep.name) / "audio"
            if not dep_audio_dir.is_dir():
                continue
            direct = dep_audio_dir / clean_lower
            if direct.is_file():
                return direct
            for f in dep_audio_dir.iterdir():
                if f.name.lower() == clean_lower and f.is_file():
                    return f

        # 3. Check cache
        if self.cache is not None:
            return self.cache.get_bank_path(clean_lower)
        return None

    def resolve_baseline_bank_path(self, bank_name: str) -> Path | None:
        """Resolves vanilla base game SoundBank path from GameCache."""
        if not bank_name or self.cache is None:
            return None
        clean_lower = bank_name.lower()
        if not clean_lower.endswith(".bnk"):
            clean_lower += ".bnk"

        return self.cache.get_bank_path(clean_lower)

    def resolve_baseline_bank_bytes(self, bank_name: str) -> bytes | None:
        """Reads baseline SoundBank bytes, or None if not found."""
        p = self.resolve_baseline_bank_path(bank_name)
        return p.read_bytes() if p is not None and p.is_file() else None

    def resolve_bank_bytes(self, bank_name: str) -> bytes | None:
        """Reads resolved SoundBank bytes, or None if not found."""
        p = self.resolve_bank_path(bank_name)
        return p.read_bytes() if p is not None and p.is_file() else None

    def resolve_bank_path_by_id(self, bank_id: int) -> Path | None:
        """Resolves SoundBank path by its 32-bit numeric bank ID."""
        if self.cache is not None:
            p = self.cache.get_bank_by_id(bank_id)
            if p is not None:
                return p
        return None

    def resolve_bank_bytes_by_id(self, bank_id: int) -> bytes | None:
        """Reads SoundBank bytes by its 32-bit numeric bank ID."""
        p = self.resolve_bank_path_by_id(bank_id)
        return p.read_bytes() if p is not None and p.is_file() else None

    def resolve_wem_path(self, wem_id: int | str) -> Path | None:
        """Resolves loose .wem path: checks project overlay first, active dependencies, then GameCache."""
        wid_str = str(wem_id).strip()
        if wid_str.lower().endswith(".wem"):
            wid_str = wid_str[:-4]
        try:
            wid = int(wid_str)
        except (ValueError, TypeError):
            return None

        # 1. Check project overlay (Tier 1 physical disk)
        if self.project.audio_dir.is_dir():
            direct = self.project.audio_dir / f"{wid}.wem"
            if direct.is_file():
                return direct

        # 2. Check active dependencies in load order (priority 0 = highest precedence)
        sorted_deps = sorted(self.project.manifest.dependencies, key=lambda d: d.priority)
        for dep in sorted_deps:
            dep_audio_dir = self.project.get_dependency_dir(dep.name) / "audio"
            if not dep_audio_dir.is_dir():
                continue
            direct = dep_audio_dir / f"{wid}.wem"
            if direct.is_file():
                return direct

        # 3. Check cache
        if self.cache is not None:
            return self.cache.get_wem_path(wid)
        return None

    def resolve_wem_bytes(self, wem_id: int | str) -> bytes | None:
        """Reads resolved .wem bytes, or None if not found."""
        p = self.resolve_wem_path(wem_id)
        if p is None or not p.is_file():
            return None
        from src.bnk.wem import repair_extracted_wem_bytes

        return repair_extracted_wem_bytes(p.read_bytes())

    def resolve_database_path(self) -> Path | None:
        """Resolves event_data.dat: checks project overlay if custom, active dependencies, else GameCache."""
        # 1. Check project overlay (Tier 1 physical disk)
        if self.project.audio_dir.is_dir():
            p = self.project.audio_dir / "event_data.dat"
            if p.is_file():
                return p
        if self.project.manifest.has_custom_event_db:
            p = self.project.audio_dir / "event_data.dat"
            if p.is_file():
                return p

        # 2. Check active dependencies in load order (priority 0 = highest precedence)
        sorted_deps = sorted(self.project.manifest.dependencies, key=lambda d: d.priority)
        for dep in sorted_deps:
            dep_audio_dir = self.project.get_dependency_dir(dep.name) / "audio"
            if not dep_audio_dir.is_dir():
                continue
            direct = dep_audio_dir / "event_data.dat"
            if direct.is_file():
                return direct
            for f in dep_audio_dir.iterdir():
                if f.name.lower() == "event_data.dat" and f.is_file():
                    return f

        # 3. Check cache
        if self.cache is not None:
            return self.cache.get_database_path()
        return None

    def resolve_database_bytes(self) -> bytes | None:
        """Reads resolved event_data.dat bytes, or None if not found."""
        p = self.resolve_database_path()
        return p.read_bytes() if p is not None and p.is_file() else None
