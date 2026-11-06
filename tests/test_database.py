from pathlib import Path

import pytest

from src.bnk.database import (
    SoundDatabase,
    fnv1_32,
)
from tests.support.factories import skip_or_fail_missing_asset


def test_fnv1_32_hashing():
    assert fnv1_32("Play_Battle_VO_Orders") == 2264862622
    assert fnv1_32("VO_ORDER") == 3817981241
    assert fnv1_32("gender") == 1776943274
    assert fnv1_32("") == 0


def test_database_empty_and_populated_roundtrip(tmp_path: Path):
    db = SoundDatabase()
    raw = db.to_bytes()
    loaded = SoundDatabase.from_bytes(raw)
    assert len(loaded.events) == 0
    assert loaded.to_bytes() == raw

    # Add items to database
    ev = db.add_event("Play_test_sound", duration=3.5)
    assert ev.event_id == fnv1_32("Play_test_sound")
    assert db.lookup_event_id("Play_test_sound") == ev.event_id
    assert db.resolve_hash(ev.event_id) == "Play_test_sound"

    sg = db.add_switch_group("VO_ORDER", values=["Order_Attack", "Order_Retreat"])
    assert sg.group_id == 3817981241
    assert len(sg.switch_names) == 2

    stg = db.add_state_group("game_mode", values=["battle", "campaign"])
    assert stg.group_id == fnv1_32("game_mode")

    de = db.add_dialogue_event("dialogue_attack", argument_group_ids=[1172968668])
    assert len(de.argument_group_ids) == 1

    rtpc_id = db.add_rtpc("music_volume")
    assert rtpc_id == 1006694123

    # Roundtrip to file
    file_path = tmp_path / "event_data.dat"
    db.save(file_path)

    loaded_db = SoundDatabase.from_file(file_path)
    assert len(loaded_db.events) == 1
    assert loaded_db.lookup_event_id("Play_test_sound") == ev.event_id
    assert loaded_db.to_bytes() == file_path.read_bytes()


@pytest.mark.assets
def test_real_attila_event_data_roundtrip():
    import os

    dat_path = os.path.join(".cache", "attila", "audio", "event_data.dat")
    if not os.path.exists(dat_path):
        skip_or_fail_missing_asset("event_data.dat not found in cache")

    with open(dat_path, "rb") as f:
        orig = f.read()

    db = SoundDatabase.from_bytes(orig)
    assert db.to_bytes() == orig
    assert len(db.events) > 1000
    assert len(db.switch_groups) > 10
