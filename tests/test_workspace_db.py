from pathlib import Path

from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.storage import ProjectStorage


def test_project_db_staging_and_revert(tmp_path: Path):
    proj_dir = tmp_path / "mod_project"
    project = ProjectStorage.create_project(proj_dir, "DB Test Mod", GameType.ATTILA)
    assert project.db_dir.is_dir()
    assert project.list_db_tables() == []

    # 1. Stage land_units table
    fake_data = b"FAKE_LAND_UNITS_DATA"
    out_path = project.stage_db_table("land_units", fake_data)
    assert out_path.is_file()
    assert out_path == project.db_dir / "land_units_tables" / "land_units"
    assert "land_units" in project.manifest.staged_db_tables
    assert project.list_db_tables() == ["land_units"]

    # 2. Stage with _tables suffix and test normalization
    fake_proj = b"FAKE_PROJECTILES"
    out_proj = project.stage_db_table("audio_projectiles_tables", fake_proj)
    assert out_proj.is_file()
    assert out_proj == project.db_dir / "audio_projectiles_tables" / "audio_projectiles"
    assert "audio_projectiles" in project.manifest.staged_db_tables
    assert sorted(project.list_db_tables()) == ["audio_projectiles", "land_units"]

    # 3. Revert non-existent
    assert project.revert_db_table("audio_explosions") is False

    # 4. Revert land_units
    assert project.revert_db_table("land_units") is True
    assert not out_path.is_file()
    assert "land_units" not in project.manifest.staged_db_tables
    assert project.list_db_tables() == ["audio_projectiles"]


def test_project_manifest_db_persistence(tmp_path: Path):
    proj_dir = tmp_path / "persist_mod"
    project = ProjectStorage.create_project(proj_dir, "Persist Mod", GameType.ATTILA)
    project.stage_db_table("land_units", b"SAMPLE")
    ProjectStorage.save_project(project)

    reloaded = ProjectStorage.open_project(proj_dir)
    assert "land_units" in reloaded.manifest.staged_db_tables
    assert reloaded.list_db_tables() == ["land_units"]


def test_cache_db_dir():
    cache = GameCache(GameType.ATTILA)
    assert cache.db_dir == Path(".cache/attila/db")


def test_project_load_metadata_catalog_layered(tmp_path: Path):
    proj_dir = tmp_path / "layered_mod"
    cache = GameCache(GameType.ATTILA)
    project = ProjectStorage.create_project(proj_dir, "Layered Mod", GameType.ATTILA, cache=cache)

    # Empty project without staged tables loads catalog via cache fallback
    catalog = project.load_metadata_catalog()
    assert catalog is not None
    if cache.db_dir.is_dir():
        assert len(catalog.units) > 0


def test_project_load_metadata_catalog_overlay_precedence(tmp_path: Path):
    proj_dir = tmp_path / "overlay_prec_mod"
    cache = GameCache(GameType.ATTILA)
    project = ProjectStorage.create_project(proj_dir, "Overlay Mod", GameType.ATTILA, cache=cache)

    tsv_content = (
        b"key\tcategory\tclass\tselection_vo\tsecondary_vo\tprimary_melee_weapon\tarmour\tshield\n"
        b"#land_units;30;dummy\n"
        b"custom_modded_hero\tinfantry\tinf_mel\tcustom_vo_shout\tcustom_sec\tsword_01\tchain_01\tshield_wood\n"
    )
    project.stage_db_table("land_units.tsv", tsv_content)

    catalog = project.load_metadata_catalog()
    assert catalog is not None
    custom_unit = catalog.get_unit("custom_modded_hero")
    assert custom_unit is not None
    assert custom_unit.key == "custom_modded_hero"
    assert custom_unit.selection_vo == "custom_vo_shout"


def test_project_load_metadata_catalog_isolated_empty(tmp_path: Path):
    proj_dir = tmp_path / "isolated_empty_mod"
    empty_cache = GameCache(GameType.ATTILA, cache_dir=tmp_path / "empty_cache" / "audio")
    project = ProjectStorage.create_project(
        proj_dir, "Empty Mod", GameType.ATTILA, cache=empty_cache
    )

    catalog = project.load_metadata_catalog()
    assert catalog is not None
    assert len(catalog.units) == 0
    assert len(catalog.cultures) == 0
    assert len(catalog.projectiles) == 0
    assert len(catalog.explosions) == 0
    assert len(catalog.materials) == 0
