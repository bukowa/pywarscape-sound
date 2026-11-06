"""
Behavioral Transition Matrix Proof for Audio Catalog.

Proves pure mathematical correctness of evolve_catalog_state,
filter_catalog_entries, and extract_catalog_categories.
ZERO Mocks, ZERO Monkeypatching, High-Signal Equivalence Classes.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.engine.catalog.causation import (
    evolve_catalog_state,
    extract_catalog_categories,
    filter_catalog_entries,
)
from src.engine.catalog.structs import (
    CatalogEffectIntent,
    CatalogError,
    CatalogEvent,
    CatalogFilterSpec,
    CatalogLoaded,
    CatalogLoading,
    CatalogScope,
    CatalogState,
    CatalogUnloaded,
    FilterChangedEvent,
    LibraryLoadedEvent,
    LibraryLoadFailedEvent,
    LoadFullLibraryIntent,
    RequestLibraryLoadEvent,
)
from src.models import AudioCatalogEntry

# -----------------------------------------------------------------------------
# Test Fixtures & Domain Entities
# -----------------------------------------------------------------------------

ENTRY_HORSE = AudioCatalogEntry(
    wem_id=10001,
    source_bank="battle_sfx",
    display_name="horse_gallop_turkic_01",
    category="Battle",
    duration_ms=2500.0,
    metadata_tags=("cavalry", "mount", "steppe"),
)

ENTRY_SHOUT = AudioCatalogEntry(
    wem_id=10002,
    source_bank="battle_sfx",
    display_name="legionary_charge_shout",
    category="Voiceover",
    duration_ms=1800.0,
    metadata_tags=("infantry", "roman", "charge"),
)

ENTRY_MUSIC = AudioCatalogEntry(
    wem_id=20001,
    source_bank="rome2_music",
    display_name="rome_campaign_theme",
    category="Music",
    duration_ms=120000.0,
    metadata_tags=("campaign", "strings", "ambient"),
)

ENTRY_UI = AudioCatalogEntry(
    wem_id=30001,
    source_bank="ui_frontend",
    display_name="button_confirm_click",
    category="UI",
    duration_ms=150.0,
    metadata_tags=("frontend", "interface"),
)

ENTRY_GENERAL = AudioCatalogEntry(
    wem_id=40001,
    source_bank="ui_frontend",
    display_name="system_notification_beep",
    category="General",
    duration_ms=300.0,
    metadata_tags=("notification",),
)

ALL_ENTRIES = (ENTRY_HORSE, ENTRY_SHOUT, ENTRY_MUSIC, ENTRY_UI, ENTRY_GENERAL)


# -----------------------------------------------------------------------------
# Canonical Transition Matrix Schema
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class TransitionCase:
    """Canonical test case representing a single catalog state-machine transition."""

    id: str
    state: CatalogState
    event: CatalogEvent
    expected_state: CatalogState
    expected_effects: tuple[CatalogEffectIntent, ...]


CASES: tuple[TransitionCase, ...] = (
    # 1. Valid Transition: Unloaded -> Loading with full library scope
    TransitionCase(
        id="unloaded_to_loading_on_request",
        state=CatalogUnloaded(local_entries=(ENTRY_HORSE, ENTRY_SHOUT)),
        event=RequestLibraryLoadEvent(scope=CatalogScope.FULL_LIBRARY),
        expected_state=CatalogLoading(
            local_entries=(ENTRY_HORSE, ENTRY_SHOUT),
            scope=CatalogScope.FULL_LIBRARY,
        ),
        expected_effects=(LoadFullLibraryIntent(current_bank_name=""),),
    ),
    # 2. Boundary Edge: Unloaded with empty entries -> Loading
    TransitionCase(
        id="unloaded_to_loading_empty_entries",
        state=CatalogUnloaded(local_entries=()),
        event=RequestLibraryLoadEvent(scope=CatalogScope.FULL_LIBRARY),
        expected_state=CatalogLoading(
            local_entries=(),
            scope=CatalogScope.FULL_LIBRARY,
        ),
        expected_effects=(LoadFullLibraryIntent(current_bank_name=""),),
    ),
    # 3. Valid Transition: Loading -> Loaded on library loaded
    TransitionCase(
        id="loading_to_loaded_on_library_loaded",
        state=CatalogLoading(
            local_entries=(ENTRY_HORSE,),
            scope=CatalogScope.FULL_LIBRARY,
        ),
        event=LibraryLoadedEvent(
            entries=(ENTRY_HORSE, ENTRY_SHOUT, ENTRY_MUSIC),
            current_bank_name="battle_sfx",
        ),
        expected_state=CatalogLoaded(
            all_entries=(ENTRY_HORSE, ENTRY_SHOUT, ENTRY_MUSIC),
            filtered_entries=(ENTRY_HORSE, ENTRY_SHOUT, ENTRY_MUSIC),
            categories=("Battle", "Music", "Voiceover"),
            filter_spec=CatalogFilterSpec(
                query="",
                scope_or_category="All Categories",
                current_bank_name="battle_sfx",
            ),
        ),
        expected_effects=(),
    ),
    # 4. Boundary Edge: Loading with empty discovered entries -> Loaded
    TransitionCase(
        id="loading_to_loaded_empty_entries",
        state=CatalogLoading(
            local_entries=(),
            scope=CatalogScope.FULL_LIBRARY,
        ),
        event=LibraryLoadedEvent(
            entries=(),
            current_bank_name="battle_sfx",
        ),
        expected_state=CatalogLoaded(
            all_entries=(),
            filtered_entries=(),
            categories=(),
            filter_spec=CatalogFilterSpec(
                query="",
                scope_or_category="All Categories",
                current_bank_name="battle_sfx",
            ),
        ),
        expected_effects=(),
    ),
    # 5. Failure Transition: Loading -> Error on library load failure
    TransitionCase(
        id="loading_to_error_on_library_load_failed",
        state=CatalogLoading(
            local_entries=(ENTRY_HORSE,),
            scope=CatalogScope.FULL_LIBRARY,
        ),
        event=LibraryLoadFailedEvent(
            error_message="Failed to unpack music.pack: I/O error",
        ),
        expected_state=CatalogError(
            error_message="Failed to unpack music.pack: I/O error",
            local_entries=(ENTRY_HORSE,),
        ),
        expected_effects=(),
    ),
    # 6. Filter Update: Text query updates filtered entries
    TransitionCase(
        id="loaded_filter_changed_query_text",
        state=CatalogLoaded(
            all_entries=(ENTRY_HORSE, ENTRY_SHOUT, ENTRY_MUSIC),
            filtered_entries=(ENTRY_HORSE, ENTRY_SHOUT, ENTRY_MUSIC),
            categories=("Battle", "Music", "Voiceover"),
            filter_spec=CatalogFilterSpec(
                query="",
                scope_or_category="All Categories",
                current_bank_name="battle_sfx",
            ),
        ),
        event=FilterChangedEvent(
            filter_spec=CatalogFilterSpec(
                query="gallop",
                scope_or_category="All Categories",
                current_bank_name="battle_sfx",
            ),
        ),
        expected_state=CatalogLoaded(
            all_entries=(ENTRY_HORSE, ENTRY_SHOUT, ENTRY_MUSIC),
            filtered_entries=(ENTRY_HORSE,),
            categories=("Battle", "Music", "Voiceover"),
            filter_spec=CatalogFilterSpec(
                query="gallop",
                scope_or_category="All Categories",
                current_bank_name="battle_sfx",
            ),
        ),
        expected_effects=(),
    ),
    # 7. Scope Filter: "This Bank" matches active bank entries
    TransitionCase(
        id="loaded_filter_changed_scope_this_bank",
        state=CatalogLoaded(
            all_entries=(ENTRY_HORSE, ENTRY_SHOUT, ENTRY_MUSIC),
            filtered_entries=(ENTRY_HORSE, ENTRY_SHOUT, ENTRY_MUSIC),
            categories=("Battle", "Music", "Voiceover"),
            filter_spec=CatalogFilterSpec(
                query="",
                scope_or_category="All Categories",
                current_bank_name="battle_sfx",
            ),
        ),
        event=FilterChangedEvent(
            filter_spec=CatalogFilterSpec(
                query="",
                scope_or_category="This Bank",
                current_bank_name="battle_sfx",
            ),
        ),
        expected_state=CatalogLoaded(
            all_entries=(ENTRY_HORSE, ENTRY_SHOUT, ENTRY_MUSIC),
            filtered_entries=(ENTRY_HORSE, ENTRY_SHOUT),
            categories=("Battle", "Music", "Voiceover"),
            filter_spec=CatalogFilterSpec(
                query="",
                scope_or_category="This Bank",
                current_bank_name="battle_sfx",
            ),
        ),
        expected_effects=(),
    ),
    # 8. Scope Filter: "Other Banks" excludes active bank entries
    TransitionCase(
        id="loaded_filter_changed_scope_other_banks",
        state=CatalogLoaded(
            all_entries=(ENTRY_HORSE, ENTRY_SHOUT, ENTRY_MUSIC),
            filtered_entries=(ENTRY_HORSE, ENTRY_SHOUT, ENTRY_MUSIC),
            categories=("Battle", "Music", "Voiceover"),
            filter_spec=CatalogFilterSpec(
                query="",
                scope_or_category="All Categories",
                current_bank_name="battle_sfx",
            ),
        ),
        event=FilterChangedEvent(
            filter_spec=CatalogFilterSpec(
                query="",
                scope_or_category="Other Banks",
                current_bank_name="battle_sfx",
            ),
        ),
        expected_state=CatalogLoaded(
            all_entries=(ENTRY_HORSE, ENTRY_SHOUT, ENTRY_MUSIC),
            filtered_entries=(ENTRY_MUSIC,),
            categories=("Battle", "Music", "Voiceover"),
            filter_spec=CatalogFilterSpec(
                query="",
                scope_or_category="Other Banks",
                current_bank_name="battle_sfx",
            ),
        ),
        expected_effects=(),
    ),
    # 9. Category Filter: Specific category matches exact category
    TransitionCase(
        id="loaded_filter_changed_scope_category",
        state=CatalogLoaded(
            all_entries=(ENTRY_HORSE, ENTRY_SHOUT, ENTRY_MUSIC),
            filtered_entries=(ENTRY_HORSE, ENTRY_SHOUT, ENTRY_MUSIC),
            categories=("Battle", "Music", "Voiceover"),
            filter_spec=CatalogFilterSpec(
                query="",
                scope_or_category="All Categories",
                current_bank_name="battle_sfx",
            ),
        ),
        event=FilterChangedEvent(
            filter_spec=CatalogFilterSpec(
                query="",
                scope_or_category="Voiceover",
                current_bank_name="battle_sfx",
            ),
        ),
        expected_state=CatalogLoaded(
            all_entries=(ENTRY_HORSE, ENTRY_SHOUT, ENTRY_MUSIC),
            filtered_entries=(ENTRY_SHOUT,),
            categories=("Battle", "Music", "Voiceover"),
            filter_spec=CatalogFilterSpec(
                query="",
                scope_or_category="Voiceover",
                current_bank_name="battle_sfx",
            ),
        ),
        expected_effects=(),
    ),
    # 10. Idempotency: Loaded state absorbs duplicate LibraryLoadedEvent
    TransitionCase(
        id="loaded_absorbs_duplicate_library_loaded_idempotently",
        state=CatalogLoaded(
            all_entries=(ENTRY_HORSE,),
            filtered_entries=(ENTRY_HORSE,),
            categories=("Battle",),
            filter_spec=CatalogFilterSpec(
                query="",
                scope_or_category="All Categories",
                current_bank_name="battle_sfx",
            ),
        ),
        event=LibraryLoadedEvent(
            entries=(ENTRY_HORSE, ENTRY_SHOUT),
            current_bank_name="battle_sfx",
        ),
        expected_state=CatalogLoaded(
            all_entries=(ENTRY_HORSE,),
            filtered_entries=(ENTRY_HORSE,),
            categories=("Battle",),
            filter_spec=CatalogFilterSpec(
                query="",
                scope_or_category="All Categories",
                current_bank_name="battle_sfx",
            ),
        ),
        expected_effects=(),
    ),
    # 11. Idempotency: Loaded state absorbs redundant RequestLibraryLoadEvent
    TransitionCase(
        id="loaded_absorbs_request_load_idempotently",
        state=CatalogLoaded(
            all_entries=(ENTRY_HORSE,),
            filtered_entries=(ENTRY_HORSE,),
            categories=("Battle",),
            filter_spec=CatalogFilterSpec(
                query="",
                scope_or_category="All Categories",
                current_bank_name="battle_sfx",
            ),
        ),
        event=RequestLibraryLoadEvent(scope=CatalogScope.FULL_LIBRARY),
        expected_state=CatalogLoaded(
            all_entries=(ENTRY_HORSE,),
            filtered_entries=(ENTRY_HORSE,),
            categories=("Battle",),
            filter_spec=CatalogFilterSpec(
                query="",
                scope_or_category="All Categories",
                current_bank_name="battle_sfx",
            ),
        ),
        expected_effects=(),
    ),
    # 12. Idempotency: Unloaded state absorbs unexpected LibraryLoadedEvent
    TransitionCase(
        id="unloaded_absorbs_unexpected_library_loaded_idempotently",
        state=CatalogUnloaded(local_entries=(ENTRY_HORSE,)),
        event=LibraryLoadedEvent(
            entries=(ENTRY_HORSE,),
            current_bank_name="battle_sfx",
        ),
        expected_state=CatalogUnloaded(local_entries=(ENTRY_HORSE,)),
        expected_effects=(),
    ),
    # 13. Idempotency: Unloaded state absorbs unexpected FilterChangedEvent
    TransitionCase(
        id="unloaded_absorbs_filter_changed_idempotently",
        state=CatalogUnloaded(local_entries=()),
        event=FilterChangedEvent(
            filter_spec=CatalogFilterSpec(
                query="charge",
                scope_or_category="All Categories",
            ),
        ),
        expected_state=CatalogUnloaded(local_entries=()),
        expected_effects=(),
    ),
    # 14. Idempotency: Loading state absorbs duplicate RequestLibraryLoadEvent
    TransitionCase(
        id="loading_absorbs_duplicate_request_idempotently",
        state=CatalogLoading(
            local_entries=(),
            scope=CatalogScope.FULL_LIBRARY,
        ),
        event=RequestLibraryLoadEvent(scope=CatalogScope.FULL_LIBRARY),
        expected_state=CatalogLoading(
            local_entries=(),
            scope=CatalogScope.FULL_LIBRARY,
        ),
        expected_effects=(),
    ),
    # 15. Idempotency: Loading state absorbs unexpected FilterChangedEvent
    TransitionCase(
        id="loading_absorbs_filter_changed_idempotently",
        state=CatalogLoading(
            local_entries=(),
            scope=CatalogScope.FULL_LIBRARY,
        ),
        event=FilterChangedEvent(
            filter_spec=CatalogFilterSpec(
                query="test",
                scope_or_category="All Categories",
            ),
        ),
        expected_state=CatalogLoading(
            local_entries=(),
            scope=CatalogScope.FULL_LIBRARY,
        ),
        expected_effects=(),
    ),
    # 16. Idempotency: Error state absorbs unexpected FilterChangedEvent
    TransitionCase(
        id="error_absorbs_unexpected_filter_changed_idempotently",
        state=CatalogError(
            error_message="disk error",
            local_entries=(ENTRY_HORSE,),
        ),
        event=FilterChangedEvent(
            filter_spec=CatalogFilterSpec(
                query="horse",
                scope_or_category="All Categories",
            ),
        ),
        expected_state=CatalogError(
            error_message="disk error",
            local_entries=(ENTRY_HORSE,),
        ),
        expected_effects=(),
    ),
    # 17. Idempotency: Error state absorbs unexpected LibraryLoadedEvent
    TransitionCase(
        id="error_absorbs_unexpected_library_loaded_idempotently",
        state=CatalogError(
            error_message="disk error",
            local_entries=(ENTRY_HORSE,),
        ),
        event=LibraryLoadedEvent(
            entries=(ENTRY_HORSE,),
            current_bank_name="battle_sfx",
        ),
        expected_state=CatalogError(
            error_message="disk error",
            local_entries=(ENTRY_HORSE,),
        ),
        expected_effects=(),
    ),
)


# -----------------------------------------------------------------------------
# Test Execution: State Transition Matrix
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.id)
def test_reconcile_transitions(case: TransitionCase) -> None:
    actual_state, actual_effects = evolve_catalog_state(case.state, case.event)
    assert actual_state == case.expected_state
    assert actual_effects == case.expected_effects


# -----------------------------------------------------------------------------
# Unit Tests: filter_catalog_entries
# -----------------------------------------------------------------------------


def test_filter_catalog_empty_entries() -> None:
    spec = CatalogFilterSpec(query="anything", scope_or_category="All Categories")
    assert filter_catalog_entries((), spec) == ()


def test_filter_catalog_empty_query_all_categories_returns_all() -> None:
    spec = CatalogFilterSpec(query="", scope_or_category="All Categories")
    assert filter_catalog_entries(ALL_ENTRIES, spec) == ALL_ENTRIES


def test_filter_catalog_case_insensitive_text_search_display_name() -> None:
    spec = CatalogFilterSpec(query="GALLOP", scope_or_category="All Categories")
    assert filter_catalog_entries(ALL_ENTRIES, spec) == (ENTRY_HORSE,)


def test_filter_catalog_case_insensitive_text_search_source_bank() -> None:
    spec = CatalogFilterSpec(query="ROME2_MUSIC", scope_or_category="All Categories")
    assert filter_catalog_entries(ALL_ENTRIES, spec) == (ENTRY_MUSIC,)


def test_filter_catalog_text_search_wem_id() -> None:
    spec = CatalogFilterSpec(query="10002", scope_or_category="All Categories")
    assert filter_catalog_entries(ALL_ENTRIES, spec) == (ENTRY_SHOUT,)


def test_filter_catalog_case_insensitive_text_search_metadata_tags() -> None:
    spec = CatalogFilterSpec(query="STRINGS", scope_or_category="All Categories")
    assert filter_catalog_entries(ALL_ENTRIES, spec) == (ENTRY_MUSIC,)


def test_filter_catalog_scope_this_bank() -> None:
    spec = CatalogFilterSpec(
        query="",
        scope_or_category="This Bank",
        current_bank_name="BATTLE_SFX",
    )
    assert filter_catalog_entries(ALL_ENTRIES, spec) == (ENTRY_HORSE, ENTRY_SHOUT)


def test_filter_catalog_scope_other_banks() -> None:
    spec = CatalogFilterSpec(
        query="",
        scope_or_category="Other Banks",
        current_bank_name="battle_sfx",
    )
    assert filter_catalog_entries(ALL_ENTRIES, spec) == (ENTRY_MUSIC, ENTRY_UI, ENTRY_GENERAL)


def test_filter_catalog_scope_custom_category() -> None:
    spec = CatalogFilterSpec(
        query="",
        scope_or_category="VOICEOVER",
        current_bank_name="battle_sfx",
    )
    assert filter_catalog_entries(ALL_ENTRIES, spec) == (ENTRY_SHOUT,)


def test_filter_catalog_query_and_category_combined() -> None:
    # Both match
    spec_match = CatalogFilterSpec(
        query="legionary",
        scope_or_category="Voiceover",
        current_bank_name="battle_sfx",
    )
    assert filter_catalog_entries(ALL_ENTRIES, spec_match) == (ENTRY_SHOUT,)

    # Text matches but category differs
    spec_mismatch = CatalogFilterSpec(
        query="legionary",
        scope_or_category="Battle",
        current_bank_name="battle_sfx",
    )
    assert filter_catalog_entries(ALL_ENTRIES, spec_mismatch) == ()


def test_filter_catalog_no_match_returns_empty() -> None:
    spec = CatalogFilterSpec(query="nonexistent_xyz", scope_or_category="All Categories")
    assert filter_catalog_entries(ALL_ENTRIES, spec) == ()


# -----------------------------------------------------------------------------
# Unit Tests: extract_catalog_categories
# -----------------------------------------------------------------------------


def test_extract_categories_empty_entries() -> None:
    assert extract_catalog_categories(()) == ()


def test_extract_categories_sorted_unique_non_empty() -> None:
    entries = (ENTRY_HORSE, ENTRY_SHOUT, ENTRY_MUSIC, ENTRY_UI)
    assert extract_catalog_categories(entries) == ("Battle", "Music", "UI", "Voiceover")


def test_extract_categories_excludes_reserved_and_empty_names() -> None:
    reserved_entries = (
        AudioCatalogEntry(
            wem_id=9001,
            source_bank="bank_a",
            display_name="test_1",
            category="All Categories",
        ),
        AudioCatalogEntry(
            wem_id=9002,
            source_bank="bank_a",
            display_name="test_2",
            category="This Bank",
        ),
        AudioCatalogEntry(
            wem_id=9003,
            source_bank="bank_a",
            display_name="test_3",
            category="Other Banks",
        ),
        AudioCatalogEntry(
            wem_id=9004,
            source_bank="bank_a",
            display_name="test_4",
            category="General",
        ),
        AudioCatalogEntry(
            wem_id=9005,
            source_bank="bank_a",
            display_name="test_5",
            category="",
        ),
        AudioCatalogEntry(
            wem_id=9006,
            source_bank="bank_a",
            display_name="test_6",
            category="Voiceover",
        ),
    )
    assert extract_catalog_categories(reserved_entries) == ("Voiceover",)


def test_extract_categories_all_default_or_reserved_returns_empty() -> None:
    entries = (
        AudioCatalogEntry(
            wem_id=9004,
            source_bank="bank_a",
            display_name="test_4",
            category="General",
        ),
    )
    assert extract_catalog_categories(entries) == ()
