"""Pure deterministic state transitions and decision logic for Project Wizard."""

from dataclasses import replace
from typing import assert_never

from src.ui.features.project_wizard.state import (
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


def reconcile_project_wizard(
    state: ProjectWizardState,
    event: ProjectWizardEvent,
) -> tuple[ProjectWizardState, tuple[ProjectWizardIntent, ...]]:
    """Pure state evolution function mapping (state, event) -> (new_state, intents)."""
    match event:
        case WizardStepTransitionRequested(step=step):
            if step == WizardStep.MOD_PACKS:
                if not state.project_name.strip():
                    return replace(state, status_message="Project name cannot be empty"), ()
                if not state.project_location.strip():
                    return replace(state, status_message="Project location cannot be empty"), ()
                if not state.is_target_dir_available:
                    msg = state.target_dir_validation_msg or "Project folder already exists"
                    return replace(state, status_message=msg), ()

            return replace(state, step=step, status_message=None), ()

        case WizardGameValidationUpdated(
            selected_game=game,
            game_path=path,
            is_game_path_valid=valid,
            game_path_validation_msg=msg,
            is_cache_valid=cache_valid,
        ):
            return replace(
                state,
                selected_game=game,
                game_path=path,
                is_game_path_valid=valid,
                game_path_validation_msg=msg,
                is_cache_valid=cache_valid,
            ), ()

        case WizardProjectNameUpdated(
            project_name=name,
            is_target_dir_available=avail,
            target_dir_validation_msg=msg,
        ):
            return replace(
                state,
                project_name=name,
                is_target_dir_available=avail,
                target_dir_validation_msg=msg,
            ), ()

        case WizardProjectLocationUpdated(
            project_location=loc,
            is_target_dir_available=avail,
            target_dir_validation_msg=msg,
        ):
            return replace(
                state,
                project_location=loc,
                is_target_dir_available=avail,
                target_dir_validation_msg=msg,
            ), ()

        case WizardImportDbTablesToggled(enabled=enabled):
            return replace(state, import_db_tables=enabled), ()

        case WizardModPackAdded(entry=entry):
            return replace(
                state,
                mod_packs=(*state.mod_packs, entry),
                status_message=None,
            ), ()

        case WizardModPackRemoved(index=idx):
            if 0 <= idx < len(state.mod_packs):
                updated = list(state.mod_packs)
                updated.pop(idx)
                return replace(state, mod_packs=tuple(updated)), ()
            return state, ()

        case WizardModPackMoved(index=idx, direction=direction):
            target = idx + direction
            if 0 <= idx < len(state.mod_packs) and 0 <= target < len(state.mod_packs):
                updated = list(state.mod_packs)
                updated[idx], updated[target] = updated[target], updated[idx]
                return replace(state, mod_packs=tuple(updated)), ()
            return state, ()

        case WizardStatusMessageSet(status_message=msg):
            return replace(state, status_message=msg), ()

        case WizardWorkProgressUpdated(
            step=step,
            is_working=is_working,
            progress_percentage=pct,
            progress_text=text,
            status_message=msg,
            is_cache_valid=cache_valid,
            created_project=proj,
        ):
            updates = {
                "step": step,
                "is_working": is_working,
                "progress_percentage": pct,
                "progress_text": text,
                "status_message": msg,
            }
            if cache_valid is not None:
                updates["is_cache_valid"] = cache_valid
            if proj is not None:
                updates["created_project"] = proj
            return replace(state, **updates), ()

        case _ as unreachable:
            assert_never(unreachable)
