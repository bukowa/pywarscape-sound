"""Pure deterministic state transitions and decision logic for Project Hub."""

from dataclasses import replace
from typing import assert_never

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
    SelectedGameChanged,
)


def reconcile_project_hub(
    state: ProjectHubState,
    event: ProjectHubEvent,
) -> tuple[ProjectHubState, tuple[ProjectHubIntent, ...]]:
    """Pure state evolution function mapping (state, event) -> (new_state, intents)."""
    match event:
        case NewProjectNameSet(name=name):
            return replace(state, new_project_name=name), ()

        case NewProjectLocationSet(location=loc):
            return replace(state, new_project_location=loc), ()

        case SelectedGameChanged(game=game):
            return replace(state, selected_game=game), ()

        case GamePathEvaluated(
            game_path=path,
            is_game_path_valid=valid,
            game_path_validation_msg=val_msg,
            is_cache_valid=cache_valid,
            cache_status_msg=cache_msg,
        ):
            return replace(
                state,
                game_path=path,
                is_game_path_valid=valid,
                game_path_validation_msg=val_msg,
                is_cache_valid=cache_valid,
                cache_status_msg=cache_msg,
            ), ()

        case CacheBuildStarted():
            return replace(
                state,
                is_building_cache=True,
                cache_progress_text="Building game cache...",
                cache_progress_percentage=0.0,
            ), ()

        case CacheBuildProgressUpdated(
            progress_text=text,
            progress_percentage=pct,
        ):
            return replace(
                state,
                cache_progress_text=text,
                cache_progress_percentage=pct,
            ), ()

        case CacheBuildFinished(
            is_cache_valid=cache_valid,
            cache_status_msg=status_msg,
            error_message=err_msg,
        ):
            if err_msg is not None:
                return replace(
                    state,
                    is_building_cache=False,
                    status_message=err_msg,
                ), ()
            return replace(
                state,
                is_cache_valid=cache_valid,
                cache_status_msg=status_msg,
                is_building_cache=False,
                cache_progress_text="Cache built successfully"
                if cache_valid
                else "Failed to build cache",
                cache_progress_percentage=1.0 if cache_valid else 0.0,
            ), ()

        case ProjectOpenedSuccessfully(
            recent_projects=recent,
            loaded_project_path=path,
        ):
            return replace(
                state,
                recent_projects=recent,
                loaded_project_path=path,
                status_message=None,
            ), ()

        case ProjectActionFailed(status_message=msg):
            return replace(
                state,
                status_message=msg,
                loaded_project_path=None,
            ), ()

        case _ as unreachable:
            assert_never(unreachable)
