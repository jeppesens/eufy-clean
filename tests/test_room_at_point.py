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
    """Build a room_pixels byte mask, ids stored OFFSET BY ONE.

    ``map_data_from_tuya_map`` stores ``(id + 1) << 2`` so that a stored 0 means
    "no room" and a real room id 0 stays representable; ``room_id_offset`` takes
    the +1 back off on read. ``rid_at`` may return None for "no room here".
    """
    def _byte(px, py):
        rid = rid_at(px, py)
        return 0 if rid is None else (((rid + 1) << 2) & 0xFF)
    return bytes(_byte(px, py) for py in range(height) for px in range(width))


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
        room_id_offset=1,
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


def test_hit_test_no_mask_returns_none():
    """No room mask decoded yet -> None (never raises)."""
    md = MapData(raw_pixels=b"", width=10, height=10, resolution=1)
    assert md.room_id_at_normalized(0.5, 0.5) is None


def test_hit_test_zero_outline_dims_returns_none():
    """A mask present but with no outline dims is unusable -> None."""
    md = MapData(
        raw_pixels=b"",
        width=10,
        height=10,
        resolution=1,
        room_pixels=b"\x1c" * 100,  # rid 7 everywhere, but...
        room_outline_width=0,  # ...no dims -> can't index
        room_outline_height=0,
    )
    assert md.room_id_at_normalized(0.5, 0.5) is None


def test_hit_test_y_flip_orientation():
    """The render Y-flips, so the image TOP is the source BOTTOM rows.

    Source rows 5-9 carry rid 7, rows 0-4 carry rid 3. A tap near the top of the
    rendered image must resolve to rid 7, and near the bottom to rid 3.
    """
    md = _map_with_mask(lambda px, py: 7 if py >= 5 else 3)
    assert md.room_id_at_normalized(0.5, 0.1) == 7  # image top  -> high source py
    assert md.room_id_at_normalized(0.5, 0.9) == 3  # image bottom -> low source py


def test_hit_test_floors_like_the_card_at_a_cell_boundary():
    """The hit-test must FLOOR the normalized point, exactly as the card does.

    The card's whole-map normalized coordinates are ``nx = col / width`` and
    ``ny = 1 - row / height``, inverted with ``Math.floor`` in ``roomIdAt`` /
    ``cellFromEvent`` (``frontend/eufy-map-renderer.js``) — a cell owns the
    half-open span of its own width. Rounding instead pushed every point in the
    OUTER half of a cell into the next cell, so a tap near a room boundary
    highlighted one room in the card and cleaned a different one.

    Here rooms split at source column 5 on a 10-wide grid. nx = 0.46 is 4.6
    cells across, i.e. the far side of column 4, which is still room 1 — rounding
    made it column 5, i.e. room 2.
    """
    md = _map_with_mask(lambda px, py: 1 if px < 5 else 2)

    assert md.room_id_at_normalized(0.46, 0.5) == 1   # col 4, its far side
    assert md.room_id_at_normalized(0.54, 0.5) == 2   # col 5, its near side
    # Every column resolves to the column the card would pick, sampled off-centre
    # so the two rules genuinely disagree (a cell centre rounds back to itself).
    for col in range(10):
        assert md.room_id_at_normalized((col + 0.7) / 10, 0.5) == (1 if col < 5 else 2)
        assert md.room_id_at_normalized((col + 0.2) / 10, 0.5) == (1 if col < 5 else 2)


def test_hit_test_rows_floor_like_the_card_too():
    """Same rule on the flipped axis: row = floor((1 - ny) * height)."""
    md = _map_with_mask(lambda px, py: 1 if py < 5 else 2)

    for row in range(10):
        for offset in (0.2, 0.7):
            ny = 1.0 - (row + offset) / 10
            assert md.room_id_at_normalized(0.5, ny) == (1 if row < 5 else 2)


def test_hit_test_returns_mask_id_and_room_zero_is_real():
    """An unset mask cell is None, but room id 0 is a REAL room and must survive.

    This is the whole point of the +1 storage offset: the Hallway is room 0 on the
    T2266, so "no room" and "room 0" cannot both be 0.
    """
    md = _map_with_mask(lambda px, py: None if px < 5 else 32)
    assert md.room_id_at_normalized(0.1, 0.5) is None  # left half  -> no room
    assert md.room_id_at_normalized(0.9, 0.5) == 32  # right half -> background id

    md0 = _map_with_mask(lambda px, py: None if px < 5 else 0)
    assert md0.room_id_at_normalized(0.1, 0.5) is None  # no room
    assert md0.room_id_at_normalized(0.9, 0.5) == 0  # room id 0, not a miss


def test_hit_test_honours_outline_origin_offset():
    """The room mask can have a different origin than the map; the offset (the same
    one render_map_png applies) must shift the lookup, and out-of-mask -> None."""
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
    assert md.room_id_at_normalized(0.0, 0.5) is None  # px 0 -> rx -2 (out of bounds)


def test_hit_test_clamps_normalized_input():
    """Out-of-range normalized coords are clamped, not indexed out of bounds."""
    md = _map_with_mask(lambda px, py: 9)
    assert md.room_id_at_normalized(-1.0, 2.0) == 9
    assert md.room_id_at_normalized(5.0, -3.0) == 9


# ---------------------------------------------------------------------------
# EufyCleanCoordinator.room_id_at_normalized — (id, name) resolution
# ---------------------------------------------------------------------------


def test_coordinator_no_map_returns_none_none(mock_hass, mock_login):
    """No map decoded -> (None, None) so the service reports a clean miss."""
    coordinator = _coordinator_with_map(mock_hass, mock_login, None)
    assert coordinator.room_id_at_normalized(0.5, 0.5) == (None, None)


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


def test_coordinator_miss_returns_none_none(mock_hass, mock_login):
    """A tap on an unset (no-room) mask cell -> (None, None)."""
    md = _map_with_mask(lambda px, py: None)
    coordinator = _coordinator_with_map(mock_hass, mock_login, md)
    assert coordinator.room_id_at_normalized(0.5, 0.5) == (None, None)


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
async def test_service_miss_returns_no_room_id(mock_coordinator):
    """A miss is room_id None (0 is a real legacy room) with an empty name."""
    mock_coordinator.room_id_at_normalized = MagicMock(return_value=(None, None))
    entity = RoboVacMQTTEntity(mock_coordinator)

    result = await entity.async_room_at_point(0.0, 0.0)

    assert result == {"room_id": None, "room_name": ""}
