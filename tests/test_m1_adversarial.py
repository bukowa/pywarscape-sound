"""
Adversarial stress testing for Milestone 1:
1. allocate_unique_wem_id: dense clusters, boundary conditions, zero collisions, 32-bit compliance.
2. BankGraphIndex.wem_references: 10,000 objects scale test, duplicate IDs, missing chunks, defensive copying.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk, DataChunk, DidxChunk
from src.bnk.models import (
    CAkAction,
    CAkEvent,
    CAkMusicTrack,
    CAkSound,
    HircObject,
)
from src.engine.graph import BankGraphIndex
from src.engine.planner import allocate_unique_wem_id

# ---------------------------------------------------------------------------
# Suite 1: allocate_unique_wem_id Stress Tests
# ---------------------------------------------------------------------------


def test_allocate_1000_unique_ids_against_dense_initial_cluster() -> None:
    """Stress test: allocate 1,000 unique IDs against a dense cluster [100001..102000]."""
    existing_ids = set(range(100001, 102001))
    allocated: set[int] = set()

    start_time = time.perf_counter()
    for _ in range(1000):
        wid = allocate_unique_wem_id(existing_ids)
        assert wid not in existing_ids, f"Collision detected: {wid} already in existing_ids"
        assert wid not in allocated, f"Collision detected: {wid} was already allocated in this run"
        assert 100000 < wid <= 0x7FFFFFFF, (
            f"ID {wid} outside positive 32-bit range (100000, 0x7FFFFFFF]"
        )
        allocated.add(wid)
        existing_ids.add(wid)

    elapsed = time.perf_counter() - start_time
    assert len(allocated) == 1000, "Must allocate exactly 1,000 unique IDs"
    assert elapsed < 5.0, f"1,000 allocations took too long: {elapsed:.2f}s"


def test_allocate_1000_unique_ids_sequential_from_empty() -> None:
    """Stress test: allocate 1,000 unique IDs sequentially from an empty set."""
    existing_ids: set[int] = set()
    allocated: set[int] = set()

    start_time = time.perf_counter()
    for _ in range(1000):
        wid = allocate_unique_wem_id(existing_ids)
        assert wid not in existing_ids
        assert wid not in allocated
        assert 100000 < wid <= 0x7FFFFFFF
        allocated.add(wid)
        existing_ids.add(wid)

    elapsed = time.perf_counter() - start_time
    assert len(allocated) == 1000
    assert elapsed < 2.0, f"Sequential allocations took too long: {elapsed:.2f}s"


def test_allocate_against_extreme_bounds_and_negatives() -> None:
    """Stress test: extreme boundary seeds and unusual numbers in existing_ids."""
    extreme_existing = {
        -2147483648,
        -100000,
        -1,
        0,
        1,
        99999,
        100000,
        0x7FFFFFFF,
        0x80000000,
        0xFFFFFFFF,
        0x100000000,
    }

    # 1. preferred_seed = 0x7FFFFFFF (collides with extreme_existing)
    wid1 = allocate_unique_wem_id(extreme_existing, preferred_seed=0x7FFFFFFF)
    assert wid1 not in extreme_existing
    assert 100000 < wid1 <= 0x7FFFFFFF
    assert wid1 != 0x7FFFFFFF

    # 2. preferred_seed = 0x7FFFFFFE (valid boundary, not in existing)
    wid2 = allocate_unique_wem_id(extreme_existing, preferred_seed=0x7FFFFFFE)
    assert wid2 == 0x7FFFFFFE

    # 3. preferred_seed = 100000 (invalid boundary <= 100000)
    wid3 = allocate_unique_wem_id(extreme_existing, preferred_seed=100000)
    assert wid3 not in extreme_existing
    assert 100000 < wid3 <= 0x7FFFFFFF

    # 4. preferred_seed = 100001 (valid lower boundary)
    wid4 = allocate_unique_wem_id(extreme_existing, preferred_seed=100001)
    assert wid4 == 100001

    # 5. preferred_seed = 0 (boundary)
    wid5 = allocate_unique_wem_id(extreme_existing, preferred_seed=0)
    assert wid5 not in extreme_existing
    assert 100000 < wid5 <= 0x7FFFFFFF

    # 6. preferred_seed = negative numbers
    for neg_seed in (-1, -100, -2147483648):
        wid_neg = allocate_unique_wem_id(extreme_existing, preferred_seed=neg_seed)
        assert wid_neg not in extreme_existing
        assert 100000 < wid_neg <= 0x7FFFFFFF

    # 7. preferred_seed exceeding 31-bit integer
    for overflow_seed in (0x80000000, 0xFFFFFFFF, 0x100000000):
        wid_ov = allocate_unique_wem_id(extreme_existing, preferred_seed=overflow_seed)
        assert wid_ov not in extreme_existing
        assert 100000 < wid_ov <= 0x7FFFFFFF


def test_allocate_1000_unique_ids_with_negative_and_extreme_existing() -> None:
    """Stress test: allocate 1,000 unique IDs starting with negative and extreme existing IDs."""
    existing_ids = set(range(-500, 500)) | {0x7FFFFFFF, 100000, 0}
    allocated: set[int] = set()

    for i in range(1000):
        # Vary preferred_seed across extreme values and negatives
        seed = -i if i % 3 == 0 else (0x7FFFFFFF if i % 5 == 0 else 100000 + i)
        wid = allocate_unique_wem_id(existing_ids, preferred_seed=seed)
        assert wid not in existing_ids
        assert wid not in allocated
        assert 100000 < wid <= 0x7FFFFFFF
        allocated.add(wid)
        existing_ids.add(wid)

    assert len(allocated) == 1000


def test_lcg_transition_orbit_distinctness() -> None:
    """Stress test: verify the LCG transition rule produces no short cycle in 50,000 steps."""
    candidate = 100001
    seen: set[int] = set()
    for _ in range(50000):
        assert candidate not in seen, "Cycle detected in LCG trajectory!"
        seen.add(candidate)
        assert 100000 < candidate <= 0x7FFFFFFF
        candidate = (candidate * 1664525 + 1013904223) & 0x7FFFFFFF
        if candidate <= 100000:
            candidate += 100001

    assert len(seen) == 50000


# ---------------------------------------------------------------------------
# Suite 2: BankGraphIndex.wem_references Stress Tests
# ---------------------------------------------------------------------------


def test_bank_graph_index_10000_objects_scale() -> None:
    """Stress test: index 10,000 objects (sounds, music tracks, events) and verify performance."""
    objects: list[HircObject] = []

    # 1. 6,000 CAkSound objects
    # - 1,000 sounds with unique WEM IDs [100001..101000]
    for i in range(1000):
        s = CAkSound(id=10000 + i)
        s.source_id = 100001 + i
        s.file_id = 100001 + i
        s.stream_type = 2
        objects.append(s)

    # - 5,000 sounds sharing 50 WEM IDs (100 sounds per WEM ID)
    for i in range(5000):
        shared_wem = 200000 + (i % 50)
        s = CAkSound(id=20000 + i)
        s.source_id = shared_wem
        s.file_id = shared_wem
        s.stream_type = 2
        objects.append(s)

    # 2. 2,000 CAkMusicTrack objects
    for i in range(2000):
        t = CAkMusicTrack(id=30000 + i)
        # 1,000 tracks with sources, 1,000 with playlist
        if i < 1000:
            src = SimpleNamespace(source_id=300000 + i, file_id=300000 + i, stream_type=2)
            t.sources = [src]
            t.playlist = []
        else:
            p = SimpleNamespace(source_id=400000 + (i - 1000), stream_type=2)
            t.sources = []
            t.playlist = [p]
        objects.append(t)

    # 3. 2,000 other objects (CAkEvent, CAkAction)
    for i in range(1000):
        ev = CAkEvent(id=50000 + i)
        ev.actions = [60000 + i]
        objects.append(ev)

        act = CAkAction(id=60000 + i)
        act.target_id = 10000 + (i % 1000)
        objects.append(act)

    assert len(objects) == 10000, "Must have exactly 10,000 objects"

    bank = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        didx=DidxChunk(entries=[]),
        data=DataChunk(data=b""),
        hirc=HircChunk(objects=objects),
    )

    # Measure build performance
    start_time = time.perf_counter()
    index = BankGraphIndex.build(bank)
    build_time = time.perf_counter() - start_time

    assert build_time < 3.0, f"Indexing 10,000 objects took too long: {build_time:.2f}s"
    assert len(index.objects_by_id) == 10000

    # Verify query correctness
    # Check unique sounds
    for i in range(10):
        refs = index.get_wem_referencing_hirc_ids(100001 + i)
        assert refs == [10000 + i]

    # Check shared sounds (100 sounds per WEM ID)
    for w_idx in range(50):
        wid = 200000 + w_idx
        refs = index.get_wem_referencing_hirc_ids(wid)
        assert len(refs) == 100
        # Verify all referencing IDs are within [20000..24999]
        for hid in refs:
            assert 20000 <= hid < 25000

    # Check music tracks
    track_refs = index.get_wem_referencing_hirc_ids(300005)
    assert track_refs == [30005]

    playlist_refs = index.get_wem_referencing_hirc_ids(400005)
    assert playlist_refs == [31005]

    # Benchmark 10,000 queries
    query_start = time.perf_counter()
    for i in range(5000):
        _ = index.get_wem_referencing_hirc_ids(100001 + (i % 1000))
        _ = index.get_wem_referencing_hirc_ids(200000 + (i % 50))
    query_time = time.perf_counter() - query_start
    assert query_time < 1.0, f"10,000 queries took too long: {query_time:.2f}s"


def test_bank_graph_index_duplicate_ids_deduplication() -> None:
    """Stress test: verify deduplication with duplicate HIRC object IDs and multi-reference tracks."""
    objects: list[HircObject] = []

    # 1. Multiple CAkSound objects with duplicate ID 500 referencing WEM 9001
    s1 = CAkSound(id=500)
    s1.source_id = 9001
    s1.stream_type = 2
    objects.append(s1)

    s2 = CAkSound(id=500)
    s2.source_id = 9001
    s2.stream_type = 2
    objects.append(s2)

    # 2. CAkMusicTrack with duplicate sources and playlist referencing WEM 9002
    track = CAkMusicTrack(id=600)
    track.sources = [
        SimpleNamespace(source_id=9002, file_id=9002, stream_type=2),
        SimpleNamespace(source_id=9002, file_id=9002, stream_type=2),
    ]
    track.playlist = [
        SimpleNamespace(source_id=9002, stream_type=2),
        SimpleNamespace(source_id=9002, stream_type=2),
    ]
    objects.append(track)

    bank = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=objects),
    )
    index = BankGraphIndex.build(bank)

    # 500 should appear only once for 9001
    refs_9001 = index.get_wem_referencing_hirc_ids(9001)
    assert refs_9001 == [500], f"Expected [500], got {refs_9001}"

    # 600 should appear only once for 9002
    refs_9002 = index.get_wem_referencing_hirc_ids(9002)
    assert refs_9002 == [600], f"Expected [600], got {refs_9002}"


def test_bank_graph_index_defensive_copying() -> None:
    """Stress test: mutating the returned list must never mutate internal index state."""
    s = CAkSound(id=101)
    s.source_id = 5555
    s.stream_type = 2

    bank = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[s]),
    )
    index = BankGraphIndex.build(bank)

    # 1. Existing WEM ID
    first_call = index.get_wem_referencing_hirc_ids(5555)
    assert first_call == [101]

    # Mutate retrieved list in multiple hostile ways
    first_call.append(999999)
    first_call.extend([888, 777])
    first_call.clear()

    # Second call must be completely pristine
    second_call = index.get_wem_referencing_hirc_ids(5555)
    assert second_call == [101], f"Defensive copy failed! State corrupted: {second_call}"
    assert first_call is not second_call

    # 2. Non-existent WEM ID
    missing_1 = index.get_wem_referencing_hirc_ids(999999)
    assert missing_1 == []
    missing_1.append(42)

    missing_2 = index.get_wem_referencing_hirc_ids(999999)
    assert missing_2 == [], "Mutating non-existent query result leaked into index!"
    assert missing_1 is not missing_2

    # 3. Non-positive WEM IDs (<= 0)
    for non_pos in (0, -1, -9999):
        res1 = index.get_wem_referencing_hirc_ids(non_pos)
        assert res1 == []
        res1.append(1234)
        res2 = index.get_wem_referencing_hirc_ids(non_pos)
        assert res2 == []
        assert res1 is not res2


def test_bank_graph_index_missing_chunks_resilience() -> None:
    """Stress test: missing or None chunks (hirc=None, didx=None, data=None, header=None)."""
    # 1. hirc is None
    bank_no_hirc = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        didx=None,
        data=None,
        hirc=None,
    )
    index1 = BankGraphIndex.build(bank_no_hirc)
    assert index1.wem_references == {}
    assert index1.get_wem_referencing_hirc_ids(123) == []

    # 2. didx and data are None
    bank_no_didx = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        didx=None,
        data=None,
        hirc=HircChunk(objects=[CAkSound(id=1, source_id=777, stream_type=2)]),
    )
    index2 = BankGraphIndex.build(bank_no_didx)
    assert index2.get_wem_referencing_hirc_ids(777) == [1]

    # 3. header is None
    bank_no_bkhd = SoundBank(
        header=None,
        hirc=HircChunk(objects=[CAkSound(id=2, source_id=888, stream_type=2)]),
    )
    index3 = BankGraphIndex.build(bank_no_bkhd)
    assert index3.get_wem_referencing_hirc_ids(888) == [2]

    # 4. Sound with None or malformed attributes
    s_malformed = CAkSound(id=3)
    s_malformed.source_id = None  # type: ignore[assignment]
    s_malformed.file_id = None  # type: ignore[assignment]
    bank_malformed = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[s_malformed]),
    )
    index4 = BankGraphIndex.build(bank_malformed)
    assert index4.wem_references == {}
