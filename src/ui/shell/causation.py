"""Pure deterministic state transitions and decision logic for the Application Shell."""

from dataclasses import replace
from typing import assert_never

from src.ui.shell.state import (
    ProjectClosed,
    ProjectOpened,
    ScreenMode,
    ShellEvent,
    ShellIntent,
    ShellState,
    StatusMessageSet,
)


def reconcile_shell(
    state: ShellState,
    event: ShellEvent,
) -> tuple[ShellState, tuple[ShellIntent, ...]]:
    """Pure state transition decision engine for the Application Shell."""
    match event:
        case ProjectOpened(project=proj):
            game_val = (
                proj.manifest.game.value
                if hasattr(proj.manifest.game, "value")
                else str(proj.manifest.game)
            )
            title = f"PyWarscape Sound - {proj.manifest.name} ({game_val})"
            new_state = replace(
                state,
                screen_mode=ScreenMode.WORKSPACE,
                active_project=proj,
                window_title=title,
                status_message=f"Project '{proj.manifest.name}' opened",
            )
            return new_state, ()

        case ProjectClosed():
            new_state = replace(
                state,
                screen_mode=ScreenMode.LAUNCHER,
                active_project=None,
                window_title="PyWarscape Sound",
                status_message=None,
            )
            return new_state, ()

        case StatusMessageSet(message=msg):
            return replace(state, status_message=msg), ()

        case _ as unreachable:
            assert_never(unreachable)
