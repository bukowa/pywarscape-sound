import pytest

from src.workspace.game import GameType
from src.workspace.storage import ProjectStorage


def test_project_lifecycle_and_staging(tmp_path):
    project_dir = tmp_path / "MyMod"
    project = ProjectStorage.create_project(project_dir, name="MyMod", game=GameType.ATTILA)

    assert project_dir.exists()
    assert (project_dir / "project.json").exists()
    assert (project_dir / "pack_root" / "audio").exists()
    assert (project_dir / "source_audio").exists()

    # Stage source audio
    dummy_wav = tmp_path / "input.wav"
    dummy_wav.write_bytes(b"RIFF_DUMMY_WAV")
    rel_path = project.stage_source_audio(dummy_wav, wem_id=5001)
    assert rel_path == "source_audio/input.wav"
    assert (project_dir / rel_path).read_bytes() == b"RIFF_DUMMY_WAV"
    assert project.manifest.source_audio[5001] == rel_path

    # Stage WEM
    project.stage_wem(5001, b"RIFF_DUMMY_WEM")
    assert (project.audio_dir / "5001.wem").read_bytes() == b"RIFF_DUMMY_WEM"
    assert 5001 in project.manifest.staged_wems

    # Save bank
    project.save_bank("battle.bnk", b"BKHD_DUMMY_BNK")
    assert (project.audio_dir / "battle.bnk").exists()
    assert "battle.bnk" in project.manifest.modified_banks

    # Revert bank
    assert project.revert_bank("battle.bnk") is True
    assert not (project.audio_dir / "battle.bnk").exists()
    assert "battle.bnk" not in project.manifest.modified_banks

    # Safe revert on non-modified bank
    assert project.revert_bank("nonexistent.bnk") is False

    # Save and reload
    ProjectStorage.save_project(project)
    reloaded = ProjectStorage.open_project(project_dir)
    assert reloaded.manifest.name == "MyMod"
    assert 5001 in reloaded.manifest.staged_wems
    assert reloaded.manifest.source_audio[5001] == rel_path


def test_open_nonexistent_project_fails(tmp_path):
    with pytest.raises(FileNotFoundError):
        ProjectStorage.open_project(tmp_path / "nonexistent")


def test_project_compile_movie_pack(tmp_path, monkeypatch):
    from src.compiler.pfh4_pack import PT_MOD, read_pfh4_index, read_pfh4_pack_type
    from src.engine.session import WorkspaceSession
    from src.workspace.game_detector import GameDetector

    # Isolate default pack destination to project folder during test
    monkeypatch.setattr(GameDetector, "detect_game_install", lambda _: None)

    project_dir = tmp_path / "CompileMod"
    project = ProjectStorage.create_project(project_dir, name="CompileMod", game=GameType.ATTILA)

    # Stage a bank and a loose WEM
    project.save_bank("battle.bnk", b"BKHD_BATTLE_DATA")
    project.stage_wem(9001, b"RIFF_WEM_9001")

    # 1. Default compile destination (defaults to PT_MOD = 3)
    expected_default = project.resolve_default_pack_path()
    assert expected_default == (project_dir / "CompileMod.pack").resolve()
    default_pack = project.compile_mod_pack()
    assert default_pack.is_file()
    assert default_pack == expected_default
    assert project.manifest.output_pack_path == str(default_pack.resolve())
    assert read_pfh4_pack_type(default_pack) == PT_MOD

    # Read pack index and verify entries
    entries = read_pfh4_index(default_pack)
    assert len(entries) == 2
    paths = {e.path.replace("\\", "/") for e in entries}
    assert "audio/battle.bnk" in paths
    assert "audio/9001.wem" in paths

    # 2. Custom compile destination via WorkspaceSession
    custom_pack = tmp_path / "custom_output" / "my_custom_mod.pack"
    session = WorkspaceSession(project=project)
    built_path = session.compile_movie_pack(custom_pack)
    assert built_path == custom_pack.resolve()
    assert custom_pack.is_file()
    assert project.manifest.output_pack_path == str(custom_pack.resolve())

    custom_entries = read_pfh4_index(custom_pack)
    assert len(custom_entries) == 2
    custom_paths = {e.path.replace("\\", "/") for e in custom_entries}
    assert "audio/battle.bnk" in custom_paths
    assert "audio/9001.wem" in custom_paths
