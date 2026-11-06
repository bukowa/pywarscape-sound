from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.resolver import AssetResolver
from src.workspace.storage import ProjectStorage


def test_resolver_layered_fallback_and_overlay(tmp_path):
    # Setup mock cache
    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    (cache_dir / "battle.bnk").write_bytes(b"VANILLA_BATTLE")
    (cache_dir / "ui.bnk").write_bytes(b"VANILLA_UI")
    (cache_dir / "event_data.dat").write_bytes(b"VANILLA_DB")
    (cache_dir / "100.wem").write_bytes(b"VANILLA_WEM_100")
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)

    # Setup project
    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)

    resolver = AssetResolver(project, cache)

    # 1. Unmodified lookup: falls back to cache
    assert resolver.is_bank_modified("battle.bnk") is False
    assert resolver.resolve_bank_bytes("battle.bnk") == b"VANILLA_BATTLE"
    assert resolver.resolve_wem_bytes(100) == b"VANILLA_WEM_100"
    assert resolver.resolve_database_bytes() == b"VANILLA_DB"

    # 2. Modify bank in project: resolver serves overlay
    project.save_bank("battle.bnk", b"MODIFIED_BATTLE")
    assert resolver.is_bank_modified("battle.bnk") is True
    assert resolver.resolve_bank_bytes("battle.bnk") == b"MODIFIED_BATTLE"
    # Unmodified ui.bnk still serves vanilla
    assert resolver.resolve_bank_bytes("ui.bnk") == b"VANILLA_UI"

    # 3. Modify WEM in project
    project.stage_wem(100, b"MODIFIED_WEM_100")
    assert resolver.resolve_wem_bytes(100) == b"MODIFIED_WEM_100"

    # 4. Modify event database
    project.save_database(b"MODIFIED_DB")
    assert resolver.resolve_database_bytes() == b"MODIFIED_DB"

    # 5. Case-insensitivity check
    assert resolver.resolve_bank_bytes("BATTLE.BNK") == b"MODIFIED_BATTLE"
    assert resolver.resolve_bank_bytes("Ui.Bnk") == b"VANILLA_UI"

    # 6. AudioProject property binding
    project.cache = cache
    assert project.resolver.resolve_bank_bytes("battle.bnk") == b"MODIFIED_BATTLE"


def test_resolve_baseline_bank_bytes(tmp_path):
    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    (cache_dir / "battle.bnk").write_bytes(b"VANILLA_BATTLE")
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)

    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)
    project.save_bank("battle.bnk", b"MODIFIED_BATTLE")

    resolver = AssetResolver(project, cache)

    # Active resolution gives overlay
    assert resolver.resolve_bank_bytes("battle.bnk") == b"MODIFIED_BATTLE"
    # Baseline resolution explicitly bypasses overlay to give vanilla
    assert resolver.resolve_baseline_bank_bytes("battle.bnk") == b"VANILLA_BATTLE"
    assert resolver.resolve_baseline_bank_path("battle.bnk") == cache_dir / "battle.bnk"

    # Non-existent bank baseline returns None
    assert resolver.resolve_baseline_bank_bytes("nonexistent.bnk") is None
