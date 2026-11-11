"""Unit tests for the RoboVacMQTTEntity."""

# pylint: disable=redefined-outer-name, unused-argument

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.vacuum import VacuumActivity
from homeassistant.exceptions import HomeAssistantError

from custom_components.robovac_mqtt.const import (
    EUFY_CLEAN_CLEAN_SPEED,
    EUFY_CLEAN_VACUUMCLEANER_STATE,
)
from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity


@pytest.fixture
def mock_coordinator():
    """Mock the coordinator."""
    coordinator = MagicMock()
    coordinator.device_id = "test_id"
    coordinator.device_name = "Test Vac"
    coordinator.device_model = "T2118"
    coordinator.api_type = "novel"
    coordinator.connection_type = "mqtt"
    coordinator.data = VacuumState()
    coordinator.async_send_command = AsyncMock()
    coordinator.build_device_command = MagicMock(return_value={"cmd": "val"})
    return coordinator


@pytest.fixture
def mock_config_entry():
    """Mock the config entry."""
    config_entry = MagicMock()
    config_entry.entry_id = "test_entry_id"
    return config_entry


def test_vacuum_properties(mock_coordinator, mock_config_entry):
    """Test vacuum properties."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    entity.hass = MagicMock()

    assert entity.unique_id == "test_id"
    # assert entity.name is None  # has_entity_name is True

    # Test Activity Mapping
    mock_coordinator.data.activity = EUFY_CLEAN_VACUUMCLEANER_STATE.CLEANING
    assert entity.activity == VacuumActivity.CLEANING

    mock_coordinator.data.activity = EUFY_CLEAN_VACUUMCLEANER_STATE.DOCKED
    assert entity.activity == VacuumActivity.DOCKED

    mock_coordinator.data.activity = "error"
    assert entity.activity == VacuumActivity.ERROR

    mock_coordinator.data.activity = "idle"
    assert entity.activity == VacuumActivity.IDLE


def test_vacuum_attributes(mock_coordinator, mock_config_entry):
    """Test vacuum attributes."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    mock_coordinator.data.battery_level = 80
    mock_coordinator.data.fan_speed = EUFY_CLEAN_CLEAN_SPEED.STANDARD
    mock_coordinator.data.error_code = 0
    mock_coordinator.data.task_status = "Cleaning"
    mock_coordinator.data.work_mode = "Room"

    attrs = entity.extra_state_attributes

    assert attrs["task_status"] == "Cleaning"
    assert attrs["work_mode"] == "Room"


@pytest.mark.asyncio
async def test_vacuum_commands(mock_coordinator, mock_config_entry):
    """Test vacuum commands."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_build = mock_coordinator.build_device_command

    # Start (Default/Docked)
    await entity.async_start()
    mock_build.assert_called_with("start_auto")
    mock_coordinator.async_send_command.assert_called_with({"cmd": "val"})

    # Start (Paused -> Resume)
    mock_coordinator.data.activity = "paused"
    await entity.async_start()
    mock_build.assert_called_with("play")

    # Stop
    await entity.async_stop()
    mock_build.assert_called_with("stop")

    # Pause
    await entity.async_pause()
    mock_build.assert_called_with("pause")

    # Return to base
    await entity.async_return_to_base()
    mock_build.assert_called_with("return_to_base")

    # Spot Clean
    await entity.async_clean_spot()
    mock_build.assert_called_with("clean_spot")

    # Locate
    await entity.async_locate()
    mock_build.assert_called_with("find_robot", active=True)


@pytest.mark.asyncio
async def test_zone_clean_dispatch(mock_coordinator, mock_config_entry):
    """zone_clean converts normalized rects, marks zone targets, and dispatches."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    quads = [[(1, 2), (3, 2), (3, 4), (1, 4)]]
    mock_coordinator.normalized_rects_to_quads_cm = MagicMock(return_value=quads)
    mock_coordinator.set_active_cleaning_targets = MagicMock()
    mock_coordinator.build_device_command = MagicMock(return_value={"152": "encoded"})
    # The reported (cloud) map id differs from the resolved one, so the
    # assertion below fails if zone_clean bypasses resolve_map_id().
    mock_coordinator.data.map_id = 2154
    mock_coordinator.resolve_map_id.return_value = 1

    await entity.async_send_command("zone_clean", {"zones": [[0.1, 0.2, 0.3, 0.4]]})

    mock_coordinator.normalized_rects_to_quads_cm.assert_called_once_with(
        [[0.1, 0.2, 0.3, 0.4]]
    )
    mock_coordinator.build_device_command.assert_called_once_with(
        "zone_clean", zones_cm=quads, map_id=1, clean_times=1
    )
    mock_coordinator.set_active_cleaning_targets.assert_called_once_with(zone_count=1)
    mock_coordinator.async_send_command.assert_called_with({"152": "encoded"})


@pytest.mark.asyncio
async def test_zone_clean_no_rects_noop(mock_coordinator, mock_config_entry):
    """zone_clean with an empty 'zones' list dispatches nothing."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.normalized_rects_to_quads_cm = MagicMock(return_value=[])

    await entity.async_send_command("zone_clean", {"zones": []})

    mock_coordinator.async_send_command.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("receives_map", "connection_type", "message"),
    [
        (True, "mqtt", "no map available yet"),
        (True, "local", "no map available yet"),
        (False, "cloud", r"Tuya \(cloud\) connection; use room_clean"),
        (False, "local", r"Tuya \(local\) connection; use room_clean"),
    ],
)
async def test_zone_clean_no_map_raises(
    mock_coordinator, mock_config_entry, receives_map, connection_type, message
):
    """zone_clean without a map (helper returns []) raises and dispatches nothing."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.receives_map = receives_map
    mock_coordinator.connection_type = connection_type
    mock_coordinator.normalized_rects_to_quads_cm = MagicMock(return_value=[])

    with pytest.raises(HomeAssistantError, match=message):
        await entity.async_send_command(
            "zone_clean", {"zones": [[0.1, 0.2, 0.3, 0.4]]}
        )

    mock_coordinator.normalized_rects_to_quads_cm.assert_called_once()
    mock_coordinator.async_send_command.assert_not_called()


@pytest.mark.asyncio
async def test_set_fan_speed(mock_coordinator, mock_config_entry):
    """Test setting fan speed."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_build = mock_coordinator.build_device_command

    speed_max = EUFY_CLEAN_CLEAN_SPEED.MAX.value
    await entity.async_set_fan_speed(speed_max)
    mock_build.assert_called_with("set_fan_speed", fan_speed=speed_max)
    mock_coordinator.async_send_command.assert_called_with({"cmd": "val"})

    # Invalid speed
    with pytest.raises(ValueError):
        await entity.async_set_fan_speed("InvalidSpeed")


@pytest.mark.asyncio
async def test_async_send_command_raw(mock_coordinator, mock_config_entry):
    """Test sending raw commands."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_build = mock_coordinator.build_device_command
    mock_coordinator.set_active_scene = MagicMock()
    mock_coordinator.set_active_cleaning_targets = MagicMock()
    mock_coordinator.data.scenes = [{"id": 5, "name": "Evening"}]

    # Test scene_clean
    await entity.async_send_command("scene_clean", params={"scene_id": 5})
    mock_build.assert_called_with("scene_clean", scene_id=5)
    mock_coordinator.set_active_scene.assert_called_with(5, "Evening")

    # Test room_clean: the reported (cloud) map id differs from the resolved
    # one, so the assertion fails if room_clean bypasses resolve_map_id().
    mock_coordinator.data.map_id = 2154
    mock_coordinator.resolve_map_id.return_value = 1
    await entity.async_send_command("room_clean", params={"room_ids": [1]})
    mock_build.assert_called_with("room_clean", room_ids=[1], map_id=1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command", ["start_auto", "pause", "return_to_base", "set_fan_speed"]
)
async def test_async_send_command_raw_passes_api_type(
    mock_coordinator, mock_config_entry, command
):
    """Raw vacuum.send_command must route through the device's DPS protocol.

    Regression: scalar (e.g. G50) devices got novel/protobuf payloads when
    commands were sent via the generic service instead of entity methods.
    Without an explicit api_type the entity defers to the coordinator's
    build_device_command (which applies the detected protocol and handles
    legacy devices); an explicit api_type in params still wins via build_command.
    """
    mock_coordinator.data = VacuumState(api_type="scalar")
    mock_coordinator.api_type = "scalar"
    mock_coordinator.build_device_command = MagicMock(return_value={"cmd": "raw"})
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    with patch("custom_components.robovac_mqtt.vacuum.build_command") as mock_build:
        mock_build.return_value = {"cmd": "raw"}

        params = {"fan_speed": "Max"} if command == "set_fan_speed" else None
        await entity.async_send_command(command, params=params)
        # No explicit api_type -> routed through the coordinator's dispatcher,
        # which applies the detected protocol (and supports legacy devices).
        assert mock_coordinator.build_device_command.call_args.args[0] == command
        mock_coordinator.async_send_command.assert_called_with({"cmd": "raw"})

        # An explicit api_type in params still wins over the detected one.
        await entity.async_send_command(command, params={"api_type": "novel"})
        assert mock_build.call_args.kwargs["api_type"] == "novel"


@pytest.fixture
def mqtt_coordinator():
    """Create a real coordinator for MQTT-level tests."""
    mock_hass = MagicMock()
    mock_login = MagicMock()
    mock_login.openudid = "test_udid"
    device_info = {
        "deviceId": "test_device",
        "deviceModel": "T2150",
        "deviceName": "Test Vacuum",
    }
    coord = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coord.async_set_updated_data = MagicMock()
    return coord


@pytest.mark.asyncio
async def test_room_clean_applies_user_preferences(mqtt_coordinator):
    """Test that room_clean command applies user preferences from select entities."""
    mqtt_coordinator.data.fan_speed = "Turbo"
    mqtt_coordinator.data.mop_water_level = "High"
    mqtt_coordinator.data.cleaning_mode = "Vacuum and mop"
    mqtt_coordinator.data.map_id = 3

    vacuum = RoboVacMQTTEntity(mqtt_coordinator)
    mqtt_coordinator.async_send_command = AsyncMock()

    await vacuum.async_send_command("room_clean", {"room_ids": [1, 2]})

    # Two commands: set_room_custom + room_clean
    assert mqtt_coordinator.async_send_command.call_count == 2

    first_call = mqtt_coordinator.async_send_command.call_args_list[0][0][0]
    assert "170" in first_call  # DPS 170 = set_room_custom

    second_call = mqtt_coordinator.async_send_command.call_args_list[1][0][0]
    assert "152" in second_call  # DPS 152 = room_clean


@pytest.mark.asyncio
async def test_room_clean_with_explicit_params_overrides_preferences(mqtt_coordinator):
    """Test that explicit params override user preferences."""
    mqtt_coordinator.data.fan_speed = "Turbo"
    mqtt_coordinator.data.mop_water_level = "High"
    mqtt_coordinator.data.cleaning_mode = "Vacuum and mop"

    vacuum = RoboVacMQTTEntity(mqtt_coordinator)
    mqtt_coordinator.async_send_command = AsyncMock()

    await vacuum.async_send_command(
        "room_clean",
        {"room_ids": [1], "fan_speed": "Quiet", "water_level": "Low"},
    )

    assert mqtt_coordinator.async_send_command.call_count == 2


@pytest.mark.asyncio
async def test_mqtt_malformed_message_does_not_crash(mqtt_coordinator):
    """Test that malformed MQTT messages don't crash the coordinator."""
    initial_fan_speed = "Standard"
    mqtt_coordinator.data.fan_speed = initial_fan_speed

    malformed_messages = [
        b"not json",
        b"{}",
        b'{"payload": "not a dict"}',
        b'{"payload": {}}',
        b'{"payload": {"data": "not a dict"}}',
    ]

    for malformed_msg in malformed_messages:
        mqtt_coordinator._handle_mqtt_message(malformed_msg)

    # State should remain unchanged after all malformed messages
    assert mqtt_coordinator.data.fan_speed == initial_fan_speed


@pytest.mark.asyncio
async def test_app_segment_clean_command(mock_coordinator, mock_config_entry):
    """Test app_segment_clean converts IDs and sends room_clean."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    entity.hass = mock_coordinator.hass
    mock_coordinator.data.map_id = 5
    mock_coordinator.resolve_map_id.return_value = 5

    await entity.async_send_command("app_segment_clean", params=[1, "2", 3.0])

    # Verify room_clean was called with int IDs via _async_handle_room_clean
    assert mock_coordinator.async_send_command.called


@pytest.mark.asyncio
async def test_app_segment_clean_invalid_ids(mock_coordinator, mock_config_entry):
    """Test app_segment_clean with invalid IDs does nothing."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    entity.hass = mock_coordinator.hass

    await entity.async_send_command("app_segment_clean", params=["invalid"])
    mock_coordinator.async_send_command.assert_not_called()


@pytest.mark.asyncio
async def test_async_clean_segments_empty_list(mock_coordinator, mock_config_entry):
    """Test async_clean_segments with empty list does nothing."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    entity.hass = mock_coordinator.hass

    await entity.async_clean_segments([])
    mock_coordinator.async_send_command.assert_not_called()


@pytest.mark.asyncio
async def test_map_load_novel_sends_command(mock_coordinator, mock_config_entry):
    """map_load on a novel device builds and sends the command."""
    mock_coordinator.api_type = "novel"
    mock_coordinator.build_device_command = MagicMock(return_value={"172": "x"})
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    await entity.async_map_load(6, seq=2)

    mock_coordinator.build_device_command.assert_called_once_with(
        "map_load", cloud_mapid=6, seq=2
    )
    mock_coordinator.async_send_command.assert_awaited_once_with({"172": "x"})


@pytest.mark.asyncio
async def test_map_load_scalar_raises(mock_coordinator, mock_config_entry):
    """map_load on a scalar/legacy device raises instead of silently no-oping."""
    mock_coordinator.api_type = "scalar"
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    with pytest.raises(HomeAssistantError):
        await entity.async_map_load(6)
    mock_coordinator.async_send_command.assert_not_called()


@pytest.mark.asyncio
async def test_map_load_empty_command_raises(mock_coordinator, mock_config_entry):
    """An empty builder result (unsupported / invalid id) raises."""
    mock_coordinator.api_type = "novel"
    mock_coordinator.build_device_command = MagicMock(return_value={})
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    with pytest.raises(HomeAssistantError):
        await entity.async_map_load(6)


@pytest.mark.asyncio
async def test_forget_map_delegates_to_coordinator(mock_coordinator, mock_config_entry):
    """Forgetting a non-active map delegates to the coordinator prune (local-only)."""
    mock_coordinator.data.map_id = 11
    mock_coordinator.async_forget_map = AsyncMock(return_value=True)
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    await entity.async_forget_map(6)

    mock_coordinator.async_forget_map.assert_awaited_once_with(6)


@pytest.mark.asyncio
async def test_forget_map_active_raises(mock_coordinator, mock_config_entry):
    """The active map cannot be forgotten (it would immediately re-seed)."""
    mock_coordinator.data.map_id = 11
    mock_coordinator.async_forget_map = AsyncMock()
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    with pytest.raises(HomeAssistantError):
        await entity.async_forget_map(11)
    mock_coordinator.async_forget_map.assert_not_called()
    mock_coordinator.async_send_command.assert_not_called()


@pytest.mark.asyncio
async def test_remote_drive_repeats_then_brakes(mock_coordinator, mock_config_entry):
    """One service call is a bounded run: repeated moves, then always a brake."""
    mock_coordinator.data.status_code = 6
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.build_device_command = MagicMock(
        side_effect=lambda cmd, **kw: {"cmd": kw["direction"]}
    )
    with patch("custom_components.robovac_mqtt.vacuum._REMOTE_REPEAT_SECONDS", 0.01):
        await entity.async_remote_drive("forward", 0.05)
    sent = [c.args[0]["cmd"] for c in mock_coordinator.async_send_command.await_args_list]
    assert sent[0] == "forward" and sent.count("forward") >= 2
    assert sent[-1] == "brake" and sent.count("brake") == 1


@pytest.mark.asyncio
async def test_remote_drive_brakes_even_if_a_send_fails(mock_coordinator, mock_config_entry):
    mock_coordinator.data.status_code = 6
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.build_device_command = MagicMock(
        side_effect=lambda cmd, **kw: {"cmd": kw["direction"]}
    )
    mock_coordinator.async_send_command = AsyncMock(
        side_effect=[HomeAssistantError("lost"), None]
    )
    with pytest.raises(HomeAssistantError):
        await entity.async_remote_drive("left", 1)
    assert mock_coordinator.async_send_command.await_args_list[-1].args[0] == {"cmd": "brake"}


@pytest.mark.asyncio
async def test_remote_drive_brake_and_zero_duration_only_stop(mock_coordinator, mock_config_entry):
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.build_device_command = MagicMock(
        side_effect=lambda cmd, **kw: {"cmd": kw["direction"]}
    )
    await entity.async_remote_drive("brake")
    await entity.async_remote_drive("forward", 0)
    assert [c.args[0]["cmd"] for c in mock_coordinator.async_send_command.await_args_list] == ["brake", "brake"]


@pytest.mark.asyncio
async def test_remote_drive_rejects_non_protobuf_robots(mock_coordinator, mock_config_entry):
    mock_coordinator.api_type = "scalar"
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    with pytest.raises(HomeAssistantError):
        await entity.async_remote_drive("forward", 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", [float("nan"), float("inf"), -1, 11])
async def test_remote_drive_rejects_non_finite_or_unbounded_duration(mock_coordinator, mock_config_entry, duration):
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    with pytest.raises(HomeAssistantError, match="finite duration"):
        await entity.async_remote_drive("forward", duration)
    mock_coordinator.async_send_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_remote_drive_requires_manual_mode(mock_coordinator, mock_config_entry):
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    with pytest.raises(HomeAssistantError, match="Enable manual"):
        await entity.async_remote_drive("forward", 1)
    mock_coordinator.async_send_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_brake_interrupts_a_run_and_conflicting_moves_are_rejected(mock_coordinator, mock_config_entry):
    mock_coordinator.data.status_code = 6
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    first_move = asyncio.Event()
    sent = []
    mock_coordinator.build_device_command.side_effect = lambda cmd, **kw: {"cmd": kw["direction"]}

    async def send(command, **kwargs):
        sent.append(command["cmd"])
        first_move.set()

    mock_coordinator.async_send_command.side_effect = send
    run = asyncio.create_task(entity.async_remote_drive("left", 10))
    try:
        await asyncio.wait_for(first_move.wait(), 1)
        with pytest.raises(HomeAssistantError, match="already running"):
            await entity.async_remote_drive("right", 1)
        await entity.async_remote_drive("brake")
        await asyncio.wait_for(run, 1)
        assert sent[0] == "left" and all(value == "brake" for value in sent[1:])
    finally:
        run.cancel()
        await asyncio.gather(run, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("duration", [0.05, 0.5])
async def test_remote_drive_brakes_at_the_requested_end_not_a_repeat_early(
    mock_coordinator, mock_config_entry, duration
):
    """The run lasts `duration`: no brake straight after the first move for short runs."""
    mock_coordinator.data.status_code = 6
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.build_device_command = MagicMock(
        side_effect=lambda cmd, **kw: {"cmd": kw["direction"]}
    )
    stamps: list[tuple[str, float]] = []
    loop = asyncio.get_running_loop()

    async def send(command, **_kw):
        stamps.append((command["cmd"], loop.time()))

    mock_coordinator.async_send_command = AsyncMock(side_effect=send)
    with patch("custom_components.robovac_mqtt.vacuum._REMOTE_REPEAT_SECONDS", duration * 2):
        await entity.async_remote_drive("forward", duration)
    (name0, start), (name1, braked) = stamps[0], stamps[-1]
    assert (name0, name1) == ("forward", "brake")
    assert braked - start >= duration * 0.9


@pytest.mark.asyncio
async def test_a_brake_call_still_ends_a_run_early(mock_coordinator, mock_config_entry):
    mock_coordinator.data.status_code = 6
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.build_device_command = MagicMock(
        side_effect=lambda cmd, **kw: {"cmd": kw["direction"]}
    )
    run = asyncio.ensure_future(entity.async_remote_drive("forward", 5))
    await asyncio.sleep(0.05)
    await entity.async_remote_drive("brake")
    await asyncio.wait_for(run, 1)


def test_vacuum_error_codes_attribute_holds_screen_codes_for_the_s1_pro(mock_coordinator, mock_config_entry):
    """The docking-retry automation matches E74/E75/E76 against this attribute."""
    mock_coordinator.data.device_model = "T2080A"
    mock_coordinator.data.error_code = 19924741
    mock_coordinator.data.error_codes = [19924741]
    mock_coordinator.data.warn_codes = []
    attrs = RoboVacMQTTEntity(mock_coordinator, mock_config_entry).extra_state_attributes
    assert attrs["error_codes"] == ["E75"] and attrs["error_codes_raw"] == [19924741]
    assert attrs["warn_codes"] == []
