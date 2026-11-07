"""Tests for BankListPanel collapsible parent categories and grouped tree visualization."""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QTreeWidgetItem

from src.ui.features.bank_viewer.bank_list_panel import BankListPanel
from src.ui.features.bank_viewer.state import BankListItem, BankStatus


def _create_sample_banks() -> list[BankListItem]:
    return [
        BankListItem(
            name="global_music.bnk",
            status=BankStatus.VANILLA,
            size_bytes=10_000_000,
            path="path/to/global_music.bnk",
        ),
        BankListItem(
            name="campaign_ui.bnk",
            status=BankStatus.MODIFIED,
            size_bytes=2_000_000,
            path="path/to/campaign_ui.bnk",
        ),
        BankListItem(
            name="battle.bnk",
            status=BankStatus.VANILLA,
            size_bytes=5_000_000,
            path="path/to/battle.bnk",
        ),
        BankListItem(
            name="battle_vo_orders.bnk",
            status=BankStatus.VANILLA,
            size_bytes=1_500_000,
            path="path/to/battle_vo_orders.bnk",
        ),
        BankListItem(
            name="battle_vo_orders_roman.bnk",
            status=BankStatus.MODIFIED,
            size_bytes=4_000_000,
            path="path/to/battle_vo_orders_roman.bnk",
        ),
        BankListItem(
            name="battle_vo_orders_barbarian.bnk",
            status=BankStatus.VANILLA,
            size_bytes=3_000_000,
            path="path/to/battle_vo_orders_barbarian.bnk",
        ),
        BankListItem(
            name="music_data.bnk",
            status=BankStatus.VANILLA,
            size_bytes=50_000_000,
            path="path/to/music_data.bnk",
        ),
        BankListItem(
            name="init.bnk",
            status=BankStatus.VANILLA,
            size_bytes=500_000,
            path="path/to/init.bnk",
        ),
    ]


def test_bank_list_panel_groups_render(qapp, qtbot):
    """Verifies that render_banks organizes soundbanks under parent categories and culture subgroups."""
    panel = BankListPanel()
    qtbot.addWidget(panel)

    banks = _create_sample_banks()
    panel.render_banks(banks, selected_name=None)

    tree = panel.tree_banks
    assert tree.topLevelItemCount() == 6

    # Verify top-level categories in canonical order
    labels = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    assert labels == [
        "Music & Movies",
        "Campaign & UI",
        "Battle SFX & Environment",
        "Battle Voice Orders",
        "Raw Audio Data Banks",
        "System & Empty Stubs",
    ]

    # 1. Music & Movies
    grp_music = tree.topLevelItem(0)
    assert grp_music.childCount() == 1
    assert grp_music.child(0).text(0) == "global_music.bnk"
    assert grp_music.child(0).text(1) == "Vanilla"
    assert grp_music.isExpanded() is True

    # 2. Campaign & UI
    grp_campaign = tree.topLevelItem(1)
    assert grp_campaign.childCount() == 1
    assert grp_campaign.child(0).text(0) == "campaign_ui.bnk"
    assert grp_campaign.child(0).text(1) == "Modified"
    assert grp_campaign.isExpanded() is True

    # 3. Battle SFX & Environment
    grp_battle = tree.topLevelItem(2)
    assert grp_battle.childCount() == 1
    assert grp_battle.child(0).text(0) == "battle.bnk"
    assert grp_battle.isExpanded() is True

    # 4. Battle Voice Orders (direct base bank + culture subgroups)
    grp_vo = tree.topLevelItem(3)
    assert grp_vo.isExpanded() is True
    # Children: direct 'battle_vo_orders.bnk', subgroup 'Barbarian', subgroup 'Roman'
    vo_children_texts = [grp_vo.child(i).text(0) for i in range(grp_vo.childCount())]
    assert "battle_vo_orders.bnk" in vo_children_texts
    assert "Barbarian" in vo_children_texts
    assert "Roman" in vo_children_texts

    # Find the Roman subgroup
    roman_subgroup: QTreeWidgetItem | None = None
    for i in range(grp_vo.childCount()):
        if grp_vo.child(i).text(0) == "Roman":
            roman_subgroup = grp_vo.child(i)
            break
    assert roman_subgroup is not None
    assert roman_subgroup.childCount() == 1
    assert roman_subgroup.child(0).text(0) == "battle_vo_orders_roman.bnk"
    assert roman_subgroup.child(0).text(1) == "Modified"

    # 5. Raw Audio Data Banks (collapsed by default)
    grp_data = tree.topLevelItem(4)
    assert grp_data.childCount() == 1
    assert grp_data.child(0).text(0) == "music_data.bnk"
    assert grp_data.isExpanded() is False

    # 6. System & Empty Stubs (collapsed by default)
    grp_system = tree.topLevelItem(5)
    assert grp_system.childCount() == 1
    assert grp_system.child(0).text(0) == "init.bnk"
    assert grp_system.isExpanded() is False


def test_bank_selection_signal_emission(qapp, qtbot):
    """Verifies that selecting a child bank emits bank_selected, while selecting category headers does not."""
    panel = BankListPanel()
    qtbot.addWidget(panel)

    banks = _create_sample_banks()
    panel.render_banks(banks, selected_name=None)

    emitted_banks: list[str] = []
    panel.bank_selected.connect(emitted_banks.append)

    tree = panel.tree_banks

    # Selecting a parent category does NOT emit bank_selected
    grp_music = tree.topLevelItem(0)
    tree.setCurrentItem(grp_music)
    assert emitted_banks == []

    # Selecting a culture subgroup does NOT emit bank_selected
    grp_vo = tree.topLevelItem(3)
    roman_subgroup = next(
        grp_vo.child(i) for i in range(grp_vo.childCount()) if grp_vo.child(i).text(0) == "Roman"
    )
    tree.setCurrentItem(roman_subgroup)
    assert emitted_banks == []

    # Selecting a child bank leaf item emits bank_selected
    roman_leaf = roman_subgroup.child(0)
    tree.setCurrentItem(roman_leaf)
    assert emitted_banks == ["battle_vo_orders_roman.bnk"]

    # Table selection is synchronized
    assert panel.table_banks.currentRow() >= 0
    current_table_bank = panel.table_banks.item(panel.table_banks.currentRow(), 0).text()
    assert current_table_bank == "battle_vo_orders_roman.bnk"


def test_render_banks_with_initial_selected_name(qapp, qtbot):
    """Verifies that render_banks with selected_name sets current item and expands parents."""
    panel = BankListPanel()
    qtbot.addWidget(panel)

    banks = _create_sample_banks()
    panel.render_banks(banks, selected_name="battle_vo_orders_roman.bnk")

    # Grouped tree selection
    current_tree_item = panel.tree_banks.currentItem()
    assert current_tree_item is not None
    assert current_tree_item.text(0) == "battle_vo_orders_roman.bnk"

    # Parents must be expanded
    roman_subgroup = current_tree_item.parent()
    assert roman_subgroup is not None
    assert roman_subgroup.text(0) == "Roman"
    assert roman_subgroup.isExpanded() is True

    vo_parent = roman_subgroup.parent()
    assert vo_parent is not None
    assert vo_parent.text(0) == "Battle Voice Orders"
    assert vo_parent.isExpanded() is True

    # Flat table selection
    assert panel.table_banks.currentRow() >= 0
    assert (
        panel.table_banks.item(panel.table_banks.currentRow(), 0).text()
        == "battle_vo_orders_roman.bnk"
    )


def test_tree_item_clicked_signal(qapp, qtbot):
    """Verifies that clicking on an item in tree_banks emits bank_selected."""
    panel = BankListPanel()
    qtbot.addWidget(panel)

    banks = _create_sample_banks()
    panel.render_banks(banks, selected_name=None)

    emitted_banks: list[str] = []
    panel.bank_selected.connect(emitted_banks.append)

    grp_music = panel.tree_banks.topLevelItem(0)
    music_leaf = grp_music.child(0)

    panel._on_tree_item_clicked(music_leaf, 0)
    assert emitted_banks == ["global_music.bnk"]


def test_table_selection_synchronizes_to_tree(qapp, qtbot):
    """Verifies that changing selection in table_banks synchronizes to tree_banks."""
    panel = BankListPanel()
    qtbot.addWidget(panel)

    banks = _create_sample_banks()
    panel.render_banks(banks, selected_name=None)

    emitted_banks: list[str] = []
    panel.bank_selected.connect(emitted_banks.append)

    # Find row for battle.bnk in table_banks
    battle_row = -1
    for r in range(panel.table_banks.rowCount()):
        if panel.table_banks.item(r, 0).text() == "battle.bnk":
            battle_row = r
            break
    assert battle_row >= 0

    panel.table_banks.selectRow(battle_row)
    assert "battle.bnk" in emitted_banks

    assert panel.tree_banks.currentItem() is not None
    assert panel.tree_banks.currentItem().text(0) == "battle.bnk"


def test_view_mode_toggle(qapp, qtbot):
    """Verifies switching between grouped tree and flat table views."""
    panel = BankListPanel()
    qtbot.addWidget(panel)

    assert panel.is_tree_view is True
    assert panel.view_stack.currentIndex() == 0
    assert panel.btn_view_mode.text() == "Flat"

    # Toggle to flat view
    panel.btn_view_mode.click()
    assert panel.is_tree_view is False
    assert panel.view_stack.currentIndex() == 1
    assert panel.btn_view_mode.text() == "Tree"

    # Toggle back to tree view
    panel.btn_view_mode.click()
    assert panel.is_tree_view is True
    assert panel.view_stack.currentIndex() == 0
    assert panel.btn_view_mode.text() == "Flat"

    # Explicit programmatic setter
    panel.set_view_mode("flat")
    assert panel.is_tree_view is False
    panel.set_view_mode("tree")
    assert panel.is_tree_view is True


def test_search_auto_expansion(qapp, qtbot):
    """Verifies that searching automatically expands even default-collapsed groups."""
    panel = BankListPanel()
    qtbot.addWidget(panel)

    banks = _create_sample_banks()
    panel.edit_search.setText("music_data")
    # Simulate filtered banks after search
    filtered = [b for b in banks if "music_data" in b.name]
    panel.render_banks(filtered, selected_name=None)

    # Only Raw Audio Data Banks should be rendered, and it should be expanded
    assert panel.tree_banks.topLevelItemCount() == 1
    grp_data = panel.tree_banks.topLevelItem(0)
    assert grp_data.text(0) == "Raw Audio Data Banks"
    assert grp_data.isExpanded() is True


def test_tree_context_menu_revert(qapp, qtbot):
    """Verifies right-click context menu construction and revert enablement for modified vs vanilla banks."""
    panel = BankListPanel()
    qtbot.addWidget(panel)

    banks = _create_sample_banks()
    panel.render_banks(banks, selected_name=None)

    # 1. Right click on top-level category -> None
    grp_music = panel.tree_banks.topLevelItem(0)
    assert panel._create_tree_context_menu(grp_music) is None

    # 2. Right click on culture subgroup -> None
    grp_vo = panel.tree_banks.topLevelItem(3)
    roman_subgroup = next(
        grp_vo.child(i) for i in range(grp_vo.childCount()) if grp_vo.child(i).text(0) == "Roman"
    )
    assert panel._create_tree_context_menu(roman_subgroup) is None

    # 3. Right click on vanilla bank -> action disabled
    music_leaf = grp_music.child(0)
    res_vanilla = panel._create_tree_context_menu(music_leaf)
    assert res_vanilla is not None
    menu_vanilla, act_vanilla = res_vanilla
    assert act_vanilla.text() == "Revert 'global_music.bnk' to Baseline..."
    assert act_vanilla.isEnabled() is False

    # 4. Right click on modified bank -> action enabled
    grp_campaign = panel.tree_banks.topLevelItem(1)
    campaign_leaf = grp_campaign.child(0)
    res_mod = panel._create_tree_context_menu(campaign_leaf)
    assert res_mod is not None
    menu_mod, act_mod = res_mod
    assert act_mod.text() == "Revert 'campaign_ui.bnk' to Baseline..."
    assert act_mod.isEnabled() is True

    # 5. Signal emission check
    revert_requests: list[str] = []
    panel.bank_revert_requested.connect(revert_requests.append)
    panel.bank_revert_requested.emit("campaign_ui.bnk")
    assert revert_requests == ["campaign_ui.bnk"]
