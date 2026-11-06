from pathlib import Path

import pytest

from src.bnk.database import SoundDatabase, fnv1_32
from src.models.catalog import AudioMetadataCatalog
from tests.support.factories import skip_or_fail_missing_asset

DB_DIR = Path(".cache/attila/db")
EVENT_DATA_PATH = Path(".cache/attila/audio/event_data.dat")


@pytest.fixture(scope="module")
def attila_sound_db():
    if not EVENT_DATA_PATH.is_file():
        skip_or_fail_missing_asset(f"event_data.dat not found at {EVENT_DATA_PATH}")
    return SoundDatabase.from_file(EVENT_DATA_PATH)


@pytest.fixture(scope="module")
def attila_catalog():
    if not DB_DIR.is_dir():
        skip_or_fail_missing_asset(f"Cache DB directory not found at {DB_DIR}")
    return AudioMetadataCatalog.from_directory(DB_DIR)


@pytest.mark.assets
def test_attila_land_unit_coverage(attila_catalog, attila_sound_db):
    """
    100% of the 1,117 land units must parse into UnitMetadata;
    1,105 units (100% of units referencing base-game switches) must resolve to valid Wwise VO_battle_order switches;
    and the 12 DLC Age of Charlemagne (cha_) units referencing DLC switches must parse cleanly with secondary/tertiary fallback orders.
    """
    assert len(attila_catalog.units) == 1117

    order_group_id = fnv1_32("VO_battle_order")
    assert order_group_id in attila_sound_db.switch_groups
    valid_orders = {s.lower() for s in attila_sound_db.switch_groups[order_group_id].switch_names}

    matching_units = [
        u for u in attila_catalog.units.values() if u.selection_vo.lower() in valid_orders
    ]
    assert len(matching_units) == 1105

    unmatched_units = [
        u for u in attila_catalog.units.values() if u.selection_vo.lower() not in valid_orders
    ]
    assert len(unmatched_units) == 12
    for u in unmatched_units:
        assert u.key.startswith("cha_")
        assert u.selection_vo is not None
        assert u.tertiary_vo is not None


@pytest.mark.assets
def test_attila_projectile_event_validation(attila_catalog, attila_sound_db):
    """
    100% of non-null fire, impact, and inflight events in audio_projectiles must exist in compiled event_data.dat.
    """
    assert len(attila_catalog.projectiles) == 28

    compiled_event_hashes = set(attila_sound_db.events.keys())
    for proj in attila_catalog.projectiles.values():
        for event_name in [proj.fire_event, proj.impact_event, proj.inflight_start_event]:
            if event_name:
                h = fnv1_32(event_name)
                assert h in compiled_event_hashes, (
                    f"Projectile {proj.key} references missing event {event_name}"
                )


@pytest.mark.assets
def test_attila_culture_junction_resolution(attila_catalog, attila_sound_db):
    """
    All 120 religion/subculture pairs must resolve to valid Wwise voiceover culture switches or states.
    """
    assert len(attila_catalog.cultures) == 120

    # Collect valid culture switches and state values
    valid_cultures = set()
    for name in ["culture", "VO_battle_culture"]:
        sg = attila_sound_db.switch_groups.get(fnv1_32(name))
        if sg:
            valid_cultures.update(s.lower() for s in sg.switch_names)

    for name in ["vo_battle_subculture", "vo_campaign_subculture"]:
        stg = attila_sound_db.state_groups.get(fnv1_32(name))
        if stg:
            valid_cultures.update(s.lower() for s in stg.state_names)

    for c in attila_catalog.cultures:
        cult = attila_catalog.resolve_culture_for_faction(c.subculture, c.religion)
        assert cult is not None, f"Failed resolving culture for {c.subculture} + {c.religion}"
        assert cult.lower() in valid_cultures, (
            f"Resolved culture {cult} not in Wwise culture switches/states"
        )


@pytest.mark.assets
def test_attila_physical_sfx_integrity(attila_catalog, attila_sound_db):
    """
    All armor and shield materials must map to valid Wwise collision material switches.
    """
    armour_sg = attila_sound_db.switch_groups.get(fnv1_32("armour_type"))
    shield_sg = attila_sound_db.switch_groups.get(fnv1_32("shield_type"))
    impact_sg = attila_sound_db.switch_groups.get(fnv1_32("projectile_impact_material"))

    assert armour_sg is not None
    assert shield_sg is not None
    assert impact_sg is not None

    valid_armour = {s.lower() for s in armour_sg.switch_names} | {
        s.lower() for s in impact_sg.switch_names
    }
    valid_shield = {s.lower() for s in shield_sg.switch_names} | {
        s.lower() for s in impact_sg.switch_names
    }

    armour_mats = attila_catalog.get_materials_for_category("armour")
    assert len(armour_mats) == 34
    for m in armour_mats:
        assert m.audio_material.lower() in valid_armour, (
            f"Armor {m.material_key} audio_material {m.audio_material} not in Wwise"
        )

    shield_mats = attila_catalog.get_materials_for_category("shield")
    assert len(shield_mats) == 28
    for m in shield_mats:
        assert m.audio_material.lower() in valid_shield, (
            f"Shield {m.material_key} audio_material {m.audio_material} not in Wwise"
        )


def test_synthetic_catalog_and_sound_db_cross_validation(tmp_path: Path):
    """Hermetic cross-validation: synthetic AudioMetadataCatalog matches synthetic SoundDatabase."""
    from tests.support.factories import encode_binary_db_table

    db_dir = tmp_path / "db"

    # 1. Create synthetic binary tables
    tables = {
        "land_units": [
            {
                "key": "test_unit",
                "category": "infantry",
                "selection_vo": "charge",
                "armour": "iron",
                "shield": "wood",
                "primary_melee_weapon": "sword",
            }
        ],
        "subculture_religion_voiceover_junctions": [
            {"religion": "rel_a", "subculture": "sub_a", "voiceover_culture": "roman"}
        ],
        "audio_projectiles": [
            {
                "key": "test_proj",
                "fire_event": "event_proj_fire",
                "impact_event": "event_proj_impact",
                "inflight_start_event": "event_proj_fly",
            }
        ],
        "audio_explosions": [{"key": "test_expl", "event": "event_expl", "max_attenuation": 100.0}],
        "unit_armour_types": [
            {"key": "iron", "armour_value": 15, "audio_material": "armour_metal"}
        ],
        "unit_shield_types": [
            {"key": "wood", "shield_defence_value": 8, "audio_material": "shield_wood"}
        ],
        "melee_weapons": [{"key": "sword", "audio_material": "mat_steel"}],
    }

    for tbl_name, rows in tables.items():
        tbl_path = db_dir / f"{tbl_name}_tables" / tbl_name
        tbl_path.parent.mkdir(parents=True, exist_ok=True)
        tbl_path.write_bytes(encode_binary_db_table(tbl_name, rows))

    # 2. Create synthetic SoundDatabase
    sound_db = SoundDatabase()
    sound_db.add_event("event_proj_fire", 2.0)
    sound_db.add_event("event_proj_impact", 1.5)
    sound_db.add_event("event_proj_fly", 3.0)
    sound_db.add_event("event_expl", 4.0)

    sound_db.add_switch_group("VO_battle_order", ["charge", "move", "halt"])
    sound_db.add_switch_group("culture", ["roman", "greek"])
    sound_db.add_switch_group("armour_type", ["armour_metal"])
    sound_db.add_switch_group("shield_type", ["shield_wood"])
    sound_db.add_switch_group("projectile_impact_material", ["armour_metal", "shield_wood"])

    # 3. Assemble catalog and cross-validate
    catalog = AudioMetadataCatalog.from_directory(db_dir)

    # Land units
    assert "test_unit" in catalog.units
    unit = catalog.units["test_unit"]
    order_sg = sound_db.switch_groups[fnv1_32("VO_battle_order")]
    assert unit.selection_vo in order_sg.switches.values()

    # Audio projectiles
    assert "test_proj" in catalog.projectiles
    proj = catalog.projectiles["test_proj"]
    for ev in [proj.fire_event, proj.impact_event, proj.inflight_start_event]:
        assert fnv1_32(ev) in sound_db.events

    # Cultures
    cult = catalog.resolve_culture_for_faction("sub_a", "rel_a")
    assert cult == "roman"
    assert cult in sound_db.switch_groups[fnv1_32("culture")].switches.values()

    # Materials
    armour_mats = catalog.get_materials_for_category("armour")
    assert len(armour_mats) == 1
    assert (
        armour_mats[0].audio_material
        in sound_db.switch_groups[fnv1_32("armour_type")].switches.values()
    )

    shield_mats = catalog.get_materials_for_category("shield")
    assert len(shield_mats) == 1
    assert (
        shield_mats[0].audio_material
        in sound_db.switch_groups[fnv1_32("shield_type")].switches.values()
    )
