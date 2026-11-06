# src/bnk
Audiokinetic Wwise v112 binary AST core (Layer 1). Handles bit-exact parsing, serialization, and container validation with zero Qt or higher-layer dependencies.
- `bank.py`: Root `SoundBank` parser/serializer, `HircChunk` orchestrator, and archive encryption artifact repair.
- `chunks.py`: Binary chunk structures including `BkhdChunk`, `DidxChunk`, `DidxEntry`, `DataChunk`, `StidChunk`, and `scan_didx_media_ids`.
- `database.py`: Total War `SoundDatabase` (`event_data.dat`) parser/serializer and Wwise FNV-1 32-bit hashing utilities.
- `models.py`: Complete typed AST for all 20 Wwise v112 HIRC objects (`CAkSound`, `CAkEvent`, `CAkRanSeqCntr`, etc.) and parameters.
- `parser_attila.py`: Dedicated HIRC parser for Total War: Attila (Wwise v112).
- `parser_rome2.py`: Dedicated HIRC parser for Total War: Rome II (supporting both Wwise v88 and v112).
- `stream.py`: High-performance bounded `ByteReader` and `ByteWriter` stream abstractions.
- `wem.py`: Wwise `.wem` RIFF container parser, Vorbis metadata extraction, and PCM .wem audio container generation.
