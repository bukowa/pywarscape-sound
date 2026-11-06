"""Pure deterministic state transitions and decision logic for Blast Radius confirmation."""

from dataclasses import replace
from typing import assert_never

from src.ui.features.blast_radius.state import (
    BlastRadiusEvent,
    BlastRadiusIntent,
    BlastRadiusState,
    ChooseActionRequested,
    CloseDialogIntent,
)


def reconcile_blast_radius(
    state: BlastRadiusState,
    event: BlastRadiusEvent,
) -> tuple[BlastRadiusState, tuple[BlastRadiusIntent, ...]]:
    """Pure state transition decision core for the Blast Radius dialog."""
    match event:
        case ChooseActionRequested(action=action):
            new_state = replace(state, chosen_action=action)
            return new_state, (CloseDialogIntent(action=action),)

        case _ as unreachable:
            assert_never(unreachable)
