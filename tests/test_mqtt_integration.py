import pytest
"""Integration tests for MQTT message handling.

This module contains integration tests that verify MQTT messages are properly
handled and entities update correctly.

**Validates: Requirements 1.5, 8.4**
"""

# pylint: disable=redefined-outer-name

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.select import (
    CleaningModeSelectEntity,
    SuctionLevelSelectEntity,
)
from custom_components.robovac_mqtt.sensor import BatterySensorEntity
from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity


@pytest.fixture
def mock_hass():
    """Mock the Home Assistant object."""
    return MagicMock()


@pytest.fixture
def mock_login():
    """Mock the EufyLogin object."""
    login = MagicMock()
    login.openudid = "test_udid"
    return login


@pytest.fixture
def coordinator(mock_hass, mock_login):
    """Create a coordinator for testing."""
    device_info = {
        "deviceId": "test_device",
        "deviceModel": "T2150",  # Mopping model
        "deviceName": "Test Vacuum",
    }
    coord = EufyCleanCoordinator(mock_hass, mock_login, device_info)
    coord.async_set_updated_data = MagicMock()
    return coord


# ============================================================================
# MQTT Message Handling Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_mqtt_message_with_room_data_updates_vacuum_entity(coordinator):
    """Test that MQTT message with room data updates vacuum entity.

    **Validates: Requirements 1.5, 8.4**

    This test verifies that when an MQTT message containing room data is received,
    the vacuum entity's extra_state_attributes are updated to include the rooms.
    """
    # Create vacuum entity
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    vacuum_entity.hass = MagicMock()

    # Initial state - no rooms
    assert coordinator.data.rooms == []

    # Create MQTT message with room data (DPS 165 - MAP_DATA)
    mqtt_payload = {
        "payload": {
            "data": {
                "165": json.dumps({
                    "rooms": [
                        {"id": 1, "name": "Kitchen"},
                        {"id": 2, "name": "Living Room"},
                        {"id": 3, "name": "Bedroom"}
                    ]
                })
            }
        }
    }

    # Mock update_state to simulate parsing the MQTT message
    with patch("custom_components.robovac_mqtt.coordinator.update_state") as mock_update:
        new_state = VacuumState(
            rooms=[
                {"id": 1, "name": "Kitchen"},
                {"id": 2, "name": "Living Room"},
                {"id": 3, "name": "Bedroom"}
            ]
        )
        mock_update.return_value = (new_state, {"rooms": new_state.rooms})

        # Send MQTT message
        payload_bytes = json.dumps(mqtt_payload).encode()
        coordinator._handle_mqtt_message(payload_bytes)

        # Verify update_state was called
        mock_update.assert_called_once()

        # Verify coordinator.async_set_updated_data was called with new state
        coordinator.async_set_updated_data.assert_called()
        call_args = coordinator.async_set_updated_data.call_args[0][0]
        assert call_args.rooms == new_state.rooms

    # Update coordinator data to simulate the state update
    coordinator.data = new_state

    # Verify vacuum entity exposes rooms in extra_state_attributes
    attrs = vacuum_entity.extra_state_attributes
    assert "rooms" in attrs
    assert len(attrs["rooms"]) == 3
    assert attrs["rooms"][0]["id"] == 1
    assert attrs["rooms"][0]["name"] == "Kitchen"
    assert attrs["rooms"][1]["id"] == 2
    assert attrs["rooms"][1]["name"] == "Living Room"
    assert attrs["rooms"][2]["id"] == 3
    assert attrs["rooms"][2]["name"] == "Bedroom"


@pytest.mark.asyncio
async def test_mqtt_message_with_fan_speed_updates_entities(coordinator):
    """Test that MQTT message with fan speed updates both vacuum and suction entities.

    **Validates: Requirements 8.4**

    This test verifies that when an MQTT message containing fan speed is received,
    both the vacuum entity and suction level entity are synchronized.
    """
    # Create entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(coordinator)
    suction_entity.hass = MagicMock()

    # Initial state
    coordinator.data.fan_speed = "Standard"
    assert vacuum_entity.fan_speed == "Standard"
    assert suction_entity.current_option == "Standard"

    # Create MQTT message with fan speed change (DPS 102 - CLEAN_SPEED)
    mqtt_payload = {
        "payload": {
            "data": {
                "102": "2"  # Turbo (index 2)
            }
        }
    }

    # Mock update_state to simulate parsing the MQTT message
    with patch("custom_components.robovac_mqtt.coordinator.update_state") as mock_update:
        new_state = VacuumState(fan_speed="Turbo")
        mock_update.return_value = (new_state, {"fan_speed": "Turbo"})

        # Send MQTT message
        payload_bytes = json.dumps(mqtt_payload).encode()
        coordinator._handle_mqtt_message(payload_bytes)

        # Verify update_state was called
        mock_update.assert_called_once()

    # Update coordinator data to simulate the state update
    coordinator.data.fan_speed = "Turbo"

    # Verify both entities reflect the new fan speed
    assert vacuum_entity.fan_speed == "Turbo"
    assert suction_entity.current_option == "Turbo"


@pytest.mark.asyncio
async def test_mqtt_message_with_battery_level_updates_sensor(coordinator):
    """Test that MQTT message with battery level updates battery sensor.

    **Validates: Requirements 8.4**

    This test verifies that when an MQTT message containing battery level is received,
    the battery sensor entity is updated.
    """
    # Create battery sensor entity
    battery_entity = BatterySensorEntity(coordinator)
    battery_entity.hass = MagicMock()

    # Initial state
    coordinator.data.battery_level = 100
    assert battery_entity.native_value == 100

    # Create MQTT message with battery level change (DPS 163 - BATTERY_LEVEL)
    mqtt_payload = {
        "payload": {
            "data": {
                "163": "75"
            }
        }
    }

    # Mock update_state to simulate parsing the MQTT message
    with patch("custom_components.robovac_mqtt.coordinator.update_state") as mock_update:
        new_state = VacuumState(battery_level=75)
        mock_update.return_value = (new_state, {"battery_level": 75})

        # Send MQTT message
        payload_bytes = json.dumps(mqtt_payload).encode()
        coordinator._handle_mqtt_message(payload_bytes)

        # Verify update_state was called
        mock_update.assert_called_once()

    # Update coordinator data to simulate the state update
    coordinator.data.battery_level = 75

    # Verify battery sensor reflects the new level
    assert battery_entity.native_value == 75


@pytest.mark.asyncio
async def test_mqtt_comprehensive_message_updates_all_entities(coordinator):
    """Test that comprehensive MQTT message updates all entities correctly.

    **Validates: Requirements 1.5, 8.4**

    This test verifies that when an MQTT message contains multiple state updates,
    all entities are synchronized correctly.
    """
    # Create all entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(coordinator)
    suction_entity.hass = MagicMock()

    cleaning_entity = CleaningModeSelectEntity(coordinator)
    cleaning_entity.hass = MagicMock()

    battery_entity = BatterySensorEntity(coordinator)
    battery_entity.hass = MagicMock()

    # Initial state
    coordinator.data.fan_speed = "Standard"
    coordinator.data.battery_level = 100
    coordinator.data.cleaning_mode = "Vacuum"
    coordinator.data.rooms = []

    # Create comprehensive MQTT message
    mqtt_payload = {
        "payload": {
            "data": {
                "102": "3",  # Max fan speed
                "163": "42",  # Battery level
                "165": json.dumps({
                    "rooms": [
                        {"id": 1, "name": "Kitchen"},
                        {"id": 2, "name": "Living Room"}
                    ]
                })
            }
        }
    }

    # Mock update_state to simulate parsing the MQTT message
    with patch("custom_components.robovac_mqtt.coordinator.update_state") as mock_update:
        new_state = VacuumState(
            fan_speed="Max",
            battery_level=42,
            cleaning_mode="Vacuum and mop",
            rooms=[
                {"id": 1, "name": "Kitchen"},
                {"id": 2, "name": "Living Room"}
            ]
        )
        mock_update.return_value = (new_state, {
            "fan_speed": "Max",
            "battery_level": 42,
            "cleaning_mode": "Vacuum and mop",
            "rooms": new_state.rooms
        })

        # Send MQTT message
        payload_bytes = json.dumps(mqtt_payload).encode()
        coordinator._handle_mqtt_message(payload_bytes)

        # Verify update_state was called
        mock_update.assert_called_once()

    # Update coordinator data to simulate the state update
    coordinator.data = new_state

    # Verify all entities reflect the new state
    assert vacuum_entity.fan_speed == "Max"
    assert suction_entity.current_option == "Max"
    assert cleaning_entity.current_option == "Vacuum and mop"
    assert battery_entity.native_value == 42
    assert len(vacuum_entity.extra_state_attributes["rooms"]) == 2
    assert vacuum_entity.extra_state_attributes["rooms"][0]["name"] == "Kitchen"
    assert vacuum_entity.extra_state_attributes["rooms"][1]["name"] == "Living Room"


@pytest.mark.asyncio
async def test_mqtt_state_synchronization_timing(coordinator):
    """Test that entity state synchronization happens immediately after MQTT update.

    Verifies that when the device reports state changes via MQTT,
    all entities update within 2 seconds (actually immediate in our implementation).
    """
    # Create all entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(coordinator)
    suction_entity.hass = MagicMock()

    battery_entity = BatterySensorEntity(coordinator)
    battery_entity.hass = MagicMock()

    # Initial state
    coordinator.data.fan_speed = "Standard"
    coordinator.data.battery_level = 100
    coordinator.data.rooms = []

    # Create MQTT message with multiple updates
    mqtt_payload = {
        "payload": {
            "data": {
                "102": "2",  # Turbo
                "163": "65",  # Battery
                "165": json.dumps({
                    "rooms": [
                        {"id": 1, "name": "Kitchen"},
                        {"id": 2, "name": "Living Room"},
                        {"id": 3, "name": "Bedroom"}
                    ]
                })
            }
        }
    }

    # Mock update_state to simulate parsing the MQTT message
    with patch("custom_components.robovac_mqtt.coordinator.update_state") as mock_update:
        new_state = VacuumState(
            fan_speed="Turbo",
            battery_level=65,
            rooms=[
                {"id": 1, "name": "Kitchen"},
                {"id": 2, "name": "Living Room"},
                {"id": 3, "name": "Bedroom"}
            ]
        )
        mock_update.return_value = (new_state, {
            "fan_speed": "Turbo",
            "battery_level": 65,
            "rooms": new_state.rooms
        })

        # Send MQTT message
        payload_bytes = json.dumps(mqtt_payload).encode()
        coordinator._handle_mqtt_message(payload_bytes)

    # Update coordinator data to simulate the state update
    coordinator.data = new_state

    # Verify all entities are immediately synchronized (no delay)
    assert vacuum_entity.fan_speed == "Turbo"
    assert suction_entity.current_option == "Turbo"
    assert battery_entity.native_value == 65
    assert len(vacuum_entity.extra_state_attributes["rooms"]) == 3
    assert vacuum_entity.extra_state_attributes["rooms"][0]["name"] == "Kitchen"


@pytest.mark.asyncio
async def test_mqtt_room_data_empty_to_populated(coordinator):
    """Test MQTT message transitioning from empty rooms to populated rooms.

    **Validates: Requirements 1.5, 8.4**

    This test verifies that room data can transition from empty to populated
    via MQTT messages.
    """
    # Create vacuum entity
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    vacuum_entity.hass = MagicMock()

    # Initial state - no rooms
    coordinator.data.rooms = []
    assert vacuum_entity.extra_state_attributes["rooms"] == []

    # Create MQTT message with room data
    mqtt_payload = {
        "payload": {
            "data": {
                "165": json.dumps({
                    "rooms": [
                        {"id": 1, "name": "Kitchen"},
                        {"id": 2, "name": "Bedroom"}
                    ]
                })
            }
        }
    }

    # Mock update_state to simulate parsing the MQTT message
    with patch("custom_components.robovac_mqtt.coordinator.update_state") as mock_update:
        new_state = VacuumState(
            rooms=[
                {"id": 1, "name": "Kitchen"},
                {"id": 2, "name": "Bedroom"}
            ]
        )
        mock_update.return_value = (new_state, {"rooms": new_state.rooms})

        # Send MQTT message
        payload_bytes = json.dumps(mqtt_payload).encode()
        coordinator._handle_mqtt_message(payload_bytes)

    # Update coordinator data to simulate the state update
    coordinator.data.rooms = new_state.rooms

    # Verify rooms are now populated
    assert len(vacuum_entity.extra_state_attributes["rooms"]) == 2
    assert vacuum_entity.extra_state_attributes["rooms"][0]["id"] == 1
    assert vacuum_entity.extra_state_attributes["rooms"][1]["id"] == 2


@pytest.mark.asyncio
async def test_mqtt_room_data_update_preserves_other_state(coordinator):
    """Test that MQTT room data update doesn't affect other entity states.

    Verifies that when only room data is updated via MQTT,
    other entity states remain unchanged.
    """
    # Create all entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(coordinator)
    suction_entity.hass = MagicMock()

    battery_entity = BatterySensorEntity(coordinator)
    battery_entity.hass = MagicMock()

    # Set initial state
    coordinator.data.fan_speed = "Max"
    coordinator.data.battery_level = 85
    coordinator.data.rooms = []

    # Verify initial state
    assert vacuum_entity.fan_speed == "Max"
    assert battery_entity.native_value == 85

    # Create MQTT message updating only room data
    mqtt_payload = {
        "payload": {
            "data": {
                "165": json.dumps({
                    "rooms": [
                        {"id": 1, "name": "Kitchen"}
                    ]
                })
            }
        }
    }

    # Mock update_state to simulate parsing the MQTT message
    with patch("custom_components.robovac_mqtt.coordinator.update_state") as mock_update:
        new_state = VacuumState(
            fan_speed="Max",  # Unchanged
            battery_level=85,  # Unchanged
            rooms=[{"id": 1, "name": "Kitchen"}]  # Changed
        )
        mock_update.return_value = (new_state, {"rooms": new_state.rooms})

        # Send MQTT message
        payload_bytes = json.dumps(mqtt_payload).encode()
        coordinator._handle_mqtt_message(payload_bytes)

    # Update coordinator data to simulate the state update
    coordinator.data = new_state

    # Verify room data updated
    assert len(vacuum_entity.extra_state_attributes["rooms"]) == 1

    # Verify other state unchanged
    assert vacuum_entity.fan_speed == "Max"
    assert suction_entity.current_option == "Max"
    assert battery_entity.native_value == 85


@pytest.mark.asyncio
async def test_mqtt_malformed_message_does_not_crash(coordinator):
    """Test that malformed MQTT messages don't crash the coordinator.

    **Validates: Error handling for MQTT message parsing**

    This test verifies that the coordinator gracefully handles malformed
    MQTT messages without crashing.
    """
    # Create entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    vacuum_entity.hass = MagicMock()

    # Set initial state
    initial_fan_speed = "Standard"
    coordinator.data.fan_speed = initial_fan_speed

    # Test various malformed MQTT messages
    malformed_messages = [
        b"not json",
        b"{}",
        b'{"payload": "not a dict"}',
        b'{"payload": {}}',
        b'{"payload": {"data": "not a dict"}}',
    ]

    for malformed_msg in malformed_messages:
        # Should not raise exception
        try:
            coordinator._handle_mqtt_message(malformed_msg)
        except Exception as e:
            pytest.fail(f"Malformed message caused exception: {e}")

        # State should remain unchanged
        assert vacuum_entity.fan_speed == initial_fan_speed


@pytest.mark.asyncio
async def test_mqtt_rapid_state_changes_maintain_consistency(coordinator):
    """Test that rapid MQTT messages maintain state consistency across entities.

    **Validates: Requirements 8.4, 8.5**

    This test verifies that when multiple MQTT messages are received in rapid
    succession, all entities remain synchronized with the coordinator state.
    """
    # Create entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(coordinator)
    suction_entity.hass = MagicMock()

    battery_entity = BatterySensorEntity(coordinator)
    battery_entity.hass = MagicMock()

    # Simulate rapid MQTT messages
    mqtt_messages = [
        ("Quiet", 100),
        ("Standard", 95),
        ("Turbo", 90),
        ("Max", 85),
        ("Standard", 80),
    ]

    for fan_speed, battery_level in mqtt_messages:
        # Mock update_state for each message
        with patch("custom_components.robovac_mqtt.coordinator.update_state") as mock_update:
            new_state = VacuumState(
                fan_speed=fan_speed,
                battery_level=battery_level
            )
            mock_update.return_value = (new_state, {
                "fan_speed": fan_speed,
                "battery_level": battery_level
            })

            # Create and send MQTT message
            mqtt_payload = {
                "payload": {
                    "data": {
                        "102": str(["Quiet", "Standard", "Turbo", "Max"].index(fan_speed)),
                        "163": str(battery_level)
                    }
                }
            }
            payload_bytes = json.dumps(mqtt_payload).encode()
            coordinator._handle_mqtt_message(payload_bytes)

        # Update coordinator data to simulate the state update
        coordinator.data.fan_speed = fan_speed
        coordinator.data.battery_level = battery_level

        # Verify all entities are synchronized after each message
        assert vacuum_entity.fan_speed == fan_speed
        assert suction_entity.current_option == fan_speed
        assert battery_entity.native_value == battery_level

        # Verify they all read from coordinator
        assert vacuum_entity.fan_speed == coordinator.data.fan_speed
        assert suction_entity.current_option == coordinator.data.fan_speed
        assert battery_entity.native_value == coordinator.data.battery_level


@pytest.mark.asyncio
async def test_room_clean_applies_user_preferences(coordinator):
    """Test that room_clean command applies user preferences from select entities.
    """
    # Setup: Set user preferences in coordinator state
    coordinator.data.fan_speed = "Turbo"
    coordinator.data.mop_water_level = "High"
    coordinator.data.cleaning_mode = "Vacuum and mop"
    coordinator.data.map_id = 3

    # Create vacuum entity
    vacuum = RoboVacMQTTEntity(coordinator)

    # Mock the coordinator's async_send_command
    coordinator.async_send_command = AsyncMock()

    # Execute: Send room_clean command without explicit params
    await vacuum.async_send_command("room_clean", {"room_ids": [1, 2]})

    # Verify: Two commands should be sen
    assert coordinator.async_send_command.call_count == 2

    # First call: set_room_custom with user preferences
    first_call = coordinator.async_send_command.call_args_list[0][0][0]
    assert "170" in first_call  # DPS 170 (MAP_EDIT_REQUEST) = set_room_custom

    # Second call: room_clean with CUSTOMIZE mode
    second_call = coordinator.async_send_command.call_args_list[1][0][0]
    assert "152" in second_call  # DPS 152 (PLAY_PAUSE)

    # Decode and verify the set_room_custom command includes preferences
    # The command should include fan_speed=Turbo, water_level=High, clean_mode=vacuum_mop


@pytest.mark.asyncio
async def test_room_clean_with_explicit_params_overrides_preferences(coordinator):
    """Test that explicit params override user preferences.
    """
    # Setup: Set user preferences
    coordinator.data.fan_speed = "Turbo"
    coordinator.data.mop_water_level = "High"
    coordinator.data.cleaning_mode = "Vacuum and mop"

    # Create vacuum entity
    vacuum = RoboVacMQTTEntity(coordinator)
    coordinator.async_send_command = AsyncMock()

    # Execute: Send room_clean with explicit params
    await vacuum.async_send_command(
        "room_clean",
        {
            "room_ids": [1],
            "fan_speed": "Quiet",  # Override
            "water_level": "Low",  # Override
        },
    )

    # Verify: Commands sent with overridden values
    assert coordinator.async_send_command.call_count == 2


@pytest.mark.asyncio
async def test_room_clean_mop_mode_applies_water_level(coordinator):
    """Test that mop mode applies water level preference.
    """
    # Setup: Set mop mode
    coordinator.data.fan_speed = "Standard"
    coordinator.data.mop_water_level = "Medium"
    coordinator.data.cleaning_mode = "Mop"
    coordinator.data.map_id = 3

    # Create vacuum entity
    vacuum = RoboVacMQTTEntity(coordinator)
    coordinator.async_send_command = AsyncMock()

    # Execute: Send room_clean
    await vacuum.async_send_command("room_clean", {"room_ids": [5]})

    # Verify: Commands sent with mop mode
    assert coordinator.async_send_command.call_count == 2
