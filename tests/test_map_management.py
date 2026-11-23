"""Mapping and room-edit commands: builders, services, schemas and the robot's reply."""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError

from custom_components.robovac_mqtt.api import commands as C
from custom_components.robovac_mqtt.api.parser import update_state
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.proto.cloud.control_pb2 import ModeCtrlRequest
from custom_components.robovac_mqtt.proto.cloud.map_edit_pb2 import (
    MapEditRequest,
    MapEditResponse,
)
from custom_components.robovac_mqtt.proto.cloud.multi_maps_pb2 import (
    MultiMapsManageRequest,
)
from custom_components.robovac_mqtt.utils import decode, encode_message
from custom_components.robovac_mqtt.vacuum import _MAP_CM, _ROOM_ID, RoboVacMQTTEntity

# ── builders ─────────────────────────────────────────────────────────


def test_start_mapping():
    req = decode(ModeCtrlRequest, C.build_start_mapping_command()["152"])
    assert req.method == ModeCtrlRequest.START_FAST_MAPPING


def test_map_save():
    req = decode(MultiMapsManageRequest, C.build_map_save_command(7)["172"])
    assert req.method == MultiMapsManageRequest.MAP_SAVE
    assert req.seq == 7 and req.save_options.multi_map_sw.value is True
    # the exact bytes an S1 Pro accepted on 23 Nov 2026
    assert C.build_map_save_command(7) == {"172": "CggFEAcqBAoCCAE="}
    assert C.build_command("map_save", seq=7) == C.build_map_save_command(7)


async def test_save_map_service(coordinator):
    await RoboVacMQTTEntity(coordinator).async_save_map()
    assert "172" in coordinator.async_send_command.await_args.args[0]


def test_rename_room():
    req = decode(MapEditRequest, C.build_rename_room_command(1, 3, " Dining Room ")["170"])
    assert req.method == MapEditRequest.RENAME_ROOM
    assert (req.map_id, req.room_desc.id, req.room_desc.name) == (1, 3, "Dining Room")
    assert not C.build_rename_room_command(1, 3, "  ")


def test_merge_rooms_drops_duplicate_ids():
    req = decode(MapEditRequest, C.build_merge_rooms_command(1, [2, "3", 2])["170"])
    assert req.method == MapEditRequest.MERGE_ROOMS
    assert list(req.merge_rooms.room_ids) == [2, 3]
    assert not C.build_merge_rooms_command(1, [2, 2])


def test_divide_room_needs_two_different_points():
    cmd = C.build_divide_room_command(1, 2, [(0, 0), (100.4, -50.6)])
    req = decode(MapEditRequest, cmd["170"])
    assert req.method == MapEditRequest.DIVIDE_ROOM
    assert req.divide_room.room_id == 2
    assert [(p.x, p.y) for p in req.divide_room.points] == [(0, 0), (100, -51)]
    assert not C.build_divide_room_command(1, 2, [(0, 0)])
    assert not C.build_divide_room_command(1, 2, [(0, 0), (0.2, 0.3)])
    assert not C.build_divide_room_command(1, 2, [(0, 0), (1, 1), (2, 0)])


@pytest.mark.parametrize(
    ("command", "kwargs"),
    [
        ("rename_room", {"room_id": 1, "name": "x"}),  # no map_id
        ("rename_room", {"map_id": 1, "name": "x"}),  # no room_id
        ("divide_room", {"map_id": 1, "points_cm": [(0, 0), (1, 1)]}),
        ("merge_rooms", {"room_ids": [1, 2]}),
    ],
)
def test_build_command_needs_explicit_ids(command, kwargs):
    assert not C.build_command(command, **kwargs)


# ── the robot's reply (on the request DP, 170) ──────────────────────────────────────


def _reply(result, fail=0):
    resp = MapEditResponse(method=MapEditRequest.MERGE_ROOMS, result=result)
    resp.fail_code.value = fail
    return {"170": encode_message(resp)}


def test_rejected_edit_is_logged_as_a_warning(caplog):
    with caplog.at_level(logging.WARNING):
        update_state(VacuumState(), _reply(MapEditResponse.FAILED, 2))
    assert "rejected the map edit MERGE_ROOMS (ROOM_UNADJACENT)" in caplog.text


def test_successful_edit_is_not_a_warning(caplog):
    with caplog.at_level(logging.WARNING):
        update_state(VacuumState(), _reply(MapEditResponse.SUCCESS))
        update_state(VacuumState(), {"170": "not base64!"})
        update_state(VacuumState(), {"170": "AggB"})  # real S1 Pro reply to a divide
    assert "rejected" not in caplog.text


# ── vacuum entity services ───────────────────────────────────────────


@pytest.fixture(name="coordinator")
def _coordinator():
    c = MagicMock()
    c.device_id = "dev"
    c.device_name = "Test Vacuum"
    c.device_model = "T2080A"
    c.api_type = "novel"
    c.data = VacuumState(activity="docked")
    c.async_send_command = AsyncMock()
    c.build_device_command = MagicMock(side_effect=C.build_command)
    c.resolve_map_id = MagicMock(return_value=7)
    return c


async def test_edit_services_target_the_active_map(coordinator):
    vac = RoboVacMQTTEntity(coordinator)
    await vac.async_rename_room(3, "Dining Room")
    await vac.async_merge_rooms([2, 3])
    await vac.async_divide_room(2, [[0, 0], [100, 50]])
    sent = [c.args[0]["170"] for c in coordinator.async_send_command.await_args_list]
    reqs = [decode(MapEditRequest, v) for v in sent]
    assert [r.map_id for r in reqs] == [7, 7, 7]
    assert reqs[0].room_desc.name == "Dining Room"


async def test_start_mapping_on_a_map_less_robot(coordinator):
    await RoboVacMQTTEntity(coordinator).async_start_mapping()
    assert "152" in coordinator.async_send_command.await_args.args[0]


async def test_start_mapping_needs_replace_map_when_rooms_exist(coordinator):
    coordinator.data = VacuumState(activity="docked", rooms=[{"id": 1, "name": "Hall"}])
    vac = RoboVacMQTTEntity(coordinator)
    with pytest.raises(HomeAssistantError, match="replace_map"):
        await vac.async_start_mapping()
    coordinator.async_send_command.assert_not_awaited()
    await vac.async_start_mapping(replace_map=True)
    coordinator.async_send_command.assert_awaited_once()


@pytest.mark.parametrize("activity", ["cleaning", "returning", "paused", "error"])
async def test_start_mapping_refused_unless_docked_or_idle(coordinator, activity):
    coordinator.data = VacuumState(activity=activity)
    with pytest.raises(HomeAssistantError, match=activity):
        await RoboVacMQTTEntity(coordinator).async_start_mapping(replace_map=True)
    coordinator.async_send_command.assert_not_awaited()


async def test_services_refuse_legacy_robots(coordinator):
    coordinator.api_type = "legacy"
    with pytest.raises(HomeAssistantError, match="protobuf"):
        await RoboVacMQTTEntity(coordinator).async_rename_room(1, "x")
    coordinator.async_send_command.assert_not_awaited()


async def test_invalid_parameters_raise(coordinator):
    vac = RoboVacMQTTEntity(coordinator)
    with pytest.raises(HomeAssistantError, match="invalid"):
        await vac.async_merge_rooms([2, 2])
    with pytest.raises(HomeAssistantError, match="invalid"):
        await vac.async_divide_room(2, [[0, 0], [float("nan"), 1]])
    coordinator.async_send_command.assert_not_awaited()


# ── schemas ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["two", -1, 0x10000, 2**32])
def test_room_id_schema_rejects(bad):
    with pytest.raises(vol.Invalid):
        _ROOM_ID(bad)


@pytest.mark.parametrize("bad", ["nan", "inf", 1e12, -2e5])
def test_map_cm_schema_rejects(bad):
    with pytest.raises(vol.Invalid):
        _MAP_CM(bad)


def test_schemas_accept_real_values():
    assert _ROOM_ID("3") == 3
    assert _MAP_CM("-120.5") == -120.5
