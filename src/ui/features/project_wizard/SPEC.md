# src/ui/features/project_wizard
Multi-step project onboarding wizard feature slice.
Guides modders through new project setup, base mod pack selection, health diagnostics, and dependency extraction.
- `causation.py`: Pure state transitions (`reconcile_project_wizard`) driving step navigation and pack list reordering.
- `state.py`: Immutable state models (`ProjectWizardState`, `WizardStep`, `ModPackEntry`).
- `store.py`: Headless `ProjectWizardStore` managing project creation, pack health scanning, and background extraction.
- `view.py`: `ProjectWizardView` stacked PySide6 wizard dialog presenting setup options, pack selection, and progress bars.
