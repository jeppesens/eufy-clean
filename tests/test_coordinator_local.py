"""Coordinator tests for the local-Tuya transport path.

Complements test_coordinator.py which covers MQTT and cloud transports.
"""

# pylint: disable=redefined-outer-name

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.robovac_mqtt.api.local_tuya import LocalTuyaError
from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState


@pytest.fixture
def mock_hass():
    return MagicMock()


@pytest.fixture
def mock_login():
    login = MagicMock()
    login.openudid = "test_udid"
    login.checkLogin = AsyncMock()
    return login


def _device_info(connection_type: str | None = None, **extra) -> dict:
    base = {
        "deviceId": "bf64ff37e97fadf4f5pxny",
        "deviceModel": "T2080A",
        "deviceName": "S1 Pro",
    }
    if connection_type is not None:
        base["connection_type"] = connection_type
    base.update(extra)
    return base


def test_connection_type_local_when_overridden(mock_hass, mock_login):
    """Explicit connection_type='local' from device_info overrides defaults."""
    info = _device_info(
        connection_type="local",
        local_key="k" * 16,
        local_host="192.168.1.50",
    )
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, info)
    assert coordinator.connection_type == "local"
    assert coordinator._local_key == "k" * 16
    assert coordinator._local_host == "192.168.1.50"
    # Local push: no polling interval should be set
    assert coordinator._base_poll_interval is None


def test_connection_type_falls_back_to_cloud_without_local_creds(
    mock_hass, mock_login
):
    """mqtt:False with no local creds → cloud polling."""
    info = _device_info(mqtt=False)
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, info)
    assert coordinator.connection_type == "cloud"


def test_connection_type_auto_local_when_creds_present(mock_hass, mock_login):
    """If local_key + local_host are both present (and mqtt:False), prefer local."""
    info = _device_info(
        local_key="k" * 16,
        local_host="192.168.1.50",
        mqtt=False,
    )
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, info)
    assert coordinator.connection_type == "local"


def test_connection_type_defaults_to_mqtt_when_unspecified(
    mock_hass, mock_login
):
    """Backward compatibility: mqtt key absent → mqtt (matches pre-PR behaviour)."""
    info = _device_info()  # no mqtt, no connection_type
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, info)
    assert coordinator.connection_type == "mqtt"


@pytest.mark.asyncio
async def test_initialize_local_falls_back_on_connect_failure(
    mock_hass, mock_login
):
    """If LocalTuyaClient.connect() raises, we should silently fall back to cloud."""
    info = _device_info(
        connection_type="local",
        local_key="k" * 16,
        local_host="192.168.1.50",
    )
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, info)
    coordinator.async_load_storage = AsyncMock()

    failing_client = MagicMock()
    failing_client.set_on_message = MagicMock()
    failing_client.connect = AsyncMock(side_effect=LocalTuyaError("no route"))

    with patch(
        "custom_components.robovac_mqtt.coordinator.LocalTuyaClient",
        return_value=failing_client,
    ):
        await coordinator.initialize()

    assert coordinator.connection_type == "cloud"
    assert coordinator.client is None  # local client should have been cleared


@pytest.mark.asyncio
async def test_initialize_local_success_uses_local_client(
    mock_hass, mock_login
):
    """Successful local init should set up the LocalTuyaClient and not poll."""
    info = _device_info(
        connection_type="local",
        local_key="k" * 16,
        local_host="192.168.1.50",
    )
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, info)
    coordinator.async_load_storage = AsyncMock()

    fake_client = MagicMock()
    fake_client.set_on_message = MagicMock()
    fake_client.connect = AsyncMock()
    fake_client.send_command = AsyncMock()

    with patch(
        "custom_components.robovac_mqtt.coordinator.LocalTuyaClient",
        return_value=fake_client,
    ) as cls:
        await coordinator.initialize()

    cls.assert_called_once_with(
        device_id="bf64ff37e97fadf4f5pxny",
        local_key="k" * 16,
        host="192.168.1.50",
        version=3.3,
    )
    fake_client.connect.assert_awaited_once()
    assert coordinator.client is fake_client
    assert coordinator.connection_type == "local"


@pytest.mark.asyncio
async def test_send_command_routes_to_local_client(mock_hass, mock_login):
    """async_send_command should hand off to LocalTuyaClient.send_command."""
    info = _device_info(
        connection_type="local",
        local_key="k" * 16,
        local_host="192.168.1.50",
    )
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, info)

    fake_client = MagicMock()
    fake_client.send_command = AsyncMock()
    coordinator.client = fake_client

    await coordinator.async_send_command({"154": "BgoEIgIIAg=="})
    fake_client.send_command.assert_awaited_once_with({"154": "BgoEIgIIAg=="})
