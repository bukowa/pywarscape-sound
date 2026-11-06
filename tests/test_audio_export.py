from pathlib import Path

import pytest

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk, DataChunk, DidxChunk, DidxEntry
from src.bnk.models import CAkSound, NodeBaseParams
from src.bnk.wem import build_silent_pcm_wem_bytes
from src.engine.audio_export import (
    _extract_wem_id_from_key,
    export_node_to_wav,
    export_nodes_to_directory,
)
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject
from src.workspace.resolver import AssetResolver


def _create_synthetic_bank_with_embedded_wem(
    bank_id: int = 100,
    sound_id: int = 200,
    wem_id: int = 300,
) -> tuple[SoundBank, bytes]:
    """Creates a SoundBank AST with an embedded silent PCM WEM."""
    silent_wem = build_silent_pcm_wem_bytes(duration_ms=100)

    header = BkhdChunk(bank_id=bank_id)
    didx = DidxChunk(entries=[DidxEntry(file_id=wem_id, offset=0, size=len(silent_wem))])
    data = DataChunk(data=silent_wem)

    sound = CAkSound(
        id=sound_id,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=0,  # Embedded
        source_id=wem_id,
        file_id=bank_id,
        node_base_params=NodeBaseParams(),
    )
    hirc = HircChunk(objects=[sound])

    bank = SoundBank(
        header=header,
        didx=didx,
        data=data,
        hirc=hirc,
    )
    return bank, silent_wem


def test_extract_wem_id_from_keys():
    bank, _ = _create_synthetic_bank_with_embedded_wem(sound_id=123, wem_id=456)

    # Media key
    assert _extract_wem_id_from_key(bank, "media:456") == 456
    assert _extract_wem_id_from_key(bank, "media:embedded:456") == 456

    # HIRC key
    assert _extract_wem_id_from_key(bank, "hirc:123") == 456

    # Invalid / missing key
    assert _extract_wem_id_from_key(bank, "hirc:999") is None
    assert _extract_wem_id_from_key(bank, "invalid:key") is None


def test_export_embedded_node_to_wav(tmp_path: Path):
    bank, _ = _create_synthetic_bank_with_embedded_wem(sound_id=101, wem_id=202)
    out_file = tmp_path / "out.wav"

    exported = export_node_to_wav(bank, "hirc:101", out_file)
    assert exported == out_file
    assert out_file.is_file()
    assert out_file.stat().st_size > 44  # Valid WAV with header + samples
    assert out_file.read_bytes()[:4] == b"RIFF"


def test_export_embedded_media_key_to_wav(tmp_path: Path):
    bank, _ = _create_synthetic_bank_with_embedded_wem(sound_id=101, wem_id=202)
    out_file = tmp_path / "media_out.wav"

    exported = export_node_to_wav(bank, "media:202", out_file)
    assert exported == out_file
    assert out_file.is_file()
    assert out_file.read_bytes()[:4] == b"RIFF"


def test_export_streamed_node_with_resolver(tmp_path: Path):
    # Setup project with staged loose WEM
    proj_dir = tmp_path / "project"
    manifest = ProjectManifest(name="ExportTest", game="attila", staged_wems=[999])
    project = AudioProject(root_dir=proj_dir, manifest=manifest)
    project.audio_dir.mkdir(parents=True, exist_ok=True)

    loose_wem = project.audio_dir / "999.wem"
    loose_wem.write_bytes(build_silent_pcm_wem_bytes(duration_ms=50))

    resolver = AssetResolver(project=project)

    # Bank referencing streamed WEM 999
    sound = CAkSound(
        id=500,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=2,  # Streamed
        source_id=999,
        file_id=999,
        node_base_params=NodeBaseParams(),
    )
    bank = SoundBank(header=BkhdChunk(bank_id=10), hirc=HircChunk(objects=[sound]))

    out_file = tmp_path / "streamed.wav"
    exported = export_node_to_wav(bank, "hirc:500", out_file, resolver=resolver)
    assert exported == out_file
    assert out_file.is_file()
    assert out_file.read_bytes()[:4] == b"RIFF"


def test_export_node_raises_on_invalid_or_missing_audio(tmp_path: Path):
    bank, _ = _create_synthetic_bank_with_embedded_wem(sound_id=101, wem_id=202)
    out_file = tmp_path / "fail.wav"

    # Non-existent node
    with pytest.raises(ValueError, match="No audio source found"):
        export_node_to_wav(bank, "hirc:9999", out_file)

    # Node with missing media data (e.g. stream_type=2 but no resolver)
    streamed_sound = CAkSound(
        id=777,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=2,
        source_id=888,
        file_id=888,
        node_base_params=NodeBaseParams(),
    )
    bank_no_media = SoundBank(header=BkhdChunk(), hirc=HircChunk(objects=[streamed_sound]))
    with pytest.raises(FileNotFoundError, match="Could not resolve audio data"):
        export_node_to_wav(bank_no_media, "hirc:777", out_file)


def test_export_nodes_to_directory(tmp_path: Path):
    bank, _ = _create_synthetic_bank_with_embedded_wem(sound_id=101, wem_id=202)
    export_dir = tmp_path / "exported_wavs"

    keys = ["hirc:101", "media:202", "hirc:nonexistent"]
    count = export_nodes_to_directory(bank, keys, export_dir)

    # hirc:101 and media:202 both reference WEM 202 -> writes 202.wav
    assert count == 2
    assert (export_dir / "202.wav").is_file()
