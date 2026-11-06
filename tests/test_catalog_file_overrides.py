from pathlib import Path

from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.manifest import DependencyPackInfo, ProjectManifest
from src.workspace.project import AudioProject
from src.workspace.storage import ProjectStorage

TSV_VANILLA_UNITS = """key\tselection_vo\tselected_vo_secondary\tselected_vo_tertiary\tculture\tsubculture\tcategory
vanilla_legionary\tvo_rome\t\t\tculture_roman\tsubculture_roman\tinfantry
vanilla_auxiliary\tvo_rome\t\t\tculture_roman\tsubculture_roman\tspear
vanilla_cavalry\tvo_rome\t\t\tculture_roman\tsubculture_roman\tcavalry
"""

TSV_MOD_DATA_REPLACEMENT = """key\tselection_vo\tselected_vo_secondary\tselected_vo_tertiary\tculture\tsubculture\tcategory
mod_sole_unit\tvo_mod\t\t\tculture_mod\tsubculture_mod\tinfantry
"""

TSV_MOD_ADDITIVE = """key\tselection_vo\tselected_vo_secondary\tselected_vo_tertiary\tculture\tsubculture\tcategory
mod_extra_knight\tvo_knight\t\t\tculture_knight\tsubculture_knight\tcavalry
"""

TSV_MOD_COLLISION = """key\tselection_vo\tselected_vo_secondary\tselected_vo_tertiary\tculture\tsubculture\tcategory
vanilla_legionary\tvo_rome_customized\t\t\tculture_roman\tsubculture_roman\tinfantry
"""


def test_catalog_same_filename_overrides_and_discards_lower_priority_file(tmp_path: Path):
    """
    Scenario 1: Mod pack defines data__ table file in land_units_tables.
    Because vanilla also defines data__, the mod file completely replaces vanilla data__.
    Only mod rows exist; vanilla rows must NOT be loaded.
    """
    proj_dir = tmp_path / "test_mod"
    cache_dir = tmp_path / "mock_cache"

    # Setup vanilla cache with land_units_tables/data__
    cache_db = cache_dir / "db" / "land_units_tables"
    cache_db.mkdir(parents=True, exist_ok=True)
    (cache_db / "data__").write_text(TSV_VANILLA_UNITS, encoding="utf-8")

    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir / "audio")

    # Project with 1 dependency pack
    manifest = ProjectManifest(
        name="TestMod",
        game=GameType.ATTILA,
        dependencies=[
            DependencyPackInfo(name="overhaul.pack", priority=0),
        ],
    )
    project = AudioProject(root_dir=proj_dir, manifest=manifest, cache=cache)
    ProjectStorage.save_project(project)

    # Dependency defines land_units_tables/data__ (SAME FILENAME)
    dep_db = project.get_dependency_dir("overhaul.pack") / "db" / "land_units_tables"
    dep_db.mkdir(parents=True, exist_ok=True)
    (dep_db / "data__").write_text(TSV_MOD_DATA_REPLACEMENT, encoding="utf-8")

    catalog = project.load_metadata_catalog()

    # The mod unit must exist
    assert catalog.get_unit("mod_sole_unit") is not None

    # Vanilla units from data__ must have been discarded completely!
    assert catalog.get_unit("vanilla_legionary") is None
    assert catalog.get_unit("vanilla_auxiliary") is None
    assert catalog.get_unit("vanilla_cavalry") is None
    assert len(catalog.units) == 1


def test_catalog_different_filename_accumulates_rows(tmp_path: Path):
    """
    Scenario 2: Mod pack defines custom-named table file (e.g. mk_units).
    Because the filename is different from vanilla data__, both files are loaded and their rows accumulate.
    """
    proj_dir = tmp_path / "test_mod"
    cache_dir = tmp_path / "mock_cache"

    # Setup vanilla cache with land_units_tables/data__
    cache_db = cache_dir / "db" / "land_units_tables"
    cache_db.mkdir(parents=True, exist_ok=True)
    (cache_db / "data__").write_text(TSV_VANILLA_UNITS, encoding="utf-8")

    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir / "audio")

    manifest = ProjectManifest(
        name="TestMod",
        game=GameType.ATTILA,
        dependencies=[
            DependencyPackInfo(name="submod.pack", priority=0),
        ],
    )
    project = AudioProject(root_dir=proj_dir, manifest=manifest, cache=cache)
    ProjectStorage.save_project(project)

    # Dependency defines land_units_tables/mk_units (DIFFERENT FILENAME)
    dep_db = project.get_dependency_dir("submod.pack") / "db" / "land_units_tables"
    dep_db.mkdir(parents=True, exist_ok=True)
    (dep_db / "mk_units").write_text(TSV_MOD_ADDITIVE, encoding="utf-8")

    catalog = project.load_metadata_catalog()

    # All 3 vanilla units must still exist
    assert catalog.get_unit("vanilla_legionary") is not None
    assert catalog.get_unit("vanilla_auxiliary") is not None
    assert catalog.get_unit("vanilla_cavalry") is not None

    # The additive mod unit must also exist
    assert catalog.get_unit("mod_extra_knight") is not None
    assert len(catalog.units) == 4


def test_catalog_different_filename_row_collision_overwrites_key(tmp_path: Path):
    """
    Scenario 3: Mod pack defines custom-named table file containing a row with the same key
    as vanilla data__. That specific entity is updated by the mod, while other vanilla units remain.
    """
    proj_dir = tmp_path / "test_mod"
    cache_dir = tmp_path / "mock_cache"

    cache_db = cache_dir / "db" / "land_units_tables"
    cache_db.mkdir(parents=True, exist_ok=True)
    (cache_db / "data__").write_text(TSV_VANILLA_UNITS, encoding="utf-8")

    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir / "audio")

    manifest = ProjectManifest(
        name="TestMod",
        game=GameType.ATTILA,
        dependencies=[
            DependencyPackInfo(name="patch.pack", priority=0),
        ],
    )
    project = AudioProject(root_dir=proj_dir, manifest=manifest, cache=cache)
    ProjectStorage.save_project(project)

    dep_db = project.get_dependency_dir("patch.pack") / "db" / "land_units_tables"
    dep_db.mkdir(parents=True, exist_ok=True)
    (dep_db / "patch_units").write_text(TSV_MOD_COLLISION, encoding="utf-8")

    catalog = project.load_metadata_catalog()

    # vanilla_legionary must be updated with mod's selection_vo
    legionary = catalog.get_unit("vanilla_legionary")
    assert legionary is not None
    assert legionary.selection_vo == "vo_rome_customized"

    # Other vanilla units are preserved
    assert catalog.get_unit("vanilla_auxiliary") is not None
    assert catalog.get_unit("vanilla_cavalry") is not None
    assert len(catalog.units) == 3


def test_catalog_multi_dependency_filename_override(tmp_path: Path):
    """
    Scenario 4: Dependency A (priority 0) and Dependency B (priority 1) both define 'custom_table'.
    Dependency B completely overrides Dependency A's 'custom_table'.
    """
    proj_dir = tmp_path / "test_mod"
    empty_cache = GameCache(GameType.ATTILA, cache_dir=tmp_path / "mock_cache" / "audio")
    manifest = ProjectManifest(
        name="TestMod",
        game=GameType.ATTILA,
        dependencies=[
            DependencyPackInfo(name="dep_a.pack", priority=1),
            DependencyPackInfo(name="dep_b.pack", priority=0),
        ],
    )
    project = AudioProject(root_dir=proj_dir, manifest=manifest, cache=empty_cache)
    ProjectStorage.save_project(project)

    dep_a_db = project.get_dependency_dir("dep_a.pack") / "db" / "land_units_tables"
    dep_a_db.mkdir(parents=True, exist_ok=True)
    (dep_a_db / "custom_table").write_text(
        """key\tselection_vo\tcategory\nunit_from_a\tvo_a\tinfantry\n""", encoding="utf-8"
    )

    dep_b_db = project.get_dependency_dir("dep_b.pack") / "db" / "land_units_tables"
    dep_b_db.mkdir(parents=True, exist_ok=True)
    (dep_b_db / "custom_table").write_text(
        """key\tselection_vo\tcategory\nunit_from_b\tvo_b\tcavalry\n""", encoding="utf-8"
    )

    catalog = project.load_metadata_catalog()

    # Unit from dep_b must exist; unit from dep_a must have been overridden completely
    assert catalog.get_unit("unit_from_b") is not None
    assert catalog.get_unit("unit_from_a") is None
    assert len(catalog.units) == 1
