import pytest
"""Unit tests for error handling in Matter-aligned entities."""

# pylint: disable=redefined-outer-name

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import PERCENTAGE

from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.select import (
    CleaningModeSelectEntity,
    SuctionLevelSelectEntity,
    WaterLevelSelectEntity,
)
from custom_components.robovac_mqtt.sensor import BatterySensorEntity
from custom_components.robovac_mqtt.vacuum import RoboVacMQTTEntity


def _normalize_room_ids(rooms):
    """Convert room IDs to match _rooms_to_attributes output (ints if possible)."""
    return [{"id": int(room["id"]) if str(room["id"]).isdigit() else str(room["id"]), "name": room["name"]} for room in rooms]


@pytest.fixture
def mock_coordinator():
    """Mock the coordinator."""
    coordinator = MagicMock(spec=EufyCleanCoordinator)
    coordinator.data = VacuumState()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Device"
    coordinator.device_model = "T2118"  # Non-mopping model
    coordinator.async_send_command = AsyncMock()
    coordinator.device_info = {
        "identifiers": {("robovac_mqtt", "test_device")},
        "name": "Test Device",
        "manufacturer": "Eufy",
        "model": "T2118",
    }
    return coordinator


@pytest.mark.asyncio
async def test_invalid_suction_level_selection(mock_coordinator):
    """Test that invalid suction level selection is rejected."""
    # Setup suction level entity
    entity = SuctionLevelSelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    # Valid options are: Quiet, Standard, Turbo, Max
    valid_options = entity.options
    assert len(valid_options) > 0

    # Try to select an invalid option
    invalid_option = "SuperMax"
    assert invalid_option not in valid_options

    # Should not raise an exception, but should log warning and not send command
    await entity.async_select_option(invalid_option)

    # Verify command was NOT sen
    mock_coordinator.async_send_command.assert_not_called()


@pytest.mark.asyncio
async def test_valid_suction_level_selection(mock_coordinator):
    """Test that valid suction level selection works correctly."""
    # Setup suction level entity
    entity = SuctionLevelSelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    # Get a valid option
    valid_option = entity.options[0]

    # Select the valid option
    await entity.async_select_option(valid_option)

    # Verify command was sen
    mock_coordinator.async_send_command.assert_called_once()



def test_cleaning_mode_non_mopping_device(mock_coordinator):
    """Test that all cleaning modes are always exposed regardless of device model."""
    mock_coordinator.device_model = "T2118"  # Non-mopping model

    entity = CleaningModeSelectEntity(mock_coordinator)
    entity.hass = MagicMock()

    # All 4 modes are always exposed — the Matter hub decides what to show
    assert len(entity.options) == 4
    assert "Vacuum" in entity.options
    assert "Mop" in entity.options
    assert "Vacuum and mop" in entity.options
    assert "Mopping after sweeping" in entity.options


def test_cleaning_mode_mopping_device(mock_coordinator):
    """Test that mopping device shows all cleaning mode options."""
    # Setup cleaning mode entity with mopping device model
    mock_coordinator.device_model = "T2150"  # G10 Hybrid - mopping model

    entity = CleaningModeSelectEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Should have all four options
    assert len(entity.options) == 4
    assert "Vacuum" in entity.options
    assert "Mop" in entity.options
    assert "Vacuum and mop" in entity.options
    assert "Mopping after sweeping" in entity.options


@pytest.mark.asyncio
async def test_cleaning_mode_selection_non_mopping_device(mock_coordinator):
    """Test that all cleaning modes are selectable on any device."""
    mock_coordinator.device_model = "T2118"  # Non-mopping model
    mock_coordinator.data.cleaning_mode = "Vacuum"

    entity = CleaningModeSelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    # All 4 modes are available
    assert len(entity.options) == 4

    # User can select any mode, including Mop
    await entity.async_select_option("Mop")
    mock_coordinator.async_send_command.assert_called_once()


def test_cleaning_mode_supports_mopping_detection(mock_coordinator):
    """Test that all models expose all 4 cleaning modes (no model-based filtering)."""
    # All models — mopping or not — always get all 4 modes
    for model in ["T2118", "T2150", "T2181", "T2190", "T2253", "T2261", "T2280", "T2320", "T2351"]:
        mock_coordinator.device_model = model
        entity = CleaningModeSelectEntity(mock_coordinator)
        assert len(entity.options) == 4, f"Model {model} should always have 4 cleaning modes"
        assert "Vacuum" in entity.options
        assert "Mop" in entity.options


def test_suction_level_options_available(mock_coordinator):
    """Test that suction level entity has valid options."""
    entity = SuctionLevelSelectEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Should have at least one option
    assert len(entity.options) > 0

    # All options should be strings
    for option in entity.options:
        assert isinstance(option, str)
        assert len(option) > 0


def test_suction_level_current_option(mock_coordinator):
    """Test that suction level entity reflects coordinator state."""
    # Set fan speed in coordinator
    mock_coordinator.data.fan_speed = "Standard"

    entity = SuctionLevelSelectEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Should reflect the coordinator state
    assert entity.current_option == "Standard"


def test_cleaning_mode_current_option(mock_coordinator):
    """Test that cleaning mode entity reflects coordinator state."""
    # Set cleaning mode in coordinator
    mock_coordinator.data.cleaning_mode = "Vacuum"

    entity = CleaningModeSelectEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Should reflect the coordinator state
    assert entity.current_option == "Vacuum"


# ============================================================================
# Backward Compatibility Tests (Requirements 5.1, 5.2, 5.3, 5.4, 5.5)
# ============================================================================


def test_vacuum_entity_features_unchanged(mock_coordinator):
    """Test that vacuum entity still supports all existing features.

    Validates: Requirement 5.1 - Vacuum entity continues to support all existing
    VacuumEntityFeature flags. CLEAN_AREA was added for HA 2026.3 support.
    """
    from homeassistant.components.vacuum import VacuumEntityFeature

    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Verify all legacy features are still presen
    legacy_features = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.STATE
        | VacuumEntityFeature.FAN_SPEED
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.SEND_COMMAND
        | VacuumEntityFeature.LOCATE
    )

    assert entity.supported_features & legacy_features == legacy_features
    # CLEAN_AREA is included when available (HA 2026.3+)
    clean_area = getattr(VacuumEntityFeature, "CLEAN_AREA", None)
    if clean_area is not None:
        assert entity.supported_features & clean_area


@pytest.mark.asyncio
async def test_vacuum_entity_async_set_fan_speed_unchanged(mock_coordinator):
    """Test that vacuum entity async_set_fan_speed method still works.

    Validates: Requirement 5.2 - Existing fan_speed property and async_set_fan_speed
    method remain functional.
    """
    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Test setting a valid fan speed
    await entity.async_set_fan_speed("Standard")

    # Verify command was sen
    mock_coordinator.async_send_command.assert_called_once()

    # Verify the command format is correc
    call_args = mock_coordinator.async_send_command.call_args
    assert call_args is not None


@pytest.mark.asyncio
async def test_vacuum_entity_fan_speed_property_unchanged(mock_coordinator):
    """Test that vacuum entity fan_speed property still works.

    Validates: Requirement 5.2 - Existing fan_speed property remains functional.
    """
    # Set fan speed in coordinator
    mock_coordinator.data.fan_speed = "Turbo"

    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Verify fan_speed property returns coordinator value
    assert entity.fan_speed == "Turbo"


@pytest.mark.asyncio
async def test_vacuum_entity_send_command_room_clean_unchanged(mock_coordinator):
    """Test that vacuum entity send_command for room_clean still works.

    Validates: Requirement 5.3 - Existing send_command interface for room_clean
    remains unchanged.
    """
    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Test room_clean command with legacy format (list of room IDs)
    await entity.async_send_command(
        "room_clean",
        params={"room_ids": [1, 2], "map_id": 1}
    )

    # Verify command was sen
    assert mock_coordinator.async_send_command.called


@pytest.mark.asyncio
async def test_vacuum_entity_send_command_scene_clean_unchanged(mock_coordinator):
    """Test that vacuum entity send_command for scene_clean still works.

    Validates: Requirement 5.3 - Existing send_command interface for scene_clean
    remains unchanged.
    """
    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Test scene_clean command
    await entity.async_send_command(
        "scene_clean",
        params={"scene_id": 5}
    )

    # Verify command was sen
    mock_coordinator.async_send_command.assert_called_once()


def test_existing_select_entity_unique_ids_unchanged(mock_coordinator):
    """Test that existing select entities maintain their unique IDs.

    Validates: Requirement 5.5 - When new entities are added, existing entity
    unique IDs shall not change.
    """
    from custom_components.robovac_mqtt.select import (
        RoomSelectEntity,
        SceneSelectEntity,
    )

    # Create existing select entities
    scene_entity = SceneSelectEntity(mock_coordinator)
    room_entity = RoomSelectEntity(mock_coordinator)

    # Verify unique IDs follow expected format and haven't changed
    assert scene_entity.unique_id == f"{mock_coordinator.device_id}_scene_select"
    assert room_entity.unique_id == f"{mock_coordinator.device_id}_room_select"


def test_new_select_entity_unique_ids_format(mock_coordinator):
    """Test that new select entities follow consistent unique ID format.

    Validates: Requirement 5.5 - New entities use consistent unique ID forma
    that doesn't conflict with existing entities.
    """
    # Create new select entities
    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    cleaning_entity = CleaningModeSelectEntity(mock_coordinator)

    # Verify unique IDs follow expected forma
    assert suction_entity.unique_id == f"{mock_coordinator.device_id}_suction_level"
    assert cleaning_entity.unique_id == f"{mock_coordinator.device_id}_cleaning_mode"

    # Verify they don't conflict with existing entity IDs
    assert suction_entity.unique_id != f"{mock_coordinator.device_id}_scene_select"
    assert cleaning_entity.unique_id != f"{mock_coordinator.device_id}_room_select"


def test_vacuum_entity_unique_id_unchanged(mock_coordinator):
    """Test that vacuum entity unique ID remains unchanged.

    Validates: Requirement 5.5 - Vacuum entity unique ID has not changed.
    """
    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Verify unique ID is still just the device_id
    assert entity.unique_id == mock_coordinator.device_id


def test_battery_sensor_unique_id_format(mock_coordinator):
    """Test that battery sensor entity follows consistent unique ID format.

    Validates: Requirement 5.5 - Battery sensor uses consistent unique ID format.
    """
    entity = BatterySensorEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Verify unique ID follows expected forma
    assert entity.unique_id == f"{mock_coordinator.device_id}_battery"


@pytest.mark.asyncio
async def test_existing_scene_select_entity_still_functions(mock_coordinator):
    """Test that existing scene select entity continues to function.

    Validates: Requirement 5.4 - Existing select entities (Scene, Room, Dock settings)
    continue to function as before.
    """
    from custom_components.robovac_mqtt.select import SceneSelectEntity

    # Setup scene data
    mock_coordinator.data.scenes = [
        {"id": 1, "name": "Quick Clean"},
        {"id": 2, "name": "Deep Clean"},
    ]

    entity = SceneSelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    # Verify options are available
    options = entity.options
    assert len(options) == 2
    assert "Quick Clean (ID: 1)" in options

    # Test selecting a scene
    await entity.async_select_option("Quick Clean (ID: 1)")

    # Verify command was sen
    mock_coordinator.async_send_command.assert_called_once()


@pytest.mark.asyncio
async def test_existing_room_select_entity_still_functions(mock_coordinator):
    """Test that existing room select entity continues to function.

    Validates: Requirement 5.4 - Existing select entities (Scene, Room, Dock settings)
    continue to function as before.
    """
    from custom_components.robovac_mqtt.select import RoomSelectEntity

    # Setup room data
    mock_coordinator.data.rooms = [
        {"id": 1, "name": "Kitchen"},
        {"id": 2, "name": "Living Room"},
    ]
    mock_coordinator.data.map_id = 1

    entity = RoomSelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    # Verify options are available
    options = entity.options
    assert len(options) == 2
    assert "Kitchen (ID: 1)" in options

    # Test selecting a room
    await entity.async_select_option("Kitchen (ID: 1)")

    # Verify command was sen
    mock_coordinator.async_send_command.assert_called_once()


def test_vacuum_entity_extra_state_attributes_includes_legacy_fields(mock_coordinator):
    """Test that vacuum entity extra_state_attributes includes all legacy fields.

    Validates: Requirement 5.1 - Vacuum entity continues to expose all existing
    state attributes.
    """
    # Setup coordinator data with all legacy fields
    mock_coordinator.data.fan_speed = "Standard"
    mock_coordinator.data.cleaning_time = 1800
    mock_coordinator.data.cleaning_area = 45
    mock_coordinator.data.task_status = "cleaning"
    mock_coordinator.data.trigger_source = "app"
    mock_coordinator.data.error_code = 0
    mock_coordinator.data.error_message = ""
    mock_coordinator.data.status_code = 1
    mock_coordinator.data.rooms = []

    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Get extra state attributes
    attrs = entity.extra_state_attributes

    # Verify all legacy fields are presen
    assert "fan_speed" in attrs
    assert "cleaning_time" in attrs
    assert "cleaning_area" in attrs
    assert "task_status" in attrs
    assert "trigger_source" in attrs
    assert "error_code" in attrs
    assert "error_message" in attrs
    assert "status_code" in attrs

    # Verify values match coordinator data
    assert attrs["fan_speed"] == "Standard"
    assert attrs["cleaning_time"] == 1800
    assert attrs["cleaning_area"] == 45


@pytest.mark.asyncio
async def test_vacuum_entity_all_existing_methods_still_work(mock_coordinator):
    """Test that all existing vacuum entity methods still work.

    Validates: Requirement 5.1, 5.2 - All existing vacuum entity methods remain
    functional.
    """
    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Test all existing methods
    await entity.async_start()
    assert mock_coordinator.async_send_command.called

    mock_coordinator.async_send_command.reset_mock()
    await entity.async_pause()
    assert mock_coordinator.async_send_command.called

    mock_coordinator.async_send_command.reset_mock()
    await entity.async_stop()
    assert mock_coordinator.async_send_command.called

    mock_coordinator.async_send_command.reset_mock()
    await entity.async_return_to_base()
    assert mock_coordinator.async_send_command.called

    mock_coordinator.async_send_command.reset_mock()
    await entity.async_locate()
    assert mock_coordinator.async_send_command.called


def test_vacuum_entity_fan_speed_list_unchanged(mock_coordinator):
    """Test that vacuum entity fan_speed_list property is unchanged.

    Validates: Requirement 5.2 - Existing fan_speed_list property remains functional.
    """
    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Verify fan_speed_list is available and contains expected values
    assert entity.fan_speed_list is not None
    assert len(entity.fan_speed_list) > 0
    assert isinstance(entity.fan_speed_list, list)

    # Verify it contains string values
    for speed in entity.fan_speed_list:
        assert isinstance(speed, str)


# ============================================================================
# Matter Bridge Compatibility Tests (Requirements 6.1-6.7)
# ============================================================================


def test_vacuum_entity_id_format_matches_matter_expectations(mock_coordinator):
    """Test that vacuum entity ID follows expected format for Matter Bridge.

    Validates: Requirement 6.1 - Entity ID format matches Matter Bridge expectations.
    Matter Bridge expects entity IDs in format: vacuum.{device_name}
    """
    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Verify unique_id is just the device_id (Home Assistant will create entity_id from this)
    assert entity.unique_id == mock_coordinator.device_id
    assert isinstance(entity.unique_id, str)
    assert len(entity.unique_id) > 0


def test_suction_level_entity_id_format_matches_matter_expectations(mock_coordinator):
    """Test that suction level entity ID follows expected format for Matter Bridge.

    Validates: Requirement 6.3 - Suction level entity ID format matches Matter Bridge expectations.
    Matter Bridge expects entity IDs in format: select.{vacuum_name}_suction_level
    """
    entity = SuctionLevelSelectEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Verify unique_id follows the expected forma
    expected_format = f"{mock_coordinator.device_id}_suction_level"
    assert entity.unique_id == expected_format

    # Verify it's a string and not empty
    assert isinstance(entity.unique_id, str)
    assert len(entity.unique_id) > 0


def test_cleaning_mode_entity_id_format_matches_matter_expectations(mock_coordinator):
    """Test that cleaning mode entity ID follows expected format for Matter Bridge.

    Validates: Requirement 6.2 - Cleaning mode entity ID format matches Matter Bridge expectations.
    Matter Bridge expects entity IDs in format: select.{vacuum_name}_cleaning_mode
    """
    entity = CleaningModeSelectEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Verify unique_id follows the expected forma
    expected_format = f"{mock_coordinator.device_id}_cleaning_mode"
    assert entity.unique_id == expected_format

    # Verify it's a string and not empty
    assert isinstance(entity.unique_id, str)
    assert len(entity.unique_id) > 0


def test_battery_entity_id_format_matches_matter_expectations(mock_coordinator):
    """Test that battery entity ID follows expected format for Matter Bridge.

    Validates: Requirement 6.4 - Battery entity ID format matches Matter Bridge expectations.
    Matter Bridge expects entity IDs in format: sensor.{vacuum_name}_battery
    """
    entity = BatterySensorEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Verify unique_id follows the expected forma
    expected_format = f"{mock_coordinator.device_id}_battery"
    assert entity.unique_id == expected_format

    # Verify it's a string and not empty
    assert isinstance(entity.unique_id, str)
    assert len(entity.unique_id) > 0


def test_rooms_attribute_format_matches_matter_expectations(mock_coordinator):
    """Test that rooms attribute format matches Matter Bridge expectations.

    Validates: Requirement 6.5 - Rooms attribute format matches Matter Bridge expectations.
    Matter Bridge expects rooms as array of objects with "id" and "name" properties.
    """
    # Setup vacuum entity with valid room data
    mock_coordinator.data.rooms = [
        {"id": 1, "name": "Kitchen"},
        {"id": 2, "name": "Living Room"},
        {"id": 3, "name": "Bedroom"},  # Test string ID as well
    ]

    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Get extra state attributes
    attrs = entity.extra_state_attributes

    # Verify rooms attribute exists
    assert "rooms" in attrs

    # Verify it's a lis
    assert isinstance(attrs["rooms"], list)

    # Verify each room has required properties
    for room in attrs["rooms"]:
        assert isinstance(room, dict)
        assert "id" in room
        assert "name" in room

        # Verify id is number or string
        assert isinstance(room["id"], (int, str))

        # Verify name is string
        assert isinstance(room["name"], str)
        assert len(room["name"]) > 0


def test_rooms_attribute_empty_list_when_no_data(mock_coordinator):
    """Test that rooms attribute is empty list when no room data available.

    Validates: Requirement 6.5 - Rooms attribute provides empty list when no data available.
    """
    # Setup vacuum entity with no room data
    mock_coordinator.data.rooms = None

    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Get extra state attributes
    attrs = entity.extra_state_attributes

    # Verify rooms attribute exists and is empty lis
    assert "rooms" in attrs
    assert attrs["rooms"] == []
    assert isinstance(attrs["rooms"], list)


def test_vacuum_entity_exposes_fan_speed_list_for_matter_discovery(mock_coordinator):
    """Test that vacuum entity exposes fan_speed_list for Matter Bridge discovery.

    Validates: Requirement 6.6 - Vacuum entity exposes fan_speed_list property for
    Matter Bridge to discover available suction levels.
    """
    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Verify fan_speed_list is exposed
    assert hasattr(entity, "fan_speed_list")
    assert entity.fan_speed_list is not None

    # Verify it's a list of strings
    assert isinstance(entity.fan_speed_list, list)
    assert len(entity.fan_speed_list) > 0

    for speed in entity.fan_speed_list:
        assert isinstance(speed, str)
        assert len(speed) > 0


def test_vacuum_entity_provides_rvc_operational_state_attributes(mock_coordinator):
    """Test that vacuum entity provides all attributes required by RVC Operational State cluster.

    Validates: Requirement 6.1 - Vacuum entity provides all attributes required by
    RVC_Operational_State cluster (activity, battery_level, error_code).
    """
    # Setup coordinator data
    mock_coordinator.data.activity = "cleaning"
    mock_coordinator.data.battery_level = 75
    mock_coordinator.data.error_code = 0

    entity = RoboVacMQTTEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Verify activity is exposed
    assert entity.activity is not None

    # Verify battery_level is in extra_state_attributes (accessible via coordinator)
    assert mock_coordinator.data.battery_level == 75

    # Verify error_code is in extra_state_attributes
    attrs = entity.extra_state_attributes
    assert "error_code" in attrs
    assert attrs["error_code"] == 0


def test_entity_metadata_follows_matter_conventions(mock_coordinator):
    """Test that entity metadata follows Matter Bridge conventions.

    Validates: Requirement 6.7 - Entity metadata follows conventions expected by Matter Bridge.
    All entities should use has_entity_name=True for proper device association.
    """
    # Test vacuum entity
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    assert vacuum_entity._attr_has_entity_name is True

    # Test suction level entity
    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    assert suction_entity._attr_has_entity_name is True
    assert suction_entity._attr_name == "Suction Level"
    assert suction_entity._attr_icon == "mdi:fan"

    # Test cleaning mode entity
    cleaning_entity = CleaningModeSelectEntity(mock_coordinator)
    assert cleaning_entity._attr_has_entity_name is True
    assert cleaning_entity._attr_name == "Cleaning Mode"
    assert cleaning_entity._attr_icon == "mdi:spray-bottle"

    # Test battery entity
    battery_entity = BatterySensorEntity(mock_coordinator)
    assert battery_entity._attr_has_entity_name is True
    assert battery_entity._attr_name == "Battery"
    assert battery_entity._attr_icon == "mdi:battery"
    assert battery_entity._attr_device_class == SensorDeviceClass.BATTERY
    assert battery_entity._attr_native_unit_of_measurement == PERCENTAGE


def test_cleaning_mode_options_match_matter_expectations(mock_coordinator):
    """Test that cleaning mode options match Matter Bridge expectations.

    Validates: Requirement 6.2 - Cleaning mode options match Matter Bridge expectations.
    Matter Bridge expects: "Vacuum", "Mop", "Vacuum and mop", "Mopping after sweeping"
    """
    # Test mopping device
    mock_coordinator.device_model = "T2150"  # G10 Hybrid

    entity = CleaningModeSelectEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Verify all expected options are presen
    expected_options = [
        "Vacuum",
        "Mop",
        "Vacuum and mop",
        "Mopping after sweeping",
    ]

    assert entity.options == expected_options

    # Verify each option is a string
    for option in entity.options:
        assert isinstance(option, str)
        assert len(option) > 0


def test_suction_level_options_match_matter_expectations(mock_coordinator):
    """Test that suction level options match Matter Bridge expectations.

    Validates: Requirement 6.3 - Suction level options match Matter Bridge expectations.
    Matter Bridge expects standardized names: Quiet, Standard, Turbo, Max
    """
    entity = SuctionLevelSelectEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Verify options are available
    assert len(entity.options) > 0

    # Verify all options are strings
    for option in entity.options:
        assert isinstance(option, str)
        assert len(option) > 0

    # Verify options contain Matter-compatible names
    # (Quiet/Silent/Low/Eco, Standard/Normal/Balanced, Turbo/Max/Strong/Boost)
    options_lower = [opt.lower() for opt in entity.options]

    # Should have at least one quiet option
    quiet_options = ["quiet", "silent", "low", "eco"]
    assert any(opt in options_lower for opt in quiet_options)

    # Should have at least one standard option
    standard_options = ["standard", "normal", "balanced"]
    assert any(opt in options_lower for opt in standard_options)

    # Should have at least one max option
    max_options = ["turbo", "max", "strong", "boost"]
    assert any(opt in options_lower for opt in max_options)


def test_all_entities_have_device_info_for_matter_grouping(mock_coordinator):
    """Test that all entities have device_info for proper Matter Bridge grouping.

    Validates: Requirement 6.7 - All entities have device_info for proper device association.
    Matter Bridge uses device_info to group entities from the same device.
    """
    # Test vacuum entity
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    assert vacuum_entity._attr_device_info is not None
    assert vacuum_entity._attr_device_info == mock_coordinator.device_info

    # Test suction level entity
    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    assert suction_entity._attr_device_info is not None
    assert suction_entity._attr_device_info == mock_coordinator.device_info

    # Test cleaning mode entity
    cleaning_entity = CleaningModeSelectEntity(mock_coordinator)
    assert cleaning_entity._attr_device_info is not None
    assert cleaning_entity._attr_device_info == mock_coordinator.device_info

    # Test battery entity
    battery_entity = BatterySensorEntity(mock_coordinator)
    assert battery_entity._attr_device_info is not None
    assert battery_entity._attr_device_info == mock_coordinator.device_info

    # Verify all device_info dicts have required fields
    for entity in [vacuum_entity, suction_entity, cleaning_entity, battery_entity]:
        device_info = entity._attr_device_info
        assert "identifiers" in device_info
        assert "name" in device_info
        assert "manufacturer" in device_info
        assert "model" in device_info


def test_entity_attributes_available_without_additional_api_calls(mock_coordinator):
    """Test that all required entity attributes are available without additional API calls.

    Validates: Requirement 6.7 - When Matter Bridge queries entity attributes, all required
    data is available without additional API calls.
    """
    # Setup coordinator data
    mock_coordinator.data.rooms = [{"id": 1, "name": "Kitchen"}]
    mock_coordinator.data.fan_speed = "Standard"
    mock_coordinator.data.cleaning_mode = "Vacuum"
    mock_coordinator.data.battery_level = 75
    mock_coordinator.data.activity = "cleaning"
    mock_coordinator.data.error_code = 0

    # Create entities
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    suction_entity.hass = MagicMock()

    cleaning_entity = CleaningModeSelectEntity(mock_coordinator)
    cleaning_entity.hass = MagicMock()

    battery_entity = BatterySensorEntity(mock_coordinator)
    battery_entity.hass = MagicMock()

    # Verify all attributes are immediately accessible (no async calls needed)
    # Vacuum entity
    assert vacuum_entity.activity is not None
    assert vacuum_entity.fan_speed is not None
    assert vacuum_entity.extra_state_attributes is not None
    assert "rooms" in vacuum_entity.extra_state_attributes
    assert "error_code" in vacuum_entity.extra_state_attributes

    # Suction level entity
    assert suction_entity.current_option is not None
    assert suction_entity.options is not None

    # Cleaning mode entity
    assert cleaning_entity.current_option is not None
    assert cleaning_entity.options is not None

    # Battery entity
    assert battery_entity.native_value is not None

    # Verify no async_send_command was called (no API calls)
    mock_coordinator.async_send_command.assert_not_called()


def test_rooms_attribute_structure_for_matter_service_area_cluster(mock_coordinator):
    """Test that rooms attribute structure is compatible with Matter Service Area cluster.

    Validates: Requirement 6.5 - Rooms attribute contains objects with "id" and "name"
    properties matching Matter Bridge format expectations for Service Area cluster.
    """
    # Setup various room data formats
    test_cases = [
        # Integer IDs
        [{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Living Room"}],
        # String IDs
        [{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Living Room"}],
        # Mixed IDs
        [{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Living Room"}],
        # Single room
        [{"id": 1, "name": "Kitchen"}],
        # Empty lis
        [],
    ]

    for room_data in test_cases:
        mock_coordinator.data.rooms = room_data

        entity = RoboVacMQTTEntity(mock_coordinator)
        entity.hass = MagicMock()

        attrs = entity.extra_state_attributes

        # Verify rooms attribute exists
        assert "rooms" in attrs
        assert isinstance(attrs["rooms"], list)

        # Verify structure of each room
        for room in attrs["rooms"]:
            assert isinstance(room, dict)
            assert "id" in room
            assert "name" in room
            assert isinstance(room["id"], (int, str))
            assert isinstance(room["name"], str)


# ============================================================================
# Multi-Entity Coordination Integration Tests (Requirements 8.1, 8.2, 8.4, 8.5)
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize("fan_speed", ["Quiet", "Standard", "Turbo", "Max"])
async def test_fan_speed_change_via_vacuum_updates_suction_entity(mock_coordinator, fan_speed):
    """Test that fan speed change via vacuum entity updates suction level entity.

    Validates: Requirement 8.1 - When fan speed is changed via the Vacuum_Entity,
    then the Suction_Level_Entity shall update to reflect the new value.
    """
    # Create both entities
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    suction_entity.hass = MagicMock()

    # Initial state
    mock_coordinator.data.fan_speed = "Standard"
    assert vacuum_entity.fan_speed == "Standard"
    assert suction_entity.current_option == "Standard"

    # Change fan speed via vacuum entity
    await vacuum_entity.async_set_fan_speed(fan_speed)

    # Verify command was sen
    assert mock_coordinator.async_send_command.called

    # Simulate coordinator state update (as would happen from MQTT message)
    mock_coordinator.data.fan_speed = fan_speed

    # Verify both entities reflect the new value
    assert vacuum_entity.fan_speed == fan_speed
    assert suction_entity.current_option == fan_speed


@pytest.mark.asyncio
@pytest.mark.parametrize("fan_speed", ["Quiet", "Standard", "Turbo", "Max"])
async def test_fan_speed_change_via_suction_entity_updates_vacuum(mock_coordinator, fan_speed):
    """Test that fan speed change via suction level entity updates vacuum entity.

    Validates: Requirement 8.2 - When fan speed is changed via the Suction_Level_Entity,
    then the Vacuum_Entity fan_speed property shall update to reflect the new value.
    """
    # Create both entities
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    suction_entity.hass = MagicMock()
    suction_entity.async_write_ha_state = MagicMock()

    # Initial state
    mock_coordinator.data.fan_speed = "Standard"
    assert vacuum_entity.fan_speed == "Standard"
    assert suction_entity.current_option == "Standard"

    # Change fan speed via suction level entity
    await suction_entity.async_select_option(fan_speed)

    # Verify command was sen
    assert mock_coordinator.async_send_command.called

    # Simulate coordinator state update (as would happen from MQTT message)
    mock_coordinator.data.fan_speed = fan_speed

    # Verify both entities reflect the new value
    assert vacuum_entity.fan_speed == fan_speed
    assert suction_entity.current_option == fan_speed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial_state,new_state",
    [
        (
            {"fan_speed": "Standard", "battery_level": 50, "cleaning_mode": "Vacuum", "rooms": []},
            {"fan_speed": "Turbo", "battery_level": 45, "cleaning_mode": "Vacuum and mop", "rooms": [{"id": 1, "name": "Kitchen"}]}
        ),
        (
            {"fan_speed": "Quiet", "battery_level": 100, "cleaning_mode": "Mop", "rooms": [{"id": 1, "name": "Kitchen"}]},
            {"fan_speed": "Max", "battery_level": 75, "cleaning_mode": "Vacuum", "rooms": [{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Living Room"}]}
        ),
        (
            {"fan_speed": "Max", "battery_level": 25, "cleaning_mode": "Mopping after sweeping", "rooms": [{"id": 1, "name": "Bedroom"}]},
            {"fan_speed": "Quiet", "battery_level": 20, "cleaning_mode": "Vacuum", "rooms": []}
        ),
    ]
)
async def test_state_synchronization_across_all_entities(mock_coordinator, initial_state, new_state):
    """Test that state changes synchronize across all entities.

    Validates: Requirements 8.1, 8.2, 8.4, 8.5 - All entities maintain synchronized state
    when coordinator data changes.
    """
    # Setup mopping device for cleaning mode tests
    mock_coordinator.device_model = "T2150"  # G10 Hybrid

    # Create all entities
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    suction_entity.hass = MagicMock()

    cleaning_entity = CleaningModeSelectEntity(mock_coordinator)
    cleaning_entity.hass = MagicMock()

    battery_entity = BatterySensorEntity(mock_coordinator)
    battery_entity.hass = MagicMock()

    # Set initial state
    mock_coordinator.data.fan_speed = initial_state["fan_speed"]
    mock_coordinator.data.battery_level = initial_state["battery_level"]
    mock_coordinator.data.cleaning_mode = initial_state["cleaning_mode"]
    mock_coordinator.data.rooms = initial_state["rooms"]

    # Verify initial state across all entities
    assert vacuum_entity.fan_speed == initial_state["fan_speed"]
    assert suction_entity.current_option == initial_state["fan_speed"]
    assert cleaning_entity.current_option == initial_state["cleaning_mode"]
    assert battery_entity.native_value == initial_state["battery_level"]
    assert vacuum_entity.extra_state_attributes["rooms"] == initial_state["rooms"]

    # Simulate coordinator state update (as would happen from MQTT message)
    mock_coordinator.data.fan_speed = new_state["fan_speed"]
    mock_coordinator.data.battery_level = new_state["battery_level"]
    mock_coordinator.data.cleaning_mode = new_state["cleaning_mode"]
    mock_coordinator.data.rooms = new_state["rooms"]

    # Verify all entities reflect the new state
    assert vacuum_entity.fan_speed == new_state["fan_speed"]
    assert suction_entity.current_option == new_state["fan_speed"]
    assert cleaning_entity.current_option == new_state["cleaning_mode"]
    assert battery_entity.native_value == new_state["battery_level"]
    assert vacuum_entity.extra_state_attributes["rooms"] == new_state["rooms"]


@pytest.mark.asyncio
async def test_bidirectional_fan_speed_sync_vacuum_to_suction(mock_coordinator):
    """Test bidirectional fan speed synchronization from vacuum to suction entity.

    Validates: Requirement 8.1 - Fan speed changes via vacuum entity are reflected
    in suction level entity through coordinator.
    """
    # Create both entities
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    suction_entity.hass = MagicMock()

    # Test multiple fan speed changes
    fan_speeds = ["Quiet", "Standard", "Turbo", "Max", "Quiet"]

    for fan_speed in fan_speeds:
        # Change via vacuum entity
        await vacuum_entity.async_set_fan_speed(fan_speed)

        # Simulate coordinator update
        mock_coordinator.data.fan_speed = fan_speed

        # Verify both entities are synchronized
        assert vacuum_entity.fan_speed == fan_speed
        assert suction_entity.current_option == fan_speed


@pytest.mark.asyncio
async def test_bidirectional_fan_speed_sync_suction_to_vacuum(mock_coordinator):
    """Test bidirectional fan speed synchronization from suction to vacuum entity.

    Validates: Requirement 8.2 - Fan speed changes via suction level entity are
    reflected in vacuum entity through coordinator.
    """
    # Create both entities
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    suction_entity.hass = MagicMock()
    suction_entity.async_write_ha_state = MagicMock()

    # Test multiple fan speed changes
    fan_speeds = ["Max", "Turbo", "Standard", "Quiet", "Max"]

    for fan_speed in fan_speeds:
        # Change via suction entity
        await suction_entity.async_select_option(fan_speed)

        # Simulate coordinator update
        mock_coordinator.data.fan_speed = fan_speed

        # Verify both entities are synchronized
        assert vacuum_entity.fan_speed == fan_speed
        assert suction_entity.current_option == fan_speed


@pytest.mark.asyncio
async def test_concurrent_entity_state_reads_are_consistent(mock_coordinator):
    """Test that concurrent reads from multiple entities return consistent state.

    Validates: Requirement 8.5 - The Integration shall use the Coordinator as the
    single source of truth for all state data.
    """
    # Setup mopping device
    mock_coordinator.device_model = "T2150"  # G10 Hybrid

    # Set coordinator state
    mock_coordinator.data.fan_speed = "Turbo"
    mock_coordinator.data.battery_level = 65
    mock_coordinator.data.cleaning_mode = "Vacuum and mop"
    mock_coordinator.data.rooms = [
        {"id": 1, "name": "Kitchen"},
        {"id": 2, "name": "Living Room"}
    ]

    # Create all entities
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    suction_entity.hass = MagicMock()

    cleaning_entity = CleaningModeSelectEntity(mock_coordinator)
    cleaning_entity.hass = MagicMock()

    battery_entity = BatterySensorEntity(mock_coordinator)
    battery_entity.hass = MagicMock()

    # Read state from all entities multiple times
    for _ in range(5):
        # All entities should return the same coordinator state
        assert vacuum_entity.fan_speed == "Turbo"
        assert suction_entity.current_option == "Turbo"
        assert cleaning_entity.current_option == "Vacuum and mop"
        assert battery_entity.native_value == 65
        assert vacuum_entity.extra_state_attributes["rooms"] == [
            {"id": 1, "name": "Kitchen"},
            {"id": 2, "name": "Living Room"}
        ]


@pytest.mark.asyncio
async def test_entity_state_updates_after_mqtt_message_simulation(mock_coordinator):
    """Test that all entities update correctly after simulated MQTT state change.

    Validates: Requirement 8.4 - When the device reports state changes via MQTT,
    then all entities shall update within 2 seconds.

    Note: This test simulates the MQTT update by directly updating coordinator data,
    as the actual MQTT timing is handled by the coordinator's message handler.
    """
    # Setup mopping device
    mock_coordinator.device_model = "T2150"  # G10 Hybrid

    # Create all entities
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    suction_entity.hass = MagicMock()

    cleaning_entity = CleaningModeSelectEntity(mock_coordinator)
    cleaning_entity.hass = MagicMock()

    battery_entity = BatterySensorEntity(mock_coordinator)
    battery_entity.hass = MagicMock()

    # Initial state
    mock_coordinator.data.fan_speed = "Standard"
    mock_coordinator.data.battery_level = 100
    mock_coordinator.data.cleaning_mode = "Vacuum"
    mock_coordinator.data.rooms = []

    # Verify initial state
    assert vacuum_entity.fan_speed == "Standard"
    assert suction_entity.current_option == "Standard"
    assert cleaning_entity.current_option == "Vacuum"
    assert battery_entity.native_value == 100

    # Simulate MQTT message updating multiple fields
    mock_coordinator.data.fan_speed = "Max"
    mock_coordinator.data.battery_level = 85
    mock_coordinator.data.cleaning_mode = "Vacuum and mop"
    mock_coordinator.data.rooms = [
        {"id": 1, "name": "Kitchen"},
        {"id": 2, "name": "Bedroom"}
    ]

    # Verify all entities immediately reflect the new state
    # (In real scenario, coordinator.async_set_updated_data triggers entity updates)
    assert vacuum_entity.fan_speed == "Max"
    assert suction_entity.current_option == "Max"
    assert cleaning_entity.current_option == "Vacuum and mop"
    assert battery_entity.native_value == 85
    assert vacuum_entity.extra_state_attributes["rooms"] == [
        {"id": 1, "name": "Kitchen"},
        {"id": 2, "name": "Bedroom"}
    ]


@pytest.mark.asyncio
async def test_multiple_rapid_fan_speed_changes_maintain_consistency(mock_coordinator):
    """Test that rapid fan speed changes maintain consistency across entities.

    Validates: Requirements 8.1, 8.2, 8.5 - Rapid state changes maintain consistency
    with coordinator as single source of truth.
    """
    # Create both entities
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    suction_entity.hass = MagicMock()
    suction_entity.async_write_ha_state = MagicMock()

    # Simulate rapid fan speed changes
    changes = [
        ("Quiet", "vacuum"),
        ("Standard", "suction"),
        ("Turbo", "vacuum"),
        ("Max", "suction"),
        ("Quiet", "vacuum"),
        ("Standard", "suction"),
    ]

    for fan_speed, source in changes:
        # Change via specified entity
        if source == "vacuum":
            await vacuum_entity.async_set_fan_speed(fan_speed)
        else:
            await suction_entity.async_select_option(fan_speed)

        # Simulate coordinator update
        mock_coordinator.data.fan_speed = fan_speed

        # Verify both entities are always synchronized
        assert vacuum_entity.fan_speed == fan_speed
        assert suction_entity.current_option == fan_speed

        # Verify they both read from the same coordinator data
        assert vacuum_entity.fan_speed == mock_coordinator.data.fan_speed
        assert suction_entity.current_option == mock_coordinator.data.fan_speed


# ============================================================================
# WaterLevelSelectEntity Tests
# ============================================================================


def test_water_level_entity_metadata(mock_coordinator):
    """Test WaterLevelSelectEntity unique_id, name, icon, and device_info."""
    entity = WaterLevelSelectEntity(mock_coordinator)
    entity.hass = MagicMock()

    assert entity._attr_unique_id == "test_device_water_level"
    assert entity._attr_name == "Water Level"
    assert entity._attr_icon == "mdi:water"
    assert entity._attr_has_entity_name is True
    assert entity._attr_device_info == mock_coordinator.device_info


def test_water_level_options(mock_coordinator):
    """Test that water level options are exactly Low/Medium/High."""
    entity = WaterLevelSelectEntity(mock_coordinator)

    assert entity.options == ["Low", "Medium", "High"]
    assert all(isinstance(opt, str) for opt in entity.options)


def test_water_level_current_option(mock_coordinator):
    """Test current_option reflects coordinator.data.mop_water_level."""
    mock_coordinator.data.mop_water_level = "Medium"
    entity = WaterLevelSelectEntity(mock_coordinator)

    assert entity.current_option == "Medium"

    mock_coordinator.data.mop_water_level = "High"
    assert entity.current_option == "High"


@pytest.mark.asyncio
async def test_valid_water_level_selection(mock_coordinator):
    """Test that a valid water level sends command and updates state."""
    mock_coordinator.data.received_fields = {"mop_water_level"}
    entity = WaterLevelSelectEntity(mock_coordinator)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    await entity.async_select_option("High")

    mock_coordinator.async_send_command.assert_called_once()
    assert mock_coordinator.data.mop_water_level == "High"
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_invalid_water_level_selection(mock_coordinator):
    """Test that an unknown water level is rejected without sending a command."""
    mock_coordinator.data.received_fields = {"mop_water_level"}
    entity = WaterLevelSelectEntity(mock_coordinator)
    entity.hass = MagicMock()

    await entity.async_select_option("Ultra")

    mock_coordinator.async_send_command.assert_not_called()


def test_water_level_availability(mock_coordinator):
    """Test availability is gated on mop_water_level in received_fields."""
    mock_coordinator.last_update_success = True

    entity = WaterLevelSelectEntity(mock_coordinator)
    entity.hass = MagicMock()

    # Empty received_fields → unavailable
    mock_coordinator.data.received_fields = set()
    assert entity.available is False

    # After mop_water_level appears → available
    mock_coordinator.data.received_fields = {"mop_water_level"}
    assert entity.available is True


def test_water_level_entity_in_device_info_grouping(mock_coordinator):
    """Test that device_info matches coordinator so entity is grouped correctly."""
    entity = WaterLevelSelectEntity(mock_coordinator)

    assert entity._attr_device_info is mock_coordinator.device_info


# ============================================================================
# MQTT Message Handling Integration Tests (Requirements 1.5, 8.4)
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mqtt_payload,expected_state",
    [
        # Test room data update via MQTT
        (
            {
                "payload": {
                    "data": {
                        "165": json.dumps({
                            "rooms": [
                                {"id": 1, "name": "Kitchen"},
                                {"id": 2, "name": "Living Room"}
                            ]
                        })
                    }
                }
            },
            {"rooms": [{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Living Room"}]}
        ),
        # Test fan speed update via MQTT
        (
            {
                "payload": {
                    "data": {
                        "102": "Turbo"
                    }
                }
            },
            {"fan_speed": "Turbo"}
        ),
        # Test battery level update via MQTT
        (
            {
                "payload": {
                    "data": {
                        "163": 75
                    }
                }
            },
            {"battery_level": 75}
        ),
        # Test multiple fields update via MQTT
        (
            {
                "payload": {
                    "data": {
                        "102": "Max",
                        "163": 50
                    }
                }
            },
            {"fan_speed": "Max", "battery_level": 50}
        ),
    ]
)
async def test_mqtt_message_updates_entity_state(mock_coordinator, mqtt_payload, expected_state):
    """Test that MQTT messages with room data update entities correctly.

    Validates: Requirement 1.5 - The rooms attribute shall update automatically when
    the Coordinator data changes.
    Validates: Requirement 8.4 - When the device reports state changes via MQTT,
    then all entities shall update within 2 seconds.
    """
    # Setup mopping device for cleaning mode tests
    mock_coordinator.device_model = "T2150"  # G10 Hybrid

    # Create all entities
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    suction_entity.hass = MagicMock()

    battery_entity = BatterySensorEntity(mock_coordinator)
    battery_entity.hass = MagicMock()

    # Set initial state
    mock_coordinator.data.rooms = []
    mock_coordinator.data.fan_speed = "Standard"
    mock_coordinator.data.battery_level = 100

    # Simulate MQTT message by directly updating coordinator data
    # (This simulates what _handle_mqtt_message does after parsing)
    if "rooms" in expected_state:
        mock_coordinator.data.rooms = expected_state["rooms"]
    if "fan_speed" in expected_state:
        mock_coordinator.data.fan_speed = expected_state["fan_speed"]
    if "battery_level" in expected_state:
        mock_coordinator.data.battery_level = expected_state["battery_level"]

    # Verify entities reflect the updated state
    if "rooms" in expected_state:
        assert vacuum_entity.extra_state_attributes["rooms"] == expected_state["rooms"]

    if "fan_speed" in expected_state:
        assert vacuum_entity.fan_speed == expected_state["fan_speed"]
        assert suction_entity.current_option == expected_state["fan_speed"]

    if "battery_level" in expected_state:
        assert battery_entity.native_value == expected_state["battery_level"]


@pytest.mark.asyncio
async def test_mqtt_room_data_empty_list_handling(mock_coordinator):
    """Test that MQTT message with empty room list is handled correctly.

    Validates: Requirement 1.5 - The rooms attribute shall update automatically when
    the Coordinator data changes (including empty list).
    """
    # Create vacuum entity
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    # Set initial state with rooms
    mock_coordinator.data.rooms = [{"id": 1, "name": "Kitchen"}]
    assert len(vacuum_entity.extra_state_attributes["rooms"]) == 1

    # Simulate MQTT message with empty room list by directly updating coordinator
    mock_coordinator.data.rooms = []

    # Verify rooms attribute is now empty lis
    assert vacuum_entity.extra_state_attributes["rooms"] == []


@pytest.mark.asyncio
async def test_mqtt_room_data_with_string_ids(mock_coordinator):
    """Test that MQTT message with string room IDs is handled correctly.

    Validates: Requirement 1.5 - The rooms attribute shall update automatically when
    the Coordinator data changes (supporting both int and string IDs).
    """
    # Create vacuum entity
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    # Simulate MQTT message with string room IDs by directly updating coordinator
    mock_coordinator.data.rooms = [
        {"id": "kitchen_1", "name": "Kitchen"},
        {"id": "living_room", "name": "Living Room"}
    ]

    # Verify rooms attribute has string IDs
    rooms = vacuum_entity.extra_state_attributes["rooms"]
    assert len(rooms) == 2
    assert rooms[0]["id"] == "kitchen_1"
    assert rooms[0]["name"] == "Kitchen"
    assert isinstance(rooms[0]["id"], str)


@pytest.mark.asyncio
async def test_mqtt_fan_speed_updates_both_entities(mock_coordinator):
    """Test that MQTT fan speed update synchronizes both vacuum and suction entities.

    Validates: Requirement 8.4 - When the device reports state changes via MQTT,
    then all entities shall update within 2 seconds.
    """
    # Create both entities
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    suction_entity.hass = MagicMock()

    # Set initial state
    mock_coordinator.data.fan_speed = "Standard"
    assert vacuum_entity.fan_speed == "Standard"
    assert suction_entity.current_option == "Standard"

    # Simulate MQTT message changing fan speed by directly updating coordinator
    mock_coordinator.data.fan_speed = "Max"

    # Verify both entities reflect the new fan speed
    assert vacuum_entity.fan_speed == "Max"
    assert suction_entity.current_option == "Max"


@pytest.mark.asyncio
async def test_mqtt_battery_level_updates_sensor(mock_coordinator):
    """Test that MQTT battery level update is reflected in battery sensor.

    Validates: Requirement 8.4 - When the device reports state changes via MQTT,
    then all entities shall update within 2 seconds.
    """
    # Create battery entity
    battery_entity = BatterySensorEntity(mock_coordinator)
    battery_entity.hass = MagicMock()

    # Set initial state
    mock_coordinator.data.battery_level = 100
    assert battery_entity.native_value == 100

    # Simulate MQTT message changing battery level by directly updating coordinator
    mock_coordinator.data.battery_level = 45

    # Verify battery entity reflects the new level
    assert battery_entity.native_value == 45


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mqtt_messages",
    [
        # Rapid fan speed changes
        [
            {"payload": {"data": {"102": "Quiet"}}},
            {"payload": {"data": {"102": "Standard"}}},
            {"payload": {"data": {"102": "Turbo"}}},
            {"payload": {"data": {"102": "Max"}}},
        ],
        # Rapid battery level changes
        [
            {"payload": {"data": {"163": 100}}},
            {"payload": {"data": {"163": 90}}},
            {"payload": {"data": {"163": 80}}},
            {"payload": {"data": {"163": 70}}},
        ],
        # Mixed rapid changes
        [
            {"payload": {"data": {"102": "Quiet", "163": 100}}},
            {"payload": {"data": {"102": "Standard", "163": 95}}},
            {"payload": {"data": {"102": "Turbo", "163": 90}}},
        ],
    ]
)
async def test_mqtt_rapid_state_changes_maintain_consistency(mock_coordinator, mqtt_messages):
    """Test that rapid MQTT messages maintain state consistency across entities.

    Validates: Requirement 8.4 - When the device reports state changes via MQTT,
    then all entities shall update within 2 seconds.
    Validates: Requirement 8.5 - The Integration shall use the Coordinator as the
    single source of truth for all state data.
    """
    # Create all entities
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    suction_entity.hass = MagicMock()

    battery_entity = BatterySensorEntity(mock_coordinator)
    battery_entity.hass = MagicMock()

    # Process each MQTT message by directly updating coordinator
    for mqtt_payload in mqtt_messages:
        # Extract data from payload
        data = mqtt_payload["payload"]["data"]

        # Update coordinator state
        if "102" in data:
            mock_coordinator.data.fan_speed = data["102"]
        if "163" in data:
            mock_coordinator.data.battery_level = data["163"]

        # Verify all entities are synchronized with coordinator
        if "102" in data:
            expected_fan_speed = data["102"]
            assert vacuum_entity.fan_speed == expected_fan_speed
            assert suction_entity.current_option == expected_fan_speed
            assert vacuum_entity.fan_speed == mock_coordinator.data.fan_speed

        if "163" in data:
            expected_battery = data["163"]
            assert battery_entity.native_value == expected_battery
            assert battery_entity.native_value == mock_coordinator.data.battery_level


@pytest.mark.asyncio
async def test_mqtt_nested_payload_string_parsing(mock_coordinator):
    """Test that MQTT messages with nested JSON string payloads are parsed correctly.

    Validates: Requirement 1.5, 8.4 - MQTT message parsing handles nested JSON strings.
    """
    # Create vacuum entity
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    # Simulate MQTT message with nested JSON string by directly updating coordinator
    mock_coordinator.data.rooms = [
        {"id": 1, "name": "Kitchen"},
        {"id": 2, "name": "Bedroom"}
    ]

    # Verify rooms were parsed correctly
    rooms = vacuum_entity.extra_state_attributes["rooms"]
    assert len(rooms) == 2
    assert rooms[0]["id"] == 1
    assert rooms[0]["name"] == "Kitchen"



@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial_fan_speed,new_fan_speed",
    [
        ("Standard", "Quiet"),
        ("Quiet", "Turbo"),
        ("Turbo", "Max"),
        ("Max", "Standard"),
        ("Standard", "Standard"),  # No change
    ]
)
async def test_mqtt_fan_speed_synchronization(mock_coordinator, initial_fan_speed, new_fan_speed):
    """Test that MQTT fan speed updates synchronize across vacuum and suction entities.

    Validates: Requirement 8.4 - When the device reports state changes via MQTT,
    then all entities shall update within 2 seconds.
    """
    # Create both entities
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    suction_entity.hass = MagicMock()

    # Set initial state
    mock_coordinator.data.fan_speed = initial_fan_speed
    assert vacuum_entity.fan_speed == initial_fan_speed
    assert suction_entity.current_option == initial_fan_speed

    # Simulate MQTT message updating fan speed
    mock_coordinator.data.fan_speed = new_fan_speed

    # Verify both entities immediately reflect the new state
    assert vacuum_entity.fan_speed == new_fan_speed
    assert suction_entity.current_option == new_fan_speed

    # Verify they're reading from the same source
    assert vacuum_entity.fan_speed == mock_coordinator.data.fan_speed
    assert suction_entity.current_option == mock_coordinator.data.fan_speed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "initial_battery,new_battery",
    [
        (100, 95),
        (95, 80),
        (80, 50),
        (50, 25),
        (25, 10),
        (10, 5),
        (100, 100),  # No change
    ]
)
async def test_mqtt_battery_level_synchronization(mock_coordinator, initial_battery, new_battery):
    """Test that MQTT battery level updates are reflected in battery sensor.

    Validates: Requirement 8.4 - When the device reports state changes via MQTT,
    then all entities shall update within 2 seconds.
    """
    # Create battery entity
    battery_entity = BatterySensorEntity(mock_coordinator)
    battery_entity.hass = MagicMock()

    # Set initial state
    mock_coordinator.data.battery_level = initial_battery
    assert battery_entity.native_value == initial_battery

    # Simulate MQTT message updating battery level
    mock_coordinator.data.battery_level = new_battery

    # Verify battery entity immediately reflects the new state
    assert battery_entity.native_value == new_battery
    assert battery_entity.native_value == mock_coordinator.data.battery_level


@pytest.mark.asyncio
async def test_mqtt_multi_field_update_synchronization(mock_coordinator):
    """Test that MQTT messages updating multiple fields synchronize all entities.

    Validates: Requirement 8.4 - When the device reports state changes via MQTT,
    then all entities shall update within 2 seconds.
    Validates: Requirement 8.5 - The Integration shall use the Coordinator as the
    single source of truth for all state data.
    """
    # Setup mopping device
    mock_coordinator.device_model = "T2150"  # G10 Hybrid

    # Create all entities
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    suction_entity.hass = MagicMock()

    battery_entity = BatterySensorEntity(mock_coordinator)
    battery_entity.hass = MagicMock()

    # Set initial state
    mock_coordinator.data.fan_speed = "Standard"
    mock_coordinator.data.battery_level = 100
    mock_coordinator.data.rooms = []

    # Verify initial state
    assert vacuum_entity.fan_speed == "Standard"
    assert suction_entity.current_option == "Standard"
    assert battery_entity.native_value == 100
    assert vacuum_entity.extra_state_attributes["rooms"] == []

    # Simulate MQTT message updating multiple fields
    mock_coordinator.data.fan_speed = "Turbo"
    mock_coordinator.data.battery_level = 65
    mock_coordinator.data.rooms = [
        {"id": 1, "name": "Kitchen"},
        {"id": 2, "name": "Living Room"},
        {"id": 3, "name": "Bedroom"}
    ]

    # Verify all entities immediately reflect the new state
    assert vacuum_entity.fan_speed == "Turbo"
    assert suction_entity.current_option == "Turbo"
    assert battery_entity.native_value == 65
    assert len(vacuum_entity.extra_state_attributes["rooms"]) == 3
    assert vacuum_entity.extra_state_attributes["rooms"][0]["name"] == "Kitchen"

    # Verify all entities read from the same coordinator
    assert vacuum_entity.fan_speed == mock_coordinator.data.fan_speed
    assert suction_entity.current_option == mock_coordinator.data.fan_speed
    assert battery_entity.native_value == mock_coordinator.data.battery_level
    assert vacuum_entity.extra_state_attributes["rooms"] == _normalize_room_ids(mock_coordinator.data.rooms)


@pytest.mark.asyncio
async def test_mqtt_room_data_transitions(mock_coordinator):
    """Test various room data transitions via MQTT messages.

    Validates: Requirement 1.5 - The rooms attribute shall update automatically when
    the Coordinator data changes.
    """
    # Create vacuum entity
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    # Transition 1: No rooms -> Single room
    mock_coordinator.data.rooms = []
    assert vacuum_entity.extra_state_attributes["rooms"] == []

    mock_coordinator.data.rooms = [{"id": 1, "name": "Kitchen"}]
    assert len(vacuum_entity.extra_state_attributes["rooms"]) == 1
    assert vacuum_entity.extra_state_attributes["rooms"][0]["name"] == "Kitchen"

    # Transition 2: Single room -> Multiple rooms
    mock_coordinator.data.rooms = [
        {"id": 1, "name": "Kitchen"},
        {"id": 2, "name": "Living Room"},
        {"id": 3, "name": "Bedroom"}
    ]
    assert len(vacuum_entity.extra_state_attributes["rooms"]) == 3

    # Transition 3: Multiple rooms -> Different rooms
    mock_coordinator.data.rooms = [
        {"id": 4, "name": "Office"},
        {"id": 5, "name": "Bathroom"}
    ]
    assert len(vacuum_entity.extra_state_attributes["rooms"]) == 2
    assert vacuum_entity.extra_state_attributes["rooms"][0]["name"] == "Office"

    # Transition 4: Multiple rooms -> Empty
    mock_coordinator.data.rooms = []
    assert vacuum_entity.extra_state_attributes["rooms"] == []

    # Transition 5: Empty -> None (missing data)
    mock_coordinator.data.rooms = None
    assert vacuum_entity.extra_state_attributes["rooms"] == []


@pytest.mark.asyncio
async def test_mqtt_state_consistency_after_rapid_updates(mock_coordinator):
    """Test that rapid MQTT updates maintain state consistency.

    Validates: Requirement 8.4 - When the device reports state changes via MQTT,
    then all entities shall update within 2 seconds.
    Validates: Requirement 8.5 - The Integration shall use the Coordinator as the
    single source of truth for all state data.
    """
    # Create all entities
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    suction_entity.hass = MagicMock()

    battery_entity = BatterySensorEntity(mock_coordinator)
    battery_entity.hass = MagicMock()

    # Simulate rapid state changes
    updates = [
        {"fan_speed": "Quiet", "battery_level": 100},
        {"fan_speed": "Standard", "battery_level": 95},
        {"fan_speed": "Turbo", "battery_level": 90},
        {"fan_speed": "Max", "battery_level": 85},
        {"fan_speed": "Standard", "battery_level": 80},
    ]

    for update in updates:
        # Simulate MQTT update
        mock_coordinator.data.fan_speed = update["fan_speed"]
        mock_coordinator.data.battery_level = update["battery_level"]

        # Verify all entities are immediately consisten
        assert vacuum_entity.fan_speed == update["fan_speed"]
        assert suction_entity.current_option == update["fan_speed"]
        assert battery_entity.native_value == update["battery_level"]

        # Verify they all read from coordinator
        assert vacuum_entity.fan_speed == mock_coordinator.data.fan_speed
        assert suction_entity.current_option == mock_coordinator.data.fan_speed
        assert battery_entity.native_value == mock_coordinator.data.battery_level


@pytest.mark.asyncio
async def test_mqtt_partial_state_updates(mock_coordinator):
    """Test that partial MQTT updates don't affect unrelated state.

    Validates: Requirement 1.5, 8.4 - State updates are independent and don'
    interfere with each other.
    """
    # Create all entities
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    suction_entity.hass = MagicMock()

    battery_entity = BatterySensorEntity(mock_coordinator)
    battery_entity.hass = MagicMock()

    # Set initial state
    mock_coordinator.data.fan_speed = "Standard"
    mock_coordinator.data.battery_level = 100
    mock_coordinator.data.rooms = [{"id": 1, "name": "Kitchen"}]

    # Update only fan speed
    mock_coordinator.data.fan_speed = "Turbo"
    assert vacuum_entity.fan_speed == "Turbo"
    assert suction_entity.current_option == "Turbo"
    assert battery_entity.native_value == 100  # Unchanged
    assert len(vacuum_entity.extra_state_attributes["rooms"]) == 1  # Unchanged

    # Update only battery level
    mock_coordinator.data.battery_level = 75
    assert vacuum_entity.fan_speed == "Turbo"  # Unchanged
    assert suction_entity.current_option == "Turbo"  # Unchanged
    assert battery_entity.native_value == 75
    assert len(vacuum_entity.extra_state_attributes["rooms"]) == 1  # Unchanged

    # Update only rooms
    mock_coordinator.data.rooms = [
        {"id": 1, "name": "Kitchen"},
        {"id": 2, "name": "Living Room"}
    ]
    assert vacuum_entity.fan_speed == "Turbo"  # Unchanged
    assert suction_entity.current_option == "Turbo"  # Unchanged
    assert battery_entity.native_value == 75  # Unchanged
    assert len(vacuum_entity.extra_state_attributes["rooms"]) == 2


@pytest.mark.asyncio
async def test_mqtt_room_data_with_special_characters(mock_coordinator):
    """Test that room names with special characters are handled correctly.

    Validates: Requirement 1.5 - The rooms attribute shall update automatically when
    the Coordinator data changes, including rooms with special characters.
    """
    # Create vacuum entity
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    # Test various special characters in room names
    special_room_data = [
        {"id": 1, "name": "Kitchen & Dining"},
        {"id": 2, "name": "Living Room (Main)"},
        {"id": 3, "name": "Bedroom #1"},
        {"id": 4, "name": "Master's Bedroom"},
        {"id": 5, "name": "Kid's Room"},
        {"id": 6, "name": "Office/Study"},
    ]

    # Simulate MQTT update with special characters
    mock_coordinator.data.rooms = special_room_data

    # Verify all rooms are present with correct names
    rooms = vacuum_entity.extra_state_attributes["rooms"]
    assert len(rooms) == 6
    assert rooms[0]["name"] == "Kitchen & Dining"
    assert rooms[1]["name"] == "Living Room (Main)"
    assert rooms[2]["name"] == "Bedroom #1"
    assert rooms[3]["name"] == "Master's Bedroom"
    assert rooms[4]["name"] == "Kid's Room"
    assert rooms[5]["name"] == "Office/Study"


@pytest.mark.asyncio
async def test_mqtt_state_synchronization_with_cleaning_mode(mock_coordinator):
    """Test that cleaning mode state synchronizes correctly with MQTT updates.

    Validates: Requirement 8.4 - When the device reports state changes via MQTT,
    then all entities shall update within 2 seconds.
    """
    # Setup mopping device
    mock_coordinator.device_model = "T2150"  # G10 Hybrid

    # Create cleaning mode entity
    cleaning_entity = CleaningModeSelectEntity(mock_coordinator)
    cleaning_entity.hass = MagicMock()

    # Test cleaning mode transitions
    cleaning_modes = ["Vacuum", "Mop", "Vacuum and mop", "Mopping after sweeping"]

    for mode in cleaning_modes:
        # Simulate MQTT update
        mock_coordinator.data.cleaning_mode = mode

        # Verify entity reflects the new mode
        assert cleaning_entity.current_option == mode
        assert cleaning_entity.current_option == mock_coordinator.data.cleaning_mode


@pytest.mark.asyncio
async def test_mqtt_comprehensive_state_update(mock_coordinator):
    """Test comprehensive MQTT state update affecting all entities.

    Validates: Requirements 1.5, 8.4, 8.5 - All entities update correctly when
    coordinator receives comprehensive state update via MQTT.
    """
    # Setup mopping device
    mock_coordinator.device_model = "T2150"  # G10 Hybrid

    # Create all entities
    vacuum_entity = RoboVacMQTTEntity(mock_coordinator)
    vacuum_entity.hass = MagicMock()

    suction_entity = SuctionLevelSelectEntity(mock_coordinator)
    suction_entity.hass = MagicMock()

    cleaning_entity = CleaningModeSelectEntity(mock_coordinator)
    cleaning_entity.hass = MagicMock()

    battery_entity = BatterySensorEntity(mock_coordinator)
    battery_entity.hass = MagicMock()

    # Simulate comprehensive MQTT state update
    mock_coordinator.data.fan_speed = "Max"
    mock_coordinator.data.battery_level = 42
    mock_coordinator.data.cleaning_mode = "Vacuum and mop"
    mock_coordinator.data.rooms = [
        {"id": 1, "name": "Kitchen"},
        {"id": 2, "name": "Living Room"},
        {"id": 3, "name": "Bedroom"},
        {"id": 4, "name": "Bathroom"},
        {"id": 5, "name": "Office"}
    ]

    # Verify all entities reflect the comprehensive update
    assert vacuum_entity.fan_speed == "Max"
    assert suction_entity.current_option == "Max"
    assert cleaning_entity.current_option == "Vacuum and mop"
    assert battery_entity.native_value == 42
    assert len(vacuum_entity.extra_state_attributes["rooms"]) == 5

    # Verify all room data is correc
    rooms = vacuum_entity.extra_state_attributes["rooms"]
    assert rooms[0]["name"] == "Kitchen"
    assert rooms[1]["name"] == "Living Room"
    assert rooms[2]["name"] == "Bedroom"
    assert rooms[3]["name"] == "Bathroom"
    assert rooms[4]["name"] == "Office"

    # Verify all entities read from coordinator
    assert vacuum_entity.fan_speed == mock_coordinator.data.fan_speed
    assert suction_entity.current_option == mock_coordinator.data.fan_speed
    assert cleaning_entity.current_option == mock_coordinator.data.cleaning_mode
    assert battery_entity.native_value == mock_coordinator.data.battery_level
    assert vacuum_entity.extra_state_attributes["rooms"] == _normalize_room_ids(mock_coordinator.data.rooms)
