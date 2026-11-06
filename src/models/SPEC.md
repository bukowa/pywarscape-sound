# src/models
Game data schemas, binary table decoders, and immutable domain models (Layer 1). Bridges Total War DB tables to Wwise audio entities with zero UI dependencies.
- `binary_table.py`: Decodes raw Total War binary DB tables (`decode_binary_table`, `is_binary_db_table`).
- `catalog.py`: `AudioMetadataCatalog` in-memory bidirectional query engine mapping DB entities to sound events, and `AudioCatalogEntry` model.
- `db_schemas.py`: Schema definitions (`TABLE_SCHEMAS`) for audio-linked database tables.
- `hashing.py`: Known 32-bit FNV-1 hash constants and name lookups (`KNOWN_HASH_NAMES`).
- `metadata.py`: Immutable dataclasses (`UnitMetadata`, `CultureVoiceMetadata`, `ProjectileAudioMetadata`, etc.).
- `parser.py`: Unified table file finder and parser supporting both TSV and binary table formats.
- Switch scoping: battle VO banks (`battle_vo_orders_<culture>_<actor>.bnk`) route `VO_CULTURE -> VO_BATTLE_ACTOR -> VO_ORDER`. Filter unit metadata by actor (`inf`=infantry, `mtd`=cavalry, `art`=artillery) and culture.
