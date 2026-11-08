"""Unit and headless UI tests for AI disclaimer dialog and changelog viewer."""

import json
from pathlib import Path

from src.ui.shell.disclaimer_dialog import (
    GITHUB_REPO_URL,
    ChangelogDialog,
    DisclaimerDialog,
)
from src.ui.shell.store import ShellStore
from src.ui.shell.view import MainWindow


def test_changelog_file_exists():
    changelog = Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    assert changelog.is_file(), "CHANGELOG.md must exist in repository root"
    content = changelog.read_text(encoding="utf-8")
    assert "[0.2.0]" in content
    assert "[0.1.0]" in content
    assert "Multi-Game SoundBank" in content


def test_disclaimer_dialog_first_run(qapp):
    dialog = DisclaimerDialog(is_first_run=True)
    assert dialog.is_first_run is True
    assert dialog.windowTitle() == "Welcome to PyWarscape Sound"
    assert not dialog.chk_dont_show.isHidden()
    assert dialog.chk_dont_show.isChecked()
    assert dialog.dont_show_again is True
    assert dialog.btn_continue.text() == "Got it, let's explore!"
    assert GITHUB_REPO_URL in dialog.btn_github.text() or "GitHub" in dialog.btn_github.text()
    dialog.close()


def test_disclaimer_dialog_about_mode(qapp):
    dialog = DisclaimerDialog(is_first_run=False)
    assert dialog.is_first_run is False
    assert "About PyWarscape Sound" in dialog.windowTitle()
    assert dialog.chk_dont_show.isHidden()
    assert dialog.btn_continue.text() == "Close"
    dialog.close()


def test_changelog_dialog_renders(qapp):
    dialog = ChangelogDialog()
    assert dialog.windowTitle() == "PyWarscape Sound - Changelog"
    text = dialog.browser.toPlainText()
    assert "[0.2.0]" in text
    assert "[0.1.0]" in text
    dialog.close()


def test_main_window_disclaimer_workflow(qapp, tmp_path: Path):
    settings_file = tmp_path / "settings.json"
    store = ShellStore()
    window = MainWindow(store, settings_file=settings_file)

    # 1. First run: settings file doesn't exist -> should show disclaimer
    assert window.should_show_disclaimer() is True

    # 2. Acknowledge disclaimer
    window._set_disclaimer_acknowledged(True)
    assert settings_file.is_file()
    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert saved.get("disclaimer_acknowledged") is True

    # 3. Subsequent check -> should not show
    assert window.should_show_disclaimer() is False

    # 4. Help menu actions exist
    assert hasattr(window, "act_disclaimer")
    assert hasattr(window, "act_changelog")
    assert hasattr(window, "act_github")
    assert window.act_disclaimer.text() == "AI Disclaimer & About..."
    assert window.act_changelog.text() == "Changelog..."
    assert window.act_github.text() == "GitHub Repository..."

    window.close()
