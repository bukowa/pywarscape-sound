# src/deps
External runtime dependency resolution and playback bridging (Layer 1/3 boundary).
Provides headless audio decoding services for proprietary and compressed Wwise `.wem` audio formats.
- `__init__.py`: Package exports for audio decoding and tool resolution (`decode_wem_to_wav_bytes`, `resolve_vgmstream_path`).
- `player.py`: `resolve_vgmstream_path` for discovery across frozen PyInstaller bundles and PATH.
- `player.py`: `decode_wem_to_wav_bytes` pipeline piping Vorbis `.wem` audio through vgmstream-cli into in-memory WAV buffers.
- `player.py`: `play_wem_buffer` headless playback helper.
