---
name: mutation-engine
description: |
  Plan, apply, or roll back audio mutations, WEM replacements, and SoundBank graph transformations. Use when modifying the two-phase mutation pipeline (ontology, planner, effectuator), WorkspaceSession undo/redo history, or engine port boundaries in Layer 2 (src/engine/).

  Trigger for:
  - Audio mutation planning in src/engine/planner.py (plan_audio_replacement, plan_batch)
  - Mutation intent execution in src/engine/effectuator.py
  - Domain mutation ontology in src/engine/ontology.py (MutationBatch, AudioMutationPlan, ReplacementScope)
  - WorkspaceSession state management or Undo/Redo in src/engine/session.py
  - Engine port interfaces in src/engine/ports.py (AudioProjectPort, AssetResolverPort)
  - Audio catalog discovery and indexing in src/engine/catalog_discovery.py
  - Audio metadata and catalog models in src/models/catalog.py (AudioCatalogEntry, AudioMetadataCatalog)
  - Graph indexing and WEM reference tracking in src/engine/graph.py (BankGraphIndex)
  - Structural bank diffing in src/engine/diff.py (BankDiffResult, diff_soundbanks)

  DO NOT trigger for:
  - Low-level binary chunk or HIRC AST parsing (use bnk-binary skill)
  - UI stores, views, or widgets (use feature-slice skill)
  - Disk project directory layout or manifest persistence (handled in src/workspace/)
  - Direct PySide6 GUI interactions or events
---

# Audio Mutation Engine (`src/engine`)

Layer 2 coordinates two-phase atomic audio mutations, graph indexing, and transactional Undo/Redo history across SoundBanks and project media.

## Read-First Files
- `src/engine/SPEC.md`: Two-phase mutation pipeline rules and session lifecycle.
- `src/engine/ontology.py`: Pure immutable intents, replacement scopes, and snapshots.
- `src/engine/planner.py`: Pure functional planner validating mutations and allocating IDs.
- `src/engine/effectuator.py`: Imperative dispatcher executing planned intents.
- `src/engine/session.py`: Primary domain façade (`WorkspaceSession`) managing banks and undo stacks.
- `src/engine/ports.py`: Decoupling protocols (`AudioProjectPort`, `AssetResolverPort`).
- `src/engine/graph.py`: Bidirectional HIRC relationship and WEM index (`BankGraphIndex`).
- `src/engine/catalog_discovery.py`: Discovers and indexes bank and workspace audio assets.
- `src/engine/diff.py`: Structural AST difference calculator (`BankDiffResult`, `diff_soundbanks`).
- `src/models/catalog.py`: Catalog entries (`AudioCatalogEntry`) and DB metadata models.

## Invariants
1. **Strict Layer Boundary:** `src/engine/` is Layer 2. It must **NEVER** import from Layer 3 (`src.workspace.*`) or Layer 4 (`PySide6`, `src.ui.*`). It interacts with projects strictly through `AudioProjectPort` and `AssetResolverPort`.
2. **Two-Phase Atomic Execution:** Mutations are planned first into an immutable `AudioMutationPlan` or rejected with `PlanRejection`. Mutations are never applied partially or directly to ASTs without a plan.
3. **Strongly-Typed Undo/Redo Snapshots:** Undo/Redo records store typed snapshots:
   - Bank changes capture `BankBatchSnapshot` (storing original bank bytes and staged file paths).
   - Media changes capture `MediaTargetSnapshot` (storing target WEM ID and original bytes).
   - Records use discriminated union kinds: `MutationRecord.kind` (`"bank" | "media"`).
4. **Stream Promotion:** When replacing embedded audio, the node is promoted to streamed (`stream_type = 2`), and a loose `.wem` file is staged into `pack_root/audio/<id>.wem`.
5. **Interactive Music Offset Recalculation:** Replacing a music track recalculates its duration, lookahead, and clip marker boundaries automatically.

## Core Mutation Intents (`src/engine/ontology.py`)
| Intent | Target Layer | Role |
|---|---|---|
| `StageMasterAudioIntent` | Disk | Copies imported source audio (`.wav`) into `source_audio/` |
| `StageLooseWemIntent` | Disk | Writes transcoded 32kHz mono PCM `.wem` to `pack_root/audio/` |
| `UpdateSoundNodeIntent` | Bank AST | Changes `CAkSound.stream_type` from embedded (0) to streamed (2) |
| `CopyMediaBytesIntent` | Disk | Duplicates existing cached WEM bytes to a new isolated ID |
| `SyncMusicTimelineIntent` | Bank AST | Recalculates `CAkMusicTrack` duration and clip boundaries |

## Key Concepts and Data Structures
- `WorkspaceSession`: Manages loaded SoundBanks, active graph indices, and undo/redo stacks (`undo()`, `redo()`, `apply_batch()`).
- `ReplacementScope.ALL_INSTANCES`: Overwrites the audio source across all referencing nodes in the bank.
- `ReplacementScope.ISOLATE_COPY`: Allocates a new unique WEM ID using `allocate_unique_wem_id()`, isolates the target node, and preserves other references.
- `AudioCatalogEntry`: Rich indexed view connecting sound nodes, WEM IDs, event names, and DB metadata.
- `BankGraphIndex`: In-memory graph providing `objects_by_id`, `parents_by_id`, and `wem_references` for blast-radius analysis.
- `BankDiffResult`: Summarizes added, modified, and removed HIRC objects when comparing active banks to vanilla baselines.
- `BankBatchSnapshot`: Stores original binary bank bytes and staged file paths for exact transactional rollback.
- `MediaTargetSnapshot`: Captures original embedded/streamed media bytes before leaf node replacement.

## Step-by-Step Checklist
1. **Define Intent:** If introducing a new mutation type, define an immutable dataclass in `src/engine/ontology.py` implementing `MutationIntent`.
2. **Implement Planning Rule:** Add the validation and intent generation logic in `src/engine/planner.py`. Ensure planners remain pure (zero I/O, zero `raise`).
3. **Implement Effectuation:** Add the imperative execution handler in `src/engine/effectuator.py`. Use transaction rollback if any step fails.
4. **Capture Undo Snapshot:** Ensure `WorkspaceSession.apply_batch` creates a valid `BankBatchSnapshot` or `MediaTargetSnapshot` before applying the plan.
5. **Update Graph Index:** Call `BankGraphIndex.build(bank)` on modified banks to maintain accurate WEM reference counts and hierarchy links.
6. **Verify Parity:** Test that applying a mutation and calling `undo()` restores bit-exact bank bytes and cleans up staged files.

## Anti-Patterns
- **Importing src.workspace:** Never import `AudioProject`, `DependencyManager`, or `ProjectStorage` directly into `src/engine/`. Use `ports.py`.
- **Mutating ASTs during planning:** Planning must be completely pure. Only the effectuator may mutate AST nodes or write files.
- **Leaking Qt objects:** Engine models and session methods must have zero references to `PySide6` signals, slots, or widgets.
- **Untyped undo data:** Do not use raw tuples or untyped dictionaries for undo history; always use typed snapshot structures.

## Verification Commands
```bash
uv run ruff format src scripts tests
uv run ruff check --fix src scripts tests
uv run ty check src
uv run scripts/arch_guard.py; uv run pytest tests/test_cleanliness.py -q
uv run pytest tests/test_audio_mutation_planner.py -q
uv run pytest tests/test_mutation_undo.py -q
uv run pytest tests/test_media_replacement.py -q
```
