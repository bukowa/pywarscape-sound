from src.ui.features.bank_viewer.causation import reconcile_viewer
from src.ui.features.bank_viewer.state import (
    BankTreeData,
    BankViewerReset,
    BankViewerState,
    HircTreeNode,
    HistoryLocation,
    JumpToNodeRequested,
    LoadBankIntent,
    NavigateHistoryBackRequested,
    NavigateHistoryForwardRequested,
    NodeSelectionRequested,
)


def test_selection_pushes_history():
    state = BankViewerState(selected_bank_name="test.bnk")
    s1, _ = reconcile_viewer(state, NodeSelectionRequested(node_key="hirc:1"))
    assert s1.navigation_history == (HistoryLocation(bank_name="test.bnk", node_key="hirc:1"),)
    assert s1.history_index == 0
    assert s1.selected_node_key == "hirc:1"
    assert s1.ensure_tree_visible is False

    s2, _ = reconcile_viewer(s1, NodeSelectionRequested(node_key="hirc:2"))
    assert s2.navigation_history == (
        HistoryLocation(bank_name="test.bnk", node_key="hirc:1"),
        HistoryLocation(bank_name="test.bnk", node_key="hirc:2"),
    )
    assert s2.history_index == 1
    assert s2.selected_node_key == "hirc:2"
    assert s2.ensure_tree_visible is False


def test_selection_same_node_is_noop():
    loc = HistoryLocation(bank_name="test.bnk", node_key="hirc:1")
    state = BankViewerState(
        selected_bank_name="test.bnk",
        navigation_history=(loc,),
        history_index=0,
        selected_node_key="hirc:1",
    )
    s1, _ = reconcile_viewer(state, NodeSelectionRequested(node_key="hirc:1"))
    assert s1.navigation_history == (loc,)
    assert s1.history_index == 0
    assert s1.selected_node_key == "hirc:1"


def test_first_node_selection_replaces_empty_bank_location():
    state = BankViewerState(
        selected_bank_name="test.bnk",
        navigation_history=(HistoryLocation(bank_name="test.bnk", node_key=None),),
        history_index=0,
        selected_node_key=None,
    )
    s1, _ = reconcile_viewer(state, NodeSelectionRequested(node_key="hirc:1"))
    assert s1.navigation_history == (HistoryLocation(bank_name="test.bnk", node_key="hirc:1"),)
    assert s1.history_index == 0
    assert s1.selected_node_key == "hirc:1"


def test_jump_sets_ensure_tree_visible():
    loc = HistoryLocation(bank_name="test.bnk", node_key="hirc:1")
    state = BankViewerState(
        selected_bank_name="test.bnk",
        navigation_history=(loc,),
        history_index=0,
    )
    s1, _ = reconcile_viewer(state, JumpToNodeRequested(node_key="hirc:2"))
    assert s1.navigation_history == (
        loc,
        HistoryLocation(bank_name="test.bnk", node_key="hirc:2"),
    )
    assert s1.history_index == 1
    assert s1.selected_node_key == "hirc:2"
    assert s1.ensure_tree_visible is True


def test_back_forward_navigation_and_truncation():
    loc1 = HistoryLocation(bank_name="test.bnk", node_key="hirc:1")
    loc2 = HistoryLocation(bank_name="test.bnk", node_key="hirc:2")
    loc3 = HistoryLocation(bank_name="test.bnk", node_key="hirc:3")
    state = BankViewerState(
        selected_bank_name="test.bnk",
        navigation_history=(loc1, loc2, loc3),
        history_index=2,
        selected_node_key="hirc:3",
    )
    # Back to hirc:2
    s1, _ = reconcile_viewer(state, NavigateHistoryBackRequested())
    assert s1.history_index == 1
    assert s1.selected_node_key == "hirc:2"
    assert s1.ensure_tree_visible is True

    # Back to hirc:1
    s2, _ = reconcile_viewer(s1, NavigateHistoryBackRequested())
    assert s2.history_index == 0
    assert s2.selected_node_key == "hirc:1"

    # Forward to hirc:2
    s3, _ = reconcile_viewer(s2, NavigateHistoryForwardRequested())
    assert s3.history_index == 1
    assert s3.selected_node_key == "hirc:2"

    # Selecting new node at index 1 truncates forward history (hirc:3 dropped)
    s4, _ = reconcile_viewer(s3, NodeSelectionRequested(node_key="hirc:4"))
    assert s4.navigation_history == (
        loc1,
        loc2,
        HistoryLocation(bank_name="test.bnk", node_key="hirc:4"),
    )
    assert s4.history_index == 2
    assert s4.selected_node_key == "hirc:4"


def test_cross_bank_navigation():
    # History: (bank_a, node_a1) -> (bank_b, node_b1)
    loc_a = HistoryLocation(bank_name="bank_a.bnk", node_key="hirc:a1")
    loc_b = HistoryLocation(bank_name="bank_b.bnk", node_key="hirc:b1")

    cached_a = BankTreeData(
        bank_name="bank_a.bnk",
        root_keys=("hirc:a1",),
        nodes_by_key={
            "hirc:a1": HircTreeNode(
                key="hirc:a1",
                label="Node A1",
                id_str="1",
                type_str="Sound",
                details="",
            )
        },
    )

    state = BankViewerState(
        selected_bank_name="bank_b.bnk",
        cached_banks={"bank_a.bnk": cached_a},
        navigation_history=(loc_a, loc_b),
        history_index=1,
        selected_node_key="hirc:b1",
    )

    # Navigate Back: should switch to bank_a.bnk, select hirc:a1, and populate from cache
    s_back, intents = reconcile_viewer(state, NavigateHistoryBackRequested())
    assert s_back.selected_bank_name == "bank_a.bnk"
    assert s_back.selected_node_key == "hirc:a1"
    assert s_back.history_index == 0
    assert s_back.root_keys == ("hirc:a1",)
    assert "hirc:a1" in s_back.nodes_by_key
    assert intents == (LoadBankIntent(bank_name="bank_a.bnk"),)

    # Navigate Forward: should switch back to bank_b.bnk and select hirc:b1
    s_fwd, intents_fwd = reconcile_viewer(s_back, NavigateHistoryForwardRequested())
    assert s_fwd.selected_bank_name == "bank_b.bnk"
    assert s_fwd.selected_node_key == "hirc:b1"
    assert s_fwd.history_index == 1
    assert intents_fwd == (LoadBankIntent(bank_name="bank_b.bnk"),)


def test_reset_clears_history():
    loc = HistoryLocation(bank_name="test.bnk", node_key="hirc:1")
    state = BankViewerState(
        navigation_history=(loc,),
        history_index=0,
        selected_node_key="hirc:1",
    )
    s, _ = reconcile_viewer(state, BankViewerReset())
    assert s.navigation_history == ()
    assert s.history_index == -1
    assert s.selected_node_key is None
