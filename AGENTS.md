# PyWarscape Sound
Python 3.12+ / PySide6 modding tool for **Total War: Attila** and **Rome II**. Opens `.pack` archives, edits Wwise v112 SoundBanks (`.bnk`) and `.wem` audio with cross-bank Undo/Redo, and compiles Movie `.pack` mods. Pure Python: no Wwise CLI, no external archive managers.

Every directory has a SPEC.md. Read the target directory's SPEC.md before touching its files.

---

## Verification Loop (Mandatory Before Declaring Done)
Always `uv run` (never bare `python`). Never judge correctness by reading code; only these gates count:
1. `uv run ruff format src scripts tests` (mandatory auto-format)
2. `uv run ruff check --fix src scripts tests` (mandatory auto-fix linter issues)
3. `uv run ty check src` (type checking)
4. `uv run scripts/arch_guard.py; uv run pytest tests/test_cleanliness.py -q` (fast architecture & cleanliness)
5. `uv run pytest tests -m "not assets" -q` (hermetic suite: 900+ tests, 0 skips; omit `-m "not assets"` only when game data is available)
6. `uv run pytest tests/test_live_game.py -m live -q` (live game integration test: verify live pack mounting and engine startup with 0 crashes before committing whenever a live game installation is available; or `uv run python scripts/test_live_game.py`)
- Run app: `uv run python app.py`
- If a gate fails unexpectedly: stop and report. Do not loop blindly.
- Bug fix: write a failing reproduction test first, then fix until it passes.

## Setup (Once Per Clone)
1. `uv sync --all-groups` — refresh `.venv` with the dev, lint, and test groups.
2. `uv run pre-commit install` — write `.git/hooks/pre-commit`. Without this step nothing runs on commit; hooks are local to each clone.
3. `uv run pre-commit run --all-files` — confirm the whole tree is clean.

`make dev` does steps 1–2, `make hooks` does step 3.

On every `git commit` the hooks run automatically: `ruff --fix` and `ruff format` over `src scripts tests` (same scope as the Verification Loop, so both agree), `ty check src`, `scripts/arch_guard.py`, plus whitespace/EOF/TOML/YAML/merge-conflict/large-file checks. A failing hook aborts the commit: re-stage whatever a fixer rewrote and commit again, or fix the reported error.

`uv run pytest` is **not** part of the hook — tests stay in the Verification Loop. Live game tests must be executed prior to committing whenever a live game install is present.

## Non-Negotiable Invariants
1. **Layers import downward only:** `ui (4) -> workspace (3) -> engine (2) -> bnk/models/compiler (1)`. Layers 1–3 and headless UI modules (`state.py`, `structs.py`, `causation.py`, `store.py`, `coordinator.py`) have **zero `PySide6` imports**.
2. **Immutable state:** frozen `@dataclass(frozen=True, slots=True)` + `tuple`; no shared mutable state across modules. Reducers (`reconcile*`) and planners are pure: zero I/O, zero `raise`.
3. **Bit-exact round-trip:** an unmodified bank must satisfy `SoundBank.from_bytes(b).to_bytes() == b` for every vanilla bank.
4. **Undo/Redo exactness:** any change to `WorkspaceSession` or `effectuator.py` must keep `undo()`/`redo()` restoring exact bank bytes, `BankGraphIndex`, and staged files.
5. **Movie packs contain only `audio/` files, never `db/` tables.**
6. **Brand-agnostic core:** The engine is generic to Total War: Attila and Rome II. Never reintroduce mod-specific branding (e.g. `1212`, `mk1212`) into core schemas, engine models, or test suites.
7. **Zero compatibility shims:** When moving or renaming functions and classes, update all call sites directly. Never introduce private aliases (`_old_name = new_name`) or module re-export shims.

## Investigation Rules
- Session start: `git status`.
- Read the target `state.py` / `store.py` / `session.py` signatures before assuming names.
- Prefer adding **new small files** registered in one place over large surgical edits to big files; do not split files arbitrarily.

## Architecture Map
### 1. Binary & Game Data (`src/bnk/`, `src/models/`, `src/compiler/pfh4_pack.py`)
- `SoundBank.from_bytes()` / `.to_bytes()` parse and rebuild `.bnk` (BKHD, DIDX, DATA, all HIRC types, STID).
- `pfh4_pack.py`: PFH4 extraction, retail decryption, Movie pack writer (`write_pfh4_movie_pack`).
- `src/models/`: decodes binary DB tables (`db/*_tables/*`) and `event_data.dat` into `AudioMetadataCatalog`.
  - **Schema parity:** `DependencyManager` extracts only `TABLE_SCHEMAS` keys; binary and TSV decoding must yield identical entities (`test_database_binary_parity.py`, `test_real_mod_packs_integration.py`).

### 2. Engine & Audio Pipeline (`src/engine/`, `src/compiler/converter.py`, `src/deps/`)
Two-phase edits so a bank is never half-corrupted:
- **Plan** (`ontology.py`, `planner.py`): `MutationBatch` -> `AudioMutationPlan` of intents, or `PlanRejection`.
- **Execute** (`effectuator.py`, `graph.py`, `diff.py`): applies the plan to in-memory ASTs and project files; `AudioConverter` (PyAV) converts `.wav/.mp3/.ogg/.flac` to 32kHz mono 16-bit PCM `.wem`; updates `BankGraphIndex`.
- **Playback** (`src/deps/player.py`): `.wem` -> in-memory WAV via bundled `tools/vgmstream/vgmstream-cli.exe`.

### 3. Workspace & Session (`src/workspace/`, `src/engine/session.py`)
- Project on disk: `project.json`, `pack_root/audio/`, `source_audio/`.
- `WorkspaceSession`: holds loaded banks, `BankGraphIndex`, transactional Undo/Redo (`session.py`, `ontology.py`); each batch snapshots affected bank bytes and staged files.
- `AssetResolver` (`resolver.py`): project overlay (`pack_root/audio/`) -> dependency packs -> read-only vanilla cache (`.cache/<game>/audio/`).

### 4. UI (`src/ui/`)
Each feature slice (`project_hub`, `project_wizard`, `bank_viewer`, `audio_sources`, `audio_transport`, `pack_repair`, `blast_radius`, plus `shell/`) has 4 files:
1. `state.py` / `structs.py`: frozen state, events, `*Intent` classes.
2. `causation.py`: pure `reconcile*` returning `(new_state, intents)`.
3. `store.py`: runs reducer, executes every `*Intent` against `WorkspaceSession`/services, notifies view.
4. `view.py`: PySide6 widget; updates only inside `render(state)`.
   - Colors/styles only from `src/ui/theme.py` (no hardcoded `#RRGGBB`).
   - Never touch `store._*` private attributes.
- `shell/coordinator.py` (`WorkspaceCoordinator`) wires stores together; stores never reference each other directly.

## `SPEC.md` Maintenance
Every `src/` domain package, `src/ui`, `src/ui/shell`, and `src/ui/features/<slice>` needs a concise `SPEC.md` (enforced by `arch_guard.py`). When a directory's role or exports change, update its `SPEC.md` and the changed files' header docstrings (1–2 sentences) in the same task.
```markdown
# <Directory Path, e.g. src/bnk>
<1-2 sentences: purpose and architectural boundary.>
- `file_a.py`: Role, key types/functions.
```

## Working Rules
- **Automated formatting only (NEVER format by hand):** Agents must NEVER manually format, indent, or style-edit code by hand. Always run automated tools: `uv run ruff format src scripts tests` and `uv run ruff check --fix src scripts tests`. Let Ruff resolve all formatting and stylistic rules deterministically.
- **Commits:** Use concise conventional commits; never `git push`. Always run live game tests (`uv run pytest tests/test_live_game.py -m live -q` or `uv run python scripts/test_live_game.py`) before committing to verify zero engine crashes and valid pack mounting whenever the game installation is available.
- **Scope:** one cohesive change at a time; no backward-compat shims, unrequested wrappers, or arbitrary file splits.
- **Subagent Delegation:** When launching subagents via `invoke_subagent`, default `Model='flash'` for all research, analysis, and execution tasks unless high-order architectural reasoning (`Model='pro'`) is explicitly requested.
- **Windows File & Permission Safety:** Always trap `(OSError, PermissionError)` when enumerating arbitrary filesystem paths or drives. Never mutate live game directories in tests without checking write permission first (`_can_write_game_dir`).
- **Approval required:** show the exact diff and wait before changing core schemas, binary/ABI structs, or build files. Never add third-party packages or external binaries/DLLs without approval.
- **Cleanliness:** code, comments, UI text, and commits in plain English with zero mentions of reverse-engineering tools; comment only non-obvious intent or invariants. **Zero AI slop icons:** absolutely no emojis or decorative unicode symbols (e.g. 🐉, 🤝, 🚀, ⚠️) in UI labels, dialogs, code comments, docstrings, or commit messages. Keep all interfaces, documentation, and user-facing text clean, serious, and professional.
- **Communication:** direct, plain Polish/English; ask one focused question at a time when requirements are ambiguous.
- **Environment:** Windows + PowerShell (no Bash syntax, chain with `;`), absolute paths for file tools.
