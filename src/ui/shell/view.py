"""Pure PySide6 Main Application Shell window hosting launcher and workspace."""

import json
import logging
from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QLineEdit,
    QMainWindow,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from src.ui.features.audio_sources import AudioSourcesStore, AudioSourcesView
from src.ui.features.audio_sources.columns import CatalogColumn
from src.ui.features.audio_transport import (
    AudioTransportBar,
    AudioTransportStore,
    PlaybackStatus,
)
from src.ui.features.bank_viewer import BankViewerStore, BankViewerView
from src.ui.features.bank_viewer.columns import TreeColumn
from src.ui.features.bank_viewer.overlays import TreeOverlay
from src.ui.features.bank_viewer.state import BankViewerState
from src.ui.features.project_hub import ProjectHubStore, ProjectHubView
from src.ui.features.project_wizard import ProjectWizardStore, ProjectWizardView
from src.ui.shell.coordinator import WorkspaceCoordinator
from src.ui.shell.state import ScreenMode, ShellState
from src.ui.shell.store import ShellStore
from src.workspace.paths import get_settings_path

logger = logging.getLogger(__name__)


def _resolve_settings_file_path() -> Path:
    """Returns path to the local gitignored settings.json file."""
    return get_settings_path()


class MainWindow(QMainWindow):
    """Main application shell coordinating project launcher and workspace views."""

    def __init__(
        self,
        store: ShellStore | None = None,
        parent: QWidget | None = None,
        settings_file: Path | None = None,
        hub_store: ProjectHubStore | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store or ShellStore()
        self.settings_file = settings_file or _resolve_settings_file_path()
        self._saved_workspace_state: bytes | None = None
        self._saved_workspace_docks_visibility: dict[str, bool] = {}
        self._current_screen_mode: ScreenMode | None = None
        self._has_restored_geometry: bool = False
        self._is_rendering: bool = False
        self._saved_bv_prefs: tuple[frozenset[TreeOverlay], tuple[TreeColumn, ...]] | None = None
        self._custom_hub_store = hub_store

        self.resize(1600, 950)
        self.setMinimumSize(1024, 680)

        self._init_ui()
        self._setup_menus()
        self.store.subscribe(self.render)
        self.render(self.store.state)

    def _init_ui(self) -> None:
        self.stacked_widget = QStackedWidget(self)
        self.setCentralWidget(self.stacked_widget)

        # Page 0: Project Hub (Launcher)
        if self._custom_hub_store is not None:
            self.hub_store = self._custom_hub_store
        elif self.settings_file != _resolve_settings_file_path():
            self.hub_store = ProjectHubStore(
                cache_file=self.settings_file.parent / "recent_projects.json"
            )
        else:
            self.hub_store = ProjectHubStore()
        self.hub_view = ProjectHubView(self.hub_store)
        self.hub_view.project_loaded.connect(self.store.open_project)
        self.stacked_widget.addWidget(self.hub_view)

        # Page 1: Workspace (SoundBank Viewer)
        self.workspace_container = QWidget()
        ws_layout = QVBoxLayout(self.workspace_container)
        ws_layout.setContentsMargins(0, 0, 0, 0)
        ws_layout.setSpacing(0)

        self.bank_viewer_store = BankViewerStore()
        self.bank_viewer_view = BankViewerView(self.bank_viewer_store)
        ws_layout.addWidget(self.bank_viewer_view, 1)

        self.transport_store = AudioTransportStore()
        self.transport_bar = AudioTransportBar(self.transport_store)
        ws_layout.addWidget(self.transport_bar, 0)

        # Audio Sources Dock with dedicated independent audio transport
        self.audio_sources_transport_store = AudioTransportStore()
        self.audio_sources_store = AudioSourcesStore()
        self.audio_sources_view = AudioSourcesView(
            self.audio_sources_store, transport_store=self.audio_sources_transport_store
        )
        self.audio_sources_dock = QDockWidget("Audio Sources", self)
        self.audio_sources_dock.setObjectName("AudioSourcesDock")
        self.audio_sources_dock.setWidget(self.audio_sources_view)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.audio_sources_dock)
        self.resizeDocks([self.audio_sources_dock], [420], Qt.Orientation.Horizontal)

        # Wire dock modification signals to capture layout adjustments
        self.audio_sources_dock.visibilityChanged.connect(self._on_dock_layout_modified)
        self.audio_sources_dock.dockLocationChanged.connect(self._on_dock_layout_modified)
        self.audio_sources_dock.topLevelChanged.connect(self._on_dock_layout_modified)

        # Wire splitter movements
        self.bank_viewer_view.splitter.splitterMoved.connect(lambda *_: self._on_splitter_moved())
        if hasattr(self.audio_sources_view, "splitter"):
            self.audio_sources_view.splitter.splitterMoved.connect(
                lambda *_: self._on_splitter_moved()
            )
        if hasattr(self.hub_view, "splitter"):
            self.hub_view.splitter.splitterMoved.connect(lambda *_: self._on_splitter_moved())

        self.coordinator = WorkspaceCoordinator(
            self.store,
            self.bank_viewer_store,
            self.transport_store,
            audio_sources_store=self.audio_sources_store,
            audio_sources_transport_store=self.audio_sources_transport_store,
        )
        self.bank_viewer_view.source_dropped.connect(self.coordinator.handle_source_dropped)
        self.bank_viewer_store.subscribe(self._on_bank_viewer_state_changed)
        self._saved_bv_prefs = (
            self.bank_viewer_store.state.active_overlays,
            self.bank_viewer_store.state.visible_columns,
        )
        self.stacked_widget.addWidget(self.workspace_container)

        # Restore layout geometry and dock states if present
        self._restore_ui_layout()

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

    def _on_dock_layout_modified(self, *_args) -> None:
        """Captures dock layout modifications in workspace mode and persists them."""
        if (
            not self._is_rendering
            and hasattr(self, "store")
            and self.store.state.screen_mode == ScreenMode.WORKSPACE
        ):
            self._saved_workspace_state = bytes(self.saveState().data())
            self._saved_workspace_docks_visibility = {
                "AudioSourcesDock": not self.audio_sources_dock.isHidden(),
            }
            self._save_ui_layout()

    def _on_splitter_moved(self) -> None:
        """Persists splitter movement to settings.json."""
        if not self._is_rendering:
            self._save_ui_layout()

    def _save_ui_layout(self) -> None:
        """Persists window geometry, dock layout state, and splitters to gitignored settings.json."""
        try:
            # Capture workspace dock state if currently in workspace
            if hasattr(self, "store") and self.store.state.screen_mode == ScreenMode.WORKSPACE:
                self._saved_workspace_state = bytes(self.saveState().data())
                self._saved_workspace_docks_visibility = {
                    "AudioSourcesDock": not self.audio_sources_dock.isHidden(),
                }

            layout_data: dict[str, object] = {
                "geometry": bytes(self.saveGeometry().data()).hex(),
                "state": (
                    self._saved_workspace_state.hex()
                    if self._saved_workspace_state
                    else bytes(self.saveState().data()).hex()
                ),
            }
            if self._saved_workspace_docks_visibility:
                layout_data["docks_visibility"] = self._saved_workspace_docks_visibility

            # Splitter states
            if hasattr(self, "bank_viewer_view") and hasattr(self.bank_viewer_view, "splitter"):
                layout_data["bank_viewer_splitter"] = bytes(
                    self.bank_viewer_view.splitter.saveState().data()
                ).hex()
            if hasattr(self, "audio_sources_view") and hasattr(self.audio_sources_view, "splitter"):
                layout_data["audio_sources_splitter"] = bytes(
                    self.audio_sources_view.splitter.saveState().data()
                ).hex()
            if hasattr(self, "hub_view") and hasattr(self.hub_view, "splitter"):
                layout_data["project_hub_splitter"] = bytes(
                    self.hub_view.splitter.saveState().data()
                ).hex()

            # Preserve other existing settings in settings.json
            existing: dict = {}
            if self.settings_file.is_file():
                try:
                    loaded = json.loads(self.settings_file.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        existing = loaded
                except (OSError, ValueError, json.JSONDecodeError):
                    existing = {}

            existing["ui_layout"] = layout_data
            if hasattr(self, "bank_viewer_store"):
                bv_state = self.bank_viewer_store.state
                existing["bank_viewer"] = {
                    "overlays": sorted(ov.value for ov in bv_state.active_overlays),
                    "columns": [col.value for col in bv_state.visible_columns],
                }
                self._saved_bv_prefs = (
                    bv_state.active_overlays,
                    bv_state.visible_columns,
                )

            if hasattr(self, "audio_sources_view") and hasattr(
                self.audio_sources_view, "tab_game_audio"
            ):
                existing["audio_sources"] = {
                    "game_audio_columns": [
                        c.value for c in self.audio_sources_view.tab_game_audio.visible_columns
                    ]
                }

            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            self.settings_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        except (OSError, ValueError):
            pass

    def _restore_ui_layout(self) -> None:
        """Restores window geometry, dock layout state, splitters, and viewer preferences from gitignored settings.json."""
        parsed: dict = {}
        if self.settings_file.is_file():
            try:
                raw_parsed = json.loads(self.settings_file.read_text(encoding="utf-8"))
                if isinstance(raw_parsed, dict):
                    parsed = raw_parsed
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                parsed = {}

        if hasattr(self, "bank_viewer_store") and isinstance(parsed.get("bank_viewer"), dict):
            bv_data = parsed["bank_viewer"]
            prev_rendering = self._is_rendering
            self._is_rendering = True
            try:
                if isinstance(bv_data.get("overlays"), list):
                    valid_ov = {o.value for o in TreeOverlay}
                    target_overlays = frozenset(
                        TreeOverlay(x)
                        for x in bv_data["overlays"]
                        if isinstance(x, str) and x in valid_ov
                    )
                    for ov in TreeOverlay:
                        is_active = ov in self.bank_viewer_store.state.active_overlays
                        should_be_active = ov in target_overlays
                        if is_active != should_be_active:
                            self.bank_viewer_store.set_tree_overlay(ov, should_be_active)

                if isinstance(bv_data.get("columns"), list):
                    valid_col = {c.value for c in TreeColumn}
                    target_cols = {
                        TreeColumn(x)
                        for x in bv_data["columns"]
                        if isinstance(x, str) and x in valid_col
                    } | {TreeColumn.NAME}
                    for col in TreeColumn:
                        is_vis = col in self.bank_viewer_store.state.visible_columns
                        should_be_vis = col in target_cols
                        if is_vis != should_be_vis:
                            self.bank_viewer_store.set_tree_column_visible(col, should_be_vis)

                self._saved_bv_prefs = (
                    self.bank_viewer_store.state.active_overlays,
                    self.bank_viewer_store.state.visible_columns,
                )
            finally:
                self._is_rendering = prev_rendering

        if (
            hasattr(self, "audio_sources_view")
            and hasattr(self.audio_sources_view, "tab_game_audio")
            and isinstance(parsed.get("audio_sources"), dict)
        ):
            as_data = parsed["audio_sources"]
            if isinstance(as_data.get("game_audio_columns"), list):
                valid_cols = {c.value for c in CatalogColumn}
                target_cols = tuple(
                    CatalogColumn(x)
                    for x in as_data["game_audio_columns"]
                    if isinstance(x, str) and x in valid_cols
                )
                if target_cols:
                    self.audio_sources_view.tab_game_audio.set_visible_columns(target_cols)

        data = parsed.get("ui_layout") or parsed
        if not data or not isinstance(data, dict):
            return

        try:
            if "geometry" in data and isinstance(data["geometry"], str):
                self._has_restored_geometry = bool(
                    self.restoreGeometry(bytes.fromhex(data["geometry"]))
                )
            if "state" in data and isinstance(data["state"], str):
                self._saved_workspace_state = bytes.fromhex(data["state"])
            if "docks_visibility" in data and isinstance(data["docks_visibility"], dict):
                self._saved_workspace_docks_visibility = {
                    str(k): bool(v) for k, v in data["docks_visibility"].items()
                }
            if (
                "bank_viewer_splitter" in data
                and isinstance(data["bank_viewer_splitter"], str)
                and hasattr(self, "bank_viewer_view")
                and hasattr(self.bank_viewer_view, "splitter")
            ):
                self.bank_viewer_view.splitter.restoreState(
                    bytes.fromhex(data["bank_viewer_splitter"])
                )
            if (
                "audio_sources_splitter" in data
                and isinstance(data["audio_sources_splitter"], str)
                and hasattr(self, "audio_sources_view")
                and hasattr(self.audio_sources_view, "splitter")
            ):
                self.audio_sources_view.splitter.restoreState(
                    bytes.fromhex(data["audio_sources_splitter"])
                )
            if (
                "project_hub_splitter" in data
                and isinstance(data["project_hub_splitter"], str)
                and hasattr(self, "hub_view")
                and hasattr(self.hub_view, "splitter")
            ):
                self.hub_view.splitter.restoreState(bytes.fromhex(data["project_hub_splitter"]))
        except (OSError, ValueError, KeyError):
            pass

    @property
    def has_restored_geometry(self) -> bool:
        """Returns True if window geometry was successfully restored from settings."""
        return self._has_restored_geometry

    def changeEvent(self, event) -> None:
        """Persists window geometry when window state changes (maximized / normalized)."""
        super().changeEvent(event)
        if (
            hasattr(self, "settings_file")
            and hasattr(event, "type")
            and event.type() == QEvent.Type.WindowStateChange
            and not getattr(self, "_is_rendering", False)
            and self.isVisible()
        ):
            self._save_ui_layout()

    def _update_undo_redo_actions(self) -> None:
        """Synchronizes Edit -> Undo and Redo actions with coordinator state."""
        if hasattr(self, "act_undo"):
            self.act_undo.setEnabled(self.coordinator.can_undo)
            self.act_undo.setStatusTip(self.coordinator.undo_status_tip)
        if hasattr(self, "act_redo"):
            self.act_redo.setEnabled(self.coordinator.can_redo)
            self.act_redo.setStatusTip(self.coordinator.redo_status_tip)

    def _on_bank_viewer_state_changed(self, bv_state: BankViewerState) -> None:
        """Synchronizes UI actions on bank viewer state changes."""
        self._update_undo_redo_actions()
        if (
            not self._is_rendering
            and (bv_state.active_overlays, bv_state.visible_columns) != self._saved_bv_prefs
        ):
            self._save_ui_layout()

    def keyPressEvent(self, event) -> None:
        """Global shortcuts: Space toggles Play/Pause when not editing text; Ctrl+Z/Y for Undo/Redo."""
        if event.matches(QKeySequence.StandardKey.Undo):
            focus = QApplication.focusWidget()
            if not isinstance(focus, QLineEdit):
                if self.coordinator.can_undo:
                    self._on_undo_triggered()
                    event.accept()
                    return
        elif event.matches(QKeySequence.StandardKey.Redo):
            focus = QApplication.focusWidget()
            if not isinstance(focus, QLineEdit):
                if self.coordinator.can_redo:
                    self._on_redo_triggered()
                    event.accept()
                    return

        if event.key() == Qt.Key.Key_Space:
            focus = QApplication.focusWidget()
            if not isinstance(focus, QLineEdit):
                if self.transport_store.state.status == PlaybackStatus.PLAYING:
                    self.transport_store.pause()
                elif self.transport_store.state.can_play:
                    self.transport_store.play()
                event.accept()
                return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        """Halt audio playback and persist UI layout cleanly when closing main window."""
        self.transport_store.stop()
        if hasattr(self, "audio_sources_transport_store"):
            self.audio_sources_transport_store.stop()
        if hasattr(self, "store") and self.store.state.screen_mode == ScreenMode.WORKSPACE:
            self._saved_workspace_state = bytes(self.saveState().data())
            self._saved_workspace_docks_visibility = {
                "AudioSourcesDock": not self.audio_sources_dock.isHidden(),
            }
        self._save_ui_layout()
        super().closeEvent(event)

    def _setup_menus(self) -> None:
        menubar = self.menuBar()

        # File Menu
        file_menu = menubar.addMenu("File")

        self.act_new_project = QAction("New Project...", self)
        self.act_new_project.setShortcut("Ctrl+N")
        self.act_new_project.triggered.connect(self._on_new_project_triggered)
        file_menu.addAction(self.act_new_project)

        self.act_open_project = QAction("Open Project...", self)
        self.act_open_project.setShortcut("Ctrl+O")
        self.act_open_project.triggered.connect(self._on_open_project_triggered)
        file_menu.addAction(self.act_open_project)

        file_menu.addSeparator()

        self.act_close_project = QAction("Close Project", self)
        self.act_close_project.triggered.connect(self.store.close_project)
        file_menu.addAction(self.act_close_project)

        file_menu.addSeparator()

        self.act_build_pack = QAction("Build Mod Pack", self)
        self.act_build_pack.setShortcut(QKeySequence("Ctrl+B"))
        self.act_build_pack.setStatusTip(
            "Compile staged audio and banks into a playable Total War Mod .pack"
        )
        self.act_build_pack.setEnabled(False)
        self.act_build_pack.triggered.connect(self._on_build_pack_triggered)
        file_menu.addAction(self.act_build_pack)

        self.act_build_and_copy = QAction("Build and Copy to Game Data", self)
        self.act_build_and_copy.setShortcut(QKeySequence("Ctrl+Shift+B"))
        self.act_build_and_copy.setStatusTip(
            "Compile mod pack and copy directly to the target game data directory"
        )
        self.act_build_and_copy.setEnabled(False)
        self.act_build_and_copy.triggered.connect(self._on_build_and_copy_triggered)
        file_menu.addAction(self.act_build_and_copy)

        self.act_pack_settings = QAction("Pack Settings...", self)
        self.act_pack_settings.setStatusTip("Configure target mod pack output path and presets")
        self.act_pack_settings.setEnabled(False)
        self.act_pack_settings.triggered.connect(self._on_pack_settings_triggered)
        file_menu.addAction(self.act_pack_settings)

        self.act_manage_dependencies = QAction("Manage Mod Dependencies...", self)
        self.act_manage_dependencies.setStatusTip(
            "Add, remove, or reorder external mod pack dependencies and reload metadata"
        )
        self.act_manage_dependencies.setEnabled(False)
        self.act_manage_dependencies.triggered.connect(self._on_manage_dependencies_triggered)
        file_menu.addAction(self.act_manage_dependencies)

        file_menu.addSeparator()

        self.act_exit = QAction("Exit", self)
        self.act_exit.setShortcut("Ctrl+Q")
        self.act_exit.triggered.connect(self.close)
        file_menu.addAction(self.act_exit)

        # Edit Menu
        edit_menu = menubar.addMenu("Edit")

        self.act_undo = QAction("Undo", self)
        self.act_undo.setShortcuts(
            [QKeySequence(QKeySequence.StandardKey.Undo), QKeySequence("Alt+Left")]
        )
        self.act_undo.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.act_undo.setStatusTip("Undo last selection or view navigation")
        self.act_undo.setEnabled(False)
        self.act_undo.triggered.connect(self._on_undo_triggered)
        edit_menu.addAction(self.act_undo)
        self.addAction(self.act_undo)

        self.act_redo = QAction("Redo", self)
        self.act_redo.setShortcuts(
            [
                QKeySequence(QKeySequence.StandardKey.Redo),
                QKeySequence("Alt+Right"),
                QKeySequence("Ctrl+Shift+Z"),
            ]
        )
        self.act_redo.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.act_redo.setStatusTip("Redo last selection or view navigation")
        self.act_redo.setEnabled(False)
        self.act_redo.triggered.connect(self._on_redo_triggered)
        edit_menu.addAction(self.act_redo)
        self.addAction(self.act_redo)

        # View Menu
        view_menu = menubar.addMenu("View")
        self.act_toggle_audio_sources = self.audio_sources_dock.toggleViewAction()
        self.act_toggle_audio_sources.setText("Audio Sources")
        view_menu.addAction(self.act_toggle_audio_sources)

        # Help Menu
        help_menu = menubar.addMenu("Help")
        self.act_disclaimer = QAction("AI Disclaimer & About...", self)
        self.act_disclaimer.setStatusTip(
            "View AI development notice, experimental status, and contribution guide"
        )
        self.act_disclaimer.triggered.connect(self._on_disclaimer_triggered)
        help_menu.addAction(self.act_disclaimer)

        self.act_changelog = QAction("Changelog...", self)
        self.act_changelog.setStatusTip("View release history and changes")
        self.act_changelog.triggered.connect(self._on_changelog_triggered)
        help_menu.addAction(self.act_changelog)

        help_menu.addSeparator()

        self.act_github = QAction("GitHub Repository...", self)
        self.act_github.setStatusTip("Open PyWarscape Sound project on GitHub")
        self.act_github.triggered.connect(self._on_open_github_triggered)
        help_menu.addAction(self.act_github)

    def should_show_disclaimer(self) -> bool:
        """Determines if the first-run AI disclaimer should be presented."""
        if not self.settings_file.is_file():
            return True
        try:
            raw = json.loads(self.settings_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return not bool(raw.get("disclaimer_acknowledged", False))
        except (OSError, ValueError, json.JSONDecodeError):
            return True
        return True

    def _set_disclaimer_acknowledged(self, acknowledged: bool) -> None:
        """Records disclaimer acknowledgement in settings.json."""
        try:
            existing: dict = {}
            if self.settings_file.is_file():
                try:
                    loaded = json.loads(self.settings_file.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        existing = loaded
                except (OSError, ValueError, json.JSONDecodeError):
                    existing = {}
            existing["disclaimer_acknowledged"] = acknowledged
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            self.settings_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        except (OSError, ValueError):
            pass

    def show_disclaimer_dialog(self, is_first_run: bool = True) -> None:
        """Displays modal AI-assisted development notice."""
        from src.ui.shell.disclaimer_dialog import DisclaimerDialog

        dialog = DisclaimerDialog(self, is_first_run=is_first_run)
        if dialog.exec() and is_first_run and dialog.dont_show_again:
            self._set_disclaimer_acknowledged(True)

    def _on_disclaimer_triggered(self) -> None:
        """Opens AI disclaimer dialog from Help menu."""
        self.show_disclaimer_dialog(is_first_run=False)

    def _on_changelog_triggered(self) -> None:
        """Opens ChangelogDialog from Help menu."""
        from src.ui.shell.disclaimer_dialog import ChangelogDialog

        dialog = ChangelogDialog(self)
        dialog.exec()

    def _on_open_github_triggered(self) -> None:
        """Opens GitHub repository in default browser."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from src.ui.shell.disclaimer_dialog import GITHUB_REPO_URL

        QDesktopServices.openUrl(QUrl(GITHUB_REPO_URL))

    def _on_undo_triggered(self) -> None:
        self.coordinator.trigger_undo()
        self._update_undo_redo_actions()

    def _on_redo_triggered(self) -> None:
        self.coordinator.trigger_redo()
        self._update_undo_redo_actions()

    def _on_new_project_triggered(self) -> None:
        """Opens Project Wizard modal dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("New Project Wizard")
        dialog.setMinimumSize(820, 600)
        d_layout = QVBoxLayout(dialog)
        d_layout.setContentsMargins(0, 0, 0, 0)

        wiz_store = ProjectWizardStore()
        wiz_view = ProjectWizardView(wiz_store)
        wiz_view.project_created.connect(
            lambda proj: (dialog.accept(), self.store.open_project(proj))
        )
        d_layout.addWidget(wiz_view)
        dialog.exec()

    def _is_copy_to_game_enabled(self, proj) -> bool:
        """Checks if copy to game data folder is enabled in settings.json for the active project."""
        if not self.settings_file.is_file():
            return False
        try:
            data = json.loads(self.settings_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                projects = data.get("projects_config", {})
                proj_conf = projects.get(str(proj.root_dir), {})
                return bool(proj_conf.get("copy_to_game_data", False))
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        return False

    def _on_build_pack_triggered(self) -> None:
        """Compiles active project into a PFH4 Mod pack in project directory with user feedback."""
        proj = self.coordinator.active_project
        if proj is None:
            return

        if not proj.manifest.output_pack_path:
            self._on_pack_settings_triggered()
            return

        self._build_pack_impl(copy_to_game=None)

    def _on_build_and_copy_triggered(self) -> None:
        """Compiles active project into a PFH4 Mod pack and copies to game data directory."""
        proj = self.coordinator.active_project
        if proj is None:
            return

        if not proj.manifest.output_pack_path:
            self._on_pack_settings_triggered()
            return

        self._build_pack_impl(copy_to_game=True)

    def _build_pack_impl(self, copy_to_game: bool | None = None) -> None:
        proj = self.coordinator.active_project
        if proj is None:
            return

        # Default destination to project root if not configured
        if not proj.manifest.output_pack_path:
            proj.set_output_pack_path(proj.resolve_default_pack_path())

        should_copy = copy_to_game
        if should_copy is None:
            should_copy = self._is_copy_to_game_enabled(proj)

        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            copied_to = None
            try:
                out_path = self.coordinator.compile_mod_pack()
                if should_copy:
                    copied_to = proj.copy_pack_to_game_data(out_path)
            finally:
                QApplication.restoreOverrideCursor()

            count_banks = len(proj.manifest.modified_banks)
            count_wems = len(proj.manifest.staged_wems)
            msg = (
                f"Compiled mod pack: {out_path.name} ({count_banks} banks, {count_wems} loose WEMs)"
            )
            if copied_to is not None:
                msg += f" -> copied to {copied_to.parent.name}/"
            elif should_copy and copied_to is None:
                msg += " (game data directory not found to copy)"
            self.status_bar.showMessage(msg, 10000)
        except Exception as exc:
            self.status_bar.showMessage(f"Failed to build mod pack: {exc}", 10000)

    def _on_pack_settings_triggered(self) -> None:
        """Opens PackSettingsDialog."""
        proj = self.coordinator.active_project
        if proj is None:
            return

        from src.ui.shell.pack_settings_dialog import PackSettingsDialog

        dialog = PackSettingsDialog(proj, self)
        dialog.pack_built.connect(
            lambda out_path: self.status_bar.showMessage(
                f"Compiled mod pack: {out_path.name}", 10000
            )
        )
        dialog.exec()

    def _on_manage_dependencies_triggered(self) -> None:
        """Opens DependencyManagerDialog to add, remove, or reorder dependencies."""
        proj = self.coordinator.active_project
        if proj is None:
            return

        from src.ui.shell.dependency_manager_dialog import DependencyManagerDialog

        dialog = DependencyManagerDialog(proj, coordinator=self.coordinator, parent=self)
        dialog.exec()

    def _on_open_project_triggered(self) -> None:
        """Opens directory picker for existing project."""
        loc = QFileDialog.getExistingDirectory(self, "Open Audio Project Directory")
        if loc:
            proj = self.store.open_project_by_path(loc)
            if proj is not None and hasattr(self, "hub_store"):
                try:
                    self.hub_store.open_existing_project(loc)
                except (OSError, ValueError, KeyError) as err:
                    logger.warning("Could not update recent projects cache: %s", err)

    def render(self, state: ShellState) -> None:
        """Projects shell state onto window title, stacked widget, and menus."""
        self.blockSignals(True)
        self._is_rendering = True
        try:
            self.setWindowTitle(state.window_title)

            # If switching away from workspace to launcher, preserve workspace dock layout
            if (
                self._current_screen_mode == ScreenMode.WORKSPACE
                and state.screen_mode != ScreenMode.WORKSPACE
            ):
                self._saved_workspace_state = bytes(self.saveState().data())
                self._saved_workspace_docks_visibility = {
                    "AudioSourcesDock": not self.audio_sources_dock.isHidden(),
                }
                self._save_ui_layout()

            if state.screen_mode == ScreenMode.WORKSPACE:
                self.act_close_project.setEnabled(True)
                if hasattr(self, "act_build_pack"):
                    self.act_build_pack.setEnabled(True)
                if hasattr(self, "act_build_and_copy"):
                    self.act_build_and_copy.setEnabled(True)
                if hasattr(self, "act_pack_settings"):
                    self.act_pack_settings.setEnabled(True)
                if hasattr(self, "act_manage_dependencies"):
                    self.act_manage_dependencies.setEnabled(True)
                if self.stacked_widget.currentIndex() != 1:
                    self.stacked_widget.setCurrentIndex(1)
                self._update_undo_redo_actions()
                if self._current_screen_mode != ScreenMode.WORKSPACE:
                    if self._saved_workspace_state:
                        self.restoreState(self._saved_workspace_state)
                        if self._saved_workspace_docks_visibility:
                            if "AudioSourcesDock" in self._saved_workspace_docks_visibility:
                                self.audio_sources_dock.setVisible(
                                    self._saved_workspace_docks_visibility["AudioSourcesDock"]
                                )
                    else:
                        if (
                            hasattr(self, "audio_sources_dock")
                            and self.audio_sources_dock.isHidden()
                        ):
                            self.audio_sources_dock.show()
                self._current_screen_mode = ScreenMode.WORKSPACE
            else:
                self.act_close_project.setEnabled(False)
                if hasattr(self, "act_build_pack"):
                    self.act_build_pack.setEnabled(False)
                if hasattr(self, "act_build_and_copy"):
                    self.act_build_and_copy.setEnabled(False)
                if hasattr(self, "act_pack_settings"):
                    self.act_pack_settings.setEnabled(False)
                if hasattr(self, "act_manage_dependencies"):
                    self.act_manage_dependencies.setEnabled(False)
                if hasattr(self, "act_undo"):
                    self.act_undo.setEnabled(False)
                if hasattr(self, "act_redo"):
                    self.act_redo.setEnabled(False)
                if self.stacked_widget.currentIndex() != 0:
                    self.stacked_widget.setCurrentIndex(0)
                if hasattr(self, "audio_sources_dock"):
                    self.audio_sources_dock.hide()
                self._current_screen_mode = ScreenMode.LAUNCHER

            msg = state.status_message or "Ready"
            if state.screen_mode == ScreenMode.WORKSPACE:
                proj = getattr(self.coordinator, "active_project", None)
                if proj is not None and proj.manifest.modified_banks:
                    count = len(proj.manifest.modified_banks)
                    bank_word = "bank" if count == 1 else "banks"
                    msg = f"{msg} | {count} modified {bank_word}"
            self.status_bar.showMessage(msg)
        finally:
            self._is_rendering = False
            self.blockSignals(False)
