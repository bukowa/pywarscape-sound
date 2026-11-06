# src/deps
External runtime dependency resolution and playback bridging (Layer 1/3 boundary).
Provides headless audio decoding services for proprietary and compressed Wwise `.wem` audio formats.
- `__init__.py`: Package exports for audio decoding and tool resolution (`decode_wem_to_wav_bytes`, `resolve_vgmstream_path`).
- `player.py`: Headless audio playback services: `resolve_vgmstream_path` discovery across frozen bundles and PATH, `decode_wem_to_wav_bytes` decoding pipeline, `play_wem_buffer` playback helper, and `AudioPreviewSink` preview sink.
