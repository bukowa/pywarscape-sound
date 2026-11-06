"""Live integration test invoking Total War: Attila or Rome II with a compiled mod pack.

Tests:
1. Mod pack compilation with ExternalFileSource audio transcoding and SilentStubSource muting.
2. Direct deployment to the live game's data/ folder as PT_MOD (type 3).
3. Live user.script.txt registration.
4. Total War: Attila / Rome II engine startup and live VFS pack mounting with zero crash reports.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.test_live_game import run_live_test
from src.workspace.game import GameType
from src.workspace.game_detector import GameDetector

_LIVE_ATTILA = GameDetector.detect_game_install(GameType.ATTILA)
if _LIVE_ATTILA is None or not (_LIVE_ATTILA / "Attila.exe").is_file():
    _env_dir = os.environ.get("ATTILA_GAME_DIR")
    if _env_dir and (Path(_env_dir) / "Attila.exe").is_file():
        _LIVE_ATTILA = Path(_env_dir)

_LIVE_ROME2 = GameDetector.detect_game_install(GameType.ROME_2)
if _LIVE_ROME2 is None or not (_LIVE_ROME2 / "Rome2.exe").is_file():
    _env_r2 = os.environ.get("ROME2_GAME_DIR")
    if _env_r2 and (Path(_env_r2) / "Rome2.exe").is_file():
        _LIVE_ROME2 = Path(_env_r2)


def _can_write_game_dir(path: Path | None) -> bool:
    if path is None:
        return False
    probe = path / "data" / ".write_probe"
    try:
        probe.touch()
        probe.unlink()
        return True
    except OSError:
        return False


@pytest.mark.live
@pytest.mark.assets
@pytest.mark.skipif(
    _LIVE_ATTILA is None
    or not (_LIVE_ATTILA / "Attila.exe").is_file()
    or not _can_write_game_dir(_LIVE_ATTILA),
    reason="Total War: Attila is not installed or data directory is not writable",
)
def test_live_attila_game_startup_with_modified_pack():
    """Live test: Compiles a real mod pack with external audio and muting,
    mounts it into Total War: Attila via user.script.txt, boots Attila.exe,
    and proves the game runs without crashing.
    """
    passed = run_live_test(duration_sec=10.0, dry_run=False, keep_pack=False, game=GameType.ATTILA)
    assert passed, "Live game integration test failed for Attila"


@pytest.mark.live
@pytest.mark.assets
@pytest.mark.skipif(
    _LIVE_ROME2 is None
    or not (_LIVE_ROME2 / "Rome2.exe").is_file()
    or not _can_write_game_dir(_LIVE_ROME2),
    reason="Total War: Rome II is not installed or data directory is not writable",
)
def test_live_rome2_game_startup_with_modified_pack():
    """Live test: Compiles a real mod pack with external audio and muting,
    mounts it into Total War: Rome II via user.script.txt, boots Rome2.exe,
    and proves the game runs without crashing.
    """
    passed = run_live_test(duration_sec=10.0, dry_run=False, keep_pack=False, game=GameType.ROME_2)
    assert passed, "Live game integration test failed for Rome II"


@pytest.mark.assets
def test_live_game_dry_run_attila():
    """Dry run live pack compilation and AST roundtrip for Attila."""
    cache_bnk = Path(".cache/attila/audio/battle_ui.bnk")
    if not cache_bnk.is_file():
        pytest.skip("Attila audio cache not found")
    passed = run_live_test(duration_sec=1.0, dry_run=True, game=GameType.ATTILA)
    assert passed, "Dry run live pack test failed for Attila"


@pytest.mark.assets
def test_live_game_dry_run_rome2():
    """Dry run live pack compilation and AST roundtrip for Rome II."""
    cache_bnk = Path(".cache/rome_2/audio/battle_advice.bnk")
    if not cache_bnk.is_file():
        pytest.skip("Rome II audio cache not found")
    passed = run_live_test(duration_sec=1.0, dry_run=True, game=GameType.ROME_2)
    assert passed, "Dry run live pack test failed for Rome II"
