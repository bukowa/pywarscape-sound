# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller packaging specification for Audio Editor.

Configures standalone desktop executable bundling for Audio Editor,
including PySide6 Qt runtime, in-memory audio transcoding via PyAV,
and the tracked vgmstream-cli audio preview helper.
"""

from pathlib import Path

block_cipher = None

# Bundle tracked vgmstream preview helper into distribution
vgmstream_binaries = []
vgmstream_dir = Path("tools/vgmstream")
if vgmstream_dir.is_dir():
    for f in vgmstream_dir.glob("*"):
        if f.is_file():
            # Bundle into distribution layout under vgmstream/
            vgmstream_binaries.append((str(f), "vgmstream"))

a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=vgmstream_binaries,
    datas=[
        ("THIRD_PARTY_LICENSES.md", "."),
        ("CHANGELOG.md", "."),
    ],
    hiddenimports=[
        "av",
        "pygame",
        "PySide6",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "src.compiler.converter",
        "src.compiler.audio_modifiers",
        "src.deps.player",
        "src.workspace.paths",
        "src.workspace.project",
        "src.bnk.bank",
        "src.engine.audio_export",
        "src.ui.shell.pack_settings_dialog",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PyWarscapeSound",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PyWarscapeSound",
)
