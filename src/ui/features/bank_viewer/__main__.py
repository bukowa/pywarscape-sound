"""Standalone developer harness and direct CLI runner for SoundBank Viewer."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from src.ui.features.bank_viewer.store import BankViewerStore
from src.ui.features.bank_viewer.view import BankViewerView
from src.ui.log import setup_logging
from src.ui.theme import apply_theme
from src.workspace.storage import ProjectStorage


def main() -> int:
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("PyWarscape Sound - SoundBank Viewer")
    apply_theme(app)

    store = BankViewerStore()

    if len(sys.argv) > 1:
        target = Path(sys.argv[1]).resolve()
        if target.is_dir() and (target / "project.json").is_file():
            project = ProjectStorage.open_project(target)
            store.load_project(project)
        elif target.is_file() and target.suffix.lower() == ".bnk":
            store.load_bank_file(target)

    view = BankViewerView(store)
    view.resize(1400, 850)
    view.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
