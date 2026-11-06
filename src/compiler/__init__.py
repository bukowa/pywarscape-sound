"""
Compiler package for v3 audio pipeline and SoundBank builds.
"""

from src.compiler.audio_modifiers import (
    AudioModifier,
    AudioModifierChain,
    GainModifier,
    MatchReferenceLoudnessModifier,
    PeakNormalizeModifier,
    apply_modifiers_to_wav_bytes,
)
from src.compiler.converter import AudioConverter
from src.compiler.pfh4_pack import (
    PT_MOD,
    PT_MOVIE,
    extract_pfh4_file,
    format_user_script_entry,
    read_pfh4_index,
    read_pfh4_pack_type,
    write_pfh4_mod_pack,
    write_pfh4_movie_pack,
    write_pfh4_pack,
)

__all__ = [
    "PT_MOD",
    "PT_MOVIE",
    "AudioConverter",
    "AudioModifier",
    "AudioModifierChain",
    "GainModifier",
    "MatchReferenceLoudnessModifier",
    "PeakNormalizeModifier",
    "apply_modifiers_to_wav_bytes",
    "extract_pfh4_file",
    "format_user_script_entry",
    "read_pfh4_index",
    "read_pfh4_pack_type",
    "write_pfh4_mod_pack",
    "write_pfh4_movie_pack",
    "write_pfh4_pack",
]
