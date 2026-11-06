"""Dedicated Wwise v112 SoundBank HIRC parser for Total War: Attila.

Handles typed object hierarchy deserialization for all standard Attila banks.
"""

from src.bnk.models import HircObject, parse_hirc_object
from src.bnk.stream import ByteReader


def parse_attila_hirc_object(reader: ByteReader) -> HircObject:
    """Parses a single HIRC object record using the Attila (Wwise v112) AST."""
    return parse_hirc_object(reader)
