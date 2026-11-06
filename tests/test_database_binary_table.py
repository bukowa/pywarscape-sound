import struct
from pathlib import Path

import pytest

from src.models.binary_table import (
    decode_binary_table,
    decode_binary_table_file,
    is_binary_db_table,
)


def test_is_binary_db_table():
    assert is_binary_db_table(b"\xfd\xfe\xfc\xff\x05\x00...") is True
    assert is_binary_db_table(b"key\tcategory\t...") is False
    assert is_binary_db_table(b"") is False


def test_decode_synthetic_binary_table():
    # Build synthetic table: magic (4) + GUID len (2) + GUID (UTF16) + ext marker (4) + ver (4) + extra (1) + rows (4)
    guid_bytes = "test-guid".encode("utf-16-le")
    header = (
        b"\xfd\xfe\xfc\xff"
        + struct.pack("<H", len(guid_bytes) // 2)
        + guid_bytes
        + b"\xfc\xfd\xfe\xff"
        + struct.pack("<IBI", 2, 1, 1)  # version 2, extra 1, 1 row
    )
    # Row for audio_explosions v2: event (OptionalStringU8), key (StringU8), max_attenuation (F32), group_event (OptionalStringU8)
    ev_bytes = b"explosion_fire"
    key_bytes = b"fireball"
    row_data = (
        b"\x01"
        + struct.pack("<H", len(ev_bytes))
        + ev_bytes
        + struct.pack("<H", len(key_bytes))
        + key_bytes
        + struct.pack("<f", 85.0)
        + b"\x00"  # group_event None
    )
    payload = header + row_data
    assert is_binary_db_table(payload) is True

    ver, rows, end_offset = decode_binary_table(payload, "audio_explosions")
    assert ver == 2
    assert len(rows) == 1
    assert rows[0]["key"] == "fireball"
    assert rows[0]["event"] == "explosion_fire"
    assert rows[0]["max_attenuation"] == pytest.approx(85.0)
    assert rows[0]["group_event"] is None
    assert end_offset == len(payload)


def test_decode_binary_table_file(tmp_path: Path):
    guid_bytes = "test-guid".encode("utf-16-le")
    header = (
        b"\xfd\xfe\xfc\xff"
        + struct.pack("<H", len(guid_bytes) // 2)
        + guid_bytes
        + struct.pack("<BI", 1, 1)  # legacy header: extra 1, 1 row (version 0)
    )
    # subculture_religion_voiceover_junctions v0: religion (StringU8), subculture (StringU8), voiceover_culture (StringU8)
    r_bytes = b"rel_catholic"
    s_bytes = b"sub_celtic"
    v_bytes = b"barbarian_christian"
    row = (
        struct.pack("<H", len(r_bytes))
        + r_bytes
        + struct.pack("<H", len(s_bytes))
        + s_bytes
        + struct.pack("<H", len(v_bytes))
        + v_bytes
    )
    p = tmp_path / "subculture_religion_voiceover_junctions"
    p.write_bytes(header + row)

    rows = decode_binary_table_file(p, "subculture_religion_voiceover_junctions")
    assert len(rows) == 1
    assert rows[0]["religion"] == "rel_catholic"
    assert rows[0]["subculture"] == "sub_celtic"
    assert rows[0]["voiceover_culture"] == "barbarian_christian"


def test_encode_binary_db_table_roundtrip_all_schemas():
    from tests.support.factories import encode_binary_db_table

    test_cases = [
        ("land_units_tables", [{"key": "att_spearman", "selection_vo": "heavy_infantry"}]),
        (
            "subculture_religion_voiceover_junctions_tables",
            [{"religion": "rel_catholic", "subculture": "sub_celtic", "voiceover_culture": "barb"}],
        ),
        ("audio_projectiles_tables", [{"key": "fire_arrow", "max_attenuation_fire": 120.0}]),
        ("audio_explosions_tables", [{"key": "bomb_blast", "max_attenuation": 250.0}]),
        ("unit_armour_types_tables", [{"key": "plate", "audio_material": "metal_heavy"}]),
        ("unit_shield_types_tables", [{"key": "scutum", "audio_material": "wood_heavy"}]),
        ("melee_weapons_tables", [{"key": "gladius", "audio_material": "sword_sharp"}]),
    ]

    for table_name, rows in test_cases:
        data = encode_binary_db_table(table_name, rows)
        assert is_binary_db_table(data) is True
        ver, decoded_rows, offset = decode_binary_table(data, table_name)
        assert offset == len(data)
        assert len(decoded_rows) == 1
        for k, v in rows[0].items():
            if isinstance(v, float):
                assert decoded_rows[0][k] == pytest.approx(v)
            else:
                assert decoded_rows[0][k] == v
