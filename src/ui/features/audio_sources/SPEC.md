# src/ui/features/audio_sources
Audio Sources dock feature slice for sound library management, batch audio replacements, and in-place DSP enhancements.
Enables modders to map external audio files, vanilla sounds, or silence onto selected SoundBank targets, and apply gain, normalization, and loudness matching modifiers.
- `causation.py`: Pure state transitions and batch mutation generators (`reconcile`, `build_batch`, `build_modifier_chain`).
- `columns.py`: Headless column identifiers, specs, cell extractors, and toggle helpers for the Game Audio catalog table (`CatalogColumn`, `CatalogColumnSpec`, `CATALOG_COLUMN_SPECS`, `toggle_visible_catalog_columns`).
- `state.py`: Immutable state models and events (`AudioSourcesState`, `AudioSourcesEvent`, `ApplyMode`, `AudioSourcesTab`, `AudioEnhanceSettings`, `LibraryRow`, `ApplyRequested`, `SilenceRequested`, `EnhanceRequested`).
- `store.py`: Headless `AudioSourcesStore` coordinating library scanning, catalog caching, enhancement dispatch, preview routing, and batch effectuation.
- `view.py`: `AudioSourcesView` PySide6 dock widget hosting library tabs, file tables, enhance controls, transport bar, and batch actions.
- `widgets/catalog_model.py`: Virtualized `AudioCatalogTableModel` and `AudioCatalogTableView` for large game audio datasets with sorting and column customization.
- `widgets/enhance_tab.py`: `EnhanceTab` interactive DSP controls for gain adjustment, peak normalization, RMS loudness matching, audition preview, and quick muting.
- `widgets/files_table.py`: `FilesTableWidget` displaying scanned audio files with search filtering.
- `widgets/game_audio_tab.py`: `GameAudioTab` for searching, auditioning, and customizing visible columns for vanilla game audio assets.
- `widgets/libraries_table.py`: `LibrariesTableWidget` for adding, removing, and scanning project sound libraries.
