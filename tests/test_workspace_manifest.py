import pytest

from src.workspace.game import GameType
from src.workspace.manifest import ProjectManifest


def test_manifest_defaults_and_roundtrip():
    manifest = ProjectManifest(
        name="Epic Mod",
        game=GameType.ATTILA,
        author="MasterModder",
        modified_banks=["battle.bnk", "ui.bnk"],
        staged_wems=[1001, 1002],
        source_audio={1001: "source_audio/horns.wav"},
        custom_names={"battle.bnk": {9999: "WarHorn_Action"}},
        has_custom_event_db=True,
    )

    json_str = manifest.to_json()
    reloaded = ProjectManifest.from_json(json_str)

    assert reloaded.schema_version == "1.0"
    assert reloaded.name == "Epic Mod"
    assert reloaded.game == GameType.ATTILA
    assert reloaded.author == "MasterModder"
    assert reloaded.modified_banks == ["battle.bnk", "ui.bnk"]
    assert reloaded.staged_wems == [1001, 1002]
    assert reloaded.source_audio == {1001: "source_audio/horns.wav"}
    assert reloaded.custom_names == {"battle.bnk": {9999: "WarHorn_Action"}}
    assert reloaded.has_custom_event_db is True


def test_manifest_rejects_absolute_source_paths():
    with pytest.raises(ValueError, match="relative"):
        ProjectManifest(name="Test", source_audio={1001: "C:/Users/test/sound.wav"})

    with pytest.raises(ValueError, match="relative"):
        ProjectManifest(name="Test", source_audio={1002: "/root/sound.wav"})


def test_manifest_dict_roundtrip_and_types():
    raw_dict = {
        "schema_version": "1.0",
        "name": "Custom Project",
        "game": "rome_2",
        "author": "Modder",
        "description": "A description",
        "version": "1.0.0",
        "modified_banks": ["music.bnk"],
        "staged_wems": [500],
        "source_audio": {"500": "source_audio/track.ogg"},
        "custom_names": {"music.bnk": {"123": "Cue_1"}},
        "has_custom_event_db": False,
    }
    m = ProjectManifest.from_dict(raw_dict)
    assert m.game == GameType.ROME_2
    assert m.source_audio == {500: "source_audio/track.ogg"}
    assert m.custom_names == {"music.bnk": {123: "Cue_1"}}
    d = m.to_dict()
    assert d["staged_wems"] == [500]
    assert d["schema_version"] == "1.0"
