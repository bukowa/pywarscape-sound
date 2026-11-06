"""Modal dialog for managing active external mod pack dependencies and load order."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.theme import (
    BTN_STYLE_DANGER,
    BTN_STYLE_PRIMARY,
    BTN_STYLE_SECONDARY,
    COLOR_BG_INPUT,
    COLOR_BG_PANEL,
    COLOR_BORDER,
    COLOR_TEXT_MUTED,
    COLOR_TEXT_PRIMARY,
    COLOR_TEXT_SECONDARY,
)
from src.workspace.dependencies import DependencyManager
from src.workspace.health import PackHealthScanner

if TYPE_CHECKING:
    from src.ui.shell.coordinator import WorkspaceCoordinator
    from src.workspace.project import AudioProject


class DependencyManagerDialog(QDialog):
    """Dialog allowing modders to inspect, add, remove, and reorder external .pack dependencies."""

    dependencies_changed = Signal()

    def __init__(
        self,
        project: AudioProject,
        coordinator: WorkspaceCoordinator | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.coordinator = coordinator
        self._has_changes = False

        self.setWindowTitle("Manage Mod Dependencies")
        self.setMinimumWidth(720)
        self.resize(780, 420)
        self.setModal(True)

        self._init_ui()
        self._refresh_table()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Header Info Card
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {COLOR_BG_PANEL}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 6px; padding: 6px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(4)

        lbl_title = QLabel("MOD DEPENDENCIES & LOAD ORDER")
        lbl_title.setStyleSheet(f"color: {COLOR_TEXT_PRIMARY}; font-weight: bold; font-size: 13px;")
        card_layout.addWidget(lbl_title)

        lbl_desc = QLabel(
            "Dependency pack files provide base SoundBanks and database metadata (units, voiceovers, combat materials). "
            "Higher priority packs override matching files from lower priority packs. "
            "Your project's own edited audio in pack_root/audio/ is always preserved and never modified."
        )
        lbl_desc.setStyleSheet(f"color: {COLOR_TEXT_SECONDARY}; font-size: 11px;")
        lbl_desc.setWordWrap(True)
        card_layout.addWidget(lbl_desc)

        main_layout.addWidget(card)

        # Content Row (Table + Side Action Buttons)
        content_row = QHBoxLayout()
        content_row.setSpacing(10)

        # Table Widget
        self.table_deps = QTableWidget(0, 5)
        self.table_deps.setHorizontalHeaderLabels(
            ["Priority", "Pack Name", "Audio Files", "DB Tables", "Source Path"]
        )
        self.table_deps.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_deps.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table_deps.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table_deps.setStyleSheet(
            f"QTableWidget {{ background-color: {COLOR_BG_INPUT}; border: 1px solid {COLOR_BORDER}; "
            f"border-radius: 4px; color: {COLOR_TEXT_PRIMARY}; font-size: 11px; }} "
            f"QHeaderView::section {{ background-color: {COLOR_BG_PANEL}; color: {COLOR_TEXT_SECONDARY}; "
            f"font-weight: bold; border: 1px solid {COLOR_BORDER}; padding: 4px; }}"
        )

        hdr = self.table_deps.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        self.table_deps.itemSelectionChanged.connect(self._update_button_states)
        content_row.addWidget(self.table_deps, 1)

        # Action Buttons Column
        btn_col = QVBoxLayout()
        btn_col.setSpacing(8)

        self.btn_add = QPushButton("Add .pack...")
        self.btn_add.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_add.clicked.connect(self._on_add_clicked)
        btn_col.addWidget(self.btn_add)

        self.btn_remove = QPushButton("Remove")
        self.btn_remove.setStyleSheet(BTN_STYLE_DANGER)
        self.btn_remove.clicked.connect(self._on_remove_clicked)
        self.btn_remove.setEnabled(False)
        btn_col.addWidget(self.btn_remove)

        btn_col.addSpacing(8)

        self.btn_up = QPushButton("Move Up")
        self.btn_up.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_up.clicked.connect(self._on_move_up_clicked)
        self.btn_up.setEnabled(False)
        btn_col.addWidget(self.btn_up)

        self.btn_down = QPushButton("Move Down")
        self.btn_down.setStyleSheet(BTN_STYLE_SECONDARY)
        self.btn_down.clicked.connect(self._on_move_down_clicked)
        self.btn_down.setEnabled(False)
        btn_col.addWidget(self.btn_down)

        btn_col.addStretch(1)
        content_row.addLayout(btn_col)

        main_layout.addLayout(content_row, 1)

        # Bottom Bar
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(10)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; font-size: 11px;")
        bottom_row.addWidget(self.lbl_status, 1)

        self.btn_close = QPushButton("Close")
        self.btn_close.setStyleSheet(BTN_STYLE_PRIMARY)
        self.btn_close.clicked.connect(self.accept)
        bottom_row.addWidget(self.btn_close)

        main_layout.addLayout(bottom_row)

    def _refresh_table(self) -> None:
        deps = sorted(self.project.manifest.dependencies, key=lambda d: d.priority)
        current_row = self.table_deps.currentRow()

        self.table_deps.blockSignals(True)
        self.table_deps.setRowCount(len(deps))

        for row, dep in enumerate(deps):
            p_item = QTableWidgetItem(str(dep.priority))
            p_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            name_item = QTableWidgetItem(dep.name)
            audio_item = QTableWidgetItem(str(len(dep.extracted_audio_files)))
            audio_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            db_item = QTableWidgetItem(str(len(dep.extracted_db_tables)))
            db_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            src_item = QTableWidgetItem(dep.source_path or "—")

            self.table_deps.setItem(row, 0, p_item)
            self.table_deps.setItem(row, 1, name_item)
            self.table_deps.setItem(row, 2, audio_item)
            self.table_deps.setItem(row, 3, db_item)
            self.table_deps.setItem(row, 4, src_item)

        if 0 <= current_row < len(deps):
            self.table_deps.selectRow(current_row)

        self.table_deps.blockSignals(False)
        self.lbl_status.setText(f"Active dependencies: {len(deps)}")
        self._update_button_states()

    def _update_button_states(self) -> None:
        row = self.table_deps.currentRow()
        count = self.table_deps.rowCount()
        has_sel = row >= 0

        self.btn_remove.setEnabled(has_sel)
        self.btn_up.setEnabled(has_sel and row > 0)
        self.btn_down.setEnabled(has_sel and row < count - 1)

    def _on_add_clicked(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Mod Pack File(s)",
            "",
            "Total War Pack Files (*.pack);;All Files (*)",
        )
        if not paths:
            return

        dep_mgr = DependencyManager(self.project)
        added_any = False

        for path_str in paths:
            p = Path(path_str)
            if not p.is_file() or not p.name.lower().endswith(".pack"):
                continue

            if any(d.name.lower() == p.name.lower() for d in self.project.manifest.dependencies):
                QMessageBox.information(
                    self,
                    "Pack Already Present",
                    f"Dependency '{p.name}' is already imported.",
                )
                continue

            # Scan pack health
            report = PackHealthScanner.scan_pack(p)
            if report.has_critical_issues:
                reply = QMessageBox.warning(
                    self,
                    "Pack Issues Detected",
                    f"Issues were detected in '{p.name}'. Import safe entries anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    continue

            try:
                plan = dep_mgr.plan_import(p)
                dep_mgr.execute_import(plan)
                added_any = True
            except Exception as e:
                QMessageBox.critical(self, "Import Failed", f"Failed to import '{p.name}': {e}")

        if added_any:
            self._has_changes = True
            self._refresh_table()

    def _on_remove_clicked(self) -> None:
        row = self.table_deps.currentRow()
        deps = sorted(self.project.manifest.dependencies, key=lambda d: d.priority)
        if not (0 <= row < len(deps)):
            return

        target_dep = deps[row]
        reply = QMessageBox.question(
            self,
            "Remove Dependency",
            f"Are you sure you want to remove dependency '{target_dep.name}'?\n\n"
            "This will delete its extracted reference files from disk. "
            "Your project's own edited audio in pack_root/audio/ will NOT be affected.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            dep_mgr = DependencyManager(self.project)
            try:
                dep_mgr.remove_dependency(target_dep.name)
                self._has_changes = True
                self._refresh_table()
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Remove Failed",
                    f"Failed to remove '{target_dep.name}': {e}",
                )

    def _on_move_up_clicked(self) -> None:
        row = self.table_deps.currentRow()
        deps = sorted(self.project.manifest.dependencies, key=lambda d: d.priority)
        if row <= 0 or row >= len(deps):
            return

        names = [d.name for d in deps]
        names[row], names[row - 1] = names[row - 1], names[row]

        dep_mgr = DependencyManager(self.project)
        try:
            dep_mgr.reorder_dependencies(names)
            self._has_changes = True
            self._refresh_table()
            self.table_deps.selectRow(row - 1)
        except Exception as e:
            QMessageBox.critical(self, "Reorder Failed", f"Failed to reorder: {e}")

    def _on_move_down_clicked(self) -> None:
        row = self.table_deps.currentRow()
        deps = sorted(self.project.manifest.dependencies, key=lambda d: d.priority)
        if row < 0 or row >= len(deps) - 1:
            return

        names = [d.name for d in deps]
        names[row], names[row + 1] = names[row + 1], names[row]

        dep_mgr = DependencyManager(self.project)
        try:
            dep_mgr.reorder_dependencies(names)
            self._has_changes = True
            self._refresh_table()
            self.table_deps.selectRow(row + 1)
        except Exception as e:
            QMessageBox.critical(self, "Reorder Failed", f"Failed to reorder: {e}")

    def accept(self) -> None:
        self._apply_hot_reload_if_changed()
        super().accept()

    def reject(self) -> None:
        self._apply_hot_reload_if_changed()
        super().reject()

    def _apply_hot_reload_if_changed(self) -> None:
        if self._has_changes:
            if self.coordinator is not None:
                self.coordinator.reload_project_dependencies()
            self.dependencies_changed.emit()
            self._has_changes = False
