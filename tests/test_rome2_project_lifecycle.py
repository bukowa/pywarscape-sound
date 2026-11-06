"""Integration test verifying complete project lifecycle for Total War: Rome II."""

import os
from pathlib import Path

import pytest

from src.bnk.bank import SoundBank
from src.bnk.models import CAkSound
from src.compiler.pfh4_pack import (
    PT_MOD,
    PT_MOVIE,
    extract_pfh4_file,
    read_pfh4_index,
    read_pfh4_pack_type,
    write_pfh4_movie_pack,
    write_pfh4_pack,
)
from src.engine.ontology import ExternalFileSource, SilentStubSource
from src.engine.session import WorkspaceSession
from src.workspace.game import GameType
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject
from src.workspace.storage import ProjectStorage
from tests.support.factories import make_synthetic_wav, skip_or_fail_missing_asset


def test_rome2_project_creation_and_persistence(tmp_path: Path):
    """Verifies creating and reloading a Rome 2 project on disk."""
    proj_dir = tmp_path / "MyRome2Mod"
    manifest = ProjectManifest(name="MyRome2Mod", game=GameType.ROME_2)
    project = AudioProject(root_dir=proj_dir, manifest=manifest)
    ProjectStorage.save_project(project)

    loaded = ProjectStorage.open_project(proj_dir)
    assert loaded.manifest.name == "MyRome2Mod"
    assert loaded.manifest.game == GameType.ROME_2


@pytest.mark.assets
def test_rome2_workspace_session_mutation_and_pack_lifecycle(tmp_path: Path):
    """End-to-end test: opens Rome 2 banks, applies audio mutations, packs to PFH4, and verifies."""
    rome2_cache = Path(".cache/rome_2/audio")
    if not rome2_cache.is_dir():
        skip_or_fail_missing_asset("Rome II audio cache not found")

    bank_file = rome2_cache / "battle_advice.bnk"
    if not bank_file.is_file():
        skip_or_fail_missing_asset(f"Baseline bank {bank_file} not found")

    proj_dir = tmp_path / "Rome2AudioProject"
    project = AudioProject(
        root_dir=proj_dir,
        manifest=ProjectManifest(name="Rome2AudioProject", game=GameType.ROME_2),
    )
    ProjectStorage.save_project(project)
    session = WorkspaceSession(project=project)

    # 1. Load baseline Rome 2 bank
    orig_bytes = bank_file.read_bytes()
    bank = SoundBank.from_bytes(orig_bytes)
    session.index_soundbank("battle_advice.bnk", bank)

    # Find a valid sound node in battle_advice.bnk
    sound_nodes = [obj for obj in bank.hirc.objects if isinstance(obj, CAkSound)]
    assert len(sound_nodes) > 0
    target_sound = sound_nodes[0]

    # 2. Mutate sound node using ExternalFileSource (transcoding to .wem)
    test_wav = make_synthetic_wav(tmp_path / "custom_shout.wav", duration_s=0.2)
    mutation_res = session.apply_sound_mutation(
        "battle_advice.bnk",
        sound_id=target_sound.id,
        source=ExternalFileSource(file_path=test_wav),
    )
    assert mutation_res is not None

    # Verify staged files
    staged_wem = project.audio_dir / f"{target_sound.source_id}.wem"
    assert staged_wem.is_file(), "Transcoded .wem audio file must be staged in pack_root/audio/"
    assert staged_wem.stat().st_size > 0

    # 3. Test Undo / Redo exactness
    assert session.can_undo_mutation
    session.undo_mutation()
    assert not staged_wem.exists(), "Undo must unstage custom .wem"

    assert session.can_redo_mutation
    session.redo_mutation()
    assert staged_wem.is_file(), "Redo must restage custom .wem"

    # Stage modified bank into project audio directory
    (project.audio_dir / "battle_advice.bnk").write_bytes(bank.to_bytes())

    # 4. Compile Mod .pack using project.compile_mod_pack
    mod_pack_path = tmp_path / "rome2_mod_regular.pack"
    compiled_pack = project.compile_mod_pack(output_path=mod_pack_path, pack_type=PT_MOD)
    assert compiled_pack.is_file()
    assert read_pfh4_pack_type(compiled_pack) == PT_MOD

    # 5. Verify pack contents and indices
    index = read_pfh4_index(compiled_pack)
    audio_paths = [entry.path for entry in index]
    assert any("battle_advice.bnk" in p for p in audio_paths)
    assert any(f"{target_sound.source_id}.wem" in p for p in audio_paths)

    # Decompile and parse compiled bank from inside the pack
    bnk_entry = next(entry for entry in index if "battle_advice.bnk" in entry.path)
    compiled_bnk_bytes = extract_pfh4_file(compiled_pack, bnk_entry)
    reparsed_bank = SoundBank.from_bytes(compiled_bnk_bytes)
    assert reparsed_bank.header.version in (88, 112)
    assert len(reparsed_bank.hirc.objects) == len(bank.hirc.objects)

    # 6. Compile Movie .pack (PT_MOVIE)
    movie_pack_path = tmp_path / "rome2_mod_movie.pack"
    compiled_movie_pack = project.compile_mod_pack(output_path=movie_pack_path, pack_type=PT_MOVIE)
    assert compiled_movie_pack.is_file()
    assert read_pfh4_pack_type(compiled_movie_pack) == PT_MOVIE
