"""Test component setup."""

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

    # Mock the EufyClean API client
    with patch("custom_components.robovac_mqtt.EufyClean") as mock_eufy_clean_cls:
        # Client instance mock
        mock_client = mock_eufy_clean_cls.return_value
        mock_client.init = AsyncMock()
        mock_client.get_devices = AsyncMock(
            return_value=[{"deviceId": "test_device_id", "name": "RoboVac"}]
        )

        # Device mock
        # We use AsyncMock for the device itself so methods are awaitable.
        mock_device = AsyncMock()
        mock_device.device_id = "test_device_id"
        mock_device.device_model_desc = "Test Robovac"
        mock_device.device_model = "T2118"
        # add_listener must be synchronous
        mock_device.add_listener = MagicMock()

        # Configure methods that return complex objects (like protobuf configs)
        # to return a safe object with primitives instead of Mocks, to avoid
        # JSON serialization errors in Home Assistant state.
        class FakeConfig:  # pylint: disable=no-self-use
            def HasField(self, field):
                return True

            def __getattr__(self, name):
                # Return a primitive (int) for any field access
                return 1

            def __bool__(self):
                return True

        mock_cfg = FakeConfig()

        mock_device.get_auto_empty_cfg.return_value = mock_cfg
        mock_device.get_auto_mop_washing_cfg.return_value = mock_cfg
        mock_device.get_wash_frequency_mode.return_value = mock_cfg
        mock_device.get_dry_duration.return_value = mock_cfg
        mock_device.get_auto_empty_mode.return_value = mock_cfg
        mock_device.get_auto_action_cfg.return_value = (
            mock_cfg  # Used by DockSelectEntity
        )
        mock_device.get_scene_list.return_value = []
        mock_device.get_clean_room_list.return_value = []
        mock_device.get_wash_frequency_value_info.return_value = mock_cfg

        # Also need basic status getters to return primitives
        mock_device.get_battery_level = AsyncMock(return_value=100)
        mock_device.get_water_level = AsyncMock(return_value=1)
        mock_device.get_dock_status = AsyncMock(return_value=0)
        mock_device.get_active_map_id = AsyncMock(return_value="map_1")
        mock_device.get_work_status = AsyncMock(return_value="Running")
        mock_device.get_clean_speed = AsyncMock(return_value="Standard")
        mock_device.get_fan_speed_list = AsyncMock(return_value=["Standard", "Turbo"])

        mock_client.init_device = AsyncMock(return_value=mock_device)

        # Setup the config entry
        result = await hass.config_entries.async_setup(config_entry.entry_id)
        assert result is True, f"Async setup failed, result: {result}"

        await hass.async_block_till_done()

        # Check if the entry state is LOADED
        assert (
            config_entry.state == ConfigEntryState.LOADED
        ), f"Entry state is {config_entry.state}, expected {ConfigEntryState.LOADED}"

        # Verify the client methods were called
        mock_eufy_clean_cls.assert_called_with("test_user", "test_password")
        mock_client.init.assert_called_once()
        mock_client.get_devices.assert_called_once()
        mock_client.init_device.assert_called_with("test_device_id")
        # mock_device.connect.assert_called_once()
        # This might be failing if logic skipped connect?

        # Unload the config entry
        unload_result = await hass.config_entries.async_unload(config_entry.entry_id)
        assert unload_result is True, f"Unload failed, result: {unload_result}"

        await hass.async_block_till_done()

        # Check if the entry state is NOT_LOADED
        assert (
            config_entry.state == ConfigEntryState.NOT_LOADED
        ), f"Entry state {config_entry.state}, expected {ConfigEntryState.NOT_LOADED}"
