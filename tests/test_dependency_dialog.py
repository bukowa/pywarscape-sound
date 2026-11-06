from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from src.ui.shell.dependency_manager_dialog import DependencyManagerDialog
from src.workspace.game import GameType
from src.workspace.health import HealthIssue, IssueSeverity, PackHealthReport, PackHealthScanner
from src.workspace.manifest import DependencyPackInfo, ProjectManifest
from src.workspace.project import AudioProject
from src.workspace.storage import ProjectStorage


def test_dependency_manager_dialog_populates_table(qapp, tmp_path: Path):
    proj_dir = tmp_path / "test_mod"
    manifest = ProjectManifest(
        name="TestMod",
        game=GameType.ATTILA,
        dependencies=[
            DependencyPackInfo(
                name="dep_a.pack",
                priority=0,
                source_path="/path/to/dep_a.pack",
                extracted_audio_files=["audio/bank1.bnk"],
                extracted_db_tables=["db/land_units_tables/units_a"],
            ),
            DependencyPackInfo(
                name="dep_b.pack",
                priority=1,
                source_path="/path/to/dep_b.pack",
                extracted_audio_files=[],
                extracted_db_tables=["db/land_units_tables/units_b"],
            ),
        ],
    )
    project = AudioProject(root_dir=proj_dir, manifest=manifest)
    ProjectStorage.save_project(project)

    coordinator = MagicMock()
    dialog = DependencyManagerDialog(project, coordinator=coordinator)

    assert dialog.table_deps.rowCount() == 2
    assert dialog.table_deps.item(0, 0).text() == "0"
    assert dialog.table_deps.item(0, 1).text() == "dep_a.pack"
    assert dialog.table_deps.item(0, 2).text() == "1"
    assert dialog.table_deps.item(0, 3).text() == "1"

    assert dialog.table_deps.item(1, 0).text() == "1"
    assert dialog.table_deps.item(1, 1).text() == "dep_b.pack"

    # Initially no selection -> remove/move buttons disabled
    assert not dialog.btn_remove.isEnabled()
    assert not dialog.btn_up.isEnabled()
    assert not dialog.btn_down.isEnabled()

    # Select row 0
    dialog.table_deps.selectRow(0)
    assert dialog.btn_remove.isEnabled()
    assert not dialog.btn_up.isEnabled()  # already top
    assert dialog.btn_down.isEnabled()

    # Move down
    dialog._on_move_down_clicked()
    assert project.manifest.dependencies[0].name == "dep_b.pack"
    assert project.manifest.dependencies[1].name == "dep_a.pack"
    assert dialog.table_deps.item(0, 1).text() == "dep_b.pack"
    assert dialog.table_deps.item(1, 1).text() == "dep_a.pack"

    # Move up
    dialog.table_deps.selectRow(1)
    dialog._on_move_up_clicked()
    assert project.manifest.dependencies[0].name == "dep_a.pack"
    assert project.manifest.dependencies[1].name == "dep_b.pack"

    # Accept dialog -> triggers hot reload because order changed
    dialog.accept()
    coordinator.reload_project_dependencies.assert_called_once()


def test_dependency_manager_dialog_remove(qapp, tmp_path: Path):
    proj_dir = tmp_path / "test_mod"
    manifest = ProjectManifest(
        name="TestMod",
        game=GameType.ATTILA,
        dependencies=[
            DependencyPackInfo(
                name="dep_a.pack",
                priority=0,
            ),
        ],
    )
    project = AudioProject(root_dir=proj_dir, manifest=manifest)
    ProjectStorage.save_project(project)

    dep_dir = project.get_dependency_dir("dep_a.pack")
    dep_dir.mkdir(parents=True, exist_ok=True)

    coordinator = MagicMock()
    dialog = DependencyManagerDialog(project, coordinator=coordinator)
    dialog.table_deps.selectRow(0)

    # Cancel removal
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
        dialog._on_remove_clicked()
    assert len(project.manifest.dependencies) == 1
    assert dep_dir.is_dir()

    # Confirm removal
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        dialog._on_remove_clicked()

    assert len(project.manifest.dependencies) == 0
    assert not dep_dir.is_dir()
    assert dialog.table_deps.rowCount() == 0

    dialog.accept()
    coordinator.reload_project_dependencies.assert_called_once()


def test_dependency_manager_dialog_add_pack_with_critical_issues(qapp, tmp_path: Path):
    proj_dir = tmp_path / "test_mod"
    manifest = ProjectManifest(
        name="TestMod",
        game=GameType.ATTILA,
        dependencies=[],
    )
    project = AudioProject(root_dir=proj_dir, manifest=manifest)
    ProjectStorage.save_project(project)

    pack_path = tmp_path / "corrupt.pack"
    pack_path.write_bytes(b"dummy")

    coordinator = MagicMock()
    dialog = DependencyManagerDialog(project, coordinator=coordinator)

    mock_report = PackHealthReport(
        pack_name="corrupt.pack",
        issues=(
            HealthIssue(
                issue_id="test_issue",
                file_path="corrupt.pack",
                object_id=None,
                title="Corrupted SoundBank",
                description="Test corruption",
                severity=IssueSeverity.CRITICAL_CRASH,
                can_autofix=False,
            ),
        ),
    )

    with (
        patch.object(QFileDialog, "getOpenFileNames", return_value=([str(pack_path)], "")),
        patch.object(PackHealthScanner, "scan_pack", return_value=mock_report),
        patch.object(
            QMessageBox, "warning", return_value=QMessageBox.StandardButton.No
        ) as mock_warn,
    ):
        dialog._on_add_clicked()
        mock_warn.assert_called_once()
