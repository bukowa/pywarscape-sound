"""Unit and integration tests for Bank Viewer Overlays, Columns, and Metadata Extraction."""

import json
import re
import subprocess
import tempfile
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from src.bnk.bank import BkhdChunk, DataChunk, DidxChunk, DidxEntry, HircChunk, SoundBank
from src.bnk.models import (
    AkPlaylistItem,
    CAkAction,
    CAkEvent,
    CAkRanSeqCntr,
    CAkSound,
)
from src.bnk.wem import build_pcm_wem_from_wav_bytes, build_silent_pcm_wem_bytes
from src.deps import resolve_vgmstream_path
from src.engine.diff import BankDiffResult
from src.engine.metadata_fields import (
    EMPTY_NODE_METADATA,
    MetadataField,
    MetadataValue,
    NodeMetadata,
    Provenance,
    extract_hirc_metadata,
    extract_wem_header_metadata,
    format_wem_codec,
    merge_node_metadata,
)
from src.ui.columns import (
    format_channel_label,
    format_duration_ms,
    format_sample_rate_khz,
)
from src.ui.features.bank_viewer.columns import (
    COLUMN_SPECS_BY_ID,
    WEM_HEADER_COLUMNS,
    TreeColumn,
    requires_wem_metadata,
)
from src.ui.features.bank_viewer.overlays import TreeOverlay
from src.ui.features.bank_viewer.state import BankParsedSuccessfully, HircTreeNode
from src.ui.features.bank_viewer.store import BankViewerStore
from src.ui.features.bank_viewer.view import BankViewerView
from src.ui.shell.view import MainWindow
from src.ui.theme import COLOR_STATUS_MODIFIED, COLOR_TEXT_MUTED
from src.workspace.cache import GameCache
from tests.support.factories import make_audio_project, skip_or_fail_missing_asset

# ==============================================================================
# 1. Engine Metadata Extractor (extract_hirc_metadata)
# ==============================================================================


def test_extract_hirc_metadata_ran_seq_cntr_shuffle():
    """Synthetic CAkRanSeqCntr with shuffle mode and weights extracts expected metadata."""
    cntr = CAkRanSeqCntr(
        id=10,
        mode=0,
        random_mode=1,
        avoid_repeat_count=4,
        playlist=[
            AkPlaylistItem(play_id=101, weight=50000),
            AkPlaylistItem(play_id=102, weight=30000),
            AkPlaylistItem(play_id=103, weight=20000),
        ],
    )
    meta = extract_hirc_metadata(cntr)

    val_mode = meta.get(MetadataField.PLAYBACK_MODE)
    assert val_mode is not None
    assert val_mode.value == "Shuffle"
    assert val_mode.provenance == Provenance.BINARY

    val_ar = meta.get(MetadataField.AVOID_REPEAT)
    assert val_ar is not None
    assert val_ar.value == 4
    assert val_ar.provenance == Provenance.BINARY

    val_pw = meta.get(MetadataField.PLAYLIST_WEIGHTS)
    assert val_pw is not None
    assert val_pw.provenance == Provenance.BINARY
    assert val_pw.value == (("hirc:101", 50.0), ("hirc:102", 30.0), ("hirc:103", 20.0))


def test_extract_hirc_metadata_ran_seq_cntr_duplicate_play_ids():
    """Duplicate play_id entries in playlist sum their percentage share accurately."""
    cntr = CAkRanSeqCntr(
        id=11,
        mode=0,
        random_mode=0,
        avoid_repeat_count=1,
        playlist=[
            AkPlaylistItem(play_id=101, weight=25000),
            AkPlaylistItem(play_id=102, weight=50000),
            AkPlaylistItem(play_id=101, weight=25000),
        ],
    )
    meta = extract_hirc_metadata(cntr)
    pw = meta.get_value(MetadataField.PLAYLIST_WEIGHTS)
    assert pw == (("hirc:101", 50.0), ("hirc:102", 50.0))


def test_extract_hirc_metadata_ran_seq_cntr_all_zero_weights():
    """All-zero weights in playlist distribute equal shares summing to 100.0."""
    cntr = CAkRanSeqCntr(
        id=12,
        mode=0,
        random_mode=0,
        avoid_repeat_count=0,
        playlist=[
            AkPlaylistItem(play_id=101, weight=0),
            AkPlaylistItem(play_id=102, weight=0),
            AkPlaylistItem(play_id=103, weight=0),
            AkPlaylistItem(play_id=104, weight=0),
        ],
    )
    meta = extract_hirc_metadata(cntr)
    pw = meta.get_value(MetadataField.PLAYLIST_WEIGHTS)
    assert pw is not None
    assert len(pw) == 4
    for _, share in pw:
        assert share == 25.0
    assert sum(s for _, s in pw) == 100.0


def test_extract_hirc_metadata_ran_seq_cntr_sequence_mode():
    """Sequence mode (mode=1) yields 'Sequence'."""
    cntr = CAkRanSeqCntr(
        id=13,
        mode=1,
        random_mode=0,
        avoid_repeat_count=1,
    )
    meta = extract_hirc_metadata(cntr)
    assert meta.get_value(MetadataField.PLAYBACK_MODE) == "Sequence"


def test_extract_hirc_metadata_non_container_returns_empty():
    """Non-container (CAkSound) returns EMPTY_NODE_METADATA."""
    snd = CAkSound(id=20, source_id=999)
    meta = extract_hirc_metadata(snd)
    assert meta == EMPTY_NODE_METADATA


def test_extract_wem_header_metadata_pcm_mono_full_and_truncated():
    """Validates pure extraction of duration, channels, sample rate, and codec from full and truncated mono PCM WEM."""
    full_wem = build_silent_pcm_wem_bytes(duration_ms=250, sample_rate=32000)
    meta_full = extract_wem_header_metadata(full_wem)

    assert meta_full.get_value(MetadataField.DURATION_MS) == 250.0
    assert meta_full.get_value(MetadataField.CHANNELS) == 1
    assert meta_full.get_value(MetadataField.SAMPLE_RATE) == 32000
    assert meta_full.get_value(MetadataField.CODEC) == "PCM"

    truncated = full_wem[:256]
    meta_trunc = extract_wem_header_metadata(truncated)

    assert meta_trunc.get_value(MetadataField.DURATION_MS) == 250.0
    assert meta_trunc.get_value(MetadataField.CHANNELS) == 1
    assert meta_trunc.get_value(MetadataField.SAMPLE_RATE) == 32000
    assert meta_trunc.get_value(MetadataField.CODEC) == "PCM"


def test_extract_wem_header_metadata_pcm_stereo_full_and_truncated():
    """Validates pure extraction of stereo 44.1kHz PCM WEM headers."""
    raw_pcm = b"\x00\x00\x00\x00" * 8820
    full_wem = build_pcm_wem_from_wav_bytes(raw_pcm, target_sample_rate=44100, target_channels=2)
    meta_full = extract_wem_header_metadata(full_wem)

    assert meta_full.get_value(MetadataField.DURATION_MS) == 100.0
    assert meta_full.get_value(MetadataField.CHANNELS) == 2
    assert meta_full.get_value(MetadataField.SAMPLE_RATE) == 44100
    assert meta_full.get_value(MetadataField.CODEC) == "PCM"

    truncated = full_wem[:256]
    meta_trunc = extract_wem_header_metadata(truncated)

    assert meta_trunc.get_value(MetadataField.DURATION_MS) == 100.0
    assert meta_trunc.get_value(MetadataField.CHANNELS) == 2
    assert meta_trunc.get_value(MetadataField.SAMPLE_RATE) == 44100
    assert meta_trunc.get_value(MetadataField.CODEC) == "PCM"


def test_extract_wem_header_metadata_corrupt_or_empty_bytes():
    """Corrupt, empty, or non-RIFF bytes safely return EMPTY_NODE_METADATA without throwing."""
    assert extract_wem_header_metadata(b"") == EMPTY_NODE_METADATA
    assert extract_wem_header_metadata(b"CORRUPT_NOT_RIFF_DATA") == EMPTY_NODE_METADATA
    assert extract_wem_header_metadata(b"RIFF\x04\x00\x00\x00WAVE") == EMPTY_NODE_METADATA
    assert extract_wem_header_metadata(b"RIFF\x20\x00\x00\x00WAVEfmt ") == EMPTY_NODE_METADATA


def test_merge_node_metadata():
    """merge_node_metadata preserves base order, replaces overlapping keys, and appends extra keys."""
    base = NodeMetadata(
        entries=(
            (MetadataField.PLAYBACK_MODE, MetadataValue("Shuffle", Provenance.BINARY)),
            (MetadataField.AVOID_REPEAT, MetadataValue(2, Provenance.BINARY)),
            (MetadataField.DURATION_MS, MetadataValue(100.0, Provenance.BINARY)),
        )
    )
    extra = NodeMetadata(
        entries=(
            (MetadataField.DURATION_MS, MetadataValue(250.0, Provenance.BINARY)),
            (MetadataField.CHANNELS, MetadataValue(1, Provenance.BINARY)),
            (MetadataField.CODEC, MetadataValue("PCM", Provenance.BINARY)),
        )
    )

    assert merge_node_metadata(EMPTY_NODE_METADATA, EMPTY_NODE_METADATA) == EMPTY_NODE_METADATA
    assert merge_node_metadata(base, EMPTY_NODE_METADATA) == base
    assert merge_node_metadata(EMPTY_NODE_METADATA, extra) == extra

    merged = merge_node_metadata(base, extra)
    assert merged.entries == (
        (MetadataField.PLAYBACK_MODE, MetadataValue("Shuffle", Provenance.BINARY)),
        (MetadataField.AVOID_REPEAT, MetadataValue(2, Provenance.BINARY)),
        (MetadataField.DURATION_MS, MetadataValue(250.0, Provenance.BINARY)),
        (MetadataField.CHANNELS, MetadataValue(1, Provenance.BINARY)),
        (MetadataField.CODEC, MetadataValue("PCM", Provenance.BINARY)),
    )


def test_pure_formatting_helpers():
    """Validates pure formatting helpers for duration, sample rate, channels, and codec."""
    assert format_duration_ms(-5.0) == ""
    assert format_duration_ms(50.0) == "0.05s"
    assert format_duration_ms(15140.0) == "15.14s"
    assert format_duration_ms(60000.0) == "1:00"
    assert format_duration_ms(135000.0) == "2:15"

    assert format_sample_rate_khz(0) == ""
    assert format_sample_rate_khz(32000) == "32 kHz"
    assert format_sample_rate_khz(44100) == "44.1 kHz"
    assert format_sample_rate_khz(28000) == "28 kHz"

    assert format_channel_label(0) == ""
    assert format_channel_label(1) == "Mono"
    assert format_channel_label(2) == "Stereo"
    assert format_channel_label(4) == "4ch"

    assert format_wem_codec(0xFFFF, "WAVE") == "Vorbis"
    assert format_wem_codec(0x0001, "WAVE") == "PCM"
    assert format_wem_codec(0xFFFE, "WAVE") == "PCM"
    assert format_wem_codec(0x0002, "WAVE") == "ADPCM"
    assert format_wem_codec(0x0001, "XWMA") == "XWMA"
    assert format_wem_codec(0x1234, "WAVE") == "0x1234"


def test_column_specs_duration_and_format_cells():
    """Validates ColumnSpec cell extractors for DURATION and FORMAT."""
    spec_dur = COLUMN_SPECS_BY_ID[TreeColumn.DURATION]
    spec_fmt = COLUMN_SPECS_BY_ID[TreeColumn.FORMAT]

    assert spec_dur.default_visible is False
    assert spec_dur.hideable is True
    assert spec_dur.searchable is True
    assert spec_dur.default_width == 85

    assert spec_fmt.default_visible is False
    assert spec_fmt.hideable is True
    assert spec_fmt.searchable is True
    assert spec_fmt.default_width == 145

    empty_node = HircTreeNode(
        key="hirc:1", label="Sound_1", id_str="1", type_str="Sound", details=""
    )
    assert spec_dur.cell(empty_node, None, frozenset()) == ""
    assert spec_fmt.cell(empty_node, None, frozenset()) == ""

    meta_vorbis = NodeMetadata(
        entries=(
            (MetadataField.DURATION_MS, MetadataValue(15140.0, Provenance.BINARY)),
            (MetadataField.CODEC, MetadataValue("Vorbis", Provenance.BINARY)),
            (MetadataField.SAMPLE_RATE, MetadataValue(32000, Provenance.BINARY)),
            (MetadataField.CHANNELS, MetadataValue(1, Provenance.BINARY)),
        )
    )
    node_v = HircTreeNode(
        key="hirc:2",
        label="Sound_2",
        id_str="2",
        type_str="Sound",
        details="",
        metadata=meta_vorbis,
    )
    assert spec_dur.cell(node_v, None, frozenset()) == "15.14s"
    assert spec_fmt.cell(node_v, None, frozenset()) == "Vorbis 32 kHz Mono"

    meta_pcm = NodeMetadata(
        entries=(
            (MetadataField.CODEC, MetadataValue("PCM", Provenance.BINARY)),
            (MetadataField.SAMPLE_RATE, MetadataValue(44100, Provenance.BINARY)),
            (MetadataField.CHANNELS, MetadataValue(2, Provenance.BINARY)),
        )
    )
    node_p = HircTreeNode(
        key="hirc:3",
        label="Sound_3",
        id_str="3",
        type_str="Sound",
        details="",
        metadata=meta_pcm,
    )
    assert spec_fmt.cell(node_p, None, frozenset()) == "PCM 44.1 kHz Stereo"

    meta_4ch = NodeMetadata(
        entries=(
            (MetadataField.CODEC, MetadataValue("Vorbis", Provenance.BINARY)),
            (MetadataField.SAMPLE_RATE, MetadataValue(28000, Provenance.BINARY)),
            (MetadataField.CHANNELS, MetadataValue(4, Provenance.BINARY)),
        )
    )
    node_4 = HircTreeNode(
        key="hirc:4",
        label="Sound_4",
        id_str="4",
        type_str="Sound",
        details="",
        metadata=meta_4ch,
    )
    assert spec_fmt.cell(node_4, None, frozenset()) == "Vorbis 28 kHz 4ch"

    assert requires_wem_metadata((TreeColumn.NAME, TreeColumn.ID)) is False
    assert requires_wem_metadata((TreeColumn.NAME, TreeColumn.DURATION)) is True
    assert requires_wem_metadata((TreeColumn.NAME, TreeColumn.FORMAT)) is True
    assert frozenset({TreeColumn.DURATION, TreeColumn.FORMAT}) == WEM_HEADER_COLUMNS


# ==============================================================================
# 2. Column & Overlay Specs (columns.py, overlays.py)
# ==============================================================================


def test_edge_aware_variation_pct_and_playback_rule(qapp, qtbot):
    """Edge-aware VARIATION_PCT only displays shares under the containing container."""
    ev = CAkEvent(id=1, actions=[2])
    act = CAkAction.create_play(id=2, target_id=100)
    cntr = CAkRanSeqCntr(
        id=100,
        mode=0,
        random_mode=1,
        avoid_repeat_count=3,
        children=[201, 202],
        playlist=[
            AkPlaylistItem(play_id=201, weight=75000),
            AkPlaylistItem(play_id=202, weight=25000),
        ],
    )
    s1 = CAkSound(id=201, source_id=1001, stream_type=2)
    s2 = CAkSound(id=202, source_id=1002, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        hirc=HircChunk(objects=[ev, act, cntr, s1, s2]),
    )

    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    store.load_soundbank_instance("test_var.bnk", bank)

    # Enable TreeColumn.VARIATION_PCT and TreeColumn.PLAYBACK_RULE
    store.set_tree_column_visible(TreeColumn.VARIATION_PCT, True)
    store.set_tree_column_visible(TreeColumn.PLAYBACK_RULE, True)

    assert store.state.visible_columns == (
        TreeColumn.NAME,
        TreeColumn.ID,
        TreeColumn.TYPE,
        TreeColumn.VARIATION_PCT,
        TreeColumn.PLAYBACK_RULE,
        TreeColumn.DETAILS,
    )

    var_idx = store.state.visible_columns.index(TreeColumn.VARIATION_PCT)
    rule_idx = store.state.visible_columns.index(TreeColumn.PLAYBACK_RULE)

    # 1. Expand "Hierarchy Tree" down to CAkRanSeqCntr and its children
    hier_item = view.tree_widget.topLevelItem(1)
    assert hier_item.text(0) == "Hierarchy Tree"
    view._on_tree_item_expanded(hier_item)

    ev_item = hier_item.child(0)
    assert ev_item.text(1) == "1"
    view._on_tree_item_expanded(ev_item)

    act_item = ev_item.child(0)
    assert act_item.text(1) == "2"
    view._on_tree_item_expanded(act_item)

    cntr_item = act_item.child(0)
    assert cntr_item.text(1) == "100"
    assert cntr_item.text(rule_idx) == "Shuffle (no-repeat 3)"
    assert cntr_item.text(var_idx) == ""

    view._on_tree_item_expanded(cntr_item)
    assert cntr_item.childCount() == 2
    snd1_item = cntr_item.child(0)
    snd2_item = cntr_item.child(1)

    assert snd1_item.text(1) == "201"
    assert snd1_item.text(var_idx) == "75.0%"

    assert snd2_item.text(1) == "202"
    assert snd2_item.text(var_idx) == "25.0%"

    # 2. Expand "All Objects by Type" -> "Sounds"
    cats_item = view.tree_widget.topLevelItem(2)
    assert cats_item.text(0) == "All Objects by Type"
    view._on_tree_item_expanded(cats_item)

    sounds_group_item = None
    for i in range(cats_item.childCount()):
        if "Sounds" in cats_item.child(i).text(0):
            sounds_group_item = cats_item.child(i)
            break
    assert sounds_group_item is not None
    view._on_tree_item_expanded(sounds_group_item)

    # In sounds_group_item, the same sound nodes must have empty variation %
    assert sounds_group_item.childCount() >= 2
    for i in range(sounds_group_item.childCount()):
        c = sounds_group_item.child(i)
        assert c.text(var_idx) == ""


def test_sequence_container_playback_rule():
    """Sequence container mode=1, avoid_repeat_count=1 formats as 'Sequence' without no-repeat."""
    node = HircTreeNode(
        key="hirc:50",
        label="MySeq",
        id_str="50",
        type_str="RanSeqCntr",
        details="",
        metadata=NodeMetadata(
            entries=(
                (MetadataField.PLAYBACK_MODE, MetadataValue("Sequence", Provenance.BINARY)),
                (MetadataField.AVOID_REPEAT, MetadataValue(1, Provenance.BINARY)),
            )
        ),
    )
    res = COLUMN_SPECS_BY_ID[TreeColumn.PLAYBACK_RULE].cell(node, None, frozenset())
    assert res == "Sequence"


def test_independent_overlay_combinations(qapp, qtbot):
    """GAME_NAMES, HIGHLIGHT_MODIFIED, and MODIFIED_TAG can be toggled independently."""
    snd = CAkSound(id=30, source_id=12345, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[snd]),
    )
    diff = BankDiffResult(modified_object_ids=frozenset([30]))

    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    store.load_soundbank_instance("mod_test.bnk", bank, diff_result=diff)

    orig_node = store.state.nodes_by_key["hirc:30"]
    friendly_node = HircTreeNode(
        key=orig_node.key,
        label=orig_node.label,
        id_str=orig_node.id_str,
        type_str=orig_node.type_str,
        details="raw_details",
        child_keys=orig_node.child_keys,
        is_modified=True,
        friendly_label="friendly_sound_name",
        friendly_details="resolved_friendly_details",
        friendly_details_provenance=Provenance.DATABASE,
    )
    store._dispatch(
        BankParsedSuccessfully(
            bank_name="mod_test.bnk",
            root_keys=store.state.root_keys,
            nodes_by_key={**store.state.nodes_by_key, "hirc:30": friendly_node},
        )
    )

    # Expand cat:sounds so child item hirc:30 is rendered
    cat_sounds = view._items_by_key.get("cat:sounds")
    assert cat_sounds is not None
    view._on_tree_item_expanded(cat_sounds)

    details_idx = store.state.visible_columns.index(TreeColumn.DETAILS)
    item = view._items_by_key["hirc:30"]

    # 1. All 3 active by default: GAME_NAMES, HIGHLIGHT_MODIFIED, MODIFIED_TAG
    assert item.text(0) == "friendly_sound_name"
    assert item.text(details_idx) == "[MOD] resolved_friendly_details"
    assert item.foreground(0).color().name().upper() == COLOR_STATUS_MODIFIED.upper()

    # 2. MODIFIED_TAG off: removes [MOD] prefix, keeps HIGHLIGHT_MODIFIED color and friendly name
    store.set_tree_overlay(TreeOverlay.MODIFIED_TAG, False)
    cat_sounds = view._items_by_key.get("cat:sounds")
    assert cat_sounds is not None
    view._on_tree_item_expanded(cat_sounds)
    item = view._items_by_key["hirc:30"]
    assert item.text(0) == "friendly_sound_name"
    assert item.text(details_idx) == "resolved_friendly_details"
    assert item.foreground(0).color().name().upper() == COLOR_STATUS_MODIFIED.upper()

    # 3. GAME_NAMES off, MODIFIED_TAG back on: shows raw label and raw details with [MOD] tag
    store.set_tree_overlay(TreeOverlay.MODIFIED_TAG, True)
    store.set_tree_overlay(TreeOverlay.GAME_NAMES, False)
    cat_sounds = view._items_by_key.get("cat:sounds")
    assert cat_sounds is not None
    view._on_tree_item_expanded(cat_sounds)
    item = view._items_by_key["hirc:30"]
    assert item.text(0) == orig_node.label
    assert item.text(details_idx) == "[MOD] raw_details"
    assert item.foreground(0).color().name().upper() == COLOR_STATUS_MODIFIED.upper()

    # 4. HIGHLIGHT_MODIFIED off: color is cleared, but [MOD] tag remains
    store.set_tree_overlay(TreeOverlay.HIGHLIGHT_MODIFIED, False)
    cat_sounds = view._items_by_key.get("cat:sounds")
    assert cat_sounds is not None
    view._on_tree_item_expanded(cat_sounds)
    item = view._items_by_key["hirc:30"]
    assert item.foreground(0).color().name().upper() != COLOR_STATUS_MODIFIED.upper()
    assert item.text(details_idx) == "[MOD] raw_details"


def test_heuristic_provenance_visual_indicator(qapp, qtbot):
    """Heuristic provenance renders with muted text and tooltip, respecting overrides."""
    snd = CAkSound(id=40, source_id=12345, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=1, version=112),
        hirc=HircChunk(objects=[snd]),
    )

    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    store.load_soundbank_instance("heur_test.bnk", bank)

    orig_node = store.state.nodes_by_key["hirc:40"]
    heur_node = HircTreeNode(
        key=orig_node.key,
        label=orig_node.label,
        id_str=orig_node.id_str,
        type_str=orig_node.type_str,
        details=orig_node.details,
        child_keys=orig_node.child_keys,
        friendly_label="inferred_sound",
        friendly_details="4 units · cavalry",
        friendly_details_provenance=Provenance.HEURISTIC,
    )
    store._dispatch(
        BankParsedSuccessfully(
            bank_name="heur_test.bnk",
            root_keys=store.state.root_keys,
            nodes_by_key={**store.state.nodes_by_key, "hirc:40": heur_node},
        )
    )

    cat_sounds = view._items_by_key.get("cat:sounds")
    assert cat_sounds is not None
    view._on_tree_item_expanded(cat_sounds)

    details_idx = store.state.visible_columns.index(TreeColumn.DETAILS)
    item = view._items_by_key["hirc:40"]

    # When GAME_NAMES is active: Details renders with COLOR_TEXT_MUTED and tooltip "Inferred (heuristic)"
    assert item.text(details_idx) == "4 units · cavalry"
    assert item.foreground(details_idx).color().name().upper() == COLOR_TEXT_MUTED.upper()
    assert item.toolTip(details_idx) == "Inferred (heuristic)"

    # Turn GAME_NAMES off: clears heuristic styling (details shows raw details, foreground is default)
    store.set_tree_overlay(TreeOverlay.GAME_NAMES, False)
    cat_sounds = view._items_by_key.get("cat:sounds")
    assert cat_sounds is not None
    view._on_tree_item_expanded(cat_sounds)
    item = view._items_by_key["hirc:40"]
    assert item.text(details_idx) == orig_node.details
    assert item.foreground(details_idx).color().name().upper() != COLOR_TEXT_MUTED.upper()

    # Re-enable GAME_NAMES and mark node as modified with HIGHLIGHT_MODIFIED active
    store.set_tree_overlay(TreeOverlay.GAME_NAMES, True)
    mod_heur_node = HircTreeNode(
        key=heur_node.key,
        label=heur_node.label,
        id_str=heur_node.id_str,
        type_str=heur_node.type_str,
        details=heur_node.details,
        child_keys=heur_node.child_keys,
        is_modified=True,
        friendly_label="inferred_sound",
        friendly_details="4 units · cavalry",
        friendly_details_provenance=Provenance.HEURISTIC,
    )
    store._dispatch(
        BankParsedSuccessfully(
            bank_name="heur_test.bnk",
            root_keys=store.state.root_keys,
            nodes_by_key={**store.state.nodes_by_key, "hirc:40": mod_heur_node},
        )
    )
    cat_sounds = view._items_by_key.get("cat:sounds")
    assert cat_sounds is not None
    view._on_tree_item_expanded(cat_sounds)
    item = view._items_by_key["hirc:40"]
    # Overridden by HIGHLIGHT_MODIFIED foreground while preserving tooltip
    assert item.foreground(details_idx).color().name().upper() == COLOR_STATUS_MODIFIED.upper()
    assert item.toolTip(details_idx) == "Inferred (heuristic)"


def test_search_across_new_visible_columns(qapp, qtbot):
    """Searching across custom visible columns matches only when those columns are visible."""
    ev = CAkEvent(id=1, actions=[2])
    act = CAkAction.create_play(id=2, target_id=100)
    cntr = CAkRanSeqCntr(
        id=100,
        mode=0,
        random_mode=1,
        avoid_repeat_count=3,
        children=[201, 202],
        playlist=[
            AkPlaylistItem(play_id=201, weight=75000),
            AkPlaylistItem(play_id=202, weight=25000),
        ],
    )
    s1 = CAkSound(id=201, source_id=1001, stream_type=2)
    s2 = CAkSound(id=202, source_id=1002, stream_type=2)
    bank = SoundBank(
        header=BkhdChunk(bank_id=999, version=112),
        hirc=HircChunk(objects=[ev, act, cntr, s1, s2]),
    )

    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    store.load_soundbank_instance("search_cols.bnk", bank)

    # 1. VARIATION_PCT hidden initially: searching "75.0%" does NOT match
    store.set_tree_search_query("75.0%")
    assert "hirc:201" not in view._items_by_key

    # 2. Enable VARIATION_PCT: searching "75.0%" DOES match
    store.set_tree_column_visible(TreeColumn.VARIATION_PCT, True)
    store.set_tree_search_query("75.0%")
    assert "hirc:201" in view._items_by_key

    # 3. PLAYBACK_RULE hidden initially: searching "no-repeat 3" does NOT match
    store.set_tree_column_visible(TreeColumn.PLAYBACK_RULE, False)
    store.set_tree_search_query("no-repeat 3")
    assert "hirc:100" not in view._items_by_key

    # 4. Enable PLAYBACK_RULE: searching "no-repeat 3" DOES match
    store.set_tree_column_visible(TreeColumn.PLAYBACK_RULE, True)
    store.set_tree_search_query("no-repeat 3")
    assert "hirc:100" in view._items_by_key


def test_header_context_menu_configuration(qapp, qtbot):
    """Header context menu is enabled and the mandatory NAME column cannot be unchecked."""
    store = BankViewerStore()
    view = BankViewerView(store)
    qtbot.addWidget(view)

    assert view.tree_widget.header().contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    assert view.column_actions[TreeColumn.NAME].isEnabled() is False
    assert view.column_actions[TreeColumn.NAME].isChecked() is True


# ==============================================================================
# 3. Persistence Round-Trip (MainWindow + settings.json)
# ==============================================================================


def test_persistence_round_trip(tmp_path: Path, qapp, qtbot):
    """Overlays and columns persist to settings.json and restore with fallback filtering."""
    settings_file = tmp_path / "settings.json"
    win1 = MainWindow(settings_file=settings_file)
    qtbot.addWidget(win1)

    # Toggle overlays (GAME_NAMES off, MODIFIED_TAG off) and columns (ID off, VARIATION_PCT on, PLAYBACK_RULE on)
    win1.bank_viewer_store.set_tree_overlay(TreeOverlay.GAME_NAMES, False)
    win1.bank_viewer_store.set_tree_overlay(TreeOverlay.MODIFIED_TAG, False)
    win1.bank_viewer_store.set_tree_column_visible(TreeColumn.ID, False)
    win1.bank_viewer_store.set_tree_column_visible(TreeColumn.VARIATION_PCT, True)
    win1.bank_viewer_store.set_tree_column_visible(TreeColumn.PLAYBACK_RULE, True)

    assert settings_file.is_file()
    saved = json.loads(settings_file.read_text(encoding="utf-8"))
    assert "bank_viewer" in saved
    assert saved["bank_viewer"] == {
        "overlays": ["highlight_modified"],
        "columns": ["name", "type", "variation_pct", "playback_rule", "details"],
    }

    # Write unknown IDs and omitted "name" into settings.json
    corrupt_settings = {
        "bank_viewer": {
            "overlays": ["highlight_modified", "future_overlay"],
            "columns": ["type", "variation_pct", "future_col"],
        }
    }
    settings_file.write_text(json.dumps(corrupt_settings, indent=2), encoding="utf-8")

    win2 = MainWindow(settings_file=settings_file)
    qtbot.addWidget(win2)

    assert win2.bank_viewer_store.state.active_overlays == frozenset(
        {TreeOverlay.HIGHLIGHT_MODIFIED}
    )
    assert win2.bank_viewer_store.state.visible_columns == (
        TreeColumn.NAME,
        TreeColumn.TYPE,
        TreeColumn.VARIATION_PCT,
    )


def test_strict_laziness_and_wem_columns_end_to_end_ui(tmp_path: Path, qapp, qtbot):
    """Verifies strict laziness of WEM columns, UI rendering, searchability, and mutation Undo/Redo."""
    project = make_audio_project(tmp_path / "mod")
    cache = GameCache(cache_dir=tmp_path / "cache")
    cache.cache_dir.mkdir(parents=True, exist_ok=True)
    project.cache = cache
    project.audio_dir.mkdir(parents=True, exist_ok=True)

    # 1. Streamed loose WEM 1001 (250ms = 0.25s)
    w1001 = build_silent_pcm_wem_bytes(duration_ms=250, sample_rate=32000)
    (cache.cache_dir / "1001.wem").write_bytes(w1001)

    # 2. Embedded WEM 2001 in main bank (500ms = 0.50s)
    w2001 = build_silent_pcm_wem_bytes(duration_ms=500, sample_rate=32000)

    # 3. Companion bank 777 with embedded WEM 3001 (750ms = 0.75s)
    w3001 = build_silent_pcm_wem_bytes(duration_ms=750, sample_rate=32000)
    comp_bank = SoundBank(
        header=BkhdChunk(bank_id=777, version=112),
        didx=DidxChunk(entries=[DidxEntry(file_id=3001, offset=0, size=len(w3001))]),
        data=DataChunk(data=w3001),
    )
    (cache.cache_dir / "companion.bnk").write_bytes(comp_bank.to_bytes())

    # 4. Main bank 999
    s1 = CAkSound(id=101, source_id=2001, stream_type=0)
    s2 = CAkSound(id=102, source_id=1001, stream_type=2)
    s3 = CAkSound(id=103, source_id=3001, file_id=777, stream_type=0)
    main_bank = SoundBank(
        header=BkhdChunk(bank_id=999, version=112),
        didx=DidxChunk(entries=[DidxEntry(file_id=2001, offset=0, size=len(w2001))]),
        data=DataChunk(data=w2001),
        hirc=HircChunk(objects=[s1, s2, s3]),
    )
    (project.audio_dir / "main.bnk").write_bytes(main_bank.to_bytes())

    # Create Store and View
    store = BankViewerStore(project=project)
    view = BankViewerView(store)
    qtbot.addWidget(view)

    store.select_bank("main.bnk")

    # A. STRICT LAZINESS: DURATION and FORMAT are OFF initially
    assert TreeColumn.DURATION not in store.state.visible_columns
    assert TreeColumn.FORMAT not in store.state.visible_columns
    assert store.state.wem_metadata_loaded is False
    assert store.state.nodes_by_key["hirc:101"].metadata == EMPTY_NODE_METADATA
    assert store.state.nodes_by_key["hirc:102"].metadata == EMPTY_NODE_METADATA
    assert store.state.nodes_by_key["hirc:103"].metadata == EMPTY_NODE_METADATA
    assert store.state.nodes_by_key["media:2001"].metadata == EMPTY_NODE_METADATA

    # B. Enable DURATION and FORMAT -> lazy inspection triggers
    store.set_tree_column_visible(TreeColumn.DURATION, True)
    store.set_tree_column_visible(TreeColumn.FORMAT, True)

    assert store.state.wem_metadata_loaded is True
    dur_idx = store.state.visible_columns.index(TreeColumn.DURATION)
    fmt_idx = store.state.visible_columns.index(TreeColumn.FORMAT)

    # Check state metadata values
    assert (
        store.state.nodes_by_key["hirc:102"].metadata.get_value(MetadataField.DURATION_MS) == 250.0
    )
    assert (
        store.state.nodes_by_key["hirc:101"].metadata.get_value(MetadataField.DURATION_MS) == 500.0
    )
    assert (
        store.state.nodes_by_key["hirc:103"].metadata.get_value(MetadataField.DURATION_MS) == 750.0
    )
    assert (
        store.state.nodes_by_key["media:2001"].metadata.get_value(MetadataField.DURATION_MS)
        == 500.0
    )

    # Check rendered cells in BankViewerView
    store.select_node("hirc:102")
    item_102 = view._items_by_key["hirc:102"]
    assert item_102.text(dur_idx) == "0.25s"
    assert item_102.text(fmt_idx) == "PCM 32 kHz Mono"

    store.select_node("hirc:101")
    item_101 = view._items_by_key["hirc:101"]
    assert item_101.text(dur_idx) == "0.50s"
    assert item_101.text(fmt_idx) == "PCM 32 kHz Mono"

    store.select_node("hirc:103")
    item_103 = view._items_by_key["hirc:103"]
    assert item_103.text(dur_idx) == "0.75s"
    assert item_103.text(fmt_idx) == "PCM 32 kHz Mono"

    store.select_node("media:2001")
    item_media = view._items_by_key["media:2001"]
    assert item_media.text(dur_idx) == "0.50s"

    # C. Tree search matching
    store.set_tree_search_query("0.25s")
    assert "hirc:102" in view._items_by_key
    assert "hirc:101" not in view._items_by_key
    store.set_tree_search_query("")

    # D. Audio mutation (mute_sound) + Undo + Redo live cell updates (0.25s -> 0.05s -> 0.25s -> 0.05s)
    res_mute = store.mute_sound(102)
    assert res_mute is True
    assert view._items_by_key["hirc:102"].text(dur_idx) == "0.05s"

    res_undo = store.undo_mutation()
    assert res_undo is True
    assert view._items_by_key["hirc:102"].text(dur_idx) == "0.25s"

    res_redo = store.redo_mutation()
    assert res_redo is True
    assert view._items_by_key["hirc:102"].text(dur_idx) == "0.05s"


# ==============================================================================
# 4. Vanilla Game Banks Verification (@pytest.mark.assets)
# ==============================================================================


@pytest.mark.assets
def test_vanilla_wem_headers_parity_against_vgmstream():
    """Ground-truth parity test verifying header extraction against vgmstream-cli -m."""
    vgm_exe = resolve_vgmstream_path()
    if vgm_exe is None or not vgm_exe.is_file():
        skip_or_fail_missing_asset(f"vgmstream-cli not found at {vgm_exe}")

    cache_audio = Path(".cache/attila/audio")
    if not cache_audio.is_dir():
        skip_or_fail_missing_asset(f"Missing vanilla game audio in {cache_audio}")

    loose_wems = list(cache_audio.glob("*.wem"))[:15]
    bnk_files = [p for p in cache_audio.glob("*.bnk") if p.stat().st_size > 10000][:5]
    if not loose_wems and not bnk_files:
        skip_or_fail_missing_asset(f"No .wem or .bnk files found in {cache_audio}")

    tested_count = 0

    # 1. Test loose .wem files
    for wem_path in loose_wems:
        wem_bytes = wem_path.read_bytes()
        if len(wem_bytes) < 64:
            continue

        meta = extract_wem_header_metadata(wem_bytes[:512])
        if not meta.entries:
            continue

        proc = subprocess.run(
            [str(vgm_exe), "-m", str(wem_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            continue

        out = proc.stdout
        sr_match = re.search(r"sample rate:\s*(\d+)", out)
        ch_match = re.search(r"channels:\s*(\d+)", out)
        samples_match = re.search(r"stream total samples:\s*(\d+)", out)
        if not (sr_match and ch_match and samples_match):
            continue

        vgm_sr = int(sr_match.group(1))
        vgm_ch = int(ch_match.group(1))
        vgm_samples = int(samples_match.group(1))
        vgm_dur_ms = (vgm_samples / vgm_sr) * 1000.0

        assert meta.get_value(MetadataField.SAMPLE_RATE) == vgm_sr
        assert meta.get_value(MetadataField.CHANNELS) == vgm_ch
        assert meta.get_value(MetadataField.CODEC) == "Vorbis"
        ext_dur = float(meta.get_value(MetadataField.DURATION_MS))
        assert abs(ext_dur - vgm_dur_ms) <= 0.2
        tested_count += 1

    # 2. Test embedded DIDX slices from .bnk files
    for bnk_path in bnk_files:
        try:
            bank = SoundBank.from_bytes(bnk_path.read_bytes())
        except Exception:
            continue

        if not (bank.didx and bank.didx.entries and bank.data and bank.data.data):
            continue

        for entry in bank.didx.entries[:3]:
            slice_bytes = bank.data.data[entry.offset : entry.offset + entry.size]
            if len(slice_bytes) < 64:
                continue

            meta = extract_wem_header_metadata(slice_bytes[:512])
            if not meta.entries:
                continue

            with tempfile.NamedTemporaryFile(suffix=".wem", delete=False) as tf:
                tf.write(slice_bytes)
                tf_name = tf.name

            try:
                proc = subprocess.run(
                    [str(vgm_exe), "-m", tf_name],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if proc.returncode != 0:
                    continue

                out = proc.stdout
                sr_match = re.search(r"sample rate:\s*(\d+)", out)
                ch_match = re.search(r"channels:\s*(\d+)", out)
                samples_match = re.search(r"stream total samples:\s*(\d+)", out)
                if not (sr_match and ch_match and samples_match):
                    continue

                vgm_sr = int(sr_match.group(1))
                vgm_ch = int(ch_match.group(1))
                vgm_samples = int(samples_match.group(1))
                vgm_dur_ms = (vgm_samples / vgm_sr) * 1000.0

                assert meta.get_value(MetadataField.SAMPLE_RATE) == vgm_sr
                assert meta.get_value(MetadataField.CHANNELS) == vgm_ch
                assert meta.get_value(MetadataField.CODEC) == "Vorbis"
                ext_dur = float(meta.get_value(MetadataField.DURATION_MS))
                assert abs(ext_dur - vgm_dur_ms) <= 0.2
                tested_count += 1
            finally:
                Path(tf_name).unlink(missing_ok=True)

    assert tested_count >= 20, (
        f"Expected >= 20 verified streams against vgmstream, got {tested_count}"
    )


@pytest.mark.assets
def test_vanilla_game_banks_container_metadata_extraction():
    """Validates container metadata extraction across real vanilla SoundBank files."""
    cache_audio = Path(".cache/attila/audio")
    bnk_files = list(cache_audio.glob("*.bnk")) if cache_audio.is_dir() else []
    if not bnk_files:
        skip_or_fail_missing_asset(f"Missing vanilla game banks in {cache_audio}")

    verified_containers = 0
    for bnk_path in bnk_files:
        try:
            data = bnk_path.read_bytes()
            bank = SoundBank.from_bytes(data)
        except Exception:
            continue

        if not bank.hirc:
            continue

        for obj in bank.hirc.objects:
            if isinstance(obj, CAkRanSeqCntr) and obj.playlist:
                meta = extract_hirc_metadata(obj)
                mode_val = meta.get(MetadataField.PLAYBACK_MODE)
                assert mode_val is not None
                assert mode_val.provenance == Provenance.BINARY
                assert mode_val.value in ("Random", "Shuffle", "Sequence")

                ar_val = meta.get(MetadataField.AVOID_REPEAT)
                assert ar_val is not None
                assert ar_val.provenance == Provenance.BINARY
                assert isinstance(ar_val.value, int)
                assert ar_val.value >= 0

                pw_val = meta.get(MetadataField.PLAYLIST_WEIGHTS)
                assert pw_val is not None
                assert pw_val.provenance == Provenance.BINARY
                assert isinstance(pw_val.value, tuple)
                total_share = sum(share for _, share in pw_val.value)
                for _, share in pw_val.value:
                    assert share >= 0.0
                assert abs(total_share - 100.0) < 0.1

                verified_containers += 1

    assert verified_containers >= 1000, (
        f"Expected >= 1000 verified containers, got {verified_containers}"
    )
