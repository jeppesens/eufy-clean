"""Unit tests for profiles.py (DeviceProfile and AccessorySpec)."""

from custom_components.robovac_mqtt.const import (
    API_TYPE_LEGACY,
    API_TYPE_NOVEL,
    API_TYPE_SCALAR,
)
from custom_components.robovac_mqtt.profiles import AccessorySpec, get_device_profile


def test_novel_default_profile():
    profile = get_device_profile("T2261", API_TYPE_NOVEL)
    assert profile.api_type == API_TYPE_NOVEL
    assert "filter_usage" in profile.accessories
    assert profile.accessories["filter_usage"].max_life_hours == 360
    assert profile.accessories["filter_usage"].time_unit == "h"
    assert profile.accessories["side_brush_usage"].max_life_hours == 180


def test_scalar_default_profile():
    profile = get_device_profile("T2210", API_TYPE_SCALAR)
    assert profile.api_type == API_TYPE_SCALAR
    assert "filter_usage" in profile.accessories
    assert profile.accessories["filter_usage"].max_life_hours == 200
    assert profile.accessories["filter_usage"].time_unit == "m"
    assert profile.accessories["side_brush_usage"].max_life_hours == 250
    assert profile.accessories["sensor_usage"].max_life_hours == 35


def test_legacy_t2266_profile():
    profile = get_device_profile("T2266", API_TYPE_LEGACY)
    assert profile.api_type == API_TYPE_LEGACY
    assert "filter_usage" in profile.accessories
    assert profile.accessories["filter_usage"].max_life_hours == 200
    assert profile.accessories["filter_usage"].legacy_key == "FM"
    assert profile.accessories["main_brush_usage"].max_life_hours == 360
    assert profile.accessories["main_brush_usage"].legacy_key == "RB"
    assert profile.accessories["side_brush_usage"].max_life_hours == 180
    assert profile.accessories["side_brush_usage"].legacy_key == "SB"
    assert profile.accessories["dustbag_usage"].max_life_hours == 50
    assert profile.accessories["dustbag_usage"].legacy_key == "DB"


def test_legacy_unmeasured_model():
    profile = get_device_profile("T2118", API_TYPE_LEGACY)
    assert profile.api_type == API_TYPE_LEGACY
    assert profile.accessories == {}


def test_omni_station_profile():
    profile = get_device_profile("T2351", API_TYPE_NOVEL)
    assert "scrape_usage" in profile.accessories
    assert "mop_usage" in profile.accessories
    assert profile.accessories["scrape_usage"].max_life_hours == 30


def test_s1_pro_profile():
    profile = get_device_profile("T2080A", API_TYPE_NOVEL)
    assert "mop_usage" in profile.accessories


def test_l60_hybrid_ses_profile():
    profile = get_device_profile("T2278", API_TYPE_NOVEL)
    assert "mop_usage" in profile.accessories
    assert "scrape_usage" not in profile.accessories


def test_flyweight_memory_optimization():
    """Verify that specs and profiles use __slots__ without __dict__ overhead."""
    spec = AccessorySpec(
        attr_name="test",
        sensor_id="test",
        sensor_name="Test",
        button_id="test",
        button_name="Test",
        icon="mdi:test",
        max_life_hours=100,
    )
    assert not hasattr(spec, "__dict__"), "AccessorySpec must have __slots__"

    profile = get_device_profile("T2351", API_TYPE_NOVEL)
    assert not hasattr(profile, "__dict__"), "DeviceProfile must have __slots__"
