"""Headless tests for WorkspaceCoordinator cross-store orchestration."""

import ast
from pathlib import Path

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk, DataChunk, DidxChunk, DidxEntry
from src.bnk.models import CAkSound
from src.engine.ontology import (
    BatchItem,
    MediaNodeTarget,
    MutationBatch,
    MutationRecord,
    SilentStubSource,
    SoundNodeTarget,
)
from src.ui.features.audio_sources.state import AudioEnhanceSettings, AudioSourcesTab
from src.ui.features.audio_sources.store import AudioSourcesStore
from src.ui.features.audio_transport.store import AudioTransportStore
from src.ui.features.bank_viewer.store import BankViewerStore
from src.ui.shell.coordinator import WorkspaceCoordinator
from src.ui.shell.store import ShellStore
from src.workspace.game import GameType
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject
from src.workspace.storage import ProjectStorage


def test_coordinator_zero_qt_imports():
    """Verify WorkspaceCoordinator module contains ZERO PySide or PyQt imports."""
    coord_file = Path(__file__).parents[1] / "src" / "ui" / "shell" / "coordinator.py"
    tree = ast.parse(coord_file.read_text(encoding="utf-8"), filename=str(coord_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(("PySide", "PyQt")), (
                    f"Banned import in coordinator.py: {alias.name}"
                )
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert not node.module.startswith(("PySide", "PyQt")), (
                    f"Banned import in coordinator.py: {node.module}"
                )


def test_coordinator_initial_state():
    """Verify coordinator starts in clean state with empty undo/redo stacks."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()

    coordinator = WorkspaceCoordinator(shell_store, bv_store, transport_store)

    assert coordinator._active_project is None
    assert coordinator._last_selected_bank_name is None
    assert coordinator._last_selected_node_key is None
    assert coordinator._last_selected_node_details is None
    assert coordinator.can_undo is False
    assert coordinator.can_redo is False
    assert coordinator.undo_status_tip == "Undo last selection or view navigation"
    assert coordinator.redo_status_tip == "Redo last selection or view navigation"
    assert transport_store.state.active_track is None


def test_coordinator_project_lifecycle(tmp_path: Path):
    """Verify opening and closing projects loads and resets bank_viewer_store."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    coordinator = WorkspaceCoordinator(shell_store, bv_store, transport_store)

    proj_dir = tmp_path / "CoordTestMod"
    proj_dir.mkdir(parents=True)
    (proj_dir / "pack_root" / "audio").mkdir(parents=True)
    manifest = ProjectManifest(name="CoordTestMod", game=GameType.ATTILA)
    proj = AudioProject(root_dir=proj_dir, manifest=manifest)

    # 1. Open project in shell store
    shell_store.open_project(proj)
    assert coordinator._active_project is proj
    assert bv_store.project is proj

    # 2. Close project in shell store
    shell_store.close_project()
    assert coordinator._active_project is None
    assert bv_store.project is None
    assert transport_store.state.active_track is None


def test_coordinator_bank_selection_resets_track_and_node():
    """Verify changing selected bank in bank_viewer_store resets active audio track."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    coordinator = WorkspaceCoordinator(shell_store, bv_store, transport_store)

    # Simulate bank selection
    bv_store.select_bank("bank_alpha.bnk")
    assert coordinator._last_selected_bank_name == "bank_alpha.bnk"
    assert coordinator._last_selected_node_key is None
    assert transport_store.state.active_track is None

    # Switch to another bank
    bv_store.select_bank("bank_beta.bnk")
    assert coordinator._last_selected_bank_name == "bank_beta.bnk"
    assert coordinator._last_selected_node_key is None
    assert transport_store.state.active_track is None


def test_coordinator_node_selection_resolves_audio_track(tmp_path: Path):
    """Verify node selection in bank_viewer_store resolves and binds audio track to transport."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    coordinator = WorkspaceCoordinator(shell_store, bv_store, transport_store)

    proj_dir = tmp_path / "AudioTestMod"
    proj_dir.mkdir(parents=True)
    (proj_dir / "pack_root" / "audio").mkdir(parents=True)
    manifest = ProjectManifest(name="AudioTestMod", game=GameType.ATTILA)
    proj = AudioProject(root_dir=proj_dir, manifest=manifest)
    shell_store.open_project(proj)

    # Construct synthetic SoundBank with embedded DIDX entry
    fake_wem_bytes = b"RIFF\x14\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    bank = SoundBank(
        header=BkhdChunk(bank_id=123, version=112),
        didx=DidxChunk(entries=[DidxEntry(file_id=9999, offset=0, size=len(fake_wem_bytes))]),
        data=DataChunk(data=fake_wem_bytes),
    )

    bv_store.load_soundbank_instance("test_audio.bnk", bank)
    bv_store.select_bank("test_audio.bnk")

    # Select media node
    bv_store.select_node("media:9999")

    assert coordinator._last_selected_node_key == "media:9999"
    assert transport_store.state.active_track is not None
    assert transport_store.state.active_track.source_id == 9999


def test_coordinator_navigation_undo_redo():
    """Verify coordinator coordinates selection history back/forward navigation."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    coordinator = WorkspaceCoordinator(shell_store, bv_store, transport_store)

    # Initial state
    assert coordinator.can_undo is False
    assert coordinator.can_redo is False

    # Simulate node navigation: node A -> node B
    bv_store.select_node("nodeA")
    bv_store.select_node("nodeB")

    assert bv_store.state.can_navigate_back is True
    assert coordinator.can_undo is True
    assert coordinator.undo_status_tip == "Undo last selection or view navigation"
    assert coordinator.can_redo is False

    # Trigger undo
    coordinator.trigger_undo()
    assert bv_store.state.selected_node_key == "nodeA"
    assert coordinator.can_redo is True
    assert coordinator.redo_status_tip == "Redo last selection or view navigation"

    # Trigger redo
    coordinator.trigger_redo()
    assert bv_store.state.selected_node_key == "nodeB"


def test_coordinator_mutation_undo_redo_precedence(tmp_path: Path):
    """Verify audio mutations take precedence in undo/redo status tips and triggers."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    coordinator = WorkspaceCoordinator(shell_store, bv_store, transport_store)

    proj_dir = tmp_path / "MutationTestProj"
    proj = ProjectStorage.create_project(proj_dir, name="MutationTestProj", game=GameType.ATTILA)
    shell_store.open_project(proj)

    bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        hirc=HircChunk(objects=[]),
    )
    bank_bytes = bank.to_bytes()

    dummy_mutation = MutationRecord(
        bank_name="test.bnk",
        node_key="hirc:1",
        description="Replace sound",
        before_bank_bytes=bank_bytes,
        after_bank_bytes=bank_bytes,
    )

    # Push to mutation undo stack in session
    bv_store.session.push_mutation_record(dummy_mutation)

    assert bv_store.can_undo_mutation is True
    assert coordinator.can_undo is True
    assert coordinator.undo_status_tip == "Undo last audio mutation"

    # Trigger undo via coordinator
    coordinator.trigger_undo()
    assert bv_store.can_undo_mutation is False
    assert bv_store.can_redo_mutation is True
    assert coordinator.can_redo is True
    assert coordinator.redo_status_tip == "Redo last audio mutation"

    # Trigger redo via coordinator
    coordinator.trigger_redo()
    assert bv_store.can_undo_mutation is True
    assert bv_store.can_redo_mutation is False


def test_coordinator_routes_selection_to_audio_sources():
    """Verify selecting nodes in BankViewer updates AudioSourcesStore targets."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    sources_store = AudioSourcesStore()

    coordinator = WorkspaceCoordinator(
        shell_store,
        bv_store,
        transport_store,
        audio_sources_store=sources_store,
    )

    assert coordinator.audio_sources_store is sources_store
    assert sources_store.state.targets == ()

    # Select bank and node
    bv_store.select_bank("battle.bnk")
    bv_store.select_node("hirc:101")

    assert len(sources_store.state.targets) == 1
    assert sources_store.state.targets[0] == SoundNodeTarget(bank_name="battle.bnk", sound_id=101)

    # Multi-selection
    bv_store.select_nodes(("hirc:101", "media:202"), primary_key="hirc:101")
    assert len(sources_store.state.targets) == 2
    assert SoundNodeTarget(bank_name="battle.bnk", sound_id=101) in sources_store.state.targets
    assert MediaNodeTarget(bank_name="battle.bnk", wem_id=202) in sources_store.state.targets

    # Clear selection
    bv_store.select_node(None)
    assert sources_store.state.targets == ()


def test_coordinator_project_lifecycle_audio_sources(tmp_path: Path):
    """Verify opening and closing projects synchronizes AudioSourcesStore project state."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    sources_store = AudioSourcesStore()

    coordinator = WorkspaceCoordinator(
        shell_store,
        bv_store,
        transport_store,
        audio_sources_store=sources_store,
    )

    proj_dir = tmp_path / "AudioSourcesLifecycleMod"
    proj = ProjectStorage.create_project(
        proj_dir, name="AudioSourcesLifecycleMod", game=GameType.ATTILA
    )

    # Open project
    shell_store.open_project(proj)
    assert sources_store.project is proj

    # Select node
    bv_store.select_bank("test.bnk")
    bv_store.select_node("hirc:555")
    assert len(sources_store.state.targets) == 1

    # Close project
    shell_store.close_project()
    assert sources_store.project is None
    assert sources_store.state.targets == ()


def test_coordinator_handles_audio_sources_preview(tmp_path: Path):
    """Verify audio file preview callback in AudioSourcesStore routes to AudioTransportStore."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    sources_store = AudioSourcesStore()

    WorkspaceCoordinator(
        shell_store,
        bv_store,
        transport_store,
        audio_sources_store=sources_store,
    )

    test_wav = tmp_path / "preview_shout.wav"
    test_wav.write_bytes(b"RIFF....WAVEfmt ")

    # Dispatch preview
    assert sources_store.on_preview_file is not None  # registered by coordinator
    # Simulate preview callback invocation
    for cb in sources_store._preview_callbacks:
        cb(test_wav)

    assert transport_store.state.active_track is not None
    assert transport_store.state.active_track.title == "preview_shout.wav"
    assert transport_store.state.active_track.file_path == str(test_wav)


def test_coordinator_handles_audio_sources_batch_apply(tmp_path: Path):
    """Verify audio sources batch apply executes session.apply_batch and forwards outcome."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    sources_store = AudioSourcesStore()

    WorkspaceCoordinator(
        shell_store,
        bv_store,
        transport_store,
        audio_sources_store=sources_store,
    )

    proj_dir = tmp_path / "BatchCoordTestMod"
    proj = ProjectStorage.create_project(proj_dir, name="BatchCoordTestMod", game=GameType.ATTILA)
    shell_store.open_project(proj)

    # Create synthetic bank with sound
    from src.bnk.models import CAkSound, NodeBaseParams

    bank = SoundBank(header=BkhdChunk(bank_id=999, version=112))
    sound = CAkSound(
        id=701,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=2,
        source_id=801,
        file_id=801,
        node_base_params=NodeBaseParams(),
    )
    bank.add_sound(sound)
    bv_store.load_soundbank_instance("battle.bnk", bank)
    bv_store.select_bank("battle.bnk")
    bv_store.select_node("hirc:701")

    # Construct batch
    batch = MutationBatch(
        description="Mute target",
        items=(
            BatchItem(
                target=SoundNodeTarget(bank_name="battle.bnk", sound_id=701),
                source=SilentStubSource(),
            ),
        ),
    )

    # Invoke batch ready callbacks
    for cb in sources_store._batch_callbacks:
        cb(batch)

    assert sources_store.state.last_outcome is not None
    assert sources_store.state.last_outcome.applied == 1
    assert "battle.bnk" in sources_store.state.last_outcome.touched_banks
    assert "battle.bnk" in proj.manifest.modified_banks


def test_coordinator_handles_audio_sources_load_game_audio(tmp_path: Path):
    """Verify coordinator populates game audio catalog entries on request."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    sources_store = AudioSourcesStore()

    WorkspaceCoordinator(
        shell_store,
        bv_store,
        transport_store,
        audio_sources_store=sources_store,
    )

    proj_dir = tmp_path / "CatalogTestMod"
    proj = ProjectStorage.create_project(proj_dir, name="CatalogTestMod", game=GameType.ATTILA)
    shell_store.open_project(proj)

    from src.bnk.models import CAkSound, NodeBaseParams

    bank = SoundBank(header=BkhdChunk(bank_id=999, version=112))
    sound = CAkSound(
        id=701,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=2,
        source_id=801,
        file_id=801,
        node_base_params=NodeBaseParams(),
    )
    bank.add_sound(sound)
    bv_store.load_soundbank_instance("battle.bnk", bank)
    bv_store.select_bank("battle.bnk")

    # When switching tab to Game Audio, it triggers load
    assert len(sources_store.state.game_audio_entries) == 0
    sources_store.set_active_tab(AudioSourcesTab.GAME_AUDIO)

    assert len(sources_store.state.game_audio_entries) > 0
    assert any(
        e.wem_id == 801 and e.source_bank == "battle.bnk"
        for e in sources_store.state.game_audio_entries
    )


def test_coordinator_handles_audio_sources_load_game_audio_with_no_bank_selected(tmp_path: Path):
    """Verify coordinator handles switching to game audio when no bank has been selected yet without crashing."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    sources_store = AudioSourcesStore()

    WorkspaceCoordinator(
        shell_store,
        bv_store,
        transport_store,
        audio_sources_store=sources_store,
    )

    proj_dir = tmp_path / "CatalogNoBankMod"
    proj = ProjectStorage.create_project(proj_dir, name="CatalogNoBankMod", game=GameType.ATTILA)
    shell_store.open_project(proj)

    from src.ui.features.bank_viewer.state import BankListItem, BankStatus

    bv_store.set_available_banks(
        (BankListItem(name="battle.bnk", status=BankStatus.VANILLA, size_bytes=100, path=""),)
    )
    assert bv_store.state.selected_bank_name is None

    # Switching to Game Audio tab must safely query without AttributeError
    sources_store.set_active_tab(AudioSourcesTab.GAME_AUDIO)


def test_coordinator_batch_apply_preserves_multiselection_and_undo(tmp_path: Path):
    """Verify applying a batch mutation to multi-selected sound nodes preserves selection and undo re-selects all nodes."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    sources_store = AudioSourcesStore()

    coord = WorkspaceCoordinator(
        shell_store,
        bv_store,
        transport_store,
        audio_sources_store=sources_store,
    )

    proj_dir = tmp_path / "MultiBatchMod"
    proj = ProjectStorage.create_project(proj_dir, name="MultiBatchMod", game=GameType.ATTILA)
    shell_store.open_project(proj)

    from src.bnk.models import CAkSound, NodeBaseParams

    bank = SoundBank(header=BkhdChunk(bank_id=999, version=112))
    s1 = CAkSound(
        id=101, stream_type=2, source_id=1001, file_id=1001, node_base_params=NodeBaseParams()
    )
    s2 = CAkSound(
        id=102, stream_type=2, source_id=1002, file_id=1002, node_base_params=NodeBaseParams()
    )
    bank.add_sound(s1)
    bank.add_sound(s2)
    bv_store.load_soundbank_instance("battle.bnk", bank)
    bv_store.select_bank("battle.bnk")
    bv_store.select_nodes(("hirc:101", "hirc:102"), primary_key="hirc:101")

    assert len(sources_store.state.targets) == 2

    # Apply batch to silence both
    batch = MutationBatch(
        description="Mute both",
        items=(
            BatchItem(
                target=SoundNodeTarget(bank_name="battle.bnk", sound_id=101),
                source=SilentStubSource(),
            ),
            BatchItem(
                target=SoundNodeTarget(bank_name="battle.bnk", sound_id=102),
                source=SilentStubSource(),
            ),
        ),
    )
    for cb in sources_store._batch_callbacks:
        cb(batch)

    # Both nodes must still be selected in bank viewer state and sources store
    assert bv_store.state.selected_node_keys == ("hirc:101", "hirc:102")
    assert len(sources_store.state.targets) == 2
    assert coord.can_undo is True

    # Trigger undo
    coord.trigger_undo()

    # After undo, both nodes must still be selected and restored
    assert bv_store.state.selected_node_keys == ("hirc:101", "hirc:102")
    assert len(sources_store.state.targets) == 2
    b_loaded = bv_store.session.get_loaded_bank("battle.bnk")
    assert [o for o in b_loaded.hirc.objects if o.id == 101][0].source_id == 1001
    assert [o for o in b_loaded.hirc.objects if o.id == 102][0].source_id == 1002


def test_coordinator_handles_audio_sources_game_preview(tmp_path: Path):
    """Verify selecting a game audio catalog entry resolves audio and routes to transport."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    sources_store = AudioSourcesStore()

    WorkspaceCoordinator(
        shell_store,
        bv_store,
        transport_store,
        audio_sources_store=sources_store,
    )

    proj_dir = tmp_path / "GamePreviewMod"
    proj = ProjectStorage.create_project(proj_dir, name="GamePreviewMod", game=GameType.ATTILA)
    shell_store.open_project(proj)

    # Staged loose WEM in project overlay
    proj.stage_wem(12345, b"RIFF....WAVEfmt ")

    from src.models import AudioCatalogEntry

    entry = AudioCatalogEntry(
        wem_id=12345,
        source_bank="unit.bnk",
        is_embedded=False,
        display_name="Unit_Charge",
    )

    sources_store.select_game_audio_entry(entry)
    assert transport_store.state.active_track is not None
    assert transport_store.state.active_track.title == "Unit_Charge"
    assert transport_store.state.active_track.source_id == 12345


def test_coordinator_handles_audio_sources_embedded_game_preview(tmp_path: Path):
    """Verify selecting an embedded game audio catalog entry extracts WEM bytes from bank."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    sources_store = AudioSourcesStore()

    WorkspaceCoordinator(
        shell_store,
        bv_store,
        transport_store,
        audio_sources_store=sources_store,
    )

    proj_dir = tmp_path / "EmbeddedGamePreviewMod"
    proj = ProjectStorage.create_project(
        proj_dir, name="EmbeddedGamePreviewMod", game=GameType.ATTILA
    )
    shell_store.open_project(proj)

    # Bank with embedded DATA chunk
    bkhd = BkhdChunk(bank_id=555, version=112)
    didx = DidxChunk()
    data_raw = b"RIFF....WAVEfmt " + b"\x00" * 40
    didx.entries.append(DidxEntry(file_id=8888, offset=0, size=len(data_raw)))
    data = DataChunk(data=data_raw)
    bank = SoundBank(header=bkhd, didx=didx, data=data)

    bv_store.load_soundbank_instance("embedded.bnk", bank)

    from src.models import AudioCatalogEntry

    entry = AudioCatalogEntry(
        wem_id=8888,
        source_bank="embedded.bnk",
        is_embedded=True,
        display_name="Embedded_Sound",
    )

    sources_store.select_game_audio_entry(entry)
    assert transport_store.state.active_track is not None
    assert transport_store.state.active_track.title == "Embedded_Sound"
    assert transport_store.state.active_track.source_id == 8888
    assert transport_store.state.active_track.embedded_bytes == data_raw


def test_coordinator_independent_audio_transports(tmp_path: Path):
    """Verify bank viewer and audio sources use independent transport stores without cross-pollution."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    main_transport = AudioTransportStore()
    sources_transport = AudioTransportStore()
    sources_store = AudioSourcesStore()

    WorkspaceCoordinator(
        shell_store,
        bv_store,
        main_transport,
        audio_sources_store=sources_store,
        audio_sources_transport_store=sources_transport,
        async_preview=False,
    )

    proj_dir = tmp_path / "IndependentTransportMod"
    proj = ProjectStorage.create_project(
        proj_dir, name="IndependentTransportMod", game=GameType.ATTILA
    )
    shell_store.open_project(proj)

    # 1. Setup soundbank and select node
    fake_wem = b"RIFF....WAVEfmt "
    bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        didx=DidxChunk(
            entries=[
                DidxEntry(file_id=901, offset=0, size=len(fake_wem)),
                DidxEntry(file_id=902, offset=0, size=len(fake_wem)),
            ]
        ),
        data=DataChunk(data=fake_wem),
    )
    bv_store.load_soundbank_instance("battle.bnk", bank)
    bv_store.select_bank("battle.bnk")
    bv_store.select_node("media:901")

    # Main transport has the node, sources transport is untouched
    assert main_transport.state.active_track is not None
    assert main_transport.state.active_track.source_id == 901
    assert sources_transport.state.active_track is None

    # 2. Preview an external audio library file
    test_wav = tmp_path / "my_horn.wav"
    test_wav.write_bytes(b"RIFF....WAVEfmt ")
    for cb in sources_store._preview_callbacks:
        cb(test_wav)

    # Sources transport has the library file, main transport STILL has the tree sound!
    assert sources_transport.state.active_track is not None
    assert sources_transport.state.active_track.title == "my_horn.wav"
    assert main_transport.state.active_track.source_id == 901
    assert main_transport.state.active_track.title != "my_horn.wav"

    # 3. Preview a game audio catalog entry
    proj.stage_wem(55555, b"RIFF....WAVEfmt ")
    from src.models import AudioCatalogEntry

    entry = AudioCatalogEntry(
        wem_id=55555,
        source_bank="unit.bnk",
        is_embedded=False,
        display_name="Unit_Cheer",
    )
    sources_store.select_game_audio_entry(entry)

    # Sources transport updated to game audio entry, main transport STILL has the tree sound!
    assert sources_transport.state.active_track.title == "Unit_Cheer"
    assert sources_transport.state.active_track.source_id == 55555
    assert main_transport.state.active_track.source_id == 901

    # 4. Mutual stop: if main transport starts playing, sources transport halts
    from src.ui.features.audio_transport.structs import PlaybackStatus

    # Simulate sources playing
    sources_transport._state = type(sources_transport._state)(
        status=PlaybackStatus.PLAYING,
        active_track=sources_transport.state.active_track,
        auto_play=True,
        loop=False,
        volume=sources_transport.state.volume,
        position_ms=sources_transport.state.position_ms,
        error_message=None,
    )
    assert sources_transport.state.status == PlaybackStatus.PLAYING

    # Selecting a different node in bank viewer stops sources transport
    bv_store.select_node("media:902")

    assert sources_transport.state.status == PlaybackStatus.READY
    assert main_transport.state.active_track.source_id == 902


def test_coordinator_handles_audio_sources_enhance_preview(tmp_path: Path):
    """Verifies that WorkspaceCoordinator resolves target audio, applies DSP modifiers, and cues in sources transport."""
    import wave

    from src.engine.ontology import SoundNodeTarget
    from src.ui.features.audio_sources.state import AudioEnhanceSettings

    shell_store = ShellStore()
    bv_store = BankViewerStore()
    main_transport = AudioTransportStore()
    sources_transport = AudioTransportStore()
    sources_store = AudioSourcesStore()

    WorkspaceCoordinator(
        shell_store,
        bv_store,
        main_transport,
        audio_sources_store=sources_store,
        audio_sources_transport_store=sources_transport,
        async_preview=False,
    )

    proj_dir = tmp_path / "EnhancePreviewMod"
    proj = ProjectStorage.create_project(proj_dir, name="EnhancePreviewMod", game=GameType.ATTILA)
    shell_store.open_project(proj)

    # Setup valid PCM WAV
    buf_wav = tmp_path / "raw_sound.wav"
    with wave.open(str(buf_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(32000)
        wf.writeframes(b"\x10\x00" * 3200)  # 100ms
    wav_bytes = buf_wav.read_bytes()

    bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        didx=DidxChunk(entries=[DidxEntry(file_id=50001, offset=0, size=len(wav_bytes))]),
        data=DataChunk(data=wav_bytes),
        hirc=HircChunk(
            objects=[
                CAkSound(id=101, source_id=50001, file_id=50001, stream_type=0),
            ]
        ),
    )
    bv_store.load_soundbank_instance("battle.bnk", bank)
    bv_store.select_bank("battle.bnk")

    target = SoundNodeTarget(bank_name="battle.bnk", sound_id=101)

    # 1. Preview with Gain +3.0 dB
    settings_gain = AudioEnhanceSettings(gain_enabled=True, gain_db=3.0)
    for cb in sources_store._preview_enhance_callbacks:
        cb(target, settings_gain)

    assert sources_transport.state.active_track is not None
    assert "Enhance Preview: Sound 101" in sources_transport.state.active_track.title
    assert "+3.0 dB" in sources_transport.state.active_track.title
    assert sources_transport.state.active_track.embedded_bytes is not None
    assert len(sources_transport.state.active_track.embedded_bytes) > 0

    # 2. Preview with Normalization -1.5 dBFS
    settings_norm = AudioEnhanceSettings(normalize_enabled=True, target_peak_db=-1.5)
    for cb in sources_store._preview_enhance_callbacks:
        cb(target, settings_norm)

    assert "Norm -1.5 dBFS" in sources_transport.state.active_track.title

    # 3. Preview with no modifiers (Original)
    settings_orig = AudioEnhanceSettings()
    for cb in sources_store._preview_enhance_callbacks:
        cb(target, settings_orig)

    assert "(Original)" in sources_transport.state.active_track.title

    # 4. Clear preview
    for cb in sources_store._clear_preview_callbacks:
        cb()

    assert sources_transport.state.active_track is None


def test_coordinator_player_bound_to_active_tab(tmp_path: Path):
    """Verifies that the bottom audio sources player dynamically switches its loaded track when switching tabs."""
    import wave

    from src.ui.features.audio_sources.state import AudioEnhanceSettings, AudioSourcesTab

    shell_store = ShellStore()
    bv_store = BankViewerStore()
    main_transport = AudioTransportStore()
    sources_transport = AudioTransportStore()
    sources_store = AudioSourcesStore()

    WorkspaceCoordinator(
        shell_store,
        bv_store,
        main_transport,
        audio_sources_store=sources_store,
        audio_sources_transport_store=sources_transport,
        async_preview=False,
    )

    proj_dir = tmp_path / "TabBoundMod"
    proj = ProjectStorage.create_project(proj_dir, name="TabBoundMod", game=GameType.ATTILA)
    shell_store.open_project(proj)

    # Setup valid PCM WAV
    buf_wav = tmp_path / "raw_sound.wav"
    with wave.open(str(buf_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(32000)
        wf.writeframes(b"\x20\x00" * 3200)
    wav_bytes = buf_wav.read_bytes()

    bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        didx=DidxChunk(entries=[DidxEntry(file_id=50001, offset=0, size=len(wav_bytes))]),
        data=DataChunk(data=wav_bytes),
        hirc=HircChunk(
            objects=[
                CAkSound(id=101, source_id=50001, file_id=50001, stream_type=0),
            ]
        ),
    )
    bv_store.load_soundbank_instance("battle.bnk", bank)
    bv_store.select_bank("battle.bnk")
    bv_store.select_node("hirc:101")

    # Setup audio file in library
    lib_file = tmp_path / "custom_lib_sound.wav"
    lib_file.write_bytes(wav_bytes)

    # 1. On Libraries tab: select library file
    sources_store.set_active_tab(AudioSourcesTab.LIBRARIES)
    sources_store.select_files((lib_file,))
    assert sources_transport.state.active_track is not None
    assert sources_transport.state.active_track.title == "custom_lib_sound.wav"

    # 2. Switch to Enhance tab -> player track switches to the target sound with Enhance settings
    sources_store.set_active_tab(AudioSourcesTab.ENHANCE)
    assert sources_transport.state.active_track is not None
    assert "Enhance Preview: Sound 101" in sources_transport.state.active_track.title
    assert "(Original)" in sources_transport.state.active_track.title

    # 3. Tweak Enhance settings -> player dynamically updates with new modifiers

    sources_store.set_enhance_settings(AudioEnhanceSettings(gain_enabled=True, gain_db=5.0))
    assert sources_transport.state.active_track is not None
    assert "+5.0 dB" in sources_transport.state.active_track.title

    # 4. Switch back to Libraries tab -> player switches back to custom_lib_sound.wav
    sources_store.set_active_tab(AudioSourcesTab.LIBRARIES)
    assert sources_transport.state.active_track is not None
    assert sources_transport.state.active_track.title == "custom_lib_sound.wav"

    # 5. Deselect file in Libraries -> player clears
    sources_store.select_files(())
    assert sources_transport.state.active_track is None

    # 6. Switch back to Enhance tab -> player restores Enhance preview
    sources_store.set_active_tab(AudioSourcesTab.ENHANCE)
    assert sources_transport.state.active_track is not None
    assert "+5.0 dB" in sources_transport.state.active_track.title


def test_coordinator_base_wav_caching_and_invalidation(tmp_path: Path):
    """Verifies that base decoded WAV is cached across preview requests and invalidated on node change."""
    import wave

    shell_store = ShellStore()
    bv_store = BankViewerStore()
    main_transport = AudioTransportStore()
    sources_transport = AudioTransportStore()
    sources_store = AudioSourcesStore()

    coordinator = WorkspaceCoordinator(
        shell_store,
        bv_store,
        main_transport,
        audio_sources_store=sources_store,
        audio_sources_transport_store=sources_transport,
        async_preview=False,
    )

    proj_dir = tmp_path / "CacheTestMod"
    proj = ProjectStorage.create_project(proj_dir, name="CacheTestMod", game=GameType.ATTILA)
    shell_store.open_project(proj)

    buf_wav = tmp_path / "raw.wav"
    with wave.open(str(buf_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(32000)
        wf.writeframes(b"\x15\x00" * 1600)
    wav_bytes = buf_wav.read_bytes()

    bank = SoundBank(
        header=BkhdChunk(bank_id=888, version=112),
        didx=DidxChunk(
            entries=[
                DidxEntry(file_id=60001, offset=0, size=len(wav_bytes)),
                DidxEntry(file_id=60002, offset=0, size=len(wav_bytes)),
            ]
        ),
        data=DataChunk(data=wav_bytes),
        hirc=HircChunk(
            objects=[
                CAkSound(id=201, source_id=60001, file_id=60001, stream_type=0),
                CAkSound(id=202, source_id=60002, file_id=60002, stream_type=0),
            ]
        ),
    )
    bv_store.load_soundbank_instance("test.bnk", bank)
    bv_store.select_bank("test.bnk")

    assert coordinator._cached_base_wav is None

    # 1. Preview node 201 -> populates cache
    target201 = SoundNodeTarget(bank_name="test.bnk", sound_id=201)
    coordinator._handle_audio_sources_enhance_preview(
        target201, AudioEnhanceSettings(gain_enabled=True, gain_db=2.0)
    )
    assert coordinator._cached_base_wav is not None
    assert coordinator._cached_base_wav[0] == "test.bnk"
    assert coordinator._cached_base_wav[1] == "hirc:201"
    assert coordinator._cached_base_wav[2] == wav_bytes

    # 2. Second preview on 201 with different settings reuses cache
    cached_ref = coordinator._cached_base_wav
    coordinator._handle_audio_sources_enhance_preview(
        target201, AudioEnhanceSettings(gain_enabled=True, gain_db=4.0)
    )
    assert coordinator._cached_base_wav is cached_ref

    # 3. Selecting a different node in bank viewer invalidates cache
    bv_store.select_node("hirc:202")
    assert coordinator._cached_base_wav is None


def test_coordinator_async_preview_generation(tmp_path: Path):
    """Verifies that async_preview=True processes in a background thread and updates the transport track."""
    import wave

    shell_store = ShellStore()
    bv_store = BankViewerStore()
    main_transport = AudioTransportStore()
    sources_transport = AudioTransportStore()
    sources_store = AudioSourcesStore()

    coordinator = WorkspaceCoordinator(
        shell_store,
        bv_store,
        main_transport,
        audio_sources_store=sources_store,
        audio_sources_transport_store=sources_transport,
        async_preview=True,
    )

    proj_dir = tmp_path / "AsyncTestMod"
    proj = ProjectStorage.create_project(proj_dir, name="AsyncTestMod", game=GameType.ATTILA)
    shell_store.open_project(proj)

    buf_wav = tmp_path / "raw_async.wav"
    with wave.open(str(buf_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(32000)
        wf.writeframes(b"\x10\x00" * 1600)
    wav_bytes = buf_wav.read_bytes()

    bank = SoundBank(
        header=BkhdChunk(bank_id=999, version=112),
        didx=DidxChunk(entries=[DidxEntry(file_id=70001, offset=0, size=len(wav_bytes))]),
        data=DataChunk(data=wav_bytes),
        hirc=HircChunk(
            objects=[
                CAkSound(id=301, source_id=70001, file_id=70001, stream_type=0),
            ]
        ),
    )
    bv_store.load_soundbank_instance("async.bnk", bank)
    bv_store.select_bank("async.bnk")

    target = SoundNodeTarget(bank_name="async.bnk", sound_id=301)
    coordinator._handle_audio_sources_enhance_preview(
        target, AudioEnhanceSettings(gain_enabled=True, gain_db=6.0)
    )

    coordinator.wait_for_preview(timeout=3.0)
    assert sources_transport.state.active_track is not None
    assert "+6.0 dB" in sources_transport.state.active_track.title
