"""Comprehensive tests for direct embedded media audio replacement, muting, and undo/redo."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from src.bnk.bank import SoundBank
from src.bnk.chunks import BkhdChunk, DataChunk, DidxChunk, DidxEntry
from src.bnk.database import SoundDatabase, fnv1_32
from src.bnk.wem import build_silent_pcm_wem_bytes
from src.engine.effectuator import execute_mutation_plan
from src.engine.ontology import (
    CopyMediaBytesIntent,
    ExistingMediaReferenceSource,
    ExternalFileSource,
    MediaNodeTarget,
    SilentStubSource,
    StageLooseWemIntent,
    StageMasterAudioIntent,
)
from src.engine.planner import plan_audio_replacement
from src.ui.features.bank_viewer.inspector_panel import InspectorPanel
from src.ui.features.bank_viewer.state import InspectorViewType, NodeInspectorDetails
from src.ui.features.bank_viewer.store import BankViewerStore
from src.ui.features.bank_viewer.view import BankViewerView
from src.ui.features.bank_viewer.views.media_view import MediaInspectorView
from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject


def _create_synthetic_companion_bank_cache(
    cache_dir: Path,
    bank_name: str = "animation_blood_data.bnk",
    media_ids: Sequence[int] = (43082521, 43082522, 43082523),
) -> GameCache:
    cache_dir.mkdir(parents=True, exist_ok=True)
    stem = bank_name.removesuffix(".bnk")
    bank = SoundBank(
        header=BkhdChunk(bank_id=fnv1_32(stem), version=112),
        didx=DidxChunk(),
        data=DataChunk(),
    )
    for mid in media_ids:
        raw_wem = build_silent_pcm_wem_bytes(duration_ms=50, sample_rate=32000)
        offset, size = bank.data.align_and_append(raw_wem)
        bank.didx.entries.append(DidxEntry(file_id=mid, offset=offset, size=size))
    (cache_dir / bank_name).write_bytes(bank.to_bytes())
    (cache_dir / "event_data.dat").write_bytes(SoundDatabase().to_bytes())
    return GameCache(GameType.ATTILA, cache_dir=cache_dir)


def test_plan_media_replacement_external_file(tmp_path: Path):
    audio_file = tmp_path / "splat.wav"
    audio_file.write_bytes(b"RIFF dummy wav content")

    target = MediaNodeTarget(bank_name="animation_blood_data.bnk", wem_id=43082521)
    source = ExternalFileSource(file_path=audio_file)

    plan = plan_audio_replacement(bank=None, target=target, source=source)

    assert "Replace Media WEM 43082521" in plan.description
    assert "splat.wav" in plan.description
    assert len(plan.effects) == 1
    intent = plan.effects[0]
    assert isinstance(intent, StageMasterAudioIntent)
    assert intent.wem_id == 43082521
    assert intent.source_path == audio_file
    assert intent.destination_rel_path == "source_audio/splat.wav"


def test_plan_media_replacement_missing_file_raises(tmp_path: Path):
    target = MediaNodeTarget(bank_name="animation_blood_data.bnk", wem_id=43082521)
    source = ExternalFileSource(file_path=tmp_path / "nonexistent.wav")

    with pytest.raises(FileNotFoundError):
        plan_audio_replacement(bank=None, target=target, source=source)


def test_plan_media_mute():
    target = MediaNodeTarget(bank_name="animation_blood_data.bnk", wem_id=43082521)
    source = SilentStubSource()

    plan = plan_audio_replacement(bank=None, target=target, source=source)

    assert "Mute Media WEM 43082521" in plan.description
    assert len(plan.effects) == 1
    intent = plan.effects[0]
    assert isinstance(intent, StageLooseWemIntent)
    assert intent.wem_id == 43082521
    assert len(intent.wem_bytes) > 0


def test_plan_media_library_reference():
    target = MediaNodeTarget(bank_name="animation_blood_data.bnk", wem_id=43082521)
    source = ExistingMediaReferenceSource(wem_id=987654, source_bank="battle_sfx.bnk")

    plan = plan_audio_replacement(bank=None, target=target, source=source)

    assert "Replace Media WEM 43082521 with library media 987654" in plan.description
    assert len(plan.effects) == 1
    intent = plan.effects[0]
    assert isinstance(intent, CopyMediaBytesIntent)
    assert intent.target_wem_id == 43082521
    assert intent.source_wem_id == 987654
    assert intent.source_bank_name == "battle_sfx.bnk"


def test_execute_media_external_file_replacement(test_project: AudioProject, tmp_path: Path):
    audio_file = tmp_path / "blood_hit.wem"
    audio_file.write_bytes(build_silent_pcm_wem_bytes(duration_ms=60))

    target = MediaNodeTarget(bank_name="animation_blood_data.bnk", wem_id=43082521)
    source = ExternalFileSource(file_path=audio_file)

    plan = plan_audio_replacement(bank=None, target=target, source=source)
    res = execute_mutation_plan(plan=plan, project=test_project, bank=None)

    assert res.success is True
    assert (test_project.source_audio_dir / "blood_hit.wem").is_file()
    assert (test_project.audio_dir / "43082521.wem").is_file()
    assert 43082521 in test_project.manifest.staged_wems
    assert test_project.manifest.source_audio[43082521] == "source_audio/blood_hit.wem"


def test_execute_media_silent_mute(test_project: AudioProject):
    target = MediaNodeTarget(bank_name="animation_blood_data.bnk", wem_id=43082521)
    source = SilentStubSource()

    plan = plan_audio_replacement(bank=None, target=target, source=source)
    res = execute_mutation_plan(plan=plan, project=test_project, bank=None)

    assert res.success is True
    assert (test_project.audio_dir / "43082521.wem").is_file()
    assert 43082521 in test_project.manifest.staged_wems


def test_execute_media_copy_bytes_via_bank(test_project: AudioProject):
    bank = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        didx=DidxChunk(entries=[DidxEntry(file_id=8888, offset=0, size=16)]),
        data=DataChunk(data=b"0123456789ABCDEF"),
    )
    assert bank.get_media_data(8888) == b"0123456789ABCDEF"
    assert bank.get_media_data(9999) is None

    target = MediaNodeTarget(bank_name="animation_blood_data.bnk", wem_id=43082521)
    source = ExistingMediaReferenceSource(wem_id=8888)

    plan = plan_audio_replacement(bank=bank, target=target, source=source)
    res = execute_mutation_plan(plan=plan, project=test_project, bank=bank)

    assert res.success is True
    assert (test_project.audio_dir / "43082521.wem").read_bytes() == b"0123456789ABCDEF"
    assert 43082521 in test_project.manifest.staged_wems


def test_execute_media_copy_bytes_unresolvable_fails(test_project: AudioProject):
    target = MediaNodeTarget(bank_name="animation_blood_data.bnk", wem_id=43082521)
    source = ExistingMediaReferenceSource(wem_id=99999999)

    plan = plan_audio_replacement(bank=None, target=target, source=source)
    res = execute_mutation_plan(plan=plan, project=test_project, bank=None)

    assert res.success is False
    assert "Could not resolve source media bytes" in res.description


def test_store_apply_media_mutation_and_undo_redo(test_project: AudioProject):
    bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        didx=DidxChunk(entries=[DidxEntry(file_id=43082521, offset=0, size=8)]),
        data=DataChunk(data=b"ORIGINAL"),
    )

    store = BankViewerStore(project=test_project)
    store.load_soundbank_instance("test_companion.bnk", bank)
    store.select_bank("test_companion.bnk")

    # Verify initial tree node is NOT modified
    node = store.state.nodes_by_key.get("media:43082521")
    assert node is not None
    assert node.is_modified is False

    # Apply mute
    success = store.mute_media(43082521)
    assert success is True
    assert (test_project.audio_dir / "43082521.wem").is_file()
    assert 43082521 in test_project.manifest.staged_wems

    # Verify node in tree is now marked modified
    mod_node = store.state.nodes_by_key.get("media:43082521")
    assert mod_node is not None
    assert mod_node.is_modified is True

    # Undo
    assert store.can_undo_mutation is True
    assert store.undo_mutation() is True
    assert not (test_project.audio_dir / "43082521.wem").is_file()
    assert 43082521 not in test_project.manifest.staged_wems
    reverted_node = store.state.nodes_by_key.get("media:43082521")
    assert reverted_node is not None
    assert reverted_node.is_modified is False

    # Redo
    assert store.can_redo_mutation is True
    assert store.redo_mutation() is True
    assert (test_project.audio_dir / "43082521.wem").is_file()
    assert 43082521 in test_project.manifest.staged_wems
    redo_node = store.state.nodes_by_key.get("media:43082521")
    assert redo_node is not None
    assert redo_node.is_modified is True


def test_media_inspector_view_buttons(qapp):
    view = MediaInspectorView()
    assert view.btn_export.isEnabled() is False
    assert view.btn_revert.isEnabled() is False

    details = NodeInspectorDetails(
        node_key="media:43082521",
        name="WEM 43082521",
        object_type="Embedded Media",
        view_type=InspectorViewType.MEDIA,
        object_id=43082521,
    )
    view.render(details)
    assert view.btn_export.isEnabled() is True
    assert view.lbl_file_id.text() == "WEM ID: 43082521"

    export_signals = []
    view.export_requested.connect(export_signals.append)

    view.btn_export.click()
    assert export_signals == [43082521]

    # Render None disables
    view.render(None)
    assert view.btn_export.isEnabled() is False
    assert view.btn_revert.isEnabled() is False


def test_inspector_panel_wires_media_signals(qapp):
    panel = InspectorPanel()
    export_events = []
    revert_events = []
    panel.export_media_requested.connect(export_events.append)
    panel.revert_media_requested.connect(revert_events.append)

    details = NodeInspectorDetails(
        node_key="media:43082521",
        name="WEM 43082521",
        object_type="Embedded Media",
        view_type=InspectorViewType.MEDIA,
        object_id=43082521,
        source_origin="Project Overlay",
    )
    panel.render_details(details)

    panel.media_view.btn_export.click()
    assert export_events == [43082521]

    panel.media_view.btn_revert.click()
    assert revert_events == [43082521]


def test_bank_viewer_view_media_actions_wired(qapp, test_project: AudioProject, monkeypatch):
    bank = SoundBank(
        header=BkhdChunk(bank_id=500, version=112),
        didx=DidxChunk(entries=[DidxEntry(file_id=43082521, offset=0, size=8)]),
        data=DataChunk(data=b"TESTDATA"),
    )
    store = BankViewerStore(project=test_project)
    store.load_soundbank_instance("companion.bnk", bank)
    store.select_bank("companion.bnk")

    # Verify store mutes media
    store.mute_media(43082521)
    assert (test_project.audio_dir / "43082521.wem").is_file()
    assert 43082521 in test_project.manifest.staged_wems


def test_real_animation_blood_data_bank_replacement_integration(tmp_path: Path):
    cache = _create_synthetic_companion_bank_cache(tmp_path / "cache" / "audio")

    manifest = ProjectManifest(
        name="RealMediaMod",
        game="attila",
        description="Testing real animation blood data bank replacement",
    )
    project = AudioProject(root_dir=tmp_path / "real_mod", manifest=manifest, cache=cache)
    store = BankViewerStore(project=project)
    store.load_project(project)
    store.select_bank("animation_blood_data.bnk")

    # Companion bank should have 0 HIRC objects and DIDX media entries
    tuple_entry = store.session.loaded_banks.get("animation_blood_data.bnk")
    assert tuple_entry is not None
    bank, _, _ = tuple_entry
    assert bank.hirc is None or len(bank.hirc.objects) == 0
    assert bank.didx is not None and len(bank.didx.entries) == 3

    target_wem = bank.didx.entries[0].file_id
    assert target_wem > 0
    node_key = f"media:{target_wem}"

    # Initially not modified
    node = store.state.nodes_by_key.get(node_key)
    assert node is not None
    assert node.is_modified is False

    # Mute media WEM
    assert store.mute_media(target_wem) is True
    assert (project.audio_dir / f"{target_wem}.wem").is_file()
    assert target_wem in project.manifest.staged_wems

    # Bank and node marked modified
    node_mod = store.state.nodes_by_key.get(node_key)
    assert node_mod is not None
    assert node_mod.is_modified is True

    # Undo
    assert store.undo_mutation() is True
    assert not (project.audio_dir / f"{target_wem}.wem").is_file()
    assert target_wem not in project.manifest.staged_wems
    node_reverted = store.state.nodes_by_key.get(node_key)
    assert node_reverted is not None
    assert node_reverted.is_modified is False

    # Redo
    assert store.redo_mutation() is True
    assert (project.audio_dir / f"{target_wem}.wem").is_file()
    assert target_wem in project.manifest.staged_wems
    node_redone = store.state.nodes_by_key.get(node_key)
    assert node_redone is not None
    assert node_redone.is_modified is True


def test_audio_resolver_prefers_staged_overlay_over_embedded_data(tmp_path: Path):
    """
    Verifies that resolve_node_audio_track prioritizes staged loose .wem files
    in the project overlay over vanilla embedded DATA chunks for media: and hirc: nodes.
    """
    cache = _create_synthetic_companion_bank_cache(tmp_path / "cache" / "audio")

    manifest = ProjectManifest(
        name="MediaModPlayback",
        game="attila",
        description="Verify resolver overlay priority",
    )
    project = AudioProject(root_dir=tmp_path / "media_mod_playback", manifest=manifest, cache=cache)
    store = BankViewerStore(project=project)
    store.load_project(project)
    store.select_bank("animation_blood_data.bnk")

    tuple_entry = store.session.loaded_banks.get("animation_blood_data.bnk")
    assert tuple_entry is not None
    bank, _, _ = tuple_entry
    target_wem = bank.didx.entries[0].file_id
    node_key = f"media:{target_wem}"

    # Before mutation: embedded in DATA
    track_before = store.resolve_audio_track(node_key)
    assert track_before is not None
    assert track_before.embedded_bytes is not None
    assert track_before.file_path is None

    # Mute media WEM (stages silent stub into pack_root/audio/<id>.wem)
    assert store.mute_media(target_wem) is True

    # After mutation: MUST resolve to staged file_path, NOT the old embedded DATA
    track_after = store.resolve_audio_track(node_key)
    assert track_after is not None
    assert track_after.file_path is not None
    assert str(target_wem) in track_after.file_path
    assert track_after.embedded_bytes is None


def test_media_inspector_view_multiselection_text(qapp):
    """Verify MediaInspectorView dynamically reflects selected_count in button text."""
    view = MediaInspectorView()

    details = NodeInspectorDetails(
        node_key="media:55501",
        object_id=55501,
        hex_id="0x0000D8CD",
        object_type="Embedded WEM",
        name="WEM 55501",
        properties=(),
    )

    # 1. Single selection
    view.render(details, selected_count=1)
    assert view.btn_export.text() == "Export WAV..."

    # 2. Multi selection (e.g. 4 nodes selected)
    view.render(details, selected_count=4)
    assert view.btn_export.text() == "Export WAV (4)..."


def test_store_mute_nodes_media_multiselection(tmp_path: Path):
    """Verify store.mute_nodes batch-mutes multiple embedded media files."""
    cache = _create_synthetic_companion_bank_cache(tmp_path / "cache" / "audio")

    manifest = ProjectManifest(
        name="MediaMultiMute",
        game="attila",
        description="Verify multi mute media",
    )
    project = AudioProject(root_dir=tmp_path / "media_multimute", manifest=manifest, cache=cache)
    store = BankViewerStore(project=project)
    store.load_project(project)
    store.select_bank("animation_blood_data.bnk")

    tuple_entry = store.session.loaded_banks.get("animation_blood_data.bnk")
    assert tuple_entry is not None
    bank, _, _ = tuple_entry
    wem1 = bank.didx.entries[0].file_id
    wem2 = bank.didx.entries[1].file_id

    # Mute both media entries simultaneously
    ok = store.mute_nodes([f"media:{wem1}", f"media:{wem2}"])
    assert ok is True

    # Both should now exist in project staged loose WEMs
    assert (project.audio_dir / f"{wem1}.wem").is_file()
    assert (project.audio_dir / f"{wem2}.wem").is_file()
    assert wem1 in project.manifest.staged_wems
    assert wem2 in project.manifest.staged_wems
