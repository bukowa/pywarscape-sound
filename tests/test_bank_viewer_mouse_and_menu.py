from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk
from src.bnk.models import CAkSound
from src.ui.features.bank_viewer.store import BankViewerStore
from src.ui.features.bank_viewer.view import BankViewerView
from src.ui.shell.store import ShellStore
from src.ui.shell.view import MainWindow


def _make_bank(bank_id: int, sound_ids: list[int]) -> SoundBank:
    hirc = HircChunk()
    hirc.objects = [CAkSound(id=sid, source_id=sid * 10, stream_type=2) for sid in sound_ids]
    return SoundBank(header=BkhdChunk(bank_id=bank_id), hirc=hirc)


def test_mouse_button_navigation(qapp: QApplication):
    store = BankViewerStore()
    view = BankViewerView(store)

    bank_a = _make_bank(100, [101, 102])
    store.load_soundbank_instance("bank_a.bnk", bank_a)
    store.select_node("hirc:101")
    store.select_node("hirc:102")

    assert store.state.selected_node_key == "hirc:102"
    assert store.state.can_navigate_back is True
    assert store.state.can_navigate_forward is False

    # Simulate Mouse Button 4 (BackButton) click over tree widget viewport
    evt_back = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(20, 20),
        QPointF(20, 20),
        Qt.MouseButton.BackButton,
        Qt.MouseButton.BackButton,
        Qt.KeyboardModifier.NoModifier,
    )
    qapp.sendEvent(view.tree_widget.viewport(), evt_back)

    assert store.state.selected_node_key == "hirc:101"
    assert store.state.can_navigate_back is False
    assert store.state.can_navigate_forward is True

    # Simulate Mouse Button 5 (ForwardButton) click over table banks
    evt_fwd = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(20, 20),
        QPointF(20, 20),
        Qt.MouseButton.ForwardButton,
        Qt.MouseButton.ForwardButton,
        Qt.KeyboardModifier.NoModifier,
    )
    qapp.sendEvent(view.bank_list_panel.table_banks.viewport(), evt_fwd)

    assert store.state.selected_node_key == "hirc:102"
    assert store.state.can_navigate_back is True
    assert store.state.can_navigate_forward is False

    view.close()


def test_cross_bank_mouse_navigation(qapp: QApplication):
    store = BankViewerStore()
    view = BankViewerView(store)

    bank_a = _make_bank(100, [101])
    bank_b = _make_bank(200, [201])
    store.load_soundbank_instance("bank_a.bnk", bank_a)
    store.select_node("hirc:101")

    store.load_soundbank_instance("bank_b.bnk", bank_b)
    store.select_node("hirc:201")

    assert store.state.selected_bank_name == "bank_b.bnk"
    assert store.state.selected_node_key == "hirc:201"
    assert store.state.can_navigate_back is True

    # Click Mouse BackButton
    evt_back = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10, 10),
        QPointF(10, 10),
        Qt.MouseButton.BackButton,
        Qt.MouseButton.BackButton,
        Qt.KeyboardModifier.NoModifier,
    )
    qapp.sendEvent(view.tree_widget.viewport(), evt_back)

    # Must transition back to bank_a.bnk and restore hirc:101
    assert store.state.selected_bank_name == "bank_a.bnk"
    assert store.state.selected_node_key == "hirc:101"

    # Click Mouse ForwardButton
    evt_fwd = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10, 10),
        QPointF(10, 10),
        Qt.MouseButton.ForwardButton,
        Qt.MouseButton.ForwardButton,
        Qt.KeyboardModifier.NoModifier,
    )
    qapp.sendEvent(view.tree_widget.viewport(), evt_fwd)

    # Must transition forward to bank_b.bnk and restore hirc:201
    assert store.state.selected_bank_name == "bank_b.bnk"
    assert store.state.selected_node_key == "hirc:201"

    view.close()


def test_shell_edit_menu_actions(qtbot):
    shell_store = ShellStore()
    shell_view = MainWindow(shell_store)
    qtbot.addWidget(shell_view)

    assert hasattr(shell_view, "act_undo")
    assert hasattr(shell_view, "act_redo")
    assert shell_view.act_undo.text() == "Undo"
    assert shell_view.act_redo.text() == "Redo"
    assert shell_view.act_undo.isEnabled() is False
    assert shell_view.act_redo.isEnabled() is False

    # Load banks in bank viewer
    bank = _make_bank(500, [501, 502])
    shell_view.bank_viewer_store.load_soundbank_instance("menu_test.bnk", bank)
    shell_view.bank_viewer_store.select_node("hirc:501")
    shell_view.bank_viewer_store.select_node("hirc:502")

    # Undo action must now be enabled
    assert shell_view.act_undo.isEnabled() is True
    assert shell_view.act_redo.isEnabled() is False

    # Trigger Undo
    shell_view.act_undo.trigger()
    assert shell_view.bank_viewer_store.state.selected_node_key == "hirc:501"
    assert shell_view.act_undo.isEnabled() is False
    assert shell_view.act_redo.isEnabled() is True

    # Trigger Redo
    shell_view.act_redo.trigger()
    assert shell_view.bank_viewer_store.state.selected_node_key == "hirc:502"
    assert shell_view.act_undo.isEnabled() is True
    assert shell_view.act_redo.isEnabled() is False

    shell_view.close()
