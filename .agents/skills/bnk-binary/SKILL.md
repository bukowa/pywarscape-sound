---
name: bnk-binary
description: |
  Inspect, parse, manipulate, or serialize Audiokinetic Wwise v112 SoundBank (.bnk) binary AST structures and RIFF chunks. Use when working on chunk framing (BKHD, DIDX, DATA, HIRC, STID), HIRC object serialization/deserialization, or low-level bank binary parsing in Layer 1 (src/bnk/).

  Trigger for:
  - Binary parsing or serialization in src/bnk/
  - Modifying or adding HIRC objects in src/bnk/models.py (CAkSound, CAkEvent, CAkAction, CAkRanSeqCntr, CAkSwitchCntr, CAkMusicTrack, etc.)
  - Chunk handling in src/bnk/chunks.py or src/bnk/bank.py (BKHD, DIDX, DATA, HIRC, STID)
  - Bit-exact round-trip debugging or ByteReader / ByteWriter stream framing
  - DIDX media entry indexing and scan_didx_media_ids

  DO NOT trigger for:
  - High-level audio mutation planning or effectuation (use mutation-engine skill)
  - UI widgets, tree rendering, or bank viewer presentation (use feature-slice skill)
  - PFH4 pack container packaging or retail decryption (handled in src/compiler/pfh4_pack.py)
  - High-level test fixture setup or audio factories (use test-factories skill)
---

# Wwise v112 Binary AST (`src/bnk`)

Layer 1 handles bit-exact parsing, typed AST representation, and serialization of Wwise v112 SoundBanks (`.bnk`). It operates with zero Qt and zero higher-layer dependencies.

## Read-First Files
- `src/bnk/SPEC.md`: Architectural boundaries and chunk responsibilities.
- `src/bnk/bank.py`: `SoundBank` root orchestrator, `HircChunk` container, and repair strategies.
- `src/bnk/chunks.py`: Low-level chunk headers, `DidxEntry`, `DataChunk`, and `scan_didx_media_ids`.
- `src/bnk/models.py`: 20 typed HIRC object definitions and parameter structures.
- `src/bnk/stream.py`: `ByteReader` and `ByteWriter` binary stream wrappers.
- `src/bnk/database.py`: SoundDatabase (`event_data.dat`) and FNV-1 32-bit hashing utilities.

## Invariants
1. **Zero PySide6 / Zero Layer 2+ imports:** `src/bnk/` is Layer 1. Never import from `src/engine`, `src/workspace`, or `PySide6`.
2. **Mutable AST dataclasses:** All HIRC and chunk AST classes must be mutable `@dataclass(slots=True)` (NEVER `frozen=True`). The engine mutates these nodes directly in memory during editing sessions.
3. **Bit-exact round-trip:** Every unmodified vanilla bank must round-trip with zero byte drift: `SoundBank.from_bytes(b).to_bytes() == b`.
4. **All 20 HIRC types supported:** Any new or modified HIRC object must properly preserve all parsed fields, parameter blocks, and trailing bytes.
5. **Stream framing integrity:** Chunk headers write a 4-byte ASCII FourCC followed by an unsigned 32-bit little-endian length (`<I`).

## Key Chunk Layouts and Types
- `BKHD`: Bank header chunk containing format `version` (112), `bank_id`, `language_id`, and feedback/project flags.
- `DIDX`: Embedded media index table holding a contiguous sequence of 12-byte `DidxEntry(file_id, offset, size)` structs.
- `DATA`: Contiguous raw binary slice holding the concatenated embedded `.wem` audio streams referenced by DIDX.
- `HIRC`: Hierarchy chunk starting with a 32-bit object count, followed by variable-length HIRC object records.
- `STID`: String mapping chunk associating SoundBank numeric IDs with human-readable string bank names.
- `scan_didx_media_ids(bnk_bytes: bytes) -> set[int]`: Scans DIDX chunks directly without full AST parsing.

## Supported HIRC Object Types (`src/bnk/models.py`)
| Type ID | Class Name | Description |
|---|---|---|
| `0x01` | `CAkSettings` | Bank-wide audio settings and property baselines |
| `0x02` | `CAkSound` | Audio playback leaf referencing embedded or streamed WEM |
| `0x03` | `CAkAction` | Action triggered by events (Play, Stop, Pause, Set State) |
| `0x04` | `CAkEvent` | Event entity grouping executable action IDs |
| `0x05` | `CAkRanSeqCntr` | Random or sequence container with playlist item weights |
| `0x06` | `CAkSwitchCntr` | Dynamic routing container switching children by group/state |
| `0x07` | `CAkActorMixer` | Hierarchical bus and voice routing node |
| `0x08` | `CAkBus` | Audio mixing bus node |
| `0x09` | `CAkLayerCntr` | Layer container evaluating multiple children simultaneously |
| `0x0A` | `CAkMusicSegment` | Interactive music segment container |
| `0x0B` | `CAkMusicTrack` | Interactive music track with duration, lookahead, and clip markers |
| `0x0C` | `CAkMusicSwitchCntr` | Interactive music state-driven transition container |
| `0x0D` | `CAkMusicRanSeqCntr` | Interactive music randomized or sequential container |
| `0x0E` | `CAkAttenuation` | Distance attenuation curve definitions |
| `0x0F` | `CAkDialogueEvent` | Dynamic dialogue event tree for voice lines |
| `0x10` | `CAkFeedbackBus` | Haptic/motion feedback bus |
| `0x11` | `CAkFeedbackNode` | Haptic/motion source node |
| `0x12` | `CAkFxShareSet` | Shared DSP effect chain parameters |
| `0x13` | `CAkFxCustom` | Custom per-node DSP effect parameters |
| `0x14` | `CAkAuxBus` | Auxiliary send mixing bus |

## Step-by-Step Checklist
1. **Locate Target Type:** Inspect `src/bnk/models.py` for the HIRC object type ID and existing field definitions.
2. **Check Reader/Writer Parity:** Verify that `parse_hirc_object` reads fields in the exact byte sequence that `to_bytes()` writes them.
3. **Handle Optional & Variable Blocks:** For complex objects (e.g. `CAkSound`, `CAkRanSeqCntr`), check child counts, playlist items, and parameter arrays before parsing.
4. **Preserve Unknown/Trailing Bytes:** If an object contains vendor-specific CA fields or unknown trailing bytes, preserve them in a raw bytes buffer (`raw_tail`).
5. **Verify Round-Trip:** Test serialization on both synthetic mock chunks and real cached vanilla banks.
6. **Update SPEC.md:** If chunk or model signatures change, update `src/bnk/SPEC.md` in the same task.

## Anti-Patterns
- **Freezing AST dataclasses:** Do NOT use `@dataclass(frozen=True)` in `src/bnk/models.py` or `chunks.py`.
- **Importing upper layers:** Do NOT import `src.engine.*`, `src.workspace.*`, or `PySide6`.
- **Assuming fixed chunk ordering:** Banks can have chunks in any order (`BKHD -> DIDX -> DATA -> HIRC` or `BKHD -> HIRC -> STID`).
- **Ignoring DIDX offset alignment:** DIDX entries reference offsets within the `DATA` chunk body; altering offsets without updating DIDX breaks playback.

## Verification Commands
```bash
uv run ruff format src scripts tests
uv run ruff check --fix v3 scripts tests
uv run ty check src
uv run scripts/arch_guard.py; uv run pytest tests/src/test_v3_cleanliness.py -q
uv run pytest tests/src/test_hirc_objects.py -q
uv run pytest tests/src/test_v3_bnk_roundtrip.py -q
```
