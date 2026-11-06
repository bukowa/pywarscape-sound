# PyWarscape Sound

PyWarscape Sound is a standalone desktop application for inspecting, modifying, and packaging Audiokinetic Wwise SoundBanks (`.bnk`) and `.wem` audio files for **Total War: Attila** and **Total War: Rome II**.

It operates natively in Python with zero external tool dependencies: no Wwise authoring application, no external archive managers, and no external audio converters required.

---

## Features

- **SoundBank Inspection**: Browse SoundBank hierarchy trees (Sounds, Events, Actions, Random/Sequence Containers, Switch Containers, and Music Tracks) and embedded DIDX media tables.
- **Audio Auditioning**: In-app preview and playback of `.wem` audio streams.
- **Audio Replacement**: Replace vanilla game audio with standard `.wav`, `.mp3`, `.ogg`, or `.flac` files. Audio is automatically converted to game-compliant 32 kHz mono PCM `.wem`.
- **Sound Muting**: Silence sounds cleanly using zero-byte audio stubs without breaking SoundBank structures.
- **Pack Health & Repair**: Scan modded SoundBanks for known binary corruptions (such as word-swapped automation points or corrupted header offsets) and repair them with one click.
- **Pack Compilation**: Package modified SoundBanks and loose audio directly into game-ready Total War PFH4 `.pack` archives (both `PT_MOD` and `PT_MOVIE`) in your project folder, with optional automatic copying to the game data directory on build.
- **Transactional Undo/Redo**: Full cross-bank undo/redo history that tracks SoundBank AST mutations and staged files.
- **100% Portable**: Stores configuration, recent projects, logs, and caches inside the application directory. No files are written to `%USERPROFILE%` or `%APPDATA%`.

---

## Download & Run (Standalone Release)

For modders and players:

1. Download the latest `PyWarscapeSound-vX.Y.Z-windows-x64.zip` from [GitHub Releases](https://github.com/Bukowa/pywarscape-sound/releases).
2. Extract the ZIP archive to any folder.
3. Run `PyWarscapeSound.exe`.

No Python installation or external tools are required. All dependencies (Python runtime, PySide6, PyAV, pygame, and vgmstream) are self-contained.

---

## Development Setup

For developers running from source:

### Prerequisites

- **OS**: Windows 10/11 (x64)
- **Python**: 3.12 or newer
- **uv**: Modern Python package and tool manager ([astral.sh/uv](https://astral.sh/uv))

### Quick Start

```powershell
# Clone repository
git clone https://github.com/Bukowa/pywarscape-sound.git
cd pywarscape-sound

# Install dependencies into virtual environment
uv sync --all-groups

# Install git pre-commit hooks
uv run pre-commit install

# Launch desktop GUI
uv run python app.py
```

---

## Testing & Quality Assurance

PyWarscape Sound includes an automated test suite and architecture enforcement tooling:

### 1. Hermetic Test Suite
Runs all unit, integration, and UI tests using synthetic fixtures. Requires zero game installations or external packs:

```powershell
uv run pytest tests -m "not assets" -q
```

### 2. Code Quality & Architecture Verification
Enforces strict layer boundaries, zero Qt leaks in stores/models, no hardcoded colors, and automated formatting:

```powershell
# Auto-format and lint check
uv run ruff format --check src scripts tests
uv run ruff check src scripts tests

# Type check
uv run ty check src

# Architecture boundary enforcement & cleanliness
uv run scripts/arch_guard.py
uv run pytest tests/test_cleanliness.py -q
```

### 3. Optional Retail Asset Round-Trip Verification
When vanilla game files are available in `.cache/attila/` or `.cache/rome_2/`, tests marked `@pytest.mark.assets` verify bit-exact round-trip serialization against all retail SoundBanks:

```powershell
uv run pytest tests -q
```

### 4. Live Game Integration Testing
When Total War: Attila is installed locally, verifies real mod pack mounting and game engine startup with zero crashes:

```powershell
uv run pytest tests/test_live_game.py -m live -q
# Or run standalone runner:
uv run python scripts/test_live_game.py
```

---

## Building the Standalone Application

To package the standalone distribution executable locally:

```powershell
uv run python scripts/build_dist.py --version 0.1.0
```

The build script:
1. Cleans intermediate build caches.
2. Invokes PyInstaller using `audio_editor.spec` in onedir mode.
3. Bundles verified `tools/vgmstream/` binaries.
4. Generates a standalone ZIP archive at `dist/PyWarscapeSound-v0.1.0-windows-x64.zip`.

---

## Release Process

PyWarscape Sound uses automated GitHub Actions workflows for continuous integration and releases:

- `.github/workflows/ci.yml`: Runs formatting, linting, type checks, and the hermetic test suite on every push and pull request.
- `.github/workflows/release.yml`: Automatically triggers when a semver release tag (`v*.*.*`) is pushed. Builds the standalone Windows bundle, generates SHA-256 checksums, and publishes a GitHub Draft Release.

### How to Publish a New Release

1. **Run local verification**:
   ```powershell
   uv run ruff format src scripts tests
   uv run ruff check --fix src scripts tests
   uv run ty check src
   uv run scripts/arch_guard.py
   uv run pytest tests/test_cleanliness.py -q
   uv run pytest tests -m "not assets" -q
   ```

2. **Commit all pending changes**:
   ```powershell
   git add .
   git commit -m "chore: prepare v0.1.0 release"
   ```

3. **Create and push an annotated git tag**:
   ```powershell
   git tag -a v0.1.0 -m "Release v0.1.0"
   git push origin v0.1.0
   ```

4. **Verify GitHub Actions Build**:
   - The `Release` workflow automatically executes all test gates.
   - It builds `dist/PyWarscapeSound-v0.1.0-windows-x64.zip` and generates `dist/SHA256SUMS.txt`.
   - It creates a Draft Release on GitHub containing the zip and checksums.

5. **Publish**:
   - Navigate to **Releases** on GitHub.
   - Review the release notes and attached assets.
   - Click **Publish release**.

> **Note**: You can also trigger a release build manually from the GitHub Actions tab via **Run workflow** on the `Release` workflow by specifying the version number.

---

## Architecture

The codebase enforces a 4-layer downward dependency hierarchy (`Layer 4 -> Layer 3 -> Layer 2 -> Layer 1`). Layers 1–3 and headless UI stores have zero Qt (`PySide6`) dependencies:

```
src/
├── bnk/               # Layer 1: Wwise v112 SoundBank AST (BKHD, DIDX, DATA, 20 HIRC types, STID) & WEM headers
├── models/            # Layer 1: Total War binary DB table decoders (db/*_tables/*) and AudioMetadataCatalog
├── compiler/          # Layer 1/2: PFH4 .pack reader/writer with retail decryption & PyAV in-memory WEM transcoder
├── deps/              # Layer 2: Headless audio decoding bridge (vgmstream CLI integration)
├── engine/            # Layer 2: Mutation ontology, pure planner, effectuator, BankGraphIndex, WorkspaceSession
│   └── catalog/       # Pure catalog filter ontology and causation
├── workspace/         # Layer 3: Living Project storage, layered AssetResolver, DependencyManager, PackHealthScanner, paths
└── ui/                # Layer 4: Data-driven PySide6 interface (state.py -> causation.py -> store.py -> view.py)
    ├── shell/         # MainWindow, dock layout persistence, and cross-feature WorkspaceCoordinator
    └── features/      # Feature slices: project_hub, project_wizard, bank_viewer, audio_sources,
                       # audio_transport, pack_repair, blast_radius
```

---

## Third-Party Components & Compliance

PyWarscape Sound is licensed under the [MIT License](LICENSE).

Third-party dependencies and open-source licenses:
- **PyAV** (FFmpeg bindings): LGPL v2.1+ / BSD 2-Clause (dynamically linked)
- **PySide6** (Qt for Python): LGPL v3 (dynamically linked)
- **Pygame**: LGPL v2.1 (dynamically linked)
- **vgmstream**: ISC License (external subprocess binary)
- **PFH4 Format Specifications**: Frodo45127 (MIT License - clean-room pure Python container implementation)

See [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for full license texts, attributions, and LGPL relinking compliance instructions.
