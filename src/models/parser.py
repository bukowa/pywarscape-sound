"""Unified database parser supporting both plain TSV and native Total War binary tables."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from src.models.binary_table import (
    MAGIC_BINARY_DB,
    decode_binary_table,
    decode_binary_table_file,
    is_binary_db_table,
)
from src.models.metadata import (
    CultureVoiceMetadata,
    ExplosionAudioMetadata,
    MaterialSFXMetadata,
    ProjectileAudioMetadata,
    UnitMetadata,
)


def find_table_file(directory: Path | str, table_name: str) -> Path | None:
    """
    Locates a database table file (TSV, binary, or extensionless) by table name across
    flat, nested, or db-nested directory structures.
    """
    base = Path(directory)
    if not base.is_dir():
        return None

    clean_table = table_name.lower()
    if clean_table.endswith(".tsv"):
        clean_table = clean_table[:-4]
    if clean_table.endswith(".bin"):
        clean_table = clean_table[:-4]
    if clean_table.endswith("_tables"):
        clean_table = clean_table[:-7]

    extensions = [".tsv", "", ".bin"]
    candidates = []
    for ext in extensions:
        candidates.extend(
            [
                base / f"{clean_table}{ext}",
                base / f"{clean_table}_tables" / f"{clean_table}{ext}",
                base / "db" / f"{clean_table}_tables" / f"{clean_table}{ext}",
            ]
        )

    for cand in candidates:
        if cand.is_file():
            return cand

    # Check for custom mod-prefixed files inside table directories
    # (e.g. db/land_units_tables/custom_land_units.tsv or raw binary)
    for table_dir in [base / f"{clean_table}_tables", base / "db" / f"{clean_table}_tables"]:
        if table_dir.is_dir():
            files = [p for p in sorted(table_dir.iterdir()) if p.is_file()]
            tsvs = [f for f in files if f.name.lower().endswith(".tsv")]
            if tsvs:
                return tsvs[0]
            if files:
                return files[0]

    # Recursive search fallback by exact or extensionless match
    for ext in extensions:
        target_name = f"{clean_table}{ext}".lower()
        for p in base.rglob("*"):
            if p.is_file() and p.name.lower() == target_name:
                return p

    # Fallback to any file inside a matching *_tables directory found anywhere
    target_dir_name = f"{clean_table}_tables"
    for p in base.rglob("*"):
        if p.is_file() and p.parent.name.lower() == target_dir_name:
            return p

    return None


def find_all_table_files(directory: Path | str, table_name: str) -> list[Path]:
    """
    Locates all matching database table files (TSV, binary, or extensionless) for a given table name
    within a directory (handling flat, <table_name>_tables, or db/<table_name>_tables).
    """
    base = Path(directory)
    if not base.is_dir():
        return []

    clean_table = table_name.lower()
    if clean_table.endswith(".tsv"):
        clean_table = clean_table[:-4]
    if clean_table.endswith(".bin"):
        clean_table = clean_table[:-4]
    if clean_table.endswith("_tables"):
        clean_table = clean_table[:-7]

    found: list[Path] = []
    seen = set()

    for table_dir in [base / f"{clean_table}_tables", base / "db" / f"{clean_table}_tables"]:
        if table_dir.is_dir():
            for p in sorted(table_dir.iterdir()):
                if p.is_file() and p.resolve() not in seen:
                    seen.add(p.resolve())
                    found.append(p)

    if not found:
        # Check flat files
        extensions = [".tsv", "", ".bin"]
        for ext in extensions:
            cand = base / f"{clean_table}{ext}"
            if cand.is_file() and cand.resolve() not in seen:
                seen.add(cand.resolve())
                found.append(cand)

    return found


def find_table_tsv(directory: Path | str, table_name: str) -> Path | None:
    """Alias for find_table_file preserving backward compatibility."""
    return find_table_file(directory, table_name)


def _parse_tsv_text(text: str) -> list[dict[str, str | None]]:
    reader = csv.reader(io.StringIO(text), delimiter="\t")
    try:
        headers = [h.strip() for h in next(reader)]
    except StopIteration:
        return []

    rows: list[dict[str, str | None]] = []
    for raw_row in reader:
        if not raw_row:
            continue
        first_cell = raw_row[0].strip()
        # Skip TSV metadata header row: #table_name;version;path
        if first_cell.startswith("#"):
            continue

        row_dict: dict[str, str | None] = {}
        for i, h in enumerate(headers):
            if i < len(raw_row):
                val = raw_row[i].strip()
                row_dict[h] = val if val else None
            else:
                row_dict[h] = None
        rows.append(row_dict)
    return rows


def parse_tsv_rows(
    source: Path | str | bytes | list[dict[str, Any]],
    table_name: str | None = None,
) -> list[dict[str, Any]]:
    """
    Parses a TSV or native Total War binary DB table into standardized row dictionaries.
    Accepts file path, in-memory bytes, or pre-parsed row dictionaries.
    """
    if source is None:
        return []

    if isinstance(source, list):
        return source

    if isinstance(source, bytes):
        if is_binary_db_table(source):
            if not table_name:
                raise ValueError("table_name is required when decoding binary table bytes")
            _, rows, _ = decode_binary_table(source, table_name)
            return rows
        text = source.decode("utf-8-sig", errors="replace")
        return _parse_tsv_text(text)

    p = Path(source)
    if not p.is_file():
        return []

    with open(p, "rb") as f:
        magic = f.read(4)

    if magic == MAGIC_BINARY_DB:
        return decode_binary_table_file(p, table_name=table_name)

    with open(p, encoding="utf-8-sig", errors="replace") as f:
        return _parse_tsv_text(f.read())


def parse_unit_armour_types(
    source: Path | str | bytes | list[dict[str, Any]] | None,
) -> dict[str, str]:
    """Extracts armour key -> audio_material mapping."""
    if source is None:
        return {}
    rows = parse_tsv_rows(source, table_name="unit_armour_types")
    result: dict[str, str] = {}
    for r in rows:
        key = r.get("key")
        audio_mat = r.get("audio_material")
        if key and audio_mat:
            result[str(key)] = str(audio_mat)
    return result


def parse_unit_shield_types(
    source: Path | str | bytes | list[dict[str, Any]] | None,
) -> dict[str, str]:
    """Extracts shield key -> audio_material mapping."""
    if source is None:
        return {}
    rows = parse_tsv_rows(source, table_name="unit_shield_types")
    result: dict[str, str] = {}
    for r in rows:
        key = r.get("key")
        audio_mat = r.get("audio_material")
        if key and audio_mat:
            result[str(key)] = str(audio_mat)
    return result


def parse_melee_weapons(source: Path | str | bytes | list[dict[str, Any]] | None) -> dict[str, str]:
    """Extracts melee weapon key -> audio_material mapping."""
    if source is None:
        return {}
    rows = parse_tsv_rows(source, table_name="melee_weapons")
    result: dict[str, str] = {}
    for r in rows:
        key = r.get("key")
        audio_mat = r.get("audio_material")
        if key and audio_mat:
            result[str(key)] = str(audio_mat)
    return result


def parse_main_units_voiceover(
    source: Path | str | bytes | list[dict[str, Any]] | None,
) -> dict[str, str]:
    """Extracts land_unit key -> voiceover culture mapping from main_units table."""
    if source is None:
        return {}
    rows = parse_tsv_rows(source, table_name="main_units")
    result: dict[str, str] = {}
    for r in rows:
        lu_key = r.get("land_unit") or r.get("unit")
        vo = r.get("voiceover")
        if lu_key and vo:
            result[str(lu_key)] = str(vo)
    return result


_CULTURE_PREFIXES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        (
            "att_mar_cel",
            "att_mar_ger",
            "att_mar_nor",
            "att_merc_cel",
            "att_merc_ger",
            "att_merc_nor",
            "cha_merc_sax",
            "cha_merc_cel",
            "cha_merc_vik",
            "att_ger_",
            "att_nor_",
            "att_cel_",
            "att_slav_",
            "att_sla_",
            "cha_cel_",
            "cha_lom_",
            "cha_sax_",
            "cha_vik_",
            "cha_slav_",
            "cha_fra_",
            "cha_dan_",
        ),
        "barbarian",
    ),
    (
        (
            "att_mar_rom",
            "att_merc_rom",
            "cha_merc_rom",
            "att_rom_",
            "att_vr_",
            "bel_rom_",
            "bel_ost_",
            "cha_byz_",
            "cha_gen_",
            "cha_rom_",
        ),
        "roman",
    ),
    (
        (
            "att_mar_est",
            "att_merc_est",
            "att_mar_des",
            "att_merc_des",
            "att_des_",
            "att_est_",
            "att_sas_",
            "cha_mus_",
        ),
        "eastern",
    ),
    (
        (
            "att_mar_alan",
            "att_merc_alan",
            "att_merc_nom",
            "att_merc_hun",
            "att_nom_",
            "att_alan_",
            "att_hun_",
            "cha_avar_",
            "cha_mag_",
        ),
        "nomad",
    ),
)


def _infer_culture_from_key(unit_key: str) -> str | None:
    k = unit_key.lower()
    for prefixes, cult in _CULTURE_PREFIXES:
        if any(k.startswith(p) for p in prefixes):
            return cult
    return None


def parse_land_units(
    source: Path | str | bytes | list[dict[str, Any]] | None,
    armour_materials: dict[str, str] | None = None,
    shield_materials: dict[str, str] | None = None,
    weapon_materials: dict[str, str] | None = None,
    voiceover_cultures: dict[str, str] | None = None,
) -> dict[str, UnitMetadata]:
    """
    Parses land_units table, linking armour, shield, and weapon foreign keys to audio materials,
    and voiceover cultures from main_units.
    """
    if source is None:
        return {}
    rows = parse_tsv_rows(source, table_name="land_units")
    armour_map = armour_materials or {}
    shield_map = shield_materials or {}
    weapon_map = weapon_materials or {}
    vo_map = voiceover_cultures or {}

    units: dict[str, UnitMetadata] = {}
    for r in rows:
        key = r.get("key")
        if not key:
            continue

        raw_armour = r.get("armour")
        raw_shield = r.get("shield")
        raw_weapon = r.get("primary_melee_weapon")

        armour_mat = armour_map.get(str(raw_armour)) if raw_armour else None
        shield_mat = shield_map.get(str(raw_shield)) if raw_shield else None
        weapon_mat = weapon_map.get(str(raw_weapon)) if raw_weapon else None

        sec_vo = r.get("selected_vo_secondary")
        tert_vo = r.get("selected_vo_tertiary")
        vo_cult = vo_map.get(str(key)) or _infer_culture_from_key(str(key))

        unit = UnitMetadata(
            key=str(key),
            category=str(r.get("category") or ""),
            unit_class=str(r.get("class") or ""),
            selection_vo=str(r.get("selection_vo") or ""),
            voiceover_culture=str(vo_cult) if vo_cult else None,
            secondary_vo=str(sec_vo) if sec_vo else None,
            tertiary_vo=str(tert_vo) if tert_vo else None,
            armour_material=armour_mat,
            shield_material=shield_mat,
            primary_weapon_material=weapon_mat,
        )
        units[str(key)] = unit

    return units


def parse_culture_junctions(
    source: Path | str | bytes | list[dict[str, Any]] | None,
) -> list[CultureVoiceMetadata]:
    """Parses subculture_religion_voiceover_junctions table into CultureVoiceMetadata."""
    if source is None:
        return []
    rows = parse_tsv_rows(source, table_name="subculture_religion_voiceover_junctions")
    junctions: list[CultureVoiceMetadata] = []
    for r in rows:
        religion = r.get("religion")
        subculture = r.get("subculture")
        vo_culture = r.get("voiceover_culture")
        if religion and subculture and vo_culture:
            junctions.append(
                CultureVoiceMetadata(
                    religion=str(religion),
                    subculture=str(subculture),
                    voiceover_culture=str(vo_culture),
                )
            )
    return junctions


def parse_audio_projectiles(
    source: Path | str | bytes | list[dict[str, Any]] | None,
) -> dict[str, ProjectileAudioMetadata]:
    """Parses audio_projectiles table into ProjectileAudioMetadata."""
    if source is None:
        return {}
    rows = parse_tsv_rows(source, table_name="audio_projectiles")
    projectiles: dict[str, ProjectileAudioMetadata] = {}
    for r in rows:
        key = r.get("key")
        if not key:
            continue
        projectiles[str(key)] = ProjectileAudioMetadata(
            key=str(key),
            fire_event=str(r["fire_event"]) if r.get("fire_event") else None,
            fire_group_event=str(r["fire_group_event"]) if r.get("fire_group_event") else None,
            incoming_event=str(r["incoming_event"]) if r.get("incoming_event") else None,
            impact_event=str(r["impact_event"]) if r.get("impact_event") else None,
            impact_blood_event=str(r["impact_blood_event"])
            if r.get("impact_blood_event")
            else None,
            inflight_start_event=str(r["inflight_start_event"])
            if r.get("inflight_start_event")
            else None,
            inflight_stop_event=str(r["inflight_stop_event"])
            if r.get("inflight_stop_event")
            else None,
            hit_tree_start_event=str(r["hit_tree_start_event"])
            if r.get("hit_tree_start_event")
            else None,
            hit_tree_stop_event=str(r["hit_tree_stop_event"])
            if r.get("hit_tree_stop_event")
            else None,
            idle_start_event=str(r["idle_start_event"]) if r.get("idle_start_event") else None,
            idle_stop_event=str(r["idle_stop_event"]) if r.get("idle_stop_event") else None,
        )
    return projectiles


def parse_audio_explosions(
    source: Path | str | bytes | list[dict[str, Any]] | None,
) -> dict[str, ExplosionAudioMetadata]:
    """Parses audio_explosions table into ExplosionAudioMetadata."""
    if source is None:
        return {}
    rows = parse_tsv_rows(source, table_name="audio_explosions")
    explosions: dict[str, ExplosionAudioMetadata] = {}
    for r in rows:
        key = r.get("key")
        if not key:
            continue
        explosions[str(key)] = ExplosionAudioMetadata(
            key=str(key),
            event=str(r["event"]) if r.get("event") else None,
            group_event=str(r["group_event"]) if r.get("group_event") else None,
        )
    return explosions


def parse_material_sfx(
    armour_source: Path | str | bytes | list[dict[str, Any]] | None = None,
    shield_source: Path | str | bytes | list[dict[str, Any]] | None = None,
    weapon_source: Path | str | bytes | list[dict[str, Any]] | None = None,
    *,
    armour_path: Path | str | bytes | list[dict[str, Any]] | None = None,
    shield_path: Path | str | bytes | list[dict[str, Any]] | None = None,
    weapon_path: Path | str | bytes | list[dict[str, Any]] | None = None,
) -> list[MaterialSFXMetadata]:
    """
    Constructs unified MaterialSFXMetadata records from armor, shield, and weapon tables.
    """
    materials: list[MaterialSFXMetadata] = []
    armour_src = armour_source if armour_source is not None else armour_path
    shield_src = shield_source if shield_source is not None else shield_path
    weapon_src = weapon_source if weapon_source is not None else weapon_path

    if armour_src:
        for r in parse_tsv_rows(armour_src, table_name="unit_armour_types"):
            key = r.get("key")
            mat = r.get("audio_material")
            if key and mat:
                materials.append(
                    MaterialSFXMetadata(
                        material_key=str(key),
                        category="armour",
                        audio_material=str(mat),
                        target_switch_group="armour_type",
                    )
                )

    if shield_src:
        for r in parse_tsv_rows(shield_src, table_name="unit_shield_types"):
            key = r.get("key")
            mat = r.get("audio_material")
            if key and mat:
                materials.append(
                    MaterialSFXMetadata(
                        material_key=str(key),
                        category="shield",
                        audio_material=str(mat),
                        target_switch_group="shield_type",
                    )
                )

    if weapon_src:
        for r in parse_tsv_rows(weapon_src, table_name="melee_weapons"):
            key = r.get("key")
            mat = r.get("audio_material")
            if key and mat:
                materials.append(
                    MaterialSFXMetadata(
                        material_key=str(key),
                        category="weapon",
                        audio_material=str(mat),
                        target_switch_group="melee_weapon",
                    )
                )

    return materials
