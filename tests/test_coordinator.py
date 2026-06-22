"""Unit tests for the EufyCleanCoordinator."""

# pylint: disable=redefined-outer-name

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.robovac_mqtt.api.map_stream import MapData
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


def _coordinator_with_map(mock_hass, mock_login, map_data):
    """Build a coordinator and pin its decoded map data (skips MQTT)."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
        "dps": {},
    }
    with patch(
        "custom_components.robovac_mqtt.coordinator.update_state"
    ) as mock_update:
        mock_update.return_value = (VacuumState(), {})
        coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coordinator._map_data = map_data  # pylint: disable=protected-access
    return coordinator


def test_normalized_rects_to_quads_cm_no_map(mock_hass, mock_login):
    """With no map decoded yet, the helper returns [] so callers no-op."""
    coordinator = _coordinator_with_map(mock_hass, mock_login, None)
    assert not coordinator.normalized_rects_to_quads_cm([(0.0, 0.0, 1.0, 1.0)])


def test_normalized_rects_to_quads_cm_orientation(mock_hass, mock_login):
    """A normalized rect maps to a world-cm rectangle with the Y-flip baked in."""
    md = MapData(
        raw_pixels=b"",
        width=400,
        height=300,
        origin_x=-1500,
        origin_y=-1000,
        resolution=5,
    )
    coordinator = _coordinator_with_map(mock_hass, mock_login, md)

    quads = coordinator.normalized_rects_to_quads_cm([(0.0, 0.0, 1.0, 1.0)])
    assert len(quads) == 1
    tl, tr, br, bl = quads[0]

    # Axis-aligned rectangle.
    assert tl[0] == bl[0] and tr[0] == br[0]
    assert tl[1] == tr[1] and bl[1] == br[1]
    # X grows left->right across the image.
    assert tl[0] < tr[0]
    # World Y DECREASES top->bottom of the image (render Y-flip).
    assert tl[1] > bl[1]
    # Exact spot-check of the unambiguous top-left corner
    # (nx=0 -> origin_x; ny=0 -> origin_y + (height-1)*res).
    assert tl == (-1500, -1000 + (300 - 1) * 5)


def test_normalized_rects_to_quads_cm_skips_malformed(mock_hass, mock_login):
    """A rect that isn't four numbers is skipped; valid ones still convert."""
    md = MapData(
        raw_pixels=b"", width=100, height=100, origin_x=0, origin_y=0, resolution=10
    )
    coordinator = _coordinator_with_map(mock_hass, mock_login, md)

    quads = coordinator.normalized_rects_to_quads_cm(
        [(0.0, 0.0, 0.5), (0.0, 0.0, 0.5, 0.5)]  # first has only 3 values
    )
    assert len(quads) == 1


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


def test_async_shutdown_timers_cancels_both(mock_hass, mock_login):
    """Test that async_shutdown_timers cancels dock and segment timers."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    mock_dock_cancel = MagicMock()
    mock_segment_cancel = MagicMock()
    coordinator._dock_idle_cancel = mock_dock_cancel
    coordinator._segment_update_cancel = mock_segment_cancel

    coordinator.async_shutdown_timers()

    mock_dock_cancel.assert_called_once()
    mock_segment_cancel.assert_called_once()
    assert coordinator._dock_idle_cancel is None
    assert coordinator._segment_update_cancel is None


def test_async_shutdown_timers_noop_when_no_timers(mock_hass, mock_login):
    """Test async_shutdown_timers is safe with no active timers."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    assert coordinator._dock_idle_cancel is None
    assert coordinator._segment_update_cancel is None

    # Should not raise
    coordinator.async_shutdown_timers()

    assert coordinator._dock_idle_cancel is None
    assert coordinator._segment_update_cancel is None


@pytest.mark.asyncio
async def test_async_send_command_no_client_logs_warning(mock_hass, mock_login):
    """Test that sending command with no client logs warning."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coordinator.client = None

    # Should not raise any exception
    await coordinator.async_send_command({"some": "cmd"})
