from custom_components.robovac_mqtt.api.parser import update_state
from custom_components.robovac_mqtt.const import DPS_MAP
from custom_components.robovac_mqtt.models import AccessoryState, VacuumState
from custom_components.robovac_mqtt.proto.cloud.consumable_pb2 import (
    ConsumableResponse,
    ConsumableRuntime,
)
from custom_components.robovac_mqtt.utils import encode_message


def test_parse_accessories_status():
    """Test parsing of ACCESSORIES_STATUS (DPS 168)."""
    # Create sample ConsumableResponse with usage data
    response = ConsumableResponse(
        runtime=ConsumableRuntime(
            filter_mesh=ConsumableRuntime.Duration(duration=10),
            rolling_brush=ConsumableRuntime.Duration(duration=20),
            side_brush=ConsumableRuntime.Duration(duration=30),
            sensor=ConsumableRuntime.Duration(duration=40),
            scrape=ConsumableRuntime.Duration(duration=50),
            mop=ConsumableRuntime.Duration(duration=60),
            dustbag=ConsumableRuntime.Duration(duration=70),
            dirty_watertank=ConsumableRuntime.Duration(duration=80),
            dirty_waterfilter=ConsumableRuntime.Duration(duration=90),
        )
    )

    encoded_value = encode_message(response)
    dps = {DPS_MAP["ACCESSORIES_STATUS"]: encoded_value}

    state = VacuumState()
    new_state, _ = update_state(state, dps)

    acc = new_state.accessories
    assert acc.filter_usage == 10
    assert acc.main_brush_usage == 20
    assert acc.side_brush_usage == 30
    assert acc.sensor_usage == 40
    assert acc.scrape_usage == 50
    assert acc.mop_usage == 60
    assert acc.dustbag_usage == 70
    assert acc.dirty_watertank_usage == 80
    assert acc.dirty_waterfilter_usage == 90


def test_parse_accessories_partial():
    """Test parsing of partial accessories data."""
    response = ConsumableResponse(
        runtime=ConsumableRuntime(
            side_brush=ConsumableRuntime.Duration(duration=100),
        )
    )

    encoded_value = encode_message(response)
    dps = {DPS_MAP["ACCESSORIES_STATUS"]: encoded_value}

    # Start with existing values
    initial_acc = AccessoryState(main_brush_usage=55)
    state = VacuumState(accessories=initial_acc)

    new_state, _ = update_state(state, dps)

    acc = new_state.accessories
    assert acc.side_brush_usage == 100
    assert acc.main_brush_usage == 55  # Should be preserved
    assert acc.filter_usage == 0  # Default
