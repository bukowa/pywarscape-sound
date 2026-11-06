"""
Audio Editor - Desktop SoundBank and Audio Editor for Attila and Rome II.
Official PySide6 application entry point.
"""

import logging
import os
import signal
import sys

# Ensure UTF-8 output formatting
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication


def _setup_signal_handling(app: QApplication) -> QTimer:
    """Configures SIGINT (Ctrl+C) handling so the Qt application terminates gracefully."""
    interrupted = False

    def _sigint_handler(*_):
        nonlocal interrupted
        if interrupted:
            sys.exit(130)
        interrupted = True
        app.quit()

    signal.signal(signal.SIGINT, _sigint_handler)

    # Allow the Python interpreter to periodically process OS signals (every 200ms)
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(200)
    return timer


def main() -> int:
    from src.ui.log import SafeApplication, setup_logging
    from src.ui.shell import MainWindow
    from src.ui.theme import apply_theme
    from src.workspace.paths import get_app_root

    app_root = get_app_root()
    if getattr(sys, "frozen", False):
        os.chdir(app_root)

    setup_logging()
    logger = logging.getLogger("app")
    logger.info("Application starting...")

    app = SafeApplication.instance() or SafeApplication(sys.argv)
    app.setApplicationName("PyWarscape Sound")
    app.setApplicationDisplayName("PyWarscape Sound")
    app.setOrganizationName("PyWarscape")

    apply_theme(app)
    sig_timer = _setup_signal_handling(app)

    window = MainWindow()
    if window.has_restored_geometry:
        window.show()
    else:
        window.showMaximized()

    if window.should_show_disclaimer():
        window.show_disclaimer_dialog(is_first_run=True)

    def _on_shutdown() -> None:
        logger.info("Application shutting down...")
        window._save_ui_layout()

    app.aboutToQuit.connect(_on_shutdown)

    ret = app.exec()
    del sig_timer
    return ret


if __name__ == "__main__":
    sys.exit(main())
