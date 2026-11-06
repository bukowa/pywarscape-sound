"""Tests for pure SoundBank baseline diffing in Layer 2."""

from src.bnk.bank import BkhdChunk, HircChunk, SoundBank
from src.bnk.chunks import DidxChunk, DidxEntry
from src.bnk.models import CAkAction, CAkEvent, CAkSound
from src.engine.diff import diff_soundbanks


def test_diff_identical_banks_returns_empty():
    ev = CAkEvent(id=10, actions=[20])
    act = CAkAction.create_play(id=20, target_id=30)
    snd = CAkSound(id=30, source_id=1001, stream_type=2)

    active = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[ev, act, snd]),
    )
    baseline = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[ev, act, snd]),
    )

    diff = diff_soundbanks(active, baseline)
    assert not diff.is_modified
    assert len(diff.modified_object_ids) == 0
    assert len(diff.added_object_ids) == 0
    assert len(diff.removed_object_ids) == 0
    assert len(diff.modified_media_ids) == 0


def test_diff_modified_hirc_object():
    ev = CAkEvent(id=10, actions=[20])
    snd_vanilla = CAkSound(id=30, source_id=1001, stream_type=2)
    snd_modified = CAkSound(id=30, source_id=9999, stream_type=2)

    baseline = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[ev, snd_vanilla]),
    )
    active = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[ev, snd_modified]),
    )

    diff = diff_soundbanks(active, baseline)
    assert diff.is_modified
    assert 30 in diff.modified_object_ids
    assert 10 not in diff.modified_object_ids
    assert len(diff.added_object_ids) == 0


def test_diff_added_and_removed_hirc_objects():
    ev1 = CAkEvent(id=10, actions=[20])
    ev2 = CAkEvent(id=11, actions=[21])

    baseline = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[ev1]),
    )
    active = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[ev2]),
    )

    diff = diff_soundbanks(active, baseline)
    assert diff.is_modified
    assert 11 in diff.added_object_ids
    assert 10 in diff.removed_object_ids
    assert 11 in diff.all_modified_object_ids


def test_diff_modified_and_added_embedded_media():
    didx_vanilla = DidxChunk(entries=[DidxEntry(file_id=101, offset=0, size=500)])
    didx_modified = DidxChunk(
        entries=[
            DidxEntry(file_id=101, offset=0, size=600),  # modified size
            DidxEntry(file_id=102, offset=600, size=300),  # newly added
        ]
    )

    baseline = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        didx=didx_vanilla,
    )
    active = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        didx=didx_modified,
    )

    diff = diff_soundbanks(active, baseline)
    assert diff.is_modified
    assert 101 in diff.modified_media_ids
    assert 102 in diff.modified_media_ids


def test_diff_none_baseline_marks_all_as_added():
    ev = CAkEvent(id=10, actions=[20])
    didx = DidxChunk(entries=[DidxEntry(file_id=101, offset=0, size=500)])
    active = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[ev]),
        didx=didx,
    )

    diff = diff_soundbanks(active, None)
    assert diff.is_modified
    assert 10 in diff.added_object_ids
    assert 10 in diff.all_modified_object_ids
    assert 101 in diff.modified_media_ids
