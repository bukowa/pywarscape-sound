"""
Audio dependencies and playback services for Audiokinetic Wwise containers.
"""

from src.deps.player import (
    decode_wem_to_wav_bytes,
    play_wem_buffer,
    resolve_vgmstream_path,
)

__all__ = [
    "decode_wem_to_wav_bytes",
    "play_wem_buffer",
    "resolve_vgmstream_path",
]
