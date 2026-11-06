"""Total War SoundDatabase (Audio/event_data.dat) parser and serializer."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from src.bnk.stream import ByteReader, ByteWriter


def fnv1_32(text: str) -> int:
    """Computes standard Audiokinetic Wwise 32-bit FNV-1 hash with ASCII lowercasing."""
    if not text:
        return 0

    hash_val = 0x811C9DC5
    prime = 0x01000193

    for ch in text.lower().encode("ascii", errors="replace"):
        hash_val = ((hash_val * prime) ^ ch) & 0xFFFFFFFF

    return hash_val


def bank_id_from_string(bank_name: str) -> int:
    """Computes 32-bit FNV-1 ID for a SoundBank name stem, stripping path and extension."""
    base = os.path.basename(bank_name)
    stem = os.path.splitext(base)[0]
    return fnv1_32(stem)


def _read_tw_string(reader: ByteReader) -> str:
    """Reads a length-prefixed ASCII string."""
    length = reader.read_u32()
    data = reader.read_bytes(length)
    return data.decode("latin1")


def _write_tw_string(writer: ByteWriter, text: str) -> None:
    """Writes a length-prefixed ASCII string."""
    encoded = text.encode("latin1", errors="replace")
    writer.write_u32(len(encoded))
    writer.write_bytes(encoded)


@dataclass(slots=True)
class SoundEvent:
    """Sound event entry with duration and associated event ID."""

    name: str
    duration: float
    event_id: int


@dataclass(slots=True)
class SoundSwitchGroup:
    """Switch group and its associated switch values."""

    name: str
    group_id: int
    switches: dict[int, str] = field(default_factory=dict)
    switch_names: list[str] = field(default_factory=list)

    def add_switch(self, switch_name: str) -> int:
        switch_id = fnv1_32(switch_name)
        if switch_name not in self.switch_names:
            self.switch_names.append(switch_name)
        self.switches[switch_id] = switch_name
        return switch_id


@dataclass(slots=True)
class SoundStateGroup:
    """State group and its associated state values."""

    name: str
    group_id: int
    states: dict[int, str] = field(default_factory=dict)
    state_names: list[str] = field(default_factory=list)

    def add_state(self, state_name: str) -> int:
        state_id = fnv1_32(state_name)
        if state_name not in self.state_names:
            self.state_names.append(state_name)
        self.states[state_id] = state_name
        return state_id


@dataclass(slots=True)
class SoundDialogueEvent:
    """Dialogue event with argument group bindings."""

    name: str
    event_id: int
    argument_group_ids: list[int] = field(default_factory=list)


@dataclass(slots=True)
class SoundDatabase:
    """Total War Audio/event_data.dat repository."""

    events: dict[int, SoundEvent] = field(default_factory=dict)
    switch_groups: dict[int, SoundSwitchGroup] = field(default_factory=dict)
    state_groups: dict[int, SoundStateGroup] = field(default_factory=dict)
    dialogue_events: dict[int, SoundDialogueEvent] = field(default_factory=dict)
    rtpcs: dict[int, str] = field(default_factory=dict)
    conversational_vo: dict[int, dict[int, list[int]]] = field(default_factory=dict)
    hash_to_name: dict[int, str] = field(default_factory=dict)
    trailing_bytes: bytes = b""

    @classmethod
    def from_bytes(cls, data: bytes) -> Self:
        reader = ByteReader(data)
        db = cls()

        # Section 1: Events
        num_events = reader.read_u32()
        for _ in range(num_events):
            name = _read_tw_string(reader)
            duration = reader.read_f32()
            event_id = fnv1_32(name)
            rec = SoundEvent(name=name, duration=duration, event_id=event_id)
            db.events[event_id] = rec
            db.hash_to_name[event_id] = name

        # Section 2: Switch Groups
        num_switch_groups = reader.read_u32()
        for _ in range(num_switch_groups):
            group_name = _read_tw_string(reader)
            group_id = fnv1_32(group_name)
            db.hash_to_name[group_id] = group_name

            num_values = reader.read_u32()
            switches: dict[int, str] = {}
            switch_names: list[str] = []
            for _ in range(num_values):
                val_name = _read_tw_string(reader)
                val_id = fnv1_32(val_name)
                switches[val_id] = val_name
                switch_names.append(val_name)
                db.hash_to_name[val_id] = val_name

            db.switch_groups[group_id] = SoundSwitchGroup(
                name=group_name,
                group_id=group_id,
                switches=switches,
                switch_names=switch_names,
            )

        # Section 3: State Groups
        num_state_groups = reader.read_u32()
        for _ in range(num_state_groups):
            group_name = _read_tw_string(reader)
            group_id = fnv1_32(group_name)
            db.hash_to_name[group_id] = group_name

            num_values = reader.read_u32()
            states: dict[int, str] = {}
            state_names: list[str] = []
            for _ in range(num_values):
                val_name = _read_tw_string(reader)
                val_id = fnv1_32(val_name)
                states[val_id] = val_name
                state_names.append(val_name)
                db.hash_to_name[val_id] = val_name

            db.state_groups[group_id] = SoundStateGroup(
                name=group_name,
                group_id=group_id,
                states=states,
                state_names=state_names,
            )

        # Section 4: Dialogue Events
        num_dialogue = reader.read_u32()
        for _ in range(num_dialogue):
            event_name = _read_tw_string(reader)
            event_id = fnv1_32(event_name)
            db.hash_to_name[event_id] = event_name

            num_args = reader.read_u32()
            arg_group_ids = [reader.read_u32() for _ in range(num_args)]

            db.dialogue_events[event_id] = SoundDialogueEvent(
                name=event_name,
                event_id=event_id,
                argument_group_ids=arg_group_ids,
            )

        # Section 5: RTPCs
        num_rtpc = reader.read_u32()
        for _ in range(num_rtpc):
            rtpc_name = _read_tw_string(reader)
            rtpc_id = fnv1_32(rtpc_name)
            db.rtpcs[rtpc_id] = rtpc_name
            db.hash_to_name[rtpc_id] = rtpc_name

        # Section 6: Conversational VO
        num_outer = reader.read_u32()
        for _ in range(num_outer):
            outer_id = reader.read_u32()
            num_middle = reader.read_u32()
            middle_dict: dict[int, list[int]] = {}
            for _ in range(num_middle):
                middle_id = reader.read_u32()
                num_inner = reader.read_u32()
                inners = [reader.read_u32() for _ in range(num_inner)]
                middle_dict[middle_id] = inners
            db.conversational_vo[outer_id] = middle_dict

        if reader.remaining > 0:
            db.trailing_bytes = reader.read_remaining()

        return db

    @classmethod
    def from_file(cls, path: str | Path) -> Self:
        with open(path, "rb") as f:
            data = f.read()
        return cls.from_bytes(data)

    def to_bytes(self) -> bytes:
        writer = ByteWriter()

        # Section 1: Events
        writer.write_u32(len(self.events))
        for rec in self.events.values():
            _write_tw_string(writer, rec.name)
            writer.write_f32(rec.duration)

        # Section 2: Switch Groups
        writer.write_u32(len(self.switch_groups))
        for sg in self.switch_groups.values():
            _write_tw_string(writer, sg.name)
            writer.write_u32(len(sg.switch_names))
            for val_name in sg.switch_names:
                _write_tw_string(writer, val_name)

        # Section 3: State Groups
        writer.write_u32(len(self.state_groups))
        for stg in self.state_groups.values():
            _write_tw_string(writer, stg.name)
            writer.write_u32(len(stg.state_names))
            for val_name in stg.state_names:
                _write_tw_string(writer, val_name)

        # Section 4: Dialogue Events
        writer.write_u32(len(self.dialogue_events))
        for de in self.dialogue_events.values():
            _write_tw_string(writer, de.name)
            writer.write_u32(len(de.argument_group_ids))
            for arg_id in de.argument_group_ids:
                writer.write_u32(arg_id)

        # Section 5: RTPCs
        writer.write_u32(len(self.rtpcs))
        for rtpc_name in self.rtpcs.values():
            _write_tw_string(writer, rtpc_name)

        # Section 6: Conversational VO
        writer.write_u32(len(self.conversational_vo))
        for outer_id, middle_dict in self.conversational_vo.items():
            writer.write_u32(outer_id)
            writer.write_u32(len(middle_dict))
            for middle_id, inner_list in middle_dict.items():
                writer.write_u32(middle_id)
                writer.write_u32(len(inner_list))
                for de_id in inner_list:
                    writer.write_u32(de_id)

        if self.trailing_bytes:
            writer.write_bytes(self.trailing_bytes)

        return writer.get_bytes()

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    def lookup_event_id(self, name: str) -> int | None:
        event_id = fnv1_32(name)
        return event_id if event_id in self.events else None

    def resolve_hash(self, hash_id: int) -> str | None:
        return self.hash_to_name.get(hash_id)

    def add_event(self, name: str, duration: float = 0.0) -> SoundEvent:
        event_id = fnv1_32(name)
        rec = SoundEvent(name=name, duration=duration, event_id=event_id)
        self.events[event_id] = rec
        self.hash_to_name[event_id] = name
        return rec

    def add_switch_group(
        self, group_name: str, values: list[str] | None = None
    ) -> SoundSwitchGroup:
        group_id = fnv1_32(group_name)
        sg = self.switch_groups.get(group_id)
        if sg is None:
            sg = SoundSwitchGroup(name=group_name, group_id=group_id)
            self.switch_groups[group_id] = sg
            self.hash_to_name[group_id] = group_name

        if values:
            for val in values:
                sg.add_switch(val)
                self.hash_to_name[fnv1_32(val)] = val
        return sg

    def add_state_group(self, group_name: str, values: list[str] | None = None) -> SoundStateGroup:
        group_id = fnv1_32(group_name)
        stg = self.state_groups.get(group_id)
        if stg is None:
            stg = SoundStateGroup(name=group_name, group_id=group_id)
            self.state_groups[group_id] = stg
            self.hash_to_name[group_id] = group_name

        if values:
            for val in values:
                stg.add_state(val)
                self.hash_to_name[fnv1_32(val)] = val
        return stg

    def add_dialogue_event(
        self, name: str, argument_group_ids: list[int] | None = None
    ) -> SoundDialogueEvent:
        event_id = fnv1_32(name)
        de = SoundDialogueEvent(
            name=name,
            event_id=event_id,
            argument_group_ids=argument_group_ids if argument_group_ids is not None else [],
        )
        self.dialogue_events[event_id] = de
        self.hash_to_name[event_id] = name
        return de

    def add_rtpc(self, name: str) -> int:
        rtpc_id = fnv1_32(name)
        self.rtpcs[rtpc_id] = name
        self.hash_to_name[rtpc_id] = name
        return rtpc_id
