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
            "test_user", "test_password", unittest.mock.ANY, websession=unittest.mock.ANY
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


async def test_bundled_eufy_clean_card_registered(hass: HomeAssistant):
    """The bundled card registers once `frontend` is set up (load-order safe)."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "test_user",
            CONF_PASSWORD: "test_password",
        },
        entry_id="card_entry_id",
    )
    config_entry.add_to_hass(hass)

    when_setup_calls: list = []

    def fake_when_setup(_hass, component, callback):
        when_setup_calls.append((component, callback))

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls, patch(
        "custom_components.robovac_mqtt.EufyCleanCoordinator"
    ) as mock_coord_cls, patch(
        "custom_components.robovac_mqtt.add_extra_js_url"
    ) as mock_add_js, patch(
        "custom_components.robovac_mqtt.async_when_setup", side_effect=fake_when_setup
    ):
        mock_login = mock_login_cls.return_value
        mock_login.init = AsyncMock()
        # Card registration is independent of devices, but setup requires at
        # least one initialized coordinator (ConfigEntryNotReady otherwise).
        mock_login.mqtt_devices = [
            {
                "deviceId": "card_device_id",
                "deviceModel": "T2118",
                "deviceName": "Card Vac",
                "dps": {},
            }
        ]
        mock_login.cloud_devices = []

        mock_coord = mock_coord_cls.return_value
        mock_coord.initialize = AsyncMock()
        mock_coord.device_id = "card_device_id"
        mock_coord.device_name = "Card Vac"
        mock_coord.device_model = "T2118"
        mock_coord.data = MagicMock()
        mock_coord.client = MagicMock()
        mock_coord.client.disconnect = AsyncMock()

        result = await hass.config_entries.async_setup(config_entry.entry_id)
        assert result is True, f"Async setup failed, result: {result}"
        await hass.async_block_till_done()

        # Registration is DEFERRED to the frontend component, not done inline — this
        # is what prevents the load-order race (entry set up before frontend) that
        # left the card unregistered on some installs (#140).
        assert len(when_setup_calls) == 1
        component, register_cb = when_setup_calls[0]
        assert component == "frontend"
        mock_add_js.assert_not_called()  # nothing registered until frontend is up

        # Frontend becomes ready -> the card registers once, with a cache-bust URL.
        await register_cb(hass, "frontend")
        assert hass.data[DOMAIN]["card_registered"] is True
        mock_add_js.assert_called_once()
        registered_url = mock_add_js.call_args.args[1]
        assert registered_url.startswith("/robovac_mqtt/eufy-clean-card.js?v=")

        # Idempotent: a second frontend-ready callback does nothing.
        await register_cb(hass, "frontend")
        mock_add_js.assert_called_once()


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


async def test_setup_auth_failure_raises_config_entry_auth_failed(hass: HomeAssistant):
    """Login failure with EufyLoginError should result in SETUP_ERROR (auth failed)."""
    from custom_components.robovac_mqtt.api.cloud import EufyLoginError

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "bad_user", CONF_PASSWORD: "bad_pass"},
        entry_id="test_auth_fail",
    )
    config_entry.add_to_hass(hass)

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls:
        mock_login = mock_login_cls.return_value
        mock_login.init = AsyncMock(side_effect=EufyLoginError("Invalid credentials"))

        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state == ConfigEntryState.SETUP_ERROR


async def test_setup_network_failure_raises_config_entry_not_ready(hass: HomeAssistant):
    """Network errors should result in SETUP_RETRY (not ready)."""
    import aiohttp

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user", CONF_PASSWORD: "pass"},
        entry_id="test_network_fail",
    )
    config_entry.add_to_hass(hass)

    with patch("custom_components.robovac_mqtt.EufyLogin") as mock_login_cls:
        mock_login = mock_login_cls.return_value
        mock_login.init = AsyncMock(
            side_effect=aiohttp.ClientError("Connection refused")
        )

        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state == ConfigEntryState.SETUP_RETRY
