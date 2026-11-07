"""Diagnostics support for Eufy Clean."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

REDACT_KEYS = {
    "password",
    # entry.data is emitted verbatim below; "username" is the account email.
    "username",
    "email",
    "access_token",
    "user_id",
    "user_center_id",
    "user_center_token",
    "gtoken",
    "certificate_pem",
    "private_key",
    "sid",
    "openudid",
    # user-chosen names: the robot's and, before migration, the rooms'
    "device_name",
    "last_seen_segments",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    coordinators = data.get("coordinators", [])

    devices = []
    for coordinator in coordinators:
        map_data = coordinator._map_data
        mqtt = coordinator._tuya_mqtt
        last_frame_ts = getattr(mqtt, "last_frame_ts", None)
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
                # live-map state: coordinates and counters only, no secrets
                "map": {
                    "has_map_data": map_data is not None,
                    "map_size": [map_data.width, map_data.height] if map_data else None,
                    "map_id": coordinator.data.map_id,
                    "fetched_map_cid": coordinator._fetched_map_cid,
                    "map_image_bytes": len(coordinator.map_image or b""),
                    "robot_pixel": coordinator._robot_pixel,
                    "dock_pixel": coordinator._dock_pixel,
                    "trail_points": len(coordinator._robot_trail),
                    "trail_head": coordinator._robot_trail[:3],
                    "trail_tail": coordinator._robot_trail[-3:],
                    # trail and live dot are placed off the dock cell; null dock
                    # here means neither can render
                    "map_dock_pixel": map_data.dock_pixel if map_data else None,
                    "legacy_dock_pose": coordinator._legacy_dock_pose,
                    # map_frame = frame of the grid we render; legacy_map_param =
                    # frame the device publishes in. They diverge as SLAM grows the
                    # map; live coordinates are differenced across the two.
                    "map_frame": (
                        {
                            "origin": [map_data.origin_x, map_data.origin_y],
                            "size": [map_data.width, map_data.height],
                        }
                        if map_data
                        else None
                    ),
                    "legacy_map_param": coordinator._legacy_map_param,
                    # unplaced points fall outside the grid we hold; they are kept
                    # and drawn once a covering grid arrives
                    "trail_raw_points": len(coordinator._robot_trail_raw),
                    "trail_unplaced": coordinator._trail_unplaced,
                    # device grid shape differs from ours; the re-download is
                    # deferred to post-clean, as the device only rewrites parked
                    "map_frame_divergence": coordinator._map_frame_divergence,
                    "trail_prev_counter": coordinator._trail_prev_counter,
                    "trail_reject_streak": coordinator._trail_reject_streak,
                    "legacy_pose_stream_active": mqtt is not None,
                    # "active" above only means the subscriber exists; these show
                    # whether the broker and device are actually feeding it
                    "mqtt_connack_rc": getattr(mqtt, "connack_rc", None),
                    "mqtt_subscribed": getattr(mqtt, "subscribed", None),
                    "mqtt_frames": getattr(mqtt, "frames", None),
                    "mqtt_last_frame_age": (
                        round(time.time() - last_frame_ts, 1)
                        if last_frame_ts
                        else None
                    ),
                    "map_keepalive_active": (
                        coordinator._map_keepalive_cancel is not None
                    ),
                    # with custom_clean_enabled False the robot stores per-room
                    # overrides but obeys none of them (looks like a failed write)
                    "rooms": len(coordinator.data.rooms or []),
                    "live_room_settings": len(coordinator._legacy_room_custom),
                    "custom_clean_enabled": coordinator.legacy_custom_clean_enabled,
                },
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
