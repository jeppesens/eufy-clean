"""Tests for diagnostics."""

from unittest.mock import MagicMock

import pytest

from custom_components.robovac_mqtt.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.robovac_mqtt.models import VacuumState


@pytest.mark.asyncio
async def test_diagnostics_output():
    """Test diagnostics returns expected structure with redacted data."""
    coordinator = MagicMock()
    coordinator.device_id = "ABCD1234EFGH5678"
    coordinator.device_model = "T2261"
    coordinator.device_name = "Test Vac"
    coordinator.api_type = "novel"
    coordinator.connection_type = "mqtt"
    coordinator.data = VacuumState(activity="cleaning", battery_level=75)
    coordinator.last_update_success = True
    coordinator.update_interval = None
    coordinator._consecutive_cloud_failures = 0

    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {
        "username": "user@example.com",
        "password": "secret123",
    }

    hass.data = {
        "robovac_mqtt": {
            "test_entry": {"coordinators": [coordinator]}
        }
    }

    result = await async_get_config_entry_diagnostics(hass, entry)

    # Check structure
    assert result["device_count"] == 1
    assert len(result["devices"]) == 1

    device = result["devices"][0]
    assert device["device_id"] == "ABCD1234..."
    assert device["device_model"] == "T2261"
    assert device["api_type"] == "novel"
    assert device["connection_type"] == "mqtt"
    assert device["activity"] == "cleaning"
    assert device["battery_level"] == 75

    # Check password is redacted
    assert result["entry_data"]["password"] == "**REDACTED**"
    # Username should be visible (not in REDACT_KEYS)
    assert result["entry_data"]["username"] == "user@example.com"


@pytest.mark.asyncio
async def test_diagnostics_no_coordinators():
    """Test diagnostics with no coordinators."""
    hass = MagicMock()
    entry = MagicMock()
    entry.entry_id = "empty_entry"
    entry.data = {"username": "user@example.com", "password": "pass"}

    hass.data = {"robovac_mqtt": {"empty_entry": {"coordinators": []}}}

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["device_count"] == 0
    assert result["devices"] == []
