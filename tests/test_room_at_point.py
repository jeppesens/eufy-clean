"""Unit tests for tap-a-room-on-the-map resolution (room_at_point).

Covers the three layers behind the bundled card's map taps:
  * MapData.room_id_at_normalized        — pure pixel-mask hit-test (Y-flip + offset)
  * EufyCleanCoordinator.room_id_at_normalized — resolves (id, name), guards no-map
  * RoboVacMQTTEntity.async_room_at_point — the response service the card calls
"""

# pylint: disable=redefined-outer-name, protected-access

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.robovac_mqtt.api.map_stream import MapData
from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _room_mask(width, height, rid_at):
    """Build a room_pixels byte mask. Each byte is (room_id << 2) | sub_type; tests
    use sub_type 0, so byte == rid << 2 (matching render_map_png's `rid = byte >> 2`)."""
    return bytes(((rid_at(px, py) << 2) & 0xFF) for py in range(height) for px in range(width))


def _map_with_mask(rid_at, width=10, height=10, resolution=1, **kw):
    """A MapData whose room mask is filled by rid_at(px, py), aligned to the grid."""
    return MapData(
        raw_pixels=b"",
        width=width,
        height=height,
        resolution=resolution,
        room_pixels=_room_mask(width, height, rid_at),
        room_outline_width=width,
        room_outline_height=height,
        **kw,
    )


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


def _coordinator_with_map(mock_hass, mock_login, map_data):
    """Build a coordinator and pin its decoded map data (skips MQTT)."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
        "dps": {},
    }
    with patch("custom_components.robovac_mqtt.coordinator.update_state") as mock_update:
        mock_update.return_value = (VacuumState(), {})
        coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coordinator._map_data = map_data
    return coordinator


@pytest.fixture
def mock_coordinator():
    """Mock coordinator for entity-level tests."""
    coordinator = MagicMock()
    coordinator.device_id = "test_id"
    coordinator.device_name = "Test Vac"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState()
    return coordinator


# ---------------------------------------------------------------------------
# MapData.room_id_at_normalized — the pure hit-test
# ---------------------------------------------------------------------------


def test_hit_test_no_mask_returns_zero():
    """No room mask decoded yet -> 0 (never raises)."""
    md = MapData(raw_pixels=b"", width=10, height=10, resolution=1)
    assert md.room_id_at_normalized(0.5, 0.5) == 0


def test_hit_test_zero_outline_dims_returns_zero():
    """A mask present but with no outline dims is unusable -> 0."""
    md = MapData(
        raw_pixels=b"",
        width=10,
        height=10,
        resolution=1,
        room_pixels=b"\x1c" * 100,  # rid 7 everywhere, but...
        room_outline_width=0,  # ...no dims -> can't index
        room_outline_height=0,
    )
    assert md.room_id_at_normalized(0.5, 0.5) == 0


def test_hit_test_y_flip_orientation():
    """The render Y-flips, so the image TOP is the source BOTTOM rows.

    Source rows 5-9 carry rid 7, rows 0-4 carry rid 3. A tap near the top of the
    rendered image must resolve to rid 7, and near the bottom to rid 3.
    """
    md = _map_with_mask(lambda px, py: 7 if py >= 5 else 3)
    assert md.room_id_at_normalized(0.5, 0.1) == 7  # image top  -> high source py
    assert md.room_id_at_normalized(0.5, 0.9) == 3  # image bottom -> low source py


def test_hit_test_returns_raw_mask_id():
    """The hit-test returns the raw mask id (incl. the background id); selecting
    which ids are 'real rooms' is the caller's job."""
    md = _map_with_mask(lambda px, py: 0 if px < 5 else 32)
    assert md.room_id_at_normalized(0.1, 0.5) == 0  # left half  -> empty
    assert md.room_id_at_normalized(0.9, 0.5) == 32  # right half -> background id


def test_hit_test_honours_outline_origin_offset():
    """The room mask can have a different origin than the map; the offset (the same
    one render_map_png applies) must shift the lookup, and out-of-mask -> 0."""
    # origin_x 0, room_outline_origin_x -10, res 5 -> ro_dx = (0 - -10)/5 = 2,
    # so map pixel px maps to mask column px-2.
    md = _map_with_mask(
        lambda px, py: 4,
        resolution=5,
        origin_x=0,
        origin_y=0,
        room_outline_origin_x=-10,
        room_outline_origin_y=0,
    )
    assert md.room_id_at_normalized(0.9, 0.5) == 4  # px 9 -> rx 7 (in bounds)
    assert md.room_id_at_normalized(0.0, 0.5) == 0  # px 0 -> rx -2 (out of bounds)


def test_hit_test_clamps_normalized_input():
    """Out-of-range normalized coords are clamped, not indexed out of bounds."""
    md = _map_with_mask(lambda px, py: 9)
    assert md.room_id_at_normalized(-1.0, 2.0) == 9
    assert md.room_id_at_normalized(5.0, -3.0) == 9


# ---------------------------------------------------------------------------
# EufyCleanCoordinator.room_id_at_normalized — (id, name) resolution
# ---------------------------------------------------------------------------


def test_coordinator_no_map_returns_zero_none(mock_hass, mock_login):
    """No map decoded -> (0, None) so the service reports a clean miss."""
    coordinator = _coordinator_with_map(mock_hass, mock_login, None)
    assert coordinator.room_id_at_normalized(0.5, 0.5) == (0, None)


def test_coordinator_resolves_room_name(mock_hass, mock_login):
    """A hit resolves to (id, name) from the mask's room_names."""
    md = _map_with_mask(lambda px, py: 7, room_names={7: "Kitchen"})
    coordinator = _coordinator_with_map(mock_hass, mock_login, md)
    assert coordinator.room_id_at_normalized(0.5, 0.5) == (7, "Kitchen")


def test_coordinator_unnamed_room_returns_id_none(mock_hass, mock_login):
    """A hit on a room with no known name still returns its id, name None."""
    md = _map_with_mask(lambda px, py: 7, room_names={})
    coordinator = _coordinator_with_map(mock_hass, mock_login, md)
    assert coordinator.room_id_at_normalized(0.5, 0.5) == (7, None)


def test_coordinator_miss_returns_zero_none(mock_hass, mock_login):
    """A tap on a 0 (no-room) mask cell -> (0, None)."""
    md = _map_with_mask(lambda px, py: 0)
    coordinator = _coordinator_with_map(mock_hass, mock_login, md)
    assert coordinator.room_id_at_normalized(0.5, 0.5) == (0, None)


# ---------------------------------------------------------------------------
# RoboVacMQTTEntity.async_room_at_point — the response service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_service_returns_resolved_room(mock_coordinator):
    """The service forwards the tap to the coordinator and returns {id, name}."""
    mock_coordinator.room_id_at_normalized = MagicMock(return_value=(5, "Kitchen"))
    entity = RoboVacMQTTEntity(mock_coordinator)

    result = await entity.async_room_at_point(0.4, 0.6)

    assert result == {"room_id": 5, "room_name": "Kitchen"}
    mock_coordinator.room_id_at_normalized.assert_called_once_with(0.4, 0.6)


@pytest.mark.asyncio
async def test_service_miss_returns_empty_name(mock_coordinator):
    """A miss returns room_id 0 and an empty string name (never None, for the card)."""
    mock_coordinator.room_id_at_normalized = MagicMock(return_value=(0, None))
    entity = RoboVacMQTTEntity(mock_coordinator)

    result = await entity.async_room_at_point(0.0, 0.0)

    assert result == {"room_id": 0, "room_name": ""}
