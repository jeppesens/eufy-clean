from unittest.mock import MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.robovac_mqtt.const import DOMAIN
from custom_components.robovac_mqtt.models import AccessoryState, VacuumState
from custom_components.robovac_mqtt.profiles import get_device_profile
from custom_components.robovac_mqtt.sensor import async_setup_entry


async def test_accessory_sensors_setup(hass: HomeAssistant):
    """Test that accessory sensors are set up correctly."""
    entry = MagicMock()
    entry.entry_id = "test_entry"

    coordinator = MagicMock()
    coordinator.device_name = "RoboVac"
    coordinator.device_id = "test_device"
    coordinator.device_info = {}
    coordinator.device_model = "T2266"
    coordinator.api_type = "novel"
    # sensor.py prefers coordinator.profile when it is a real DeviceProfile;
    # a MagicMock is not, so it falls back to get_device_profile(model, api_type).
    coordinator.profile = None
    profile = get_device_profile("T2266", "novel")
    accessory_max = {
        attr: spec.max_life_hours for attr, spec in profile.accessories.items()
    }

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
    max_main = accessory_max["main_brush_usage"]
    assert rb_sensor.native_value == max_main - 100
    assert rb_sensor.extra_state_attributes["usage_hours"] == 100
    assert rb_sensor.extra_state_attributes["total_life_hours"] == max_main

    # Find side brush sensor
    sb_sensor = next(
        e for e in added_entities if e._attr_name == "Side Brush Remaining"
    )
    max_side = accessory_max["side_brush_usage"]
    assert sb_sensor.native_value == max_side - 50

    # Verify negative handling (over usage)
    coordinator.data.accessories.main_brush_usage = 400
    assert rb_sensor.native_value == 0  # Should be 0, not -40 (max(0, ...))


@pytest.mark.parametrize(
    ("model", "usage", "expected"),
    [
        # Values reported by an L60 SES.
        (
            "T2277",
            AccessoryState(
                filter_usage=30,
                main_brush_usage=31,
                side_brush_usage=21,
                sensor_usage=138,
                dustbag_usage=171,
            ),
            {
                "Filter Remaining": (170, 200),
                "Rolling Brush Remaining": (329, 360),
                "Side Brush Remaining": (229, 250),
                "Dust Bag Remaining": (1269, 1440),
            },
        ),
        # Values reported by an Omni E35 (#186). Its profile doesn't list the
        # scrape and dustbag counters, so they get no sensor.
        (
            "T210M",
            AccessoryState(
                filter_usage=27,
                main_brush_usage=27,
                side_brush_usage=27,
                sensor_usage=27,
                scrape_usage=1,
                mop_usage=19,
                dustbag_usage=1,
                dirty_waterfilter_usage=19,
            ),
            {
                "Filter Remaining": (333, 360),
                "Rolling Brush Remaining": (153, 180),
                "Side Brush Remaining": (153, 180),
                "Sensor Remaining": (93, 120),
                "Mopping Cloth Remaining": (41, 60),
                "Sewage Tank Filter Remaining": (161, 180),
            },
        ),
    ],
)
async def test_accessory_sensors_model_override(
    hass: HomeAssistant,
    model: str,
    usage: AccessoryState,
    expected: dict[str, tuple[int, int]],
):
    """A model with its own profile gets exactly those accessories."""
    entry = MagicMock()
    entry.entry_id = "test_entry"

    coordinator = MagicMock()
    coordinator.device_name = "RoboVac"
    coordinator.device_id = "test_device"
    coordinator.device_info = {}
    coordinator.device_model = model
    coordinator.api_type = "novel"
    coordinator.data = VacuumState(accessories=usage)

    # A second, default-profile vacuum set up after it must not leak its
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
    # (remaining, total) hours, as the app shows them for the same device.
    assert {
        name: (e.native_value, e.extra_state_attributes["total_life_hours"])
        for name, e in remaining.items()
    } == expected


async def test_accessory_sensors_default_table_has_no_per_model_parts(
    hass: HomeAssistant,
):
    """Models without an override keep the default accessories.

    The dust bag and sewage tank filter only exist in per-model profiles.
    """
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
    assert {n for n in names if n.endswith("Remaining")} == {
        "Filter Remaining",
        "Rolling Brush Remaining",
        "Side Brush Remaining",
        "Sensor Remaining",
        "Cleaning Tray Remaining",
        "Mopping Cloth Remaining",
    }


def test_s1_pro_lifespans_come_from_the_model_profile():
    """S1 Pro lifespans come from the Eufy app's accessory table; no tray."""
    s1 = get_device_profile("T2080A", "novel").accessories
    assert s1["filter_usage"].max_life_hours == 60
    assert s1["sensor_usage"].max_life_hours == 360
    assert "scrape_usage" not in s1  # no cleaning tray on the S1 Pro
    # The plain S1 (T2080) is a different robot and keeps the default lifespans.
    s1_plain = get_device_profile("T2080", "novel").accessories
    assert s1_plain["filter_usage"].max_life_hours == 360
