"""PySide6 Project Hub view projection."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.ui.features.project_hub.state import ProjectHubState
from src.ui.features.project_hub.store import ProjectHubStore
from src.ui.features.project_wizard import ProjectWizardStore, ProjectWizardView
from src.ui.theme import (
    BTN_STYLE_PRIMARY,
    BTN_STYLE_SECONDARY,
    COLOR_ACCENT,
    COLOR_BG_INPUT,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_SUCCESS,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    COMBO_STYLE,
    INPUT_STYLE,
)
from src.workspace.game import GameType


class ProjectHubView(QWidget):
    """Pure data-driven presentation widget for the launcher Project Hub."""

    project_loaded = Signal(object)  # Emits AudioProject when opened/created

    def __init__(self, store: ProjectHubStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._init_ui()
        self.store.subscribe(self.render)
        self.render(self.store.state)

    def _init_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(24, 24, 24, 24)
        root_layout.setSpacing(16)

        # Header Title
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)
        title = QLabel("PyWarscape Sound")
        title.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: 20px; font-weight: 700;")
        subtitle = QLabel("Total War Wwise SoundBank & Audio Middleware Workspace")
        subtitle.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 12px;")
        header_layout.addWidget(title)
        header_layout.addWidget(subtitle)
        root_layout.addLayout(header_layout)

        # Splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)

        # Left Card: Recent Projects
        left_card = QFrame()
        left_card.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_PANEL}; border: 1px solid {COLOR_BORDER}; border-radius: 6px; }}"
        )
        left_card.setMinimumWidth(120)
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(14, 14, 14, 14)
        left_layout.setSpacing(10)

        recent_title = QLabel("Recent Projects")
        recent_title.setStyleSheet(
            f"color: {COLOR_TEXT_PRIMARY}; font-size: 14px; font-weight: 600; border: none;"
        )
        self.recent_list = QListWidget()
        self.recent_list.setStyleSheet(
            f"QListWidget {{ background-color: {COLOR_BG_INPUT}; color: {COLOR_TEXT_PRIMARY}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 4px; padding: 4px; }} "
            f"QListWidget::item {{ padding: 6px; border-bottom: 1px solid {COLOR_BORDER}; }} "
            f"QListWidget::item:selected {{ background-color: {COLOR_ACCENT}; }}"
        )
        self.recent_list.itemDoubleClicked.connect(self._on_recent_item_double_clicked)
        left_layout.addWidget(recent_title)
        left_layout.addWidget(self.recent_list)
        self.splitter.addWidget(left_card)

        # Right Card: Actions & Game Cache
        right_card = QFrame()
        right_card.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_PANEL}; border: 1px solid {COLOR_BORDER}; border-radius: 6px; }}"
        )
        right_card.setMinimumWidth(120)
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(16, 16, 16, 16)
        right_layout.setSpacing(12)

        # Section: New Project
        create_title = QLabel("New Project")
        create_title.setStyleSheet(
            f"color: {COLOR_TEXT_PRIMARY}; font-size: 14px; font-weight: 600; border: none;"
        )
        create_desc = QLabel(
            "Configure target game and base mod dependencies in the creation wizard."
        )
        create_desc.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 12px; border: none;")
        create_desc.setWordWrap(True)
        self.btn_create = QPushButton("New Project...")
        self.btn_create.setStyleSheet(BTN_STYLE_PRIMARY)
        self.btn_create.clicked.connect(self.open_wizard)

        right_layout.addWidget(create_title)
        right_layout.addWidget(create_desc)
        right_layout.addWidget(self.btn_create)

        # Section: Open Project
        open_title = QLabel("Open Existing Project")
        open_title.setStyleSheet(
            f"color: {COLOR_TEXT_PRIMARY}; font-size: 14px; font-weight: 600; border: none; margin-top: 6px;"
        )
        open_desc = QLabel("Open an existing PyWarscape Sound mod project directory from disk.")
        open_desc.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 12px; border: none;")
        open_desc.setWordWrap(True)
        self.btn_open = QPushButton("Browse Project Folder...")
        self.btn_open.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_open.clicked.connect(self._on_open_clicked)

        right_layout.addWidget(open_title)
        right_layout.addWidget(open_desc)
        right_layout.addWidget(self.btn_open)

        # Section: Game Installation & Cache
        cache_title = QLabel("Game Installation & Cache")
        cache_title.setStyleSheet(
            f"color: {COLOR_TEXT_PRIMARY}; font-size: 14px; font-weight: 600; border: none; margin-top: 6px;"
        )
        cache_desc = QLabel(
            "Configure game installation folder and build vanilla soundbanks cache."
        )
        cache_desc.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 12px; border: none;")
        cache_desc.setWordWrap(True)

        right_layout.addWidget(cache_title)
        right_layout.addWidget(cache_desc)

        # Game Selector Row
        self.combo_game = QComboBox()
        self.combo_game.setStyleSheet(COMBO_STYLE)
        self.combo_game.addItems(["Attila", "Rome II"])
        self.combo_game.currentTextChanged.connect(self._on_game_changed)
        right_layout.addWidget(self.combo_game)

        # Path row
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.edit_game_path = QLineEdit()
        self.edit_game_path.setStyleSheet(INPUT_STYLE)
        self.edit_game_path.setPlaceholderText("Game installation directory...")
        self.edit_game_path.textChanged.connect(self.store.set_game_path)
        self.btn_browse_game = QPushButton("Browse...")
        self.btn_browse_game.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_browse_game.clicked.connect(self._on_browse_game_clicked)
        path_row.addWidget(self.edit_game_path)
        path_row.addWidget(self.btn_browse_game)
        right_layout.addLayout(path_row)

        self.lbl_game_status = QLabel()
        self.lbl_game_status.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 11px; border: none;"
        )
        right_layout.addWidget(self.lbl_game_status)

        # Cache Status & Action
        cache_action_row = QHBoxLayout()
        cache_action_row.setSpacing(10)
        self.lbl_cache_status = QLabel("Game Cache: Unindexed")
        self.lbl_cache_status.setStyleSheet(
            f"color: {COLOR_WARNING}; font-size: 12px; font-weight: 600; border: none;"
        )
        self.btn_build_cache = QPushButton("Build Cache")
        self.btn_build_cache.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_build_cache.clicked.connect(self._on_build_cache_clicked)
        cache_action_row.addWidget(self.lbl_cache_status)
        cache_action_row.addStretch()
        cache_action_row.addWidget(self.btn_build_cache)
        right_layout.addLayout(cache_action_row)

        # Progress bar
        self.progress_cache = QProgressBar()
        self.progress_cache.setFixedHeight(6)
        self.progress_cache.setTextVisible(False)
        self.progress_cache.setRange(0, 100)
        self.progress_cache.setVisible(False)
        self.lbl_cache_progress = QLabel()
        self.lbl_cache_progress.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; border: none;"
        )
        self.lbl_cache_progress.setVisible(False)
        right_layout.addWidget(self.progress_cache)
        right_layout.addWidget(self.lbl_cache_progress)

        right_layout.addStretch()

        self.splitter.addWidget(right_card)
        self.splitter.setSizes([350, 450])
        root_layout.addWidget(self.splitter, 1)

        # Status Bar
        self.status_label = QLabel()
        self.status_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        self.status_label.setWordWrap(True)
        root_layout.addWidget(self.status_label)

    def _on_game_changed(self, text: str) -> None:
        gt = GameType.ROME_2 if text == "Rome II" else GameType.ATTILA
        self.store.set_selected_game(gt)

    def _on_browse_game_clicked(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Game Installation Directory")
        if folder:
            self.store.set_game_path(folder)

    def _on_build_cache_clicked(self) -> None:
        self.store.build_cache()

    def _on_open_clicked(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Open Audio Project")
        if folder:
            project = self.store.open_project_by_path(folder)
            if project is not None:
                self.project_loaded.emit(project)

    def _on_recent_item_double_clicked(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            project = self.store.open_project_by_path(path)
            if project is not None:
                self.project_loaded.emit(project)

    def create_wizard_dialog(self) -> tuple[QDialog, ProjectWizardView]:
        """Build and configure the modal project wizard dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("PyWarscape Sound - Project Wizard")
        dialog.resize(750, 550)
        d_layout = QVBoxLayout(dialog)
        d_layout.setContentsMargins(0, 0, 0, 0)

        wiz_store = ProjectWizardStore(
            initial_game=self.store.state.selected_game,
            default_location=self.store.state.new_project_location,
        )
        if self.store.state.new_project_name:
            wiz_store.set_project_name(self.store.state.new_project_name)

        wiz_view = ProjectWizardView(wiz_store, parent=dialog)

        def _on_created(proj: object) -> None:
            dialog.accept()
            p_dir = getattr(proj, "root_dir", None) or getattr(proj, "location", None)
            if p_dir:
                self.store.open_project_by_path(str(p_dir))
            self.project_loaded.emit(proj)

        wiz_view.project_created.connect(_on_created)
        d_layout.addWidget(wiz_view)
        return dialog, wiz_view

    def open_wizard(self) -> None:
        """Launch the multi-step project wizard in a modal dialog."""
        dialog, _ = self.create_wizard_dialog()
        dialog.exec()

    def render(self, state: ProjectHubState) -> None:
        """Update widget presentation from immutable state with signal blocking."""
        self.recent_list.blockSignals(True)
        self.recent_list.clear()
        if not state.recent_projects:
            empty_item = QListWidgetItem("No recent projects found.")
            empty_item.setFlags(
                empty_item.flags() & ~Qt.ItemFlag.ItemIsEnabled & ~Qt.ItemFlag.ItemIsSelectable
            )
            self.recent_list.addItem(empty_item)
        else:
            for p in state.recent_projects:
                badge = "Rome II" if p.game == "rome_2" else "Attila"
                item = QListWidgetItem(f"{p.name} [{badge}]\n{p.path}")
                item.setData(Qt.ItemDataRole.UserRole, p.path)
                self.recent_list.addItem(item)
        self.recent_list.blockSignals(False)

        # Game combo
        self.combo_game.blockSignals(True)
        game_text = "Rome II" if state.selected_game == GameType.ROME_2 else "Attila"
        if self.combo_game.currentText() != game_text:
            idx = self.combo_game.findText(game_text)
            if idx >= 0:
                self.combo_game.setCurrentIndex(idx)
        self.combo_game.blockSignals(False)

        # Game path
        self.edit_game_path.blockSignals(True)
        if self.edit_game_path.text() != state.game_path:
            self.edit_game_path.setText(state.game_path)
        self.edit_game_path.blockSignals(False)

        # Game path validation
        if state.game_path_validation_msg:
            color = COLOR_SUCCESS if state.is_game_path_valid else COLOR_WARNING
            self.lbl_game_status.setText(state.game_path_validation_msg)
            self.lbl_game_status.setStyleSheet(f"color: {color}; font-size: 11px; border: none;")
        else:
            self.lbl_game_status.setText("")

        # Cache status & action button
        if state.is_cache_valid:
            self.lbl_cache_status.setText(state.cache_status_msg or "Cache Ready")
            self.lbl_cache_status.setStyleSheet(
                f"color: {COLOR_SUCCESS}; font-size: 12px; font-weight: 600; border: none;"
            )
            self.btn_build_cache.setText("Rebuild Cache")
        else:
            self.lbl_cache_status.setText(state.cache_status_msg or "Game Cache: Not Built")
            self.lbl_cache_status.setStyleSheet(
                f"color: {COLOR_WARNING}; font-size: 12px; font-weight: 600; border: none;"
            )
            self.btn_build_cache.setText("Build Cache")

        self.btn_build_cache.setEnabled(state.is_game_path_valid and not state.is_building_cache)

        # Progress bar
        self.progress_cache.setVisible(state.is_building_cache)
        self.lbl_cache_progress.setVisible(state.is_building_cache)
        if state.is_building_cache:
            self.progress_cache.setValue(int(state.cache_progress_percentage * 100))
            self.lbl_cache_progress.setText(state.cache_progress_text or "Building...")

        # Status label
        self.status_label.blockSignals(True)
        if state.status_message:
            self.status_label.setText(state.status_message)
            self.status_label.setStyleSheet(f"color: {COLOR_WARNING}; font-size: 11px;")
        elif state.loaded_project_path:
            self.status_label.setText(f"Loaded: {state.loaded_project_path}")
            self.status_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        else:
            self.status_label.setText("")
            self.status_label.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        self.status_label.blockSignals(False)
