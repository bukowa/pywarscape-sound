"""State models for the Pack Health Repair feature slice."""

from dataclasses import dataclass

from src.workspace.health import IssueSeverity


@dataclass(frozen=True, slots=True)
class RepairItemState:
    """Immutable display descriptor for an individual diagnostic defect or repair item."""

    issue_id: str
    file_path: str
    title: str
    description: str
    severity: IssueSeverity
    can_autofix: bool
    fix_description: str = ""
    is_selected: bool = False


@dataclass(frozen=True, slots=True)
class PackRepairState:
    """Single source of truth for the Pack Health Repair dialog."""

    pack_name: str = ""
    items: tuple[RepairItemState, ...] = ()
    can_autofix_any: bool = False
    selected_count: int = 0


# ==============================================================================
# Events & Commands
# ==============================================================================


@dataclass(frozen=True, slots=True)
class ToggleRepairItemRequested:
    """Request to toggle selection of a single repair item."""

    issue_id: str


@dataclass(frozen=True, slots=True)
class SelectAllRepairItemsRequested:
    """Request to select or deselect all fixable repair items."""

    selected: bool


type PackRepairEvent = ToggleRepairItemRequested | SelectAllRepairItemsRequested


# ==============================================================================
# Effect Intents
# ==============================================================================


@dataclass(frozen=True, slots=True)
class NoOpRepairIntent:
    """Empty intent placeholder when no side effects are required."""

    pass


type PackRepairIntent = NoOpRepairIntent
