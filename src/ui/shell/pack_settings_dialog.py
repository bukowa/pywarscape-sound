"""Mod pack export destination settings and build dialog."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ui.theme import (
    BTN_STYLE_PRIMARY,
    BTN_STYLE_SECONDARY,
    CHECKBOX_STYLE,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_SUCCESS,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
    INPUT_STYLE,
)
from src.workspace.game_detector import GameDetector
from src.workspace.paths import get_settings_path
from src.workspace.project import AudioProject


class PackSettingsDialog(QDialog):
    """Dialog allowing modders to configure output .pack file destination and build."""

    pack_built = Signal(Path)

    def __init__(self, project: AudioProject, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("Mod Pack Settings & Export")
        self.setMinimumWidth(640)
        self.resize(680, 320)
        self.setModal(True)

        self._init_ui()
        self._load_current_values()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Header Card
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_PANEL}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 6px; padding: 10px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(12, 12, 12, 12)
        card_layout.setSpacing(8)

        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form_layout.setSpacing(10)

        self.lbl_project_name = QLabel(self.project.manifest.name)
        self.lbl_project_name.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-weight: bold;")
        form_layout.addRow(QLabel("Project Name:"), self.lbl_project_name)

        self.lbl_game = QLabel(self.project.manifest.game.value.capitalize())
        self.lbl_game.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY};")
        form_layout.addRow(QLabel("Target Game:"), self.lbl_game)

        path_row = QHBoxLayout()
        self.txt_pack_path = QLineEdit()
        self.txt_pack_path.setStyleSheet(INPUT_STYLE)
        self.txt_pack_path.setPlaceholderText("Select output .pack file path...")
        self.txt_pack_path.textChanged.connect(self._on_path_changed)
        path_row.addWidget(self.txt_pack_path, 1)

        self.btn_browse = QPushButton("Browse...")
        self.btn_browse.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_browse.clicked.connect(self._on_browse_clicked)
        path_row.addWidget(self.btn_browse)
        form_layout.addRow(QLabel("Pack Destination:"), path_row)

        card_layout.addLayout(form_layout)

        # Destination status label
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        card_layout.addWidget(self.lbl_status)

        # Preset Button Row
        preset_row = QHBoxLayout()
        self.btn_project_dir_preset = QPushButton("Set to Project Folder")
        self.btn_project_dir_preset.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_project_dir_preset.clicked.connect(self._on_use_project_dir_preset)
        preset_row.addWidget(self.btn_project_dir_preset)

        self.btn_game_data_preset = QPushButton("Set to Game Data Directory")
        self.btn_game_data_preset.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_game_data_preset.clicked.connect(self._on_use_game_data_preset)
        preset_row.addWidget(self.btn_game_data_preset)
        preset_row.addStretch()
        card_layout.addLayout(preset_row)

        # Auto-copy Checkbox Row
        copy_box = QVBoxLayout()
        copy_box.setSpacing(4)
        self.chk_copy_to_game = QCheckBox(
            "Also copy compiled .pack to game data folder after build"
        )
        self.chk_copy_to_game.setStyleSheet(CHECKBOX_STYLE)
        copy_box.addWidget(self.chk_copy_to_game)

        self.lbl_game_target = QLabel("")
        self.lbl_game_target.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; font-size: 11px; padding-left: 20px;"
        )
        copy_box.addWidget(self.lbl_game_target)
        card_layout.addLayout(copy_box)

        main_layout.addWidget(card)

        # Dialog Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_save_only = QPushButton("Save Settings")
        self.btn_save_only.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_save_only.clicked.connect(self._on_save_only_clicked)
        btn_layout.addWidget(self.btn_save_only)

        self.btn_build_now = QPushButton("Build Mod Pack Now")
        self.btn_build_now.setStyleSheet(BTN_STYLE_PRIMARY)
        self.btn_build_now.clicked.connect(self._on_build_now_clicked)
        btn_layout.addWidget(self.btn_build_now)

        main_layout.addLayout(btn_layout)

    def _load_copy_to_game_setting(self) -> bool:
        settings_file = get_settings_path()
        if not settings_file.is_file():
            return False
        try:
            data = json.loads(settings_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                projects = data.get("projects_config", {})
                proj_conf = projects.get(str(self.project.root_dir), {})
                return bool(proj_conf.get("copy_to_game_data", False))
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return False

    def _save_copy_to_game_setting(self, enable: bool) -> None:
        settings_file = get_settings_path()
        try:
            existing: dict = {}
            if settings_file.is_file():
                try:
                    loaded = json.loads(settings_file.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        existing = loaded
                except (OSError, ValueError, json.JSONDecodeError):
                    existing = {}
            projects = existing.setdefault("projects_config", {})
            proj_conf = projects.setdefault(str(self.project.root_dir), {})
            proj_conf["copy_to_game_data"] = enable
            settings_file.parent.mkdir(parents=True, exist_ok=True)
            settings_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        except (OSError, ValueError):
            pass

    def _load_current_values(self) -> None:
        default_path = self.project.resolve_default_pack_path()
        current_str = self.project.manifest.output_pack_path or str(default_path)
        self.txt_pack_path.setText(current_str)
        self._update_status(current_str)

        # Check game data folder detection
        game_pack = self.project.resolve_game_data_pack_path()
        if game_pack is not None:
            self.lbl_game_target.setText(f"Target: {game_pack}")
            self.lbl_game_target.setStyleSheet(
                f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px; padding-left: 20px;"
            )
            self.chk_copy_to_game.setEnabled(True)
            self.chk_copy_to_game.setChecked(self._load_copy_to_game_setting())
        else:
            self.lbl_game_target.setText("(Game data folder not detected for target game)")
            self.lbl_game_target.setStyleSheet(
                f"color: {COLOR_TEXT_MUTED}; font-size: 11px; padding-left: 20px;"
            )
            self.chk_copy_to_game.setEnabled(False)
            self.chk_copy_to_game.setChecked(False)

    def _on_path_changed(self, text: str) -> None:
        self._update_status(text.strip())

    def _update_status(self, path_str: str) -> None:
        if not path_str:
            self.lbl_status.setText("Please specify an output .pack destination.")
            self.btn_build_now.setEnabled(False)
            self.btn_save_only.setEnabled(False)
            return

        p = Path(path_str)
        if "data" in p.parts:
            self.lbl_status.setText("Ready for direct in-game testing in Total War data folder.")
            self.lbl_status.setStyleSheet(
                f"color: {COLOR_SUCCESS}; font-size: 11px; font-weight: bold;"
            )
        else:
            self.lbl_status.setText("Target located in project folder.")
            self.lbl_status.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px;")

        self.btn_build_now.setEnabled(True)
        self.btn_save_only.setEnabled(True)

    def _on_browse_clicked(self) -> None:
        initial = self.txt_pack_path.text().strip() or str(self.project.resolve_default_pack_path())
        chosen, _ = QFileDialog.getSaveFileName(
            self,
            "Select Total War Mod Pack File",
            initial,
            "Total War Pack Files (*.pack)",
        )
        if chosen:
            self.txt_pack_path.setText(chosen)

    def _on_use_game_data_preset(self) -> None:
        detected = GameDetector.detect_game_install(self.project.manifest.game)
        if detected and (detected / "data").is_dir():
            target = detected / "data" / f"{self.project.manifest.name}.pack"
            self.txt_pack_path.setText(str(target))
        else:
            self.txt_pack_path.setText(str(self.project.resolve_default_pack_path()))

    def _on_use_project_dir_preset(self) -> None:
        target = self.project.root_dir / f"{self.project.manifest.name}.pack"
        self.txt_pack_path.setText(str(target))

    def _on_save_only_clicked(self) -> None:
        chosen = self.txt_pack_path.text().strip()
        if chosen:
            self.project.set_output_pack_path(chosen)
        self._save_copy_to_game_setting(self.chk_copy_to_game.isChecked())
        self.accept()

    def _on_build_now_clicked(self) -> None:
        chosen = self.txt_pack_path.text().strip()
        if chosen:
            self.project.set_output_pack_path(chosen)
        self._save_copy_to_game_setting(self.chk_copy_to_game.isChecked())
        try:
            out_path = self.project.compile_mod_pack(validate=True)
            if self.chk_copy_to_game.isChecked():
                self.project.copy_pack_to_game_data(out_path)
            self.pack_built.emit(out_path)
            self.accept()
        except Exception as ex:
            from src.ui.theme import COLOR_WARNING

            self.lbl_status.setText(f"Export blocked: {ex}")
            self.lbl_status.setStyleSheet(
                f"color: {COLOR_WARNING}; font-size: 11px; font-weight: bold;"
            )
