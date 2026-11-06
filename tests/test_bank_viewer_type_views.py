from PySide6.QtWidgets import QApplication

from src.ui.features.bank_viewer.state import (
    InspectorProperty,
    InspectorViewType,
    NodeInspectorDetails,
    NodeReferenceSummary,
)
from src.ui.features.bank_viewer.views.container_view import ContainerInspectorView
from src.ui.features.bank_viewer.views.default_view import DefaultInspectorView
from src.ui.features.bank_viewer.views.event_action_view import EventActionInspectorView
from src.ui.features.bank_viewer.views.media_view import MediaInspectorView
from src.ui.features.bank_viewer.views.music_view import MusicInspectorView
from src.ui.features.bank_viewer.views.sound_view import SoundInspectorView


def test_all_type_views_render_and_clear_cleanly(qapp: QApplication):
    views = [
        DefaultInspectorView(),
        SoundInspectorView(),
        MediaInspectorView(),
        ContainerInspectorView(),
        EventActionInspectorView(),
        MusicInspectorView(),
    ]
    details = NodeInspectorDetails(
        node_key="hirc:100",
        name="Test Node",
        object_type="Sound",
        view_type=InspectorViewType.SOUND,
        object_id=100,
        hex_id="0x00000064",
        properties=(
            InspectorProperty(
                category="Audio Source", label="Stream Type", value="Streamed (External)"
            ),
            InspectorProperty(category="Audio Source", label="Source Media ID", value="500"),
            InspectorProperty(category="Routing", label="Output Bus ID", value="200"),
            InspectorProperty(category="Parameters", label="Priority", value="50"),
        ),
        parent_references=(
            NodeReferenceSummary(
                key="hirc:10", label="Container_10", id_str="10", type_str="RanSeqCntr"
            ),
        ),
        child_references=(
            NodeReferenceSummary(key="hirc:20", label="Child_20", id_str="20", type_str="Sound"),
        ),
    )
    for v in views:
        assert hasattr(v, "jump_requested")
        v.render(details)
        # Verify signal blocking preserved and no exceptions
        v.render(None)


def test_views_emit_jump_requested(qapp: QApplication):
    media_v = MediaInspectorView()
    jump_key = None
    media_v.jump_requested.connect(lambda k: nonlocal_assign(k))

    def nonlocal_assign(k):
        nonlocal jump_key
        jump_key = k

    details = NodeInspectorDetails(
        node_key="media:5001",
        name="WEM 5001",
        object_type="Embedded Media",
        view_type=InspectorViewType.MEDIA,
        object_id=5001,
        hex_id="0x00001389",
        properties=(),
        parent_references=(
            NodeReferenceSummary(key="hirc:101", label="Sound_101", id_str="101", type_str="Sound"),
        ),
    )
    media_v.render(details)
    assert media_v.ref_table.rowCount() == 1
    # Trigger cell double click on referencing sound
    media_v.ref_table.cellDoubleClicked.emit(0, 0)
    assert jump_key == "hirc:101"


def test_container_view_renders_switch_semantics(qapp: QApplication):
    from src.ui.features.bank_viewer.state import SwitchContainerSemantics, SwitchRouteEntry

    cntr_v = ContainerInspectorView()
    jump_key = None
    cntr_v.jump_requested.connect(lambda k: nonlocal_assign(k))

    def nonlocal_assign(k):
        nonlocal jump_key
        jump_key = k

    details = NodeInspectorDetails(
        node_key="hirc:648180848",
        name="SwitchCntr_648180848",
        object_type="SwitchCntr",
        view_type=InspectorViewType.CONTAINER,
        object_id=648180848,
        hex_id="0x26A27470",
        properties=(),
        child_references=(
            NodeReferenceSummary(
                key="hirc:20236167",
                label="LayerCntr_20236167",
                id_str="20236167",
                type_str="LayerCntr",
            ),
            NodeReferenceSummary(
                key="hirc:71115871",
                label="LayerCntr_71115871",
                id_str="71115871",
                type_str="LayerCntr",
            ),
            NodeReferenceSummary(
                key="hirc:1044587686",
                label="LayerCntr_1044587686",
                id_str="1044587686",
                type_str="LayerCntr",
            ),
        ),
        switch_semantics=SwitchContainerSemantics(
            group_id=2520241501,
            group_name="rain_intensity",
            group_type=0,
            default_switch_id=2849147824,
            default_switch_name="medium",
            routes=(
                SwitchRouteEntry(
                    switch_id=1935470627,
                    switch_name="light",
                    target_key="hirc:20236167",
                    target_id=20236167,
                    target_name="LayerCntr_20236167",
                    target_type="LayerCntr",
                    is_default=False,
                ),
                SwitchRouteEntry(
                    switch_id=2849147824,
                    switch_name="medium",
                    target_key="hirc:71115871",
                    target_id=71115871,
                    target_name="LayerCntr_71115871",
                    target_type="LayerCntr",
                    is_default=True,
                ),
                SwitchRouteEntry(
                    switch_id=2732489590,
                    switch_name="heavy",
                    target_key="hirc:1044587686",
                    target_id=1044587686,
                    target_name="LayerCntr_1044587686",
                    target_type="LayerCntr",
                    is_default=False,
                ),
                SwitchRouteEntry(
                    switch_id=748895195,
                    switch_name="none",
                    target_key="hirc:71115871",
                    target_id=71115871,
                    target_name="LayerCntr_71115871",
                    target_type="LayerCntr",
                    is_default=False,
                ),
            ),
        ),
    )

    cntr_v.render(details)

    assert not cntr_v.routing_table.isHidden()
    assert cntr_v.routing_table.rowCount() == 4
    assert cntr_v.child_table.rowCount() == 3
    assert "rain_intensity" in cntr_v.lbl_primary.text()
    assert "medium" in cntr_v.lbl_secondary.text()

    # Test double-click jump from routing table (row 1: medium -> 71115871)
    cntr_v.routing_table.cellDoubleClicked.emit(1, 0)
    assert jump_key == "hirc:71115871"

    # Test double-click jump from direct children table (row 0: 20236167)
    cntr_v.child_table.cellDoubleClicked.emit(0, 0)
    assert jump_key == "hirc:20236167"


def test_container_view_renders_ran_seq_semantics(qapp: QApplication):
    from src.ui.features.bank_viewer.state import PlaylistItemEntry, RanSeqContainerSemantics

    cntr_v = ContainerInspectorView()
    jump_key = None
    cntr_v.jump_requested.connect(lambda k: nonlocal_assign(k))

    def nonlocal_assign(k):
        nonlocal jump_key
        jump_key = k

    details = NodeInspectorDetails(
        node_key="hirc:9001",
        name="RanSeqCntr_9001",
        object_type="RanSeqCntr",
        view_type=InspectorViewType.CONTAINER,
        object_id=9001,
        hex_id="0x00002329",
        properties=(),
        child_references=(
            NodeReferenceSummary(key="hirc:101", label="Sound_101", id_str="101", type_str="Sound"),
        ),
        ran_seq_semantics=RanSeqContainerSemantics(
            mode_str="Random (Shuffle)",
            loop_count=1,
            transition_time_ms=500.0,
            avoid_repeat_count=2,
            playlist=(
                PlaylistItemEntry(
                    index=1,
                    play_id=101,
                    target_key="hirc:101",
                    target_name="Sound_101",
                    target_type="Sound",
                    weight=100,
                    weight_percent=100.0,
                ),
            ),
        ),
    )

    cntr_v.render(details)
    assert not cntr_v.routing_table.isHidden()
    assert cntr_v.routing_table.rowCount() == 1
    assert "Shuffle" in cntr_v.lbl_primary.text()

    cntr_v.routing_table.cellDoubleClicked.emit(0, 0)
    assert jump_key == "hirc:101"
