"""Unit tests for the RoboVacMQTTEntity."""

# pylint: disable=redefined-outer-name, unused-argument

from types import MethodType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant.components.vacuum import (
    Segment,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.robovac_mqtt.api.legacy_parser import encode_legacy_loops
from custom_components.robovac_mqtt.api.parser_scalar import encode_scalar_repeat
from custom_components.robovac_mqtt.const import (
    DOMAIN,
    EUFY_CLEAN_CLEAN_SPEED,
    MIN_CLEAN_TIMES,
)
from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity, async_setup_entry

_VACUUM = "custom_components.robovac_mqtt.vacuum"


@pytest.fixture
def mock_coordinator():
    """Mock the coordinator."""
    coordinator = MagicMock()
    coordinator.device_id = "test_id"
    coordinator.device_name = "Test Vac"
    coordinator.device_model = "T2118"
    coordinator.api_type = "novel"
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
    mock_coordinator.data.activity = "cleaning"
    assert entity.activity == VacuumActivity.CLEANING

    mock_coordinator.data.activity = "docked"
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


@pytest.mark.parametrize("supported", [True, False])
def test_vacuum_attributes_say_whether_nogo_zones_can_be_saved(
    mock_coordinator, mock_config_entry, supported
):
    """The card offers No-go and Wall only when this is exactly ``True``."""
    mock_coordinator.nogo_zones_supported = supported
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    assert entity.extra_state_attributes["nogo_zones_supported"] is supported


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
async def test_zone_clean_no_rects_raises(mock_coordinator, mock_config_entry):
    """zone_clean with an empty 'zones' list raises instead of silently no-op'ing.

    A silent success on a command that never reached the device is the failure
    mode this integration has been bitten by before, so the entity now surfaces it.
    """
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.normalized_rects_to_quads_cm = MagicMock(return_value=[])

    with pytest.raises(HomeAssistantError, match="zone_clean"):
        await entity.async_send_command("zone_clean", {"zones": []})

    mock_coordinator.async_send_command.assert_not_called()


@pytest.mark.asyncio
async def test_zone_clean_no_map_raises(mock_coordinator, mock_config_entry):
    """zone_clean before the map has loaded (helper returns []) raises, not silent."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.normalized_rects_to_quads_cm = MagicMock(return_value=[])

    with pytest.raises(HomeAssistantError, match="no map available yet"):
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

    # Invalid speed: a user error, reported as such
    with pytest.raises(ServiceValidationError):
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
async def test_clean_area_entity_returns_its_segments(
    mock_coordinator, mock_config_entry
):
    """An entity advertising CLEAN_AREA answers HA's vacuum/get_segments
    (async_get_segments) with its map rooms."""
    mock_coordinator.data.rooms = [{"id": 3, "name": "Kitchen"}, {"id": 5}]
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    assert VacuumEntityFeature.CLEAN_AREA in entity.supported_features
    assert await entity.async_get_segments() == [
        Segment(id="3", name="Kitchen"),
        Segment(id="5", name="Room 5"),
    ]


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


# ---------------------------------------------------------------------------
# set_nogo_zones — drawing restricted geometry on the map
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_nogo_zones_forwards_rectangles(mock_coordinator, mock_config_entry):
    """Normalized rectangles reach the coordinator, merged by default."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.async_set_nogo_zones = AsyncMock(return_value=True)

    await entity.async_send_command(
        "set_nogo_zones", {"forbidden": [[0.1, 0.2, 0.3, 0.4]]}
    )

    mock_coordinator.async_set_nogo_zones.assert_awaited_once_with(
        add_forbidden=[[0.1, 0.2, 0.3, 0.4]], add_ban_mop=[], add_walls=[],
        remove_forbidden=[], remove_ban_mop=[], remove_walls=[],
        move_forbidden=[], move_ban_mop=[], move_walls=[],
        expect_revision=None, replace=False,
    )


@pytest.mark.asyncio
async def test_set_nogo_zones_empty_without_replace_raises(
    mock_coordinator, mock_config_entry
):
    """Sending nothing would WIPE the device's geometry, so it must be deliberate.

    The underlying document replaces all restricted geometry at once, and the
    device accepts it silently — so an accidental empty call is exactly the kind
    of destructive no-op that must not be reachable by mistake.
    """
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.async_set_nogo_zones = AsyncMock(return_value=True)

    with pytest.raises(HomeAssistantError, match="replace: true"):
        await entity.async_send_command("set_nogo_zones", {})

    mock_coordinator.async_set_nogo_zones.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_nogo_zones_explicit_clear_is_allowed(
    mock_coordinator, mock_config_entry
):
    """`replace: true` with no rectangles is the documented way to clear."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.async_set_nogo_zones = AsyncMock(return_value=True)

    await entity.async_send_command("set_nogo_zones", {"replace": True})

    mock_coordinator.async_set_nogo_zones.assert_awaited_once_with(
        add_forbidden=[], add_ban_mop=[], add_walls=[],
        remove_forbidden=[], remove_ban_mop=[], remove_walls=[],
        move_forbidden=[], move_ban_mop=[], move_walls=[],
        expect_revision=None, replace=True,
    )


@pytest.mark.asyncio
async def test_set_nogo_zones_rejects_non_lists(mock_coordinator, mock_config_entry):
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.async_set_nogo_zones = AsyncMock(return_value=True)

    with pytest.raises(HomeAssistantError, match="must be lists"):
        await entity.async_send_command("set_nogo_zones", {"forbidden": "nope"})


@pytest.mark.asyncio
async def test_set_nogo_zones_forwards_virtual_walls(
    mock_coordinator, mock_config_entry
):
    """A wall is a LINE — the same four numbers, but two endpoints, not a box."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.async_set_nogo_zones = AsyncMock(return_value=True)

    await entity.async_send_command(
        "set_nogo_zones", {"walls": [[0.1, 0.9, 0.8, 0.2]]}
    )

    mock_coordinator.async_set_nogo_zones.assert_awaited_once_with(
        add_forbidden=[], add_ban_mop=[], add_walls=[[0.1, 0.9, 0.8, 0.2]],
        remove_forbidden=[], remove_ban_mop=[], remove_walls=[],
        move_forbidden=[], move_ban_mop=[], move_walls=[],
        expect_revision=None, replace=False,
    )


@pytest.mark.asyncio
async def test_set_nogo_zones_removal_needs_no_new_shapes(
    mock_coordinator, mock_config_entry
):
    """Deleting is a legitimate call on its own — no shapes to add, not a clear.

    Without this the only way to remove a zone from the card would be
    ``replace: true`` with the full survivor list, which round-trips every
    surviving shape through normalized coordinates that clamp to the map image.
    """
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.async_set_nogo_zones = AsyncMock(return_value=True)

    await entity.async_send_command(
        "set_nogo_zones", {"remove_forbidden": [1], "revision": 7}
    )

    mock_coordinator.async_set_nogo_zones.assert_awaited_once_with(
        add_forbidden=[], add_ban_mop=[], add_walls=[],
        remove_forbidden=[1], remove_ban_mop=[], remove_walls=[],
        move_forbidden=[], move_ban_mop=[], move_walls=[],
        expect_revision=7, replace=False,
    )


@pytest.mark.asyncio
async def test_set_nogo_zones_rejects_non_list_removals(
    mock_coordinator, mock_config_entry
):
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.async_set_nogo_zones = AsyncMock(return_value=True)

    with pytest.raises(HomeAssistantError, match="must be lists of indices"):
        await entity.async_send_command("set_nogo_zones", {"remove_walls": 2})


@pytest.mark.asyncio
async def test_set_nogo_zones_forwards_rotated_corner_points(
    mock_coordinator, mock_config_entry
):
    """A zone given as four corners passes through untouched (rotation)."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.async_set_nogo_zones = AsyncMock(return_value=True)
    diamond = [[0.5, 0.2], [0.8, 0.5], [0.5, 0.8], [0.2, 0.5]]

    await entity.async_send_command("set_nogo_zones", {"forbidden": [diamond]})

    assert mock_coordinator.async_set_nogo_zones.await_args.kwargs[
        "add_forbidden"
    ] == [diamond]


@pytest.mark.asyncio
async def test_set_nogo_zones_forwards_a_move(mock_coordinator, mock_config_entry):
    """Moving an existing shape is a delta on an index, not a new outline."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.async_set_nogo_zones = AsyncMock(return_value=True)
    move = {"index": 0, "dx": 25.0, "dy": -10.0, "rotate": 0.3}

    await entity.async_send_command(
        "set_nogo_zones", {"move_forbidden": [move], "revision": 4}
    )

    kwargs = mock_coordinator.async_set_nogo_zones.await_args.kwargs
    assert kwargs["move_forbidden"] == [move]
    assert kwargs["expect_revision"] == 4
    # A move on its own is a change: it must not trip the "no shapes" guard.
    assert kwargs["add_forbidden"] == []


@pytest.mark.asyncio
async def test_set_nogo_zones_rejects_non_list_moves(
    mock_coordinator, mock_config_entry
):
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.async_set_nogo_zones = AsyncMock(return_value=True)

    with pytest.raises(HomeAssistantError, match="index, dx, dy, rotate"):
        await entity.async_send_command("set_nogo_zones", {"move_walls": {"index": 0}})


async def _service_schemas(hass) -> dict[str, vol.Schema]:
    """The entity-service schemas async_setup_entry registers, by service name."""
    platform = MagicMock()
    entry = MagicMock(entry_id="entry1")
    hass.data[DOMAIN] = {"entry1": {"coordinators": []}}
    with patch(
        f"{_VACUUM}.entity_platform.async_get_current_platform", return_value=platform
    ):
        await async_setup_entry(hass, entry, MagicMock())
    return {
        call.args[0]: vol.Schema(call.args[1])
        for call in platform.async_register_entity_service.call_args_list
    }


@pytest.mark.parametrize(
    ("service", "base"),
    [("set_room_config", {"room": "Kitchen"}), ("set_schedule", {"time": "08:00"})],
)
async def test_clean_times_services_validate_the_const_range(hass, service, base):
    """The pass-count range follows MIN/MAX_CLEAN_TIMES, not a copy of it."""
    with patch(f"{_VACUUM}.MAX_CLEAN_TIMES", 5):
        schema = (await _service_schemas(hass))[service]

    assert schema({**base, "clean_times": 5})["clean_times"] == 5
    with pytest.raises(vol.Invalid):
        schema({**base, "clean_times": 6})
    with pytest.raises(vol.Invalid):
        schema({**base, "clean_times": MIN_CLEAN_TIMES - 1})


async def test_set_schedule_schema_fills_in_no_defaults(hass):
    """Omitted fields stay omitted, so an edit keeps the schedule's values."""
    schema = (await _service_schemas(hass))["set_schedule"]

    assert schema({"schedule_id": 5, "time": "10:00"}) == {
        "schedule_id": 5, "time": "10:00",
    }
    assert schema({"suction": "Max"}) == {"suction": "Max"}


@pytest.mark.parametrize(
    ("encode", "days", "expected"),
    [
        (encode_legacy_loops, "0111110", "0111110"),
        (encode_scalar_repeat, "135", "135"),
        (encode_legacy_loops, "Mon, Sun", "1100000"),
        (encode_scalar_repeat, ["Mon", "Sun"], "17"),
    ],
)
async def test_set_schedule_days_reach_the_encoders_as_typed(hass, encode, days, expected):
    """A raw day mask typed as the service's days survives the schema."""
    schema = (await _service_schemas(hass))["set_schedule"]

    assert encode(schema({"days": days})["days"]) == expected


async def test_set_schedule_forwards_omitted_fields_as_none(
    mock_coordinator, mock_config_entry
):
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    mock_coordinator.async_set_schedule = AsyncMock(return_value=True)

    await entity.async_set_schedule(schedule_id=5, time="10:00")

    mock_coordinator.async_set_schedule.assert_awaited_once_with(
        schedule_id=5, time="10:00", days=None, enabled=None, suction=None,
        water=None, rooms=None, clean_times=None, mode=None,
    )


@pytest.mark.parametrize(
    ("room", "map_rooms", "expected"),
    [
        ("Lounge", [{"id": 1, "name": "Living"}], 1),
        ("lounge (id: 1)", [{"id": 1, "name": "Living"}], 1),
        ("Living", [{"id": 1, "name": "Living"}], 1),
        ("Kitchen", [{"id": 1, "name": "Living"}, {"id": 2, "name": "Kitchen"}], 2),
        ("4", [], 4),
        ("Office", [], 4),
        ("Garage", [{"id": 1, "name": "Living"}], None),
        ("9", [{"id": 1, "name": "Living"}], None),
    ],
)
def test_room_names_resolve_like_the_clean_room_select(
    mock_coordinator, mock_config_entry, room, map_rooms, expected
):
    """Service room arguments resolve against the Clean Room select's list
    (overrides first), its option labels, then the map rooms; numeric override
    ids resolve before any map room has loaded."""
    mock_coordinator.room_name_overrides = {1: "Lounge", 4: "Office"}
    mock_coordinator.data.rooms = map_rooms
    mock_coordinator.selectable_rooms = MethodType(
        EufyCleanCoordinator.selectable_rooms, mock_coordinator
    )
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    assert entity._resolve_room_id(room) == expected


@pytest.mark.asyncio
async def test_set_room_config_refuses_an_override_room_missing_from_the_map(
    mock_coordinator, mock_config_entry
):
    """An override id the map does not hold has no customRooms row to write."""
    mock_coordinator.api_type = "legacy"
    mock_coordinator.legacy_room_config_supported = True
    mock_coordinator.room_name_overrides = {7: "Attic"}
    mock_coordinator.data.rooms = [{"id": 1, "name": "Living"}]
    mock_coordinator.selectable_rooms = MethodType(
        EufyCleanCoordinator.selectable_rooms, mock_coordinator
    )
    mock_coordinator.async_set_room_config = AsyncMock(return_value=True)
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    with pytest.raises(HomeAssistantError, match="not on the current map"):
        await entity.async_set_room_config("Attic", suction="Max")
    mock_coordinator.async_set_room_config.assert_not_awaited()
