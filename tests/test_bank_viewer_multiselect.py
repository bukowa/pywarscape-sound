"""Unit tests for BankViewer multi-selection and drag-and-drop audio source ingestion."""

import json

import pytest
from PySide6.QtCore import QByteArray, QMimeData, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QAbstractItemView

from src.bnk.bank import BkhdChunk, HircChunk, SoundBank
from src.bnk.models import CAkEvent
from src.ui.features.bank_viewer.causation import reconcile_viewer
from src.ui.features.bank_viewer.state import (
    BankViewerState,
    MultiNodeSelectionRequested,
    NodeSelectionRequested,
)
from src.ui.features.bank_viewer.store import BankViewerStore
from src.ui.features.bank_viewer.view import BankViewerView


def test_bank_viewer_multi_selection_configuration(qapp):
    store = BankViewerStore()
    view = BankViewerView(store)

    assert view.tree_widget.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection
    assert view.tree_widget.acceptDrops() is True


def test_causation_multi_node_selection():
    initial_state = BankViewerState(selected_bank_name="test.bnk")

    # Multi selection with explicit primary
    evt1 = MultiNodeSelectionRequested(
        node_keys=("hirc:10", "hirc:20", "hirc:30"),
        primary_key="hirc:20",
    )
    s1, intents1 = reconcile_viewer(initial_state, evt1)
    assert s1.selected_node_keys == ("hirc:10", "hirc:20", "hirc:30")
    assert s1.selected_node_key == "hirc:20"

    # Multi selection with default primary (first element)
    evt2 = MultiNodeSelectionRequested(
        node_keys=("hirc:10", "hirc:20"),
        primary_key=None,
    )
    s2, intents2 = reconcile_viewer(initial_state, evt2)
    assert s2.selected_node_keys == ("hirc:10", "hirc:20")
    assert s2.selected_node_key == "hirc:10"

    # Multi selection with empty keys clears selection
    evt3 = MultiNodeSelectionRequested(node_keys=(), primary_key=None)
    s3, _ = reconcile_viewer(s2, evt3)
    assert s3.selected_node_keys == ()
    assert s3.selected_node_key is None

    # Single selection updates selected_node_keys tuple
    evt4 = NodeSelectionRequested(node_key="hirc:50")
    s4, _ = reconcile_viewer(initial_state, evt4)
    assert s4.selected_node_keys == ("hirc:50",)
    assert s4.selected_node_key == "hirc:50"

    # Single selection None clears both
    evt5 = NodeSelectionRequested(node_key=None)
    s5, _ = reconcile_viewer(s4, evt5)
    assert s5.selected_node_keys == ()
    assert s5.selected_node_key is None


def test_store_select_nodes():
    store = BankViewerStore()
    store.select_nodes(("hirc:100", "hirc:200"), primary_key="hirc:200")

    assert store.state.selected_node_keys == ("hirc:100", "hirc:200")
    assert store.state.selected_node_key == "hirc:200"


def test_view_tree_multi_selection_updates_store(qapp):
    store = BankViewerStore()
    view = BankViewerView(store)

    # Synthetic bank with 2 events
    ev1 = CAkEvent(id=1, actions=[])
    ev2 = CAkEvent(id=2, actions=[])
    bank = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[ev1, ev2]),
    )
    store.load_soundbank_instance("test.bnk", bank)

    # In tree, select both items
    item1 = view._items_by_key.get("hirc:1")
    item2 = view._items_by_key.get("hirc:2")
    assert item1 is not None and item2 is not None

    view.tree_widget.setCurrentItem(item2)
    item1.setSelected(True)
    item2.setSelected(True)
    view._on_tree_selection_changed()

    assert set(store.state.selected_node_keys) == {"hirc:1", "hirc:2"}
    assert store.state.selected_node_key in ("hirc:1", "hirc:2")


def test_view_tree_drag_and_drop_ingestion(qapp):
    store = BankViewerStore()
    view = BankViewerView(store)

    ev = CAkEvent(id=99, actions=[])
    bank = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[ev]),
    )
    store.load_soundbank_instance("test.bnk", bank)

    # 1. Drag enter with invalid format is ignored
    invalid_mime = QMimeData()
    invalid_mime.setText("plain text")
    enter_ev1 = QDragEnterEvent(
        QPointF(10.0, 10.0),
        Qt.DropAction.CopyAction,
        invalid_mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.tree_widget.dragEnterEvent(enter_ev1)
    assert not enter_ev1.isAccepted()

    # 2. Drag enter with valid format is accepted
    valid_mime = QMimeData()
    payload = ["source_audio/sound1.wav", "source_audio/sound2.wav"]
    valid_mime.setData(
        "application/x-audio-editor-source", QByteArray(json.dumps(payload).encode("utf-8"))
    )

    enter_ev2 = QDragEnterEvent(
        QPointF(10.0, 10.0),
        Qt.DropAction.CopyAction,
        valid_mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.tree_widget.dragEnterEvent(enter_ev2)
    assert enter_ev2.isAccepted()

    # 3. Drag move is accepted
    move_ev = QDragMoveEvent(
        QPointF(10.0, 10.0),
        Qt.DropAction.CopyAction,
        valid_mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.tree_widget.dragMoveEvent(move_ev)
    assert move_ev.isAccepted()

    # 4. Drop event emits source_dropped signal
    dropped_signals = []
    view.source_dropped.connect(lambda paths, target: dropped_signals.append((paths, target)))

    item = view._items_by_key.get("hirc:99")
    assert item is not None
    view.tree_widget.setCurrentItem(item)
    rect = view.tree_widget.visualItemRect(item)
    pos = rect.center()

    drop_ev = QDropEvent(
        QPointF(float(pos.x()), float(pos.y())),
        Qt.DropAction.CopyAction,
        valid_mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.tree_widget.dropEvent(drop_ev)
    assert drop_ev.isAccepted()

    assert len(dropped_signals) == 1
    paths, target = dropped_signals[0]
    assert paths == ("source_audio/sound1.wav", "source_audio/sound2.wav")
    assert target == "hirc:99"


def test_view_tree_ctrl_click_multiselect_preservation(qapp, qtbot):
    """Verifies that Ctrl-click multi-selection in BankTreeWidget is fully preserved during state updates."""
    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    ev1 = CAkEvent(id=10, actions=[])
    ev2 = CAkEvent(id=20, actions=[])
    ev3 = CAkEvent(id=30, actions=[])
    bank = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[ev1, ev2, ev3]),
    )
    store.load_soundbank_instance("test.bnk", bank)

    item1 = view._items_by_key.get("hirc:10")
    item2 = view._items_by_key.get("hirc:20")
    item3 = view._items_by_key.get("hirc:30")
    assert item1 is not None and item2 is not None and item3 is not None

    # 1. Normal click on item1
    rect1 = view.tree_widget.visualItemRect(item1)
    qtbot.mouseClick(
        view.tree_widget.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        rect1.center(),
    )
    assert len(view.tree_widget.selectedItems()) == 1
    assert store.state.selected_node_keys == ("hirc:10",)

    # 2. Ctrl-click on item2 to add to selection
    rect2 = view.tree_widget.visualItemRect(item2)
    qtbot.mouseClick(
        view.tree_widget.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        rect2.center(),
    )
    assert len(view.tree_widget.selectedItems()) == 2
    assert set(store.state.selected_node_keys) == {"hirc:10", "hirc:20"}

    # 3. Simulate view.render(store.state) to verify _update_tree_selection does NOT wipe selection
    view.render(store.state)
    assert len(view.tree_widget.selectedItems()) == 2
    assert "hirc:10" in store.state.selected_node_keys
    assert "hirc:20" in store.state.selected_node_keys

    # 4. Ctrl-click on item3 to add 3rd item
    rect3 = view.tree_widget.visualItemRect(item3)
    qtbot.mouseClick(
        view.tree_widget.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        rect3.center(),
    )
    assert len(view.tree_widget.selectedItems()) == 3
    assert set(store.state.selected_node_keys) == {"hirc:10", "hirc:20", "hirc:30"}

    # 5. Ctrl-click on item2 again to toggle deselect
    qtbot.mouseClick(
        view.tree_widget.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ControlModifier,
        rect2.center(),
    )
    assert len(view.tree_widget.selectedItems()) == 2
    assert set(store.state.selected_node_keys) == {"hirc:10", "hirc:30"}
