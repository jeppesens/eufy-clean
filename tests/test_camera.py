"""Unit tests for the camera platform setup."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.robovac_mqtt.camera import async_setup_entry
from custom_components.robovac_mqtt.coordinator import EufyCleanCoordinator
from custom_components.robovac_mqtt.models import VacuumState


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("api_type", "receives_map", "expected_unique_ids"),
    [
        ("novel", True, ["dev_map"]),
        ("novel", False, []),
        ("legacy", False, []),
        ("scalar", True, []),
    ],
)
async def test_map_camera_only_created_where_a_map_arrives(
    api_type, receives_map, expected_unique_ids
):
    """Without a map source (Tuya Cloud polling, or local Tuya without the P2P
    feed) there is no map camera, and the one an older build registered is
    pruned. The live camera is added later, once P2P is up, so it is never
    pruned. Scalar devices get no map camera on any transport."""
    coordinator = MagicMock(spec=EufyCleanCoordinator)
    coordinator.device_id = "dev"
    coordinator.api_type = api_type
    coordinator.receives_map = receives_map
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
        added_unique_ids={*expected_unique_ids, "dev_camera"},
        platform="camera",
    )
