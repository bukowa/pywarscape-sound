from pathlib import Path

import pytest

from src.workspace.cache import GameCache
from src.workspace.game import GameType, get_game_config
from tests.support.factories import skip_or_fail_missing_asset


def test_game_configs_and_paths():
    attila = get_game_config(GameType.ATTILA)
    assert attila.display_name == "Attila"
    assert "boot.pack" in attila.vanilla_packs
    assert attila.default_cache_dir == Path(".cache/attila/audio")

    rome2 = get_game_config(GameType.ROME_2)
    assert rome2.display_name == "Rome II"
    assert "boot.pack" in rome2.vanilla_packs


@pytest.mark.assets
def test_real_attila_cache_inspection():
    cache = GameCache(GameType.ATTILA)
    if not (cache.cache_dir.exists() and any(cache.cache_dir.glob("*.bnk"))):
        skip_or_fail_missing_asset("Attila game cache not available locally")
    assert cache.is_valid() is True
    banks = cache.list_banks()
    assert len(banks) >= 126
    assert "battle.bnk" in [b.lower() for b in banks]
    assert cache.get_bank_path("battle.bnk") is not None
    assert cache.get_database_path() is not None


def test_invalid_cache_path(tmp_path):
    empty_cache = GameCache(GameType.ATTILA, cache_dir=tmp_path / "empty")
    assert empty_cache.is_valid() is False
    assert empty_cache.get_bank_path("battle.bnk") is None
    assert empty_cache.list_banks() == []


def test_extract_from_synthetic_game_pack(tmp_path):
    from src.compiler.pfh4_pack import write_pfh4_movie_pack

    game_data = tmp_path / "data"
    game_data.mkdir()
    pack_path = game_data / "boot.pack"

    files = [
        ("audio/test.bnk", b"DUMMY_BNK"),
        ("audio/event_data.dat", b"DUMMY_DB"),
        ("text/ignored.txt", b"IGNORED"),
    ]
    write_pfh4_movie_pack(pack_path, files)

    target_cache_dir = tmp_path / "cache" / "audio"
    cache = GameCache(GameType.ATTILA, cache_dir=target_cache_dir)
    extracted_count = cache.extract_from_game_packs(game_data)

    assert extracted_count == 2
    assert (target_cache_dir / "test.bnk").read_bytes() == b"DUMMY_BNK"
    assert (target_cache_dir / "event_data.dat").read_bytes() == b"DUMMY_DB"
    assert not (target_cache_dir / "ignored.txt").exists()
    assert cache.is_valid() is True


def test_extract_db_tables_from_synthetic_game_pack(tmp_path):
    """Verifies that extract_from_game_packs extracts audio-related DB tables into db_dir."""
    from src.compiler.pfh4_pack import write_pfh4_movie_pack

    game_data = tmp_path / "data"
    game_data.mkdir()
    pack_path = game_data / "boot.pack"

    land_units_data = b"BINARY_LAND_UNITS"
    projectiles_data = b"BINARY_PROJECTILES"
    unrelated_data = b"CAMPAIGN_TABLES"

    files = [
        ("audio/test.bnk", b"DUMMY_BNK"),
        ("audio/event_data.dat", b"DUMMY_DB"),
        ("db/land_units_tables/land_units", land_units_data),
        ("db/audio_projectiles_tables/audio_projectiles", projectiles_data),
        ("db/campaign_variables_tables/campaign_variables", unrelated_data),
    ]
    write_pfh4_movie_pack(pack_path, files)

    target_cache_dir = tmp_path / "cache" / "audio"
    cache = GameCache(GameType.ATTILA, cache_dir=target_cache_dir)
    extracted_count = cache.extract_from_game_packs(game_data)

    # Audio files + 2 matching DB tables = 4
    assert extracted_count == 4

    # Audio extracted normally
    assert (target_cache_dir / "test.bnk").read_bytes() == b"DUMMY_BNK"

    # DB tables extracted into db_dir with preserved structure
    db_dir = cache.db_dir
    assert db_dir.is_dir()
    assert (db_dir / "land_units_tables" / "land_units").read_bytes() == land_units_data
    assert (
        db_dir / "audio_projectiles_tables" / "audio_projectiles"
    ).read_bytes() == projectiles_data

    # Unrelated DB table NOT extracted
    assert not (db_dir / "campaign_variables_tables").exists()
