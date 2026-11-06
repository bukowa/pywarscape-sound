"""Typed, immutable domain data structures mapping Total War game database entities to Wwise audio."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UnitMetadata:
    """Unit audio profile and classification attributes parsed from game tables."""

    key: str
    category: str
    unit_class: str
    selection_vo: str
    voiceover_culture: str | None = None
    secondary_vo: str | None = None
    tertiary_vo: str | None = None
    armour_material: str | None = None
    shield_material: str | None = None
    primary_weapon_material: str | None = None


@dataclass(frozen=True)
class CultureVoiceMetadata:
    """Represents faction culture and religion voiceover routing."""

    religion: str
    subculture: str
    voiceover_culture: str


@dataclass(frozen=True)
class ProjectileAudioMetadata:
    """Represents projectile sound event bindings."""

    key: str
    fire_event: str | None = None
    fire_group_event: str | None = None
    incoming_event: str | None = None
    impact_event: str | None = None
    impact_blood_event: str | None = None
    inflight_start_event: str | None = None
    inflight_stop_event: str | None = None
    hit_tree_start_event: str | None = None
    hit_tree_stop_event: str | None = None
    idle_start_event: str | None = None
    idle_stop_event: str | None = None


@dataclass(frozen=True)
class ExplosionAudioMetadata:
    """Represents explosion sound event bindings."""

    key: str
    event: str | None = None
    group_event: str | None = None


@dataclass(frozen=True)
class MaterialSFXMetadata:
    """Represents physical collision material bindings for armors and weapons."""

    material_key: str
    category: str  # 'armour', 'shield', 'weapon', 'ground'
    audio_material: str
    target_switch_group: str
