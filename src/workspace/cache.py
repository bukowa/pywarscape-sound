import struct
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.bnk.chunks import scan_didx_media_ids
from src.workspace.game import GameType, get_game_config

# Database table directory names required for metadata resolution.
# Matches paths like db/land_units_tables/land_units inside vanilla packs.
_AUDIO_DB_TABLE_DIRS: frozenset[str] = frozenset(
    {
        "land_units_tables",
        "unit_armour_types_tables",
        "unit_shield_types_tables",
        "melee_weapons_tables",
        "subculture_religion_voiceover_junctions_tables",
        "audio_projectiles_tables",
        "audio_explosions_tables",
    }
)


class GameCache:
    """Read-only manager for indexed vanilla SoundBanks, event_data.dat, and loose audio."""

    def __init__(
        self, game_type: GameType | str = GameType.ATTILA, cache_dir: Path | str | None = None
    ) -> None:
        self.game_type = GameType(game_type) if isinstance(game_type, str) else game_type
        self.config = get_game_config(self.game_type)
        self.cache_dir = Path(cache_dir) if cache_dir is not None else self.config.default_cache_dir
        self._bank_id_to_path: dict[int, Path] | None = None
        self._wems_cache: list[int] | None = None
        self._loose_catalog_cache: tuple[Any, ...] | None = None
        self._bank_media_ids_cache: dict[str, frozenset[int]] = {}

    def is_valid(self) -> bool:
        """Verifies that cache directory exists and contains vanilla .bnk files and event_data.dat."""
        if not self.cache_dir.is_dir():
            return False
        has_bnks = any(self.cache_dir.glob("*.bnk"))
        has_db = (self.cache_dir / "event_data.dat").is_file()
        return has_bnks and has_db

    def get_bank_path(self, name: str) -> Path | None:
        """Case-insensitive lookup for a vanilla SoundBank."""
        if not self.cache_dir.is_dir():
            return None
        clean_name = name.lower()
        if not clean_name.endswith(".bnk"):
            clean_name += ".bnk"

        direct = self.cache_dir / clean_name
        if direct.is_file():
            return direct

        for path in self.cache_dir.glob("*.bnk"):
            if path.name.lower() == clean_name:
                return path
        return None

    def get_bank_by_id(self, bank_id: int) -> Path | None:
        """Resolves a SoundBank path by its 32-bit numeric bank ID."""
        if self._bank_id_to_path is None:
            self._bank_id_to_path = self._index_bank_ids()
        return self._bank_id_to_path.get(bank_id)

    def _index_bank_ids(self) -> dict[int, Path]:
        mapping: dict[int, Path] = {}
        if not self.cache_dir.is_dir():
            return mapping
        for path in self.cache_dir.glob("*.bnk"):
            try:
                with open(path, "rb") as f:
                    head = f.read(16)
                    if len(head) == 16 and head[:4] == b"BKHD":
                        _, bid = struct.unpack_from("<II", head, 8)
                        mapping[bid] = path
            except OSError:
                continue
        return mapping

    def get_bank_media_ids(self, bank_name: str) -> frozenset[int]:
        """Returns memoized set of embedded WEM IDs present in bank's DIDX chunk."""
        clean_name = bank_name.lower()
        if not clean_name.endswith(".bnk"):
            clean_name += ".bnk"
        if clean_name in self._bank_media_ids_cache:
            return self._bank_media_ids_cache[clean_name]
        path = self.get_bank_path(clean_name)
        if path is None or not path.is_file():
            return frozenset()
        media_ids = self.scan_didx_media_ids(path)
        self._bank_media_ids_cache[clean_name] = media_ids
        return media_ids

    scan_didx_media_ids = staticmethod(scan_didx_media_ids)
    _scan_didx_media_ids = scan_didx_media_ids

    def get_wem_path(self, wem_id: int | str) -> Path | None:
        """Lookup for a loose .wem audio file."""
        if not self.cache_dir.is_dir():
            return None
        clean_wid = str(wem_id).removesuffix(".wem")
        target = f"{clean_wid}.wem"
        path = self.cache_dir / target
        return path if path.is_file() else None

    def get_database_path(self) -> Path | None:
        """Lookup for vanilla event_data.dat."""
        db_path = self.cache_dir / "event_data.dat"
        return db_path if db_path.is_file() else None

    @property
    def db_dir(self) -> Path:
        """Returns path to cached vanilla db tables directory (.cache/<game>/db)."""
        return self.cache_dir.parent / "db"

    def get_table_path(self, table_name: str) -> Path | None:
        """Lookup for cached vanilla database table file."""
        from src.models.parser import find_table_file

        if not self.db_dir.is_dir():
            return None
        return find_table_file(self.db_dir, table_name)

    def list_banks(self) -> list[str]:
        """Returns sorted list of available vanilla SoundBank filenames."""
        if not self.cache_dir.is_dir():
            return []
        return sorted([p.name for p in self.cache_dir.glob("*.bnk")])

    def list_wems(self) -> list[int]:
        """Returns sorted list of integer IDs for extracted loose .wem files."""
        if self._wems_cache is not None:
            return self._wems_cache
        if not self.cache_dir.is_dir():
            return []
        wems: list[int] = []
        for p in self.cache_dir.glob("*.wem"):
            stem = p.stem
            if stem.isdigit():
                wems.append(int(stem))
        self._wems_cache = sorted(wems)
        return self._wems_cache

    def get_loose_wem_catalog(self, sound_db: Any | None = None) -> tuple[Any, ...]:
        """Returns memoized loose .wem catalog entries for vanilla game assets."""
        if self._loose_catalog_cache is not None:
            return self._loose_catalog_cache
        from src.models import AudioCatalogEntry

        entries: list[AudioCatalogEntry] = []
        for wid in self.list_wems():
            entries.append(
                AudioCatalogEntry(
                    wem_id=wid,
                    source_bank="Vanilla (Loose)",
                    is_embedded=False,
                    display_name=f"WEM {wid}",
                    category="General",
                )
            )
        self._loose_catalog_cache = tuple(entries)
        return self._loose_catalog_cache

    def extract_from_game_packs(
        self,
        game_data_dir: Path | str,
        progress_cb: Callable[[str, float], None] | None = None,
    ) -> int:
        """Extracts audio .bnk, .wem, event_data.dat, and audio-related DB tables from vanilla packs."""
        from src.bnk.bank import repair_extracted_bnk_bytes
        from src.bnk.wem import repair_extracted_wem_bytes
        from src.compiler.pfh4_pack import extract_pfh4_file, read_pfh4_index

        g_data = Path(game_data_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        total_extracted = 0
        written_files: set[str] = set()

        total_packs = len(self.config.vanilla_packs)
        for idx, pack_name in enumerate(self.config.vanilla_packs):
            pack_path = g_data / pack_name
            if not pack_path.is_file():
                continue

            if progress_cb is not None:
                progress_cb(pack_name, idx / max(1, total_packs))

            entries = read_pfh4_index(pack_path)
            for e in entries:
                norm = e.path.replace("/", "\\").lower()

                # --- Audio files (audio/*.bnk, audio/*.wem, audio/event_data.dat) ---
                if norm.startswith("audio\\"):
                    fname = Path(e.path.replace("\\", "/")).name
                    fname_lower = fname.lower()
                    if not (
                        fname_lower.endswith(".bnk")
                        or fname_lower.endswith(".wem")
                        or fname_lower == "event_data.dat"
                    ):
                        continue

                    dest = self.cache_dir / fname
                    data = extract_pfh4_file(pack_path, e)
                    if fname_lower.endswith(".bnk"):
                        data = repair_extracted_bnk_bytes(data)
                    elif fname_lower.endswith(".wem"):
                        data = repair_extracted_wem_bytes(data)

                    dest.write_bytes(data)

                    if fname_lower not in written_files:
                        written_files.add(fname_lower)
                        total_extracted += 1
                    continue

                # --- DB tables (db/<table>_tables/<file>) for metadata resolution ---
                if norm.startswith("db\\"):
                    parts = norm.split("\\")
                    # Expected: db\<table_dir>\<file>  (3 segments)
                    if len(parts) < 3:
                        continue
                    table_dir_name = parts[1]
                    if table_dir_name not in _AUDIO_DB_TABLE_DIRS:
                        continue

                    # Preserve relative path under db_dir: <table_dir>/<file>
                    orig_parts = e.path.replace("\\", "/").split("/")
                    rel_path = "/".join(orig_parts[1:])  # strip leading "db/"
                    dest = self.db_dir / rel_path
                    dest.parent.mkdir(parents=True, exist_ok=True)

                    data = extract_pfh4_file(pack_path, e)
                    dest.write_bytes(data)

                    dest_key = f"db/{rel_path}".lower()
                    if dest_key not in written_files:
                        written_files.add(dest_key)
                        total_extracted += 1
                    continue

        if progress_cb is not None:
            progress_cb("Complete", 1.0)

        self._wems_cache = None
        self._loose_catalog_cache = None
        self._bank_id_to_path = None
        self._bank_media_ids_cache.clear()
        return total_extracted
