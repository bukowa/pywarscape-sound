"""Table-driven state transition proofs for Project Wizard causation."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from src.ui.features.project_wizard.causation import reconcile_project_wizard
from src.ui.features.project_wizard.state import (
    ModPackEntry,
    ProjectWizardEvent,
    ProjectWizardIntent,
    ProjectWizardState,
    WizardGameValidationUpdated,
    WizardImportDbTablesToggled,
    WizardModPackAdded,
    WizardModPackMoved,
    WizardModPackRemoved,
    WizardProjectLocationUpdated,
    WizardProjectNameUpdated,
    WizardStatusMessageSet,
    WizardStep,
    WizardStepTransitionRequested,
    WizardWorkProgressUpdated,
)
from src.workspace.game import GameType
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject


@dataclass(frozen=True, slots=True)
class WizardTransitionCase:
    id: str
    initial_state: ProjectWizardState
    event: ProjectWizardEvent
    expected_state: ProjectWizardState
    expected_intents: tuple[ProjectWizardIntent, ...]


DUMMY_MANIFEST = ProjectManifest(
    name="TestMod",
    game=GameType.ATTILA,
)
DUMMY_PROJECT = AudioProject(
    root_dir=Path("projects/TestMod"),
    manifest=DUMMY_MANIFEST,
)

PACK_ALPHA = ModPackEntry(path="C:/mods/alpha.pack", filename="alpha.pack", size_bytes=1000)
PACK_BETA = ModPackEntry(path="C:/mods/beta.pack", filename="beta.pack", size_bytes=2000)
PACK_GAMMA = ModPackEntry(path="C:/mods/gamma.pack", filename="gamma.pack", size_bytes=3000)

BASE_STATE = ProjectWizardState(
    project_name="MyAudioMod",
    project_location="C:/projects",
    is_target_dir_available=True,
)

CASES: tuple[WizardTransitionCase, ...] = (
    WizardTransitionCase(
        id="transition_to_mod_packs_success",
        initial_state=BASE_STATE,
        event=WizardStepTransitionRequested(step=WizardStep.MOD_PACKS),
        expected_state=ProjectWizardState(
            step=WizardStep.MOD_PACKS,
            project_name="MyAudioMod",
            project_location="C:/projects",
            is_target_dir_available=True,
            status_message=None,
        ),
        expected_intents=(),
    ),
    WizardTransitionCase(
        id="transition_to_mod_packs_blocked_empty_name",
        initial_state=ProjectWizardState(
            step=WizardStep.SETUP,
            project_name="   ",
            project_location="C:/projects",
            is_target_dir_available=True,
        ),
        event=WizardStepTransitionRequested(step=WizardStep.MOD_PACKS),
        expected_state=ProjectWizardState(
            step=WizardStep.SETUP,
            project_name="   ",
            project_location="C:/projects",
            is_target_dir_available=True,
            status_message="Project name cannot be empty",
        ),
        expected_intents=(),
    ),
    WizardTransitionCase(
        id="transition_to_mod_packs_blocked_empty_location",
        initial_state=ProjectWizardState(
            step=WizardStep.SETUP,
            project_name="ValidMod",
            project_location="",
            is_target_dir_available=True,
        ),
        event=WizardStepTransitionRequested(step=WizardStep.MOD_PACKS),
        expected_state=ProjectWizardState(
            step=WizardStep.SETUP,
            project_name="ValidMod",
            project_location="",
            is_target_dir_available=True,
            status_message="Project location cannot be empty",
        ),
        expected_intents=(),
    ),
    WizardTransitionCase(
        id="transition_to_mod_packs_blocked_target_dir_unavailable",
        initial_state=ProjectWizardState(
            step=WizardStep.SETUP,
            project_name="ExistingMod",
            project_location="C:/projects",
            is_target_dir_available=False,
            target_dir_validation_msg="Folder already exists",
        ),
        event=WizardStepTransitionRequested(step=WizardStep.MOD_PACKS),
        expected_state=ProjectWizardState(
            step=WizardStep.SETUP,
            project_name="ExistingMod",
            project_location="C:/projects",
            is_target_dir_available=False,
            target_dir_validation_msg="Folder already exists",
            status_message="Folder already exists",
        ),
        expected_intents=(),
    ),
    WizardTransitionCase(
        id="transition_to_setup_from_mod_packs",
        initial_state=ProjectWizardState(
            step=WizardStep.MOD_PACKS,
            project_name="MyAudioMod",
            project_location="C:/projects",
            is_target_dir_available=True,
        ),
        event=WizardStepTransitionRequested(step=WizardStep.SETUP),
        expected_state=ProjectWizardState(
            step=WizardStep.SETUP,
            project_name="MyAudioMod",
            project_location="C:/projects",
            is_target_dir_available=True,
            status_message=None,
        ),
        expected_intents=(),
    ),
    WizardTransitionCase(
        id="game_validation_updated",
        initial_state=BASE_STATE,
        event=WizardGameValidationUpdated(
            selected_game=GameType.ROME_2,
            game_path="C:/Games/Rome2",
            is_game_path_valid=True,
            game_path_validation_msg="Valid install",
            is_cache_valid=True,
        ),
        expected_state=ProjectWizardState(
            selected_game=GameType.ROME_2,
            game_path="C:/Games/Rome2",
            is_game_path_valid=True,
            game_path_validation_msg="Valid install",
            is_cache_valid=True,
            project_name="MyAudioMod",
            project_location="C:/projects",
            is_target_dir_available=True,
        ),
        expected_intents=(),
    ),
    WizardTransitionCase(
        id="project_name_updated",
        initial_state=BASE_STATE,
        event=WizardProjectNameUpdated(
            project_name="NewName",
            is_target_dir_available=False,
            target_dir_validation_msg="Directory in use",
        ),
        expected_state=ProjectWizardState(
            project_name="NewName",
            project_location="C:/projects",
            is_target_dir_available=False,
            target_dir_validation_msg="Directory in use",
        ),
        expected_intents=(),
    ),
    WizardTransitionCase(
        id="project_location_updated",
        initial_state=BASE_STATE,
        event=WizardProjectLocationUpdated(
            project_location="D:/NewWorkspace",
            is_target_dir_available=True,
            target_dir_validation_msg="",
        ),
        expected_state=ProjectWizardState(
            project_name="MyAudioMod",
            project_location="D:/NewWorkspace",
            is_target_dir_available=True,
            target_dir_validation_msg="",
        ),
        expected_intents=(),
    ),
    WizardTransitionCase(
        id="import_db_tables_toggled",
        initial_state=BASE_STATE,
        event=WizardImportDbTablesToggled(enabled=False),
        expected_state=ProjectWizardState(
            project_name="MyAudioMod",
            project_location="C:/projects",
            is_target_dir_available=True,
            import_db_tables=False,
        ),
        expected_intents=(),
    ),
    WizardTransitionCase(
        id="mod_pack_added",
        initial_state=ProjectWizardState(mod_packs=(PACK_ALPHA,)),
        event=WizardModPackAdded(entry=PACK_BETA),
        expected_state=ProjectWizardState(
            mod_packs=(PACK_ALPHA, PACK_BETA),
            status_message=None,
        ),
        expected_intents=(),
    ),
    WizardTransitionCase(
        id="mod_pack_removed_valid_index",
        initial_state=ProjectWizardState(mod_packs=(PACK_ALPHA, PACK_BETA, PACK_GAMMA)),
        event=WizardModPackRemoved(index=1),
        expected_state=ProjectWizardState(mod_packs=(PACK_ALPHA, PACK_GAMMA)),
        expected_intents=(),
    ),
    WizardTransitionCase(
        id="mod_pack_removed_invalid_index_no_op",
        initial_state=ProjectWizardState(mod_packs=(PACK_ALPHA, PACK_BETA)),
        event=WizardModPackRemoved(index=5),
        expected_state=ProjectWizardState(mod_packs=(PACK_ALPHA, PACK_BETA)),
        expected_intents=(),
    ),
    WizardTransitionCase(
        id="mod_pack_moved_up",
        initial_state=ProjectWizardState(mod_packs=(PACK_ALPHA, PACK_BETA, PACK_GAMMA)),
        event=WizardModPackMoved(index=1, direction=-1),
        expected_state=ProjectWizardState(mod_packs=(PACK_BETA, PACK_ALPHA, PACK_GAMMA)),
        expected_intents=(),
    ),
    WizardTransitionCase(
        id="mod_pack_moved_down",
        initial_state=ProjectWizardState(mod_packs=(PACK_ALPHA, PACK_BETA, PACK_GAMMA)),
        event=WizardModPackMoved(index=0, direction=1),
        expected_state=ProjectWizardState(mod_packs=(PACK_BETA, PACK_ALPHA, PACK_GAMMA)),
        expected_intents=(),
    ),
    WizardTransitionCase(
        id="mod_pack_moved_out_of_bounds_no_op",
        initial_state=ProjectWizardState(mod_packs=(PACK_ALPHA, PACK_BETA)),
        event=WizardModPackMoved(index=0, direction=-1),
        expected_state=ProjectWizardState(mod_packs=(PACK_ALPHA, PACK_BETA)),
        expected_intents=(),
    ),
    WizardTransitionCase(
        id="status_message_set",
        initial_state=BASE_STATE,
        event=WizardStatusMessageSet(status_message="Custom error"),
        expected_state=ProjectWizardState(
            project_name="MyAudioMod",
            project_location="C:/projects",
            is_target_dir_available=True,
            status_message="Custom error",
        ),
        expected_intents=(),
    ),
    WizardTransitionCase(
        id="work_progress_updated_running",
        initial_state=ProjectWizardState(step=WizardStep.MOD_PACKS),
        event=WizardWorkProgressUpdated(
            step=WizardStep.PROGRESS,
            is_working=True,
            progress_percentage=0.5,
            progress_text="Importing alpha.pack...",
        ),
        expected_state=ProjectWizardState(
            step=WizardStep.PROGRESS,
            is_working=True,
            progress_percentage=0.5,
            progress_text="Importing alpha.pack...",
            status_message=None,
        ),
        expected_intents=(),
    ),
    WizardTransitionCase(
        id="work_progress_updated_finished",
        initial_state=ProjectWizardState(
            step=WizardStep.PROGRESS,
            is_working=True,
            progress_percentage=0.5,
            progress_text="Importing alpha.pack...",
        ),
        event=WizardWorkProgressUpdated(
            step=WizardStep.PROGRESS,
            is_working=False,
            progress_percentage=1.0,
            progress_text="Project created successfully",
            created_project=DUMMY_PROJECT,
            status_message=None,
        ),
        expected_state=ProjectWizardState(
            step=WizardStep.PROGRESS,
            is_working=False,
            progress_percentage=1.0,
            progress_text="Project created successfully",
            created_project=DUMMY_PROJECT,
            status_message=None,
        ),
        expected_intents=(),
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_reconcile_project_wizard_transitions(case: WizardTransitionCase) -> None:
    new_state, intents = reconcile_project_wizard(case.initial_state, case.event)
    assert new_state == case.expected_state
    assert intents == case.expected_intents
