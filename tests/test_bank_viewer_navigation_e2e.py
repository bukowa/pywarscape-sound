from PySide6.QtCore import Qt

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk, DidxChunk, DidxEntry
from src.bnk.models import CAkRanSeqCntr, CAkSound
from src.ui.features.bank_viewer.state import HistoryLocation
from src.ui.features.bank_viewer.store import BankViewerStore
from src.ui.features.bank_viewer.view import BankViewerView


def test_bank_viewer_navigation_and_tree_sync(qtbot):
    bank = SoundBank(
        header=BkhdChunk(bank_id=300),
        didx=DidxChunk(entries=[DidxEntry(file_id=6001, offset=0, size=512)]),
        hirc=HircChunk(),
    )
    sound = CAkSound(id=301, source_id=6001, stream_type=0)
    cntr = CAkRanSeqCntr(id=302, children=[301])
    bank.hirc.objects = [sound, cntr]

    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    store.load_soundbank_instance("test_bank.bnk", bank)

    # 1. Select Container
    store.select_node("hirc:302")
    assert store.state.selected_node_key == "hirc:302"
    assert store.state.can_navigate_back is False

    # 2. Select Sound
    store.select_node("hirc:301")
    assert store.state.selected_node_key == "hirc:301"
    assert store.state.can_navigate_back is True

    # 3. Navigate back via store
    store.navigate_back()
    assert store.state.selected_node_key == "hirc:302"
    assert store.state.can_navigate_forward is True

    # Verify tree selected item is hirc:302
    curr_item = view.tree_widget.currentItem()
    assert curr_item is not None
    assert curr_item.data(0, Qt.ItemDataRole.UserRole + 1) == "hirc:302"


def test_bank_viewer_jump_reference_synchronization(qtbot):
    bank = SoundBank(
        header=BkhdChunk(bank_id=400),
        didx=DidxChunk(entries=[DidxEntry(file_id=7001, offset=0, size=512)]),
        hirc=HircChunk(),
    )
    sound = CAkSound(id=401, source_id=7001, stream_type=0)
    cntr = CAkRanSeqCntr(id=402, children=[401])
    bank.hirc.objects = [sound, cntr]

    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    store.load_soundbank_instance("test_jump.bnk", bank)

    # Start at Sound
    store.select_node("hirc:401")
    assert store.state.selected_node_key == "hirc:401"

    # Jump to parent container via inspector combo
    assert view.inspector_panel.combo_parents.count() >= 2
    view.inspector_panel.combo_parents.setCurrentIndex(1)

    assert store.state.selected_node_key == "hirc:402"
    assert view.tree_widget.currentItem().data(0, Qt.ItemDataRole.UserRole + 1) == "hirc:402"


def test_bank_viewer_keyboard_navigation_shortcuts(qtbot):
    bank = SoundBank(
        header=BkhdChunk(bank_id=500),
        hirc=HircChunk(),
    )
    s1 = CAkSound(id=501, source_id=1, stream_type=2)
    s2 = CAkSound(id=502, source_id=2, stream_type=2)
    bank.hirc.objects = [s1, s2]

    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    store.load_soundbank_instance("test_kb.bnk", bank)

    store.select_node("hirc:501")
    store.select_node("hirc:502")
    assert store.state.history_index == 1

    # Simulate Alt+Left shortcut trigger
    view._shortcut_back.activated.emit()
    assert store.state.selected_node_key == "hirc:501"
    assert store.state.history_index == 0

    # Simulate Alt+Right shortcut trigger
    view._shortcut_forward.activated.emit()
    assert store.state.selected_node_key == "hirc:502"
    assert store.state.history_index == 1

    # Simulate Ctrl+Z (Undo) shortcut trigger
    view._shortcut_undo.activated.emit()
    assert store.state.selected_node_key == "hirc:501"
    assert store.state.history_index == 0

    # Simulate Ctrl+Y (Redo) shortcut trigger
    view._shortcut_redo.activated.emit()
    assert store.state.selected_node_key == "hirc:502"
    assert store.state.history_index == 1


def test_bank_viewer_jump_to_collapsed_category_child(qtbot):
    bank = SoundBank(
        header=BkhdChunk(bank_id=600),
        hirc=HircChunk(),
    )
    sound = CAkSound(id=601, source_id=10, stream_type=2)
    bank.hirc.objects = [sound]

    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    store.load_soundbank_instance("test_cat.bnk", bank)

    # Categories start collapsed
    cat_item = view._items_by_key.get("cat:sounds")
    if cat_item is not None:
        cat_item.setExpanded(False)

    # Jump to sound: should auto-expand parent category and select
    store.jump_to_node("hirc:601")

    assert store.state.selected_node_key == "hirc:601"
    curr_item = view.tree_widget.currentItem()
    assert curr_item is not None
    assert curr_item.data(0, Qt.ItemDataRole.UserRole + 1) == "hirc:601"


def test_cross_bank_transition_history(qtbot):
    b1 = SoundBank(header=BkhdChunk(bank_id=701), hirc=HircChunk())
    b1.hirc.objects = [CAkSound(id=711, source_id=1, stream_type=2)]

    b2 = SoundBank(header=BkhdChunk(bank_id=702), hirc=HircChunk())
    b2.hirc.objects = [CAkSound(id=722, source_id=2, stream_type=2)]

    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    store.load_soundbank_instance("bank1.bnk", b1)
    store.select_node("hirc:711")
    assert store.state.selected_node_key == "hirc:711"
    assert store.state.selected_bank_name == "bank1.bnk"

    store.load_soundbank_instance("bank2.bnk", b2)
    store.select_node("hirc:722")
    assert store.state.selected_node_key == "hirc:722"
    assert store.state.selected_bank_name == "bank2.bnk"

    # Both banks and selections are preserved in navigation history
    assert len(store.state.navigation_history) == 2
    assert store.state.navigation_history[0] == HistoryLocation(
        bank_name="bank1.bnk", node_key="hirc:711"
    )
    assert store.state.navigation_history[1] == HistoryLocation(
        bank_name="bank2.bnk", node_key="hirc:722"
    )

    # Navigate Back: transitions back to bank1.bnk and selects hirc:711
    store.navigate_back()
    assert store.state.selected_bank_name == "bank1.bnk"
    assert store.state.selected_node_key == "hirc:711"

    # Navigate Forward: transitions forward to bank2.bnk and selects hirc:722
    store.navigate_forward()
    assert store.state.selected_bank_name == "bank2.bnk"
    assert store.state.selected_node_key == "hirc:722"
