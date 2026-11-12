"""Unit tests for the EufyCleanCoordinator."""

import asyncio
import base64
import io
import json
import math
import time
from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from PIL import Image
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.robovac_mqtt.api.map_render import render_map
from custom_components.robovac_mqtt.api.map_stream import MapData
from custom_components.robovac_mqtt.const import DPS_MAP, WORK_STATE_REMOTE_CTRL
from custom_components.robovac_mqtt.coordinator import (
    _LEGACY_MAP_POST_CLEAN_CHECKS,
    _MAP_STATE_SAVE_DELAY,
    EufyCleanCoordinator,
    _safe_storage_key,
)
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.proto.cloud.control_pb2 import ModeCtrlRequest
from custom_components.robovac_mqtt.utils import decode

# pylint: disable=redefined-outer-name


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


def test_normalized_rects_to_quads_cm_keeps_a_rotated_quad(mock_hass, mock_login):
    """Four explicit corners are used AS GIVEN — this is how rotation survives.

    Both wire formats carry a free quadrilateral (legacy ``setNogoZones`` flattens
    x0,y0..x3,y3; the novel path sends a ``Quadrangle``), so the only thing that
    ever made a zone axis-aligned was taking a bounding box here.
    """
    md = MapData(
        raw_pixels=b"", width=100, height=100, origin_x=0, origin_y=0, resolution=10
    )
    coordinator = _coordinator_with_map(mock_hass, mock_login, md)

    # A diamond: no two corners share an x or a y, so a bbox is detectable.
    diamond = [[0.5, 0.2], [0.8, 0.5], [0.5, 0.8], [0.2, 0.5]]
    quads = coordinator.normalized_rects_to_quads_cm([diamond])
    assert len(quads) == 1
    corners = quads[0]
    assert len(corners) == 4
    assert len({c[0] for c in corners}) == 3  # 0.2 / 0.5 / 0.8 in x
    assert len({c[1] for c in corners}) == 3  # and in y — not a rectangle
    # Corner order is preserved, not re-sorted.
    assert corners[0] == coordinator._normalized_to_cm(0.5, 0.2)
    assert corners[1] == coordinator._normalized_to_cm(0.8, 0.5)


def test_normalized_rects_to_quads_cm_rejects_wrong_corner_count(
    mock_hass, mock_login
):
    """A point-list shape must have exactly four corners; a triangle is dropped."""
    md = MapData(
        raw_pixels=b"", width=100, height=100, origin_x=0, origin_y=0, resolution=10
    )
    coordinator = _coordinator_with_map(mock_hass, mock_login, md)
    assert not coordinator.normalized_rects_to_quads_cm(
        [[[0.1, 0.1], [0.5, 0.1], [0.3, 0.5]]]
    )


def test_normalized_lines_to_segments_cm_accepts_explicit_endpoints(
    mock_hass, mock_login
):
    """A wall may be given as two points; both forms produce the same segment."""
    md = MapData(
        raw_pixels=b"", width=100, height=100, origin_x=0, origin_y=0, resolution=10
    )
    coordinator = _coordinator_with_map(mock_hass, mock_login, md)
    flat = coordinator.normalized_lines_to_segments_cm([(0.1, 0.2, 0.7, 0.9)])
    points = coordinator.normalized_lines_to_segments_cm([[[0.1, 0.2], [0.7, 0.9]]])
    assert flat == points
    assert len(flat[0]) == 2


def test_blob_units_round_trip_through_world_cm(mock_hass, mock_login):
    """``_blob_units_to_shapes_cm`` is the exact inverse of the outbound converter.

    Live 0x68 geometry and geometry we send must land in the same frame, or a
    zone would jump the moment the device echoed it back.
    """
    md = MapData(
        raw_pixels=b"", width=150, height=215, origin_x=520, origin_y=1350,
        resolution=5,
    )
    coordinator = _coordinator_with_map(mock_hass, mock_login, md)
    blob = [[(861, 593), (1161, 593), (1161, 893), (861, 893)]]
    cm = coordinator._blob_units_to_shapes_cm(blob)
    assert coordinator._zone_quads_to_blob_units(cm) == blob


def test_live_forbidden_zone_channel_updates_the_map(mock_hass, mock_login):
    """A 0x68 frame replaces the no-go table and publishes a geometry revision."""
    md = MapData(
        raw_pixels=b"", width=150, height=215, origin_x=520, origin_y=1350,
        resolution=5,
    )
    coordinator = _coordinator_with_map(mock_hass, mock_login, md)
    coordinator._rerender_map = MagicMock()
    before = coordinator.map_geometry_revision

    body = bytes.fromhex("1808ba0d10a20918921220a20928921230fa0d38ba0d40fa0d")
    coordinator._on_legacy_meta(0x68, body)

    assert len(md.forbidden_zones) == 1
    assert coordinator._zone_quads_to_blob_units(md.forbidden_zones) == [
        [(861, 593), (1161, 593), (1161, 893), (861, 893)]
    ]
    assert coordinator.map_geometry_revision > before
    coordinator._rerender_map.assert_called_once()


def test_live_zone_channel_ignores_an_empty_body(mock_hass, mock_login):
    """Silence is not "everything was deleted" — existing geometry is kept.

    The device announces a cleared category by not sending a data frame at all,
    so treating an empty body as a clear would erase zones the user still has.
    """
    md = MapData(
        raw_pixels=b"", width=150, height=215, origin_x=520, origin_y=1350,
        resolution=5,
    )
    md.forbidden_zones = [[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]]
    coordinator = _coordinator_with_map(mock_hass, mock_login, md)
    coordinator._rerender_map = MagicMock()
    coordinator._on_legacy_meta(0x68, b"")
    assert len(md.forbidden_zones) == 1
    coordinator._rerender_map.assert_not_called()


def test_geometry_signature_notices_a_moved_zone(mock_hass, mock_login):
    """Editing a zone in place must publish a revision — count alone cannot see it."""
    md = MapData(
        raw_pixels=b"", width=100, height=100, origin_x=0, origin_y=0, resolution=5
    )
    md.forbidden_zones = [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]]
    coordinator = _coordinator_with_map(mock_hass, mock_login, md)
    coordinator._notify_map_geometry()
    revision = coordinator.map_geometry_revision

    md.forbidden_zones = [[(50.0, 50.0), (60.0, 50.0), (60.0, 60.0), (50.0, 60.0)]]
    coordinator._notify_map_geometry()
    assert coordinator.map_geometry_revision > revision


@pytest.mark.asyncio
async def test_set_nogo_zones_reflects_the_write_locally(mock_hass, mock_login):
    """A delete must show immediately: the device never announces an empty category.

    ``replace=True`` with two of three zones is exactly what deleting one looks
    like on the wire, and the local map has to match what was sent — the 0x68
    echo cannot report "now empty", so waiting for it would leave the deleted
    zone on screen.
    """
    md = MapData(
        raw_pixels=b"", width=150, height=215, origin_x=520, origin_y=1350,
        resolution=5,
    )
    md.forbidden_zones = [
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        [(20.0, 20.0), (30.0, 20.0), (30.0, 30.0), (20.0, 30.0)],
    ]
    md.virtual_walls = [((0.0, 0.0), (5.0, 5.0))]
    coordinator = _coordinator_with_map(mock_hass, mock_login, md)
    coordinator.api_type = "legacy"
    coordinator.build_device_command = MagicMock(return_value={"124": "x"})
    coordinator.async_send_command = AsyncMock()
    coordinator._rerender_map = MagicMock()

    # Keep one no-go zone and the wall; drop the other zone.
    await coordinator.async_set_nogo_zones(
        add_forbidden=[[[0.1, 0.1], [0.2, 0.1], [0.2, 0.2], [0.1, 0.2]]],
        add_walls=[(0.3, 0.3, 0.4, 0.4)],
        replace=True,
    )

    coordinator.async_send_command.assert_awaited_once()
    assert len(md.forbidden_zones) == 1  # the two old ones are gone
    assert len(md.virtual_walls) == 1
    assert not md.ban_mop_zones
    coordinator._rerender_map.assert_called_once()


def _legacy_coordinator_with_geometry(mock_hass, mock_login):
    md = MapData(
        raw_pixels=b"", width=150, height=215, origin_x=520, origin_y=1350,
        resolution=5,
    )
    md.forbidden_zones = [
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        [(20.0, 20.0), (30.0, 20.0), (30.0, 30.0), (20.0, 30.0)],
    ]
    md.virtual_walls = [((0.0, 0.0), (5.0, 5.0))]
    coordinator = _coordinator_with_map(mock_hass, mock_login, md)
    coordinator.api_type = "legacy"
    coordinator.build_device_command = MagicMock(return_value={"124": "x"})
    coordinator.async_send_command = AsyncMock()
    coordinator._rerender_map = MagicMock()
    return coordinator, md


@pytest.mark.asyncio
async def test_set_nogo_zones_removes_by_index(mock_hass, mock_login):
    """Deleting keeps the survivors in world cm — they never round-trip the client."""
    coordinator, md = _legacy_coordinator_with_geometry(mock_hass, mock_login)
    survivor = md.forbidden_zones[1]

    await coordinator.async_set_nogo_zones(remove_forbidden=[0])

    assert md.forbidden_zones == [list(survivor)]
    assert len(md.virtual_walls) == 1  # untouched category is resent as-is
    coordinator.async_send_command.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_nogo_zones_rejects_an_out_of_range_index(mock_hass, mock_login):
    """A stale index must fail loudly: the write is replace-all and has no undo."""
    coordinator, md = _legacy_coordinator_with_geometry(mock_hass, mock_login)

    with pytest.raises(HomeAssistantError, match="outside"):
        await coordinator.async_set_nogo_zones(remove_forbidden=[5])

    assert len(md.forbidden_zones) == 2
    coordinator.async_send_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_nogo_zones_revision_guard(mock_hass, mock_login):
    """A client deleting index 1 of geometry it no longer has is refused."""
    coordinator, _md = _legacy_coordinator_with_geometry(mock_hass, mock_login)
    coordinator.map_geometry_revision = 4

    with pytest.raises(HomeAssistantError, match="revision"):
        await coordinator.async_set_nogo_zones(
            remove_forbidden=[1], expect_revision=3
        )
    coordinator.async_send_command.assert_not_awaited()

    await coordinator.async_set_nogo_zones(remove_forbidden=[1], expect_revision=4)
    coordinator.async_send_command.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_nogo_zones_moves_a_shape_by_a_world_cm_delta(mock_hass, mock_login):
    """A move translates the points the device already holds — no round trip.

    The shape here deliberately sits OUTSIDE the map image (x well past
    width * resolution). Coordinates sent from a client would be clamped into the
    image and the zone would jump onto the map edge; a delta carries it exactly.
    """
    coordinator, md = _legacy_coordinator_with_geometry(mock_hass, mock_login)
    md.forbidden_zones = [
        [(2000.0, 3000.0), (2100.0, 3000.0), (2100.0, 3100.0), (2000.0, 3100.0)]
    ]

    await coordinator.async_set_nogo_zones(
        move_forbidden=[{"index": 0, "dx": 50.0, "dy": -25.0}]
    )

    assert md.forbidden_zones == [
        [(2050.0, 2975.0), (2150.0, 2975.0), (2150.0, 3075.0), (2050.0, 3075.0)]
    ]


@pytest.mark.asyncio
async def test_set_nogo_zones_rotates_about_the_centroid(mock_hass, mock_login):
    """Rotation is about the shape's own centre, in isotropic world cm."""
    coordinator, md = _legacy_coordinator_with_geometry(mock_hass, mock_login)
    md.forbidden_zones = [
        [(100.0, 100.0), (300.0, 100.0), (300.0, 200.0), (100.0, 200.0)]
    ]

    await coordinator.async_set_nogo_zones(
        move_forbidden=[{"index": 0, "rotate": math.pi / 2}]
    )

    zone = md.forbidden_zones[0]
    xs = [p[0] for p in zone]
    ys = [p[1] for p in zone]
    # A 200 x 100 box turned a quarter turn about (200, 150) is a 100 x 200 box.
    assert round(max(xs) - min(xs)) == 100
    assert round(max(ys) - min(ys)) == 200
    assert round(sum(xs) / 4) == 200 and round(sum(ys) / 4) == 150  # centre held


@pytest.mark.asyncio
async def test_set_nogo_zones_moves_and_removes_index_the_same_list(
    mock_hass, mock_login
):
    """Both address the ORIGINAL geometry, so one save can do both."""
    coordinator, md = _legacy_coordinator_with_geometry(mock_hass, mock_login)
    moved_from = md.forbidden_zones[1][0]

    await coordinator.async_set_nogo_zones(
        move_forbidden=[{"index": 1, "dx": 10.0, "dy": 0.0}],
        remove_forbidden=[0],
    )

    assert len(md.forbidden_zones) == 1
    assert md.forbidden_zones[0][0] == (moved_from[0] + 10.0, moved_from[1])


@pytest.mark.asyncio
async def test_set_nogo_zones_rejects_moving_and_removing_the_same_shape(
    mock_hass, mock_login
):
    coordinator, _md = _legacy_coordinator_with_geometry(mock_hass, mock_login)
    with pytest.raises(HomeAssistantError, match="both moved and removed"):
        await coordinator.async_set_nogo_zones(
            move_forbidden=[{"index": 0}], remove_forbidden=[0]
        )


@pytest.mark.asyncio
async def test_set_nogo_zones_rejects_a_bad_move_entry(mock_hass, mock_login):
    coordinator, md = _legacy_coordinator_with_geometry(mock_hass, mock_login)
    with pytest.raises(HomeAssistantError, match="outside"):
        await coordinator.async_set_nogo_zones(move_forbidden=[{"index": 9, "dx": 1}])
    with pytest.raises(HomeAssistantError, match="mapping with an 'index'"):
        await coordinator.async_set_nogo_zones(move_walls=[[0, 1, 2]])
    coordinator.async_send_command.assert_not_awaited()
    assert len(md.forbidden_zones) == 2


@pytest.mark.asyncio
async def test_set_nogo_zones_replace_and_remove_conflict(mock_hass, mock_login):
    coordinator, _md = _legacy_coordinator_with_geometry(mock_hass, mock_login)
    with pytest.raises(HomeAssistantError, match="meaningless"):
        await coordinator.async_set_nogo_zones(remove_walls=[0], replace=True)


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
        mock_update.return_value = (new_state, {"battery_level": 50, "raw_dps": {}})

        coordinator._handle_mqtt_message(payload_bytes)

        mock_update.assert_called()
        coordinator.async_set_updated_data.assert_called_with(new_state)


def test_remember_map_id_seeds_and_dedupes(mock_hass, mock_login):
    """A visited map id is recorded once and persisted; re-seeing it or a
    non-positive/missing id is a no-op (cheap to call on every state)."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coordinator.async_save_maps = MagicMock()

    coordinator._remember_map_id(4)
    assert coordinator.last_seen_maps == {4: ""}
    assert coordinator.async_save_maps.call_count == 1

    # Already known -> no re-write, no extra save.
    coordinator._remember_map_id(4)
    assert coordinator.last_seen_maps == {4: ""}
    assert coordinator.async_save_maps.call_count == 1

    # Non-positive / missing ids are ignored.
    coordinator._remember_map_id(0)
    coordinator._remember_map_id(None)
    assert coordinator.last_seen_maps == {4: ""}
    assert coordinator.async_save_maps.call_count == 1


@pytest.mark.asyncio
async def test_async_forget_map_prunes_and_persists(mock_hass, mock_login):
    """forget_map drops a known id, persists, and refreshes listeners so the Switch Map
    selector stops offering it; an unknown id is a no-op (returns False, no extra work)."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coordinator.last_seen_maps = {6: "Home", 7: "Spare", 11: ""}
    coordinator.async_save_maps = AsyncMock()
    coordinator.async_update_listeners = MagicMock()

    removed = await coordinator.async_forget_map(6)
    assert removed is True
    assert coordinator.last_seen_maps == {7: "Spare", 11: ""}
    coordinator.async_save_maps.assert_awaited_once()
    coordinator.async_update_listeners.assert_called_once()

    # Unknown id -> no removal, no extra save/refresh.
    removed = await coordinator.async_forget_map(99)
    assert removed is False
    assert coordinator.last_seen_maps == {7: "Spare", 11: ""}
    coordinator.async_save_maps.assert_awaited_once()
    coordinator.async_update_listeners.assert_called_once()


def test_handle_mqtt_message_seeds_startup_map(mock_hass, mock_login):
    """The map active at STARTUP is persisted even though it never arrives as a
    map_id 'change' — regression for the selector dropping it after a switch."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coordinator.async_set_updated_data = MagicMock()
    coordinator.async_save_maps = MagicMock()

    payload_bytes = b'{"payload": {"data": {"101": "val"}}}'
    with patch(
        "custom_components.robovac_mqtt.coordinator.update_state"
    ) as mock_update:
        # changes == {} -> the startup map_id is NOT flagged as changed.
        mock_update.return_value = (VacuumState(map_id=4), {})
        coordinator._handle_mqtt_message(payload_bytes)

    assert coordinator.last_seen_maps == {4: ""}
    coordinator.async_save_maps.assert_called_once()


def test_handle_mqtt_message_switch_keeps_prior_map(mock_hass, mock_login):
    """Start on map 4, then switch to 6 in the app: both stay in the selector.
    (The reported bug was 4 disappearing until it was switched back to.)"""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coordinator.async_set_updated_data = MagicMock()
    coordinator.async_save_maps = MagicMock()

    payload_bytes = b'{"payload": {"data": {"101": "val"}}}'
    with patch(
        "custom_components.robovac_mqtt.coordinator.update_state"
    ) as mock_update:
        mock_update.return_value = (VacuumState(map_id=4), {})  # startup on 4
        coordinator._handle_mqtt_message(payload_bytes)
        mock_update.return_value = (VacuumState(map_id=6), {"map_id": 6})  # switch
        coordinator._handle_mqtt_message(payload_bytes)

    assert coordinator.last_seen_maps == {4: "", 6: ""}


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
async def test_async_send_command_no_client_raises(mock_hass, mock_login):
    """Test that sending command with no client raises HomeAssistantError."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coordinator.client = None

    with pytest.raises(HomeAssistantError, match="no connection available"):
        await coordinator.async_send_command({"some": "cmd"})


@pytest.mark.asyncio
async def test_async_send_command_empty_dict_ignored(mock_hass, mock_login):
    """Test that sending empty command dict is silently ignored."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    mock_client = MagicMock()
    mock_client.send_command = AsyncMock()
    coordinator.client = mock_client

    await coordinator.async_send_command({})


@pytest.mark.asyncio
async def test_async_send_command_wraps_exception_in_ha_error(mock_hass, mock_login):
    """Test that generic exceptions from MQTT send are wrapped in HomeAssistantError."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2118",
        "deviceName": "Test Vac",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    mock_client = MagicMock()
    mock_client.send_command = AsyncMock(side_effect=OSError("Connection lost"))
    coordinator.client = mock_client

    with pytest.raises(HomeAssistantError, match="Failed to send command"):
        await coordinator.async_send_command({"some": "cmd"})


# ── Cloud/Legacy coordinator tests ─────────────────────────────────


def test_coordinator_cloud_init(mock_hass, mock_login):
    """Cloud coordinator should set connection_type and update_interval."""
    device_info = {
        "deviceId": "cloud_dev",
        "deviceModel": "T2210",
        "deviceName": "Cloud Vac",
        "mqtt": False,
        "apiType": "legacy",
        "dps": {"15": "Running", "104": 80},
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    assert coordinator.connection_type == "cloud"
    assert coordinator.api_type == "legacy"
    assert coordinator.update_interval is not None
    assert coordinator.data.activity == "cleaning"
    assert coordinator.data.battery_level == 80


def test_coordinator_mqtt_novel_init(mock_hass, mock_login):
    """MQTT novel coordinator should have no polling interval."""
    device_info = {
        "deviceId": "mqtt_dev",
        "deviceModel": "T2261",
        "deviceName": "MQTT Vac",
        "mqtt": True,
        "apiType": "novel",
    }

    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    assert coordinator.connection_type == "mqtt"
    assert coordinator.api_type == "novel"
    assert coordinator.update_interval is None


def test_parse_dps_legacy(mock_hass, mock_login):
    """_parse_dps should use legacy parser for legacy api_type."""
    device_info = {
        "deviceId": "dev1",
        "deviceModel": "T2210",
        "deviceName": "Vac",
        "apiType": "legacy",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    new_state, _ = coordinator._parse_dps({"104": 42})
    assert new_state.battery_level == 42


def test_parse_dps_novel(mock_hass, mock_login):
    """_parse_dps should use novel parser for novel api_type."""
    device_info = {
        "deviceId": "dev1",
        "deviceModel": "T2261",
        "deviceName": "Vac",
        "apiType": "novel",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    # DPS 163 is novel battery level (plain int)
    new_state, _ = coordinator._parse_dps({"163": 75})
    assert new_state.battery_level == 75


@pytest.mark.parametrize(
    ("connection_type", "has_p2p", "expected"),
    [
        ("mqtt", False, True),
        ("local", True, True),
        ("local", False, False),
        ("cloud", False, False),
    ],
)
def test_receives_map(mock_hass, mock_login, connection_type, has_p2p, expected):
    """A map arrives over Eufy MQTT or the local P2P feed, never over Tuya Cloud polling."""
    device_info = {
        "deviceId": "dev1",
        "deviceModel": "T2080A",
        "deviceName": "Vac",
        "apiType": "novel",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coordinator.connection_type = connection_type
    coordinator.p2p = MagicMock() if has_p2p else None

    assert coordinator.receives_map is expected


@pytest.mark.parametrize(
    ("connection_type", "has_tuya_session", "expected"),
    [("cloud", True, True), ("local", True, True), ("cloud", False, False)],
)
def test_receives_map_legacy_tuya(
    mock_hass, mock_login, connection_type, has_tuya_session, expected
):
    """A legacy robot's map comes from Tuya cloud storage, which needs a Tuya session."""
    device_info = {
        "deviceId": "dev1",
        "deviceModel": "T2266",
        "deviceName": "Vac",
        "apiType": "legacy",
        "connection_type": connection_type,
    }
    mock_login.tuya_thing_client = MagicMock() if has_tuya_session else None
    mock_login.tuya_client = None
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    assert coordinator.p2p is None
    assert coordinator.receives_map is expected


def test_legacy_robot_skips_the_p2p_feed(mock_hass, mock_login):
    """Legacy robots take the Tuya cloud map; the P2P feed would compete for _map_data."""
    device_info = {
        "deviceId": "dev1",
        "deviceModel": "T2266",
        "deviceName": "Vac",
        "apiType": "legacy",
        "connection_type": "local",
        "local_key": "0123456789abcdef",
        "local_host": "192.168.1.50",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coordinator._start_p2p_feed()

    assert coordinator.p2p is None


def test_build_device_command_legacy(mock_hass, mock_login):
    """build_device_command should use legacy builder for legacy api_type."""
    device_info = {
        "deviceId": "dev1",
        "deviceModel": "T2210",
        "deviceName": "Vac",
        "apiType": "legacy",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    cmd = coordinator.build_device_command("start_auto")
    assert cmd == {"2": True, "5": "auto"}


def test_build_device_command_novel(mock_hass, mock_login):
    """build_device_command should use novel builder for novel api_type."""
    device_info = {
        "deviceId": "dev1",
        "deviceModel": "T2261",
        "deviceName": "Vac",
        "apiType": "novel",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    cmd = coordinator.build_device_command("find_robot", active=True)
    # Novel find_robot uses DPS 160
    assert "160" in cmd


def test_build_device_command_caller_model_wins(mock_hass, mock_login):
    """A model passed by the caller wins over the coordinator's own, so this
    T2080A gets one-based room order. The coordinator's own model is covered by
    test_s1_pro_room_command_uses_its_model_context."""
    device_info = {
        "deviceId": "dev1",
        "deviceModel": "T2080A",
        "deviceName": "Vac",
        "apiType": "novel",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    cmd = coordinator.build_device_command(
        "room_clean", room_ids=[6, 2], map_id=1, model="T2351"
    )
    rooms = decode(ModeCtrlRequest, cmd[DPS_MAP["PLAY_PAUSE"]]).select_rooms_clean.rooms
    assert [(room.id, room.order) for room in rooms] == [(6, 1), (2, 2)]


@pytest.mark.asyncio
async def test_cloud_send_command(mock_hass, mock_login):
    """Cloud coordinator should send commands via Tuya Cloud."""
    device_info = {
        "deviceId": "cloud_dev",
        "deviceModel": "T2210",
        "deviceName": "Cloud Vac",
        "mqtt": False,
        "apiType": "legacy",
    }
    mock_login.sendCloudCommand = AsyncMock()
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    await coordinator.async_send_command({"2": True})
    mock_login.sendCloudCommand.assert_called_once_with("cloud_dev", {"2": True})


@pytest.mark.asyncio
async def test_cloud_initialize(mock_hass, mock_login):
    """Cloud coordinator should initialize without MQTT client."""
    device_info = {
        "deviceId": "cloud_dev",
        "deviceModel": "T2210",
        "deviceName": "Cloud Vac",
        "mqtt": False,
        "apiType": "legacy",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    await coordinator.initialize()

    assert coordinator.client is None


@pytest.mark.asyncio
async def test_cloud_update_data(mock_hass, mock_login):
    """Cloud coordinator should poll via Tuya Cloud API."""
    device_info = {
        "deviceId": "cloud_dev",
        "deviceModel": "T2210",
        "deviceName": "Cloud Vac",
        "mqtt": False,
        "apiType": "legacy",
    }
    mock_login.getCloudDevice = AsyncMock(
        return_value={"15": "Charging", "104": 100}
    )
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    result = await coordinator._async_update_data()

    assert result.battery_level == 100
    assert result.activity == "docked"
    mock_login.getCloudDevice.assert_called_once_with("cloud_dev")


# ── Cloud polling backoff ─────────────────────────────────────────


def _make_cloud_coordinator(mock_hass, mock_login):
    """Helper to create a cloud/legacy coordinator."""
    device_info = {
        "deviceId": "cloud_dev",
        "deviceModel": "T2210",
        "deviceName": "Cloud Vac",
        "mqtt": False,
        "apiType": "legacy",
    }
    return EufyCleanCoordinator(mock_hass, mock_login, device_info)


@pytest.mark.asyncio
async def test_cloud_poll_failure_increments_counter(mock_hass, mock_login):
    """Poll failure should increment consecutive failure counter."""
    mock_login.getCloudDevice = AsyncMock(return_value=None)
    coordinator = _make_cloud_coordinator(mock_hass, mock_login)

    await coordinator._async_update_data()

    assert coordinator._consecutive_cloud_failures == 1


@pytest.mark.asyncio
async def test_cloud_poll_success_resets_counter(mock_hass, mock_login):
    """Successful poll should reset failure counter and restore interval."""
    mock_login.getCloudDevice = AsyncMock(return_value=None)
    coordinator = _make_cloud_coordinator(mock_hass, mock_login)
    base_interval = coordinator.update_interval

    # Simulate 3 failures
    for _ in range(3):
        await coordinator._async_update_data()
    assert coordinator._consecutive_cloud_failures == 3
    assert coordinator.update_interval > base_interval

    # Now succeed
    mock_login.getCloudDevice = AsyncMock(
        return_value={"15": "Charging", "104": 100}
    )
    await coordinator._async_update_data()

    assert coordinator._consecutive_cloud_failures == 0
    assert coordinator.update_interval == base_interval


@pytest.mark.asyncio
async def test_cloud_poll_backoff_increases_interval(mock_hass, mock_login):
    """Each failure should increase the polling interval."""
    mock_login.getCloudDevice = AsyncMock(return_value=None)
    coordinator = _make_cloud_coordinator(mock_hass, mock_login)
    base_interval = coordinator.update_interval

    await coordinator._async_update_data()
    interval_after_1 = coordinator.update_interval

    await coordinator._async_update_data()
    interval_after_2 = coordinator.update_interval

    assert interval_after_1 > base_interval
    assert interval_after_2 > interval_after_1


@pytest.mark.asyncio
async def test_cloud_poll_raises_after_threshold(mock_hass, mock_login):
    """After threshold consecutive failures, UpdateFailed should be raised."""
    mock_login.getCloudDevice = AsyncMock(return_value=None)
    coordinator = _make_cloud_coordinator(mock_hass, mock_login)

    # First 4 failures return stale data
    for _ in range(4):
        result = await coordinator._async_update_data()
        assert isinstance(result, VacuumState)

    # 5th failure should raise
    with pytest.raises(UpdateFailed, match="unreachable after 5"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_cloud_poll_backoff_caps_at_max(mock_hass, mock_login):
    """Backoff interval should not exceed 5 minutes."""
    mock_login.getCloudDevice = AsyncMock(return_value=None)
    coordinator = _make_cloud_coordinator(mock_hass, mock_login)

    # Run up to threshold - 1 failures (before UpdateFailed)
    for _ in range(4):
        await coordinator._async_update_data()

    assert coordinator.update_interval <= timedelta(minutes=5)


def test_resolve_map_id_priority(mock_hass, mock_login, caplog):
    """resolve_map_id: per-map override > all-maps override > device-reported
    id > 1, with a lone per-map override in place of the 1 until a map id is
    reported.

    Overrides exist because some devices (T2080A / S1 Pro) report their cloud
    map id on the UniversalData DPS, which the firmware rejects in
    SelectRoomsClean — the user can pin the local map id instead.
    """
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2080A",
        "deviceName": "Test Vac",
        "dps": {},
    }
    with patch(
        "custom_components.robovac_mqtt.coordinator.update_state"
    ) as mock_update:
        mock_update.return_value = (VacuumState(), {})
        coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)

    # Nothing known yet -> firmware default (first saved map).
    assert coordinator.resolve_map_id() == 1
    # Device-reported id is used when present...
    coordinator.data.map_id = 2154
    assert coordinator.resolve_map_id() == 2154
    # ...a per-map override for another map leaves it alone, and the log names
    # the reported id so the user knows which line to add...
    coordinator.map_id_overrides = {3001: 2}
    assert coordinator.resolve_map_id() == 2154
    assert "'2154: <local id>'" in caplog.text
    # ...the all-maps override wins over the reported id, and the unmatched map
    # is still named in the log...
    caplog.clear()
    coordinator.map_id_override = 1
    assert coordinator.resolve_map_id() == 1
    assert "'2154: <local id>'" in caplog.text
    # ...and an override for the reported map wins over everything.
    coordinator.data.map_id = 3001
    assert coordinator.resolve_map_id() == 2

    # No map id reported yet (e.g. just after setup, before DPS 165): the log
    # says so, and a lone per-map line is used instead of the 1...
    coordinator.data.map_id = 0
    coordinator.map_id_override = None
    assert coordinator.resolve_map_id() == 2
    assert "No map id reported yet" in caplog.text
    # ...but with several lines the current map is unknown, so 1 stays.
    coordinator.map_id_overrides = {3001: 2, 2154: 3}
    assert coordinator.resolve_map_id() == 1


def test_map_id_override_from_device_info(mock_hass, mock_login):
    """The map-id overrides plumbed through device_info land on the coordinator."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2080A",
        "deviceName": "Test Vac",
        "dps": {},
        "map_id_override": 1,
        "map_id_overrides": {2154: 2},
    }
    with patch(
        "custom_components.robovac_mqtt.coordinator.update_state"
    ) as mock_update:
        mock_update.return_value = (VacuumState(), {})
        coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    assert coordinator.map_id_override == 1
    assert coordinator.map_id_overrides == {2154: 2}


@pytest.fixture
def current_room_coordinator():
    coord = EufyCleanCoordinator(
        MagicMock(), MagicMock(),
        {"deviceId": "test", "deviceName": "Vacuum cleaner", "deviceModel": "T2351"},
    )
    # Asymmetric mask catches accidental Y inversion; left/right room split.
    coord._map_data = MapData(
        raw_pixels=b"", width=4, height=3, resolution=1,
        room_pixels=bytes(rid << 2 for rid in [7, 7, 8, 8, 7, 7, 8, 8, 9, 9, 9, 9]),
        room_outline_width=4, room_outline_height=3,
        room_names={7: "Bathroom", 8: "Hallway", 9: "Living Room"},
    )
    return coord


@pytest.mark.parametrize("pixel,expected", [
    ((0, 0), (7, "Bathroom")), ((3, 0), (8, "Hallway")),
    ((0, 2), (9, "Living Room")), ((3, 2), (9, "Living Room")),
    (None, (None, None)), ((-1, 0), (None, None)), ((4, 0), (None, None)),
])
def test_physical_room(current_room_coordinator, pixel, expected):
    coordinator = current_room_coordinator
    coordinator._robot_pixel = pixel
    coordinator.data.robot_position_x = 14522
    coordinator.data.robot_position_y = 2410
    coordinator.data.active_room_ids = [8]
    assert coordinator.current_room() == expected


def test_missing_map_or_mask(current_room_coordinator):
    coordinator = current_room_coordinator
    coordinator._robot_pixel = (0, 0)
    coordinator._map_data.room_pixels = None
    assert coordinator.current_room() == (None, None)
    coordinator._map_data = None
    assert coordinator.current_room() == (None, None)


@pytest.mark.parametrize("width,height", [(0, 3), (4, 0), (-1, 3)])
def test_invalid_dimensions(current_room_coordinator, width, height):
    coordinator = current_room_coordinator
    coordinator._robot_pixel = (0, 0)
    coordinator._map_data.width = width
    coordinator._map_data.height = height
    assert coordinator.current_room() == (None, None)


def test_only_room_changes_signal(current_room_coordinator):
    coordinator = current_room_coordinator
    coordinator.async_update_listeners = MagicMock()
    with patch("custom_components.robovac_mqtt.coordinator.async_dispatcher_send") as send:
        coordinator._robot_pixel = (0, 0)
        coordinator._update_current_room()
        coordinator._robot_pixel = (1, 1)
        coordinator._update_current_room()
        assert send.call_count == 1
        coordinator._robot_pixel = (2, 1)
        coordinator._update_current_room()
        assert send.call_count == 2
        coordinator._map_data.room_names[8] = "Renamed Hallway"
        coordinator._update_current_room()
        assert send.call_count == 3
        coordinator._robot_pixel = None
        coordinator._update_current_room()
        assert send.call_count == 4
        coordinator._update_current_room()
        assert send.call_count == 4
        coordinator.async_update_listeners.assert_not_called()


def _room_zero_coordinator(room_names):
    """A legacy map (rooms numbered from 0) with the robot in room 0."""
    coord = EufyCleanCoordinator(
        MagicMock(), MagicMock(),
        {"deviceId": "test", "deviceName": "Vacuum cleaner", "deviceModel": "T2266"},
    )
    coord._map_data = MapData(
        raw_pixels=b"", width=2, height=1, resolution=1,
        room_pixels=bytes(stored << 2 for stored in [1, 2]),
        room_outline_width=2, room_outline_height=1,
        room_names=room_names, room_id_offset=1,
    )
    coord._robot_pixel = (0, 0)
    return coord


def test_legacy_room_zero_is_a_room():
    coordinator = _room_zero_coordinator({0: "Hallway"})
    assert coordinator.current_room() == (0, "Hallway")


def test_legacy_room_zero_takes_its_name_from_the_room_list():
    coordinator = _room_zero_coordinator({})
    coordinator.data.rooms = [{"id": 0, "name": "Hallway"}]
    assert coordinator.current_room() == (0, "Hallway")


def test_current_room_name_fallback(current_room_coordinator):
    coordinator = current_room_coordinator
    coordinator._robot_pixel = (0, 0)
    coordinator._map_data.room_names.clear()
    assert coordinator.current_room() == (7, None)
    coordinator.data.rooms = [{"id": 7, "name": "Bathroom"}]
    assert coordinator.current_room() == (7, "Bathroom")


def test_calibration_points_match_the_renderer(mock_hass, mock_login):
    """World-cm <-> image-pixel pairs follow the renderer's Y-flip and scale."""
    coordinator = EufyCleanCoordinator(
        mock_hass, mock_login, {"deviceId": "d", "deviceModel": "T2080A", "deviceName": "S1"}
    )
    assert coordinator.calibration_points() is None
    md = MapData(raw_pixels=b"\xaa" * 50, width=20, height=10, origin_x=-100, origin_y=-50, resolution=5)
    coordinator._map_data = md
    coordinator.map_image = render_map(md, max_px=200)
    assert Image.open(io.BytesIO(coordinator.map_image)).size == (200, 100)
    points = coordinator.calibration_points()
    assert points[0] == {"vacuum": {"x": -100, "y": -50}, "map": {"x": 5.0, "y": 95.0}}
    # +500 cm in x = +100 grid cells; +500 cm in y moves up the image.
    assert points[1]["map"] == {"x": 1005.0, "y": 95.0}
    assert points[2]["map"] == {"x": 5.0, "y": -905.0}


def test_remote_control_is_not_treated_as_the_robot_moving_for_p2p():
    """Manual control must not trigger the continuously moving map retry policy."""

    class _Stub:
        data = VacuumState(activity="cleaning", status_code=3)

    stub = _Stub()
    assert EufyCleanCoordinator._robot_is_moving(stub) is True
    stub.data = VacuumState(activity="cleaning", status_code=WORK_STATE_REMOTE_CTRL)
    assert EufyCleanCoordinator._robot_is_moving(stub) is False
    stub.data = VacuumState(activity="docked", status_code=0)
    assert EufyCleanCoordinator._robot_is_moving(stub) is False


def test_s1_pro_remote_command_uses_its_model_context(mock_hass, mock_login):
    device_info = {
        "deviceId": "dev1", "deviceModel": "T2080A", "deviceName": "Vac", "apiType": "novel",
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    assert coordinator.build_device_command("remote_move", direction="left") == {"155": "BBICCAM="}
    assert coordinator.build_device_command("remote_move", direction="brake") == {"155": "AhIA"}


@pytest.mark.parametrize("connection_type", ["local", "cloud"])
def test_s1_pro_room_command_uses_its_model_context(mock_hass, mock_login, connection_type):
    """Room entities need no model override to get the T2080A's zero-based slots."""
    device_info = {
        "deviceId": "dev1", "deviceModel": "T2080A", "deviceName": "Vac",
        "apiType": "novel", "connection_type": connection_type,
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    command = coordinator.build_device_command("room_clean", room_ids=[6, 2], map_id=7)
    rooms = decode(ModeCtrlRequest, command["152"]).select_rooms_clean.rooms
    assert [(room.id, room.order) for room in rooms] == [(6, 0), (2, 1)]


# --- legacy map: blob re-fetch, cold start and change detection ---------------
#
# The blob carries no room outlines (they exist only on the 0x65 stream channel)
# and a parked robot publishes nothing, so anything that installs a fresh
# blob-built MapData has to carry the cached outlines across or they are gone
# until the polygons themselves change.


def test_live_dock_pose_replaces_the_blob_copy(mock_hass, mock_login):
    """0x75 is map-relative 0.5 cm, row-flipped — the same maths as the blob's tag 11.

    Checked against a real frame: origin (520,1350), dock (472,1358), height 215
    -> cell (47, 78), which is the dock this map renders.
    """
    md = _blob_map_data()
    md.dock_pixel = (10, 10)
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, md)
    coordinator._legacy_dock_pose = {"x": 472, "y": 1358, "theta": 0, "type": 1}

    assert coordinator._apply_legacy_dock_pose() is True
    assert md.dock_pixel == (47, 78)
    assert coordinator._dock_pixel == (47, 78)
    # ...and the pose transform now hangs off the live value.
    assert coordinator._legacy_pose_to_pixel(0, 0) is not None
    assert coordinator._apply_legacy_dock_pose() is False  # idempotent


def test_a_dock_off_the_grid_is_refused(mock_hass, mock_login):
    """An off-grid dock means the GRID is stale; keep what we have."""
    md = _blob_map_data()
    md.dock_pixel = (10, 10)
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, md)
    coordinator._legacy_dock_pose = {"x": 99999, "y": 0, "theta": 0, "type": 1}
    assert coordinator._apply_legacy_dock_pose() is False
    assert md.dock_pixel == (10, 10)


def test_changed_extents_refetch_rather_than_reinterpret_the_grid(
    mock_hass, mock_login
):
    """raw_pixels is indexed by the extents it was fetched with."""
    md = _blob_map_data()
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, md)
    mock_hass.async_create_task = MagicMock()
    coordinator._legacy_map_param = {
        "width": 151, "height": 215, "origin_x": 530, "origin_y": 1350,
        "dock_x": 482, "dock_y": 1358,
    }

    assert coordinator._check_legacy_map_param() is True
    assert (md.width, md.origin_x) == (150, 520), "the held grid is left alone"
    mock_hass.async_create_task.assert_called_once()
    mock_hass.async_create_task.call_args[0][0].close()

    # Throttled: a repeat announcement must not spin the download.
    mock_hass.async_create_task.reset_mock()
    assert coordinator._check_legacy_map_param() is False
    mock_hass.async_create_task.assert_not_called()


def test_matching_extents_do_nothing(mock_hass, mock_login):
    """The common case is the device confirming what we already hold."""
    md = _blob_map_data()
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, md)
    mock_hass.async_create_task = MagicMock()
    coordinator._legacy_map_param = {
        "width": 150, "height": 215, "origin_x": 520, "origin_y": 1350,
        "dock_x": 472, "dock_y": 1358,
    }
    assert coordinator._check_legacy_map_param() is False
    mock_hass.async_create_task.assert_not_called()


@pytest.mark.asyncio
async def test_a_refetch_does_not_revert_a_zone_edit_the_blob_predates(
    mock_hass, mock_login
):
    """The blob is written on the device's schedule — up to an hour behind."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator.data = replace(coordinator.data, rooms=[{"id": 0, "name": "Hallway"}])
    # The user just deleted every no-go zone; the write path stamps that.
    coordinator.remember_live_restricted_geometry(0x68, [])

    fresh = _blob_map_data()
    fresh.forbidden_zones = [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]]
    tuya_map = MagicMock()
    tuya_map.as_entity_rooms.return_value = coordinator.data.rooms
    coordinator._map_storage.async_fetch_map.return_value = tuya_map
    coordinator._map_storage.last_map_version = f"{time.time() - 600:.0f}:/blob"
    mock_hass.async_add_executor_job = AsyncMock(return_value=fresh)

    assert await coordinator.async_refresh_legacy_map() is True
    assert not fresh.forbidden_zones, "the deleted zone must not come back"


@pytest.mark.asyncio
async def test_a_refetch_keeps_geometry_the_blob_is_newer_than(mock_hass, mock_login):
    """An edit made in the APP is exactly the case our copy must not override."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator.data = replace(coordinator.data, rooms=[{"id": 0, "name": "Hallway"}])
    coordinator._legacy_live_geometry[0x68] = ([], time.time() - 3600)

    fresh = _blob_map_data()
    zone = [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]]
    fresh.forbidden_zones = list(zone)
    tuya_map = MagicMock()
    tuya_map.as_entity_rooms.return_value = coordinator.data.rooms
    coordinator._map_storage.async_fetch_map.return_value = tuya_map
    coordinator._map_storage.last_map_version = f"{time.time():.0f}:/blob"
    mock_hass.async_add_executor_job = AsyncMock(return_value=fresh)

    assert await coordinator.async_refresh_legacy_map() is True
    assert fresh.forbidden_zones == zone


def _end_a_clean(coordinator, prev="cleaning", activity="docked"):
    """Drive the activity transition that ends a cleaning session."""
    coordinator._track_activity_change(
        prev, VacuumState(activity=activity), {"activity": activity}
    )


@pytest.mark.parametrize(
    ("api_type", "dock_after", "robot_after"),
    [
        # novel: the map carries no dock, so the robot's resting cell becomes it
        ("novel", (20, 20), (20, 20)),
        # legacy: the dock is the map's; the pose snaps onto it
        ("legacy", (5, 5), (5, 5)),
    ],
)
def test_the_dock_cell_follows_each_docking(
    mock_hass, mock_login, api_type, dock_after, robot_after
):
    """A dock captured once (a stop mid-room, another map) must not stick."""
    coordinator = _coordinator_with_map(
        mock_hass, mock_login, MapData(raw_pixels=b"", width=40, height=40,
                                       origin_x=0, origin_y=0, resolution=5)
    )
    coordinator.api_type = api_type
    coordinator._dock_pixel = (5, 5)
    coordinator._robot_pixel = (20, 20)

    with patch("custom_components.robovac_mqtt.coordinator.async_call_later"):
        _end_a_clean(coordinator)

    assert coordinator._dock_pixel == dock_after
    assert coordinator._robot_pixel == robot_after


def test_a_finished_clean_arms_the_two_map_freshness_checks(mock_hass, mock_login):
    """The rewrite happens after the clean, so that is when we look for it."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    with patch(
        "custom_components.robovac_mqtt.coordinator.async_call_later"
    ) as later:
        later.side_effect = lambda *a, **k: MagicMock()
        _end_a_clean(coordinator)
        assert [c[0][1] for c in later.call_args_list] == list(
            _LEGACY_MAP_POST_CLEAN_CHECKS
        )


def test_each_leg_of_a_resume_run_rearms_rather_than_piling_up(mock_hass, mock_login):
    """A recharge-and-resume run docks once per leg; two checks stay two."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    cancels = []
    with patch(
        "custom_components.robovac_mqtt.coordinator.async_call_later"
    ) as later:
        later.side_effect = lambda *a, **k: cancels.append(MagicMock()) or cancels[-1]
        _end_a_clean(coordinator)
        first = list(cancels)
        _end_a_clean(coordinator, prev="returning")
    assert all(c.called for c in first), "the previous leg's checks are cancelled"
    assert len(coordinator._map_freshness_cancels) == 2


def test_sitting_in_the_dock_arms_nothing(mock_hass, mock_login):
    """Only a clean ENDING arms the checks — not any report of being docked."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    with patch(
        "custom_components.robovac_mqtt.coordinator.async_call_later"
    ) as later:
        _end_a_clean(coordinator, prev="idle")
        later.assert_not_called()


@pytest.mark.asyncio
async def test_the_freshness_check_runs_while_parked(mock_hass, mock_login):
    """It is armed after docking, so refusing to run while parked would be fatal."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator.data = replace(coordinator.data, activity="docked")
    coordinator._map_version = "v1"
    coordinator._map_storage.async_map_version.return_value = "v2"
    coordinator.async_refresh_legacy_map = AsyncMock(return_value=True)

    await coordinator._async_legacy_map_freshness()
    coordinator.async_refresh_legacy_map.assert_awaited_once()


def test_the_return_to_dock_leg_is_kept_but_the_post_dock_replay_is_not():
    """The dashed transit leg is only drawable if its frames survive the gate."""
    md = MapData(
        raw_pixels=b"", width=150, height=215, origin_x=520, origin_y=1350,
        resolution=5,
    )
    md.dock_pixel = (47, 78)
    coordinator = _coordinator_with_map(MagicMock(), MagicMock(), md)
    coordinator.api_type = "legacy"
    coordinator._rerender_map = MagicMock()

    coordinator.data = replace(coordinator.data, activity="cleaning")
    coordinator._on_legacy_trail(1, [(0, 0, 0)])
    assert len(coordinator._robot_trail) == 1

    # Heading home: type-1 transit points, still part of this session.
    coordinator.data = replace(coordinator.data, activity="returning")
    coordinator._on_legacy_trail(2, [(10, 10, 1), (20, 20, 1)])
    assert len(coordinator._robot_trail) == 3
    assert coordinator._robot_trail_types[-1] == 1

    # On the dock the session is over: the device replays its history, which must
    # not be appended on top of the trail we already have.
    coordinator.data = replace(coordinator.data, activity="docked")
    coordinator._on_legacy_trail(3, [(30, 30, 0)])
    assert len(coordinator._robot_trail) == 3


def _legacy_map_coordinator(mock_hass, mock_login, map_data=None):
    """A legacy coordinator with a mocked Tuya storage client."""
    coordinator = _coordinator_with_map(mock_hass, mock_login, map_data)
    coordinator.api_type = "legacy"
    storage = MagicMock()
    storage.async_fetch_map = AsyncMock()
    storage.async_map_version = AsyncMock()
    storage.last_map_version = "v-new"
    coordinator._map_storage = storage
    coordinator._rerender_map = MagicMock()
    # Past startup: .storage has been read, so the coordinator knows which map it
    # holds. The one test that cares flips this back off itself.
    coordinator._storage_loaded = True
    return coordinator


def _blob_map_data():
    return MapData(
        raw_pixels=b"", width=150, height=215, origin_x=520, origin_y=1350,
        resolution=5,
    )


@pytest.mark.asyncio
async def test_blob_refetch_keeps_the_live_room_polygons(mock_hass, mock_login):
    """A re-fetch must not drop the stream-only room outlines."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator._legacy_room_polygons = {0: [(0, 0), (100, 0), (100, 100)]}
    fresh = _blob_map_data()
    tuya_map = MagicMock()
    tuya_map.as_entity_rooms.return_value = []
    coordinator._map_storage.async_fetch_map.return_value = tuya_map
    mock_hass.async_add_executor_job = AsyncMock(return_value=fresh)

    assert await coordinator.async_refresh_legacy_map() is True
    assert list(fresh.room_polygons) == [0]
    assert len(fresh.room_polygons[0]) == 3


def test_room_polygons_are_reprojected_onto_the_current_map(mock_hass, mock_login):
    """Cells are recomputed from the world-frame cache, not copied.

    A re-fetched map can have grown, and the cell of a vertex depends on the
    map's own origin and height.
    """
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator._legacy_room_polygons = {0: [(0, 0), (100, 0), (100, 100)]}
    assert coordinator._apply_legacy_room_polygons() is True
    first = coordinator._map_data.room_polygons[0]

    taller = _blob_map_data()
    taller.height = 238
    coordinator._map_data = taller
    coordinator._apply_legacy_room_polygons()
    assert coordinator._map_data.room_polygons[0] != first


# --- the room list off the stream (0x6a / 0x70 / 0x71 / 0x73) -----------------
# Synthetic six-room frames in the device's wire layout: 0x70 rooms 0-5 with
# room 0 clean_times 2, room 1 fan 2, room 2 order 1; 0x73 orders room 2 = 1,
# room 5 = 2; 0x6a names Entry, Lounge, Guest Room, Study, Washroom, Galley.
_LIVE_ROOM_CUSTOM = bytes.fromhex(
    "0810011801200428010a080210021803200228010a080410011802200228020a"
    "080610031801200428010a080810011804200228010a080a1002180120022801"
)
_LIVE_ROOM_ORDER = bytes.fromhex(
    "021001040802100104080410020408061001040808100104080a1004"
)
_LIVE_ROOM_NAMES = bytes.fromhex(
    "071205456e7472790a080112064c6f756e67650e0802120a477565737420526f"
    "6f6d090803120553747564790c0804120857617368726f6f6d0a080512064761"
    "6c6c6579"
)


def _six_rooms(coordinator):
    return {room["id"]: room for room in coordinator.data.rooms}


def test_live_room_settings_reach_the_room_list(mock_hass, mock_login):
    """A 0x70 frame updates the per-room overrides without a blob download.

    These were blob-only: a suction change made in the eufy app did not reach the
    selectors until the device next rewrote its map object, which is hours.
    """
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator.data = replace(coordinator.data, rooms=[
        {"id": 0, "name": "Hallway", "fan_speed": -1, "water_level": -1,
         "clean_times": 0, "clean_order": 0},
    ])
    coordinator._on_legacy_meta(0x70, _LIVE_ROOM_CUSTOM)

    rooms = _six_rooms(coordinator)
    assert rooms[0]["clean_times"] == 2
    assert rooms[1]["fan_speed"] == 2
    assert rooms[2]["clean_order"] == 1
    # The name the list already had is kept: 0x70 carries no names.
    assert rooms[0]["name"] == "Hallway"


def test_live_clean_order_does_not_blank_the_other_room_settings(
    mock_hass, mock_login
):
    """0x73 is the order column only, so it MERGES into the 0x70 rows.

    Taking it as a whole row would leave every room at fan/water -1 — a silent
    reset of settings the user set, with nothing on the wire to blame.
    """
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator._on_legacy_meta(0x70, _LIVE_ROOM_CUSTOM)
    coordinator._on_legacy_meta(0x73, _LIVE_ROOM_ORDER)

    rooms = _six_rooms(coordinator)
    assert rooms[1]["fan_speed"] == 2
    assert rooms[2]["clean_order"] == 1
    assert coordinator._legacy_room_custom[1]["fan_speed"] == 2


def test_live_room_names_reach_the_room_list(mock_hass, mock_login):
    """A rename must reach the SELECTORS, not just the map layer.

    0x6a already updated MapData.room_names; the room list it is chosen from was
    rebuilt only by a blob fetch, so the two could disagree for hours.
    """
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator.data = replace(coordinator.data, rooms=[
        {"id": 0, "name": "Room 0"}, {"id": 1, "name": "Room 1"},
    ])
    coordinator._on_legacy_meta(0x6A, _LIVE_ROOM_NAMES)

    rooms = _six_rooms(coordinator)
    assert rooms[0]["name"] == "Entry"
    assert rooms[1]["name"] == "Lounge"


def test_a_room_the_list_has_never_seen_is_appended(mock_hass, mock_login):
    """The blob counts grid cells; 0x6a is the device's own table.

    A room named on the stream but absent from our (older) grid is added rather
    than hidden — hiding it makes it unselectable — and the rooms already in the
    list keep their position so the entities do not reshuffle.
    """
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator.data = replace(coordinator.data, rooms=[{"id": 5, "name": "Kitchen"}])
    coordinator._on_legacy_meta(0x6A, _LIVE_ROOM_NAMES)

    assert [room["id"] for room in coordinator.data.rooms] == [5, 0, 1, 2, 3, 4]
    assert _six_rooms(coordinator)[3]["name"] == "Study"


def test_live_room_table_is_idempotent(mock_hass, mock_login):
    """An identical re-send changes nothing, so nothing is dispatched twice."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator._on_legacy_meta(0x70, _LIVE_ROOM_CUSTOM)
    before = [dict(room) for room in coordinator.data.rooms]
    assert coordinator._remember_legacy_room_custom(
        {rid: dict(row) for rid, row in coordinator._legacy_room_custom.items()}
    ) is False
    assert coordinator.data.rooms == before


def test_live_custom_clean_flag_comes_off_0x71(mock_hass, mock_login):
    """0x71 is the one part of the per-room settings 0x70 cannot tell you.

    With it off the robot stores every override and obeys none — otherwise
    indistinguishable from a failed write.
    """
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    assert coordinator.legacy_custom_clean_enabled is None
    coordinator._on_legacy_meta(0x71, bytes.fromhex("020801"))
    assert coordinator.legacy_custom_clean_enabled is True
    coordinator._on_legacy_meta(0x71, bytes.fromhex("020800"))
    assert coordinator.legacy_custom_clean_enabled is False
    # Silence is not "off".
    coordinator._on_legacy_meta(0x71, b"")
    assert coordinator.legacy_custom_clean_enabled is False


@pytest.mark.asyncio
async def test_blob_refetch_keeps_the_newer_live_room_table(mock_hass, mock_login):
    """A download must not revert settings the stream reported after it was written.

    The version token is the object's mtime, so this is a comparison rather than
    a guess — the same rule the zone channels use.
    """
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator._on_legacy_meta(0x70, _LIVE_ROOM_CUSTOM)
    coordinator._on_legacy_meta(0x6A, _LIVE_ROOM_NAMES)
    coordinator._map_storage.last_map_version = "1000:layout/lay.bin"  # long stale

    fresh = _blob_map_data()
    tuya_map = MagicMock()
    tuya_map.custom_clean_enabled = False
    tuya_map.as_entity_rooms.return_value = [
        {"id": 1, "name": "Old Name", "fan_speed": -1, "water_level": -1,
         "clean_times": 0, "clean_order": 0},
    ]
    coordinator._map_storage.async_fetch_map.return_value = tuya_map
    mock_hass.async_add_executor_job = AsyncMock(return_value=fresh)

    assert await coordinator.async_refresh_legacy_map() is True
    rooms = _six_rooms(coordinator)
    assert rooms[1]["name"] == "Lounge"
    assert rooms[1]["fan_speed"] == 2


@pytest.mark.asyncio
async def test_a_newer_blob_wins_over_the_live_room_table(mock_hass, mock_login):
    """An edit made in the app while we were not listening must not be overridden.

    The blob is written after that edit; our stream copy predates it. "Always
    prefer the stream" would resurrect the old settings here.
    """
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator._on_legacy_meta(0x70, _LIVE_ROOM_CUSTOM)
    coordinator._legacy_rooms_ts = 1000.0
    coordinator._map_storage.last_map_version = "2000000000:layout/lay.bin"

    fresh = _blob_map_data()
    tuya_map = MagicMock()
    tuya_map.custom_clean_enabled = True
    tuya_map.as_entity_rooms.return_value = [
        {"id": 1, "name": "Living Room", "fan_speed": 0, "water_level": 0,
         "clean_times": 0, "clean_order": 0},
    ]
    coordinator._map_storage.async_fetch_map.return_value = tuya_map
    mock_hass.async_add_executor_job = AsyncMock(return_value=fresh)

    assert await coordinator.async_refresh_legacy_map() is True
    assert coordinator.data.rooms == tuya_map.as_entity_rooms.return_value
    assert coordinator.legacy_custom_clean_enabled is True


@pytest.mark.asyncio
async def test_startup_skips_the_download_when_the_version_matches(
    mock_hass, mock_login
):
    """A restored map that storage says is unchanged costs no blob download."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator._map_version = "v1"
    coordinator.data = replace(coordinator.data, rooms=[{"id": 0, "name": "Hallway"}])
    coordinator._map_storage.async_map_version.return_value = "v1"
    coordinator.async_refresh_legacy_map = AsyncMock()

    assert await coordinator.async_ensure_legacy_map() is True
    coordinator.async_refresh_legacy_map.assert_not_called()
    coordinator._map_storage.async_fetch_map.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["v2", None])
async def test_startup_downloads_when_the_version_moved_or_is_unknown(
    mock_hass, mock_login, version
):
    """None means "could not tell", which must never pass as "unchanged"."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator._map_version = "v1"
    coordinator.data = replace(coordinator.data, rooms=[{"id": 0, "name": "Hallway"}])
    coordinator._map_storage.async_map_version.return_value = version
    coordinator.async_refresh_legacy_map = AsyncMock(return_value=True)

    assert await coordinator.async_ensure_legacy_map() is True
    coordinator.async_refresh_legacy_map.assert_awaited_once()


@pytest.mark.asyncio
async def test_startup_without_a_restored_map_downloads(mock_hass, mock_login):
    """Nothing to compare against — go straight to the blob."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, None)
    coordinator.async_refresh_legacy_map = AsyncMock(return_value=True)
    assert await coordinator.async_ensure_legacy_map() is True
    coordinator.async_refresh_legacy_map.assert_awaited_once()
    coordinator._map_storage.async_map_version.assert_not_called()


@pytest.mark.asyncio
async def test_first_cid_after_a_startup_fetch_does_not_refetch(
    mock_hass, mock_login
):
    """The startup fetch runs before DPS 125, so the first cid names what we hold."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    tuya_map = MagicMock()
    tuya_map.as_entity_rooms.return_value = []
    coordinator._map_storage.async_fetch_map.return_value = tuya_map
    mock_hass.async_add_executor_job = AsyncMock(return_value=_blob_map_data())

    await coordinator.async_refresh_legacy_map()
    assert coordinator._adopt_next_map_cid is True

    mock_hass.async_create_task = MagicMock()
    coordinator._maybe_refresh_legacy_map(VacuumState(map_id=7))
    mock_hass.async_create_task.assert_not_called()
    assert coordinator._fetched_map_cid == 7

    # A later, genuinely different cid still re-fetches.
    coordinator._maybe_refresh_legacy_map(VacuumState(map_id=8))
    mock_hass.async_create_task.assert_called_once()
    mock_hass.async_create_task.call_args[0][0].close()  # never scheduled here


def test_a_cid_seen_before_storage_is_read_does_not_refetch(mock_hass, mock_login):
    """The constructor parses DPS 125 before .storage says which map we hold.

    Acting on that cid re-downloaded a blob already on disk: every cid looks new
    when ``_fetched_map_cid`` has not been restored yet.
    """
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator._storage_loaded = False
    mock_hass.async_create_task = MagicMock()

    coordinator._maybe_refresh_legacy_map(VacuumState(map_id=451))
    mock_hass.async_create_task.assert_not_called()

    coordinator._storage_loaded = True
    coordinator._maybe_refresh_legacy_map(VacuumState(map_id=451))
    mock_hass.async_create_task.assert_called_once()
    mock_hass.async_create_task.call_args[0][0].close()  # never scheduled here


@pytest.mark.asyncio
async def test_startup_downloads_when_the_device_changed_map(mock_hass, mock_login):
    """A cid that moved while we were down is a real change the token cannot see.

    ``async_map_version`` answers "was the newest object rewritten?", which is a
    different question from "is this still the map we hold?".
    """
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator._map_version = "v1"
    coordinator._fetched_map_cid = 451
    coordinator.data = replace(
        coordinator.data, map_id=452, rooms=[{"id": 0, "name": "Hallway"}]
    )
    coordinator.async_refresh_legacy_map = AsyncMock(return_value=True)

    assert await coordinator.async_ensure_legacy_map() is True
    coordinator.async_refresh_legacy_map.assert_awaited_once()
    coordinator._map_storage.async_map_version.assert_not_called()


@pytest.mark.asyncio
async def test_the_pose_dock_survives_a_download_free_restart(mock_hass, mock_login):
    """A restart that skips the blob must still be able to place the robot.

    ``_legacy_pose_to_pixel`` reads ``MapData.dock_pixel``; persisting it keeps the
    dot and trail when the blob download is skipped.
    """
    md = _blob_map_data()
    md.dock_pixel = (47, 78)
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, md)
    coordinator._dock_pixel = (47, 78)
    coordinator._store = MagicMock()
    coordinator._store.async_load = AsyncMock(return_value={})
    coordinator._store.async_save = AsyncMock()
    await coordinator._async_save_map_state()
    saved = coordinator._store.async_save.await_args[0][0]
    assert saved["map_data"]["dock_pixel"] == [47, 78]

    restored = _legacy_map_coordinator(mock_hass, mock_login, None)
    restored._store = MagicMock()
    restored._store.async_load = AsyncMock(return_value=saved)
    await restored.async_load_storage()
    assert restored._map_data.dock_pixel == (47, 78)
    assert restored._legacy_pose_to_pixel(-256, -565) is not None


@pytest.mark.asyncio
async def test_a_pre_dock_pixel_document_is_healed_on_restore(mock_hass, mock_login):
    """Documents written before dock_pixel was persisted still place the robot."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, None)
    coordinator._store = MagicMock()
    md = _blob_map_data()
    md.dock_pixel = (47, 78)
    seed = _legacy_map_coordinator(mock_hass, mock_login, md)
    seed._dock_pixel = (47, 78)
    seed._store = MagicMock()
    seed._store.async_load = AsyncMock(return_value={})
    seed._store.async_save = AsyncMock()
    await seed._async_save_map_state()
    doc = seed._store.async_save.await_args[0][0]
    doc["map_data"].pop("dock_pixel")  # as an older build wrote it

    coordinator._store.async_load = AsyncMock(return_value=doc)
    await coordinator.async_load_storage()
    assert coordinator._map_data.dock_pixel == (47, 78)


@pytest.mark.asyncio
async def test_the_room_list_survives_a_download_free_restart(mock_hass, mock_login):
    """No room list means no selectable rooms: the card resolves taps against it."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator.data = replace(coordinator.data, rooms=[
        {"id": 0, "name": "Hallway", "fan_speed": -1, "water_level": -1,
         "clean_times": 0},
    ])
    coordinator._store = MagicMock()
    coordinator._store.async_load = AsyncMock(return_value={})
    coordinator._store.async_save = AsyncMock()
    await coordinator._async_save_map_state()
    saved = coordinator._store.async_save.await_args[0][0]
    assert saved["rooms"][0]["name"] == "Hallway"

    restored = _legacy_map_coordinator(mock_hass, mock_login, None)
    restored._store = MagicMock()
    restored._store.async_load = AsyncMock(return_value=saved)
    await restored.async_load_storage()
    assert [r["id"] for r in restored.data.rooms] == [0]


@pytest.mark.asyncio
async def test_startup_downloads_when_there_is_no_room_list(mock_hass, mock_login):
    """An unchanged map is not enough — without rooms nothing is selectable."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator._map_version = "v1"
    coordinator._fetched_map_cid = 451
    coordinator.data = replace(coordinator.data, map_id=451, rooms=[])
    coordinator.async_refresh_legacy_map = AsyncMock(return_value=True)

    assert await coordinator.async_ensure_legacy_map() is True
    coordinator.async_refresh_legacy_map.assert_awaited_once()
    coordinator._map_storage.async_map_version.assert_not_called()


@pytest.mark.asyncio
async def test_map_change_detection_survives_a_restart(mock_hass, mock_login):
    """The version token, the cid and the room outlines are persisted."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator._map_version = "v1"
    coordinator._fetched_map_cid = 7
    coordinator._legacy_room_polygons = {0: [(0, 0), (100, 0), (100, 100)]}
    coordinator._store = MagicMock()
    coordinator._store.async_load = AsyncMock(return_value={})
    coordinator._store.async_save = AsyncMock()

    await coordinator._async_save_map_state()
    saved = coordinator._store.async_save.await_args[0][0]
    assert saved["map_version"] == "v1"
    assert saved["fetched_map_cid"] == 7

    restored = _legacy_map_coordinator(mock_hass, mock_login, None)
    restored._store = MagicMock()
    restored._store.async_load = AsyncMock(return_value=saved)
    await restored.async_load_storage()

    assert restored._storage_loaded is True
    assert restored._map_version == "v1"
    assert restored._fetched_map_cid == 7
    assert restored._legacy_room_polygons == {0: [(0, 0), (100, 0), (100, 100)]}
    # And the restored map carries the outlines the blob never had.
    assert list(restored._map_data.room_polygons) == [0]


# --- the map frame: live coordinates vs the grid we hold ----------------------
#
# Live m/m/i coordinates are offsets from the DEVICE's current map origin, and
# that origin moves whenever SLAM grows the map, while the grid we render comes
# from a cloud blob that lags it by minutes to hours. Reading one frame's numbers
# as the other's cells slid the dock — and with it every pose and trail point
# placed off it (_legacy_pose_to_pixel) — by the whole growth.
#
# The numbers below are the two frames this T2266 actually held, either side of
# one real growth event:
#
#   before  150 x 215, origin (520, 1350), dock 0.5 cm (472, 1358) -> cell (47, 78)
#   after   207 x 214, origin (1090, 1350), dock 0.5 cm (1043, 1356) -> cell (104, 77)
#
# The "before" frame is the one this file's own _blob_map_data fixture was
# written against; the "after" is a live 0x64 frame. Width +57, origin_x +570
# and dock_x +571 move together, so
# all 57 columns were added on the LEFT; origin_y is unchanged and the height lost
# a row at the bottom, which is the dock's row stepping 78 -> 77.
#
# Read in the old grid, the new frame's dock_x lands on column 104 of 150 — two
# thirds of the way across, in the wrong room. That is what the screenshots of the
# bug showed, with the trail following it.

_LIVE_PARAM_AFTER_GROWTH = {
    "width": 207, "height": 214, "origin_x": 1090, "origin_y": 1350,
    "dock_x": 1043, "dock_y": 1356,
}


def _grown_map_data():
    """The grid that same growth eventually delivered to us."""
    return MapData(
        raw_pixels=b"", width=207, height=214, origin_x=1090, origin_y=1350,
        resolution=5, dock_pixel=(104, 77),
    )


def test_a_live_dock_quoted_in_a_grown_frame_still_lands_on_our_cell(
    mock_hass, mock_login
):
    """The device grew 57 columns to the left; the dock did not move an inch."""
    md = _blob_map_data()
    md.dock_pixel = (47, 78)
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, md)
    coordinator._dock_pixel = (47, 78)
    coordinator._legacy_map_param = dict(_LIVE_PARAM_AFTER_GROWTH)
    coordinator._legacy_dock_pose = {
        "x": 1043, "y": 1356, "theta": 1579, "type": 2,
    }

    assert coordinator._apply_legacy_dock_pose() is False, "unmoved, so no event"
    assert md.dock_pixel == (47, 78), "read as-is this was column 104 of 150"
    assert coordinator._legacy_live_cell(1043, 1356) == (47, 78)


def test_a_grown_frame_moves_rows_too(mock_hass, mock_login):
    """Rows are stored bottom-up, so growth at the top has to be undone as well."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    # 20 rows added at the top: origin_y and height step together, and the dock's
    # offset from the top-left grows with them while its cell does not move.
    coordinator._legacy_map_param = {
        "width": 150, "height": 235, "origin_x": 520, "origin_y": 1550,
        "dock_x": 472, "dock_y": 1558,
    }
    assert coordinator._legacy_live_cell(472, 1558) == (47, 78)


def test_a_dock_that_teleports_a_metre_is_refused(mock_hass, mock_login):
    """The frame can move between the 0x64 that announces it and the next 0x75.

    A charging dock does not move while the robot cleans around it, so the jump is
    read as the frame skew it is rather than re-anchoring the whole map on it.
    """
    md = _blob_map_data()
    md.dock_pixel = (47, 78)
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, md)
    coordinator._dock_pixel = (47, 78)
    # The stream has already placed the dock once, so there is a live baseline to
    # judge the next one against. The blob's copy is not one — that is the stale
    # value 0x75 exists to correct, and the test above lets it move anywhere.
    coordinator._legacy_dock_cell = (47, 78)
    coordinator._legacy_dock_pose = {"x": 1043, "y": 1356, "theta": 0, "type": 2}

    assert coordinator._apply_legacy_dock_pose() is False
    assert md.dock_pixel == (47, 78)
    assert coordinator._dock_pixel == (47, 78)


def test_a_dock_that_creeps_is_still_accepted(mock_hass, mock_login):
    """SLAM refines the dock by a cell or two; that is what 0x75 is for."""
    md = _blob_map_data()
    md.dock_pixel = (47, 78)
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, md)
    coordinator._legacy_dock_cell = (47, 78)
    coordinator._legacy_dock_pose = {"x": 492, "y": 1378, "theta": 0, "type": 2}

    assert coordinator._apply_legacy_dock_pose() is True
    assert md.dock_pixel == (49, 76)


def test_a_grown_map_carries_the_live_trail_with_it(mock_hass, mock_login):
    """A re-fetched map that gained columns re-indexes every cell we hold.

    Without this the points keep their old columns and strand themselves 57 cells
    west of the rooms they were driven in — the block of sweeps the bug drew
    outside the map, over blank grid.
    """
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator._robot_trail = [(47, 78), (30, 90), (31.5, 91.0)]
    coordinator._robot_trail_types = [1, 0, 0]
    coordinator._previous_trail = [(50, 50)]
    coordinator._robot_pixel = (31.5, 91.0)
    coordinator._dock_pixel = (47, 78)
    coordinator._legacy_dock_cell = (47, 78)
    coordinator._notify_map_trail_reset = MagicMock()

    coordinator._set_map_data(_grown_map_data())

    # +57 columns, -1 row: the dock point lands on the cell the grown map itself
    # reports for the dock, which is the check that the arithmetic is the map's.
    assert coordinator._robot_trail == [(104, 77), (87, 89), (88.5, 90.0)]
    assert coordinator._robot_trail_types == [1, 0, 0]
    assert coordinator._previous_trail == [(107, 49)]
    assert coordinator._robot_pixel == (88.5, 90.0)
    assert coordinator._dock_pixel == (104, 77) == coordinator._map_data.dock_pixel
    assert coordinator._legacy_dock_cell == (104, 77)
    # Subscribers hold the old frame's points, so they get the whole list again.
    coordinator._notify_map_trail_reset.assert_called_once()


def test_reprojected_points_that_fall_off_the_new_grid_are_dropped(
    mock_hass, mock_login
):
    """A map can lose ground as well; a point with nowhere to go leaves a gap,
    and the renderers already decline to draw a line across one."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _grown_map_data())
    coordinator._robot_trail = [(5, 77), (104, 77)]
    coordinator._robot_trail_types = [0, 1]

    # The mirror of the growth above: 57 columns given back to the left.
    coordinator._set_map_data(_blob_map_data())
    assert coordinator._robot_trail == [(47, 78)]
    assert coordinator._robot_trail_types == [1]


def test_an_unmoved_frame_leaves_the_trail_alone(mock_hass, mock_login):
    """The common case is a re-fetch of the same extents, which must cost nothing."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator._robot_trail = [(47, 78)]
    coordinator._set_map_data(_blob_map_data())
    assert coordinator._robot_trail == [(47, 78)]


def test_the_novel_path_is_never_reprojected(mock_hass, mock_login):
    """Novel maps measure their origin in centimetres off a world pose and are not
    row-flipped, so the legacy arithmetic would shear their trail, not move it."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator.api_type = "novel"
    coordinator._robot_trail = [(47, 78)]
    coordinator._set_map_data(_grown_map_data())
    assert coordinator._robot_trail == [(47, 78)]


# --- the divergence between the device's grid and ours ------------------------
#
# The device rewrites the blob only while parked, so a mid-clean download returns
# the grid already held. Live coordinates are frame-differenced
# (_legacy_live_cell), so the divergence is survivable until the clean ends.


def _diverged_param():
    """The live 0x64 from the growth in the frame tests above."""
    return dict(_LIVE_PARAM_AFTER_GROWTH)


def test_a_mismatch_is_recorded_and_fetched_during_a_clean_too(mock_hass, mock_login):
    """The device writes its map object at the START of a run, so it is worth having.

    The device rewrites its map object at the start of a run (within seconds), so
    the download is not deferred to the end.
    """
    for activity in ("cleaning", "returning", "paused", "docked"):
        coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
        mock_hass.async_create_task = MagicMock()
        coordinator.data = replace(coordinator.data, activity=activity)
        coordinator._legacy_map_param = _diverged_param()

        assert coordinator._check_legacy_map_param() is True, activity
        mock_hass.async_create_task.assert_called_once()
        mock_hass.async_create_task.call_args[0][0].close()
        assert coordinator._map_frame_divergence == (207, 214, 1090, 1350), (
            "...and it is remembered, so diagnostics says so and the post-clean"
            " check knows to try again if this fetch came back still stale"
        )


def test_installing_the_matching_grid_clears_the_divergence(mock_hass, mock_login):
    """A parked robot sends no 0x64, so nothing else would ever clear it."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator._legacy_map_param = _diverged_param()
    coordinator._map_frame_divergence = (207, 214, 1090, 1350)

    coordinator._set_map_data(_grown_map_data())
    assert coordinator._map_frame_divergence is None

    # ...and a grid that still does not match leaves it standing.
    coordinator._set_map_data(_blob_map_data())
    assert coordinator._map_frame_divergence == (207, 214, 1090, 1350)


def test_frames_agreeing_again_clears_the_divergence(mock_hass, mock_login):
    """The re-fetch landed; nothing is outstanding any more."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _grown_map_data())
    coordinator._map_frame_divergence = (150, 215, 520, 1350)
    coordinator._legacy_map_param = _diverged_param()

    assert coordinator._check_legacy_map_param() is False
    assert coordinator._map_frame_divergence is None


@pytest.mark.asyncio
async def test_the_post_clean_check_fetches_while_the_frame_is_diverged(
    mock_hass, mock_login
):
    """"Unchanged" from the listing does not make our grid the right shape."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator.data = replace(coordinator.data, activity="docked")
    coordinator._map_version = "v1"
    coordinator._map_storage.async_map_version.return_value = "v1"  # unchanged
    coordinator.async_refresh_legacy_map = AsyncMock(return_value=True)

    # Without a divergence an unchanged token means no download, as before.
    await coordinator._async_legacy_map_freshness()
    coordinator.async_refresh_legacy_map.assert_not_awaited()

    coordinator._map_frame_divergence = (207, 214, 1090, 1350)
    await coordinator._async_legacy_map_freshness()
    coordinator.async_refresh_legacy_map.assert_awaited_once()


# --- points the grid we hold cannot fit ---------------------------------------
#
# Points off our grid are kept in the device frame (dock-relative) and placed once
# the grid grows.


def _cleaning_coordinator(map_data):
    coordinator = _coordinator_with_map(MagicMock(), MagicMock(), map_data)
    coordinator.api_type = "legacy"
    coordinator._rerender_map = MagicMock()
    coordinator.data = replace(coordinator.data, activity="cleaning")
    return coordinator


def test_points_off_the_held_grid_are_kept_and_placed_by_the_next_map(
    mock_hass, mock_login
):
    """The whole point of item 12: they come back instead of being lost."""
    md = _blob_map_data()
    md.dock_pixel = (47, 78)
    coordinator = _cleaning_coordinator(md)

    # The robot drives west out of the grid we hold. Placement is the dock cell
    # plus _LEGACY_POSE_DOCK_OFFSET plus x/10, so on this 150-wide map the dock
    # column is 51 and x = -700 is column -19: off the grid, undrawable. Each step
    # is inside the jump gate, so nothing here is rejected for any other reason.
    coordinator._on_legacy_trail(
        1, [(0, 0, 0), (-400, 0, 0), (-700, 0, 1), (-400, 0, 0)]
    )
    assert [c for c, _ in coordinator._robot_trail] == [51, 11, 11], (
        "the point outside the grid cannot be drawn"
    )
    assert len(coordinator._robot_trail_raw) == 4, "...but it is not thrown away"
    assert coordinator._trail_unplaced == 1, "and diagnostics says one did not fit"

    coordinator._set_map_data(_grown_map_data())
    # 57 columns further left now exist, so the same four points all place — and
    # they are placed from raw against the new dock, not translated.
    assert [c for c, _ in coordinator._robot_trail] == [108, 68, 38, 68]
    assert coordinator._robot_trail_types == [0, 0, 1, 0], "with its own type, in order"
    assert coordinator._trail_unplaced == 0, "nothing is off-grid any more"


def test_a_grown_map_re_places_the_trail_rather_than_shifting_it(
    mock_hass, mock_login
):
    """Same answer as the translation, arrived at without accumulating rounding."""
    md = _blob_map_data()
    md.dock_pixel = (47, 78)
    coordinator = _cleaning_coordinator(md)
    coordinator._on_legacy_trail(1, [(0, 0, 1), (50, 50, 0)])
    before = list(coordinator._robot_trail)

    coordinator._set_map_data(_grown_map_data())
    assert coordinator._robot_trail == [(c + 57, r - 1) for c, r in before]
    assert coordinator._robot_trail_types == [1, 0]


def test_a_live_dock_after_trail_points_re_places_the_trail(mock_hass, mock_login):
    """The trail hangs off the dock: the first 0x75 moves both."""
    md = _blob_map_data()
    md.dock_pixel = (10, 10)  # the blob's stale copy
    coordinator = _cleaning_coordinator(md)
    coordinator._on_legacy_trail(1, [(0, 0, 1), (50, 50, 0)])
    coordinator._legacy_dock_pose = {"x": 472, "y": 1358, "theta": 0, "type": 1}
    coordinator._notify_map_trail_reset = MagicMock()

    assert coordinator._apply_legacy_dock_pose() is True

    assert coordinator._robot_trail == [
        coordinator._legacy_pose_to_pixel(0, 0),
        coordinator._legacy_pose_to_pixel(50, 50),
    ]
    assert coordinator._robot_trail_types == [1, 0]
    # subscribers hold the old placement
    coordinator._notify_map_trail_reset.assert_called_once()


@pytest.mark.asyncio
async def test_a_refetch_after_growth_places_the_trail_against_the_live_dock(
    mock_hass, mock_login
):
    """The grown blob's dock copy is as stale as the first one; the trail follows
    the live dock, not the blob's."""
    md = _blob_map_data()
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, md)
    coordinator._legacy_map_param = {
        "width": 150, "height": 215, "origin_x": 520, "origin_y": 1350,
    }
    coordinator._legacy_dock_pose = {"x": 472, "y": 1358, "theta": 0, "type": 1}
    coordinator._apply_legacy_dock_pose()
    coordinator.data = replace(coordinator.data, activity="cleaning")
    coordinator._on_legacy_trail(1, [(0, 0, 0), (10, 0, 0)])
    # The device's map grew 57 columns to the left; 0x64/0x75 quote the new frame.
    coordinator._legacy_map_param = {
        "width": 207, "height": 215, "origin_x": 1090, "origin_y": 1350,
    }
    coordinator._legacy_dock_pose = {"x": 1042, "y": 1358, "theta": 0, "type": 1}
    grown = MapData(
        raw_pixels=b"", width=207, height=215, origin_x=1090, origin_y=1350,
        resolution=5, dock_pixel=(60, 60),  # stale
    )
    tuya_map = MagicMock()
    tuya_map.as_entity_rooms.return_value = []
    coordinator._map_storage.async_fetch_map.return_value = tuya_map
    mock_hass.async_add_executor_job = AsyncMock(return_value=grown)

    assert await coordinator.async_refresh_legacy_map() is True

    assert grown.dock_pixel == (104, 78)
    assert coordinator._robot_trail == [
        coordinator._legacy_pose_to_pixel(0, 0),
        coordinator._legacy_pose_to_pixel(10, 0),
    ]


def test_a_new_session_drops_the_raw_points_too(mock_hass, mock_login):
    """Otherwise the next clean re-places the previous one's whole path."""
    md = _blob_map_data()
    md.dock_pixel = (47, 78)
    coordinator = _cleaning_coordinator(md)
    coordinator._on_legacy_trail(1, [(0, 0, 0)])
    coordinator._clear_trail()
    assert coordinator._robot_trail_raw == []
    coordinator._set_map_data(_grown_map_data())
    assert coordinator._robot_trail == []


async def test_a_moving_robot_still_saves_the_map_state_within_the_delay(
    hass, hass_storage, mock_login
):
    """A render every 2 s must not hold the write off until the clean ends.

    Runs HA's real Store: a crash mid-clean otherwise loses the whole session.
    """
    coordinator = EufyCleanCoordinator(
        hass, mock_login,
        {"deviceId": "dev1", "deviceModel": "T2118", "deviceName": "Test Vac"},
    )
    await coordinator.async_load_storage()
    coordinator._map_data = MapData(
        raw_pixels=b"\x00" * 4, width=4, height=4, origin_x=0, origin_y=0,
        resolution=5,
    )
    key = f"robovac_mqtt.{_safe_storage_key('dev1')}"
    start = dt_util.utcnow()
    writes: list[int] = []  # seconds into the clean at which a write landed
    for tick in range(1, 40):
        coordinator._robot_trail = [(1, 1)] * tick
        coordinator._rerender_map()
        async_fire_time_changed(hass, start + timedelta(seconds=2 * tick))
        await hass.async_block_till_done()
        stored = hass_storage.get(key, {}).get("data", {}).get("robot_trail", [])
        if len(stored) == tick:
            writes.append(2 * tick)

    assert writes, "nothing was written while the robot moved"
    # Every write re-arms the next: the gap never exceeds the delay.
    gaps = [b - a for a, b in zip([0, *writes], writes)]
    assert len(writes) >= 2 and max(gaps) <= _MAP_STATE_SAVE_DELAY + 2, writes
    await coordinator.async_teardown()


@pytest.mark.asyncio
async def test_cleared_trail_and_dock_state_does_not_come_back_from_storage():
    """A restart before the new clean's first point must not bring the old path back.

    The document is shared and long-lived, so a key left out when its value
    is cleared restores the previous value.
    """
    md = _blob_map_data()
    md.dock_pixel = (47, 78)
    coordinator = _cleaning_coordinator(md)
    coordinator._store = MagicMock()
    coordinator._store.async_load = AsyncMock(return_value={})
    coordinator._store.async_save = AsyncMock()
    coordinator._on_legacy_trail(1, [(0, 0, 0), (50, 50, 0), (100, 50, 0)])
    coordinator._previous_trail = [(1, 1), (2, 2)]
    coordinator._dock_pixel = (47, 78)
    coordinator._map_version = "1700000000:/blob"
    await coordinator._async_save_map_state()
    # The next clean starts: the trail is just the dock cell, no raw point yet.
    coordinator._clear_trail()
    coordinator._append_trail_point((47, 78))
    # A grown map dropped the old run and the dock cell; a fetch had no version.
    coordinator._previous_trail = []
    coordinator._dock_pixel = None
    coordinator._map_version = None
    await coordinator._async_save_map_state()
    saved = coordinator._store.async_save.await_args[0][0]

    restored = _cleaning_coordinator(None)
    restored._store = MagicMock()
    restored._store.async_load = AsyncMock(return_value=saved)
    await restored.async_load_storage()

    assert restored._robot_trail == [(47, 78)]
    assert restored._robot_trail_raw == []
    assert restored._previous_trail == []
    assert restored._dock_pixel is None
    assert restored._map_version is None


# ---------------------------------------------------------------------------
# async_set_room_configs — the one path allowed to write legacy customRooms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_map_operation_leaves_rooms_and_zones_as_they_were(
    mock_hass, mock_login
):
    """Nothing reached the robot, so nothing may claim it did."""
    coordinator, md = _legacy_coordinator_with_geometry(mock_hass, mock_login)
    rooms = [{"id": 0, "name": "Hallway", "fan_speed": -1, "water_level": -1,
              "clean_times": 0}]
    coordinator.data = replace(coordinator.data, rooms=rooms, map_id=3)
    coordinator.tuya_schema = None
    coordinator.build_device_command = MagicMock(return_value={"124": "x"})
    coordinator.async_send_command = AsyncMock(side_effect=HomeAssistantError("down"))
    zones = [list(z) for z in md.forbidden_zones]

    with pytest.raises(HomeAssistantError):
        await coordinator.async_set_room_config(0, fan_speed="Max")
    with pytest.raises(HomeAssistantError):
        await coordinator.async_set_nogo_zones(remove_forbidden=[0])

    assert coordinator.data.rooms == rooms
    assert md.forbidden_zones == zones
    assert not coordinator._legacy_live_geometry, "no zone edit was stamped"


def _legacy_room_coordinator(mock_hass, mock_login, rooms):
    coordinator = _coordinator_with_map(mock_hass, mock_login, None)
    coordinator.api_type = "legacy"
    coordinator.tuya_schema = None
    coordinator.data = replace(coordinator.data, rooms=rooms, map_id=3)
    coordinator.async_send_command = AsyncMock()
    return coordinator


async def test_set_room_configs_resends_every_room_that_has_an_override(
    mock_hass, mock_login
):
    """customRooms is replace-all, so the document must carry the untouched rooms.

    Room 0 is the one being changed; room 1 already carries an override and has
    to be resent verbatim or the write erases it; room 2 has none and is left
    off, which is what keeps it on the general settings.
    """
    coordinator = _legacy_room_coordinator(
        mock_hass,
        mock_login,
        [
            {"id": 0, "fan_speed": -1, "water_level": -1, "clean_times": 0},
            {"id": 1, "fan_speed": 0, "water_level": 2, "clean_times": 3},
            {"id": 2, "fan_speed": -1, "water_level": -1, "clean_times": 0},
        ],
    )

    assert await coordinator.async_set_room_configs({0: {"fan_speed": "Max"}})

    (payload,), _ = coordinator.async_send_command.call_args
    doc = json.loads(base64.b64decode(payload["124"]))
    assert doc["method"] == "customRooms"
    assert [p["roomId"] for p in doc["data"]["property"]] == [0, 1]


async def test_set_room_configs_uses_the_map_id_override(mock_hass, mock_login):
    """The options-flow override applies here as it does to room cleans."""
    coordinator = _legacy_room_coordinator(
        mock_hass, mock_login, [{"id": 0, "fan_speed": -1, "water_level": -1, "clean_times": 0}]
    )
    coordinator.map_id_overrides = {3: 7}

    assert await coordinator.async_set_room_configs({0: {"fan_speed": "Max"}})

    (payload,), _ = coordinator.async_send_command.call_args
    doc = json.loads(base64.b64decode(payload["124"]))
    assert doc["data"]["mapId"] == 7


async def test_set_room_configs_applies_optimistically_to_data_rooms(
    mock_hass, mock_login
):
    """The entities must reflect the change before the next map refresh."""
    coordinator = _legacy_room_coordinator(
        mock_hass, mock_login, [{"id": 0, "fan_speed": -1, "water_level": -1, "clean_times": 0}]
    )

    assert await coordinator.async_set_room_configs({0: {"clean_times": 2}})

    assert coordinator.data.rooms[0]["clean_times"] == 2


async def test_set_room_configs_without_a_room_list_is_a_no_op(mock_hass, mock_login):
    """No parsed rooms means no way to build a complete document — so don't."""
    coordinator = _legacy_room_coordinator(mock_hass, mock_login, [])

    assert await coordinator.async_set_room_configs({0: {"fan_speed": "Max"}}) is False
    coordinator.async_send_command.assert_not_awaited()


# ---------------------------------------------------------------------------
# async_refresh_legacy_map — what a download must not undo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_refetch_puts_the_live_dock_back_over_the_blob_copy(
    mock_hass, mock_login
):
    """The blob's dock goes stale while the SLAM estimate moves.

    It matters more than any other single value because **the pose transform
    hangs off dock_pixel** — reverting it to the download's copy moves the dock
    marker, the robot dot and every re-projected trail point by the stale
    offset, and 0x75 only arrives while the robot is publishing, so nothing puts
    it back until the next clean.
    """
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator._legacy_dock_pose = {"x": 472, "y": 1358, "theta": 0, "type": 1}

    fresh = _blob_map_data()
    fresh.dock_pixel = (10, 10)  # the blob's stale copy
    tuya_map = MagicMock()
    tuya_map.as_entity_rooms.return_value = []
    coordinator._map_storage.async_fetch_map.return_value = tuya_map
    mock_hass.async_add_executor_job = AsyncMock(return_value=fresh)

    assert await coordinator.async_refresh_legacy_map() is True
    assert fresh.dock_pixel == (47, 78)
    assert coordinator._dock_pixel == (47, 78)


@pytest.mark.asyncio
async def test_a_refetch_publishes_geometry_after_the_live_carry_overs(
    mock_hass, mock_login
):
    """The LAST geometry event must describe the map the client will be served.

    _set_map_data notifies as it installs, which is BEFORE the carry-overs put
    the live zones and room table back — so the event a client acted on
    described a map with a zone the user had already deleted, and with the robot
    parked no further m/m/i frame was coming to correct it.
    """
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    coordinator.remember_live_restricted_geometry(0x68, [])

    fresh = _blob_map_data()
    fresh.forbidden_zones = [[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]]
    tuya_map = MagicMock()
    tuya_map.as_entity_rooms.return_value = []
    coordinator._map_storage.async_fetch_map.return_value = tuya_map
    coordinator._map_storage.last_map_version = f"{time.time() - 600:.0f}:/blob"
    mock_hass.async_add_executor_job = AsyncMock(return_value=fresh)

    # What the map looked like at each notification.
    snapshots: list[list] = []
    real_notify = coordinator._notify_map_geometry

    def _record():
        md = coordinator._map_data
        snapshots.append([] if md is None else list(md.forbidden_zones))
        real_notify()

    coordinator._notify_map_geometry = _record

    assert await coordinator.async_refresh_legacy_map() is True

    assert snapshots, "the refresh published no geometry at all"
    assert snapshots[-1] == [], "the last event still described the deleted zone"


@pytest.mark.asyncio
async def test_two_concurrent_refreshes_do_not_interleave(mock_hass, mock_login):
    """The guard has to span the INSTALL, not just the download.

    An 0x64 re-map and a fresh DPS-125 cid arrive together. With the guard
    released after the fetch, the two installs interleaved across the executor
    decode and the older blob could land last while _map_version described the
    newer one — after which _reproject_legacy_live_cells shifts the trail by the
    wrong frame delta.
    """
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, _blob_map_data())
    tuya_map = MagicMock()
    tuya_map.as_entity_rooms.return_value = []

    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_fetch(*_a, **_kw):
        started.set()
        await release.wait()
        return tuya_map

    coordinator._map_storage.async_fetch_map = _slow_fetch
    mock_hass.async_add_executor_job = AsyncMock(side_effect=lambda *_a: _blob_map_data())

    first = asyncio.ensure_future(coordinator.async_refresh_legacy_map())
    await started.wait()
    # Second trigger while the first is still inside the fetch/decode: refused.
    assert await coordinator.async_refresh_legacy_map() is False
    release.set()
    assert await first is True
    assert coordinator._map_refresh_in_progress is False


# ---------------------------------------------------------------------------
# async_load_storage — the "not read yet" window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_storage_is_only_marked_loaded_once_it_really_is(
    mock_hass, mock_login
):
    """A cid arriving mid-load must not re-download a blob already on disk.

    _storage_loaded gates _maybe_refresh_legacy_map precisely because the
    identity of the map we hold lives in .storage. Setting it before the await
    left a window where the flag said "known" and _fetched_map_cid said None.
    """
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, None)
    coordinator._storage_loaded = False
    seen: list[bool] = []

    async def _slow_load():
        seen.append(coordinator._storage_loaded)
        return {}

    coordinator._store.async_load = _slow_load

    await coordinator.async_load_storage()

    assert seen == [False]
    assert coordinator._storage_loaded is True


@pytest.mark.asyncio
async def test_a_failed_storage_read_still_ends_the_not_yet_window(
    mock_hass, mock_login
):
    """Otherwise one bad read suppresses every later map refresh for the run."""
    coordinator = _legacy_map_coordinator(mock_hass, mock_login, None)
    coordinator._storage_loaded = False
    coordinator._store.async_load = AsyncMock(side_effect=OSError("disk"))

    with pytest.raises(OSError):
        await coordinator.async_load_storage()

    assert coordinator._storage_loaded is True
