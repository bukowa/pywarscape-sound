from pathlib import Path

from src.models.parser import (
    find_table_tsv,
    parse_audio_explosions,
    parse_audio_projectiles,
    parse_culture_junctions,
    parse_land_units,
    parse_material_sfx,
    parse_melee_weapons,
    parse_tsv_rows,
    parse_unit_armour_types,
    parse_unit_shield_types,
)


def test_parse_tsv_rows_skips_metadata_and_normalizes_empty(tmp_path: Path):
    tsv_content = (
        "key\tcategory\tselection_vo\n"
        "#land_units_tables;30;db/land_units_tables/land_units\t\t\n"
        "unit_1\tinfantry\tselected_inf_melee\n"
        "unit_2\tcavalry\t\n"
        "unit_3\t\tselected_cavalry\n"
    )
    p = tmp_path / "land_units.tsv"
    p.write_text(tsv_content, encoding="utf-8")

    rows = parse_tsv_rows(p)
    assert len(rows) == 3
    assert rows[0] == {
        "key": "unit_1",
        "category": "infantry",
        "selection_vo": "selected_inf_melee",
    }
    assert rows[1] == {"key": "unit_2", "category": "cavalry", "selection_vo": None}
    assert rows[2] == {"key": "unit_3", "category": None, "selection_vo": "selected_cavalry"}


def test_cross_table_foreign_key_resolution(tmp_path: Path):
    armour_tsv = "key\tarmour_value\taudio_material\n#unit_armour_types;1;path\t\t\natt_iron\t50\tchainmail\n"
    shield_tsv = (
        "key\tdefence\taudio_material\n#unit_shield_types;1;path\t\t\natt_shield\t10\twood\n"
    )
    weapon_tsv = "key\tdamage\taudio_material\n#melee_weapons;1;path\t\t\natt_sword\t20\tsword\n"
    unit_tsv = (
        "key\tcategory\tclass\tarmour\tshield\tprimary_melee_weapon\tselection_vo\tselected_vo_secondary\tselected_vo_tertiary\n"
        "#land_units;1;path\t\t\t\t\t\t\t\t\n"
        "hero_unit\tinfantry\tinf_mel\tatt_iron\tatt_shield\tatt_sword\tselected_inf_melee\tselected_inf\tselected_generic\n"
    )
    (tmp_path / "unit_armour_types.tsv").write_text(armour_tsv, encoding="utf-8")
    (tmp_path / "unit_shield_types.tsv").write_text(shield_tsv, encoding="utf-8")
    (tmp_path / "melee_weapons.tsv").write_text(weapon_tsv, encoding="utf-8")
    (tmp_path / "land_units.tsv").write_text(unit_tsv, encoding="utf-8")

    armour_map = parse_unit_armour_types(tmp_path / "unit_armour_types.tsv")
    shield_map = parse_unit_shield_types(tmp_path / "unit_shield_types.tsv")
    weapon_map = parse_melee_weapons(tmp_path / "melee_weapons.tsv")

    units = parse_land_units(
        tmp_path / "land_units.tsv",
        armour_materials=armour_map,
        shield_materials=shield_map,
        weapon_materials=weapon_map,
    )
    assert len(units) == 1
    u = units["hero_unit"]
    assert u.armour_material == "chainmail"
    assert u.shield_material == "wood"
    assert u.primary_weapon_material == "sword"


def test_find_table_tsv_locates_both_flat_and_nested_layouts(tmp_path: Path):
    flat = tmp_path / "flat"
    flat.mkdir()
    (flat / "audio_projectiles.tsv").write_text("key\tfire_event\n", encoding="utf-8")
    assert find_table_tsv(flat, "audio_projectiles") == flat / "audio_projectiles.tsv"

    nested = tmp_path / "nested"
    nested_table = nested / "audio_projectiles_tables"
    nested_table.mkdir(parents=True)
    (nested_table / "audio_projectiles.tsv").write_text("key\tfire_event\n", encoding="utf-8")
    assert find_table_tsv(nested, "audio_projectiles") == nested_table / "audio_projectiles.tsv"

    # Mod-prefixed table discovery (e.g. custom_land_units.tsv inside land_units_tables)
    mod_dir = tmp_path / "mod_pack"
    mod_table_dir = mod_dir / "db" / "land_units_tables"
    mod_table_dir.mkdir(parents=True)
    (mod_table_dir / "custom_land_units.tsv").write_text("key\tcategory\n", encoding="utf-8")
    assert find_table_tsv(mod_dir, "land_units") == mod_table_dir / "custom_land_units.tsv"


def test_parse_tsv_rows_utf8_bom(tmp_path: Path):
    # Simulates TSV exported with UTF-8 BOM (\ufeff)
    tsv_content = (
        "\ufeffkey\tcategory\tselection_vo\n#table\nunit_1\tinfantry\tselected_inf_melee\n"
    )
    p = tmp_path / "bom_table.tsv"
    p.write_bytes(tsv_content.encode("utf-8"))

    rows = parse_tsv_rows(p)
    assert len(rows) == 1
    assert "key" in rows[0]
    assert rows[0]["key"] == "unit_1"


def test_parse_projectiles_and_explosions(tmp_path: Path):
    proj_tsv = (
        "key\tfire_event\tfire_group_event\tincoming_event\timpact_event\timpact_blood_event\tinflight_start_event\tinflight_stop_event\thit_tree_start_event\thit_tree_stop_event\tidle_start_event\tidle_stop_event\n"
        "#audio_projectiles;1;path\n"
        "arrow\tprojectile_fire_arrow\t\t\tprojectile_impact_arrow\tprojectile_impact_blood\tprojectile_inflight_arrow_play\t\t\t\t\t\n"
    )
    exp_tsv = (
        "key\tevent\tgroup_event\n"
        "#audio_explosions;1;path\n"
        "beehive\tprojectile_explosion_beehive\t\n"
    )
    (tmp_path / "audio_projectiles.tsv").write_text(proj_tsv, encoding="utf-8")
    (tmp_path / "audio_explosions.tsv").write_text(exp_tsv, encoding="utf-8")

    projs = parse_audio_projectiles(tmp_path / "audio_projectiles.tsv")
    assert len(projs) == 1
    p = projs["arrow"]
    assert p.fire_event == "projectile_fire_arrow"
    assert p.fire_group_event is None
    assert p.impact_blood_event == "projectile_impact_blood"

    exps = parse_audio_explosions(tmp_path / "audio_explosions.tsv")
    assert len(exps) == 1
    assert exps["beehive"].event == "projectile_explosion_beehive"


def test_parse_culture_junctions_and_materials(tmp_path: Path):
    cult_tsv = (
        "religion\tsubculture\tvoiceover_culture\n"
        "#subculture_religion_voiceover_junctions;1;path\n"
        "rel_1\tsub_1\tbarbarian_christian\n"
    )
    (tmp_path / "subculture_religion_voiceover_junctions.tsv").write_text(
        cult_tsv, encoding="utf-8"
    )
    cults = parse_culture_junctions(tmp_path / "subculture_religion_voiceover_junctions.tsv")
    assert len(cults) == 1
    assert cults[0].voiceover_culture == "barbarian_christian"

    armour_tsv = "key\taudio_material\n#table\nplate\tiron\n"
    (tmp_path / "armour.tsv").write_text(armour_tsv, encoding="utf-8")
    mats = parse_material_sfx(armour_path=tmp_path / "armour.tsv")
    assert len(mats) == 1
    assert mats[0].category == "armour"
    assert mats[0].audio_material == "iron"
    assert mats[0].target_switch_group == "armour_type"
