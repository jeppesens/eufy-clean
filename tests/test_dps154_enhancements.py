"""Test DPS 154 Phase 1 Enhancements."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.robovac_mqtt.api.parser import _process_cleaning_parameters
from custom_components.robovac_mqtt.models import VacuumState


class MockCleanParam:
    """Mock CleanParam for testing."""
    
    def __init__(self, has_fan=True, has_carpet=True, has_corner=True):
        self.clean_type = MockCleanType()
        self.fan = MockFan() if has_fan else None
        self.mop_mode = MockMopMode(has_corner)
        self.clean_extent = MockCleanExtent()
        self.clean_carpet = MockCleanCarpet() if has_carpet else None
        self.smart_mode_sw = MockSwitch()

    def HasField(self, field_name):
        """Check if field exists."""
        return hasattr(self, field_name) and getattr(self, field_name) is not None


class MockCleanType:
    def __init__(self):
        self.value = 2  # SWEEP_AND_MOP


class MockFan:
    def __init__(self):
        self.suction = 2  # Turbo


class MockMopMode:
    def __init__(self, has_corner=True):
        self.level = 1  # MIDDLE
        # corner_clean is a scalar field on mop_mode; 0 = Normal, 1 = Deep.
        # The parser now tracks corner_clean whenever mop_mode is present.
        self.corner_clean = 1 if has_corner else 0


class MockCleanExtent:
    def __init__(self):
        self.value = 1  # NARROW


class MockCleanCarpet:
    def __init__(self):
        self.strategy = 0  # AUTO_RAISE


class MockSwitch:
    def __init__(self):
        pass


def test_process_cleaning_parameters_full():
    """Test processing full DPS 154 data with all fields."""
    state = VacuumState()
    changes = {}
    
    clean_param = MockCleanParam()
    
    with patch('custom_components.robovac_mqtt.api.parser.decode') as mock_decode:
        mock_decode.return_value = MagicMock(clean_param=clean_param)
        
        _process_cleaning_parameters(state, MagicMock(), changes)
    
    # Verify all expected fields were extracted
    expected_fields = {
        'cleaning_mode': 'Vacuum and mop',
        'fan_speed': 'Turbo', 
        'corner_cleaning': 'Deep',
        'cleaning_intensity': 'Narrow',
        'carpet_strategy': 'Auto Raise',
        'smart_mode': True
    }
    
    for field, expected_value in expected_fields.items():
        assert field in changes, f"Missing field: {field}"
        assert changes[field] == expected_value, f"Field {field}: expected {expected_value}, got {changes[field]}"


def test_process_cleaning_parameters_partial():
    """Test processing partial DPS 154 data with missing optional fields."""
    state = VacuumState()
    changes = {}
    
    # Create clean_param missing some fields
    clean_param = MockCleanParam(has_fan=False, has_carpet=False, has_corner=False)
    
    with patch('custom_components.robovac_mqtt.api.parser.decode') as mock_decode:
        mock_decode.return_value = MagicMock(clean_param=clean_param)
        
        _process_cleaning_parameters(state, MagicMock(), changes)
    
    # Verify only available fields were extracted
    expected_fields = {
        'cleaning_mode': 'Vacuum and mop',
        'cleaning_intensity': 'Narrow',
        'smart_mode': True,
        # corner_cleaning is now tracked whenever mop_mode is present
        # (corner_clean=0 maps to "Normal")
        'corner_cleaning': 'Normal',
    }
    
    # Should have expected fields
    for field, expected_value in expected_fields.items():
        assert field in changes, f"Missing field: {field}"
        assert changes[field] == expected_value, f"Field {field}: expected {expected_value}, got {changes[field]}"
    
    # Should NOT have missing fields
    missing_fields = ['fan_speed', 'carpet_strategy']
    for field in missing_fields:
        assert field not in changes, f"Field {field} should be absent but found: {changes.get(field)}"


def test_process_cleaning_parameters_empty():
    """Test processing DPS 154 with no clean_param."""
    state = VacuumState()
    changes = {}
    
    with patch('custom_components.robovac_mqtt.api.parser.decode') as mock_decode:
        mock_decode.return_value = MagicMock(clean_param=None)
        
        _process_cleaning_parameters(state, MagicMock(), changes)
    
    # Should have no changes
    assert len(changes) == 0, f"Expected no changes, got: {changes}"


def test_process_cleaning_parameters_decode_failure():
    """Test handling of decode failures."""
    state = VacuumState()
    changes = {}
    
    with patch('custom_components.robovac_mqtt.api.parser.decode') as mock_decode:
        # First decode fails, second also fails
        mock_decode.side_effect = [Exception("Decode failed"), Exception("Request decode failed")]
        
        _process_cleaning_parameters(state, MagicMock(), changes)
    
    # Should have no changes due to decode failures
    assert len(changes) == 0, f"Expected no changes on decode failure, got: {changes}"
