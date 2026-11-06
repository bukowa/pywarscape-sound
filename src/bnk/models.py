"""Audiokinetic Wwise v112 HIRC AST and shared parameter hierarchies."""

from dataclasses import dataclass, field
from typing import Self

from src.bnk.stream import ByteReader, ByteWriter

# ==============================================================================
# Shared Parameter Sub-Structures & RTPC
# ==============================================================================


@dataclass(slots=True)
class AkRtpcGraphPoint:
    """A single graph point on an RTPC conversion curve."""

    from_val: float
    to_val: float
    interp: int


@dataclass(slots=True)
class AkRtpcEntry:
    """Real-Time Parameter Control (RTPC) subscription entry."""

    rtpc_id: int
    rtpc_type: int
    rtpc_accum: int
    param_id: int
    rtpc_curve_id: int
    scaling: int
    points: list[AkRtpcGraphPoint] = field(default_factory=list)

    @classmethod
    def read_list(cls, reader: ByteReader) -> list["AkRtpcEntry"]:
        count = reader.read_u16()
        rtpcs: list[AkRtpcEntry] = []
        for _ in range(count):
            rtpc_id, rtpc_type, rtpc_accum, param_id, curve_id, scaling, pts_cnt = (
                reader.read_struct("<IBBBIBH")
            )
            pts: list[AkRtpcGraphPoint] = []
            for _ in range(pts_cnt):
                fv, tv, interp = reader.read_struct("<ffI")
                pts.append(AkRtpcGraphPoint(fv, tv, interp))
            rtpcs.append(
                cls(
                    rtpc_id=rtpc_id,
                    rtpc_type=rtpc_type,
                    rtpc_accum=rtpc_accum,
                    param_id=param_id,
                    rtpc_curve_id=curve_id,
                    scaling=scaling,
                    points=pts,
                )
            )
        return rtpcs

    @classmethod
    def write_list(cls, writer: ByteWriter, rtpcs: list["AkRtpcEntry"]) -> None:
        writer.write_u16(len(rtpcs))
        for rtpc in rtpcs:
            writer.write_struct(
                "<IBBBIBH",
                rtpc.rtpc_id,
                rtpc.rtpc_type,
                rtpc.rtpc_accum,
                rtpc.param_id,
                rtpc.rtpc_curve_id,
                rtpc.scaling,
                len(rtpc.points),
            )
            for pt in rtpc.points:
                writer.write_struct("<ffI", pt.from_val, pt.to_val, pt.interp)


@dataclass(slots=True)
class AkStateGroupChunk:
    """State group synchronization chunk binding states to instances."""

    state_group_id: int
    sync_type: int
    states: list[tuple[int, int]] = field(default_factory=list)

    @classmethod
    def read_list(cls, reader: ByteReader) -> list["AkStateGroupChunk"]:
        num_sg = reader.read_u32()
        state_groups: list[AkStateGroupChunk] = []
        for _ in range(num_sg):
            sg_id, sync_type, num_states = reader.read_struct("<IBH")
            states: list[tuple[int, int]] = []
            if num_states > 0:
                flat = reader.read_struct(f"<{num_states * 2}I")
                states = [(flat[i * 2], flat[i * 2 + 1]) for i in range(num_states)]
            state_groups.append(cls(state_group_id=sg_id, sync_type=sync_type, states=states))
        return state_groups

    @classmethod
    def write_list(cls, writer: ByteWriter, state_groups: list["AkStateGroupChunk"]) -> None:
        writer.write_u32(len(state_groups))
        for sg in state_groups:
            writer.write_struct("<IBH", sg.state_group_id, sg.sync_type, len(sg.states))
            for sid, sinst in sg.states:
                writer.write_struct("<II", sid, sinst)


@dataclass(slots=True)
class AkPathVertex:
    """3D positioning path vertex in an audio trajectory (16 bytes)."""

    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    duration: int = 0


@dataclass(slots=True)
class AkPathListItemOffset:
    """Path playlist item vertex range (8 bytes)."""

    vertices_offset: int = 0
    num_vertices: int = 0


@dataclass(slots=True)
class Ak3DAutomationParams:
    """3D automation random range parameters (12 bytes)."""

    x_range: float = 0.0
    y_range: float = 0.0
    z_range: float = 0.0


@dataclass(slots=True)
class AkPositioningParams:
    """Positioning and 3D spatialization parameters for Wwise v112."""

    bits_positioning: int = 0
    bits_3d: int | None = None
    attenuation_id: int | None = None
    path_mode: int | None = None
    transition_time: int | None = None
    vertices: list[AkPathVertex] = field(default_factory=list)
    playlist_items: list[AkPathListItemOffset] = field(default_factory=list)
    automation_params: list[Ak3DAutomationParams] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        bits_positioning = reader.read_u8()
        bits_3d = None
        attenuation_id = None
        path_mode = None
        transition_time = None
        vertices: list[AkPathVertex] = []
        playlist_items: list[AkPathListItemOffset] = []
        automation_params: list[Ak3DAutomationParams] = []

        if (bits_positioning & 1) == 1 and ((bits_positioning >> 3) & 1) == 1:
            bits_3d = reader.read_u8()
            attenuation_id = reader.read_u32()
            if (bits_3d & 3) != 1:
                path_mode = reader.read_u8()
                transition_time = reader.read_i32()
                num_verts = reader.read_u32()
                for _ in range(num_verts):
                    x, y, z, dur = reader.read_struct("<fffi")
                    vertices.append(AkPathVertex(x=x, y=y, z=z, duration=dur))
                num_pl = reader.read_u32()
                for _ in range(num_pl):
                    off, cnt = reader.read_struct("<II")
                    playlist_items.append(
                        AkPathListItemOffset(vertices_offset=off, num_vertices=cnt)
                    )
                for _ in range(num_pl):
                    xr, yr, zr = reader.read_struct("<fff")
                    automation_params.append(
                        Ak3DAutomationParams(x_range=xr, y_range=yr, z_range=zr)
                    )

        return cls(
            bits_positioning=bits_positioning,
            bits_3d=bits_3d,
            attenuation_id=attenuation_id,
            path_mode=path_mode,
            transition_time=transition_time,
            vertices=vertices,
            playlist_items=playlist_items,
            automation_params=automation_params,
        )

    def write(self, writer: ByteWriter) -> None:
        writer.write_u8(self.bits_positioning)
        if (self.bits_positioning & 1) == 1 and ((self.bits_positioning >> 3) & 1) == 1:
            writer.write_u8(self.bits_3d if self.bits_3d is not None else 0)
            writer.write_u32(self.attenuation_id if self.attenuation_id is not None else 0)
            if ((self.bits_3d if self.bits_3d is not None else 0) & 3) != 1:
                writer.write_u8(self.path_mode or 0)
                writer.write_i32(self.transition_time or 0)
                writer.write_u32(len(self.vertices))
                for v in self.vertices:
                    writer.write_struct("<fffi", v.x, v.y, v.z, v.duration)
                writer.write_u32(len(self.playlist_items))
                for item in self.playlist_items:
                    writer.write_struct("<II", item.vertices_offset, item.num_vertices)
                for auto in self.automation_params:
                    writer.write_struct("<fff", auto.x_range, auto.y_range, auto.z_range)

    def to_bytes(self) -> bytes:
        writer = ByteWriter()
        self.write(writer)
        return writer.get_bytes()


@dataclass(slots=True)
class AkAdvSettingsParams:
    """Advanced sound engine playback settings (6 bytes)."""

    bit_vector: int = 0
    virtual_queue_behavior: int = 0
    max_num_instance: int = 0
    below_threshold_behavior: int = 0
    hdr_bit_vector: int = 0

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        bv, vqb, mni, btb, hbv = reader.read_struct("<BBHBB")
        return cls(
            bit_vector=bv,
            virtual_queue_behavior=vqb,
            max_num_instance=mni,
            below_threshold_behavior=btb,
            hdr_bit_vector=hbv,
        )

    def write(self, writer: ByteWriter) -> None:
        writer.write_struct(
            "<BBHBB",
            self.bit_vector,
            self.virtual_queue_behavior,
            self.max_num_instance,
            self.below_threshold_behavior,
            self.hdr_bit_vector,
        )

    def to_bytes(self) -> bytes:
        writer = ByteWriter()
        self.write(writer)
        return writer.get_bytes()


@dataclass(slots=True)
class NodeBaseParams:
    """Shared parameter hierarchy for all Wwise v112 actor/sound/container nodes."""

    is_override_fx: int = 0
    fx_chunks: list[tuple[int, int, int, int]] = field(default_factory=list)
    bits_fx: int = 0
    override_attachment: int = 0
    override_bus_id: int = 0
    direct_parent_id: int = 0
    bit_vector: int = 0
    props: dict[int, float] = field(default_factory=dict)
    ranged_props: dict[int, tuple[float, float]] = field(default_factory=dict)
    positioning: AkPositioningParams = field(default_factory=AkPositioningParams)
    aux_bits: int = 0
    aux_bus_ids: list[int] = field(default_factory=list)
    adv_settings: AkAdvSettingsParams = field(default_factory=AkAdvSettingsParams)
    state_groups: list[AkStateGroupChunk] = field(default_factory=list)
    rtpcs: list[AkRtpcEntry] = field(default_factory=list)
    feedback_bus_id: int | None = None

    @property
    def attenuation_id(self) -> int | None:
        return self.positioning.attenuation_id

    @attenuation_id.setter
    def attenuation_id(self, value: int | None) -> None:
        self.positioning.attenuation_id = value

    @classmethod
    def read(cls, reader: ByteReader, feedback_in_bank: bool = False) -> Self:
        # 1. FX params
        is_override_fx, num_fx = reader.read_struct("<BB")
        bits_fx = 0
        fx_chunks: list[tuple[int, int, int, int]] = []
        if num_fx != 0:
            bits_fx = reader.read_u8()
            for _ in range(num_fx):
                fx_chunks.append(reader.read_struct("<BIBB"))

        # 2. Base params
        override_attachment, override_bus_id, direct_parent_id, bit_vector = reader.read_struct(
            "<BIIB"
        )

        # 3. PropBundle0 (single float properties)
        props0_count = reader.read_u8()
        if props0_count > 0:
            prop0_ids = reader.read_bytes(props0_count)
            prop0_vals = reader.read_struct(f"<{props0_count}f")
            props = dict(zip(prop0_ids, prop0_vals))
        else:
            props = {}

        # PropBundle1 (ranged min/max properties)
        props1_count = reader.read_u8()
        if props1_count > 0:
            prop1_ids = reader.read_bytes(props1_count)
            flat_vals = reader.read_struct(f"<{props1_count * 2}f")
            ranged_props = {
                prop1_ids[i]: (flat_vals[i * 2], flat_vals[i * 2 + 1]) for i in range(props1_count)
            }
        else:
            ranged_props = {}

        # 4. Positioning
        positioning = AkPositioningParams.read(reader)

        # 5. Aux params
        aux_bits = reader.read_u8()
        aux_bus_ids: list[int] = []
        if ((aux_bits >> 3) & 1) == 1:
            aux_bus_ids = list(reader.read_struct("<IIII"))

        # 6. Advanced Settings
        adv_settings = AkAdvSettingsParams.read(reader)

        # 7. State groups
        state_groups = AkStateGroupChunk.read_list(reader)

        # 8. RTPCs
        rtpcs = AkRtpcEntry.read_list(reader)

        # 9. Feedback bus
        feedback_bus_id = None
        if feedback_in_bank and reader.remaining >= 4:
            feedback_bus_id = reader.read_u32()

        return cls(
            is_override_fx=is_override_fx,
            fx_chunks=fx_chunks,
            bits_fx=bits_fx,
            override_attachment=override_attachment,
            override_bus_id=override_bus_id,
            direct_parent_id=direct_parent_id,
            bit_vector=bit_vector,
            props=props,
            ranged_props=ranged_props,
            positioning=positioning,
            aux_bits=aux_bits,
            aux_bus_ids=aux_bus_ids,
            adv_settings=adv_settings,
            state_groups=state_groups,
            rtpcs=rtpcs,
            feedback_bus_id=feedback_bus_id,
        )

    def write(self, writer: ByteWriter) -> None:
        # 1. FX params
        writer.write_struct("<BB", self.is_override_fx, len(self.fx_chunks))
        if self.fx_chunks:
            writer.write_u8(self.bits_fx)
            for chunk in self.fx_chunks:
                writer.write_struct("<BIBB", chunk[0], chunk[1], chunk[2], chunk[3])

        # 2. Base params
        writer.write_struct(
            "<BIIB",
            self.override_attachment,
            self.override_bus_id,
            self.direct_parent_id,
            self.bit_vector,
        )

        # 3. PropBundle0
        writer.write_u8(len(self.props))
        if self.props:
            writer.write_bytes(bytes(self.props.keys()))
            writer.write_struct(f"<{len(self.props)}f", *self.props.values())

        # PropBundle1
        writer.write_u8(len(self.ranged_props))
        if self.ranged_props:
            writer.write_bytes(bytes(self.ranged_props.keys()))
            flat_ranged: list[float] = []
            for rmin, rmax in self.ranged_props.values():
                flat_ranged.extend((rmin, rmax))
            writer.write_struct(f"<{len(flat_ranged)}f", *flat_ranged)

        # 4. Positioning
        self.positioning.write(writer)

        # 5. Aux
        writer.write_u8(self.aux_bits)
        if ((self.aux_bits >> 3) & 1) == 1:
            for ab_id in self.aux_bus_ids:
                writer.write_u32(ab_id)

        # 6. Advanced settings
        self.adv_settings.write(writer)

        # 7. State groups
        AkStateGroupChunk.write_list(writer, self.state_groups)

        # 8. RTPCs
        AkRtpcEntry.write_list(writer, self.rtpcs)

        # 9. Feedback
        if self.feedback_bus_id is not None:
            writer.write_u32(self.feedback_bus_id)

    def to_bytes(self) -> bytes:
        writer = ByteWriter()
        self.write(writer)
        return writer.get_bytes()


# ==============================================================================
# Container, Ducking & Decision Tree Sub-Structures
# ==============================================================================


@dataclass(slots=True)
class ActionException:
    """Action exception item bypassing action execution."""

    id: int = 0
    is_bus: int = 0


@dataclass(slots=True)
class ActionParams:
    """Action parameters payload extracted according to Wwise v112 action type."""

    props: dict[int, float] = field(default_factory=dict)
    ranged_props: dict[int, tuple[float, float]] = field(default_factory=dict)
    fade_curve: int | None = None
    bank_id: int | None = None
    switch_group_id: int | None = None
    switch_state_id: int | None = None
    state_group_id: int | None = None
    target_state_id: int | None = None
    active_flags: int | None = None
    bypass_transition: int | None = None
    value_meaning: int | None = None
    randomizer_base: float | None = None
    randomizer_min: float | None = None
    randomizer_max: float | None = None
    is_bypass: int | None = None
    target_mask: int | None = None
    is_seek_relative_to_duration: int | None = None
    snap_to_nearest_marker: int | None = None
    exceptions: list[ActionException] = field(default_factory=list)

    @classmethod
    def from_bytes(cls, data: bytes, action_type: int) -> Self:
        if not data:
            return cls()
        reader = ByteReader(data)
        num_props = reader.read_u8()
        prop_ids = reader.read_bytes(num_props) if num_props > 0 else b""
        prop_vals = reader.read_struct(f"<{num_props}f") if num_props > 0 else ()
        props = dict(zip(prop_ids, prop_vals))

        num_range = reader.read_u8()
        range_ids = reader.read_bytes(num_range) if num_range > 0 else b""
        flat_range = reader.read_struct(f"<{num_range * 2}f") if num_range > 0 else ()
        ranged_props = {
            range_ids[i]: (flat_range[i * 2], flat_range[i * 2 + 1]) for i in range(num_range)
        }

        fade_curve = None
        bank_id = None
        switch_group_id = None
        switch_state_id = None
        state_group_id = None
        target_state_id = None
        active_flags = None
        bypass_transition = None
        value_meaning = None
        randomizer_base = None
        randomizer_min = None
        randomizer_max = None
        is_bypass = None
        target_mask = None
        is_seek_relative_to_duration = None
        snap_to_nearest_marker = None
        exceptions: list[ActionException] = []

        cat = (action_type >> 8) & 0xFF
        if cat == 0x04:  # Play
            fade_curve, bank_id = reader.read_struct("<BI")
        elif cat == 0x12:  # SetState
            state_group_id, target_state_id = reader.read_struct("<II")
        elif cat == 0x19:  # SetSwitch
            switch_group_id, switch_state_id = reader.read_struct("<II")
        elif cat in (0x01, 0x06, 0x07):  # Stop, Mute, Unmute
            fade_curve = reader.read_u8()
            exc_cnt = reader.read_u32()
            for _ in range(exc_cnt):
                eid, is_bus = reader.read_struct("<IB")
                exceptions.append(ActionException(id=eid, is_bus=is_bus))
        elif cat in (0x02, 0x03):  # Pause, Resume
            fade_curve, active_flags = reader.read_struct("<BB")
            exc_cnt = reader.read_u32()
            for _ in range(exc_cnt):
                eid, is_bus = reader.read_struct("<IB")
                exceptions.append(ActionException(id=eid, is_bus=is_bus))
        elif cat in (0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F):  # SetAkProp
            fade_curve, value_meaning, r_base, r_min, r_max = reader.read_struct("<BBfff")
            randomizer_base, randomizer_min, randomizer_max = r_base, r_min, r_max
            exc_cnt = reader.read_u32()
            for _ in range(exc_cnt):
                eid, is_bus = reader.read_struct("<IB")
                exceptions.append(ActionException(id=eid, is_bus=is_bus))
        elif cat == 0x13:  # SetGameParameter
            fade_curve, bypass_transition, value_meaning, r_base, r_min, r_max = reader.read_struct(
                "<BBBfff"
            )
            randomizer_base, randomizer_min, randomizer_max = r_base, r_min, r_max
            exc_cnt = reader.read_u32()
            for _ in range(exc_cnt):
                eid, is_bus = reader.read_struct("<IB")
                exceptions.append(ActionException(id=eid, is_bus=is_bus))
        elif cat == 0x1A:  # BypassFX
            is_bypass, target_mask = reader.read_struct("<BB")
            exc_cnt = reader.read_u32()
            for _ in range(exc_cnt):
                eid, is_bus = reader.read_struct("<IB")
                exceptions.append(ActionException(id=eid, is_bus=is_bus))
        elif cat == 0x1E:  # Seek
            is_seek_relative_to_duration, r_base, r_min, r_max, snap_to_nearest_marker = (
                reader.read_struct("<BfffB")
            )
            randomizer_base, randomizer_min, randomizer_max = r_base, r_min, r_max
            exc_cnt = reader.read_u32()
            for _ in range(exc_cnt):
                eid, is_bus = reader.read_struct("<IB")
                exceptions.append(ActionException(id=eid, is_bus=is_bus))
        elif cat in (0x10, 0x1C):  # Break, Trigger
            pass
        else:
            raise ValueError(
                f"Unsupported action category 0x{cat:02X} for action type 0x{action_type:04X}"
            )

        if reader.remaining != 0:
            raise ValueError(
                f"Unparsed trailing bytes ({reader.remaining}) in ActionParams for action type 0x{action_type:04X}"
            )

        return cls(
            props=props,
            ranged_props=ranged_props,
            fade_curve=fade_curve,
            bank_id=bank_id,
            switch_group_id=switch_group_id,
            switch_state_id=switch_state_id,
            state_group_id=state_group_id,
            target_state_id=target_state_id,
            active_flags=active_flags,
            bypass_transition=bypass_transition,
            value_meaning=value_meaning,
            randomizer_base=randomizer_base,
            randomizer_min=randomizer_min,
            randomizer_max=randomizer_max,
            is_bypass=is_bypass,
            target_mask=target_mask,
            is_seek_relative_to_duration=is_seek_relative_to_duration,
            snap_to_nearest_marker=snap_to_nearest_marker,
            exceptions=exceptions,
        )

    def to_bytes(self, action_type: int) -> bytes:
        writer = ByteWriter()
        writer.write_u8(len(self.props))
        if self.props:
            writer.write_bytes(bytes(self.props.keys()))
            writer.write_struct(f"<{len(self.props)}f", *self.props.values())

        writer.write_u8(len(self.ranged_props))
        if self.ranged_props:
            writer.write_bytes(bytes(self.ranged_props.keys()))
            flat_range: list[float] = []
            for rmin, rmax in self.ranged_props.values():
                flat_range.extend((rmin, rmax))
            writer.write_struct(f"<{len(flat_range)}f", *flat_range)

        cat = (action_type >> 8) & 0xFF
        if cat == 0x04:
            writer.write_struct(
                "<BI",
                self.fade_curve if self.fade_curve is not None else 4,
                self.bank_id if self.bank_id is not None else 0,
            )
        elif cat == 0x12:
            writer.write_struct(
                "<II",
                self.state_group_id if self.state_group_id is not None else 0,
                self.target_state_id if self.target_state_id is not None else 0,
            )
        elif cat == 0x19:
            writer.write_struct(
                "<II",
                self.switch_group_id if self.switch_group_id is not None else 0,
                self.switch_state_id if self.switch_state_id is not None else 0,
            )
        elif cat in (0x01, 0x06, 0x07):
            writer.write_u8(self.fade_curve if self.fade_curve is not None else 0)
            writer.write_u32(len(self.exceptions))
            for exc in self.exceptions:
                writer.write_struct("<IB", exc.id, exc.is_bus)
        elif cat in (0x02, 0x03):
            writer.write_struct(
                "<BB",
                self.fade_curve if self.fade_curve is not None else 0,
                self.active_flags if self.active_flags is not None else 0,
            )
            writer.write_u32(len(self.exceptions))
            for exc in self.exceptions:
                writer.write_struct("<IB", exc.id, exc.is_bus)
        elif cat in (0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F):
            writer.write_struct(
                "<BBfff",
                self.fade_curve if self.fade_curve is not None else 0,
                self.value_meaning if self.value_meaning is not None else 0,
                self.randomizer_base if self.randomizer_base is not None else 0.0,
                self.randomizer_min if self.randomizer_min is not None else 0.0,
                self.randomizer_max if self.randomizer_max is not None else 0.0,
            )
            writer.write_u32(len(self.exceptions))
            for exc in self.exceptions:
                writer.write_struct("<IB", exc.id, exc.is_bus)
        elif cat == 0x13:
            writer.write_struct(
                "<BBBfff",
                self.fade_curve if self.fade_curve is not None else 0,
                self.bypass_transition if self.bypass_transition is not None else 0,
                self.value_meaning if self.value_meaning is not None else 0,
                self.randomizer_base if self.randomizer_base is not None else 0.0,
                self.randomizer_min if self.randomizer_min is not None else 0.0,
                self.randomizer_max if self.randomizer_max is not None else 0.0,
            )
            writer.write_u32(len(self.exceptions))
            for exc in self.exceptions:
                writer.write_struct("<IB", exc.id, exc.is_bus)
        elif cat == 0x1A:
            writer.write_struct(
                "<BB",
                self.is_bypass if self.is_bypass is not None else 0,
                self.target_mask if self.target_mask is not None else 0,
            )
            writer.write_u32(len(self.exceptions))
            for exc in self.exceptions:
                writer.write_struct("<IB", exc.id, exc.is_bus)
        elif cat == 0x1E:
            writer.write_struct(
                "<BfffB",
                self.is_seek_relative_to_duration
                if self.is_seek_relative_to_duration is not None
                else 0,
                self.randomizer_base if self.randomizer_base is not None else 0.0,
                self.randomizer_min if self.randomizer_min is not None else 0.0,
                self.randomizer_max if self.randomizer_max is not None else 0.0,
                self.snap_to_nearest_marker if self.snap_to_nearest_marker is not None else 0,
            )
            writer.write_u32(len(self.exceptions))
            for exc in self.exceptions:
                writer.write_struct("<IB", exc.id, exc.is_bus)
        elif cat in (0x10, 0x1C):
            pass

        return writer.get_bytes()


@dataclass(slots=True)
class AkPlaylistItem:
    """Random/Sequence container playlist variation item."""

    play_id: int
    weight: int = 50000


@dataclass(slots=True)
class AkSwitchParam:
    """Switch parameter record for CAkSwitchCntr."""

    node_id: int
    bit_vector0: int = 0
    bit_vector1: int = 0
    fade_out_time: float = 0.0
    fade_in_time: float = 0.0

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        nid, bv0, bv1, fot, fit = reader.read_struct("<IBBff")
        return cls(
            node_id=nid, bit_vector0=bv0, bit_vector1=bv1, fade_out_time=fot, fade_in_time=fit
        )

    def write(self, writer: ByteWriter) -> None:
        writer.write_struct(
            "<IBBff",
            self.node_id,
            self.bit_vector0,
            self.bit_vector1,
            self.fade_out_time,
            self.fade_in_time,
        )


@dataclass(slots=True)
class AkDuckInfo:
    """Bus ducking rule specification for CAkBus and CAkAuxBus."""

    bus_id: int
    duck_volume: float = 0.0
    fade_out_time: int = 0
    fade_in_time: int = 0
    fade_curve: int = 0
    target_prop: int = 0

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        bid, dv, fot, fit, fc, tp = reader.read_struct("<IfiiBB")
        return cls(
            bus_id=bid,
            duck_volume=dv,
            fade_out_time=fot,
            fade_in_time=fit,
            fade_curve=fc,
            target_prop=tp,
        )

    def write(self, writer: ByteWriter) -> None:
        writer.write_struct(
            "<IfiiBB",
            self.bus_id,
            self.duck_volume,
            self.fade_out_time,
            self.fade_in_time,
            self.fade_curve,
            self.target_prop,
        )


@dataclass(slots=True)
class CAkLayerAssoc:
    """Association linking child sounds to crossfade curve in CAkLayer."""

    child_id: int
    curve_points: list[tuple[float, float, int]] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        child_id, num_points = reader.read_struct("<II")
        points = []
        for _ in range(num_points):
            points.append(reader.read_struct("<ffI"))
        return cls(child_id=child_id, curve_points=points)

    def write(self, writer: ByteWriter) -> None:
        writer.write_struct("<II", self.child_id, len(self.curve_points))
        for fv, tv, interp in self.curve_points:
            writer.write_struct("<ffI", fv, tv, interp)


@dataclass(slots=True)
class CAkLayerRtpc:
    """Layer-specific RTPC curve binding."""

    rtpc_id: int
    rtpc_type: int
    rtpc_accum: int
    param_id: int
    rtpc_curve_id: int
    scaling: int
    points: list[tuple[float, float, int]] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        rid, rtype, raccum, pid, cid, sc, num_pts = reader.read_struct("<IBBBIBH")
        points = [reader.read_struct("<ffI") for _ in range(num_pts)]
        return cls(
            rtpc_id=rid,
            rtpc_type=rtype,
            rtpc_accum=raccum,
            param_id=pid,
            rtpc_curve_id=cid,
            scaling=sc,
            points=points,
        )

    def write(self, writer: ByteWriter) -> None:
        writer.write_struct(
            "<IBBBIBH",
            self.rtpc_id,
            self.rtpc_type,
            self.rtpc_accum,
            self.param_id,
            self.rtpc_curve_id,
            self.scaling,
            len(self.points),
        )
        for fv, tv, interp in self.points:
            writer.write_struct("<ffI", fv, tv, interp)


@dataclass(slots=True)
class CAkLayer:
    """Blend/crossfading layer in CAkLayerCntr."""

    layer_id: int
    rtpc_entries: list[CAkLayerRtpc] = field(default_factory=list)
    crossfading_rtpc_id: int = 0
    crossfading_rtpc_type: int = 0
    associations: list[CAkLayerAssoc] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        lid, num_rtpc = reader.read_struct("<IH")
        rtpc_entries = [CAkLayerRtpc.read(reader) for _ in range(num_rtpc)]
        c_rid, c_rtype, num_assocs = reader.read_struct("<IBI")
        associations = [CAkLayerAssoc.read(reader) for _ in range(num_assocs)]
        return cls(
            layer_id=lid,
            rtpc_entries=rtpc_entries,
            crossfading_rtpc_id=c_rid,
            crossfading_rtpc_type=c_rtype,
            associations=associations,
        )

    def write(self, writer: ByteWriter) -> None:
        writer.write_struct("<IH", self.layer_id, len(self.rtpc_entries))
        for rtpc in self.rtpc_entries:
            rtpc.write(writer)
        writer.write_struct(
            "<IBI", self.crossfading_rtpc_id, self.crossfading_rtpc_type, len(self.associations)
        )
        for assoc in self.associations:
            assoc.write(writer)


@dataclass(slots=True)
class AkAttenuationCurve:
    """Distance attenuation curve (Volume, LPF, HPF)."""

    scaling: int = 0
    points: list[tuple[float, float, int]] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        scaling, num_points = reader.read_struct("<BH")
        points = [reader.read_struct("<ffI") for _ in range(num_points)]
        return cls(scaling=scaling, points=points)

    def write(self, writer: ByteWriter) -> None:
        writer.write_struct("<BH", self.scaling, len(self.points))
        for fv, tv, interp in self.points:
            writer.write_struct("<ffI", fv, tv, interp)


@dataclass(slots=True)
class DecisionTreeNode:
    """12-byte node in Wwise v112 AkDecisionTree."""

    key: int
    audio_node_id: int = 0
    children_idx: int = 0
    children_count: int = 0
    weight: int = 50
    probability: int = 100
    is_leaf: bool = False
    children: list["DecisionTreeNode"] = field(default_factory=list)


@dataclass(slots=True)
class AkDecisionTree:
    """Multidimensional decision tree for dialogue and interactive music routing."""

    root: DecisionTreeNode = field(default_factory=lambda: DecisionTreeNode(key=0))
    nodes: list[DecisionTreeNode] = field(default_factory=list)
    max_depth: int = 0

    @classmethod
    def read(cls, reader: ByteReader, tree_data_size: int, max_depth: int) -> Self:
        node_count = tree_data_size // 12
        raw_nodes: list[DecisionTreeNode] = []

        for _ in range(node_count):
            key, mid, weight, prob = reader.read_struct("<IIHH")
            c_idx, c_cnt = mid & 0xFFFF, (mid >> 16) & 0xFFFF
            is_over = (c_idx + c_cnt) > node_count
            is_audio_node = (c_idx > node_count) or (c_cnt > node_count) or is_over
            raw_nodes.append(
                DecisionTreeNode(
                    key=key,
                    audio_node_id=mid,
                    children_idx=c_idx,
                    children_count=c_cnt,
                    weight=weight,
                    probability=prob,
                    is_leaf=is_audio_node,
                )
            )

        def build_branch(node_idx: int, current_depth: int) -> DecisionTreeNode:
            if node_idx >= len(raw_nodes):
                return DecisionTreeNode(key=0, is_leaf=True)
            node = raw_nodes[node_idx]
            if current_depth == max_depth or node.is_leaf:
                node.is_leaf = True
                return node
            node.is_leaf = False
            children = []
            for i in range(node.children_count):
                child_idx = node.children_idx + i
                if child_idx < len(raw_nodes):
                    child = build_branch(child_idx, current_depth + 1)
                    children.append(child)
            node.children = children
            return node

        root = build_branch(0, 0) if raw_nodes else DecisionTreeNode(key=0, is_leaf=True)
        return cls(root=root, nodes=raw_nodes, max_depth=max_depth)

    def to_bytes(self) -> bytes:
        writer = ByteWriter()
        for node in self.nodes:
            writer.write_u32(node.key)
            if node.is_leaf:
                writer.write_u32(node.audio_node_id)
            else:
                mid = (node.children_idx & 0xFFFF) | ((node.children_count & 0xFFFF) << 16)
                writer.write_u32(mid)
            writer.write_struct("<HH", node.weight, node.probability)
        return writer.get_bytes()

    def get_all_leaf_audio_node_ids(self) -> list[int]:
        """Returns unique non-zero audio_node_id values across all leaf nodes in declaration order."""
        result: list[int] = []
        seen = set()
        for node in self.nodes:
            if node.is_leaf and node.audio_node_id != 0:
                if node.audio_node_id not in seen:
                    seen.add(node.audio_node_id)
                    result.append(node.audio_node_id)
        return result


@dataclass(slots=True)
class AkMusicMarker:
    """Interactive music cue marker."""

    id: int
    position: float
    name: str = ""

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        mid, pos, nlen = reader.read_struct("<IdI")
        name = ""
        if nlen > 0:
            name = reader.read_bytes(nlen).decode("utf-8", errors="replace")
        return cls(id=mid, position=pos, name=name)

    def write(self, writer: ByteWriter) -> None:
        enc = self.name.encode("utf-8") if self.name else b""
        writer.write_struct("<IdI", self.id, self.position, len(enc))
        if enc:
            writer.write_bytes(enc)


@dataclass(slots=True)
class AkMusicStinger:
    """Stinger definition (24 bytes)."""

    trigger_id: int = 0
    segment_id: int = 0
    sync_play_at: int = 0
    cue_filter_hash: int = 0
    dont_repeat_time: int = 0
    num_segment_look_ahead: int = 0

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        t_id, s_id, spa, cfh, drt, nsla = reader.read_struct("<IIIIiI")
        return cls(
            trigger_id=t_id,
            segment_id=s_id,
            sync_play_at=spa,
            cue_filter_hash=cfh,
            dont_repeat_time=drt,
            num_segment_look_ahead=nsla,
        )

    def write(self, writer: ByteWriter) -> None:
        writer.write_struct(
            "<IIIIiI",
            self.trigger_id,
            self.segment_id,
            self.sync_play_at,
            self.cue_filter_hash,
            self.dont_repeat_time,
            self.num_segment_look_ahead,
        )


@dataclass(slots=True)
class AkMusicTrackSource:
    """Media source descriptor for CAkMusicTrack."""

    plugin_id: int = 0x00040001
    stream_type: int = 2
    source_id: int = 0
    file_id: int = 0
    file_offset: int | None = None
    in_memory_media_size: int = 0
    source_bits: int = 0
    plugin_params: bytes = b""

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        pl_id, st_type, src_id, f_id = reader.read_struct("<IBII")
        f_off = None
        if st_type != 2:
            f_off = reader.read_u32()
        imms, s_bits = reader.read_struct("<IB")
        pl_params = b""
        if (pl_id & 0x0F) in (2, 5):
            extra_sz = reader.read_u32()
            if extra_sz > 0 and reader.remaining > 0:
                pl_params = reader.read_bytes(min(extra_sz, reader.remaining))
        return cls(
            plugin_id=pl_id,
            stream_type=st_type,
            source_id=src_id,
            file_id=f_id,
            file_offset=f_off,
            in_memory_media_size=imms,
            source_bits=s_bits,
            plugin_params=pl_params,
        )

    def write(self, writer: ByteWriter) -> None:
        writer.write_struct("<IBII", self.plugin_id, self.stream_type, self.source_id, self.file_id)
        if self.stream_type != 2:
            writer.write_u32(self.file_offset if self.file_offset is not None else 0)
        writer.write_struct("<IB", self.in_memory_media_size, self.source_bits)
        if (self.plugin_id & 0x0F) in (2, 5):
            writer.write_u32(len(self.plugin_params))
            if self.plugin_params:
                writer.write_bytes(self.plugin_params)


@dataclass(slots=True)
class AkTrackSrcInfo:
    """Playlist timing descriptor for CAkMusicTrack."""

    track_id: int = 0
    source_id: int = 0
    play_at: float = 0.0
    begin_trim_offset: float = 0.0
    end_trim_offset: float = 0.0
    src_duration: float = 0.0

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        tid, sid, pa, bto, eto, dur = reader.read_struct("<IIdddd")
        return cls(
            track_id=tid,
            source_id=sid,
            play_at=pa,
            begin_trim_offset=bto,
            end_trim_offset=eto,
            src_duration=dur,
        )

    def write(self, writer: ByteWriter) -> None:
        writer.write_struct(
            "<IIdddd",
            self.track_id,
            self.source_id,
            self.play_at,
            self.begin_trim_offset,
            self.end_trim_offset,
            self.src_duration,
        )


@dataclass(slots=True)
class AkClipAutomationPoint:
    from_val: float
    to_val: float
    interp: int


@dataclass(slots=True)
class AkClipAutomation:
    clip_idx: int
    auto_type: int
    points: list[AkClipAutomationPoint] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        c_idx, a_type, num_pts = reader.read_struct("<III")
        points = []
        for _ in range(num_pts):
            fv, tv, interp = reader.read_struct("<ffI")
            points.append(AkClipAutomationPoint(fv, tv, interp))
        return cls(clip_idx=c_idx, auto_type=a_type, points=points)

    def write(self, writer: ByteWriter) -> None:
        writer.write_struct("<III", self.clip_idx, self.auto_type, len(self.points))
        for pt in self.points:
            writer.write_struct("<ffI", pt.from_val, pt.to_val, pt.interp)


@dataclass(slots=True)
class AkTrackSwitchTransParams:
    """Transition parameters for music switch tracks (32 bytes)."""

    src_transition_time: int = 0
    src_fade_curve: int = 0
    src_fade_offset: int = 0
    sync_type: int = 0
    cue_filter_hash: int = 0
    dest_transition_time: int = 0
    dest_fade_curve: int = 0
    dest_fade_offset: int = 0

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        stt, sfc, sfo, st, cfh, dtt, dfc, dfo = reader.read_struct("<iIiIIiIi")
        return cls(
            src_transition_time=stt,
            src_fade_curve=sfc,
            src_fade_offset=sfo,
            sync_type=st,
            cue_filter_hash=cfh,
            dest_transition_time=dtt,
            dest_fade_curve=dfc,
            dest_fade_offset=dfo,
        )

    def write(self, writer: ByteWriter) -> None:
        writer.write_struct(
            "<iIiIIiIi",
            self.src_transition_time,
            self.src_fade_curve,
            self.src_fade_offset,
            self.sync_type,
            self.cue_filter_hash,
            self.dest_transition_time,
            self.dest_fade_curve,
            self.dest_fade_offset,
        )


@dataclass(slots=True)
class AkTrackSwitchInfo:
    """Switch configuration descriptor for Switch Music Tracks."""

    group_type: int = 0
    group_id: int = 0
    default_switch: int = 0
    switch_assocs: list[int] = field(default_factory=list)
    switch_trans_params: AkTrackSwitchTransParams = field(default_factory=AkTrackSwitchTransParams)

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        gt, gid, ds, num_assocs = reader.read_struct("<BIII")
        switch_assocs = list(reader.read_struct(f"<{num_assocs}I")) if num_assocs > 0 else []
        stp = AkTrackSwitchTransParams.read(reader)
        return cls(
            group_type=gt,
            group_id=gid,
            default_switch=ds,
            switch_assocs=switch_assocs,
            switch_trans_params=stp,
        )

    def write(self, writer: ByteWriter) -> None:
        writer.write_struct(
            "<BIII", self.group_type, self.group_id, self.default_switch, len(self.switch_assocs)
        )
        if self.switch_assocs:
            writer.write_struct(f"<{len(self.switch_assocs)}I", *self.switch_assocs)
        self.switch_trans_params.write(writer)


@dataclass(slots=True)
class AkMusicTransitionRule:
    """Transition rule between source and destination music objects."""

    source_ids: list[int] = field(default_factory=list)
    dst_ids: list[int] = field(default_factory=list)
    src_rule: bytes = field(default_factory=lambda: b"\x00" * 21)
    dst_rule: bytes = field(default_factory=lambda: b"\x00" * 24)
    alloc_trans_object_flag: int = 0
    trans_object: bytes = b""

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        src_cnt = reader.read_u32()
        src_ids = list(reader.read_struct(f"<{src_cnt}I")) if src_cnt > 0 else []
        dst_cnt = reader.read_u32()
        dst_ids = list(reader.read_struct(f"<{dst_cnt}I")) if dst_cnt > 0 else []
        src_rule = reader.read_bytes(21)
        dst_rule = reader.read_bytes(24)
        alloc_flag = reader.read_u8()
        trans_obj = reader.read_bytes(30) if alloc_flag == 1 else b""
        return cls(
            source_ids=src_ids,
            dst_ids=dst_ids,
            src_rule=src_rule,
            dst_rule=dst_rule,
            alloc_trans_object_flag=alloc_flag,
            trans_object=trans_obj,
        )

    def write(self, writer: ByteWriter) -> None:
        writer.write_u32(len(self.source_ids))
        if self.source_ids:
            writer.write_struct(f"<{len(self.source_ids)}I", *self.source_ids)
        writer.write_u32(len(self.dst_ids))
        if self.dst_ids:
            writer.write_struct(f"<{len(self.dst_ids)}I", *self.dst_ids)
        writer.write_bytes(self.src_rule)
        writer.write_bytes(self.dst_rule)
        writer.write_u8(self.alloc_trans_object_flag)
        if self.alloc_trans_object_flag == 1:
            writer.write_bytes(self.trans_object)


@dataclass(slots=True)
class AkMusicTransNodeParams:
    """Base parameter block for CAkMusicTransNode derived containers."""

    flags: int = 0
    node_base_params: NodeBaseParams = field(default_factory=NodeBaseParams)
    children: list[int] = field(default_factory=list)
    meter_info: bytes = field(default_factory=lambda: b"\x00" * 23)
    stingers: list[AkMusicStinger] = field(default_factory=list)
    rules: list[AkMusicTransitionRule] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        flags = reader.read_u8()
        nb = NodeBaseParams.read(reader)
        num_children = reader.read_u32()
        children = list(reader.read_struct(f"<{num_children}I")) if num_children > 0 else []
        meter_info = reader.read_bytes(23)
        num_stingers = reader.read_u32()
        stingers = [AkMusicStinger.read(reader) for _ in range(num_stingers)]
        num_rules = reader.read_u32()
        rules = [AkMusicTransitionRule.read(reader) for _ in range(num_rules)]
        return cls(
            flags=flags,
            node_base_params=nb,
            children=children,
            meter_info=meter_info,
            stingers=stingers,
            rules=rules,
        )

    def write(self, writer: ByteWriter) -> None:
        writer.write_u8(self.flags)
        self.node_base_params.write(writer)
        writer.write_u32(len(self.children))
        if self.children:
            writer.write_struct(f"<{len(self.children)}I", *self.children)
        writer.write_bytes(self.meter_info)
        writer.write_u32(len(self.stingers))
        for st in self.stingers:
            st.write(writer)
        writer.write_u32(len(self.rules))
        for r in self.rules:
            r.write(writer)


@dataclass(slots=True)
class AkMusicRanSeqPlaylistItem:
    """A playlist item entry (30 bytes) in a Music Random/Sequence Container."""

    segment_id: int = 0
    playlist_item_id: int = 0
    num_children: int = 0
    rs_type: int = 0
    loop: int = 1
    loop_min: int = 0
    loop_max: int = 0
    weight: int = 50000
    avoid_repeat_count: int = 0
    is_using_weight: int = 0
    is_shuffle: int = 0

    @classmethod
    def read(cls, reader: ByteReader) -> Self:
        sid, pid, nc, rst, loop, lmin, lmax, wt, arc, iuw, is_sh = reader.read_struct(
            "<IIIIhhhIHBB"
        )
        return cls(
            segment_id=sid,
            playlist_item_id=pid,
            num_children=nc,
            rs_type=rst,
            loop=loop,
            loop_min=lmin,
            loop_max=lmax,
            weight=wt,
            avoid_repeat_count=arc,
            is_using_weight=iuw,
            is_shuffle=is_sh,
        )

    def write(self, writer: ByteWriter) -> None:
        writer.write_struct(
            "<IIIIhhhIHBB",
            self.segment_id,
            self.playlist_item_id,
            self.num_children,
            self.rs_type,
            self.loop,
            self.loop_min,
            self.loop_max,
            self.weight,
            self.avoid_repeat_count,
            self.is_using_weight,
            self.is_shuffle,
        )


# ==============================================================================
# HIRC Object Abstract Base & 18 Concrete Types
# ==============================================================================


@dataclass(slots=True)
class HircObject:
    """Abstract base class for all 18 typed Wwise v112 HIRC AST objects."""

    id: int = 0
    obj_type: int = 0

    def write_body(self, writer: ByteWriter) -> None:
        raise NotImplementedError

    def to_bytes(self) -> bytes:
        body_writer = ByteWriter()
        self.write_body(body_writer)
        body = body_writer.get_bytes()

        frame_writer = ByteWriter()
        frame_writer.write_u8(self.obj_type)
        frame_writer.write_u32(4 + len(body))  # section_len = 4 bytes (id) + body
        frame_writer.write_u32(self.id)
        frame_writer.write_bytes(body)
        return frame_writer.get_bytes()


@dataclass(slots=True)
class CAkState(HircObject):
    """CAkState (Type 1) - State properties definition."""

    obj_type: int = 1
    props: dict[int, float] = field(default_factory=dict)

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        num_props = reader.read_u8()
        if num_props > 0:
            pids = reader.read_bytes(num_props)
            pvals = reader.read_struct(f"<{num_props}f")
            props = dict(zip(pids, pvals))
        else:
            props = {}
        return cls(id=obj_id, obj_type=1, props=props)

    def write_body(self, writer: ByteWriter) -> None:
        writer.write_u8(len(self.props))
        if self.props:
            writer.write_bytes(bytes(self.props.keys()))
            writer.write_struct(f"<{len(self.props)}f", *self.props.values())


@dataclass(slots=True)
class CAkSound(HircObject):
    """CAkSound (Type 2) - Streamed or embedded playable audio source."""

    obj_type: int = 2
    plugin_id: int = 0x40001
    stream_type: int = 2
    source_id: int = 0
    file_id: int = 0
    file_offset: int = 0
    in_memory_media_size: int = 0
    source_bits: int = 0
    plugin_params: bytes = b""
    node_base_params: NodeBaseParams = field(default_factory=NodeBaseParams)

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        plugin_id, stream_type, source_id, file_id = reader.read_struct("<IBII")
        file_offset = 0
        if stream_type != 2:
            file_offset = reader.read_u32()
        in_memory_media_size, source_bits = reader.read_struct("<IB")
        plugin_params = b""
        if (plugin_id & 0x0F) in (2, 5):
            param_size = reader.read_u32()
            plugin_params = reader.read_bytes(param_size) if param_size > 0 else b""
        nb = NodeBaseParams.read(reader)
        return cls(
            id=obj_id,
            obj_type=2,
            plugin_id=plugin_id,
            stream_type=stream_type,
            source_id=source_id,
            file_id=file_id,
            file_offset=file_offset,
            in_memory_media_size=in_memory_media_size,
            source_bits=source_bits,
            plugin_params=plugin_params,
            node_base_params=nb,
        )

    def write_body(self, writer: ByteWriter) -> None:
        writer.write_struct("<IBII", self.plugin_id, self.stream_type, self.source_id, self.file_id)
        if self.stream_type != 2:
            writer.write_u32(self.file_offset)
        writer.write_struct("<IB", self.in_memory_media_size, self.source_bits)
        if (self.plugin_id & 0x0F) in (2, 5):
            writer.write_u32(len(self.plugin_params))
            if self.plugin_params:
                writer.write_bytes(self.plugin_params)
        self.node_base_params.write(writer)


@dataclass(slots=True)
class CAkAction(HircObject):
    """CAkAction (Type 3) - Event action trigger."""

    obj_type: int = 3
    action_type: int = 0x0403
    id_ext: int = 0
    id_ext_4: int = 0
    params: ActionParams = field(default_factory=ActionParams)

    @property
    def target_id(self) -> int:
        """Target HIRC object ID referenced by this action."""
        return self.id_ext

    @target_id.setter
    def target_id(self, val: int) -> None:
        self.id_ext = val

    @classmethod
    def create_play(
        cls, id: int, target_id: int, bank_id: int = 0, fade_curve: int = 4
    ) -> "CAkAction":
        return cls(
            id=id,
            obj_type=3,
            action_type=0x0403,
            id_ext=target_id,
            id_ext_4=0,
            params=ActionParams(fade_curve=fade_curve, bank_id=bank_id),
        )

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        action_type, id_ext, id_ext_4 = reader.read_struct("<HIB")
        tail = reader.read_remaining()
        params = ActionParams.from_bytes(tail, action_type)
        return cls(
            id=obj_id,
            obj_type=3,
            action_type=action_type,
            id_ext=id_ext,
            id_ext_4=id_ext_4,
            params=params,
        )

    def write_body(self, writer: ByteWriter) -> None:
        writer.write_struct("<HIB", self.action_type, self.id_ext, self.id_ext_4)
        writer.write_bytes(self.params.to_bytes(self.action_type))


@dataclass(slots=True)
class CAkEvent(HircObject):
    """CAkEvent (Type 4) - Trigger event grouping CAkAction targets."""

    obj_type: int = 4
    actions: list[int] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        count = reader.read_u32()
        actions = list(reader.read_struct(f"<{count}I")) if count > 0 else []
        return cls(id=obj_id, obj_type=4, actions=actions)

    def write_body(self, writer: ByteWriter) -> None:
        writer.write_u32(len(self.actions))
        if self.actions:
            writer.write_struct(f"<{len(self.actions)}I", *self.actions)


@dataclass(slots=True)
class CAkRanSeqCntr(HircObject):
    """CAkRanSeqCntr (Type 5) - Random/Sequence container."""

    obj_type: int = 5
    node_base_params: NodeBaseParams = field(default_factory=NodeBaseParams)
    loop_count: int = 1
    loop_mod_min: int = 0
    loop_mod_max: int = 0
    transition_time: float = 1000.0
    transition_time_mod_min: float = 0.0
    transition_time_mod_max: float = 0.0
    avoid_repeat_count: int = 1
    transition_mode: int = 0
    random_mode: int = 0
    mode: int = 0
    bit_vector: int = 0
    children: list[int] = field(default_factory=list)
    playlist: list[AkPlaylistItem] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        nb = NodeBaseParams.read(reader)
        lc, lmin, lmax, tt, ttmin, ttmax, arc, tm, rm, m, bv = reader.read_struct("<HHHfffHBBBB")
        num_children = reader.read_u32()
        children = list(reader.read_struct(f"<{num_children}I")) if num_children > 0 else []
        num_playlist = reader.read_u16()
        playlist = []
        for _ in range(num_playlist):
            pid, w = reader.read_struct("<Ii")
            playlist.append(AkPlaylistItem(play_id=pid, weight=w))
        return cls(
            id=obj_id,
            obj_type=5,
            node_base_params=nb,
            loop_count=lc,
            loop_mod_min=lmin,
            loop_mod_max=lmax,
            transition_time=tt,
            transition_time_mod_min=ttmin,
            transition_time_mod_max=ttmax,
            avoid_repeat_count=arc,
            transition_mode=tm,
            random_mode=rm,
            mode=m,
            bit_vector=bv,
            children=children,
            playlist=playlist,
        )

    def write_body(self, writer: ByteWriter) -> None:
        self.node_base_params.write(writer)
        writer.write_struct(
            "<HHHfffHBBBB",
            self.loop_count,
            self.loop_mod_min,
            self.loop_mod_max,
            self.transition_time,
            self.transition_time_mod_min,
            self.transition_time_mod_max,
            self.avoid_repeat_count,
            self.transition_mode,
            self.random_mode,
            self.mode,
            self.bit_vector,
        )
        writer.write_u32(len(self.children))
        if self.children:
            writer.write_struct(f"<{len(self.children)}I", *self.children)
        writer.write_u16(len(self.playlist))
        for item in self.playlist:
            writer.write_struct("<Ii", item.play_id, item.weight)


@dataclass(slots=True)
class CAkSwitchCntr(HircObject):
    """CAkSwitchCntr (Type 6) - Switch container routing children based on game syncs."""

    obj_type: int = 6
    node_base_params: NodeBaseParams = field(default_factory=NodeBaseParams)
    group_type: int = 0
    group_id: int = 0
    default_switch: int = 0
    is_continuous_validation: int = 0
    children: list[int] = field(default_factory=list)
    switch_map: dict[int, list[int]] = field(default_factory=dict)
    parameters: list[AkSwitchParam] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        nb = NodeBaseParams.read(reader)
        gt, gid, ds, cv = reader.read_struct("<BIIB")
        num_children = reader.read_u32()
        children = list(reader.read_struct(f"<{num_children}I")) if num_children > 0 else []
        num_switches = reader.read_u32()
        switch_map: dict[int, list[int]] = {}
        for _ in range(num_switches):
            sid, cnt = reader.read_struct("<II")
            nids = list(reader.read_struct(f"<{cnt}I")) if cnt > 0 else []
            switch_map[sid] = nids
        num_params = reader.read_u32()
        parameters = [AkSwitchParam.read(reader) for _ in range(num_params)]
        return cls(
            id=obj_id,
            obj_type=6,
            node_base_params=nb,
            group_type=gt,
            group_id=gid,
            default_switch=ds,
            is_continuous_validation=cv,
            children=children,
            switch_map=switch_map,
            parameters=parameters,
        )

    def write_body(self, writer: ByteWriter) -> None:
        self.node_base_params.write(writer)
        writer.write_struct(
            "<BIIB",
            self.group_type,
            self.group_id,
            self.default_switch,
            self.is_continuous_validation,
        )
        writer.write_u32(len(self.children))
        if self.children:
            writer.write_struct(f"<{len(self.children)}I", *self.children)
        writer.write_u32(len(self.switch_map))
        for sid, nids in self.switch_map.items():
            writer.write_struct("<II", sid, len(nids))
            if nids:
                writer.write_struct(f"<{len(nids)}I", *nids)
        writer.write_u32(len(self.parameters))
        for param in self.parameters:
            param.write(writer)


@dataclass(slots=True)
class CAkActorMixer(HircObject):
    """CAkActorMixer (Type 7) - Hierarchical grouping container."""

    obj_type: int = 7
    node_base_params: NodeBaseParams = field(default_factory=NodeBaseParams)
    children: list[int] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        nb = NodeBaseParams.read(reader)
        num_children = reader.read_u32()
        children = list(reader.read_struct(f"<{num_children}I")) if num_children > 0 else []
        return cls(id=obj_id, obj_type=7, node_base_params=nb, children=children)

    def write_body(self, writer: ByteWriter) -> None:
        self.node_base_params.write(writer)
        writer.write_u32(len(self.children))
        if self.children:
            writer.write_struct(f"<{len(self.children)}I", *self.children)


@dataclass(slots=True)
class _CAkBusBase(HircObject):
    """Shared base representation for CAkBus and CAkAuxBus."""

    override_bus_id: int = 0
    props: dict[int, float] = field(default_factory=dict)
    positioning: AkPositioningParams = field(default_factory=AkPositioningParams)
    adv_flags: int = 0
    max_num_instance: int = 0
    channel_config: int = 0
    hdr_flags: int = 0
    recovery_time: int = 0
    max_duck_volume: float = -96.0
    ducks: list[AkDuckInfo] = field(default_factory=list)
    bits_fx: int = 0
    fx_chunks: list[tuple[int, int, int, int]] = field(default_factory=list)
    override_attachment_params: int = 0
    fx0_id: int = 0
    is_shareset0: int = 0
    rtpcs: list[AkRtpcEntry] = field(default_factory=list)
    state_groups: list[AkStateGroupChunk] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        override_bus_id = reader.read_u32()
        props: dict[int, float] = {}
        positioning = AkPositioningParams()
        adv_flags = 0
        max_num_instance = 0
        channel_config = 0
        hdr_flags = 0
        recovery_time = 0
        max_duck_volume = -96.0
        ducks: list[AkDuckInfo] = []
        bits_fx = 0
        fx_chunks: list[tuple[int, int, int, int]] = []
        override_attachment_params = 0
        fx0_id = 0
        is_shareset0 = 0
        rtpcs: list[AkRtpcEntry] = []
        state_groups: list[AkStateGroupChunk] = []

        if reader.remaining > 0:
            num_props = reader.read_u8()
            if num_props > 0:
                pids = reader.read_bytes(num_props)
                pvals = reader.read_struct(f"<{num_props}f")
                props = dict(zip(pids, pvals))

            positioning = AkPositioningParams.read(reader)
            adv_flags, max_num_instance, channel_config, hdr_flags = reader.read_struct("<BHIB")
            recovery_time, max_duck_volume, num_ducks = reader.read_struct("<ifI")
            ducks = [AkDuckInfo.read(reader) for _ in range(num_ducks)]

            num_fx = reader.read_u8()
            if num_fx > 0:
                bits_fx = reader.read_u8()
                for _ in range(num_fx):
                    fx_chunks.append(reader.read_struct("<BIBB"))
            override_attachment_params, fx0_id, is_shareset0 = reader.read_struct("<BIB")

            rtpcs = AkRtpcEntry.read_list(reader)
            state_groups = AkStateGroupChunk.read_list(reader)

        return cls(
            id=obj_id,
            override_bus_id=override_bus_id,
            props=props,
            positioning=positioning,
            adv_flags=adv_flags,
            max_num_instance=max_num_instance,
            channel_config=channel_config,
            hdr_flags=hdr_flags,
            recovery_time=recovery_time,
            max_duck_volume=max_duck_volume,
            ducks=ducks,
            bits_fx=bits_fx,
            fx_chunks=fx_chunks,
            override_attachment_params=override_attachment_params,
            fx0_id=fx0_id,
            is_shareset0=is_shareset0,
            rtpcs=rtpcs,
            state_groups=state_groups,
        )

    def write_body(self, writer: ByteWriter) -> None:
        writer.write_u32(self.override_bus_id)
        writer.write_u8(len(self.props))
        if self.props:
            writer.write_bytes(bytes(self.props.keys()))
            writer.write_struct(f"<{len(self.props)}f", *self.props.values())
        self.positioning.write(writer)
        writer.write_struct(
            "<BHIB", self.adv_flags, self.max_num_instance, self.channel_config, self.hdr_flags
        )
        writer.write_struct("<ifI", self.recovery_time, self.max_duck_volume, len(self.ducks))
        for duck in self.ducks:
            duck.write(writer)
        writer.write_u8(len(self.fx_chunks))
        if self.fx_chunks:
            writer.write_u8(self.bits_fx)
            for chunk in self.fx_chunks:
                writer.write_struct("<BIBB", chunk[0], chunk[1], chunk[2], chunk[3])
        writer.write_struct("<BIB", self.override_attachment_params, self.fx0_id, self.is_shareset0)
        AkRtpcEntry.write_list(writer, self.rtpcs)
        AkStateGroupChunk.write_list(writer, self.state_groups)


@dataclass(slots=True)
class CAkBus(_CAkBusBase):
    """CAkBus (Type 8) - Audio mixing and output bus."""

    obj_type: int = 8


@dataclass(slots=True)
class CAkAuxBus(_CAkBusBase):
    """CAkAuxBus (Type 20) - Auxiliary send/reverb bus."""

    obj_type: int = 20


@dataclass(slots=True)
class CAkLayerCntr(HircObject):
    """CAkLayerCntr (Type 9) - Layer container blending multiple sounds with curves."""

    obj_type: int = 9
    node_base_params: NodeBaseParams = field(default_factory=NodeBaseParams)
    children: list[int] = field(default_factory=list)
    layers: list[CAkLayer] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        nb = NodeBaseParams.read(reader)
        num_children = reader.read_u32()
        children = list(reader.read_struct(f"<{num_children}I")) if num_children > 0 else []
        num_layers = reader.read_u32()
        layers = [CAkLayer.read(reader) for _ in range(num_layers)]
        return cls(id=obj_id, obj_type=9, node_base_params=nb, children=children, layers=layers)

    def write_body(self, writer: ByteWriter) -> None:
        self.node_base_params.write(writer)
        writer.write_u32(len(self.children))
        if self.children:
            writer.write_struct(f"<{len(self.children)}I", *self.children)
        writer.write_u32(len(self.layers))
        for layer in self.layers:
            layer.write(writer)


@dataclass(slots=True)
class CAkMusicSegment(HircObject):
    """CAkMusicSegment (Type 10) - Interactive music segment."""

    obj_type: int = 10
    flags: int = 0
    node_base_params: NodeBaseParams = field(default_factory=NodeBaseParams)
    child_ids: list[int] = field(default_factory=list)
    grid_period: float = 0.0
    grid_offset: float = 0.0
    tempo: float = 120.0
    time_sig_num_beats_bar: int = 4
    time_sig_beat_val: int = 4
    meter_info_flag: int = 0
    stingers: list[AkMusicStinger] = field(default_factory=list)
    duration: float = 0.0
    markers: list[AkMusicMarker] = field(default_factory=list)

    @property
    def num_stingers(self) -> int:
        return len(self.stingers)

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        flags = reader.read_u8()
        nb = NodeBaseParams.read(reader)
        num_children = reader.read_u32()
        child_ids = list(reader.read_struct(f"<{num_children}I")) if num_children > 0 else []
        grid_period, grid_offset, tempo, beats_bar, beat_val, meter_info_flag, num_stingers = (
            reader.read_struct("<ddfBBBI")
        )
        stingers = [AkMusicStinger.read(reader) for _ in range(num_stingers)]
        duration, num_markers = reader.read_struct("<dI")
        markers = [AkMusicMarker.read(reader) for _ in range(num_markers)]
        return cls(
            id=obj_id,
            obj_type=10,
            flags=flags,
            node_base_params=nb,
            child_ids=child_ids,
            grid_period=grid_period,
            grid_offset=grid_offset,
            tempo=tempo,
            time_sig_num_beats_bar=beats_bar,
            time_sig_beat_val=beat_val,
            meter_info_flag=meter_info_flag,
            stingers=stingers,
            duration=duration,
            markers=markers,
        )

    def write_body(self, writer: ByteWriter) -> None:
        writer.write_u8(self.flags)
        self.node_base_params.write(writer)
        writer.write_u32(len(self.child_ids))
        if self.child_ids:
            writer.write_struct(f"<{len(self.child_ids)}I", *self.child_ids)
        writer.write_struct(
            "<ddfBBB",
            self.grid_period,
            self.grid_offset,
            self.tempo,
            self.time_sig_num_beats_bar,
            self.time_sig_beat_val,
            self.meter_info_flag,
        )
        writer.write_u32(len(self.stingers))
        for st in self.stingers:
            st.write(writer)
        writer.write_struct("<dI", self.duration, len(self.markers))
        for m in self.markers:
            m.write(writer)


@dataclass(slots=True)
class CAkMusicTrack(HircObject):
    """CAkMusicTrack (Type 11) - Music track containing audio sources and timing."""

    obj_type: int = 11
    flags: int = 0
    sources: list[AkMusicTrackSource] = field(default_factory=list)
    playlist: list[AkTrackSrcInfo] = field(default_factory=list)
    num_sub_track: int | None = None
    clip_automations: list[AkClipAutomation] = field(default_factory=list)
    node_base_params: NodeBaseParams = field(default_factory=NodeBaseParams)
    track_type: int = 0
    look_ahead_time: int = 0
    switch_info: AkTrackSwitchInfo | None = None

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        flags = reader.read_u8()
        num_sources = reader.read_u32()
        sources = [AkMusicTrackSource.read(reader) for _ in range(num_sources)]
        num_playlist = reader.read_u32()
        playlist = [AkTrackSrcInfo.read(reader) for _ in range(num_playlist)]
        num_sub_track = None
        if num_playlist > 0:
            num_sub_track = reader.read_u32()
        num_clip_auto = reader.read_u32()
        if num_clip_auto * 12 > reader.remaining:
            if (num_clip_auto & 0xFF) == 0 and 0 < (num_clip_auto >> 8) * 12 <= reader.remaining:
                num_clip_auto = num_clip_auto >> 8
            elif (
                0
                < ((num_clip_auto >> 16) | ((num_clip_auto & 0xFFFF) << 16)) * 12
                <= reader.remaining
            ):
                num_clip_auto = (num_clip_auto >> 16) | ((num_clip_auto & 0xFFFF) << 16)
        clip_automations = [AkClipAutomation.read(reader) for _ in range(num_clip_auto)]
        nb = NodeBaseParams.read(reader)
        track_type = reader.read_u8()
        switch_info = None
        if track_type == 3 and reader.remaining >= 46:
            switch_info = AkTrackSwitchInfo.read(reader)
        look_ahead_time = reader.read_i32()
        return cls(
            id=obj_id,
            obj_type=11,
            flags=flags,
            sources=sources,
            playlist=playlist,
            num_sub_track=num_sub_track,
            clip_automations=clip_automations,
            node_base_params=nb,
            track_type=track_type,
            look_ahead_time=look_ahead_time,
            switch_info=switch_info,
        )

    def write_body(self, writer: ByteWriter) -> None:
        writer.write_u8(self.flags)
        writer.write_u32(len(self.sources))
        for src in self.sources:
            src.write(writer)
        writer.write_u32(len(self.playlist))
        for item in self.playlist:
            item.write(writer)
        if len(self.playlist) > 0:
            writer.write_u32(self.num_sub_track if self.num_sub_track is not None else 1)
        writer.write_u32(len(self.clip_automations))
        for ca in self.clip_automations:
            ca.write(writer)
        self.node_base_params.write(writer)
        writer.write_u8(self.track_type)
        if self.track_type == 3 and self.switch_info is not None:
            self.switch_info.write(writer)
        writer.write_i32(self.look_ahead_time)


@dataclass(slots=True)
class CAkMusicSwitchCntr(HircObject):
    """CAkMusicSwitchCntr (Type 12) - Music switch container."""

    obj_type: int = 12
    trans_params: AkMusicTransNodeParams = field(default_factory=AkMusicTransNodeParams)
    continue_playback: int = 0
    tree_depth: int = 0
    arguments: list[tuple[int, int]] = field(default_factory=list)
    mode: int = 0
    tree: AkDecisionTree = field(default_factory=AkDecisionTree)

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        tp = AkMusicTransNodeParams.read(reader)
        continue_playback, tree_depth = reader.read_struct("<BI")
        group_ids = [reader.read_u32() for _ in range(tree_depth)]
        group_types = [reader.read_u8() for _ in range(tree_depth)]
        arguments = list(zip(group_ids, group_types))
        tree_data_size, mode = reader.read_struct("<IB")
        tree = AkDecisionTree.read(reader, tree_data_size=tree_data_size, max_depth=tree_depth)
        return cls(
            id=obj_id,
            obj_type=12,
            trans_params=tp,
            continue_playback=continue_playback,
            tree_depth=tree_depth,
            arguments=arguments,
            mode=mode,
            tree=tree,
        )

    def write_body(self, writer: ByteWriter) -> None:
        self.trans_params.write(writer)
        writer.write_struct("<BI", self.continue_playback, len(self.arguments))
        for gid, _ in self.arguments:
            writer.write_u32(gid)
        for _, gtype in self.arguments:
            writer.write_u8(gtype)
        tree_bytes = self.tree.to_bytes()
        writer.write_struct("<IB", len(tree_bytes), self.mode)
        writer.write_bytes(tree_bytes)


@dataclass(slots=True)
class CAkMusicRanSeqCntr(HircObject):
    """CAkMusicRanSeqCntr (Type 13) - Music random/sequence container."""

    obj_type: int = 13
    trans_params: AkMusicTransNodeParams = field(default_factory=AkMusicTransNodeParams)
    playlist: list[AkMusicRanSeqPlaylistItem] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        tp = AkMusicTransNodeParams.read(reader)
        num_items = reader.read_u32()
        playlist = [AkMusicRanSeqPlaylistItem.read(reader) for _ in range(num_items)]
        return cls(id=obj_id, obj_type=13, trans_params=tp, playlist=playlist)

    def write_body(self, writer: ByteWriter) -> None:
        self.trans_params.write(writer)
        writer.write_u32(len(self.playlist))
        for item in self.playlist:
            item.write(writer)


@dataclass(slots=True)
class CAkAttenuation(HircObject):
    """CAkAttenuation (Type 14) - 3D distance roll-off and cone curves."""

    obj_type: int = 14
    cone_enabled: int = 0
    cone_params: tuple[float, float, float, float, float] | None = None
    curve_to_use: list[int] = field(default_factory=lambda: [0] * 7)
    curves: list[AkAttenuationCurve] = field(default_factory=list)
    rtpcs: list[AkRtpcEntry] = field(default_factory=list)

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        cone_enabled = reader.read_u8()
        cone_params = None
        if cone_enabled != 0:
            cone_params = reader.read_struct("<fffff")
        curve_to_use = list(reader.read_bytes(7))
        num_curves = reader.read_u8()
        curves = [AkAttenuationCurve.read(reader) for _ in range(num_curves)]
        rtpcs = []
        if reader.remaining > 0:
            rtpcs = AkRtpcEntry.read_list(reader)
        return cls(
            id=obj_id,
            obj_type=14,
            cone_enabled=cone_enabled,
            cone_params=cone_params,
            curve_to_use=curve_to_use,
            curves=curves,
            rtpcs=rtpcs,
        )

    def write_body(self, writer: ByteWriter) -> None:
        writer.write_u8(self.cone_enabled)
        if self.cone_enabled != 0:
            if self.cone_params:
                writer.write_struct("<fffff", *self.cone_params)
            else:
                writer.write_struct("<fffff", 0.0, 0.0, 0.0, 0.0, 0.0)
        for c in self.curve_to_use[:7]:
            writer.write_u8(c)
        for _ in range(7 - len(self.curve_to_use)):
            writer.write_u8(0)
        writer.write_u8(len(self.curves))
        for curve in self.curves:
            curve.write(writer)
        AkRtpcEntry.write_list(writer, self.rtpcs)


@dataclass(slots=True)
class CAkDialogueEvent(HircObject):
    """CAkDialogueEvent (Type 15) - Dynamic dialogue event decision tree router."""

    obj_type: int = 15
    probability: int = 100
    tree_depth: int = 0
    arguments: list[tuple[int, int]] = field(default_factory=list)
    mode: int = 1
    tree: AkDecisionTree = field(default_factory=AkDecisionTree)

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        prob, tree_depth = reader.read_struct("<BI")
        group_ids = [reader.read_u32() for _ in range(tree_depth)]
        group_types = [reader.read_u8() for _ in range(tree_depth)]
        arguments = list(zip(group_ids, group_types))
        tree_data_size, mode = reader.read_struct("<IB")
        tree = AkDecisionTree.read(reader, tree_data_size=tree_data_size, max_depth=tree_depth)
        return cls(
            id=obj_id,
            obj_type=15,
            probability=prob,
            tree_depth=tree_depth,
            arguments=arguments,
            mode=mode,
            tree=tree,
        )

    def write_body(self, writer: ByteWriter) -> None:
        writer.write_struct("<BI", self.probability, len(self.arguments))
        for gid, _ in self.arguments:
            writer.write_u32(gid)
        for _, gtype in self.arguments:
            writer.write_u8(gtype)
        tree_bytes = self.tree.to_bytes()
        writer.write_struct("<IB", len(tree_bytes), self.mode)
        writer.write_bytes(tree_bytes)


@dataclass(slots=True)
class _CAkFxBase(HircObject):
    """Base class for effect plugin structures (CAkFxShareSet and CAkFxCustom)."""

    fx_id: int = 0
    plugin_params: bytes = b""
    media_refs: list[tuple[int, int]] = field(default_factory=list)
    rtpcs: list[AkRtpcEntry] = field(default_factory=list)
    rtpc_init_flags: int = 0

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        fx_id, param_size = reader.read_struct("<II")
        plugin_params = reader.read_bytes(param_size)
        num_media = reader.read_u8()
        media_refs = []
        for _ in range(num_media):
            media_refs.append(reader.read_struct("<BI"))
        rtpcs: list[AkRtpcEntry] = []
        rtpc_init_flags = 0
        if reader.remaining > 0:
            rtpcs = AkRtpcEntry.read_list(reader)
            if reader.remaining >= 2:
                rtpc_init_flags = reader.read_u16()
        return cls(
            id=obj_id,
            fx_id=fx_id,
            plugin_params=plugin_params,
            media_refs=media_refs,
            rtpcs=rtpcs,
            rtpc_init_flags=rtpc_init_flags,
        )

    def write_body(self, writer: ByteWriter) -> None:
        writer.write_struct("<II", self.fx_id, len(self.plugin_params))
        if self.plugin_params:
            writer.write_bytes(self.plugin_params)
        writer.write_u8(len(self.media_refs))
        for idx, src_id in self.media_refs:
            writer.write_struct("<BI", idx, src_id)
        AkRtpcEntry.write_list(writer, self.rtpcs)
        writer.write_u16(self.rtpc_init_flags)


@dataclass(slots=True)
class CAkFxShareSet(_CAkFxBase):
    """CAkFxShareSet (Type 18) - Shared audio effect parameters."""

    obj_type: int = 18


@dataclass(slots=True)
class CAkFxCustom(_CAkFxBase):
    """CAkFxCustom (Type 19) - Custom object-specific audio effect parameters."""

    obj_type: int = 19


@dataclass(slots=True)
class CAkFeedbackBus(HircObject):
    """CAkFeedbackBus (Type 16) - Minimal stub for tactile feedback bus."""

    obj_type: int = 16
    raw_data: bytes = b""

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        return cls(id=obj_id, obj_type=16, raw_data=reader.read_remaining())

    def write_body(self, writer: ByteWriter) -> None:
        writer.write_bytes(self.raw_data)


@dataclass(slots=True)
class CAkFeedbackNode(HircObject):
    """CAkFeedbackNode (Type 17) - Minimal stub for tactile feedback node."""

    obj_type: int = 17
    raw_data: bytes = b""

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int) -> Self:
        return cls(id=obj_id, obj_type=17, raw_data=reader.read_remaining())

    def write_body(self, writer: ByteWriter) -> None:
        writer.write_bytes(self.raw_data)


@dataclass(slots=True)
class CAkGenericHirc(HircObject):
    """Generic bit-exact preserved HIRC record for legacy or unmodeled soundbank objects."""

    obj_type: int = 0
    raw_body: bytes = b""

    @classmethod
    def read(cls, reader: ByteReader, obj_id: int, obj_type: int = 0) -> Self:
        return cls(id=obj_id, obj_type=obj_type, raw_body=reader.read_remaining())

    def write_body(self, writer: ByteWriter) -> None:
        writer.write_bytes(self.raw_body)


# ==============================================================================
# HIRC Type Dispatcher
# ==============================================================================

HIRC_TYPE_MAP = {
    1: CAkState,
    2: CAkSound,
    3: CAkAction,
    4: CAkEvent,
    5: CAkRanSeqCntr,
    6: CAkSwitchCntr,
    7: CAkActorMixer,
    8: CAkBus,
    9: CAkLayerCntr,
    10: CAkMusicSegment,
    11: CAkMusicTrack,
    12: CAkMusicSwitchCntr,
    13: CAkMusicRanSeqCntr,
    14: CAkAttenuation,
    15: CAkDialogueEvent,
    16: CAkFeedbackBus,
    17: CAkFeedbackNode,
    18: CAkFxShareSet,
    19: CAkFxCustom,
    20: CAkAuxBus,
}


def parse_hirc_object(reader: ByteReader) -> HircObject:
    """Parses a single HIRC object within a strictly bounded slice."""
    obj_type = reader.read_u8()
    section_len = reader.read_u32()
    sub_reader = reader.read_slice(section_len)
    obj_id = sub_reader.read_u32()

    cls = HIRC_TYPE_MAP.get(obj_type)
    if cls is None:
        raise ValueError(f"Unknown HIRC object type {obj_type} (id {obj_id})")

    return cls.read(sub_reader, obj_id)
