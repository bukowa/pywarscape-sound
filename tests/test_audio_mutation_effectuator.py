from pathlib import Path

import pytest

from src.bnk.models import CAkSound, NodeBaseParams
from src.bnk.wem import build_silent_pcm_wem_bytes
from src.engine.effectuator import execute_mutation_plan
from src.engine.ontology import (
    ExistingMediaReferenceSource,
    ExternalFileSource,
    SilentStubSource,
    SoundNodeTarget,
)
from src.engine.planner import plan_audio_replacement
from src.workspace.project import AudioProject


class MockBank:
    """Mock SoundBank with serializable objects."""

    def __init__(self, name: str, objects: dict) -> None:
        self.name = name
        self.objects = objects

    def to_bytes(self) -> bytes:
        return b"BKHD\x04\x00\x00\x00\x70\x00\x00\x00"


def test_execute_external_audio_replacement(test_project: AudioProject, tmp_path: Path):
    # Create test input audio (a valid silent PCM WEM or WAV)
    test_wav = tmp_path / "shout.wem"
    test_wav.write_bytes(build_silent_pcm_wem_bytes(duration_ms=100))

    sound = CAkSound(
        id=204996993,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=0,  # Originally embedded
        source_id=12345,
        file_id=12345,
        file_offset=500,
        in_memory_media_size=1024,
        node_base_params=NodeBaseParams(),
    )
    bank = MockBank("battle_rain.bnk", {204996993: sound})

    target = SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=204996993)
    source = ExternalFileSource(file_path=test_wav)

    plan = plan_audio_replacement(bank=bank, target=target, source=source)
    results = execute_mutation_plan(plan=plan, project=test_project, bank=bank)

    assert results.success is True
    # Verify in-memory HIRC mutation
    assert sound.stream_type == 2
    assert sound.file_id == 12345
    assert sound.source_id == 12345
    assert sound.file_offset == 0
    assert sound.in_memory_media_size == 0

    # Verify disk staging
    assert (test_project.source_audio_dir / "shout.wem").is_file()
    assert (test_project.audio_dir / "12345.wem").is_file()
    assert (test_project.audio_dir / "battle_rain.bnk").is_file()

    # Verify manifest tracking
    assert 12345 in test_project.manifest.staged_wems
    assert "battle_rain.bnk" in test_project.manifest.modified_banks
    assert test_project.manifest.source_audio[12345] == "source_audio/shout.wem"


def test_execute_silent_stub_mute(test_project: AudioProject):
    sound = CAkSound(
        id=204996993,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=2,
        source_id=12345,
        file_id=12345,
        node_base_params=NodeBaseParams(),
    )
    bank = MockBank("battle_rain.bnk", {204996993: sound})

    target = SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=204996993)
    source = SilentStubSource(stub_wem_id=1)

    plan = plan_audio_replacement(bank=bank, target=target, source=source)
    results = execute_mutation_plan(plan=plan, project=test_project, bank=bank)

    assert results.success is True
    assert sound.stream_type == 2
    assert sound.source_id == 1
    assert sound.file_id == 1

    # Silent 1.wem should be automatically staged
    assert (test_project.audio_dir / "1.wem").is_file()
    assert 1 in test_project.manifest.staged_wems
    assert "battle_rain.bnk" in test_project.manifest.modified_banks


def test_execute_existing_media_reference(test_project: AudioProject):
    sound = CAkSound(
        id=204996993,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=0,
        source_id=12345,
        file_id=12345,
        node_base_params=NodeBaseParams(),
    )
    bank = MockBank("battle_rain.bnk", {204996993: sound})

    target = SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=204996993)
    source = ExistingMediaReferenceSource(wem_id=987654321)

    plan = plan_audio_replacement(bank=bank, target=target, source=source)
    results = execute_mutation_plan(plan=plan, project=test_project, bank=bank)

    assert results.success is True
    assert sound.stream_type == 2
    assert sound.source_id == 987654321
    assert sound.file_id == 987654321

    # No files should be staged in source_audio or staged_wems
    assert len(test_project.manifest.source_audio) == 0
    assert 987654321 not in test_project.manifest.staged_wems
    assert "battle_rain.bnk" in test_project.manifest.modified_banks


def test_execute_wav_conversion_to_wem(test_project: AudioProject, tmp_path: Path):
    import wave

    # Create standard 44.1kHz 16-bit mono WAV
    wav_path = tmp_path / "voice_sample.wav"
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(b"\x00\x00" * 4410)  # 100ms of audio

    sound = CAkSound(
        id=777,
        obj_type=2,
        plugin_id=0x00040001,
        stream_type=0,
        source_id=888,
        file_id=888,
        node_base_params=NodeBaseParams(),
    )
    bank = MockBank("battle_rain.bnk", {777: sound})
    target = SoundNodeTarget(bank_name="battle_rain.bnk", sound_id=777)
    source = ExternalFileSource(file_path=wav_path)

    plan = plan_audio_replacement(bank=bank, target=target, source=source)
    results = execute_mutation_plan(plan=plan, project=test_project, bank=bank)

    assert results.success is True
    # Staged .wem should exist and start with RIFF
    staged_wem = test_project.audio_dir / "888.wem"
    assert staged_wem.is_file()
    data = staged_wem.read_bytes()
    assert data[:4] == b"RIFF"
    assert b"WAVE" in data[:12]
