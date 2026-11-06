from pathlib import Path

import pytest

from src.compiler.pfh4_pack import write_pfh4_movie_pack
from src.workspace.game import GameType
from src.workspace.importer import PartImporter
from src.workspace.storage import ProjectStorage


def test_part_importer_import_bank_wem_database_and_table(tmp_path: Path):
    proj_dir = tmp_path / "ImportProj"
    project = ProjectStorage.create_project(proj_dir, name="ImportProj", game=GameType.ATTILA)

    # Create dummy pack with bank, wem, event_data.dat, and DB table
    pack_path = tmp_path / "external_asset_pack.pack"
    files = {
        "audio/external_battle.bnk": b"EXTERNAL_BNK_PAYLOAD",
        "audio/654321.wem": b"EXTERNAL_WEM_PAYLOAD",
        "audio/event_data.dat": b"EXTERNAL_EVENT_DB_PAYLOAD",
        "db/battle_entities_tables/data": b"EXTERNAL_DB_TABLE_PAYLOAD",
    }
    write_pfh4_movie_pack(pack_path, files)

    importer = PartImporter(project)

    # 1. Import bank
    bank_dest = importer.import_bank(pack_path, "external_battle.bnk")
    assert bank_dest.is_file()
    assert (project.audio_dir / "external_battle.bnk").exists()
    assert "external_battle.bnk" in project.manifest.modified_banks

    # 2. Import WEM
    wem_dest = importer.import_wem(pack_path, 654321)
    assert wem_dest.is_file()
    assert (project.audio_dir / "654321.wem").exists()
    assert 654321 in project.manifest.staged_wems

    # 3. Import database
    db_dest = importer.import_database(pack_path)
    assert db_dest.is_file()
    assert (project.audio_dir / "event_data.dat").exists()
    assert project.manifest.has_custom_event_db is True

    # 4. Import DB table
    table_dest = importer.import_db_table(pack_path, "db/battle_entities_tables/data")
    assert table_dest.is_file()
    assert (
        project.db_dir / "battle_entities_tables" / "data"
    ).read_bytes() == b"EXTERNAL_DB_TABLE_PAYLOAD"


def test_part_importer_file_not_found_handling(tmp_path: Path):
    proj_dir = tmp_path / "NotFoundProj"
    project = ProjectStorage.create_project(proj_dir, name="NotFoundProj", game=GameType.ATTILA)

    pack_path = tmp_path / "empty_pack.pack"
    write_pfh4_movie_pack(pack_path, {})

    importer = PartImporter(project)

    with pytest.raises(FileNotFoundError, match="SoundBank 'missing.bnk' not found"):
        importer.import_bank(pack_path, "missing.bnk")

    with pytest.raises(FileNotFoundError, match="WEM '999' not found"):
        importer.import_wem(pack_path, 999)

    with pytest.raises(FileNotFoundError, match="event_data.dat not found"):
        importer.import_database(pack_path)

    with pytest.raises(
        FileNotFoundError, match="Database table 'db/missing_tables/data' not found"
    ):
        importer.import_db_table(pack_path, "db/missing_tables/data")
