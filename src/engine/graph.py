"""Pre-indexed bidirectional HIRC item relationship lookups and root resolution."""

import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.bnk.bank import SoundBank
from src.bnk.models import (
    CAkAction,
    CAkActorMixer,
    CAkAttenuation,
    CAkAuxBus,
    CAkBus,
    CAkDialogueEvent,
    CAkEvent,
    CAkFxCustom,
    CAkFxShareSet,
    CAkLayerCntr,
    CAkMusicRanSeqCntr,
    CAkMusicSegment,
    CAkMusicSwitchCntr,
    CAkMusicTrack,
    CAkRanSeqCntr,
    CAkSound,
    CAkState,
    CAkSwitchCntr,
    HircObject,
)
from src.models.hashing import KNOWN_HASH_NAMES

_CATEGORY_MAPPINGS = (
    (CAkEvent, "events"),
    (CAkAction, "actions"),
    (CAkSwitchCntr, "switch_cntrs"),
    (CAkRanSeqCntr, "ran_seq_cntrs"),
    (CAkSound, "sounds"),
    (CAkMusicTrack, "music_tracks"),
    (CAkMusicSegment, "music_segments"),
    (CAkDialogueEvent, "dialogue_events"),
    (CAkState, "states"),
    (CAkActorMixer, "actor_mixers"),
    ((CAkBus, CAkAuxBus), "buses"),
    (CAkLayerCntr, "layer_cntrs"),
    (CAkMusicSwitchCntr, "music_switches"),
    (CAkMusicRanSeqCntr, "music_ran_seqs"),
    (CAkAttenuation, "attenuations"),
    ((CAkFxShareSet, CAkFxCustom), "fx"),
)


def _clean_str(val: str | None) -> str | None:
    """Returns None if string is falsy or literal 'none'/'null'."""
    if not val or val.strip().lower() in ("none", "null"):
        return None
    return val.strip()


def get_child_ids_for_object(obj: HircObject | None) -> list[int]:
    """Returns direct child HIRC IDs referenced by the given object."""
    if obj is None:
        return []
    children: list[int] = []

    if isinstance(obj, CAkEvent):
        children.extend(obj.actions)
    elif isinstance(obj, CAkAction):
        tid = getattr(obj, "target_id", 0) or getattr(obj, "id_ext", 0)
        if tid > 0:
            children.append(tid)
    elif isinstance(obj, CAkSwitchCntr):
        children.extend(obj.children)
        for target_list in obj.switch_map.values():
            for tgt in target_list:
                if tgt not in children:
                    children.append(tgt)
    elif isinstance(obj, CAkRanSeqCntr):
        children.extend(obj.children)
        for item in obj.playlist:
            if item.play_id not in children:
                children.append(item.play_id)
    elif isinstance(obj, CAkDialogueEvent):
        if getattr(obj, "tree", None):
            children.extend(obj.tree.get_all_leaf_audio_node_ids())
    elif isinstance(obj, CAkMusicSegment):
        for track in getattr(obj, "child_ids", []):
            children.append(track)
    elif isinstance(obj, (CAkActorMixer, CAkLayerCntr)):
        children.extend(obj.children)
    elif isinstance(obj, CAkMusicSwitchCntr):
        tp = getattr(obj, "trans_params", None)
        if tp and hasattr(tp, "children"):
            for cid in tp.children:
                if cid not in children:
                    children.append(cid)
        for cid in getattr(obj, "child_ids", []):
            if cid not in children:
                children.append(cid)
        if getattr(obj, "tree", None):
            for leaf in obj.tree.get_all_leaf_audio_node_ids():
                if leaf not in children:
                    children.append(leaf)
        if tp and hasattr(tp, "rules"):
            for rule in tp.rules:
                if (
                    getattr(rule, "alloc_trans_object_flag", 0) != 0
                    and len(getattr(rule, "trans_object", b"")) >= 4
                ):
                    trans_seg_id = struct.unpack_from("<I", rule.trans_object, 0)[0]
                    if trans_seg_id > 0 and trans_seg_id not in children:
                        children.append(trans_seg_id)
    elif isinstance(obj, CAkMusicRanSeqCntr):
        tp = getattr(obj, "trans_params", None)
        if tp and hasattr(tp, "children"):
            for cid in tp.children:
                if cid not in children:
                    children.append(cid)
        for cid in getattr(obj, "child_ids", []):
            if cid not in children:
                children.append(cid)
        if getattr(obj, "playlist", None):
            for pitem in obj.playlist:
                sid = getattr(pitem, "segment_id", 0)
                pid = getattr(pitem, "playlist_item_id", 0) or getattr(pitem, "play_id", 0)
                if sid > 0 and sid not in children:
                    children.append(sid)
                if pid > 0 and pid not in children:
                    children.append(pid)
        if tp and hasattr(tp, "rules"):
            for rule in tp.rules:
                if (
                    getattr(rule, "alloc_trans_object_flag", 0) != 0
                    and len(getattr(rule, "trans_object", b"")) >= 4
                ):
                    trans_seg_id = struct.unpack_from("<I", rule.trans_object, 0)[0]
                    if trans_seg_id > 0 and trans_seg_id not in children:
                        children.append(trans_seg_id)
    return children


def categorize_bank_objects(bank: SoundBank) -> dict[str, list[HircObject]]:
    """Categorizes all HIRC items by type for hierarchical folder display."""
    cats: dict[str, list[HircObject]] = {
        "events": [],
        "actions": [],
        "switch_cntrs": [],
        "ran_seq_cntrs": [],
        "sounds": [],
        "music_tracks": [],
        "music_segments": [],
        "dialogue_events": [],
        "states": [],
        "actor_mixers": [],
        "buses": [],
        "layer_cntrs": [],
        "music_switches": [],
        "music_ran_seqs": [],
        "attenuations": [],
        "fx": [],
        "other": [],
    }
    if not bank.hirc:
        return cats

    for obj in bank.hirc.objects:
        matched = False
        for type_cls, key in _CATEGORY_MAPPINGS:
            if isinstance(obj, type_cls):
                cats[key].append(obj)
                matched = True
                break
        if not matched:
            cats["other"].append(obj)
    return cats


def build_switch_target_map(bank: SoundBank) -> dict[int, int]:
    """Maps switch target container ID -> switch value ID across all CAkSwitchCntr objects."""
    m: dict[int, int] = {}
    if not bank.hirc:
        return m
    for obj in bank.hirc.objects:
        if isinstance(obj, CAkSwitchCntr):
            for sw_val, targets in getattr(obj, "switch_map", {}).items():
                for tid in targets:
                    if tid not in m:
                        m[tid] = sw_val
    return m


def compute_root_objects(
    bank: SoundBank, child_map: dict[int, list[int]] | None = None
) -> list[HircObject]:
    """Determines natural root nodes: Events, DialogueEvents, and unparented Switch/RanSeq containers."""
    if not bank.hirc:
        return []

    referenced: set[int] = set()
    if child_map is not None:
        for children in child_map.values():
            referenced.update(children)
    else:
        for obj in bank.hirc.objects:
            referenced.update(get_child_ids_for_object(obj))

    roots: list[HircObject] = []
    for obj in bank.hirc.objects:
        if isinstance(obj, (CAkEvent, CAkDialogueEvent)) or (
            isinstance(obj, (CAkSwitchCntr, CAkRanSeqCntr)) and obj.id not in referenced
        ):
            roots.append(obj)
    return roots


def resolve_hash_name(
    object_id: int,
    bank: SoundBank,
    custom_names: dict[int, str] | None = None,
    sound_db: Any | None = None,
) -> str | None:
    """Resolves a 32-bit ID to a human-readable name using known constants, sound_db, or STID."""
    if not object_id:
        return None

    res: str | None = None
    if custom_names and object_id in custom_names:
        res = custom_names[object_id]
    elif object_id in KNOWN_HASH_NAMES:
        res = KNOWN_HASH_NAMES[object_id]
    elif sound_db is not None and hasattr(sound_db, "resolve_hash"):
        res = sound_db.resolve_hash(object_id)

    if not res and bank.stid is not None:
        res = bank.stid.bank_names.get(object_id)

    return _clean_str(res)


def resolve_object_label(
    obj: HircObject,
    bank: SoundBank,
    name_resolver: Callable[[int], str | None],
    switch_target_map: dict[int, int] | None = None,
    label_cache: dict[int, str | None] | None = None,
) -> str | None:
    """Enriches HIRC object display labels by resolving underlying streams, targets, or lines."""
    if label_cache is not None and obj.id in label_cache:
        return label_cache[obj.id]

    direct = _clean_str(name_resolver(obj.id))
    if direct:
        if label_cache is not None:
            label_cache[obj.id] = direct
        return direct

    lbl: str | None = None
    if isinstance(obj, CAkSound):
        wem_id = getattr(obj, "source_id", 0) or getattr(obj, "file_id", 0)
        wem_lbl = _clean_str(name_resolver(wem_id)) if wem_id else None
        lbl = wem_lbl or (f"Sound (WEM {wem_id})" if wem_id else f"Sound_{obj.id}")
    elif isinstance(obj, CAkMusicTrack):
        wid = obj.sources[0].source_id if obj.sources else getattr(obj, "source_id", 0)
        lbl = _clean_str(name_resolver(wid)) if wid else f"MusicTrack_{obj.id}"
    elif isinstance(obj, CAkRanSeqCntr):
        if switch_target_map is None:
            switch_target_map = build_switch_target_map(bank)
        sw_val = switch_target_map.get(obj.id)
        if sw_val is not None:
            sw_name = name_resolver(sw_val)
            lbl = _clean_str(sw_name) or "Default Switch"

    lbl = _clean_str(lbl)
    if label_cache is not None:
        label_cache[obj.id] = lbl
    return lbl


def _extract_sound_wem_id(sound: CAkSound) -> int:
    """Extracts the underlying WEM ID from a CAkSound object."""
    if hasattr(sound, "bank_source_data") and sound.bank_source_data is not None:
        bsd = sound.bank_source_data
        if hasattr(bsd, "media_information") and bsd.media_information is not None:
            mid = int(getattr(bsd.media_information, "source_id", 0) or 0)
            if mid > 0:
                return mid
    return int(getattr(sound, "source_id", 0) or getattr(sound, "file_id", 0) or 0)


@dataclass(slots=True)
class BankGraphIndex:
    """Pre-indexed bidirectional graph of SoundBank HIRC objects for O(1) traversals."""

    child_map: dict[int, list[int]]
    parent_map: dict[int, list[int]]
    categorized: dict[str, list[HircObject]]
    roots: list[HircObject]
    switch_target_map: dict[int, int]
    label_cache: dict[int, str | None] = field(default_factory=dict)
    objects_by_id: dict[int, HircObject] = field(default_factory=dict)
    bank: SoundBank | None = None
    wem_references: dict[int, list[int]] = field(default_factory=dict)

    @classmethod
    def build(cls, bank: SoundBank) -> "BankGraphIndex":
        """Builds bidirectional relationship maps, categorization, and roots in O(N)."""
        child_map: dict[int, list[int]] = {}
        parent_map: dict[int, list[int]] = {}
        objects_by_id: dict[int, HircObject] = {}
        wem_references: dict[int, list[int]] = {}

        if bank.hirc:
            for obj in bank.hirc.objects:
                objects_by_id[obj.id] = obj
                parent_map[obj.id] = []

                if isinstance(obj, CAkSound):
                    wid = _extract_sound_wem_id(obj)
                    if wid > 0:
                        refs = wem_references.setdefault(wid, [])
                        if obj.id not in refs:
                            refs.append(obj.id)
                elif isinstance(obj, CAkMusicTrack):
                    track_wems: set[int] = set()
                    if hasattr(obj, "sources") and obj.sources:
                        for s in obj.sources:
                            sid = getattr(s, "source_id", 0) or getattr(s, "file_id", 0)
                            if sid > 0:
                                track_wems.add(sid)
                    if hasattr(obj, "playlist") and obj.playlist:
                        for p in obj.playlist:
                            pid = getattr(p, "source_id", 0)
                            if pid > 0:
                                track_wems.add(pid)
                    if not track_wems:
                        direct = getattr(obj, "source_id", 0) or getattr(obj, "file_id", 0)
                        if direct > 0:
                            track_wems.add(direct)
                    for wid in track_wems:
                        refs = wem_references.setdefault(wid, [])
                        if obj.id not in refs:
                            refs.append(obj.id)

            for obj in bank.hirc.objects:
                children = get_child_ids_for_object(obj)
                child_map[obj.id] = children
                for cid in children:
                    if cid not in parent_map:
                        parent_map[cid] = []
                    if obj.id not in parent_map[cid]:
                        parent_map[cid].append(obj.id)

        categorized = categorize_bank_objects(bank)
        roots = compute_root_objects(bank, child_map=child_map)
        switch_target_map = build_switch_target_map(bank)

        return cls(
            child_map=child_map,
            parent_map=parent_map,
            categorized=categorized,
            roots=roots,
            switch_target_map=switch_target_map,
            label_cache={},
            objects_by_id=objects_by_id,
            bank=bank,
            wem_references=wem_references,
        )

    def get_wem_referencing_hirc_ids(self, wem_id: int) -> list[int]:
        """Returns direct HIRC object IDs referencing the specified WEM source ID in O(1)."""
        if not wem_id or wem_id <= 0:
            return []
        return list(self.wem_references.get(wem_id, []))

    def get_child_ids(self, obj_id: int) -> list[int]:
        """Returns direct child IDs for the specified object ID in O(1)."""
        return list(self.child_map.get(obj_id, []))

    def get_parent_ids(self, target_id: int) -> list[int]:
        """Returns parent object IDs referencing the specified target ID in O(1)."""
        return list(self.parent_map.get(target_id, []))

    def get_root_objects(self) -> list[HircObject]:
        """Returns pre-calculated root objects."""
        return self.roots

    def get_categorized_objects(self) -> dict[str, list[HircObject]]:
        """Returns pre-calculated object categorization."""
        return self.categorized

    def resolve_label(self, obj: HircObject, sound_db: Any | None = None) -> str | None:
        """Resolves label for object using graph label cache and sound_db."""
        bank = self.bank
        if not bank:
            return None

        def resolver(hid: int) -> str | None:
            return resolve_hash_name(hid, bank, sound_db=sound_db)

        return resolve_object_label(
            obj,
            bank,
            name_resolver=resolver,
            switch_target_map=self.switch_target_map,
            label_cache=self.label_cache,
        )
