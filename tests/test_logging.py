"""
Tests for application-wide logging and crash diagnostics (v3/ui/log.py).
"""

from __future__ import annotations

import logging
import sys
import threading

import pytest

from src.ui.log import (
    DEFAULT_LOG_FILENAME,
    resolve_log_file_path,
    setup_logging,
    teardown_logging,
)


@pytest.fixture(autouse=True)
def clean_logging():
    """Ensure logging handlers and hooks are restored after each test."""
    yield
    teardown_logging()


def test_resolve_log_file_path_default(monkeypatch):
    monkeypatch.delenv("AUDIO_EDITOR_LOG_FILE", raising=False)
    path = resolve_log_file_path()
    assert path.name == DEFAULT_LOG_FILENAME
    assert path.is_absolute()


def test_resolve_log_file_path_env_var(tmp_path, monkeypatch):
    custom_log = tmp_path / "custom" / "debug.log"
    monkeypatch.setenv("AUDIO_EDITOR_LOG_FILE", str(custom_log))
    path = resolve_log_file_path()
    assert path == custom_log.resolve()


def test_setup_logging_creates_file_and_logs_info(tmp_path):
    log_file = tmp_path / "test_app.log"
    setup_logging(log_path=log_file, level=logging.INFO, install_qt_handler=False)

    logger = logging.getLogger("test_logger")
    logger.info("Hello world information message")

    for handler in logging.getLogger().handlers:
        handler.flush()

    assert log_file.is_file()
    content = log_file.read_text(encoding="utf-8")
    assert "[INFO] test_logger: Hello world information message" in content


def test_logger_error_and_exception_writes_to_file(tmp_path):
    log_file = tmp_path / "test_errors.log"
    setup_logging(log_path=log_file, install_qt_handler=False)

    logger = logging.getLogger("db_service")
    logger.error("Failed to decode table row 42")

    try:
        raise ValueError("corrupt wem header")
    except ValueError:
        logger.exception("Audio conversion failure")

    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_file.read_text(encoding="utf-8")
    assert "[ERROR] db_service: Failed to decode table row 42" in content
    assert "[ERROR] db_service: Audio conversion failure" in content
    assert "ValueError: corrupt wem header" in content
    assert "Traceback (most recent call last):" in content


def test_sys_excepthook_captures_uncaught_exception(tmp_path):
    log_file = tmp_path / "test_crash.log"
    setup_logging(log_path=log_file, install_qt_handler=False)

    try:
        raise UnboundLocalError("cannot access local variable 'dur_ms'")
    except UnboundLocalError:
        exc_type, exc_val, exc_tb = sys.exc_info()
        sys.excepthook(exc_type, exc_val, exc_tb)

    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_file.read_text(encoding="utf-8")
    assert "[CRITICAL] root: Uncaught exception:" in content
    assert "UnboundLocalError: cannot access local variable 'dur_ms'" in content
    assert "Traceback (most recent call last):" in content


def test_threading_excepthook_captures_thread_exception(tmp_path):
    log_file = tmp_path / "test_thread_crash.log"
    setup_logging(log_path=log_file, install_qt_handler=False)

    worker_thread = threading.Thread(name="VgmstreamWorker", target=lambda: None)

    try:
        raise RuntimeError("vgmstream subprocess terminated with code -1")
    except RuntimeError:
        exc_type, exc_val, exc_tb = sys.exc_info()
        hook_args = threading.ExceptHookArgs((exc_type, exc_val, exc_tb, worker_thread))
        threading.excepthook(hook_args)

    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_file.read_text(encoding="utf-8")
    assert "[CRITICAL] threading: Uncaught thread exception in VgmstreamWorker:" in content
    assert "RuntimeError: vgmstream subprocess terminated with code -1" in content


def test_keyboard_interrupt_bypasses_critical_logging(tmp_path, monkeypatch):
    log_file = tmp_path / "test_sigint.log"
    setup_logging(log_path=log_file, install_qt_handler=False)

    orig_called = False

    def fake_orig(exc_type, exc_val, exc_tb):
        nonlocal orig_called
        orig_called = True

    import src.ui.log

    monkeypatch.setattr(src.ui.log, "_original_excepthook", fake_orig)

    try:
        raise KeyboardInterrupt()
    except KeyboardInterrupt:
        exc_type, exc_val, exc_tb = sys.exc_info()
        sys.excepthook(exc_type, exc_val, exc_tb)

    assert orig_called is True

    for handler in logging.getLogger().handlers:
        handler.flush()

    content = ""
    if log_file.exists():
        content = log_file.read_text(encoding="utf-8")

    assert "[CRITICAL]" not in content
    assert "KeyboardInterrupt" not in content


def test_qt_message_handler_integration(tmp_path):
    log_file = tmp_path / "test_qt.log"
    setup_logging(log_path=log_file, install_qt_handler=True)

    from PySide6.QtCore import qCritical, qWarning

    qWarning("QSS style sheet parser warning")
    qCritical("Qt widget layout critical error")

    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_file.read_text(encoding="utf-8")
    assert "[WARNING] Qt: QSS style sheet parser warning" in content
    assert "[ERROR] Qt: Qt widget layout critical error" in content


def test_safe_application_notify_catches_event_exception(tmp_path):
    import subprocess
    import sys

    log_file = tmp_path / "test_notify.log"
    code = f"""
import logging
from PySide6.QtCore import QEvent, QObject
from src.ui.log import SafeApplication, setup_logging

setup_logging(log_path=r"{log_file}", install_qt_handler=False)
app = SafeApplication([])

class FaultyObject(QObject):
    def customEvent(self, ev):
        raise RuntimeError("simulated crash in event handler")

faulty = FaultyObject()
app.postEvent(faulty, QEvent(QEvent.Type.User))
app.processEvents()

for handler in logging.getLogger().handlers:
    handler.flush()
"""
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0
    content = log_file.read_text(encoding="utf-8")
    assert "[CRITICAL] root: Global exception caught in QApplication.notify:" in content
    assert "simulated crash in event handler" in content
