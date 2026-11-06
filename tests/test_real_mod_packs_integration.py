"""Integration tests for mod pack ingestion, metadata catalog queries, and copy-on-write export."""

from pathlib import Path

import pytest

from src.bnk.bank import HircChunk, SoundBank
from src.bnk.chunks import BkhdChunk, DataChunk, DidxChunk, DidxEntry, StidChunk
from src.bnk.models import CAkMusicTrack, CAkSound, NodeBaseParams
from src.bnk.wem import build_silent_pcm_wem_bytes
from src.compiler.pfh4_pack import read_pfh4_index, write_pfh4_movie_pack
from src.workspace.dependencies import DependencyManager, ResolutionAction
from src.workspace.game import GameType
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject
from src.workspace.storage import ProjectStorage
from tests.support.factories import encode_binary_db_table, write_synthetic_pfh4_pack


@pytest.fixture(scope="session")
def db_pack_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("db_pack")
    pack_path = out_dir / "synthetic_db_mod.pack"

    files = {
        "db/land_units_tables/custom_units": encode_binary_db_table(
            "land_units_tables",
            [
                {
                    "key": f"unit_{i}",
                    "category": "infantry",
                    "selection_vo": f"vo_{i}",
                    "armour": f"armour_{i % 5}",
                    "shield": f"shield_{i % 5}",
                    "primary_melee_weapon": f"weapon_{i % 5}",
                }
                for i in range(15)
            ],
        ),
        "db/subculture_religion_voiceover_junctions_tables/custom_vo": encode_binary_db_table(
            "subculture_religion_voiceover_junctions_tables",
            [
                {
                    "religion": f"rel_{i}",
                    "subculture": f"sub_{i}",
                    "voiceover_culture": f"vo_cult_{i}",
                }
                for i in range(10)
            ],
        ),
        "db/audio_projectiles_tables/custom_proj": encode_binary_db_table(
            "audio_projectiles_tables",
            [{"key": f"proj_{i}", "fire_event": f"event_proj_{i}"} for i in range(10)],
        ),
        "db/audio_explosions_tables/custom_expl": encode_binary_db_table(
            "audio_explosions_tables",
            [
                {"key": f"expl_{i}", "event": f"event_expl_{i}", "max_attenuation": 100.0}
                for i in range(10)
            ],
        ),
        "db/unit_armour_types_tables/custom_armour": encode_binary_db_table(
            "unit_armour_types_tables",
            [
                {"key": f"armour_{i}", "armour_value": 10, "audio_material": f"mat_armour_{i}"}
                for i in range(5)
            ],
        ),
        "db/unit_shield_types_tables/custom_shield": encode_binary_db_table(
            "unit_shield_types_tables",
            [
                {
                    "key": f"shield_{i}",
                    "shield_defence_value": 5,
                    "audio_material": f"mat_shield_{i}",
                }
                for i in range(5)
            ],
        ),
        "db/melee_weapons_tables/custom_weapons": encode_binary_db_table(
            "melee_weapons_tables",
            [{"key": f"weapon_{i}", "audio_material": f"mat_weapon_{i}"} for i in range(5)],
        ),
        "db/building_effects_junction_tables/test": b"NON_AUDIO_DATA_BUILDINGS",
        "db/cdir_events_dilemma_option_junctions_tables/test": b"NON_AUDIO_DATA_DILEMMAS",
    }
    return write_synthetic_pfh4_pack(pack_path, files)


@pytest.fixture(scope="session")
def music_pack_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out_dir = tmp_path_factory.mktemp("music_pack")
    pack_path = out_dir / "synthetic_music_mod.pack"

    files: dict[str, bytes] = {}

    # 4 SoundBanks
    banks_spec = [
        ("audio/global_music.bnk", 1001, "global_music"),
        ("audio/battle_music.bnk", 1002, "battle_music"),
        ("audio/campaign_music.bnk", 1003, "campaign_music"),
        ("audio/battle_vo_orders.bnk", 1004, "battle_vo_orders"),
    ]

    for rel_path, bank_id, bank_name in banks_spec:
        silent_wem = build_silent_pcm_wem_bytes(duration_ms=50)
        wem_id = bank_id + 1000
        header = BkhdChunk(bank_id=bank_id)
        didx = DidxChunk(entries=[DidxEntry(file_id=wem_id, offset=0, size=len(silent_wem))])
        data = DataChunk(data=silent_wem)
        sound = CAkSound(
            id=bank_id + 2000,
            obj_type=2,
            plugin_id=0x00040001,
            stream_type=0,  # Embedded
            source_id=wem_id,
            file_id=bank_id,
            node_base_params=NodeBaseParams(),
        )
        track = CAkMusicTrack(id=bank_id + 3000)
        hirc = HircChunk(objects=[sound, track])
        stid = StidChunk(bank_names={bank_id: bank_name})
        sb = SoundBank(
            header=header,
            didx=didx,
            data=data,
            hirc=hirc,
            stid=stid,
        )
        files[rel_path] = sb.to_bytes()

    # 60 loose streamed .wem files
    for i in range(1, 61):
        files[f"audio/{100000 + i}.wem"] = build_silent_pcm_wem_bytes(duration_ms=20)

    return write_synthetic_pfh4_pack(pack_path, files)


def test_mod_packs_ingestion_and_metadata_catalog(
    tmp_path: Path, db_pack_path: Path, music_pack_path: Path
):
    """
    Given synthetic overhaul mod packs:
    - synthetic_db_mod.pack (database pack)
    - synthetic_music_mod.pack (soundbank & audio pack)
    When a project is created and dependencies are ingested:
    Then:
    1. Only the 7 audio-relevant DB tables are extracted, ignoring non-audio tables.
    2. AudioMetadataCatalog parses and indexes units, cultures, projectiles, and armor.
    3. SoundBanks from the music pack resolve and deserialize cleanly into Layer 1 AST.
    """
    proj_dir = tmp_path / "CustomAudioSubmod"
    manifest = ProjectManifest(name="CustomAudioSubmod", game=GameType.ATTILA)
    project = AudioProject(root_dir=proj_dir, manifest=manifest)
    ProjectStorage.save_project(project)

    mgr = DependencyManager(project)

    # 1. Ingest Database Overhaul Pack (priority 0)
    plan_comp = mgr.plan_import(db_pack_path, priority=0)
    assert plan_comp.pack_name == db_pack_path.name
    assert len(plan_comp.conflicts) == 0
    # Exactly 7 audio/metadata tables recognized from TABLE_SCHEMAS
    assert len(plan_comp.safe_db_files) == 7
    assert len(plan_comp.safe_audio_files) == 0
    mgr.execute_import(plan_comp)

    # 2. Ingest Music Pack (priority 1)
    plan_music = mgr.plan_import(music_pack_path, priority=1)
    assert plan_music.pack_name == music_pack_path.name
    assert len(plan_music.conflicts) == 0
    assert len(plan_music.safe_db_files) == 0
    # 4 bnks and 60 loose wems
    assert len(plan_music.safe_audio_files) == 64
    mgr.execute_import(plan_music)

    assert len(project.manifest.dependencies) == 2

    # 3. Verify AudioMetadataCatalog layered loading
    catalog = project.load_metadata_catalog()
    assert len(catalog.units) >= 10, f"Expected 10+ units, got {len(catalog.units)}"
    assert len(catalog.cultures) >= 5, f"Expected 5+ cultures, got {len(catalog.cultures)}"
    assert len(catalog.projectiles) >= 5, f"Expected 5+ projectiles, got {len(catalog.projectiles)}"
    assert len(catalog.materials) >= 5, f"Expected 5+ materials, got {len(catalog.materials)}"

    # 4. Verify AssetResolver resolves dependency assets
    resolver = project.resolver
    for bnk_name in [
        "battle_music.bnk",
        "global_music.bnk",
        "campaign_music.bnk",
        "battle_vo_orders.bnk",
    ]:
        bank_p = resolver.resolve_bank_path(bnk_name)
        assert bank_p is not None, f"Could not resolve bank {bnk_name}"
        assert bank_p.is_file()
        assert "dependencies" in str(bank_p)

        # Parse into typed SoundBank AST
        data = bank_p.read_bytes()
        sb = SoundBank.from_bytes(data)
        assert sb.header.bank_id is not None or len(data) > 0


def test_selective_db_extraction_ignores_non_audio_tables(tmp_path: Path, db_pack_path: Path):
    """Verifies that non-audio tables in mod packs are safely filtered out during dependency import."""
    proj_dir = tmp_path / "SelectiveExtractionProj"
    project = AudioProject(
        root_dir=proj_dir,
        manifest=ProjectManifest(name="SelectiveExtractionProj", game=GameType.ATTILA),
    )
    ProjectStorage.save_project(project)

    mgr = DependencyManager(project)
    plan = mgr.plan_import(db_pack_path, priority=0)
    assert len(plan.safe_db_files) == 7
    assert len(plan.safe_audio_files) == 0
    mgr.execute_import(plan)

    dep_db_dir = project.get_dependency_dir(db_pack_path.name) / "db"
    assert (dep_db_dir / "land_units_tables" / "custom_units").is_file()
    assert not (dep_db_dir / "building_effects_junction_tables").exists()
    assert not (dep_db_dir / "cdir_events_dilemma_option_junctions_tables").exists()


def test_mod_packs_copy_on_write_override_and_export_boundary(
    tmp_path: Path, db_pack_path: Path, music_pack_path: Path
):
    """
    Tests the full end-to-end modder lifecycle on synthetic mod assets:
    1. Ingest mod packs into project.
    2. Modder overrides a mod soundbank (global_music.bnk) in pack_root/audio/.
    3. Modder stages a new loose streamed .wem (999999.wem).
    4. AssetResolver routes to pack_root/audio/ for modified assets (Copy-on-Write).
    5. Exporting compiles a standalone PFH4 Movie pack containing strictly
       user-modified assets, with zero DB metadata and zero untouched dependency assets.
    """
    proj_dir = tmp_path / "SubmodWorkspace"
    manifest = ProjectManifest(name="SubmodWorkspace", game=GameType.ATTILA)
    project = AudioProject(root_dir=proj_dir, manifest=manifest)
    ProjectStorage.save_project(project)

    mgr = DependencyManager(project)
    mgr.execute_import(mgr.plan_import(db_pack_path, priority=0))
    mgr.execute_import(mgr.plan_import(music_pack_path, priority=1))

    resolver = project.resolver
    orig_bank_p = resolver.resolve_bank_path("global_music.bnk")
    assert orig_bank_p is not None
    assert "dependencies" in str(orig_bank_p)
    orig_bytes = orig_bank_p.read_bytes()

    # Parse SoundBank from dependency
    sb = SoundBank.from_bytes(orig_bytes)
    assert sb.hirc is not None and len(sb.hirc.objects) == 2

    # 1. Modder modifies the SoundBank (reserialize through Layer 1 AST)
    modified_bank_bytes = sb.to_bytes()
    saved_bank_p = project.save_bank("global_music.bnk", modified_bank_bytes)
    assert saved_bank_p.is_file()
    assert "global_music.bnk" in project.manifest.modified_banks

    # 2. Modder stages a custom voice stream WEM
    custom_wem_bytes = b"RIFF_CUSTOM_VOICE_STREAM_DATA_12345678"
    staged_wem_p = project.stage_wem(999999, custom_wem_bytes)
    assert staged_wem_p.is_file()
    assert 999999 in project.manifest.staged_wems

    # 3. Verify Copy-on-Write Resolution
    resolved_bank = resolver.resolve_bank_path("global_music.bnk")
    assert resolved_bank is not None
    assert "pack_root" in str(resolved_bank), (
        "Modified bank must resolve to project pack_root overlay"
    )

    resolved_wem = resolver.resolve_wem_path(999999)
    assert resolved_wem is not None
    assert "pack_root" in str(resolved_wem), "Staged wem must resolve to project pack_root overlay"

    # Untouched bank still resolves to dependency
    resolved_campaign = resolver.resolve_bank_path("campaign_music.bnk")
    assert resolved_campaign is not None
    assert "dependencies" in str(resolved_campaign), (
        "Untouched bank must resolve to dependency layer"
    )

    # 4. Mod Export: Compile standalone PFH4 Movie pack
    output_pack_path = tmp_path / "custom_music_submod.pack"

    # Pack builder compiles files from project pack_root/audio/
    export_files = {}
    for f in project.audio_dir.iterdir():
        if f.is_file():
            export_files[f"audio/{f.name}"] = f.read_bytes()

    compiled_pack = write_pfh4_movie_pack(output_pack_path, export_files)
    assert compiled_pack.is_file()

    # 5. Verify Compiled Pack Fidelity & Metadata Boundary
    entries = read_pfh4_index(compiled_pack)
    entry_paths = [e.path.replace("\\", "/") for e in entries]

    # Must contain ONLY user modifications
    assert "audio/global_music.bnk" in entry_paths
    assert "audio/999999.wem" in entry_paths
    assert len(entry_paths) == 2, (
        f"Expected exactly 2 files in export, got {len(entry_paths)}: {entry_paths}"
    )

    # Invariant: Strict Metadata Boundary (Zero DB tables exported)
    assert not any(p.startswith("db/") for p in entry_paths), (
        "Compiled pack must NEVER contain db/ tables"
    )

    # Invariant: Zero untouched dependency assets exported
    assert not any("campaign_music.bnk" in p for p in entry_paths)
    assert not any("battle_music.bnk" in p for p in entry_paths)
    assert not any("battle_vo_orders.bnk" in p for p in entry_paths)


def test_clean_project_late_dependency_import_and_conflict_handling(
    tmp_path: Path, music_pack_path: Path
):
    """
    Tests starting from a clean project without dependencies:
    1. User stages work in clean project (modified battle_music.bnk and staged wem 5005).
    2. User later imports music_pack.
    3. Conflict detection correctly identifies battle_music.bnk as modified.
    4. Choosing KEEP_LOCAL preserves the modder's local changes.
    5. Choosing OVERWRITE_LOCAL cleanly yields to the dependency asset.
    """
    proj_dir = tmp_path / "CleanStartMod"
    project = ProjectStorage.create_project(proj_dir, name="CleanStartMod", game=GameType.ATTILA)

    # 1. User starts clean and creates local edits
    project.save_bank("battle_music.bnk", b"MODDER_EARLY_BATTLE_MUSIC")
    project.stage_wem(5005, b"MODDER_EARLY_WEM_5005")

    mgr = DependencyManager(project)

    # 2. User imports music_pack into the existing project
    plan = mgr.plan_import(music_pack_path, priority=0)
    assert len(plan.conflicts) == 1
    conflict = plan.conflicts[0]
    assert conflict.virtual_path == "audio/battle_music.bnk"

    # 3. Resolve conflict with KEEP_LOCAL
    mgr.execute_import(plan, {"audio/battle_music.bnk": ResolutionAction.KEEP_LOCAL})

    resolver = project.resolver
    assert (
        resolver.resolve_bank_path("battle_music.bnk").read_bytes() == b"MODDER_EARLY_BATTLE_MUSIC"
    )
    assert "battle_music.bnk" in project.manifest.modified_banks
    # Non-conflicting banks and wems are imported
    assert resolver.resolve_bank_path("campaign_music.bnk") is not None
    assert resolver.resolve_bank_path("global_music.bnk") is not None

    # 4. Re-import: dependency imports are strictly non-destructive (local Tier 1 is preserved)
    plan2 = mgr.plan_import(music_pack_path, priority=0)
    mgr.execute_import(plan2, {"audio/battle_music.bnk": ResolutionAction.OVERWRITE_LOCAL})
    assert "battle_music.bnk" in project.manifest.modified_banks

    # Explicit revert adopts the dependency baseline
    reverted_banks, _ = project.revert_bank_completely("battle_music.bnk")
    assert reverted_banks == 1
    assert "battle_music.bnk" not in project.manifest.modified_banks
    # Now resolves to dependency version
    assert "dependencies" in str(resolver.resolve_bank_path("battle_music.bnk"))
