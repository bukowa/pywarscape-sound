"""Headless state store for the Pack Health Repair feature slice."""

from collections.abc import Callable
from dataclasses import replace

from src.ui.features.pack_repair.causation import reconcile_pack_repair
from src.ui.features.pack_repair.state import (
    PackRepairEvent,
    PackRepairState,
    RepairItemState,
    SelectAllRepairItemsRequested,
    ToggleRepairItemRequested,
)
from src.workspace.health import PackHealthReport


class PackRepairStore:
    """Headless observable store managing pack health diagnostic state and repair selections."""

    def __init__(self, report: PackHealthReport) -> None:
        self._subscribers: list[Callable[[PackRepairState], None]] = []

        items: list[RepairItemState] = []
        for issue in report.issues:
            items.append(
                RepairItemState(
                    issue_id=issue.issue_id,
                    file_path=issue.file_path,
                    title=issue.title,
                    description=issue.description,
                    severity=issue.severity,
                    can_autofix=issue.can_autofix,
                    fix_description=issue.fix_description or "",
                    is_selected=issue.can_autofix,
                )
            )

        items_tuple = tuple(items)
        can_autofix_any = any(item.can_autofix for item in items_tuple)
        selected_count = sum(1 for item in items_tuple if item.is_selected)

        self._state = PackRepairState(
            pack_name=report.pack_name,
            items=items_tuple,
            can_autofix_any=can_autofix_any,
            selected_count=selected_count,
        )

    @property
    def state(self) -> PackRepairState:
        """Current immutable snapshot of the pack repair state."""
        return self._state

    def subscribe(self, callback: Callable[[PackRepairState], None]) -> None:
        """Register a state listener invoked whenever state changes."""
        self._subscribers.append(callback)

    def _dispatch(self, event: PackRepairEvent) -> None:
        """Pure state evolution and subscriber notification."""
        new_state, _intents = reconcile_pack_repair(self._state, event)
        if new_state != self._state:
            self._state = new_state
            for callback in list(self._subscribers):
                callback(self._state)

    def toggle_item(self, issue_id: str) -> None:
        """Toggle the selection state of a repair item if it can be autofixed."""
        self._dispatch(ToggleRepairItemRequested(issue_id=issue_id))

    def select_all(self, selected: bool) -> None:
        """Select or deselect all fixable repair items."""
        self._dispatch(SelectAllRepairItemsRequested(selected=selected))

    def get_selected_issue_ids(self) -> set[str]:
        """Return the set of issue IDs currently selected for auto-fix."""
        return {item.issue_id for item in self._state.items if item.is_selected}

    def _update_state(self, **kwargs) -> None:
        """Replace state with updated fields and notify all registered subscribers."""
        self._state = replace(self._state, **kwargs)
        for callback in list(self._subscribers):
            callback(self._state)
