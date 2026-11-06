---
name: test-factories
description: |
  Write, maintain, and structure unit, integration, and UI tests under tests/src/. Use when creating test fixtures, synthetic audio files, project factories, or handling game asset dependency markers and skips.

  Trigger for:
  - Creating or updating tests in tests/src/
  - Shared fixtures in tests/conftest.py (qapp, test_project, skip_or_fail_missing_asset)
  - Synthetic audio generation or test factories in tests/support/factories.py (make_synthetic_wav, make_audio_project, encode_binary_db_table, write_synthetic_pfh4_pack)
  - Game data and pack asset skips via skip_or_fail_missing_asset or @pytest.mark.assets
  - UI testing with pytest-qt (qtbot, render assertions, headless offscreen setup)
  - Architecture and cleanliness test maintenance (tests/src/test_v3_cleanliness.py)

  DO NOT trigger for:
  - Modifying production UI widgets or theme tokens (use feature-slice skill)
  - Implementing engine planning or effectuation (use mutation-engine skill)
  - Low-level binary chunk parsing in src/bnk/ (use bnk-binary skill)
  - Running live game startup integration tests with Attila.exe (@pytest.mark.live)
---

# Test Fixtures & Factories (`tests/v3` and `tests/support`)

Guidance for authoring and maintaining fast, hermetic, and deterministic tests across unit, integration, and UI feature slices.

## Read-First Files
- `tests/conftest.py`: Root pytest fixtures (`qapp`, `test_project`), audio driver muting, and headless environment variables.
- `tests/support/factories.py`: Synthetic audio generators (`make_synthetic_wav`) and test project builders (`make_audio_project`).
- `tests/src/test_v3_cleanliness.py`: Enforces architectural cleanliness and structure.
- `scripts/arch_guard.py`: Static AST rules for forbidden test imports and fixture duplications.

## Shared Test Fixtures and Builders
| Fixture / Helper | Location | Purpose |
|---|---|---|
| `qapp` | `tests/conftest.py` | Session-scoped `QApplication` instance for headless Qt UI testing |
| `test_project` | `tests/conftest.py` | Function-scoped lightweight `AudioProject` in `tmp_path` |
| `skip_or_fail_missing_asset` | `tests/support/factories.py` | Skips if assets absent, fails if `REQUIRE_GAME_DATA=1` |
| `@pytest.mark.assets` | `pyproject.toml` | Marks tests requiring external vanilla cache or mod packs |
| `make_synthetic_wav` | `tests/support/factories.py` | Creates valid PCM WAV files (silent or test tones) |
| `make_audio_project` | `tests/support/factories.py` | Constructs initialized `AudioProject` instances with custom metadata |
| `encode_binary_db_table` | `tests/support/factories.py` | Encodes table rows into binary DB tables matching `TABLE_SCHEMAS` |
| `write_synthetic_pfh4_pack` | `tests/support/factories.py` | Builds and writes synthetic Total War PFH4 pack archives |

## Canonical Test Patterns
```python
# 1. Hermetic synthetic audio and project test
from tests.support.factories import make_audio_project, make_synthetic_wav


def test_synthetic_flow(tmp_path: Path):
    project = make_audio_project(tmp_path / "project", name="TestMod")
    wav_path = make_synthetic_wav(tmp_path / "sample.wav", duration_s=0.5, tone=True)
    assert wav_path.is_file()
    assert project.manifest.name == "TestMod"


# 2. Hermetic synthetic PFH4 pack with binary DB table
from tests.support.factories import encode_binary_db_table, write_synthetic_pfh4_pack


def test_synthetic_pack_flow(tmp_path: Path):
    rows = [{"key": "unit_1", "category": "infantry", "selection_vo": "charge"}]
    bin_table = encode_binary_db_table("land_units", rows)
    pack_path = write_synthetic_pfh4_pack(
        tmp_path / "test.pack",
        {"db/land_units_tables/test_units": bin_table},
    )
    assert pack_path.is_file()


# 3. Asset-dependent test with strict CI enforcement
from tests.support.factories import skip_or_fail_missing_asset


@pytest.mark.assets
def test_external_asset_workflow():
    asset_path = Path(".cache/attila/audio/battle.bnk")
    if not asset_path.is_file():
        skip_or_fail_missing_asset(f"Missing required game asset: {asset_path}")
    # Execute verification...


# 4. Synchronous UI WorkspaceCoordinator test
def test_coordinator_sync(qapp, qtbot, tmp_path: Path):
    # Pass async_preview=False to eliminate background threading in unit tests
    coordinator = WorkspaceCoordinator(async_preview=False)
    assert coordinator is not None


# 5. Hermetic synthetic GameCache fixture
def test_component_with_synthetic_cache(tmp_path: Path):
    # Set up mock cache directory without requiring 20+ GB vanilla game data
    cache_audio = tmp_path / ".cache" / "attila" / "audio"
    cache_audio.mkdir(parents=True)

    # Write minimal valid SoundBank and dummy WEM
    bank = SoundBank()
    (cache_audio / "init.bnk").write_bytes(bank.to_bytes())
    (cache_audio / "123456.wem").write_bytes(b"RIFF....WAVE")

    # Initialize project pointing to this cache
    project = make_audio_project(tmp_path / "mod", cache_root=tmp_path / ".cache")
    assert project.cache.has_bank("init.bnk")
```

## Invariants
1. **No Duplicate `qapp` Fixture:** Never define `def qapp(` inside `tests/src/*.py`. The shared session fixture in `tests/conftest.py` must be used. (Enforced by `scripts/arch_guard.py`).
2. **No `QT_QPA_PLATFORM` in Tests:** Never set or modify `os.environ["QT_QPA_PLATFORM"]` in test files. It is configured globally in `tests/conftest.py`.
3. **No `PYTEST_CURRENT_TEST` in Production:** Never read or branch on `PYTEST_CURRENT_TEST` inside `src/` production code. Production code must remain test-agnostic.
4. **Mandatory `@pytest.mark.assets` on External Asset Tests:** Any test that requires `.cache/` or `.pack` files must be decorated with `@pytest.mark.assets` and use `skip_or_fail_missing_asset(reason)` instead of raw `pytest.skip`.
5. **Synchronous Coordinator Testing:** Pass `async_preview=False` explicitly when instantiating `WorkspaceCoordinator` in unit tests to avoid unhandled background threads.
6. **No Mocking in Causation Tests:** Causation and table tests must be pure and never import `unittest.mock` or `mock`.
7. **Live Game Testing Rule Before Commit:** Run live game integration tests (`uv run pytest tests/src/test_live_game.py -m live -q` or `uv run python scripts/test_live_game.py`) before committing whenever a live game installation is detected.

## Step-by-Step Checklist
1. **Choose Strategy:** Decide whether the test is hermetic (synthetic) or asset-dependent:
   - Hermetic: Use `tmp_path`, `make_synthetic_wav()`, and synthetic `SoundBank()` instances.
   - Asset-dependent: Decorate with `@pytest.mark.assets` and gate with `skip_or_fail_missing_asset(...)`.
2. **UI Test Setup:** For widget tests, accept `qapp` and `qtbot` fixtures. Use `qtbot.addWidget(widget)` for lifecycle tracking.
3. **Assert State Reductions:** Test `causation.py` reducers directly by feeding states and events: `new_state, intents = reconcile_*(state, event)`.
4. **Cleanliness Verification:** Run `uv run scripts/arch_guard.py` to ensure no architectural test rules are violated.

## Anti-Patterns
- **Calling bare `pytest.skip()` on assets:** Always call `skip_or_fail_missing_asset(reason)` so `REQUIRE_GAME_DATA=1` CI runs catch missing data.
- **Redefining `qapp`:** Adding `@pytest.fixture def qapp():` in a test file triggers an immediate `arch_guard` failure.
- **Physical audio output:** Never bypass SDL dummy audio muting unless testing physical devices intentionally via `PYTEST_ENABLE_AUDIO=1`.
- **Sleeping in tests:** Never use `time.sleep()`; use `qtbot.wait_until()` or synchronous event pump loops.

## Verification Commands
```bash
uv run ruff format src scripts tests
uv run ruff check --fix v3 scripts tests
uv run ty check src
uv run scripts/arch_guard.py; uv run pytest tests/src/test_v3_cleanliness.py -q
uv run pytest tests/v3 -m "not assets" -q  # Hermetic suite (840+ tests, 0 skips)
uv run pytest tests/src/test_live_game.py -m live -q  # Live game integration test (mandatory before commit if game installed)
```
