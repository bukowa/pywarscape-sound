from pathlib import Path

from src.compiler.pfh4_pack import read_pfh4_index, write_pfh4_movie_pack
from src.workspace.dependencies import (
    ConflictType,
    DependencyManager,
    ResolutionAction,
)
from src.workspace.game import GameType
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject
from src.workspace.storage import ProjectStorage

TSV_MK_UNITS = """key\tselection_vo\tselected_vo_secondary\tselected_vo_tertiary\tculture\tsubculture\tcategory
mk_knights_templar\tvo_crusader\t\t\tculture_latin\tsubculture_crusader\tcavalry
"""

TSV_MK_UNITS_V2 = """key\tselection_vo\tselected_vo_secondary\tselected_vo_tertiary\tculture\tsubculture\tcategory
mk_knights_templar\tvo_crusader_v2\t\t\tculture_latin\tsubculture_crusader\tcavalry
"""


def test_end_to_end_dependency_lifecycle_and_submod_packaging(tmp_path: Path):
    # 1. Initialize fresh project
    proj_dir = tmp_path / "CrusaderSoundSubmod"
    manifest = ProjectManifest(name="CrusaderSoundSubmod", game=GameType.ATTILA)
    project = AudioProject(root_dir=proj_dir, manifest=manifest)
    ProjectStorage.save_project(project)

    # 2. Synthesize external overhaul dependency .pack
    dep_pack_path = tmp_path / "custom_overhaul.pack"
    dep_files = {
        "audio/mk_music.bnk": b"DEP_ORIGINAL_MUSIC_BNK",
        "audio/5555.wem": b"DEP_STREAM_5555_WEM",
        "audio/event_data.dat": b"DEP_EVENT_DATABASE",
        "db/land_units_tables/mk_units": TSV_MK_UNITS.encode("utf-8"),
        "ui/textures/crusader_banner.png": b"IGNORED_TEXTURE_DATA",
    }
    write_pfh4_movie_pack(dep_pack_path, dep_files)

    # 3. Ingest pack via DependencyManager
    mgr = DependencyManager(project)
    plan = mgr.plan_import(dep_pack_path, priority=1)

    assert plan.pack_name == "custom_overhaul.pack"
    assert len(plan.conflicts) == 0
    assert len(plan.safe_audio_files) == 3
    assert len(plan.safe_db_files) == 1

    mgr.execute_import(plan)

    assert len(project.manifest.dependencies) == 1
    assert project.manifest.dependencies[0].name == "custom_overhaul.pack"

    # 4. Query unit in AudioMetadataCatalog
    catalog = project.load_metadata_catalog()
    unit = catalog.get_unit("mk_knights_templar")
    assert unit is not None
    assert unit.key == "mk_knights_templar"
    assert unit.selection_vo == "vo_crusader"
    assert unit.category == "cavalry"

    # 5. Resolve assets via AssetResolver -> resolves to dependency layer
    resolver = project.resolver
    bank_p = resolver.resolve_bank_path("mk_music.bnk")
    assert bank_p is not None
    assert bank_p.read_bytes() == b"DEP_ORIGINAL_MUSIC_BNK"
    assert "dependencies" in str(bank_p)

    wem_p = resolver.resolve_wem_path(5555)
    assert wem_p is not None
    assert wem_p.read_bytes() == b"DEP_STREAM_5555_WEM"
    assert "dependencies" in str(wem_p)

    db_p = resolver.resolve_database_path()
    assert db_p is not None
    assert db_p.read_bytes() == b"DEP_EVENT_DATABASE"

    # 6. Copy-on-Write: Modify soundbank in project
    project.save_bank("mk_music.bnk", b"LOCAL_USER_EDITED_MUSIC_BNK")
    assert "mk_music.bnk" in project.manifest.modified_banks

    # Now AssetResolver must resolve to the local user modification in pack_root/audio/
    resolved_edited = resolver.resolve_bank_path("mk_music.bnk")
    assert resolved_edited is not None
    assert resolved_edited.read_bytes() == b"LOCAL_USER_EDITED_MUSIC_BNK"
    assert "pack_root" in str(resolved_edited)

    # 7. Re-import updated dependency pack (which also changed mk_music.bnk)
    updated_dep_files = {
        "audio/mk_music.bnk": b"DEP_V2_MUSIC_BNK",
        "audio/5555.wem": b"DEP_V2_STREAM_5555_WEM",
        "audio/event_data.dat": b"DEP_V2_EVENT_DATABASE",
        "db/land_units_tables/mk_units": TSV_MK_UNITS_V2.encode("utf-8"),
    }
    write_pfh4_movie_pack(dep_pack_path, updated_dep_files)

    plan_reimport = mgr.plan_import(dep_pack_path)
    assert len(plan_reimport.conflicts) == 1
    conflict = plan_reimport.conflicts[0]
    assert conflict.virtual_path == "audio/mk_music.bnk"
    assert conflict.conflict_type == ConflictType.BANK_MODIFIED

    # Test KEEP_LOCAL resolution
    mgr.execute_import(plan_reimport, {"audio/mk_music.bnk": ResolutionAction.KEEP_LOCAL})
    assert resolver.resolve_bank_path("mk_music.bnk").read_bytes() == b"LOCAL_USER_EDITED_MUSIC_BNK"
    assert "mk_music.bnk" in project.manifest.modified_banks

    # Test OVERWRITE_LOCAL resolution: dependencies never overwrite Tier 1 local mod files
    plan_reimport2 = mgr.plan_import(dep_pack_path)
    mgr.execute_import(plan_reimport2, {"audio/mk_music.bnk": ResolutionAction.OVERWRITE_LOCAL})
    assert "mk_music.bnk" in project.manifest.modified_banks
    assert resolver.resolve_bank_path("mk_music.bnk").read_bytes() == b"LOCAL_USER_EDITED_MUSIC_BNK"

    # Explicit revert cleanly adopts the dependency baseline
    reverted_banks, _ = project.revert_bank_completely("mk_music.bnk")
    assert reverted_banks == 1
    assert "mk_music.bnk" not in project.manifest.modified_banks
    assert resolver.resolve_bank_path("mk_music.bnk").read_bytes() == b"DEP_V2_MUSIC_BNK"

    # 8. Lightweight submod packaging verification:
    # Add a user modded bank and a staged wem
    project.save_bank("submod_unique.bnk", b"SUBMOD_UNIQUE_SOUNDS")
    project.stage_wem(9999, b"SUBMOD_UNIQUE_VOICE_STREAM")

    # Mod packaging strictly gathers user modifications from pack_root/audio/
    output_pack_path = tmp_path / "CrusaderSubmod_Release.pack"
    user_files = {}
    for p in project.audio_dir.iterdir():
        if p.is_file():
            user_files[f"audio/{p.name}"] = p.read_bytes()

    compiled_pack = write_pfh4_movie_pack(output_pack_path, user_files)
    assert compiled_pack.is_file()

    # Verify compiled pack contents
    entries = read_pfh4_index(compiled_pack)
    entry_paths = [e.path.replace("\\", "/") for e in entries]

    # Must contain ONLY user modifications
    assert "audio/submod_unique.bnk" in entry_paths
    assert "audio/9999.wem" in entry_paths

    # Must NOT contain untouched dependency assets or db tables
    assert not any("5555.wem" in p for p in entry_paths)
    assert not any("event_data.dat" in p for p in entry_paths)
    assert not any("db/" in p for p in entry_paths)
    assert not any("mk_units" in p for p in entry_paths)
    assert len(entry_paths) == 2


def test_multi_dependency_stacking_persistence_and_reopen(tmp_path: Path):
    proj_dir = tmp_path / "MultiStackMod"
    project = ProjectStorage.create_project(proj_dir, name="MultiStackMod", game=GameType.ATTILA)

    # 1. Base overhaul pack (priority 1)
    pack1_path = tmp_path / "base_overhaul.pack"
    tsv_units_base = "key\tselection_vo\tselected_vo_secondary\tselected_vo_tertiary\tculture\tsubculture\tcategory\nunit_templar\tvo_templar_base\t\t\tculture_latin\tsubculture_crusader\tcavalry\n"
    pack1_files = {
        "audio/shared_battle.bnk": b"PACK1_BATTLE_BNK",
        "audio/1001.wem": b"PACK1_WEM_1001",
        "db/land_units_tables/units_base": tsv_units_base.encode("utf-8"),
    }
    write_pfh4_movie_pack(pack1_path, pack1_files)

    # 2. Sub-expansion pack (priority 0, highest precedence)
    pack2_path = tmp_path / "vo_submod.pack"
    tsv_units_expansion = "key\tselection_vo\tselected_vo_secondary\tselected_vo_tertiary\tculture\tsubculture\tcategory\nunit_templar\tvo_templar_expansion\t\t\tculture_latin\tsubculture_crusader\tcavalry\n"
    pack2_files = {
        "audio/shared_battle.bnk": b"PACK2_BATTLE_BNK",
        "audio/2002.wem": b"PACK2_WEM_2002",
        "db/land_units_tables/units_exp": tsv_units_expansion.encode("utf-8"),
    }
    write_pfh4_movie_pack(pack2_path, pack2_files)

    # Ingest both: sub-expansion with priority 0 (higher), base with priority 1 (lower)
    mgr = DependencyManager(project)
    mgr.execute_import(mgr.plan_import(pack2_path, priority=0))
    mgr.execute_import(mgr.plan_import(pack1_path, priority=1))

    # User modifies shared_battle.bnk in pack_root/audio/ and stages 3003.wem
    project.save_bank("shared_battle.bnk", b"USER_CUSTOM_BATTLE_BNK")
    project.stage_wem(3003, b"USER_CUSTOM_WEM_3003")
    ProjectStorage.save_project(project)

    # 3. Simulate new session by reloading project from disk
    reloaded = ProjectStorage.open_project(proj_dir)
    assert len(reloaded.manifest.dependencies) == 2
    assert [d.name for d in reloaded.manifest.dependencies] == [
        "vo_submod.pack",
        "base_overhaul.pack",
    ]

    # 4. Verify asset resolution on reloaded project
    resolver = reloaded.resolver
    assert resolver.resolve_bank_bytes("shared_battle.bnk") == b"USER_CUSTOM_BATTLE_BNK"
    assert resolver.resolve_wem_bytes(1001) == b"PACK1_WEM_1001"
    assert resolver.resolve_wem_bytes(2002) == b"PACK2_WEM_2002"
    assert resolver.resolve_wem_bytes(3003) == b"USER_CUSTOM_WEM_3003"

    # 5. Verify metadata catalog on reloaded project
    catalog = reloaded.load_metadata_catalog()
    unit = catalog.get_unit("unit_templar")
    assert unit is not None
    # Higher priority sub-expansion should override base
    assert unit.selection_vo == "vo_templar_expansion"

    # 6. Reorder dependencies and verify precedence flips
    mgr_reloaded = DependencyManager(reloaded)
    mgr_reloaded.reorder_dependencies(["base_overhaul.pack", "vo_submod.pack"])
    # Now base (base_overhaul.pack) is priority 0 (higher) and vo_submod is priority 1 (lower)
    # Revert user modification to test dependency resolution
    reloaded.revert_bank("shared_battle.bnk")
    assert reloaded.resolver.resolve_bank_bytes("shared_battle.bnk") == b"PACK1_BATTLE_BNK"

    # 7. Remove dependency and verify cleanup
    dep1_dir = reloaded.get_dependency_dir("base_overhaul.pack")
    assert dep1_dir.is_dir()
    mgr_reloaded.remove_dependency("base_overhaul.pack")
    assert not dep1_dir.exists()
    assert len(reloaded.manifest.dependencies) == 1
    assert reloaded.resolver.resolve_bank_bytes("shared_battle.bnk") == b"PACK2_BATTLE_BNK"
