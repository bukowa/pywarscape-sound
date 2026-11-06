from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.engine.session import WorkspaceSession
from src.ui.features.bank_viewer.causation import reconcile_viewer
from src.ui.features.bank_viewer.state import (
    BankListItem,
    BankModificationKind,
    BankStatus,
    BankViewerState,
    FilterModifiedOnlyToggled,
)
from src.ui.features.bank_viewer.store import BankViewerStore
from src.workspace.cache import GameCache
from src.workspace.game import GameType
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject
from src.workspace.storage import ProjectStorage


def test_bank_modification_kinds_and_filtering(tmp_path: Path):
    cache_dir = tmp_path / "cache" / "audio"
    cache_dir.mkdir(parents=True)
    # Bank 1: vanilla only
    (cache_dir / "vanilla.bnk").write_bytes(b"VANILLA_BNK")
    # Bank 2: structure only modified
    (cache_dir / "struct_mod.bnk").write_bytes(b"STRUCT_BNK")
    # Bank 3: audio only modified (has staged loose wem)
    (cache_dir / "audio_mod.bnk").write_bytes(b"AUDIO_BNK")
    # Bank 4: both structure and audio modified
    (cache_dir / "full_mod.bnk").write_bytes(b"FULL_BNK")

    cache = GameCache(GameType.ATTILA, cache_dir=cache_dir)
    # Mock media IDs for each bank
    cache.get_bank_media_ids = MagicMock(
        side_effect=lambda name: {
            "vanilla.bnk": frozenset({1001}),
            "struct_mod.bnk": frozenset({2002}),
            "audio_mod.bnk": frozenset({3003}),
            "full_mod.bnk": frozenset({4004}),
        }.get(name.lower(), frozenset())
    )

    proj_dir = tmp_path / "ModKindProj"
    project = ProjectStorage.create_project(
        proj_dir, name="ModKindProj", game=GameType.ATTILA, cache=cache
    )

    # 1. Modify structure of struct_mod.bnk
    project.save_bank("struct_mod.bnk", b"LOCAL_STRUCT_BYTES")

    # 2. Stage audio 3003 (contained in audio_mod.bnk, but audio_mod.bnk itself is NOT modified)
    project.stage_wem(3003, b"CUSTOM_AUDIO_3003")

    # 3. Modify structure of full_mod.bnk AND stage audio 4004
    project.save_bank("full_mod.bnk", b"LOCAL_FULL_BYTES")
    project.stage_wem(4004, b"CUSTOM_AUDIO_4004")

    store = BankViewerStore(project=project)

    items = {item.name.lower(): item for item in store.state.available_banks}

    # Verify vanilla.bnk
    assert "vanilla.bnk" in items
    assert items["vanilla.bnk"].status == BankStatus.VANILLA
    assert items["vanilla.bnk"].modification_kind == BankModificationKind.NONE

    # Verify struct_mod.bnk
    assert "struct_mod.bnk" in items
    assert items["struct_mod.bnk"].status == BankStatus.MODIFIED
    assert items["struct_mod.bnk"].modification_kind == BankModificationKind.STRUCTURE

    # Verify audio_mod.bnk
    assert "audio_mod.bnk" in items
    assert items["audio_mod.bnk"].status == BankStatus.MODIFIED
    assert items["audio_mod.bnk"].modification_kind == BankModificationKind.AUDIO

    # Verify full_mod.bnk
    assert "full_mod.bnk" in items
    assert items["full_mod.bnk"].status == BankStatus.MODIFIED
    assert items["full_mod.bnk"].modification_kind == BankModificationKind.FULL

    # Verify filter_modified_only includes STRUCTURE, AUDIO, and FULL, but excludes VANILLA
    state_filtered, _ = reconcile_viewer(store.state, FilterModifiedOnlyToggled(enabled=True))
    filtered_names = {b.name.lower() for b in state_filtered.filtered_banks}

    assert "vanilla.bnk" not in filtered_names
    assert "struct_mod.bnk" in filtered_names
    assert "audio_mod.bnk" in filtered_names
    assert "full_mod.bnk" in filtered_names
