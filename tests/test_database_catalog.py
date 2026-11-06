from pathlib import Path

import pytest

from src.models.catalog import AudioMetadataCatalog
from src.models.metadata import (
    CultureVoiceMetadata,
    ExplosionAudioMetadata,
    MaterialSFXMetadata,
    ProjectileAudioMetadata,
    UnitMetadata,
)


@pytest.fixture
def sample_catalog():
    units = {
        "unit_swords": UnitMetadata(
            key="unit_swords",
            category="infantry",
            unit_class="inf_mel",
            selection_vo="selected_inf_melee",
            secondary_vo="selected_swordsmen",
            tertiary_vo="selected_generic",
            armour_material="chainmail",
            shield_material="wood",
            primary_weapon_material="sword",
        ),
        "unit_cav": UnitMetadata(
            key="unit_cav",
            category="cavalry",
            unit_class="cav_mis",
            selection_vo="selected_cavalry_missile",
            secondary_vo="selected_cavalry",
            tertiary_vo="selected_generic",
            armour_material="leather",
            shield_material=None,
            primary_weapon_material="spear",
        ),
    }
    cultures = [
        CultureVoiceMetadata("rel_catholic", "subcult_celtic", "barbarian_christian"),
        CultureVoiceMetadata("rel_pagan", "subcult_germanic", "barbarian_pagan"),
    ]
    projectiles = {
        "arrow": ProjectileAudioMetadata(
            key="arrow",
            fire_event="projectile_fire_arrow",
            fire_group_event=None,
            incoming_event=None,
            impact_event="projectile_impact_arrow",
            impact_blood_event=None,
            inflight_start_event="projectile_inflight_arrow_play",
            inflight_stop_event=None,
            hit_tree_start_event=None,
            hit_tree_stop_event=None,
            idle_start_event=None,
            idle_stop_event=None,
        )
    }
    explosions = {
        "fireball": ExplosionAudioMetadata("fireball", "projectile_explosion_fireball", None)
    }
    materials = [
        MaterialSFXMetadata("att_chainmail", "armour", "chainmail", "armour_type"),
        MaterialSFXMetadata("att_shield_wood", "shield", "wood", "shield_type"),
    ]
    return AudioMetadataCatalog(units, cultures, projectiles, explosions, materials)


def test_unit_lookup_case_insensitive(sample_catalog):
    assert sample_catalog.get_unit("UNIT_SWORDS") is not None
    assert sample_catalog.get_unit("unit_swords").key == "unit_swords"
    assert sample_catalog.get_unit("nonexistent") is None


def test_units_by_order_switch(sample_catalog):
    inf = sample_catalog.get_units_for_order_switch("SELECTED_INF_MELEE")
    assert len(inf) == 1
    assert inf[0].key == "unit_swords"

    # With secondary included
    swords = sample_catalog.get_units_for_order_switch("selected_swordsmen", include_secondary=True)
    assert len(swords) == 1
    assert swords[0].key == "unit_swords"


def test_projectile_by_event(sample_catalog):
    projs = sample_catalog.get_projectiles_for_event("PROJECTILE_FIRE_ARROW")
    assert len(projs) == 1
    assert projs[0].key == "arrow"


def test_culture_resolution(sample_catalog):
    cult = sample_catalog.resolve_culture_for_faction("subcult_celtic", "rel_catholic")
    assert cult == "barbarian_christian"
    assert sample_catalog.resolve_culture_for_faction("unknown", "unknown") is None


def test_materials_by_switch_group(sample_catalog):
    mats = sample_catalog.get_materials_for_switch_group("armour_type")
    assert len(mats) == 1
    assert mats[0].audio_material == "chainmail"


def test_catalog_none_defense(sample_catalog):
    assert sample_catalog.get_unit(None) is None
    assert sample_catalog.get_units_for_order_switch(None) == []
    assert sample_catalog.get_units_by_category(None) == []
    assert sample_catalog.get_projectile(None) is None
    assert sample_catalog.get_projectiles_for_event(None) == []
    assert sample_catalog.get_explosion(None) is None
    assert sample_catalog.get_explosions_for_event(None) == []
    assert sample_catalog.resolve_culture_for_faction(None, "rel") is None
    assert sample_catalog.resolve_culture_for_faction("sub", None) is None
    assert sample_catalog.get_materials_for_category(None) == []
    assert sample_catalog.get_materials_for_switch_group(None) == []


def test_catalog_from_directory_factory(tmp_path: Path):
    armour_tsv = (
        "key\tarmour_value\taudio_material\n#unit_armour_types;1;path\natt_iron\t50\tchainmail\n"
    )
    shield_tsv = "key\tdefence\taudio_material\n#unit_shield_types;1;path\natt_wood\t10\twood\n"
    weapon_tsv = "key\tdamage\taudio_material\n#melee_weapons;1;path\natt_sword\t20\tsword\n"
    unit_tsv = (
        "key\tcategory\tclass\tarmour\tshield\tprimary_melee_weapon\tselection_vo\tselected_vo_secondary\tselected_vo_tertiary\n"
        "#land_units;1;path\n"
        "unit_roman\tinfantry\tinf_mel\tatt_iron\tatt_wood\tatt_sword\tselected_legionaries\t\t\n"
    )
    cult_tsv = "religion\tsubculture\tvoiceover_culture\n#table\nrel_rome\tsub_rome\troman\n"
    proj_tsv = "key\tfire_event\n#table\npilum\tprojectile_fire_pilum\n"
    exp_tsv = "key\tevent\n#table\npot\texplosion_pot\n"

    (tmp_path / "unit_armour_types.tsv").write_text(armour_tsv, encoding="utf-8")
    (tmp_path / "unit_shield_types.tsv").write_text(shield_tsv, encoding="utf-8")
    (tmp_path / "melee_weapons.tsv").write_text(weapon_tsv, encoding="utf-8")
    (tmp_path / "land_units.tsv").write_text(unit_tsv, encoding="utf-8")
    (tmp_path / "subculture_religion_voiceover_junctions.tsv").write_text(
        cult_tsv, encoding="utf-8"
    )
    (tmp_path / "audio_projectiles.tsv").write_text(proj_tsv, encoding="utf-8")
    (tmp_path / "audio_explosions.tsv").write_text(exp_tsv, encoding="utf-8")

    cat = AudioMetadataCatalog.from_directory(tmp_path)
    assert len(cat.units) == 1
    u = cat.get_unit("unit_roman")
    assert u is not None
    assert u.armour_material == "chainmail"
    assert u.shield_material == "wood"
    assert u.primary_weapon_material == "sword"
    assert cat.resolve_culture_for_faction("sub_rome", "rel_rome") == "roman"
    assert len(cat.get_projectiles_for_event("projectile_fire_pilum")) == 1
