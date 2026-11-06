"""
Tests for application signal handling and SIGINT (Ctrl+C) termination.
"""

import signal

import pytest
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QWidget

from app import _setup_signal_handling
from src.ui.features.bank_viewer.view import _MouseNavFilter


def test_setup_signal_handling_attaches_sigint(qtbot, monkeypatch):
    app = QApplication.instance() or QApplication([])
    saved_handlers = {}

    def fake_signal(sig, handler):
        saved_handlers[sig] = handler

    monkeypatch.setattr(signal, "signal", fake_signal)

    quit_called = False

    def fake_quit():
        nonlocal quit_called
        quit_called = True

    monkeypatch.setattr(app, "quit", fake_quit)

    timer = _setup_signal_handling(app)
    try:
        assert signal.SIGINT in saved_handlers
        assert timer.isActive()
        assert timer.interval() == 200

        # Trigger first SIGINT -> calls app.quit()
        saved_handlers[signal.SIGINT](signal.SIGINT, None)
        assert quit_called is True

        # Trigger second SIGINT -> calls sys.exit(130)
        with pytest.raises(SystemExit) as exc_info:
            saved_handlers[signal.SIGINT](signal.SIGINT, None)
        assert exc_info.value.code == 130
    finally:
        timer.stop()


def test_mouse_nav_filter_handles_keyboard_interrupt(qtbot, monkeypatch):
    parent_widget = QWidget()
    qtbot.addWidget(parent_widget)

    nav_filter = _MouseNavFilter(parent_widget)

    quit_called = False
    app = QApplication.instance()

    def fake_quit():
        nonlocal quit_called
        quit_called = True

    monkeypatch.setattr(app, "quit", fake_quit)

    # Simulate super().eventFilter raising KeyboardInterrupt
    def raise_keyboard_interrupt(self, watched, event):
        raise KeyboardInterrupt()

    monkeypatch.setattr(QObject, "eventFilter", raise_keyboard_interrupt)

    dummy_watched = QObject()
    dummy_event = QEvent(QEvent.Type.User)

    result = nav_filter.eventFilter(dummy_watched, dummy_event)
    assert result is False
    assert quit_called is True
