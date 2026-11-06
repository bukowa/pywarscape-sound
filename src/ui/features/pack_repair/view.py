"""PySide6 dialog view for the Pack Health Repair feature slice."""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.ui.features.pack_repair.state import PackRepairState, RepairItemState
from src.ui.features.pack_repair.store import PackRepairStore
from src.ui.theme import (
    BTN_STYLE_PRIMARY,
    BTN_STYLE_SECONDARY,
    CHECKBOX_STYLE,
    COLOR_ACCENT,
    COLOR_BG_BASE,
    COLOR_BG_INPUT,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_SUCCESS,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
)
from src.workspace.health import IssueSeverity


class PackRepairDialog(QDialog):
    """Data-driven modal dialog presenting diagnostic defects and repair options."""

    def __init__(self, store: PackRepairStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._checkbox_by_id: dict[str, QCheckBox] = {}

        self.setWindowTitle(f"Pack Health Repair — {self.store.state.pack_name}")
        self.setMinimumWidth(580)
        self.setMinimumHeight(440)
        self.setStyleSheet(
            f"QDialog {{ background-color: {COLOR_BG_BASE}; color: {COLOR_TEXT_PRIMARY}; }}"
        )

        self._init_ui()
        self.store.subscribe(self.render)
        self.render(self.store.state)
        self.setVisible(True)

    def _init_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(12)

        # Header section
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)

        self.title_label = QLabel("Pack Health Diagnostic")
        self.title_label.setStyleSheet(
            f"QLabel {{ color: {COLOR_TEXT_PRIMARY}; font-size: 16px; font-weight: 700; border: none; }}"
        )
        header_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel()
        self.subtitle_label.setStyleSheet(
            f"QLabel {{ color: {COLOR_TEXT_SECONDARY}; font-size: 12px; border: none; }}"
        )
        header_layout.addWidget(self.subtitle_label)

        root_layout.addLayout(header_layout)

        # Scrollable items area
        scroll_area = QScrollArea()
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(
            f"QScrollArea {{ background-color: {COLOR_BG_BASE}; border: none; }}"
        )

        items_container = QWidget()
        items_container.setStyleSheet(f"QWidget {{ background-color: {COLOR_BG_BASE}; }}")
        self.items_layout = QVBoxLayout(items_container)
        self.items_layout.setContentsMargins(0, 0, 0, 0)
        self.items_layout.setSpacing(8)

        for item in self.store.state.items:
            card = self._build_item_card(item)
            self.items_layout.addWidget(card)

        self.items_layout.addStretch(1)
        scroll_area.setWidget(items_container)
        root_layout.addWidget(scroll_area, 1)

        # Footer action buttons
        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(10)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet(BTN_STYLE_SECONDARY)
        self.cancel_button.clicked.connect(self.reject)
        footer_layout.addWidget(self.cancel_button)

        self.ignore_button = QPushButton("Ignore & Proceed")
        self.ignore_button.setStyleSheet(BTN_STYLE_SECONDARY)
        self.ignore_button.clicked.connect(self._on_ignore_clicked)
        footer_layout.addWidget(self.ignore_button)

        footer_layout.addStretch(1)

        self.fix_button = QPushButton("Auto-Fix & Continue")
        self.fix_button.setStyleSheet(BTN_STYLE_PRIMARY)
        self.fix_button.clicked.connect(self._on_fix_clicked)
        footer_layout.addWidget(self.fix_button)

        root_layout.addLayout(footer_layout)

    def _build_item_card(self, item: RepairItemState) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_PANEL}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 6px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(6)

        # Top row: Checkbox with title and severity badge
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        cb = QCheckBox(item.title)
        cb.setObjectName(f"cb_{item.issue_id}")
        cb.setStyleSheet(CHECKBOX_STYLE)
        cb.setChecked(item.is_selected)
        cb.setEnabled(item.can_autofix)
        cb.toggled.connect(lambda checked, i_id=item.issue_id: self.store.toggle_item(i_id))
        self._checkbox_by_id[item.issue_id] = cb
        top_row.addWidget(cb, 1)

        badge = QLabel()
        if item.severity == IssueSeverity.CRITICAL_CRASH:
            badge.setText("CRITICAL CTD")
            badge.setStyleSheet(
                f"QLabel {{ color: {COLOR_TEXT_PRIMARY}; background-color: {COLOR_ACCENT}; "
                f"border: 1px solid {COLOR_BORDER}; border-radius: 3px; padding: 2px 6px; "
                f"font-weight: 700; font-size: 10px; }}"
            )
        else:
            badge.setText("WARNING")
            badge.setStyleSheet(
                f"QLabel {{ color: {COLOR_WARNING}; background-color: {COLOR_BG_INPUT}; "
                f"border: 1px solid {COLOR_WARNING}; border-radius: 3px; padding: 2px 6px; "
                f"font-weight: 700; font-size: 10px; }}"
            )
        top_row.addWidget(badge, 0)
        card_layout.addLayout(top_row)

        # File path
        lbl_file = QLabel(item.file_path)
        lbl_file.setStyleSheet(
            f"QLabel {{ color: {COLOR_TEXT_MUTED}; font-size: 11px; font-family: monospace; border: none; }}"
        )
        card_layout.addWidget(lbl_file)

        # Description
        lbl_desc = QLabel(item.description)
        lbl_desc.setStyleSheet(
            f"QLabel {{ color: {COLOR_TEXT_SECONDARY}; font-size: 12px; border: none; }}"
        )
        lbl_desc.setWordWrap(True)
        card_layout.addWidget(lbl_desc)

        # Repair action hint
        if item.can_autofix and item.fix_description:
            lbl_fix = QLabel(f"Repair: {item.fix_description}")
            lbl_fix.setStyleSheet(
                f"QLabel {{ color: {COLOR_SUCCESS}; font-size: 11px; font-weight: 600; border: none; }}"
            )
            card_layout.addWidget(lbl_fix)
        elif not item.can_autofix:
            lbl_manual = QLabel("Manual inspection required (no automated fix)")
            lbl_manual.setStyleSheet(
                f"QLabel {{ color: {COLOR_TEXT_MUTED}; font-size: 11px; border: none; }}"
            )
            card_layout.addWidget(lbl_manual)

        return card

    def _on_fix_clicked(self) -> None:
        self.done(QDialog.DialogCode.Accepted)

    def _on_ignore_clicked(self) -> None:
        self.done(10)

    def render(self, state: PackRepairState) -> None:
        """Project immutable state into dialog widgets with strict signal blocking."""
        subtitle_text = f"Found {len(state.items)} diagnostic defect(s) in {state.pack_name}."
        if self.subtitle_label.text() != subtitle_text:
            self.subtitle_label.blockSignals(True)
            self.subtitle_label.setText(subtitle_text)
            self.subtitle_label.blockSignals(False)

        # Sync checkboxes
        for item in state.items:
            cb = self._checkbox_by_id.get(item.issue_id)
            if cb is not None:
                if cb.isChecked() != item.is_selected:
                    cb.blockSignals(True)
                    cb.setChecked(item.is_selected)
                    cb.blockSignals(False)
                if cb.isEnabled() != item.can_autofix:
                    cb.blockSignals(True)
                    cb.setEnabled(item.can_autofix)
                    cb.blockSignals(False)

        # Update button state
        can_fix = state.can_autofix_any and state.selected_count > 0
        if self.fix_button.isEnabled() != can_fix:
            self.fix_button.blockSignals(True)
            self.fix_button.setEnabled(can_fix)
            self.fix_button.blockSignals(False)
