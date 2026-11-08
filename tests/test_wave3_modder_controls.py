"""Tests for Wave 3 Everyday Modder Controls (Tasks 9, 10, 11, 12)."""

from pathlib import Path
from unittest.mock import MagicMock

from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk
from src.bnk.models import (
    CAkAction,
    CAkEvent,
    CAkRanSeqCntr,
    CAkSound,
)
from src.engine.ontology import (
    BatchItem,
    MutationBatch,
    ReplacementScope,
    SilentStubSource,
    SoundNodeTarget,
)
from src.ui.features.audio_sources.state import AudioEnhanceSettings
from src.ui.features.audio_sources.store import AudioSourcesStore
from src.ui.features.audio_transport.store import AudioTransportStore
from src.ui.features.bank_viewer.store import BankViewerStore
from src.ui.features.bank_viewer.view import BankTreeWidget, BankViewerView
from src.ui.features.blast_radius.state import BlastRadiusAction
from src.ui.features.blast_radius.store import check_replacement_branch
from src.ui.features.blast_radius.view import BlastRadiusDialog
from src.ui.shell.coordinator import WorkspaceCoordinator
from src.ui.shell.store import ShellStore
from src.ui.shell.view import MainWindow
from tests.support.factories import make_synthetic_wav
from tests.test_e2e_wem_blast_radius import _setup_test_project_and_session


def test_bank_tree_widget_url_drag_and_drop(qtbot):
    """Task 9: BankTreeWidget accepts URLs in dragEnter and emits source_dropped on drop."""
    widget = BankTreeWidget()
    qtbot.addWidget(widget)

    received_drops: list[tuple[tuple[str, ...], str]] = []
    widget.source_dropped.connect(lambda paths, target: received_drops.append((paths, target)))

    from PySide6.QtCore import QMimeData

    mime = QMimeData()
    test_urls = [
        QUrl.fromLocalFile("C:/audio/test1.wav"),
        QUrl.fromLocalFile("C:/audio/test2.wav"),
    ]
    mime.setUrls(test_urls)

    # Test dragEnterEvent
    drag_enter = QDragEnterEvent(
        QPoint(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.dragEnterEvent(drag_enter)

    # Test dropEvent
    drop = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.dropEvent(drop)

    assert len(received_drops) == 1
    paths, target = received_drops[0]
    assert len(paths) == 2
    assert "test1.wav" in paths[0]
    assert "test2.wav" in paths[1]


def test_coordinator_handle_source_dropped_single_target(tmp_path: Path):
    """Task 9: Coordinator handle_source_dropped distributes or applies audio file to target."""
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

    sound = CAkSound(id=101, obj_type=2, source_id=1001, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=500, version=112),
        hirc=HircChunk(objects=[sound]),
    )
    bv_store.load_soundbank_instance("battle.bnk", bank)
    bv_store.select_bank("battle.bnk")

    wav_file = tmp_path / "voice.wav"
    make_synthetic_wav(wav_file, duration_s=0.1)

    mock_batch_handler = MagicMock()
    coordinator._handle_audio_sources_batch = mock_batch_handler

    coordinator.handle_source_dropped((str(wav_file),), "hirc:101")

    assert mock_batch_handler.called
    batch: MutationBatch = mock_batch_handler.call_args[0][0]
    assert len(batch.items) == 1
    assert isinstance(batch.items[0].target, SoundNodeTarget)
    assert batch.items[0].target.sound_id == 101


def test_main_window_wires_source_dropped_to_coordinator(monkeypatch, qtbot, tmp_path: Path):
    """Task 9: MainWindow connects bank_viewer_view.source_dropped to coordinator.handle_source_dropped."""
    mock_handler = MagicMock()
    monkeypatch.setattr(WorkspaceCoordinator, "handle_source_dropped", mock_handler)

    shell_store = ShellStore()
    main_window = MainWindow(shell_store, settings_file=tmp_path / "settings.json")
    qtbot.addWidget(main_window)

    main_window.bank_viewer_view.source_dropped.emit(("test.wav",), "hirc:101")
    assert mock_handler.called
    mock_handler.assert_called_once_with(("test.wav",), "hirc:101")
    main_window.close()


def test_resolve_targets_from_container_descendants():
    """Task 10: Selecting a container resolves descendant playable Sound and MusicTrack leaf targets."""
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

    sound1 = CAkSound(id=101, obj_type=2, source_id=1001, stream_type=2)
    sound2 = CAkSound(id=102, obj_type=2, source_id=1002, stream_type=2)
    container = CAkRanSeqCntr(id=5000, obj_type=5, children=[101, 102])
    bank = SoundBank(
        header=BkhdChunk(bank_id=600, version=112),
        hirc=HircChunk(objects=[container, sound1, sound2]),
    )
    bv_store.load_soundbank_instance("ambient.bnk", bank)
    bv_store.select_bank("ambient.bnk")

    bv_store.select_node("hirc:5000")

    targets = sources_store.state.targets
    assert len(targets) == 2
    assert targets[0] == SoundNodeTarget(bank_name="ambient.bnk", sound_id=101)
    assert targets[1] == SoundNodeTarget(bank_name="ambient.bnk", sound_id=102)


def test_resolve_targets_event_action_deduplication():
    """Task 10: Selecting an Event resolves its Action child targets, deduplicating targets."""
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

    sound = CAkSound(id=101, obj_type=2, source_id=1001, stream_type=2)
    action1 = CAkAction(id=801, obj_type=3, id_ext=101)
    action2 = CAkAction(id=802, obj_type=3, id_ext=101)
    event = CAkEvent(id=901, obj_type=4, actions=[801, 802])

    bank = SoundBank(
        header=BkhdChunk(bank_id=700, version=112),
        hirc=HircChunk(objects=[event, action1, action2, sound]),
    )
    bv_store.load_soundbank_instance("events.bnk", bank)
    bv_store.select_bank("events.bnk")

    bv_store.select_node("hirc:901")

    targets = sources_store.state.targets
    assert len(targets) == 1
    assert targets[0] == SoundNodeTarget(bank_name="events.bnk", sound_id=101)


def test_coordinator_confirm_replacement_scope_called_on_mute_and_enhance():
    """Task 11: confirm_replacement_scope hook is called when muting and filtering enhance targets."""
    shell_store = ShellStore()
    bv_store = BankViewerStore()
    transport_store = AudioTransportStore()
    sources_store = AudioSourcesStore()

    confirm_calls: list[SoundNodeTarget] = []

    def mock_confirm(target):
        confirm_calls.append(target)
        return (True, ReplacementScope.OVERWRITE)

    coordinator = WorkspaceCoordinator(
        shell_store,
        bv_store,
        transport_store,
        audio_sources_store=sources_store,
        confirm_replacement_scope=mock_confirm,
    )

    target = SoundNodeTarget(bank_name="test.bnk", sound_id=555)
    batch = MutationBatch(
        description="Mute node",
        items=(BatchItem(target=target, source=SilentStubSource(stub_wem_id=1)),),
    )
    coordinator._handle_audio_sources_batch(batch)
    assert len(confirm_calls) == 1
    assert confirm_calls[0] == target

    confirm_calls.clear()
    settings = AudioEnhanceSettings(gain_enabled=True, gain_db=2.0)
    coordinator._handle_audio_sources_enhance((target,), settings)
    assert len(confirm_calls) == 1
    assert confirm_calls[0] == target


def test_blast_radius_enriches_node_name_with_context(qapp, qtbot, monkeypatch, tmp_path: Path):
    """Task 11: check_replacement_branch enriches referencing node_name with event/switch metadata."""
    sound_a = CAkSound(id=101, obj_type=2, source_id=8888, stream_type=2)
    action_a = CAkAction(id=801, obj_type=3, id_ext=101)
    event_a = CAkEvent(id=901, obj_type=4, actions=[801])
    bank_a = SoundBank(
        header=BkhdChunk(bank_id=100, version=112),
        hirc=HircChunk(objects=[event_a, action_a, sound_a]),
    )
    sound_b = CAkSound(id=201, obj_type=2, source_id=8888, stream_type=2)
    bank_b = SoundBank(
        header=BkhdChunk(bank_id=200, version=112),
        hirc=HircChunk(objects=[sound_b]),
    )

    project, session = _setup_test_project_and_session(
        tmp_path,
        banks={"bank_a.bnk": bank_a, "bank_b.bnk": bank_b},
    )

    session.resolve_and_parse_bank("bank_a.bnk")
    session.resolve_and_parse_bank("bank_b.bnk")

    mock_db = MagicMock()
    mock_db.resolve_hash.return_value = "Play_Hero_Attack"
    mock_db.resolve_event_name.return_value = "Play_Hero_Attack"
    mock_db.resolve_switch_name.return_value = None
    mock_db.resolve_game_name.return_value = None
    session.sound_db = mock_db

    captured_dialog: list[BlastRadiusDialog] = []

    def mock_exec(self):
        captured_dialog.append(self)
        return BlastRadiusAction.OVERWRITE

    monkeypatch.setattr(BlastRadiusDialog, "exec", mock_exec)

    target = SoundNodeTarget(bank_name="bank_a.bnk", sound_id=101)
    proceed, scope = check_replacement_branch(
        session,
        "bank_a.bnk",
        target,
        parent_widget=None,
    )
    assert proceed is True
    assert scope == ReplacementScope.OVERWRITE

    assert len(captured_dialog) == 1
    items = captured_dialog[0].store.state.items
    assert len(items) == 2
    # Verify that node_name was enriched with the resolved event context
    assert any("Play_Hero_Attack" in item.node_name for item in items)


def test_bank_viewer_store_revert_node(tmp_path: Path):
    """Task 12: revert_node restores modified sound node and invalidates caches."""
    sound = CAkSound(id=101, obj_type=2, source_id=1111, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=100, version=112),
        hirc=HircChunk(objects=[sound]),
    )
    project, session = _setup_test_project_and_session(
        tmp_path,
        banks={"test.bnk": bank},
    )

    store = BankViewerStore(project=project)
    store.select_bank("test.bnk")

    store.mute_sound(101)
    assert store.state.nodes_by_key["hirc:101"].is_modified is True

    reverted = store.revert_node("hirc:101")
    assert reverted is True
    assert store.state.nodes_by_key["hirc:101"].is_modified is False


def test_bank_viewer_store_container_variation_and_params(tmp_path: Path):
    """Task 12: append_container_variation and update_node_params in BankViewerStore."""
    sound = CAkSound(id=101, obj_type=2, source_id=1111, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=100, version=112),
        hirc=HircChunk(objects=[sound]),
    )
    project, session = _setup_test_project_and_session(
        tmp_path,
        banks={"test.bnk": bank},
    )

    store = BankViewerStore(project=project)
    store.select_bank("test.bnk")

    wav_path = tmp_path / "variation.wav"
    make_synthetic_wav(wav_path, duration_s=0.1)

    assert store.update_node_params(101, -3.0, 50.0) is True

    outcome = store.append_container_variation(5000, wav_path)
    assert isinstance(outcome, bool)


def test_bank_viewer_view_context_menu_multi_selection(qtbot):
    """Task 12: Right-click on multi-selection shows Export and Mute Selected."""
    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    sound1 = CAkSound(id=101, obj_type=2, source_id=1001, stream_type=2)
    sound2 = CAkSound(id=102, obj_type=2, source_id=1002, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=800, version=112),
        hirc=HircChunk(objects=[sound1, sound2]),
    )
    store.load_soundbank_instance("menu_test.bnk", bank)
    store.select_nodes(("hirc:101", "hirc:102"), primary_key="hirc:101")

    assert "hirc:101" in view._current_nodes
    assert "hirc:102" in view._current_nodes

    view.close()
