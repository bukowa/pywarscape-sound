from PySide6.QtWidgets import QApplication

from src.ui.features.bank_viewer.inspector_panel import InspectorPanel
from src.ui.features.bank_viewer.state import (
    InspectorViewType,
    NodeInspectorDetails,
    NodeReferenceSummary,
)


def test_inspector_panel_host_switches_stack(qapp: QApplication):
    panel = InspectorPanel()

    sound_det = NodeInspectorDetails(
        node_key="hirc:100",
        name="Sound_100",
        object_type="Sound",
        view_type=InspectorViewType.SOUND,
        object_id=100,
        hex_id="0x00000064",
    )
    panel.render_details(sound_det)
    assert panel.active_view_type == InspectorViewType.SOUND

    media_det = NodeInspectorDetails(
        node_key="media:500",
        name="WEM 500",
        object_type="Embedded Media",
        view_type=InspectorViewType.MEDIA,
        object_id=500,
        hex_id="0x000001F4",
    )
    panel.render_details(media_det)
    assert panel.active_view_type == InspectorViewType.MEDIA


def test_inspector_panel_emits_jump(qapp: QApplication):
    panel = InspectorPanel()
    jump_key = None

    panel.jump_requested.connect(lambda k: nonlocal_jump(k))

    def nonlocal_jump(k):
        nonlocal jump_key
        jump_key = k

    # Ensure header has type badge and id label without nav buttons
    assert hasattr(panel, "type_badge")
    assert hasattr(panel, "id_lbl")
    assert not hasattr(panel, "btn_nav_back")
    assert not hasattr(panel, "btn_nav_forward")

    # Test jump via reference combo box
    det_with_parents = NodeInspectorDetails(
        node_key="hirc:200",
        name="Sound_200",
        object_type="Sound",
        view_type=InspectorViewType.SOUND,
        object_id=200,
        hex_id="0x000000C8",
        parent_references=(
            NodeReferenceSummary(
                key="hirc:10", label="Container_10", id_str="10", type_str="RanSeqCntr"
            ),
        ),
    )
    panel.render_details(det_with_parents)
    assert panel.combo_parents.count() == 2  # Placeholder + 1 reference
    # Activate reference item (index 1)
    panel.combo_parents.setCurrentIndex(1)
    assert jump_key == "hirc:10"
