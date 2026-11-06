"""Pure-Python Steam game installation detection and directory validation."""

import re
from pathlib import Path

from src.workspace.game import GameType, get_game_config

try:
    import winreg
except ImportError:
    winreg = None  # Non-Windows platforms or testing environments


class GameDetector:
    """Headless discovery helper for locating and validating Total War installations."""

    _ATTILA_FOLDER_NAMES = [
        "Total War Attila",
        "Total War - Attila",
        "Attila",
    ]

    _ROME2_FOLDER_NAMES = [
        "Total War Rome II",
        "Total War - Rome II",
        "Rome II",
        "Rome2",
    ]

    @classmethod
    def validate_game_dir(
        cls,
        game_type: GameType | str,
        path: str | Path,
    ) -> tuple[bool, str]:
        """
        Verifies that the target directory contains the required game executable and
        at least one core vanilla sound pack in the data directory.
        """
        if not path:
            return False, "Directory path is empty"

        target_dir = Path(path)
        if not target_dir.is_dir():
            return False, f"Directory does not exist: {target_dir}"

        try:
            config = get_game_config(game_type)
        except ValueError as err:
            return False, str(err)

        # Check executable (case-insensitive check)
        exe_found = False
        target_exe_lower = config.executable.lower()
        for item in target_dir.iterdir():
            if item.name.lower() == target_exe_lower and item.is_file():
                exe_found = True
                break

        if not exe_found:
            return False, f"Executable '{config.executable}' not found in directory"

        # Check data directory
        data_dir = target_dir / config.data_rel_path
        if not data_dir.is_dir():
            return False, f"Data directory '{config.data_rel_path}' not found"

        # Check packs
        pack_files = [p.name.lower() for p in data_dir.glob("*.pack")]
        if not pack_files:
            return False, "No .pack files found in data directory"

        vanilla_set = {p.lower() for p in config.vanilla_packs}
        if "sound.pack" in pack_files or any(p in vanilla_set for p in pack_files):
            return True, "Valid game directory"

        return False, "No vanilla sound packs found in data directory"

    @classmethod
    def parse_steam_libraryfolders(cls, vdf_path: Path) -> list[Path]:
        """Extracts library directory paths from a Steam libraryfolders.vdf file."""
        if not vdf_path.is_file():
            return []

        try:
            content = vdf_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        # Matches "path"\s+"<path>"
        pattern = re.compile(r'"path"\s+"([^"]+)"', re.IGNORECASE)
        found_paths: list[Path] = []
        for match in pattern.finditer(content):
            raw_path = match.group(1).replace("\\\\", "/").strip()
            p = Path(raw_path)
            if p not in found_paths:
                found_paths.append(p)

        return found_paths

    @classmethod
    def detect_game_install(cls, game_type: GameType | str) -> Path | None:
        """
        Attempts to locate the game installation directory on disk.
        1. Checks Windows Registry via Steam App ID.
        2. Parses Steam libraryfolders.vdf across known Steam roots.
        3. Checks standard default installation paths.
        """
        gt = GameType(game_type) if isinstance(game_type, str) else game_type
        config = get_game_config(gt)

        # 1. Registry query
        reg_dir = cls._query_registry_install_dir(config.store_id)
        if reg_dir is not None:
            valid, _ = cls.validate_game_dir(gt, reg_dir)
            if valid:
                return reg_dir

        # 2. Check Steam libraries
        steam_roots = cls._get_steam_root_candidates()
        library_folders: list[Path] = []
        for s_root in steam_roots:
            if s_root.is_dir() and s_root not in library_folders:
                library_folders.append(s_root)
            vdf = s_root / "steamapps" / "libraryfolders.vdf"
            for lib in cls.parse_steam_libraryfolders(vdf):
                if lib not in library_folders:
                    library_folders.append(lib)

        folder_names = (
            cls._ATTILA_FOLDER_NAMES if gt == GameType.ATTILA else cls._ROME2_FOLDER_NAMES
        )

        for lib in library_folders:
            common_dir = lib / "steamapps" / "common"
            if not common_dir.is_dir():
                continue
            for fname in folder_names:
                candidate = common_dir / fname
                valid, _ = cls.validate_game_dir(gt, candidate)
                if valid:
                    return candidate

        # 3. Default direct candidate checks
        for candidate in cls._get_default_game_candidates(gt):
            valid, _ = cls.validate_game_dir(gt, candidate)
            if valid:
                return candidate

        return None

    @classmethod
    def _query_registry_install_dir(cls, app_id: int) -> Path | None:
        """Queries Windows registry for Steam App install location."""
        if winreg is None:
            return None

        subkeys = [
            rf"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App {app_id}",
            rf"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Steam App {app_id}",
        ]

        for subkey in subkeys:
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(root, subkey) as key:
                        val, _ = winreg.QueryValueEx(key, "InstallLocation")
                        if val:
                            p = Path(val)
                            if p.is_dir():
                                return p
                except (OSError, FileNotFoundError):
                    continue

        return None

    @classmethod
    def _get_steam_root_candidates(cls) -> list[Path]:
        """Locates candidate Steam installation directories."""
        candidates: list[Path] = []

        if winreg is not None:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                    val, _ = winreg.QueryValueEx(key, "SteamPath")
                    if val:
                        candidates.append(Path(val))
            except (OSError, FileNotFoundError):
                pass

        # Standard default paths on Windows
        standard_roots = [
            Path("C:/Program Files (x86)/Steam"),
            Path("C:/Program Files/Steam"),
            Path("D:/Steam"),
            Path("E:/Steam"),
        ]
        for root in standard_roots:
            if root not in candidates:
                candidates.append(root)

        return candidates

    @classmethod
    def _get_default_game_candidates(cls, game_type: GameType) -> list[Path]:
        """Provides default candidate locations under standard paths."""
        folder_names = (
            cls._ATTILA_FOLDER_NAMES if game_type == GameType.ATTILA else cls._ROME2_FOLDER_NAMES
        )
        candidates: list[Path] = []
        bases = [
            Path("C:/Program Files (x86)/Steam/steamapps/common"),
            Path("C:/Program Files/Steam/steamapps/common"),
            Path("D:/Steam/steamapps/common"),
            Path("D:/SteamLibrary/steamapps/common"),
            Path("E:/Steam/steamapps/common"),
            Path("E:/SteamLibrary/steamapps/common"),
        ]
        for b in bases:
            for fname in folder_names:
                candidates.append(b / fname)

        return candidates
