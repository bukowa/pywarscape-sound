import struct
from pathlib import Path

from src.models.catalog import AudioMetadataCatalog


def test_catalog_from_directory_with_binary_files(tmp_path: Path):
    # Setup directory containing raw binary files without .tsv extension
    db_dir = tmp_path / "db"
    (db_dir / "audio_explosions_tables").mkdir(parents=True)

    guid_bytes = "test-guid".encode("utf-16-le")
    header = (
        b"\xfd\xfe\xfc\xff"
        + struct.pack("<H", len(guid_bytes) // 2)
        + guid_bytes
        + b"\xfc\xfd\xfe\xff"
        + struct.pack("<IBI", 2, 1, 1)
    )
    ev_bytes = b"projectile_explosion_pot"
    key_bytes = b"pot"
    row_data = (
        b"\x01"
        + struct.pack("<H", len(ev_bytes))
        + ev_bytes
        + struct.pack("<H", len(key_bytes))
        + key_bytes
        + struct.pack("<f", 120.0)
        + b"\x00"
    )
    (db_dir / "audio_explosions_tables" / "audio_explosions").write_bytes(header + row_data)

    cat = AudioMetadataCatalog.from_directory(tmp_path)
    assert len(cat.explosions) == 1
    assert cat.get_explosion("pot") is not None
    assert cat.get_explosion("pot").event == "projectile_explosion_pot"


def test_catalog_from_synthetic_pack(tmp_path: Path):
    # Construct a valid PFH4 pack file containing db/audio_explosions_tables/audio_explosions
    pack_path = tmp_path / "test_mod.pack"
    guid_bytes = "test-guid".encode("utf-16-le")
    header = (
        b"\xfd\xfe\xfc\xff"
        + struct.pack("<H", len(guid_bytes) // 2)
        + guid_bytes
        + b"\xfc\xfd\xfe\xff"
        + struct.pack("<IBI", 2, 1, 1)
    )
    ev_bytes = b"projectile_explosion_bomb"
    key_bytes = b"bomb"
    table_payload = (
        header
        + b"\x01"
        + struct.pack("<H", len(ev_bytes))
        + ev_bytes
        + struct.pack("<H", len(key_bytes))
        + key_bytes
        + struct.pack("<f", 200.0)
        + b"\x00"
    )

    # PFH4 header: 'PFH4' (4) + pack_type (4) + dep_count (4) + dep_offset (4) + file_count (4) + index_size (4)
    # Followed by index: file_size (4) + null-terminated path (str)
    file_rel_path = "db/audio_explosions_tables/audio_explosions\x00".encode("ascii")
    index_bytes = struct.pack("<I", len(table_payload)) + file_rel_path
    pack_header = b"PFH4" + struct.pack("<IIIIII", 4, 0, 0, 1, len(index_bytes), 0)
    pack_data = pack_header + index_bytes + table_payload
    pack_path.write_bytes(pack_data)

    cat = AudioMetadataCatalog.from_pack(pack_path)
    assert len(cat.explosions) == 1
    assert cat.get_explosion("bomb") is not None
    assert cat.get_explosion("bomb").event == "projectile_explosion_bomb"
