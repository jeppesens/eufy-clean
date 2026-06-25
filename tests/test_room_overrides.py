"""Tests for the per-device room name override feature.

Covers:
- _parse_rooms_text / _format_rooms_text round-trip and tolerance
- RoomSelectEntity prefers overrides when set; falls back to coordinator
  data when not
- async_select_option translates name -> id correctly via the override
"""

# pylint: disable=redefined-outer-name

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.robovac_mqtt.config_flow import (
    _format_rooms_text,
    _parse_rooms_text,
)
from custom_components.robovac_mqtt.select import RoomSelectEntity


# ── _parse_rooms_text ────────────────────────────────────────────────


def test_parse_rooms_basic():
    text = "1: Lounge\n5: Kitchen\n8: Playroom"
    assert _parse_rooms_text(text) == {1: "Lounge", 5: "Kitchen", 8: "Playroom"}


def test_parse_rooms_tolerates_whitespace_blanks_comments():
    text = "  \n# comment\n  1 :   Lounge with space  \n\n5:Kitchen\n"
    assert _parse_rooms_text(text) == {1: "Lounge with space", 5: "Kitchen"}


def test_parse_rooms_skips_unparseable_lines():
    text = "1: Lounge\nnot a line\n3: \n: missing id\nfour: bad"
    assert _parse_rooms_text(text) == {1: "Lounge"}


def test_parse_rooms_duplicate_id_last_wins():
    text = "1: First\n1: Second\n1: Final"
    assert _parse_rooms_text(text) == {1: "Final"}


def test_format_rooms_round_trips():
    rooms = {5: "Kitchen", 1: "Lounge", 8: "Playroom"}
    text = _format_rooms_text(rooms)
    # Sorted by id so the textarea is stable across saves
    assert text == "1: Lounge\n5: Kitchen\n8: Playroom"
    assert _parse_rooms_text(text) == rooms


def test_format_rooms_empty_returns_empty_string():
    assert _format_rooms_text({}) == ""


def test_format_rooms_sorts_numerically_not_lexically():
    """Override storage should preserve int ordering so room 10 comes after 9."""
    rooms = {10: "Garage", 2: "Hall", 1: "Lounge"}
    assert _format_rooms_text(rooms) == "1: Lounge\n2: Hall\n10: Garage"


# ── RoomSelectEntity ─────────────────────────────────────────────────


def _coord(room_overrides=None, p2p_rooms=None):
    c = MagicMock()
    c.device_id = "dev_1"
    c.device_name = "Test Vac"
    c.room_name_overrides = room_overrides or {}
    c.data = MagicMock()
    c.data.rooms = p2p_rooms or []
    c.data.map_id = 3
    c.build_device_command = MagicMock(return_value={"152": "encoded"})
    c.async_send_command = AsyncMock()
    c.device_info = MagicMock()
    return c


def test_options_uses_overrides_when_set():
    c = _coord(room_overrides={5: "Kitchen", 1: "Lounge"})
    ent = RoomSelectEntity(c)
    # "None" placeholder first, then rooms sorted by id with disambiguating labels.
    assert ent.options == ["None", "Lounge (ID: 1)", "Kitchen (ID: 5)"]


def test_options_falls_back_to_p2p_when_no_overrides():
    c = _coord(p2p_rooms=[{"id": 1, "name": "DeviceLounge"}, {"id": 2, "name": "DeviceKitchen"}])
    ent = RoomSelectEntity(c)
    assert ent.options == ["None", "DeviceLounge (ID: 1)", "DeviceKitchen (ID: 2)"]


def test_overrides_take_priority_over_p2p():
    c = _coord(
        room_overrides={5: "MyKitchen"},
        p2p_rooms=[{"id": 1, "name": "DeviceLounge"}, {"id": 2, "name": "DeviceKitchen"}],
    )
    ent = RoomSelectEntity(c)
    assert ent.options == ["None", "MyKitchen (ID: 5)"]


def test_options_empty_when_neither_source():
    c = _coord()
    ent = RoomSelectEntity(c)
    # Only the placeholder when there are no rooms from either source.
    assert ent.options == ["None"]


@pytest.mark.asyncio
async def test_select_option_sends_room_clean_with_override_id():
    c = _coord(room_overrides={5: "Kitchen", 1: "Lounge"})
    ent = RoomSelectEntity(c)
    ent.async_write_ha_state = MagicMock()
    await ent.async_select_option("Kitchen (ID: 5)")
    c.build_device_command.assert_called_once_with(
        "room_clean", room_ids=[5], map_id=3
    )
    c.async_send_command.assert_awaited_once()


@pytest.mark.asyncio
async def test_select_option_unknown_room_logs_and_returns():
    c = _coord(room_overrides={5: "Kitchen"})
    ent = RoomSelectEntity(c)
    ent.async_write_ha_state = MagicMock()
    await ent.async_select_option("Nonexistent")
    c.build_device_command.assert_not_called()
    c.async_send_command.assert_not_awaited()


def test_options_disambiguates_duplicate_room_names():
    """Two rooms sharing a name still get distinct labels (via the ID suffix)."""
    c = _coord(room_overrides={1: "Bedroom", 2: "Bedroom"})
    ent = RoomSelectEntity(c)
    # Labels are unique because each carries its room id.
    assert ent.options == ["None", "Bedroom (ID: 1)", "Bedroom (ID: 2)"]
    assert len(set(ent.options)) == len(ent.options)


@pytest.mark.asyncio
async def test_select_duplicate_name_resolves_correct_id():
    """Selecting the second of two same-named rooms cleans the right room id."""
    c = _coord(room_overrides={1: "Bedroom", 2: "Bedroom"})
    ent = RoomSelectEntity(c)
    ent.async_write_ha_state = MagicMock()
    await ent.async_select_option("Bedroom (ID: 2)")
    c.build_device_command.assert_called_once_with(
        "room_clean", room_ids=[2], map_id=3
    )
