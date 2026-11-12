"""Unit tests for api/legacy_commands.py: legacy command building."""

import base64
import dataclasses
import json
import logging

import pytest

from custom_components.robovac_mqtt import profiles
from custom_components.robovac_mqtt.api.legacy_commands import (
    build_legacy_command,
    build_legacy_schedule_dps,
)
from custom_components.robovac_mqtt.profiles import LEGACY_DUSTBAG_50H, DeviceProfile
from custom_components.robovac_mqtt.proto.cloud.consumable_pb2 import ConsumableRequest

# ── Basic commands ──────────────────────────────────────────────────


def test_start_auto():
    result = build_legacy_command("start_auto")
    assert result == {"2": True, "5": "auto"}


def test_play():
    result = build_legacy_command("play")
    assert result == {"2": True}


def test_resume():
    result = build_legacy_command("resume")
    assert result == {"2": True}


def test_pause():
    result = build_legacy_command("pause")
    assert result == {"2": False}


def test_stop():
    result = build_legacy_command("stop")
    assert result == {"2": False}


def test_return_to_base():
    result = build_legacy_command("return_to_base")
    assert result == {"101": True}


def test_go_home():
    result = build_legacy_command("go_home")
    assert result == {"101": True}


# ── Find robot ──────────────────────────────────────────────────────


def test_find_robot_active():
    result = build_legacy_command("find_robot", active=True)
    assert result == {"103": True}


def test_find_robot_inactive():
    result = build_legacy_command("find_robot", active=False)
    assert result == {"103": False}


def test_find_robot_default_active():
    result = build_legacy_command("find_robot")
    assert result == {"103": True}


# ── Fan speed ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "speed",
    ["No_suction", "Standard", "Quiet", "Turbo", "Boost_IQ", "Max"],
)
def test_set_fan_speed_valid(speed):
    result = build_legacy_command("set_fan_speed", fan_speed=speed)
    assert result == {"102": speed}


def test_set_fan_speed_invalid():
    result = build_legacy_command("set_fan_speed", fan_speed="SuperMax")
    assert result == {}


def test_set_fan_speed_missing():
    result = build_legacy_command("set_fan_speed")
    assert result == {}


# ── Cleaning modes ──────────────────────────────────────────────────


def test_clean_spot():
    result = build_legacy_command("clean_spot")
    assert result == {"2": True, "5": "Spot"}


def test_room_clean():
    result = build_legacy_command("room_clean")
    assert result == {"2": True, "5": "room"}


def test_edge_clean():
    result = build_legacy_command("edge_clean")
    assert result == {"2": True, "5": "Edge"}


# ── Room clean with room_ids warning ──────────────────────────────


def test_room_clean_with_room_ids_builds_select_rooms_clean():
    """room_clean with room_ids builds a DPS-124 selectRoomsClean document.

    Legacy per-room clean IS supported: it is a base64 JSON map operation on
    DPS 124, verified against hardware. The
    top-level epoch-ms ``timestamp`` is mandatory — without it the firmware
    discards the write silently.
    """
    result = build_legacy_command("room_clean", room_ids=[1, 2, 3])

    assert set(result) == {"124"}
    doc = json.loads(base64.b64decode(result["124"]))
    assert doc["method"] == "selectRoomsClean"
    assert doc["data"] == {"roomIds": [1, 2, 3], "cleanTimes": 1}
    assert isinstance(doc["timestamp"], int) and doc["timestamp"] > 1_600_000_000_000


def test_room_clean_without_room_ids_no_warning(caplog):
    """room_clean without room_ids should not warn."""
    with caplog.at_level(logging.WARNING):
        result = build_legacy_command("room_clean")

    assert result == {"2": True, "5": "room"}
    assert "room_ids" not in caplog.text


# ── Unsupported commands ────────────────────────────────────────────


@pytest.mark.parametrize(
    "command",
    [
        "scene_clean",
        "set_room_custom",
        "set_auto_cfg",
        "go_dry",
        "go_selfcleaning",
        "collect_dust",
        "set_cleaning_mode",
        "set_water_level",
        "set_cleaning_intensity",
        "reset_accessory",
        "nonexistent_command",
    ],
)
def test_unsupported_commands_return_empty(command):
    """Unsupported commands should return empty dict."""
    result = build_legacy_command(command)
    assert result == {}


# ── Consumable reset (DPS 116) ─────────────────────────────────────


def _reset_doc(result: dict) -> dict:
    (dps, encoded), = result.items()
    assert dps == "116"
    return json.loads(base64.b64decode(encoded))


def test_reset_type_resolves_through_the_profile_specs(monkeypatch):
    """A bare reset_type maps to the legacy_key of the spec carrying that proto_type."""
    spec = dataclasses.replace(
        LEGACY_DUSTBAG_50H, proto_type=ConsumableRequest.MOP, legacy_key="MP"
    )
    monkeypatch.setitem(
        profiles.MODEL_PROFILES,
        "T9999",
        DeviceProfile(model="T9999", api_type="legacy", accessories={"mop_usage": spec}),
    )
    result = build_legacy_command("reset_accessory", reset_type=ConsumableRequest.MOP)
    assert _reset_doc(result) == {"consumable": {"reset": ["MP"]}}


def test_reset_accessory_prefers_the_explicit_legacy_key():
    result = build_legacy_command(
        "reset_accessory", legacy_key="SB", reset_type=ConsumableRequest.FILTER_MESH
    )
    assert _reset_doc(result) == {"consumable": {"reset": ["SB"]}}


# ── DPS key correctness ────────────────────────────────────────────


def test_dps_keys_are_strings():
    """All DPS keys in output should be string type."""
    result = build_legacy_command("start_auto")
    for key in result:
        assert isinstance(key, str), f"DPS key {key!r} should be a string"


# ---------------------------------------------------------------------------
# set_nogo_zones — restricted geometry editing (DPS 124 setNogoZones)
# ---------------------------------------------------------------------------


def _nogo_doc(result):
    return json.loads(base64.b64decode(result["124"]))


def test_set_nogo_zones_matches_the_app_payload_shape():
    """Vertices are FLATTENED into numbered keys, per the app's ecl_add_forbidden."""
    result = build_legacy_command(
        "set_nogo_zones",
        forbidden_zones=[[(0, 0), (10, 0), (10, 10), (0, 10)]],
        virtual_walls=[[(1, 1), (2, 2)]],
        ban_mop_zones=[],
    )
    doc = _nogo_doc(result)
    assert doc["method"] == "setNogoZones"
    assert doc["data"]["forbiddenZones"] == [
        {"x0": 0, "y0": 0, "x1": 10, "y1": 0, "x2": 10, "y2": 10, "x3": 0, "y3": 10}
    ]
    # A wall is TWO points, not four — the vertex count varies by shape.
    assert doc["data"]["virtualWallZones"] == [{"x0": 1, "y0": 1, "x1": 2, "y1": 2}]
    assert doc["data"]["banMopZones"] == []
    assert isinstance(doc["timestamp"], int)


def test_set_nogo_zones_sends_all_three_lists_always():
    """The document is REPLACE-ALL, so every category must be present every time.

    Omitting a key would erase that geometry on the device, silently.
    """
    doc = _nogo_doc(build_legacy_command("set_nogo_zones"))
    assert set(doc["data"]) == {"forbiddenZones", "virtualWallZones", "banMopZones"}
    assert doc["data"] == {
        "forbiddenZones": [],
        "virtualWallZones": [],
        "banMopZones": [],
    }


def test_set_nogo_zones_empty_is_not_a_no_op():
    """Unlike the other builders, all-empty is a legitimate 'clear everything'."""
    assert build_legacy_command("set_nogo_zones") != {}


def test_set_nogo_zones_skips_malformed_shapes(caplog):
    """A zone with the wrong vertex count is dropped with a warning, not sent."""
    with caplog.at_level(logging.WARNING):
        doc = _nogo_doc(
            build_legacy_command(
                "set_nogo_zones",
                forbidden_zones=[[(0, 0), (1, 1)]],  # only 2 points
                virtual_walls=[[(0, 0), (1, 1), (2, 2)]],  # 3, wants 2
            )
        )
    assert doc["data"]["forbiddenZones"] == []
    assert doc["data"]["virtualWallZones"] == []
    assert "set_nogo_zones" in caplog.text


# ---------------------------------------------------------------------------
# set_room_custom — REPLACE-ALL, so the caller has to vouch for the list
# ---------------------------------------------------------------------------


def _custom_rooms_doc(result):
    return json.loads(base64.b64decode(result["124"]))


def _complete_rooms():
    return [
        {"room_id": 0, "fan_speed": "Max", "water_level": "High", "clean_times": 2},
        {"room_id": 1, "fan_speed": "Quiet"},
    ]


def test_set_room_custom_builds_the_document_when_declared_complete():
    result = build_legacy_command(
        "set_room_custom", map_id=3, room_config=_complete_rooms(), complete=True
    )
    doc = _custom_rooms_doc(result)
    assert doc["method"] == "customRooms"
    assert doc["data"]["mapId"] == 3
    assert doc["data"]["active"] is True
    # Room id 0 is a real room; it must survive into the document.
    assert [p["roomId"] for p in doc["data"]["property"]] == [0, 1]


def test_set_room_custom_refuses_a_list_not_declared_complete(caplog):
    """No `complete` -> refuse, because a partial document is destructive.

    customRooms replaces the whole table: it applies cleanly and wipes the
    override of every room it left out. Nothing in the list itself can say
    whether it is the full set, so the builder will not guess.
    """
    with caplog.at_level(logging.WARNING):
        result = build_legacy_command(
            "set_room_custom", map_id=3, room_config=_complete_rooms()
        )
    assert result == {}
    assert "replace-all" in caplog.text


def test_set_room_custom_refuses_bare_room_ids(caplog):
    """A bare id list IS, by construction, "just the rooms the caller named"."""
    with caplog.at_level(logging.WARNING):
        result = build_legacy_command(
            "set_room_custom",
            map_id=3,
            room_config=[1, 2],
            fan_speed="Max",
            complete=True,
        )
    assert result == {}
    assert "bare ids" in caplog.text


def test_set_room_custom_needs_a_map_id(caplog):
    with caplog.at_level(logging.WARNING):
        result = build_legacy_command(
            "set_room_custom", room_config=_complete_rooms(), complete=True
        )
    assert result == {}
    assert "needs a map_id" in caplog.text


def test_set_room_custom_one_bad_entry_voids_the_whole_document(caplog):
    """A partially-built replace-all document is worse than none at all."""
    with caplog.at_level(logging.WARNING):
        result = build_legacy_command(
            "set_room_custom",
            map_id=3,
            room_config=[{"room_id": 0}, {"fan_speed": "Max"}],  # second has no id
            complete=True,
        )
    assert result == {}


def test_legacy_clean_times_clamped_to_the_service_range():
    for asked, sent in ((9, 3), (-2, 1), (None, 1)):
        result = build_legacy_command("room_clean", room_ids=[1], clean_times=asked)
        doc = json.loads(base64.b64decode(result["124"]))
        assert doc["data"]["cleanTimes"] == sent


# ---------------------------------------------------------------------------
# Schedule timers: the DPS 124 document a Tuya timer replays
# ---------------------------------------------------------------------------


def test_schedule_document_has_the_app_shape():
    """All six data fields, rooms as property[].roomId, levels in app spelling."""
    doc = json.loads(
        base64.b64decode(
            build_legacy_schedule_dps(
                map_id=3, suction="max", water="mid", mode="Customize",
                rooms=[0, 2], clean_times=2,
            )["124"]
        )
    )
    assert doc["method"] == "scheduleRoomsClean"
    assert doc["data"] == {
        "mapId": 3,
        "cleanMode": "customize",
        "cleanLevel": "Max",
        "waterMode": "medium",
        "property": [{"roomId": 0}, {"roomId": 2}],
        "cleanTimes": 2,
    }
    assert isinstance(doc["timestamp"], int) and doc["timestamp"] > 1_600_000_000_000


def test_whole_house_schedule_document_defaults():
    doc = json.loads(base64.b64decode(build_legacy_schedule_dps(map_id=1)["124"]))
    assert doc["method"] == "scheduleAutoClean"
    assert doc["data"] == {
        "mapId": 1,
        "cleanMode": "general",
        "cleanLevel": "Standard",
        "waterMode": "medium",
        "property": [],
        "cleanTimes": 1,
    }


@pytest.mark.parametrize(
    "kwargs", [{"suction": "loud"}, {"water": "Medium"}, {"mode": "spot"}]
)
def test_schedule_document_rejects_unknown_values(kwargs):
    with pytest.raises(ValueError):
        build_legacy_schedule_dps(map_id=1, **kwargs)
