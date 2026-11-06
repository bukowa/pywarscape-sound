"""Pure deterministic state transitions and decision logic for Pack Health Repair."""

from dataclasses import replace
from typing import assert_never

from src.ui.features.pack_repair.state import (
    PackRepairEvent,
    PackRepairIntent,
    PackRepairState,
    RepairItemState,
    SelectAllRepairItemsRequested,
    ToggleRepairItemRequested,
)


def reconcile_pack_repair(
    state: PackRepairState,
    event: PackRepairEvent,
) -> tuple[PackRepairState, tuple[PackRepairIntent, ...]]:
    """Pure state evolution function mapping (state, event) -> (new_state, intents)."""
    match event:
        case ToggleRepairItemRequested(issue_id=issue_id):
            new_items: list[RepairItemState] = []
            changed = False
            for item in state.items:
                if item.issue_id == issue_id and item.can_autofix:
                    new_items.append(replace(item, is_selected=not item.is_selected))
                    changed = True
                else:
                    new_items.append(item)

            if not changed:
                return state, ()

            items_tuple = tuple(new_items)
            selected_count = sum(1 for item in items_tuple if item.is_selected)
            return replace(state, items=items_tuple, selected_count=selected_count), ()

        case SelectAllRepairItemsRequested(selected=selected):
            new_items: list[RepairItemState] = []
            changed = False
            for item in state.items:
                target_selected = selected if item.can_autofix else False
                if item.is_selected != target_selected:
                    new_items.append(replace(item, is_selected=target_selected))
                    changed = True
                else:
                    new_items.append(item)

            if not changed:
                return state, ()

            items_tuple = tuple(new_items)
            selected_count = sum(1 for item in items_tuple if item.is_selected)
            return replace(state, items=items_tuple, selected_count=selected_count), ()

        case _ as unreachable:
            assert_never(unreachable)
