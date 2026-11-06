from pathlib import Path

import pytest

from src.compiler.pfh4_pack import write_pfh4_movie_pack
from src.workspace.dependencies import (
    ConflictType,
    DependencyManager,
    ResolutionAction,
)
from src.workspace.game import GameType
from src.workspace.manifest import DependencyPackInfo
from src.workspace.storage import ProjectStorage


def _create_test_pack(pack_path: Path, files: dict[str, bytes]) -> Path:
    """Helper to write a valid PFH4 pack with test files."""
    return write_pfh4_movie_pack(pack_path, files)


def test_dependency_manager_plan_import_detects_conflicts_and_safe_files(tmp_path):
    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)

    # Local user modifications
    project.save_bank("modified.bnk", b"LOCAL_MODIFIED_BANK")

    # Create dummy incoming PFH4 pack
    pack_path = tmp_path / "incoming_mod.pack"
    files = {
        "audio/safe.bnk": b"SAFE_BANK_PAYLOAD",
        "audio/modified.bnk": b"INCOMING_MODIFIED_BANK_PAYLOAD",
        "db/land_units_tables/test_units": b"LAND_UNITS_DATA",
        "db/ignored_tables/ignored_data": b"IGNORED_DB_DATA",
        "ui/flags/test.png": b"IGNORED_UI_DATA",
    }
    _create_test_pack(pack_path, files)

    mgr = DependencyManager(project)
    plan = mgr.plan_import(pack_path, priority=1)

    assert plan.pack_name == "incoming_mod.pack"
    assert plan.priority == 1
    assert len(plan.sha256) == 64

    # Safe audio files (safe.bnk only)
    safe_audio_names = [vpath for vpath, _ in plan.safe_audio_files]
    assert safe_audio_names == ["audio/safe.bnk"]
    assert plan.safe_audio_files[0][1] == b"SAFE_BANK_PAYLOAD"

    # Safe DB tables (land_units_tables only, ignored_tables filtered out)
    safe_db_names = [vpath for vpath, _ in plan.safe_db_files]
    assert safe_db_names == ["db/land_units_tables/test_units"]
    assert plan.safe_db_files[0][1] == b"LAND_UNITS_DATA"

    # Conflicts: modified.bnk detected as BANK_MODIFIED
    assert len(plan.conflicts) == 1
    conflict = plan.conflicts[0]
    assert conflict.virtual_path == "audio/modified.bnk"
    assert conflict.conflict_type == ConflictType.BANK_MODIFIED
    assert conflict.local_size == len(b"LOCAL_MODIFIED_BANK")
    assert conflict.incoming_size == len(b"INCOMING_MODIFIED_BANK_PAYLOAD")
    assert conflict.resolution == ResolutionAction.KEEP_LOCAL
    assert plan.conflict_payloads["audio/modified.bnk"] == b"INCOMING_MODIFIED_BANK_PAYLOAD"


def test_dependency_manager_execute_import_keep_local(tmp_path):
    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)
    project.save_bank("modified.bnk", b"LOCAL_MODIFIED_BANK")

    pack_path = tmp_path / "incoming_mod.pack"
    files = {
        "audio/safe.bnk": b"SAFE_BANK_PAYLOAD",
        "audio/modified.bnk": b"INCOMING_MODIFIED_BANK_PAYLOAD",
        "db/land_units_tables/test_units": b"LAND_UNITS_DATA",
    }
    _create_test_pack(pack_path, files)

    mgr = DependencyManager(project)
    plan = mgr.plan_import(pack_path, priority=5)

    # Execute with default KEEP_LOCAL
    mgr.execute_import(plan)

    dep_dir = project.get_dependency_dir("incoming_mod.pack")
    # Both files extracted to dependencies dir
    assert (dep_dir / "audio" / "safe.bnk").read_bytes() == b"SAFE_BANK_PAYLOAD"
    assert (dep_dir / "audio" / "modified.bnk").read_bytes() == b"INCOMING_MODIFIED_BANK_PAYLOAD"
    assert (dep_dir / "db" / "land_units_tables" / "test_units").read_bytes() == b"LAND_UNITS_DATA"

    # User local version preserved
    assert (project.audio_dir / "modified.bnk").read_bytes() == b"LOCAL_MODIFIED_BANK"
    assert "modified.bnk" in project.manifest.modified_banks

    # Manifest dependency registered
    assert len(project.manifest.dependencies) == 1
    dep_info = project.manifest.dependencies[0]
    assert dep_info.name == "incoming_mod.pack"
    assert dep_info.priority == 5
    assert sorted(dep_info.extracted_audio_files) == ["audio/modified.bnk", "audio/safe.bnk"]
    assert dep_info.extracted_db_tables == ["db/land_units_tables/test_units"]


def test_dependency_manager_execute_import_overwrite_local(tmp_path):
    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)
    project.save_bank("modified.bnk", b"LOCAL_MODIFIED_BANK")
    project.manifest.custom_names["modified.bnk"] = {123: "CustomAlias"}

    pack_path = tmp_path / "incoming_mod.pack"
    files = {
        "audio/safe.bnk": b"SAFE_BANK_PAYLOAD",
        "audio/modified.bnk": b"INCOMING_MODIFIED_BANK_PAYLOAD",
    }
    _create_test_pack(pack_path, files)

    mgr = DependencyManager(project)
    plan = mgr.plan_import(pack_path, priority=2)

    # Execute with OVERWRITE_LOCAL
    mgr.execute_import(plan, resolutions={"audio/modified.bnk": ResolutionAction.OVERWRITE_LOCAL})

    dep_dir = project.get_dependency_dir("incoming_mod.pack")
    assert (dep_dir / "audio" / "modified.bnk").read_bytes() == b"INCOMING_MODIFIED_BANK_PAYLOAD"

    # Under non-destructive dependency isolation, local Tier 1 files in pack_root/audio/ are PRESERVED
    assert (project.audio_dir / "modified.bnk").exists()
    assert (project.audio_dir / "modified.bnk").read_bytes() == b"LOCAL_MODIFIED_BANK"
    assert "modified.bnk" in project.manifest.modified_banks

    # Explicit revert cleanly removes local modified bank
    reverted_banks, _ = project.revert_bank_completely("modified.bnk")
    assert reverted_banks == 1
    assert not (project.audio_dir / "modified.bnk").exists()
    assert "modified.bnk" not in project.manifest.modified_banks


def test_dependency_manager_wem_and_event_db_conflicts(tmp_path):
    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)

    # Stage a WEM and save custom event DB
    project.stage_wem(99999, b"LOCAL_WEM_DATA")
    project.stage_source_audio(tmp_path / "dummy.wav", 99999) if False else None
    project.manifest.source_audio[99999] = "source_audio/master.wav"
    project.save_database(b"LOCAL_EVENT_DB")

    pack_path = tmp_path / "dep_audio.pack"
    files = {
        "audio/99999.wem": b"INCOMING_WEM_DATA",
        "audio/event_data.dat": b"INCOMING_EVENT_DB",
        "audio/88888.wem": b"SAFE_WEM_DATA",
    }
    _create_test_pack(pack_path, files)

    mgr = DependencyManager(project)
    plan = mgr.plan_import(pack_path)

    # Safe audio has 88888.wem
    assert [p for p, _ in plan.safe_audio_files] == ["audio/88888.wem"]

    # Conflicts should detect WEM_STAGED and EVENT_DB_MODIFIED
    c_types = {c.virtual_path: c.conflict_type for c in plan.conflicts}
    assert c_types["audio/99999.wem"] == ConflictType.WEM_STAGED
    assert c_types["audio/event_data.dat"] == ConflictType.EVENT_DB_MODIFIED

    # Execute with OVERWRITE_LOCAL for both
    mgr.execute_import(
        plan,
        resolutions={
            "audio/99999.wem": ResolutionAction.OVERWRITE_LOCAL,
            "audio/event_data.dat": ResolutionAction.OVERWRITE_LOCAL,
        },
    )

    # Non-destructive isolation: local wem and event_data.dat are preserved
    assert 99999 in project.manifest.staged_wems
    assert 99999 in project.manifest.source_audio
    assert (project.audio_dir / "99999.wem").exists()
    assert project.manifest.has_custom_event_db
    assert (project.audio_dir / "event_data.dat").exists()

    # But both are extracted in dependency dir
    dep_dir = project.get_dependency_dir("dep_audio.pack")
    assert (dep_dir / "audio" / "99999.wem").read_bytes() == b"INCOMING_WEM_DATA"
    assert (dep_dir / "audio" / "event_data.dat").read_bytes() == b"INCOMING_EVENT_DB"

    # Explicit revert cleans up local files
    assert project.revert_wem_completely(99999) is True
    assert 99999 not in project.manifest.staged_wems
    assert not (project.audio_dir / "99999.wem").exists()

    assert project.revert_database() is True
    assert not project.manifest.has_custom_event_db
    assert not (project.audio_dir / "event_data.dat").exists()
    assert (dep_dir / "audio" / "event_data.dat").read_bytes() == b"INCOMING_EVENT_DB"


def test_dependency_manager_case_insensitive_bank_conflict(tmp_path):
    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)
    project.save_bank("battle.bnk", b"LOCAL_BATTLE")

    pack_path = tmp_path / "dep.pack"
    files = {
        "audio/BATTLE.BNK": b"INCOMING_BATTLE",
    }
    _create_test_pack(pack_path, files)

    mgr = DependencyManager(project)
    plan = mgr.plan_import(pack_path)

    assert len(plan.conflicts) == 1
    assert plan.conflicts[0].conflict_type == ConflictType.BANK_MODIFIED


def test_dependency_manager_rejects_path_traversal(tmp_path):
    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)

    # Synthesize raw PFH4 pack containing a directory traversal path
    pack_path = tmp_path / "malicious.pack"
    import struct

    idx_buf = bytearray()
    idx_buf.extend(struct.pack("<I", 4))
    idx_buf.extend(b"audio/../../evil.wem\x00")
    hdr = struct.pack("<4sIIIIII", b"PFH4", 4, 0, 0, 1, len(idx_buf), 0)
    pack_path.write_bytes(hdr + idx_buf + b"EVIL")

    mgr = DependencyManager(project)
    with pytest.raises(ValueError, match="traversal"):
        mgr.plan_import(pack_path)


def test_dependency_manager_reorder_and_remove(tmp_path):
    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)

    pack1 = tmp_path / "dep1.pack"
    _create_test_pack(pack1, {"audio/p1.bnk": b"P1"})
    pack2 = tmp_path / "dep2.pack"
    _create_test_pack(pack2, {"audio/p2.bnk": b"P2"})

    mgr = DependencyManager(project)
    plan1 = mgr.plan_import(pack1, priority=1)
    mgr.execute_import(plan1)

    plan2 = mgr.plan_import(pack2, priority=2)
    mgr.execute_import(plan2)

    # Check initial order
    dep_names = [d.name for d in project.manifest.dependencies]
    assert dep_names == ["dep1.pack", "dep2.pack"]
    assert project.manifest.dependencies[0].priority == 1
    assert project.manifest.dependencies[1].priority == 2

    # Reorder
    mgr.reorder_dependencies(["dep2.pack", "dep1.pack"])
    dep_priorities = {d.name: d.priority for d in project.manifest.dependencies}
    assert dep_priorities["dep2.pack"] == 0
    assert dep_priorities["dep1.pack"] == 1

    # Remove dep1
    # Also stage a user file to ensure user files are preserved
    project.save_bank("user.bnk", b"USER_SAVED")
    dep1_dir = project.get_dependency_dir("dep1.pack")
    assert dep1_dir.is_dir()

    mgr.remove_dependency("dep1.pack")
    assert not dep1_dir.exists()
    assert [d.name for d in project.manifest.dependencies] == ["dep2.pack"]
    assert (project.audio_dir / "user.bnk").read_bytes() == b"USER_SAVED"
    assert "user.bnk" in project.manifest.modified_banks


def test_dependency_manager_reimport_updates_existing(tmp_path):
    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)

    pack_path = tmp_path / "dep.pack"
    _create_test_pack(pack_path, {"audio/v1.bnk": b"VERSION_1"})

    mgr = DependencyManager(project)
    plan1 = mgr.plan_import(pack_path)
    assert plan1.priority == 0
    mgr.execute_import(plan1)

    assert len(project.manifest.dependencies) == 1
    assert project.manifest.dependencies[0].extracted_audio_files == ["audio/v1.bnk"]

    # Now update pack with v2
    _create_test_pack(pack_path, {"audio/v2.bnk": b"VERSION_2"})
    plan2 = mgr.plan_import(pack_path)
    # Existing priority preserved
    assert plan2.priority == 0
    mgr.execute_import(plan2)

    assert len(project.manifest.dependencies) == 1
    assert project.manifest.dependencies[0].extracted_audio_files == ["audio/v2.bnk"]
    dep_dir = project.get_dependency_dir("dep.pack")
    assert (dep_dir / "audio" / "v2.bnk").read_bytes() == b"VERSION_2"


def test_dependency_manager_error_cases(tmp_path):
    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)
    mgr = DependencyManager(project)

    # Missing file
    with pytest.raises(FileNotFoundError):
        mgr.plan_import(tmp_path / "nonexistent.pack")

    # Malformed pack with drive letter in entry
    import struct

    idx_buf = bytearray()
    idx_buf.extend(struct.pack("<I", 4))
    idx_buf.extend(b"C:/evil.wem\x00")
    hdr = struct.pack("<4sIIIIII", b"PFH4", 4, 0, 0, 1, len(idx_buf), 0)
    bad_pack = tmp_path / "bad.pack"
    bad_pack.write_bytes(hdr + idx_buf + b"DATA")

    with pytest.raises(ValueError, match="drive letter"):
        mgr.plan_import(bad_pack)

    # Reorder unknown dependency
    project.manifest.dependencies.append(DependencyPackInfo(name="dummy.pack", source_path=""))
    with pytest.raises(ValueError, match="not found in project"):
        mgr.reorder_dependencies(["nonexistent.pack"])

    # Remove unknown dependency
    with pytest.raises(ValueError, match="not found in project"):
        mgr.remove_dependency("nonexistent.pack")


def test_dependency_manager_case_insensitive_reorder_and_remove(tmp_path):
    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)

    pack1 = tmp_path / "AlphaMod.pack"
    _create_test_pack(pack1, {"audio/alpha.bnk": b"ALPHA"})
    pack2 = tmp_path / "BetaMod.pack"
    _create_test_pack(pack2, {"audio/beta.bnk": b"BETA"})

    mgr = DependencyManager(project)
    mgr.execute_import(mgr.plan_import(pack1))
    mgr.execute_import(mgr.plan_import(pack2))

    # Reorder with different casing
    mgr.reorder_dependencies(["betamod.pack", "ALPHAMOD.PACK"])
    dep_priorities = {d.name.lower(): d.priority for d in project.manifest.dependencies}
    assert dep_priorities["betamod.pack"] == 0
    assert dep_priorities["alphamod.pack"] == 1

    # Remove with uppercase casing
    mgr.remove_dependency("BETAMOD.PACK")
    assert len(project.manifest.dependencies) == 1
    assert project.manifest.dependencies[0].name == "AlphaMod.pack"


def test_dependency_manager_reorder_validation_errors(tmp_path):
    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)

    pack1 = tmp_path / "dep1.pack"
    _create_test_pack(pack1, {"audio/p1.bnk": b"P1"})
    pack2 = tmp_path / "dep2.pack"
    _create_test_pack(pack2, {"audio/p2.bnk": b"P2"})

    mgr = DependencyManager(project)
    mgr.execute_import(mgr.plan_import(pack1))
    mgr.execute_import(mgr.plan_import(pack2))

    # Duplicate names in new_order
    with pytest.raises(ValueError, match="duplicate"):
        mgr.reorder_dependencies(["dep1.pack", "dep1.pack"])

    # Wrong length
    with pytest.raises(ValueError, match="Expected 2 dependencies"):
        mgr.reorder_dependencies(["dep1.pack"])


def test_dependency_manager_root_level_audio_files(tmp_path):
    project_dir = tmp_path / "project"
    project = ProjectStorage.create_project(project_dir, name="TestMod", game=GameType.ATTILA)

    # Some packs place .bnk and .wem at archive root without "audio/" prefix
    pack_path = tmp_path / "root_audio.pack"
    files = {
        "root_bank.bnk": b"ROOT_BANK_DATA",
        "7777.wem": b"ROOT_WEM_DATA",
        "event_data.dat": b"ROOT_EVENT_DATA",
    }
    _create_test_pack(pack_path, files)

    mgr = DependencyManager(project)
    plan = mgr.plan_import(pack_path)

    audio_vpaths = [vpath for vpath, _ in plan.safe_audio_files]
    assert "audio/root_bank.bnk" in audio_vpaths
    assert "audio/7777.wem" in audio_vpaths
    assert "audio/event_data.dat" in audio_vpaths

    mgr.execute_import(plan)
    dep_dir = project.get_dependency_dir("root_audio.pack")
    assert (dep_dir / "audio" / "root_bank.bnk").read_bytes() == b"ROOT_BANK_DATA"
    assert (dep_dir / "audio" / "7777.wem").read_bytes() == b"ROOT_WEM_DATA"
    assert (dep_dir / "audio" / "event_data.dat").read_bytes() == b"ROOT_EVENT_DATA"


def test_workspace_exports():
    import src.workspace as ws

    assert hasattr(ws, "ConflictType")
    assert hasattr(ws, "ResolutionAction")
    assert hasattr(ws, "ImportConflict")
    assert hasattr(ws, "ImportPlan")
    assert hasattr(ws, "DependencyManager")
    assert hasattr(ws, "DependencyPackInfo")
