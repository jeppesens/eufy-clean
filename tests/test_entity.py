"""Unit tests for entity.py: protocol capability gating."""

from unittest.mock import MagicMock

import pytest

from custom_components.robovac_mqtt.entity import (
    effective_api_type,
    filter_supported_entities,
    has_firmware_api,
)


@pytest.mark.parametrize(
    ("api_type", "expected"),
    [
        ("scalar", "scalar"),
        ("novel", "novel"),
        ("legacy", "novel"),
        ("unknown", "novel"),
        ("", "novel"),
    ],
)
def test_effective_api_type(api_type, expected):
    """Any non-scalar api type speaks the novel protocol."""
    assert effective_api_type(api_type) == expected


def _entity(supported):
    entity = MagicMock()
    entity.supported_api_types = supported
    return entity


@pytest.mark.parametrize(
    ("api_type", "expected_supported"),
    [
        ("novel", [None, ("novel",)]),
        ("scalar", [None, ("scalar",)]),
        ("legacy", [None, ("novel",)]),  # legacy/unknown parse+command as novel
    ],
)
def test_filter_supported_entities(api_type, expected_supported):
    """Only universal + matching-protocol entities survive the filter."""
    coordinator = MagicMock()
    coordinator.api_type = api_type
    entities = [_entity(None), _entity(("novel",)), _entity(("scalar",))]

    result = filter_supported_entities(coordinator, entities)

    assert [e.supported_api_types for e in result] == expected_supported


def test_filter_supported_entities_missing_attribute_is_universal():
    """Entities that never declare supported_api_types are kept everywhere."""
    coordinator = MagicMock()
    coordinator.api_type = "scalar"
    entity = object()  # no supported_api_types attribute at all

    assert filter_supported_entities(coordinator, [entity]) == [entity]


@pytest.mark.parametrize(
    ("thing_client", "tuya_ids", "expected"),
    [
        (object(), {"dev1"}, True),
        # An MQTT robot on an account whose Tuya login works: its id is no devId.
        (object(), {"other"}, False),
        (object(), set(), False),
        (None, {"dev1"}, False),
    ],
)
def test_firmware_api_needs_the_device_known_to_tuya(thing_client, tuya_ids, expected):
    """Firmware calls address the Tuya devId, so the device must be on the
    account's Tuya device list as well as the Thing client existing."""
    coordinator = MagicMock()
    coordinator.device_id = "dev1"
    coordinator.eufy_login.tuya_thing_client = thing_client
    coordinator.eufy_login.tuya_device_ids = tuya_ids

    assert has_firmware_api(coordinator) is expected
