"""Tests for cleaning-schedule (TimerRequest/TimerResponse) support.

The parser fixture below is a REAL TimerResponse captured from a RoboVac
Omni S1 Pro (T2080A, fw 7.0.168) over local Tuya — the device's full timer
list as published on the TIMING DP after an app-side schedule edit.
"""

# pylint: disable=redefined-outer-name

import asyncio
import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.robovac_mqtt.api.commands import (
    build_schedule_timer,
    build_timer_request_command,
)
from custom_components.robovac_mqtt.api.parser import (
    _parse_timer_response,
    update_state,
)
from custom_components.robovac_mqtt.const import DPS_MAP, SCHEDULE_DAY_BITS
from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.proto.cloud.timing_pb2 import (
    TimerInfo,
    TimerRequest,
    TimerResponse,
)
from custom_components.robovac_mqtt.utils import decode, encode_message

# Captured 2026-08-15: INQUIRY-class response, 4 timers. Timer #3 is a
# Saturday whole-house rooms clean listing all 9 rooms of the map (including
# room id 0); timer #2 is a single-room (id 0) weekday schedule.
CAPTURED_TIMER_LIST = (
    "jgIaACItCgIIBBICCAEaCBIGEAEYCCAtIgIIASoVGhMSEQoCCAISAggCGgIIAiIAiAECIjUKAg"
    "gBEgQIARABGgwIARIEEAEYCRoCCB8iAggBKhcaFQgBEhEKAggDEgIIAhoCCAIiAIgBASJrCgII"
    "AxIECAEQARoOCAESBhABGBQgCBoCCEAiAggBKksIASJHEkUIARICCAMaAggCIgIIAioAMgIIAT"
    "IECAkQATIECAMQAjIECAIQAzIECAoQBDIECAUQBTIECAYQBjIECAQQBzICEAiIAQEiNwoCCAIS"
    "BAgBEAEaDAgBEgQQARgPGgIIHyICCAEqGQgBIhUSEwgBEgAaAggCIgIIAioAMgCIAQI="
)


def test_parse_captured_timer_list():
    """The real T2080A timer list parses into 4 schedules with room data."""
    parsed = _parse_timer_response(CAPTURED_TIMER_LIST)
    assert parsed is not None
    schedules = parsed["schedules"]
    assert len(schedules) == 4
    by_id = {s["id"]: s for s in schedules}

    # Timer 1: Sun-Thu 09:00 auto clean, enabled.
    t1 = by_id[1]
    assert t1["type"] == "auto"
    assert t1["time"] == "09:00"
    assert t1["enabled"] is True
    assert set(t1["days"]) == {"sun", "mon", "tue", "wed", "thu"}
    assert t1["once"] is False

    # Timer 3: Saturday whole-house rooms clean on map 1 — 9 rooms in
    # cleaning order, INCLUDING room id 0.
    t3 = by_id[3]
    assert t3["type"] == "rooms"
    assert t3["days"] == ["sat"]
    assert t3["map_id"] == 1
    assert t3["room_ids"] == [1, 9, 3, 2, 10, 5, 6, 4, 0]

    # Timer 2: weekday single-room schedule targeting room 0.
    t2 = by_id[2]
    assert t2["type"] == "rooms"
    assert t2["room_ids"] == [0]

    # Every schedule carries raw TimerInfo bytes that round-trip losslessly.
    for sched in schedules:
        raw = TimerInfo()
        raw.ParseFromString(base64.b64decode(sched["raw"]))
        assert raw.id.value == sched["id"]


def test_update_state_routes_timing_dp():
    """A TimerResponse on the TIMING DP lands in VacuumState.schedules."""
    state = VacuumState(api_type="novel")
    new_state, changes = update_state(
        state, {DPS_MAP["TIMING"]: CAPTURED_TIMER_LIST}
    )
    assert len(new_state.schedules) == 4
    assert "last_timer_seq" in changes
    assert new_state.last_timer_result == 0


def test_update_state_timing_dp_tolerates_non_timer_payload():
    """MapEditResponse acks share this DP and even "decode" as empty
    TimerResponses (clashing fields become unknown fields) — they must not
    touch schedules or the request-correlation fields."""
    state = VacuumState(api_type="novel")
    for ack in ("BAgFGAI=", "AggF"):  # real FAILED and SUCCESS ack bytes
        new_state, changes = update_state(state, {DPS_MAP["TIMING"]: ack})
        assert new_state.schedules == []
        assert "schedules" not in changes
        assert "last_timer_seq" not in changes


def test_build_timer_request_inquiry():
    """INQUIRY encodes method+seq with no timer."""
    result = build_timer_request_command(TimerRequest.INQUIRY, 1001)
    assert DPS_MAP["TIMING"] in result
    decoded = decode(TimerRequest, result[DPS_MAP["TIMING"]])
    assert decoded.method == TimerRequest.INQUIRY
    assert decoded.seq == 1001
    assert not decoded.HasField("timer")


def test_build_schedule_timer_rooms_roundtrip():
    """A rooms-type timer keeps room id 0, order, map id, days and time."""
    week_bits = SCHEDULE_DAY_BITS["sun"] | SCHEDULE_DAY_BITS["thu"]
    timer = build_schedule_timer(
        hours=9,
        minutes=30,
        week_bits=week_bits,
        action_type="rooms",
        room_ids=[0, 6],
        map_id=1,
        enabled=True,
        summer=True,
    )
    result = build_timer_request_command(TimerRequest.ADD, 1002, timer)
    decoded = decode(TimerRequest, result[DPS_MAP["TIMING"]])
    t = decoded.timer
    # ADD carries no id (the device assigns one).
    assert t.id.value == 0
    assert t.status.valid is True
    assert t.status.opened is True
    assert t.desc.trigger == TimerInfo.Desc.CYCLE
    assert t.desc.timing.hours == 9
    assert t.desc.timing.minutes == 30
    assert t.desc.timing.summer is True
    assert t.desc.cycle.week_bits == week_bits
    assert t.action.type == TimerInfo.Action.SCHEDULE_ROOMS_CLEAN
    general = t.action.sche_rooms_clean.general
    assert general.map_id == 1
    assert [(r.id, r.order) for r in general.rooms] == [(0, 1), (6, 2)]


def test_build_schedule_timer_once_auto():
    """No week bits -> one-shot SINGLE trigger; auto clean selects the oneof."""
    timer = build_schedule_timer(
        hours=22, minutes=5, week_bits=0, action_type="auto", enabled=False
    )
    assert timer.desc.trigger == TimerInfo.Desc.SINGLE
    assert not timer.desc.HasField("cycle")
    assert timer.status.opened is False
    assert timer.action.type == TimerInfo.Action.SCHEDULE_AUTO_CLEAN
    assert timer.action.WhichOneof("Param") == "sche_auto_clean"


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


async def test_coordinator_timer_request_correlation(mock_hass, mock_login):
    """async_timer_request resolves when a TimerResponse with the matching
    seq arrives through the normal DPS-update path."""
    device_info = {
        "deviceId": "test_id",
        "deviceModel": "T2080A",
        "deviceName": "Test Vac",
        "dps": {},
    }
    coordinator = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coordinator.async_send_command = AsyncMock()
    # The dock-status debounce path calls async_call_later on a mock hass;
    # patch to a no-op cancel handle.
    request = asyncio.create_task(
        coordinator.async_timer_request(TimerRequest.INQUIRY, timeout=5)
    )
    await asyncio.sleep(0)  # let the request register its waiter + send
    assert coordinator.async_send_command.await_count == 1
    sent = coordinator.async_send_command.await_args.args[0]
    seq = decode(TimerRequest, sent[DPS_MAP["TIMING"]]).seq

    # Device answers with a full timer list echoing the seq.
    resp = TimerResponse(seq=seq)
    resp.result.value = 0
    timer = resp.timers.add()
    timer.id.value = 7
    timer.status.opened = True
    timer.desc.timing.hours = 9
    envelope = json.dumps(
        {
            "payload": json.dumps(
                {"data": {DPS_MAP["TIMING"]: encode_message(resp)}}
            )
        }
    ).encode()
    with patch(
        "custom_components.robovac_mqtt.coordinator.async_call_later"
    ):
        coordinator._handle_mqtt_message(envelope)

    result = await asyncio.wait_for(request, 5)
    assert result["success"] is True
    assert [s["id"] for s in result["schedules"]] == [7]
    assert coordinator.data.schedules[0]["time"] == "09:00"
