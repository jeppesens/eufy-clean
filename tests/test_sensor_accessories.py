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


async def test_accessory_sensors_model_override(hass: HomeAssistant):
    """A model with its own lifespan table gets exactly those accessories."""
    entry = MagicMock()
    entry.entry_id = "test_entry"

    coordinator = MagicMock()
    coordinator.device_name = "RoboVac"
    coordinator.device_id = "test_device"
    coordinator.device_info = {}
    coordinator.device_model = "T2277"
    coordinator.api_type = "novel"

    # Values reported by an L60 SES; the app shows 170/200, 329/360,
    # 229/250 and 1269/1440 hours remaining for the same device.
    coordinator.data = VacuumState(
        accessories=AccessoryState(
            filter_usage=30,
            main_brush_usage=31,
            side_brush_usage=21,
            sensor_usage=138,
            dustbag_usage=171,
        )
    )

    # A second, default-table vacuum set up after it must not leak its
    # lifespans into the first one's sensors.
    other = MagicMock()
    other.device_name = "Other"
    other.device_id = "other_device"
    other.device_info = {}
    other.device_model = "T2351"
    other.api_type = "novel"
    other.data = VacuumState(accessories=AccessoryState())

    hass.data[DOMAIN] = {"test_entry": {"coordinators": [coordinator, other]}}

    added_entities: list = []
    await async_setup_entry(hass, entry, added_entities.extend)

    remaining = {
        e._attr_name: e
        for e in added_entities
        if e.coordinator is coordinator and e._attr_name.endswith("Remaining")
    }
    assert set(remaining) == {
        "Filter Remaining",
        "Rolling Brush Remaining",
        "Side Brush Remaining",
        "Dust Bag Remaining",
    }
    assert remaining["Filter Remaining"].native_value == 170
    assert remaining["Rolling Brush Remaining"].native_value == 329
    assert remaining["Side Brush Remaining"].native_value == 229
    assert remaining["Dust Bag Remaining"].native_value == 1269
    assert (
        remaining["Dust Bag Remaining"].extra_state_attributes["total_life_hours"]
        == 1440
    )


async def test_accessory_sensors_default_table_has_no_dustbag(hass: HomeAssistant):
    """Models without an override keep the default accessories (no dust bag)."""
    entry = MagicMock()
    entry.entry_id = "test_entry"

    coordinator = MagicMock()
    coordinator.device_name = "RoboVac"
    coordinator.device_id = "test_device"
    coordinator.device_info = {}
    coordinator.device_model = "T2351"
    coordinator.api_type = "novel"
    coordinator.data = VacuumState(accessories=AccessoryState())

    hass.data[DOMAIN] = {"test_entry": {"coordinators": [coordinator]}}

    added_entities: list = []
    await async_setup_entry(hass, entry, added_entities.extend)

    names = {e._attr_name for e in added_entities}
    assert "Dust Bag Remaining" not in names
    assert {
        "Filter Remaining",
        "Rolling Brush Remaining",
        "Side Brush Remaining",
        "Sensor Remaining",
        "Cleaning Tray Remaining",
        "Mopping Cloth Remaining",
    } <= names
