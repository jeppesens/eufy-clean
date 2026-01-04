from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant

from custom_components.robovac_mqtt.const import ACCESSORY_MAX_LIFE, DOMAIN
from custom_components.robovac_mqtt.models import AccessoryState, VacuumState
from custom_components.robovac_mqtt.sensor import async_setup_entry


async def test_accessory_sensors_setup(hass: HomeAssistant):
    """Test that accessory sensors are set up correctly."""
    entry = MagicMock()
    entry.entry_id = "test_entry"

    coordinator = MagicMock()
    coordinator.device_name = "RoboVac"
    coordinator.device_id = "test_device"
    coordinator.device_info = {}

    # Mock state with some usage
    acc_state = AccessoryState(
        main_brush_usage=100,  # Max 360
        side_brush_usage=50,  # Max 200
        filter_usage=0,  # Max 150
    )
    coordinator.data = VacuumState(accessories=acc_state)

    hass.data[DOMAIN] = {"test_entry": {"coordinators": [coordinator]}}

    added_entities = []

    def async_add_entities(entities):
        added_entities.extend(entities)

    await async_setup_entry(hass, entry, async_add_entities)

    # Find rolling brush sensor
    rb_sensor = next(
        e for e in added_entities if e._attr_name == "Rolling Brush Remaining"
    )
    max_main = ACCESSORY_MAX_LIFE["main_brush_usage"]
    assert rb_sensor.native_value == max_main - 100
    assert rb_sensor.extra_state_attributes["usage_hours"] == 100
    assert rb_sensor.extra_state_attributes["total_life_hours"] == max_main

    # Find side brush sensor
    sb_sensor = next(
        e for e in added_entities if e._attr_name == "Side Brush Remaining"
    )
    max_side = ACCESSORY_MAX_LIFE["side_brush_usage"]
    assert sb_sensor.native_value == max_side - 50

    # Verify negative handling (over usage)
    coordinator.data.accessories.main_brush_usage = 400
    assert rb_sensor.native_value == 0  # Should be 0, not -40 (max(0, ...))
