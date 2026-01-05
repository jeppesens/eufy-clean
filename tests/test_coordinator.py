"""Unit tests for the EufyCleanCoordinator."""

# pylint: disable=redefined-outer-name

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState


@pytest.fixture
def mock_hass():
    """Mock the Home Assistant object."""
    return MagicMock()


@pytest.fixture
def mock_login():
    """Mock the EufyLogin object."""
    login = MagicMock()
    login.openudid = "test_udid"
    login.checkLogin = AsyncMock()
    return login


def test_coordinator_init(mock_hass, mock_login):
    """Test coordinator initialization."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
        "dps": {"152": "test_dps"},  # Some initial DPS
    }

    with patch(
        "custom_components.robovac_mqtt.coordinator.update_state"
    ) as mock_update:
        mock_update.return_value = (VacuumState(battery_level=100), {})

        coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

        assert coordinator.device_id == "test_id"
        assert coordinator.device_name == "Test Vac"
        # Verify initial DPS processing
        mock_update.assert_called_once()
        assert coordinator.data.battery_level == 100


@pytest.mark.asyncio
async def test_coordinator_initialize_success(mock_hass, mock_login):
    """Test successful initialization of the coordinator."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }

    mock_login.mqtt_credentials = {
        "user_id": "uid",
        "app_name": "app",
        "thing_name": "thing",
        "certificate_pem": "cert",
        "private_key": "key",
        "endpoint_addr": "endpoint",
    }

    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    with patch(
        "custom_components.robovac_mqtt.coordinator.EufyCleanClient"
    ) as mock_client_cls:
        mock_client = mock_client_cls.return_value
        mock_client.connect = AsyncMock()

        await coordinator.initialize()

        mock_login.checkLogin.assert_not_called()  # Creds existed
        mock_client_cls.assert_called_once()
        mock_client.connect.assert_called_once()
        assert coordinator.client == mock_client


@pytest.mark.asyncio
async def test_coordinator_initialize_failed_creds(mock_hass, mock_login):
    """Test initialization failure when no credentials."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    mock_login.mqtt_credentials = None

    # Even after checkLogin, still None
    async def side_effect_check():
        mock_login.mqtt_credentials = None

    mock_login.checkLogin.side_effect = side_effect_check

    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    with pytest.raises(UpdateFailed):
        await coordinator.initialize()

    mock_login.checkLogin.assert_called_once()


def test_handle_mqtt_message(mock_hass, mock_login):
    """Test handling of MQTT messages."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coordinator.async_set_updated_data = MagicMock()

    # Create dummy payload: {"payload": {"data": {"dps_key": "dps_val"}}}
    payload_str = '{"payload": {"data": {"101": "val"}}}'
    payload_bytes = payload_str.encode()

    with patch(
        "custom_components.robovac_mqtt.coordinator.update_state"
    ) as mock_update:
        new_state = VacuumState(battery_level=50)
        mock_update.return_value = (new_state, {})

        coordinator._handle_mqtt_message(payload_bytes)

        mock_update.assert_called()
        coordinator.async_set_updated_data.assert_called_with(new_state)


@pytest.mark.asyncio
async def test_async_send_command(mock_hass, mock_login):
    """Test sending commands."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    # Mock client
    mock_client = MagicMock()
    mock_client.send_command = AsyncMock()
    coordinator.client = mock_client

    cmd = {"some": "cmd"}
    await coordinator.async_send_command(cmd)

    mock_client.send_command.assert_called_with(cmd)
