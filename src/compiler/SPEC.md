# src/compiler
Audio transcoding and pack archive compilation pipeline (Layer 1/3 boundary).
Converts raw audio into Wwise-compliant `.wem` containers and packages mod assets into Total War PFH4 archives with zero subprocess dependencies.
- `__init__.py`: Package exports for audio conversion and pack generation.
- `audio_modifiers.py`: Pure-Python audio modifier pipeline and loudness matching (`AudioModifier`, `GainModifier`, `PeakNormalizeModifier`, `MatchReferenceLoudnessModifier`, `AudioModifierChain`, `apply_modifiers_to_wav_bytes`).
- `converter.py`: In-memory `AudioConverter` using PyAV (libavcodec) for headless decoding, mono/stereo channel and sample-rate preservation (up to 48kHz), and `0xFFFE` PCM `.wem` container encoding.
- `pfh4_pack.py`: Native reader and writer for Total War PFH4/PFH5 archives (`PfhEntry`, `read_pfh4_index`, `read_pfh4_pack_type`, `decrypt_pfh4_stream`, `write_pfh4_pack`, `write_pfh4_mod_pack`, `write_pfh4_movie_pack`, `format_user_script_entry`).
