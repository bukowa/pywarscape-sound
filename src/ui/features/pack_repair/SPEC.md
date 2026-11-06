# src/ui/features/pack_repair
Mod pack health diagnostics and soundbank auto-repair modal dialog feature slice.
Surfaces detected binary corruptions (e.g. word-swapped automation points, bad headers) and allows selective one-click fixes.
- `causation.py`: Pure state transition reducer (`reconcile_pack_repair`) handling item selection and batch toggling.
- `state.py`: Immutable state models (`PackRepairState`, `RepairItemState`) describing detected health defects.
- `store.py`: Headless `PackRepairStore` translating `PackHealthReport` findings into selectable repair actions.
- `view.py`: `PackRepairDialog` PySide6 modal dialog presenting diagnostic issues and repair action triggers.
