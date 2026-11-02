"""Unit tests for the RoboVacMQTTEntity Custom Room Cleaning."""

# pylint: disable=redefined-outer-name, unused-argument

from unittest.mock import AsyncMock, MagicMock, call

import pytest

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
