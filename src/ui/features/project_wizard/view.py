"""PySide6 Project Wizard view projection for Audio Editor v3."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
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
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.ui.features.pack_repair import PackRepairDialog, PackRepairStore
from src.ui.features.project_wizard.state import ProjectWizardState, WizardStep
from src.ui.features.project_wizard.store import ProjectWizardStore
from src.ui.theme import (
    BTN_STYLE_DANGER,
    BTN_STYLE_PRIMARY,
    BTN_STYLE_SECONDARY,
    CHECKBOX_STYLE,
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
    PROGRESS_BAR_STYLE,
)
from src.workspace.game import GameType
from src.workspace.health import PackHealthScanner, RepairStrategyRegistry


class ProjectWizardView(QWidget):
    """Pure data-driven multi-step wizard widget for project onboarding."""

    project_created = Signal(object)
    cancelled = Signal()

    def __init__(self, store: ProjectWizardStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._init_ui()
        self.store.subscribe(self.render)
        self.render(self.store.state)

    def _init_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(20, 20, 20, 20)
        root_layout.setSpacing(14)

        # Header
        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel("PyWarscape Sound - Project Wizard")
        title.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-size: 18px; font-weight: 700;")
        subtitle = QLabel("Configure game installation, cache status, and base mod dependencies")
        subtitle.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 12px;")
        header.addWidget(title)
        header.addWidget(subtitle)
        root_layout.addLayout(header)

        # Stacked pages
        self.stacked_widget = QStackedWidget()
        self._page_setup = self._build_setup_page()
        self._page_mod_packs = self._build_mod_packs_page()
        self._page_progress = self._build_progress_page()

        self.stacked_widget.addWidget(self._page_setup)
        self.stacked_widget.addWidget(self._page_mod_packs)
        self.stacked_widget.addWidget(self._page_progress)
        root_layout.addWidget(self.stacked_widget, 1)

        # Bottom status label
        self.lbl_global_status = QLabel()
        self.lbl_global_status.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        root_layout.addWidget(self.lbl_global_status)

    def _build_setup_page(self) -> QWidget:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_PANEL}; border: 1px solid {COLOR_BORDER}; border-radius: 6px; }}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Game Selector
        lbl_game = QLabel("Target Game Engine")
        lbl_game.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 12px; font-weight: 600; border: none;"
        )
        self.combo_game = QComboBox()
        self.combo_game.setStyleSheet(COMBO_STYLE)
        self.combo_game.addItems(["Attila", "Rome II"])
        self.combo_game.currentTextChanged.connect(self._on_game_changed)
        layout.addWidget(lbl_game)
        layout.addWidget(self.combo_game)

        # Game Cache Status
        self.lbl_cache_status = QLabel("Game Cache: Unindexed")
        self.lbl_cache_status.setStyleSheet(
            f"color: {COLOR_WARNING}; font-size: 12px; font-weight: 600; border: none;"
        )
        layout.addWidget(self.lbl_cache_status)

        # Project Name
        lbl_pname = QLabel("Project Name")
        lbl_pname.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 12px; font-weight: 600; border: none; margin-top: 6px;"
        )
        self.edit_name = QLineEdit()
        self.edit_name.setStyleSheet(INPUT_STYLE)
        self.edit_name.textChanged.connect(self.store.set_project_name)
        layout.addWidget(lbl_pname)
        layout.addWidget(self.edit_name)

        # Project Location
        lbl_ploc = QLabel("Workspace Directory")
        lbl_ploc.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 12px; font-weight: 600; border: none;"
        )
        loc_row = QHBoxLayout()
        loc_row.setSpacing(8)
        self.edit_location = QLineEdit()
        self.edit_location.setStyleSheet(INPUT_STYLE)
        self.edit_location.textChanged.connect(self.store.set_project_location)
        self.btn_browse_location = QPushButton("Browse...")
        self.btn_browse_location.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_browse_location.clicked.connect(self._on_browse_location_clicked)
        loc_row.addWidget(self.edit_location)
        loc_row.addWidget(self.btn_browse_location)
        layout.addWidget(lbl_ploc)
        layout.addLayout(loc_row)

        self.lbl_target_status = QLabel()
        self.lbl_target_status.setStyleSheet(
            f"color: {COLOR_WARNING}; font-size: 11px; border: none;"
        )
        self.lbl_target_status.setVisible(False)
        layout.addWidget(self.lbl_target_status)

        layout.addStretch()

        # Step 1 Action Bar
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_cancel.clicked.connect(self.cancelled.emit)

        self.btn_skip = QPushButton("Skip / Vanilla Project")
        self.btn_skip.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_skip.clicked.connect(self._on_skip_clicked)

        self.btn_next = QPushButton("Next: Base Mod Packs ->")
        self.btn_next.setStyleSheet(BTN_STYLE_PRIMARY)
        self.btn_next.clicked.connect(lambda: self.store.go_to_step(WizardStep.MOD_PACKS))

        actions.addWidget(self.btn_cancel)
        actions.addStretch()
        actions.addWidget(self.btn_skip)
        actions.addWidget(self.btn_next)
        layout.addLayout(actions)

        return card

    def _build_mod_packs_page(self) -> QWidget:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_PANEL}; border: 1px solid {COLOR_BORDER}; border-radius: 6px; }}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        desc = QLabel(
            "Select overhaul or parent mod .pack files in priority load order (top to bottom)"
        )
        desc.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 12px; border: none;")
        layout.addWidget(desc)

        list_row = QHBoxLayout()
        list_row.setSpacing(10)

        self.list_packs = QListWidget()
        self.list_packs.setStyleSheet(
            f"QListWidget {{ background-color: {COLOR_BG_INPUT}; color: {COLOR_TEXT_PRIMARY}; "
            f"border: 1px solid {COLOR_BORDER}; border-radius: 4px; padding: 4px; }} "
            f"QListWidget::item {{ padding: 6px; border-bottom: 1px solid {COLOR_BORDER}; }} "
            f"QListWidget::item:selected {{ background-color: {COLOR_ACCENT}; }}"
        )
        list_row.addWidget(self.list_packs, 1)

        side_btns = QVBoxLayout()
        side_btns.setSpacing(6)
        self.btn_add_pack = QPushButton("Add .pack...")
        self.btn_add_pack.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_add_pack.clicked.connect(self._on_add_pack_clicked)

        self.btn_remove_pack = QPushButton("Remove")
        self.btn_remove_pack.setStyleSheet(BTN_STYLE_DANGER)
        self.btn_remove_pack.clicked.connect(self._on_remove_pack_clicked)

        self.btn_move_up = QPushButton("Move Up")
        self.btn_move_up.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_move_up.clicked.connect(self._on_move_up_clicked)

        self.btn_move_down = QPushButton("Move Down")
        self.btn_move_down.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_move_down.clicked.connect(self._on_move_down_clicked)

        side_btns.addWidget(self.btn_add_pack)
        side_btns.addWidget(self.btn_remove_pack)
        side_btns.addWidget(self.btn_move_up)
        side_btns.addWidget(self.btn_move_down)
        side_btns.addStretch()
        list_row.addLayout(side_btns)
        layout.addLayout(list_row, 1)

        self.chk_import_db = QCheckBox("Import audio-linked DB tables as metadata (Recommended)")
        self.chk_import_db.setStyleSheet(CHECKBOX_STYLE)
        self.chk_import_db.toggled.connect(self.store.set_import_db_tables)
        layout.addWidget(self.chk_import_db)

        # Step 2 Action Bar
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.btn_back_mod_packs = QPushButton("<- Back")
        self.btn_back_mod_packs.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_back_mod_packs.clicked.connect(lambda: self.store.go_to_step(WizardStep.SETUP))

        self.btn_skip_mod_packs = QPushButton("Skip / Vanilla Project")
        self.btn_skip_mod_packs.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_skip_mod_packs.clicked.connect(self._on_skip_clicked)

        self.btn_create_ingest = QPushButton("Create & Ingest ->")
        self.btn_create_ingest.setStyleSheet(BTN_STYLE_PRIMARY)
        self.btn_create_ingest.clicked.connect(self._on_create_ingest_clicked)

        actions.addWidget(self.btn_back_mod_packs)
        actions.addStretch()
        actions.addWidget(self.btn_skip_mod_packs)
        actions.addWidget(self.btn_create_ingest)
        layout.addLayout(actions)

        return card

    def _build_progress_page(self) -> QWidget:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_PANEL}; border: 1px solid {COLOR_BORDER}; border-radius: 6px; }}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        lbl_title = QLabel("Creating Project & Ingesting Dependencies")
        lbl_title.setStyleSheet(
            f"color: {COLOR_TEXT_PRIMARY}; font-size: 14px; font-weight: 600; border: none;"
        )
        layout.addWidget(lbl_title)

        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(PROGRESS_BAR_STYLE)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.lbl_progress_desc = QLabel("Initializing...")
        self.lbl_progress_desc.setStyleSheet(
            f"color: {COLOR_TEXT_SECONDARY}; font-size: 12px; border: none;"
        )
        layout.addWidget(self.lbl_progress_desc)

        layout.addStretch()
        return card

    def _on_game_changed(self, text: str) -> None:
        gt = GameType.ROME_2 if text == "Rome II" else GameType.ATTILA
        self.store.set_selected_game(gt)

    def _on_browse_location_clicked(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Workspace Directory")
        if folder:
            self.store.set_project_location(folder)

    def _on_add_pack_clicked(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Mod Pack File(s)", "", "Pack Files (*.pack)"
        )
        if not paths:
            return

        for path in paths:
            self._process_single_pack(path)

    def _process_single_pack(self, path: str) -> None:
        report = PackHealthScanner.scan_pack(path)
        if report.issues:
            repair_store = PackRepairStore(report)
            dialog = PackRepairDialog(repair_store, parent=self)
            result = dialog.exec()
            if result == QDialog.DialogCode.Accepted:
                selected_ids = repair_store.get_selected_issue_ids()
                repaired_files: dict[str, bytes] = {}
                if selected_ids:
                    from src.compiler.pfh4_pack import extract_pfh4_file, read_pfh4_index

                    entries = read_pfh4_index(path)
                    entries_by_norm = {e.path.replace("\\", "/").lower(): e for e in entries}

                    # Find all files with selected issues
                    files_to_repair = {
                        item.file_path for item in repair_store.state.items if item.is_selected
                    }
                    for fpath in files_to_repair:
                        norm_fpath = fpath.replace("\\", "/").lower()
                        matching_entry = entries_by_norm.get(norm_fpath)
                        if matching_entry is None:
                            base = norm_fpath.split("/")[-1]
                            for ep_lower, ent in entries_by_norm.items():
                                if ep_lower.split("/")[-1] == base:
                                    matching_entry = ent
                                    break

                        if matching_entry is not None:
                            raw_data = extract_pfh4_file(path, matching_entry)
                            try:
                                fixed_data = RepairStrategyRegistry.repair_bank(
                                    fpath, raw_data, issue_ids=selected_ids
                                )
                                repaired_files[fpath] = fixed_data
                            except (ValueError, KeyError, RuntimeError, OSError):
                                pass

                self.store.add_mod_pack(path, repaired_files=repaired_files)
            elif result == 10:
                self.store.add_mod_pack(path)
            else:
                # Cancelled / Rejected: abort without adding
                return
        else:
            self.store.add_mod_pack(path)

    def _on_remove_pack_clicked(self) -> None:
        row = self.list_packs.currentRow()
        if row >= 0:
            self.store.remove_mod_pack(row)

    def _on_move_up_clicked(self) -> None:
        row = self.list_packs.currentRow()
        if row > 0:
            if self.store.move_mod_pack(row, direction=-1):
                self.list_packs.setCurrentRow(row - 1)

    def _on_move_down_clicked(self) -> None:
        row = self.list_packs.currentRow()
        if row >= 0 and row < self.list_packs.count() - 1:
            if self.store.move_mod_pack(row, direction=1):
                self.list_packs.setCurrentRow(row + 1)

    def _on_skip_clicked(self) -> None:
        proj = self.store.skip_to_finish()
        if proj is not None:
            self.project_created.emit(proj)

    def _on_create_ingest_clicked(self) -> None:
        proj = self.store.create_project_and_ingest()
        if proj is not None:
            self.project_created.emit(proj)

    def render(self, state: ProjectWizardState) -> None:
        """Project immutable state into widgets with signal blocking."""
        # 1. Page navigation
        idx = (
            0
            if state.step == WizardStep.SETUP
            else (1 if state.step == WizardStep.MOD_PACKS else 2)
        )
        if self.stacked_widget.currentIndex() != idx:
            self.stacked_widget.blockSignals(True)
            self.stacked_widget.setCurrentIndex(idx)
            self.stacked_widget.blockSignals(False)

        # 2. Setup Page Fields
        game_text = "Rome II" if state.selected_game == GameType.ROME_2 else "Attila"
        if self.combo_game.currentText() != game_text:
            self.combo_game.blockSignals(True)
            self.combo_game.setCurrentText(game_text)
            self.combo_game.blockSignals(False)

        self.lbl_cache_status.blockSignals(True)
        if state.is_cache_valid:
            self.lbl_cache_status.setText("Game Cache: Ready")
            self.lbl_cache_status.setStyleSheet(
                f"color: {COLOR_SUCCESS}; font-size: 12px; font-weight: 600; border: none;"
            )
        else:
            self.lbl_cache_status.setText(
                "Game Cache: Not Built (Please configure and build cache in Project Hub)"
            )
            self.lbl_cache_status.setStyleSheet(
                f"color: {COLOR_WARNING}; font-size: 12px; font-weight: 600; border: none;"
            )
        self.lbl_cache_status.blockSignals(False)

        if self.edit_name.text() != state.project_name:
            self.edit_name.blockSignals(True)
            self.edit_name.setText(state.project_name)
            self.edit_name.blockSignals(False)

        if self.edit_location.text() != state.project_location:
            self.edit_location.blockSignals(True)
            self.edit_location.setText(state.project_location)
            self.edit_location.blockSignals(False)

        self.lbl_target_status.blockSignals(True)
        if not state.is_target_dir_available and state.target_dir_validation_msg:
            self.lbl_target_status.setText(state.target_dir_validation_msg)
            self.lbl_target_status.setVisible(True)
        else:
            self.lbl_target_status.setText("")
            self.lbl_target_status.setVisible(False)
        self.lbl_target_status.blockSignals(False)

        can_next = bool(
            state.project_name.strip()
            and state.project_location.strip()
            and state.is_target_dir_available
            and not state.is_working
        )
        self.btn_next.setEnabled(can_next)
        self.btn_skip.setEnabled(can_next)

        # 3. Mod Packs Page Fields
        current_row = self.list_packs.currentRow()
        self.list_packs.blockSignals(True)
        self.list_packs.clear()
        for i, entry in enumerate(state.mod_packs, start=1):
            sz_mb = entry.size_bytes / (1024 * 1024)
            item = QListWidgetItem(f"[{i}] {entry.filename} ({sz_mb:.1f} MB)\n{entry.path}")
            self.list_packs.addItem(item)
        if 0 <= current_row < self.list_packs.count():
            self.list_packs.setCurrentRow(current_row)
        self.list_packs.blockSignals(False)

        if self.chk_import_db.isChecked() != state.import_db_tables:
            self.chk_import_db.blockSignals(True)
            self.chk_import_db.setChecked(state.import_db_tables)
            self.chk_import_db.blockSignals(False)

        # 4. Progress Page
        pct_int = int(state.progress_percentage * 100)
        self.progress_bar.blockSignals(True)
        self.progress_bar.setValue(pct_int)
        self.progress_bar.blockSignals(False)

        self.lbl_progress_desc.blockSignals(True)
        self.lbl_progress_desc.setText(state.progress_text or "Processing...")
        self.lbl_progress_desc.blockSignals(False)

        # Global Status
        self.lbl_global_status.blockSignals(True)
        self.lbl_global_status.setText(state.status_message or "")
        self.lbl_global_status.blockSignals(False)
