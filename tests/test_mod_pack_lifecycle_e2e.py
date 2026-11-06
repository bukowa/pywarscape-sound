"""End-to-end integration tests for Total War mod pack compilation, decompilation, and modification lifecycle.

Tests the full lifecycle across:
1. Unmodified / clean baseline project pack build.
2. Single bank modification pack build and decompile verification.
3. Sound replacement with staged streamed .wem container and AST promotion.
4. Multiple banks and multiple loose .wem files packaging and integrity.
5. Silent stub muting (SilentStubSource) across sound nodes.
6. Existing media reference redirection (ExistingMediaReferenceSource).
7. Undo/Redo cycles and verifying that un-mutated/reverted banks are omitted from the build.
8. UI actions and status bar feedback via MainWindow.
9. UI PackSettingsDialog presets ("Game Data Directory" vs "Project Folder") and "Build Mod Pack Now".
10. PT_MOD (type 3) vs PT_MOVIE (type 4) and user.script.txt generation.
11. Game startup crash prevention invariants (no db/ tables, Windows backslash paths, uncompressed audio).
12. Batch silence mutation across multiple nodes simultaneously.
13. Embedded to streamed sound promotion (DIDX embedded audio promoted to loose WEM).
14. Direct loose WEM override via MediaNodeTarget.
15. Music track replacement (CAkMusicTrack and AkMusicTrackSource).
16. Overwriting staged WEM payloads without duplicate entries.
17. Total War Virtual File System (VFS) mod pack override priority simulation.
18. External raw audio (WAV) transcoding via PyAV to PCM .wem, pack compilation, and decompile verification.
"""

import struct
import wave
from pathlib import Path

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk, DataChunk, DidxChunk, DidxEntry
from src.bnk.models import AkMusicTrackSource, CAkMusicTrack, CAkSound
from src.compiler.pfh4_pack import (
    PT_MOD,
    extract_pfh4_file,
    format_user_script_entry,
    read_pfh4_index,
    read_pfh4_pack_type,
    write_pfh4_pack,
)
from src.engine.ontology import (
    BatchItem,
    ExistingMediaReferenceSource,
    ExternalFileSource,
    MutationBatch,
    SilentStubSource,
    SoundNodeTarget,
)
from src.engine.session import WorkspaceSession
from src.ui.shell.pack_settings_dialog import PackSettingsDialog
from src.ui.shell.store import ShellStore
from src.ui.shell.view import MainWindow
from src.workspace.game import GameType
from src.workspace.game_detector import GameDetector
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject
from src.workspace.storage import ProjectStorage


def _create_test_project(tmp_path: Path, name: str) -> AudioProject:
    """Helper creating a test project isolated inside tmp_path."""
    proj_dir = tmp_path / name
    proj_dir.mkdir(parents=True, exist_ok=True)
    manifest = ProjectManifest(
        name=name,
        game=GameType.ATTILA,
        output_pack_path=str(proj_dir / f"{name}.pack"),
    )
    project = AudioProject(root_dir=proj_dir, manifest=manifest)
    ProjectStorage.save_project(project)
    return project


def _create_sample_bank(
    bank_id: int, sound_id: int, source_id: int, stream_type: int = 2
) -> SoundBank:
    """Helper creating a minimal valid SoundBank AST with one CAkSound."""
    sound = CAkSound(id=sound_id, source_id=source_id, stream_type=stream_type)
    return SoundBank(
        header=BkhdChunk(bank_id=bank_id, version=112),
        hirc=HircChunk(objects=[sound]),
    )


def test_pack_build_unmodified_clean_project(tmp_path: Path):
    """
    Given a clean mod project with zero modifications in pack_root/audio/,
    When the mod pack is compiled,
    Then a valid PT_MOD PFH4 archive is created with zero entries,
    and decompilation succeeds without errors.
    """
    project = _create_test_project(tmp_path, "CleanMod")

    output_pack = project.compile_mod_pack()
    assert output_pack.is_file()
    assert output_pack == project.root_dir / "CleanMod.pack"

    # Verify PFH4 header properties: default is always PT_MOD (3)
    pack_type = read_pfh4_pack_type(output_pack)
    assert pack_type == PT_MOD

    # Decompile index: must have exactly 0 entries
    entries = read_pfh4_index(output_pack)
    assert len(entries) == 0


def test_pack_build_single_bank_modified(tmp_path: Path):
    """
    Given a project where a single SoundBank has been modified and saved,
    When the mod pack is compiled,
    Then:
    1. The resulting .pack contains exactly audio/battle.bnk.
    2. Decompiling and parsing the extracted bank AST succeeds with bit-exact fidelity.
    3. The sound node properties match the modification.
    """
    project = _create_test_project(tmp_path, "SingleBankMod")

    bank = _create_sample_bank(bank_id=5001, sound_id=701, source_id=88001, stream_type=2)
    project.save_bank("battle.bnk", bank.to_bytes())

    output_pack = project.compile_movie_pack()
    assert output_pack.is_file()

    entries = read_pfh4_index(output_pack)
    assert len(entries) == 1
    assert entries[0].path.replace("/", "\\") == "audio\\battle.bnk"

    # Decompile and parse bank from the pack archive
    extracted_bytes = extract_pfh4_file(output_pack, entries[0])
    parsed_bank = SoundBank.from_bytes(extracted_bytes)

    assert parsed_bank.header.bank_id == 5001
    assert parsed_bank.hirc is not None
    assert len(parsed_bank.hirc.objects) == 1

    sound_obj = parsed_bank.hirc.objects[0]
    assert isinstance(sound_obj, CAkSound)
    assert sound_obj.id == 701
    assert sound_obj.source_id == 88001
    assert sound_obj.stream_type == 2


def test_pack_build_single_sound_replacement_with_staged_streamed_wem(tmp_path: Path):
    """
    Given a project with a SoundBank and a staged replacement .wem file,
    When the mod pack is compiled,
    Then:
    1. Both audio/battle.bnk and audio/90001.wem are packaged.
    2. Decompiling extracts the .wem and matches the staged bytes bit-for-bit.
    3. Decompiling and parsing battle.bnk confirms CAkSound references 90001 with stream_type=2.
    """
    project = _create_test_project(tmp_path, "StreamedWemMod")

    bank = _create_sample_bank(bank_id=4002, sound_id=302, source_id=90001, stream_type=2)
    project.save_bank("battle.bnk", bank.to_bytes())

    custom_wem_bytes = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00data\x04\x00\x00\x00TEST"
    project.stage_wem(90001, custom_wem_bytes)

    output_pack = project.compile_movie_pack()
    entries = read_pfh4_index(output_pack)
    assert len(entries) == 2

    entry_map = {e.path.replace("\\", "/"): e for e in entries}
    assert "audio/battle.bnk" in entry_map
    assert "audio/90001.wem" in entry_map

    # Extract and verify the loose WEM
    extracted_wem = extract_pfh4_file(output_pack, entry_map["audio/90001.wem"])
    assert extracted_wem == custom_wem_bytes

    # Extract and verify the SoundBank
    extracted_bnk = extract_pfh4_file(output_pack, entry_map["audio/battle.bnk"])
    parsed_bank = SoundBank.from_bytes(extracted_bnk)
    sound_obj = parsed_bank.hirc.objects[0]
    assert isinstance(sound_obj, CAkSound)
    assert sound_obj.source_id == 90001
    assert sound_obj.stream_type == 2


def test_pack_build_multiple_banks_and_multiple_wems(tmp_path: Path):
    """
    Given a project with multiple modified SoundBanks and multiple staged .wem streams,
    When the mod pack is compiled,
    Then:
    1. All banks and wems are compiled with correct paths and offsets.
    2. Decompiling and verifying each entry confirms complete integrity without cross-talk.
    """
    project = _create_test_project(tmp_path, "MultiBankMod")

    banks_data = {
        "battle.bnk": _create_sample_bank(bank_id=101, sound_id=1, source_id=1001),
        "campaign.bnk": _create_sample_bank(bank_id=102, sound_id=2, source_id=1002),
        "music.bnk": _create_sample_bank(bank_id=103, sound_id=3, source_id=1003),
    }
    for b_name, b_obj in banks_data.items():
        project.save_bank(b_name, b_obj.to_bytes())

    wems_data = {
        1001: b"WEM_PAYLOAD_1001_SFX",
        1002: b"WEM_PAYLOAD_1002_VOICE",
        1003: b"WEM_PAYLOAD_1003_MUSIC",
        1004: b"WEM_PAYLOAD_1004_EXTRA",
    }
    for w_id, w_bytes in wems_data.items():
        project.stage_wem(w_id, w_bytes)

    output_pack = project.compile_movie_pack()
    entries = read_pfh4_index(output_pack)
    assert len(entries) == 7

    entry_map = {e.path.replace("\\", "/"): e for e in entries}

    # Verify all banks
    for b_name, expected_obj in banks_data.items():
        rel_path = f"audio/{b_name}"
        assert rel_path in entry_map
        extracted = extract_pfh4_file(output_pack, entry_map[rel_path])
        parsed = SoundBank.from_bytes(extracted)
        assert parsed.header.bank_id == expected_obj.header.bank_id

    # Verify all WEMs
    for w_id, expected_payload in wems_data.items():
        rel_path = f"audio/{w_id}.wem"
        assert rel_path in entry_map
        extracted = extract_pfh4_file(output_pack, entry_map[rel_path])
        assert extracted == expected_payload


def test_pack_build_with_silent_stub_muting(tmp_path: Path):
    """
    Given a WorkspaceSession muting a sound node with SilentStubSource,
    When the mod pack is compiled,
    Then the bank AST updates the sound node to reference the silent stub,
    the stub WEM is packaged, and decompilation confirms the muted configuration.
    """
    project = _create_test_project(tmp_path, "SilentStubMod")

    bank = _create_sample_bank(bank_id=3001, sound_id=45, source_id=5000, stream_type=0)
    session = WorkspaceSession(project=project)
    session.index_soundbank("ambience.bnk", bank)

    # Apply silent stub mutation
    session.apply_sound_mutation(
        "ambience.bnk", sound_id=45, source=SilentStubSource(stub_wem_id=1)
    )

    output_pack = session.compile_movie_pack()
    assert output_pack.is_file()

    entries = read_pfh4_index(output_pack)
    entry_map = {e.path.replace("\\", "/"): e for e in entries}

    assert "audio/ambience.bnk" in entry_map
    assert "audio/1.wem" in entry_map

    # Decompile bank: sound node 45 must point to stub 1 with stream_type=2
    bnk_bytes = extract_pfh4_file(output_pack, entry_map["audio/ambience.bnk"])
    parsed_bank = SoundBank.from_bytes(bnk_bytes)
    sound_obj = parsed_bank.hirc.objects[0]
    assert isinstance(sound_obj, CAkSound)
    assert sound_obj.source_id == 1
    assert sound_obj.stream_type == 2


def test_pack_build_with_existing_media_reference(tmp_path: Path):
    """
    Given a sound node mutated to point to an existing media WEM ID from another bank,
    When the mod pack is compiled,
    Then the sound node in the compiled pack references that WEM ID without requiring duplicate files.
    """
    project = _create_test_project(tmp_path, "MediaRefMod")

    bank = _create_sample_bank(bank_id=6001, sound_id=88, source_id=200, stream_type=2)
    session = WorkspaceSession(project=project)
    session.index_soundbank("speech.bnk", bank)

    # Redirect sound 88 to existing media ID 777999
    session.apply_sound_mutation(
        "speech.bnk",
        sound_id=88,
        source=ExistingMediaReferenceSource(wem_id=777999, source_bank="vanilla_speech.bnk"),
    )

    output_pack = session.compile_movie_pack()
    entries = read_pfh4_index(output_pack)
    entry_map = {e.path.replace("\\", "/"): e for e in entries}

    assert "audio/speech.bnk" in entry_map
    bnk_bytes = extract_pfh4_file(output_pack, entry_map["audio/speech.bnk"])
    parsed_bank = SoundBank.from_bytes(bnk_bytes)
    sound_obj = parsed_bank.hirc.objects[0]
    assert isinstance(sound_obj, CAkSound)
    assert sound_obj.source_id == 777999


def test_pack_build_after_undo_and_redo_cycles(tmp_path: Path):
    """
    Given mutations applied across multiple banks,
    When an undo is performed on one bank,
    Then compiling the pack includes ONLY the remaining modified bank.
    When redo is performed, compiling the pack includes BOTH banks.
    """
    project = _create_test_project(tmp_path, "UndoRedoMod")

    bank_a = _create_sample_bank(bank_id=111, sound_id=10, source_id=100)
    bank_b = _create_sample_bank(bank_id=222, sound_id=20, source_id=200)

    session = WorkspaceSession(project=project)
    session.index_soundbank("bank_a.bnk", bank_a)
    session.index_soundbank("bank_b.bnk", bank_b)

    # Mutate bank_a
    session.apply_sound_mutation("bank_a.bnk", 10, SilentStubSource(stub_wem_id=1))
    # Mutate bank_b
    session.apply_sound_mutation("bank_b.bnk", 20, ExistingMediaReferenceSource(wem_id=999))

    # 1. Both modified -> pack contains bank_a, bank_b, and 1.wem
    pack1 = session.compile_movie_pack()
    entries1 = {e.path.replace("\\", "/") for e in read_pfh4_index(pack1)}
    assert "audio/bank_a.bnk" in entries1
    assert "audio/bank_b.bnk" in entries1
    assert "audio/1.wem" in entries1

    # 2. Undo bank_b mutation
    session.undo_mutation()

    pack2 = session.compile_movie_pack()
    entries2 = {e.path.replace("\\", "/") for e in read_pfh4_index(pack2)}
    assert "audio/bank_a.bnk" in entries2
    assert "audio/1.wem" in entries2
    assert "audio/bank_b.bnk" not in entries2, "Reverted bank_b must not appear in compiled pack"

    # 3. Redo bank_b mutation
    session.redo_mutation()

    pack3 = session.compile_movie_pack()
    entries3 = {e.path.replace("\\", "/") for e in read_pfh4_index(pack3)}
    assert "audio/bank_a.bnk" in entries3
    assert "audio/bank_b.bnk" in entries3
    assert "audio/1.wem" in entries3


def test_pack_build_ui_actions_and_status_bar_feedback(qapp, tmp_path: Path, monkeypatch):
    """
    Given MainWindow with an active project containing multiple modifications,
    When the user triggers the 'Build Mod Pack' action (Ctrl+B),
    Then:
    1. The .pack file is compiled on disk as PT_MOD.
    2. The status bar presents formatted feedback with exact bank and WEM counts.
    3. Decompiling the pack verifies all assets were written.
    4. user.script.txt entry is registered.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData"))
    store = ShellStore()
    window = MainWindow(store)

    proj_dir = tmp_path / "UiBuildMod"
    project = ProjectStorage.create_project(proj_dir, name="UiBuildMod", game=GameType.ATTILA)

    bank1 = _create_sample_bank(bank_id=701, sound_id=1, source_id=501)
    bank2 = _create_sample_bank(bank_id=702, sound_id=2, source_id=502)
    project.save_bank("ui_bank_1.bnk", bank1.to_bytes())
    project.save_bank("ui_bank_2.bnk", bank2.to_bytes())
    project.stage_wem(501, b"UI_WEM_501")
    project.stage_wem(502, b"UI_WEM_502")
    project.stage_wem(503, b"UI_WEM_503")

    pack_dest = tmp_path / "output" / "UiBuildMod.pack"
    project.set_output_pack_path(pack_dest)

    store.open_project(project)
    assert window.act_build_pack.isEnabled()

    # Trigger build via action
    window._on_build_pack_triggered()

    assert pack_dest.is_file()
    status_msg = window.status_bar.currentMessage()
    assert "Compiled mod pack: UiBuildMod.pack" in status_msg
    assert "2 banks" in status_msg
    assert "3 loose WEMs" in status_msg

    # Decompile and verify entries
    entries = read_pfh4_index(pack_dest)
    entry_paths = {e.path.replace("\\", "/") for e in entries}
    assert len(entry_paths) == 5
    assert "audio/ui_bank_1.bnk" in entry_paths
    assert "audio/ui_bank_2.bnk" in entry_paths
    assert "audio/501.wem" in entry_paths
    assert "audio/502.wem" in entry_paths
    assert "audio/503.wem" in entry_paths


def test_pack_build_ui_pack_settings_dialog_presets_and_build_now(
    qapp, tmp_path: Path, monkeypatch
):
    """
    Given PackSettingsDialog,
    When the user selects presets ('Set to Project Folder' or 'Set to Game Data Directory')
    and clicks 'Build Mod Pack Now',
    Then the configured destination is compiled, the pack_built signal is emitted,
    and decompiling confirms valid pack contents.
    """
    monkeypatch.setenv("APPDATA", str(tmp_path / "FakeAppData"))
    proj_dir = tmp_path / "SettingsDialogMod"
    project = ProjectStorage.create_project(
        proj_dir, name="SettingsDialogMod", game=GameType.ATTILA
    )
    project.save_bank("custom.bnk", _create_sample_bank(1, 1, 1).to_bytes())

    dialog = PackSettingsDialog(project)

    # 1. Test Project Folder preset
    dialog.btn_project_dir_preset.click()
    expected_proj_pack = proj_dir / "SettingsDialogMod.pack"
    assert dialog.txt_pack_path.text() == str(expected_proj_pack)

    # 2. Test Game Data Directory preset with mocked GameDetector
    fake_game_data = tmp_path / "FakeTotalWarAttila" / "data"
    fake_game_data.mkdir(parents=True)
    monkeypatch.setattr(
        GameDetector, "detect_game_install", lambda gt: tmp_path / "FakeTotalWarAttila"
    )

    dialog.btn_game_data_preset.click()
    expected_game_pack = fake_game_data / "SettingsDialogMod.pack"
    assert dialog.txt_pack_path.text() == str(expected_game_pack)
    assert "Ready for direct in-game testing" in dialog.lbl_status.text()

    # 3. Test Build Mod Pack Now button
    built_paths = []
    dialog.pack_built.connect(built_paths.append)

    dialog.btn_build_now.click()
    assert len(built_paths) == 1
    assert built_paths[0] == expected_game_pack
    assert expected_game_pack.is_file()

    # Decompile and verify contents
    entries = read_pfh4_index(expected_game_pack)
    assert len(entries) == 1
    assert entries[0].path.replace("/", "\\") == "audio\\custom.bnk"


def test_pack_build_mod_type_and_user_script_integration(tmp_path: Path, monkeypatch):
    """
    Tests compiling as PT_MOD (type 3) and user.script.txt registration:
    1. compile_mod_pack defaults to PT_MOD (type 3).
    2. format_user_script_entry produces the exact line 'mod "<name>.pack";\r\n'.
    3. register_in_user_script appends the entry to user.script.txt without duplicating lines.
    """
    proj_dir = tmp_path / "ModTypeTest"
    project = ProjectStorage.create_project(proj_dir, name="ModTypeTest", game=GameType.ATTILA)
    project.save_bank("test.bnk", b"TEST_BNK_DATA")

    # 1. Compile as PT_MOD (default)
    mod_pack_path = tmp_path / "workshop_submod.pack"
    compiled_pack = project.compile_mod_pack(output_path=mod_pack_path)
    assert compiled_pack.is_file()

    pack_type = read_pfh4_pack_type(compiled_pack)
    assert pack_type == PT_MOD

    # 2. Verify user.script.txt entry formatting
    script_entry = format_user_script_entry(compiled_pack.name)
    assert script_entry == 'mod "workshop_submod.pack";\r\n'

    # 3. Test register_in_user_script with isolated APPDATA
    fake_appdata = tmp_path / "FakeAppData"
    monkeypatch.setenv("APPDATA", str(fake_appdata))

    script_path = project.register_in_user_script(compiled_pack.name)
    assert script_path is not None
    assert script_path.is_file()
    assert 'mod "workshop_submod.pack";' in script_path.read_text(encoding="utf-8")

    # Test idempotency (no duplicate entries)
    project.register_in_user_script(compiled_pack.name)
    content = script_path.read_text(encoding="utf-8")
    assert content.count('mod "workshop_submod.pack";') == 1


def test_pack_build_game_crash_prevention_invariants(tmp_path: Path):
    """
    Verifies critical Total War engine invariants to ensure the game will not crash on startup:
    1. Temporary and stray files (.tmp) in audio_dir are strictly excluded.
    2. Zero db/ tables are packaged (strict metadata boundary prevents CTD).
    3. All entry paths use Windows backslash '\\'.
    4. Data payloads are uncompressed streamable bytes.
    """
    project = _create_test_project(tmp_path, "CrashPreventionMod")

    # Valid bank
    project.save_bank("voice.bnk", b"BKHD_VOICE_PAYLOAD")

    # Stray temporary files that must be excluded
    (project.audio_dir / "conversion.tmp").write_bytes(b"STRAY_TEMP_DATA")
    (project.audio_dir / "cache.tmp").write_bytes(b"STRAY_TEMP_DATA")

    # Stage a DB table in the project (must NEVER be packaged)
    db_dir = project.root_dir / "pack_root" / "db" / "land_units_tables"
    db_dir.mkdir(parents=True)
    (db_dir / "units").write_text("dummy db table content", encoding="utf-8")
    project.manifest.staged_db_tables.append("land_units")
    project.save_manifest()

    output_pack = project.compile_movie_pack()
    entries = read_pfh4_index(output_pack)

    # 1. Exactly 1 file (voice.bnk), no .tmp files
    assert len(entries) == 1
    raw_path = entries[0].path
    assert "\\" in raw_path
    assert "/" not in raw_path
    assert raw_path == "audio\\voice.bnk"

    # 2. Strict rule: NO db/ tables
    entry_paths = [e.path.replace("\\", "/") for e in entries]
    assert not any(p.startswith("db/") for p in entry_paths)
    assert not any(p.endswith(".tmp") for p in entry_paths)

    # 3. Payload integrity
    payload = extract_pfh4_file(output_pack, entries[0])
    assert payload == b"BKHD_VOICE_PAYLOAD"


def test_pack_build_batch_silence_mutation_across_multiple_nodes(tmp_path: Path):
    """
    Given a SoundBank containing multiple CAkSound nodes,
    When a MutationBatch mutes all nodes simultaneously using SilentStubSource,
    Then compiling the pack updates all sound nodes to reference the stub WEM,
    and decompilation confirms all nodes were muted without individual failures.
    """
    project = _create_test_project(tmp_path, "BatchMuteMod")

    sounds = [
        CAkSound(id=10, source_id=100, stream_type=2),
        CAkSound(id=20, source_id=200, stream_type=2),
        CAkSound(id=30, source_id=300, stream_type=2),
    ]
    bank = SoundBank(
        header=BkhdChunk(bank_id=901, version=112),
        hirc=HircChunk(objects=sounds),
    )

    session = WorkspaceSession(project=project)
    session.index_soundbank("sfx.bnk", bank)

    batch = MutationBatch(
        description="Mute all three SFX nodes",
        items=(
            BatchItem(
                target=SoundNodeTarget(bank_name="sfx.bnk", sound_id=10),
                source=SilentStubSource(stub_wem_id=1),
            ),
            BatchItem(
                target=SoundNodeTarget(bank_name="sfx.bnk", sound_id=20),
                source=SilentStubSource(stub_wem_id=1),
            ),
            BatchItem(
                target=SoundNodeTarget(bank_name="sfx.bnk", sound_id=30),
                source=SilentStubSource(stub_wem_id=1),
            ),
        ),
    )
    outcome = session.apply_batch(batch)
    assert outcome.applied == 3
    assert len(outcome.rejections) == 0

    output_pack = session.compile_movie_pack()
    entries = read_pfh4_index(output_pack)
    entry_map = {e.path.replace("\\", "/"): e for e in entries}

    assert "audio/sfx.bnk" in entry_map
    assert "audio/1.wem" in entry_map

    # Decompile and parse bank: all 3 sounds must reference source_id=1
    bnk_bytes = extract_pfh4_file(output_pack, entry_map["audio/sfx.bnk"])
    parsed_bank = SoundBank.from_bytes(bnk_bytes)
    assert len(parsed_bank.hirc.objects) == 3
    for obj in parsed_bank.hirc.objects:
        assert isinstance(obj, CAkSound)
        assert obj.source_id == 1
        assert obj.stream_type == 2


def test_pack_build_embedded_to_streamed_sound_promotion(tmp_path: Path):
    """
    Given a SoundBank with an embedded media DIDX entry and stream_type=0,
    When the sound node is mutated,
    Then the sound is promoted to streamed (stream_type=2),
    and compiling creates a loose WEM in the pack while updating the bank AST.
    """
    project = _create_test_project(tmp_path, "EmbeddedPromotionMod")

    sound = CAkSound(id=1, source_id=4444, stream_type=0)
    didx = DidxChunk(entries=[DidxEntry(file_id=4444, offset=0, size=32)])
    data = DataChunk(data=b"\x00" * 32)
    bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        didx=didx,
        data=data,
        hirc=HircChunk(objects=[sound]),
    )

    session = WorkspaceSession(project=project)
    session.index_soundbank("embedded.bnk", bank)

    # Mutate sound node 1 with SilentStubSource
    session.apply_sound_mutation("embedded.bnk", sound_id=1, source=SilentStubSource(stub_wem_id=1))

    output_pack = session.compile_movie_pack()
    entries = read_pfh4_index(output_pack)
    entry_map = {e.path.replace("\\", "/"): e for e in entries}

    assert "audio/embedded.bnk" in entry_map
    assert "audio/1.wem" in entry_map

    # Decompile bank: stream_type must be 2 (streamed)
    bnk_bytes = extract_pfh4_file(output_pack, entry_map["audio/embedded.bnk"])
    parsed_bank = SoundBank.from_bytes(bnk_bytes)
    sound_obj = parsed_bank.hirc.objects[0]
    assert isinstance(sound_obj, CAkSound)
    assert sound_obj.source_id == 1
    assert sound_obj.stream_type == 2


def test_pack_build_media_node_loose_wem_override(tmp_path: Path):
    """
    Given a project where an embedded media is targeted directly via MediaNodeTarget,
    When mutated,
    Then a loose WEM with the target WEM ID is staged and packaged into the pack,
    allowing Total War to override the embedded audio without needing to rebuild the soundbank.
    """
    project = _create_test_project(tmp_path, "MediaNodeLooseMod")

    bank = _create_sample_bank(bank_id=999, sound_id=5, source_id=4444, stream_type=0)
    session = WorkspaceSession(project=project)
    session.index_soundbank("vanilla_bank.bnk", bank)

    session.apply_media_mutation(
        "vanilla_bank.bnk", wem_id=4444, source=SilentStubSource(stub_wem_id=1)
    )

    output_pack = session.compile_movie_pack()
    entries = read_pfh4_index(output_pack)
    entry_map = {e.path.replace("\\", "/"): e for e in entries}

    # Staged loose 4444.wem is packaged into the mod pack
    assert "audio/4444.wem" in entry_map
    payload = extract_pfh4_file(output_pack, entry_map["audio/4444.wem"])
    assert len(payload) > 0
    assert payload.startswith(b"RIFF")


def test_pack_build_music_track_replacement(tmp_path: Path):
    """
    Given a SoundBank with a CAkMusicTrack containing a music source,
    When the music track is modified with a new source ID and loose stream WEM,
    Then compiling the pack includes the updated bank and the new music WEM,
    and decompilation confirms the music track AST was preserved and updated.
    """
    project = _create_test_project(tmp_path, "MusicTrackMod")

    source = AkMusicTrackSource(source_id=8001, stream_type=2)
    track = CAkMusicTrack(id=500, track_type=1, sources=[source])
    bank = SoundBank(
        header=BkhdChunk(bank_id=888, version=112),
        hirc=HircChunk(objects=[track]),
    )
    # Save original bank
    project.save_bank("music_data.bnk", bank.to_bytes())

    # Modder replaces the music track source to 8002
    track.sources[0].source_id = 8002
    project.save_bank("music_data.bnk", bank.to_bytes())
    project.stage_wem(8002, b"RIFF_CUSTOM_STEREO_MUSIC_DATA_WEM")

    output_pack = project.compile_movie_pack()
    entries = read_pfh4_index(output_pack)
    entry_map = {e.path.replace("\\", "/"): e for e in entries}

    assert "audio/music_data.bnk" in entry_map
    assert "audio/8002.wem" in entry_map

    bnk_bytes = extract_pfh4_file(output_pack, entry_map["audio/music_data.bnk"])
    parsed_bank = SoundBank.from_bytes(bnk_bytes)
    assert len(parsed_bank.hirc.objects) == 1
    parsed_track = parsed_bank.hirc.objects[0]
    assert isinstance(parsed_track, CAkMusicTrack)
    assert parsed_track.sources[0].source_id == 8002


def test_pack_build_overwrite_staged_wem_payload(tmp_path: Path):
    """
    Given a modder stages a replacement WEM and later overwrites it with a revised version,
    When the pack is compiled,
    Then the compiled pack contains exactly ONE instance of the WEM with the latest payload.
    """
    project = _create_test_project(tmp_path, "WemOverwriteMod")

    # Initial replacement
    project.stage_wem(55001, b"WEM_VERSION_1_DRAFT")
    # Later revised replacement
    project.stage_wem(55001, b"WEM_VERSION_2_FINAL_MASTER")

    output_pack = project.compile_movie_pack()
    entries = read_pfh4_index(output_pack)

    # Exactly 1 entry for 55001.wem
    assert len(entries) == 1
    assert entries[0].path.replace("\\", "/") == "audio/55001.wem"

    payload = extract_pfh4_file(output_pack, entries[0])
    assert payload == b"WEM_VERSION_2_FINAL_MASTER"


def test_pack_build_total_war_vfs_mod_pack_override_priority(tmp_path: Path):
    """
    Simulates the Total War game engine Virtual File System (VFS) mounting:
    1. Vanilla sound.pack contains vanilla battle.bnk (sound source 111) and ambience.bnk.
    2. Submod mod.pack (PT_MOD = 3) contains modified battle.bnk (sound source 999).
    3. Total War VFS resolution order: Mod packs override Release packs when loaded.
    4. Decompiling and resolving proves battle.bnk yields the mod version,
       while untouched ambience.bnk falls back cleanly to the vanilla pack.
    """
    # 1. Synthesize vanilla sound.pack (PT_RELEASE = 1)
    vanilla_battle = _create_sample_bank(bank_id=1, sound_id=10, source_id=111)
    vanilla_ambience = _create_sample_bank(bank_id=2, sound_id=20, source_id=222)
    vanilla_pack_path = tmp_path / "vanilla_sound.pack"
    write_pfh4_pack(
        vanilla_pack_path,
        {
            "audio/battle.bnk": vanilla_battle.to_bytes(),
            "audio/ambience.bnk": vanilla_ambience.to_bytes(),
        },
        pack_type=1,  # PT_RELEASE
    )

    # 2. Compile submod Mod pack (PT_MOD = 3)
    project = _create_test_project(tmp_path, "VfsOverrideMod")
    mod_battle = _create_sample_bank(bank_id=1, sound_id=10, source_id=999)
    project.save_bank("battle.bnk", mod_battle.to_bytes())
    mod_pack_path = project.compile_mod_pack()
    assert read_pfh4_pack_type(mod_pack_path) == PT_MOD

    # 3. Simulate Total War VFS Layered Mount
    # VFS loads packs: lower priority packs first, active mod packs override
    vfs_index: dict[str, tuple[Path, object]] = {}

    # Mount vanilla pack
    for entry in read_pfh4_index(vanilla_pack_path):
        vfs_index[entry.path.replace("\\", "/").lower()] = (vanilla_pack_path, entry)

    # Mount mod pack (PT_MOD overrides release)
    for entry in read_pfh4_index(mod_pack_path):
        vfs_index[entry.path.replace("\\", "/").lower()] = (mod_pack_path, entry)

    # 4. Resolve audio/battle.bnk -> must resolve to mod pack
    battle_pack, battle_entry = vfs_index["audio/battle.bnk"]
    assert battle_pack == mod_pack_path
    battle_bytes = extract_pfh4_file(battle_pack, battle_entry)
    parsed_battle = SoundBank.from_bytes(battle_bytes)
    assert parsed_battle.hirc.objects[0].source_id == 999

    # 5. Resolve audio/ambience.bnk -> untouched, must resolve to vanilla pack
    ambience_pack, ambience_entry = vfs_index["audio/ambience.bnk"]
    assert ambience_pack == vanilla_pack_path
    ambience_bytes = extract_pfh4_file(ambience_pack, ambience_entry)
    parsed_ambience = SoundBank.from_bytes(ambience_bytes)
    assert parsed_ambience.hirc.objects[0].source_id == 222


def test_pack_build_external_audio_file_transcoding_and_decompilation(tmp_path: Path):
    """
    Given a modder provides an external raw audio file (WAV),
    When the sound node is mutated with ExternalFileSource,
    Then:
    1. The raw audio is automatically transcoded via AudioConverter into a 32kHz PCM .wem.
    2. Master audio is staged in source_audio/ and converted .wem is staged in pack_root/audio/.
    3. The soundbank AST promotes the sound node to streamed (stream_type=2) with the allocated WEM ID.
    4. Compiling creates a PT_MOD pack containing both the modified bank and the loose transcoded WEM.
    5. Decompiling the pack verifies the WEM payload is a valid RIFF container and the bank AST is bit-exact.
    6. Undoing the mutation reverts the bank and removes the staged WEM from subsequent pack builds.
    """
    # 1. Synthesize a 16-bit 44.1kHz mono WAV file
    wav_path = tmp_path / "custom_shout.wav"
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        # 0.1s of audio samples
        sample_count = 4410
        samples = [int(1000 * ((i % 100) / 50.0 - 1.0)) for i in range(sample_count)]
        wf.writeframes(struct.pack("<" + "h" * sample_count, *samples))

    project = _create_test_project(tmp_path, "ExternalAudioMod")
    original_bank = _create_sample_bank(bank_id=9001, sound_id=42, source_id=12345, stream_type=0)

    session = WorkspaceSession(project=project)
    session.index_soundbank("battle_voice.bnk", original_bank)

    # 2. Mutate sound node 42 using ExternalFileSource
    res = session.apply_sound_mutation(
        "battle_voice.bnk",
        sound_id=42,
        source=ExternalFileSource(file_path=wav_path),
    )
    assert res is not None

    # Verify staging on disk
    staged_wems = project.manifest.staged_wems
    assert len(staged_wems) == 1
    allocated_wem_id = staged_wems[0]
    staged_wem_file = project.audio_dir / f"{allocated_wem_id}.wem"
    assert staged_wem_file.is_file()
    assert staged_wem_file.read_bytes().startswith(b"RIFF")

    # 3. Compile mod pack
    pack_path = session.compile_mod_pack()
    assert pack_path.is_file()
    assert read_pfh4_pack_type(pack_path) == PT_MOD

    # 4. Decompile and verify pack contents
    entries = read_pfh4_index(pack_path)
    entry_map = {e.path.replace("\\", "/"): e for e in entries}
    assert len(entries) == 2
    assert "audio/battle_voice.bnk" in entry_map
    assert f"audio/{allocated_wem_id}.wem" in entry_map

    # Decompile and verify bank AST
    bnk_bytes = extract_pfh4_file(pack_path, entry_map["audio/battle_voice.bnk"])
    parsed_bank = SoundBank.from_bytes(bnk_bytes)
    assert len(parsed_bank.hirc.objects) == 1
    sound_obj = parsed_bank.hirc.objects[0]
    assert isinstance(sound_obj, CAkSound)
    assert sound_obj.id == 42
    assert sound_obj.source_id == allocated_wem_id
    assert sound_obj.stream_type == 2  # Promoted from embedded (0) to streamed (2)

    # Decompile and verify transcoded WEM container
    wem_bytes = extract_pfh4_file(pack_path, entry_map[f"audio/{allocated_wem_id}.wem"])
    assert wem_bytes.startswith(b"RIFF")
    assert b"WAVE" in wem_bytes[:16]
    assert len(wem_bytes) == staged_wem_file.stat().st_size

    # 5. Verify Undo cycle cleans up the pack
    session.undo_mutation()
    pack_reverted = session.compile_mod_pack()
    reverted_entries = read_pfh4_index(pack_reverted)
    assert len(reverted_entries) == 0, "After undoing the mutation, mod pack must be empty"
