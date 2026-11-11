"""Exercise the documented retry automation through HA's actual script engine."""

# pylint: disable=redefined-outer-name

import asyncio
import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

AUTOMATION = yaml.safe_load((Path(__file__).parents[1] / "docs/examples/eufy-dock-retry.yaml").read_text())
HELPER = "input_text.eufy_dock_retry_history"
VACUUM = "vacuum.robovac"


def fault(hass, codes=("E75",), state="error"):
    hass.states.async_set(VACUUM, state, {"error_code": codes[0], "error_codes": list(codes)})


@pytest.fixture
async def retry(hass, tmp_path, request):
    hass.config.config_dir = str(tmp_path)
    calls = []

    async def resume(call):
        calls.append(call.data.get("command", call.service))
        hass.states.async_set(VACUUM, "returning", {"error_code": 0, "error_codes": []})

    hass.services.async_register("vacuum", "send_command", resume)
    hass.services.async_register("vacuum", "return_to_base", resume)
    assert await async_setup_component(hass, "input_text", {"input_text": {
        "eufy_dock_retry_history": {"name": "Eufy dock retry history", "max": 255},
    }})
    await hass.services.async_call("input_text", "set_value", {"entity_id": HELPER, "value": "[]"}, blocking=True)
    assert await async_setup_component(hass, "persistent_notification", {})
    config = {"id": "eufy_dock_retry", **copy.deepcopy(AUTOMATION)}
    if getattr(request, "param", False):
        # Accelerate only timer waits for the persistent-failure scenario.
        # Separate tests exercise the real three-minute cooldown and cancellation.
        def immediate_waits(node):
            if isinstance(node, dict):
                if "wait_template" in node:
                    node["timeout"] = 0
                if "wait_seconds" in node.get("variables", {}):
                    node["variables"]["wait_seconds"] = 0
                for child in node.values():
                    immediate_waits(child)
            elif isinstance(node, list):
                for child in node:
                    immediate_waits(child)
        immediate_waits(config)
    assert await async_setup_component(hass, "automation", {"automation": [config]})
    await hass.async_block_till_done()
    entities = hass.states.async_entity_ids("automation")
    assert len(entities) == 1
    yield calls, entities[0]
    await hass.services.async_call("automation", "turn_off", {"entity_id": entities[0], "stop_actions": True}, blocking=True)
    await hass.async_block_till_done()


async def trigger(hass, entity):
    await hass.services.async_call("automation", "trigger", {"entity_id": entity, "skip_condition": False}, blocking=True)
    await hass.async_block_till_done()


@pytest.mark.parametrize("codes,state,expected", [
    (("E75",), "error", ["resume"]),
    (("E74",), "error", ["resume"]),
    (("E76",), "error", ["return_to_base"]),
    (("E30",), "error", []),
    (("E75", "E30"), "error", []),
    (("E75",), "docked", []),
    (("E75",), "cleaning", []),
])
async def test_retry_targets_only_active_docking_faults(hass, retry, codes, state, expected):
    calls, entity = retry
    fault(hass, codes, state)
    await trigger(hass, entity)
    assert calls == expected
    history = json.loads(hass.states.get(HELPER).state)
    assert len(history) == len(expected)


@pytest.mark.parametrize("history", ["not-json", "null", "{}", '["123"]'])
async def test_invalid_history_fails_closed(hass, retry, history):
    calls, entity = retry
    await hass.services.async_call("input_text", "set_value", {"entity_id": HELPER, "value": history}, blocking=True)
    fault(hass)
    await trigger(hass, entity)
    assert calls == []
    assert hass.states.get(HELPER).state == history


async def test_eleventh_retry_is_rejected_without_resetting_the_persistent_budget(hass, retry):
    calls, entity = retry
    now = int(dt_util.utcnow().timestamp())
    previous = [now - 1790 + index * 180 for index in range(10)]
    await hass.services.async_call("input_text", "set_value", {"entity_id": HELPER, "value": json.dumps(previous)}, blocking=True)
    fault(hass)
    await trigger(hass, entity)
    assert calls == []
    assert json.loads(hass.states.get(HELPER).state) == previous


async def test_old_attempts_expire_from_the_rolling_window(hass, retry):
    calls, entity = retry
    now = int(dt_util.utcnow().timestamp())
    await hass.services.async_call("input_text", "set_value", {"entity_id": HELPER, "value": json.dumps([now - 1900])}, blocking=True)
    fault(hass)
    await trigger(hass, entity)
    assert calls == ["resume"]
    assert len(json.loads(hass.states.get(HELPER).state)) == 1


async def test_recovery_during_cooldown_cancels_the_waiting_retry(hass, retry):
    calls, entity = retry
    now = int(dt_util.utcnow().timestamp())
    await hass.services.async_call("input_text", "set_value", {"entity_id": HELPER, "value": json.dumps([now])}, blocking=True)
    fault(hass)
    task = asyncio.create_task(hass.services.async_call("automation", "trigger", {"entity_id": entity, "skip_condition": False}, blocking=True))
    await asyncio.sleep(0.05)
    assert not calls
    hass.states.async_set(VACUUM, "docked", {"error_code": "E75", "error_codes": ["E75"]})
    await asyncio.wait_for(task, 2)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=4))
    await hass.async_block_till_done()
    assert calls == []


@pytest.mark.parametrize("retry", [True], indirect=True)
async def test_persistent_failure_sends_exactly_ten_commands(hass, retry):
    calls, entity = retry

    async def still_faulted(call):
        calls.append(call.data["command"])

    hass.services.async_register("vacuum", "send_command", still_faulted)
    fault(hass)
    await trigger(hass, entity)
    assert calls == ["resume"] * 10
    assert len(json.loads(hass.states.get(HELPER).state)) == 10
    await trigger(hass, entity)
    assert calls == ["resume"] * 10
