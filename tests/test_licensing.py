"""Licensing and Third-Party Compliance Tests."""

from pathlib import Path


def test_third_party_licenses_complete():
    lic_file = Path("THIRD_PARTY_LICENSES.md")
    assert lic_file.is_file(), "THIRD_PARTY_LICENSES.md must exist at repository root"
    content = lic_file.read_text(encoding="utf-8")

    # Core project attribution
    assert "PyWarscape Sound" in content
    assert "MIT License" in content

    # Third-party components
    assert "vgmstream" in content
    assert "PyAV" in content
    assert "FFmpeg" in content
    assert "PySide6" in content
    assert "RPFM" in content
    assert "Pygame" in content or "pygame-ce" in content

    # License types
    assert "LGPL" in content

    # Compliance explanation
    assert "Dynamic Linking" in content or "dynamic linking" in content
    assert "External Process" in content or "external process" in content or "subprocess" in content
