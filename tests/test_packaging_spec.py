"""Tests for standalone PyInstaller packaging specification."""

import ast
from pathlib import Path


def test_packaging_spec_configuration():
    spec_path = Path("audio_editor.spec")
    assert spec_path.is_file(), "audio_editor.spec must exist at repository root"
    content = spec_path.read_text(encoding="utf-8")

    # Syntax check: spec file is valid Python
    ast.parse(content)

    # Core entry point and requirements
    assert "app.py" in content
    assert "vgmstream" in content
    assert "av" in content
    assert "pygame" in content
    assert "PySide6" in content

    # GUI window configuration
    assert "console=False" in content or "console = False" in content
