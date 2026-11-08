"""Pure PySide6 data-driven host widget for property inspector and type views."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.ui.features.bank_viewer.state import InspectorViewType, NodeInspectorDetails
from src.ui.features.bank_viewer.views.container_view import ContainerInspectorView
from src.ui.features.bank_viewer.views.default_view import DefaultInspectorView
from src.ui.features.bank_viewer.views.event_action_view import EventActionInspectorView
from src.ui.features.bank_viewer.views.game_entities_widget import GameEntitiesWidget
from src.ui.features.bank_viewer.views.media_view import MediaInspectorView
from src.ui.features.bank_viewer.views.music_view import MusicInspectorView
from src.ui.features.bank_viewer.views.sound_view import SoundInspectorView
from src.ui.theme import (
    COLOR_ACCENT,
    COLOR_BG_DISABLED,
    COLOR_BG_INPUT,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
)

_ROLE_TARGET_KEY = Qt.ItemDataRole.UserRole + 1


class InspectorPanel(QWidget):
    """Host widget coordinating navigation controls, header metadata, and type-specific views."""

    navigate_back = Signal()
    navigate_forward = Signal()
    jump_requested = Signal(str)
    reference_media_requested = Signal(int, int)
    export_sound_requested = Signal(int)
    export_media_requested = Signal(int)
    revert_media_requested = Signal(int)
    node_params_changed = Signal(int, float, float)
    append_variation_requested = Signal(int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active_view_type: InspectorViewType = InspectorViewType.DEFAULT
        self._init_ui()

    @property
    def active_view_type(self) -> InspectorViewType:
        """Currently active view type in the stack."""
        return self._active_view_type

    @property
    def prop_table(self):
        """Property table accessor for active view or default fallback."""
        curr = self.view_stack.currentWidget()
        if hasattr(curr, "prop_table"):
            return curr.prop_table
        return self.default_view.prop_table

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # 1. Header Card
        self.header_card = QFrame()
        self.header_card.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_PANEL}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; padding: 6px; }}"
        )
        card_layout = QVBoxLayout(self.header_card)
        card_layout.setContentsMargins(4, 4, 4, 4)
        card_layout.setSpacing(4)

        # Top row: Type badge + Object ID
        top_row = QHBoxLayout()
        top_row.setSpacing(4)

        self.type_badge = QLabel("NONE")
        self.type_badge.setStyleSheet(
            f"background-color: {COLOR_ACCENT}; color: {COLOR_TEXT_PRIMARY}; "
            f"font-size: 10px; font-weight: bold; border-radius: 3px; padding: 2px 6px;"
        )
        top_row.addWidget(self.type_badge)
        top_row.addStretch()

        self.id_lbl = QLabel("")
        self.id_lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        top_row.addWidget(self.id_lbl)
        card_layout.addLayout(top_row)

        # Second row: Name / Resolved Label
        self.name_lbl = QLabel("No object selected")
        self.name_lbl.setStyleSheet(
            f"color: {COLOR_TEXT_PRIMARY}; font-size: 13px; font-weight: bold;"
        )
        self.name_lbl.setWordWrap(True)
        card_layout.addWidget(self.name_lbl)

        # Third row: Interactive Reference Jump Dropdowns
        ref_row = QHBoxLayout()
        ref_row.setSpacing(6)

        combo_style = (
            f"QComboBox {{ background-color: {COLOR_BG_INPUT}; color: {COLOR_TEXT_PRIMARY}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 3px; font-size: 11px; padding: 2px 6px; }} "
            f"QComboBox:disabled {{ color: {COLOR_TEXT_MUTED}; background-color: {COLOR_BG_DISABLED}; border: 1px solid {COLOR_BORDER}; }} "
            f"QComboBox QAbstractItemView {{ background-color: {COLOR_BG_PANEL}; color: {COLOR_TEXT_PRIMARY}; "
            f"selection-background-color: {COLOR_ACCENT}; border: 1px solid {COLOR_BORDER}; }}"
        )

        self.combo_parents = QComboBox()
        self.combo_parents.setStyleSheet(combo_style)
        self.combo_parents.addItem("Referenced By: None", "")
        self.combo_parents.setEnabled(False)
        self.combo_parents.currentIndexChanged.connect(self._on_parent_combo_changed)
        ref_row.addWidget(self.combo_parents, 1)

        self.combo_children = QComboBox()
        self.combo_children.setStyleSheet(combo_style)
        self.combo_children.addItem("Targets: None", "")
        self.combo_children.setEnabled(False)
        self.combo_children.currentIndexChanged.connect(self._on_child_combo_changed)
        ref_row.addWidget(self.combo_children, 1)

        card_layout.addLayout(ref_row)
        layout.addWidget(self.header_card)

        # 2. Type View Stack
        self.view_stack = QStackedWidget()

        self.default_view = DefaultInspectorView()
        self.sound_view = SoundInspectorView()
        self.media_view = MediaInspectorView()
        self.container_view = ContainerInspectorView()
        self.event_action_view = EventActionInspectorView()
        self.music_view = MusicInspectorView()

        # Connect sub-view jump requests
        for v in (
            self.default_view,
            self.sound_view,
            self.media_view,
            self.container_view,
            self.event_action_view,
            self.music_view,
        ):
            v.jump_requested.connect(self.jump_requested)

        self.sound_view.reference_media_requested.connect(self.reference_media_requested)
        self.sound_view.export_requested.connect(self.export_sound_requested)
        self.sound_view.node_params_changed.connect(self.node_params_changed)
        self.container_view.append_variation_requested.connect(self.append_variation_requested)
        self.music_view.export_requested.connect(self.export_sound_requested)

        self.media_view.export_requested.connect(self.export_media_requested)
        self.media_view.revert_requested.connect(self.revert_media_requested)

        self.view_stack.addWidget(self.default_view)  # Index 0
        self.view_stack.addWidget(self.sound_view)  # Index 1
        self.view_stack.addWidget(self.media_view)  # Index 2
        self.view_stack.addWidget(self.container_view)  # Index 3
        self.view_stack.addWidget(self.event_action_view)  # Index 4
        self.view_stack.addWidget(self.music_view)  # Index 5

        layout.addWidget(self.view_stack, 1)

        # 3. Game Entities Section (collapsible table for units, projectiles, etc.)
        self.game_entities_widget = GameEntitiesWidget()
        layout.addWidget(self.game_entities_widget)

    def _on_parent_combo_changed(self, index: int) -> None:
        if index > 0:
            target_key = self.combo_parents.itemData(index)
            if target_key:
                self.jump_requested.emit(target_key)
                self.combo_parents.blockSignals(True)
                self.combo_parents.setCurrentIndex(0)
                self.combo_parents.blockSignals(False)

    def _on_child_combo_changed(self, index: int) -> None:
        if index > 0:
            target_key = self.combo_children.itemData(index)
            if target_key:
                self.jump_requested.emit(target_key)
                self.combo_children.blockSignals(True)
                self.combo_children.setCurrentIndex(0)
                self.combo_children.blockSignals(False)

    def render_navigation_state(self, can_back: bool, can_forward: bool) -> None:
        """Retained for compatibility; navigation is now driven via Edit menu and mouse buttons."""
        pass

    def render_details(self, details: NodeInspectorDetails | None, selected_count: int = 1) -> None:
        """Projects node inspector details into UI controls with strict signal blocking."""
        if details is None:
            self.type_badge.setText("NONE")
            self.id_lbl.setText("")
            self.name_lbl.setText("Select an object in the hierarchy tree to inspect.")
            self._render_references((), ())
            self.view_stack.setCurrentWidget(self.default_view)
            self._active_view_type = InspectorViewType.DEFAULT
            self.default_view.render(None)
            self.game_entities_widget.render(None)
            return

        self.type_badge.setText(details.object_type.upper())
        id_text = (
            f"ID: {details.object_id} ({details.hex_id})" if details.object_id is not None else ""
        )
        self.id_lbl.setText(id_text)
        self.name_lbl.setText(details.name)

        # References dropdowns
        self._render_references(details.parent_references, details.child_references)

        # Switch stack widget based on view_type
        target_widget = self._get_widget_for_view_type(details.view_type)
        self.view_stack.setCurrentWidget(target_widget)
        self._active_view_type = details.view_type
        if isinstance(target_widget, (SoundInspectorView, MediaInspectorView)):
            target_widget.render(details, selected_count=selected_count)
        else:
            target_widget.render(details)

        # Render Game Entities collapsible section
        self.game_entities_widget.render(details.game_entities)

    def _get_widget_for_view_type(
        self, vtype: InspectorViewType
    ) -> (
        SoundInspectorView
        | MediaInspectorView
        | ContainerInspectorView
        | EventActionInspectorView
        | MusicInspectorView
        | DefaultInspectorView
    ):
        match vtype:
            case InspectorViewType.SOUND:
                return self.sound_view
            case InspectorViewType.MEDIA:
                return self.media_view
            case InspectorViewType.CONTAINER:
                return self.container_view
            case InspectorViewType.EVENT_ACTION:
                return self.event_action_view
            case InspectorViewType.MUSIC:
                return self.music_view
            case _:
                return self.default_view

    def _render_references(
        self,
        parent_refs: tuple,
        child_refs: tuple,
    ) -> None:
        # Parent references combo
        self.combo_parents.blockSignals(True)
        self.combo_parents.clear()
        p_len = len(parent_refs)
        if p_len == 0:
            self.combo_parents.addItem("Referenced By: None", "")
            self.combo_parents.setEnabled(False)
        else:
            self.combo_parents.addItem(f"Referenced By ({p_len})...", "")
            for ref in parent_refs:
                target_key = f"{ref.bank_name}::{ref.key}" if ref.bank_name else ref.key
                self.combo_parents.addItem(f"{ref.label} ({ref.type_str} {ref.id_str})", target_key)
            self.combo_parents.setEnabled(True)
        self.combo_parents.setCurrentIndex(0)
        self.combo_parents.blockSignals(False)

        # Child references combo
        self.combo_children.blockSignals(True)
        self.combo_children.clear()
        c_len = len(child_refs)
        if c_len == 0:
            self.combo_children.addItem("Targets: None", "")
            self.combo_children.setEnabled(False)
        else:
            self.combo_children.addItem(f"Targets ({c_len})...", "")
            for ref in child_refs:
                target_key = f"{ref.bank_name}::{ref.key}" if ref.bank_name else ref.key
                self.combo_children.addItem(
                    f"{ref.label} ({ref.type_str} {ref.id_str})", target_key
                )
            self.combo_children.setEnabled(True)
        self.combo_children.setCurrentIndex(0)
        self.combo_children.blockSignals(False)
