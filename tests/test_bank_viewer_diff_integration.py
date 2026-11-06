"""Vertical end-to-end integration test for SoundBank modification highlighting and filtering."""

import pytest

from src.bnk.bank import BkhdChunk, HircChunk, SoundBank
from src.bnk.models import CAkAction, CAkEvent, CAkSound
from src.ui.features.bank_viewer.overlays import TreeOverlay
from src.ui.features.bank_viewer.store import BankViewerStore
from src.ui.features.bank_viewer.view import BankViewerView
from src.ui.theme import COLOR_STATUS_MODIFIED
from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.storage import ProjectStorage


def test_end_to_end_modification_highlight_and_filtering(tmp_path, qapp, qtbot):
    # 1. Vanilla Baseline Bank
    ev = CAkEvent(id=10, actions=[20])
    act = CAkAction.create_play(id=20, target_id=30)
    snd_vanilla = CAkSound(id=30, source_id=1001, stream_type=2)

    vanilla_bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        hirc=HircChunk(objects=[ev, act, snd_vanilla]),
    )
    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    (cache_dir / "global_movies.bnk").write_bytes(vanilla_bank.to_bytes())
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)

    # 2. Project with modified bank (Sound 30 modified to source_id=9999)
    snd_mod = CAkSound(id=30, source_id=9999, stream_type=2)
    modified_bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        hirc=HircChunk(objects=[ev, act, snd_mod]),
    )
    proj_dir = tmp_path / "project"
    project = ProjectStorage.create_project(proj_dir, name="MyAudioMod", game=GameType.ATTILA)
    project.cache = cache
    project.save_bank("global_movies.bnk", modified_bank.to_bytes())

    # 3. Mount UI Feature Slice
    store = BankViewerStore(project=project)
    view = BankViewerView(store)
    qtbot.addWidget(view)

    # Left panel shows modified bank
    assert view.table_banks.rowCount() == 1
    assert view.table_banks.item(0, 0).text() == "global_movies.bnk"
    assert view.table_banks.item(0, 1).text() == "Modified"

    # Select the modified bank
    store.select_bank("global_movies.bnk")

    # Verify options defaults
    assert view.overlay_actions[TreeOverlay.HIGHLIGHT_MODIFIED].isChecked() is True
    assert view.chk_show_modified_only.isChecked() is False

    # Tree root groups
    assert view.tree_widget.topLevelItemCount() == 3

    # group:chunks has no modifications -> normal color
    item_chunks = view._items_by_key["group:chunks"]
    assert item_chunks.foreground(0).color().name().upper() != COLOR_STATUS_MODIFIED.upper()

    # group:hierarchy and group:categories have modifications -> highlighted
    item_hier = view._items_by_key["group:hierarchy"]
    item_cats = view._items_by_key["group:categories"]
    assert item_hier.foreground(0).color().name().upper() == COLOR_STATUS_MODIFIED.upper()
    assert item_cats.foreground(0).color().name().upper() == COLOR_STATUS_MODIFIED.upper()

    # Expand categories group
    view.tree_widget.expandItem(item_cats)
    # Modified Sound 30 is in cat:sounds
    cat_sounds = view._items_by_key.get("cat:sounds")
    assert cat_sounds is not None
    assert cat_sounds.foreground(0).color().name().upper() == COLOR_STATUS_MODIFIED.upper()

    # Expand cat:sounds
    view.tree_widget.expandItem(cat_sounds)
    item_snd = view._items_by_key.get("hirc:30")
    assert item_snd is not None
    assert item_snd.foreground(0).color().name().upper() == COLOR_STATUS_MODIFIED.upper()
    assert "[MOD]" in item_snd.text(3)

    # 4. Filter to "Show Modified Only"
    view.chk_show_modified_only.setChecked(True)
    assert store.state.filter_tree_modified_only is True

    # After filtering:
    # group:chunks should be excluded from top-level items because it has 0 modifications
    top_keys = [
        view.tree_widget.topLevelItem(i).data(0, 257)
        for i in range(view.tree_widget.topLevelItemCount())
    ]
    assert "group:chunks" not in top_keys
    assert "group:hierarchy" in top_keys
    assert "group:categories" in top_keys

    # In categories, only cat:sounds has modified items; cat:events and cat:actions should not be present
    item_cats_filtered = view._items_by_key.get("group:categories")
    cat_keys = [
        item_cats_filtered.child(i).data(0, 257) for i in range(item_cats_filtered.childCount())
    ]
    assert "cat:sounds" in cat_keys
    assert "cat:events" not in cat_keys
    assert "cat:actions" not in cat_keys

    # 5. Toggle Highlight Modified off
    view.overlay_actions[TreeOverlay.HIGHLIGHT_MODIFIED].setChecked(False)
    assert TreeOverlay.HIGHLIGHT_MODIFIED not in store.state.active_overlays
    # Tree re-renders without highlight styling, but preservation of structure holds
    item_cats_unhighlighted = view._items_by_key.get("group:categories")
    assert (
        item_cats_unhighlighted.foreground(0).color().name().upper()
        != COLOR_STATUS_MODIFIED.upper()
    )
