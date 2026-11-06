import zipfile
from pathlib import Path

import pytest

from scripts.build_dist import (
    build_standalone,
    clean_build_artifacts,
    package_zip,
    verify_and_sync_vgmstream,
    verify_distribution,
)


def test_clean_build_artifacts(tmp_path: Path):
    dist_dir = tmp_path / "dist"
    build_dir = tmp_path / "build"

    app_dir = dist_dir / "PyWarscapeSound"
    app_dir.mkdir(parents=True)
    (app_dir / "dummy.txt").write_text("hello")

    build_dir.mkdir(parents=True)
    (build_dir / "temp.obj").write_text("data")

    clean_build_artifacts(dist_dir, build_dir)

    assert not app_dir.exists()
    assert not build_dir.exists()


def test_verify_and_sync_vgmstream(tmp_path: Path):
    app_dir = tmp_path / "PyWarscapeSound"
    tools_dir = tmp_path / "tools" / "vgmstream"
    tools_dir.mkdir(parents=True)

    dummy_cli = tools_dir / "vgmstream-cli.exe"
    dummy_cli.write_bytes(b"dummy_exe_bytes")

    verify_and_sync_vgmstream(app_dir, tools_dir)

    synced_cli = app_dir / "vgmstream" / "vgmstream-cli.exe"
    assert synced_cli.is_file()
    assert synced_cli.read_bytes() == b"dummy_exe_bytes"


def test_verify_distribution(tmp_path: Path):
    app_dir = tmp_path / "PyWarscapeSound"
    app_dir.mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="Application executable not found"):
        verify_distribution(app_dir)

    (app_dir / "PyWarscapeSound.exe").write_bytes(b"MZ_DUMMY_EXE")
    # Should not raise
    verify_distribution(app_dir)


def test_package_zip(tmp_path: Path):
    app_dir = tmp_path / "dist" / "PyWarscapeSound"
    app_dir.mkdir(parents=True)
    (app_dir / "PyWarscapeSound.exe").write_bytes(b"EXE_CONTENT")
    sub_dir = app_dir / "data"
    sub_dir.mkdir()
    (sub_dir / "sample.txt").write_text("test content")

    zip_path = tmp_path / "dist" / "PyWarscapeSound-v1.0.0.zip"
    result = package_zip(app_dir, zip_path)

    assert result == zip_path
    assert zip_path.is_file()

    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        assert "PyWarscapeSound/PyWarscapeSound.exe" in [n.replace("\\", "/") for n in namelist]
        assert "PyWarscapeSound/data/sample.txt" in [n.replace("\\", "/") for n in namelist]


def test_build_standalone_with_skip_build(tmp_path: Path):
    dist_dir = tmp_path / "dist"
    app_dir = dist_dir / "PyWarscapeSound"
    app_dir.mkdir(parents=True)
    (app_dir / "PyWarscapeSound.exe").write_bytes(b"EXE_CONTENT")

    tools_dir = tmp_path / "tools" / "vgmstream"
    tools_dir.mkdir(parents=True)
    (tools_dir / "vgmstream-cli.exe").write_bytes(b"VGM_CONTENT")

    zip_path = build_standalone(
        version="1.0.0-test",
        skip_build=True,
        dist_dir=dist_dir,
        build_dir=tmp_path / "build",
    )

    assert zip_path.is_file()
    assert zip_path.name == "PyWarscapeSound-v1.0.0-test-windows-x64.zip"
