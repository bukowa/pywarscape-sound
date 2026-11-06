from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class GameType(str, Enum):
    ATTILA = "attila"
    ROME_2 = "rome_2"


@dataclass(slots=True, frozen=True)
class GameConfig:
    game_type: GameType
    display_name: str
    store_id: int
    executable: str
    data_rel_path: str
    vanilla_packs: list[str]
    default_cache_dir: Path


ATTILA_VANILLA_PACKS: list[str] = [
    "boot.pack",
    "data.pack",
    "models.pack",
    "models2.pack",
    "models3.pack",
    "movies.pack",
    "music.pack",
    "music_en_shared_rome2.pack",
    "belisarius.pack",
    "blood.pack",
    "charlemagne.pack",
    "slavs.pack",
    "sound.pack",
    "terrain.pack",
    "terrain2.pack",
    "tiles.pack",
    "tiles2.pack",
    "tiles3.pack",
    "tiles4.pack",
    "local_en_shared_rome2.pack",
    "local_en.pack",
]

ROME2_VANILLA_PACKS: list[str] = [
    "boot.pack",
    "data.pack",
    "data_rome2.pack",
    "models.pack",
    "models2.pack",
    "movies.pack",
    "music_en_shared_rome2.pack",
    "music.pack",
    "blood_rome2.pack",
    "divided.pack",
    "gaul.pack",
    "greeks.pack",
    "invasion.pack",
    "sound.pack",
    "terrain.pack",
    "local_en_shared_rome2.pack",
    "local_en.pack",
]

_CONFIGS: dict[GameType, GameConfig] = {
    GameType.ATTILA: GameConfig(
        game_type=GameType.ATTILA,
        display_name="Attila",
        store_id=325610,
        executable="Attila.exe",
        data_rel_path="data",
        vanilla_packs=ATTILA_VANILLA_PACKS,
        default_cache_dir=Path(".cache/attila/audio"),
    ),
    GameType.ROME_2: GameConfig(
        game_type=GameType.ROME_2,
        display_name="Rome II",
        store_id=214950,
        executable="Rome2.exe",
        data_rel_path="data",
        vanilla_packs=ROME2_VANILLA_PACKS,
        default_cache_dir=Path(".cache/rome_2/audio"),
    ),
}


def get_game_config(game_type: GameType | str) -> GameConfig:
    gt = GameType(game_type) if isinstance(game_type, str) else game_type
    if gt not in _CONFIGS:
        raise ValueError(f"Unsupported game type: {game_type}")
    return _CONFIGS[gt]


def resolve_user_script_path(game_type: GameType | str) -> Path | None:
    """Resolves the user.script.txt path for the target game in %APPDATA%."""
    import os

    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    config = get_game_config(game_type)
    folder = "Attila" if config.game_type == GameType.ATTILA else "Rome2"
    return Path(appdata) / "The Creative Assembly" / folder / "scripts" / "user.script.txt"
