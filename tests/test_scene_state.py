from unittest.mock import MagicMock

from custom_components.robovac_mqtt.api.parser import update_state
from custom_components.robovac_mqtt.const import DPS_MAP
from custom_components.robovac_mqtt.models import VacuumState
from custom_components.robovac_mqtt.proto.cloud.work_status_pb2 import WorkStatus
from custom_components.robovac_mqtt.select import SceneSelectEntity
from custom_components.robovac_mqtt.utils import encode_message


def test_scene_select_entity_mocked():
    """Test SceneSelectEntity with mocked coordinator."""

    # 1. Setup Mock Coordinator
    mock_coordinator = MagicMock()
    mock_coordinator.device_id = "test_id"
    mock_coordinator.device_info = {}
    mock_coordinator.data = VacuumState()

    # Pre-populate available scenes
    mock_coordinator.data.scenes = [
        {"id": 1, "name": "Living Room"},
        {"id": 8, "name": "Hallway test"},
    ]

    entity = SceneSelectEntity(mock_coordinator)
    entity.hass = MagicMock()

    # 2. Test Initial State (None)
    assert entity.current_option is None

    # 3. Simulate Scene Active (ID Match)
    mock_coordinator.data.current_scene_id = 8
    mock_coordinator.data.current_scene_name = "Hallway test"

    assert entity.current_option == "Hallway test (ID: 8)"

    # 4. Simulate Scene Active (No Name in List, use reported name)
    mock_coordinator.data.current_scene_id = 99
    mock_coordinator.data.current_scene_name = "New Scene"

    # Should use the reported name as fallback with ID
    assert entity.current_option == "New Scene (ID: 99)"

    # 5. Simulate Scene Inactive (ID=0)
    mock_coordinator.data.current_scene_id = 0
    mock_coordinator.data.current_scene_name = None

    assert entity.current_option is None


def test_scene_parsing_logic():
    """Test extracting scene info from WorkStatus proto."""
    ws = WorkStatus()
    ws.current_scene.id = 8
    ws.current_scene.name = "Hallway test"

    encoded = encode_message(ws)
    mock_dps = {DPS_MAP["WORK_STATUS"]: encoded}

    state_obj = VacuumState()
    _, changes = update_state(state_obj, mock_dps)

    assert changes.get("current_scene_id") == 8
    assert changes.get("current_scene_name") == "Hallway test"


def test_scene_parsing_partial_update():
    """Test response when WorkStatus partial update (omitted fields) arrives."""
    ws = WorkStatus()
    # No mode, no state (default 0), no current_scene
    # This simulates a partial update like 'station' only

    encoded = encode_message(ws)
    mock_dps = {DPS_MAP["WORK_STATUS"]: encoded}

    state_obj = VacuumState()
    # Pre-set state to simulate active scene
    state_obj.current_scene_id = 9
    state_obj.current_scene_name = "Old"

    _, changes = update_state(state_obj, mock_dps)

    # Should NOT be in changes dict (preserving old state)
    assert "current_scene_id" not in changes
    assert "current_scene_name" not in changes


def test_scene_parsing_explicit_clear_mode():
    """Test clearing scene when Mode changes to Auto."""
    ws = WorkStatus()
    ws.mode.value = 0  # AUTO

    encoded = encode_message(ws)
    mock_dps = {DPS_MAP["WORK_STATUS"]: encoded}

    state_obj = VacuumState()
    state_obj.current_scene_id = 9

    _, changes = update_state(state_obj, mock_dps)

    assert changes.get("current_scene_id") == 0
    assert changes.get("current_scene_name") is None


def test_scene_parsing_explicit_clear_state():
    """Test clearing scene when State changes to Charging."""
    ws = WorkStatus()
    ws.state = 3  # CHARGING

    encoded = encode_message(ws)
    mock_dps = {DPS_MAP["WORK_STATUS"]: encoded}

    state_obj = VacuumState()
    state_obj.current_scene_id = 9

    _, changes = update_state(state_obj, mock_dps)

    assert changes.get("current_scene_id") == 0
    assert changes.get("current_scene_name") is None
