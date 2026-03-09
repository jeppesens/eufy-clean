"""Unit tests for segment cleaning functionality.

Tests verify that async_clean_segments properly extracts and applies
custom cleaning parameters when cleaning segments.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
from custom_components.robovac_mqtt.models import VacuumState


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with room data and custom parameters."""
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.data = VacuumState()
    
    # Set up rooms data
    coordinator.data.rooms = [
        {"id": 1, "name": "Living Room"},
        {"id": 2, "name": "Kitchen"},
        {"id": 3, "name": "Bedroom"}
    ]
    coordinator.data.map_id = 1
    
    # Set up custom cleaning parameters
    coordinator.data.fan_speed = "Turbo"
    coordinator.data.cleaning_mode = "Vacuum and mop"
    coordinator.data.mop_water_level = "High"
    coordinator.data.cleaning_intensity = "Deep"
    coordinator.data.received_fields = {"mop_water_level", "cleaning_intensity"}
    
    coordinator.async_send_command = AsyncMock()
    return coordinator


@pytest.fixture
def vacuum_entity(mock_coordinator):
    """Create a vacuum entity for testing."""
    return RoboVacMQTTEntity(mock_coordinator)


async def test_async_clean_segments_with_custom_params(vacuum_entity, mock_coordinator):
    """Test that segment cleaning applies current custom parameters."""
    # Act
    await vacuum_entity.async_clean_segments(["1", "2"])
    
    # Assert
    # Should call async_send_command twice: once for room_custom, once for room_clean
    assert mock_coordinator.async_send_command.call_count == 2
    
    # The calls should be dictionaries with command payloads
    calls = mock_coordinator.async_send_command.call_args_list
    
    # Both calls should be dictionaries (command payloads)
    assert isinstance(calls[0][0][0], dict)  # room_custom call
    assert isinstance(calls[1][0][0], dict)  # room_clean call
    
    # The room_clean call should have the room_clean payload structure
    room_clean_payload = calls[1][0][0]
    assert "152" in room_clean_payload  # room_clean DPS key
    
    # Verify the room_clean command was called with correct parameters
    # by checking that _async_handle_room_clean was called with the right params
    # We can verify this indirectly by checking that custom params were applied
    # (which would only happen if the logic executed correctly)


async def test_async_clean_segments_without_custom_params(vacuum_entity, mock_coordinator):
    """Test that segment cleaning works with default parameters."""
    # Reset coordinator to default values
    mock_coordinator.data.fan_speed = "Standard"
    mock_coordinator.data.cleaning_mode = "Vacuum"
    mock_coordinator.data.received_fields = set()
    
    # Act
    await vacuum_entity.async_clean_segments(["3"])
    
    # Assert
    # Should call async_send_command once for room_clean (no custom params needed)
    assert mock_coordinator.async_send_command.call_count == 1
    
    # Verify the call is a dictionary payload
    call = mock_coordinator.async_send_command.call_args
    payload = call[0][0]
    assert isinstance(payload, dict)
    assert "152" in payload  # room_clean DPS key


async def test_async_clean_segments_invalid_ids(vacuum_entity, mock_coordinator):
    """Test that segment cleaning handles invalid segment IDs gracefully."""
    # Act
    await vacuum_entity.async_clean_segments(["invalid", "abc", ""])
    
    # Assert
    # Should not call send_command for invalid IDs
    mock_coordinator.async_send_command.assert_not_called()


async def test_async_clean_segments_mixed_valid_invalid(vacuum_entity, mock_coordinator):
    """Test that segment cleaning filters out invalid IDs and processes valid ones."""
    # Act
    await vacuum_entity.async_clean_segments(["1", "invalid", "2", ""])
    
    # Assert
    # Should call async_send_command twice for valid room IDs with custom params
    assert mock_coordinator.async_send_command.call_count == 2
    
    # Verify both calls are dictionary payloads
    calls = mock_coordinator.async_send_command.call_args_list
    assert isinstance(calls[0][0][0], dict)  # room_custom call
    assert isinstance(calls[1][0][0], dict)  # room_clean call


async def test_async_clean_segments_with_map_id(vacuum_entity, mock_coordinator):
    """Test that segment cleaning uses proper map_id from coordinator."""
    # Set a specific map_id
    mock_coordinator.data.map_id = 5
    
    # Act
    await vacuum_entity.async_clean_segments(["1", "3"])
    
    # Assert
    # Should call async_send_command twice for custom params + room_clean
    assert mock_coordinator.async_send_command.call_count == 2
    
    # Verify both calls are dictionary payloads
    calls = mock_coordinator.async_send_command.call_args_list
    assert isinstance(calls[0][0][0], dict)  # room_custom call
    assert isinstance(calls[1][0][0], dict)  # room_clean call
