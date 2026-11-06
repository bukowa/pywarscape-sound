---
name: feature-slice
description: |
  Create, modify, or maintain 4-file MVU UI feature slices and shell modules under src/ui/features/<slice>/ and src/ui/shell/. Use when working on UI state, causation reducers, headless stores, or PySide6 views.

  Trigger for:
  - Any 4-file UI slice under src/ui/features/ (project_hub, project_wizard, bank_viewer, audio_sources, audio_transport, pack_repair, blast_radius)
  - Application shell and multi-store coordinator in src/ui/shell/ (state, causation, store, view, coordinator)
  - Pure state reducers in causation.py (reconcile_*, match event:, assert_never)
  - Headless UI stores in store.py and intent execution
  - PySide6 widget rendering in view.py and render(state) methods
  - Design system tokens and styling from src/ui/theme.py

  DO NOT trigger for:
  - Low-level binary chunk or HIRC AST parsing (use bnk-binary skill)
  - Audio mutation planning or effectuation in the engine (use mutation-engine skill)
  - Non-UI workspace storage or project serialization (handled in src/workspace/)
  - Direct database binary table decoding (handled in src/models/)
---

# UI Feature Slices (`src/ui/features/<slice>` and `src/ui/shell`)

Every UI feature slice in Layer 4 is strictly structured into 4 cohesive files plus a directory `SPEC.md`. It follows a Model-View-Update (MVU) unidirectional data flow pattern.

## Read-First Files
- `src/ui/SPEC.md`: UI layer design system rules and styling guidelines.
- `src/ui/theme.py`: Theme tokens (`COLOR_*`, `BTN_STYLE_*`, `INPUT_STYLE`, `apply_theme`).
- `src/ui/shell/coordinator.py`: `WorkspaceCoordinator` wiring stores together.
- Target slice files: `state.py`, `causation.py`, `store.py`, `view.py`, and `SPEC.md`.

## Active Feature Slices
| Slice Directory | Role and Responsibility |
|---|---|
| `project_hub/` | Welcome screen, recent projects list, quick actions |
| `project_wizard/` | Multi-step dialog creating new audio projects |
| `bank_viewer/` | SoundBank tree navigation, node inspection, audio preview |
| `audio_sources/` | External audio file import, staging, and transcoding |
| `audio_transport/` | Persistent bottom audio playback bar, seek, volume controls |
| `pack_repair/` | Headless bank validation, health issues report, repair actions |
| `blast_radius/` | Impact analysis dialog for shared WEM replacements |

## The 4-File Architecture
1. **`state.py` / `structs.py`**: Immutable dataclasses (`frozen=True, slots=True`) modeling state, event types (discriminated union), and `*Intent` classes.
2. **`causation.py`**: Pure reducer function `reconcile_<feature>(state, event) -> tuple[State, tuple[Intent, ...]]`. Zero I/O, zero `raise`, zero Qt imports.
3. **`store.py`**: Headless Python class maintaining state, running `reconcile_*`, executing returned intents against `WorkspaceSession`/services, and notifying the view via Qt signals.
4. **`view.py`**: PySide6 widget. Dispatches user actions as events to `store.dispatch(event)`. Re-renders UI state exclusively inside `render(state: State)`.

## Canonical Pattern Implementations
```python
# causation.py: Pure reducer with exhaustive pattern matching
def reconcile_feature(
    state: FeatureState, event: FeatureEvent
) -> tuple[FeatureState, tuple[FeatureIntent, ...]]:
    match event:
        case SelectionChanged(node_id):
            return _on_selection_changed(state, node_id)
        case ActionTriggered():
            return _on_action_triggered(state)
        case _ as unreachable:
            assert_never(unreachable)


# store.py: Headless store dispatching to pure reducer
class FeatureStore:
    def dispatch(self, event: FeatureEvent) -> None:
        self._state, intents = reconcile_feature(self._state, event)
        for intent in intents:
            self._execute_intent(intent)
        self.state_changed.emit(self._state)
```

## Invariants
1. **Zero PySide6 in Headless Modules:** `state.py`, `structs.py`, `causation.py`, `store.py`, and `coordinator.py` must contain **ZERO `PySide6` imports**. (Enforced by `scripts/arch_guard.py`).
2. **Pure Reducers:** `causation.py` must be completely deterministic and pure: no network, no disk I/O, no exception raising.
3. **Exhaustive Event Matching:** Reducers must use `match event:` and terminate with `case _ as unreachable: assert_never(unreachable)` from `typing`. Keep functions under 120 lines by delegating to intra-module `_on_<event_name>` helper functions.
4. **Every Intent Handled:** Every `*Intent` yielded by a reducer must be explicitly executed in `store._execute_intent(intent)` or mapped to an engine/session action.
5. **No Hardcoded Hex Colors:** Views must **NEVER** use hardcoded `#RRGGBB` color strings. All colors, borders, and styles must be imported from `src/ui/theme.py`.
6. **Strict View Encapsulation:** `view.py` must never access private `store._*` attributes. Widget state is updated strictly through `view.render(state)`.
7. **Signal Blocking on Render:** Wrap programmatic updates to checkboxes, sliders, and inputs with `.blockSignals(True)` / `.blockSignals(False)` to prevent infinite feedback loops.
8. **Virtualization for Large Tables:** For tables containing over 200 rows, use `QTableView` with a virtualized `QAbstractTableModel`.

## Step-by-Step Checklist
1. **State & Events:** Define the immutable state and discriminated event union in `state.py`.
2. **Pure Reducer:** Implement the reducer transition in `causation.py` with exhaustive pattern matching and `assert_never`.
3. **Store Wiring:** Add intent execution in `store.py`, binding inputs to the store's public dispatch methods.
4. **View Rendering:** Implement widget layout and update `render(state)` in `view.py`, consuming colors exclusively from `theme.py`.
5. **Update SPEC.md:** Ensure the slice's `SPEC.md` documents all key types and exported signals.

## Anti-Patterns
- **Importing PySide6 in causation/state/store:** Strictly forbidden; keep business logic headless.
- **Mutating widgets outside render():** Do NOT alter widget text or checkboxes inside button click callbacks; dispatch an event and wait for `render(state)`.
- **Calling other stores directly:** Stores must never import or reference each other; route cross-store coordination through `src/ui/shell/coordinator.py`.
- **Missing SPEC.md:** Every slice directory must have a valid `SPEC.md` passing `scripts/arch_guard.py`.

## Verification Commands
```bash
uv run ruff format src scripts tests
uv run ruff check --fix v3 scripts tests
uv run ty check src
uv run scripts/arch_guard.py; uv run pytest tests/src/test_v3_cleanliness.py -q
uv run pytest tests/src/ -k "causation" -q
```
