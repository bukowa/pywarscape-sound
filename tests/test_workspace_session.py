"""Unit tests for WorkspaceSession domain façade."""

import ast
from pathlib import Path

import pytest

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk, DataChunk, DidxChunk, DidxEntry
from src.bnk.models import AkMusicTrackSource, CAkMusicTrack, CAkSound
from src.engine.ontology import SilentStubSource, WemReference
from src.engine.session import WorkspaceSession
from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.storage import ProjectStorage


def test_workspace_session_no_qt_or_ui_imports():
    """Verify WorkspaceSession module contains ZERO PySide, PyQt, or src.ui imports."""
    session_file = Path(__file__).parents[1] / "src" / "engine" / "session.py"
    tree = ast.parse(session_file.read_text(encoding="utf-8"), filename=str(session_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(("PySide", "PyQt", "src.ui")), (
                    f"Banned import in session.py: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert not node.module.startswith(("PySide", "PyQt", "src.ui")), (
                    f"Banned import in session.py: {node.module}"
                )


def test_workspace_session_initial_state():
    """Verify clean initial state of WorkspaceSession."""
    session = WorkspaceSession()
    assert session.project is None
    assert session.sound_db is None
    assert session.resolver is None
    assert session.companion_banks == {}
    assert session.can_undo_mutation is False
    assert session.can_redo_mutation is False
    assert session.get_loaded_entry("test.bnk") is None
    assert session.get_loaded_bank("test.bnk") is None
    assert session.get_staged_wems() is None


def test_workspace_session_set_project_and_reset(tmp_path: Path):
    """Verify setting project initializes resolver and reset clears all session state."""
    session = WorkspaceSession()
    proj_dir = tmp_path / "TestProject"
    project = ProjectStorage.create_project(proj_dir, name="TestProject", game=GameType.ATTILA)

    session.set_project(project)
    assert session.project is project
    assert session.resolver is not None
    assert session.get_staged_wems() == set()

    session.reset()
    assert session.project is None
    assert session.resolver is None
    assert session.can_undo_mutation is False
    assert session.get_staged_wems() is None


def test_workspace_session_index_and_get_bank():
    """Verify indexing and retrieving SoundBank ASTs with case-insensitivity."""
    session = WorkspaceSession()
    sound = CAkSound(id=1, source_id=100, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=42, version=112),
        hirc=HircChunk(objects=[sound]),
    )

    indexed_bank, graph_index, diff_res = session.index_soundbank("Battle_Unit.bnk", bank)
    assert indexed_bank is bank
    assert diff_res is None
    assert 1 in graph_index.objects_by_id

    # Case-insensitive retrieval
    assert session.get_loaded_bank("BATTLE_UNIT.BNK") is bank
    assert session.get_loaded_bank("battle_unit.bnk") is bank
    assert session.get_loaded_bank("other.bnk") is None

    entry = session.get_loaded_entry("battle_unit.bnk")
    assert entry is not None
    assert entry[0] is bank
    assert entry[1] is graph_index


def test_workspace_session_resolve_and_parse_bank(tmp_path: Path):
    """Verify resolving, parsing, and caching bank from disk."""
    session = WorkspaceSession()
    sound = CAkSound(id=10, source_id=500, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=99, version=112),
        hirc=HircChunk(objects=[sound]),
    )
    bank_path = tmp_path / "loose_bank.bnk"
    bank_path.write_bytes(bank.to_bytes())

    # First resolve: reads from disk, parses, indexes
    parsed_bank, graph_index, diff_res = session.resolve_and_parse_bank(str(bank_path))
    assert parsed_bank.header.bank_id == 99
    assert session.get_loaded_bank(str(bank_path)) is parsed_bank

    # Second resolve: returns from warm cache
    cached_bank, _, _ = session.resolve_and_parse_bank(str(bank_path))
    assert cached_bank is parsed_bank

    # Missing file raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        session.resolve_and_parse_bank("non_existent_bank.bnk")


def test_workspace_session_diff_calculation(tmp_path: Path):
    """Verify baseline bank diffing and staged WEM integration."""
    # Setup vanilla cache
    vanilla_sound = CAkSound(id=100, source_id=111, stream_type=2)
    vanilla_bank = SoundBank(
        header=BkhdChunk(bank_id=500, version=112),
        hirc=HircChunk(objects=[vanilla_sound]),
    )
    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    (cache_dir / "battle.bnk").write_bytes(vanilla_bank.to_bytes())
    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)

    # Setup project with modified bank
    modified_sound = CAkSound(id=100, source_id=999, stream_type=2)
    modified_bank = SoundBank(
        header=BkhdChunk(bank_id=500, version=112),
        didx=DidxChunk(entries=[DidxEntry(file_id=12345, offset=0, size=16)]),
        data=DataChunk(data=b"\x00" * 16),
        hirc=HircChunk(objects=[modified_sound]),
    )
    proj_dir = tmp_path / "project"
    project = ProjectStorage.create_project(proj_dir, name="DiffMod", game=GameType.ATTILA)
    project.cache = cache

    session = WorkspaceSession(project=project)
    diff_res = session.compute_bank_diff("battle.bnk", modified_bank)
    assert diff_res is not None
    assert 100 in diff_res.modified_object_ids

    # Stage loose WEM overriding embedded DIDX entry (12345)
    project.manifest.staged_wems.append(12345)
    diff_with_staged = session.compute_bank_diff("battle.bnk", modified_bank)
    assert diff_with_staged is not None
    assert 12345 in diff_with_staged.modified_media_ids


def test_workspace_session_sound_mutation_and_undo_redo(tmp_path: Path):
    """Verify sound node audio replacement mutation followed by atomic Undo and Redo."""
    sound = CAkSound(id=50, source_id=500, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=300, version=112),
        hirc=HircChunk(objects=[sound]),
    )

    proj_dir = tmp_path / "SoundMod"
    project = ProjectStorage.create_project(proj_dir, name="SoundMod", game=GameType.ATTILA)

    session = WorkspaceSession(project=project)
    session.index_soundbank("battle.bnk", bank)

    assert session.can_undo_mutation is False
    assert session.can_redo_mutation is False

    # 1. Apply mutation: mute sound 50 with silent stub 1.wem
    res = session.apply_sound_mutation("battle.bnk", 50, SilentStubSource(stub_wem_id=1))
    assert res is not None
    mutated_bank, diff_res, node_key = res
    assert node_key == "hirc:50"
    assert session.can_undo_mutation is True
    assert session.can_redo_mutation is False
    assert (project.audio_dir / "1.wem").is_file()
    assert 1 in project.manifest.staged_wems
    assert "battle.bnk" in project.manifest.modified_banks

    # 2. Undo mutation
    undo_res = session.undo_mutation()
    assert undo_res is not None
    touched_banks, reverted_key = undo_res
    assert touched_banks == ("battle.bnk",)
    assert reverted_key == "hirc:50"
    assert session.can_undo_mutation is False
    assert session.can_redo_mutation is True
    assert not (project.audio_dir / "1.wem").is_file()
    assert 1 not in project.manifest.staged_wems
    assert "battle.bnk" not in project.manifest.modified_banks

    # 3. Redo mutation
    redo_res = session.redo_mutation()
    assert redo_res is not None
    r_touched_banks, redone_key = redo_res
    assert r_touched_banks == ("battle.bnk",)
    assert redone_key == "hirc:50"
    assert session.can_undo_mutation is True
    assert session.can_redo_mutation is False
    assert (project.audio_dir / "1.wem").is_file()
    assert 1 in project.manifest.staged_wems
    assert "battle.bnk" in project.manifest.modified_banks


def test_workspace_session_media_mutation_and_undo_redo(tmp_path: Path):
    """Verify embedded media replacement mutation followed by atomic Undo and Redo."""
    bank = SoundBank(
        header=BkhdChunk(bank_id=400, version=112),
        didx=DidxChunk(entries=[DidxEntry(file_id=888, offset=0, size=16)]),
        data=DataChunk(data=b"\x00" * 16),
        hirc=HircChunk(objects=[]),
    )

    proj_dir = tmp_path / "MediaMod"
    project = ProjectStorage.create_project(proj_dir, name="MediaMod", game=GameType.ATTILA)
    project.save_bank("media.bnk", bank.to_bytes())

    session = WorkspaceSession(project=project)
    session.index_soundbank("media.bnk", bank)

    # 1. Apply mutation: replace media 888 with silent stub
    res = session.apply_media_mutation("media.bnk", 888, SilentStubSource(stub_wem_id=888))
    assert res is not None
    mutated_bank, diff_res, node_key = res
    assert node_key == "media:888"
    assert session.can_undo_mutation is True
    assert (project.audio_dir / "888.wem").is_file()
    assert 888 in project.manifest.staged_wems

    # 2. Undo
    undo_res = session.undo_mutation()
    assert undo_res is not None
    assert not (project.audio_dir / "888.wem").is_file()
    assert 888 not in project.manifest.staged_wems
    assert session.can_undo_mutation is False
    assert session.can_redo_mutation is True

    # 3. Redo
    redo_res = session.redo_mutation()
    assert redo_res is not None
    assert (project.audio_dir / "888.wem").is_file()
    assert 888 in project.manifest.staged_wems
    assert session.can_undo_mutation is True
    assert session.can_redo_mutation is False


def test_workspace_session_extract_sound_wem_id():
    """Verify robust extraction of WEM ID across CAkSound structures."""
    # Top-level source_id
    s1 = CAkSound(id=1, source_id=12345, stream_type=2)
    assert WorkspaceSession.extract_sound_wem_id(s1) == 12345

    # Top-level file_id fallback
    s2 = CAkSound(id=2, source_id=0, file_id=67890, stream_type=2)
    assert WorkspaceSession.extract_sound_wem_id(s2) == 67890

    # Default fallback to 0
    s3 = CAkSound(id=3, source_id=0, file_id=0, stream_type=2)
    assert WorkspaceSession.extract_sound_wem_id(s3) == 0

    # Embedded bank_source_data.media_information structure
    class MockMediaInfo:
        source_id = 998877

    class MockBankSourceData:
        media_information = MockMediaInfo()

    class MockSoundWithSourceData:
        bank_source_data = MockBankSourceData()

    assert WorkspaceSession.extract_sound_wem_id(MockSoundWithSourceData()) == 998877


def test_workspace_session_catalog_providers():
    """Verify local and global catalog provider builders."""
    session = WorkspaceSession()
    sound = CAkSound(id=10, source_id=500, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=101, version=112),
        hirc=HircChunk(objects=[sound]),
    )
    session.index_soundbank("test_cat.bnk", bank)

    local_cat, cat_provider = session.build_local_and_global_catalog_providers("test_cat.bnk")
    assert isinstance(local_cat, tuple)
    assert callable(cat_provider)
    global_items = cat_provider()
    assert isinstance(global_items, (list, tuple))

    # Non-loaded bank returns empty defaults
    empty_cat, empty_provider = session.build_local_and_global_catalog_providers("unknown.bnk")
    assert empty_cat == ()
    assert empty_provider() == ()


def test_wem_reference_dataclass_contract():
    """Verify WemReference attributes, immutability, and keyword-only construction."""
    ref = WemReference(
        bank_name="test.bnk",
        node_id=123,
        node_name="Sound_123",
        node_type="Sound",
        node_key="hirc:123",
        stream_type=2,
        is_embedded=False,
    )
    assert ref.bank_name == "test.bnk"
    assert ref.node_id == 123
    assert ref.node_name == "Sound_123"
    assert ref.node_type == "Sound"
    assert ref.node_key == "hirc:123"
    assert ref.stream_type == 2
    assert ref.is_embedded is False

    with pytest.raises(AttributeError):
        ref.stream_type = 0  # Immutable / frozen


def test_get_cross_bank_wem_references_empty():
    """Verify zero results for unindexed session or invalid IDs."""
    session = WorkspaceSession()
    assert session.get_cross_bank_wem_references(100) == ()
    assert session.get_wem_reference_count(100) == 0
    assert session.get_cross_bank_wem_references(0) == ()
    assert session.get_wem_reference_count(-5) == 0


def test_get_cross_bank_wem_references_single_bank():
    """Verify single bank reference querying distinguishes streamed vs embedded audio."""
    session = WorkspaceSession()
    snd_streamed = CAkSound(id=10, source_id=501, stream_type=2)
    snd_embedded = CAkSound(id=20, source_id=502, stream_type=0)
    didx = DidxChunk(entries=[DidxEntry(file_id=502, offset=0, size=1024)])

    bank = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        didx=didx,
        hirc=HircChunk(objects=[snd_streamed, snd_embedded]),
    )
    session.index_soundbank("test_bank.bnk", bank)

    # Streamed query
    refs_501 = session.get_cross_bank_wem_references(501)
    assert len(refs_501) == 1
    assert session.get_wem_reference_count(501) == 1
    assert refs_501[0].bank_name == "test_bank.bnk"
    assert refs_501[0].node_id == 10
    assert refs_501[0].node_key == "hirc:10"
    assert refs_501[0].node_type == "Sound"
    assert refs_501[0].stream_type == 2
    assert refs_501[0].is_embedded is False

    # Embedded query
    refs_502 = session.get_cross_bank_wem_references(502)
    assert len(refs_502) == 1
    assert session.get_wem_reference_count(502) == 1
    assert refs_502[0].bank_name == "test_bank.bnk"
    assert refs_502[0].node_id == 20
    assert refs_502[0].stream_type == 0
    assert refs_502[0].is_embedded is True


def test_get_cross_bank_wem_references_multi_bank():
    """Verify cross-bank WEM sharing aggregates references across all loaded banks."""
    session = WorkspaceSession()
    shared_wid = 9999

    # Bank 1: battle_vo.bnk with 1 streamed sound
    b1_snd = CAkSound(id=100, source_id=shared_wid, stream_type=2)
    bank1 = SoundBank(
        header=BkhdChunk(bank_id=10, version=112),
        hirc=HircChunk(objects=[b1_snd]),
    )

    # Bank 2: campaign_vo.bnk with 1 embedded sound and 1 music track
    b2_snd = CAkSound(id=200, source_id=shared_wid, stream_type=0)
    b2_track = CAkMusicTrack(
        id=300,
        sources=[AkMusicTrackSource(source_id=shared_wid, stream_type=0)],
    )
    b2_didx = DidxChunk(entries=[DidxEntry(file_id=shared_wid, offset=0, size=2048)])
    bank2 = SoundBank(
        header=BkhdChunk(bank_id=20, version=112),
        didx=b2_didx,
        hirc=HircChunk(objects=[b2_snd, b2_track]),
    )

    session.index_soundbank("battle_vo.bnk", bank1)
    session.index_soundbank("campaign_vo.bnk", bank2)

    assert session.get_wem_reference_count(shared_wid) == 3
    refs = session.get_cross_bank_wem_references(shared_wid)
    assert len(refs) == 3

    node_ids = {r.node_id for r in refs}
    assert node_ids == {100, 200, 300}

    banks_by_node = {r.node_id: r.bank_name for r in refs}
    assert banks_by_node[100] == "battle_vo.bnk"
    assert banks_by_node[200] == "campaign_vo.bnk"
    assert banks_by_node[300] == "campaign_vo.bnk"

    types_by_node = {r.node_id: r.node_type for r in refs}
    assert types_by_node[100] == "Sound"
    assert types_by_node[200] == "Sound"
    assert types_by_node[300] == "MusicTrack"

    embedded_by_node = {r.node_id: r.is_embedded for r in refs}
    assert embedded_by_node[100] is False
    assert embedded_by_node[200] is True
    assert embedded_by_node[300] is True
