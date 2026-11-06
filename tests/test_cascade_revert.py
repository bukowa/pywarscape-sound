from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.engine.session import WorkspaceSession
from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject
from src.workspace.storage import ProjectStorage


def test_cascade_revert_bank_shared_media_preservation(tmp_path: Path):
    proj_dir = tmp_path / "CascadeMod"
    project = ProjectStorage.create_project(proj_dir, name="CascadeMod", game=GameType.ATTILA)

    # Modified Bank A and Bank B
    project.save_bank("bank_a.bnk", b"BANK_A_MODIFIED")
    project.save_bank("bank_b.bnk", b"BANK_B_MODIFIED")
    project.manifest.custom_names["bank_a.bnk"] = {101: "AliasA"}
    project.manifest.custom_names["bank_b.bnk"] = {202: "AliasB"}

    # WEM 101: exclusive to Bank A
    # WEM 202: shared between Bank A and Bank B
    # WEM 303: exclusive to Bank B
    project.stage_wem(101, b"WEM_101_EXCLUSIVE_A")
    project.stage_wem(202, b"WEM_202_SHARED_A_B")
    project.stage_wem(303, b"WEM_303_EXCLUSIVE_B")

    # Master audio staged for WEM 101 and WEM 202
    master101 = tmp_path / "master_exclusive.wav"
    master101.write_bytes(b"RIFF_101")
    project.stage_source_audio(master101, 101)

    master202 = tmp_path / "master_shared.wav"
    master202.write_bytes(b"RIFF_202")
    project.stage_source_audio(master202, 202)

    assert (project.audio_dir / "bank_a.bnk").exists()
    assert (project.audio_dir / "101.wem").exists()
    assert (project.audio_dir / "202.wem").exists()
    assert (project.audio_dir / "303.wem").exists()
    assert (project.source_audio_dir / "master_exclusive.wav").exists()

    # Media provider simulating embedded/referenced media IDs
    def mock_media_provider(name: str) -> frozenset[int]:
        n = name.lower()
        if "bank_a" in n:
            return frozenset({101, 202})
        if "bank_b" in n:
            return frozenset({202, 303})
        return frozenset()

    # Revert Bank A completely
    banks_rev, wems_rev = project.revert_bank_completely(
        "bank_a.bnk", all_banks_media_provider=mock_media_provider
    )

    assert banks_rev == 1
    assert (
        wems_rev == 1
    )  # Only WEM 101 is reverted; WEM 202 is preserved because Bank B is modified!

    # Bank A removed
    assert not (project.audio_dir / "bank_a.bnk").exists()
    assert "bank_a.bnk" not in project.manifest.modified_banks
    assert "bank_a.bnk" not in project.manifest.custom_names

    # WEM 101 removed
    assert not (project.audio_dir / "101.wem").exists()
    assert 101 not in project.manifest.staged_wems
    assert 101 not in project.manifest.source_audio
    assert not (project.source_audio_dir / "master_exclusive.wav").exists()

    # WEM 202 preserved (shared with Bank B)
    assert (project.audio_dir / "202.wem").exists()
    assert 202 in project.manifest.staged_wems
    assert 202 in project.manifest.source_audio
    assert (project.source_audio_dir / "master_shared.wav").exists()

    # WEM 303 preserved (belongs to Bank B)
    assert (project.audio_dir / "303.wem").exists()
    assert 303 in project.manifest.staged_wems

    # Now revert Bank B completely
    banks_rev_b, wems_rev_b = project.revert_bank_completely(
        "bank_b.bnk", all_banks_media_provider=mock_media_provider
    )
    assert banks_rev_b == 1
    assert wems_rev_b == 2  # WEM 202 and WEM 303 are both reverted now

    assert not (project.audio_dir / "bank_b.bnk").exists()
    assert not (project.audio_dir / "202.wem").exists()
    assert not (project.audio_dir / "303.wem").exists()
    assert not (project.source_audio_dir / "master_shared.wav").exists()
    assert project.manifest.modified_banks == []
    assert project.manifest.staged_wems == []


def test_session_revert_invalidates_in_memory_ast_and_caches(tmp_path: Path):
    proj_dir = tmp_path / "SessionRevertMod"
    project = ProjectStorage.create_project(proj_dir, name="SessionRevertMod", game=GameType.ATTILA)
    project.save_bank("voice.bnk", b"VOICE_BYTES")
    project.stage_wem(777, b"WEM_777")

    session = WorkspaceSession(project=project)
    # Populate in-memory caches
    mock_bank = MagicMock()
    mock_bank.didx = None
    session._loaded_banks["voice.bnk"] = (mock_bank, MagicMock(), None)
    session.cache_wem(777, b"WEM_777_CACHED")

    assert "voice.bnk" in session.loaded_banks
    assert 777 in session.wem_cache

    # Revert WEM via session
    assert session.revert_wem(777) is True
    assert 777 not in session.wem_cache
    assert not (project.audio_dir / "777.wem").exists()

    # Revert Bank via session
    b_rev, w_rev = session.revert_bank("voice.bnk")
    assert b_rev == 1
    assert "voice.bnk" not in session.loaded_banks
    assert not (project.audio_dir / "voice.bnk").exists()


def test_cascade_revert_real_didx_unshared_media(tmp_path: Path):
    """Verifies that cascade revert scans real DIDX chunk from disk before bank deletion without mocks."""
    import struct

    proj_dir = tmp_path / "RealDidxProj"
    project = ProjectStorage.create_project(proj_dir, name="RealDidxProj", game=GameType.ATTILA)

    # Build real BKHD and DIDX chunks
    bkhd = b"BKHD" + struct.pack("<III", 8, 112, 1)
    didx = b"DIDX" + struct.pack("<IIII", 12, 5555, 0, 100)
    project.save_bank("custom_standalone.bnk", bkhd + didx)
    project.stage_wem(5555, b"WEM_5555_BYTES")

    session = WorkspaceSession(project=project)
    media_ids = session.get_bank_media_ids("custom_standalone.bnk")
    assert 5555 in media_ids

    b_rev, w_rev = session.revert_bank("custom_standalone.bnk")
    assert b_rev == 1
    assert w_rev == 1
    assert not (project.audio_dir / "custom_standalone.bnk").exists()
    assert not (project.audio_dir / "5555.wem").exists()
    assert 5555 not in project.manifest.staged_wems
    assert "custom_standalone.bnk" not in project.manifest.modified_banks


def test_revert_modified_vanilla_bank_with_new_wems(tmp_path: Path):
    """Verifies that an overlay bank overriding a vanilla bank scans overlay DIDX before deletion."""
    import struct

    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    bkhd = b"BKHD" + struct.pack("<III", 8, 112, 1)
    didx_vanilla = b"DIDX" + struct.pack("<IIII", 12, 1111, 0, 100)
    (cache_dir / "battle.bnk").write_bytes(bkhd + didx_vanilla)

    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)
    proj_dir = tmp_path / "ModVanillaProj"
    project = ProjectStorage.create_project(
        proj_dir, name="ModVanillaProj", game=GameType.ATTILA, cache=cache
    )

    # User modified battle.bnk with an extra WEM 2222
    didx_mod = b"DIDX" + struct.pack("<IIIIIII", 24, 1111, 0, 100, 2222, 100, 200)
    project.save_bank("battle.bnk", bkhd + didx_mod)
    project.stage_wem(2222, b"WEM_2222_BYTES")

    session = WorkspaceSession(project=project)
    # Resolver must resolve overlay first, returning both 1111 and 2222
    assert session.get_bank_media_ids("battle.bnk") == frozenset({1111, 2222})

    b_rev, w_rev = session.revert_bank("battle.bnk")
    assert b_rev == 1
    assert w_rev == 1
    assert not (project.audio_dir / "battle.bnk").exists()
    assert not (project.audio_dir / "2222.wem").exists()
    assert 2222 not in project.manifest.staged_wems
    assert "battle.bnk" not in project.manifest.modified_banks


def test_store_revert_actions_and_selection_refresh(tmp_path: Path):
    """Verifies that BankViewerStore revert_bank and revert_wem update selection and state cleanly."""
    from src.ui.features.bank_viewer.state import BankStatus
    from src.ui.features.bank_viewer.store import BankViewerStore

    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    (cache_dir / "test_store.bnk").write_bytes(b"VANILLA_TEST_STORE_BNK")

    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)
    proj_dir = tmp_path / "StoreRevertProj"
    project = ProjectStorage.create_project(
        proj_dir, name="StoreRevertProj", game=GameType.ATTILA, cache=cache
    )

    project.save_bank("test_store.bnk", b"LOCAL_MODIFIED_BNK")
    project.stage_wem(9090, b"LOCAL_WEM_9090")

    store = BankViewerStore(project=project)
    store.select_bank("test_store.bnk")
    assert store.state.selected_bank_name == "test_store.bnk"
    assert store.is_wem_modified(9090) is True

    # Revert loose WEM
    assert store.revert_wem(9090) is True
    assert store.is_wem_modified(9090) is False
    assert not (project.audio_dir / "9090.wem").exists()

    # Revert bank to baseline
    b_rev, w_rev = store.revert_bank("test_store.bnk")
    assert b_rev == 1
    item = next(b for b in store.state.available_banks if b.name.lower() == "test_store.bnk")
    assert item.status == BankStatus.VANILLA
