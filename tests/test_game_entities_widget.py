"""Tests for GameEntitiesWidget, GameEntitiesTableModel, and InspectorPanel integration."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.ui.features.bank_viewer.inspector_panel import InspectorPanel
from src.ui.features.bank_viewer.state import (
    GameEntitiesSection,
    GameEntityEntry,
    NodeInspectorDetails,
)
from src.ui.features.bank_viewer.views.game_entities_widget import (
    GameEntitiesTableModel,
    GameEntitiesWidget,
)


def _get_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_game_entities_table_model_units() -> None:
    _get_app()
    model = GameEntitiesTableModel()
    entries = (
        GameEntityEntry(key="att_alan_swordsmen", category="inf_mel", unit_class="melee_inf"),
        GameEntityEntry(key="att_alan_cavalry", category="cav_mel", unit_class="melee_cav"),
        GameEntityEntry(key="att_hunn_horse_archers", category="cav_mis", unit_class="missile_cav"),
    )
    model.set_data(entries, "units")

    assert model.rowCount() == 3
    assert model.columnCount() == 3
    assert model.headerData(0, Qt.Orientation.Horizontal) == "Unit Key"
    assert model.headerData(1, Qt.Orientation.Horizontal) == "Category"
    assert model.headerData(2, Qt.Orientation.Horizontal) == "Class"

    idx00 = model.index(0, 0)
    idx01 = model.index(0, 1)
    idx02 = model.index(0, 2)
    assert model.data(idx00) == "att_alan_swordsmen"
    assert model.data(idx01) == "inf_mel"
    assert model.data(idx02) == "melee_inf"

    # Test filtering
    model.set_filter("cavalry")
    assert model.rowCount() == 1
    assert model.data(model.index(0, 0)) == "att_alan_cavalry"

    model.set_filter("cav")  # Matches category cav_mel and cav_mis
    assert model.rowCount() == 2

    model.set_filter("nonexistent")
    assert model.rowCount() == 0

    model.set_filter("")  # Reset
    assert model.rowCount() == 3


def test_game_entities_table_model_projectiles() -> None:
    _get_app()
    model = GameEntitiesTableModel()
    entries = (
        GameEntityEntry(key="att_arrow_fire", extra="fire=Play_missile_fire_arrow"),
        GameEntityEntry(key="att_ballista_bolt", extra="impact=Play_impact_ballista"),
    )
    model.set_data(entries, "projectiles")

    assert model.rowCount() == 2
    assert model.columnCount() == 2
    assert model.headerData(0, Qt.Orientation.Horizontal) == "Entity Key"
    assert model.headerData(1, Qt.Orientation.Horizontal) == "Details"

    assert model.data(model.index(0, 0)) == "att_arrow_fire"
    assert model.data(model.index(0, 1)) == "fire=Play_missile_fire_arrow"


def test_game_entities_widget_lifecycle() -> None:
    _get_app()
    widget = GameEntitiesWidget()
    assert not widget.isVisible()

    entries = (
        GameEntityEntry(key="att_alan_swordsmen", category="inf_mel", unit_class="melee_inf"),
        GameEntityEntry(key="att_alan_cavalry", category="cav_mel", unit_class="melee_cav"),
    )
    section = GameEntitiesSection(
        entity_type="units",
        entries=entries,
        total_count=2,
    )
    widget.render(section)

    assert widget.isVisible()
    assert "2 units" in widget.btn_toggle.text()
    assert widget.model.rowCount() == 2
    assert "2 items" in widget.lbl_count.text()

    # Filter interaction
    widget.edit_filter.setText("sword")
    assert widget.model.rowCount() == 1
    assert "1 of 2" in widget.lbl_count.text()

    # Toggle collapse
    assert widget.content_frame.isVisible()
    widget.btn_toggle.click()
    assert not widget.content_frame.isVisible()
    assert "▶" in widget.btn_toggle.text()

    widget.btn_toggle.click()
    assert widget.content_frame.isVisible()
    assert "▼" in widget.btn_toggle.text()

    # Render None hides widget
    widget.render(None)
    assert not widget.isVisible()


def test_inspector_panel_renders_game_entities() -> None:
    _get_app()
    panel = InspectorPanel()
    panel.show()

    entries = (
        GameEntityEntry(key="att_alan_swordsmen", category="inf_mel", unit_class="melee_inf"),
    )
    section = GameEntitiesSection(
        entity_type="units",
        entries=entries,
        total_count=1,
    )
    details = NodeInspectorDetails(
        node_key="hirc:182034529",
        name="selected_inf_melee [Units]",
        object_type="RanSeqCntr",
        game_entities=section,
    )

    panel.render_details(details)
    assert not panel.game_entities_widget.isHidden()
    assert panel.game_entities_widget.model.rowCount() == 1

    # Deselect node
    panel.render_details(None)
    assert panel.game_entities_widget.isHidden()
    panel.hide()


def test_builder_game_entities_section() -> None:
    from unittest.mock import MagicMock

    from src.engine.metadata_resolver import NodeMetadataInfo
    from src.models.metadata import UnitMetadata
    from src.ui.features.bank_viewer.builder import _build_game_entities_section

    mock_catalog = MagicMock()
    unit = UnitMetadata(
        key="att_alan_swordsmen",
        category="inf_mel",
        unit_class="melee_inf",
        selection_vo="selected_inf_melee",
    )
    mock_catalog.get_unit.side_effect = lambda k: unit if k == "att_alan_swordsmen" else None

    meta = NodeMetadataInfo(
        friendly_label="selected_inf_melee [Units]",
        category="Units",
        entity_names=("att_alan_swordsmen", "unknown_unit"),
    )

    section = _build_game_entities_section(meta, mock_catalog)
    assert section is not None
    assert section.entity_type == "units"
    assert section.total_count == 2
    assert section.entries[0].key == "att_alan_swordsmen"
    assert section.entries[0].category == "inf_mel"
    assert section.entries[0].unit_class == "melee_inf"
    assert section.entries[1].key == "unknown_unit"
    assert section.entries[1].category == ""
