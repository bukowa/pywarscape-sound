"""Tests for pure-python Steam game detection and directory validation."""

from pathlib import Path
from unittest.mock import patch

from src.workspace.game import GameType
from src.workspace.game_detector import GameDetector


def test_validate_game_dir_nonexistent(tmp_path: Path):
    valid, msg = GameDetector.validate_game_dir(GameType.ATTILA, tmp_path / "does_not_exist")
    assert not valid
    assert "not exist" in msg.lower()


def test_validate_game_dir_empty_path():
    valid, msg = GameDetector.validate_game_dir(GameType.ATTILA, "")
    assert not valid
    assert "not exist" in msg.lower() or "empty" in msg.lower()


def test_validate_game_dir_missing_exe(tmp_path: Path):
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    valid, msg = GameDetector.validate_game_dir(GameType.ATTILA, game_dir)
    assert not valid
    assert "executable" in msg.lower()


def test_validate_game_dir_missing_data(tmp_path: Path):
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    (game_dir / "Attila.exe").write_text("dummy", encoding="utf-8")
    valid, msg = GameDetector.validate_game_dir(GameType.ATTILA, game_dir)
    assert not valid
    assert "data" in msg.lower()


def test_validate_game_dir_no_packs(tmp_path: Path):
    game_dir = tmp_path / "game"
    (game_dir / "data").mkdir(parents=True)
    (game_dir / "Attila.exe").write_text("dummy", encoding="utf-8")
    valid, msg = GameDetector.validate_game_dir(GameType.ATTILA, game_dir)
    assert not valid
    assert "pack" in msg.lower()


def test_validate_game_dir_valid_attila(tmp_path: Path):
    game_dir = tmp_path / "game"
    (game_dir / "data").mkdir(parents=True)
    (game_dir / "Attila.exe").write_text("dummy", encoding="utf-8")
    (game_dir / "data" / "sound.pack").write_bytes(b"PFH4" + b"\x00" * 20)
    valid, msg = GameDetector.validate_game_dir(GameType.ATTILA, game_dir)
    assert valid
    assert "valid" in msg.lower()


def test_validate_game_dir_valid_rome2(tmp_path: Path):
    game_dir = tmp_path / "game_rome2"
    (game_dir / "data").mkdir(parents=True)
    (game_dir / "Rome2.exe").write_text("dummy", encoding="utf-8")
    (game_dir / "data" / "sound.pack").write_bytes(b"PFH4" + b"\x00" * 20)
    valid, msg = GameDetector.validate_game_dir(GameType.ROME_2, game_dir)
    assert valid
    assert "valid" in msg.lower()


def test_parse_steam_libraryfolders(tmp_path: Path):
    vdf = tmp_path / "libraryfolders.vdf"
    vdf.write_text(
        r"""
        "libraryfolders"
        {
            "0"
            {
                "path"      "C:\\Program Files (x86)\\Steam"
            }
            "1"
            {
                "path"      "D:\\Games\\SteamLibrary"
            }
        }
        """,
        encoding="utf-8",
    )
    paths = GameDetector.parse_steam_libraryfolders(vdf)
    assert len(paths) == 2
    assert Path("C:/Program Files (x86)/Steam") in paths
    assert Path("D:/Games/SteamLibrary") in paths


def test_parse_steam_libraryfolders_corrupted(tmp_path: Path):
    vdf = tmp_path / "corrupted.vdf"
    vdf.write_text("invalid contents {}}", encoding="utf-8")
    paths = GameDetector.parse_steam_libraryfolders(vdf)
    assert paths == []


def test_parse_steam_libraryfolders_nonexistent(tmp_path: Path):
    paths = GameDetector.parse_steam_libraryfolders(tmp_path / "missing.vdf")
    assert paths == []


def test_detect_game_install_from_mocked_registry(tmp_path: Path):
    game_dir = tmp_path / "AttilaSteam"
    (game_dir / "data").mkdir(parents=True)
    (game_dir / "Attila.exe").write_text("dummy", encoding="utf-8")
    (game_dir / "data" / "sound.pack").write_bytes(b"PFH4" + b"\x00" * 20)

    with patch.object(GameDetector, "_query_registry_install_dir", return_value=game_dir):
        detected = GameDetector.detect_game_install(GameType.ATTILA)
        assert detected == game_dir


def test_detect_game_install_from_steam_library(tmp_path: Path):
    steam_root = tmp_path / "Steam"
    lib_dir = tmp_path / "SteamLibrary"
    vdf_file = steam_root / "steamapps" / "libraryfolders.vdf"
    vdf_file.parent.mkdir(parents=True)

    vdf_file.write_text(
        f'''
        "libraryfolders"
        {{
            "0"
            {{
                "path"      "{str(lib_dir).replace("\\", "\\\\")}"
            }}
        }}
        ''',
        encoding="utf-8",
    )

    game_dir = lib_dir / "steamapps" / "common" / "Total War Attila"
    (game_dir / "data").mkdir(parents=True)
    (game_dir / "Attila.exe").write_text("dummy", encoding="utf-8")
    (game_dir / "data" / "sound.pack").write_bytes(b"PFH4" + b"\x00" * 20)

    with (
        patch.object(GameDetector, "_query_registry_install_dir", return_value=None),
        patch.object(GameDetector, "_get_steam_root_candidates", return_value=[steam_root]),
    ):
        detected = GameDetector.detect_game_install(GameType.ATTILA)
        assert detected == game_dir


def test_detect_game_install_not_found():
    with (
        patch.object(GameDetector, "_query_registry_install_dir", return_value=None),
        patch.object(GameDetector, "_get_steam_root_candidates", return_value=[]),
        patch.object(GameDetector, "_get_default_game_candidates", return_value=[]),
    ):
        detected = GameDetector.detect_game_install(GameType.ATTILA)
        assert detected is None
