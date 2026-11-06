from dataclasses import FrozenInstanceError

import pytest

from src.models.metadata import (
    CultureVoiceMetadata,
    ExplosionAudioMetadata,
    MaterialSFXMetadata,
    ProjectileAudioMetadata,
    UnitMetadata,
)


def test_unit_metadata_instantiation_and_immutability():
    unit = UnitMetadata(
        key="att_alan_alani_swordsmen",
        category="inf_melee",
        unit_class="inf_mel",
        selection_vo="selected_inf_melee",
        secondary_vo="selected_swordsmen",
        tertiary_vo="selected_generic",
        armour_material="chainmail",
        shield_material="wood",
        primary_weapon_material="sword",
    )
    assert unit.key == "att_alan_alani_swordsmen"
    assert unit.selection_vo == "selected_inf_melee"
    assert unit.armour_material == "chainmail"
    with pytest.raises(FrozenInstanceError):
        unit.key = "changed"  # type: ignore


def test_culture_voice_metadata_instantiation():
    cult = CultureVoiceMetadata(
        religion="att_rel_chr_catholic",
        subculture="att_sub_cult_barbarian_celtic",
        voiceover_culture="barbarian_christian",
    )
    assert cult.religion == "att_rel_chr_catholic"
    assert cult.voiceover_culture == "barbarian_christian"


def test_projectile_audio_metadata_instantiation():
    proj = ProjectileAudioMetadata(
        key="arrow_flaming",
        fire_event="projectile_fire_arrow_flaming",
        fire_group_event="projectile_fire_group_arrow_flaming",
        incoming_event=None,
        impact_event="projectile_impact_arrow",
        impact_blood_event="projectile_impact_blood",
        inflight_start_event="projectile_inflight_arrow_flaming_play",
        inflight_stop_event="projectile_inflight_arrow_flaming_stop",
        hit_tree_start_event="projectile_hit_tree_canopy_arrow_play",
        hit_tree_stop_event="projectile_hit_tree_canopy_arrow_stop",
        idle_start_event=None,
        idle_stop_event=None,
    )
    assert proj.key == "arrow_flaming"
    assert proj.incoming_event is None
    assert proj.fire_event == "projectile_fire_arrow_flaming"


def test_explosion_audio_metadata_instantiation():
    exp = ExplosionAudioMetadata(
        key="fireball",
        event="projectile_explosion_fireball",
        group_event=None,
    )
    assert exp.key == "fireball"
    assert exp.event == "projectile_explosion_fireball"


def test_material_sfx_metadata_instantiation():
    mat = MaterialSFXMetadata(
        material_key="att_cuirass",
        category="armour",
        audio_material="segmented",
        target_switch_group="armour_type",
    )
    assert mat.category == "armour"
    assert mat.audio_material == "segmented"
