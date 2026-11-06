"""src models package."""

from src.models.binary_table import (
    MAGIC_BINARY_DB,
    MAGIC_EXTENDED_HEADER,
    decode_binary_table,
    decode_binary_table_file,
    is_binary_db_table,
)
from src.models.catalog import AudioCatalogEntry, AudioMetadataCatalog
from src.models.db_schemas import (
    TABLE_SCHEMAS,
    get_table_schema,
)
from src.models.metadata import (
    CultureVoiceMetadata,
    ExplosionAudioMetadata,
    MaterialSFXMetadata,
    ProjectileAudioMetadata,
    UnitMetadata,
)
from src.models.parser import (
    find_table_file,
    find_table_tsv,
    parse_audio_explosions,
    parse_audio_projectiles,
    parse_culture_junctions,
    parse_land_units,
    parse_main_units_voiceover,
    parse_material_sfx,
    parse_melee_weapons,
    parse_tsv_rows,
    parse_unit_armour_types,
    parse_unit_shield_types,
)

__all__ = [
    "MAGIC_BINARY_DB",
    "MAGIC_EXTENDED_HEADER",
    "TABLE_SCHEMAS",
    "AudioCatalogEntry",
    "AudioMetadataCatalog",
    "CultureVoiceMetadata",
    "ExplosionAudioMetadata",
    "MaterialSFXMetadata",
    "ProjectileAudioMetadata",
    "UnitMetadata",
    "decode_binary_table",
    "decode_binary_table_file",
    "find_table_file",
    "find_table_tsv",
    "get_table_schema",
    "is_binary_db_table",
    "parse_audio_explosions",
    "parse_audio_projectiles",
    "parse_culture_junctions",
    "parse_land_units",
    "parse_main_units_voiceover",
    "parse_material_sfx",
    "parse_melee_weapons",
    "parse_tsv_rows",
    "parse_unit_armour_types",
    "parse_unit_shield_types",
]
