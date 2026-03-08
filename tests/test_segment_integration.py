"""Integration test for segment change detection."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
from custom_components.robovac_mqtt.models import VacuumState


def test_segment_change_detection_integration():
    """Test the complete segment change detection flow."""
    # Setup mock coordinator and config entry
    coordinator = MagicMock()
    coordinator.device_id = "test_id"
    coordinator.device_name = "Test Vac"
    coordinator.data = VacuumState()
    coordinator.hass = MagicMock()

    config_entry = MagicMock()
    config_entry.data = {}
    config_entry.entry_id = "test_entry_id"

    # Propagate async_update_entry calls to config_entry.data so that
    # last_seen_segments (which reads config_entry.data) stays consistent.
    def _update_entry(entry, **kwargs):
        if "data" in kwargs:
            entry.data = kwargs["data"]

    coordinator.hass.config_entries.async_update_entry.side_effect = _update_entry

    # Initially no rooms - should initialize with None (no segments stored)
    coordinator.data.rooms = []
    entity = RoboVacMQTTEntity(coordinator, config_entry)

    # Verify no segments stored initially (empty list results in None)
    assert entity.last_seen_segments is None

    # Simulate rooms appearing for the first time
    coordinator.data.rooms = [
        {"id": 1, "name": "Living Room"},
        {"id": 2, "name": "Kitchen"},
    ]

    # First-time detection: baseline stored silently, no issue raised
    with patch.object(entity, 'async_create_segments_issue') as mock_create_issue:
        entity._check_for_segment_changes()
        mock_create_issue.assert_not_called()

    # Baseline is now stored; last_seen_segments must be non-None
    assert entity.last_seen_segments is not None
    assert len(entity.last_seen_segments) == 2

    # Test explicit store clears any issue and persists segments
    with patch('custom_components.robovac_mqtt.vacuum.async_delete_issue') as mock_delete:
        entity._store_last_seen_segments(entity._get_room_segments())

        stored = entity.last_seen_segments
        assert len(stored) == 2
        assert stored[0].id == "1"
        assert stored[0].name == "Living Room"

        # Verify issue deletion was called
        mock_delete.assert_called_once()
    
    # Test no change detection when segments are the same
    with patch.object(entity, 'async_create_segments_issue') as mock_create_issue:
        entity._check_for_segment_changes()
        mock_create_issue.assert_not_called()
    
    # Test change detection when room name changes
    coordinator.data.rooms = [
        {"id": 1, "name": "Living Room Updated"},  # Name changed
        {"id": 2, "name": "Kitchen"},
    ]
    
    with patch.object(entity, 'async_create_segments_issue') as mock_create_issue:
        entity._check_for_segment_changes()
        mock_create_issue.assert_called_once()
    
    # Test change detection when room is removed
    coordinator.data.rooms = [
        {"id": 2, "name": "Kitchen"},  # Room 1 removed
    ]
    
    with patch.object(entity, 'async_create_segments_issue') as mock_create_issue:
        entity._check_for_segment_changes()
        mock_create_issue.assert_called_once()
    
    # Test change detection when room is added
    coordinator.data.rooms = [
        {"id": 2, "name": "Kitchen"},
        {"id": 3, "name": "Bedroom"},  # New room added
    ]
    
    with patch.object(entity, 'async_create_segments_issue') as mock_create_issue:
        entity._check_for_segment_changes()
        mock_create_issue.assert_called_once()


def test_backward_compatibility_no_config_entry():
    """Test that entity works without config entry (backward compatibility)."""
    coordinator = MagicMock()
    coordinator.device_id = "test_id"
    coordinator.device_name = "Test Vac"
    coordinator.data = VacuumState(rooms=[{"id": 1, "name": "Kitchen"}])
    coordinator.hass = MagicMock()
    
    # Create entity without config entry
    entity = RoboVacMQTTEntity(coordinator)
    
    # Should work but segment detection features should be disabled
    assert entity.last_seen_segments is None
    
    # Should not create issues when no config entry
    with patch('custom_components.robovac_mqtt.vacuum.async_create_issue') as mock_create:
        entity.async_create_segments_issue()
        mock_create.assert_not_called()
    
    # Should not store segments when no config entry
    with patch('custom_components.robovac_mqtt.vacuum.async_delete_issue') as mock_delete:
        entity._store_last_seen_segments(entity._get_room_segments())
        mock_delete.assert_not_called()
    
    # Should not detect changes when no config entry
    with patch.object(entity, 'async_create_segments_issue') as mock_create:
        entity._check_for_segment_changes()
        mock_create.assert_not_called()
    
    # But basic functionality should still work
    assert len(entity._get_room_segments()) == 1
    assert entity._get_room_segments()[0].name == "Kitchen"
