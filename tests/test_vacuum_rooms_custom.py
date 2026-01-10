"""Unit tests for the RoboVacMQTTEntity Custom Room Cleaning."""

# pylint: disable=redefined-outer-name, unused-argument

from unittest.mock import AsyncMock, MagicMock, call, patch

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
    coordinator.data = VacuumState()
    coordinator.data.map_id = 1
    coordinator.async_send_command = AsyncMock()
    return coordinator


@pytest.mark.asyncio
async def test_room_clean_standard(mock_coordinator):
    """Test standard room clean without custom parameters."""
    entity = RoboVacMQTTEntity(mock_coordinator)

    with patch("custom_components.robovac_mqtt.vacuum.build_command") as mock_build:
        mock_build.return_value = {"cmd": "val"}

        # Test room_clean without extra params
        await entity.async_send_command("room_clean", params={"room_ids": [1]})

        mock_build.assert_called_once_with("room_clean", room_ids=[1], map_id=1)
        mock_coordinator.async_send_command.assert_called_once_with({"cmd": "val"})


@pytest.mark.asyncio
async def test_room_clean_custom(mock_coordinator):
    """Test room clean with custom parameters."""
    entity = RoboVacMQTTEntity(mock_coordinator)

    with patch("custom_components.robovac_mqtt.vacuum.build_command") as mock_build:
        # We need to simulate different return values if we want to distinguish calls,
        # but verifying the call definitions is enough.
        mock_build.side_effect = [{"cmd": "config"}, {"cmd": "start"}]

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

        # Verify calls to build_command
        # Note: 'room_ids' was renamed to 'room_config' in build_command call for set_room_custom
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

        mock_build.assert_has_calls([first_call, second_call])

        # Verify calls to coordinator.async_send_command
        mock_coordinator.async_send_command.assert_has_calls(
            [call({"cmd": "config"}), call({"cmd": "start"})]
        )


@pytest.mark.asyncio
async def test_room_clean_custom_partial_params(mock_coordinator):
    """Test room clean with only one custom parameter."""
    entity = RoboVacMQTTEntity(mock_coordinator)

    with patch("custom_components.robovac_mqtt.vacuum.build_command") as mock_build:
        mock_build.side_effect = [{"cmd": "config"}, {"cmd": "start"}]

        params = {"room_ids": [3], "clean_times": 3}

        await entity.async_send_command("room_clean", params=params)

        # Verify calls to build_command
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

        mock_build.assert_has_calls([first_call, second_call])


@pytest.mark.asyncio
async def test_room_clean_multi_room_config(mock_coordinator):
    """Test room clean with different settings per room (list of dicts)."""
    entity = RoboVacMQTTEntity(mock_coordinator)

    with patch("custom_components.robovac_mqtt.vacuum.build_command") as mock_build:
        mock_build.side_effect = [{"cmd": "config"}, {"cmd": "start"}]

        # New params structure
        params = {
            "rooms": [
                {"id": 1, "fan_speed": "Turbo", "clean_mode": "vacuum_mop"},
                {"id": 2, "fan_speed": "Quiet", "clean_mode": "vacuum"},
            ]
        }

        await entity.async_send_command("room_clean", params=params)

        # Verify calls to build_command
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

        mock_build.assert_has_calls([first_call, second_call])
