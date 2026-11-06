from pathlib import Path

from src.ui.features.audio_sources.store import AudioSourcesStore
from src.ui.features.audio_transport.store import AudioTransportStore
from src.ui.features.bank_viewer.store import BankViewerStore
from src.ui.shell.coordinator import WorkspaceCoordinator
from src.ui.shell.state import ProjectOpened
from src.ui.shell.store import ShellStore
from src.workspace.cache import GameCache
from src.workspace.dependencies import DependencyManager
from src.workspace.game import GameType
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject
from src.workspace.storage import ProjectStorage

TSV_DEP_UNITS = """key\tselection_vo\tcategory
unit_hot_reload_test\tvo_hot_reload\tinfantry
"""


def test_coordinator_hot_reload_project_dependencies(tmp_path: Path):
    proj_dir = tmp_path / "hot_reload_mod"
    cache_dir = tmp_path / "mock_cache"
    empty_cache = GameCache(GameType.ATTILA, cache_dir=cache_dir / "audio")

    manifest = ProjectManifest(
        name="HotReloadMod",
        game=GameType.ATTILA,
    )
    project = AudioProject(root_dir=proj_dir, manifest=manifest, cache=empty_cache)
    ProjectStorage.save_project(project)

    shell_store = ShellStore()
    transport_store = AudioTransportStore()
    bank_viewer_store = BankViewerStore()
    audio_sources_store = AudioSourcesStore()

    coordinator = WorkspaceCoordinator(
        shell_store=shell_store,
        bank_viewer_store=bank_viewer_store,
        transport_store=transport_store,
        audio_sources_store=audio_sources_store,
        async_preview=False,
    )

    # Open project
    shell_store._dispatch(ProjectOpened(project=project))
    assert coordinator.active_project is project

    # Initial catalog is empty
    initial_catalog = bank_viewer_store.metadata_catalog
    assert initial_catalog is not None
    assert initial_catalog.get_unit("unit_hot_reload_test") is None

    # 1. Add dependency pack using DependencyManager
    dep_mgr = DependencyManager(project)
    dep_dir = project.get_dependency_dir("overhaul.pack")
    (dep_dir / "db" / "land_units_tables").mkdir(parents=True, exist_ok=True)
    (dep_dir / "db" / "land_units_tables" / "custom_units").write_text(
        TSV_DEP_UNITS, encoding="utf-8"
    )

    from src.workspace.manifest import DependencyPackInfo

    project.manifest.dependencies.append(
        DependencyPackInfo(
            name="overhaul.pack",
            source_path=str(tmp_path / "overhaul.pack"),
            priority=0,
            extracted_db_tables=["db/land_units_tables/custom_units"],
        )
    )
    ProjectStorage.save_project(project)

    # Trigger hot-reload on coordinator
    coordinator.reload_project_dependencies()

    # Verify catalog has been updated
    reloaded_catalog = bank_viewer_store.metadata_catalog
    assert reloaded_catalog is not None
    assert reloaded_catalog.get_unit("unit_hot_reload_test") is not None
    assert reloaded_catalog.get_unit("unit_hot_reload_test").selection_vo == "vo_hot_reload"

    # 2. Remove dependency
    dep_mgr.remove_dependency("overhaul.pack")
    assert not dep_dir.is_dir()
    assert len(project.manifest.dependencies) == 0

    # Trigger hot-reload again
    coordinator.reload_project_dependencies()

    # Verify catalog no longer contains the unit
    cleared_catalog = bank_viewer_store.metadata_catalog
    assert cleared_catalog is not None
    assert cleared_catalog.get_unit("unit_hot_reload_test") is None
