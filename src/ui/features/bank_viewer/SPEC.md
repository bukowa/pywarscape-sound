# src/ui/features/bank_viewer
SoundBank exploration and HIRC hierarchy inspection feature slice.
Provides full AST visualization, navigation history, property inspection, and direct node audio replacement.
- `audio_resolver.py`: Resolves playable `AudioTrack` items from SoundBank HIRC nodes and embedded DIDX entries.
- `bank_list_panel.py`: `BankListPanel` displaying available vanilla and modified project SoundBanks.
- `builder.py`: Projections mapping SoundBank AST and graph index into `HircTreeNode` hierarchies and property sheets.
- `causation.py`: Pure state transitions (`reconcile_viewer`) handling selection, tree filtering, lazy WEM header metadata, and back/forward navigation.
- `columns.py`: Configurable hierarchy tree columns, widths, and cell/provenance extractors (`ColumnSpec`, `TreeColumn`, `WEM_HEADER_COLUMNS`, `requires_wem_metadata`, `toggle_visible_columns`).
- `inspector_panel.py`: `InspectorPanel` coordinating navigation headers and stacked type-specific inspector views.
- `overlays.py`: Interactive hierarchy tree overlay specifications and pure resolution helpers (`OverlaySpec`, `TreeOverlay`, `resolve_node_label`, `resolve_node_details`).
- `state.py`: Immutable state models (`BankViewerState`, `HircTreeNode`, `NodeInspectorDetails`, `InspectorViewType`).
- `store.py`: Headless `BankViewerStore` orchestrating bank AST caching, diff inspection, navigation history, and batch node muting (`mute_nodes`).
- `view.py`: `BankViewerView` PySide6 widget containing resizable splitters, hierarchy trees, multi-selection routing, and context menus.
- `views/container_view.py`: `ContainerInspectorView` inspecting Random/Sequence and Switch container routing.
- `views/default_view.py`: `DefaultInspectorView` generic fallback inspector rendering raw HIRC properties.
- `views/event_action_view.py`: `EventActionInspectorView` displaying event action targets and delays.
- `views/game_entities_widget.py`: `GameEntitiesWidget` collapsible inspector section and `GameEntitiesTableModel` virtual table for game database entity rosters.
- `views/media_view.py`: `MediaInspectorView` displaying embedded DIDX WEM media details, cross-bank references, and export controls.
- `views/music_view.py`: `MusicInspectorView` presenting interactive music playlists, segments, and track markers.
- `views/sound_view.py`: `SoundInspectorView` displaying sound node playback types, streamed/embedded indicators, cross-bank WEM references, and export controls.
