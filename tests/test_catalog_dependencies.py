from pathlib import Path

from src.workspace.game import GameType
from src.workspace.manifest import DependencyPackInfo, ProjectManifest
from src.workspace.project import AudioProject
from src.workspace.storage import ProjectStorage

TSV_UNITS_A = """key\tselection_vo\tselected_vo_secondary\tselected_vo_tertiary\tculture\tsubculture\tcategory\nunit_roman_infantry\tvo_rome\t\t\tculture_roman\tsubculture_roman\tinfantry\n"""

TSV_UNITS_B = """key\tselection_vo\tselected_vo_secondary\tselected_vo_tertiary\tculture\tsubculture\tcategory\nunit_greek_hoplite\tvo_greek\t\t\tculture_greek\tsubculture_greek\tspear\n"""

TSV_UNITS_OVERRIDE = """key\tselection_vo\tselected_vo_secondary\tselected_vo_tertiary\tculture\tsubculture\tcategory\nunit_roman_infantry\tvo_rome_overridden\t\t\tculture_roman\tsubculture_roman\tinfantry\n"""


def test_catalog_aggregates_units_across_multiple_dependencies(tmp_path: Path):
    proj_dir = tmp_path / "test_mod"
    manifest = ProjectManifest(
        name="TestMod",
        game=GameType.ATTILA,
        dependencies=[
            DependencyPackInfo(name="pack_a.pack", priority=0),
            DependencyPackInfo(name="pack_b.pack", priority=1),
        ],
    )
    project = AudioProject(root_dir=proj_dir, manifest=manifest)
    ProjectStorage.save_project(project)

    # Dependency A defines unit_roman_infantry
    dep_a_db = project.get_dependency_dir("pack_a.pack") / "db" / "land_units_tables"
    dep_a_db.mkdir(parents=True, exist_ok=True)
    (dep_a_db / "units_a.tsv").write_text(TSV_UNITS_A, encoding="utf-8")

    # Dependency B defines unit_greek_hoplite
    dep_b_db = project.get_dependency_dir("pack_b.pack") / "db" / "land_units_tables"
    dep_b_db.mkdir(parents=True, exist_ok=True)
    (dep_b_db / "units_b.tsv").write_text(TSV_UNITS_B, encoding="utf-8")

    catalog = project.load_metadata_catalog()

    # Both units must be resolved
    unit_a = catalog.get_unit("unit_roman_infantry")
    assert unit_a is not None
    assert unit_a.key == "unit_roman_infantry"
    assert unit_a.selection_vo == "vo_rome"

    unit_b = catalog.get_unit("unit_greek_hoplite")
    assert unit_b is not None
    assert unit_b.key == "unit_greek_hoplite"
    assert unit_b.selection_vo == "vo_greek"


def test_catalog_priority_override_across_dependencies(tmp_path: Path):
    proj_dir = tmp_path / "test_mod"
    manifest = ProjectManifest(
        name="TestMod",
        game=GameType.ATTILA,
        dependencies=[
            DependencyPackInfo(name="pack_a.pack", priority=1),
            DependencyPackInfo(name="pack_b.pack", priority=0),
        ],
    )
    project = AudioProject(root_dir=proj_dir, manifest=manifest)
    ProjectStorage.save_project(project)

    # Dependency A defines base unit_roman_infantry
    dep_a_db = project.get_dependency_dir("pack_a.pack") / "db" / "land_units_tables"
    dep_a_db.mkdir(parents=True, exist_ok=True)
    (dep_a_db / "units_a.tsv").write_text(TSV_UNITS_A, encoding="utf-8")

    # Dependency B overrides unit_roman_infantry
    dep_b_db = project.get_dependency_dir("pack_b.pack") / "db" / "land_units_tables"
    dep_b_db.mkdir(parents=True, exist_ok=True)
    (dep_b_db / "units_override.tsv").write_text(TSV_UNITS_OVERRIDE, encoding="utf-8")

    catalog = project.load_metadata_catalog()
    unit = catalog.get_unit("unit_roman_infantry")
    assert unit is not None
    assert unit.selection_vo == "vo_rome_overridden"


TSV_ARMOUR_A = """key\taudio_material
leather\tmat_leather
iron\tmat_iron
"""

TSV_ARMOUR_B = """key\taudio_material
chainmail_mk\tmat_chainmail
iron\tmat_heavy_iron
"""

TSV_WEAPONS_A = """key\taudio_material
gladivs\tmat_sword
"""

TSV_UNITS_CROSS = """key\tselection_vo\tselected_vo_secondary\tselected_vo_tertiary\tculture\tsubculture\tcategory\tarmour\tprimary_melee_weapon
unit_crusader\tvo_crusader\t\t\tculture_latin\tsubculture_crusader\tinfantry\tchainmail_mk\tgladivs
"""


def test_catalog_aggregates_materials_and_cross_table_links_across_dependencies(tmp_path: Path):
    proj_dir = tmp_path / "test_mod"
    manifest = ProjectManifest(
        name="TestMod",
        game=GameType.ATTILA,
        dependencies=[
            DependencyPackInfo(name="pack_a.pack", priority=1),
            DependencyPackInfo(name="pack_b.pack", priority=0),
        ],
    )
    project = AudioProject(root_dir=proj_dir, manifest=manifest)
    ProjectStorage.save_project(project)

    # Dependency A defines base armour (leather, iron) and weapons (gladivs)
    dep_a_armour = project.get_dependency_dir("pack_a.pack") / "db" / "unit_armour_types_tables"
    dep_a_armour.mkdir(parents=True, exist_ok=True)
    (dep_a_armour / "armour_a.tsv").write_text(TSV_ARMOUR_A, encoding="utf-8")

    dep_a_weapons = project.get_dependency_dir("pack_a.pack") / "db" / "melee_weapons_tables"
    dep_a_weapons.mkdir(parents=True, exist_ok=True)
    (dep_a_weapons / "weapons_a.tsv").write_text(TSV_WEAPONS_A, encoding="utf-8")

    # Dependency B defines new armour (chainmail_mk), overrides iron, and defines unit_crusader
    dep_b_armour = project.get_dependency_dir("pack_b.pack") / "db" / "unit_armour_types_tables"
    dep_b_armour.mkdir(parents=True, exist_ok=True)
    (dep_b_armour / "armour_b.tsv").write_text(TSV_ARMOUR_B, encoding="utf-8")

    dep_b_units = project.get_dependency_dir("pack_b.pack") / "db" / "land_units_tables"
    dep_b_units.mkdir(parents=True, exist_ok=True)
    (dep_b_units / "units_b.tsv").write_text(TSV_UNITS_CROSS, encoding="utf-8")

    catalog = project.load_metadata_catalog()

    # Verify material aggregation
    armour_mats = {
        m.material_key: m.audio_material for m in catalog.get_materials_for_category("armour")
    }
    assert "leather" in armour_mats, "Base armour from pack_a must not be lost"
    assert armour_mats["leather"] == "mat_leather"
    assert "chainmail_mk" in armour_mats, "New armour from pack_b must be included"
    assert armour_mats["chainmail_mk"] == "mat_chainmail"
    assert armour_mats["iron"] == "mat_heavy_iron", (
        "Higher priority pack_b must override iron material"
    )

    weapon_mats = {
        m.material_key: m.audio_material for m in catalog.get_materials_for_category("weapon")
    }
    assert "gladivs" in weapon_mats
    assert weapon_mats["gladivs"] == "mat_sword"

    # Verify cross-table foreign key linkage: unit_crusader in pack_b links to armour in pack_b and weapon in pack_a
    unit = catalog.get_unit("unit_crusader")
    assert unit is not None
    assert unit.armour_material == "mat_chainmail"
    assert unit.primary_weapon_material == "mat_sword"


def test_catalog_loads_native_binary_tables_from_dependencies(tmp_path: Path):
    import struct

    proj_dir = tmp_path / "test_mod"
    manifest = ProjectManifest(
        name="TestMod",
        game=GameType.ATTILA,
        dependencies=[
            DependencyPackInfo(name="binary_dep.pack", priority=0),
        ],
    )
    project = AudioProject(root_dir=proj_dir, manifest=manifest)
    ProjectStorage.save_project(project)

    # Construct raw binary audio_explosions table
    guid_bytes = "test-guid".encode("utf-16-le")
    header = (
        b"\xfd\xfe\xfc\xff"
        + struct.pack("<H", len(guid_bytes) // 2)
        + guid_bytes
        + b"\xfc\xfd\xfe\xff"
        + struct.pack("<IBI", 2, 1, 1)
    )
    ev_bytes = b"dep_binary_explosion_event"
    key_bytes = b"mortar_shell"
    payload = (
        header
        + b"\x01"
        + struct.pack("<H", len(ev_bytes))
        + ev_bytes
        + struct.pack("<H", len(key_bytes))
        + key_bytes
        + struct.pack("<f", 150.0)
        + b"\x00"
    )

    dep_dir = project.get_dependency_dir("binary_dep.pack") / "db" / "audio_explosions_tables"
    dep_dir.mkdir(parents=True, exist_ok=True)
    # Write native binary table without .tsv extension
    (dep_dir / "audio_explosions").write_bytes(payload)

    catalog = project.load_metadata_catalog()
    exp = catalog.get_explosion("mortar_shell")
    assert exp is not None
    assert exp.key == "mortar_shell"
    assert exp.event == "dep_binary_explosion_event"
    assert exp.group_event is None
