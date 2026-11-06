"""Headless store unit tests for BankViewerStore."""

import ast
from pathlib import Path

from src.bnk.bank import BkhdChunk, HircChunk, SoundBank
from src.bnk.models import CAkAction, CAkEvent, CAkSound, CAkSwitchCntr
from src.ui.features.bank_viewer.columns import TreeColumn
from src.ui.features.bank_viewer.overlays import TreeOverlay
from src.ui.features.bank_viewer.state import BankListItem, BankStatus
from src.ui.features.bank_viewer.store import BankViewerStore


def test_no_qt_imports():
    """Verify headless state, store, causation, builder, overlays, and columns contain ZERO Qt imports via AST analysis."""
    pkg_dir = Path(__file__).parents[1] / "src" / "ui" / "features" / "bank_viewer"
    for py_file in (
        pkg_dir / "state.py",
        pkg_dir / "store.py",
        pkg_dir / "builder.py",
        pkg_dir / "causation.py",
        pkg_dir / "overlays.py",
        pkg_dir / "columns.py",
    ):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(("PySide", "PyQt")), (
                        f"Qt import in {py_file.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert not node.module.startswith(("PySide", "PyQt")), (
                        f"Qt import in {py_file.name}"
                    )


def test_initial_store_state():
    store = BankViewerStore()
    assert store.state.available_banks == ()
    assert store.state.selected_bank_name is None
    assert store.state.bank_search_query == ""
    assert store.state.filter_modified_only is False
    assert store.state.is_loading is False


def test_filtering_banks():
    store = BankViewerStore()
    b1 = BankListItem(
        name="battle_orders.bnk", status=BankStatus.MODIFIED, size_bytes=1000, path="a"
    )
    b2 = BankListItem(name="campaign_env.bnk", status=BankStatus.VANILLA, size_bytes=2000, path="b")
    store.set_available_banks((b1, b2))

    assert len(store.state.filtered_banks) == 2

    # Filter search
    store.set_bank_search_query("orders")
    assert store.state.filtered_banks == (b1,)

    # Clear search, toggle modified only
    store.set_bank_search_query("")
    store.toggle_filter_modified_only(True)
    assert store.state.filtered_banks == (b1,)


def test_select_node_updates_inspector_details():
    store = BankViewerStore()
    # Create synthetic bank with Event -> Action -> Sound
    ev = CAkEvent(id=1, actions=[2])
    act = CAkAction.create_play(id=2, target_id=3)
    snd = CAkSound(id=3, source_id=99999, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=123, version=112),
        hirc=HircChunk(objects=[ev, act, snd]),
    )

    # Load parsed bank directly
    store.load_soundbank_instance("test.bnk", bank)

    state = store.state
    assert state.selected_bank_name == "test.bnk"
    assert "group:chunks" in state.root_keys
    assert "group:hierarchy" in state.root_keys
    assert "group:categories" in state.root_keys

    # Select Sound node
    store.select_node("hirc:3")
    details = store.state.selected_node_details
    assert details is not None
    assert details.object_id == 3
    assert details.object_type == "Sound"
    # Verify stream type property is extracted
    prop_labels = [p.label for p in details.properties]
    assert "Stream Type" in prop_labels
    assert "Source Media ID" in prop_labels

    # Verify parent and child links
    assert "hirc:2" in details.parent_keys


def test_subscribers_notified_on_state_change():
    store = BankViewerStore()
    notifications = []
    store.subscribe(lambda state: notifications.append(state.bank_search_query))

    store.set_bank_search_query("search1")
    store.set_bank_search_query("search2")

    assert notifications == ["search1", "search2"]


def test_load_soundbank_with_switch_container():
    store = BankViewerStore()
    sw = CAkSwitchCntr(
        id=50,
        group_id=1001,
        default_switch=2002,
        children=[60],
        switch_map={2002: [60]},
    )
    snd = CAkSound(id=60, source_id=777)
    bank = SoundBank(
        header=BkhdChunk(bank_id=555, version=112),
        hirc=HircChunk(objects=[sw, snd]),
    )

    store.load_soundbank_instance("switch_bank.bnk", bank)
    store.select_node("hirc:50")

    details = store.state.selected_node_details
    assert details is not None
    assert details.object_id == 50
    assert details.object_type == "SwitchCntr"

    props = {p.label: p.value for p in details.properties}
    assert props.get("Default Switch") == "2002"
    assert props.get("Group ID") == "1001"


def test_load_bank_file_error_handling(tmp_path):
    store = BankViewerStore()

    # Non-existent file
    store.load_bank_file(tmp_path / "missing.bnk")
    assert "Failed to load" in (store.state.status_message or "")

    # Corrupted binary file
    corrupt = tmp_path / "corrupt.bnk"
    corrupt.write_bytes(b"INVALID_HEADER_BYTES")
    store.load_bank_file(corrupt)
    assert "Failed to load" in (store.state.status_message or "")


def test_reset_clears_viewer_state():
    store = BankViewerStore()
    b = BankListItem(name="a.bnk", status=BankStatus.VANILLA, size_bytes=100, path="a")
    store.set_available_banks((b,))
    assert len(store.state.available_banks) == 1

    store.reset()
    assert len(store.state.available_banks) == 0
    assert store.state.selected_bank_name is None


def test_warm_bank_cache_hit_and_lazy_resolution():
    store = BankViewerStore()
    snd = CAkSound(id=100, source_id=999, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        hirc=HircChunk(objects=[snd]),
    )
    store.load_soundbank_instance("warm_test.bnk", bank)

    # First load cached tree
    assert store.state.selected_bank_name == "warm_test.bnk"
    assert "warm_test.bnk" in store.state.cached_banks

    # Switch away to blank
    store.set_available_banks(())

    # Switch back to warm bank -> zero I/O, loaded from in-memory cache
    store.select_bank("warm_test.bnk")
    assert store.state.is_loading is False
    assert "cached" in (store.state.status_message or "")

    # Lazy inspector details resolution
    assert store.state.selected_node_details is None
    store.select_node("hirc:100")
    details = store.state.selected_node_details
    assert details is not None
    assert details.object_id == 100
    assert details.object_type == "Sound"


def test_store_loads_modified_bank_with_baseline_diff(tmp_path):
    from src.workspace.cache import GameCache
    from src.workspace.game import GameType
    from src.workspace.storage import ProjectStorage

    # Setup vanilla bank
    vanilla_bank = SoundBank(
        header=BkhdChunk(bank_id=500, version=112),
        hirc=HircChunk(objects=[CAkSound(id=100, source_id=111, stream_type=2)]),
    )
    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    (cache_dir / "battle.bnk").write_bytes(vanilla_bank.to_bytes())
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)

    # Setup project with modified bank
    modified_bank = SoundBank(
        header=BkhdChunk(bank_id=500, version=112),
        hirc=HircChunk(objects=[CAkSound(id=100, source_id=999, stream_type=2)]),
    )
    proj_dir = tmp_path / "project"
    project = ProjectStorage.create_project(proj_dir, name="Mod", game=GameType.ATTILA)
    project.cache = cache
    project.save_bank("battle.bnk", modified_bank.to_bytes())

    store = BankViewerStore()
    store.load_project(project)
    store.select_bank("battle.bnk")

    node = store.state.nodes_by_key.get("hirc:100")
    assert node is not None
    assert node.is_modified is True

    # Test toggles
    store.set_tree_modified_filter(True)
    assert store.state.filter_tree_modified_only is True

    store.set_tree_overlay(TreeOverlay.HIGHLIGHT_MODIFIED, False)
    assert TreeOverlay.HIGHLIGHT_MODIFIED not in store.state.active_overlays

    store.set_tree_column_visible(TreeColumn.VARIATION_PCT, True)
    assert TreeColumn.VARIATION_PCT in store.state.visible_columns


def test_store_loads_dependency_bank_and_diffs_against_vanilla(tmp_path):
    from src.workspace.cache import GameCache
    from src.workspace.game import GameType
    from src.workspace.manifest import DependencyPackInfo
    from src.workspace.storage import ProjectStorage

    # Setup vanilla bank in GameCache
    vanilla_bank = SoundBank(
        header=BkhdChunk(bank_id=700, version=112),
        hirc=HircChunk(objects=[CAkSound(id=200, source_id=111, stream_type=2)]),
    )
    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    (cache_dir / "dep_music.bnk").write_bytes(vanilla_bank.to_bytes())
    (cache_dir / "vanilla_only.bnk").write_bytes(vanilla_bank.to_bytes())
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)

    # Setup dependency bank in dependencies/custom_music.pack/audio/dep_music.bnk
    dep_bank = SoundBank(
        header=BkhdChunk(bank_id=700, version=112),
        hirc=HircChunk(objects=[CAkSound(id=200, source_id=999, stream_type=2)]),
    )
    proj_dir = tmp_path / "project"
    project = ProjectStorage.create_project(
        proj_dir, name="DependencyProject", game=GameType.ATTILA
    )
    project.cache = cache

    dep_dir = project.get_dependency_dir("custom_music.pack") / "audio"
    dep_dir.mkdir(parents=True)
    (dep_dir / "dep_music.bnk").write_bytes(dep_bank.to_bytes())
    project.manifest.dependencies.append(
        DependencyPackInfo(name="custom_music.pack", priority=0, sha256="abc")
    )
    ProjectStorage.save_project(project)

    store = BankViewerStore()
    store.load_project(project)

    # Verify discovery and status classification
    bank_map = {b.name.lower(): b for b in store.state.available_banks}
    assert "dep_music.bnk" in bank_map
    assert bank_map["dep_music.bnk"].status == BankStatus.DEPENDENCY
    assert "vanilla_only.bnk" in bank_map
    assert bank_map["vanilla_only.bnk"].status == BankStatus.VANILLA

    # Verify filtering: Show Modified Only keeps DEPENDENCY and MODIFIED, excludes VANILLA
    store.toggle_filter_modified_only(True)
    filtered_names = [b.name.lower() for b in store.state.filtered_banks]
    assert "dep_music.bnk" in filtered_names
    assert "vanilla_only.bnk" not in filtered_names

    # Select dependency bank and verify it diffs against vanilla cache
    store.select_bank("dep_music.bnk")
    node = store.state.nodes_by_key.get("hirc:200")
    assert node is not None
    assert node.is_modified is True
