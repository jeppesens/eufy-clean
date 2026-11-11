"""Unit tests for the map camera platform."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.robovac_mqtt.camera import async_setup_entry
from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("api_type", "connection_type", "expected_unique_ids"),
    [
        ("novel", "mqtt", ["dev_map"]),
        ("novel", "cloud", []),
        ("novel", "local", []),
        ("legacy", "cloud", []),
        ("scalar", "mqtt", []),
    ],
)
async def test_map_camera_only_created_for_mqtt(
    api_type, connection_type, expected_unique_ids
):
    """The map only arrives over MQTT, so Tuya transports get no map camera
    (and the one an older build registered is pruned). Scalar devices get none
    on any transport."""
    coordinator = MagicMock(spec=EufyCleanCoordinator)
    coordinator.device_id = "dev"
    coordinator.api_type = api_type
    coordinator.connection_type = connection_type
    coordinator.p2p = None
    coordinator.data = VacuumState()

    hass = MagicMock()
    config_entry = MagicMock()
    config_entry.entry_id = "entry"
    hass.data = {"robovac_mqtt": {"entry": {"coordinators": [coordinator]}}}

    added_entities: list = []
    with patch("custom_components.robovac_mqtt.camera.prune_orphan_entities") as prune:
        await async_setup_entry(hass, config_entry, added_entities.extend)

    assert [e.unique_id for e in added_entities] == expected_unique_ids
    prune.assert_called_once_with(
        hass,
        "entry",
        [coordinator],
        added_unique_ids=set(expected_unique_ids),
        platform="camera",
    )
