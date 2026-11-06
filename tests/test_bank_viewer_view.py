"""Offscreen headless UI tests for BankViewerView."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QHeaderView

from src.bnk.bank import BkhdChunk, HircChunk, SoundBank
from src.bnk.models import CAkAction, CAkEvent, CAkSound
from src.ui.features.bank_viewer.overlays import TreeOverlay
from src.ui.features.bank_viewer.state import BankListItem, BankStatus
from src.ui.features.bank_viewer.store import BankViewerStore
from src.ui.features.bank_viewer.view import BankViewerView


def test_initial_view_render(qapp, qtbot):
    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    assert view.table_banks.rowCount() == 0
    assert view.lbl_bank_count.text() == "0 banks"
    assert view.lbl_tree_bank_name.text() == "No Bank Selected"
    assert view.tree_widget.topLevelItemCount() == 0
    assert (
        view.inspector_panel.name_lbl.text() == "Select an object in the hierarchy tree to inspect."
    )


def test_view_renders_banks(qapp, qtbot):
    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    b1 = BankListItem(name="battle.bnk", status=BankStatus.VANILLA, size_bytes=1024, path="a")
    b2 = BankListItem(name="campaign.bnk", status=BankStatus.MODIFIED, size_bytes=2048, path="b")
    store.set_available_banks((b1, b2))

    assert view.table_banks.rowCount() == 2
    assert view.table_banks.item(0, 0).text() == "battle.bnk"
    assert view.table_banks.item(0, 1).text() == "Vanilla"
    assert view.table_banks.item(1, 0).text() == "campaign.bnk"
    assert view.table_banks.item(1, 1).text() == "Modified"


def test_view_renders_tree_and_inspector(qapp, qtbot):
    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    # Load synthetic bank with Event -> Action -> Sound
    ev = CAkEvent(id=10, actions=[20])
    act = CAkAction.create_play(id=20, target_id=30)
    snd = CAkSound(id=30, source_id=12345, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=999, version=112),
        hirc=HircChunk(objects=[ev, act, snd]),
    )
    store.load_soundbank_instance("test_bank.bnk", bank)

    assert view.lbl_tree_bank_name.text() == "test_bank.bnk"
    assert view.tree_widget.topLevelItemCount() == 3  # Chunks, Hierarchy, Categories

    # Select Sound node
    store.select_node("hirc:30")

    # Inspector panel should project Sound properties
    insp = view.inspector_panel
    assert insp.type_badge.text() == "SOUND"
    assert "ID: 30" in insp.id_lbl.text()
    assert insp.prop_table.rowCount() > 0


def test_user_interaction_dispatches_to_store(qapp, qtbot):
    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    # Typing in search bar updates store
    view.edit_bank_search.setText("my_bank")
    assert store.state.bank_search_query == "my_bank"

    # Toggling modified only updates store
    view.chk_modified_only.setChecked(True)
    assert store.state.filter_modified_only is True


def test_tree_lazy_expansion(qapp, qtbot):
    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    ev = CAkEvent(id=10, actions=[20])
    act = CAkAction.create_play(id=20, target_id=30)
    snd = CAkSound(id=30, source_id=12345, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=999, version=112),
        hirc=HircChunk(objects=[ev, act, snd]),
    )
    store.load_soundbank_instance("test_lazy.bnk", bank)

    # Hierarchy group item
    hier_item = view.tree_widget.topLevelItem(1)
    assert hier_item.text(0) == "Hierarchy Tree"
    assert hier_item.childCount() == 1

    ev_item = hier_item.child(0)
    assert "Event" in ev_item.text(2)
    # Event has children, but is unexpanded, so it has 1 lazy placeholder
    assert ev_item.childCount() == 1
    assert ev_item.child(0).text(0) == "Loading..."

    # Expanding the item triggers on-demand lazy child loading
    ev_item.setExpanded(True)
    view._on_tree_item_expanded(ev_item)

    # Placeholder replaced by Action item
    assert ev_item.childCount() == 1
    assert "Action" in ev_item.child(0).text(2)


def test_tree_search_filtering(qapp, qtbot):
    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    ev = CAkEvent(id=10, actions=[20])
    act = CAkAction.create_play(id=20, target_id=30)
    snd = CAkSound(id=30, source_id=12345, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=999, version=112),
        hirc=HircChunk(objects=[ev, act, snd]),
    )
    store.load_soundbank_instance("test_filter.bnk", bank)

    # 1. Filter for the sound node by its unique WEM ID (child search preserves parents)
    view.edit_tree_search.setText("12345")
    sound_item = view._items_by_key.get("hirc:30")
    assert sound_item is not None
    assert sound_item.text(1) == "30"
    assert "Sound" in sound_item.text(2)
    assert sound_item.font(0).bold() is True

    # Hierarchy parents are preserved and visible
    act_parent = sound_item.parent()
    assert act_parent is not None
    assert act_parent.text(1) == "20"
    assert "Action" in act_parent.text(2)

    ev_grandparent = act_parent.parent()
    assert ev_grandparent is not None
    assert ev_grandparent.text(1) == "10"
    assert "Event" in ev_grandparent.text(2)

    # 2. Filter for the event node by its ID (parent search preserves children)
    view.edit_tree_search.setText("10")
    ev_item = view._items_by_key.get("hirc:10")
    assert ev_item is not None
    assert ev_item.text(1) == "10"
    assert ev_item.font(0).bold() is True

    # Children of matched event are preserved and visible
    assert ev_item.childCount() == 1
    act_child = ev_item.child(0)
    assert act_child.text(1) == "20"
    assert act_child.childCount() == 1
    snd_child = act_child.child(0)
    assert snd_child.text(1) == "30"

    # 3. Clearing search restores full tree with default groups
    view.edit_tree_search.setText("")
    assert view.tree_widget.topLevelItemCount() == 3


def test_selection_does_not_rebuild_tree(qapp, qtbot):
    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    ev = CAkEvent(id=10, actions=[20])
    act = CAkAction.create_play(id=20, target_id=30)
    snd = CAkSound(id=30, source_id=12345, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=999, version=112),
        hirc=HircChunk(objects=[ev, act, snd]),
    )
    store.load_soundbank_instance("test_selection.bnk", bank)

    top_item_before = view.tree_widget.topLevelItem(0)

    # Selecting nodes updates selection without clearing or recreating tree items
    store.select_node("chunk:BKHD")
    assert view.tree_widget.topLevelItem(0) is top_item_before
    assert view.tree_widget.currentItem() is top_item_before.child(0)

    store.select_node("group:chunks")
    assert view.tree_widget.topLevelItem(0) is top_item_before
    assert view.tree_widget.currentItem() is top_item_before


def test_view_switches_banks_cleanly_without_stale_tree_nodes(qapp, qtbot):
    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    ev = CAkEvent(id=10, actions=[20])
    act = CAkAction.create_play(id=20, target_id=30)
    snd = CAkSound(id=30, source_id=12345, stream_type=2)
    bank_a = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[ev, act, snd]),
    )
    bank_b = SoundBank(
        header=BkhdChunk(bank_id=2, version=112),
    )

    # 1. Load Bank A
    store.load_soundbank_instance("bank_a.bnk", bank_a)
    assert "bank_a.bnk" in view.lbl_tree_bank_name.text()
    assert "hirc:10" in view._items_by_key

    # 2. Switch to Bank B (which has no HIRC objects)
    store.load_soundbank_instance("bank_b.bnk", bank_b)
    assert "bank_b.bnk" in view.lbl_tree_bank_name.text()
    # Stale nodes from Bank A must NOT remain in Bank B's view!
    assert "hirc:10" not in view._items_by_key


def test_tree_widget_columns_are_interactive_and_resizable(qapp, qtbot):
    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)
    thdr = view.tree_widget.header()

    for col in range(4):
        assert thdr.sectionResizeMode(col) == QHeaderView.ResizeMode.Interactive
    assert thdr.stretchLastSection() is True
    assert view.tree_widget.columnWidth(0) >= 200
    assert view.tree_widget.columnWidth(1) >= 80
    assert view.tree_widget.columnWidth(2) >= 100


def test_tree_modified_highlight_and_filter_ui(qapp, qtbot):
    from src.engine.diff import BankDiffResult
    from src.ui.theme import COLOR_STATUS_MODIFIED

    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    assert view.overlay_actions[TreeOverlay.HIGHLIGHT_MODIFIED].isChecked() is True
    assert view.chk_show_modified_only.isChecked() is False

    # Load bank with modified Sound (id=30)
    ev = CAkEvent(id=10, actions=[20])
    act = CAkAction.create_play(id=20, target_id=30)
    snd = CAkSound(id=30, source_id=12345, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[ev, act, snd]),
    )
    diff = BankDiffResult(modified_object_ids=frozenset([30]))
    store.load_soundbank_instance("mod_test.bnk", bank, diff_result=diff)

    # In default view: Chunks, Hierarchy, Categories are present
    assert view.tree_widget.topLevelItemCount() == 3

    # Check that parent group "All Objects by Type" has modified children color
    cat_group_item = view._items_by_key.get("group:categories")
    assert cat_group_item is not None
    assert cat_group_item.foreground(0).color().name().upper() == COLOR_STATUS_MODIFIED.upper()

    # Toggle Show Modified Only -> dispatches to store
    view.chk_show_modified_only.setChecked(True)
    assert store.state.filter_tree_modified_only is True

    # Toggle Highlight Modified -> dispatches to store
    view.overlay_actions[TreeOverlay.HIGHLIGHT_MODIFIED].setChecked(False)
    assert TreeOverlay.HIGHLIGHT_MODIFIED not in store.state.active_overlays


def test_bank_viewer_store_public_helpers_and_encapsulation(qapp, qtbot):
    """Verify that BankViewerStore exposes clean public APIs and view respects encapsulation."""
    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    assert store.project is None
    assert store.sound_db is None
    assert store.resolver is None

    # Load bank
    snd = CAkSound(id=50, source_id=99999, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=42, version=112),
        hirc=HircChunk(objects=[snd]),
    )
    store.load_soundbank_instance("my_bank.bnk", bank)

    loaded = store.get_loaded_bank("my_bank.bnk")
    assert loaded is bank
    assert store.get_loaded_bank("nonexistent.bnk") is None

    # WEM ID extraction
    assert store.extract_sound_wem_id(snd) == 99999

    # Catalog provider helper
    local_cat, prov = store.build_local_and_global_catalog_providers("my_bank.bnk")
    assert isinstance(local_cat, tuple)
    assert callable(prov)

    # View AST analysis: verify ZERO store._* access in BankViewerView
    import ast

    view_path = Path(__file__).parents[1] / "src" / "ui" / "features" / "bank_viewer" / "view.py"
    tree = ast.parse(view_path.read_text(encoding="utf-8"), filename=str(view_path))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr.startswith("_")
            and not (node.attr.startswith("__") and node.attr.endswith("__"))
        ):
            val = node.value
            is_store_ref = False
            if (isinstance(val, ast.Name) and "store" in val.id.lower()) or (
                isinstance(val, ast.Attribute) and "store" in val.attr.lower()
            ):
                is_store_ref = True
            assert not is_store_ref, (
                f"View encapsulation violation at line {node.lineno}: private store access '{node.attr}'"
            )


def test_export_audio_buttons_and_signals(qapp, qtbot, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    # Mock file dialog so it doesn't block on user interaction
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: ("", ""))

    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    sound_signals = []
    view.inspector_panel.export_sound_requested.connect(lambda sid: sound_signals.append(sid))

    # Sound inspector export button
    view.inspector_panel.sound_view._current_sound_id = 456
    view.inspector_panel.sound_view.btn_export.setEnabled(True)
    view.inspector_panel.sound_view.btn_export.click()
    assert sound_signals == [456]

    media_signals = []
    view.inspector_panel.export_media_requested.connect(lambda wid: media_signals.append(wid))

    # Media inspector export button
    view.inspector_panel.media_view._current_wem_id = 789
    view.inspector_panel.media_view.btn_export.setEnabled(True)
    view.inspector_panel.media_view.btn_export.click()
    assert media_signals == [789]


def test_show_game_metadata_toggle_swaps_labels(qapp, qtbot):
    from unittest.mock import MagicMock

    from src.bnk.chunks import BkhdChunk

    store = BankViewerStore()
    mock_db = MagicMock()
    mock_db.resolve_hash.return_value = "Play_unit_charge_roman"
    store.session.sound_db = mock_db

    ev = CAkEvent(id=1001, actions=())
    snd = CAkSound(id=4001, source_id=50001, stream_type=2)
    hirc = HircChunk(objects=[ev, snd])
    bkhd = BkhdChunk(bank_id=999, version=112, language_id=0)
    bank = SoundBank(header=bkhd, hirc=hirc)

    store.load_soundbank_instance("battle.bnk", bank)
    view = BankViewerView(store)
    qtbot.addWidget(view)

    assert view.overlay_actions[TreeOverlay.GAME_NAMES].isChecked() is True

    # With game metadata enabled, Event 1001 displays friendly label
    item_ev = view._items_by_key.get("hirc:1001")
    assert item_ev is not None
    assert item_ev.text(0) == "Play_unit_charge_roman"

    # Toggle action to turn OFF game metadata
    view.overlay_actions[TreeOverlay.GAME_NAMES].setChecked(False)
    assert TreeOverlay.GAME_NAMES not in store.state.active_overlays
    item_ev_raw = view._items_by_key.get("hirc:1001")
    assert item_ev_raw is not None
    assert item_ev_raw.text(0) != "Play_unit_charge_roman"
    assert "1001" in item_ev_raw.text(0) or item_ev_raw.text(1) == "1001"

    # Toggle action back ON
    view.overlay_actions[TreeOverlay.GAME_NAMES].setChecked(True)
    assert TreeOverlay.GAME_NAMES in store.state.active_overlays
    item_ev_restored = view._items_by_key.get("hirc:1001")
    assert item_ev_restored.text(0) == "Play_unit_charge_roman"

    # Test search filter matches friendly name
    store.set_tree_search_query("roman")
    item_searched = view._items_by_key.get("hirc:1001")
    assert item_searched is not None
    assert item_searched.text(0) == "Play_unit_charge_roman"


def test_duplicate_node_selection_preserves_current_item(qapp, qtbot):
    from src.bnk.chunks import BkhdChunk
    from src.bnk.models import CAkSound, CAkSwitchCntr

    s1 = CAkSound(id=1, source_id=101, stream_type=2)
    sw_order = CAkSwitchCntr(id=486554051, children=[1])
    sw_actor = CAkSwitchCntr(id=134857562, children=[486554051])
    sw_culture = CAkSwitchCntr(id=678417983, children=[134857562])

    bkhd = BkhdChunk(bank_id=999, version=112, language_id=0)
    bank = SoundBank(header=bkhd, hirc=HircChunk(objects=[sw_order, sw_actor, sw_culture, s1]))

    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)
    store.load_soundbank_instance("test.bnk", bank)

    from PySide6.QtCore import Qt

    ROLE = Qt.ItemDataRole.UserRole + 1
    cats_item = view.tree_widget.topLevelItem(2)
    sw_cntrs_item = cats_item.child(0)
    view.tree_widget.expandItem(sw_cntrs_item)

    # sw_cntrs_item has children: sw_order (child 0), sw_actor (child 1), sw_culture (child 2)
    vo_order_top = sw_cntrs_item.child(0)
    sw_actor_item = sw_cntrs_item.child(1)

    # Expand sw_actor so it creates its child instance of sw_order
    view.tree_widget.expandItem(sw_actor_item)
    vo_order_bottom = sw_actor_item.child(0)

    assert vo_order_top.data(0, ROLE) == "hirc:486554051"
    assert vo_order_bottom.data(0, ROLE) == "hirc:486554051"
    assert vo_order_top != vo_order_bottom

    # Now click vo_order_top
    view.tree_widget.setCurrentItem(vo_order_top)
    vo_order_top.setSelected(True)
    qapp.processEvents()

    # Current item must remain vo_order_top and NOT be hijacked to vo_order_bottom
    assert view.tree_widget.currentItem() == vo_order_top
    assert view.tree_widget.currentItem().parent() == sw_cntrs_item
