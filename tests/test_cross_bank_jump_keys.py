"""Tests verifying that all inspector views and header combos include bank_name
in jump keys so cross-bank navigation works correctly.

Bug: When a NodeReferenceSummary carries a bank_name (e.g. a WEM shared across
banks), the jump key emitted must be "bank_name::hirc:ID" so the causation
reducer triggers a cross-bank transition.  Without the prefix the reducer
defaults to the current bank and silently fails to navigate.

This file covers:
  1. InspectorPanel combo_parents and combo_children
  2. MediaInspectorView ref_table
  3. SoundInspectorView ref_table
  4. EventActionInspectorView targets_table
  5. MusicInspectorView tracks_table
  6. ContainerInspectorView child_table
  7. Causation reducer round-trip (JumpToNodeRequested with "::" prefix)
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.ui.features.bank_viewer.causation import reconcile_viewer
from src.ui.features.bank_viewer.inspector_panel import InspectorPanel
from src.ui.features.bank_viewer.state import (
    BankViewerState,
    InspectorProperty,
    InspectorViewType,
    JumpToNodeRequested,
    NodeInspectorDetails,
    NodeReferenceSummary,
)
from src.ui.features.bank_viewer.views.container_view import ContainerInspectorView
from src.ui.features.bank_viewer.views.event_action_view import EventActionInspectorView
from src.ui.features.bank_viewer.views.media_view import MediaInspectorView
from src.ui.features.bank_viewer.views.music_view import MusicInspectorView
from src.ui.features.bank_viewer.views.sound_view import SoundInspectorView

_ROLE_TARGET_KEY = Qt.ItemDataRole.UserRole + 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cross_bank_ref(key: str = "hirc:999", bank: str = "other.bnk") -> NodeReferenceSummary:
    """Factory for a cross-bank NodeReferenceSummary."""
    return NodeReferenceSummary(
        key=key,
        label="Sound_999",
        id_str="999",
        type_str="Sound",
        bank_name=bank,
    )


def _same_bank_ref(key: str = "hirc:100") -> NodeReferenceSummary:
    """Factory for a same-bank NodeReferenceSummary (empty bank_name)."""
    return NodeReferenceSummary(
        key=key,
        label="Sound_100",
        id_str="100",
        type_str="Sound",
        bank_name="",
    )


def _capture_jump(widget):
    """Connect jump_requested signal and return a mutable list that records emitted keys."""
    captured = []
    widget.jump_requested.connect(captured.append)
    return captured


# ===========================================================================
# 1. InspectorPanel combo boxes
# ===========================================================================


class TestInspectorPanelCrossBank:
    def test_combo_parents_emits_qualified_key_for_cross_bank_ref(self, qapp: QApplication):
        panel = InspectorPanel()
        captured = _capture_jump(panel)

        det = NodeInspectorDetails(
            node_key="media:5000",
            name="WEM 5000",
            object_type="Embedded Media",
            view_type=InspectorViewType.MEDIA,
            object_id=5000,
            hex_id="0x00001388",
            parent_references=(_cross_bank_ref("hirc:415", "battle.bnk"),),
        )
        panel.render_details(det)

        assert panel.combo_parents.count() == 2  # placeholder + 1 ref
        data = panel.combo_parents.itemData(1)
        assert data == "battle.bnk::hirc:415"

        # Selecting it should emit the qualified key
        panel.combo_parents.setCurrentIndex(1)
        assert captured == ["battle.bnk::hirc:415"]

    def test_combo_parents_emits_bare_key_when_no_bank_name(self, qapp: QApplication):
        panel = InspectorPanel()
        captured = _capture_jump(panel)

        det = NodeInspectorDetails(
            node_key="hirc:200",
            name="Sound_200",
            object_type="Sound",
            view_type=InspectorViewType.SOUND,
            object_id=200,
            hex_id="0x000000C8",
            parent_references=(_same_bank_ref("hirc:10"),),
        )
        panel.render_details(det)

        data = panel.combo_parents.itemData(1)
        assert data == "hirc:10"

        panel.combo_parents.setCurrentIndex(1)
        assert captured == ["hirc:10"]

    def test_combo_children_emits_qualified_key_for_cross_bank_ref(self, qapp: QApplication):
        panel = InspectorPanel()
        captured = _capture_jump(panel)

        det = NodeInspectorDetails(
            node_key="hirc:300",
            name="Event_300",
            object_type="Event",
            view_type=InspectorViewType.EVENT_ACTION,
            object_id=300,
            hex_id="0x0000012C",
            child_references=(_cross_bank_ref("hirc:777", "sfx.bnk"),),
        )
        panel.render_details(det)

        assert panel.combo_children.count() == 2
        data = panel.combo_children.itemData(1)
        assert data == "sfx.bnk::hirc:777"

        panel.combo_children.setCurrentIndex(1)
        assert captured == ["sfx.bnk::hirc:777"]

    def test_combo_children_emits_bare_key_when_no_bank_name(self, qapp: QApplication):
        panel = InspectorPanel()
        captured = _capture_jump(panel)

        det = NodeInspectorDetails(
            node_key="hirc:300",
            name="Event_300",
            object_type="Event",
            view_type=InspectorViewType.EVENT_ACTION,
            object_id=300,
            hex_id="0x0000012C",
            child_references=(_same_bank_ref("hirc:50"),),
        )
        panel.render_details(det)

        panel.combo_children.setCurrentIndex(1)
        assert captured == ["hirc:50"]

    def test_multiple_cross_bank_parent_refs(self, qapp: QApplication):
        panel = InspectorPanel()

        refs = (
            _cross_bank_ref("hirc:1", "bank_a.bnk"),
            _cross_bank_ref("hirc:2", "bank_b.bnk"),
            _same_bank_ref("hirc:3"),
        )
        det = NodeInspectorDetails(
            node_key="media:9000",
            name="WEM 9000",
            object_type="Embedded Media",
            view_type=InspectorViewType.MEDIA,
            object_id=9000,
            hex_id="0x00002328",
            parent_references=refs,
        )
        panel.render_details(det)

        assert panel.combo_parents.count() == 4  # placeholder + 3 refs
        assert panel.combo_parents.itemData(1) == "bank_a.bnk::hirc:1"
        assert panel.combo_parents.itemData(2) == "bank_b.bnk::hirc:2"
        assert panel.combo_parents.itemData(3) == "hirc:3"


# ===========================================================================
# 2. MediaInspectorView ref_table (already correct, regression guard)
# ===========================================================================


class TestMediaViewCrossBank:
    def test_ref_table_stores_qualified_jump_key(self, qapp: QApplication):
        view = MediaInspectorView()

        det = NodeInspectorDetails(
            node_key="media:6001",
            name="WEM 6001",
            object_type="Embedded Media",
            view_type=InspectorViewType.MEDIA,
            object_id=6001,
            hex_id="0x00001771",
            audio_references=(_cross_bank_ref("hirc:500", "battle.bnk"),),
            audio_reference_count=1,
        )
        view.render(det)

        assert view.ref_table.rowCount() == 1
        item = view.ref_table.item(0, 0)
        assert item.data(_ROLE_TARGET_KEY) == "battle.bnk::hirc:500"

    def test_ref_table_double_click_emits_qualified_key(self, qapp: QApplication):
        view = MediaInspectorView()
        captured = _capture_jump(view)

        det = NodeInspectorDetails(
            node_key="media:6001",
            name="WEM 6001",
            object_type="Embedded Media",
            view_type=InspectorViewType.MEDIA,
            object_id=6001,
            hex_id="0x00001771",
            audio_references=(_cross_bank_ref("hirc:500", "battle.bnk"),),
            audio_reference_count=1,
        )
        view.render(det)

        view.ref_table.cellDoubleClicked.emit(0, 0)
        assert captured == ["battle.bnk::hirc:500"]

    def test_ref_table_bare_key_when_no_bank(self, qapp: QApplication):
        view = MediaInspectorView()
        captured = _capture_jump(view)

        det = NodeInspectorDetails(
            node_key="media:6001",
            name="WEM 6001",
            object_type="Embedded Media",
            view_type=InspectorViewType.MEDIA,
            object_id=6001,
            hex_id="0x00001771",
            parent_references=(_same_bank_ref("hirc:101"),),
        )
        view.render(det)

        view.ref_table.cellDoubleClicked.emit(0, 0)
        assert captured == ["hirc:101"]

    def test_all_columns_carry_jump_key(self, qapp: QApplication):
        """Double-clicking any column should still yield the correct jump key."""
        view = MediaInspectorView()

        det = NodeInspectorDetails(
            node_key="media:6001",
            name="WEM 6001",
            object_type="Embedded Media",
            view_type=InspectorViewType.MEDIA,
            object_id=6001,
            hex_id="0x00001771",
            audio_references=(
                NodeReferenceSummary(
                    key="hirc:500",
                    label="Sound_500",
                    id_str="500",
                    type_str="Sound",
                    bank_name="battle.bnk",
                ),
            ),
            audio_reference_count=1,
        )
        view.render(det)

        for col in range(view.ref_table.columnCount()):
            item = view.ref_table.item(0, col)
            assert item is not None, f"Column {col} item is None"
            assert item.data(_ROLE_TARGET_KEY) == "battle.bnk::hirc:500", (
                f"Column {col} missing qualified jump key"
            )


# ===========================================================================
# 3. SoundInspectorView ref_table (already correct, regression guard)
# ===========================================================================


class TestSoundViewCrossBank:
    def test_ref_table_stores_qualified_jump_key(self, qapp: QApplication):
        view = SoundInspectorView()

        det = NodeInspectorDetails(
            node_key="hirc:301",
            name="Sound_301",
            object_type="Sound",
            view_type=InspectorViewType.SOUND,
            object_id=301,
            hex_id="0x0000012D",
            properties=(
                InspectorProperty(
                    category="Audio Source", label="Stream Type", value="Embedded (Bank)"
                ),
                InspectorProperty(category="Audio Source", label="Source Media ID", value="6001"),
            ),
            audio_references=(_cross_bank_ref("hirc:401", "music.bnk"),),
            audio_reference_count=1,
            is_streamed=False,
            source_wem_id=6001,
        )
        view.render(det)

        assert view.ref_table.rowCount() == 1
        item = view.ref_table.item(0, 0)
        assert item.data(_ROLE_TARGET_KEY) == "music.bnk::hirc:401"

    def test_ref_table_double_click_emits_qualified_key(self, qapp: QApplication):
        view = SoundInspectorView()
        captured = _capture_jump(view)

        det = NodeInspectorDetails(
            node_key="hirc:301",
            name="Sound_301",
            object_type="Sound",
            view_type=InspectorViewType.SOUND,
            object_id=301,
            hex_id="0x0000012D",
            properties=(
                InspectorProperty(
                    category="Audio Source", label="Stream Type", value="Embedded (Bank)"
                ),
                InspectorProperty(category="Audio Source", label="Source Media ID", value="6001"),
            ),
            audio_references=(_cross_bank_ref("hirc:401", "music.bnk"),),
            audio_reference_count=1,
            is_streamed=False,
            source_wem_id=6001,
        )
        view.render(det)

        view.ref_table.cellDoubleClicked.emit(0, 0)
        assert captured == ["music.bnk::hirc:401"]


# ===========================================================================
# 4. EventActionInspectorView targets_table
# ===========================================================================


class TestEventActionViewCrossBank:
    def test_targets_table_stores_qualified_jump_key(self, qapp: QApplication):
        view = EventActionInspectorView()

        det = NodeInspectorDetails(
            node_key="hirc:800",
            name="Event_800",
            object_type="Event",
            view_type=InspectorViewType.EVENT_ACTION,
            object_id=800,
            hex_id="0x00000320",
            child_references=(_cross_bank_ref("hirc:801", "sfx.bnk"),),
        )
        view.render(det)

        assert view.targets_table.rowCount() == 1
        item = view.targets_table.item(0, 0)
        assert item.data(_ROLE_TARGET_KEY) == "sfx.bnk::hirc:801"

    def test_targets_table_double_click_emits_qualified_key(self, qapp: QApplication):
        view = EventActionInspectorView()
        captured = _capture_jump(view)

        det = NodeInspectorDetails(
            node_key="hirc:800",
            name="Event_800",
            object_type="Event",
            view_type=InspectorViewType.EVENT_ACTION,
            object_id=800,
            hex_id="0x00000320",
            child_references=(_cross_bank_ref("hirc:801", "sfx.bnk"),),
        )
        view.render(det)

        view.targets_table.cellDoubleClicked.emit(0, 0)
        assert captured == ["sfx.bnk::hirc:801"]

    def test_targets_table_bare_key_when_no_bank(self, qapp: QApplication):
        view = EventActionInspectorView()
        captured = _capture_jump(view)

        det = NodeInspectorDetails(
            node_key="hirc:800",
            name="Event_800",
            object_type="Event",
            view_type=InspectorViewType.EVENT_ACTION,
            object_id=800,
            hex_id="0x00000320",
            child_references=(_same_bank_ref("hirc:801"),),
        )
        view.render(det)

        view.targets_table.cellDoubleClicked.emit(0, 0)
        assert captured == ["hirc:801"]

    def test_all_columns_carry_jump_key(self, qapp: QApplication):
        """All columns should store _ROLE_TARGET_KEY for robust navigation."""
        view = EventActionInspectorView()

        det = NodeInspectorDetails(
            node_key="hirc:800",
            name="Event_800",
            object_type="Event",
            view_type=InspectorViewType.EVENT_ACTION,
            object_id=800,
            hex_id="0x00000320",
            child_references=(_cross_bank_ref("hirc:801", "sfx.bnk"),),
        )
        view.render(det)

        for col in range(view.targets_table.columnCount()):
            item = view.targets_table.item(0, col)
            assert item is not None, f"Column {col} item is None"
            assert item.data(_ROLE_TARGET_KEY) == "sfx.bnk::hirc:801", (
                f"Column {col} missing qualified jump key"
            )


# ===========================================================================
# 5. MusicInspectorView tracks_table
# ===========================================================================


class TestMusicViewCrossBank:
    def test_tracks_table_stores_qualified_jump_key(self, qapp: QApplication):
        view = MusicInspectorView()

        det = NodeInspectorDetails(
            node_key="hirc:900",
            name="MusicSegment_900",
            object_type="MusicSegment",
            view_type=InspectorViewType.MUSIC,
            object_id=900,
            hex_id="0x00000384",
            child_references=(_cross_bank_ref("hirc:901", "music_data.bnk"),),
        )
        view.render(det)

        assert view.tracks_table.rowCount() == 1
        item = view.tracks_table.item(0, 0)
        assert item.data(_ROLE_TARGET_KEY) == "music_data.bnk::hirc:901"

    def test_tracks_table_double_click_emits_qualified_key(self, qapp: QApplication):
        view = MusicInspectorView()
        captured = _capture_jump(view)

        det = NodeInspectorDetails(
            node_key="hirc:900",
            name="MusicSegment_900",
            object_type="MusicSegment",
            view_type=InspectorViewType.MUSIC,
            object_id=900,
            hex_id="0x00000384",
            child_references=(_cross_bank_ref("hirc:901", "music_data.bnk"),),
        )
        view.render(det)

        view.tracks_table.cellDoubleClicked.emit(0, 0)
        assert captured == ["music_data.bnk::hirc:901"]

    def test_tracks_table_bare_key_when_no_bank(self, qapp: QApplication):
        view = MusicInspectorView()
        captured = _capture_jump(view)

        det = NodeInspectorDetails(
            node_key="hirc:900",
            name="MusicSegment_900",
            object_type="MusicSegment",
            view_type=InspectorViewType.MUSIC,
            object_id=900,
            hex_id="0x00000384",
            child_references=(_same_bank_ref("hirc:901"),),
        )
        view.render(det)

        view.tracks_table.cellDoubleClicked.emit(0, 0)
        assert captured == ["hirc:901"]

    def test_all_columns_carry_jump_key(self, qapp: QApplication):
        view = MusicInspectorView()

        det = NodeInspectorDetails(
            node_key="hirc:900",
            name="MusicSegment_900",
            object_type="MusicSegment",
            view_type=InspectorViewType.MUSIC,
            object_id=900,
            hex_id="0x00000384",
            child_references=(_cross_bank_ref("hirc:901", "music_data.bnk"),),
        )
        view.render(det)

        for col in range(view.tracks_table.columnCount()):
            item = view.tracks_table.item(0, col)
            assert item is not None, f"Column {col} item is None"
            assert item.data(_ROLE_TARGET_KEY) == "music_data.bnk::hirc:901", (
                f"Column {col} missing qualified jump key"
            )


# ===========================================================================
# 6. ContainerInspectorView child_table
# ===========================================================================


class TestContainerViewCrossBank:
    def test_child_table_stores_qualified_jump_key(self, qapp: QApplication):
        view = ContainerInspectorView()

        det = NodeInspectorDetails(
            node_key="hirc:400",
            name="RanSeqCntr_400",
            object_type="RanSeqCntr",
            view_type=InspectorViewType.CONTAINER,
            object_id=400,
            hex_id="0x00000190",
            child_references=(_cross_bank_ref("hirc:401", "ambient.bnk"),),
        )
        view.render(det)

        assert view.child_table.rowCount() == 1
        item = view.child_table.item(0, 0)
        assert item.data(_ROLE_TARGET_KEY) == "ambient.bnk::hirc:401"

    def test_child_table_double_click_emits_qualified_key(self, qapp: QApplication):
        view = ContainerInspectorView()
        captured = _capture_jump(view)

        det = NodeInspectorDetails(
            node_key="hirc:400",
            name="RanSeqCntr_400",
            object_type="RanSeqCntr",
            view_type=InspectorViewType.CONTAINER,
            object_id=400,
            hex_id="0x00000190",
            child_references=(_cross_bank_ref("hirc:401", "ambient.bnk"),),
        )
        view.render(det)

        view.child_table.cellDoubleClicked.emit(0, 0)
        assert captured == ["ambient.bnk::hirc:401"]

    def test_child_table_bare_key_when_no_bank(self, qapp: QApplication):
        view = ContainerInspectorView()
        captured = _capture_jump(view)

        det = NodeInspectorDetails(
            node_key="hirc:400",
            name="RanSeqCntr_400",
            object_type="RanSeqCntr",
            view_type=InspectorViewType.CONTAINER,
            object_id=400,
            hex_id="0x00000190",
            child_references=(_same_bank_ref("hirc:401"),),
        )
        view.render(det)

        view.child_table.cellDoubleClicked.emit(0, 0)
        assert captured == ["hirc:401"]

    def test_all_columns_carry_jump_key(self, qapp: QApplication):
        view = ContainerInspectorView()

        det = NodeInspectorDetails(
            node_key="hirc:400",
            name="RanSeqCntr_400",
            object_type="RanSeqCntr",
            view_type=InspectorViewType.CONTAINER,
            object_id=400,
            hex_id="0x00000190",
            child_references=(_cross_bank_ref("hirc:401", "ambient.bnk"),),
        )
        view.render(det)

        for col in range(view.child_table.columnCount()):
            item = view.child_table.item(0, col)
            assert item is not None, f"Column {col} item is None"
            assert item.data(_ROLE_TARGET_KEY) == "ambient.bnk::hirc:401", (
                f"Column {col} missing qualified jump key"
            )


# ===========================================================================
# 7. Causation reducer: JumpToNodeRequested with "::" prefix
# ===========================================================================


class TestCausationCrossBankJump:
    def test_jump_with_qualified_key_triggers_cross_bank_transition(self):
        """Simulates the full cycle: view emits 'bank.bnk::hirc:42', reducer splits it."""
        state = BankViewerState(selected_bank_name="current.bnk")

        # First select a node to populate history
        from src.ui.features.bank_viewer.state import NodeSelectionRequested

        s1, _ = reconcile_viewer(state, NodeSelectionRequested(node_key="hirc:1"))

        # Now jump with qualified key (as emitted by the fixed views)
        s2, intents = reconcile_viewer(s1, JumpToNodeRequested(node_key="other.bnk::hirc:42"))

        assert s2.selected_bank_name == "other.bnk"
        assert s2.selected_node_key == "hirc:42"
        assert s2.ensure_tree_visible is True
        # Should emit LoadBankIntent for the cross-bank target
        assert len(intents) >= 1
        from src.ui.features.bank_viewer.state import LoadBankIntent

        assert any(isinstance(i, LoadBankIntent) and i.bank_name == "other.bnk" for i in intents)

    def test_jump_with_bare_key_stays_in_current_bank(self):
        """Bare key without '::' should not trigger cross-bank transition."""
        state = BankViewerState(selected_bank_name="current.bnk")

        from src.ui.features.bank_viewer.state import NodeSelectionRequested

        s1, _ = reconcile_viewer(state, NodeSelectionRequested(node_key="hirc:1"))

        s2, intents = reconcile_viewer(s1, JumpToNodeRequested(node_key="hirc:42"))

        assert s2.selected_bank_name == "current.bnk"
        assert s2.selected_node_key == "hirc:42"
        assert s2.ensure_tree_visible is True
        # No LoadBankIntent for same-bank jump
        from src.ui.features.bank_viewer.state import LoadBankIntent

        assert not any(isinstance(i, LoadBankIntent) for i in intents)

    def test_jump_with_same_bank_qualified_key_stays_in_current_bank(self):
        """Qualified key pointing to same bank should NOT reload the bank."""
        state = BankViewerState(selected_bank_name="current.bnk")

        from src.ui.features.bank_viewer.state import NodeSelectionRequested

        s1, _ = reconcile_viewer(state, NodeSelectionRequested(node_key="hirc:1"))

        s2, intents = reconcile_viewer(s1, JumpToNodeRequested(node_key="current.bnk::hirc:42"))

        assert s2.selected_bank_name == "current.bnk"
        assert s2.selected_node_key == "hirc:42"
        from src.ui.features.bank_viewer.state import LoadBankIntent

        assert not any(isinstance(i, LoadBankIntent) for i in intents)
