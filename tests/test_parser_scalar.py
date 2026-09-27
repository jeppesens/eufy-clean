"""Unit tests for api/parser_scalar.py: DPS 151 schedule encoding."""

import pytest

from custom_components.robovac_mqtt.api.parser_scalar import (
    encode_scalar_repeat,
    scalar_pattern_to_int,
    scalar_raw_to_schedule_entry,
    scalar_suction_to_int,
    schedule_entry_to_scalar_raw,
)
from custom_components.robovac_mqtt.const import (
    SCALAR_CLEAN_PATTERN_NAMES,
    SCALAR_SUCTION_LEVELS,
)


def test_suction_index_is_the_position_in_the_suction_levels():
    """DPS 151 "s" uses the DPS 102 index, by name in any case or as a number."""
    for index, name in enumerate(SCALAR_SUCTION_LEVELS):
        assert scalar_suction_to_int(name) == index
        assert scalar_suction_to_int(name.upper()) == index
        assert scalar_suction_to_int(index) == index


@pytest.mark.parametrize("value", ["Boost_IQ", "loud", len(SCALAR_SUCTION_LEVELS), True, None])
def test_unknown_suction_has_no_index(value):
    """An unknown level is reported, not mapped to Standard."""
    assert scalar_suction_to_int(value) is None


def test_pattern_number_comes_from_the_pattern_names():
    """Names, their numbers and "general" (the default pattern) resolve."""
    for value, name in SCALAR_CLEAN_PATTERN_NAMES.items():
        assert scalar_pattern_to_int(name.lower()) == value
        assert scalar_pattern_to_int(str(value)) == value
    assert scalar_pattern_to_int("general") == min(SCALAR_CLEAN_PATTERN_NAMES)


@pytest.mark.parametrize("value", ["zigzag", "spot", 0, max(SCALAR_CLEAN_PATTERN_NAMES) + 1])
def test_unknown_pattern_has_no_number(value):
    assert scalar_pattern_to_int(value) is None


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        ("Mon, Wed, Sun", "137"),
        (["Weekends"], "67"),
        ("Every day", "1234567"),
        ("531", "135"),
        (None, ""),
    ],
)
def test_repeat_string_is_monday_first_digits(days, expected):
    assert encode_scalar_repeat(days) == expected


def test_repeat_string_rejects_an_unknown_day():
    with pytest.raises(ValueError):
        encode_scalar_repeat("Mon, Mondy")


def test_schedule_entry_round_trips_through_the_raw_form():
    """Re-encoding a parsed DPS 151 entry gives back the entry the robot sent."""
    raw = {"id": 4, "e": False, "t": "0930", "r": "246", "s": 3, "f": 2}
    assert schedule_entry_to_scalar_raw(scalar_raw_to_schedule_entry(raw)) == raw


@pytest.mark.parametrize("enabled", [True, False])
def test_enabled_flag_is_a_json_bool(enabled):
    """DPS 151 "e" is a JSON bool on the wire, never 1/0."""
    assert schedule_entry_to_scalar_raw({"id": 1, "enabled": enabled})["e"] is enabled
