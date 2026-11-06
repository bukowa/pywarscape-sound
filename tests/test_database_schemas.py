from src.models.db_schemas import TABLE_SCHEMAS, get_table_schema


def test_attila_table_schemas_exist():
    # Attila versions: land_units v30, junctions v0, projectiles v5, explosions v2, armour v1, shield v3, weapons v7
    assert get_table_schema("land_units", 30) is not None
    assert len(get_table_schema("land_units", 30)) == 52

    assert get_table_schema("subculture_religion_voiceover_junctions", 0) is not None
    assert len(get_table_schema("subculture_religion_voiceover_junctions", 0)) == 3

    assert get_table_schema("audio_projectiles", 5) is not None
    assert len(get_table_schema("audio_projectiles", 5)) == 20

    assert get_table_schema("audio_explosions", 2) is not None
    assert len(get_table_schema("audio_explosions", 2)) == 4

    assert get_table_schema("unit_armour_types", 1) is not None
    assert len(get_table_schema("unit_armour_types", 1)) == 5

    assert get_table_schema("unit_shield_types", 3) is not None
    assert len(get_table_schema("unit_shield_types", 3)) == 5

    assert get_table_schema("melee_weapons", 7) is not None
    assert len(get_table_schema("melee_weapons", 7)) == 14


def test_rome2_table_schemas_exist():
    # Rome II versions: land_units v27, melee_weapons v6, audio_projectiles v1
    assert get_table_schema("land_units", 27) is not None
    assert len(get_table_schema("land_units", 27)) == 51

    assert get_table_schema("melee_weapons", 6) is not None
    assert len(get_table_schema("melee_weapons", 6)) == 13

    assert get_table_schema("audio_projectiles", 1) is not None
    assert len(get_table_schema("audio_projectiles", 1)) == 9


def test_schema_field_types_valid():
    valid_types = {
        "StringU8",
        "OptionalStringU8",
        "StringU16",
        "OptionalStringU16",
        "I32",
        "F32",
        "Boolean",
        "I64",
        "I16",
    }
    for (tname, ver), fields in TABLE_SCHEMAS.items():
        for fname, ftype in fields:
            assert ftype in valid_types, f"Invalid type {ftype} for {tname} v{ver}.{fname}"
