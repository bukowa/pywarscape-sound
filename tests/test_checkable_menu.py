"""Unit and UI tests for CheckableMenu and persistent multi-select dropdown menus."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk
from src.bnk.models import CAkSound
from src.models import AudioCatalogEntry
from src.ui.features.audio_sources.columns import CatalogColumn
from src.ui.features.audio_sources.widgets.game_audio_tab import GameAudioTab
from src.ui.features.bank_viewer.columns import TreeColumn
from src.ui.features.bank_viewer.overlays import TreeOverlay
from src.ui.features.bank_viewer.store import BankViewerStore
from src.ui.features.bank_viewer.view import BankViewerView
from src.ui.menu import CheckableMenu


def _make_bank(bank_id: int = 100, sound_ids: tuple[int, ...] = (101, 102)) -> SoundBank:
    hirc = HircChunk()
    hirc.objects = [CAkSound(id=sid, source_id=sid * 10, stream_type=2) for sid in sound_ids]
    return SoundBank(header=BkhdChunk(bank_id=bank_id), hirc=hirc)


def test_checkable_menu_click_toggles_and_keeps_open(qtbot):
    """Clicking checkable items toggles their state without closing the popup menu."""
    menu = CheckableMenu()
    qtbot.addWidget(menu)

    act1 = menu.addAction("Option 1")
    act1.setCheckable(True)
    act1.setChecked(False)

    act2 = menu.addAction("Option 2")
    act2.setCheckable(True)
    act2.setChecked(True)

    menu.show()
    QApplication.processEvents()
    assert menu.isVisible() is True

    # Click Option 1 (unchecked -> checked)
    rect1 = menu.actionGeometry(act1)
    QTest.mouseClick(
        menu, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect1.center()
    )
    QApplication.processEvents()
    assert act1.isChecked() is True
    assert menu.isVisible() is True

    # Click Option 2 (checked -> unchecked)
    rect2 = menu.actionGeometry(act2)
    QTest.mouseClick(
        menu, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect2.center()
    )
    QApplication.processEvents()
    assert act2.isChecked() is False
    assert menu.isVisible() is True

    # Click Option 1 again (checked -> unchecked)
    QTest.mouseClick(
        menu, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect1.center()
    )
    QApplication.processEvents()
    assert act1.isChecked() is False
    assert menu.isVisible() is True


def test_checkable_menu_disabled_item_does_not_toggle_or_close(qtbot):
    """Clicking a disabled checkable item does not toggle it and keeps the menu open."""
    menu = CheckableMenu()
    qtbot.addWidget(menu)

    act = menu.addAction("Mandatory Column")
    act.setCheckable(True)
    act.setChecked(True)
    act.setEnabled(False)

    menu.show()
    QApplication.processEvents()

    rect = menu.actionGeometry(act)
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center())
    QApplication.processEvents()

    assert act.isChecked() is True
    assert menu.isVisible() is True


def test_checkable_menu_non_checkable_command_closes_menu(qtbot):
    """Clicking a normal, non-checkable action triggers it and dismisses the menu."""
    menu = CheckableMenu()
    qtbot.addWidget(menu)

    triggered_count = 0

    def on_triggered():
        nonlocal triggered_count
        triggered_count += 1

    act_cmd = menu.addAction("Reset Defaults")
    act_cmd.triggered.connect(on_triggered)

    menu.show()
    QApplication.processEvents()

    rect = menu.actionGeometry(act_cmd)
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center())
    QApplication.processEvents()

    assert triggered_count == 1
    assert menu.isVisible() is False


def test_checkable_menu_keyboard_space_and_escape(qtbot):
    """Space key toggles checkable item in place; Escape key closes the menu."""
    menu = CheckableMenu()
    qtbot.addWidget(menu)

    act = menu.addAction("Check Item")
    act.setCheckable(True)
    act.setChecked(False)

    menu.setActiveAction(act)
    menu.show()
    QApplication.processEvents()

    # Space toggles
    QTest.keyClick(menu, Qt.Key.Key_Space)
    QApplication.processEvents()
    assert act.isChecked() is True
    assert menu.isVisible() is True

    # Space toggles again
    QTest.keyClick(menu, Qt.Key.Key_Space)
    QApplication.processEvents()
    assert act.isChecked() is False
    assert menu.isVisible() is True

    # Escape dismisses
    QTest.keyClick(menu, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert menu.isVisible() is False


def test_checkable_menu_border_click_does_not_dismiss(qtbot):
    """Clicking within the menu rect (e.g. inner padding) does not dismiss the menu."""
    menu = CheckableMenu()
    qtbot.addWidget(menu)

    act = menu.addAction("Option")
    act.setCheckable(True)

    menu.show()
    QApplication.processEvents()

    # Click top-left edge (padding area where actionAt is None)
    QTest.mouseClick(menu, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(1, 1))
    QApplication.processEvents()
    assert menu.isVisible() is True


def test_bank_viewer_columns_menu_stays_open_on_toggle(qtbot):
    """BankViewerView Columns menu stays open when toggling columns and updates button text."""
    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    bank = _make_bank(100, (101, 102))
    store.load_soundbank_instance("test_bank.bnk", bank)

    assert isinstance(view.columns_menu, CheckableMenu)
    assert isinstance(view.overlays_menu, CheckableMenu)

    view.btn_columns.showMenu()
    QApplication.processEvents()
    assert view.columns_menu.isVisible() is True

    # Toggle ID column (hide it)
    act_id = view.column_actions[TreeColumn.ID]
    assert act_id.isChecked() is True
    rect_id = view.columns_menu.actionGeometry(act_id)
    QTest.mouseClick(
        view.columns_menu,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        rect_id.center(),
    )
    QApplication.processEvents()

    # Menu MUST remain open after click
    assert view.columns_menu.isVisible() is True
    assert act_id.isChecked() is False
    assert TreeColumn.ID not in store.state.visible_columns
    assert "Columns (3)" in view.btn_columns.text()

    # Toggle Type column (hide it) while menu is still open
    act_type = view.column_actions[TreeColumn.TYPE]
    assert act_type.isChecked() is True
    rect_type = view.columns_menu.actionGeometry(act_type)
    QTest.mouseClick(
        view.columns_menu,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        rect_type.center(),
    )
    QApplication.processEvents()

    # Menu still open after second toggle
    assert view.columns_menu.isVisible() is True
    assert act_type.isChecked() is False
    assert TreeColumn.TYPE not in store.state.visible_columns
    assert "Columns (2)" in view.btn_columns.text()

    # Close with Escape
    QTest.keyClick(view.columns_menu, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert view.columns_menu.isVisible() is False


def test_bank_viewer_overlays_menu_stays_open_on_toggle(qtbot):
    """BankViewerView Overlays menu stays open when toggling overlays and updates button text."""
    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    view.btn_overlays.showMenu()
    QApplication.processEvents()
    assert view.overlays_menu.isVisible() is True

    act_game = view.overlay_actions[TreeOverlay.GAME_NAMES]
    initial_checked = act_game.isChecked()
    rect_game = view.overlays_menu.actionGeometry(act_game)

    QTest.mouseClick(
        view.overlays_menu,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        rect_game.center(),
    )
    QApplication.processEvents()

    # Menu stays open and state toggled
    assert view.overlays_menu.isVisible() is True
    assert act_game.isChecked() != initial_checked
    assert (TreeOverlay.GAME_NAMES in store.state.active_overlays) == act_game.isChecked()

    view.overlays_menu.close()


def test_game_audio_tab_columns_menu_stays_open(qtbot):
    """GameAudioTab Columns menu stays open when toggling catalog columns."""
    tab = GameAudioTab()
    qtbot.addWidget(tab)

    entries = [
        AudioCatalogEntry(
            wem_id=101,
            display_name="sound_1",
            source_bank="bank_a.bnk",
            category="Battle",
            duration_ms=2500.0,
        )
    ]
    tab.set_entries(entries)

    assert isinstance(tab._columns_menu, CheckableMenu)

    tab.btn_columns.showMenu()
    QApplication.processEvents()
    assert tab._columns_menu.isVisible() is True

    # Toggle Category column
    act_cat = tab._column_actions[CatalogColumn.CATEGORY]
    assert act_cat.isChecked() is False
    rect_cat = tab._columns_menu.actionGeometry(act_cat)

    QTest.mouseClick(
        tab._columns_menu,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        rect_cat.center(),
    )
    QApplication.processEvents()

    # Menu stays open and Category becomes visible
    assert tab._columns_menu.isVisible() is True
    assert act_cat.isChecked() is True
    assert CatalogColumn.CATEGORY in tab.visible_columns

    tab._columns_menu.close()
