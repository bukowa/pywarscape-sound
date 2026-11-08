# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.2] - 2026-11-08

### Fixed
- **Hierarchy Tree Selection & Focus Preservation**:
  - Maintained exact tree item path, expansion state, and vertical scroll position across tree rebuilds when applying audio replacements or muting.
  - Isolated tree cycle detection per hierarchy branch so shared containers and sound nodes under multiple parents expand and render correctly.
- **Cross-Bank Active Selection Stability**:
  - Prevented active bank focus jumps to companion/sibling banks during cross-bank media replacements by invalidating background caches and refreshing only the active bank.

## [0.3.1] - 2026-11-08

### Added
- **Pre-Flight Pack Export Integrity Validator**:
  - Validates movie pack exports before writing to disk to prevent silent game crashes.
  - Checks path isolation (`audio/` only), bit-exact SoundBank roundtrip, WEM RIFF/WAVE headers, non-empty data size, and DAG media closure.
- **E2E Modder Core Jobs Suite**:
  - Added comprehensive 11-job end-to-end modder verification matrix (`tests/test_e2e_modder_core_jobs.py`) covering all game sound replacement workflows.

### Fixed
- **SoundBank Byte Exactness on Undo**:
  - Fixed `MutationRecord.is_media` classification so bank undo transactions correctly restore exact SoundBank binary bytes and AST structures.
- **Loose Vorbis Streaming**:
  - Tolerated untouched vanilla base game Vorbis streams when local audio cache is unpopulated, preventing false rejection of valid exports.
- **WEM Header Parsing**:
  - Protected Vorbis chunk header parsing against short or synthetic stream headers.

## [0.3.0] - 2026-11-08

### Added
- **Companion Logic SoundBank Mapping**:
  - Automatic mapping for all 28 split Attila and Rome II data banks (`*_data.bnk`) to companion logic banks.
- **Decision Trees & Switch Inspectors**:
  - Multi-depth decision tree resolution and table inspectors for `CAkMusicSwitchCntr` and `CAkDialogueEvent`.
  - Contextual switch condition display and hierarchy tree path labels.
- **Audio Fine-Tuning & Pool Variations**:
  - Sound node parameter tuning for volume (`PropID 0`) and pitch (`PropID 2`).
  - Support for appending new random/sequence audio variations to sound pools.
- **Modder Usability & Workflows**:
  - Direct drag-and-drop replacement onto SoundBank hierarchy tree rows.
  - Right-click context menus for sub-tracks, muting, and per-slot baseline revert.
  - Blast radius impact dialog displaying affected events and switch contexts.
  - End-to-end modder workflow integration test suite validating playable compiled packs.

### Changed
- Baseline SoundBank resolution queries active mod dependencies before falling back to game cache.

### Fixed
- True per-slot baseline revert for sound nodes and music tracks without affecting sibling edits.
- Global WEM ID generator checks unopened project and cache banks to prevent collisions.

## [0.2.0] - 2026-11-08

### Added
- **Music Track Replacement**:
  - Full support for interactive music track (`CAkMusicTrack`) audio replacement and sub-track manipulation in the mutation pipeline (`planner.py`, `effectuator.py`, `graph.py`, `session.py`).
  - Added dedicated Music Track view panel (`views/music_view.py`) for inspecting music sub-tracks, durations, and clips.
- **Engine Capability Matrix & Conformance Vectors**:
  - Implemented capability matrix (`src/engine/capability_matrix.json`, `src/engine/capabilities.py`) validating node-level mutation constraints and feature gates.
  - Added vector-driven conformance verification test suite (`tests/vectors/`) covering SoundBank mutation scenarios.
- **SoundBank Navigation & Categorization**:
  - Added bank list grouping and classification by game and category in `bank_list_panel.py`.
- **UI Refinements**:
  - Renamed sound library folder addition button to "Add Folder...".
- **Agent Release Management**:
  - Added comprehensive release-management agent skill documenting all release steps and canonical file updates.

### Fixed
- **SoundBank Hierarchy Refresh**:
  - Fixed tree hierarchy synchronization when promoting embedded sounds to streamed `.wem` or overwriting existing `.wem` assets.

### Documentation
- Added AI-assisted development and vibecoded notice to README.

## [0.1.0] - 2026-11-06

### Added
- **Multi-Game SoundBank Parsing & Serialization**:
  - Pure Python Audiokinetic Wwise SoundBank (`.bnk`) AST parser and bit-exact serializer.
  - Dedicated Total War: Attila parser (`parser_attila.py`) supporting Wwise v112 SoundBanks.
  - Dedicated Total War: Rome II parser (`parser_rome2.py`) supporting both legacy Wwise v88 and modern v112 SoundBanks with typed `CAkAttenuationV88` curves and bit-exact fallback.
  - Verified 100% bit-exact round-trip preservation across all 105 Rome II banks and 126 Attila vanilla banks.
- **Audio Conversion & Processing**:
  - Integrated PyAV transcode pipeline converting `.wav`, `.mp3`, `.ogg`, and `.flac` into game-compliant 32 kHz mono 16-bit PCM `.wem` audio.
  - Audio enhancement tools: Gain adjustment, peak normalization, target RMS matching, and preview playback.
  - In-app playback auditioning of `.wem` audio via bundled, integrity-verified `vgmstream`.
- **PFH4 Container & Game Packaging**:
  - Retail PFH4 `.pack` extraction and retail decryption.
  - Game-compliant Movie pack (`PT_MOVIE`) and Mod pack (`PT_MOD`) compilation into project directory with optional automatic copy to game data directory.
- **Engine Mutation Pipeline**:
  - Two-phase mutation pipeline (`plan_batch` -> `effectuate_plan`) ensuring SoundBanks are never half-corrupted.
  - Transactional cross-bank Undo and Redo with rollback snapshots for bank bytes, staged audio, and graph indices.
  - Sound muting via zero-byte audio stubs.
  - Mod pack corruption repair (word-swapped automation points, bad DIDX headers).
- **Desktop Graphical Interface (PySide6)**:
  - 4-file Model-View-Update (MVU) architecture (`state.py`, `causation.py`, `store.py`, `view.py`).
  - Project Hub: Open/create projects, track recent projects, scan game installations.
  - Project Wizard: Multi-game project setup, asset extraction, dependency configuration.
  - SoundBank Viewer: Hierarchical AST inspection, DIDX media table, property inspector, cross-bank jump navigation.
  - Audio Sources Panel: Searchable game audio catalog, metadata resolvers, external file imports, multi-selection replacement.
  - Audio Transport Bar: Waveform seek bar, playback controls, volume slider, looping.
  - Pack Repair View: Diagnostic scanner for corrupted mod packs with automated one-click healing.
  - High-contrast dark theme design system with centralized semantic design tokens.
  - AI-assistance startup disclaimer and GitHub contribution guide.
- **Security & Quality**:
  - Full GitHub Actions CI with action versions pinned to commit SHAs.
  - CodeQL automated security scanning and vulnerability analysis.
  - Dependency vulnerability auditing via `pip-audit`.
  - Binary integrity verification for bundled binaries (`test_vgmstream_integrity.py`).
  - Hermetic automated test suite with over 900 tests, strict architecture boundary enforcement (`arch_guard.py`), and zero `PySide6` imports in headless layers.
