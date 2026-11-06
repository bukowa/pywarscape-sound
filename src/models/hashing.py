"""Audiokinetic Wwise hashing constants and known identifier specifications.

Calculates and maps standard 32-bit FNV-1 identifiers matching Audiokinetic
Wwise v112 sound pipeline architecture for Total War: Attila and Rome II.
"""

from typing import Final

# Master Battle VO Events
MASTER_EVENT_PLAY_BATTLE_VO_ORDERS: Final[int] = 1391812361  # Play_Battle_VO_Orders

# Switch Groups configured on Unit Sound Objects and Pipelines
SWITCH_GROUP_VO_ORDER: Final[int] = 1172968668  # VO_ORDER
SWITCH_GROUP_VO_CULTURE: Final[int] = 993407210  # VO_CULTURE
SWITCH_GROUP_VO_BATTLE_ACTOR: Final[int] = 4285663799  # VO_BATTLE_ACTOR
SWITCH_GROUP_VO_BATTLE_CULTURE: Final[int] = 993474794  # vo_battle_culture
SWITCH_GROUP_GENDER: Final[int] = 1776943274  # gender
SWITCH_GROUP_GROUP_MOVEMENT_STATE: Final[int] = 3908834760  # group_movement_state
SWITCH_GROUP_MELEE_WEAPON: Final[int] = 2833351022  # melee_weapon
SWITCH_GROUP_GROUND_TYPE: Final[int] = 4040317175  # ground_type
SWITCH_GROUP_VO_CAMPAIGN_CULTURE: Final[int] = 1194659798  # vo_campaign_culture
SWITCH_GROUP_VO_CAMPAIGN_SUBCULTURE: Final[int] = 1066379064  # vo_campaign_subculture
SWITCH_GROUP_VO_CAMPAIGN_CHARACTER: Final[int] = 1017849973  # vo_campaign_character
SWITCH_GROUP_LOCATION: Final[int] = 2033773498  # location

# Engine State Groups
STATE_GROUP_GAME_MODE: Final[int] = 1071299879  # game_mode
STATE_GROUP_MIXER: Final[int] = 3133553484  # mixer
STATE_GROUP_SPEAKER_CONFIG: Final[int] = 1495137055  # speaker_config

# Real-Time Parameter Controls (RTPCs)
RTPC_MUSIC_VOLUME: Final[int] = 1006694123  # music_volume
RTPC_SFX_VOLUME: Final[int] = 1564184899  # sfx_volume
RTPC_ADVISOR_VOLUME: Final[int] = 265386196  # advisor_volume
RTPC_MOVIE_VOLUME: Final[int] = 1303938648  # movie_volume
RTPC_MASTER_VOLUME: Final[int] = 4179668368  # master_volume
RTPC_VO_VOLUME: Final[int] = 2295553393  # vo_volume
RTPC_INTERFACE_VOLUME: Final[int] = 3274368607  # interface_volume
RTPC_VOICE_CHAT_VOLUME: Final[int] = 2492104443  # voice_chat_volume
RTPC_NUM_ENTITIES: Final[int] = 2233671539  # num_entities

# Known Audiokinetic Wwise engine hash mappings
KNOWN_HASH_NAMES: Final[dict[int, str]] = {
    MASTER_EVENT_PLAY_BATTLE_VO_ORDERS: "Play_Battle_VO_Orders",
    SWITCH_GROUP_VO_ORDER: "VO_ORDER",
    SWITCH_GROUP_VO_CULTURE: "VO_CULTURE",
    SWITCH_GROUP_VO_BATTLE_ACTOR: "VO_BATTLE_ACTOR",
    SWITCH_GROUP_VO_BATTLE_CULTURE: "vo_battle_culture",
    SWITCH_GROUP_GENDER: "gender",
    SWITCH_GROUP_GROUP_MOVEMENT_STATE: "group_movement_state",
    SWITCH_GROUP_MELEE_WEAPON: "melee_weapon",
    SWITCH_GROUP_GROUND_TYPE: "ground_type",
    SWITCH_GROUP_VO_CAMPAIGN_CULTURE: "vo_campaign_culture",
    SWITCH_GROUP_VO_CAMPAIGN_SUBCULTURE: "vo_campaign_subculture",
    SWITCH_GROUP_VO_CAMPAIGN_CHARACTER: "vo_campaign_character",
    SWITCH_GROUP_LOCATION: "location",
    STATE_GROUP_GAME_MODE: "game_mode",
    STATE_GROUP_MIXER: "mixer",
    STATE_GROUP_SPEAKER_CONFIG: "speaker_config",
    RTPC_MUSIC_VOLUME: "music_volume",
    RTPC_SFX_VOLUME: "sfx_volume",
    RTPC_ADVISOR_VOLUME: "advisor_volume",
    RTPC_MOVIE_VOLUME: "movie_volume",
    RTPC_MASTER_VOLUME: "master_volume",
    RTPC_VO_VOLUME: "vo_volume",
    RTPC_INTERFACE_VOLUME: "interface_volume",
    RTPC_VOICE_CHAT_VOLUME: "voice_chat_volume",
    RTPC_NUM_ENTITIES: "num_entities",
}
