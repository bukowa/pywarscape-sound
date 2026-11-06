"""Pure immutable data ontology for the SoundBank Viewer feature slice."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from src.engine.metadata_fields import EMPTY_NODE_METADATA, NodeMetadata, Provenance
from src.ui.features.bank_viewer.columns import DEFAULT_VISIBLE_COLUMNS, TreeColumn
from src.ui.features.bank_viewer.overlays import DEFAULT_ACTIVE_OVERLAYS, TreeOverlay

_EMPTY_MAP: Mapping = MappingProxyType({})


# ==============================================================================
# Domain Vocabulary & Types
# ==============================================================================


class BankStatus(str, Enum):
    """Source origin status for SoundBanks."""

    VANILLA = "Vanilla"
    MODIFIED = "Modified"
    DEPENDENCY = "Dependency"
    EXTERNAL = "External"


class BankModificationKind(str, Enum):
    """Granular classification of how a bank is modified in the project."""

    NONE = "None"
    STRUCTURE = "Structure"
    AUDIO = "Audio"
    FULL = "Full"


class InspectorViewType(str, Enum):
    """View category identifying the dedicated inspector layout to render."""

    DEFAULT = "default"
    SOUND = "sound"
    MEDIA = "media"
    CONTAINER = "container"
    EVENT_ACTION = "event_action"
    MUSIC = "music"


# ==============================================================================
# Entity & Observation Structs
# ==============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class HistoryLocation:
    """Immutable location snapshot in SoundBank viewing history."""

    bank_name: str | None = None
    node_key: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class NodeReferenceSummary:
    """Concise metadata descriptor for an interactive reference link."""

    key: str
    label: str
    id_str: str
    type_str: str
    bank_name: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class BankListItem:
    """Immutable metadata descriptor for a selectable SoundBank."""

    name: str
    status: BankStatus
    size_bytes: int
    path: str
    modification_kind: BankModificationKind = BankModificationKind.NONE

    @property
    def display_size(self) -> str:
        """Formatted human-readable file size."""
        if self.size_bytes >= 1024 * 1024:
            return f"{self.size_bytes / (1024 * 1024):.1f} MB"
        if self.size_bytes >= 1024:
            return f"{self.size_bytes / 1024:.1f} KB"
        return f"{self.size_bytes} B"


@dataclass(frozen=True, slots=True, kw_only=True)
class InspectorProperty:
    """Key-value property entry grouped for display in the property inspector."""

    category: str
    label: str
    value: str


@dataclass(frozen=True, slots=True, kw_only=True)
class SwitchRouteEntry:
    """A single state-to-target route entry in a Switch Container."""

    switch_id: int
    switch_name: str
    target_key: str
    target_id: int
    target_name: str
    target_type: str
    is_default: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class SwitchContainerSemantics:
    """Rich semantic descriptors for CAkSwitchCntr."""

    group_id: int
    group_name: str
    group_type: int
    default_switch_id: int
    default_switch_name: str
    routes: tuple[SwitchRouteEntry, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class PlaylistItemEntry:
    """A single playlist entry in a Random/Sequence Container."""

    index: int
    play_id: int
    target_key: str
    target_name: str
    target_type: str
    weight: int
    weight_percent: float


@dataclass(frozen=True, slots=True, kw_only=True)
class RanSeqContainerSemantics:
    """Rich semantic descriptors for CAkRanSeqCntr."""

    mode_str: str
    loop_count: int
    transition_time_ms: float
    avoid_repeat_count: int
    playlist: tuple[PlaylistItemEntry, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class GameEntityEntry:
    """Single game entity row for the inspector's Game Entities section."""

    key: str
    category: str = ""
    unit_class: str = ""
    extra: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class GameEntitiesSection:
    """Collapsible game metadata section for the inspector panel."""

    entity_type: str  # "units", "projectiles", "explosions", "materials"
    entries: tuple[GameEntityEntry, ...] = ()
    total_count: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class NodeInspectorDetails:
    """Detailed metadata for the currently inspected chunk or HIRC node."""

    node_key: str
    name: str
    object_type: str
    view_type: InspectorViewType = InspectorViewType.DEFAULT
    object_id: int | None = None
    hex_id: str | None = None
    properties: tuple[InspectorProperty, ...] = ()
    parent_keys: tuple[str, ...] = ()
    child_keys: tuple[str, ...] = ()
    parent_references: tuple[NodeReferenceSummary, ...] = ()
    child_references: tuple[NodeReferenceSummary, ...] = ()
    audio_references: tuple[NodeReferenceSummary, ...] = ()
    audio_reference_count: int = 0
    is_streamed: bool = True
    source_wem_id: int | None = None
    switch_semantics: SwitchContainerSemantics | None = None
    ran_seq_semantics: RanSeqContainerSemantics | None = None
    game_entities: GameEntitiesSection | None = None
    source_origin: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class HircTreeNode:
    """A projected node in the SoundBank hierarchy/chunk tree."""

    key: str
    label: str
    id_str: str
    type_str: str
    details: str
    child_keys: tuple[str, ...] = ()
    is_modified: bool = False
    has_modified_children: bool = False
    friendly_label: str | None = None
    friendly_details: str | None = None
    metadata: NodeMetadata = EMPTY_NODE_METADATA
    friendly_details_provenance: Provenance = Provenance.DATABASE


@dataclass(frozen=True, slots=True, kw_only=True)
class BankTreeData:
    """Immutable cached tree projection for a parsed SoundBank."""

    bank_name: str
    root_keys: tuple[str, ...] = ()
    nodes_by_key: Mapping[str, HircTreeNode] = _EMPTY_MAP
    wem_metadata_loaded: bool = False


# ==============================================================================
# State Struct (Single Source of Truth)
# ==============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class BankViewerState:
    """Single source of truth for the SoundBank Viewer."""

    available_banks: tuple[BankListItem, ...] = ()
    selected_bank_name: str | None = None
    bank_search_query: str = ""
    filter_modified_only: bool = False

    # In-memory session cache of previously parsed bank tree skeletons
    cached_banks: Mapping[str, BankTreeData] = _EMPTY_MAP

    # Active bank tree projection
    tree_search_query: str = ""
    filter_tree_modified_only: bool = False
    active_overlays: frozenset[TreeOverlay] = DEFAULT_ACTIVE_OVERLAYS
    visible_columns: tuple[TreeColumn, ...] = DEFAULT_VISIBLE_COLUMNS
    root_keys: tuple[str, ...] = ()
    nodes_by_key: Mapping[str, HircTreeNode] = _EMPTY_MAP
    wem_metadata_loaded: bool = False

    # Lazy inspector details cache: populated on-demand when nodes are selected
    details_by_key: Mapping[str, NodeInspectorDetails] = _EMPTY_MAP
    selected_node_key: str | None = None
    selected_node_keys: tuple[str, ...] = ()

    # View Navigation Stack
    navigation_history: tuple[HistoryLocation, ...] = ()
    history: tuple[HistoryLocation, ...] = ()
    history_index: int = -1
    ensure_tree_visible: bool = False

    is_loading: bool = False
    status_message: str | None = None

    def __post_init__(self) -> None:
        if self.history and not self.navigation_history:
            object.__setattr__(self, "navigation_history", self.history)
        elif self.navigation_history and not self.history:
            object.__setattr__(self, "history", self.navigation_history)
        if self.selected_node_keys and self.selected_node_key is None:
            object.__setattr__(self, "selected_node_key", self.selected_node_keys[0])

    @property
    def can_navigate_back(self) -> bool:
        """True if history has previous visited nodes to navigate back to."""
        return self.history_index > 0

    @property
    def can_navigate_forward(self) -> bool:
        """True if history has forward visited nodes to navigate forward to."""
        return 0 <= self.history_index < len(self.navigation_history) - 1

    @property
    def filtered_banks(self) -> tuple[BankListItem, ...]:
        """Declarative pure query of banks filtered by search and modified flags."""
        q = self.bank_search_query.strip().lower()
        res = []
        for b in self.available_banks:
            if q and q not in b.name.lower():
                continue
            if self.filter_modified_only and b.status == BankStatus.VANILLA:
                continue
            res.append(b)
        return tuple(res)

    @property
    def selected_node_details(self) -> NodeInspectorDetails | None:
        """Currently selected node inspector details, if resolved."""
        if not self.selected_node_key:
            return None
        return self.details_by_key.get(self.selected_node_key)


# ==============================================================================
# Events & Commands (What Just Happened)
# ==============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class AvailableBanksDiscovered:
    """New list of project and cache soundbanks available."""

    banks: tuple[BankListItem, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class BankSearchQuerySet:
    """User updated the bank list filter text."""

    query: str


@dataclass(frozen=True, slots=True, kw_only=True)
class FilterModifiedOnlyToggled:
    """User toggled 'Show Modified Only'."""

    enabled: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class BankSelectionRequested:
    """User selected a SoundBank to view."""

    bank_name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class BankParsedSuccessfully:
    """External I/O completed parsing bank into tree and inspector models."""

    bank_name: str
    root_keys: tuple[str, ...]
    nodes_by_key: Mapping[str, HircTreeNode]
    details_by_key: Mapping[str, NodeInspectorDetails] = _EMPTY_MAP


@dataclass(frozen=True, slots=True, kw_only=True)
class BankParseFailed:
    """Parsing the SoundBank raised an error."""

    bank_name: str
    error: str


@dataclass(frozen=True, slots=True, kw_only=True)
class TreeSearchQuerySet:
    """User updated the hierarchy tree filter text."""

    query: str


@dataclass(frozen=True, slots=True, kw_only=True)
class TreeModifiedFilterToggled:
    """User toggled the hierarchy tree modified-only filter checkbox."""

    filter_modified_only: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class TreeOverlayToggled:
    """User toggled a hierarchy tree overlay."""

    overlay: TreeOverlay
    enabled: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class TreeColumnToggled:
    """User toggled a hierarchy tree column visibility."""

    column: TreeColumn
    visible: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class NodeSelectionRequested:
    """User selected a node in the hierarchy/chunk tree."""

    node_key: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class MultiNodeSelectionRequested:
    """User selected multiple nodes in the hierarchy/chunk tree."""

    node_keys: tuple[str, ...]
    primary_key: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class JumpToNodeRequested:
    """User clicked an interactive reference link to jump to a specific node."""

    node_key: str
    bank_name: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class NavigateHistoryBackRequested:
    """User clicked the Back navigation button or pressed Alt+Left."""


@dataclass(frozen=True, slots=True, kw_only=True)
class NavigateHistoryForwardRequested:
    """User clicked the Forward navigation button or pressed Alt+Right."""


@dataclass(frozen=True, slots=True, kw_only=True)
class NodeDetailsResolved:
    """Inspector details dynamically resolved on-demand for a selected node."""

    node_key: str
    details: NodeInspectorDetails


@dataclass(frozen=True, slots=True, kw_only=True)
class BankWemMetadataResolved:
    """Lazy WEM header metadata resolved for audio nodes in a SoundBank."""

    bank_name: str
    metadata_by_key: Mapping[str, NodeMetadata] = _EMPTY_MAP


@dataclass(frozen=True, slots=True, kw_only=True)
class BankCacheInvalidated:
    """SoundBank was modified or deleted; remove from in-memory cache."""

    bank_name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ViewerCachesInvalidated:
    """Wipes all cached parsed bank trees and invalidates session caches."""


@dataclass(frozen=True, slots=True, kw_only=True)
class BankViewerReset:
    """Reset viewer state back to initial blank state."""


type ViewerEvent = (
    AvailableBanksDiscovered
    | BankSearchQuerySet
    | FilterModifiedOnlyToggled
    | BankSelectionRequested
    | BankParsedSuccessfully
    | BankParseFailed
    | TreeSearchQuerySet
    | TreeModifiedFilterToggled
    | TreeOverlayToggled
    | TreeColumnToggled
    | NodeSelectionRequested
    | MultiNodeSelectionRequested
    | JumpToNodeRequested
    | NavigateHistoryBackRequested
    | NavigateHistoryForwardRequested
    | NodeDetailsResolved
    | BankWemMetadataResolved
    | BankCacheInvalidated
    | ViewerCachesInvalidated
    | BankViewerReset
)


# ==============================================================================
# Effect Intents (Data As Actions)
# ==============================================================================


@dataclass(frozen=True, slots=True, kw_only=True)
class LoadBankIntent:
    """Request Imperative Shell to load and parse SoundBank bytes."""

    bank_name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolveNodeDetailsIntent:
    """Request Imperative Shell to resolve property inspector details for an inspected node."""

    bank_name: str
    node_key: str


@dataclass(frozen=True, slots=True, kw_only=True)
class ResolveBankWemMetadataIntent:
    """Request Imperative Shell to lazily inspect WEM headers for the current bank."""

    bank_name: str


@dataclass(frozen=True, slots=True, kw_only=True)
class LogStatusIntent:
    """Request logging or UI status bar display."""

    message: str


type ViewerIntent = (
    LoadBankIntent | ResolveNodeDetailsIntent | ResolveBankWemMetadataIntent | LogStatusIntent
)
