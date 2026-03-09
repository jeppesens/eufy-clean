# pylint: disable=redefined-outer-name
import pytest
"""Tests for segment change detection functionality."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from homeassistant.helpers.issue_registry import IssueSeverity

from custom_components.robovac_mqtt.vacuum import (
    RoboVacMQTTEntity,
    Segment,
    _serialize_segments,
    _deserialize_segments,
)
from custom_components.robovac_mqtt.models import VacuumState


def test_serialize_deserialize_segments():
    """Test segment serialization and deserialization."""
    segments = [
        Segment(id="1", name="Living Room", group="main"),
        Segment(id="2", name="Kitchen", group="main"),
        Segment(id="3", name="Bedroom", group=None),
    ]

    # Test serialization
    serialized = _serialize_segments(segments)
    expected = [
        {"id": "1", "name": "Living Room", "group": "main"},
        {"id": "2", "name": "Kitchen", "group": "main"},
        {"id": "3", "name": "Bedroom", "group": None},
    ]
    assert serialized == expected

    # Test deserialization
    deserialized = _deserialize_segments(serialized)
    assert len(deserialized) == 3
    assert deserialized[0].id == "1"
    assert deserialized[0].name == "Living Room"
    assert deserialized[0].group == "main"
    assert deserialized[2].group is None


@pytest.fixture
def mock_coordinator():
    """Mock the coordinator."""
    coordinator = MagicMock()
    coordinator.device_id = "test_id"
    coordinator.device_name = "Test Vac"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState()
    coordinator.async_send_command = AsyncMock()
    coordinator.hass = MagicMock()

    coordinator.hass.config_entries.async_update_entry = MagicMock()
    coordinator.hass.async_create_task = MagicMock(side_effect=lambda coro: asyncio.create_task(coro))

    coordinator.last_seen_segments = None
    coordinator.async_save_segments = AsyncMock()
    def _save_segments(segments):
        coordinator.last_seen_segments = segments
    coordinator.async_save_segments.side_effect = _save_segments

    return coordinator


@pytest.fixture
def mock_config_entry():
    """Mock the config entry."""
    config_entry = MagicMock()
    config_entry.data = {}
    config_entry.entry_id = "test_entry_id"

    # Make the data dict actually store values
    def set_data(key, value):
        config_entry.data[key] = value

    config_entry.__setitem__ = lambda self, key, value: set_data(key, value)

    return config_entry


@pytest.mark.asyncio
@patch("custom_components.robovac_mqtt.vacuum.async_dispatcher_connect")
async def test_vacuum_entity_with_segment_detection(mock_connect, mock_coordinator, mock_config_entry):
    """Test vacuum entity initialization with segment detection."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    # Need to simulate being added to hass
    entity.hass = mock_coordinator.hass
    await entity.async_added_to_hass()

    # Verify dispatcher connection is set up
    assert mock_connect.called
    assert mock_connect.call_args[0][0] == mock_coordinator.hass
    assert mock_connect.call_args[0][1] == f"robovac_mqtt_{mock_coordinator.device_id}_rooms_updated"
    assert mock_connect.call_args[0][2] == entity._check_for_segment_changes


def test_last_seen_segments_property(mock_coordinator, mock_config_entry):
    """Test last_seen_segments property."""
    # Setup stored segments
    stored_segments = [
        {"id": "1", "name": "Living Room", "group": None},
        {"id": "2", "name": "Kitchen", "group": None},
    ]
    mock_coordinator.last_seen_segments = stored_segments

    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    last_seen = entity.last_seen_segments
    assert len(last_seen) == 2
    assert last_seen[0].id == "1"
    assert last_seen[0].name == "Living Room"
    assert last_seen[1].id == "2"
    assert last_seen[1].name == "Kitchen"


def test_last_seen_segments_none_when_not_stored(mock_coordinator, mock_config_entry):
    """Test last_seen_segments returns None when not stored."""
    mock_config_entry.data = {}

    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    assert entity.last_seen_segments is None


@patch('custom_components.robovac_mqtt.vacuum.async_create_issue')
def test_async_create_segments_issue(mock_create_issue, mock_coordinator, mock_config_entry):
    """Test creating segments issue."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    entity.async_create_segments_issue()

    # Verify issue creation was called with correct parameters
    mock_create_issue.assert_called_once_with(
        hass=mock_coordinator.hass,
        domain="robovac_mqtt",
        issue_id="segments_changed_test_id",
        is_fixable=False,
        severity=IssueSeverity.WARNING,
        translation_key="segments_changed",
        translation_placeholders={"device_name": "Test Vac"},
    )


@pytest.mark.asyncio
@patch('custom_components.robovac_mqtt.vacuum.async_delete_issue')
async def test_store_last_seen_segments(mock_delete_issue, mock_coordinator, mock_config_entry):
    """Test storing last seen segments."""
    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    segments = [
        Segment(id="1", name="Living Room", group=None),
        Segment(id="2", name="Kitchen", group=None),
    ]

    entity._store_last_seen_segments(segments)
    await asyncio.sleep(0)

    # Verify coordinator.async_save_segments was called
    mock_coordinator.async_save_segments.assert_called_once_with([
        {"id": "1", "name": "Living Room", "group": None},
        {"id": "2", "name": "Kitchen", "group": None},
    ])

    # Verify issue deletion was called
    mock_delete_issue.assert_called_once_with(
        hass=mock_coordinator.hass,
        domain="robovac_mqtt",
        issue_id="segments_changed_test_id",
    )


@pytest.mark.asyncio
async def test_check_for_segment_changes_no_previous(mock_coordinator, mock_config_entry):
    """Test segment change detection when no previous segments stored."""
    mock_config_entry.data = {}  # No last_seen_segments

    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    # Should not create issue when no previous segments
    with patch.object(entity, 'async_create_segments_issue') as mock_create:
        entity._check_for_segment_changes()
        mock_create.assert_not_called()


@pytest.mark.asyncio
async def test_check_for_segment_changes_with_changes(mock_coordinator, mock_config_entry):
    """Test segment change detection when changes are detected."""
    # Setup previous segments
    previous_segments = [
        {"id": "1", "name": "Living Room", "group": None},
        {"id": "2", "name": "Kitchen", "group": None},
    ]
    # Setup previous segments in coordinator BEFORE entity init to prevent baseline detection
    mock_coordinator.last_seen_segments = previous_segments

    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)
    # Await the initialization task to clear it from the event loop
    # (The constructor starts the task)
    await asyncio.sleep(0)

    # Now set new rooms to trigger change
    mock_coordinator.data.rooms = [
        {"id": 1, "name": "Living Room"},  # Same ID, different name
        {"id": 3, "name": "Bedroom"},      # New room
    ]

    with patch.object(entity, 'async_create_segments_issue') as mock_create:
        entity._check_for_segment_changes()
        await asyncio.sleep(0)
        mock_create.assert_called_once()


@pytest.mark.asyncio
async def test_check_for_segment_changes_no_changes(mock_coordinator, mock_config_entry):
    """Test segment change detection when no changes are detected."""
    # Setup previous segments
    previous_segments = [
        {"id": "1", "name": "Living Room", "group": None},
        {"id": "2", "name": "Kitchen", "group": None},
    ]
    mock_config_entry.data = {"last_seen_segments": previous_segments}

    # Mock current segments (same as previous)
    mock_coordinator.data.rooms = [
        {"id": 1, "name": "Living Room"},
        {"id": 2, "name": "Kitchen"},
    ]

    entity = RoboVacMQTTEntity(mock_coordinator, mock_config_entry)

    with patch.object(entity, 'async_create_segments_issue') as mock_create:
        entity._check_for_segment_changes()
        mock_create.assert_not_called()
