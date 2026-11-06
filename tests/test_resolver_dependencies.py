from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.manifest import DependencyPackInfo
from src.workspace.resolver import AssetResolver
from src.workspace.storage import ProjectStorage


def test_project_dependency_directories(tmp_path):
    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)

    assert project.dependencies_dir == project_dir / "dependencies"
    assert (
        project.get_dependency_dir("custom_audio.pack")
        == project_dir / "dependencies" / "custom_audio.pack"
    )


def test_resolver_bank_3_tier_precedence(tmp_path):
    # Setup vanilla cache
    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    (cache_dir / "vanilla_only.bnk").write_bytes(b"CACHE_VANILLA_ONLY")
    (cache_dir / "shared.bnk").write_bytes(b"CACHE_SHARED")
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)

    # Setup project
    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)

    # Add dependencies with differing priorities: dep_high (priority=0, highest), dep_low (priority=10)
    dep_low_dir = project.get_dependency_dir("dep_low.pack") / "audio"
    dep_low_dir.mkdir(parents=True)
    (dep_low_dir / "shared.bnk").write_bytes(b"DEP_LOW_SHARED")
    (dep_low_dir / "dep_only.bnk").write_bytes(b"DEP_LOW_ONLY")
    (dep_low_dir / "dep_priority.bnk").write_bytes(b"DEP_LOW_PRIORITY")

    dep_high_dir = project.get_dependency_dir("dep_high.pack") / "audio"
    dep_high_dir.mkdir(parents=True)
    (dep_high_dir / "shared.bnk").write_bytes(b"DEP_HIGH_SHARED")
    (dep_high_dir / "dep_priority.bnk").write_bytes(b"DEP_HIGH_PRIORITY")

    project.manifest.dependencies = [
        DependencyPackInfo(name="dep_low.pack", source_path="/path/low", priority=10),
        DependencyPackInfo(name="dep_high.pack", source_path="/path/high", priority=0),
    ]

    resolver = AssetResolver(project, cache)

    # 1. Bank present only in vanilla cache -> resolves to cache
    assert resolver.resolve_bank_bytes("vanilla_only.bnk") == b"CACHE_VANILLA_ONLY"

    # 2. Bank present in dependency only -> resolves to dependency
    assert resolver.resolve_bank_bytes("dep_only.bnk") == b"DEP_LOW_ONLY"

    # 3. Bank present in both dependencies -> resolves to higher-priority dependency
    assert resolver.resolve_bank_bytes("dep_priority.bnk") == b"DEP_HIGH_PRIORITY"
    assert resolver.resolve_bank_bytes("shared.bnk") == b"DEP_HIGH_SHARED"

    # 4. Bank modified in project overlay -> overrides dependency and cache
    project.save_bank("shared.bnk", b"PROJECT_OVERLAY_SHARED")
    assert resolver.resolve_bank_bytes("shared.bnk") == b"PROJECT_OVERLAY_SHARED"
    assert resolver.resolve_bank_path("shared.bnk") == project.audio_dir / "shared.bnk"

    # 5. Case-insensitivity across dependencies
    assert resolver.resolve_bank_bytes("DEP_PRIORITY.BNK") == b"DEP_HIGH_PRIORITY"
    assert resolver.resolve_bank_bytes("Dep_Only") == b"DEP_LOW_ONLY"


def test_resolver_wem_3_tier_precedence(tmp_path):
    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    (cache_dir / "100.wem").write_bytes(b"CACHE_WEM_100")
    (cache_dir / "200.wem").write_bytes(b"CACHE_WEM_200")
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)

    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)

    dep1_dir = project.get_dependency_dir("dep1.pack") / "audio"
    dep1_dir.mkdir(parents=True)
    (dep1_dir / "200.wem").write_bytes(b"DEP1_WEM_200")
    (dep1_dir / "300.wem").write_bytes(b"DEP1_WEM_300")

    dep2_dir = project.get_dependency_dir("dep2.pack") / "audio"
    dep2_dir.mkdir(parents=True)
    (dep2_dir / "200.wem").write_bytes(b"DEP2_WEM_200")
    (dep2_dir / "400.wem").write_bytes(b"DEP2_WEM_400")

    project.manifest.dependencies = [
        DependencyPackInfo(name="dep1.pack", source_path="/p1", priority=10),
        DependencyPackInfo(name="dep2.pack", source_path="/p2", priority=0),
    ]

    resolver = AssetResolver(project, cache)

    # 1. Vanilla only
    assert resolver.resolve_wem_bytes(100) == b"CACHE_WEM_100"

    # 2. Dependency only
    assert resolver.resolve_wem_bytes("300") == b"DEP1_WEM_300"
    assert resolver.resolve_wem_bytes("400.wem") == b"DEP2_WEM_400"
    assert resolver.resolve_wem_bytes("400.WEM") == b"DEP2_WEM_400"

    # 3. Higher priority dependency overrides lower priority dependency & cache
    assert resolver.resolve_wem_bytes(200) == b"DEP2_WEM_200"
    assert resolver.resolve_wem_path(200) == dep2_dir / "200.wem"

    # 4. Project overlay overrides everything
    project.stage_wem(200, b"PROJECT_WEM_200")
    assert resolver.resolve_wem_bytes(200) == b"PROJECT_WEM_200"
    assert resolver.resolve_wem_path(200) == project.audio_dir / "200.wem"


def test_resolver_database_3_tier_precedence(tmp_path):
    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    (cache_dir / "event_data.dat").write_bytes(b"CACHE_EVENT_DATA")
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)

    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)

    resolver = AssetResolver(project, cache)

    # 1. Vanilla only
    assert resolver.resolve_database_bytes() == b"CACHE_EVENT_DATA"
    assert resolver.resolve_database_path() == cache_dir / "event_data.dat"

    # 2. Add dependency with event_data.dat
    dep_dir = project.get_dependency_dir("dep.pack") / "audio"
    dep_dir.mkdir(parents=True)
    (dep_dir / "event_data.dat").write_bytes(b"DEP_EVENT_DATA")
    project.manifest.dependencies = [
        DependencyPackInfo(name="dep.pack", source_path="/p", priority=10),
    ]

    assert resolver.resolve_database_bytes() == b"DEP_EVENT_DATA"
    assert resolver.resolve_database_path() == dep_dir / "event_data.dat"

    # 3. Higher priority dependency overrides
    dep_top_dir = project.get_dependency_dir("dep_top.pack") / "audio"
    dep_top_dir.mkdir(parents=True)
    (dep_top_dir / "event_data.dat").write_bytes(b"DEP_TOP_EVENT_DATA")
    project.manifest.dependencies.append(
        DependencyPackInfo(name="dep_top.pack", source_path="/ptop", priority=0)
    )

    assert resolver.resolve_database_bytes() == b"DEP_TOP_EVENT_DATA"
    assert resolver.resolve_database_path() == dep_top_dir / "event_data.dat"

    # 4. Project overlay overrides
    project.save_database(b"PROJECT_EVENT_DATA")
    assert resolver.resolve_database_bytes() == b"PROJECT_EVENT_DATA"
    assert resolver.resolve_database_path() == project.audio_dir / "event_data.dat"


def test_resolver_nonexistent_returns_none(tmp_path):
    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)
    empty_cache = GameCache(GameType.ATTILA, cache_dir=tmp_path / "empty_cache")
    project.cache = empty_cache
    resolver = AssetResolver(project, cache=empty_cache)

    assert resolver.resolve_bank_path("nonexistent.bnk") is None
    assert resolver.resolve_bank_bytes("nonexistent.bnk") is None
    assert resolver.resolve_bank_path("") is None
    assert resolver.resolve_bank_bytes("") is None
    assert resolver.resolve_wem_path(999999) is None
    assert resolver.resolve_wem_bytes(999999) is None
    assert resolver.resolve_wem_path("invalid_wem") is None
    assert resolver.resolve_wem_bytes("invalid_wem.wem") is None
    assert resolver.resolve_database_path() is None
    assert resolver.resolve_database_bytes() is None
