"""Tests for the entity-registry orphan pruning helper."""

# pylint: disable=redefined-outer-name

from unittest.mock import MagicMock

import pytest

from custom_components.robovac_mqtt._orphan_cleanup import prune_orphan_entities
from custom_components.robovac_mqtt.const import DOMAIN


def _registry_entry(entity_id, unique_id, platform=DOMAIN, domain="sensor"):
    e = MagicMock()
    e.entity_id = entity_id
    e.unique_id = unique_id
    e.platform = platform
    e.domain = domain
    return e


@pytest.fixture
def registry_with_entries(monkeypatch):
    """Build a fake entity registry with mixed entries we can inspect."""
    entries = {
        # Two of OUR entities — one current, one orphan
        "1": _registry_entry("sensor.robovac_battery", "dev1_battery"),
        "2": _registry_entry("sensor.robovac_active_map", "dev1_active_map"),
        # An entry that belongs to a different integration — must NOT be touched
        "3": _registry_entry(
            "sensor.someoneelse_thing", "thing_id_1", platform="other_integration"
        ),
        # An entry for a different device our coordinator doesn't manage
        "4": _registry_entry("sensor.robovac_old_device", "dev_unknown_battery"),
    }

    fake_registry = MagicMock()
    fake_registry.entities = entries
    removed: list[str] = []

    def remove(entity_id):
        # Same semantics as the real registry — drop the entry by id
        for k, v in list(entries.items()):
            if v.entity_id == entity_id:
                removed.append(entity_id)
                entries.pop(k)
                return
        raise KeyError(entity_id)

    fake_registry.async_remove = remove
    fake_registry._removed = removed  # for assertions

    def fake_async_get(_hass):
        return fake_registry

    def fake_async_entries_for_config_entry(_registry, _entry_id):
        return list(entries.values())

    monkeypatch.setattr(
        "custom_components.robovac_mqtt._orphan_cleanup.er.async_get",
        fake_async_get,
    )
    monkeypatch.setattr(
        "custom_components.robovac_mqtt._orphan_cleanup.er.async_entries_for_config_entry",
        fake_async_entries_for_config_entry,
    )
    return fake_registry


def test_orphan_pruned_when_not_in_added_unique_ids(registry_with_entries):
    """Registry entries that the current setup didn't add should be removed."""
    coordinator = MagicMock()
    coordinator.device_id = "dev1"

    removed = prune_orphan_entities(
        hass=MagicMock(),
        config_entry_id="entry_x",
        coordinators=[coordinator],
        added_unique_ids={"dev1_battery"},  # active_map is NOT here → orphan
        platform="sensor",
    )

    assert removed == 1
    assert registry_with_entries._removed == ["sensor.robovac_active_map"]


def test_other_integration_entries_untouched(registry_with_entries):
    """Entries belonging to platforms other than ours must not be removed."""
    coordinator = MagicMock()
    coordinator.device_id = "dev1"

    prune_orphan_entities(
        hass=MagicMock(),
        config_entry_id="entry_x",
        coordinators=[coordinator],
        added_unique_ids={"dev1_battery"},
        platform="sensor",
    )

    # Verify the unrelated entry is still in the registry
    remaining_unique_ids = {e.unique_id for e in registry_with_entries.entities.values()}
    assert "thing_id_1" in remaining_unique_ids


def test_unmanaged_device_entries_untouched(registry_with_entries):
    """Entries for devices our coordinators don't manage stay put."""
    coordinator = MagicMock()
    coordinator.device_id = "dev1"

    prune_orphan_entities(
        hass=MagicMock(),
        config_entry_id="entry_x",
        coordinators=[coordinator],
        added_unique_ids={"dev1_battery"},
        platform="sensor",
    )

    # dev_unknown_battery (different device prefix) must survive
    remaining_unique_ids = {e.unique_id for e in registry_with_entries.entities.values()}
    assert "dev_unknown_battery" in remaining_unique_ids


def test_no_op_when_all_entries_match_current_setup(registry_with_entries):
    """If every registry entry is in added_unique_ids, nothing is removed."""
    coordinator = MagicMock()
    coordinator.device_id = "dev1"

    removed = prune_orphan_entities(
        hass=MagicMock(),
        config_entry_id="entry_x",
        coordinators=[coordinator],
        added_unique_ids={"dev1_battery", "dev1_active_map"},
        platform="sensor",
    )

    assert removed == 0
    assert registry_with_entries._removed == []


def test_platform_filter_isolates_sensor_from_select(registry_with_entries):
    """Pruning sensors must not affect select-domain entries."""
    # Add a select-domain entry that's "orphan" by sensor's added_unique_ids
    registry_with_entries.entities["5"] = _registry_entry(
        "select.robovac_scene",
        "dev1_scene_select",
        domain="select",
    )
    coordinator = MagicMock()
    coordinator.device_id = "dev1"

    removed = prune_orphan_entities(
        hass=MagicMock(),
        config_entry_id="entry_x",
        coordinators=[coordinator],
        added_unique_ids={"dev1_battery"},
        platform="sensor",
    )

    assert removed == 1  # only sensor's orphan, not the select one
    remaining_unique_ids = {e.unique_id for e in registry_with_entries.entities.values()}
    assert "dev1_scene_select" in remaining_unique_ids
