"""High-contrast dark theme styling and centralized design tokens."""

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QIcon, QPalette
from PySide6.QtWidgets import QApplication

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_CHECKMARK_SVG = (_ASSETS_DIR / "checkmark.svg").as_posix()

# ----------------------------------------------------------------------
# Centralized Semantic Color Tokens
# ----------------------------------------------------------------------
COLOR_BG_BASE = "#161719"
COLOR_BG_PANEL = "#1F2125"
COLOR_BG_INPUT = "#131416"
COLOR_BG_DISABLED = "#26282B"

COLOR_TEXT_PRIMARY = "#F0F2F5"
COLOR_TEXT_SECONDARY = "#C5C8D0"
COLOR_TEXT_MUTED = "#7D838F"
COLOR_TEXT_BRIGHT = "#FFFFFF"

COLOR_BG_TAB_HOVER = "#22252B"

COLOR_BORDER = "#3E4249"
COLOR_ACCENT = "#264F78"
COLOR_SUCCESS = "#4E9A51"
COLOR_WARNING = "#DDB23B"
COLOR_STATUS_MODIFIED = "#E5C07B"

# ----------------------------------------------------------------------
# Button Stylesheets
# ----------------------------------------------------------------------
BTN_STYLE_PRIMARY = (
    "QPushButton { "
    "background-color: #264F78; "
    "color: #FFFFFF; "
    "border: 1px solid #3771A8; "
    "border-radius: 4px; "
    "padding: 6px 14px; "
    "font-weight: 600; "
    "min-height: 24px; "
    "min-width: 0px; "
    "} "
    "QPushButton:hover { "
    "background-color: #2F6294; "
    "} "
    "QPushButton:disabled { "
    "background-color: #26282B; "
    "color: #7D838F; "
    "border: 1px solid #36383E; "
    "}"
)

BTN_STYLE_SECONDARY = (
    "QPushButton { "
    "background-color: #2E3138; "
    "color: #F0F2F5; "
    "border: 1px solid #3E4249; "
    "border-radius: 4px; "
    "padding: 6px 14px; "
    "min-height: 24px; "
    "min-width: 0px; "
    "} "
    "QPushButton:hover { "
    "background-color: #383C45; "
    "} "
    "QPushButton:disabled { "
    "background-color: #26282B; "
    "color: #7D838F; "
    "border: 1px solid #36383E; "
    "}"
)

BTN_STYLE_PRESET = (
    "QPushButton { "
    "background-color: #2E3138; "
    "color: #F0F2F5; "
    "border: 1px solid #3E4249; "
    "border-radius: 3px; "
    "padding: 2px 6px; "
    "font-size: 10px; "
    "min-height: 20px; "
    "} "
    "QPushButton:hover { "
    "background-color: #383C45; "
    "}"
)

BTN_STYLE_DANGER = (
    "QPushButton { "
    "background-color: #2E3138; "
    "color: #F2B8B5; "
    "border: 1px solid #6E3B3B; "
    "border-radius: 4px; "
    "padding: 6px 14px; "
    "min-height: 24px; "
    "min-width: 0px; "
    "} "
    "QPushButton:hover { "
    "background-color: #4A2828; "
    "color: #FFFFFF; "
    "} "
    "QPushButton:disabled { "
    "background-color: #26282B; "
    "color: #7D838F; "
    "border: 1px solid #36383E; "
    "}"
)

# ----------------------------------------------------------------------
# Input Stylesheets
# ----------------------------------------------------------------------
INPUT_STYLE = (
    f"QLineEdit {{ "
    f"background-color: {COLOR_BG_INPUT}; "
    f"color: {COLOR_TEXT_PRIMARY}; "
    f"border: 1px solid {COLOR_BORDER}; "
    f"border-radius: 4px; "
    f"padding: 6px 10px; "
    f"}} "
    f"QLineEdit:focus {{ "
    f"border: 1px solid {COLOR_ACCENT}; "
    f"background-color: #18191C; "
    f"}}"
)

COMBO_STYLE = (
    f"QComboBox {{ "
    f"background-color: {COLOR_BG_INPUT}; "
    f"color: {COLOR_TEXT_PRIMARY}; "
    f"border: 1px solid {COLOR_BORDER}; "
    f"border-radius: 4px; "
    f"padding: 6px 10px; "
    f"}} "
    f"QComboBox:focus {{ "
    f"border: 1px solid {COLOR_ACCENT}; "
    f"}} "
    f"QComboBox QAbstractItemView {{ "
    f"background-color: {COLOR_BG_PANEL}; "
    f"color: {COLOR_TEXT_PRIMARY}; "
    f"selection-background-color: {COLOR_ACCENT}; "
    f"selection-color: #FFFFFF; "
    f"border: 1px solid {COLOR_BORDER}; "
    f"}}"
)

PROGRESS_BAR_STYLE = (
    f"QProgressBar {{ "
    f"background-color: {COLOR_BG_INPUT}; "
    f"color: {COLOR_TEXT_PRIMARY}; "
    f"border: 1px solid {COLOR_BORDER}; "
    f"border-radius: 4px; "
    f"text-align: center; "
    f"min-height: 18px; "
    f"}} "
    f"QProgressBar::chunk {{ "
    f"background-color: {COLOR_ACCENT}; "
    f"border-radius: 3px; "
    f"}}"
)

CHECKBOX_STYLE = (
    f"QCheckBox {{ "
    f"color: {COLOR_TEXT_PRIMARY}; "
    f"spacing: 8px; "
    f"font-size: 12px; "
    f"}} "
    f"QCheckBox::indicator {{ "
    f"width: 16px; "
    f"height: 16px; "
    f"background-color: {COLOR_BG_INPUT}; "
    f"border: 1px solid {COLOR_BORDER}; "
    f"border-radius: 3px; "
    f"}} "
    f"QCheckBox::indicator:hover {{ "
    f"border: 1px solid {COLOR_ACCENT}; "
    f"}} "
    f"QCheckBox::indicator:checked {{ "
    f"background-color: {COLOR_ACCENT}; "
    f"border: 1px solid #3771A8; "
    f'image: url("{_CHECKMARK_SVG}"); '
    f"}}"
)


# ----------------------------------------------------------------------
# Application Theme Initializer
# ----------------------------------------------------------------------
def apply_theme(app: QApplication) -> None:
    """Applies the Fusion style, dark palette, and default font to the application."""
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLOR_BG_BASE))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLOR_TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLOR_BG_BASE))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLOR_BG_PANEL))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(COLOR_BG_PANEL))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(COLOR_TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLOR_TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.Button, QColor("#2E3138"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLOR_TEXT_PRIMARY))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Link, QColor(COLOR_ACCENT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLOR_ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))

    # Disabled colors
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(COLOR_TEXT_MUTED)
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(COLOR_TEXT_MUTED)
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(COLOR_TEXT_MUTED)
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor(COLOR_BG_DISABLED)
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor(COLOR_BG_DISABLED)
    )

    app.setPalette(palette)

    font = QFont("Segoe UI", 9)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)


def make_transport_icon(
    kind: str,
    color_hex: str = COLOR_TEXT_PRIMARY,
    disabled_hex: str = COLOR_TEXT_MUTED,
    size: int = 14,
) -> "QIcon":
    """Renders high-contrast vector transport icons (play, pause, stop) as crisp QIcons."""
    from PySide6.QtCore import QPoint, QRect, Qt
    from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPixmap, QPolygon

    icon = QIcon()
    for mode, col_hex in ((QIcon.Mode.Normal, color_hex), (QIcon.Mode.Disabled, disabled_hex)):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QBrush(QColor(col_hex)))
        painter.setPen(Qt.PenStyle.NoPen)

        if kind == "play":
            poly = QPolygon(
                [
                    QPoint(int(round(size * 0.25)), int(round(size * 0.18))),
                    QPoint(int(round(size * 0.82)), int(round(size * 0.5))),
                    QPoint(int(round(size * 0.25)), int(round(size * 0.82))),
                ]
            )
            painter.drawPolygon(poly)
        elif kind == "pause":
            w = max(2, int(round(size * 0.22)))
            h = int(round(size * 0.65))
            top = int(round(size * 0.175))
            gap = int(round(size * 0.16))
            x1 = int(round((size - (2 * w + gap)) / 2))
            x2 = x1 + w + gap
            painter.drawRect(QRect(x1, top, w, h))
            painter.drawRect(QRect(x2, top, w, h))
        elif kind == "stop":
            margin = int(round(size * 0.25))
            painter.drawRect(QRect(margin, margin, size - 2 * margin, size - 2 * margin))

        painter.end()
        icon.addPixmap(pixmap, mode)

    return icon


__all__ = [
    "BTN_STYLE_DANGER",
    "BTN_STYLE_PRESET",
    "BTN_STYLE_PRIMARY",
    "BTN_STYLE_SECONDARY",
    "CHECKBOX_STYLE",
    "COLOR_ACCENT",
    "COLOR_BG_BASE",
    "COLOR_BG_DISABLED",
    "COLOR_BG_INPUT",
    "COLOR_BG_PANEL",
    "COLOR_BG_TAB_HOVER",
    "COLOR_BORDER",
    "COLOR_SUCCESS",
    "COLOR_TEXT_BRIGHT",
    "COLOR_TEXT_MUTED",
    "COLOR_TEXT_PRIMARY",
    "COLOR_TEXT_SECONDARY",
    "COLOR_WARNING",
    "COMBO_STYLE",
    "INPUT_STYLE",
    "PROGRESS_BAR_STYLE",
    "apply_theme",
    "make_transport_icon",
]
