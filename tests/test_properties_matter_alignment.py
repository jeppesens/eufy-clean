"""Unit tests for Matter specification alignment - Room data structure validation.

This module contains unit tests to verify room data structure validation
for the Matter specification alignment implementation.

**Validates: Requirements 1.2, 1.3, 6.5**
"""

# pylint: disable=redefined-outer-name

import pytest
from custom_components.robovac_mqtt.models import VacuumState


def _normalize_room_ids(rooms):
    """Convert room IDs to strings to match vacuum entity behavior."""
    return [{"id": str(room["id"]), "name": room["name"]} for room in rooms]


def test_room_data_empty_list():
    """Test that empty room list is handled correctly.
    
    **Validates: Requirements 1.2, 1.3, 6.5**
    """
    state = VacuumState(rooms=[])
    
    # Empty list should be valid
    assert state.rooms == []
    assert isinstance(state.rooms, list)


def test_room_data_single_room_with_integer_id():
    """Test single room with integer id.
    
    **Validates: Requirements 1.2, 1.3, 6.5**
    """
    rooms = [{"id": 1, "name": "Kitchen"}]
    state = VacuumState(rooms=rooms)
    
    # Verify room structure
    assert len(state.rooms) == 1
    room = state.rooms[0]
    assert isinstance(room, dict)
    assert "id" in room
    assert "name" in room
    assert isinstance(room["id"], int)  # Original data type preserved
    assert isinstance(room["name"], str)
    assert room["id"] == 1
    assert room["name"] == "Kitchen"


def test_room_data_single_room_with_string_id():
    """Test single room with string id.
    
    **Validates: Requirements 1.2, 1.3, 6.5**
    """
    rooms = [{"id": "room_1", "name": "Living Room"}]
    state = VacuumState(rooms=rooms)
    
    # Verify room structure
    assert len(state.rooms) == 1
    room = state.rooms[0]
    assert isinstance(room, dict)
    assert "id" in room
    assert "name" in room
    assert isinstance(room["id"], str)
    assert isinstance(room["name"], str)
    assert room["id"] == "room_1"
    assert room["name"] == "Living Room"


def test_room_data_multiple_rooms_with_integer_ids():
    """Test multiple rooms with integer ids.
    
    **Validates: Requirements 1.2, 1.3, 6.5**
    """
    rooms = [
        {"id": 1, "name": "Kitchen"},
        {"id": 2, "name": "Living Room"},
        {"id": 3, "name": "Bedroom"}
    ]
    state = VacuumState(rooms=rooms)
    
    # Verify all rooms have correct structure
    assert len(state.rooms) == 3
    for room in state.rooms:
        assert isinstance(room, dict)
        assert "id" in room
        assert "name" in room
        assert isinstance(room["id"], int)  # Original data type preserved
        assert isinstance(room["name"], str)


def test_room_data_multiple_rooms_with_string_ids():
    """Test multiple rooms with string ids.
    
    **Validates: Requirements 1.2, 1.3, 6.5**
    """
    rooms = [
        {"id": "kitchen", "name": "Kitchen"},
        {"id": "living_room", "name": "Living Room"},
        {"id": "bedroom", "name": "Bedroom"}
    ]
    state = VacuumState(rooms=rooms)
    
    # Verify all rooms have correct structure
    assert len(state.rooms) == 3
    for room in state.rooms:
        assert isinstance(room, dict)
        assert "id" in room
        assert "name" in room
        assert isinstance(room["id"], str)
        assert isinstance(room["name"], str)


def test_room_data_mixed_id_types():
    """Test rooms with mixed id types (integers and strings).
    
    **Validates: Requirements 1.2, 1.3, 6.5**
    """
    rooms = [
        {"id": 1, "name": "Kitchen"},
        {"id": "living_room", "name": "Living Room"},
        {"id": 3, "name": "Bedroom"},
        {"id": "office", "name": "Office"}
    ]
    state = VacuumState(rooms=rooms)
    
    # Verify all rooms have correct structure
    assert len(state.rooms) == 4
    for room in state.rooms:
        assert isinstance(room, dict)
        assert "id" in room
        assert "name" in room
        # ID can be either int or str
        assert isinstance(room["id"], (int, str))
        assert isinstance(room["name"], str)


def test_room_data_special_characters_in_names():
    """Test rooms with special characters in names.
    
    **Validates: Requirements 1.2, 1.3, 6.5**
    """
    rooms = [
        {"id": 1, "name": "Master Bedroom #1"},
        {"id": 2, "name": "Kid's Room"},
        {"id": 3, "name": "Living & Dining"},
        {"id": 4, "name": "Hallway (2nd Floor)"}
    ]
    state = VacuumState(rooms=rooms)
    
    # Verify all rooms have correct structure
    assert len(state.rooms) == 4
    for room in state.rooms:
        assert isinstance(room, dict)
        assert "id" in room
        assert "name" in room
        assert isinstance(room["id"], (int, str))  # VacuumState stores raw types; normalisation happens at attribute layer
        assert isinstance(room["name"], str)
        # Verify names are preserved correctly
        assert len(room["name"]) > 0


def test_room_data_large_id_values():
    """Test rooms with large integer id values.
    
    **Validates: Requirements 1.2, 1.3, 6.5**
    """
    rooms = [
        {"id": 999999, "name": "Room A"},
        {"id": 1000000, "name": "Room B"}
    ]
    state = VacuumState(rooms=rooms)
    
    # Verify rooms with large IDs work correctly
    assert len(state.rooms) == 2
    for room in state.rooms:
        assert isinstance(room, dict)
        assert "id" in room
        assert "name" in room
        assert isinstance(room["id"], (int, str))  # VacuumState stores raw types; normalisation happens at attribute layer
        assert int(room["id"]) > 0  # Convert to int for numeric comparison


def test_room_data_long_names():
    """Test rooms with long names.
    
    **Validates: Requirements 1.2, 1.3, 6.5**
    """
    rooms = [
        {"id": 1, "name": "A" * 100},  # Very long name
        {"id": 2, "name": "Master Bedroom with Walk-in Closet and Ensuite Bathroom"}
    ]
    state = VacuumState(rooms=rooms)
    
    # Verify rooms with long names work correctly
    assert len(state.rooms) == 2
    for room in state.rooms:
        assert isinstance(room, dict)
        assert "id" in room
        assert "name" in room
        assert isinstance(room["name"], str)
        assert len(room["name"]) > 0


def test_room_data_unicode_names():
    """Test rooms with unicode characters in names.
    
    **Validates: Requirements 1.2, 1.3, 6.5**
    """
    rooms = [
        {"id": 1, "name": "Küche"},  # German
        {"id": 2, "name": "Salon"},  # French
        {"id": 3, "name": "客厅"},  # Chinese
        {"id": 4, "name": "リビング"}  # Japanese
    ]
    state = VacuumState(rooms=rooms)
    
    # Verify rooms with unicode names work correctly
    assert len(state.rooms) == 4
    for room in state.rooms:
        assert isinstance(room, dict)
        assert "id" in room
        assert "name" in room
        assert isinstance(room["name"], str)
        assert len(room["name"]) > 0


# ============================================================================
# Room Data Exposure Tests (Task 1.4)
# ============================================================================

def test_vacuum_entity_exposes_empty_rooms_list():
    """Test that vacuum entity exposes empty rooms list when no room data available.
    
    **Validates: Requirements 1.1, 1.4**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    # Create mock coordinator with empty rooms
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(rooms=[])
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Get extra state attributes
    attrs = entity.extra_state_attributes
    
    # Verify rooms attribute exists and is empty list
    assert "rooms" in attrs
    assert attrs["rooms"] == []
    assert isinstance(attrs["rooms"], list)


def test_vacuum_entity_exposes_single_room():
    """Test that vacuum entity exposes single room in extra_state_attributes.
    
    **Validates: Requirements 1.1**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    # Create mock coordinator with single room
    rooms = [{"id": 1, "name": "Kitchen"}]
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(rooms=rooms)
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Get extra state attributes
    attrs = entity.extra_state_attributes
    
    # Verify rooms attribute exists and contains the room
    assert "rooms" in attrs
    assert attrs["rooms"] == _normalize_room_ids(rooms)
    assert len(attrs["rooms"]) == 1
    assert attrs["rooms"][0]["id"] == "1"
    assert attrs["rooms"][0]["name"] == "Kitchen"


def test_vacuum_entity_exposes_multiple_rooms_with_integer_ids():
    """Test that vacuum entity exposes multiple rooms with integer IDs.
    
    **Validates: Requirements 1.1, 1.2, 1.3**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    # Create mock coordinator with multiple rooms
    rooms = [
        {"id": 1, "name": "Kitchen"},
        {"id": 2, "name": "Living Room"},
        {"id": 3, "name": "Bedroom"}
    ]
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(rooms=rooms)
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Get extra state attributes
    attrs = entity.extra_state_attributes
    
    # Verify rooms attribute exists and contains all rooms
    assert "rooms" in attrs
    # Convert expected rooms to string IDs to match actual behavior
    expected_rooms = [{"id": str(room["id"]), "name": room["name"]} for room in rooms]
    assert attrs["rooms"] == expected_rooms
    assert len(attrs["rooms"]) == 3
    
    # Verify each room has correct structure
    for i, room in enumerate(attrs["rooms"]):
        assert "id" in room
        assert "name" in room
        assert isinstance(room["id"], str)  # Code converts to string
        assert isinstance(room["name"], str)


def test_vacuum_entity_exposes_multiple_rooms_with_string_ids():
    """Test that vacuum entity exposes multiple rooms with string IDs.
    
    **Validates: Requirements 1.1, 1.2, 1.3**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    # Create mock coordinator with multiple rooms (string IDs)
    rooms = [
        {"id": "kitchen", "name": "Kitchen"},
        {"id": "living_room", "name": "Living Room"},
        {"id": "bedroom", "name": "Bedroom"}
    ]
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(rooms=rooms)
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Get extra state attributes
    attrs = entity.extra_state_attributes
    
    # Verify rooms attribute exists and contains all rooms
    assert "rooms" in attrs
    assert attrs["rooms"] == rooms
    assert len(attrs["rooms"]) == 3
    
    # Verify each room has correct structure
    for room in attrs["rooms"]:
        assert "id" in room
        assert "name" in room
        assert isinstance(room["id"], str)
        assert isinstance(room["name"], str)


def test_vacuum_entity_exposes_rooms_with_mixed_id_types():
    """Test that vacuum entity exposes rooms with mixed ID types.
    
    **Validates: Requirements 1.1, 1.2, 1.3**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    # Create mock coordinator with mixed ID types
    rooms = [
        {"id": 1, "name": "Kitchen"},
        {"id": "living_room", "name": "Living Room"},
        {"id": 3, "name": "Bedroom"},
        {"id": "office", "name": "Office"}
    ]
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(rooms=rooms)
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Get extra state attributes
    attrs = entity.extra_state_attributes
    
    # Verify rooms attribute exists and contains all rooms
    assert "rooms" in attrs
    assert attrs["rooms"] == _normalize_room_ids(rooms)
    assert len(attrs["rooms"]) == 4
    
    # Verify each room has correct structure
    for room in attrs["rooms"]:
        assert "id" in room
        assert "name" in room
        assert isinstance(room["id"], str)  # All IDs converted to strings
        assert isinstance(room["name"], str)


def test_vacuum_entity_exposes_rooms_with_special_characters():
    """Test that vacuum entity exposes rooms with special characters in names.
    
    **Validates: Requirements 1.1, 1.2, 1.3**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    # Create mock coordinator with special characters in room names
    rooms = [
        {"id": 1, "name": "Master Bedroom #1"},
        {"id": 2, "name": "Kid's Room"},
        {"id": 3, "name": "Living & Dining"},
        {"id": 4, "name": "Hallway (2nd Floor)"}
    ]
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(rooms=rooms)
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Get extra state attributes
    attrs = entity.extra_state_attributes
    
    # Verify rooms attribute exists and contains all rooms
    assert "rooms" in attrs
    assert attrs["rooms"] == _normalize_room_ids(rooms)
    assert len(attrs["rooms"]) == 4
    
    # Verify special characters are preserved
    for room in attrs["rooms"]:
        assert "id" in room
        assert "name" in room
        assert isinstance(room["id"], str)  # All IDs converted to strings
        assert isinstance(room["name"], str)
        assert len(room["name"]) > 0


def test_vacuum_entity_exposes_rooms_with_unicode_names():
    """Test that vacuum entity exposes rooms with unicode characters in names.
    
    **Validates: Requirements 1.1, 1.2, 1.3**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    # Create mock coordinator with unicode room names
    rooms = [
        {"id": 1, "name": "Küche"},  # German
        {"id": 2, "name": "Salon"},  # French
        {"id": 3, "name": "客厅"},  # Chinese
        {"id": 4, "name": "リビング"}  # Japanese
    ]
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(rooms=rooms)
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Get extra state attributes
    attrs = entity.extra_state_attributes
    
    # Verify rooms attribute exists and contains all rooms
    assert "rooms" in attrs
    assert attrs["rooms"] == _normalize_room_ids(rooms)
    assert len(attrs["rooms"]) == 4
    
    # Verify unicode characters are preserved
    for room in attrs["rooms"]:
        assert "id" in room
        assert "name" in room
        assert isinstance(room["name"], str)
        assert len(room["name"]) > 0


def test_vacuum_entity_handles_none_rooms():
    """Test that vacuum entity handles None rooms gracefully.
    
    **Validates: Requirements 1.4**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    # Create mock coordinator with None rooms
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(rooms=None)
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Get extra state attributes
    attrs = entity.extra_state_attributes
    
    # Verify rooms attribute exists and is empty list (not None)
    assert "rooms" in attrs
    assert attrs["rooms"] == []
    assert isinstance(attrs["rooms"], list)


def test_vacuum_entity_preserves_other_attributes():
    """Test that vacuum entity preserves other attributes when exposing rooms.
    
    **Validates: Requirements 1.1, 5.1**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    # Create mock coordinator with rooms and other attributes
    rooms = [{"id": 1, "name": "Kitchen"}]
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(
        rooms=rooms,
        fan_speed="Standard",
        cleaning_time=120,
        cleaning_area=50,
        task_status="Cleaning",
        trigger_source="app",
        error_code=0,
        error_message="",
        status_code=0
    )
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Get extra state attributes
    attrs = entity.extra_state_attributes
    
    # Verify rooms attribute exists
    assert "rooms" in attrs
    assert attrs["rooms"] == _normalize_room_ids(rooms)
    
    # Verify other attributes are preserved
    assert "fan_speed" in attrs
    assert attrs["fan_speed"] == "Standard"
    assert "cleaning_time" in attrs
    assert attrs["cleaning_time"] == 120
    assert "cleaning_area" in attrs
    assert attrs["cleaning_area"] == 50
    assert "task_status" in attrs
    assert attrs["task_status"] == "Cleaning"
    assert "trigger_source" in attrs
    assert attrs["trigger_source"] == "app"
    assert "error_code" in attrs
    assert attrs["error_code"] == 0
    assert "error_message" in attrs
    assert attrs["error_message"] == ""
    assert "status_code" in attrs
    assert attrs["status_code"] == 0


# ============================================================================
# Suction Level Command Propagation Tests (Task 2.2)
# ============================================================================

def test_suction_level_entity_sends_quiet_command():
    """Test that selecting Quiet suction level sends correct command.
    
    **Validates: Requirements 2.4**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    coordinator.async_send_command = AsyncMock()
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    
    # Select Quiet option
    import asyncio
    asyncio.run(entity.async_select_option("Quiet"))
    
    # Verify command was sent with correct parameters
    coordinator.async_send_command.assert_called_once()
    call_args = coordinator.async_send_command.call_args[0][0]
    
    # Verify command structure - should contain CLEAN_SPEED DPS key
    assert DPS_MAP["CLEAN_SPEED"] in call_args
    # Quiet is index 0 in EUFY_CLEAN_NOVEL_CLEAN_SPEED
    assert call_args[DPS_MAP["CLEAN_SPEED"]] == "0"


def test_suction_level_entity_sends_standard_command():
    """Test that selecting Standard suction level sends correct command.
    
    **Validates: Requirements 2.4**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Quiet")
    coordinator.async_send_command = AsyncMock()
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    
    # Select Standard option
    import asyncio
    asyncio.run(entity.async_select_option("Standard"))
    
    # Verify command was sent
    coordinator.async_send_command.assert_called_once()
    call_args = coordinator.async_send_command.call_args[0][0]
    
    # Verify command structure - should contain CLEAN_SPEED DPS key
    assert DPS_MAP["CLEAN_SPEED"] in call_args
    # Standard is index 1 in EUFY_CLEAN_NOVEL_CLEAN_SPEED
    assert call_args[DPS_MAP["CLEAN_SPEED"]] == "1"


def test_suction_level_entity_sends_turbo_command():
    """Test that selecting Turbo suction level sends correct command.
    
    **Validates: Requirements 2.4**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    coordinator.async_send_command = AsyncMock()
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    
    # Select Turbo option
    import asyncio
    asyncio.run(entity.async_select_option("Turbo"))
    
    # Verify command was sent
    coordinator.async_send_command.assert_called_once()
    call_args = coordinator.async_send_command.call_args[0][0]
    
    # Verify command structure - should contain CLEAN_SPEED DPS key
    assert DPS_MAP["CLEAN_SPEED"] in call_args
    # Turbo is index 2 in EUFY_CLEAN_NOVEL_CLEAN_SPEED
    assert call_args[DPS_MAP["CLEAN_SPEED"]] == "2"


def test_suction_level_entity_sends_max_command():
    """Test that selecting Max suction level sends correct command.
    
    **Validates: Requirements 2.4**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Turbo")
    coordinator.async_send_command = AsyncMock()
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    
    # Select Max option
    import asyncio
    asyncio.run(entity.async_select_option("Max"))
    
    # Verify command was sent
    coordinator.async_send_command.assert_called_once()
    call_args = coordinator.async_send_command.call_args[0][0]
    
    # Verify command structure - should contain CLEAN_SPEED DPS key
    assert DPS_MAP["CLEAN_SPEED"] in call_args
    # Max is index 3 in EUFY_CLEAN_NOVEL_CLEAN_SPEED
    assert call_args[DPS_MAP["CLEAN_SPEED"]] == "3"


def test_suction_level_entity_rejects_invalid_option():
    """Test that selecting an invalid suction level does not send command.
    
    **Validates: Requirements 2.4**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    coordinator.async_send_command = AsyncMock()
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Try to select invalid option
    import asyncio
    asyncio.run(entity.async_select_option("InvalidSpeed"))
    
    # Verify command was NOT sent
    coordinator.async_send_command.assert_not_called()


def test_suction_level_entity_all_valid_options():
    """Test that all valid suction level options send commands.
    
    **Validates: Requirements 2.4**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    # Valid options from EUFY_CLEAN_NOVEL_CLEAN_SPEED
    valid_options = ["Quiet", "Standard", "Turbo", "Max"]
    expected_indices = ["0", "1", "2", "3"]
    
    for option, expected_index in zip(valid_options, expected_indices):
        # Create fresh mock coordinator for each test
        coordinator = MagicMock()
        coordinator.device_id = "test_device"
        coordinator.device_name = "Test Vacuum"
        coordinator.device_model = "T2118"
        coordinator.data = VacuumState(fan_speed="Standard")
        coordinator.async_send_command = AsyncMock()
        
        # Create suction level entity
        entity = SuctionLevelSelectEntity(coordinator)
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()
        
        # Select option
        import asyncio
        asyncio.run(entity.async_select_option(option))
        
        # Verify command was sent
        coordinator.async_send_command.assert_called_once()
        call_args = coordinator.async_send_command.call_args[0][0]
        
        # Verify command structure
        assert DPS_MAP["CLEAN_SPEED"] in call_args, f"Missing CLEAN_SPEED for option {option}"
        assert call_args[DPS_MAP["CLEAN_SPEED"]] == expected_index, f"Wrong index for option {option}"


def test_suction_level_entity_command_with_different_initial_states():
    """Test that commands are sent correctly regardless of initial fan speed state.
    
    **Validates: Requirements 2.4**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    initial_states = ["Quiet", "Standard", "Turbo", "Max"]
    target_option = "Turbo"
    
    for initial_state in initial_states:
        # Create mock coordinator with different initial state
        coordinator = MagicMock()
        coordinator.device_id = "test_device"
        coordinator.device_name = "Test Vacuum"
        coordinator.device_model = "T2118"
        coordinator.data = VacuumState(fan_speed=initial_state)
        coordinator.async_send_command = AsyncMock()
        
        # Create suction level entity
        entity = SuctionLevelSelectEntity(coordinator)
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()
        
        # Select target option
        import asyncio
        asyncio.run(entity.async_select_option(target_option))
        
        # Verify command was sent
        coordinator.async_send_command.assert_called_once()
        call_args = coordinator.async_send_command.call_args[0][0]
        
        # Verify command structure
        assert DPS_MAP["CLEAN_SPEED"] in call_args
        # Turbo is index 2
        assert call_args[DPS_MAP["CLEAN_SPEED"]] == "2"


def test_suction_level_entity_case_sensitive_validation():
    """Test that option validation is case-sensitive.
    
    **Validates: Requirements 2.4**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    coordinator.async_send_command = AsyncMock()
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    
    # Try lowercase (should fail)
    import asyncio
    asyncio.run(entity.async_select_option("quiet"))
    coordinator.async_send_command.assert_not_called()
    
    # Try uppercase (should fail)
    asyncio.run(entity.async_select_option("QUIET"))
    coordinator.async_send_command.assert_not_called()
    
    # Try correct case (should succeed)
    asyncio.run(entity.async_select_option("Quiet"))
    coordinator.async_send_command.assert_called_once()


# ============================================================================
# Suction Level State Reflection Tests (Task 2.3)
# ============================================================================

def test_suction_level_entity_reflects_quiet_state():
    """Test that suction level entity reflects Quiet fan speed from coordinator.
    
    **Validates: Requirements 2.5**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator with Quiet fan speed
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Quiet")
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Verify current_option matches coordinator fan_speed
    assert entity.current_option == "Quiet"
    assert entity.current_option == coordinator.data.fan_speed


def test_suction_level_entity_reflects_standard_state():
    """Test that suction level entity reflects Standard fan speed from coordinator.
    
    **Validates: Requirements 2.5**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator with Standard fan speed
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Verify current_option matches coordinator fan_speed
    assert entity.current_option == "Standard"
    assert entity.current_option == coordinator.data.fan_speed


def test_suction_level_entity_reflects_turbo_state():
    """Test that suction level entity reflects Turbo fan speed from coordinator.
    
    **Validates: Requirements 2.5**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator with Turbo fan speed
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Turbo")
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Verify current_option matches coordinator fan_speed
    assert entity.current_option == "Turbo"
    assert entity.current_option == coordinator.data.fan_speed


def test_suction_level_entity_reflects_max_state():
    """Test that suction level entity reflects Max fan speed from coordinator.
    
    **Validates: Requirements 2.5**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator with Max fan speed
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Max")
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Verify current_option matches coordinator fan_speed
    assert entity.current_option == "Max"
    assert entity.current_option == coordinator.data.fan_speed


def test_suction_level_entity_reflects_all_valid_fan_speeds():
    """Test that suction level entity reflects all valid fan speed values.
    
    **Validates: Requirements 2.5**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Test all valid fan speeds
    valid_fan_speeds = ["Quiet", "Standard", "Turbo", "Max"]
    
    for fan_speed in valid_fan_speeds:
        # Create mock coordinator with specific fan speed
        coordinator = MagicMock()
        coordinator.device_id = "test_device"
        coordinator.device_name = "Test Vacuum"
        coordinator.device_model = "T2118"
        coordinator.data = VacuumState(fan_speed=fan_speed)
        
        # Create suction level entity
        entity = SuctionLevelSelectEntity(coordinator)
        
        # Verify current_option matches coordinator fan_speed
        assert entity.current_option == fan_speed, f"Failed for fan_speed={fan_speed}"
        assert entity.current_option == coordinator.data.fan_speed


def test_suction_level_entity_reflects_none_state():
    """Test that suction level entity handles None fan speed gracefully.
    
    **Validates: Requirements 2.5**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator with None fan speed
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed=None)
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Verify current_option is None
    assert entity.current_option is None
    assert entity.current_option == coordinator.data.fan_speed


def test_suction_level_entity_state_updates_with_coordinator():
    """Test that suction level entity state updates when coordinator data changes.
    
    **Validates: Requirements 2.5, 2.6**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator with initial fan speed
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Quiet")
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Verify initial state
    assert entity.current_option == "Quiet"
    
    # Update coordinator data to new fan speed
    coordinator.data = VacuumState(fan_speed="Turbo")
    
    # Verify entity reflects new state
    assert entity.current_option == "Turbo"
    assert entity.current_option == coordinator.data.fan_speed


def test_suction_level_entity_state_reflects_multiple_changes():
    """Test that suction level entity reflects multiple fan speed changes.
    
    **Validates: Requirements 2.5, 2.6**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Quiet")
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Test sequence of fan speed changes
    fan_speed_sequence = ["Quiet", "Standard", "Turbo", "Max", "Standard", "Quiet"]
    
    for fan_speed in fan_speed_sequence:
        # Update coordinator data
        coordinator.data = VacuumState(fan_speed=fan_speed)
        
        # Verify entity reflects current state
        assert entity.current_option == fan_speed
        assert entity.current_option == coordinator.data.fan_speed


def test_suction_level_entity_state_independent_of_other_attributes():
    """Test that suction level entity state is independent of other coordinator attributes.
    
    **Validates: Requirements 2.5**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator with various attributes
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(
        fan_speed="Turbo",
        cleaning_mode="Vacuum",
        battery_level=75,
        task_status="Cleaning",
        rooms=[{"id": 1, "name": "Kitchen"}]
    )
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Verify entity only reflects fan_speed, not other attributes
    assert entity.current_option == "Turbo"
    assert entity.current_option == coordinator.data.fan_speed
    
    # Update other attributes but keep fan_speed same
    coordinator.data = VacuumState(
        fan_speed="Turbo",
        cleaning_mode="Mop",
        battery_level=50,
        task_status="Idle",
        rooms=[]
    )
    
    # Verify entity still reflects correct fan_speed
    assert entity.current_option == "Turbo"


def test_suction_level_entity_state_with_empty_string():
    """Test that suction level entity handles empty string fan speed.
    
    **Validates: Requirements 2.5**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator with empty string fan speed
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="")
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Verify current_option is empty string
    assert entity.current_option == ""
    assert entity.current_option == coordinator.data.fan_speed


# ============================================================================
# Vacuum Entity Backward Compatibility Tests (Task 8.1)
# ============================================================================

def test_vacuum_entity_async_set_fan_speed_quiet():
    """Test that async_set_fan_speed method works for Quiet fan speed.
    
    **Validates: Requirements 5.2**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    coordinator.async_send_command = AsyncMock()
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Call async_set_fan_speed
    import asyncio
    asyncio.run(entity.async_set_fan_speed("Quiet"))
    
    # Verify command was sent
    coordinator.async_send_command.assert_called_once()
    call_args = coordinator.async_send_command.call_args[0][0]
    
    # Verify command structure
    assert DPS_MAP["CLEAN_SPEED"] in call_args
    assert call_args[DPS_MAP["CLEAN_SPEED"]] == "0"


def test_vacuum_entity_async_set_fan_speed_standard():
    """Test that async_set_fan_speed method works for Standard fan speed.
    
    **Validates: Requirements 5.2**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Quiet")
    coordinator.async_send_command = AsyncMock()
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Call async_set_fan_speed
    import asyncio
    asyncio.run(entity.async_set_fan_speed("Standard"))
    
    # Verify command was sent
    coordinator.async_send_command.assert_called_once()
    call_args = coordinator.async_send_command.call_args[0][0]
    
    # Verify command structure
    assert DPS_MAP["CLEAN_SPEED"] in call_args
    assert call_args[DPS_MAP["CLEAN_SPEED"]] == "1"


def test_vacuum_entity_async_set_fan_speed_turbo():
    """Test that async_set_fan_speed method works for Turbo fan speed.
    
    **Validates: Requirements 5.2**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    coordinator.async_send_command = AsyncMock()
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Call async_set_fan_speed
    import asyncio
    asyncio.run(entity.async_set_fan_speed("Turbo"))
    
    # Verify command was sent
    coordinator.async_send_command.assert_called_once()
    call_args = coordinator.async_send_command.call_args[0][0]
    
    # Verify command structure
    assert DPS_MAP["CLEAN_SPEED"] in call_args
    assert call_args[DPS_MAP["CLEAN_SPEED"]] == "2"


def test_vacuum_entity_async_set_fan_speed_max():
    """Test that async_set_fan_speed method works for Max fan speed.
    
    **Validates: Requirements 5.2**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Turbo")
    coordinator.async_send_command = AsyncMock()
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Call async_set_fan_speed
    import asyncio
    asyncio.run(entity.async_set_fan_speed("Max"))
    
    # Verify command was sent
    coordinator.async_send_command.assert_called_once()
    call_args = coordinator.async_send_command.call_args[0][0]
    
    # Verify command structure
    assert DPS_MAP["CLEAN_SPEED"] in call_args
    assert call_args[DPS_MAP["CLEAN_SPEED"]] == "3"


def test_vacuum_entity_async_set_fan_speed_all_valid_speeds():
    """Test that async_set_fan_speed works for all valid fan speeds.
    
    **Validates: Requirements 5.2**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    # Test all valid fan speeds
    valid_speeds = ["Quiet", "Standard", "Turbo", "Max"]
    expected_indices = ["0", "1", "2", "3"]
    
    for speed, expected_index in zip(valid_speeds, expected_indices):
        # Create fresh mock coordinator
        coordinator = MagicMock()
        coordinator.device_id = "test_device"
        coordinator.device_name = "Test Vacuum"
        coordinator.device_model = "T2118"
        coordinator.data = VacuumState(fan_speed="Standard")
        coordinator.async_send_command = AsyncMock()
        
        # Create vacuum entity
        entity = RoboVacMQTTEntity(coordinator)
        
        # Call async_set_fan_speed
        import asyncio
        asyncio.run(entity.async_set_fan_speed(speed))
        
        # Verify command was sent
        coordinator.async_send_command.assert_called_once()
        call_args = coordinator.async_send_command.call_args[0][0]
        
        # Verify command structure
        assert DPS_MAP["CLEAN_SPEED"] in call_args, f"Missing CLEAN_SPEED for speed {speed}"
        assert call_args[DPS_MAP["CLEAN_SPEED"]] == expected_index, f"Wrong index for speed {speed}"


def test_vacuum_entity_async_set_fan_speed_rejects_invalid():
    """Test that async_set_fan_speed rejects invalid fan speeds.
    
    **Validates: Requirements 5.2**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    coordinator.async_send_command = AsyncMock()
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Try to set invalid fan speed
    import asyncio
    with pytest.raises(ValueError, match="Fan speed .* not supported"):
        asyncio.run(entity.async_set_fan_speed("InvalidSpeed"))
    
    # Verify command was NOT sent
    coordinator.async_send_command.assert_not_called()


def test_vacuum_entity_send_command_scene_clean():
    """Test that send_command works for scene_clean with existing parameter format.
    
    **Validates: Requirements 5.3**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState()
    coordinator.async_send_command = AsyncMock()
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Call send_command with scene_clean
    import asyncio
    asyncio.run(entity.async_send_command("scene_clean", {"scene_id": 5}))
    
    # Verify command was sent
    coordinator.async_send_command.assert_called_once()
    call_args = coordinator.async_send_command.call_args[0][0]
    
    # Verify command structure - scene_clean uses PLAY_PAUSE DPS
    assert DPS_MAP["PLAY_PAUSE"] in call_args
    assert isinstance(call_args[DPS_MAP["PLAY_PAUSE"]], str)
    # The command is encoded, so we just verify it's not empty
    assert len(call_args[DPS_MAP["PLAY_PAUSE"]]) > 0


def test_vacuum_entity_send_command_scene_clean_multiple_scenes():
    """Test that send_command works for multiple scene IDs.
    
    **Validates: Requirements 5.3**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    # Test multiple scene IDs
    scene_ids = [1, 2, 3, 5, 10]
    
    for scene_id in scene_ids:
        # Create fresh mock coordinator
        coordinator = MagicMock()
        coordinator.device_id = "test_device"
        coordinator.device_name = "Test Vacuum"
        coordinator.device_model = "T2118"
        coordinator.data = VacuumState()
        coordinator.async_send_command = AsyncMock()
        
        # Create vacuum entity
        entity = RoboVacMQTTEntity(coordinator)
        
        # Call send_command with scene_clean
        import asyncio
        asyncio.run(entity.async_send_command("scene_clean", {"scene_id": scene_id}))
        
        # Verify command was sent
        coordinator.async_send_command.assert_called_once()
        call_args = coordinator.async_send_command.call_args[0][0]
        
        # Verify command structure - scene_clean uses PLAY_PAUSE DPS
        assert DPS_MAP["PLAY_PAUSE"] in call_args, f"Missing PLAY_PAUSE for scene {scene_id}"
        assert isinstance(call_args[DPS_MAP["PLAY_PAUSE"]], str)
        assert len(call_args[DPS_MAP["PLAY_PAUSE"]]) > 0


def test_vacuum_entity_send_command_room_clean_simple():
    """Test that send_command works for room_clean with simple room_ids parameter.
    
    **Validates: Requirements 5.3**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(map_id=1)
    coordinator.async_send_command = AsyncMock()
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Call send_command with room_clean (simple format)
    import asyncio
    asyncio.run(entity.async_send_command("room_clean", {"room_ids": [1, 2, 3]}))
    
    # Verify command was sent
    coordinator.async_send_command.assert_called_once()
    call_args = coordinator.async_send_command.call_args[0][0]
    
    # Verify command structure - room_clean uses PLAY_PAUSE DPS
    assert DPS_MAP["PLAY_PAUSE"] in call_args
    assert isinstance(call_args[DPS_MAP["PLAY_PAUSE"]], str)
    assert len(call_args[DPS_MAP["PLAY_PAUSE"]]) > 0


def test_vacuum_entity_send_command_room_clean_with_map_id():
    """Test that send_command works for room_clean with explicit map_id.
    
    **Validates: Requirements 5.3**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(map_id=1)
    coordinator.async_send_command = AsyncMock()
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Call send_command with room_clean and explicit map_id
    import asyncio
    asyncio.run(entity.async_send_command("room_clean", {"room_ids": [1, 2], "map_id": 2}))
    
    # Verify command was sent
    coordinator.async_send_command.assert_called_once()
    call_args = coordinator.async_send_command.call_args[0][0]
    
    # Verify command structure - room_clean uses PLAY_PAUSE DPS
    assert DPS_MAP["PLAY_PAUSE"] in call_args
    assert isinstance(call_args[DPS_MAP["PLAY_PAUSE"]], str)
    assert len(call_args[DPS_MAP["PLAY_PAUSE"]]) > 0


def test_vacuum_entity_send_command_room_clean_with_custom_params():
    """Test that send_command works for room_clean with custom parameters.
    
    **Validates: Requirements 5.3**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(map_id=1)
    coordinator.async_send_command = AsyncMock()
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Call send_command with room_clean and custom parameters
    import asyncio
    asyncio.run(entity.async_send_command(
        "room_clean",
        {
            "room_ids": [1, 2],
            "fan_speed": "Turbo",
            "water_level": "Medium",
            "clean_times": 2
        }
    ))
    
    # Verify two commands were sent (set_room_custom + room_clean)
    assert coordinator.async_send_command.call_count == 2
    
    # First call should be set_room_custom - uses MAP_EDIT_REQUEST DPS
    first_call_args = coordinator.async_send_command.call_args_list[0][0][0]
    assert DPS_MAP["MAP_EDIT_REQUEST"] in first_call_args
    
    # Second call should be room_clean - uses PLAY_PAUSE DPS
    second_call_args = coordinator.async_send_command.call_args_list[1][0][0]
    assert DPS_MAP["PLAY_PAUSE"] in second_call_args


def test_vacuum_entity_send_command_room_clean_with_rooms_config():
    """Test that send_command works for room_clean with rooms configuration.
    
    **Validates: Requirements 5.3**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(map_id=1)
    coordinator.async_send_command = AsyncMock()
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Call send_command with room_clean and rooms configuration
    rooms_config = [
        {"id": 1, "fan_speed": "Turbo", "water_level": "Medium"},
        {"id": 2, "fan_speed": "Max", "water_level": "High"}
    ]
    import asyncio
    asyncio.run(entity.async_send_command("room_clean", {"rooms": rooms_config}))
    
    # Verify two commands were sent (set_room_custom + room_clean)
    assert coordinator.async_send_command.call_count == 2
    
    # First call should be set_room_custom - uses MAP_EDIT_REQUEST DPS
    first_call_args = coordinator.async_send_command.call_args_list[0][0][0]
    assert DPS_MAP["MAP_EDIT_REQUEST"] in first_call_args
    
    # Second call should be room_clean - uses PLAY_PAUSE DPS
    second_call_args = coordinator.async_send_command.call_args_list[1][0][0]
    assert DPS_MAP["PLAY_PAUSE"] in second_call_args


def test_vacuum_entity_send_command_room_clean_multiple_room_combinations():
    """Test that send_command works for various room ID combinations.
    
    **Validates: Requirements 5.3**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.const import DPS_MAP
    
    # Test various room ID combinations
    room_combinations = [
        [1],
        [1, 2],
        [1, 2, 3],
        [5, 10, 15],
        [1, 2, 3, 4, 5]
    ]
    
    for room_ids in room_combinations:
        # Create fresh mock coordinator
        coordinator = MagicMock()
        coordinator.device_id = "test_device"
        coordinator.device_name = "Test Vacuum"
        coordinator.device_model = "T2118"
        coordinator.data = VacuumState(map_id=1)
        coordinator.async_send_command = AsyncMock()
        
        # Create vacuum entity
        entity = RoboVacMQTTEntity(coordinator)
        
        # Call send_command with room_clean
        import asyncio
        asyncio.run(entity.async_send_command("room_clean", {"room_ids": room_ids}))
        
        # Verify command was sent
        coordinator.async_send_command.assert_called_once()
        call_args = coordinator.async_send_command.call_args[0][0]
        
        # Verify command structure - room_clean uses PLAY_PAUSE DPS
        assert DPS_MAP["PLAY_PAUSE"] in call_args, f"Missing PLAY_PAUSE for rooms {room_ids}"
        assert isinstance(call_args[DPS_MAP["PLAY_PAUSE"]], str)
        assert len(call_args[DPS_MAP["PLAY_PAUSE"]]) > 0


def test_vacuum_entity_send_command_preserves_parameter_format():
    """Test that send_command preserves existing parameter formats unchanged.
    
    **Validates: Requirements 5.3**
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(map_id=1)
    coordinator.async_send_command = AsyncMock()
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Test scene_clean parameter format
    import asyncio
    scene_params = {"scene_id": 5}
    asyncio.run(entity.async_send_command("scene_clean", scene_params))
    coordinator.async_send_command.assert_called_once()
    
    # Reset mock
    coordinator.async_send_command.reset_mock()
    
    # Test room_clean parameter format
    room_params = {"room_ids": [1, 2, 3], "map_id": 1}
    asyncio.run(entity.async_send_command("room_clean", room_params))
    coordinator.async_send_command.assert_called_once()
    
    # Reset mock
    coordinator.async_send_command.reset_mock()
    
    # Test room_clean with custom parameters format
    custom_params = {
        "room_ids": [1, 2],
        "fan_speed": "Turbo",
        "water_level": "Medium",
        "clean_times": 2,
        "clean_mode": "Vacuum",
        "clean_intensity": "Standard",
        "edge_mopping": True
    }
    asyncio.run(entity.async_send_command("room_clean", custom_params))
    # Should send two commands (set_room_custom + room_clean)
    assert coordinator.async_send_command.call_count == 2


def test_vacuum_entity_fan_speed_property_unchanged():
    """Test that fan_speed property remains unchanged and functional.
    
    **Validates: Requirements 5.2**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    # Test all valid fan speeds
    fan_speeds = ["Quiet", "Standard", "Turbo", "Max"]
    
    for fan_speed in fan_speeds:
        # Create mock coordinator with specific fan speed
        coordinator = MagicMock()
        coordinator.device_id = "test_device"
        coordinator.device_name = "Test Vacuum"
        coordinator.device_model = "T2118"
        coordinator.data = VacuumState(fan_speed=fan_speed)
        
        # Create vacuum entity
        entity = RoboVacMQTTEntity(coordinator)
        
        # Verify fan_speed property returns correct value
        assert entity.fan_speed == fan_speed
        assert entity.fan_speed == coordinator.data.fan_speed


def test_vacuum_entity_fan_speed_list_unchanged():
    """Test that fan_speed_list property remains unchanged.
    
    **Validates: Requirements 5.2**
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState()
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Verify fan_speed_list contains expected values
    expected_speeds = ["Quiet", "Standard", "Turbo", "Max"]
    assert entity.fan_speed_list == expected_speeds
    
    # Verify all expected speeds are present
    for speed in expected_speeds:
        assert speed in entity.fan_speed_list


# ============================================================================
# Fan Speed Capability Adaptation Tests (Task 8.2)
# Property 11: Fan Speed Capability Adaptation
# ============================================================================

def test_suction_level_entity_options_match_device_capabilities():
    """Test that suction level entity options match device fan speed capabilities.
    
    **Property 11: Fan Speed Capability Adaptation**
    **Validates: Requirements 7.3**
    
    This test verifies that the suction level entity only exposes fan speed
    options that are supported by the device. The options list should be
    derived from the device's capabilities, not a hardcoded list.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    from custom_components.robovac_mqtt.const import EUFY_CLEAN_NOVEL_CLEAN_SPEED
    
    # Create mock coordinator with standard device
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"  # Standard model
    coordinator.data = VacuumState(fan_speed="Standard")
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Verify options list matches device capabilities
    # For standard devices, should have all 4 speeds from EUFY_CLEAN_NOVEL_CLEAN_SPEED
    expected_options = [speed.value for speed in EUFY_CLEAN_NOVEL_CLEAN_SPEED]
    assert entity.options == expected_options
    assert len(entity.options) == 4
    assert "Quiet" in entity.options
    assert "Standard" in entity.options
    assert "Turbo" in entity.options
    assert "Max" in entity.options


def test_suction_level_entity_options_are_subset_of_valid_speeds():
    """Test that suction level entity options are always a subset of valid speeds.
    
    **Property 11: Fan Speed Capability Adaptation**
    **Validates: Requirements 7.3**
    
    This test verifies that regardless of device model, the options list
    only contains valid fan speed values and doesn't include unsupported speeds.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    from custom_components.robovac_mqtt.const import EUFY_CLEAN_NOVEL_CLEAN_SPEED
    
    # Test multiple device models
    device_models = [
        "T2118",  # RoboVac 30C
        "T2150",  # G10 Hybrid
        "T2181",  # LR30 Hybrid+
        "T2262",  # Non-mopping model
    ]
    
    # All valid fan speeds from the constant
    all_valid_speeds = [speed.value for speed in EUFY_CLEAN_NOVEL_CLEAN_SPEED]
    
    for model in device_models:
        # Create mock coordinator for each model
        coordinator = MagicMock()
        coordinator.device_id = f"test_device_{model}"
        coordinator.device_name = f"Test Vacuum {model}"
        coordinator.device_model = model
        coordinator.data = VacuumState(fan_speed="Standard")
        
        # Create suction level entity
        entity = SuctionLevelSelectEntity(coordinator)
        
        # Verify all options are valid speeds
        for option in entity.options:
            assert option in all_valid_speeds, f"Invalid option '{option}' for model {model}"
        
        # Verify options list is not empty
        assert len(entity.options) > 0, f"Empty options list for model {model}"


def test_suction_level_entity_options_consistent_across_instances():
    """Test that suction level entity options are consistent for same device model.
    
    **Property 11: Fan Speed Capability Adaptation**
    **Validates: Requirements 7.3**
    
    This test verifies that multiple instances of the same device model
    have the same fan speed options list.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    device_model = "T2118"
    
    # Create multiple coordinators for the same model
    entities = []
    for i in range(5):
        coordinator = MagicMock()
        coordinator.device_id = f"test_device_{i}"
        coordinator.device_name = f"Test Vacuum {i}"
        coordinator.device_model = device_model
        coordinator.data = VacuumState(fan_speed="Standard")
        
        entity = SuctionLevelSelectEntity(coordinator)
        entities.append(entity)
    
    # Verify all entities have the same options list
    first_options = entities[0].options
    for entity in entities[1:]:
        assert entity.options == first_options, "Options list should be consistent for same model"


def test_suction_level_entity_options_do_not_include_invalid_speeds():
    """Test that suction level entity options do not include invalid or unsupported speeds.
    
    **Property 11: Fan Speed Capability Adaptation**
    **Validates: Requirements 7.3**
    
    This test verifies that the options list does not contain invalid speeds
    like empty strings, None, or arbitrary values.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Verify no invalid values in options
    invalid_values = ["", None, "Invalid", "Unknown", "Auto", "Custom"]
    for invalid_value in invalid_values:
        assert invalid_value not in entity.options, f"Invalid value '{invalid_value}' should not be in options"
    
    # Verify all options are non-empty strings
    for option in entity.options:
        assert isinstance(option, str), f"Option '{option}' should be a string"
        assert len(option) > 0, f"Option should not be empty string"


def test_suction_level_entity_current_option_is_in_options_list():
    """Test that current_option is always in the options list when not None.
    
    **Property 11: Fan Speed Capability Adaptation**
    **Validates: Requirements 7.3**
    
    This test verifies that the current fan speed is always one of the
    available options, ensuring consistency between device state and
    available capabilities.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    from custom_components.robovac_mqtt.const import EUFY_CLEAN_NOVEL_CLEAN_SPEED
    
    # Test all valid fan speeds
    valid_speeds = [speed.value for speed in EUFY_CLEAN_NOVEL_CLEAN_SPEED]
    
    for fan_speed in valid_speeds:
        # Create mock coordinator with specific fan speed
        coordinator = MagicMock()
        coordinator.device_id = "test_device"
        coordinator.device_name = "Test Vacuum"
        coordinator.device_model = "T2118"
        coordinator.data = VacuumState(fan_speed=fan_speed)
        
        # Create suction level entity
        entity = SuctionLevelSelectEntity(coordinator)
        
        # Verify current_option is in options list
        if entity.current_option is not None:
            assert entity.current_option in entity.options, \
                f"Current option '{entity.current_option}' should be in options list"


def test_suction_level_entity_options_order_is_consistent():
    """Test that suction level entity options maintain consistent ordering.
    
    **Property 11: Fan Speed Capability Adaptation**
    **Validates: Requirements 7.3**
    
    This test verifies that the options list maintains a consistent order
    (typically from lowest to highest intensity) for better UX.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    from custom_components.robovac_mqtt.const import EUFY_CLEAN_NOVEL_CLEAN_SPEED
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Expected order from EUFY_CLEAN_NOVEL_CLEAN_SPEED
    expected_order = [speed.value for speed in EUFY_CLEAN_NOVEL_CLEAN_SPEED]
    
    # Verify options match expected order
    assert entity.options == expected_order, "Options should maintain consistent order"


def test_suction_level_entity_options_immutable_after_creation():
    """Test that suction level entity options list doesn't change after creation.
    
    **Property 11: Fan Speed Capability Adaptation**
    **Validates: Requirements 7.3**
    
    This test verifies that the options list is determined at entity creation
    and remains stable throughout the entity's lifetime.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Store initial options
    initial_options = entity.options.copy()
    
    # Simulate state changes
    coordinator.data = VacuumState(fan_speed="Turbo")
    coordinator.data = VacuumState(fan_speed="Max")
    coordinator.data = VacuumState(fan_speed="Quiet")
    
    # Verify options haven't changed
    assert entity.options == initial_options, "Options list should remain stable after creation"


def test_suction_level_entity_rejects_options_not_in_list():
    """Test that suction level entity rejects fan speeds not in options list.
    
    **Property 11: Fan Speed Capability Adaptation**
    **Validates: Requirements 7.3**
    
    This test verifies that attempting to select a fan speed not in the
    options list is properly rejected and doesn't send a command.
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    coordinator.async_send_command = AsyncMock()
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Get valid options
    valid_options = entity.options
    
    # Try to select speeds not in options list
    invalid_speeds = ["SuperMax", "UltraQuiet", "Boost", "Eco", "Auto"]
    
    for invalid_speed in invalid_speeds:
        # Make sure it's not in valid options
        if invalid_speed not in valid_options:
            # Reset mock
            coordinator.async_send_command.reset_mock()
            
            # Try to select invalid speed
            import asyncio
            asyncio.run(entity.async_select_option(invalid_speed))
            
            # Verify command was NOT sent
            coordinator.async_send_command.assert_not_called()


def test_suction_level_entity_accepts_all_options_in_list():
    """Test that suction level entity accepts all fan speeds in options list.
    
    **Property 11: Fan Speed Capability Adaptation**
    **Validates: Requirements 7.3**
    
    This test verifies that all speeds in the options list can be successfully
    selected and result in a command being sent.
    """
    from unittest.mock import AsyncMock, MagicMock, Mock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    coordinator.async_send_command = AsyncMock()
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Mock async_write_ha_state to avoid Home Assistant setup requirement
    entity.async_write_ha_state = Mock()
    
    # Try to select each option in the list
    for option in entity.options:
        # Reset mock
        coordinator.async_send_command.reset_mock()
        
        # Select option
        import asyncio
        asyncio.run(entity.async_select_option(option))
        
        # Verify command was sent
        coordinator.async_send_command.assert_called_once(), \
            f"Command should be sent for valid option '{option}'"


# ============================================================================
# Property-Based Tests converted to Parameterized Tests (Task 8.2)
# Property 11: Fan Speed Capability Adaptation
# ============================================================================

@pytest.mark.parametrize("device_model,initial_fan_speed", [
    ("T2118", "Quiet"),
    ("T2118", "Standard"),
    ("T2118", "Turbo"),
    ("T2118", "Max"),
    ("T2150", "Quiet"),
    ("T2150", "Standard"),
    ("T2150", "Turbo"),
    ("T2150", "Max"),
    ("T2181", "Quiet"),
    ("T2181", "Standard"),
    ("T2181", "Turbo"),
    ("T2181", "Max"),
    ("T2262", "Quiet"),
    ("T2262", "Standard"),
    ("T2262", "Turbo"),
    ("T2262", "Max"),
    ("T2320", "Quiet"),
    ("T2320", "Standard"),
    ("T2320", "Turbo"),
    ("T2320", "Max"),
])
def test_property_fan_speed_options_always_valid(device_model: str, initial_fan_speed: str):
    """Property test: Fan speed options are always valid for any device model.
    
    **Property 11: Fan Speed Capability Adaptation**
    **Validates: Requirements 7.3**
    
    This property-based test verifies that regardless of device model,
    the suction level entity always provides a valid, non-empty list of
    fan speed options that are consistent with the device capabilities.
    
    Tests 20 combinations of device models and initial fan speeds.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    from custom_components.robovac_mqtt.const import EUFY_CLEAN_NOVEL_CLEAN_SPEED
    
    # Create mock coordinator with random device model and fan speed
    coordinator = MagicMock()
    coordinator.device_id = f"test_device_{device_model}"
    coordinator.device_name = f"Test Vacuum {device_model}"
    coordinator.device_model = device_model
    coordinator.data = VacuumState(fan_speed=initial_fan_speed)
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Property 1: Options list is not empty
    assert len(entity.options) > 0, "Options list should never be empty"
    
    # Property 2: All options are valid fan speeds
    all_valid_speeds = [speed.value for speed in EUFY_CLEAN_NOVEL_CLEAN_SPEED]
    for option in entity.options:
        assert option in all_valid_speeds, f"Option '{option}' should be a valid fan speed"
    
    # Property 3: All options are strings
    for option in entity.options:
        assert isinstance(option, str), f"Option '{option}' should be a string"
        assert len(option) > 0, "Option should not be empty string"
    
    # Property 4: Options list has no duplicates
    assert len(entity.options) == len(set(entity.options)), "Options list should have no duplicates"
    
    # Property 5: Current option (if not None) is in options list
    if entity.current_option is not None:
        assert entity.current_option in entity.options, \
            f"Current option '{entity.current_option}' should be in options list"


@pytest.mark.parametrize("fan_speed_sequence", [
    ["Quiet"],
    ["Standard", "Turbo"],
    ["Max", "Quiet", "Standard"],
    ["Turbo", "Max", "Quiet", "Standard"],
    ["Quiet", "Standard", "Turbo", "Max", "Quiet"],
    ["Max", "Turbo", "Standard", "Quiet", "Max", "Turbo"],
    ["Standard", "Standard", "Standard"],
    ["Quiet", "Max", "Quiet", "Max"],
    ["Turbo", "Quiet", "Max", "Standard", "Turbo"],
    ["Max", "Max", "Quiet", "Quiet", "Standard", "Standard"],
    ["Quiet", "Standard", "Turbo", "Max", "Max", "Turbo", "Standard", "Quiet"],
    ["Standard", "Turbo", "Standard", "Turbo", "Standard"],
    ["Max", "Quiet", "Standard", "Turbo", "Max", "Quiet"],
    ["Turbo", "Turbo", "Max", "Max", "Quiet"],
    ["Quiet", "Quiet", "Quiet", "Standard", "Turbo", "Max"],
])
def test_property_options_stable_across_state_changes(fan_speed_sequence: list[str]):
    """Property test: Options list remains stable across state changes.
    
    **Property 11: Fan Speed Capability Adaptation**
    **Validates: Requirements 7.3**
    
    This property-based test verifies that the options list is determined
    at entity creation and remains unchanged regardless of subsequent
    state changes in the coordinator.
    
    Tests 15 different sequences of fan speed changes.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed=fan_speed_sequence[0])
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Store initial options
    initial_options = entity.options.copy()
    
    # Apply sequence of state changes
    for fan_speed in fan_speed_sequence:
        coordinator.data = VacuumState(fan_speed=fan_speed)
        
        # Property: Options list remains unchanged
        assert entity.options == initial_options, \
            f"Options list should remain stable after changing to {fan_speed}"


@pytest.mark.parametrize("valid_option", ["Quiet", "Standard", "Turbo", "Max"])
def test_property_valid_options_accepted(valid_option: str):
    """Property test: All valid options in the list are accepted.
    
    **Property 11: Fan Speed Capability Adaptation**
    **Validates: Requirements 7.3**
    
    This property-based test verifies that any option from the entity's
    options list can be successfully selected without errors.
    
    Tests all 4 valid fan speed options.
    """
    from unittest.mock import AsyncMock, MagicMock, Mock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    coordinator.async_send_command = AsyncMock()
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Mock async_write_ha_state to avoid Home Assistant setup requirement
    entity.async_write_ha_state = Mock()
    
    # Property: Valid option should be accepted and send command
    if valid_option in entity.options:
        import asyncio
        asyncio.run(entity.async_select_option(valid_option))
        
        # Verify command was sent
        coordinator.async_send_command.assert_called_once()


@pytest.mark.parametrize("invalid_option", [
    "SuperMax", "UltraQuiet", "Boost", "Eco", "Auto",
    "quiet", "QUIET", "standard", "STANDARD",
    "turbo", "TURBO", "max", "MAX",
    "Low", "Medium", "High", "VeryHigh",
    "Speed1", "Speed2", "Speed3", "Speed4",
])
def test_property_invalid_options_rejected(invalid_option: str):
    """Property test: Invalid options not in the list are rejected.
    
    **Property 11: Fan Speed Capability Adaptation**
    **Validates: Requirements 7.3**
    
    This property-based test verifies that any option not in the entity's
    options list is properly rejected and doesn't send a command.
    
    Tests 20 different invalid fan speed options.
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    coordinator.async_send_command = AsyncMock()
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Property: Invalid option should be rejected and not send command
    if invalid_option not in entity.options:
        import asyncio
        asyncio.run(entity.async_select_option(invalid_option))
        
        # Verify command was NOT sent
        coordinator.async_send_command.assert_not_called()


@pytest.mark.parametrize("device_models", [
    ["T2118", "T2118"],
    ["T2150", "T2150", "T2150"],
    ["T2181", "T2181"],
    ["T2262", "T2262", "T2262", "T2262"],
    ["T2320", "T2320"],
    ["T2118", "T2118", "T2118", "T2118", "T2118"],
    ["T2150", "T2150"],
    ["T2181", "T2181", "T2181"],
    ["T2262", "T2262"],
    ["T2320", "T2320", "T2320"],
])
def test_property_same_model_same_options(device_models: list[str]):
    """Property test: Same device model always has same options.
    
    **Property 11: Fan Speed Capability Adaptation**
    **Validates: Requirements 7.3**
    
    This property-based test verifies that multiple instances of the same
    device model always have identical options lists.
    
    Tests 10 different combinations of device models.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Group by model and verify consistency
    model_options = {}
    
    for i, model in enumerate(device_models):
        # Create mock coordinator
        coordinator = MagicMock()
        coordinator.device_id = f"test_device_{i}"
        coordinator.device_name = f"Test Vacuum {i}"
        coordinator.device_model = model
        coordinator.data = VacuumState(fan_speed="Standard")
        
        # Create suction level entity
        entity = SuctionLevelSelectEntity(coordinator)
        
        # Property: Same model should have same options
        if model in model_options:
            assert entity.options == model_options[model], \
                f"Model {model} should have consistent options across instances"
        else:
            model_options[model] = entity.options


# ============================================================================
# Bidirectional Fan Speed Synchronization Tests (Task 8.3)
# Property 12: Bidirectional Fan Speed Synchronization
# ============================================================================

def test_vacuum_entity_fan_speed_change_reflects_in_suction_level_entity():
    """Test that changing fan speed via vacuum entity updates suction level entity.
    
    **Property 12: Bidirectional Fan Speed Synchronization**
    **Validates: Requirements 8.1**
    
    This test verifies that when fan speed is changed through the vacuum entity,
    the suction level entity reflects the same fan speed value from the coordinator.
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator with initial fan speed
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    coordinator.async_send_command = AsyncMock()
    
    # Create both entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    suction_level_entity = SuctionLevelSelectEntity(coordinator)
    
    # Verify initial state
    assert vacuum_entity.fan_speed == "Standard"
    assert suction_level_entity.current_option == "Standard"
    
    # Change fan speed via vacuum entity
    import asyncio
    asyncio.run(vacuum_entity.async_set_fan_speed("Turbo"))
    
    # Simulate coordinator update (device responds with new fan speed)
    coordinator.data = VacuumState(fan_speed="Turbo")
    
    # Verify both entities reflect the new fan speed
    assert vacuum_entity.fan_speed == "Turbo"
    assert suction_level_entity.current_option == "Turbo"
    assert vacuum_entity.fan_speed == suction_level_entity.current_option



def test_suction_level_entity_fan_speed_change_reflects_in_vacuum_entity():
    """Test that changing fan speed via suction level entity updates vacuum entity.
    
    **Property 12: Bidirectional Fan Speed Synchronization**
    **Validates: Requirements 8.2**
    
    This test verifies that when fan speed is changed through the suction level entity,
    the vacuum entity reflects the same fan speed value from the coordinator.
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator with initial fan speed
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    coordinator.async_send_command = AsyncMock()
    
    # Create both entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    suction_level_entity = SuctionLevelSelectEntity(coordinator)
    
    # Mock async_write_ha_state to avoid Home Assistant setup requirement
    suction_level_entity.async_write_ha_state = MagicMock()
    
    # Verify initial state
    assert vacuum_entity.fan_speed == "Standard"
    assert suction_level_entity.current_option == "Standard"
    
    # Change fan speed via suction level entity
    import asyncio
    asyncio.run(suction_level_entity.async_select_option("Max"))
    
    # Simulate coordinator update (device responds with new fan speed)
    coordinator.data = VacuumState(fan_speed="Max")
    
    # Verify both entities reflect the new fan speed
    assert vacuum_entity.fan_speed == "Max"
    assert suction_level_entity.current_option == "Max"
    assert vacuum_entity.fan_speed == suction_level_entity.current_option



def test_bidirectional_sync_all_fan_speeds_via_vacuum_entity():
    """Test bidirectional sync for all fan speeds changed via vacuum entity.
    
    **Property 12: Bidirectional Fan Speed Synchronization**
    **Validates: Requirements 8.1**
    
    This test verifies that all valid fan speed changes through the vacuum entity
    are properly reflected in the suction level entity.
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Test all valid fan speeds
    fan_speeds = ["Quiet", "Standard", "Turbo", "Max"]
    
    for target_speed in fan_speeds:
        # Create fresh mock coordinator
        coordinator = MagicMock()
        coordinator.device_id = "test_device"
        coordinator.device_name = "Test Vacuum"
        coordinator.device_model = "T2118"
        coordinator.data = VacuumState(fan_speed="Standard")
        coordinator.async_send_command = AsyncMock()
        
        # Create both entities
        vacuum_entity = RoboVacMQTTEntity(coordinator)
        suction_level_entity = SuctionLevelSelectEntity(coordinator)
        
        # Change fan speed via vacuum entity
        import asyncio
        asyncio.run(vacuum_entity.async_set_fan_speed(target_speed))
        
        # Simulate coordinator update
        coordinator.data = VacuumState(fan_speed=target_speed)
        
        # Verify both entities reflect the same fan speed
        assert vacuum_entity.fan_speed == target_speed, \
            f"Vacuum entity should reflect {target_speed}"
        assert suction_level_entity.current_option == target_speed, \
            f"Suction level entity should reflect {target_speed}"
        assert vacuum_entity.fan_speed == suction_level_entity.current_option, \
            f"Both entities should be synchronized at {target_speed}"



def test_bidirectional_sync_all_fan_speeds_via_suction_level_entity():
    """Test bidirectional sync for all fan speeds changed via suction level entity.
    
    **Property 12: Bidirectional Fan Speed Synchronization**
    **Validates: Requirements 8.2**
    
    This test verifies that all valid fan speed changes through the suction level entity
    are properly reflected in the vacuum entity.
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Test all valid fan speeds
    fan_speeds = ["Quiet", "Standard", "Turbo", "Max"]
    
    for target_speed in fan_speeds:
        # Create fresh mock coordinator
        coordinator = MagicMock()
        coordinator.device_id = "test_device"
        coordinator.device_name = "Test Vacuum"
        coordinator.device_model = "T2118"
        coordinator.data = VacuumState(fan_speed="Standard")
        coordinator.async_send_command = AsyncMock()
        
        # Create both entities
        vacuum_entity = RoboVacMQTTEntity(coordinator)
        suction_level_entity = SuctionLevelSelectEntity(coordinator)
        
        # Mock async_write_ha_state to avoid Home Assistant setup requirement
        suction_level_entity.async_write_ha_state = MagicMock()
        
        # Change fan speed via suction level entity
        import asyncio
        asyncio.run(suction_level_entity.async_select_option(target_speed))
        
        # Simulate coordinator update
        coordinator.data = VacuumState(fan_speed=target_speed)
        
        # Verify both entities reflect the same fan speed
        assert vacuum_entity.fan_speed == target_speed, \
            f"Vacuum entity should reflect {target_speed}"
        assert suction_level_entity.current_option == target_speed, \
            f"Suction level entity should reflect {target_speed}"
        assert vacuum_entity.fan_speed == suction_level_entity.current_option, \
            f"Both entities should be synchronized at {target_speed}"



def test_bidirectional_sync_multiple_changes_alternating():
    """Test bidirectional sync with multiple alternating changes.
    
    **Property 12: Bidirectional Fan Speed Synchronization**
    **Validates: Requirements 8.1, 8.2**
    
    This test verifies that synchronization works correctly when fan speed
    is changed multiple times, alternating between vacuum entity and suction level entity.
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    coordinator.async_send_command = AsyncMock()
    
    # Create both entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    suction_level_entity = SuctionLevelSelectEntity(coordinator)
    
    # Mock async_write_ha_state to avoid Home Assistant setup requirement
    suction_level_entity.async_write_ha_state = MagicMock()
    
    import asyncio
    
    # Change 1: Via vacuum entity to Turbo
    asyncio.run(vacuum_entity.async_set_fan_speed("Turbo"))
    coordinator.data = VacuumState(fan_speed="Turbo")
    assert vacuum_entity.fan_speed == "Turbo"
    assert suction_level_entity.current_option == "Turbo"
    
    # Change 2: Via suction level entity to Quiet
    asyncio.run(suction_level_entity.async_select_option("Quiet"))
    coordinator.data = VacuumState(fan_speed="Quiet")
    assert vacuum_entity.fan_speed == "Quiet"
    assert suction_level_entity.current_option == "Quiet"
    
    # Change 3: Via vacuum entity to Max
    asyncio.run(vacuum_entity.async_set_fan_speed("Max"))
    coordinator.data = VacuumState(fan_speed="Max")
    assert vacuum_entity.fan_speed == "Max"
    assert suction_level_entity.current_option == "Max"
    
    # Change 4: Via suction level entity to Standard
    asyncio.run(suction_level_entity.async_select_option("Standard"))
    coordinator.data = VacuumState(fan_speed="Standard")
    assert vacuum_entity.fan_speed == "Standard"
    assert suction_level_entity.current_option == "Standard"
    
    # Final verification: Both entities are synchronized
    assert vacuum_entity.fan_speed == suction_level_entity.current_option



def test_bidirectional_sync_with_different_initial_states():
    """Test bidirectional sync starting from different initial fan speeds.
    
    **Property 12: Bidirectional Fan Speed Synchronization**
    **Validates: Requirements 8.1, 8.2**
    
    This test verifies that synchronization works correctly regardless of
    the initial fan speed state.
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Test different initial states
    initial_states = ["Quiet", "Standard", "Turbo", "Max"]
    target_speed = "Turbo"
    
    for initial_speed in initial_states:
        # Create mock coordinator with specific initial state
        coordinator = MagicMock()
        coordinator.device_id = "test_device"
        coordinator.device_name = "Test Vacuum"
        coordinator.device_model = "T2118"
        coordinator.data = VacuumState(fan_speed=initial_speed)
        coordinator.async_send_command = AsyncMock()
        
        # Create both entities
        vacuum_entity = RoboVacMQTTEntity(coordinator)
        suction_level_entity = SuctionLevelSelectEntity(coordinator)
        
        # Verify initial synchronization
        assert vacuum_entity.fan_speed == initial_speed
        assert suction_level_entity.current_option == initial_speed
        
        # Change via vacuum entity
        import asyncio
        asyncio.run(vacuum_entity.async_set_fan_speed(target_speed))
        coordinator.data = VacuumState(fan_speed=target_speed)
        
        # Verify synchronization after change
        assert vacuum_entity.fan_speed == target_speed
        assert suction_level_entity.current_option == target_speed
        assert vacuum_entity.fan_speed == suction_level_entity.current_option



def test_bidirectional_sync_coordinator_is_single_source_of_truth():
    """Test that coordinator is the single source of truth for fan speed.
    
    **Property 12: Bidirectional Fan Speed Synchronization**
    **Validates: Requirements 8.1, 8.2**
    
    This test verifies that both entities always read from the coordinator
    and reflect the coordinator's state, not maintaining separate state.
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    coordinator.async_send_command = AsyncMock()
    
    # Create both entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    suction_level_entity = SuctionLevelSelectEntity(coordinator)
    
    # Verify initial state from coordinator
    assert vacuum_entity.fan_speed == coordinator.data.fan_speed
    assert suction_level_entity.current_option == coordinator.data.fan_speed
    
    # Directly update coordinator data (simulating MQTT update)
    coordinator.data = VacuumState(fan_speed="Turbo")
    
    # Verify both entities immediately reflect coordinator state
    assert vacuum_entity.fan_speed == "Turbo"
    assert suction_level_entity.current_option == "Turbo"
    assert vacuum_entity.fan_speed == coordinator.data.fan_speed
    assert suction_level_entity.current_option == coordinator.data.fan_speed
    
    # Update coordinator again
    coordinator.data = VacuumState(fan_speed="Quiet")
    
    # Verify both entities reflect new coordinator state
    assert vacuum_entity.fan_speed == "Quiet"
    assert suction_level_entity.current_option == "Quiet"
    assert vacuum_entity.fan_speed == coordinator.data.fan_speed
    assert suction_level_entity.current_option == coordinator.data.fan_speed



def test_bidirectional_sync_with_none_fan_speed():
    """Test bidirectional sync when fan speed is None.
    
    **Property 12: Bidirectional Fan Speed Synchronization**
    **Validates: Requirements 8.1, 8.2**
    
    This test verifies that both entities handle None fan speed gracefully
    and remain synchronized.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator with None fan speed
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed=None)
    
    # Create both entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    suction_level_entity = SuctionLevelSelectEntity(coordinator)
    
    # Verify both entities reflect None
    assert vacuum_entity.fan_speed is None
    assert suction_level_entity.current_option is None
    assert vacuum_entity.fan_speed == suction_level_entity.current_option
    
    # Update to valid fan speed
    coordinator.data = VacuumState(fan_speed="Standard")
    
    # Verify both entities reflect the new state
    assert vacuum_entity.fan_speed == "Standard"
    assert suction_level_entity.current_option == "Standard"
    assert vacuum_entity.fan_speed == suction_level_entity.current_option



# ============================================================================
# Property-Based Tests converted to Parameterized Tests (Task 8.3)
# Property 12: Bidirectional Fan Speed Synchronization
# ============================================================================

@pytest.mark.parametrize("initial_speed,target_speed", [
    ("Quiet", "Quiet"),
    ("Quiet", "Standard"),
    ("Quiet", "Turbo"),
    ("Quiet", "Max"),
    ("Standard", "Quiet"),
    ("Standard", "Standard"),
    ("Standard", "Turbo"),
    ("Standard", "Max"),
    ("Turbo", "Quiet"),
    ("Turbo", "Standard"),
    ("Turbo", "Turbo"),
    ("Turbo", "Max"),
    ("Max", "Quiet"),
    ("Max", "Standard"),
    ("Max", "Turbo"),
    ("Max", "Max"),
])
def test_property_bidirectional_sync_via_vacuum_entity(
    initial_speed: str,
    target_speed: str
):
    """Property test: Fan speed changes via vacuum entity sync to suction level entity.
    
    **Property 12: Bidirectional Fan Speed Synchronization**
    **Validates: Requirements 8.1**
    
    This property-based test verifies that for any initial and target fan speed,
    changing the fan speed through the vacuum entity results in both entities
    reflecting the same value from the coordinator.
    
    Tests 16 combinations of initial and target speeds.
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator with initial fan speed
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed=initial_speed)
    coordinator.async_send_command = AsyncMock()
    
    # Create both entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    suction_level_entity = SuctionLevelSelectEntity(coordinator)
    
    # Property 1: Initial state is synchronized
    assert vacuum_entity.fan_speed == initial_speed
    assert suction_level_entity.current_option == initial_speed
    assert vacuum_entity.fan_speed == suction_level_entity.current_option
    
    # Change fan speed via vacuum entity
    import asyncio
    asyncio.run(vacuum_entity.async_set_fan_speed(target_speed))
    
    # Simulate coordinator update
    coordinator.data = VacuumState(fan_speed=target_speed)
    
    # Property 2: After change, both entities reflect coordinator state
    assert vacuum_entity.fan_speed == target_speed
    assert suction_level_entity.current_option == target_speed
    
    # Property 3: Both entities are synchronized
    assert vacuum_entity.fan_speed == suction_level_entity.current_option
    
    # Property 4: Both entities read from coordinator
    assert vacuum_entity.fan_speed == coordinator.data.fan_speed
    assert suction_level_entity.current_option == coordinator.data.fan_speed



@pytest.mark.parametrize("initial_speed,target_speed", [
    ("Quiet", "Quiet"),
    ("Quiet", "Standard"),
    ("Quiet", "Turbo"),
    ("Quiet", "Max"),
    ("Standard", "Quiet"),
    ("Standard", "Standard"),
    ("Standard", "Turbo"),
    ("Standard", "Max"),
    ("Turbo", "Quiet"),
    ("Turbo", "Standard"),
    ("Turbo", "Turbo"),
    ("Turbo", "Max"),
    ("Max", "Quiet"),
    ("Max", "Standard"),
    ("Max", "Turbo"),
    ("Max", "Max"),
])
def test_property_bidirectional_sync_via_suction_level_entity(
    initial_speed: str,
    target_speed: str
):
    """Property test: Fan speed changes via suction level entity sync to vacuum entity.
    
    **Property 12: Bidirectional Fan Speed Synchronization**
    **Validates: Requirements 8.2**
    
    This property-based test verifies that for any initial and target fan speed,
    changing the fan speed through the suction level entity results in both entities
    reflecting the same value from the coordinator.
    
    Tests 16 combinations of initial and target speeds.
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator with initial fan speed
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed=initial_speed)
    coordinator.async_send_command = AsyncMock()
    
    # Create both entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    suction_level_entity = SuctionLevelSelectEntity(coordinator)
    
    # Mock async_write_ha_state to avoid Home Assistant setup requirement
    suction_level_entity.async_write_ha_state = MagicMock()
    
    # Property 1: Initial state is synchronized
    assert vacuum_entity.fan_speed == initial_speed
    assert suction_level_entity.current_option == initial_speed
    assert vacuum_entity.fan_speed == suction_level_entity.current_option
    
    # Change fan speed via suction level entity
    import asyncio
    asyncio.run(suction_level_entity.async_select_option(target_speed))
    
    # Simulate coordinator update
    coordinator.data = VacuumState(fan_speed=target_speed)
    
    # Property 2: After change, both entities reflect coordinator state
    assert vacuum_entity.fan_speed == target_speed
    assert suction_level_entity.current_option == target_speed
    
    # Property 3: Both entities are synchronized
    assert vacuum_entity.fan_speed == suction_level_entity.current_option
    
    # Property 4: Both entities read from coordinator
    assert vacuum_entity.fan_speed == coordinator.data.fan_speed
    assert suction_level_entity.current_option == coordinator.data.fan_speed



@pytest.mark.parametrize("speed_sequence", [
    ["Quiet", "Standard"],
    ["Standard", "Turbo", "Max"],
    ["Max", "Quiet", "Standard", "Turbo"],
    ["Turbo", "Max", "Quiet"],
    ["Quiet", "Quiet", "Standard"],
    ["Standard", "Turbo", "Standard", "Turbo"],
    ["Max", "Quiet", "Max", "Quiet", "Max"],
    ["Turbo", "Standard", "Quiet", "Max", "Turbo"],
    ["Quiet", "Standard", "Turbo", "Max"],
    ["Max", "Turbo", "Standard", "Quiet"],
    ["Standard", "Standard", "Turbo", "Turbo"],
    ["Quiet", "Max", "Standard"],
    ["Turbo", "Quiet", "Turbo", "Quiet"],
    ["Max", "Max", "Quiet", "Quiet"],
    ["Standard", "Turbo", "Max", "Quiet", "Standard"],
])
def test_property_bidirectional_sync_multiple_changes(speed_sequence: list[str]):
    """Property test: Synchronization maintained across multiple fan speed changes.
    
    **Property 12: Bidirectional Fan Speed Synchronization**
    **Validates: Requirements 8.1, 8.2**
    
    This property-based test verifies that synchronization is maintained
    across a sequence of fan speed changes, alternating between vacuum entity
    and suction level entity.
    
    Tests 15 different sequences of fan speed changes.
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator with initial fan speed
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed=speed_sequence[0])
    coordinator.async_send_command = AsyncMock()
    
    # Create both entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    suction_level_entity = SuctionLevelSelectEntity(coordinator)
    
    # Mock async_write_ha_state to avoid Home Assistant setup requirement
    suction_level_entity.async_write_ha_state = MagicMock()
    
    import asyncio
    
    # Apply sequence of changes, alternating between entities
    for i, target_speed in enumerate(speed_sequence):
        # Alternate between vacuum entity and suction level entity
        if i % 2 == 0:
            # Change via vacuum entity
            asyncio.run(vacuum_entity.async_set_fan_speed(target_speed))
        else:
            # Change via suction level entity
            asyncio.run(suction_level_entity.async_select_option(target_speed))
        
        # Simulate coordinator update
        coordinator.data = VacuumState(fan_speed=target_speed)
        
        # Property: Both entities are always synchronized
        assert vacuum_entity.fan_speed == target_speed, \
            f"Vacuum entity should reflect {target_speed} at step {i}"
        assert suction_level_entity.current_option == target_speed, \
            f"Suction level entity should reflect {target_speed} at step {i}"
        assert vacuum_entity.fan_speed == suction_level_entity.current_option, \
            f"Entities should be synchronized at step {i}"
        
        # Property: Both entities read from coordinator
        assert vacuum_entity.fan_speed == coordinator.data.fan_speed
        assert suction_level_entity.current_option == coordinator.data.fan_speed



@pytest.mark.parametrize("fan_speed", ["Quiet", "Standard", "Turbo", "Max"])
def test_property_coordinator_single_source_of_truth(fan_speed: str):
    """Property test: Coordinator is always the single source of truth.
    
    **Property 12: Bidirectional Fan Speed Synchronization**
    **Validates: Requirements 8.1, 8.2**
    
    This property-based test verifies that both entities always read from
    the coordinator and never maintain separate state. Any coordinator update
    is immediately reflected in both entities.
    
    Tests all 4 fan speeds.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Standard")
    
    # Create both entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    suction_level_entity = SuctionLevelSelectEntity(coordinator)
    
    # Property 1: Initial state from coordinator
    assert vacuum_entity.fan_speed == coordinator.data.fan_speed
    assert suction_level_entity.current_option == coordinator.data.fan_speed
    
    # Directly update coordinator (simulating MQTT update)
    coordinator.data = VacuumState(fan_speed=fan_speed)
    
    # Property 2: Both entities immediately reflect coordinator state
    assert vacuum_entity.fan_speed == fan_speed
    assert suction_level_entity.current_option == fan_speed
    
    # Property 3: Both entities read from coordinator
    assert vacuum_entity.fan_speed == coordinator.data.fan_speed
    assert suction_level_entity.current_option == coordinator.data.fan_speed
    
    # Property 4: Both entities are synchronized
    assert vacuum_entity.fan_speed == suction_level_entity.current_option



@pytest.mark.parametrize("device_model,initial_speed,target_speed", [
    ("T2118", "Quiet", "Standard"),
    ("T2118", "Standard", "Turbo"),
    ("T2118", "Turbo", "Max"),
    ("T2118", "Max", "Quiet"),
    ("T2150", "Quiet", "Turbo"),
    ("T2150", "Standard", "Max"),
    ("T2150", "Turbo", "Quiet"),
    ("T2150", "Max", "Standard"),
    ("T2181", "Quiet", "Max"),
    ("T2181", "Standard", "Quiet"),
    ("T2181", "Turbo", "Standard"),
    ("T2181", "Max", "Turbo"),
    ("T2262", "Quiet", "Turbo"),
    ("T2262", "Standard", "Max"),
    ("T2262", "Turbo", "Quiet"),
    ("T2262", "Max", "Standard"),
    ("T2320", "Quiet", "Max"),
    ("T2320", "Standard", "Turbo"),
    ("T2320", "Turbo", "Quiet"),
    ("T2320", "Max", "Standard"),
])
def test_property_bidirectional_sync_across_device_models(
    device_model: str,
    initial_speed: str,
    target_speed: str
):
    """Property test: Bidirectional sync works across different device models.
    
    **Property 12: Bidirectional Fan Speed Synchronization**
    **Validates: Requirements 8.1, 8.2**
    
    This property-based test verifies that bidirectional synchronization
    works correctly regardless of the device model.
    
    Tests 20 combinations of device models and fan speed combinations.
    """
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator with specific device model
    coordinator = MagicMock()
    coordinator.device_id = f"test_device_{device_model}"
    coordinator.device_name = f"Test Vacuum {device_model}"
    coordinator.device_model = device_model
    coordinator.data = VacuumState(fan_speed=initial_speed)
    coordinator.async_send_command = AsyncMock()
    
    # Create both entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    suction_level_entity = SuctionLevelSelectEntity(coordinator)
    
    # Mock async_write_ha_state to avoid Home Assistant setup requirement
    suction_level_entity.async_write_ha_state = MagicMock()
    
    # Property 1: Initial synchronization
    assert vacuum_entity.fan_speed == initial_speed
    assert suction_level_entity.current_option == initial_speed
    assert vacuum_entity.fan_speed == suction_level_entity.current_option
    
    # Change via vacuum entity
    import asyncio
    asyncio.run(vacuum_entity.async_set_fan_speed(target_speed))
    coordinator.data = VacuumState(fan_speed=target_speed)
    
    # Property 2: Synchronization after change
    assert vacuum_entity.fan_speed == target_speed
    assert suction_level_entity.current_option == target_speed
    assert vacuum_entity.fan_speed == suction_level_entity.current_option
    
    # Change via suction level entity back to initial
    asyncio.run(suction_level_entity.async_select_option(initial_speed))
    coordinator.data = VacuumState(fan_speed=initial_speed)
    
    # Property 3: Synchronization maintained
    assert vacuum_entity.fan_speed == initial_speed
    assert suction_level_entity.current_option == initial_speed
    assert vacuum_entity.fan_speed == suction_level_entity.current_option


# ============================================================================
# Coordinator State Reactivity Tests (Task 10.1)
# Property 3: Coordinator State Reactivity
# ============================================================================

def test_vacuum_entity_rooms_update_on_coordinator_change():
    """Test that vacuum entity rooms attribute updates when coordinator data changes.
    
    **Property 3: Coordinator State Reactivity**
    **Validates: Requirements 1.5**
    
    This test verifies that when the coordinator's room data changes,
    the vacuum entity's extra_state_attributes immediately reflects the new rooms.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    # Create mock coordinator with initial rooms
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(rooms=[{"id": 1, "name": "Kitchen"}])
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Verify initial rooms
    attrs = entity.extra_state_attributes
    assert "rooms" in attrs
    assert len(attrs["rooms"]) == 1
    assert attrs["rooms"][0]["name"] == "Kitchen"
    
    # Update coordinator with new rooms
    coordinator.data = VacuumState(rooms=[
        {"id": 1, "name": "Kitchen"},
        {"id": 2, "name": "Living Room"},
        {"id": 3, "name": "Bedroom"}
    ])
    
    # Verify entity reflects new rooms
    attrs = entity.extra_state_attributes
    assert "rooms" in attrs
    assert len(attrs["rooms"]) == 3
    assert attrs["rooms"][0]["name"] == "Kitchen"
    assert attrs["rooms"][1]["name"] == "Living Room"
    assert attrs["rooms"][2]["name"] == "Bedroom"


def test_suction_level_entity_updates_on_coordinator_fan_speed_change():
    """Test that suction level entity updates when coordinator fan_speed changes.
    
    **Property 3: Coordinator State Reactivity**
    **Validates: Requirements 2.6**
    
    This test verifies that when the coordinator's fan_speed changes,
    the suction level entity's current_option immediately reflects the new value.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator with initial fan speed
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed="Quiet")
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Verify initial fan speed
    assert entity.current_option == "Quiet"
    
    # Update coordinator with new fan speed
    coordinator.data = VacuumState(fan_speed="Turbo")
    
    # Verify entity reflects new fan speed
    assert entity.current_option == "Turbo"
    
    # Update again
    coordinator.data = VacuumState(fan_speed="Max")
    
    # Verify entity reflects latest fan speed
    assert entity.current_option == "Max"


def test_cleaning_mode_entity_updates_on_coordinator_change():
    """Test that cleaning mode entity updates when coordinator cleaning_mode changes.
    
    **Property 3: Coordinator State Reactivity**
    **Validates: Requirements 3.5**
    
    This test verifies that when the coordinator's cleaning_mode changes,
    the cleaning mode entity's current_option immediately reflects the new value.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import CleaningModeSelectEntity
    
    # Create mock coordinator with initial cleaning mode
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2150"  # Mopping-capable model
    coordinator.data = VacuumState(cleaning_mode="Vacuum")
    
    # Create cleaning mode entity
    entity = CleaningModeSelectEntity(coordinator)
    
    # Verify initial cleaning mode
    assert entity.current_option == "Vacuum"
    
    # Update coordinator with new cleaning mode
    coordinator.data = VacuumState(cleaning_mode="Mop")
    
    # Verify entity reflects new cleaning mode
    assert entity.current_option == "Mop"
    
    # Update again
    coordinator.data = VacuumState(cleaning_mode="Vacuum and mop")
    
    # Verify entity reflects latest cleaning mode
    assert entity.current_option == "Vacuum and mop"


def test_battery_sensor_entity_updates_on_coordinator_change():
    """Test that battery sensor entity updates when coordinator battery_level changes.
    
    **Property 3: Coordinator State Reactivity**
    **Validates: Requirements 4.3**
    
    This test verifies that when the coordinator's battery_level changes,
    the battery sensor entity's native_value immediately reflects the new value.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.sensor import BatterySensorEntity
    
    # Create mock coordinator with initial battery level
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(battery_level=100)
    
    # Create battery sensor entity
    entity = BatterySensorEntity(coordinator)
    
    # Verify initial battery level
    assert entity.native_value == 100
    
    # Update coordinator with new battery level
    coordinator.data = VacuumState(battery_level=75)
    
    # Verify entity reflects new battery level
    assert entity.native_value == 75
    
    # Update again
    coordinator.data = VacuumState(battery_level=25)
    
    # Verify entity reflects latest battery level
    assert entity.native_value == 25


def test_all_entities_update_on_coordinator_state_change():
    """Test that all entities update when coordinator state changes comprehensively.
    
    **Property 3: Coordinator State Reactivity**
    **Validates: Requirements 1.5, 2.6, 4.3**
    
    This test verifies that when the coordinator's state changes,
    all relevant entities (vacuum, suction level, cleaning mode, battery)
    immediately reflect the new state.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity, CleaningModeSelectEntity
    from custom_components.robovac_mqtt.sensor import BatterySensorEntity
    
    # Create mock coordinator with initial state
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2150"  # Mopping-capable model
    coordinator.data = VacuumState(
        rooms=[{"id": 1, "name": "Kitchen"}],
        fan_speed="Standard",
        cleaning_mode="Vacuum",
        battery_level=100
    )
    
    # Create all entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    suction_level_entity = SuctionLevelSelectEntity(coordinator)
    cleaning_mode_entity = CleaningModeSelectEntity(coordinator)
    battery_entity = BatterySensorEntity(coordinator)
    
    # Verify initial state
    assert vacuum_entity.extra_state_attributes["rooms"] == [{"id": "1", "name": "Kitchen"}]
    assert suction_level_entity.current_option == "Standard"
    assert cleaning_mode_entity.current_option == "Vacuum"
    assert battery_entity.native_value == 100
    
    # Update coordinator with completely new state
    coordinator.data = VacuumState(
        rooms=[
            {"id": 1, "name": "Kitchen"},
            {"id": 2, "name": "Living Room"},
            {"id": 3, "name": "Bedroom"}
        ],
        fan_speed="Turbo",
        cleaning_mode="Vacuum and mop",
        battery_level=50
    )
    
    # Verify all entities reflect new state
    assert len(vacuum_entity.extra_state_attributes["rooms"]) == 3
    assert vacuum_entity.extra_state_attributes["rooms"][1]["name"] == "Living Room"
    assert suction_level_entity.current_option == "Turbo"
    assert cleaning_mode_entity.current_option == "Vacuum and mop"
    assert battery_entity.native_value == 50


def test_entities_update_on_multiple_coordinator_changes():
    """Test that entities update correctly across multiple coordinator state changes.
    
    **Property 3: Coordinator State Reactivity**
    **Validates: Requirements 1.5, 2.6, 4.3**
    
    This test verifies that entities continue to update correctly
    across multiple sequential coordinator state changes.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    from custom_components.robovac_mqtt.sensor import BatterySensorEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(
        rooms=[],
        fan_speed="Quiet",
        battery_level=100
    )
    
    # Create entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    suction_level_entity = SuctionLevelSelectEntity(coordinator)
    battery_entity = BatterySensorEntity(coordinator)
    
    # State change 1
    coordinator.data = VacuumState(
        rooms=[{"id": 1, "name": "Kitchen"}],
        fan_speed="Standard",
        battery_level=90
    )
    assert len(vacuum_entity.extra_state_attributes["rooms"]) == 1
    assert suction_level_entity.current_option == "Standard"
    assert battery_entity.native_value == 90
    
    # State change 2
    coordinator.data = VacuumState(
        rooms=[{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Bedroom"}],
        fan_speed="Turbo",
        battery_level=75
    )
    assert len(vacuum_entity.extra_state_attributes["rooms"]) == 2
    assert suction_level_entity.current_option == "Turbo"
    assert battery_entity.native_value == 75
    
    # State change 3
    coordinator.data = VacuumState(
        rooms=[],
        fan_speed="Max",
        battery_level=50
    )
    assert vacuum_entity.extra_state_attributes["rooms"] == []
    assert suction_level_entity.current_option == "Max"
    assert battery_entity.native_value == 50


def test_entities_handle_partial_coordinator_updates():
    """Test that entities handle partial coordinator state updates correctly.
    
    **Property 3: Coordinator State Reactivity**
    **Validates: Requirements 1.5, 2.6, 4.3**
    
    This test verifies that entities correctly handle coordinator updates
    where only some fields change while others remain the same.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    from custom_components.robovac_mqtt.sensor import BatterySensorEntity
    
    # Create mock coordinator
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(
        rooms=[{"id": 1, "name": "Kitchen"}],
        fan_speed="Standard",
        battery_level=100
    )
    
    # Create entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    suction_level_entity = SuctionLevelSelectEntity(coordinator)
    battery_entity = BatterySensorEntity(coordinator)
    
    # Update only fan_speed
    coordinator.data = VacuumState(
        rooms=[{"id": 1, "name": "Kitchen"}],
        fan_speed="Turbo",
        battery_level=100
    )
    assert vacuum_entity.extra_state_attributes["rooms"] == [{"id": "1", "name": "Kitchen"}]
    assert suction_level_entity.current_option == "Turbo"
    assert battery_entity.native_value == 100
    
    # Update only battery_level
    coordinator.data = VacuumState(
        rooms=[{"id": 1, "name": "Kitchen"}],
        fan_speed="Turbo",
        battery_level=75
    )
    assert vacuum_entity.extra_state_attributes["rooms"] == [{"id": "1", "name": "Kitchen"}]
    assert suction_level_entity.current_option == "Turbo"
    assert battery_entity.native_value == 75
    
    # Update only rooms
    coordinator.data = VacuumState(
        rooms=[{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Bedroom"}],
        fan_speed="Turbo",
        battery_level=75
    )
    assert len(vacuum_entity.extra_state_attributes["rooms"]) == 2
    assert suction_level_entity.current_option == "Turbo"
    assert battery_entity.native_value == 75


# ============================================================================
# Property-Based Tests converted to Parameterized Tests (Task 10.1)
# Property 3: Coordinator State Reactivity
# ============================================================================

@pytest.mark.parametrize("rooms_list", [
    [],
    [{"id": 1, "name": "Kitchen"}],
    [{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Living Room"}],
    [{"id": "room1", "name": "Bedroom"}],
    [{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Living Room"}, {"id": 3, "name": "Bedroom"}],
    [{"id": "kitchen", "name": "Kitchen"}, {"id": "living", "name": "Living Room"}],
    [{"id": 1, "name": "Room A"}, {"id": 2, "name": "Room B"}, {"id": 3, "name": "Room C"}, {"id": 4, "name": "Room D"}],
    [{"id": 100, "name": "Large ID Room"}],
    [{"id": "abc123", "name": "String ID Room"}],
    [{"id": 1, "name": "Küche"}, {"id": 2, "name": "客厅"}],
    [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}, {"id": 3, "name": "C"}, {"id": 4, "name": "D"}, {"id": 5, "name": "E"}],
    [{"id": 1, "name": "Master Bedroom #1"}],
    [{"id": "room_1", "name": "Office"}, {"id": "room_2", "name": "Garage"}],
    [{"id": 1, "name": "Room 1"}, {"id": 2, "name": "Room 2"}, {"id": 3, "name": "Room 3"}],
    [{"id": 99, "name": "Test Room"}],
])
def test_property_vacuum_entity_rooms_reactivity(rooms_list: list[dict]):
    """Property test: Vacuum entity rooms attribute always reflects coordinator state.
    
    **Property 3: Coordinator State Reactivity**
    **Validates: Requirements 1.5**
    
    This property-based test verifies that for any room data in the coordinator,
    the vacuum entity's extra_state_attributes immediately reflects that data.
    
    Tests 15 different room configurations.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    # Create mock coordinator with random rooms
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(rooms=rooms_list)
    
    # Create vacuum entity
    entity = RoboVacMQTTEntity(coordinator)
    
    # Property: Entity rooms attribute matches coordinator data
    attrs = entity.extra_state_attributes
    assert "rooms" in attrs
    assert attrs["rooms"] == _normalize_room_ids(rooms_list)
    
    # Property: Rooms list length matches
    assert len(attrs["rooms"]) == len(rooms_list)


@pytest.mark.parametrize("fan_speed", ["Quiet", "Standard", "Turbo", "Max"])
def test_property_suction_level_entity_fan_speed_reactivity(fan_speed: str):
    """Property test: Suction level entity always reflects coordinator fan_speed.
    
    **Property 3: Coordinator State Reactivity**
    **Validates: Requirements 2.6**
    
    This property-based test verifies that for any fan_speed in the coordinator,
    the suction level entity's current_option immediately reflects that value.
    
    Tests all 4 fan speeds.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity
    
    # Create mock coordinator with random fan speed
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(fan_speed=fan_speed)
    
    # Create suction level entity
    entity = SuctionLevelSelectEntity(coordinator)
    
    # Property: Entity current_option matches coordinator fan_speed
    assert entity.current_option == fan_speed
    assert entity.current_option == coordinator.data.fan_speed


@pytest.mark.parametrize("cleaning_mode", ["Vacuum", "Mop", "Vacuum and mop", "Mopping after sweeping"])
def test_property_cleaning_mode_entity_reactivity(cleaning_mode: str):
    """Property test: Cleaning mode entity always reflects coordinator cleaning_mode.
    
    **Property 3: Coordinator State Reactivity**
    **Validates: Requirements 3.5**
    
    This property-based test verifies that for any cleaning_mode in the coordinator,
    the cleaning mode entity's current_option immediately reflects that value.
    
    Tests all 4 cleaning modes.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.select import CleaningModeSelectEntity
    
    # Create mock coordinator with random cleaning mode
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2150"  # Mopping-capable model
    coordinator.data = VacuumState(cleaning_mode=cleaning_mode)
    
    # Create cleaning mode entity
    entity = CleaningModeSelectEntity(coordinator)
    
    # Property: Entity current_option matches coordinator cleaning_mode
    assert entity.current_option == cleaning_mode
    assert entity.current_option == coordinator.data.cleaning_mode


@pytest.mark.parametrize("battery_level", [0, 10, 25, 50, 75, 90, 100, 5, 15, 35, 45, 55, 65, 80, 95])
def test_property_battery_sensor_entity_reactivity(battery_level: int):
    """Property test: Battery sensor entity always reflects coordinator battery_level.
    
    **Property 3: Coordinator State Reactivity**
    **Validates: Requirements 4.3**
    
    This property-based test verifies that for any battery_level in the coordinator,
    the battery sensor entity's native_value immediately reflects that value.
    
    Tests 15 different battery levels.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.sensor import BatterySensorEntity
    
    # Create mock coordinator with random battery level
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(battery_level=battery_level)
    
    # Create battery sensor entity
    entity = BatterySensorEntity(coordinator)
    
    # Property: Entity native_value matches coordinator battery_level
    assert entity.native_value == battery_level
    assert entity.native_value == coordinator.data.battery_level


@pytest.mark.parametrize("rooms_list,fan_speed,cleaning_mode,battery_level", [
    ([], "Quiet", "Vacuum", 100),
    ([{"id": 1, "name": "Kitchen"}], "Standard", "Mop", 75),
    ([{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Living Room"}], "Turbo", "Vacuum and mop", 50),
    ([{"id": "room1", "name": "Bedroom"}], "Max", "Mopping after sweeping", 25),
    ([{"id": 1, "name": "A"}, {"id": 2, "name": "B"}], "Quiet", "Vacuum", 90),
    ([], "Standard", "Mop", 10),
    ([{"id": 1, "name": "Kitchen"}], "Turbo", "Vacuum and mop", 60),
    ([{"id": 1, "name": "A"}, {"id": 2, "name": "B"}, {"id": 3, "name": "C"}], "Max", "Vacuum", 40),
    ([{"id": "kitchen", "name": "Kitchen"}], "Quiet", "Mop", 80),
    ([{"id": 1, "name": "Room 1"}], "Standard", "Vacuum and mop", 55),
    ([], "Turbo", "Mopping after sweeping", 30),
    ([{"id": 1, "name": "A"}], "Max", "Vacuum", 95),
    ([{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Bedroom"}], "Quiet", "Mop", 20),
    ([{"id": "r1", "name": "R1"}, {"id": "r2", "name": "R2"}], "Standard", "Vacuum and mop", 70),
    ([{"id": 1, "name": "Test"}], "Turbo", "Vacuum", 45),
])
def test_property_all_entities_coordinator_reactivity(
    rooms_list: list[dict],
    fan_speed: str,
    cleaning_mode: str,
    battery_level: int
):
    """Property test: All entities always reflect coordinator state changes.
    
    **Property 3: Coordinator State Reactivity**
    **Validates: Requirements 1.5, 2.6, 4.3**
    
    This property-based test verifies that for any coordinator state,
    all entities (vacuum, suction level, cleaning mode, battery) immediately
    reflect the coordinator's data.
    
    Tests 15 different combinations of state values.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity, CleaningModeSelectEntity
    from custom_components.robovac_mqtt.sensor import BatterySensorEntity
    
    # Create mock coordinator with random state
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2150"  # Mopping-capable model
    coordinator.data = VacuumState(
        rooms=rooms_list,
        fan_speed=fan_speed,
        cleaning_mode=cleaning_mode,
        battery_level=battery_level
    )
    
    # Create all entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    suction_level_entity = SuctionLevelSelectEntity(coordinator)
    cleaning_mode_entity = CleaningModeSelectEntity(coordinator)
    battery_entity = BatterySensorEntity(coordinator)
    
    # Property 1: Vacuum entity rooms match coordinator (IDs normalised to str)
    assert vacuum_entity.extra_state_attributes["rooms"] == _normalize_room_ids(rooms_list)
    
    # Property 2: Suction level entity matches coordinator fan_speed
    assert suction_level_entity.current_option == fan_speed
    
    # Property 3: Cleaning mode entity matches coordinator cleaning_mode
    assert cleaning_mode_entity.current_option == cleaning_mode
    
    # Property 4: Battery entity matches coordinator battery_level
    assert battery_entity.native_value == battery_level
    
    # Property 5: All entities read from coordinator (single source of truth)
    assert vacuum_entity.extra_state_attributes["rooms"] == _normalize_room_ids(coordinator.data.rooms)
    assert suction_level_entity.current_option == coordinator.data.fan_speed
    assert cleaning_mode_entity.current_option == coordinator.data.cleaning_mode
    assert battery_entity.native_value == coordinator.data.battery_level


@pytest.mark.parametrize("state_sequence", [
    [
        {"rooms": [], "fan_speed": "Quiet", "cleaning_mode": "Vacuum", "battery_level": 100},
        {"rooms": [{"id": 1, "name": "Kitchen"}], "fan_speed": "Standard", "cleaning_mode": "Mop", "battery_level": 90},
    ],
    [
        {"rooms": [{"id": 1, "name": "A"}], "fan_speed": "Standard", "cleaning_mode": "Vacuum", "battery_level": 80},
        {"rooms": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}], "fan_speed": "Turbo", "cleaning_mode": "Vacuum and mop", "battery_level": 70},
        {"rooms": [], "fan_speed": "Max", "cleaning_mode": "Mopping after sweeping", "battery_level": 60},
    ],
    [
        {"rooms": [{"id": 1, "name": "Kitchen"}], "fan_speed": "Quiet", "cleaning_mode": "Vacuum", "battery_level": 100},
        {"rooms": [{"id": 1, "name": "Kitchen"}], "fan_speed": "Turbo", "cleaning_mode": "Vacuum", "battery_level": 100},
        {"rooms": [{"id": 1, "name": "Kitchen"}], "fan_speed": "Turbo", "cleaning_mode": "Mop", "battery_level": 100},
        {"rooms": [{"id": 1, "name": "Kitchen"}], "fan_speed": "Turbo", "cleaning_mode": "Mop", "battery_level": 50},
    ],
    [
        {"rooms": [], "fan_speed": "Max", "cleaning_mode": "Vacuum", "battery_level": 25},
        {"rooms": [{"id": 1, "name": "Room"}], "fan_speed": "Quiet", "cleaning_mode": "Mop", "battery_level": 75},
    ],
    [
        {"rooms": [{"id": 1, "name": "A"}], "fan_speed": "Standard", "cleaning_mode": "Vacuum and mop", "battery_level": 50},
        {"rooms": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}], "fan_speed": "Standard", "cleaning_mode": "Vacuum and mop", "battery_level": 50},
        {"rooms": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}, {"id": 3, "name": "C"}], "fan_speed": "Standard", "cleaning_mode": "Vacuum and mop", "battery_level": 50},
    ],
    [
        {"rooms": [], "fan_speed": "Quiet", "cleaning_mode": "Vacuum", "battery_level": 100},
        {"rooms": [], "fan_speed": "Standard", "cleaning_mode": "Vacuum", "battery_level": 90},
        {"rooms": [], "fan_speed": "Turbo", "cleaning_mode": "Vacuum", "battery_level": 80},
        {"rooms": [], "fan_speed": "Max", "cleaning_mode": "Vacuum", "battery_level": 70},
    ],
    [
        {"rooms": [{"id": 1, "name": "Kitchen"}], "fan_speed": "Turbo", "cleaning_mode": "Vacuum", "battery_level": 60},
        {"rooms": [{"id": 1, "name": "Kitchen"}], "fan_speed": "Turbo", "cleaning_mode": "Mop", "battery_level": 50},
        {"rooms": [{"id": 1, "name": "Kitchen"}], "fan_speed": "Turbo", "cleaning_mode": "Vacuum and mop", "battery_level": 40},
    ],
    [
        {"rooms": [{"id": 1, "name": "A"}], "fan_speed": "Quiet", "cleaning_mode": "Vacuum", "battery_level": 100},
        {"rooms": [{"id": 2, "name": "B"}], "fan_speed": "Standard", "cleaning_mode": "Mop", "battery_level": 75},
        {"rooms": [{"id": 3, "name": "C"}], "fan_speed": "Turbo", "cleaning_mode": "Vacuum and mop", "battery_level": 50},
        {"rooms": [{"id": 4, "name": "D"}], "fan_speed": "Max", "cleaning_mode": "Mopping after sweeping", "battery_level": 25},
    ],
    [
        {"rooms": [], "fan_speed": "Standard", "cleaning_mode": "Vacuum", "battery_level": 50},
        {"rooms": [], "fan_speed": "Standard", "cleaning_mode": "Vacuum", "battery_level": 50},
    ],
    [
        {"rooms": [{"id": 1, "name": "Test"}], "fan_speed": "Max", "cleaning_mode": "Vacuum", "battery_level": 100},
        {"rooms": [], "fan_speed": "Quiet", "cleaning_mode": "Mop", "battery_level": 0},
    ],
])
def test_property_entities_track_coordinator_state_sequence(state_sequence: list[dict]):
    """Property test: Entities track coordinator through sequence of state changes.
    
    **Property 3: Coordinator State Reactivity**
    **Validates: Requirements 1.5, 2.6, 4.3**
    
    This property-based test verifies that entities continue to correctly
    reflect coordinator state across a sequence of state changes.
    
    Tests 10 different sequences of state changes.
    """
    from unittest.mock import MagicMock
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    from custom_components.robovac_mqtt.select import SuctionLevelSelectEntity, CleaningModeSelectEntity
    from custom_components.robovac_mqtt.sensor import BatterySensorEntity
    
    # Create mock coordinator with initial state
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2150"  # Mopping-capable model
    coordinator.data = VacuumState(
        rooms=state_sequence[0]["rooms"],
        fan_speed=state_sequence[0]["fan_speed"],
        cleaning_mode=state_sequence[0]["cleaning_mode"],
        battery_level=state_sequence[0]["battery_level"]
    )
    
    # Create all entities
    vacuum_entity = RoboVacMQTTEntity(coordinator)
    suction_level_entity = SuctionLevelSelectEntity(coordinator)
    cleaning_mode_entity = CleaningModeSelectEntity(coordinator)
    battery_entity = BatterySensorEntity(coordinator)
    
    # Apply sequence of state changes
    for i, state in enumerate(state_sequence):
        # Update coordinator state
        coordinator.data = VacuumState(
            rooms=state["rooms"],
            fan_speed=state["fan_speed"],
            cleaning_mode=state["cleaning_mode"],
            battery_level=state["battery_level"]
        )
        
        # Property: All entities reflect current coordinator state
        assert vacuum_entity.extra_state_attributes["rooms"] == _normalize_room_ids(state["rooms"]), \
            f"Vacuum entity rooms mismatch at step {i}"
        assert suction_level_entity.current_option == state["fan_speed"], \
            f"Suction level entity mismatch at step {i}"
        assert cleaning_mode_entity.current_option == state["cleaning_mode"], \
            f"Cleaning mode entity mismatch at step {i}"
        assert battery_entity.native_value == state["battery_level"], \
            f"Battery entity mismatch at step {i}"
        
        # Property: All entities read from coordinator
        assert vacuum_entity.extra_state_attributes["rooms"] == _normalize_room_ids(coordinator.data.rooms)
        assert suction_level_entity.current_option == coordinator.data.fan_speed
        assert cleaning_mode_entity.current_option == coordinator.data.cleaning_mode
        assert battery_entity.native_value == coordinator.data.battery_level

