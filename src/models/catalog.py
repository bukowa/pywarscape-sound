"""In-memory bidirectional query engine mapping game databases to Wwise audio assets."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.models.metadata import (
    CultureVoiceMetadata,
    ExplosionAudioMetadata,
    MaterialSFXMetadata,
    ProjectileAudioMetadata,
    UnitMetadata,
)
from src.models.parser import (
    find_table_file,
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


@dataclass(frozen=True, slots=True, kw_only=True)
class AudioCatalogEntry:
    """An audio asset available for selection in the Smart Audio Replacer."""

    wem_id: int
    source_bank: str
    is_embedded: bool = False
    duration_ms: float = 0.0

    # Human-readable identifiers (populated from STID & FNV-1 hashes)
    display_name: str
    category: str = "General"  # e.g. "Voiceover", "Battle", "UI", "Music", "Environment"

    # Forward-compatible metadata slots (ready for DB table ingestion later)
    event_name: str | None = None
    unit_key: str | None = None  # e.g. "att_kho_clibanarii"
    culture_key: str | None = None  # e.g. "att_culture_huns"
    metadata_tags: tuple[str, ...] = ()  # Searchable tags


class AudioMetadataCatalog:
    """
    In-memory bidirectional query engine mapping game databases to Wwise audio assets.
    Provides fast O(1) indexed lookups with case-insensitive key resolution.
    """

    def __init__(
        self,
        units: dict[str, UnitMetadata],
        cultures: list[CultureVoiceMetadata],
        projectiles: dict[str, ProjectileAudioMetadata],
        explosions: dict[str, ExplosionAudioMetadata],
        materials: list[MaterialSFXMetadata],
    ) -> None:
        self.units = units
        self.cultures = cultures
        self.projectiles = projectiles
        self.explosions = explosions
        self.materials = materials

        # 1. Inverted indices for Units
        self._units_by_key: dict[str, UnitMetadata] = {}
        self._units_by_selection_vo: dict[str, list[UnitMetadata]] = defaultdict(list)
        self._units_by_secondary_vo: dict[str, list[UnitMetadata]] = defaultdict(list)
        self._units_by_tertiary_vo: dict[str, list[UnitMetadata]] = defaultdict(list)
        self._units_by_category: dict[str, list[UnitMetadata]] = defaultdict(list)
        self._units_by_vo_culture: dict[str, list[UnitMetadata]] = defaultdict(list)

        for u in units.values():
            self._units_by_key[u.key.lower()] = u
            if u.selection_vo:
                self._units_by_selection_vo[u.selection_vo.lower()].append(u)
            if u.secondary_vo:
                self._units_by_secondary_vo[u.secondary_vo.lower()].append(u)
            if u.tertiary_vo:
                self._units_by_tertiary_vo[u.tertiary_vo.lower()].append(u)
            if u.category:
                self._units_by_category[u.category.lower()].append(u)
            if u.voiceover_culture:
                self._units_by_vo_culture[u.voiceover_culture.lower()].append(u)

        # 2. Inverted indices for Culture routing
        self._cultures_by_junction: dict[tuple[str, str], str] = {}
        for c in cultures:
            key = (c.subculture.lower(), c.religion.lower())
            self._cultures_by_junction[key] = c.voiceover_culture

        # 3. Inverted indices for Projectiles
        self._projectiles_by_key: dict[str, ProjectileAudioMetadata] = {}
        self._projectiles_by_event: dict[str, list[ProjectileAudioMetadata]] = defaultdict(list)

        for p in projectiles.values():
            self._projectiles_by_key[p.key.lower()] = p
            events = [
                p.fire_event,
                p.fire_group_event,
                p.incoming_event,
                p.impact_event,
                p.impact_blood_event,
                p.inflight_start_event,
                p.inflight_stop_event,
                p.hit_tree_start_event,
                p.hit_tree_stop_event,
                p.idle_start_event,
                p.idle_stop_event,
            ]
            for ev in events:
                if ev:
                    self._projectiles_by_event[ev.lower()].append(p)

        # 4. Inverted indices for Explosions
        self._explosions_by_key: dict[str, ExplosionAudioMetadata] = {}
        self._explosions_by_event: dict[str, list[ExplosionAudioMetadata]] = defaultdict(list)

        for e in explosions.values():
            self._explosions_by_key[e.key.lower()] = e
            for ev in [e.event, e.group_event]:
                if ev:
                    self._explosions_by_event[ev.lower()].append(e)

        # 5. Inverted indices for Materials
        self._materials_by_key: dict[tuple[str, str], MaterialSFXMetadata] = {}
        self._materials_by_category: dict[str, list[MaterialSFXMetadata]] = defaultdict(list)
        self._materials_by_switch_group: dict[str, list[MaterialSFXMetadata]] = defaultdict(list)

        for m in materials:
            self._materials_by_key[(m.category.lower(), m.material_key.lower())] = m
            self._materials_by_category[m.category.lower()].append(m)
            self._materials_by_switch_group[m.target_switch_group.lower()].append(m)

    def get_unit(self, unit_key: str | None) -> UnitMetadata | None:
        """Resolves unit audio attributes by unit key in O(1)."""
        if not unit_key:
            return None
        return self._units_by_key.get(unit_key.lower())

    def get_units_for_order_switch(
        self,
        switch_name: str | None,
        include_secondary: bool = False,
        voiceover_culture: str | None = None,
        allowed_categories: tuple[str, ...] | list[str] | set[str] | None = None,
    ) -> list[UnitMetadata]:
        """
        Finds all units that dispatch a given selection or order switch.
        Optionally filters by voiceover culture prefix (e.g. 'barbarian' matches 'barbarian', 'barbarian_pagan', etc.)
        and allowed unit categories (e.g. ('inf_melee', 'inf_ranged')).
        """
        if not switch_name:
            return []
        key = switch_name.lower()
        results = list(self._units_by_selection_vo.get(key, []))
        if include_secondary:
            seen = {u.key for u in results}
            for u in self._units_by_secondary_vo.get(key, []):
                if u.key not in seen:
                    results.append(u)
                    seen.add(u.key)

        if allowed_categories is not None:
            norm_cats = {c.lower() for c in allowed_categories}
            results = [u for u in results if u.category and u.category.lower() in norm_cats]

        if voiceover_culture:
            cult_prefix = voiceover_culture.lower().split("_")[0]
            cult_matched = [
                u
                for u in results
                if u.voiceover_culture
                and (
                    u.voiceover_culture.lower() == voiceover_culture.lower()
                    or u.voiceover_culture.lower().startswith(cult_prefix)
                )
            ]
            results = cult_matched or [u for u in results if not u.voiceover_culture]

        return results

    def get_units_by_category(self, category: str | None) -> list[UnitMetadata]:
        """Returns all units belonging to a category (e.g. 'cavalry', 'inf_melee')."""
        if not category:
            return []
        return self._units_by_category.get(category.lower(), [])

    def resolve_culture_for_faction(
        self, subculture: str | None, religion: str | None
    ) -> str | None:
        """Resolves Wwise voiceover culture switch/state from faction subculture and religion."""
        if not subculture or not religion:
            return None
        return self._cultures_by_junction.get((subculture.lower(), religion.lower()))

    def get_projectile(self, projectile_key: str | None) -> ProjectileAudioMetadata | None:
        """Resolves projectile audio definition by key in O(1)."""
        if not projectile_key:
            return None
        return self._projectiles_by_key.get(projectile_key.lower())

    def get_projectiles_for_event(self, event_name: str | None) -> list[ProjectileAudioMetadata]:
        """Finds all projectiles referencing a specific Wwise event name."""
        if not event_name:
            return []
        return self._projectiles_by_event.get(event_name.lower(), [])

    def get_explosion(self, explosion_key: str | None) -> ExplosionAudioMetadata | None:
        """Resolves explosion audio definition by key in O(1)."""
        if not explosion_key:
            return None
        return self._explosions_by_key.get(explosion_key.lower())

    def get_explosions_for_event(self, event_name: str | None) -> list[ExplosionAudioMetadata]:
        """Finds all explosions referencing a specific Wwise event name."""
        if not event_name:
            return []
        return self._explosions_by_event.get(event_name.lower(), [])

    def get_materials_for_category(self, category: str | None) -> list[MaterialSFXMetadata]:
        """Returns all collision materials in a category (e.g. 'armour', 'shield', 'weapon')."""
        if not category:
            return []
        return self._materials_by_category.get(category.lower(), [])

    def get_materials_for_switch_group(self, switch_group: str | None) -> list[MaterialSFXMetadata]:
        """Returns all collision materials bound to a specific Wwise switch group."""
        if not switch_group:
            return []
        return self._materials_by_switch_group.get(switch_group.lower(), [])

    @classmethod
    def from_directory(cls, directory: Path | str) -> AudioMetadataCatalog:
        """
        Factory scanning a directory containing TSVs or binary DB files (flat or nested)
        and assembling a fully indexed AudioMetadataCatalog.
        """
        dir_path = Path(directory)

        # 1. Parse material lookup tables first
        armour_path = find_table_file(dir_path, "unit_armour_types")
        shield_path = find_table_file(dir_path, "unit_shield_types")
        weapon_path = find_table_file(dir_path, "melee_weapons")

        armour_map = parse_unit_armour_types(armour_path) if armour_path else {}
        shield_map = parse_unit_shield_types(shield_path) if shield_path else {}
        weapon_map = parse_melee_weapons(weapon_path) if weapon_path else {}

        # 1b. Parse main units voiceovers
        main_units_path = find_table_file(dir_path, "main_units")
        vo_map = parse_main_units_voiceover(main_units_path) if main_units_path else {}

        # 2. Parse land units with cross-table linking
        land_units_path = find_table_file(dir_path, "land_units")
        units = (
            parse_land_units(
                land_units_path,
                armour_materials=armour_map,
                shield_materials=shield_map,
                weapon_materials=weapon_map,
                voiceover_cultures=vo_map,
            )
            if land_units_path
            else {}
        )

        # 3. Parse culture junctions
        cult_path = find_table_file(dir_path, "subculture_religion_voiceover_junctions")
        cultures = parse_culture_junctions(cult_path) if cult_path else []

        # 4. Parse audio projectiles
        proj_path = find_table_file(dir_path, "audio_projectiles")
        projectiles = parse_audio_projectiles(proj_path) if proj_path else {}

        # 5. Parse audio explosions
        exp_path = find_table_file(dir_path, "audio_explosions")
        explosions = parse_audio_explosions(exp_path) if exp_path else {}

        # 6. Parse unified material SFX
        materials = parse_material_sfx(
            armour_path=armour_path,
            shield_path=shield_path,
            weapon_path=weapon_path,
        )

        return cls(
            units=units,
            cultures=cultures,
            projectiles=projectiles,
            explosions=explosions,
            materials=materials,
        )

    @classmethod
    def from_pack(cls, pack_path: Path | str) -> AudioMetadataCatalog:
        """
        Extracts and decodes the 7 audio-linked database tables directly from a .pack file
        in-memory without temporary files, returning an indexed AudioMetadataCatalog.
        """
        from src.compiler.pfh4_pack import read_pfh4_index

        pack_p = Path(pack_path)
        if not pack_p.is_file():
            raise FileNotFoundError(f"Pack file not found: {pack_path}")

        entries = read_pfh4_index(pack_p)

        target_tables = {
            "unit_armour_types",
            "unit_shield_types",
            "melee_weapons",
            "land_units",
            "subculture_religion_voiceover_junctions",
            "audio_projectiles",
            "audio_explosions",
        }

        # Map matched table_name -> list of PfhEntry
        table_entries: dict[str, list[Any]] = defaultdict(list)
        for e in entries:
            norm_path = e.path.replace("\\", "/").strip("/").lower()
            parts = norm_path.split("/")
            matched_table = None
            for part in parts:
                if part.endswith("_tables"):
                    t_cand = part[:-7]
                    if t_cand in target_tables:
                        matched_table = t_cand
                        break
            if not matched_table:
                fname = parts[-1]
                stem = fname.rsplit(".", 1)[0] if "." in fname else fname
                if stem in target_tables:
                    matched_table = stem

            if matched_table:
                table_entries[matched_table].append(e)

        table_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        with open(pack_p, "rb") as f:
            for tbl, e_list in table_entries.items():
                for e in e_list:
                    f.seek(e.offset)
                    data = f.read(e.size)
                    rows = parse_tsv_rows(data, table_name=tbl)
                    table_rows[tbl].extend(rows)

        armour_map = parse_unit_armour_types(table_rows.get("unit_armour_types", []))
        shield_map = parse_unit_shield_types(table_rows.get("unit_shield_types", []))
        weapon_map = parse_melee_weapons(table_rows.get("melee_weapons", []))

        units = parse_land_units(
            table_rows.get("land_units", []),
            armour_materials=armour_map,
            shield_materials=shield_map,
            weapon_materials=weapon_map,
        )
        cultures = parse_culture_junctions(
            table_rows.get("subculture_religion_voiceover_junctions", [])
        )
        projectiles = parse_audio_projectiles(table_rows.get("audio_projectiles", []))
        explosions = parse_audio_explosions(table_rows.get("audio_explosions", []))
        materials = parse_material_sfx(
            armour_path=table_rows.get("unit_armour_types", []),
            shield_path=table_rows.get("unit_shield_types", []),
            weapon_path=table_rows.get("melee_weapons", []),
        )

        return cls(
            units=units,
            cultures=cultures,
            projectiles=projectiles,
            explosions=explosions,
            materials=materials,
        )

    @classmethod
    def load_from_project_and_dependencies(cls, project: Any) -> AudioMetadataCatalog:
        """Loads and indexes metadata catalog aggregating across project overlay, dependencies, and cache."""
        return project.load_metadata_catalog()
