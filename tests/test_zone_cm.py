"""Tests for zone and spot cleaning in world centimetres."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError

from custom_components.robovac_mqtt.api.commands import (
    build_command,
    rects_cm_to_quads,
)
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.proto.cloud.control_pb2 import ModeCtrlRequest
from custom_components.robovac_mqtt.utils import decode
from custom_components.robovac_mqtt.vacuum import _ZONE_CM, RoboVacMQTTEntity

# ── rects_cm_to_quads ────────────────────────────────────────────────


def test_rect_becomes_ordered_quad():
    assert rects_cm_to_quads([[250, 100, 100, -50]]) == [
        [(100, -50), (250, -50), (250, 100), (100, 100)]
    ]


def test_explicit_corners_kept():
    corners = [[0, 0], [10, 0], [10, 10], [0, 10]]
    assert rects_cm_to_quads([corners]) == [[(0, 0), (10, 0), (10, 10), (0, 10)]]


def test_bad_zones_skipped():
    assert not rects_cm_to_quads([[1, 2, 3], [5, 5, 5, 9], "nope", [[0, 0], [1, 1]]])


@pytest.mark.parametrize(
    "zone",
    [
        [0, 0, float("nan"), 10],
        [0, 0, float("inf"), 10],
        [0, 0, 3e9, 10],
        [0, 0, 0.4, 0.4],  # rounds to zero area
        [True, 0, 1, 2],
        [[0, 0], [0, 0], [0, 0], [0, 0]],
        [[0, 0], [10, 0], [20, 0], [30, 0]],  # collinear corners
    ],
)
def test_invalid_values_and_zero_area_skipped(zone):
    assert not rects_cm_to_quads([zone])


def test_zones_must_be_a_list():
    assert not rects_cm_to_quads(5)


# ── vacuum entity services ───────────────────────────────────────────


@pytest.fixture(name="coordinator")
def _coordinator():
    c = MagicMock()
    c.device_id = "dev"
    c.device_name = "Test Vacuum"
    c.api_type = "novel"
    c.data = VacuumState()
    c.async_send_command = AsyncMock()
    c.build_device_command = MagicMock(return_value={"152": "x"})
    c.resolve_map_id = MagicMock(return_value=4)
    return c


async def test_async_clean_zone_converts_cm_rects(coordinator):
    await RoboVacMQTTEntity(coordinator).async_clean_zone(
        [[0, 0, 100, 50]], clean_times=2
    )
    coordinator.build_device_command.assert_called_once_with(
        "zone_clean",
        zones_cm=[[(0, 0), (100, 0), (100, 50), (0, 50)]],
        map_id=4,
        clean_times=2,
    )
    coordinator.set_active_cleaning_targets.assert_called_once_with(zone_count=1)
    coordinator.async_send_command.assert_awaited_once()


async def test_async_clean_zone_without_valid_zones_raises(coordinator):
    with pytest.raises(HomeAssistantError):
        await RoboVacMQTTEntity(coordinator).async_clean_zone([[1, 1, 1, 5]])
    coordinator.async_send_command.assert_not_awaited()


async def test_async_clean_spot_at_is_a_square_zone(coordinator):
    await RoboVacMQTTEntity(coordinator).async_clean_spot_at(25, 239, size=100)
    coordinator.build_device_command.assert_called_once_with(
        "zone_clean",
        zones_cm=[[(-25, 189), (75, 189), (75, 289), (-25, 289)]],
        map_id=4,
        clean_times=1,
    )


async def test_send_command_zone_clean_with_cm_zones(coordinator):
    await RoboVacMQTTEntity(coordinator).async_send_command(
        "zone_clean", {"zones_cm": [[0, 0, 10, 10]]}
    )
    assert coordinator.build_device_command.call_args.args[0] == "zone_clean"


async def test_async_clean_zone_needs_a_protobuf_robot(coordinator):
    coordinator.api_type = "legacy"
    with pytest.raises(HomeAssistantError, match="protobuf"):
        await RoboVacMQTTEntity(coordinator).async_clean_zone([[0, 0, 100, 50]])
    coordinator.async_send_command.assert_not_awaited()


async def test_async_clean_zone_sends_nothing_when_no_command_is_built(coordinator):
    coordinator.build_device_command.return_value = None
    await RoboVacMQTTEntity(coordinator).async_clean_zone([[0, 0, 100, 50]])
    coordinator.async_send_command.assert_not_awaited()


async def test_send_command_zones_cm_keeps_map_id_and_clamps_passes(coordinator):
    await RoboVacMQTTEntity(coordinator).async_send_command(
        "zone_clean", {"zones_cm": [[0, 0, 10, 10]], "clean_times": 9, "map_id": 7}
    )
    coordinator.build_device_command.assert_called_once_with(
        "zone_clean",
        zones_cm=[[(0, 0), (10, 0), (10, 10), (0, 10)]],
        map_id=7,
        clean_times=3,
    )


@pytest.mark.parametrize(
    "params",
    [{"zones_cm": 5}, {"zones_cm": [[0, 0, 10, 10]], "clean_times": "two"}],
)
async def test_send_command_zones_cm_rejects_bad_params(coordinator, params):
    with pytest.raises(HomeAssistantError):
        await RoboVacMQTTEntity(coordinator).async_send_command("zone_clean", params)
    coordinator.async_send_command.assert_not_awaited()


async def test_one_rectangle_without_the_outer_list(coordinator):
    await RoboVacMQTTEntity(coordinator).async_clean_zone([0, 0, 100, 50])
    assert coordinator.build_device_command.call_args.kwargs["zones_cm"] == [
        [(0, 0), (100, 0), (100, 50), (0, 50)]
    ]


async def test_spot_errors_name_clean_spot(coordinator):
    with pytest.raises(HomeAssistantError, match="^clean_spot"):
        await RoboVacMQTTEntity(coordinator).async_clean_spot_at(float("nan"), 0)


async def test_zone_clean_end_to_end_protobuf(coordinator):
    """Through the real builder: the robot gets these corners, map and passes."""
    coordinator.build_device_command = MagicMock(side_effect=build_command)
    await RoboVacMQTTEntity(coordinator).async_clean_zone([[-25, 189, 75, 289]], 2)
    value = coordinator.async_send_command.await_args.args[0]["152"]
    req = decode(ModeCtrlRequest, value)
    assert req.method == ModeCtrlRequest.START_SELECT_ZONES_CLEAN
    zones = req.select_zones_clean
    assert zones.map_id == 4 and zones.zones[0].clean_times == 2
    quad = zones.zones[0].quadrangle
    corners = [(p.x, p.y) for p in (quad.p0, quad.p1, quad.p2, quad.p3)]
    assert sorted(corners) == sorted([(-25, 189), (75, 189), (75, 289), (-25, 289)])


@pytest.mark.parametrize("bad", ["nan", "inf", 2e5, -2e5])
def test_spot_schema_rejects_bad_coordinates(bad):
    with pytest.raises(vol.Invalid):
        _ZONE_CM(bad)


def test_spot_schema_accepts_a_real_coordinate():
    assert _ZONE_CM("25.5") == 25.5
