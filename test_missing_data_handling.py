#!/usr/bin/env python3
"""Simple test to verify missing data handling without full test infrastructure."""

import sys
from unittest.mock import MagicMock, patch
import logging

# Set up logging to see debug messages
logging.basicConfig(level=logging.DEBUG, format='%(name)s - %(levelname)s - %(message)s')

# Mock homeassistant modules before importing
sys.modules['homeassistant'] = MagicMock()
sys.modules['homeassistant.components'] = MagicMock()
sys.modules['homeassistant.components.vacuum'] = MagicMock()
sys.modules['homeassistant.components.sensor'] = MagicMock()
sys.modules['homeassistant.config_entries'] = MagicMock()
sys.modules['homeassistant.core'] = MagicMock()
sys.modules['homeassistant.const'] = MagicMock()
sys.modules['homeassistant.helpers'] = MagicMock()
sys.modules['homeassistant.helpers.entity_platform'] = MagicMock()
sys.modules['homeassistant.helpers.update_coordinator'] = MagicMock()

# Import after mocking
from custom_components.robovac_mqtt.models import VacuumState

print("=" * 80)
print("Testing Missing Data Handling")
print("=" * 80)

# Test 1: Vacuum entity with empty rooms
print("\n1. Testing vacuum entity with empty rooms list...")
with patch('custom_components.robovac_mqtt.vacuum._LOGGER') as mock_logger:
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(rooms=[])
    
    entity = RoboVacMQTTEntity(coordinator)
    attrs = entity.extra_state_attributes
    
    assert "rooms" in attrs, "rooms attribute should be present"
    assert attrs["rooms"] == [], "rooms should be empty list"
    assert mock_logger.debug.called, "Debug logging should be called for empty rooms"
    print(f"   ✓ Empty rooms list handled correctly")
    print(f"   ✓ Debug log called: {mock_logger.debug.call_args}")

# Test 2: Vacuum entity with None rooms
print("\n2. Testing vacuum entity with None rooms...")
with patch('custom_components.robovac_mqtt.vacuum._LOGGER') as mock_logger:
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(rooms=None)
    
    entity = RoboVacMQTTEntity(coordinator)
    attrs = entity.extra_state_attributes
    
    assert "rooms" in attrs, "rooms attribute should be present"
    assert attrs["rooms"] == [], "rooms should be empty list when None"
    assert mock_logger.debug.called, "Debug logging should be called for None rooms"
    print(f"   ✓ None rooms handled correctly (converted to empty list)")
    print(f"   ✓ Debug log called: {mock_logger.debug.call_args}")

# Test 3: Vacuum entity with valid rooms (no logging)
print("\n3. Testing vacuum entity with valid rooms...")
with patch('custom_components.robovac_mqtt.vacuum._LOGGER') as mock_logger:
    from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity
    
    rooms = [{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Living Room"}]
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(rooms=rooms)
    
    entity = RoboVacMQTTEntity(coordinator)
    attrs = entity.extra_state_attributes
    
    assert "rooms" in attrs, "rooms attribute should be present"
    assert attrs["rooms"] == rooms, "rooms should match input"
    assert not mock_logger.debug.called, "Debug logging should NOT be called for valid rooms"
    print(f"   ✓ Valid rooms handled correctly")
    print(f"   ✓ No debug log called (as expected)")

# Test 4: Battery sensor with None battery
print("\n4. Testing battery sensor with None battery...")
with patch('custom_components.robovac_mqtt.sensor._LOGGER') as mock_logger:
    from custom_components.robovac_mqtt.sensor import BatterySensorEntity
    
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(battery_level=None)
    
    entity = BatterySensorEntity(coordinator)
    value = entity.native_value
    
    assert value is None, "Battery value should be None when unavailable"
    assert mock_logger.debug.called, "Debug logging should be called for None battery"
    print(f"   ✓ None battery handled correctly")
    print(f"   ✓ Debug log called: {mock_logger.debug.call_args}")

# Test 5: Battery sensor with negative battery
print("\n5. Testing battery sensor with negative battery...")
with patch('custom_components.robovac_mqtt.sensor._LOGGER') as mock_logger:
    from custom_components.robovac_mqtt.sensor import BatterySensorEntity
    
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(battery_level=-1)
    
    entity = BatterySensorEntity(coordinator)
    value = entity.native_value
    
    assert value is None, "Battery value should be None when negative"
    assert mock_logger.debug.called, "Debug logging should be called for negative battery"
    print(f"   ✓ Negative battery handled correctly")
    print(f"   ✓ Debug log called: {mock_logger.debug.call_args}")

# Test 6: Battery sensor with valid battery (no logging)
print("\n6. Testing battery sensor with valid battery...")
with patch('custom_components.robovac_mqtt.sensor._LOGGER') as mock_logger:
    from custom_components.robovac_mqtt.sensor import BatterySensorEntity
    
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(battery_level=75)
    
    entity = BatterySensorEntity(coordinator)
    value = entity.native_value
    
    assert value == 75, "Battery value should match input"
    assert not mock_logger.debug.called, "Debug logging should NOT be called for valid battery"
    print(f"   ✓ Valid battery handled correctly")
    print(f"   ✓ No debug log called (as expected)")

# Test 7: Battery sensor with zero battery (edge case)
print("\n7. Testing battery sensor with zero battery...")
with patch('custom_components.robovac_mqtt.sensor._LOGGER') as mock_logger:
    from custom_components.robovac_mqtt.sensor import BatterySensorEntity
    
    coordinator = MagicMock()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Vacuum"
    coordinator.device_model = "T2118"
    coordinator.data = VacuumState(battery_level=0)
    
    entity = BatterySensorEntity(coordinator)
    value = entity.native_value
    
    assert value == 0, "Battery value should be 0 (valid state)"
    assert not mock_logger.debug.called, "Debug logging should NOT be called for zero battery (valid)"
    print(f"   ✓ Zero battery handled correctly (valid state)")
    print(f"   ✓ No debug log called (as expected)")

print("\n" + "=" * 80)
print("All tests passed! ✓")
print("=" * 80)
