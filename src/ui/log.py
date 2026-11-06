"""
Application-wide logging configuration, file recording, and crash diagnostics.
Provides rotating file logging, sys.excepthook, threading.excepthook, and Qt message interception.
"""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication

from src.workspace.paths import get_log_file_path

DEFAULT_LOG_FILENAME = "app.log"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_active_file_handler: logging.Handler | None = None
_active_stream_handler: logging.Handler | None = None
_original_excepthook: Callable | None = None
_original_thread_excepthook: Callable | None = None


def resolve_log_file_path() -> Path:
    """Returns destination path for the application log file."""
    return get_log_file_path()


def _app_excepthook(exc_type, exc_value, exc_tb) -> None:
    """Catches unhandled main-thread and Qt event-loop exceptions and logs them."""
    if issubclass(exc_type, KeyboardInterrupt):
        if _original_excepthook and _original_excepthook is not _app_excepthook:
            _original_excepthook(exc_type, exc_value, exc_tb)
        else:
            sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    logger = logging.getLogger("root")
    logger.critical(
        "Uncaught exception:",
        exc_info=(exc_type, exc_value, exc_tb),
    )
    if _active_file_handler:
        _active_file_handler.flush()


def _app_thread_excepthook(args: threading.ExceptHookArgs) -> None:
    """Catches unhandled worker-thread exceptions and logs them."""
    if issubclass(args.exc_type, KeyboardInterrupt):
        if (
            _original_thread_excepthook
            and _original_thread_excepthook is not _app_thread_excepthook
        ):
            _original_thread_excepthook(args)
        return

    thread_name = args.thread.name if args.thread else "UnknownThread"
    logger = logging.getLogger("threading")
    logger.critical(
        f"Uncaught thread exception in {thread_name}:",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback)
        if args.exc_value is not None
        else True,
    )
    if _active_file_handler:
        _active_file_handler.flush()


def _install_qt_message_handler() -> None:
    """Connects Qt runtime warnings and criticals to Python logging."""
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler

        def _qt_message_handler(msg_type: QtMsgType, context, message: str) -> None:
            qt_logger = logging.getLogger("Qt")
            loc = (
                f" ({context.file}:{context.line})"
                if context and getattr(context, "file", None)
                else ""
            )
            if msg_type == QtMsgType.QtFatalMsg:
                qt_logger.critical(f"{message}{loc}")
            elif msg_type == QtMsgType.QtCriticalMsg:
                qt_logger.error(f"{message}{loc}")
            elif msg_type == QtMsgType.QtWarningMsg:
                qt_logger.warning(f"{message}{loc}")
            elif msg_type == QtMsgType.QtInfoMsg:
                qt_logger.info(f"{message}{loc}")

        qInstallMessageHandler(_qt_message_handler)
    except (ImportError, RuntimeError):
        pass


def setup_logging(
    log_path: Path | str | None = None,
    level: int = logging.INFO,
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    install_qt_handler: bool = True,
) -> Path:
    """
    Initializes application-wide rotating file and console logging.
    Installs sys.excepthook, threading.excepthook, and Qt message handler.
    """
    global _active_file_handler, _active_stream_handler
    global _original_excepthook, _original_thread_excepthook

    target_path = Path(log_path).resolve() if log_path else resolve_log_file_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(min(level, logging.INFO))

    # Detach previous handlers if re-configuring
    if _active_file_handler:
        root_logger.removeHandler(_active_file_handler)
        _active_file_handler.close()
        _active_file_handler = None

    if _active_stream_handler:
        root_logger.removeHandler(_active_stream_handler)
        _active_stream_handler = None

    # Rotating file handler
    file_handler = RotatingFileHandler(
        target_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    root_logger.addHandler(file_handler)
    _active_file_handler = file_handler

    # Stderr stream handler (for console output)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(logging.WARNING)
    stream_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    root_logger.addHandler(stream_handler)
    _active_stream_handler = stream_handler

    # Install exception hooks
    if sys.excepthook is not _app_excepthook:
        _original_excepthook = sys.excepthook
        sys.excepthook = _app_excepthook

    if hasattr(threading, "excepthook") and threading.excepthook is not _app_thread_excepthook:
        _original_thread_excepthook = threading.excepthook
        threading.excepthook = _app_thread_excepthook

    if install_qt_handler:
        _install_qt_message_handler()

    return target_path


def teardown_logging() -> None:
    """Restores original exception hooks and closes active handlers (useful in tests)."""
    global _active_file_handler, _active_stream_handler
    global _original_excepthook, _original_thread_excepthook

    root_logger = logging.getLogger()
    if _active_file_handler:
        root_logger.removeHandler(_active_file_handler)
        _active_file_handler.close()
        _active_file_handler = None

    if _active_stream_handler:
        root_logger.removeHandler(_active_stream_handler)
        _active_stream_handler = None

    if _original_excepthook is not None:
        sys.excepthook = _original_excepthook
        _original_excepthook = None

    if _original_thread_excepthook is not None and hasattr(threading, "excepthook"):
        threading.excepthook = _original_thread_excepthook
        _original_thread_excepthook = None


class SafeApplication(QApplication):
    """QApplication with a global event exception boundary logging all uncaught UI events."""

    def notify(self, receiver: QObject, event: QEvent) -> bool:
        """Global Qt event dispatch try-catch boundary capturing unhandled exceptions."""
        try:
            return super().notify(receiver, event)
        except Exception:
            logger = logging.getLogger("root")
            logger.critical(
                "Global exception caught in QApplication.notify:",
                exc_info=True,
            )
            if _active_file_handler:
                _active_file_handler.flush()
            return False
