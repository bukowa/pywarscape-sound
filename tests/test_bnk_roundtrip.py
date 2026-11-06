"""Comprehensive bit-exact round-trip verification across all vanilla assets."""

import glob
import os

import pytest

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk, DataChunk, DidxChunk, DidxEntry, StidChunk
from src.bnk.database import SoundDatabase
from src.bnk.models import CAkAction, CAkEvent, CAkSound
from tests.support.factories import skip_or_fail_missing_asset


def test_synthetic_soundbank_bit_exact_roundtrip():
    """Hermetic verification: full SoundBank with BKHD, DIDX, DATA, HIRC, and STID chunks roundtrips bit-exact."""
    sound = CAkSound(id=101, plugin_id=0x40001, stream_type=2, source_id=101, file_id=101)
    action = CAkAction.create_play(id=102, target_id=101)
    event = CAkEvent(id=103, actions=[102])

    bank = SoundBank(
        header=BkhdChunk(version=112, bank_id=98765),
        didx=DidxChunk(
            entries=[
                DidxEntry(file_id=101, offset=0, size=16),
                DidxEntry(file_id=102, offset=16, size=16),
            ]
        ),
        data=DataChunk(data=b"0123456789ABCDEF0123456789ABCDEF"),
        hirc=HircChunk(objects=[sound, action, event]),
        stid=StidChunk(bank_names={98765: "SyntheticBank"}),
    )

    orig_bytes = bank.to_bytes()
    bank_parsed = SoundBank.from_bytes(orig_bytes)
    reserialized = bank_parsed.to_bytes()

    assert reserialized == orig_bytes
    assert bank_parsed.header is not None
    assert bank_parsed.header.bank_id == 98765
    assert bank_parsed.didx is not None and len(bank_parsed.didx.entries) == 2
    assert (
        bank_parsed.data is not None
        and bank_parsed.data.data == b"0123456789ABCDEF0123456789ABCDEF"
    )
    assert bank_parsed.hirc is not None and len(bank_parsed.hirc.objects) == 3
    assert bank_parsed.stid is not None and bank_parsed.stid.bank_names == {98765: "SyntheticBank"}


@pytest.mark.assets
def test_all_attila_banks_bit_exact_roundtrip():
    cache_dir = os.path.join(".cache", "attila", "audio")
    bnk_files = glob.glob(os.path.join(cache_dir, "*.bnk"))
    if not bnk_files:
        skip_or_fail_missing_asset(f"No SoundBank assets found in {cache_dir}")

    assert len(bnk_files) in (126, 127), f"Expected 126 or 127 Attila banks, found {len(bnk_files)}"

    for bnk_path in bnk_files:
        with open(bnk_path, "rb") as f:
            orig = f.read()
        bank = SoundBank.from_bytes(orig)
        reserialized = bank.to_bytes()
        assert reserialized == orig, (
            f"Bit-exact round-trip failed on {os.path.basename(bnk_path)} (orig={len(orig)}, reserialized={len(reserialized)})"
        )


@pytest.mark.assets
def test_attila_event_data_roundtrip():
    dat_path = os.path.join(".cache", "attila", "audio", "event_data.dat")
    if not os.path.exists(dat_path):
        skip_or_fail_missing_asset("event_data.dat not found in cache")
    with open(dat_path, "rb") as f:
        orig = f.read()
    db = SoundDatabase.from_bytes(orig)
    assert db.to_bytes() == orig


@pytest.mark.assets
def test_all_rome2_banks_bit_exact_roundtrip():
    cache_dir = os.path.join(".cache", "rome_2", "audio")
    bnk_files = glob.glob(os.path.join(cache_dir, "*.bnk"))
    if not bnk_files:
        skip_or_fail_missing_asset(f"No Rome II SoundBank assets found in {cache_dir}")

    assert len(bnk_files) in (105, 117), (
        f"Expected 105 or 117 Rome II banks, found {len(bnk_files)}"
    )

    for bnk_path in bnk_files:
        with open(bnk_path, "rb") as f:
            orig = f.read()
        bank = SoundBank.from_bytes(orig)
        reserialized = bank.to_bytes()
        assert reserialized == orig, (
            f"Bit-exact round-trip failed on {os.path.basename(bnk_path)} (orig={len(orig)}, reserialized={len(reserialized)})"
        )


@pytest.mark.assets
def test_rome2_event_data_roundtrip():
    dat_path = os.path.join(".cache", "rome_2", "audio", "event_data.dat")
    if not os.path.exists(dat_path):
        skip_or_fail_missing_asset("Rome II event_data.dat not found in cache")
    with open(dat_path, "rb") as f:
        orig = f.read()
    db = SoundDatabase.from_bytes(orig)
    assert db.to_bytes() == orig
