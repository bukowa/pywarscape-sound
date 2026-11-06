import wave
from pathlib import Path

import pytest

from src.bnk.bank import SoundBank
from src.bnk.models import CAkSound, NodeBaseParams
from src.ui.features.bank_viewer.state import InspectorProperty, NodeInspectorDetails
from src.ui.features.bank_viewer.store import BankViewerStore
from src.ui.features.bank_viewer.view import BankViewerView
from src.ui.features.bank_viewer.views.sound_view import SoundInspectorView
from src.workspace.project import AudioProject


@pytest.fixture
def sample_wav(tmp_path: Path) -> Path:
    wav_path = tmp_path / "test_shout.wav"
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(32000)
        wf.writeframes(b"\x00\x00" * 3200)  # 100ms
    return wav_path


def test_sound_inspector_view_buttons(qtbot):
    view = SoundInspectorView()
    qtbot.addWidget(view)

    # Initial state without details: buttons disabled
    view.render(None)
    assert not view.btn_reference.isEnabled()
    assert not view.btn_export.isEnabled()

    # Render with sound details
    details = NodeInspectorDetails(
        node_key="hirc:204996993",
        object_id=204996993,
        hex_id="0x0C381401",
        object_type="Sound",
        name="Sound_204996993",
        properties=(
            InspectorProperty(category="Audio", label="Stream Type", value="Embedded"),
            InspectorProperty(category="Audio", label="Source Media ID", value="174224638"),
        ),
    )
    view.render(details)
    assert view.btn_reference.isEnabled()
    assert view.btn_export.isEnabled()
    assert view.btn_export.text() == "Export WAV..."

    # Test export signal
    with qtbot.waitSignal(view.export_requested, timeout=1000) as blocker:
        view.btn_export.click()
    assert blocker.args == [204996993]


def test_sound_inspector_view_multiselection_text(qtbot):
    view = SoundInspectorView()
    qtbot.addWidget(view)

    details = NodeInspectorDetails(
        node_key="hirc:204996993",
        object_id=204996993,
        hex_id="0x0C381401",
        object_type="Sound",
        name="Sound_204996993",
        properties=(),
    )

    # 1. Single selection
    view.render(details, selected_count=1)
    assert view.btn_export.text() == "Export WAV..."

    # 2. Multi selection (e.g. 5 nodes selected)
    view.render(details, selected_count=5)
    assert view.btn_export.text() == "Export WAV (5)..."


def test_store_replace_audio_and_playback_resolution(test_project: AudioProject, sample_wav: Path):
    sound = CAkSound(
        id=204996993,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=0,  # Embedded
        source_id=174224638,
        file_id=174224638,
        node_base_params=NodeBaseParams(),
    )
    bank = SoundBank()
    bank.header.bank_id = 999
    bank.add_sound(sound)

    store = BankViewerStore(project=test_project)
    store.load_soundbank_instance("battle_rain.bnk", bank)
    store.select_bank("battle_rain.bnk")

    # Perform replace
    success = store.replace_sound_audio(204996993, sample_wav)
    assert success is True

    # Bank must be marked modified
    assert "battle_rain.bnk" in test_project.manifest.modified_banks
    assert (test_project.audio_dir / "174224638.wem").is_file()

    # Audio track resolver must now find the staged WEM
    track = store.resolve_audio_track("hirc:204996993")
    assert track is not None
    assert track.file_path is not None
    assert Path(track.file_path).name == "174224638.wem"

    # Mute test
    mute_success = store.mute_sound(204996993)
    assert mute_success is True
    assert sound.file_id == 1
    assert (test_project.audio_dir / "1.wem").is_file()


def test_view_user_mute_interaction(qtbot, test_project: AudioProject):
    sound = CAkSound(
        id=123456,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=2,
        source_id=55555,
        file_id=55555,
        node_base_params=NodeBaseParams(),
    )
    bank = SoundBank()
    bank.header.bank_id = 888
    bank.add_sound(sound)

    store = BankViewerStore(project=test_project)
    store.load_soundbank_instance("battle_rain.bnk", bank)
    store.select_bank("battle_rain.bnk")
    store.select_node("hirc:123456")

    # Muting via store muting logic
    assert store.mute_sound(123456) is True

    # Bank node should now be updated to 1.wem
    assert sound.file_id == 1
    assert (test_project.audio_dir / "1.wem").is_file()


def test_main_window_audio_sources_dock_integration(qtbot, tmp_path: Path):
    """Verify MainWindow mounts Audio Sources dock."""
    from src.ui.shell.view import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)

    assert hasattr(window, "audio_sources_dock")
    assert window.audio_sources_dock.objectName() == "AudioSourcesDock"
    assert hasattr(window, "audio_sources_store")
    assert hasattr(window, "audio_sources_view")
    assert window.audio_sources_view._store is window.audio_sources_store
    assert window.coordinator.audio_sources_store is window.audio_sources_store


def test_store_mute_nodes_multiselection(test_project: AudioProject):
    """Verify mute_nodes batch-mutes multiple sound nodes in an atomic transaction."""
    sound1 = CAkSound(
        id=101,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=0,
        source_id=1001,
        file_id=1001,
        node_base_params=NodeBaseParams(),
    )
    sound2 = CAkSound(
        id=102,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=0,
        source_id=1002,
        file_id=1002,
        node_base_params=NodeBaseParams(),
    )
    bank = SoundBank()
    bank.header.bank_id = 999
    bank.add_sound(sound1)
    bank.add_sound(sound2)

    store = BankViewerStore(project=test_project)
    store.load_soundbank_instance("test_multimute.bnk", bank)
    store.select_bank("test_multimute.bnk")

    # Mute both nodes simultaneously
    ok = store.mute_nodes(["hirc:101", "hirc:102"])
    assert ok is True

    # Both sounds should now point to file_id 1 (silent stub)
    assert sound1.file_id == 1
    assert sound2.file_id == 1
    assert (test_project.audio_dir / "1.wem").is_file()
