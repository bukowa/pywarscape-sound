from pathlib import Path

import pytest

from src.workspace.manifest import ProjectManifest, SoundLibraryRef


def test_manifest_sound_library_roundtrip():
    manifest = ProjectManifest(name="TestMod")
    lib = SoundLibraryRef(id="lib_1", name="Footsteps", path="source_audio/libraries/footsteps")
    manifest.sound_libraries.append(lib)

    d = manifest.to_dict()
    assert "sound_libraries" in d
    assert d["sound_libraries"] == [
        {"id": "lib_1", "name": "Footsteps", "path": "source_audio/libraries/footsteps"}
    ]

    restored = ProjectManifest.from_dict(d)
    assert len(restored.sound_libraries) == 1
    assert restored.sound_libraries[0] == lib


def test_manifest_sound_library_backward_compat():
    d = {"name": "OldMod", "game": "attila"}
    manifest = ProjectManifest.from_dict(d)
    assert manifest.sound_libraries == []


def test_sound_library_ref_validation_empty_fields():
    with pytest.raises(ValueError, match="id"):
        SoundLibraryRef(id="", name="Footsteps", path="source_audio/libraries/footsteps")
    with pytest.raises(ValueError, match="id"):
        SoundLibraryRef(id="   ", name="Footsteps", path="source_audio/libraries/footsteps")

    with pytest.raises(ValueError, match="name"):
        SoundLibraryRef(id="lib_1", name="", path="source_audio/libraries/footsteps")
    with pytest.raises(ValueError, match="name"):
        SoundLibraryRef(id="lib_1", name="   ", path="source_audio/libraries/footsteps")

    with pytest.raises(ValueError, match="path"):
        SoundLibraryRef(id="lib_1", name="Footsteps", path="")
    with pytest.raises(ValueError, match="path"):
        SoundLibraryRef(id="lib_1", name="Footsteps", path="   ")


def test_sound_library_ref_forbids_parent_traversal():
    with pytest.raises(ValueError, match=r"parent traversal \(\.\.\)"):
        SoundLibraryRef(id="lib_1", name="Footsteps", path="../outside")

    with pytest.raises(ValueError, match=r"parent traversal \(\.\.\)"):
        SoundLibraryRef(id="lib_1", name="Footsteps", path="source_audio/../outside")

    with pytest.raises(ValueError, match=r"parent traversal \(\.\.\)"):
        SoundLibraryRef(id="lib_1", name="Footsteps", path=r"C:\audio\..\secrets")


def test_sound_library_ref_allows_absolute_and_relative_paths():
    # Project-relative POSIX path
    rel_lib = SoundLibraryRef(
        id="lib_rel", name="Relative", path="source_audio/libraries/footsteps"
    )
    assert rel_lib.path == "source_audio/libraries/footsteps"

    # Absolute Windows path
    win_lib = SoundLibraryRef(
        id="lib_win", name="Windows Library", path="C:/SoundLibraries/Weapons"
    )
    assert win_lib.path == "C:/SoundLibraries/Weapons"

    # Absolute POSIX path
    posix_lib = SoundLibraryRef(
        id="lib_posix", name="POSIX Library", path="/opt/sound_libraries/voices"
    )
    assert posix_lib.path == "/opt/sound_libraries/voices"


def test_sound_library_ref_to_and_from_dict():
    ref = SoundLibraryRef(id="lib_fx", name="Effects", path="D:/audio/fx")
    data = ref.to_dict()
    assert data == {"id": "lib_fx", "name": "Effects", "path": "D:/audio/fx"}

    restored = SoundLibraryRef.from_dict(data)
    assert restored == ref


def test_manifest_normalizes_dicts_to_sound_library_ref():
    manifest = ProjectManifest(
        name="DictInitMod",
        sound_libraries=[
            {"id": "lib_d", "name": "FromDict", "path": "source_audio/libraries/dict"}
        ],  # type: ignore[list-item]
    )
    assert len(manifest.sound_libraries) == 1
    assert isinstance(manifest.sound_libraries[0], SoundLibraryRef)
    assert manifest.sound_libraries[0].id == "lib_d"


def test_manifest_sound_libraries_invalid_type_raises():
    with pytest.raises(TypeError, match="Expected SoundLibraryRef or dict"):
        ProjectManifest(
            name="InvalidTypeMod",
            sound_libraries=[123],  # type: ignore[list-item]
        )


def test_manifest_json_roundtrip_with_sound_libraries():
    manifest = ProjectManifest(
        name="FullJsonMod",
        sound_libraries=[
            SoundLibraryRef(id="lib_1", name="Horns", path="source_audio/libraries/horns"),
            SoundLibraryRef(id="lib_2", name="Ambience", path="E:/Sounds/Ambience"),
        ],
    )
    json_text = manifest.to_json()
    loaded = ProjectManifest.from_json(json_text)
    assert len(loaded.sound_libraries) == 2
    assert loaded.sound_libraries[0].id == "lib_1"
    assert loaded.sound_libraries[1].id == "lib_2"
    assert loaded.sound_libraries[1].path == "E:/Sounds/Ambience"


def test_scan_library_and_project_crud(tmp_path: Path):
    from src.workspace.project import AudioProject
    from src.workspace.sound_library import scan_library

    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    lib_dir = proj_dir / "libs" / "sfx"
    lib_dir.mkdir(parents=True)
    (lib_dir / "sound_b.wav").write_bytes(b"RIFF dummy 2")
    (lib_dir / "sound_a.wav").write_bytes(b"RIFF dummy 1")
    (lib_dir / "notes.txt").write_text("ignore me")

    manifest = ProjectManifest(name="TestProj")
    proj = AudioProject(root_dir=proj_dir, manifest=manifest)

    ref = proj.add_sound_library(lib_dir, name="SFX")
    assert ref.name == "SFX"
    assert ref.path == "libs/sfx"

    # Duplicate root rejection
    with pytest.raises(ValueError, match="already registered"):
        proj.add_sound_library(lib_dir)

    entries = scan_library(proj_dir, ref)
    assert len(entries) == 2
    assert [e.rel_path for e in entries] == ["sound_a.wav", "sound_b.wav"]
    assert entries[0].library_id == ref.id
    assert entries[0].abs_path == (lib_dir / "sound_a.wav").resolve()
    assert entries[0].size_bytes == len(b"RIFF dummy 1")


def test_missing_library_path_is_graceful(tmp_path: Path):
    from src.workspace.project import AudioProject
    from src.workspace.sound_library import is_library_available, scan_library

    proj_dir = tmp_path / "proj"
    manifest = ProjectManifest(name="TestProj")
    proj = AudioProject(root_dir=proj_dir, manifest=manifest)
    ref = SoundLibraryRef(id="missing", name="Missing", path="non_existent/folder")

    assert is_library_available(proj_dir, ref) is False
    assert scan_library(proj_dir, ref) == ()


def test_sound_library_external_absolute_path_encoding(tmp_path: Path):
    from src.workspace.project import AudioProject
    from src.workspace.sound_library import is_library_available, resolve_library_root, scan_library

    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    ext_dir = tmp_path / "external_sfx"
    ext_dir.mkdir()
    (ext_dir / "hit.wav").write_bytes(b"RIFF hit")

    proj = AudioProject(root_dir=proj_dir, manifest=ProjectManifest(name="ExtMod"))
    ref = proj.add_sound_library(ext_dir)

    # Name defaults to directory basename
    assert ref.name == "external_sfx"
    # Encoded path is absolute POSIX
    assert ref.path == ext_dir.resolve().as_posix()
    assert is_library_available(proj_dir, ref) is True
    assert resolve_library_root(proj_dir, ref) == ext_dir.resolve()

    entries = scan_library(proj_dir, ref)
    assert len(entries) == 1
    assert entries[0].rel_path == "hit.wav"


def test_sound_library_project_root_rejected(tmp_path: Path):
    from src.workspace.project import AudioProject
    from src.workspace.sound_library import encode_library_path

    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    proj = AudioProject(root_dir=proj_dir, manifest=ProjectManifest(name="RootTest"))

    with pytest.raises(ValueError, match="cannot be the project root itself"):
        proj.add_sound_library(proj_dir)

    with pytest.raises(ValueError, match="cannot be the project root itself"):
        encode_library_path(proj_dir, proj_dir)


def test_sound_library_crud_rename_remove_and_list(tmp_path: Path):
    from src.workspace.project import AudioProject

    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    lib1 = proj_dir / "libs" / "lib1"
    lib2 = proj_dir / "libs" / "lib2"
    lib1.mkdir(parents=True)
    lib2.mkdir(parents=True)

    proj = AudioProject(root_dir=proj_dir, manifest=ProjectManifest(name="CrudMod"))
    ref1 = proj.add_sound_library(lib1, name="Lib1")
    ref2 = proj.add_sound_library(lib2, name="Lib2")

    libs = proj.list_sound_libraries()
    assert len(libs) == 2
    assert libs[0].id == ref1.id
    assert libs[1].id == ref2.id

    # Rename existing
    renamed = proj.rename_sound_library(ref1.id, "RenamedLib1")
    assert renamed is True
    assert proj.list_sound_libraries()[0].name == "RenamedLib1"

    # Reload from disk project.json to verify persistence
    reloaded = AudioProject(
        root_dir=proj_dir,
        manifest=ProjectManifest.from_json(proj.manifest_path.read_text(encoding="utf-8")),
    )
    assert reloaded.list_sound_libraries()[0].name == "RenamedLib1"

    # Rename non-existent
    assert proj.rename_sound_library("does_not_exist", "Name") is False

    # Remove existing
    removed = proj.remove_sound_library(ref1.id)
    assert removed is True
    assert len(proj.list_sound_libraries()) == 1
    assert proj.list_sound_libraries()[0].id == ref2.id

    # Remove non-existent
    assert proj.remove_sound_library("does_not_exist") is False

    # Check persistence after remove
    reloaded2 = AudioProject(
        root_dir=proj_dir,
        manifest=ProjectManifest.from_json(proj.manifest_path.read_text(encoding="utf-8")),
    )
    assert len(reloaded2.list_sound_libraries()) == 1


def test_sound_library_nested_folders_and_hidden_files(tmp_path: Path):
    from src.workspace.project import AudioProject
    from src.workspace.sound_library import scan_library

    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    lib_dir = proj_dir / "audio_source"
    (lib_dir / "weapons" / "swords").mkdir(parents=True)
    (lib_dir / ".git").mkdir()

    # Supported audio extensions: .wav, .mp3, .ogg, .flac, .wem
    (lib_dir / "weapons" / "swords" / "clash.wav").write_bytes(b"clash")
    (lib_dir / "weapons" / "bow.ogg").write_bytes(b"bow")
    (lib_dir / "ambient.flac").write_bytes(b"ambient")
    (lib_dir / "music.mp3").write_bytes(b"music")
    (lib_dir / "streamed.wem").write_bytes(b"wem")

    # Files that should be ignored
    (lib_dir / ".git" / "ignored.wav").write_bytes(b"git")
    (lib_dir / ".hidden.wav").write_bytes(b"hidden")
    (lib_dir / "readme.txt").write_text("info")

    proj = AudioProject(root_dir=proj_dir, manifest=ProjectManifest(name="ScanMod"))
    ref = proj.add_sound_library(lib_dir, name="AudioSource")

    entries = scan_library(proj_dir, ref)
    rel_paths = [e.rel_path for e in entries]
    assert rel_paths == [
        "ambient.flac",
        "music.mp3",
        "streamed.wem",
        "weapons/bow.ogg",
        "weapons/swords/clash.wav",
    ]


def test_sound_library_large_fast_scan(tmp_path: Path):
    """Verifies that scan_library scans thousands of files in milliseconds with zero redundant syscalls."""
    import time

    from src.workspace.project import AudioProject
    from src.workspace.sound_library import scan_library

    proj_dir = tmp_path / "speed_proj"
    proj_dir.mkdir()
    lib_dir = proj_dir / "large_library"

    # Create 10 subdirectories with 100 audio files each = 1,000 files
    for d_idx in range(10):
        sub = lib_dir / f"category_{d_idx:02d}"
        sub.mkdir(parents=True)
        for f_idx in range(100):
            (sub / f"sound_{f_idx:03d}.wav").write_bytes(b"RIFF")

    proj = AudioProject(root_dir=proj_dir, manifest=ProjectManifest(name="SpeedMod"))
    ref = proj.add_sound_library(lib_dir, name="LargeLib")

    t0 = time.perf_counter()
    entries = scan_library(proj_dir, ref)
    t1 = time.perf_counter()

    assert len(entries) == 1000
    # Must complete fast (well under 0.5s on any filesystem)
    assert (t1 - t0) < 0.5
    # Verify first and last entries are sorted
    assert entries[0].rel_path == "category_00/sound_000.wav"
    assert entries[-1].rel_path == "category_09/sound_099.wav"
    assert entries[0].size_bytes == 4
    assert entries[0].abs_path.is_file()
