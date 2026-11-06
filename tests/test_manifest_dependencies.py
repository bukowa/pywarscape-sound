from src.workspace.manifest import DependencyPackInfo, ProjectManifest


def test_manifest_with_dependencies_round_trip():
    dep = DependencyPackInfo(
        name="custom_audio.pack",
        source_path="C:/games/custom_audio.pack",
        priority=1,
        imported_at="2026-10-29T12:00:00Z",
        sha256="abcdef123456",
        extracted_audio_files=["audio/custom_music.bnk"],
        extracted_db_tables=["db/land_units_tables/mk_units"],
    )
    manifest = ProjectManifest(
        name="TestMod",
        dependencies=[dep],
    )
    d = manifest.to_dict()
    assert d["schema_version"] == "1.0"
    assert len(d["dependencies"]) == 1
    assert d["dependencies"][0]["name"] == "custom_audio.pack"

    restored = ProjectManifest.from_dict(d)
    assert len(restored.dependencies) == 1
    assert restored.dependencies[0].name == "custom_audio.pack"
    assert restored.dependencies[0].extracted_audio_files == ["audio/custom_music.bnk"]
    assert restored.dependencies[0].extracted_db_tables == ["db/land_units_tables/mk_units"]
    assert restored.dependencies[0].priority == 1
    assert restored.dependencies[0].imported_at == "2026-10-29T12:00:00Z"
    assert restored.dependencies[0].sha256 == "abcdef123456"


def test_dependency_pack_info_defaults():
    dep = DependencyPackInfo(
        name="minimal.pack",
        source_path="C:/games/minimal.pack",
    )
    assert dep.name == "minimal.pack"
    assert dep.source_path == "C:/games/minimal.pack"
    assert dep.priority == 0
    assert dep.imported_at == ""
    assert dep.sha256 == ""
    assert dep.extracted_audio_files == []
    assert dep.extracted_db_tables == []


def test_manifest_roundtrip_json_with_dependencies():
    dep1 = DependencyPackInfo(
        name="pack_a.pack",
        source_path="D:/packs/pack_a.pack",
        priority=1,
        extracted_audio_files=["audio/battle.bnk"],
    )
    dep2 = DependencyPackInfo(
        name="pack_b.pack",
        source_path="D:/packs/pack_b.pack",
        priority=2,
        extracted_db_tables=["db/battle_entities_tables/data"],
    )
    manifest = ProjectManifest(
        name="MultiDepMod",
        dependencies=[dep1, dep2],
    )
    json_text = manifest.to_json()
    loaded = ProjectManifest.from_json(json_text)
    assert len(loaded.dependencies) == 2
    assert loaded.dependencies[0].name == "pack_a.pack"
    assert loaded.dependencies[1].name == "pack_b.pack"
    assert loaded.dependencies[0].priority == 1
    assert loaded.dependencies[1].priority == 2


def test_manifest_from_dict_defaults_empty_dependencies():
    raw_dict = {
        "schema_version": "1.0",
        "name": "LegacyStyleProject",
    }
    m = ProjectManifest.from_dict(raw_dict)
    assert m.dependencies == []
    d = m.to_dict()
    assert d["dependencies"] == []
