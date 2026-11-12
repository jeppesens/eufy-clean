"""Unit tests for the RoboVacMQTTEntity Custom Room Cleaning."""

# pylint: disable=redefined-outer-name, unused-argument

from unittest.mock import AsyncMock, MagicMock, call

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

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
    coordinator.data = VacuumState()
    coordinator.data.map_id = 1
    coordinator.resolve_map_id.return_value = 1
    coordinator.async_send_command = AsyncMock()
    coordinator.build_device_command = MagicMock(return_value={"cmd": "val"})
    return coordinator


@pytest.mark.asyncio
async def test_room_clean_standard(mock_coordinator):
    """Test standard room clean without custom parameters."""
    entity = RoboVacMQTTEntity(mock_coordinator)

    # Test room_clean without extra params
    await entity.async_send_command("room_clean", params={"room_ids": [1]})

    mock_coordinator.build_device_command.assert_called_once_with("room_clean", room_ids=[1], map_id=1)
    mock_coordinator.async_send_command.assert_called_once_with({"cmd": "val"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "room_ids,expected",
    [
        (3, [3]),  # a single id, as in `room_ids: 3`
        ("3", [3]),
        ((3, 4), [3, 4]),  # a tuple is read like a list
        (["3", "x", 4], [3, 4]),  # invalid ids are skipped
    ],
)
async def test_room_clean_coerces_room_ids(mock_coordinator, room_ids, expected):
    """room_ids takes one id or a list; ids become ints and invalid ones are skipped."""
    entity = RoboVacMQTTEntity(mock_coordinator)

    await entity.async_send_command("room_clean", params={"room_ids": room_ids})

    mock_coordinator.build_device_command.assert_called_once_with(
        "room_clean", room_ids=expected, map_id=1
    )


@pytest.mark.asyncio
async def test_room_clean_without_valid_room_ids_sends_nothing(mock_coordinator):
    """No valid room id means no command is sent."""
    entity = RoboVacMQTTEntity(mock_coordinator)

    await entity.async_send_command("room_clean", params={"room_ids": "x"})

    mock_coordinator.build_device_command.assert_not_called()
    mock_coordinator.async_send_command.assert_not_called()


@pytest.mark.asyncio
async def test_room_clean_custom(mock_coordinator):
    """Test room clean with custom parameters."""
    entity = RoboVacMQTTEntity(mock_coordinator)

    # We need to simulate different return values for the two build_device_command calls
    mock_coordinator.build_device_command.side_effect = [{"cmd": "config"}, {"cmd": "start"}]

    params = {
        "room_ids": [1, 2],
        "fan_speed": "Turbo",
        "water_level": "High",
        "clean_times": 2,
        "clean_mode": "vacuum_mop",
        "clean_intensity": "Deep",
        "edge_mopping": True,
    }

    await entity.async_send_command("room_clean", params=params)

    # Verify calls to build_device_command
    first_call = call(
        "set_room_custom",
        room_config=[1, 2],
        map_id=1,
        fan_speed="Turbo",
        water_level="High",
        clean_times=2,
        clean_mode="vacuum_mop",
        clean_intensity="Deep",
        edge_mopping=True,
    )
    second_call = call("room_clean", room_ids=[1, 2], map_id=1, mode="CUSTOMIZE")

    mock_coordinator.build_device_command.assert_has_calls([first_call, second_call])

    # Verify calls to coordinator.async_send_command
    mock_coordinator.async_send_command.assert_has_calls(
        [call({"cmd": "config"}), call({"cmd": "start"})]
    )


@pytest.mark.asyncio
async def test_room_clean_custom_partial_params(mock_coordinator):
    """Test room clean with only one custom parameter."""
    entity = RoboVacMQTTEntity(mock_coordinator)

    mock_coordinator.build_device_command.side_effect = [{"cmd": "config"}, {"cmd": "start"}]

    params = {"room_ids": [3], "clean_times": 3}

    await entity.async_send_command("room_clean", params=params)

    # Verify calls to build_device_command
    first_call = call(
        "set_room_custom",
        room_config=[3],
        map_id=1,
        fan_speed=None,
        water_level=None,
        clean_times=3,
        clean_mode=None,
        clean_intensity=None,
        edge_mopping=None,
    )
    second_call = call("room_clean", room_ids=[3], map_id=1, mode="CUSTOMIZE")

    mock_coordinator.build_device_command.assert_has_calls([first_call, second_call])


@pytest.mark.asyncio
async def test_room_clean_multi_room_config(mock_coordinator):
    """Test room clean with different settings per room (list of dicts)."""
    entity = RoboVacMQTTEntity(mock_coordinator)

    mock_coordinator.build_device_command.side_effect = [{"cmd": "config"}, {"cmd": "start"}]

    # New params structure
    params = {
        "rooms": [
            {"id": 1, "fan_speed": "Turbo", "clean_mode": "vacuum_mop"},
            {"id": 2, "fan_speed": "Quiet", "clean_mode": "vacuum"},
        ]
    }

    await entity.async_send_command("room_clean", params=params)

    # Verify calls to build_device_command
    first_call = call(
        "set_room_custom",
        room_config=[
            {"id": 1, "fan_speed": "Turbo", "clean_mode": "vacuum_mop"},
            {"id": 2, "fan_speed": "Quiet", "clean_mode": "vacuum"},
        ],
        map_id=1,
    )
    # room_clean should receive the extracted IDs
    second_call = call("room_clean", room_ids=[1, 2], map_id=1, mode="CUSTOMIZE")

    mock_coordinator.build_device_command.assert_has_calls([first_call, second_call])


# ---------------------------------------------------------------------------
# Legacy: customRooms is REPLACE-ALL, so neither call shape may build one
# from the selection alone.
# ---------------------------------------------------------------------------


@pytest.fixture
def legacy_coordinator(mock_coordinator):
    """The same coordinator, speaking the legacy (Tuya DPS) protocol."""
    mock_coordinator.api_type = "legacy"
    mock_coordinator.async_set_room_configs = AsyncMock(return_value=True)
    return mock_coordinator


@pytest.mark.asyncio
async def test_legacy_room_ids_with_globals_go_through_the_coordinator(
    legacy_coordinator,
):
    """The bare-id shape must NOT build a partial customRooms document.

    A legacy document naming only the selected rooms collapses every other
    room's stored suction/water/repeat override — silently, because it applies
    cleanly. The 'rooms' shape already routed around that; this one did not, so
    ``room_clean`` with room_ids + fan_speed wiped the rest of the flat.
    """
    entity = RoboVacMQTTEntity(legacy_coordinator)

    await entity.async_send_command(
        "room_clean", params={"room_ids": [2], "fan_speed": "Max"}
    )

    # The settings went to the merge path, which resends every room that
    # already carries an override...
    legacy_coordinator.async_set_room_configs.assert_awaited_once_with(
        {2: {"fan_speed": "Max"}}
    )
    # ...and nothing built a set_room_custom document straight from [2].
    built = [c.args[0] for c in legacy_coordinator.build_device_command.call_args_list]
    assert "set_room_custom" not in built
    assert built == ["room_clean"]


@pytest.mark.asyncio
async def test_legacy_room_ids_without_globals_still_just_cleans(legacy_coordinator):
    """No per-room settings asked for -> no settings write at all, whatever the
    robot's global suction / water level (customRooms rows persist)."""
    legacy_coordinator.data.fan_speed = "Max"
    legacy_coordinator.data.mop_water_level = "High"
    legacy_coordinator.data.received_fields.add("mop_water_level")
    entity = RoboVacMQTTEntity(legacy_coordinator)

    await entity.async_send_command("room_clean", params={"room_ids": [1, 2]})

    legacy_coordinator.async_set_room_configs.assert_not_awaited()
    legacy_coordinator.build_device_command.assert_called_once_with(
        "room_clean", room_ids=[1, 2], map_id=1
    )


@pytest.mark.asyncio
async def test_legacy_room_ids_only_forward_fields_legacy_can_carry(
    legacy_coordinator,
):
    """clean_mode / intensity / edge have no place in a legacy customRooms row."""
    entity = RoboVacMQTTEntity(legacy_coordinator)

    await entity.async_send_command(
        "room_clean",
        params={
            "room_ids": [0],
            "water_level": "High",
            "clean_times": 2,
            "clean_mode": "vacuum_mop",
            "edge_mopping": True,
        },
    )

    # Room id 0 is a real room on legacy — it must be a target like any other.
    legacy_coordinator.async_set_room_configs.assert_awaited_once_with(
        {0: {"water_level": "High", "clean_times": 2}}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("params", "accepted"),
    [
        ({"room_ids": [2], "fan_speed": "Boost_IQ"}, "Quiet, Standard, Turbo, Max"),
        ({"rooms": [{"id": 2, "water_level": "Medium"}]}, "Low, Mid, High"),
    ],
)
async def test_legacy_room_clean_rejects_levels_a_room_cannot_store(
    legacy_coordinator, params, accepted
):
    """A level customRooms cannot carry is refused with the accepted values,
    before any settings write or clean."""
    entity = RoboVacMQTTEntity(legacy_coordinator)

    with pytest.raises(ServiceValidationError, match=accepted):
        await entity.async_send_command("room_clean", params=params)

    legacy_coordinator.async_set_room_configs.assert_not_awaited()
    legacy_coordinator.async_send_command.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [
        {"room_ids": [2], "fan_speed": "Max"},
        {"rooms": [{"id": 2, "fan_speed": "max"}]},
    ],
)
async def test_legacy_room_clean_is_not_sent_when_the_settings_write_is_refused(
    legacy_coordinator, params
):
    """A refused customRooms write stops the call: the room is not cleaned with
    its stored settings instead of the requested ones."""
    legacy_coordinator.async_set_room_configs.return_value = False
    entity = RoboVacMQTTEntity(legacy_coordinator)

    with pytest.raises(HomeAssistantError):
        await entity.async_send_command("room_clean", params=params)

    legacy_coordinator.async_set_room_configs.assert_awaited_once()
    legacy_coordinator.async_send_command.assert_not_awaited()
