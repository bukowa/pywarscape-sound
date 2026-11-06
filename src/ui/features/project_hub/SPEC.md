# src/ui/features/project_hub
Welcome launcher and mod project management feature slice.
Serves as the application startup hub for game detection, cache building, and opening recent projects.
- `causation.py`: Pure state transitions (`reconcile_project_hub`) for game selection and cache build updates.
- `state.py`: Immutable state models (`ProjectHubState`, `RecentProjectItem`) tracking project history and cache readiness.
- `store.py`: Headless `ProjectHubStore` managing game discovery, recent project persistence, and game cache building.
- `view.py`: `ProjectHubView` PySide6 projection widget displaying game installation status and recent project lists.
