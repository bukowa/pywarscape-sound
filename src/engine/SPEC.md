# src/engine
Core mutation engine, graph indexing, and session management (Layer 2).
Executes two-phase atomic audio mutations with complete Undo/Redo tracking and zero Qt imports.
- `audio_export.py`: Audio extraction pipeline exporting SoundBank nodes and embedded/streamed WEMs to WAV files (`resolve_node_wav_bytes`, `export_node_to_wav`, `export_nodes_to_directory`).
- `catalog/causation.py`: Pure state transitions for audio catalog discovery and filtering (`evolve_catalog_state`, `filter_catalog_entries`).
- `catalog/structs.py`: Immutable data types and algebraic states for catalog exploration (`CatalogScope`, `CatalogState`, `CatalogFilterSpec`).
- `catalog_discovery.py`: Discovers and indexes bank and workspace audio assets (`build_audio_catalog_for_bank`).
- `diff.py`: Computes structural AST differences between active SoundBanks and vanilla baselines (`BankDiffResult`, `diff_soundbanks`).
- `effectuator.py`: Imperative dispatcher executing `AudioMutationPlan` intents onto disk and bank ASTs (`execute_mutation_plan`).
- `graph.py`: Pre-indexed bidirectional HIRC item relationship and WEM reference graph (`BankGraphIndex`).
- `metadata_fields.py`: Typed metadata field identifiers, provenance classifications, WEM header decoding, and HIRC attribute extraction (`MetadataField`, `Provenance`, `NodeMetadata`, `extract_hirc_metadata`, `extract_wem_header_metadata`, `format_wem_codec`, `merge_node_metadata`).
- `metadata_resolver.py`: Pluggable game metadata resolution pipeline enriching SoundBank AST and media nodes with Total War database entities (`CompositeMetadataResolver`, `NodeMetadataInfo`, `SoundDatabaseProvider`, `GameCatalogProvider`, `GraphHierarchyProvider`).
- `ontology.py`: Pure immutable data ontology for mutations, replacement scopes, WEM references, effect intents, and batch snapshots (`MutationBatch`, `AudioMutationPlan`, `ReplacementScope`, `WemReference`, `BankBatchSnapshot`, `MediaTargetSnapshot`).
- `planner.py`: Pure functional planner evaluating mutation batches, WEM ID allocation, sound lookups, and generating plans (`plan_audio_replacement`, `plan_batch`, `allocate_unique_wem_id`, `find_sound_in_bank`).
- `ports.py`: Boundary protocols decoupling engine from workspace (`AssetResolverPort`, `AudioProjectPort`).
- `session.py`: Primary domain façade managing loaded bank ASTs, mutation application, and atomic Undo/Redo stacks (`WorkspaceSession`).
- `wem_metadata.py`: Lazy WEM audio stream header inspection, sequential chunk scanning, companion bank metadata resolution, and loose file duration resolution (`resolve_bank_wem_metadata`, `resolve_wem_duration_ms`).
- Stream promotion: replacing embedded audio promotes the node to streamed (`stream_type = 2`) and stages a loose `.wem`.
- Music tracks: replacing a music track recalculates its duration and marker offsets.
