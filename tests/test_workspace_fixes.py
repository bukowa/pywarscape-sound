from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.storage import ProjectStorage


def test_bank_casing_normalization_and_no_duplicates(tmp_path):
    project_dir = tmp_path / "CasingProj"
    project = ProjectStorage.create_project(project_dir, name="CasingTest")

    # Save with different casing
    project.save_bank("Battle.bnk", b"DATA_1")
    project.save_bank("battle.bnk", b"DATA_2")
    project.save_bank("BATTLE", b"DATA_3")

    # Assert exactly 1 entry in modified_banks, normalized to lowercase
    assert project.manifest.modified_banks == ["battle.bnk"]
    assert (project.audio_dir / "battle.bnk").read_bytes() == b"DATA_3"

    # Revert with mixed casing
    assert project.revert_bank("BATTLE.BNK") is True
    assert project.manifest.modified_banks == []
    assert not (project.audio_dir / "battle.bnk").exists()


def test_resolver_consistency_with_manifest_truth(tmp_path):
    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    (cache_dir / "battle.bnk").write_bytes(b"VANILLA_BATTLE")
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)

    project_dir = tmp_path / "ResolverProj"
    project = ProjectStorage.create_project(project_dir, name="ResolverTest", cache=cache)
    resolver = project.resolver

    # If untracked file was dumped in audio_dir without being in modified_banks,
    # resolver should not desynchronize from is_bank_modified.
    (project.audio_dir / "untracked.bnk").write_bytes(b"UNTRACKED")
    # Untracked bank is not modified according to manifest
    assert resolver.is_bank_modified("untracked.bnk") is False


def test_stage_source_audio_idempotent_if_already_in_source_audio(tmp_path):
    project_dir = tmp_path / "SameFileProj"
    project = ProjectStorage.create_project(project_dir, name="SameFile")

    # Create file directly in source_audio
    src_file = project.source_audio_dir / "shout.wav"
    src_file.write_bytes(b"RIFF_SHOUT")

    # Staging it should not crash with SameFileError or PermissionError
    rel = project.stage_source_audio(src_file, wem_id=7001)
    assert rel == "source_audio/shout.wav"
    assert project.manifest.source_audio[7001] == "source_audio/shout.wav"
    assert project.get_source_audio_path(7001) == src_file


def test_resolve_wem_accepts_extension_string(tmp_path):
    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    (cache_dir / "8001.wem").write_bytes(b"WEM_8001")
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)

    project_dir = tmp_path / "WemProj"
    project = ProjectStorage.create_project(project_dir, name="WemTest", cache=cache)
    resolver = project.resolver

    assert resolver.resolve_wem_bytes("8001.wem") == b"WEM_8001"
    assert resolver.resolve_wem_bytes("8001") == b"WEM_8001"
    assert cache.get_wem_path("8001.wem") is not None


def test_revert_wem_removes_file_and_manifest_entry(tmp_path):
    project_dir = tmp_path / "RevertWemProj"
    project = ProjectStorage.create_project(project_dir, name="RevertWem")

    project.stage_wem(9001, b"WEM_9001")
    assert 9001 in project.manifest.staged_wems
    assert (project.audio_dir / "9001.wem").exists()

    assert project.revert_wem(9001) is True
    assert 9001 not in project.manifest.staged_wems
    assert not (project.audio_dir / "9001.wem").exists()

    # Second revert is a safe no-op
    assert project.revert_wem(9001) is False
