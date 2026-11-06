"""Pure immutable data ontology for the Blast Radius replacement confirmation feature slice."""

from dataclasses import dataclass
from enum import Enum


class BlastRadiusMode(str, Enum):
    """Dialog presentation mode for audio replacement confirmation."""

    PROMOTION_NOTICE = "promotion_notice"
    SHARED_CONFIRMATION = "shared_confirmation"


class BlastRadiusAction(str, Enum):
    """Modder decision outcome in the blast radius confirmation dialog."""

    OVERWRITE = "overwrite"
    ISOLATE = "isolate"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class BlastRadiusImpactItem:
    """Descriptor for a single referencing HIRC node affected by a shared WEM replacement."""

    bank_name: str
    node_id: int
    node_name: str
    node_type: str
    stream_type: int = 0
    is_embedded: bool = True
    node_key: str = ""


@dataclass(frozen=True, slots=True)
class BlastRadiusState:
    """Immutable single source of truth for the Blast Radius confirmation dialog."""

    mode: BlastRadiusMode = BlastRadiusMode.SHARED_CONFIRMATION
    target_bank_name: str = ""
    target_node_id: int = 0
    wem_id: int = 0
    items: tuple[BlastRadiusImpactItem, ...] = ()
    chosen_action: BlastRadiusAction | None = None


# ==============================================================================
# Events (What Just Happened)
# ==============================================================================


@dataclass(frozen=True, slots=True)
class ChooseActionRequested:
    """User clicked Overwrite, Isolate/Fork, or Cancel in the confirmation dialog."""

    action: BlastRadiusAction


type BlastRadiusEvent = ChooseActionRequested


# ==============================================================================
# Effect Intents (Data As Actions)
# ==============================================================================


@dataclass(frozen=True, slots=True)
class CloseDialogIntent:
    """Request Imperative Shell to close the modal dialog with the chosen action."""

    action: BlastRadiusAction


type BlastRadiusIntent = CloseDialogIntent
