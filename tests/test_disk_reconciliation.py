from pathlib import Path

import pytest

from src.workspace.game import GameType
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject
from src.workspace.storage import ProjectStorage


def test_reconcile_manifest_detects_new_physical_files(tmp_path: Path):
    proj_dir = tmp_path / "ReconcileMod"
    project = ProjectStorage.create_project(proj_dir, name="ReconcileMod", game=GameType.ATTILA)

    assert project.manifest.modified_banks == []
    assert project.manifest.staged_wems == []
    assert project.manifest.has_custom_event_db is False

    # Simulate dropping files physically into pack_root/audio/
    project.audio_dir.mkdir(parents=True, exist_ok=True)
    (project.audio_dir / "battle_music.bnk").write_bytes(b"BANK_BYTES")
    (project.audio_dir / "12345678.wem").write_bytes(b"WEM_BYTES")
    (project.audio_dir / "event_data.dat").write_bytes(b"EVENT_DB_BYTES")
    # Ignored files (temporary or non-audio)
    (project.audio_dir / "temp_file.tmp").write_bytes(b"TMP")
    (project.audio_dir / "notes.txt").write_bytes(b"NOTES")

    modified = project.reconcile_manifest_with_disk()
    assert modified is True

    assert "battle_music.bnk" in project.manifest.modified_banks
    assert 12345678 in project.manifest.staged_wems
    assert project.manifest.has_custom_event_db is True

    # Reopening project preserves reconciled manifest
    reloaded = ProjectStorage.open_project(proj_dir)
    assert "battle_music.bnk" in reloaded.manifest.modified_banks
    assert 12345678 in reloaded.manifest.staged_wems
    assert reloaded.manifest.has_custom_event_db is True


def test_reconcile_manifest_prunes_deleted_physical_files(tmp_path: Path):
    proj_dir = tmp_path / "PruneMod"
    project = ProjectStorage.create_project(proj_dir, name="PruneMod", game=GameType.ATTILA)

    project.save_bank("custom_bank.bnk", b"BANK_DATA")
    project.stage_wem(999000, b"WEM_DATA")
    project.save_database(b"DB_DATA")

    assert "custom_bank.bnk" in project.manifest.modified_banks
    assert 999000 in project.manifest.staged_wems
    assert project.manifest.has_custom_event_db is True

    # Delete files physically from disk
    (project.audio_dir / "custom_bank.bnk").unlink()
    (project.audio_dir / "999000.wem").unlink()
    (project.audio_dir / "event_data.dat").unlink()

    modified = project.reconcile_manifest_with_disk()
    assert modified is True

    assert project.manifest.modified_banks == []
    assert project.manifest.staged_wems == []
    assert project.manifest.has_custom_event_db is False


def test_reconcile_manifest_called_on_compile(tmp_path: Path):
    proj_dir = tmp_path / "CompileReconcileMod"
    project = ProjectStorage.create_project(proj_dir, name="CompileMod", game=GameType.ATTILA)

    # Physically drop a bank
    project.audio_dir.mkdir(parents=True, exist_ok=True)
    (project.audio_dir / "untracked_sound.bnk").write_bytes(b"UNTRACKED_BNK")

    out_pack = project.compile_mod_pack(output_path=tmp_path / "CompileMod.pack")
    assert out_pack.is_file()

    # Reconcile must have occurred during compile_mod_pack
    assert "untracked_sound.bnk" in project.manifest.modified_banks


def test_reconcile_manifest_prunes_orphaned_source_audio(tmp_path: Path):
    proj_dir = tmp_path / "PruneSrcMod"
    project = ProjectStorage.create_project(proj_dir, name="PruneSrcMod", game=GameType.ATTILA)

    project.stage_wem(888000, b"WEM_BYTES")
    raw_wav = tmp_path / "raw.wav"
    raw_wav.write_bytes(b"RIFF_AUDIO")
    project.stage_source_audio(raw_wav, 888000)

    assert 888000 in project.manifest.source_audio
    assert (project.source_audio_dir / "raw.wav").exists()

    # Physically delete the staged WEM
    (project.audio_dir / "888000.wem").unlink()

    assert project.reconcile_manifest_with_disk() is True
    assert 888000 not in project.manifest.staged_wems
    assert 888000 not in project.manifest.source_audio
    assert not (project.source_audio_dir / "raw.wav").exists()
