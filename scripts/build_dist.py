# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pyinstaller>=6.0.0",
# ]
# ///
"""Standalone packaging script for Audio Editor.

Automates PyInstaller build for onedir distribution, verifies required
binaries (including vgmstream-cli), and packages a portable .zip release archive.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("build_dist")

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_FILE = REPO_ROOT / "audio_editor.spec"
TOOLS_VGMSTREAM = REPO_ROOT / "tools" / "vgmstream"
DEFAULT_DIST_DIR = REPO_ROOT / "dist"
DEFAULT_BUILD_DIR = REPO_ROOT / "build"


def clean_build_artifacts(dist_dir: Path, build_dir: Path) -> None:
    """Removes intermediate build and dist artifacts."""
    logger.info("Cleaning previous build artifacts...")
    app_dist = dist_dir / "PyWarscapeSound"
    if app_dist.exists():
        shutil.rmtree(app_dist, ignore_errors=True)
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)


def run_pyinstaller(spec_file: Path) -> None:
    """Executes PyInstaller with the spec file."""
    if not spec_file.is_file():
        raise FileNotFoundError(f"Spec file not found: {spec_file}")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(spec_file),
        "--clean",
        "--noconfirm",
    ]
    logger.info("Running PyInstaller: %s", " ".join(cmd))
    res = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if res.returncode != 0:
        raise RuntimeError(f"PyInstaller build failed with exit code {res.returncode}")


def verify_and_sync_vgmstream(app_dir: Path, tools_vgmstream: Path) -> None:
    """Ensures vgmstream runtime binaries exist inside the application distribution layout."""
    target_vgmstream = app_dir / "vgmstream"
    target_vgmstream.mkdir(parents=True, exist_ok=True)

    if tools_vgmstream.is_dir():
        for src_file in tools_vgmstream.glob("*"):
            if src_file.is_file():
                dest_file = target_vgmstream / src_file.name
                if not dest_file.exists():
                    logger.info("Syncing binary: %s -> %s", src_file.name, dest_file)
                    shutil.copy2(src_file, dest_file)

    exe_names = ("vgmstream-cli.exe", "vgmstream-cli")
    found = any((target_vgmstream / name).is_file() for name in exe_names)
    if not found:
        logger.warning(
            "vgmstream-cli executable not found in %s! Audio auditioning may require PATH fallback.",
            target_vgmstream,
        )


def verify_distribution(app_dir: Path) -> None:
    """Verifies that the compiled application directory is complete and valid."""
    exe_path = app_dir / "PyWarscapeSound.exe"
    if not exe_path.is_file():
        # Fallback check for linux/mac test environments
        exe_path = app_dir / "PyWarscapeSound"
        if not exe_path.is_file():
            raise FileNotFoundError(f"Application executable not found in {app_dir}")

    logger.info("Distribution executable verified: %s", exe_path)


def package_zip(app_dir: Path, zip_path: Path) -> Path:
    """Compresses the application directory into a release zip archive."""
    logger.info("Creating release zip archive at %s...", zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in app_dir.rglob("*"):
            arcname = item.relative_to(app_dir.parent)
            zf.write(item, arcname)

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    logger.info("Archive created successfully: %s (%.1f MB)", zip_path.name, size_mb)
    return zip_path


def build_standalone(
    version: str = "1.0.0",
    skip_build: bool = False,
    dist_dir: Path = DEFAULT_DIST_DIR,
    build_dir: Path = DEFAULT_BUILD_DIR,
) -> Path:
    """Main build orchestrator returning path to the packaged release zip."""
    app_dir = dist_dir / "PyWarscapeSound"

    if not skip_build:
        clean_build_artifacts(dist_dir, build_dir)
        run_pyinstaller(SPEC_FILE)

    verify_and_sync_vgmstream(app_dir, TOOLS_VGMSTREAM)
    verify_distribution(app_dir)

    zip_filename = f"PyWarscapeSound-v{version}-windows-x64.zip"
    zip_path = dist_dir / zip_filename
    return package_zip(app_dir, zip_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and package standalone PyWarscape Sound.")
    parser.add_argument(
        "--version",
        default="1.0.0",
        help="Release version string (default: 1.0.0)",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip PyInstaller build and package existing dist/PyWarscapeSound directory",
    )
    args = parser.parse_args()

    try:
        out_zip = build_standalone(version=args.version, skip_build=args.skip_build)
        logger.info("Build completed successfully: %s", out_zip)
        return 0
    except Exception as exc:
        logger.error("Build failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
