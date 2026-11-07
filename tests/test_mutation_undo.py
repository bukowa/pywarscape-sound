"""
Comprehensive verification test suite for Audio Mutation Undo/Redo stack in Layer 2/3 and BankViewerStore.
"""

from pathlib import Path

import pytest

from src.bnk.bank import BkhdChunk, HircChunk, SoundBank
from src.bnk.models import (
    AkMusicMarker,
    AkMusicTrackSource,
    AkTrackSrcInfo,
    CAkMusicSegment,
    CAkMusicTrack,
    CAkSound,
)
from src.engine.ontology import (
    BatchItem,
    ExternalFileSource,
    MediaNodeTarget,
    MusicTrackTarget,
    MutationBatch,
    MutationRecord,
    ReplacementScope,
)
from src.engine.session import WorkspaceSession
from src.ui.features.bank_viewer.state import BankStatus
from src.ui.features.bank_viewer.store import BankViewerStore
from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.storage import ProjectStorage
from tests.support.factories import make_synthetic_wav


def _setup_test_project_and_store(tmp_path: Path):
    """Sets up an AudioProject with vanilla GameCache containing battle_rain.bnk."""
    # 1. Build Vanilla SoundBank with Sound 3001 and 3002 (embedded sounds)
    s1 = CAkSound(id=3001, source_id=12345, file_id=0, stream_type=0)
    s2 = CAkSound(id=3002, source_id=67890, file_id=0, stream_type=0)
    vanilla_bank = SoundBank(
        header=BkhdChunk(bank_id=555, version=112),
        hirc=HircChunk(objects=[s1, s2]),
    )
    vanilla_bytes = vanilla_bank.to_bytes()

    # 2. Stage into GameCache
    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True, exist_ok=True)
    bank_path = cache_dir / "battle_rain.bnk"
    bank_path.write_bytes(vanilla_bytes)
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)

    # 3. Create fresh mod project
    proj_dir = tmp_path / "project"
    project = ProjectStorage.create_project(proj_dir, name="UndoTestProject", game=GameType.ATTILA)
    project.cache = cache

    # 4. Initialize store and load bank
    store = BankViewerStore(project=project)
    store.select_bank("battle_rain.bnk")

    return project, store, vanilla_bank


def test_mutation_record_ontology_contract():
    """Verifies MutationRecord dataclass creation, fields, immutability, and defaults."""
    record = MutationRecord(
        bank_name="battle_rain.bnk",
        node_key="hirc:3001",
        description="Replace audio with custom_sound.wav",
        before_bank_bytes=b"BEFORE",
        after_bank_bytes=b"AFTER",
        staged_wem_ids=(1001, 1002),
        was_bank_originally_modified=False,
    )

    assert record.bank_name == "battle_rain.bnk"
    assert record.node_key == "hirc:3001"
    assert record.description == "Replace audio with custom_sound.wav"
    assert record.before_bank_bytes == b"BEFORE"
    assert record.after_bank_bytes == b"AFTER"
    assert record.staged_wem_ids == (1001, 1002)
    assert record.was_bank_originally_modified is False
    assert record.kind == "bank"
    assert record.is_media is False

    media_record = MutationRecord(
        bank_name="battle_rain.bnk",
        node_key="media:1001",
        description="Mute media",
        before_bank_bytes=b"BEFORE_WEM",
        after_bank_bytes=b"",
        staged_wem_ids=(1001,),
        kind="media",
    )
    assert media_record.kind == "media"
    assert media_record.is_media is True

    # Immutability check
    with pytest.raises((AttributeError, TypeError)):
        record.bank_name = "other.bnk"  # type: ignore


def test_replace_audio_undo_and_redo(tmp_path: Path):
    """
    Tests replacing audio on a vanilla bank:
    1. Verify can_undo_mutation == True after replacement.
    2. Call undo_mutation():
       - Node restored to original WEM ID.
       - Loose WEM file deleted from disk and unlisted in manifest.
       - Bank removed from modified_banks and unlinked from pack_root/audio/.
    3. Call redo_mutation():
       - Node re-modified to new WEM ID.
       - Loose WEM re-staged on disk and re-listed in manifest.
       - Bank re-marked modified in manifest.
    """
    project, store, _ = _setup_test_project_and_store(tmp_path)

    assert store.can_undo_mutation is False
    assert store.can_redo_mutation is False

    # Create replacement WAV
    wav_path = make_synthetic_wav(tmp_path / "custom_sound.wav")

    # Replace audio for Sound 3001
    success = store.replace_sound_audio(3001, wav_path)
    assert success is True

    # Validate post-mutation state
    assert store.can_undo_mutation is True
    assert store.can_redo_mutation is False
    assert len(store.session.undo_history) == 1
    bank_record = store.session.undo_history[0]
    assert bank_record.kind == "bank"
    assert bank_record.is_media is False

    # Verify Sound node was updated in memory
    bank_tuple = store.session.loaded_banks.get("battle_rain.bnk")
    assert bank_tuple is not None
    bank, _, _ = bank_tuple
    sound_mod = next(
        obj for obj in bank.hirc.objects if isinstance(obj, CAkSound) and obj.id == 3001
    )
    new_wem_id = sound_mod.source_id
    assert new_wem_id != 12345
    assert (project.audio_dir / f"{new_wem_id}.wem").is_file()
    assert new_wem_id in project.manifest.staged_wems
    assert "battle_rain.bnk" in project.manifest.modified_banks
    assert (project.audio_dir / "battle_rain.bnk").is_file()

    # --- 1. UNDO MUTATION ---
    undo_success = store.undo_mutation()
    assert undo_success is True

    assert store.can_undo_mutation is False
    assert store.can_redo_mutation is True

    # Sound node must be restored to original source_id
    bank_tuple_undone = store.session.loaded_banks.get("battle_rain.bnk")
    assert bank_tuple_undone is not None
    bank_undone, _, _ = bank_tuple_undone
    sound_restored = next(
        obj for obj in bank_undone.hirc.objects if isinstance(obj, CAkSound) and obj.id == 3001
    )
    assert sound_restored.source_id == 12345
    assert bank_undone.to_bytes() == bank_record.before_bank_bytes

    # Loose WEM must be deleted and removed from manifest
    assert not (project.audio_dir / f"{new_wem_id}.wem").is_file()
    assert new_wem_id not in project.manifest.staged_wems

    # Bank was originally vanilla, so it must be removed from modified_banks and disk
    assert "battle_rain.bnk" not in project.manifest.modified_banks
    assert not (project.audio_dir / "battle_rain.bnk").is_file()

    # Available banks list in state should show status VANILLA
    bank_item = next(b for b in store.state.available_banks if b.name.lower() == "battle_rain.bnk")
    assert bank_item.status == BankStatus.VANILLA

    # --- 2. REDO MUTATION ---
    redo_success = store.redo_mutation()
    assert redo_success is True

    assert store.can_undo_mutation is True
    assert store.can_redo_mutation is False

    # Sound node must be re-modified
    bank_tuple_redone = store.session.loaded_banks.get("battle_rain.bnk")
    assert bank_tuple_redone is not None
    bank_redone, _, _ = bank_tuple_redone
    sound_redone = next(
        obj for obj in bank_redone.hirc.objects if isinstance(obj, CAkSound) and obj.id == 3001
    )
    assert sound_redone.source_id == new_wem_id
    assert bank_redone.to_bytes() == bank_record.after_bank_bytes

    # Loose WEM must be re-staged on disk and in manifest
    assert (project.audio_dir / f"{new_wem_id}.wem").is_file()
    assert new_wem_id in project.manifest.staged_wems

    # Bank must be re-marked modified
    assert "battle_rain.bnk" in project.manifest.modified_banks
    assert (project.audio_dir / "battle_rain.bnk").is_file()

    # Bank status in store state must be MODIFIED
    bank_item_mod = next(
        b for b in store.state.available_banks if b.name.lower() == "battle_rain.bnk"
    )
    assert bank_item_mod.status == BankStatus.MODIFIED


def test_mute_sound_undo(tmp_path: Path):
    """Verifies that muting a sound with silent stub 1.wem can be cleanly undone."""
    project, store, _ = _setup_test_project_and_store(tmp_path)

    # Mute Sound 3001
    success = store.mute_sound(3001)
    assert success is True
    assert store.can_undo_mutation is True

    # Verify sound node points to stub WEM 1
    bank_tuple = store.session.loaded_banks.get("battle_rain.bnk")
    assert bank_tuple is not None
    bank, _, _ = bank_tuple
    sound = next(obj for obj in bank.hirc.objects if isinstance(obj, CAkSound) and obj.id == 3001)
    assert sound.source_id == 1
    assert (project.audio_dir / "1.wem").is_file()
    assert 1 in project.manifest.staged_wems

    # Undo mute
    undo_success = store.undo_mutation()
    assert undo_success is True

    # Assert restored to original WEM ID 12345
    bank_tuple_restored = store.session.loaded_banks.get("battle_rain.bnk")
    assert bank_tuple_restored is not None
    bank_res, _, _ = bank_tuple_restored
    sound_res = next(
        obj for obj in bank_res.hirc.objects if isinstance(obj, CAkSound) and obj.id == 3001
    )
    assert sound_res.source_id == 12345

    # 1.wem removed
    assert not (project.audio_dir / "1.wem").is_file()
    assert 1 not in project.manifest.staged_wems
    assert "battle_rain.bnk" not in project.manifest.modified_banks


def test_sequential_mutations_preserve_partial_modifications(tmp_path: Path):
    """
    Tests sequential mutations on the same bank:
    Mutate Sound 3001, then mutate Sound 3002.
    Undo Sound 3002: Bank remains modified because Sound 3001 is still modified.
    Undo Sound 3001: Bank reverts to vanilla.
    """
    project, store, _ = _setup_test_project_and_store(tmp_path)

    # 1. Mutate Sound 3001
    wav1 = make_synthetic_wav(tmp_path / "s1.wav")
    assert store.replace_sound_audio(3001, wav1) is True
    wid1 = next(
        obj.source_id
        for obj in store.session.loaded_banks["battle_rain.bnk"][0].hirc.objects
        if isinstance(obj, CAkSound) and obj.id == 3001
    )

    # 2. Mutate Sound 3002
    wav2 = make_synthetic_wav(tmp_path / "s2.wav")
    assert store.replace_sound_audio(3002, wav2) is True
    wid2 = next(
        obj.source_id
        for obj in store.session.loaded_banks["battle_rain.bnk"][0].hirc.objects
        if isinstance(obj, CAkSound) and obj.id == 3002
    )

    assert len(store.session.undo_history) == 2

    # Undo Sound 3002
    assert store.undo_mutation() is True
    # Sound 3002 restored to original 67890
    bank = store.session.loaded_banks["battle_rain.bnk"][0]
    s2 = next(obj for obj in bank.hirc.objects if isinstance(obj, CAkSound) and obj.id == 3002)
    s1 = next(obj for obj in bank.hirc.objects if isinstance(obj, CAkSound) and obj.id == 3001)
    assert s2.source_id == 67890
    assert s1.source_id == wid1
    # Bank must STILL be in modified_banks because Sound 3001 is modified!
    assert "battle_rain.bnk" in project.manifest.modified_banks
    assert wid2 not in project.manifest.staged_wems
    assert wid1 in project.manifest.staged_wems

    # Undo Sound 3001
    assert store.undo_mutation() is True
    bank = store.session.loaded_banks["battle_rain.bnk"][0]
    s1_restored = next(
        obj for obj in bank.hirc.objects if isinstance(obj, CAkSound) and obj.id == 3001
    )
    assert s1_restored.source_id == 12345
    # Now that all mutations are undone, bank is unlinked from modified_banks
    assert "battle_rain.bnk" not in project.manifest.modified_banks
    assert not (project.audio_dir / "battle_rain.bnk").is_file()
    assert wid1 not in project.manifest.staged_wems


def test_new_mutation_clears_redo_stack(tmp_path: Path):
    """Verifies that executing a new mutation purges any available redo history."""
    _, store, _ = _setup_test_project_and_store(tmp_path)

    wav1 = make_synthetic_wav(tmp_path / "wav1.wav")
    store.replace_sound_audio(3001, wav1)
    assert store.can_undo_mutation is True

    store.undo_mutation()
    assert store.can_redo_mutation is True

    # Apply new mutation
    wav2 = make_synthetic_wav(tmp_path / "wav2.wav")
    store.replace_sound_audio(3002, wav2)

    assert store.can_undo_mutation is True
    assert store.can_redo_mutation is False  # Redo history cleared!


def test_reset_clears_mutation_stacks(tmp_path: Path):
    """Verifies that resetting store clears undo and redo stacks."""
    _, store, _ = _setup_test_project_and_store(tmp_path)

    wav = make_synthetic_wav(tmp_path / "sound.wav")
    store.replace_sound_audio(3001, wav)
    assert store.can_undo_mutation is True

    store.reset()
    assert store.can_undo_mutation is False
    assert store.can_redo_mutation is False
    assert len(store.session.undo_history) == 0
    assert len(store.session.redo_history) == 0


def test_reference_sound_media_undo_and_redo(tmp_path: Path):
    """Verifies that retargeting a sound to an existing WEM ID can be undone and redone."""
    project, store, _ = _setup_test_project_and_store(tmp_path)

    # Reference existing media 999888
    assert store.reference_sound_media(3001, 999888) is True
    assert store.can_undo_mutation is True

    bank = store.session.loaded_banks["battle_rain.bnk"][0]
    s1 = next(obj for obj in bank.hirc.objects if isinstance(obj, CAkSound) and obj.id == 3001)
    assert s1.source_id == 999888
    assert "battle_rain.bnk" in project.manifest.modified_banks

    # Undo
    assert store.undo_mutation() is True
    bank_undone = store.session.loaded_banks["battle_rain.bnk"][0]
    s1_undone = next(
        obj for obj in bank_undone.hirc.objects if isinstance(obj, CAkSound) and obj.id == 3001
    )
    assert s1_undone.source_id == 12345
    assert "battle_rain.bnk" not in project.manifest.modified_banks

    # Redo
    assert store.redo_mutation() is True
    bank_redone = store.session.loaded_banks["battle_rain.bnk"][0]
    s1_redone = next(
        obj for obj in bank_redone.hirc.objects if isinstance(obj, CAkSound) and obj.id == 3001
    )
    assert s1_redone.source_id == 999888
    assert "battle_rain.bnk" in project.manifest.modified_banks


def test_shell_edit_menu_mutation_undo_integration(tmp_path: Path):
    """Verifies MainWindow Edit -> Undo and Redo actions invoke audio mutation undo/redo."""
    from PySide6.QtWidgets import QApplication

    from src.ui.shell.store import ShellStore
    from src.ui.shell.view import MainWindow

    app = QApplication.instance() or QApplication([])

    project, _, _ = _setup_test_project_and_store(tmp_path)

    shell_store = ShellStore()
    shell_view = MainWindow(shell_store)
    shell_store.open_project(project)

    # In workspace, BankViewer is loaded with project
    shell_view.bank_viewer_store.select_bank("battle_rain.bnk")

    assert shell_view.act_undo.isEnabled() is False
    assert shell_view.act_redo.isEnabled() is False

    # Mutate Sound 3001
    wav = make_synthetic_wav(tmp_path / "menu_snd.wav")
    assert shell_view.bank_viewer_store.replace_sound_audio(3001, wav) is True

    # Undo action must be enabled with mutation status tip
    assert shell_view.act_undo.isEnabled() is True
    assert shell_view.act_redo.isEnabled() is False
    assert "mutation" in shell_view.act_undo.statusTip().lower()

    # Trigger Undo via action
    shell_view.act_undo.trigger()
    assert shell_view.bank_viewer_store.can_undo_mutation is False
    assert shell_view.act_redo.isEnabled() is True
    assert "mutation" in shell_view.act_redo.statusTip().lower()

    # Trigger Redo via action
    shell_view.act_redo.trigger()
    assert shell_view.bank_viewer_store.can_undo_mutation is True
    assert shell_view.act_redo.isEnabled() is False

    shell_view.close()


def test_batch_mutation_multiple_media_nodes_undo_redo(tmp_path: Path):
    """Verify that batch mutation on multiple media nodes properly reverts all media on undo and restores them on redo."""
    from src.bnk.chunks import DataChunk, DidxChunk, DidxEntry
    from src.engine.ontology import MediaNodeTarget, SilentStubSource
    from src.engine.session import WorkspaceSession

    proj_dir = tmp_path / "MultiMediaMod"
    project = ProjectStorage.create_project(proj_dir, name="MultiMediaMod", game=GameType.ATTILA)
    session = WorkspaceSession(project=project)

    data = b"0123456789abcdef" * 4
    bank = SoundBank(
        header=BkhdChunk(bank_id=999, version=112),
        didx=DidxChunk(
            entries=[
                DidxEntry(file_id=501, offset=0, size=32),
                DidxEntry(file_id=502, offset=32, size=32),
                DidxEntry(file_id=503, offset=64, size=32),
            ]
        ),
        data=DataChunk(data=data),
    )
    session.index_soundbank("media_test.bnk", bank)

    batch = MutationBatch(
        description="Mute 3 media files",
        items=(
            BatchItem(
                target=MediaNodeTarget(bank_name="media_test.bnk", wem_id=501),
                source=SilentStubSource(),
            ),
            BatchItem(
                target=MediaNodeTarget(bank_name="media_test.bnk", wem_id=502),
                source=SilentStubSource(),
            ),
            BatchItem(
                target=MediaNodeTarget(bank_name="media_test.bnk", wem_id=503),
                source=SilentStubSource(),
            ),
        ),
    )
    outcome = session.apply_batch(batch)
    assert outcome.applied == 3
    assert set(project.manifest.staged_wems) == {501, 502, 503}
    assert (project.audio_dir / "501.wem").is_file()
    assert (project.audio_dir / "502.wem").is_file()
    assert (project.audio_dir / "503.wem").is_file()
    assert session.can_undo_mutation is True
    assert len(session.undo_history) == 3
    for media_rec in session.undo_history:
        assert media_rec.kind == "media"
        assert media_rec.is_media is True

    # Undo
    undo_res = session.undo_mutation()
    assert undo_res is not None
    assert len(project.manifest.staged_wems) == 0
    assert not (project.audio_dir / "501.wem").is_file()
    assert not (project.audio_dir / "502.wem").is_file()
    assert not (project.audio_dir / "503.wem").is_file()
    assert session.can_undo_mutation is False
    assert session.can_redo_mutation is True

    # Redo
    redo_res = session.redo_mutation()
    assert redo_res is not None
    assert set(project.manifest.staged_wems) == {501, 502, 503}
    assert (project.audio_dir / "501.wem").is_file()
    assert (project.audio_dir / "502.wem").is_file()
    assert (project.audio_dir / "503.wem").is_file()


def test_undo_redo_loose_wem_overwrite_restores_prior_bytes(tmp_path: Path):
    """
    Verifies that when overwriting a pre-existing loose .wem file,
    undo restores the original file bytes instead of deleting the file,
    and redo restores the new audio bytes.
    """
    proj_dir = tmp_path / "OverwriteMod"
    project = ProjectStorage.create_project(proj_dir, name="OverwriteMod", game=GameType.ATTILA)
    session = WorkspaceSession(project=project)

    # 1. Pre-stage a loose WEM on disk and register in manifest
    prior_bytes = b"PRIOR_LOOSE_BYTES_V1_DUMMY_RIFF_CONTENT"
    project.stage_wem(12345, prior_bytes)
    assert (project.audio_dir / "12345.wem").read_bytes() == prior_bytes
    assert 12345 in project.manifest.staged_wems

    # 2. Setup bank with Sound 3001 pointing to 12345
    sound = CAkSound(id=3001, source_id=12345, file_id=12345, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        hirc=HircChunk(objects=[sound]),
    )
    session.index_soundbank("test_bank.bnk", bank)

    # 3. Create a new audio WAV file to replace sound 3001
    wav_path = make_synthetic_wav(tmp_path / "new_audio.wav", duration_s=0.1)
    source = ExternalFileSource(file_path=wav_path)

    # 4. Apply mutation with OVERWRITE scope
    outcome = session.apply_sound_mutation(
        "test_bank.bnk",
        3001,
        source,
        scope=ReplacementScope.OVERWRITE,
    )
    assert outcome is not None
    new_wem_bytes = (project.audio_dir / "12345.wem").read_bytes()
    assert new_wem_bytes != prior_bytes
    assert 12345 in project.manifest.staged_wems
    assert session.can_undo_mutation is True

    # 5. Undo mutation: verify prior bytes are restored and file is NOT unlinked!
    undo_res = session.undo_mutation()
    assert undo_res is not None
    assert (project.audio_dir / "12345.wem").is_file()
    assert (project.audio_dir / "12345.wem").read_bytes() == prior_bytes
    assert 12345 in project.manifest.staged_wems
    assert session.can_undo_mutation is False
    assert session.can_redo_mutation is True

    # 6. Redo mutation: verify new bytes are restored
    redo_res = session.redo_mutation()
    assert redo_res is not None
    assert (project.audio_dir / "12345.wem").read_bytes() == new_wem_bytes
    assert 12345 in project.manifest.staged_wems


def test_undo_redo_isolate_scope_forks_and_restores(tmp_path: Path):
    """
    Verifies that isolate scope forks a new unique WEM ID leaving sibling nodes intact,
    and undo reverts the sound node AST and cleans up the newly staged loose WEM.
    """
    proj_dir = tmp_path / "IsolateMod"
    project = ProjectStorage.create_project(proj_dir, name="IsolateMod", game=GameType.ATTILA)
    session = WorkspaceSession(project=project)

    shared_wid = 12345
    s1 = CAkSound(id=3001, source_id=shared_wid, file_id=shared_wid, stream_type=2)
    s2 = CAkSound(id=3002, source_id=shared_wid, file_id=shared_wid, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        hirc=HircChunk(objects=[s1, s2]),
    )
    session.index_soundbank("test_bank.bnk", bank)

    wav_path = make_synthetic_wav(tmp_path / "custom.wav", duration_s=0.1)
    source = ExternalFileSource(file_path=wav_path)
    forked_wid = 999111

    # Apply mutation with ISOLATE scope and explicit forked WEM
    outcome = session.apply_sound_mutation(
        "test_bank.bnk",
        3001,
        source,
        scope=ReplacementScope.ISOLATE,
        forked_wem_id=forked_wid,
    )
    assert outcome is not None
    modified_bank = outcome[0]
    m_s1 = next(o for o in modified_bank.hirc.objects if o.id == 3001)
    m_s2 = next(o for o in modified_bank.hirc.objects if o.id == 3002)
    assert m_s1.source_id == forked_wid
    assert m_s1.file_id == forked_wid
    assert m_s2.source_id == shared_wid
    assert (project.audio_dir / f"{forked_wid}.wem").is_file()
    assert forked_wid in project.manifest.staged_wems

    # Undo
    undo_res = session.undo_mutation()
    assert undo_res is not None
    restored_bank = session.get_loaded_bank("test_bank.bnk")
    r_s1 = next(o for o in restored_bank.hirc.objects if o.id == 3001)
    r_s2 = next(o for o in restored_bank.hirc.objects if o.id == 3002)
    assert r_s1.source_id == shared_wid
    assert r_s2.source_id == shared_wid
    assert not (project.audio_dir / f"{forked_wid}.wem").exists()
    assert forked_wid not in project.manifest.staged_wems

    # Redo
    redo_res = session.redo_mutation()
    assert redo_res is not None
    redone_bank = session.get_loaded_bank("test_bank.bnk")
    rd_s1 = next(o for o in redone_bank.hirc.objects if o.id == 3001)
    assert rd_s1.source_id == forked_wid
    assert (project.audio_dir / f"{forked_wid}.wem").is_file()
    assert forked_wid in project.manifest.staged_wems


def test_sequential_overwrites_multi_level_undo_preserves_history(tmp_path: Path):
    """
    Verifies multi-level undo/redo across sequential overwrites of the same loose WEM.
    """
    proj_dir = tmp_path / "SeqMod"
    project = ProjectStorage.create_project(proj_dir, name="SeqMod", game=GameType.ATTILA)
    session = WorkspaceSession(project=project)

    v1_bytes = b"ORIGINAL_V1_WEM_DATA"
    project.stage_wem(12345, v1_bytes)

    sound = CAkSound(id=3001, source_id=12345, file_id=12345, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        hirc=HircChunk(objects=[sound]),
    )
    session.index_soundbank("test_bank.bnk", bank)

    # Overwrite 1: v1 -> v2
    wav1 = make_synthetic_wav(tmp_path / "audio_v2.wav", duration_s=0.05)
    session.apply_sound_mutation("test_bank.bnk", 3001, ExternalFileSource(file_path=wav1))
    v2_bytes = (project.audio_dir / "12345.wem").read_bytes()
    assert v2_bytes != v1_bytes

    # Overwrite 2: v2 -> v3
    wav2 = make_synthetic_wav(tmp_path / "audio_v3.wav", duration_s=0.1)
    session.apply_sound_mutation("test_bank.bnk", 3001, ExternalFileSource(file_path=wav2))
    v3_bytes = (project.audio_dir / "12345.wem").read_bytes()
    assert v3_bytes != v2_bytes

    # Undo 1: should restore v2 bytes
    session.undo_mutation()
    assert (project.audio_dir / "12345.wem").read_bytes() == v2_bytes

    # Undo 2: should restore v1 bytes
    session.undo_mutation()
    assert (project.audio_dir / "12345.wem").read_bytes() == v1_bytes

    # Redo 1: should restore v2 bytes
    session.redo_mutation()
    assert (project.audio_dir / "12345.wem").read_bytes() == v2_bytes

    # Redo 2: should restore v3 bytes
    session.redo_mutation()
    assert (project.audio_dir / "12345.wem").read_bytes() == v3_bytes


def test_music_track_mutation_undo_redo_round_trip(tmp_path: Path):
    """
    Verifies that mutating a CAkMusicTrack scales segment timeline & markers,
    updates plugin_id to PCM 0x00010001, and undo restores the SoundBank bit-exactly.
    """
    proj_dir = tmp_path / "MusicMod"
    project = ProjectStorage.create_project(proj_dir, name="MusicMod", game=GameType.ATTILA)
    session = WorkspaceSession(project=project)

    initial_markers = [
        AkMusicMarker(id=1, position=0.0, name="<Entry>"),
        AkMusicMarker(id=2, position=2500.0, name="Verse"),
        AkMusicMarker(id=3, position=5000.0, name="<Exit>"),
    ]
    seg = CAkMusicSegment(
        id=1000,
        child_ids=[2000],
        duration=5000.0,
        markers=list(initial_markers),
    )
    track = CAkMusicTrack(
        id=2000,
        sources=[
            AkMusicTrackSource(
                plugin_id=0x00040001,  # Vorbis
                stream_type=2,
                source_id=88888,
                file_id=88888,
            )
        ],
        playlist=[AkTrackSrcInfo(track_id=2000, source_id=88888, src_duration=5000.0)],
    )
    bank = SoundBank(
        header=BkhdChunk(bank_id=900, version=112),
        hirc=HircChunk(objects=[seg, track]),
    )
    orig_bytes = bank.to_bytes()
    session.index_soundbank("music.bnk", bank)

    # Apply mutation replacing music track audio
    custom_wav = make_synthetic_wav(tmp_path / "music.wav", duration_s=0.1)
    batch = MutationBatch(
        description="Replace music track",
        items=(
            BatchItem(
                target=MusicTrackTarget(bank_name="music.bnk", track_id=2000, source_index=0),
                source=ExternalFileSource(file_path=custom_wav),
                scope=ReplacementScope.OVERWRITE,
            ),
        ),
    )
    session.apply_batch(batch)

    # Verify track updated to PCM
    mod_track = next(o for o in bank.hirc.objects if isinstance(o, CAkMusicTrack) and o.id == 2000)
    assert mod_track.sources[0].plugin_id == 0x00010001
    assert (project.audio_dir / "88888.wem").is_file()

    # Verify timeline updated
    mod_seg = next(o for o in bank.hirc.objects if isinstance(o, CAkMusicSegment) and o.id == 1000)
    assert mod_seg.duration != 5000.0
    assert mod_seg.markers[1].position != 2500.0
    assert bank.to_bytes() != orig_bytes

    # Undo: exact bit-exact restoration
    session.undo_mutation()
    undone_bank = session.get_loaded_bank("music.bnk")
    assert undone_bank is not None
    assert undone_bank.to_bytes() == orig_bytes
    restored_seg = next(
        o for o in undone_bank.hirc.objects if isinstance(o, CAkMusicSegment) and o.id == 1000
    )
    assert restored_seg.duration == 5000.0
    assert restored_seg.markers[1].position == 2500.0

    # Redo: reapplies modification
    session.redo_mutation()
    redone_bank = session.get_loaded_bank("music.bnk")
    assert redone_bank is not None
    redone_track = next(
        o for o in redone_bank.hirc.objects if isinstance(o, CAkMusicTrack) and o.id == 2000
    )
    assert redone_track.sources[0].plugin_id == 0x00010001
    assert redone_bank.to_bytes() != orig_bytes


def test_cross_bank_promotion_undo_redo_round_trip(tmp_path: Path):
    """
    Verifies that mutating media in music_data.bnk automatically discovers companion
    music.bnk, promotes sibling CAkMusicTrack and CAkSound nodes, and undo restores both bit-exactly.
    """
    proj_dir = tmp_path / "CrossBankMod"
    project = ProjectStorage.create_project(proj_dir, name="CrossBankMod", game=GameType.ATTILA)
    session = WorkspaceSession(project=project)

    shared_wem = 771122

    # 1. music_data.bnk (holds media or sound)
    data_sound = CAkSound(
        id=101, source_id=shared_wem, file_id=shared_wem, stream_type=2, plugin_id=0x00040001
    )
    data_bank = SoundBank(
        header=BkhdChunk(bank_id=10, version=112),
        hirc=HircChunk(objects=[data_sound]),
    )
    orig_data_bytes = data_bank.to_bytes()
    session.index_soundbank("music_data.bnk", data_bank)

    # 2. companion music.bnk (holds CAkMusicTrack and CAkSound referencing shared_wem)
    comp_track = CAkMusicTrack(
        id=201,
        sources=[
            AkMusicTrackSource(
                plugin_id=0x00040001, stream_type=2, source_id=shared_wem, file_id=shared_wem
            )
        ],
        playlist=[AkTrackSrcInfo(track_id=201, source_id=shared_wem, src_duration=1000.0)],
    )
    comp_sound = CAkSound(
        id=202, source_id=shared_wem, file_id=shared_wem, stream_type=2, plugin_id=0x00040001
    )
    comp_bank = SoundBank(
        header=BkhdChunk(bank_id=20, version=112),
        hirc=HircChunk(objects=[comp_track, comp_sound]),
    )
    orig_comp_bytes = comp_bank.to_bytes()
    session.index_soundbank("music.bnk", comp_bank)

    # Target music_data.bnk with media replacement
    custom_wav = make_synthetic_wav(tmp_path / "companion.wav", duration_s=0.08)
    batch = MutationBatch(
        description="Replace data media",
        items=(
            BatchItem(
                target=MediaNodeTarget(bank_name="music_data.bnk", wem_id=shared_wem),
                source=ExternalFileSource(file_path=custom_wav),
                scope=ReplacementScope.OVERWRITE,
            ),
        ),
    )
    session.apply_batch(batch)

    # Verify both banks modified and nodes promoted to PCM
    mod_comp = session.get_loaded_bank("music.bnk")
    assert mod_comp is not None
    m_track = next(o for o in mod_comp.hirc.objects if isinstance(o, CAkMusicTrack) and o.id == 201)
    m_sound = next(o for o in mod_comp.hirc.objects if isinstance(o, CAkSound) and o.id == 202)
    assert m_track.sources[0].plugin_id == 0x00010001
    assert m_sound.plugin_id == 0x00010001
    assert mod_comp.to_bytes() != orig_comp_bytes
    assert (project.audio_dir / f"{shared_wem}.wem").is_file()

    # Undo: both banks restored bit-exact and staged media reverted
    session.undo_mutation()
    undone_data = session.get_loaded_bank("music_data.bnk")
    undone_comp = session.get_loaded_bank("music.bnk")
    assert undone_data is not None and undone_comp is not None
    assert undone_data.to_bytes() == orig_data_bytes
    assert undone_comp.to_bytes() == orig_comp_bytes
    u_track = next(
        o for o in undone_comp.hirc.objects if isinstance(o, CAkMusicTrack) and o.id == 201
    )
    u_sound = next(o for o in undone_comp.hirc.objects if isinstance(o, CAkSound) and o.id == 202)
    assert u_track.sources[0].plugin_id == 0x00040001
    assert u_sound.plugin_id == 0x00040001
    assert not (project.audio_dir / f"{shared_wem}.wem").is_file()

    # Redo: companion bank re-promoted and staged media restored
    session.redo_mutation()
    redone_data = session.get_loaded_bank("music_data.bnk")
    redone_comp = session.get_loaded_bank("music.bnk")
    assert redone_data is not None and redone_comp is not None
    r_track = next(
        o for o in redone_comp.hirc.objects if isinstance(o, CAkMusicTrack) and o.id == 201
    )
    r_sound = next(o for o in redone_comp.hirc.objects if isinstance(o, CAkSound) and o.id == 202)
    assert r_track.sources[0].plugin_id == 0x00010001
    assert r_sound.plugin_id == 0x00010001
    assert redone_comp.to_bytes() != orig_comp_bytes
    assert (project.audio_dir / f"{shared_wem}.wem").is_file()
