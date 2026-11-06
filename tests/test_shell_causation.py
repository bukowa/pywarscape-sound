"""Table-driven state transition proofs for v3 Application Shell causation."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from src.ui.shell.causation import reconcile_shell
from src.ui.shell.state import (
    ProjectClosed,
    ProjectOpened,
    ScreenMode,
    ShellEvent,
    ShellIntent,
    ShellState,
    StatusMessageSet,
)
from src.workspace.game import GameType
from src.workspace.manifest import ProjectManifest
from src.workspace.project import AudioProject


@dataclass(frozen=True, slots=True)
class ShellTransitionCase:
    id: str
    initial_state: ShellState
    event: ShellEvent
    expected_state: ShellState
    expected_intents: tuple[ShellIntent, ...]


DUMMY_MANIFEST = ProjectManifest(
    name="TestMod",
    game=GameType.ATTILA,
)
DUMMY_PROJECT = AudioProject(
    root_dir=Path("projects/TestMod"),
    manifest=DUMMY_MANIFEST,
)

CASES: tuple[ShellTransitionCase, ...] = (
    ShellTransitionCase(
        id="open_project_switches_to_workspace",
        initial_state=ShellState(),
        event=ProjectOpened(project=DUMMY_PROJECT),
        expected_state=ShellState(
            screen_mode=ScreenMode.WORKSPACE,
            active_project=DUMMY_PROJECT,
            window_title="PyWarscape Sound - TestMod (attila)",
            status_message="Project 'TestMod' opened",
        ),
        expected_intents=(),
    ),
    ShellTransitionCase(
        id="close_project_returns_to_launcher",
        initial_state=ShellState(
            screen_mode=ScreenMode.WORKSPACE,
            active_project=DUMMY_PROJECT,
            window_title="PyWarscape Sound - TestMod (attila)",
            status_message="Project 'TestMod' opened",
        ),
        event=ProjectClosed(),
        expected_state=ShellState(
            screen_mode=ScreenMode.LAUNCHER,
            active_project=None,
            window_title="PyWarscape Sound",
            status_message=None,
        ),
        expected_intents=(),
    ),
    ShellTransitionCase(
        id="set_status_message",
        initial_state=ShellState(),
        event=StatusMessageSet(message="Ready"),
        expected_state=ShellState(
            status_message="Ready",
        ),
        expected_intents=(),
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_reconcile_shell_transitions(case: ShellTransitionCase) -> None:
    new_state, intents = reconcile_shell(case.initial_state, case.event)
    assert new_state == case.expected_state
    assert intents == case.expected_intents
