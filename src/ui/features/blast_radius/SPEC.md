# src/ui/features/blast_radius
Blast radius inspection and audio replacement confirmation modal dialog feature slice.
Presents shared WEM reference impact tables, embedded-to-streamed promotion notices, and binary Overwrite vs Isolate/Fork choices.
- `__init__.py`: Package exports (`BlastRadiusDialog`, `BlastRadiusStore`, `check_replacement_branch`).
- `causation.py`: Pure state transition reducer (`reconcile_blast_radius`) handling user action choices.
- `state.py`: Immutable state models (`BlastRadiusState`, `BlastRadiusImpactItem`, `BlastRadiusMode`, `BlastRadiusAction`).
- `store.py`: Headless `BlastRadiusStore` and `check_replacement_branch` workflow controller hook.
- `view.py`: `BlastRadiusDialog` PySide6 modal dialog rendering the 5-column impact table and replacement mode controls.
