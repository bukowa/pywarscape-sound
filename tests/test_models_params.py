from src.bnk.models import (
    AkAdvSettingsParams,
    AkPositioningParams,
    AkRtpcEntry,
    AkRtpcGraphPoint,
    AkStateGroupChunk,
    NodeBaseParams,
)
from src.bnk.stream import ByteReader, ByteWriter


def test_node_base_params_roundtrip():
    params = NodeBaseParams(
        override_bus_id=1234,
        direct_parent_id=5678,
        props={0: -4.5, 2: 100.0},
        ranged_props={1: (-2.0, 2.0)},
        adv_settings=AkAdvSettingsParams(max_num_instance=5),
        positioning=AkPositioningParams(bits_positioning=1),
    )
    writer = ByteWriter()
    params.write(writer)
    encoded = writer.get_bytes()

    decoded = NodeBaseParams.read(ByteReader(encoded))
    assert decoded.override_bus_id == 1234
    assert decoded.direct_parent_id == 5678
    assert abs(decoded.props[0] - (-4.5)) < 1e-5
    assert abs(decoded.props[2] - 100.0) < 1e-5
    assert decoded.ranged_props[1] == (-2.0, 2.0)
    assert decoded.adv_settings.max_num_instance == 5

    writer2 = ByteWriter()
    decoded.write(writer2)
    assert writer2.get_bytes() == encoded


def test_node_base_params_rtpc_and_states():
    points = [AkRtpcGraphPoint(0.0, 1.0, 4), AkRtpcGraphPoint(100.0, 0.0, 4)]
    rtpc = AkRtpcEntry(
        rtpc_id=501,
        rtpc_type=1,
        rtpc_accum=0,
        param_id=2,
        rtpc_curve_id=1,
        scaling=0,
        points=points,
    )
    sg = AkStateGroupChunk(state_group_id=900, sync_type=1, states=[(10, 101), (20, 102)])
    params = NodeBaseParams(
        override_bus_id=777,
        rtpcs=[rtpc],
        state_groups=[sg],
    )
    raw = params.to_bytes()
    decoded = NodeBaseParams.read(ByteReader(raw))
    assert len(decoded.rtpcs) == 1
    assert decoded.rtpcs[0].rtpc_id == 501
    assert len(decoded.rtpcs[0].points) == 2
    assert decoded.rtpcs[0].points[0].from_val == 0.0
    assert len(decoded.state_groups) == 1
    assert decoded.state_groups[0].states == [(10, 101), (20, 102)]
    assert decoded.to_bytes() == raw


def test_node_base_params_attenuation_id_sync():
    pos = AkPositioningParams(bits_positioning=9, bits_3d=1, attenuation_id=8888)
    params = NodeBaseParams(positioning=pos)
    assert params.attenuation_id == 8888

    # Mutating via property
    params.attenuation_id = 9999
    assert params.positioning.attenuation_id == 9999

    raw = params.to_bytes()
    decoded = NodeBaseParams.read(ByteReader(raw))
    assert decoded.attenuation_id == 9999
    assert decoded.positioning.attenuation_id == 9999
