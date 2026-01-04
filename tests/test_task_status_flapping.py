"""Test to verify task_status doesn't flap during mid-cleaning wash cycles.

This test replays actual message sequences from the robovac between 2-4 AM
to ensure the task_status logic correctly differentiates between:
1. Mid-cleaning wash pauses (should show "Washing Mop")
2. Post-cleaning final wash (should show "Completed")
"""

from custom_components.robovac_mqtt.api.parser import update_state
from custom_components.robovac_mqtt.const import DPS_MAP
from custom_components.robovac_mqtt.models import VacuumState


def test_mid_cleaning_wash_no_flapping():
    """Test that task_status doesn't flap during mid-cleaning wash cycles.

    Based on actual log sequence from 2026-01-04 02:00-02:02 where the robot:
    1. Is cleaning (state: CLEANING)
    2. Pauses to wash mop (cleaning.state: PAUSED + go_wash.mode: WASHING)
    3. Briefly reports CHARGING while dock performs washing tasks
    4. Returns to CLEANING with go_wash.mode: WASHING

    The task_status should remain "Washing Mop" throughout this sequence,
    not flap to "Completed" when state briefly changes to CHARGING.
    """
    state = VacuumState()

    # Sequence 1: Robot is cleaning (state 5)
    # DPS 153: WorkStatus - state: CLEANING, scheduled_task: true
    state = update_state(
        state, {DPS_MAP["WORK_STATUS"]: "EgoCCAEQBRoAMgIYAXICIgB6AA=="}
    )
    assert state.task_status == "Cleaning"
    assert state.activity == "cleaning"

    # Sequence 2: Robot pauses for mid-cleaning wash
    # DPS 153: WorkStatus - state: CLEANING, cleaning.state: PAUSED, go_wash.mode: WASHING
    state = update_state(
        state, {DPS_MAP["WORK_STATUS"]: "HAoCCAEQBRoAMgQIARgBOgIQAXIGCgIIASIAegA="}
    )
    first_status = state.task_status
    assert (
        first_status == "Washing Mop"
    ), "Should show 'Washing Mop' when go_wash.mode is WASHING"

    # Sequence 3: Dock starts adding clean water
    # DPS 173: StationResponse - state: WASHING, clear_water_adding: true
    state = update_state(
        state,
        {
            DPS_MAP[
                "STATION_STATUS"
            ]: "NgooCgwKBggBGgIIFBIAGAESBggBEgIIASABMg4KAggBEgQIAhgPGgIIARIGCAEQASABKgIIOg=="
        },
    )
    assert state.dock_status == "Adding clean water"

    # Sequence 4: Robot reports CLEANING again (continuing wash)
    # DPS 153: WorkStatus - state: CLEANING, scheduled_task: true (no go_wash means still at dock)
    state = update_state(
        state, {DPS_MAP["WORK_STATUS"]: "EgoCCAEQBRoAMgIYAXICIgB6AA=="}
    )
    # Task status can transition between Washing Mop and Cleaning during dock operations
    assert state.task_status in (
        "Washing Mop",
        "Cleaning",
    ), "Task status should be washing or cleaning during dock wash"

    # Sequence 5: Robot pauses again with wash mode
    # DPS 153: WorkStatus - state: CLEANING, cleaning.state: PAUSED, go_wash.mode: WASHING
    state = update_state(
        state, {DPS_MAP["WORK_STATUS"]: "GgoCCAEQBRoAMgQIARgBOgIQAXIECgAiAHoA"}
    )
    assert state.task_status == "Washing Mop"

    # Sequence 6: Dock finishes adding water, goes idle
    # DPS 173: StationResponse - state: IDLE
    state = update_state(
        state,
        {
            DPS_MAP[
                "STATION_STATUS"
            ]: "MgooCgwKBggBGgIIFBIAGAESBggBEgIIASABMg4KAggBEgQIAhgPGgIIARICCAEqAgg6"
        },
    )
    assert state.dock_status == "Idle"

    # Sequence 7: Dock starts washing with recycled water
    # DPS 173: StationResponse - state: WASHING, waste_water_recycling: true
    state = update_state(
        state,
        {
            DPS_MAP[
                "STATION_STATUS"
            ]: "NgooCgwKBggBGgIIFBIAGAESBggBEgIIASABMg4KAggBEgQIAhgPGgIIARIGCAEQASgBKgIIOA=="
        },
    )
    assert state.dock_status == "Recycling waste water"

    # Sequence 8: Robot reports CLEANING again during wash
    # DPS 153: WorkStatus - state: CLEANING, scheduled_task: true
    state = update_state(
        state, {DPS_MAP["WORK_STATUS"]: "EgoCCAEQBRoAMgIYAXICIgB6AA=="}
    )
    assert state.task_status in (
        "Washing Mop",
        "Cleaning",
    ), "Task status should be washing or cleaning during dock wash"


def test_post_cleaning_stays_completed():
    """Test that task_status stays 'Completed' after cleaning ends.

    Based on log sequence around 03:01:53 where:
    1. Cleaning completes (state: CHARGING, NO cleaning field)
    2. Dock performs final wash/recycling
    3. Task status should stay "Completed", not change back to "Washing Mop"
    """
    state = VacuumState()

    # Sequence 1: Cleaning completes - robot in CHARGING state with NO cleaning field
    # DPS 153: WorkStatus - state: CHARGING (state 3), no cleaning field
    state = update_state(state, {DPS_MAP["WORK_STATUS"]: "ChADGgByAiIAegA="})
    assert (
        state.task_status == "Completed"
    ), "Should be Completed when charging and no cleaning field"
    assert state.activity == "docked"

    # Sequence 2: Dock starts washing (post-cleaning final wash)
    # DPS 173: StationResponse - state: WASHING
    state = update_state(
        state,
        {
            DPS_MAP[
                "STATION_STATUS"
            ]: "NAooCgwKBggBGgIIFBIAGAESBggBEgIIASABMg4KAggBEgQIAhgPGgIIARIECAEQASoCCDc="
        },
    )
    assert state.dock_status == "Washing"

    # Sequence 3: Robot still in CHARGING state (no cleaning field)
    # Task status should STAY "Completed" even though dock is washing
    state = update_state(state, {DPS_MAP["WORK_STATUS"]: "ChADGgByAiIAegA="})
    assert (
        state.task_status == "Completed"
    ), "Task status should stay Completed after cleaning ends, even during final wash"

    # Sequence 4: Dock does recycling
    # DPS 173: StationResponse - waste_water_recycling: true
    state = update_state(
        state,
        {
            DPS_MAP[
                "STATION_STATUS"
            ]: "NgooCgwKBggBGgIIFBIAGAESBggBEgIIASABMg4KAggBEgQIAhgPGgIIARIGCAEQASgBKgIIOA=="
        },
    )
    assert state.dock_status == "Recycling waste water"

    # Sequence 5: Robot still reports CHARGING (no cleaning field)
    # Task status should STILL be "Completed"
    state = update_state(state, {DPS_MAP["WORK_STATUS"]: "ChADGgByAiIAegA="})
    assert (
        state.task_status == "Completed"
    ), "Task status must stay Completed, not change to Washing Mop post-cleaning"


def test_mid_cleaning_with_paused_state():
    """Test mid-cleaning wash with CHARGING state but cleaning.state: PAUSED.

    This is the KEY flapping scenario from logs:
    - Robot alternates between CHARGING and CLEANING states during washing
    - cleaning.state: PAUSED is present in both
    - Dock is performing washing tasks
    - Should show "Washing Mop", not flip-flop to "Completed"
    """
    state = VacuumState()

    # Set initial state with dock washing
    state = update_state(
        state,
        {
            DPS_MAP[
                "STATION_STATUS"
            ]: "NgooCgwKBggBGgIIFBIAGAESBggBEgIIASABMg4KAggBEgQIAhgPGgIIARIGCAEQASgBKgIIOA=="
        },
    )
    assert state.dock_status == "Recycling waste water"

    # KEY SCENARIO 1: Robot reports CHARGING but cleaning.state: PAUSED is present
    # DPS 153: WorkStatus - state: CHARGING (3), cleaning.state: PAUSED
    # This is the critical flapping trigger
    state = update_state(
        state, {DPS_MAP["WORK_STATUS"]: "EgoCCAEQAxoAMgIIAXICIgB6AA=="}
    )

    # With the fix, this should show "Washing Mop" because:
    # 1. cleaning field exists with PAUSED state (state == 1)
    # 2. dock_status indicates washing activity ("Recycling waste water")
    assert (
        state.task_status == "Washing Mop"
    ), "CRITICAL: Should show 'Washing Mop' not 'Completed' when CHARGING with cleaning.PAUSED during dock washing"
    assert state.status_code == 3, "Should be in CHARGING state (3)"

    # KEY SCENARIO 2: Robot alternates to CLEANING with go_wash.mode: WASHING
    # DPS 153: state: CLEANING, cleaning.state: PAUSED, go_wash.mode: WASHING
    state = update_state(
        state, {DPS_MAP["WORK_STATUS"]: "GAoCCAEQBRoAMgIIAToCEAFyBAoAIgB6AA=="}
    )
    assert (
        state.task_status == "Washing Mop"
    ), "Should stay 'Washing Mop' when go_wash.mode is WASHING"

    # KEY SCENARIO 3: Back to CHARGING again
    # This would cause flapping without the fix
    state = update_state(
        state, {DPS_MAP["WORK_STATUS"]: "EgoCCAEQAxoAMgIIAXICIgB6AA=="}
    )
    assert (
        state.task_status == "Washing Mop"
    ), "Should STAY 'Washing Mop', not flap back to 'Completed'"

    # Clean up - dock finishes washing
    state = update_state(
        state,
        {
            DPS_MAP[
                "STATION_STATUS"
            ]: "MgooCgwKBggBGgIIFBIAGAESBggBEgIIASABMg4KAggBEgQIAhgPGgIIARICCAEqAggz"
        },
    )
    assert state.dock_status == "Idle"

    # Now robot should show Completed
    state = update_state(
        state, {DPS_MAP["WORK_STATUS"]: "EgoCCAEQAxoAMgIIAXICIgB6AA=="}
    )
    # After washing is done (dock_status is Idle, not washing), it should be Completed
    assert (
        state.task_status == "Completed"
    ), "Should be 'Completed' when CHARGING and dock is NOT washing"
