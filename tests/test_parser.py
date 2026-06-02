"""Unit tests for api/parser.py: work status mapping, cleaning parameters,
room name parsing, deduplication, and related const lookups."""

from unittest.mock import MagicMock, patch

from custom_components.robovac_mqtt.api.parser import (
    _deduplicate_room_names,
    _map_task_status,
    _map_work_status,
    _parse_map_data,
    _process_cleaning_parameters,
)
from custom_components.robovac_mqtt.const import WORK_MODE_NAMES
from custom_components.robovac_mqtt.models import VacuumState

# ── Helpers ──────────────────────────────────────────────────────────


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


def _mock_clean_param(**kwargs):
    """Build a mock CleanParam protobuf message."""
    mock = MagicMock()
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
        mock.smart_mode_sw.value = kwargs["smart_mode"]
        present_fields.add("smart_mode_sw")

    mock.HasField.side_effect = lambda f: f in present_fields
    return mock


# ── _map_work_status Tests ───────────────────────────────────────────


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
    """State 5 with go_wash mode WASHING (1) should map to docked, not cleaning."""
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


def test_map_work_status_state_15_paused():
    """Test WorkStatus state 15 maps to paused."""
    ws = _make_work_status(15)
    assert _map_work_status(ws) == "paused"


def test_map_work_status_cleaning_paused():
    """State 5 with cleaning.state=PAUSED (no go_wash) should map to paused."""
    ws = MagicMock()
    ws.state = 5
    ws.HasField.side_effect = lambda f: f == "cleaning"
    ws.cleaning.state = 1  # PAUSED
    assert _map_work_status(ws) == "paused"


def test_map_work_status_cleaning_paused_with_go_wash_ignored():
    """State 5 with cleaning.state=PAUSED AND go_wash present should NOT map to paused.

    When go_wash is active (even NAVIGATION mode), the robot is heading to/at
    the dock for a mop wash. The existing flapping-prevention logic handles
    this scenario; we must not override it with "paused".
    """
    ws = MagicMock()
    ws.state = 5
    ws.HasField.side_effect = lambda f: f in {"cleaning", "go_wash"}
    ws.cleaning.state = 1  # PAUSED
    ws.go_wash.mode = 0  # NAVIGATION
    assert _map_work_status(ws) == "cleaning"


def test_map_work_status_cleaning_doing():
    """State 5 with cleaning.state=DOING should still map to cleaning."""
    ws = MagicMock()
    ws.state = 5
    ws.HasField.side_effect = lambda f: f == "cleaning"
    ws.cleaning.state = 0  # DOING
    assert _map_work_status(ws) == "cleaning"


def test_map_work_status_emptying_dust():
    """Test WorkStatus state 3 with station.dust_collection_system.state=EMPTYING."""
    ws = MagicMock()
    ws.state = 3
    ws.HasField.side_effect = lambda f: f == "station"
    ws.station.dust_collection_system.state = 0  # EMPTYING
    assert _map_work_status(ws) == "docked"


def test_map_task_status_emptying_dust():
    """Test task status when emptying dust at dock."""
    ws = MagicMock()
    ws.state = 3
    ws.HasField.side_effect = lambda f: f in {"station", "dust_collection_system"}
    ws.station.HasField.side_effect = lambda f: f == "dust_collection_system"
    ws.station.dust_collection_system.state = 0  # EMPTYING
    # is_resumable is False
    assert _map_task_status(ws, "Idle") == "Emptying Dust"


# ── _process_cleaning_parameters Tests ───────────────────────────────


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
    clean_param = _mock_clean_param(fan_suction=4)  # Should be "Boost_IQ"

    mock_response = MagicMock()
    mock_response.HasField.side_effect = lambda f: f == "clean_param"
    mock_response.clean_param = clean_param
    mock_decode.return_value = mock_response

    state = VacuumState()
    changes: dict = {}
    _process_cleaning_parameters(state, "encoded", changes)

    assert changes["fan_speed"] == "Boost_IQ"


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
    """Test DPS 154 correctly tracks corner_clean == 0 (Normal)."""
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
            raise ValueError("not a response")
        mock_request = MagicMock()
        mock_request.HasField.side_effect = lambda f: f == "clean_param"
        mock_request.clean_param = clean_param
        return mock_request

    mock_decode.side_effect = side_effect

    state = VacuumState()
    changes: dict = {}
    _process_cleaning_parameters(state, "encoded", changes)

    assert changes["cleaning_mode"] == "Vacuum"


# ── Room Name Parsing Tests ──────────────────────────────────────────


@patch("custom_components.robovac_mqtt.api.parser.decode")
def test_map_data_room_names_no_id_suffix(mock_decode):
    """Room names from parser should NOT contain (ID: N) suffix."""
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

    result = _parse_map_data("encoded_value")

    assert result is not None
    assert result["map_id"] == 5
    rooms = result["rooms"]
    assert len(rooms) == 3
    assert rooms[0] == {"id": 10, "name": "Kitchen"}
    assert rooms[1] == {"id": 12, "name": "Living Room"}  # Whitespace stripped
    assert rooms[2] == {"id": 15, "name": "Room 15"}  # Fallback for empty


# ── Room Name Deduplication Tests ────────────────────────────────────


def test_deduplicate_room_names():
    """Test that duplicate room names get a numbered suffix."""
    rooms = [
        {"id": 1, "name": "Kitchen"},
        {"id": 2, "name": "Kitchen"},
        {"id": 3, "name": "Bedroom"},
        {"id": 4, "name": "Kitchen"},
    ]
    result = _deduplicate_room_names(rooms)

    assert result[0] == {"id": 1, "name": "Kitchen"}
    assert result[1] == {"id": 2, "name": "Kitchen (2)"}
    assert result[2] == {"id": 3, "name": "Bedroom"}
    assert result[3] == {"id": 4, "name": "Kitchen (3)"}


def test_deduplicate_room_names_no_duplicates():
    """Test that unique room names are unchanged."""
    rooms = [
        {"id": 1, "name": "Kitchen"},
        {"id": 2, "name": "Bedroom"},
    ]
    result = _deduplicate_room_names(rooms)
    assert result == rooms


# ── Work Mode Mapping Test ───────────────────────────────────────────


def test_work_mode_names_mapping():
    """Test that work mode values are correctly mapped to names."""
    assert WORK_MODE_NAMES[0] == "Auto"
    assert WORK_MODE_NAMES[1] == "Room"
    assert WORK_MODE_NAMES[3] == "Spot"
    assert WORK_MODE_NAMES[8] == "Scene"


# ── G-series scalar/JSON protocol (e.g. T2210/G50) ───────────────────
# These devices send plain int/JSON DPS on different DPS numbers and emit no
# WorkStatus (153). Captured from a real G50 — see docs/g50_capture/FINDINGS.md.

_G50_DPS = {
    "15": 5,  # state -> docked/charging
    "5": 0,
    "104": 86,  # battery
    "102": 0,  # suction -> Quiet
    "118": 1,  # BoostIQ on
    "154": 2,  # pattern -> Random
    "111": 5,  # volume -> 50%
    "139": 0,  # child lock off
    "103": 0,  # find robot off
    "107": {"en": True, "start_t": "2100", "end_t": "0900"},  # DND
    "150": {  # accessory usage counters (minutes)
        "side_brush": 6209,
        "roller_brush": 6209,
        "dust_filter": 6209,
        "mop": 0,
        "roller_brush_cover": 6208,
        "sensors": 1355,
    },
    "109": 300,  # clean time = 300 s (5 min)
    "110": 4,  # clean area = 4 m² (≈43 ft²)
    "177": 0,  # error code (scalar, not protobuf)
}


def _parse_g50(dps):
    from custom_components.robovac_mqtt.api.parser import update_state

    # api_type is sticky in real use (set from the first full message); set it
    # here so partial-dps cases route to the scalar parser deterministically.
    state = VacuumState(device_model="T2210", api_type="scalar")
    new_state, _ = update_state(state, dps)
    return new_state


def test_g_series_state_and_battery():
    s = _parse_g50(_G50_DPS)
    assert s.activity == "docked"
    assert s.charging is True
    assert s.task_status == "Charging"
    assert s.battery_level == 86


def test_g_series_state_transitions():
    assert _parse_g50({"15": 2}).activity == "cleaning"
    assert _parse_g50({"15": 4}).activity == "returning"
    assert _parse_g50({"15": 7}).activity == "paused"
    assert _parse_g50({"15": 0}).activity == "idle"
    assert _parse_g50({"15": 5}).activity == "docked"  # charging
    assert _parse_g50({"15": 6}).activity == "docked"  # charge complete
    assert _parse_g50({"15": 5}).charging is True
    assert _parse_g50({"15": 6}).charging is False
    assert _parse_g50({"15": 2}).charging is False


def test_g_series_suction_scale():
    assert _parse_g50({"102": 0}).fan_speed == "Quiet"
    assert _parse_g50({"102": 1}).fan_speed == "Standard"
    assert _parse_g50({"102": 2}).fan_speed == "Turbo"
    assert _parse_g50({"102": 3}).fan_speed == "Max"


def test_g_series_toggles_and_pattern():
    s = _parse_g50(_G50_DPS)
    assert s.boost_iq is True
    assert s.cleaning_pattern == "Random"
    assert _parse_g50({"154": 1}).cleaning_pattern == "Arranged"
    assert s.volume == 50
    assert s.child_lock is False
    assert s.find_robot is False


def test_g_series_dnd_json():
    s = _parse_g50(_G50_DPS)
    assert s.dnd_enabled is True
    assert (s.dnd_start_hour, s.dnd_start_minute) == (21, 0)
    assert (s.dnd_end_hour, s.dnd_end_minute) == (9, 0)


def test_g_series_accessories_counters():
    s = _parse_g50(_G50_DPS)
    assert s.accessories.filter_usage == 6209
    assert s.accessories.main_brush_usage == 6209
    assert s.accessories.side_brush_usage == 6209
    assert s.accessories.sensor_usage == 1355


def test_scalar_clean_stats():
    """DPS 109 = cleaning time (seconds), DPS 110 = cleaning area (m²).
    Verified live: 300s/4m² -> app 5min/43ft²; 780s/3m² -> app 13min/32ft²."""
    s = _parse_g50({"109": 300, "110": 4})
    assert s.cleaning_time == 300
    assert s.cleaning_area == 4
    s = _parse_g50({"109": 780, "110": 3})
    assert s.cleaning_time == 780
    assert s.cleaning_area == 3


def test_scalar_cleaning_pref_and_activity_log():
    assert _parse_g50({"135": 1}).auto_return is True
    assert _parse_g50({"135": 0}).auto_return is False
    assert _parse_g50({"142": 1}).activity_log_upload is True
    assert _parse_g50({"142": 0}).activity_log_upload is False


def test_scalar_error_from_106_and_177():
    assert _parse_g50({"106": 5}).error_code == 5
    assert _parse_g50({"177": 7}).error_code == 7
    assert _parse_g50({"106": 0, "177": 0}).error_code == 0
    assert _parse_g50({"106": 0, "177": 0}).error_message == ""
    # non-zero fault wins regardless of which key carries it
    assert _parse_g50({"106": 0, "177": 9}).error_code == 9
    # 4-digit codes map via EUFY_CLEAN_ERROR_CODES (verified live: 7002 lift fault)
    s = _parse_g50({"106": 7002})
    assert s.error_code == 7002
    assert s.error_message == "MACHINE PICKED UP"


def test_scalar_schedule_decode():
    s = _parse_g50(
        {"151": {"l": [{"e": True, "t": "0930", "r": "246", "s": 0, "f": 1, "id": 1}]}}
    )
    assert len(s.schedules) == 1
    e = s.schedules[0]
    assert e["enabled"] is True
    assert e["time"] == "09:30"
    assert e["days"] == "Tue, Thu, Sat"
    assert e["suction"] == "Quiet"
    assert e["pattern"] == "Arranged"


def test_g_series_accepts_string_scalars():
    """Device sometimes sends scalars as strings; parser must coerce."""
    s = _parse_g50({"104": "73", "102": "2", "15": "2"})
    assert s.battery_level == 73
    assert s.fan_speed == "Turbo"
    assert s.activity == "cleaning"


def test_scalar_pause_flag_marks_paused():
    """DPS 122=1 while mid-clean -> paused; 122=0 -> back to cleaning."""
    from custom_components.robovac_mqtt.api.parser import update_state

    s = VacuumState(device_model="T2210", api_type="scalar")
    s, _ = update_state(s, {"15": 2})  # cleaning
    assert s.activity == "cleaning"
    s, _ = update_state(s, {"122": 1})  # stationary mid-clean -> paused
    assert s.activity == "paused"
    assert s.task_status == "Paused"
    s, _ = update_state(s, {"122": 0, "15": 2})  # moving again
    assert s.activity == "cleaning"
    # 122=1 while docked must NOT be read as paused
    d = VacuumState(device_model="T2210", api_type="scalar")
    d, _ = update_state(d, {"15": 5, "122": 1})
    assert d.activity == "docked"


def test_novel_state_ignores_scalar_dps():
    """A novel (protobuf) state must NOT interpret scalar DPS numbers as state."""
    from custom_components.robovac_mqtt.api.parser import update_state

    state = VacuumState(api_type="novel")
    new_state, _ = update_state(state, {"104": 86, "102": 0})
    # Novel path ignores Tuya scalar keys -> defaults preserved
    assert new_state.battery_level == 0
    assert new_state.activity == "idle"


# Protocol classification (checkApiType) is tested in tests/test_cloud.py.
