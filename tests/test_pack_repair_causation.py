"""Table-driven state transition proofs for Pack Health Repair causation."""

from dataclasses import dataclass

import pytest

from src.ui.features.pack_repair.causation import reconcile_pack_repair
from src.ui.features.pack_repair.state import (
    PackRepairEvent,
    PackRepairIntent,
    PackRepairState,
    RepairItemState,
    SelectAllRepairItemsRequested,
    ToggleRepairItemRequested,
)
from src.workspace.health import IssueSeverity


@dataclass(frozen=True, slots=True)
class RepairTransitionCase:
    id: str
    initial_state: PackRepairState
    event: PackRepairEvent
    expected_state: PackRepairState
    expected_intents: tuple[PackRepairIntent, ...]


ITEM_FIXABLE_SELECTED = RepairItemState(
    issue_id="fixable_1",
    file_path="audio/global.bnk",
    title="Fixable Issue 1",
    description="Description 1",
    severity=IssueSeverity.CRITICAL_CRASH,
    can_autofix=True,
    fix_description="Fix 1",
    is_selected=True,
)

ITEM_FIXABLE_UNSELECTED = RepairItemState(
    issue_id="fixable_2",
    file_path="audio/music.bnk",
    title="Fixable Issue 2",
    description="Description 2",
    severity=IssueSeverity.WARNING,
    can_autofix=True,
    fix_description="Fix 2",
    is_selected=False,
)

ITEM_NON_FIXABLE = RepairItemState(
    issue_id="unfixable_1",
    file_path="audio/events.dat",
    title="Unfixable Issue",
    description="Manual fix required",
    severity=IssueSeverity.WARNING,
    can_autofix=False,
    fix_description="",
    is_selected=False,
)

BASE_STATE = PackRepairState(
    pack_name="test.pack",
    items=(ITEM_FIXABLE_SELECTED, ITEM_FIXABLE_UNSELECTED, ITEM_NON_FIXABLE),
    can_autofix_any=True,
    selected_count=1,
)

CASES: tuple[RepairTransitionCase, ...] = (
    RepairTransitionCase(
        id="toggle_fixable_selected_to_unselected",
        initial_state=BASE_STATE,
        event=ToggleRepairItemRequested(issue_id="fixable_1"),
        expected_state=PackRepairState(
            pack_name="test.pack",
            items=(
                RepairItemState(
                    issue_id="fixable_1",
                    file_path="audio/global.bnk",
                    title="Fixable Issue 1",
                    description="Description 1",
                    severity=IssueSeverity.CRITICAL_CRASH,
                    can_autofix=True,
                    fix_description="Fix 1",
                    is_selected=False,
                ),
                ITEM_FIXABLE_UNSELECTED,
                ITEM_NON_FIXABLE,
            ),
            can_autofix_any=True,
            selected_count=0,
        ),
        expected_intents=(),
    ),
    RepairTransitionCase(
        id="toggle_fixable_unselected_to_selected",
        initial_state=BASE_STATE,
        event=ToggleRepairItemRequested(issue_id="fixable_2"),
        expected_state=PackRepairState(
            pack_name="test.pack",
            items=(
                ITEM_FIXABLE_SELECTED,
                RepairItemState(
                    issue_id="fixable_2",
                    file_path="audio/music.bnk",
                    title="Fixable Issue 2",
                    description="Description 2",
                    severity=IssueSeverity.WARNING,
                    can_autofix=True,
                    fix_description="Fix 2",
                    is_selected=True,
                ),
                ITEM_NON_FIXABLE,
            ),
            can_autofix_any=True,
            selected_count=2,
        ),
        expected_intents=(),
    ),
    RepairTransitionCase(
        id="toggle_non_fixable_item_no_op",
        initial_state=BASE_STATE,
        event=ToggleRepairItemRequested(issue_id="unfixable_1"),
        expected_state=BASE_STATE,
        expected_intents=(),
    ),
    RepairTransitionCase(
        id="toggle_unknown_issue_id_no_op",
        initial_state=BASE_STATE,
        event=ToggleRepairItemRequested(issue_id="unknown_id"),
        expected_state=BASE_STATE,
        expected_intents=(),
    ),
    RepairTransitionCase(
        id="select_all_true_selects_only_fixable_items",
        initial_state=BASE_STATE,
        event=SelectAllRepairItemsRequested(selected=True),
        expected_state=PackRepairState(
            pack_name="test.pack",
            items=(
                ITEM_FIXABLE_SELECTED,
                RepairItemState(
                    issue_id="fixable_2",
                    file_path="audio/music.bnk",
                    title="Fixable Issue 2",
                    description="Description 2",
                    severity=IssueSeverity.WARNING,
                    can_autofix=True,
                    fix_description="Fix 2",
                    is_selected=True,
                ),
                ITEM_NON_FIXABLE,
            ),
            can_autofix_any=True,
            selected_count=2,
        ),
        expected_intents=(),
    ),
    RepairTransitionCase(
        id="select_all_false_deselects_all_items",
        initial_state=BASE_STATE,
        event=SelectAllRepairItemsRequested(selected=False),
        expected_state=PackRepairState(
            pack_name="test.pack",
            items=(
                RepairItemState(
                    issue_id="fixable_1",
                    file_path="audio/global.bnk",
                    title="Fixable Issue 1",
                    description="Description 1",
                    severity=IssueSeverity.CRITICAL_CRASH,
                    can_autofix=True,
                    fix_description="Fix 1",
                    is_selected=False,
                ),
                ITEM_FIXABLE_UNSELECTED,
                ITEM_NON_FIXABLE,
            ),
            can_autofix_any=True,
            selected_count=0,
        ),
        expected_intents=(),
    ),
    RepairTransitionCase(
        id="select_all_no_op_when_already_matching",
        initial_state=PackRepairState(
            pack_name="test.pack",
            items=(
                RepairItemState(
                    issue_id="fixable_1",
                    file_path="audio/global.bnk",
                    title="Fixable Issue 1",
                    description="Description 1",
                    severity=IssueSeverity.CRITICAL_CRASH,
                    can_autofix=True,
                    fix_description="Fix 1",
                    is_selected=False,
                ),
                ITEM_FIXABLE_UNSELECTED,
                ITEM_NON_FIXABLE,
            ),
            can_autofix_any=True,
            selected_count=0,
        ),
        event=SelectAllRepairItemsRequested(selected=False),
        expected_state=PackRepairState(
            pack_name="test.pack",
            items=(
                RepairItemState(
                    issue_id="fixable_1",
                    file_path="audio/global.bnk",
                    title="Fixable Issue 1",
                    description="Description 1",
                    severity=IssueSeverity.CRITICAL_CRASH,
                    can_autofix=True,
                    fix_description="Fix 1",
                    is_selected=False,
                ),
                ITEM_FIXABLE_UNSELECTED,
                ITEM_NON_FIXABLE,
            ),
            can_autofix_any=True,
            selected_count=0,
        ),
        expected_intents=(),
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_reconcile_pack_repair_transitions(case: RepairTransitionCase) -> None:
    new_state, intents = reconcile_pack_repair(case.initial_state, case.event)
    assert new_state == case.expected_state
    assert intents == case.expected_intents
