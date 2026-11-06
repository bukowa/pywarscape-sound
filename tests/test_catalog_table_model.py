"""Unit and integration tests for virtualized AudioCatalogTableModel, AudioCatalogTableView, and GameAudioTab."""

import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor

from src.engine.metadata_fields import Provenance
from src.engine.wem_metadata import resolve_wem_duration_ms
from src.models import AudioCatalogEntry
from src.ui.features.audio_sources.columns import (
    CATALOG_COLUMN_SPECS,
    DEFAULT_VISIBLE_CATALOG_COLUMNS,
    CatalogColumn,
    toggle_visible_catalog_columns,
)
from src.ui.features.audio_sources.widgets.catalog_model import (
    AudioCatalogTableModel,
    AudioCatalogTableView,
)
from src.ui.features.audio_sources.widgets.game_audio_tab import GameAudioTab
from src.ui.shell.view import MainWindow
from src.ui.theme import COLOR_TEXT_MUTED


@pytest.fixture
def sample_entries() -> tuple[AudioCatalogEntry, ...]:
    return (
        AudioCatalogEntry(
            wem_id=101,
            source_bank="unit_voice.bnk",
            is_embedded=True,
            display_name="Voice_Charge_01",
            category="Voiceover",
            duration_ms=45230.0,
        ),
        AudioCatalogEntry(
            wem_id=202,
            source_bank="battle_sfx.bnk",
            is_embedded=False,
            display_name="Sword_Clash_Heavy",
            category="Battle",
            duration_ms=0.0,
        ),
    )


@pytest.fixture
def extended_entries() -> tuple[AudioCatalogEntry, ...]:
    return (
        AudioCatalogEntry(
            wem_id=101,
            source_bank="unit_voice.bnk",
            is_embedded=True,
            display_name="Voice_Charge_01",
            category="Voiceover",
            duration_ms=45230.0,
        ),
        AudioCatalogEntry(
            wem_id=202,
            source_bank="battle_sfx.bnk",
            is_embedded=False,
            display_name="Sword_Clash_Heavy",
            category="Battle",
            duration_ms=0.0,
        ),
        AudioCatalogEntry(
            wem_id=303,
            source_bank="ambient.bnk",
            is_embedded=False,
            display_name="Wind_Breeze_Loop",
            category="Ambient",
            duration_ms=120000.0,
        ),
    )


# ==============================================================================
# 1. Pure Column Specs and Toggling
# ==============================================================================


def test_toggle_visible_catalog_columns():
    initial = DEFAULT_VISIBLE_CATALOG_COLUMNS
    assert initial == (
        CatalogColumn.NAME,
        CatalogColumn.SOURCE_BANK,
        CatalogColumn.MEDIA_ID,
        CatalogColumn.TYPE,
    )

    # Name is non-hideable, cannot be toggled off
    after_hide_name = toggle_visible_catalog_columns(initial, CatalogColumn.NAME, False)
    assert CatalogColumn.NAME in after_hide_name

    # Add Duration (placed before Category, after Type according to canonical order)
    with_dur = toggle_visible_catalog_columns(initial, CatalogColumn.DURATION, True)
    assert with_dur == (
        CatalogColumn.NAME,
        CatalogColumn.SOURCE_BANK,
        CatalogColumn.MEDIA_ID,
        CatalogColumn.TYPE,
        CatalogColumn.DURATION,
    )

    # Add Category
    with_all = toggle_visible_catalog_columns(with_dur, CatalogColumn.CATEGORY, True)
    assert with_all == tuple(s.id for s in CATALOG_COLUMN_SPECS)

    # Remove Source Bank
    less_bank = toggle_visible_catalog_columns(with_all, CatalogColumn.SOURCE_BANK, False)
    assert CatalogColumn.SOURCE_BANK not in less_bank
    assert CatalogColumn.NAME in less_bank


# ==============================================================================
# 2. Table Model Default State, Columns, and Data (Preserving Existing Tests)
# ==============================================================================


def test_catalog_table_model_columns_and_data(sample_entries):
    model = AudioCatalogTableModel(sample_entries)
    assert model.rowCount() == 2
    assert model.columnCount() == 4
    assert model.COLUMNS == ("Name / Label", "Source Bank", "Media ID", "Type")

    # Header check
    assert model.headerData(0, Qt.Orientation.Horizontal) == "Name / Label"
    assert model.headerData(1, Qt.Orientation.Horizontal) == "Source Bank"
    assert model.headerData(2, Qt.Orientation.Horizontal) == "Media ID"
    assert model.headerData(3, Qt.Orientation.Horizontal) == "Type"

    # Row 0 data
    idx0_name = model.index(0, 0)
    idx0_bank = model.index(0, 1)
    idx0_id = model.index(0, 2)
    idx0_type = model.index(0, 3)

    assert model.data(idx0_name, Qt.ItemDataRole.DisplayRole) == "Voice_Charge_01"
    assert model.data(idx0_bank, Qt.ItemDataRole.DisplayRole) == "unit_voice.bnk"
    assert model.data(idx0_id, Qt.ItemDataRole.DisplayRole) == "101"
    assert model.data(idx0_type, Qt.ItemDataRole.DisplayRole) == "Embedded"
    assert model.data(idx0_name, Qt.ItemDataRole.UserRole) == sample_entries[0]

    # Row 1 data (streamed)
    idx1_type = model.index(1, 3)
    assert model.data(idx1_type, Qt.ItemDataRole.DisplayRole) == "Streamed"

    # Out of bounds
    assert model.data(model.index(99, 0), Qt.ItemDataRole.DisplayRole) is None
    assert model.entry_at(99) is None
    assert model.entry_at(1) == sample_entries[1]


def test_catalog_table_model_set_entries():
    model = AudioCatalogTableModel()
    assert model.rowCount() == 0

    new_entries = (
        AudioCatalogEntry(
            wem_id=303,
            source_bank="music.bnk",
            is_embedded=False,
            display_name="Track_Intro",
            category="Music",
        ),
    )
    model.set_entries(new_entries)
    assert model.rowCount() == 1
    assert model.entry_at(0) == new_entries[0]


def test_catalog_table_view_integration(qtbot, sample_entries):
    view = AudioCatalogTableView()
    qtbot.addWidget(view)

    view.catalog_model.set_entries(sample_entries)
    assert view.rowCount() == 2
    assert view.selected_entry() is None

    # Select row 1
    view.selectRow(1)
    assert view.selected_entry() == sample_entries[1]

    # Reset entries
    view.catalog_model.set_entries(())
    assert view.rowCount() == 0
    assert view.selected_entry() is None


# ==============================================================================
# 3. Column Visibility, Provenance Styling, and Tooltips
# ==============================================================================


def test_catalog_table_model_visible_columns_and_provenance(extended_entries):
    all_cols = tuple(s.id for s in CATALOG_COLUMN_SPECS)
    model = AudioCatalogTableModel(extended_entries, visible_columns=all_cols)
    assert model.columnCount() == 6
    assert model.COLUMNS == (
        "Name / Label",
        "Source Bank",
        "Media ID",
        "Type",
        "Duration",
        "Category",
    )

    # Standard column (NAME, index 0): no heuristic foreground or tooltip
    idx_name = model.index(0, 0)
    assert model.data(idx_name, Qt.ItemDataRole.ForegroundRole) is None
    assert model.data(idx_name, Qt.ItemDataRole.ToolTipRole) is None

    # Heuristic column (CATEGORY, index 5): muted foreground color and tooltip
    idx_cat = model.index(0, 5)
    assert model.data(idx_cat, Qt.ItemDataRole.DisplayRole) == "Voiceover"
    fg_brush = model.data(idx_cat, Qt.ItemDataRole.ForegroundRole)
    assert isinstance(fg_brush, QBrush)
    assert fg_brush.color() == QColor(COLOR_TEXT_MUTED)
    assert model.data(idx_cat, Qt.ItemDataRole.ToolTipRole) == "Inferred (heuristic)"

    # Duration column (index 4)
    idx_dur0 = model.index(0, 4)
    assert model.data(idx_dur0, Qt.ItemDataRole.DisplayRole) == "45.23s"
    idx_dur1 = model.index(1, 4)
    # Entry 1 has duration_ms=0.0 and no resolver
    assert model.data(idx_dur1, Qt.ItemDataRole.DisplayRole) == ""
    idx_dur2 = model.index(2, 4)
    assert model.data(idx_dur2, Qt.ItemDataRole.DisplayRole) == "2:00"


def test_catalog_table_model_duration_resolver(sample_entries):
    all_cols = tuple(s.id for s in CATALOG_COLUMN_SPECS)

    def fake_resolver(wem_id: int) -> float | None:
        if wem_id == 202:
            return 3500.0  # 3.5s
        return None

    model = AudioCatalogTableModel(
        sample_entries, visible_columns=all_cols, duration_resolver=fake_resolver
    )

    # Entry 1 (wem_id 202) had 0.0, but fake_resolver resolves 3500.0
    idx1_dur = model.index(1, 4)
    assert model.data(idx1_dur, Qt.ItemDataRole.DisplayRole) == "3.50s"
    assert model._duration_cache.get(202) == 3500.0


# ==============================================================================
# 4. Sorting
# ==============================================================================


def test_catalog_table_model_sorting(extended_entries):
    all_cols = tuple(s.id for s in CATALOG_COLUMN_SPECS)
    model = AudioCatalogTableModel(extended_entries, visible_columns=all_cols)

    # Sort by Name (col 0) Ascending: Sword_Clash_Heavy, Voice_Charge_01, Wind_Breeze_Loop
    model.sort(0, Qt.SortOrder.AscendingOrder)
    assert model.entry_at(0).display_name == "Sword_Clash_Heavy"
    assert model.entry_at(1).display_name == "Voice_Charge_01"
    assert model.entry_at(2).display_name == "Wind_Breeze_Loop"

    # Sort by Name (col 0) Descending
    model.sort(0, Qt.SortOrder.DescendingOrder)
    assert model.entry_at(0).display_name == "Wind_Breeze_Loop"
    assert model.entry_at(1).display_name == "Voice_Charge_01"
    assert model.entry_at(2).display_name == "Sword_Clash_Heavy"

    # Sort by Media ID (col 2) Ascending: 101, 202, 303
    model.sort(2, Qt.SortOrder.AscendingOrder)
    assert model.entry_at(0).wem_id == 101
    assert model.entry_at(1).wem_id == 202
    assert model.entry_at(2).wem_id == 303

    # Sort by Media ID (col 2) Descending: 303, 202, 101
    model.sort(2, Qt.SortOrder.DescendingOrder)
    assert model.entry_at(0).wem_id == 303
    assert model.entry_at(2).wem_id == 101

    # Sort by Duration (col 4) Ascending: 0.0 (entry 202), 45230.0 (entry 101), 120000.0 (entry 303)
    model.sort(4, Qt.SortOrder.AscendingOrder)
    assert model.entry_at(0).wem_id == 202
    assert model.entry_at(1).wem_id == 101
    assert model.entry_at(2).wem_id == 303

    # Sort by Category (col 5) Ascending: Ambient, Battle, Voiceover
    model.sort(5, Qt.SortOrder.AscendingOrder)
    assert model.entry_at(0).category == "Ambient"
    assert model.entry_at(1).category == "Battle"
    assert model.entry_at(2).category == "Voiceover"


# ==============================================================================
# 5. Table View Columns and Header Context Menu
# ==============================================================================


def test_catalog_table_view_columns_customization(qtbot, sample_entries):
    view = AudioCatalogTableView()
    qtbot.addWidget(view)

    view.catalog_model.set_entries(sample_entries)
    assert view.rowCount() == 2
    assert view.visible_columns == DEFAULT_VISIBLE_CATALOG_COLUMNS

    # Toggle Duration column on view
    changed_signal_received: list[tuple[CatalogColumn, ...]] = []
    view.columns_changed.connect(changed_signal_received.append)

    view.set_column_visible(CatalogColumn.DURATION, True)
    assert CatalogColumn.DURATION in view.visible_columns
    assert len(changed_signal_received) == 1
    assert CatalogColumn.DURATION in changed_signal_received[0]
    assert view.catalog_model.columnCount() == 5

    # Context menu creation
    menu = view.create_columns_menu()
    actions = {act.text(): act for act in menu.actions()}
    assert "Duration" in actions
    assert actions["Duration"].isChecked()
    assert actions["Name / Label"].isEnabled() is False  # Non-hideable


def test_catalog_table_view_sorting(qtbot, extended_entries):
    view = AudioCatalogTableView()
    qtbot.addWidget(view)
    view.catalog_model.set_entries(extended_entries)

    # Sort by column 0 (Name) ascending via table view
    view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
    assert view.catalog_model.entry_at(0).display_name == "Sword_Clash_Heavy"

    # Sort by column 0 (Name) descending
    view.sortByColumn(0, Qt.SortOrder.DescendingOrder)
    assert view.catalog_model.entry_at(0).display_name == "Wind_Breeze_Loop"


# ==============================================================================
# 6. GameAudioTab Columns Button and Filtering
# ==============================================================================


def test_game_audio_tab_columns_and_actions(qtbot, extended_entries):
    tab = GameAudioTab()
    qtbot.addWidget(tab)
    tab.set_entries(extended_entries)

    assert tab.visible_columns == DEFAULT_VISIBLE_CATALOG_COLUMNS

    # Toggle Category visible via tab method
    tab.set_column_visible(CatalogColumn.CATEGORY, True)
    assert CatalogColumn.CATEGORY in tab.visible_columns
    assert tab._column_actions[CatalogColumn.CATEGORY].isChecked()

    # Search filter includes category even when searched
    tab.edit_search.setText("battle")
    assert tab.table.rowCount() == 1
    assert tab.lbl_count.text() == "1 entries"
    assert tab.table.catalog_model.entry_at(0).category == "Battle"

    tab.edit_search.setText("")
    assert tab.table.rowCount() == 3


# ==============================================================================
# 7. Engine WEM Duration Resolution
# ==============================================================================


def test_resolve_wem_duration_ms(tmp_path):
    assert resolve_wem_duration_ms(1234, None) is None

    class DummyResolver:
        def __init__(self, path=None, raw_bytes=None):
            self.path = path
            self.raw_bytes = raw_bytes

        def resolve_wem_path(self, wem_id: int):
            return self.path

        def resolve_wem_bytes(self, wem_id: int):
            return self.raw_bytes

    empty_resolver = DummyResolver()
    assert resolve_wem_duration_ms(1234, empty_resolver) is None

    # Create dummy loose WEM file with valid PCM format chunk
    fake_wem = tmp_path / "1234.wem"
    import struct

    data_bytes = b"\x00" * 64000  # 1 second of audio at 32kHz 16-bit mono
    fmt_payload = struct.pack("<HHIIHH", 1, 1, 32000, 64000, 2, 16)
    riff_data = (
        b"RIFF"
        + struct.pack("<I", 36 + len(data_bytes))
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt_payload))
        + fmt_payload
        + b"data"
        + struct.pack("<I", len(data_bytes))
        + data_bytes
    )
    fake_wem.write_bytes(riff_data)

    file_resolver = DummyResolver(path=fake_wem)
    duration = resolve_wem_duration_ms(1234, file_resolver)
    assert duration is not None
    assert pytest.approx(duration, rel=1e-2) == 1000.0


# ==============================================================================
# 8. MainWindow Settings Persistence Round-Trip
# ==============================================================================


def test_main_window_audio_sources_columns_persistence(qtbot, tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr("src.ui.shell.view._resolve_settings_file_path", lambda: settings_file)

    win = MainWindow()
    qtbot.addWidget(win)

    # Default columns
    assert win.audio_sources_view.tab_game_audio.visible_columns == DEFAULT_VISIBLE_CATALOG_COLUMNS

    # Customize columns: add Duration and Category
    custom_cols = (
        CatalogColumn.NAME,
        CatalogColumn.MEDIA_ID,
        CatalogColumn.DURATION,
        CatalogColumn.CATEGORY,
    )
    win.audio_sources_view.tab_game_audio.set_visible_columns(custom_cols)
    assert win.audio_sources_view.tab_game_audio.visible_columns == (
        CatalogColumn.NAME,
        CatalogColumn.MEDIA_ID,
        CatalogColumn.DURATION,
        CatalogColumn.CATEGORY,
    )

    # Trigger save
    win._save_ui_layout()
    assert settings_file.is_file()
    saved_data = json.loads(settings_file.read_text(encoding="utf-8"))
    assert "audio_sources" in saved_data
    assert saved_data["audio_sources"]["game_audio_columns"] == [c.value for c in custom_cols]

    # Create new window and verify layout is restored
    win2 = MainWindow()
    qtbot.addWidget(win2)
    assert win2.audio_sources_view.tab_game_audio.visible_columns == custom_cols
