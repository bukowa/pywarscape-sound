# src/ui/shell
Main application shell and multi-store workspace coordinator (Layer 4).
Hosts the primary desktop window, dock widgets, and routes cross-feature events between stores without coupling.
- `causation.py`: Pure state transition reducer (`reconcile_shell`) for shell lifecycle events.
- `coordinator.py`: Headless `WorkspaceCoordinator` connecting BankViewer, AudioSources, and Transport stores.
- `dependency_manager_dialog.py`: `DependencyManagerDialog` modal dialog for inspecting, adding, removing, and reordering external mod pack dependencies.
- `disclaimer_dialog.py`: `DisclaimerDialog` notice on AI assistance and `ChangelogDialog` release log viewer.
- `pack_settings_dialog.py`: `PackSettingsDialog` modal dialog configuring target mod pack output paths and presets.
- `state.py`: Immutable shell state models (`ShellState`, `ScreenMode`, `ProjectOpened`, `ProjectClosed`).
- `store.py`: Headless `ShellStore` managing project open/close workflows and dispatching shell events.
- `view.py`: `MainWindow` PySide6 desktop window hosting the launcher, docks, status bar, and menus.
