"""The robot's reply to a ModeCtrl command (DPS 152): surfaced, not dropped."""

# pylint: disable=protected-access,redefined-outer-name

import logging
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.robovac_mqtt.api.commands import build_command
from custom_components.robovac_mqtt.api.local_tuya import LocalTuyaClient
from custom_components.robovac_mqtt.api.parser import rejected_mode_ctrl, update_state
from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.proto.cloud.control_pb2 import (
    ModeCtrlRequest,
    ModeCtrlResponse,
)
from custom_components.robovac_mqtt.utils import decode, encode_message

# Real replies from an S1 Pro (T2080A): room clean refused, auto clean accepted.
ROOM_CLEAN_FAILED = "BAgBGAE="
AUTO_CLEAN_OK = "AA=="


def test_rejected_mode_ctrl():
    assert rejected_mode_ctrl(ROOM_CLEAN_FAILED) == (1, "START_SELECT_ROOMS_CLEAN")
    assert rejected_mode_ctrl(AUTO_CLEAN_OK) is None
    assert rejected_mode_ctrl("not base64!") is None
    # a method outside the enum still names itself
    unknown = encode_message(
        ModeCtrlResponse(method=11, result=ModeCtrlResponse.FAILED)
    )
    assert rejected_mode_ctrl(unknown) == (11, "method 11")


def test_request_echoes_never_read_as_refusals():
    for command in ("start_auto", "pause", "stop", "return_to_base", "play"):
        assert rejected_mode_ctrl(build_command(command)["152"]) is None
    room = build_command("room_clean", room_ids=[1], map_id=1)["152"]
    assert rejected_mode_ctrl(room) is None


def test_parser_warns_on_a_refused_command(caplog):
    with caplog.at_level(logging.WARNING):
        update_state(VacuumState(), {"152": ROOM_CLEAN_FAILED})
    assert "rejected START_SELECT_ROOMS_CLEAN" in caplog.text


def test_parser_quiet_on_an_accepted_command(caplog):
    with caplog.at_level(logging.WARNING):
        update_state(VacuumState(), {"152": AUTO_CLEAN_OK})
        update_state(VacuumState(), {"152": "AggN"})  # pause echo, no params
    assert "rejected" not in caplog.text


@pytest.fixture
def fake_dev():
    return MagicMock()


@pytest.mark.asyncio
async def test_local_send_returns_and_dispatches_the_reply(fake_dev):
    with patch("custom_components.robovac_mqtt.api.local_tuya.tinytuya") as tt:
        tt.Device.return_value = fake_dev
        fake_dev.status.return_value = {"dps": {"163": 80}}
        client = LocalTuyaClient(device_id="d", local_key="k" * 16, host="1.2.3.4")
        received = []
        client.set_on_message(received.append)
        await client.connect()
        fake_dev.set_multiple_values.return_value = {"dps": {"152": ROOM_CLEAN_FAILED}}
        reply = await client.send_command({"152": "x"})
        assert reply == {"152": ROOM_CLEAN_FAILED}
        assert ROOM_CLEAN_FAILED in received[-1].decode()
        fake_dev.set_multiple_values.return_value = {"Error": "timeout"}
        assert await client.send_command({"152": "x"}) is None
        fake_dev.set_multiple_values.return_value = None
        assert await client.send_command({"152": "x"}) is None
        await client.send_command({"155": "drive"}, wait=False)
        assert fake_dev.set_multiple_values.call_args.kwargs["nowait"] is True
        await client.disconnect()


def _coordinator(reply):
    login = MagicMock(openudid="udid", tuya_client=None)
    info = {"deviceId": "d" * 22, "deviceModel": "T2080A", "deviceName": "S1 Pro"}
    coord = EufyCleanCoordinator(MagicMock(), login, info)
    client = MagicMock(spec=LocalTuyaClient)

    async def send(_cmd, wait=True):
        return reply

    client.send_command = send
    coord.client = client
    return coord


ROOM_CLEAN = build_command("room_clean", room_ids=[1], map_id=1)


def _failed(method):
    return encode_message(
        ModeCtrlResponse(method=method, result=ModeCtrlResponse.FAILED)
    )


@pytest.mark.asyncio
async def test_a_refused_clean_fails_the_service_call():
    coord = _coordinator({"152": ROOM_CLEAN_FAILED})
    with pytest.raises(HomeAssistantError, match="rejected START_SELECT_ROOMS_CLEAN"):
        await coord.async_send_command(ROOM_CLEAN)


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["stop", "pause", "play"])
async def test_a_refused_stop_or_pause_does_not_raise(command):
    """A 'stop, then return' script must not abort on a docked robot."""
    sent = build_command(command)
    method = decode(ModeCtrlRequest, sent["152"]).method
    await _coordinator({"152": _failed(method)}).async_send_command(sent)


@pytest.mark.asyncio
async def test_a_refusal_for_another_command_is_not_blamed_on_this_one():
    late = _failed(ModeCtrlRequest.START_SELECT_ZONES_CLEAN)
    await _coordinator({"152": late}).async_send_command(ROOM_CLEAN)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "reply"),
    [
        (build_command("start_auto"), {"152": AUTO_CLEAN_OK}),
        (build_command("start_auto"), None),
        ({"154": "settings"}, {"152": ROOM_CLEAN_FAILED}),  # not a ModeCtrl send
    ],
)
async def test_other_replies_pass(command, reply):
    await _coordinator(reply).async_send_command(command)


@pytest.mark.asyncio
async def test_an_unreadable_sent_command_is_never_blamed():
    await _coordinator({"152": ROOM_CLEAN_FAILED}).async_send_command({"152": "%%%"})
