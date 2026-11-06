import shutil

from src.bnk.bank import SoundBank
from src.bnk.chunks import BkhdChunk
from src.bnk.database import SoundDatabase, fnv1_32
from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.resolver import AssetResolver
from src.workspace.storage import ProjectStorage


def test_workspace_real_bnk_mutation_and_relocation(tmp_path):
    # Set up synthetic Attila cache
    attila_cache_dir = tmp_path / "cache_attila" / "audio"
    attila_cache_dir.mkdir(parents=True, exist_ok=True)
    synthetic_battle = SoundBank(
        header=BkhdChunk(version=112, bank_id=fnv1_32("battle")),
    )
    (attila_cache_dir / "battle.bnk").write_bytes(synthetic_battle.to_bytes())
    (attila_cache_dir / "event_data.dat").write_bytes(SoundDatabase().to_bytes())
    real_cache = GameCache(GameType.ATTILA, cache_dir=attila_cache_dir)
    vanilla_battle_path = real_cache.get_bank_path("battle.bnk")
    assert vanilla_battle_path is not None

    # Create project in dir A
    dir_a = tmp_path / "Project_A"
    project = ProjectStorage.create_project(dir_a, name="PortabilityTest", game=GameType.ATTILA)

    # Parse vanilla bank using SoundBank AST
    bank = SoundBank.from_bytes(vanilla_battle_path.read_bytes())
    # Save into project
    project.save_bank("battle.bnk", bank.to_bytes())

    # Stage raw source audio and converted WEM
    raw_wav = tmp_path / "horn.wav"
    raw_wav.write_bytes(b"RIFF....WAVEfmt ....data....")
    project.stage_source_audio(raw_wav, wem_id=999001)
    project.stage_wem(999001, b"RIFF_FAKE_WEM_999001")

    # Set custom alias
    project.manifest.custom_names["battle.bnk"] = {12345: "MainTheme_Cue"}
    ProjectStorage.save_project(project)

    # RELOCATE PROJECT: move entire folder from dir_a to dir_b
    dir_b = tmp_path / "Renamed_Moved_Project_B"
    shutil.move(str(dir_a), str(dir_b))

    # Open project from new location without any hardcoded path dependencies
    reloaded_project = ProjectStorage.open_project(dir_b, cache=real_cache)
    resolver = AssetResolver(reloaded_project, real_cache)

    assert resolver.is_bank_modified("battle.bnk") is True
    reloaded_bank_bytes = resolver.resolve_bank_bytes("battle.bnk")
    assert reloaded_bank_bytes == bank.to_bytes()
    assert resolver.resolve_wem_bytes(999001) == b"RIFF_FAKE_WEM_999001"

    # Verify source audio relative path resolves correctly in new location
    source_rel = reloaded_project.manifest.source_audio[999001]
    assert (dir_b / source_rel).exists()
    assert (dir_b / source_rel).read_bytes() == b"RIFF....WAVEfmt ....data...."
    assert reloaded_project.manifest.custom_names["battle.bnk"][12345] == "MainTheme_Cue"


def test_rome2_cache_and_project_resolution(tmp_path):
    rome2_cache_dir = tmp_path / "cache_rome2" / "audio"
    rome2_cache_dir.mkdir(parents=True, exist_ok=True)
    synthetic_rome_bank = SoundBank(
        header=BkhdChunk(version=112, bank_id=fnv1_32("rome_battle")),
    )
    (rome2_cache_dir / "rome_battle.bnk").write_bytes(synthetic_rome_bank.to_bytes())
    (rome2_cache_dir / "event_data.dat").write_bytes(SoundDatabase().to_bytes())
    rome2_cache = GameCache(GameType.ROME_2, cache_dir=rome2_cache_dir)

    project_dir = tmp_path / "Rome2_Project"
    project = ProjectStorage.create_project(project_dir, name="Rome2Mod", game=GameType.ROME_2)
    resolver = AssetResolver(project, rome2_cache)

    # Vanilla lookups
    banks = rome2_cache.list_banks()
    assert len(banks) >= 1
    first_bank = banks[0]
    assert resolver.is_bank_modified(first_bank) is False
    assert resolver.resolve_bank_bytes(first_bank) is not None
