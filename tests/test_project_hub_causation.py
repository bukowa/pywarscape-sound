"""Table-driven state transition proofs for Project Hub causation."""

from dataclasses import dataclass

import pytest

from src.ui.features.project_hub.causation import reconcile_project_hub
from src.ui.features.project_hub.state import (
    CacheBuildFinished,
    CacheBuildProgressUpdated,
    CacheBuildStarted,
    GamePathEvaluated,
    NewProjectLocationSet,
    NewProjectNameSet,
    ProjectActionFailed,
    ProjectHubEvent,
    ProjectHubIntent,
    ProjectHubState,
    ProjectOpenedSuccessfully,
    RecentProjectItem,
    SelectedGameChanged,
)
from src.workspace.game import GameType


@dataclass(frozen=True, slots=True)
class HubTransitionCase:
    id: str
    initial_state: ProjectHubState
    event: ProjectHubEvent
    expected_state: ProjectHubState
    expected_intents: tuple[ProjectHubIntent, ...]


RECENT_ITEM = RecentProjectItem(
    name="RecentMod",
    path="C:/projects/RecentMod",
    game="attila",
    last_opened="2026-11-01T10:00:00Z",
)

BASE_STATE = ProjectHubState()

CASES: tuple[HubTransitionCase, ...] = (
    HubTransitionCase(
        id="set_new_project_name",
        initial_state=BASE_STATE,
        event=NewProjectNameSet(name="SuperMod"),
        expected_state=ProjectHubState(new_project_name="SuperMod"),
        expected_intents=(),
    ),
    HubTransitionCase(
        id="set_new_project_location",
        initial_state=BASE_STATE,
        event=NewProjectLocationSet(location="D:/mods"),
        expected_state=ProjectHubState(new_project_location="D:/mods"),
        expected_intents=(),
    ),
    HubTransitionCase(
        id="select_game_changed",
        initial_state=BASE_STATE,
        event=SelectedGameChanged(game=GameType.ROME_2),
        expected_state=ProjectHubState(selected_game=GameType.ROME_2),
        expected_intents=(),
    ),
    HubTransitionCase(
        id="game_path_evaluated_valid",
        initial_state=BASE_STATE,
        event=GamePathEvaluated(
            game_path="C:/Games/Attila",
            is_game_path_valid=True,
            game_path_validation_msg="Installation verified",
            is_cache_valid=True,
            cache_status_msg="Cache Ready",
        ),
        expected_state=ProjectHubState(
            game_path="C:/Games/Attila",
            is_game_path_valid=True,
            game_path_validation_msg="Installation verified",
            is_cache_valid=True,
            cache_status_msg="Cache Ready",
        ),
        expected_intents=(),
    ),
    HubTransitionCase(
        id="game_path_evaluated_invalid",
        initial_state=BASE_STATE,
        event=GamePathEvaluated(
            game_path="C:/Invalid/Path",
            is_game_path_valid=False,
            game_path_validation_msg="Executable not found",
            is_cache_valid=False,
            cache_status_msg="Game Cache: Not Built",
        ),
        expected_state=ProjectHubState(
            game_path="C:/Invalid/Path",
            is_game_path_valid=False,
            game_path_validation_msg="Executable not found",
            is_cache_valid=False,
            cache_status_msg="Game Cache: Not Built",
        ),
        expected_intents=(),
    ),
    HubTransitionCase(
        id="cache_build_started",
        initial_state=BASE_STATE,
        event=CacheBuildStarted(),
        expected_state=ProjectHubState(
            is_building_cache=True,
            cache_progress_text="Building game cache...",
            cache_progress_percentage=0.0,
        ),
        expected_intents=(),
    ),
    HubTransitionCase(
        id="cache_build_progress_updated",
        initial_state=ProjectHubState(
            is_building_cache=True,
            cache_progress_text="Building game cache...",
            cache_progress_percentage=0.0,
        ),
        event=CacheBuildProgressUpdated(
            progress_text="Extracting soundbanks...",
            progress_percentage=0.65,
        ),
        expected_state=ProjectHubState(
            is_building_cache=True,
            cache_progress_text="Extracting soundbanks...",
            cache_progress_percentage=0.65,
        ),
        expected_intents=(),
    ),
    HubTransitionCase(
        id="cache_build_finished_success",
        initial_state=ProjectHubState(
            is_building_cache=True,
            cache_progress_text="Extracting soundbanks...",
            cache_progress_percentage=0.65,
        ),
        event=CacheBuildFinished(
            is_cache_valid=True,
            cache_status_msg="Cache Ready (127 SoundBanks)",
        ),
        expected_state=ProjectHubState(
            is_building_cache=False,
            is_cache_valid=True,
            cache_status_msg="Cache Ready (127 SoundBanks)",
            cache_progress_text="Cache built successfully",
            cache_progress_percentage=1.0,
        ),
        expected_intents=(),
    ),
    HubTransitionCase(
        id="cache_build_finished_failure_status",
        initial_state=ProjectHubState(
            is_building_cache=True,
            cache_progress_text="Extracting soundbanks...",
            cache_progress_percentage=0.65,
        ),
        event=CacheBuildFinished(
            is_cache_valid=False,
            cache_status_msg="Game Cache: Not Built",
        ),
        expected_state=ProjectHubState(
            is_building_cache=False,
            is_cache_valid=False,
            cache_status_msg="Game Cache: Not Built",
            cache_progress_text="Failed to build cache",
            cache_progress_percentage=0.0,
        ),
        expected_intents=(),
    ),
    HubTransitionCase(
        id="cache_build_finished_with_error_message",
        initial_state=ProjectHubState(
            is_building_cache=True,
            cache_progress_text="Extracting soundbanks...",
            cache_progress_percentage=0.65,
        ),
        event=CacheBuildFinished(
            is_cache_valid=False,
            cache_status_msg="",
            error_message="Extraction aborted: disk full",
        ),
        expected_state=ProjectHubState(
            is_building_cache=False,
            status_message="Extraction aborted: disk full",
            cache_progress_text="Extracting soundbanks...",
            cache_progress_percentage=0.65,
        ),
        expected_intents=(),
    ),
    HubTransitionCase(
        id="project_opened_successfully",
        initial_state=ProjectHubState(
            status_message="Previous error",
            loaded_project_path=None,
        ),
        event=ProjectOpenedSuccessfully(
            recent_projects=(RECENT_ITEM,),
            loaded_project_path="C:/projects/RecentMod",
        ),
        expected_state=ProjectHubState(
            recent_projects=(RECENT_ITEM,),
            loaded_project_path="C:/projects/RecentMod",
            status_message=None,
        ),
        expected_intents=(),
    ),
    HubTransitionCase(
        id="project_action_failed",
        initial_state=ProjectHubState(
            loaded_project_path="C:/projects/OldMod",
        ),
        event=ProjectActionFailed(status_message="Cannot open project: corrupted manifest"),
        expected_state=ProjectHubState(
            loaded_project_path=None,
            status_message="Cannot open project: corrupted manifest",
        ),
        expected_intents=(),
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_reconcile_project_hub_transitions(case: HubTransitionCase) -> None:
    new_state, intents = reconcile_project_hub(case.initial_state, case.event)
    assert new_state == case.expected_state
    assert intents == case.expected_intents
