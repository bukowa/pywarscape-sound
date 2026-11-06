# Test Suite & Synthetic Test Architecture

## Overview
The test suite validates the 4-layer architecture of the application:
- **Layer 1: AST Core** (`src/bnk/`, `src/models/`, `src/compiler/pfh4_pack.py`)
- **Layer 2: Engine & Audio Pipeline** (`src/engine/`, `src/compiler/converter.py`, `src/deps/`)
- **Layer 3: Workspace & Session** (`src/workspace/`, `src/engine/session.py`)
- **Layer 4: UI Feature Slices & Shell** (`src/ui/`)

---

## Hermetic Synthetic Test Architecture
All feature logic, mutation planning, effectuation, UI state flows, dependency resolution, and pack repair tests run **100% hermetically** without requiring any game installations or external asset files.

Hermetic fixtures and generators are centralized in `tests/support/factories.py`:

| Factory Helper | Purpose |
| :--- | :--- |
| `make_synthetic_wav(path, duration_s, sample_rate, tone)` | Generates valid uncompressed mono PCM RIFF WAV audio files for test feeds. |
| `make_audio_project(root_dir, name, game, description)` | Creates an isolated `AudioProject` workspace with valid directory layout. |
| `encode_binary_db_table(table_type, rows, version, guid)` | Dynamically serializes dictionary rows into Total War binary DB tables matching `TABLE_SCHEMAS`. |
| `write_synthetic_pfh4_pack(pack_path, files, pack_type)` | Constructs and serializes Total War PFH4 `.pack` archives containing arbitrary file hierarchies. |

---

## Test Execution

### Hermetic Test Suite (Out-of-the-Box)
Runs all unit, integration, and UI tests that do not depend on external retail game assets:

```powershell
uv run pytest tests -m "not assets" -q
```

### Full Test Suite
Runs all tests, automatically skipping tests that require external vanilla retail files if the game cache is not populated:

```powershell
uv run pytest tests -q
```

### Single Test File
```powershell
uv run pytest tests/test_media_replacement.py -q
```

---

## Optional Retail Game Cache Verification (`@pytest.mark.assets`)
A subset of tests verify bit-exact binary round-tripping and schema coverage against retail vanilla game files:
- **Scope**: `.cache/attila/` and `.cache/rome_2/` SoundBanks (`*.bnk`), databases (`event_data.dat`), and decoded DB tables (`db/*`).
- **Marker**: Decorated with `@pytest.mark.assets`.
- **Skip vs. Fail**: Tests use `skip_or_fail_missing_asset(reason)`. When retail game assets are absent locally, these tests cleanly skip.
- **Strict CI Verification**: Setting `REQUIRE_GAME_DATA=1` turns skips into test failures to ensure CI nodes with extracted game data strictly verify all retail assets:

```powershell
$env:REQUIRE_GAME_DATA = "1"
uv run pytest tests -q
```

---

## Live Game Integration Testing (`@pytest.mark.live`)
Before committing changes affecting SoundBanks, packing, audio pipelines, or game models, run live game integration tests against a local Total War: Attila installation:
- **Scope**: Compiles a real mod pack with external audio (`ExternalFileSource`) and silence muting (`SilentStubSource`), deploys to `data/` as `PT_MOD`, registers in `user.script.txt`, launches `Attila.exe`, applies CPU affinity workaround, and monitors process health and crash reports.
- **Rule**: Must be run before committing whenever a local game installation is detected.
- **Execution via Pytest**:
  ```powershell
  uv run pytest tests/test_live_game.py -m live -q
  ```
- **Execution via Standalone Script**:
  ```powershell
  uv run python scripts/test_live_game.py
  # Dry-run pack compilation and AST verification only:
  uv run python scripts/test_live_game.py --dry-run
  ```
