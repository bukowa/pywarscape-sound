"""Dual-verification suite for native Total War binary DB tables against TSV assets.

Enforces:
1. Zero byte offset drift across 100% of binary tables in .cache/attila/db/
2. Bit/entity-exact equality between AudioMetadataCatalog loaded from raw binary tables
   and loaded from TSVs.
"""

from pathlib import Path

import pytest

from src.models.binary_table import decode_binary_table
from src.models.catalog import AudioMetadataCatalog
from tests.support.factories import skip_or_fail_missing_asset

CACHE_DB_DIR = Path(".cache/attila/db")

AUDIO_TABLES = [
    "land_units",
    "subculture_religion_voiceover_junctions",
    "audio_projectiles",
    "audio_explosions",
    "unit_armour_types",
    "unit_shield_types",
    "melee_weapons",
]


@pytest.fixture(scope="module")
def cache_catalog():
    if not CACHE_DB_DIR.is_dir():
        skip_or_fail_missing_asset(f"Cache DB directory not found at {CACHE_DB_DIR}")
    return AudioMetadataCatalog.from_directory(CACHE_DB_DIR)


@pytest.fixture(scope="module")
def tsv_catalog(tmp_path_factory):
    if not CACHE_DB_DIR.is_dir():
        skip_or_fail_missing_asset(f"Cache DB directory not found at {CACHE_DB_DIR}")

    tsv_dir = tmp_path_factory.mktemp("parity_tsvs")
    for tbl in AUDIO_TABLES:
        bin_p = CACHE_DB_DIR / f"{tbl}_tables" / tbl
        if not bin_p.is_file():
            continue
        _, rows, _ = decode_binary_table(bin_p.read_bytes(), tbl)
        if not rows:
            continue
        headers = list(rows[0].keys())
        out_f = tsv_dir / f"{tbl}.tsv"
        lines = ["\t".join(headers)]
        for r in rows:
            lines.append("\t".join("" if r[h] is None else str(r[h]) for h in headers))
        out_f.write_text("\n".join(lines), encoding="utf-8")

    return AudioMetadataCatalog.from_directory(tsv_dir)


@pytest.mark.assets
@pytest.mark.parametrize("table_name", AUDIO_TABLES)
def test_binary_table_zero_drift(table_name: str):
    if not CACHE_DB_DIR.is_dir():
        skip_or_fail_missing_asset(f"Cache DB directory not found at {CACHE_DB_DIR}")

    file_path = CACHE_DB_DIR / f"{table_name}_tables" / table_name
    assert file_path.is_file(), f"Binary table missing: {file_path}"

    data = file_path.read_bytes()
    version, rows, end_offset = decode_binary_table(data, table_name)

    assert len(rows) > 0, f"Table {table_name} decoded 0 rows"
    assert end_offset == len(data), (
        f"Byte offset drift in {table_name} (v{version}): "
        f"decoded {end_offset} of {len(data)} bytes ({len(data) - end_offset} unconsumed)"
    )


@pytest.mark.assets
def test_catalog_binary_and_tsv_entity_parity(cache_catalog, tsv_catalog):
    # 1. Land units entity parity
    assert len(cache_catalog.units) == len(tsv_catalog.units)
    assert cache_catalog.units == tsv_catalog.units

    # 2. Culture voiceover junctions parity
    assert len(cache_catalog.cultures) == len(tsv_catalog.cultures)
    assert cache_catalog.cultures == tsv_catalog.cultures

    # 3. Audio projectiles parity
    assert len(cache_catalog.projectiles) == len(tsv_catalog.projectiles)
    assert cache_catalog.projectiles == tsv_catalog.projectiles

    # 4. Audio explosions parity
    assert len(cache_catalog.explosions) == len(tsv_catalog.explosions)
    assert cache_catalog.explosions == tsv_catalog.explosions

    # 5. Collision material SFX parity
    assert len(cache_catalog.materials) == len(tsv_catalog.materials)
    assert cache_catalog.materials == tsv_catalog.materials


def test_synthetic_binary_table_zero_drift():
    """Hermetic verification: zero byte offset drift on synthetic binary DB tables for all 7 tables."""
    from tests.support.factories import encode_binary_db_table

    for table_name in AUDIO_TABLES:
        sample_rows = [
            {"key": f"{table_name}_entry_1"},
            {"key": f"{table_name}_entry_2"},
        ]
        if table_name == "land_units":
            sample_rows = [
                {
                    "key": "unit_1",
                    "category": "infantry",
                    "selection_vo": "vo_1",
                    "armour": "leather",
                    "shield": "round",
                    "primary_melee_weapon": "sword",
                },
                {
                    "key": "unit_2",
                    "category": "cavalry",
                    "selection_vo": "vo_2",
                    "armour": "chain",
                    "shield": "kite",
                    "primary_melee_weapon": "lance",
                },
            ]
        elif table_name == "subculture_religion_voiceover_junctions":
            sample_rows = [
                {"religion": "christian", "subculture": "roman", "voiceover_culture": "latin"},
                {"religion": "pagan", "subculture": "germanic", "voiceover_culture": "barbarian"},
            ]
        elif table_name == "audio_projectiles":
            sample_rows = [
                {
                    "key": "arrow",
                    "fire_event": "event_arrow_fire",
                    "impact_event": "event_arrow_hit",
                },
            ]
        elif table_name == "audio_explosions":
            sample_rows = [
                {"key": "catapult_exp", "event": "event_exp", "max_attenuation": 100.0},
            ]
        elif table_name == "unit_armour_types":
            sample_rows = [
                {"key": "leather", "armour_value": 10, "audio_material": "mat_leather"},
            ]
        elif table_name == "unit_shield_types":
            sample_rows = [
                {"key": "round", "shield_defence_value": 5, "audio_material": "mat_wood"},
            ]
        elif table_name == "melee_weapons":
            sample_rows = [
                {"key": "sword", "audio_material": "mat_metal"},
            ]

        encoded = encode_binary_db_table(table_name, sample_rows)
        version, decoded_rows, end_offset = decode_binary_table(encoded, table_name)
        assert len(decoded_rows) == len(sample_rows)
        assert end_offset == len(encoded), (
            f"Offset drift in synthetic {table_name}: decoded {end_offset} of {len(encoded)}"
        )


def test_synthetic_catalog_binary_and_tsv_parity(tmp_path: Path):
    """Hermetic verification: 100% entity equality between binary DB and TSV loaded catalog."""
    from tests.support.factories import encode_binary_db_table

    bin_dir = tmp_path / "bin_db"
    tsv_dir = tmp_path / "tsv_db"

    table_data = {
        "unit_armour_types": [
            {"key": "armour_1", "armour_value": 10, "audio_material": "mat_leather"},
            {"key": "armour_2", "armour_value": 20, "audio_material": "mat_iron"},
        ],
        "unit_shield_types": [
            {"key": "shield_1", "shield_defence_value": 5, "audio_material": "mat_wood"},
        ],
        "melee_weapons": [
            {"key": "weapon_1", "audio_material": "mat_blade"},
        ],
        "land_units": [
            {
                "key": "unit_1",
                "category": "infantry",
                "selection_vo": "vo_order_1",
                "armour": "armour_1",
                "shield": "shield_1",
                "primary_melee_weapon": "weapon_1",
            },
        ],
        "subculture_religion_voiceover_junctions": [
            {"religion": "rel_1", "subculture": "sub_1", "voiceover_culture": "cult_1"},
        ],
        "audio_projectiles": [
            {"key": "proj_1", "fire_event": "event_fire_1", "impact_event": "event_hit_1"},
        ],
        "audio_explosions": [
            {"key": "expl_1", "event": "event_expl_1", "max_attenuation": 100.0},
        ],
    }

    for tbl, rows in table_data.items():
        tbl_file = bin_dir / f"{tbl}_tables" / tbl
        tbl_file.parent.mkdir(parents=True, exist_ok=True)
        bin_bytes = encode_binary_db_table(tbl, rows)
        tbl_file.write_bytes(bin_bytes)

        _, dec_rows, _ = decode_binary_table(bin_bytes, tbl)
        headers = list(dec_rows[0].keys())
        out_tsv = tsv_dir / f"{tbl}.tsv"
        out_tsv.parent.mkdir(parents=True, exist_ok=True)
        tsv_lines = ["\t".join(headers)]
        for r in dec_rows:
            tsv_lines.append("\t".join("" if r[h] is None else str(r[h]) for h in headers))
        out_tsv.write_text("\n".join(tsv_lines), encoding="utf-8")

    bin_catalog = AudioMetadataCatalog.from_directory(bin_dir)
    tsv_catalog = AudioMetadataCatalog.from_directory(tsv_dir)

    assert len(bin_catalog.units) == len(tsv_catalog.units)
    assert bin_catalog.units == tsv_catalog.units

    assert len(bin_catalog.cultures) == len(tsv_catalog.cultures)
    assert bin_catalog.cultures == tsv_catalog.cultures

    assert len(bin_catalog.projectiles) == len(tsv_catalog.projectiles)
    assert bin_catalog.projectiles == tsv_catalog.projectiles

    assert len(bin_catalog.explosions) == len(tsv_catalog.explosions)
    assert bin_catalog.explosions == tsv_catalog.explosions

    assert len(bin_catalog.materials) == len(tsv_catalog.materials)
    assert bin_catalog.materials == tsv_catalog.materials
