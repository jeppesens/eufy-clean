"""Diagnostics support for Eufy Clean."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

REDACT_KEYS = {
    "password",
    "access_token",
    "user_id",
    "user_center_id",
    "user_center_token",
    "gtoken",
    "certificate_pem",
    "private_key",
    "sid",
    "openudid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinators = data.get("coordinators", [])

    devices = []
    for coordinator in coordinators:
        devices.append(
            {
                "device_id": coordinator.device_id[:8] + "...",
                "device_model": coordinator.device_model,
                "device_name": coordinator.device_name,
                "api_type": coordinator.api_type,
                "connection_type": coordinator.connection_type,
                "activity": coordinator.data.activity,
                "battery_level": coordinator.data.battery_level,
                "last_update_success": coordinator.last_update_success,
                "update_interval": str(coordinator.update_interval),
                "consecutive_cloud_failures": coordinator._consecutive_cloud_failures,
            }
        )

    return async_redact_data(
        {
            "entry_data": dict(entry.data),
            "device_count": len(coordinators),
            "devices": devices,
        },
        REDACT_KEYS,
    )
