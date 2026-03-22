"""Test component setup."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.robovac_mqtt.const import DOMAIN


async def test_load_unload_entry(hass: HomeAssistant):
    """Test loading and unloading the integration."""
    # Create a mock config entry
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_password",
        },
        entry_id="test_entry_id",
    )
    config_entry.add_to_hass(hass)

    # Mock EufyLogin and EufyCleanCoordinator
    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls, patch(
        "custom_components.robovac_mqtt.EufyCleanCoordinator"
    ) as mock_coord_cls:

        # Setup Login mock
        mock_login = mock_login_cls.return_value
        mock_login.init = AsyncMock()
        mock_login.mqtt_devices = [
            {
                "deviceId": "test_device_id",
                "deviceModel": "T2118",
                "deviceName": "Test Vac",
                "dps": {},
            }
        ]
        mock_login.cloud_devices = []

        # Setup Coordinator mock
        mock_coord = mock_coord_cls.return_value
        mock_coord.initialize = AsyncMock()
        mock_coord.device_id = "test_device_id"
        mock_coord.device_name = "Test Vac"
        mock_coord.device_model = "T2118"
        mock_coord.data = MagicMock()  # Mock the VacuumState data

        # Mock client and disconnect method
        mock_coord.client = MagicMock()
        mock_coord.client.disconnect = AsyncMock()

        # Setup the config entry
        result = await hass.config_entries.async_setup(config_entry.entry_id)
        assert result is True, f"Async setup failed, result: {result}"

        await hass.async_block_till_done()

        # Check if the entry state is LOADED
        assert (
            config_entry.state == ConfigEntryState.LOADED
        ), f"Entry state is {config_entry.state}, expected {ConfigEntryState.LOADED}"

        # Verify calls
        mock_login_cls.assert_called_with(
            "test_user", "test_password", unittest.mock.ANY
        )
        mock_login.init.assert_called_once()
        mock_coord_cls.assert_called_once()
        mock_coord.initialize.assert_called_once()

        # Unload the config entry
        unload_result = await hass.config_entries.async_unload(config_entry.entry_id)
        assert unload_result is True, f"Unload failed, result: {unload_result}"

        await hass.async_block_till_done()

        # Check if the entry state is NOT_LOADED
        assert (
            config_entry.state == ConfigEntryState.NOT_LOADED
        ), f"Entry state {config_entry.state}, expected {ConfigEntryState.NOT_LOADED}"


async def test_mixed_mqtt_and_cloud_device_setup(hass: HomeAssistant):
    """Test setup with both MQTT (novel) and cloud (legacy) devices."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_password",
        },
        entry_id="test_mixed_entry",
    )
    config_entry.add_to_hass(hass)

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls, patch(
        "custom_components.robovac_mqtt.EufyCleanCoordinator"
    ) as mock_coord_cls:

        mock_login = mock_login_cls.return_value
        mock_login.init = AsyncMock()
        mock_login.mqtt_devices = [
            {
                "deviceId": "mqtt_dev_1",
                "deviceModel": "T2261",
                "deviceName": "X8 Pro",
                "dps": {"153": "something"},
                "apiType": "novel",
                "mqtt": True,
            }
        ]
        mock_login.cloud_devices = [
            {
                "deviceId": "cloud_dev_1",
                "deviceModel": "T2210",
                "deviceName": "G30",
                "dps": {"15": "Running"},
                "apiType": "legacy",
                "mqtt": False,
            }
        ]

        # Track coordinator creation calls
        coordinators = []

        def make_coordinator(*args, **kwargs):
            coord = MagicMock()
            coord.initialize = AsyncMock()
            device_info = args[2] if len(args) > 2 else kwargs.get("device_info", {})
            coord.device_id = device_info["deviceId"]
            coord.device_name = device_info["deviceName"]
            coord.device_model = device_info["deviceModel"]
            coord.data = MagicMock()
            coord.client = MagicMock()
            coord.client.disconnect = AsyncMock()
            coordinators.append((coord, device_info))
            return coord

        mock_coord_cls.side_effect = make_coordinator

        result = await hass.config_entries.async_setup(config_entry.entry_id)
        assert result is True
        await hass.async_block_till_done()

        # Should have created 2 coordinators
        assert len(coordinators) == 2

        device_ids = {info["deviceId"] for _, info in coordinators}
        assert "mqtt_dev_1" in device_ids
        assert "cloud_dev_1" in device_ids

        # Both should have initialize() called
        for coord, _ in coordinators:
            coord.initialize.assert_called_once()
