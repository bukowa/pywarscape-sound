"""Table-driven state transition proof for Bank Viewer causation logic.

Strictly mock-free, pure functional verification.
"""

from dataclasses import dataclass

import pytest

from src.engine.metadata_fields import (
    MetadataField,
    MetadataValue,
    NodeMetadata,
    Provenance,
)
from src.ui.features.bank_viewer.causation import reconcile_viewer
from src.ui.features.bank_viewer.columns import TreeColumn
from src.ui.features.bank_viewer.overlays import TreeOverlay
from src.ui.features.bank_viewer.state import (
    AvailableBanksDiscovered,
    BankCacheInvalidated,
    BankListItem,
    BankParsedSuccessfully,
    BankParseFailed,
    BankSearchQuerySet,
    BankSelectionRequested,
    BankStatus,
    BankTreeData,
    BankViewerReset,
    BankViewerState,
    BankWemMetadataResolved,
    FilterModifiedOnlyToggled,
    HircTreeNode,
    HistoryLocation,
    InspectorProperty,
    LoadBankIntent,
    LogStatusIntent,
    NodeDetailsResolved,
    NodeInspectorDetails,
    NodeSelectionRequested,
    ResolveBankWemMetadataIntent,
    ResolveNodeDetailsIntent,
    TreeColumnToggled,
    TreeModifiedFilterToggled,
    TreeOverlayToggled,
    TreeSearchQuerySet,
    ViewerEvent,
    ViewerIntent,
)


@dataclass(frozen=True, slots=True)
class TransitionCase:
    """A test vector row in the transition proof matrix."""

    id: str
    initial_state: BankViewerState
    event: ViewerEvent
    expected_state: BankViewerState
    expected_intents: tuple[ViewerIntent, ...]


# Static fixture definitions
BANK_1 = BankListItem(
    name="battle_individual_units.bnk",
    status=BankStatus.VANILLA,
    size_bytes=10240,
    path="cache/audio/battle_individual_units.bnk",
)
BANK_2 = BankListItem(
    name="init.bnk",
    status=BankStatus.MODIFIED,
    size_bytes=20480,
    path="pack_root/audio/init.bnk",
)

NODE_CHUNKS = HircTreeNode(
    key="group:chunks",
    label="Chunks",
    id_str="",
    type_str="Group",
    details="Summary",
    child_keys=("chunk:BKHD",),
)
NODE_BKHD = HircTreeNode(
    key="chunk:BKHD",
    label="BKHD (Header)",
    id_str="100",
    type_str="Chunk",
    details="v112",
    child_keys=(),
)

DETAILS_BKHD = NodeInspectorDetails(
    node_key="chunk:BKHD",
    name="BKHD (Header)",
    object_type="Chunk",
    object_id=100,
    hex_id="0x00000064",
    properties=(InspectorProperty(category="Header", label="Version", value="112"),),
)

CACHED_INIT = BankTreeData(
    bank_name="init.bnk",
    root_keys=("group:chunks",),
    nodes_by_key={"group:chunks": NODE_CHUNKS, "chunk:BKHD": NODE_BKHD},
)


CASES: tuple[TransitionCase, ...] = (
    TransitionCase(
        id="discover_available_banks",
        initial_state=BankViewerState(),
        event=AvailableBanksDiscovered(banks=(BANK_1, BANK_2)),
        expected_state=BankViewerState(available_banks=(BANK_1, BANK_2)),
        expected_intents=(),
    ),
    TransitionCase(
        id="set_bank_search_query",
        initial_state=BankViewerState(available_banks=(BANK_1, BANK_2)),
        event=BankSearchQuerySet(query="init"),
        expected_state=BankViewerState(
            available_banks=(BANK_1, BANK_2),
            bank_search_query="init",
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="toggle_filter_modified_only",
        initial_state=BankViewerState(available_banks=(BANK_1, BANK_2)),
        event=FilterModifiedOnlyToggled(enabled=True),
        expected_state=BankViewerState(
            available_banks=(BANK_1, BANK_2),
            filter_modified_only=True,
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="request_cold_bank_selection_triggers_load_intent",
        initial_state=BankViewerState(available_banks=(BANK_1, BANK_2)),
        event=BankSelectionRequested(bank_name="init.bnk"),
        expected_state=BankViewerState(
            available_banks=(BANK_1, BANK_2),
            selected_bank_name="init.bnk",
            navigation_history=(HistoryLocation(bank_name="init.bnk", node_key=None),),
            history_index=0,
            is_loading=True,
            status_message="Loading init.bnk...",
        ),
        expected_intents=(LoadBankIntent(bank_name="init.bnk"),),
    ),
    TransitionCase(
        id="request_warm_bank_selection_cache_hit_zero_io",
        initial_state=BankViewerState(
            available_banks=(BANK_1, BANK_2),
            cached_banks={"init.bnk": CACHED_INIT},
        ),
        event=BankSelectionRequested(bank_name="init.bnk"),
        expected_state=BankViewerState(
            available_banks=(BANK_1, BANK_2),
            cached_banks={"init.bnk": CACHED_INIT},
            selected_bank_name="init.bnk",
            root_keys=("group:chunks",),
            nodes_by_key={"group:chunks": NODE_CHUNKS, "chunk:BKHD": NODE_BKHD},
            navigation_history=(HistoryLocation(bank_name="init.bnk", node_key=None),),
            history_index=0,
            is_loading=False,
            status_message="Loaded init.bnk (cached)",
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="bank_parsed_successfully_populates_tree_and_cache",
        initial_state=BankViewerState(
            available_banks=(BANK_1, BANK_2),
            selected_bank_name="init.bnk",
            is_loading=True,
            status_message="Loading init.bnk...",
        ),
        event=BankParsedSuccessfully(
            bank_name="init.bnk",
            root_keys=("group:chunks",),
            nodes_by_key={"group:chunks": NODE_CHUNKS, "chunk:BKHD": NODE_BKHD},
            details_by_key={"chunk:BKHD": DETAILS_BKHD},
        ),
        expected_state=BankViewerState(
            available_banks=(BANK_1, BANK_2),
            selected_bank_name="init.bnk",
            cached_banks={"init.bnk": CACHED_INIT},
            root_keys=("group:chunks",),
            nodes_by_key={"group:chunks": NODE_CHUNKS, "chunk:BKHD": NODE_BKHD},
            details_by_key={"chunk:BKHD": DETAILS_BKHD},
            navigation_history=(HistoryLocation(bank_name="init.bnk", node_key=None),),
            history_index=0,
            is_loading=False,
            status_message="Loaded init.bnk",
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="bank_parse_failed_reports_error",
        initial_state=BankViewerState(
            available_banks=(BANK_1, BANK_2),
            selected_bank_name="corrupted.bnk",
            is_loading=True,
            status_message="Loading corrupted.bnk...",
        ),
        event=BankParseFailed(
            bank_name="corrupted.bnk",
            error="Unexpected EOF in BKHD chunk",
        ),
        expected_state=BankViewerState(
            available_banks=(BANK_1, BANK_2),
            selected_bank_name="corrupted.bnk",
            is_loading=False,
            status_message="Failed to load corrupted.bnk: Unexpected EOF in BKHD chunk",
        ),
        expected_intents=(
            LogStatusIntent(message="Failed to load corrupted.bnk: Unexpected EOF in BKHD chunk"),
        ),
    ),
    TransitionCase(
        id="set_tree_search_query",
        initial_state=BankViewerState(selected_bank_name="init.bnk"),
        event=TreeSearchQuerySet(query="BKHD"),
        expected_state=BankViewerState(
            selected_bank_name="init.bnk",
            tree_search_query="BKHD",
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="select_node_cache_miss_emits_resolve_intent",
        initial_state=BankViewerState(
            selected_bank_name="init.bnk",
            details_by_key={},
        ),
        event=NodeSelectionRequested(node_key="chunk:BKHD"),
        expected_state=BankViewerState(
            selected_bank_name="init.bnk",
            selected_node_key="chunk:BKHD",
            selected_node_keys=("chunk:BKHD",),
            details_by_key={},
            navigation_history=(HistoryLocation(bank_name="init.bnk", node_key="chunk:BKHD"),),
            history_index=0,
            ensure_tree_visible=False,
        ),
        expected_intents=(ResolveNodeDetailsIntent(bank_name="init.bnk", node_key="chunk:BKHD"),),
    ),
    TransitionCase(
        id="select_node_cache_hit_zero_intents",
        initial_state=BankViewerState(
            selected_bank_name="init.bnk",
            selected_node_key=None,
            details_by_key={"chunk:BKHD": DETAILS_BKHD},
        ),
        event=NodeSelectionRequested(node_key="chunk:BKHD"),
        expected_state=BankViewerState(
            selected_bank_name="init.bnk",
            selected_node_key="chunk:BKHD",
            selected_node_keys=("chunk:BKHD",),
            details_by_key={"chunk:BKHD": DETAILS_BKHD},
            navigation_history=(HistoryLocation(bank_name="init.bnk", node_key="chunk:BKHD"),),
            history_index=0,
            ensure_tree_visible=False,
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="deselect_node_in_tree",
        initial_state=BankViewerState(
            selected_bank_name="init.bnk",
            details_by_key={"chunk:BKHD": DETAILS_BKHD},
            selected_node_key="chunk:BKHD",
            selected_node_keys=("chunk:BKHD",),
        ),
        event=NodeSelectionRequested(node_key=None),
        expected_state=BankViewerState(
            selected_bank_name="init.bnk",
            details_by_key={"chunk:BKHD": DETAILS_BKHD},
            selected_node_key=None,
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="node_details_resolved_populates_details_cache",
        initial_state=BankViewerState(
            selected_bank_name="init.bnk",
            selected_node_key="chunk:BKHD",
            selected_node_keys=("chunk:BKHD",),
            details_by_key={},
        ),
        event=NodeDetailsResolved(node_key="chunk:BKHD", details=DETAILS_BKHD),
        expected_state=BankViewerState(
            selected_bank_name="init.bnk",
            selected_node_key="chunk:BKHD",
            selected_node_keys=("chunk:BKHD",),
            details_by_key={"chunk:BKHD": DETAILS_BKHD},
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="bank_cache_invalidated_evicts_cache_entry",
        initial_state=BankViewerState(
            cached_banks={"init.bnk": CACHED_INIT},
        ),
        event=BankCacheInvalidated(bank_name="init.bnk"),
        expected_state=BankViewerState(
            cached_banks={},
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="reset_viewer_to_blank_state_preserving_custom_overlays_and_columns",
        initial_state=BankViewerState(
            available_banks=(BANK_1,),
            cached_banks={"init.bnk": CACHED_INIT},
            selected_bank_name="init.bnk",
            selected_node_key="chunk:BKHD",
            selected_node_keys=("chunk:BKHD",),
            details_by_key={"chunk:BKHD": DETAILS_BKHD},
            active_overlays=frozenset({TreeOverlay.HIGHLIGHT_MODIFIED}),
            visible_columns=(TreeColumn.NAME, TreeColumn.DETAILS),
        ),
        event=BankViewerReset(),
        expected_state=BankViewerState(
            active_overlays=frozenset({TreeOverlay.HIGHLIGHT_MODIFIED}),
            visible_columns=(TreeColumn.NAME, TreeColumn.DETAILS),
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="toggle_tree_modified_filter_on_and_off",
        initial_state=BankViewerState(filter_tree_modified_only=False),
        event=TreeModifiedFilterToggled(filter_modified_only=True),
        expected_state=BankViewerState(filter_tree_modified_only=True),
        expected_intents=(),
    ),
    TransitionCase(
        id="toggle_overlay_highlight_modified_off",
        initial_state=BankViewerState(),
        event=TreeOverlayToggled(overlay=TreeOverlay.HIGHLIGHT_MODIFIED, enabled=False),
        expected_state=BankViewerState(
            active_overlays=frozenset({TreeOverlay.GAME_NAMES, TreeOverlay.MODIFIED_TAG})
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="toggle_overlay_highlight_modified_back_on",
        initial_state=BankViewerState(
            active_overlays=frozenset({TreeOverlay.GAME_NAMES, TreeOverlay.MODIFIED_TAG})
        ),
        event=TreeOverlayToggled(overlay=TreeOverlay.HIGHLIGHT_MODIFIED, enabled=True),
        expected_state=BankViewerState(
            active_overlays=frozenset(
                {TreeOverlay.GAME_NAMES, TreeOverlay.HIGHLIGHT_MODIFIED, TreeOverlay.MODIFIED_TAG}
            )
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="toggle_overlay_game_names_off",
        initial_state=BankViewerState(),
        event=TreeOverlayToggled(overlay=TreeOverlay.GAME_NAMES, enabled=False),
        expected_state=BankViewerState(
            active_overlays=frozenset({TreeOverlay.HIGHLIGHT_MODIFIED, TreeOverlay.MODIFIED_TAG})
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="toggle_overlay_game_names_back_on",
        initial_state=BankViewerState(
            active_overlays=frozenset({TreeOverlay.HIGHLIGHT_MODIFIED, TreeOverlay.MODIFIED_TAG})
        ),
        event=TreeOverlayToggled(overlay=TreeOverlay.GAME_NAMES, enabled=True),
        expected_state=BankViewerState(
            active_overlays=frozenset(
                {TreeOverlay.GAME_NAMES, TreeOverlay.HIGHLIGHT_MODIFIED, TreeOverlay.MODIFIED_TAG}
            )
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="toggle_overlay_modified_tag_off",
        initial_state=BankViewerState(),
        event=TreeOverlayToggled(overlay=TreeOverlay.MODIFIED_TAG, enabled=False),
        expected_state=BankViewerState(
            active_overlays=frozenset({TreeOverlay.GAME_NAMES, TreeOverlay.HIGHLIGHT_MODIFIED})
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="toggle_column_variation_pct_on",
        initial_state=BankViewerState(),
        event=TreeColumnToggled(column=TreeColumn.VARIATION_PCT, visible=True),
        expected_state=BankViewerState(
            visible_columns=(
                TreeColumn.NAME,
                TreeColumn.ID,
                TreeColumn.TYPE,
                TreeColumn.VARIATION_PCT,
                TreeColumn.DETAILS,
            )
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="toggle_column_playback_rule_on_canonical_order",
        initial_state=BankViewerState(
            visible_columns=(
                TreeColumn.NAME,
                TreeColumn.ID,
                TreeColumn.TYPE,
                TreeColumn.VARIATION_PCT,
                TreeColumn.DETAILS,
            )
        ),
        event=TreeColumnToggled(column=TreeColumn.PLAYBACK_RULE, visible=True),
        expected_state=BankViewerState(
            visible_columns=(
                TreeColumn.NAME,
                TreeColumn.ID,
                TreeColumn.TYPE,
                TreeColumn.VARIATION_PCT,
                TreeColumn.PLAYBACK_RULE,
                TreeColumn.DETAILS,
            )
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="attempt_toggle_column_name_off_is_noop",
        initial_state=BankViewerState(),
        event=TreeColumnToggled(column=TreeColumn.NAME, visible=False),
        expected_state=BankViewerState(),
        expected_intents=(),
    ),
    TransitionCase(
        id="toggle_column_duration_on_no_bank_selected",
        initial_state=BankViewerState(),
        event=TreeColumnToggled(column=TreeColumn.DURATION, visible=True),
        expected_state=BankViewerState(
            visible_columns=(
                TreeColumn.NAME,
                TreeColumn.ID,
                TreeColumn.TYPE,
                TreeColumn.DURATION,
                TreeColumn.DETAILS,
            )
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="toggle_column_duration_on_with_selected_bank_triggers_resolve_wem_intent",
        initial_state=BankViewerState(
            selected_bank_name="init.bnk",
            nodes_by_key={"group:chunks": NODE_CHUNKS},
            wem_metadata_loaded=False,
        ),
        event=TreeColumnToggled(column=TreeColumn.DURATION, visible=True),
        expected_state=BankViewerState(
            selected_bank_name="init.bnk",
            nodes_by_key={"group:chunks": NODE_CHUNKS},
            visible_columns=(
                TreeColumn.NAME,
                TreeColumn.ID,
                TreeColumn.TYPE,
                TreeColumn.DURATION,
                TreeColumn.DETAILS,
            ),
            wem_metadata_loaded=False,
        ),
        expected_intents=(ResolveBankWemMetadataIntent(bank_name="init.bnk"),),
    ),
    TransitionCase(
        id="toggle_column_format_on_when_already_loaded_is_noop_for_intents",
        initial_state=BankViewerState(
            selected_bank_name="init.bnk",
            nodes_by_key={"group:chunks": NODE_CHUNKS},
            wem_metadata_loaded=True,
        ),
        event=TreeColumnToggled(column=TreeColumn.FORMAT, visible=True),
        expected_state=BankViewerState(
            selected_bank_name="init.bnk",
            nodes_by_key={"group:chunks": NODE_CHUNKS},
            visible_columns=(
                TreeColumn.NAME,
                TreeColumn.ID,
                TreeColumn.TYPE,
                TreeColumn.FORMAT,
                TreeColumn.DETAILS,
            ),
            wem_metadata_loaded=True,
        ),
        expected_intents=(),
    ),
    TransitionCase(
        id="bank_selection_with_duration_visible_triggers_resolve_wem_intent",
        initial_state=BankViewerState(
            cached_banks={"init.bnk": CACHED_INIT},
            visible_columns=(
                TreeColumn.NAME,
                TreeColumn.DURATION,
                TreeColumn.DETAILS,
            ),
        ),
        event=BankSelectionRequested(bank_name="init.bnk"),
        expected_state=BankViewerState(
            selected_bank_name="init.bnk",
            cached_banks={"init.bnk": CACHED_INIT},
            visible_columns=(
                TreeColumn.NAME,
                TreeColumn.DURATION,
                TreeColumn.DETAILS,
            ),
            root_keys=CACHED_INIT.root_keys,
            nodes_by_key=CACHED_INIT.nodes_by_key,
            wem_metadata_loaded=False,
            navigation_history=(HistoryLocation(bank_name="init.bnk", node_key=None),),
            history=(HistoryLocation(bank_name="init.bnk", node_key=None),),
            history_index=0,
            status_message="Loaded init.bnk (cached)",
        ),
        expected_intents=(ResolveBankWemMetadataIntent(bank_name="init.bnk"),),
    ),
    TransitionCase(
        id="bank_parsed_with_format_visible_triggers_resolve_wem_intent",
        initial_state=BankViewerState(
            selected_bank_name="init.bnk",
            visible_columns=(
                TreeColumn.NAME,
                TreeColumn.FORMAT,
                TreeColumn.DETAILS,
            ),
        ),
        event=BankParsedSuccessfully(
            bank_name="init.bnk",
            root_keys=("group:chunks",),
            nodes_by_key={"group:chunks": NODE_CHUNKS},
        ),
        expected_state=BankViewerState(
            selected_bank_name="init.bnk",
            cached_banks={
                "init.bnk": BankTreeData(
                    bank_name="init.bnk",
                    root_keys=("group:chunks",),
                    nodes_by_key={"group:chunks": NODE_CHUNKS},
                    wem_metadata_loaded=False,
                )
            },
            visible_columns=(
                TreeColumn.NAME,
                TreeColumn.FORMAT,
                TreeColumn.DETAILS,
            ),
            root_keys=("group:chunks",),
            nodes_by_key={"group:chunks": NODE_CHUNKS},
            wem_metadata_loaded=False,
            navigation_history=(HistoryLocation(bank_name="init.bnk", node_key=None),),
            history=(HistoryLocation(bank_name="init.bnk", node_key=None),),
            history_index=0,
            status_message="Loaded init.bnk",
        ),
        expected_intents=(ResolveBankWemMetadataIntent(bank_name="init.bnk"),),
    ),
    TransitionCase(
        id="bank_wem_metadata_resolved_merges_metadata_and_sets_loaded",
        initial_state=BankViewerState(
            selected_bank_name="init.bnk",
            cached_banks={"init.bnk": CACHED_INIT},
            root_keys=("group:chunks",),
            nodes_by_key={"group:chunks": NODE_CHUNKS},
            wem_metadata_loaded=False,
        ),
        event=BankWemMetadataResolved(
            bank_name="init.bnk",
            metadata_by_key={
                "group:chunks": NodeMetadata(
                    entries=(
                        (
                            MetadataField.DURATION_MS,
                            MetadataValue(123.4, Provenance.BINARY),
                        ),
                    )
                )
            },
        ),
        expected_state=BankViewerState(
            selected_bank_name="init.bnk",
            cached_banks={
                "init.bnk": BankTreeData(
                    bank_name="init.bnk",
                    root_keys=("group:chunks",),
                    nodes_by_key={
                        "group:chunks": HircTreeNode(
                            key="group:chunks",
                            label="Chunks",
                            id_str="",
                            type_str="Group",
                            details="Summary",
                            child_keys=("chunk:BKHD",),
                            metadata=NodeMetadata(
                                entries=(
                                    (
                                        MetadataField.DURATION_MS,
                                        MetadataValue(123.4, Provenance.BINARY),
                                    ),
                                )
                            ),
                        ),
                        "chunk:BKHD": NODE_BKHD,
                    },
                    wem_metadata_loaded=True,
                )
            },
            root_keys=("group:chunks",),
            nodes_by_key={
                "group:chunks": HircTreeNode(
                    key="group:chunks",
                    label="Chunks",
                    id_str="",
                    type_str="Group",
                    details="Summary",
                    child_keys=("chunk:BKHD",),
                    metadata=NodeMetadata(
                        entries=(
                            (
                                MetadataField.DURATION_MS,
                                MetadataValue(123.4, Provenance.BINARY),
                            ),
                        )
                    ),
                )
            },
            wem_metadata_loaded=True,
        ),
        expected_intents=(),
    ),
)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_reconcile_viewer_transition(case: TransitionCase) -> None:
    """Verifies that reconcile_viewer deterministically produces expected state and intents."""
    new_state, intents = reconcile_viewer(case.initial_state, case.event)
    assert new_state == case.expected_state
    assert intents == case.expected_intents
