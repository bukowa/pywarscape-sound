"""
Empirical stress-test suite for Milestone 1:
- Multi-bank shared WEM overwrites with cross-bank embedded promotion and atomic undo.
- Isolate replacement with unique WEM allocation and clean file unlinking on undo.
- Sequential mutations (3x replace, 3x undo, 3x redo) with manifest and byte verification.
"""

from __future__ import annotations

import wave
from pathlib import Path

from src.bnk.bank import BkhdChunk, DidxChunk, DidxEntry, HircChunk, SoundBank
from src.bnk.models import CAkSound
from src.engine.ontology import (
    BatchItem,
    ExternalFileSource,
    MutationBatch,
    ReplacementScope,
    SoundNodeTarget,
)
from src.engine.session import WorkspaceSession
from src.workspace.game import GameType
from src.workspace.storage import ProjectStorage


def _create_wav_file(path: Path, freq: int = 440, duration_ms: int = 50) -> Path:
    """Creates a deterministic mono 16-bit 32kHz PCM WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    num_samples = int(32000 * (duration_ms / 1000.0))
    # Fill with deterministic byte pattern based on freq
    byte_val = (freq % 250) + 1
    sample_bytes = bytes([byte_val, 0]) * num_samples
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(32000)
        wf.writeframes(sample_bytes)
    return path


def _build_test_bank(bank_id: int, sounds: list[CAkSound], didx_wems: list[int] = ()) -> SoundBank:
    """Builds an in-memory SoundBank with specified sounds and optional DIDX entries."""
    didx = None
    if didx_wems:
        didx = DidxChunk(
            entries=[
                DidxEntry(file_id=wid, offset=i * 1024, size=1024)
                for i, wid in enumerate(didx_wems)
            ]
        )
    return SoundBank(
        header=BkhdChunk(bank_id=bank_id, version=112),
        didx=didx,
        hirc=HircChunk(objects=sounds),
    )


# =============================================================================
# Challenge 1: Multi-bank shared WEM overwrites
# =============================================================================


def test_multi_bank_shared_wem_overwrite_promotion_and_atomic_undo(tmp_path: Path):
    """
    Empirically challenge 1A:
    - Multiple loaded banks referencing a shared embedded WEM.
    - An overwrite mutation on one bank promotes all embedded referencing nodes
      across all loaded banks to streamed audio (stream_type = 2).
    - A single undo_mutation() restores all touched banks and loose audio files byte-for-byte.
    """
    proj_dir = tmp_path / "MultiBankProject"
    project = ProjectStorage.create_project(proj_dir, name="MultiBankProject", game=GameType.ATTILA)

    shared_wid = 9001

    # Bank Alpha: Node 101 (embedded) and Node 102 (embedded sibling)
    s101 = CAkSound(id=101, source_id=shared_wid, file_id=shared_wid, stream_type=0)
    s102 = CAkSound(id=102, source_id=shared_wid, file_id=shared_wid, stream_type=0)
    bank_alpha = _build_test_bank(1, [s101, s102], didx_wems=[shared_wid])

    # Bank Beta: Node 201 (embedded) and Node 202 (already streamed)
    s201 = CAkSound(id=201, source_id=shared_wid, file_id=shared_wid, stream_type=0)
    s202 = CAkSound(id=202, source_id=shared_wid, file_id=shared_wid, stream_type=2)
    bank_beta = _build_test_bank(2, [s201, s202], didx_wems=[shared_wid])

    # Bank Gamma: Node 301 (embedded, shared WEM) and Node 302 (unrelated WEM 7001)
    s301 = CAkSound(id=301, source_id=shared_wid, file_id=shared_wid, stream_type=0)
    s302 = CAkSound(id=302, source_id=7001, file_id=7001, stream_type=0)
    bank_gamma = _build_test_bank(3, [s301, s302], didx_wems=[shared_wid, 7001])

    alpha_bytes_orig = bank_alpha.to_bytes()
    beta_bytes_orig = bank_beta.to_bytes()
    gamma_bytes_orig = bank_gamma.to_bytes()

    # Initialize session and index all three banks
    session = WorkspaceSession(project=project)
    session.index_soundbank("bank_alpha.bnk", bank_alpha)
    session.index_soundbank("bank_beta.bnk", bank_beta)
    session.index_soundbank("bank_gamma.bnk", bank_gamma)

    # Pre-condition: verify reference indexing across all 3 banks
    refs = session.get_cross_bank_wem_references(shared_wid)
    assert len(refs) == 5, f"Expected 5 references to shared WEM {shared_wid}, got {len(refs)}"
    assert session.get_wem_reference_count(shared_wid) == 5

    # Prepare replacement audio
    wav_path = _create_wav_file(tmp_path / "new_audio.wav", freq=550)

    # Apply mutation on Bank Alpha, Node 101 with OVERWRITE scope
    batch = MutationBatch(
        description="Overwrite shared WEM 9001",
        items=(
            BatchItem(
                target=SoundNodeTarget(bank_name="bank_alpha.bnk", sound_id=101),
                source=ExternalFileSource(file_path=wav_path),
                scope=ReplacementScope.OVERWRITE,
            ),
        ),
    )
    outcome = session.apply_batch(batch)
    assert outcome.applied == 1
    assert "bank_alpha.bnk" in outcome.touched_banks
    assert "bank_beta.bnk" in outcome.touched_banks
    assert "bank_gamma.bnk" in outcome.touched_banks

    # Verify AST mutations across all 3 loaded banks
    # Bank Alpha:
    b_alpha_mod = session.get_loaded_bank("bank_alpha.bnk")
    hirc_a = {obj.id: obj for obj in b_alpha_mod.hirc.objects}
    assert hirc_a[101].stream_type == 2, "Target node 101 must be promoted to streamed (2)"
    assert hirc_a[102].stream_type == 2, (
        "Sibling node 102 in bank_alpha must be promoted to streamed (2)"
    )

    # Bank Beta:
    b_beta_mod = session.get_loaded_bank("bank_beta.bnk")
    hirc_b = {obj.id: obj for obj in b_beta_mod.hirc.objects}
    assert hirc_b[201].stream_type == 2, (
        "Cross-bank node 201 in bank_beta must be promoted to streamed (2)"
    )
    assert hirc_b[202].stream_type == 2, "Node 202 in bank_beta was already streamed (2)"

    # Bank Gamma:
    b_gamma_mod = session.get_loaded_bank("bank_gamma.bnk")
    hirc_g = {obj.id: obj for obj in b_gamma_mod.hirc.objects}
    assert hirc_g[301].stream_type == 2, (
        "Cross-bank node 301 in bank_gamma must be promoted to streamed (2)"
    )
    assert hirc_g[302].stream_type == 0, (
        "Unrelated node 302 in bank_gamma must remain untouched (0)"
    )

    # Verify loose audio file staged on disk and manifest updated
    loose_wem_path = project.audio_dir / f"{shared_wid}.wem"
    assert loose_wem_path.is_file(), f"Staged WEM {shared_wid}.wem must exist on disk"
    assert shared_wid in project.manifest.staged_wems
    new_wem_bytes = loose_wem_path.read_bytes()
    assert len(new_wem_bytes) > 0

    # Verify all 3 banks are saved to project audio directory and in manifest
    for bname in ("bank_alpha.bnk", "bank_beta.bnk", "bank_gamma.bnk"):
        assert (project.audio_dir / bname).is_file(), f"{bname} should be saved in pack_root/audio/"
        assert bname.lower() in [b.lower() for b in project.manifest.modified_banks]

    # Now execute a SINGLE undo_mutation()
    assert session.can_undo_mutation is True
    undo_result = session.undo_mutation()
    assert undo_result is not None
    touched_undone, _ = undo_result
    assert set(touched_undone) == {"bank_alpha.bnk", "bank_beta.bnk", "bank_gamma.bnk"}

    # Verify byte-for-byte bank restoration
    b_alpha_undone = session.get_loaded_bank("bank_alpha.bnk")
    b_beta_undone = session.get_loaded_bank("bank_beta.bnk")
    b_gamma_undone = session.get_loaded_bank("bank_gamma.bnk")

    assert b_alpha_undone.to_bytes() == alpha_bytes_orig, (
        "Bank Alpha must be restored byte-for-byte"
    )
    assert b_beta_undone.to_bytes() == beta_bytes_orig, "Bank Beta must be restored byte-for-byte"
    assert b_gamma_undone.to_bytes() == gamma_bytes_orig, (
        "Bank Gamma must be restored byte-for-byte"
    )

    # Verify AST stream_type values restored
    hirc_a_un = {obj.id: obj for obj in b_alpha_undone.hirc.objects}
    assert hirc_a_un[101].stream_type == 0
    assert hirc_a_un[102].stream_type == 0

    hirc_b_un = {obj.id: obj for obj in b_beta_undone.hirc.objects}
    assert hirc_b_un[201].stream_type == 0

    hirc_g_un = {obj.id: obj for obj in b_gamma_undone.hirc.objects}
    assert hirc_g_un[301].stream_type == 0

    # Verify loose audio file is unlinked from disk and removed from manifest
    assert not loose_wem_path.exists(), f"Staged WEM {shared_wid}.wem must be deleted on undo"
    assert shared_wid not in project.manifest.staged_wems

    # Verify banks removed from manifest and unlinked from disk (since they weren't originally modified)
    for bname in ("bank_alpha.bnk", "bank_beta.bnk", "bank_gamma.bnk"):
        assert not (project.audio_dir / bname).exists(), f"{bname} should be unlinked on undo"
        assert bname.lower() not in [b.lower() for b in project.manifest.modified_banks]

    # Verify redo_mutation() re-establishes exact modified state
    assert session.can_redo_mutation is True
    redo_result = session.redo_mutation()
    assert redo_result is not None

    assert loose_wem_path.is_file()
    assert loose_wem_path.read_bytes() == new_wem_bytes
    assert session.get_loaded_bank("bank_alpha.bnk").to_bytes() == b_alpha_mod.to_bytes()
    assert session.get_loaded_bank("bank_beta.bnk").to_bytes() == b_beta_mod.to_bytes()
    assert session.get_loaded_bank("bank_gamma.bnk").to_bytes() == b_gamma_mod.to_bytes()


def test_multi_bank_shared_wem_overwrite_with_preexisting_loose_wem(tmp_path: Path):
    """
    Empirically challenge 1B:
    - Pre-existing loose WEM file already exists in pack_root/audio/ before mutation.
    - Overwriting shared audio mutates the loose WEM file on disk.
    - undo_mutation() must restore the PRE-EXISTING loose WEM bytes byte-for-byte,
      NEVER deleting the pre-existing file!
    """
    proj_dir = tmp_path / "PreexistingLooseProject"
    project = ProjectStorage.create_project(
        proj_dir, name="PreexistingLooseProject", game=GameType.ATTILA
    )

    shared_wid = 9002

    # Pre-create pre-existing loose WEM
    preexisting_bytes = b"RIFF_PREEXISTING_WEM_TEST_PAYLOAD_1234567890"
    project.stage_wem(shared_wid, preexisting_bytes)
    assert (project.audio_dir / f"{shared_wid}.wem").read_bytes() == preexisting_bytes
    assert shared_wid in project.manifest.staged_wems

    # Banks referencing shared_wid
    s1 = CAkSound(id=1, source_id=shared_wid, file_id=shared_wid, stream_type=2)
    s2 = CAkSound(id=2, source_id=shared_wid, file_id=shared_wid, stream_type=2)
    bank_a = _build_test_bank(10, [s1])
    bank_b = _build_test_bank(20, [s2])

    a_orig = bank_a.to_bytes()
    b_orig = bank_b.to_bytes()

    session = WorkspaceSession(project=project)
    session.index_soundbank("bank_a.bnk", bank_a)
    session.index_soundbank("bank_b.bnk", bank_b)

    # Replacement audio
    wav_path = _create_wav_file(tmp_path / "overwrite_sound.wav", freq=660)

    # Mutate bank_a sound 1
    batch = MutationBatch(
        description="Overwrite pre-existing loose WEM",
        items=(
            BatchItem(
                target=SoundNodeTarget(bank_name="bank_a.bnk", sound_id=1),
                source=ExternalFileSource(file_path=wav_path),
                scope=ReplacementScope.OVERWRITE,
            ),
        ),
    )
    outcome = session.apply_batch(batch)
    assert outcome.applied == 1

    # Verify loose WEM was replaced on disk
    current_bytes = (project.audio_dir / f"{shared_wid}.wem").read_bytes()
    assert current_bytes != preexisting_bytes, "WEM bytes should have been replaced with new audio"

    # Call undo_mutation()
    session.undo_mutation()

    # The file MUST still exist and its content MUST be restored byte-for-byte to preexisting_bytes
    wem_path = project.audio_dir / f"{shared_wid}.wem"
    assert wem_path.is_file(), "Pre-existing loose WEM must NOT be deleted by undo"
    assert wem_path.read_bytes() == preexisting_bytes, (
        "Pre-existing loose WEM bytes must be restored byte-for-byte"
    )
    assert shared_wid in project.manifest.staged_wems, "Pre-existing WEM must remain in manifest"


# =============================================================================
# Challenge 2: Isolate replacement
# =============================================================================


def test_isolate_replacement_allocates_unique_wem_and_undo_unlinks(tmp_path: Path):
    """
    Empirically challenge 2:
    - Target node sharing WEM 5555 with sibling and cross-bank nodes.
    - Applying ISOLATE replacement allocates a new unique WEM ID (> 100,000).
    - ONLY the target node receives the new WEM ID.
    - Sibling nodes and cross-bank nodes remain pointing to the original WEM 5555.
    - undo_mutation() unlinks newly staged file while restoring target node pointers byte-for-byte.
    """
    proj_dir = tmp_path / "IsolateProject"
    project = ProjectStorage.create_project(proj_dir, name="IsolateProject", game=GameType.ATTILA)

    original_wid = 5555

    # Bank 1: Target Node 1001, Sibling Node 1002 (embedded), Sibling Node 1003 (streamed)
    s1001 = CAkSound(id=1001, source_id=original_wid, file_id=original_wid, stream_type=0)
    s1002 = CAkSound(id=1002, source_id=original_wid, file_id=original_wid, stream_type=0)
    s1003 = CAkSound(id=1003, source_id=original_wid, file_id=original_wid, stream_type=2)
    bank_1 = _build_test_bank(100, [s1001, s1002, s1003], didx_wems=[original_wid])

    # Bank 2: Cross-bank Node 2001 (embedded)
    s2001 = CAkSound(id=2001, source_id=original_wid, file_id=original_wid, stream_type=0)
    bank_2 = _build_test_bank(200, [s2001], didx_wems=[original_wid])

    bank_1_orig_bytes = bank_1.to_bytes()
    bank_2_orig_bytes = bank_2.to_bytes()

    session = WorkspaceSession(project=project)
    session.index_soundbank("bank_1.bnk", bank_1)
    session.index_soundbank("bank_2.bnk", bank_2)

    # Verify initial sharing
    assert session.get_wem_reference_count(original_wid) == 4

    # Perform ISOLATE replacement on Node 1001
    wav_path = _create_wav_file(tmp_path / "fork_audio.wav", freq=770)
    batch = MutationBatch(
        description="Isolate Node 1001",
        items=(
            BatchItem(
                target=SoundNodeTarget(bank_name="bank_1.bnk", sound_id=1001),
                source=ExternalFileSource(file_path=wav_path),
                scope=ReplacementScope.ISOLATE,
            ),
        ),
    )
    outcome = session.apply_batch(batch)
    assert outcome.applied == 1
    assert outcome.touched_banks == ("bank_1.bnk",), "Only bank_1 should be touched in ISOLATE"

    # Verify Bank 1 AST
    b1_mod = session.get_loaded_bank("bank_1.bnk")
    hirc_1 = {obj.id: obj for obj in b1_mod.hirc.objects}

    target_node = hirc_1[1001]
    new_wid = target_node.source_id
    assert new_wid != original_wid, f"Target node should have received new WEM ID, got {new_wid}"
    assert new_wid > 100000, f"New WEM ID must be > 100000, got {new_wid}"
    assert target_node.file_id == new_wid
    assert target_node.stream_type == 2, "Target node should be promoted to streamed"

    # Verify SIBLINGS in Bank 1 remain completely untouched!
    sib_1002 = hirc_1[1002]
    assert sib_1002.source_id == original_wid, "Sibling 1002 source_id must remain 5555"
    assert sib_1002.file_id == original_wid, "Sibling 1002 file_id must remain 5555"
    assert sib_1002.stream_type == 0, "Sibling 1002 stream_type must remain 0 (embedded)"

    sib_1003 = hirc_1[1003]
    assert sib_1003.source_id == original_wid, "Sibling 1003 source_id must remain 5555"
    assert sib_1003.stream_type == 2, "Sibling 1003 stream_type must remain 2"

    # Verify Bank 2 remains completely untouched!
    b2_mod = session.get_loaded_bank("bank_2.bnk")
    assert b2_mod.to_bytes() == bank_2_orig_bytes, "Bank 2 must remain completely unmodified"
    assert "bank_2.bnk" not in [b.lower() for b in project.manifest.modified_banks]

    # Verify newly staged WEM file exists on disk
    new_wem_file = project.audio_dir / f"{new_wid}.wem"
    assert new_wem_file.is_file(), f"New WEM file {new_wid}.wem must be created"
    assert new_wid in project.manifest.staged_wems
    assert original_wid not in project.manifest.staged_wems

    # Undo the ISOLATE mutation
    assert session.can_undo_mutation is True
    undo_res = session.undo_mutation()
    assert undo_res is not None

    # Verify target node pointers restored and Bank 1 restored byte-for-byte
    b1_undone = session.get_loaded_bank("bank_1.bnk")
    assert b1_undone.to_bytes() == bank_1_orig_bytes, "Bank 1 must be restored byte-for-byte"
    hirc_1_un = {obj.id: obj for obj in b1_undone.hirc.objects}
    assert hirc_1_un[1001].source_id == original_wid
    assert hirc_1_un[1001].stream_type == 0

    # Verify newly staged file is completely unlinked from disk and removed from manifest
    assert not new_wem_file.exists(), f"Staged WEM file {new_wid}.wem must be deleted on undo"
    assert new_wid not in project.manifest.staged_wems
    assert "bank_1.bnk" not in [b.lower() for b in project.manifest.modified_banks]

    # Redo the ISOLATE mutation
    session.redo_mutation()
    b1_redone = session.get_loaded_bank("bank_1.bnk")
    assert b1_redone.to_bytes() == b1_mod.to_bytes()
    assert new_wem_file.is_file()
    assert new_wid in project.manifest.staged_wems


# =============================================================================
# Challenge 3: Sequential mutations (3x cycle)
# =============================================================================


def test_sequential_mutations_3x_replace_undo_redo_cycles(tmp_path: Path):
    """
    Empirically challenge 3:
    - Replacing the same sound node 3 times in a row with distinct audio files.
    - Undoing 3 times, verifying exact state and manifest at each step.
    - Redoing 3 times, verifying exact state and manifest at each step.
    """
    proj_dir = tmp_path / "SequentialProject"
    project = ProjectStorage.create_project(
        proj_dir, name="SequentialProject", game=GameType.ATTILA
    )

    original_wid = 4444
    sound_target_id = 700

    sound = CAkSound(
        id=sound_target_id, source_id=original_wid, file_id=original_wid, stream_type=0
    )
    bank = _build_test_bank(50, [sound], didx_wems=[original_wid])
    orig_bank_bytes = bank.to_bytes()

    session = WorkspaceSession(project=project)
    session.index_soundbank("test_seq.bnk", bank)

    wav1 = _create_wav_file(tmp_path / "audio_step1.wav", freq=300)
    wav2 = _create_wav_file(tmp_path / "audio_step2.wav", freq=600)
    wav3 = _create_wav_file(tmp_path / "audio_step3.wav", freq=900)

    # Step 1: Replace with wav1 (OVERWRITE scope)
    batch1 = MutationBatch(
        description="Step 1 replace",
        items=(
            BatchItem(
                target=SoundNodeTarget(bank_name="test_seq.bnk", sound_id=sound_target_id),
                source=ExternalFileSource(file_path=wav1),
                scope=ReplacementScope.OVERWRITE,
            ),
        ),
    )
    outcome1 = session.apply_batch(batch1)
    assert outcome1.applied == 1
    bank_bytes_after_1 = session.get_loaded_bank("test_seq.bnk").to_bytes()
    wem_bytes_after_1 = (project.audio_dir / f"{original_wid}.wem").read_bytes()
    staged_wems_after_1 = set(project.manifest.staged_wems)
    assert staged_wems_after_1 == {original_wid}

    # Step 2: Replace with wav2 (OVERWRITE scope again)
    batch2 = MutationBatch(
        description="Step 2 replace",
        items=(
            BatchItem(
                target=SoundNodeTarget(bank_name="test_seq.bnk", sound_id=sound_target_id),
                source=ExternalFileSource(file_path=wav2),
                scope=ReplacementScope.OVERWRITE,
            ),
        ),
    )
    outcome2 = session.apply_batch(batch2)
    assert outcome2.applied == 1
    bank_bytes_after_2 = session.get_loaded_bank("test_seq.bnk").to_bytes()
    wem_bytes_after_2 = (project.audio_dir / f"{original_wid}.wem").read_bytes()
    assert wem_bytes_after_2 != wem_bytes_after_1, "Step 2 audio bytes must differ from Step 1"
    staged_wems_after_2 = set(project.manifest.staged_wems)
    assert staged_wems_after_2 == {original_wid}

    # Step 3: Replace with wav3 (OVERWRITE scope third time)
    batch3 = MutationBatch(
        description="Step 3 replace",
        items=(
            BatchItem(
                target=SoundNodeTarget(bank_name="test_seq.bnk", sound_id=sound_target_id),
                source=ExternalFileSource(file_path=wav3),
                scope=ReplacementScope.OVERWRITE,
            ),
        ),
    )
    outcome3 = session.apply_batch(batch3)
    assert outcome3.applied == 1
    bank_bytes_after_3 = session.get_loaded_bank("test_seq.bnk").to_bytes()
    wem_bytes_after_3 = (project.audio_dir / f"{original_wid}.wem").read_bytes()
    assert wem_bytes_after_3 != wem_bytes_after_2, "Step 3 audio bytes must differ from Step 2"
    staged_wems_after_3 = set(project.manifest.staged_wems)
    assert staged_wems_after_3 == {original_wid}

    # -------------------------------------------------------------------------
    # Undo sequence (3 times)
    # -------------------------------------------------------------------------

    # Undo 1 (reverses Step 3 -> should restore Step 2 state)
    assert session.can_undo_mutation is True
    res_u1 = session.undo_mutation()
    assert res_u1 is not None
    assert session.get_loaded_bank("test_seq.bnk").to_bytes() == bank_bytes_after_2
    assert (project.audio_dir / f"{original_wid}.wem").read_bytes() == wem_bytes_after_2
    assert set(project.manifest.staged_wems) == staged_wems_after_2

    # Undo 2 (reverses Step 2 -> should restore Step 1 state)
    assert session.can_undo_mutation is True
    res_u2 = session.undo_mutation()
    assert res_u2 is not None
    assert session.get_loaded_bank("test_seq.bnk").to_bytes() == bank_bytes_after_1
    assert (project.audio_dir / f"{original_wid}.wem").read_bytes() == wem_bytes_after_1
    assert set(project.manifest.staged_wems) == staged_wems_after_1

    # Undo 3 (reverses Step 1 -> should restore clean initial state)
    assert session.can_undo_mutation is True
    res_u3 = session.undo_mutation()
    assert res_u3 is not None
    assert session.get_loaded_bank("test_seq.bnk").to_bytes() == orig_bank_bytes
    assert not (project.audio_dir / f"{original_wid}.wem").exists()
    assert set(project.manifest.staged_wems) == set()
    assert "test_seq.bnk" not in [b.lower() for b in project.manifest.modified_banks]
    assert session.can_undo_mutation is False

    # -------------------------------------------------------------------------
    # Redo sequence (3 times)
    # -------------------------------------------------------------------------

    # Redo 1 (re-applies Step 1)
    assert session.can_redo_mutation is True
    session.redo_mutation()
    assert session.get_loaded_bank("test_seq.bnk").to_bytes() == bank_bytes_after_1
    assert (project.audio_dir / f"{original_wid}.wem").read_bytes() == wem_bytes_after_1
    assert set(project.manifest.staged_wems) == staged_wems_after_1

    # Redo 2 (re-applies Step 2)
    assert session.can_redo_mutation is True
    session.redo_mutation()
    assert session.get_loaded_bank("test_seq.bnk").to_bytes() == bank_bytes_after_2
    assert (project.audio_dir / f"{original_wid}.wem").read_bytes() == wem_bytes_after_2
    assert set(project.manifest.staged_wems) == staged_wems_after_2

    # Redo 3 (re-applies Step 3)
    assert session.can_redo_mutation is True
    session.redo_mutation()
    assert session.get_loaded_bank("test_seq.bnk").to_bytes() == bank_bytes_after_3
    assert (project.audio_dir / f"{original_wid}.wem").read_bytes() == wem_bytes_after_3
    assert set(project.manifest.staged_wems) == staged_wems_after_3
    assert session.can_redo_mutation is False


def test_sequential_mutations_isolate_chain_3x(tmp_path: Path):
    """
    Empirically challenge 3 variant:
    - 3 sequential ISOLATE mutations on the same sound node.
    - Each isolate generates a distinct unique WEM ID.
    - Verify file unlinking on each undo step so orphaned files are cleanly removed.
    """
    proj_dir = tmp_path / "SequentialIsolateProject"
    project = ProjectStorage.create_project(
        proj_dir, name="SequentialIsolateProject", game=GameType.ATTILA
    )

    original_wid = 3333
    sound = CAkSound(id=800, source_id=original_wid, file_id=original_wid, stream_type=0)
    bank = _build_test_bank(60, [sound], didx_wems=[original_wid])
    orig_bank_bytes = bank.to_bytes()

    session = WorkspaceSession(project=project)
    session.index_soundbank("test_iso_seq.bnk", bank)

    wavs = [_create_wav_file(tmp_path / f"iso_step_{i}.wav", freq=200 * i) for i in (1, 2, 3)]

    forked_wems: list[int] = []

    for i, wav in enumerate(wavs, 1):
        batch = MutationBatch(
            description=f"Isolate step {i}",
            items=(
                BatchItem(
                    target=SoundNodeTarget(bank_name="test_iso_seq.bnk", sound_id=800),
                    source=ExternalFileSource(file_path=wav),
                    scope=ReplacementScope.ISOLATE,
                ),
            ),
        )
        outcome = session.apply_batch(batch)
        assert outcome.applied == 1
        current_bank = session.get_loaded_bank("test_iso_seq.bnk")
        current_node = [o for o in current_bank.hirc.objects if o.id == 800][0]
        wid = current_node.source_id
        assert wid != original_wid
        assert wid not in forked_wems
        forked_wems.append(wid)
        assert (project.audio_dir / f"{wid}.wem").is_file()

    # We now have 3 forked WEM files on disk
    assert len(forked_wems) == 3
    for wid in forked_wems:
        assert (project.audio_dir / f"{wid}.wem").is_file()

    # Undo Step 3:
    session.undo_mutation()
    # forked_wems[2] must be deleted!
    assert not (project.audio_dir / f"{forked_wems[2]}.wem").exists(), (
        "Step 3 forked WEM should be unlinked"
    )
    assert (project.audio_dir / f"{forked_wems[1]}.wem").is_file()
    assert (project.audio_dir / f"{forked_wems[0]}.wem").is_file()

    # Undo Step 2:
    session.undo_mutation()
    # forked_wems[1] must be deleted!
    assert not (project.audio_dir / f"{forked_wems[1]}.wem").exists(), (
        "Step 2 forked WEM should be unlinked"
    )
    assert (project.audio_dir / f"{forked_wems[0]}.wem").is_file()

    # Undo Step 1:
    session.undo_mutation()
    # forked_wems[0] must be deleted!
    assert not (project.audio_dir / f"{forked_wems[0]}.wem").exists(), (
        "Step 1 forked WEM should be unlinked"
    )
    assert session.get_loaded_bank("test_iso_seq.bnk").to_bytes() == orig_bank_bytes
    assert set(project.manifest.staged_wems) == set()


# =============================================================================
# Additional Empirical Stress Tests: Edge Cases & Adversarial Scenarios
# =============================================================================


def test_multi_bank_mixed_initial_modified_state(tmp_path: Path):
    """
    Stress-test undo when one touched bank was already modified in the project,
    while another touched bank was purely vanilla/unmodified.
    Undo must preserve the pre-batch modified state for Bank A while
    completely reverting (unlinking) Bank B.
    """
    proj_dir = tmp_path / "MixedStateProject"
    project = ProjectStorage.create_project(
        proj_dir, name="MixedStateProject", game=GameType.ATTILA
    )

    shared_wid = 9911

    s_a = CAkSound(id=1, source_id=shared_wid, file_id=shared_wid, stream_type=0)
    bank_a = _build_test_bank(10, [s_a], didx_wems=[shared_wid])
    s_b = CAkSound(id=2, source_id=shared_wid, file_id=shared_wid, stream_type=0)
    bank_b = _build_test_bank(20, [s_b], didx_wems=[shared_wid])

    # Simulate bank_a ALREADY being modified in the project prior to this mutation
    initial_a_bytes = bank_a.to_bytes()
    project.save_bank("bank_a.bnk", initial_a_bytes)
    assert "bank_a.bnk" in project.manifest.modified_banks
    assert (project.audio_dir / "bank_a.bnk").is_file()

    # bank_b is NOT in manifest
    assert "bank_b.bnk" not in project.manifest.modified_banks

    session = WorkspaceSession(project=project)
    session.index_soundbank("bank_a.bnk", bank_a)
    session.index_soundbank("bank_b.bnk", bank_b)

    wav = _create_wav_file(tmp_path / "mixed_test.wav", freq=450)
    batch = MutationBatch(
        description="Overwrite shared WEM across mixed-state banks",
        items=(
            BatchItem(
                target=SoundNodeTarget(bank_name="bank_a.bnk", sound_id=1),
                source=ExternalFileSource(file_path=wav),
                scope=ReplacementScope.OVERWRITE,
            ),
        ),
    )
    outcome = session.apply_batch(batch)
    assert outcome.applied == 1
    assert "bank_b.bnk" in project.manifest.modified_banks

    # Undo
    session.undo_mutation()

    # bank_a MUST remain saved on disk and listed in modified_banks!
    assert (project.audio_dir / "bank_a.bnk").is_file()
    assert (project.audio_dir / "bank_a.bnk").read_bytes() == initial_a_bytes
    assert "bank_a.bnk" in project.manifest.modified_banks

    # bank_b MUST be reverted and unlinked!
    assert not (project.audio_dir / "bank_b.bnk").exists()
    assert "bank_b.bnk" not in project.manifest.modified_banks


def test_allocate_unique_wem_id_stress_and_bounds():
    """
    Stress-test allocate_unique_wem_id under dense collision sets.
    Verify:
    1. Bounds: 100000 < WEM ID <= 0x7FFFFFFF.
    2. Zero collisions across 5,000 sequential allocations.
    """
    from src.engine.planner import allocate_unique_wem_id

    existing: set[int] = {100001, 100002, 100003, 500000, 0x7FFFFFFF}

    for i in range(5000):
        new_id = allocate_unique_wem_id(existing, preferred_seed=100001 + (i % 50))
        assert 100000 < new_id <= 0x7FFFFFFF, f"WEM ID {new_id} out of bounds!"
        assert new_id not in existing, f"Collision detected for ID {new_id}!"
        existing.add(new_id)


def test_undo_redo_stack_invalidation_on_new_mutation(tmp_path: Path):
    """
    Verify that applying a new mutation clears the redo stack (can_redo_mutation becomes False).
    """
    proj_dir = tmp_path / "RedoInvalidationProject"
    project = ProjectStorage.create_project(
        proj_dir, name="RedoInvalidationProject", game=GameType.ATTILA
    )

    s1 = CAkSound(id=1, source_id=101, file_id=101, stream_type=2)
    bank = _build_test_bank(1, [s1])

    session = WorkspaceSession(project=project)
    session.index_soundbank("test.bnk", bank)

    wav1 = _create_wav_file(tmp_path / "w1.wav", freq=350)
    wav2 = _create_wav_file(tmp_path / "w2.wav", freq=700)

    # Mutation 1
    session.apply_batch(
        MutationBatch(
            description="M1",
            items=(
                BatchItem(
                    target=SoundNodeTarget(bank_name="test.bnk", sound_id=1),
                    source=ExternalFileSource(file_path=wav1),
                ),
            ),
        )
    )
    assert session.can_undo_mutation is True
    assert session.can_redo_mutation is False

    # Undo M1
    session.undo_mutation()
    assert session.can_undo_mutation is False
    assert session.can_redo_mutation is True

    # Mutation 2 (should wipe redo stack)
    session.apply_batch(
        MutationBatch(
            description="M2",
            items=(
                BatchItem(
                    target=SoundNodeTarget(bank_name="test.bnk", sound_id=1),
                    source=ExternalFileSource(file_path=wav2),
                ),
            ),
        )
    )
    assert session.can_undo_mutation is True
    assert session.can_redo_mutation is False, "Redo stack must be invalidated on new mutation!"


def test_multi_item_batch_mixed_scopes_atomic_undo(tmp_path: Path):
    """
    Test a single MutationBatch containing both an ISOLATE item and an OVERWRITE item.
    Verify both are applied and a single undo_mutation() reverses all effects atomically.
    """
    proj_dir = tmp_path / "MixedBatchProject"
    project = ProjectStorage.create_project(
        proj_dir, name="MixedBatchProject", game=GameType.ATTILA
    )

    wid_shared = 7701
    wid_solo = 8801

    # Bank 1 has s1 (solo) and s2 (shared)
    s1 = CAkSound(id=1, source_id=wid_solo, file_id=wid_solo, stream_type=0)
    s2 = CAkSound(id=2, source_id=wid_shared, file_id=wid_shared, stream_type=0)
    bank_1 = _build_test_bank(1, [s1, s2], didx_wems=[wid_solo, wid_shared])

    # Bank 2 has s3 (shared)
    s3 = CAkSound(id=3, source_id=wid_shared, file_id=wid_shared, stream_type=0)
    bank_2 = _build_test_bank(2, [s3], didx_wems=[wid_shared])

    b1_orig = bank_1.to_bytes()
    b2_orig = bank_2.to_bytes()

    session = WorkspaceSession(project=project)
    session.index_soundbank("bank_1.bnk", bank_1)
    session.index_soundbank("bank_2.bnk", bank_2)

    wav_iso = _create_wav_file(tmp_path / "wav_iso.wav", freq=330)
    wav_ovr = _create_wav_file(tmp_path / "wav_ovr.wav", freq=660)

    # Single batch with ISOLATE on s1 and OVERWRITE on s2
    batch = MutationBatch(
        description="Mixed batch",
        items=(
            BatchItem(
                target=SoundNodeTarget(bank_name="bank_1.bnk", sound_id=1),
                source=ExternalFileSource(file_path=wav_iso),
                scope=ReplacementScope.ISOLATE,
            ),
            BatchItem(
                target=SoundNodeTarget(bank_name="bank_1.bnk", sound_id=2),
                source=ExternalFileSource(file_path=wav_ovr),
                scope=ReplacementScope.OVERWRITE,
            ),
        ),
    )

    outcome = session.apply_batch(batch)
    assert outcome.applied == 2
    assert "bank_1.bnk" in outcome.touched_banks
    assert "bank_2.bnk" in outcome.touched_banks

    b1_mod = session.get_loaded_bank("bank_1.bnk")
    b2_mod = session.get_loaded_bank("bank_2.bnk")

    hirc_1 = {o.id: o for o in b1_mod.hirc.objects}
    hirc_2 = {o.id: o for o in b2_mod.hirc.objects}

    forked_id = hirc_1[1].source_id
    assert forked_id != wid_solo
    assert hirc_1[1].stream_type == 2

    assert hirc_1[2].source_id == wid_shared
    assert hirc_1[2].stream_type == 2

    # Cross-bank s3 promoted to streamed
    assert hirc_2[3].source_id == wid_shared
    assert hirc_2[3].stream_type == 2

    # Files staged
    assert (project.audio_dir / f"{forked_id}.wem").is_file()
    assert (project.audio_dir / f"{wid_shared}.wem").is_file()

    # Single undo
    undo_res = session.undo_mutation()
    assert undo_res is not None

    assert session.get_loaded_bank("bank_1.bnk").to_bytes() == b1_orig
    assert session.get_loaded_bank("bank_2.bnk").to_bytes() == b2_orig
    assert not (project.audio_dir / f"{forked_id}.wem").exists()
    assert not (project.audio_dir / f"{wid_shared}.wem").exists()
    assert set(project.manifest.staged_wems) == set()
