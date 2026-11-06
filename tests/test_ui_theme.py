"""Tests for centralized v3 UI theme constants and application palette."""

from PySide6.QtGui import QPalette

from src.ui.theme import (
    BTN_STYLE_DANGER,
    BTN_STYLE_PRIMARY,
    BTN_STYLE_SECONDARY,
    CHECKBOX_STYLE,
    COLOR_ACCENT,
    COLOR_BG_BASE,
    COLOR_BG_DISABLED,
    COLOR_BG_INPUT,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COMBO_STYLE,
    INPUT_STYLE,
    PROGRESS_BAR_STYLE,
    apply_theme,
)


def test_theme_color_constants():
    """Verify all semantic color constants are properly defined hex color strings."""
    expected_colors = {
        COLOR_BG_BASE: "#161719",
        COLOR_BG_PANEL: "#1F2125",
        COLOR_BG_INPUT: "#131416",
        COLOR_BG_DISABLED: "#26282B",
        COLOR_TEXT_PRIMARY: "#F0F2F5",
        COLOR_TEXT_SECONDARY: "#C5C8D0",
        COLOR_TEXT_MUTED: "#7D838F",
        COLOR_BORDER: "#3E4249",
        COLOR_ACCENT: "#264F78",
    }
    for color, expected in expected_colors.items():
        assert isinstance(color, str)
        assert color.startswith("#")
        assert color.upper() == expected.upper()


def test_button_and_input_styles():
    """Verify button and input stylesheets conform to specifications."""
    # BTN_STYLE_PRIMARY
    assert "QPushButton" in BTN_STYLE_PRIMARY
    assert "#264F78" in BTN_STYLE_PRIMARY
    assert "#FFFFFF" in BTN_STYLE_PRIMARY
    assert "#3771A8" in BTN_STYLE_PRIMARY
    assert "border-radius: 4px" in BTN_STYLE_PRIMARY
    assert ":hover" in BTN_STYLE_PRIMARY
    assert ":disabled" in BTN_STYLE_PRIMARY

    # BTN_STYLE_SECONDARY
    assert "QPushButton" in BTN_STYLE_SECONDARY
    assert "#2E3138" in BTN_STYLE_SECONDARY
    assert "#F0F2F5" in BTN_STYLE_SECONDARY
    assert "#3E4249" in BTN_STYLE_SECONDARY
    assert "border-radius: 4px" in BTN_STYLE_SECONDARY
    assert ":hover" in BTN_STYLE_SECONDARY
    assert ":disabled" in BTN_STYLE_SECONDARY

    # BTN_STYLE_DANGER
    assert "QPushButton" in BTN_STYLE_DANGER
    assert "#2E3138" in BTN_STYLE_DANGER
    assert "#F2B8B5" in BTN_STYLE_DANGER
    assert "#6E3B3B" in BTN_STYLE_DANGER
    assert "border-radius: 4px" in BTN_STYLE_DANGER
    assert ":hover" in BTN_STYLE_DANGER
    assert ":disabled" in BTN_STYLE_DANGER

    # INPUT_STYLE
    assert "QLineEdit" in INPUT_STYLE
    assert COLOR_BG_INPUT in INPUT_STYLE
    assert COLOR_TEXT_PRIMARY in INPUT_STYLE
    assert COLOR_BORDER in INPUT_STYLE
    assert "border-radius: 4px" in INPUT_STYLE

    # COMBO_STYLE
    assert "QComboBox" in COMBO_STYLE
    assert COLOR_BG_INPUT in COMBO_STYLE
    assert COLOR_TEXT_PRIMARY in COMBO_STYLE
    assert COLOR_BORDER in COMBO_STYLE
    assert "border-radius: 4px" in COMBO_STYLE
    assert COLOR_BG_PANEL in COMBO_STYLE

    # PROGRESS_BAR_STYLE
    assert "QProgressBar" in PROGRESS_BAR_STYLE
    assert COLOR_ACCENT in PROGRESS_BAR_STYLE

    # CHECKBOX_STYLE
    assert "QCheckBox" in CHECKBOX_STYLE
    assert "indicator" in CHECKBOX_STYLE
    assert "checkmark.svg" in CHECKBOX_STYLE


def test_apply_theme_execution(qapp):
    """Verify apply_theme sets Fusion style, dark QPalette, and application font."""
    app = qapp
    apply_theme(app)

    # Fusion style
    assert app.style().objectName().lower() == "fusion"

    # Dark palette checks
    palette = app.palette()
    assert palette.color(QPalette.ColorRole.Window).name().upper() == "#161719"
    assert palette.color(QPalette.ColorRole.WindowText).name().upper() == "#F0F2F5"
    assert palette.color(QPalette.ColorRole.Base).name().upper() == "#161719"
    assert palette.color(QPalette.ColorRole.AlternateBase).name().upper() == "#1F2125"

    # Application font check
    font = app.font()
    assert font is not None


def test_checkbox_rendering_shows_checkmark(qapp):
    """Verify QCheckBox with CHECKBOX_STYLE renders a visible checkmark icon when checked."""
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QCheckBox

    _app = qapp

    cb = QCheckBox("Test Checkmark")
    cb.setStyleSheet(CHECKBOX_STYLE)
    cb.setChecked(True)
    cb.resize(200, 30)

    pix = QPixmap(200, 30)
    cb.render(pix)
    img = pix.toImage()

    # Verify that white pixels exist in the indicator region (x: 0..20, y: 0..30)
    has_white_checkmark = any(
        img.pixelColor(x, y).name().upper() == "#FFFFFF" for x in range(20) for y in range(30)
    )
    assert has_white_checkmark, "CHECKBOX_STYLE did not render a white checkmark icon"
