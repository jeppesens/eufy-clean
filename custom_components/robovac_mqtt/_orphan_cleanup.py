"""Prune entity-registry entries a previous build created but this one gates off.

HA keeps such entries forever, showing them as permanently unavailable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import EufyCleanCoordinator

_LOGGER = logging.getLogger(__name__)


def prune_orphan_entities(
    hass: HomeAssistant,
    config_entry_id: str,
    coordinators: list[EufyCleanCoordinator],
    added_unique_ids: set[str],
    platform: str,
) -> int:
    """Remove registry entries for our coordinators that this setup didn't add.

    ``added_unique_ids`` are the entities the current setup is creating; returns
    the number of orphans removed.
    """
    try:
        registry = er.async_get(hass)
        # snapshot: async_remove mutates the registry as we iterate
        existing_entries = list(
            er.async_entries_for_config_entry(registry, config_entry_id)
        )
    except (AttributeError, RuntimeError) as err:
        # best-effort: skip silently if the registry isn't reachable
        _LOGGER.debug("Skipping orphan cleanup (no registry available: %s)", err)
        return 0
    device_ids = {c.device_id for c in coordinators}
    removed = 0
    for entry in existing_entries:
        if entry.platform != DOMAIN or entry.domain != platform:
            continue
        # our unique_ids are always "{device_id}_{suffix}"
        if not any(entry.unique_id.startswith(f"{d}_") for d in device_ids):
            continue
        if entry.unique_id in added_unique_ids:
            continue
        _LOGGER.info(
            "Removing orphan %s entity %s: this build does not provide it for"
            " this device",
            platform,
            entry.entity_id,
        )
        # unique_id embeds the eufy device id
        _LOGGER.debug("Orphan unique_id: %s", entry.unique_id)
        registry.async_remove(entry.entity_id)
        removed += 1
    if removed:
        _LOGGER.debug("Pruned %d orphan %s entities", removed, platform)
    return removed
