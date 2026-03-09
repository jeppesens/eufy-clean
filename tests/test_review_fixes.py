"""Tests for DPS 154 parsing, work status mapping, select entity availability,
and edge cases identified during code review."""

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from custom_components.robovac_mqtt.api.commands import (
    build_set_cleaning_mode_command,
    build_set_cleaning_intensity_command,
    build_set_water_level_command,
)
from custom_components.robovac_mqtt.api.parser import (
    _map_work_status,
    _process_cleaning_parameters,
    update_state,
)
from custom_components.robovac_mqtt.const import DPS_MAP
from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.select import (
    CleaningModeSelectEntity,
    SuctionLevelSelectEntity,
    WaterLevelSelectEntity,
    CleaningIntensitySelectEntity,
    MopIntensitySelectEntity,
)


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def mock_coordinator():
    """Fixture for a minimal coordinator mock."""
    coordinator = MagicMock(spec=EufyCleanCoordinator)
    coordinator.data = VacuumState()
    coordinator.device_id = "test_device"
    coordinator.device_name = "Test Device"
    coordinator.device_model = "T2351"
    coordinator.async_send_command = AsyncMock()
    coordinator.last_update_success = True
    return coordinator


# ── _map_work_status Tests ────────────────────────────────────────────


def _make_work_status(
    state: int,
    go_wash_mode: int | None = None,
    has_station_wash: bool = False,
):
    """Build a minimal mock WorkStatus."""
    ws = MagicMock()
    ws.state = state

    if go_wash_mode is not None:
        ws.HasField.side_effect = lambda f: f in {"go_wash"} or (
            f == "station" and has_station_wash
        )
        ws.go_wash.mode = go_wash_mode
    elif has_station_wash:
        ws.HasField.side_effect = lambda f: f == "station"
        ws.station.HasField.return_value = True
    else:
        ws.HasField.return_value = False
    return ws


def test_map_work_status_idle():
    """State 0 and 1 map to idle."""
    assert _map_work_status(_make_work_status(0)) == "idle"
    assert _map_work_status(_make_work_status(1)) == "idle"


def test_map_work_status_error():
    """State 2 maps to error."""
    assert _map_work_status(_make_work_status(2)) == "error"


def test_map_work_status_docked():
    """State 3 maps to docked (charging)."""
    assert _map_work_status(_make_work_status(3)) == "docked"


def test_map_work_status_cleaning():
    """State 4 maps to cleaning."""
    assert _map_work_status(_make_work_status(4)) == "cleaning"


def test_map_work_status_returning():
    """State 7 maps to returning."""
    assert _map_work_status(_make_work_status(7)) == "returning"


def test_map_work_status_washing_shows_docked():
    """State 5 with go_wash mode WASHING (1) should map to docked, not cleaning.

    The vacuum is physically at the station when washing; users expect "docked".
    """
    ws = _make_work_status(5, go_wash_mode=1)
    assert _map_work_status(ws) == "docked"


def test_map_work_status_drying_shows_docked():
    """State 5 with go_wash mode DRYING (2) should map to docked."""
    ws = _make_work_status(5, go_wash_mode=2)
    assert _map_work_status(ws) == "docked"


def test_map_work_status_navigation_to_wash_shows_cleaning():
    """State 5 with go_wash mode NAVIGATION (0) should still be cleaning."""
    ws = _make_work_status(5, go_wash_mode=0)
    assert _map_work_status(ws) == "cleaning"


def test_map_work_status_station_wash_drying_shows_docked():
    """State 5 with station.washing_drying_system should map to docked."""
    ws = _make_work_status(5, has_station_wash=True)
    assert _map_work_status(ws) == "docked"


def test_map_work_status_plain_cleaning():
    """State 5 without go_wash or station fields is normal cleaning."""
    ws = _make_work_status(5)
    assert _map_work_status(ws) == "cleaning"


# ── _process_cleaning_parameters Tests ────────────────────────────────


def _mock_clean_param(**kwargs):
    """Build a mock CleanParam protobuf message."""
    mock = MagicMock()
    # Default: nothing has a field
    all_fields = {
        "clean_type", "fan", "mop_mode", "clean_extent",
        "clean_carpet", "smart_mode_sw",
    }
    present_fields = set()

    if "clean_type" in kwargs:
        mock.clean_type.value = kwargs["clean_type"]
        present_fields.add("clean_type")

    if "fan_suction" in kwargs:
        mock.fan.suction = kwargs["fan_suction"]
        present_fields.add("fan")

    if "mop_level" in kwargs:
        mock.mop_mode.level = kwargs["mop_level"]
        mock.mop_mode.corner_clean = kwargs.get("corner_clean", 0)
        present_fields.add("mop_mode")

    if "clean_extent" in kwargs:
        mock.clean_extent.value = kwargs["clean_extent"]
        present_fields.add("clean_extent")

    if "carpet_strategy" in kwargs:
        mock.clean_carpet.strategy = kwargs["carpet_strategy"]
        present_fields.add("clean_carpet")

    if "smart_mode" in kwargs:
        mock.smart_mode_sw = kwargs["smart_mode"]
        present_fields.add("smart_mode_sw")

    mock.HasField.side_effect = lambda f: f in present_fields
    return mock


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_process_cleaning_params_cleaning_mode(mock_decode):
    """Test DPS 154 parsing extracts cleaning mode."""
    clean_param = _mock_clean_param(clean_type=2)  # SWEEP_AND_MOP

    mock_response = MagicMock()
    mock_response.HasField.side_effect = lambda f: f == "clean_param"
    mock_response.clean_param = clean_param
    mock_decode.return_value = mock_response

    state = VacuumState()
    changes: dict = {}
    _process_cleaning_parameters(state, "encoded", changes)

    assert changes["cleaning_mode"] == "Vacuum and mop"
    assert "cleaning_mode" in changes.get("received_fields", set())


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_process_cleaning_params_fan_speed(mock_decode):
    """Test DPS 154 parsing extracts fan speed with aligned naming."""
    clean_param = _mock_clean_param(fan_suction=4)  # Should be "Boost IQ"

    mock_response = MagicMock()
    mock_response.HasField.side_effect = lambda f: f == "clean_param"
    mock_response.clean_param = clean_param
    mock_decode.return_value = mock_response

    state = VacuumState()
    changes: dict = {}
    _process_cleaning_parameters(state, "encoded", changes)

    assert changes["fan_speed"] == "Boost IQ"


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_process_cleaning_params_mop_water_level(mock_decode):
    """Test DPS 154 parsing extracts mop water level."""
    clean_param = _mock_clean_param(mop_level=0)  # LOW

    mock_response = MagicMock()
    mock_response.HasField.side_effect = lambda f: f == "clean_param"
    mock_response.clean_param = clean_param
    mock_decode.return_value = mock_response

    state = VacuumState()
    changes: dict = {}
    _process_cleaning_parameters(state, "encoded", changes)

    assert changes["mop_water_level"] == "Low"
    assert "mop_water_level" in changes.get("received_fields", set())


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_process_cleaning_params_corner_cleaning_normal(mock_decode):
    """Test DPS 154 correctly tracks corner_clean == 0 (Normal).

    Previously, the guard `!= 0` prevented Normal mode from being tracked.
    """
    clean_param = _mock_clean_param(mop_level=1, corner_clean=0)

    mock_response = MagicMock()
    mock_response.HasField.side_effect = lambda f: f == "clean_param"
    mock_response.clean_param = clean_param
    mock_decode.return_value = mock_response

    state = VacuumState()
    changes: dict = {}
    _process_cleaning_parameters(state, "encoded", changes)

    assert changes["corner_cleaning"] == "Normal"
    assert "corner_cleaning" in changes.get("received_fields", set())


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_process_cleaning_params_corner_cleaning_deep(mock_decode):
    """Test DPS 154 correctly tracks corner_clean == 1 (Deep)."""
    clean_param = _mock_clean_param(mop_level=1, corner_clean=1)

    mock_response = MagicMock()
    mock_response.HasField.side_effect = lambda f: f == "clean_param"
    mock_response.clean_param = clean_param
    mock_decode.return_value = mock_response

    state = VacuumState()
    changes: dict = {}
    _process_cleaning_parameters(state, "encoded", changes)

    assert changes["corner_cleaning"] == "Deep"


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_process_cleaning_params_cleaning_intensity(mock_decode):
    """Test DPS 154 parsing extracts cleaning intensity."""
    clean_param = _mock_clean_param(clean_extent=2)  # Quick

    mock_response = MagicMock()
    mock_response.HasField.side_effect = lambda f: f == "clean_param"
    mock_response.clean_param = clean_param
    mock_decode.return_value = mock_response

    state = VacuumState()
    changes: dict = {}
    _process_cleaning_parameters(state, "encoded", changes)

    assert changes["cleaning_intensity"] == "Quick"
    assert "cleaning_intensity" in changes.get("received_fields", set())


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_process_cleaning_params_carpet_strategy(mock_decode):
    """Test DPS 154 parsing extracts carpet strategy."""
    clean_param = _mock_clean_param(carpet_strategy=1)  # Avoid

    mock_response = MagicMock()
    mock_response.HasField.side_effect = lambda f: f == "clean_param"
    mock_response.clean_param = clean_param
    mock_decode.return_value = mock_response

    state = VacuumState()
    changes: dict = {}
    _process_cleaning_parameters(state, "encoded", changes)

    assert changes["carpet_strategy"] == "Avoid"
    assert "carpet_strategy" in changes.get("received_fields", set())


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_process_cleaning_params_smart_mode(mock_decode):
    """Test DPS 154 parsing extracts smart mode."""
    clean_param = _mock_clean_param(smart_mode=True)

    mock_response = MagicMock()
    mock_response.HasField.side_effect = lambda f: f == "clean_param"
    mock_response.clean_param = clean_param
    mock_decode.return_value = mock_response

    state = VacuumState()
    changes: dict = {}
    _process_cleaning_parameters(state, "encoded", changes)

    assert changes["smart_mode"] is True
    assert "smart_mode" in changes.get("received_fields", set())


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_process_cleaning_params_all_fields(mock_decode):
    """Test DPS 154 parsing extracts all fields when all are present."""
    clean_param = _mock_clean_param(
        clean_type=1,  # MOP_ONLY
        fan_suction=2,  # Turbo
        mop_level=2,  # HIGH
        corner_clean=1,  # Deep
        clean_extent=0,  # Normal
        carpet_strategy=2,  # Ignore
        smart_mode=False,
    )

    mock_response = MagicMock()
    mock_response.HasField.side_effect = lambda f: f == "clean_param"
    mock_response.clean_param = clean_param
    mock_decode.return_value = mock_response

    state = VacuumState()
    changes: dict = {}
    _process_cleaning_parameters(state, "encoded", changes)

    assert changes["cleaning_mode"] == "Mop"
    assert changes["fan_speed"] == "Turbo"
    assert changes["mop_water_level"] == "High"
    assert changes["corner_cleaning"] == "Deep"
    assert changes["cleaning_intensity"] == "Normal"
    assert changes["carpet_strategy"] == "Ignore"
    assert changes["smart_mode"] is False


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_process_cleaning_params_decode_failure(mock_decode):
    """Test graceful handling when neither response nor request decodes."""
    mock_decode.side_effect = Exception("bad protobuf")

    state = VacuumState()
    changes: dict = {}
    _process_cleaning_parameters(state, "garbage", changes)

    # No fields should be set
    assert "cleaning_mode" not in changes
    assert "fan_speed" not in changes


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_process_cleaning_params_fallback_to_request(mock_decode):
    """Test that parser falls back to CleanParamRequest when Response fails."""
    call_count = 0
    clean_param = _mock_clean_param(clean_type=0)  # SWEEP_ONLY

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: CleanParamResponse fails
            raise Exception("not a response")
        else:
            # Second call: CleanParamRequest succeeds
            mock_request = MagicMock()
            mock_request.HasField.side_effect = lambda f: f == "clean_param"
            mock_request.clean_param = clean_param
            return mock_request

    mock_decode.side_effect = side_effect

    state = VacuumState()
    changes: dict = {}
    _process_cleaning_parameters(state, "encoded", changes)

    assert changes["cleaning_mode"] == "Vacuum"


# ── Select Entity Availability Tests ──────────────────────────────────


def test_suction_level_unavailable_without_fan_speed(mock_coordinator):
    """SuctionLevelSelectEntity should be unavailable until fan_speed is tracked."""
    mock_coordinator.data.received_fields = set()
    mock_coordinator.last_updated = None

    entity = SuctionLevelSelectEntity(mock_coordinator)
    assert entity.available is False


def test_suction_level_available_with_fan_speed(mock_coordinator):
    """SuctionLevelSelectEntity should be available once fan_speed is tracked."""
    mock_coordinator.data.received_fields = {"fan_speed"}
    mock_coordinator.last_updated = None

    entity = SuctionLevelSelectEntity(mock_coordinator)
    assert entity.available is True


def test_cleaning_mode_unavailable_without_field(mock_coordinator):
    """CleaningModeSelectEntity should be unavailable until cleaning_mode is tracked."""
    mock_coordinator.data.received_fields = set()
    mock_coordinator.last_updated = None

    entity = CleaningModeSelectEntity(mock_coordinator)
    assert entity.available is False


def test_cleaning_mode_available_with_field(mock_coordinator):
    """CleaningModeSelectEntity should be available once cleaning_mode is tracked."""
    mock_coordinator.data.received_fields = {"cleaning_mode"}
    mock_coordinator.last_updated = None

    entity = CleaningModeSelectEntity(mock_coordinator)
    assert entity.available is True


def test_water_level_unavailable_without_field(mock_coordinator):
    """WaterLevelSelectEntity should be unavailable until mop_water_level is tracked."""
    mock_coordinator.data.received_fields = set()
    mock_coordinator.last_updated = None

    entity = WaterLevelSelectEntity(mock_coordinator)
    assert entity.available is False


def test_water_level_available_with_field(mock_coordinator):
    """WaterLevelSelectEntity should be available once mop_water_level is tracked."""
    mock_coordinator.data.received_fields = {"mop_water_level"}
    mock_coordinator.last_updated = None

    entity = WaterLevelSelectEntity(mock_coordinator)
    assert entity.available is True


def test_cleaning_intensity_unavailable_without_field(mock_coordinator):
    """CleaningIntensitySelectEntity should be unavailable until cleaning_intensity is tracked."""
    mock_coordinator.data.received_fields = set()
    mock_coordinator.last_updated = None

    entity = CleaningIntensitySelectEntity(mock_coordinator)
    assert entity.available is False


def test_mop_intensity_unavailable_without_field(mock_coordinator):
    """MopIntensitySelectEntity should be unavailable until mop_water_level is tracked."""
    mock_coordinator.data.received_fields = set()
    mock_coordinator.last_updated = None

    entity = MopIntensitySelectEntity(mock_coordinator)
    assert entity.available is False


# ── Invalid Command Edge Case Tests ───────────────────────────────────


def test_set_cleaning_mode_invalid():
    """Invalid cleaning mode should return empty dict."""
    result = build_set_cleaning_mode_command("nonexistent_mode")
    assert result == {}


def test_set_water_level_invalid():
    """Invalid water level should return empty dict."""
    result = build_set_water_level_command("super_high")
    assert result == {}


def test_set_cleaning_intensity_invalid():
    """Invalid cleaning intensity should return empty dict."""
    result = build_set_cleaning_intensity_command("ultra_deep")
    assert result == {}


# ── Room Name Parsing Test ────────────────────────────────────────────


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_map_data_room_names_no_id_suffix(mock_decode):
    """Room names from parser should NOT contain (ID: N) suffix.

    The suffix was previously embedded in parser output, leaking into
    Matter segments, state attributes, and segment change detection.
    """
    # Mock RoomParams response
    room1 = MagicMock()
    room1.id = 10
    room1.name = "Kitchen"
    room2 = MagicMock()
    room2.id = 12
    room2.name = "  Living Room  "  # With whitespace
    room3 = MagicMock()
    room3.id = 15
    room3.name = ""  # Empty name

    mock_room_params = MagicMock()
    mock_room_params.map_id = 5
    mock_room_params.rooms = [room1, room2, room3]

    # First call (UniversalDataResponse) fails, second (RoomParams) succeeds
    mock_decode.side_effect = [Exception("not universal"), mock_room_params]

    from custom_components.robovac_mqtt.api.parser import _parse_map_data

    result = _parse_map_data("encoded_value")

    assert result is not None
    assert result["map_id"] == 5
    rooms = result["rooms"]
    assert len(rooms) == 3
    assert rooms[0] == {"id": 10, "name": "Kitchen"}
    assert rooms[1] == {"id": 12, "name": "Living Room"}  # Whitespace stripped
    assert rooms[2] == {"id": 15, "name": "Room 15"}  # Fallback for empty


# ── Work Mode Tracking Test ───────────────────────────────────────────


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_work_mode_names_mapping(mock_decode):
    """Test that work mode values are correctly mapped to names."""
    from custom_components.robovac_mqtt.const import WORK_MODE_NAMES

    # Verify all expected modes are mapped
    assert WORK_MODE_NAMES[0] == "Auto"
    assert WORK_MODE_NAMES[1] == "Room"
    assert WORK_MODE_NAMES[3] == "Spot"
    assert WORK_MODE_NAMES[8] == "Scene"
