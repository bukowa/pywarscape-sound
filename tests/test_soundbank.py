from pathlib import Path

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk, DataChunk, DidxChunk, DidxEntry, StidChunk
from src.bnk.models import CAkRanSeqCntr, CAkSound, CAkSwitchCntr


def test_media_only_bank_omits_hirc():
    bank = SoundBank(
        header=BkhdChunk(
            version=112,
            bank_id=500,
            language_id=0,
            feedback_in_bank=0,
            project_id=1,
            padding=b"\x00" * 8,
        ),
        didx=DidxChunk([DidxEntry(1, 0, 16)]),
        data=DataChunk(b"\x00" * 16),
        hirc=None,
        chunk_order=["BKHD", "DIDX", "DATA"],
    )
    raw = bank.to_bytes()
    reparsed = SoundBank.from_bytes(raw)
    assert reparsed.hirc is None
    assert reparsed.chunk_order == ["BKHD", "DIDX", "DATA"]
    assert reparsed.to_bytes() == raw


def test_soundbank_with_hirc_and_custom_chunks(tmp_path: Path):
    sound = CAkSound(id=1001, source_id=2001, file_id=2001, stream_type=2)
    hirc = HircChunk(objects=[sound])
    bank = SoundBank(
        header=BkhdChunk(version=112, bank_id=777),
        hirc=hirc,
        stid=StidChunk(bank_names={777: "TestBank"}),
        chunk_order=["BKHD", "STMG", "HIRC", "ENVS", "STID"],
        custom_chunks={"STMG": b"\x01\x02\x03\x04", "ENVS": b"\xaa\xbb"},
    )

    file_path = tmp_path / "test.bnk"
    bank.save(file_path)

    loaded = SoundBank.from_file(file_path)
    assert loaded.header.bank_id == 777
    assert loaded.hirc is not None
    assert len(loaded.hirc.objects) == 1
    assert loaded.hirc.objects[0].id == 1001
    assert loaded.custom_chunks["STMG"] == b"\x01\x02\x03\x04"
    assert loaded.custom_chunks["ENVS"] == b"\xaa\xbb"
    assert loaded.chunk_order == ["BKHD", "STMG", "HIRC", "ENVS", "STID"]
    assert loaded.to_bytes() == file_path.read_bytes()


def test_soundbank_object_queries_and_helpers():
    sound = CAkSound(id=101)
    ran_seq = CAkRanSeqCntr(id=102)
    order_switch = CAkSwitchCntr(id=103, group_id=1172968668)

    bank = SoundBank(
        header=BkhdChunk(version=112, bank_id=1),
        hirc=HircChunk(objects=[sound, ran_seq]),
    )
    assert bank.get_sound(101) == sound
    assert bank.get_ran_seq(102) == ran_seq
    assert bank.get_switch_cntr(103) is None
    assert (
        next(
            (
                o
                for o in bank.hirc.objects
                if isinstance(o, CAkSwitchCntr) and o.group_id == 1172968668
            ),
            None,
        )
        is None
    )

    bank.add_object(order_switch)
    assert bank.get_switch_cntr(103) == order_switch
    assert (
        next(
            (
                o
                for o in bank.hirc.objects
                if isinstance(o, CAkSwitchCntr) and o.group_id == 1172968668
            ),
            None,
        )
        == order_switch
    )


def test_soundbank_dynamic_chunk_reconciliation():
    # 1. Start with bank having HIRC
    sound = CAkSound(id=101)
    bank = SoundBank(
        header=BkhdChunk(version=112, bank_id=1),
        hirc=HircChunk(objects=[sound]),
        chunk_order=["BKHD", "HIRC"],
    )
    # Removing HIRC chunk dynamically
    bank.hirc = None
    raw = bank.to_bytes()
    reparsed = SoundBank.from_bytes(raw)
    assert reparsed.hirc is None
    assert "HIRC" not in reparsed.chunk_order
    assert reparsed.chunk_order == ["BKHD"]

    # 2. Start with media-only bank (no HIRC in chunk_order)
    media_bank = SoundBank(
        header=BkhdChunk(version=112, bank_id=2),
        didx=DidxChunk([DidxEntry(1, 0, 16)]),
        data=DataChunk(b"\x00" * 16),
        hirc=None,
        chunk_order=["BKHD", "DIDX", "DATA"],
    )
    # Adding HIRC dynamically
    media_bank.hirc = HircChunk(objects=[sound])
    raw2 = media_bank.to_bytes()
    reparsed2 = SoundBank.from_bytes(raw2)
    assert reparsed2.hirc is not None
    assert len(reparsed2.hirc.objects) == 1
    assert "HIRC" in reparsed2.chunk_order
