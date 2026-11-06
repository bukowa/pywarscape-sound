"""AI-assisted development disclaimer dialog and project contribution guide."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.ui.theme import (
    BTN_STYLE_PRIMARY,
    BTN_STYLE_SECONDARY,
    CHECKBOX_STYLE,
    COLOR_BG_BASE,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_BRIGHT,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
)
from src.workspace.paths import get_app_root

GITHUB_REPO_URL = "https://github.com/bukowa/pywarscape-sound"


class DisclaimerDialog(QDialog):
    """Modal dialog displaying AI-assisted development notice and community links."""

    def __init__(self, parent: QWidget | None = None, is_first_run: bool = True) -> None:
        super().__init__(parent)
        self.is_first_run = is_first_run

        title = (
            "Welcome to PyWarscape Sound"
            if is_first_run
            else "About PyWarscape Sound & AI Disclaimer"
        )
        self.setWindowTitle(title)
        self.setMinimumWidth(640)
        self.resize(680, 480)
        self.setModal(True)

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)

        # Header Card
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_PANEL}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 8px; padding: 14px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(10)

        title_label = QLabel("PyWarscape Sound")
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet(f"QLabel {{ color: {COLOR_TEXT_BRIGHT}; }}")
        card_layout.addWidget(title_label)

        sub_label = QLabel("Modding Toolkit & SoundBank Editor for Total War: Attila & Rome II")
        sub_label.setStyleSheet(f"QLabel {{ color: {COLOR_TEXT_MUTED}; font-size: 11px; }}")
        card_layout.addWidget(sub_label)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"QFrame {{ border-top: 1px solid {COLOR_BORDER}; }}")
        card_layout.addWidget(line)

        # Body explanation text
        body_label = QLabel()
        body_label.setWordWrap(True)
        body_label.setStyleSheet(
            f"QLabel {{ color: {COLOR_TEXT_PRIMARY}; font-size: 12px; line-height: 1.4; }}"
        )
        body_text = (
            f"<p style='color: {COLOR_TEXT_PRIMARY}; font-size: 13px; font-weight: bold; margin-bottom: 6px;'>"
            "AI-Assisted Development Notice & Experimental Status"
            "</p>"
            f"<p style='color: {COLOR_TEXT_SECONDARY}; margin-bottom: 12px;'>"
            "PyWarscape Sound was created with the assistance of AI coding agents. While backed by "
            "an automated test suite (>900 unit and integration tests, bit-exact round-trip verification across "
            "all vanilla SoundBanks), <b>there may still be edge-case bugs</b> in complex scenarios."
            "</p>"
            f"<p style='color: {COLOR_TEXT_PRIMARY}; font-size: 13px; font-weight: bold; margin-bottom: 6px;'>"
            "Community Collaboration & Bug Reports"
            "</p>"
            f"<ul style='color: {COLOR_TEXT_SECONDARY}; margin-top: 0px; margin-bottom: 12px; padding-left: 20px;'>"
            "<li><b>Found an issue or unexpected crash?</b> Please file an issue on GitHub with details so we can fix it.</li>"
            "<li><b>Want to add features or support more games?</b> Clone the repository and contribute! You can easily "
            "pair with AI coding agents (or use human ingenuity) to improve it. The codebase was intentionally designed with strict "
            "architecture guards and specification documents to make human-agent collaboration smooth and reliable.</li>"
            "</ul>"
            f"<p style='color: {COLOR_TEXT_MUTED}; font-size: 11px;'>"
            "Happy modding and sound designing!"
            "</p>"
        )
        body_label.setText(body_text)
        card_layout.addWidget(body_label)
        main_layout.addWidget(card)

        # First-run Checkbox
        self.chk_dont_show = QCheckBox("Do not show this message on startup again")
        self.chk_dont_show.setStyleSheet(CHECKBOX_STYLE)
        self.chk_dont_show.setChecked(True)
        if not self.is_first_run:
            self.chk_dont_show.setVisible(False)
        main_layout.addWidget(self.chk_dont_show)

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_github = QPushButton("Open GitHub Repository")
        self.btn_github.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_github.clicked.connect(self._open_github)
        btn_layout.addWidget(self.btn_github)

        btn_layout.addStretch()

        btn_text = "Got it, let's explore!" if self.is_first_run else "Close"
        self.btn_continue = QPushButton(btn_text)
        self.btn_continue.setStyleSheet(BTN_STYLE_PRIMARY)
        self.btn_continue.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_continue)

        main_layout.addLayout(btn_layout)

    def _open_github(self) -> None:
        QDesktopServices.openUrl(QUrl(GITHUB_REPO_URL))

    @property
    def dont_show_again(self) -> bool:
        """Returns True if user checked 'do not show again'."""
        return self.chk_dont_show.isChecked()


class ChangelogDialog(QDialog):
    """Modal dialog presenting the project CHANGELOG.md."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("PyWarscape Sound - Changelog")
        self.setMinimumWidth(700)
        self.resize(750, 520)
        self.setModal(True)

        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.browser = QTextBrowser()
        self.browser.setStyleSheet(
            f"QTextBrowser {{ background-color: {COLOR_BG_BASE}; color: {COLOR_TEXT_PRIMARY}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 6px; padding: 12px; }}"
        )

        changelog_path = get_app_root() / "CHANGELOG.md"
        if changelog_path.is_file():
            try:
                content = changelog_path.read_text(encoding="utf-8")
                self.browser.setMarkdown(content)
            except OSError:
                self.browser.setPlainText("Failed to load CHANGELOG.md.")
        else:
            self.browser.setPlainText("CHANGELOG.md not found.")

        layout.addWidget(self.browser)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_close = QPushButton("Close")
        btn_close.setStyleSheet(BTN_STYLE_PRIMARY)
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)
