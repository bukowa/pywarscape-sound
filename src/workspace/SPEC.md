# src/workspace
Mod project workspace lifecycle, storage, and layered asset resolution (Layer 3).
Coordinates multi-game caches, dependency pack overlays, and sound library scanning without Qt imports.
- `cache.py`: `GameCache` managing indexed vanilla SoundBanks, `event_data.dat`, loose audio, and audio-related DB table extraction.
- `dependencies.py`: `DependencyManager` handling external `.pack` ingestion, table extraction, and priority conflicts.
- `game.py`: Game definitions (`GameType`, `GameConfig`, `get_game_config`, `resolve_user_script_path`) for Attila and Rome II.
- `game_detector.py`: Pure-Python `GameDetector` locating Steam library folders and game installation directories.
- `health.py`: Diagnostic `PackHealthScanner` detecting and auto-repairing binary corruptions in SoundBanks.
- `importer.py`: Dedicated `PartImporter` service for copying SoundBanks, loose WEMs, and DB tables from external `.pack` files into `pack_root/audio/`.
- `manifest.py`: Portable `ProjectManifest` schema (1.0), `DependencyPackInfo`, and `SoundLibraryRef`.
- `paths.py`: Portable application root and configuration path resolution (`get_app_root`, `get_settings_path`, `get_recent_projects_path`, `get_log_file_path`, `get_cache_dir`).
- `project.py`: `AudioProject` workspace model encapsulating `pack_root/`, `source_audio/`, and staged tables.
- `resolver.py`: 3-tier copy-on-write `AssetResolver` querying project overlay, dependencies, and vanilla cache.
- `sound_library.py`: Scans external sound libraries and resolves audio file entries (`LibraryFileEntry`, `resolve_library_root`).
- `storage.py`: `ProjectStorage` factory creating, saving, and verifying atomic project directories on disk.
