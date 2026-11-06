from pathlib import Path

import pytest

from src.compiler.pfh4_pack import write_pfh4_movie_pack
from src.workspace.dependencies import DependencyManager
from src.workspace.game import GameType
from src.workspace.manifest import DependencyPackInfo
from src.workspace.project import AudioProject
from src.workspace.resolver import AssetResolver
from src.workspace.storage import ProjectStorage


def test_natural_dependency_priority_order_in_resolver(tmp_path: Path):
    proj_dir = tmp_path / "PriorityProj"
    project = ProjectStorage.create_project(proj_dir, name="PriorityProj", game=GameType.ATTILA)

    # Dependency with Priority 0 (Highest Precedence)
    dep0_dir = project.get_dependency_dir("dep_p0.pack") / "audio"
    dep0_dir.mkdir(parents=True)
    (dep0_dir / "battle.bnk").write_bytes(b"BNK_PRIORITY_0")
    (dep0_dir / "100.wem").write_bytes(b"WEM_PRIORITY_0")
    (dep0_dir / "event_data.dat").write_bytes(b"DB_PRIORITY_0")

    # Dependency with Priority 1 (Lower Precedence)
    dep1_dir = project.get_dependency_dir("dep_p1.pack") / "audio"
    dep1_dir.mkdir(parents=True)
    (dep1_dir / "battle.bnk").write_bytes(b"BNK_PRIORITY_1")
    (dep1_dir / "100.wem").write_bytes(b"WEM_PRIORITY_1")
    (dep1_dir / "event_data.dat").write_bytes(b"DB_PRIORITY_1")

    # Dependency with Priority 5 (Lowest Precedence)
    dep5_dir = project.get_dependency_dir("dep_p5.pack") / "audio"
    dep5_dir.mkdir(parents=True)
    (dep5_dir / "battle.bnk").write_bytes(b"BNK_PRIORITY_5")
    (dep5_dir / "100.wem").write_bytes(b"WEM_PRIORITY_5")
    (dep5_dir / "event_data.dat").write_bytes(b"DB_PRIORITY_5")

    project.manifest.dependencies = [
        DependencyPackInfo(name="dep_p5.pack", source_path="/p5", priority=5),
        DependencyPackInfo(name="dep_p0.pack", source_path="/p0", priority=0),
        DependencyPackInfo(name="dep_p1.pack", source_path="/p1", priority=1),
    ]

    resolver = AssetResolver(project)

    # AssetResolver must resolve to Priority 0 because 0 is highest precedence
    assert resolver.resolve_bank_bytes("battle.bnk") == b"BNK_PRIORITY_0"
    assert resolver.resolve_wem_bytes(100) == b"WEM_PRIORITY_0"
    assert resolver.resolve_database_bytes() == b"DB_PRIORITY_0"


def test_metadata_catalog_multi_layer_priority_order(tmp_path: Path):
    proj_dir = tmp_path / "MetaPriorityProj"
    project = ProjectStorage.create_project(proj_dir, name="MetaPriorityProj", game=GameType.ATTILA)

    # Pack 0 (Priority 0): Submod changing VO to Templar Overhaul
    pack0_path = tmp_path / "submod_p0.pack"
    tsv_p0 = (
        "key\tselection_vo\tselected_vo_secondary\tselected_vo_tertiary\tculture\tsubculture\tcategory\n"
        "unit_knight\tvo_templar_high_priority\t\t\tculture_latin\tsubculture_crusader\tcavalry\n"
    )
    write_pfh4_movie_pack(pack0_path, {"db/land_units_tables/units": tsv_p0.encode("utf-8")})

    # Pack 1 (Priority 1): Base Overhaul
    pack1_path = tmp_path / "base_p1.pack"
    tsv_p1 = (
        "key\tselection_vo\tselected_vo_secondary\tselected_vo_tertiary\tculture\tsubculture\tcategory\n"
        "unit_knight\tvo_knight_base_overhaul\t\t\tculture_latin\tsubculture_crusader\tcavalry\n"
    )
    write_pfh4_movie_pack(pack1_path, {"db/land_units_tables/units": tsv_p1.encode("utf-8")})

    mgr = DependencyManager(project)
    mgr.execute_import(mgr.plan_import(pack0_path, priority=0))
    mgr.execute_import(mgr.plan_import(pack1_path, priority=1))

    catalog = project.load_metadata_catalog()
    unit = catalog.get_unit("unit_knight")
    assert unit is not None
    # Priority 0 must win over Priority 1
    assert unit.selection_vo == "vo_templar_high_priority"

    # Reorder priorities: make Pack 1 priority 0 and Pack 0 priority 1
    mgr.reorder_dependencies(["base_p1.pack", "submod_p0.pack"])
    catalog2 = project.load_metadata_catalog()
    unit2 = catalog2.get_unit("unit_knight")
    assert unit2 is not None
    # Now base_p1 (Priority 0) wins
    assert unit2.selection_vo == "vo_knight_base_overhaul"
