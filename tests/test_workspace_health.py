"""Tests for headless mod pack health scanner and AST repair engine."""

from pathlib import Path

import pytest

from src.compiler.pfh4_pack import write_pfh4_movie_pack
from src.workspace.health import (
    IssueSeverity,
    PackHealthScanner,
    RepairStrategyRegistry,
)


def _build_test_bank_with_swapped_track() -> bytes:
    raw_track_hex = (
        "0ba0000000c3e4be0e00010000000100040002ecff9d39ecff9d3900000000000100000000"
        "000000ecff9d390000000000000000000000000000000000000000000000004fc1cb2978c9"
        "114101000000000100000000000000000000030000000000000000000000090000004cfc10"
        "430000000004000000ef6e1143000000000400000000000000000000e88cdd2d000000c000"
        "000100000000000000000000002c010000"
    )
    bkhd = bytes.fromhex("424b484418000000700000000100000000000000000000002b00000000000000")
    hirc_body = bytes.fromhex("01000000") + bytes.fromhex(raw_track_hex)
    hirc = bytes.fromhex("48495243") + len(hirc_body).to_bytes(4, "little") + hirc_body
    return bkhd + hirc


def _build_test_bank_with_corrupt_stid() -> bytes:
    bkhd = bytes.fromhex("424b484418000000700000000100000000000000000000002b00000000000000")
    # STID chunk with embedded null byte in bank name
    stid_body = (
        (1).to_bytes(4, "little")  # ui_type
        + (1).to_bytes(4, "little")  # count
        + (9999).to_bytes(4, "little")  # bank_id
        + (16).to_bytes(1, "little")  # len
        + b"Clean_Bank\x00\x9f\x12\x34\x56\x78"  # 16 bytes with null
    )
    stid = bytes.fromhex("53544944") + len(stid_body).to_bytes(4, "little") + stid_body
    return bkhd + stid


def test_scan_soundbank_detects_swapped_clip_automation():
    # Synthetic soundbank bytes with swapped count 0x00000100 (256) on track 247391427
    bnk_bytes = _build_test_bank_with_swapped_track()

    issues = PackHealthScanner.scan_soundbank("test_music.bnk", bnk_bytes)
    assert len(issues) == 1
    issue = issues[0]
    assert issue.issue_id == "ca_track_clip_auto_swapped"
    assert issue.object_id == 247391427
    assert issue.severity == IssueSeverity.CRITICAL_CRASH
    assert issue.can_autofix is True


def test_repair_bank_normalizes_to_canonical_bytes():
    bnk_bytes = _build_test_bank_with_swapped_track()

    repaired = RepairStrategyRegistry.repair_bank("test_music.bnk", bnk_bytes)
    assert repaired != bnk_bytes
    # Re-scanning repaired bank must produce zero issues
    clean_issues = PackHealthScanner.scan_soundbank("test_music.bnk", repaired)
    assert len(clean_issues) == 0


def test_scan_soundbank_detects_corrupted_stid():
    bnk_bytes = _build_test_bank_with_corrupt_stid()

    issues = PackHealthScanner.scan_soundbank("test_stid.bnk", bnk_bytes)
    assert len(issues) == 1
    issue = issues[0]
    assert issue.issue_id == "stid_corrupted_string"
    assert issue.object_id == 9999
    assert issue.severity == IssueSeverity.WARNING
    assert issue.can_autofix is True

    # Repair should clean the string
    repaired = RepairStrategyRegistry.repair_bank("test_stid.bnk", bnk_bytes)
    clean_issues = PackHealthScanner.scan_soundbank("test_stid.bnk", repaired)
    assert len(clean_issues) == 0


def test_scan_and_repair_corrupted_stid_with_binary_garbage():
    bkhd = bytes.fromhex("424b484418000000700000000100000000000000000000002b00000000000000")
    # Real-world defect pattern: Global_Movies_Loc\xb3~\x93\x1d\x00\x9f
    raw_name_bytes = b"Global_Movies_Loc\xb3~\x93\x1d\x00\x9f"
    stid_body = (
        (1).to_bytes(4, "little")
        + (1).to_bytes(4, "little")
        + (3604709923).to_bytes(4, "little")
        + len(raw_name_bytes).to_bytes(1, "little")
        + raw_name_bytes
    )
    stid = bytes.fromhex("53544944") + len(stid_body).to_bytes(4, "little") + stid_body
    bnk_bytes = bkhd + stid

    issues = PackHealthScanner.scan_soundbank("global_movies.bnk", bnk_bytes)
    assert len(issues) == 1
    issue = issues[0]
    assert issue.issue_id == "stid_corrupted_string"
    assert issue.object_id == 3604709923
    assert (
        issue.fix_description == "Truncate STID bank name to valid clean string 'Global_Movies_Loc'"
    )

    repaired = RepairStrategyRegistry.repair_bank("global_movies.bnk", bnk_bytes)
    from src.bnk.bank import SoundBank

    repaired_sb = SoundBank.from_bytes(repaired)
    assert repaired_sb.stid is not None
    assert repaired_sb.stid.bank_names[3604709923] == "Global_Movies_Loc"

    clean_issues = PackHealthScanner.scan_soundbank("global_movies.bnk", repaired)
    assert len(clean_issues) == 0


def test_scan_pack_returns_structured_report(tmp_path: Path):
    broken_bnk = _build_test_bank_with_swapped_track()
    clean_bkhd = bytes.fromhex("424b484418000000700000000100000000000000000000002b00000000000000")

    pack_path = tmp_path / "test_pack.pack"
    write_pfh4_movie_pack(
        pack_path,
        {
            "audio/broken.bnk": broken_bnk,
            "audio/clean.bnk": clean_bkhd,
            "audio/sound.wem": b"RIFFDUMMY",
        },
    )

    report = PackHealthScanner.scan_pack(pack_path)
    assert report.pack_name == "test_pack.pack"
    assert report.has_critical_issues is True
    assert report.all_fixable is True
    assert len(report.issues) == 1
    assert report.issues[0].file_path == "audio/broken.bnk"
    assert report.issues[0].issue_id == "ca_track_clip_auto_swapped"


def test_scan_soundbank_detects_truncated_chunk():
    bkhd = bytes.fromhex("424b484418000000700000000100000000000000000000002b00000000000000")
    # HIRC header declaring 1000 bytes, but only 4 bytes follow
    hirc_truncated = b"HIRC" + (1000).to_bytes(4, "little") + b"\x01\x00\x00\x00"
    bnk_bytes = bkhd + hirc_truncated

    issues = PackHealthScanner.scan_soundbank("truncated.bnk", bnk_bytes)
    assert len(issues) == 1
    assert issues[0].issue_id == "bnk_truncated_chunk"
    assert issues[0].severity == IssueSeverity.CRITICAL_CRASH


def test_scan_soundbank_continues_past_corrupt_hirc_object():
    bkhd = bytes.fromhex("424b484418000000700000000100000000000000000000002b00000000000000")
    # Object 1: malformed CAkMusicTrack with truncated payload
    obj1_corrupt = (
        (11).to_bytes(1, "little")
        + (10).to_bytes(4, "little")
        + b"\x01\x02\x03\x04\x05\x06\x07\x08\x09\x0a"
    )
    # Object 2: valid CAkMusicTrack with swapped automation count
    raw_track_hex = (
        "0ba0000000c3e4be0e00010000000100040002ecff9d39ecff9d3900000000000100000000"
        "000000ecff9d390000000000000000000000000000000000000000000000004fc1cb2978c9"
        "114101000000000100000000000000000000030000000000000000000000090000004cfc10"
        "430000000004000000ef6e1143000000000400000000000000000000e88cdd2d000000c000"
        "000100000000000000000000002c010000"
    )
    obj2_swapped = bytes.fromhex(raw_track_hex)

    hirc_body = (2).to_bytes(4, "little") + obj1_corrupt + obj2_swapped
    hirc = b"HIRC" + len(hirc_body).to_bytes(4, "little") + hirc_body
    bnk_bytes = bkhd + hirc

    issues = PackHealthScanner.scan_soundbank("multi_hirc.bnk", bnk_bytes)
    # The scanner should not abort on object 1; it should proceed and detect object 2
    swapped_issues = [i for i in issues if i.issue_id == "ca_track_clip_auto_swapped"]
    assert len(swapped_issues) == 1
    assert swapped_issues[0].object_id == 247391427


def test_synthetic_pack_health_scan_and_repair(tmp_path: Path):
    pack_path = tmp_path / "custom_music.pack"
    swapped_bnk = _build_test_bank_with_swapped_track()
    clean_bkhd = bytes.fromhex("424b484418000000700000000100000000000000000000002b00000000000000")
    write_pfh4_movie_pack(
        pack_path,
        {
            "audio/global_music.bnk": swapped_bnk,
            "audio/clean_music.bnk": clean_bkhd,
            "audio/sound.wem": b"RIFFDUMMY",
        },
    )

    report = PackHealthScanner.scan_pack(pack_path)
    assert report.has_critical_issues is True
    track_issues = [i for i in report.issues if i.object_id == 247391427]
    assert len(track_issues) == 1
    assert track_issues[0].issue_id == "ca_track_clip_auto_swapped"
    assert track_issues[0].severity == IssueSeverity.CRITICAL_CRASH

    # Repair the affected bank
    from src.compiler.pfh4_pack import extract_pfh4_file, read_pfh4_index

    entries = read_pfh4_index(pack_path)
    target_entry = next(e for e in entries if "global_music.bnk" in e.path)
    orig_bytes = extract_pfh4_file(pack_path, target_entry)

    repaired_bytes = RepairStrategyRegistry.repair_bank("global_music.bnk", orig_bytes)
    repaired_issues = PackHealthScanner.scan_soundbank("global_music.bnk", repaired_bytes)
    assert len(repaired_issues) == 0
