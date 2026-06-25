"""Shared helper for pruning entity-registry orphans.

When entities are conditionally created (e.g., gated by transport type or
api_type) the previous build may have registered entities the current build
no longer provides. HA keeps those registry entries forever, so they show as
permanently-unavailable on the device page until the user manually deletes
them. This helper removes the diff at platform setup.
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
    coordinators: list["EufyCleanCoordinator"],
    added_unique_ids: set[str],
    platform: str,
) -> int:
    """Remove registry entries for our coordinators that this setup didn't add.

    Args:
        hass: HA core.
        config_entry_id: ID of the config entry whose entities we are pruning.
        coordinators: All coordinators owned by this config entry.
        added_unique_ids: unique_ids of entities the current setup is creating.
        platform: HA platform domain (e.g., "sensor", "select").

    Returns:
        Count of orphans removed.
    """
    try:
        registry = er.async_get(hass)
        # Snapshot the list — async_remove mutates the registry as we iterate.
        existing_entries = list(
            er.async_entries_for_config_entry(registry, config_entry_id)
        )
    except (AttributeError, RuntimeError) as err:
        # Best-effort cleanup — skip silently if the registry isn't reachable
        # (e.g., in narrow unit-test contexts that mock hass).
        _LOGGER.debug("Skipping orphan cleanup (no registry available: %s)", err)
        return 0
    device_ids = {c.device_id for c in coordinators}
    removed = 0
    for entry in existing_entries:
        if entry.platform != DOMAIN or entry.domain != platform:
            continue
        # Our unique_ids are always "{device_id}_{suffix}" — only consider
        # registry entries that belong to one of our coordinators' devices.
        if not any(entry.unique_id.startswith(f"{d}_") for d in device_ids):
            continue
        if entry.unique_id in added_unique_ids:
            continue
        _LOGGER.info(
            "Removing orphan %s entity %s (unique_id=%s) — current build does"
            " not provide it for this device",
            platform,
            entry.entity_id,
            entry.unique_id,
        )
        registry.async_remove(entry.entity_id)
        removed += 1
    if removed:
        _LOGGER.debug("Pruned %d orphan %s entities", removed, platform)
    return removed
