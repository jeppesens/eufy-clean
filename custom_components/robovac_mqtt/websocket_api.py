"""Websocket commands serving the client-rendered map; see docs/MAP_WS_CONTRACT.md.

Registration is global, not per config entry: ``async_register_command`` raises
on a duplicate name. The integration's ``async_setup`` calls ``async_setup``
here once; a ``hass.data`` flag keeps it idempotent.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .api.map_geometry import build_map_dynamic
from .const import DOMAIN
from .coordinator import EufyCleanCoordinator

DATA_WS_REGISTERED = "websocket_api_registered"

# "device exists but has no decoded map" (yet; never on a scalar device) — distinct
# from ERR_NOT_FOUND so the client retries after the next "geometry" event
ERR_NO_MAP = "no_map"


@callback
def async_setup(hass: HomeAssistant) -> None:
    """Register the map websocket commands exactly once."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(DATA_WS_REGISTERED):
        return
    domain_data[DATA_WS_REGISTERED] = True
    websocket_api.async_register_command(hass, ws_map_geometry)
    websocket_api.async_register_command(hass, ws_map_subscribe)


@callback
def _find_coordinator(
    hass: HomeAssistant, device_id: str
) -> EufyCleanCoordinator | None:
    """Return the coordinator whose EUFY device id is ``device_id``.

    Skips one in teardown: it has sent ``gone`` and sends nothing more, so the
    device is not found until its entry is set up again.
    """
    for entry_data in hass.data.get(DOMAIN, {}).values():
        if not isinstance(entry_data, dict):
            continue  # the registration flag, not an entry
        for coordinator in entry_data.get("coordinators", []):
            if (
                coordinator.device_id == device_id
                and not coordinator._is_closing()  # noqa: SLF001
            ):
                return coordinator
    return None


def _coordinator_for_entity(
    hass: HomeAssistant, entity_id: str
) -> EufyCleanCoordinator | None:
    """Resolve one of this integration's entities to its coordinator.

    Two id spaces meet here: ``coordinator.device_id`` is the eufy device id,
    while HA's device registry (and ``hass.entities[...].device_id``) uses an
    unrelated UUID. Walk entity -> HA device -> ``identifiers[(DOMAIN, eufy id)]``.
    """
    entity_entry = er.async_get(hass).async_get(entity_id)
    if entity_entry is None or entity_entry.device_id is None:
        return None
    device_entry = dr.async_get(hass).async_get(entity_entry.device_id)
    if device_entry is None:
        return None
    for domain, identifier in device_entry.identifiers:
        if domain != DOMAIN:
            continue
        coordinator = _find_coordinator(hass, identifier)
        if coordinator is not None:
            return coordinator
    return None


@callback
def _resolve(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> EufyCleanCoordinator | None:
    """Look up the addressed coordinator, sending an error if there is none.

    Accepts ``entity_id`` (preferred) or ``device_id`` (the eufy id, not HA's).
    """
    entity_id = msg.get("entity_id")
    device_id = msg.get("device_id")
    if entity_id:
        coordinator = _coordinator_for_entity(hass, entity_id)
        addressed = f"entity {entity_id}"
    elif device_id:
        coordinator = _find_coordinator(hass, device_id)
        addressed = f"device id {device_id}"
    else:
        connection.send_error(
            msg["id"],
            websocket_api.const.ERR_INVALID_FORMAT,
            "one of entity_id or device_id is required",
        )
        return None
    if coordinator is None:
        connection.send_error(
            msg["id"],
            websocket_api.const.ERR_NOT_FOUND,
            f"No Eufy vacuum for {addressed}",
        )
    return coordinator


def _refuse_p2p_map(
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    coordinator: EufyCleanCoordinator,
) -> bool:
    """Refuse a robot on the local P2P map feed; True when refused.

    The geometry payload describes the MQTT and legacy map formats only. The
    P2P map has no geometry payload; clients show the camera image instead.
    """
    if coordinator.p2p is None:
        return False
    connection.send_error(
        msg["id"],
        websocket_api.const.ERR_NOT_SUPPORTED,
        f"No map geometry for {coordinator.device_name}: use the camera image",
    )
    return True


@websocket_api.websocket_command(
    {
        vol.Required("type"): "robovac_mqtt/map/geometry",
        # entity_id is what the bundled card sends; device_id is the eufy id,
        # kept for scripted callers.
        vol.Exclusive("entity_id", "addr"): str,
        vol.Exclusive("device_id", "addr"): str,
    }
)
@websocket_api.async_response
async def ws_map_geometry(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Serve the one-shot map geometry snapshot.

    The static half runs in an executor (per-cell walk, too slow for the loop);
    the live half must be taken after that hop so ``trail_seq`` cannot lag an
    event the client already has.
    """
    coordinator = _resolve(hass, connection, msg)
    if coordinator is None:
        return
    if _refuse_p2p_map(connection, msg, coordinator):
        return

    static = await coordinator.async_map_static_geometry()
    if static is None:
        connection.send_error(
            msg["id"],
            ERR_NO_MAP,
            f"No map decoded yet for {coordinator.device_name}",
        )
        return
    _, payload = static  # the revision is already inside the payload
    if coordinator._is_closing():  # noqa: SLF001 - teardown began during the build
        connection.send_error(
            msg["id"],
            websocket_api.const.ERR_NOT_FOUND,
            f"{coordinator.device_name} is being unloaded",
        )
        return

    # flush last: the snapshot's trail_seq and the next event's "from" must not
    # straddle a pending batch, or the client thinks it missed events
    coordinator.flush_map_events()

    trail = list(coordinator._robot_trail)  # noqa: SLF001
    trail_types = coordinator._trail_types_for(0, len(trail))  # noqa: SLF001
    connection.send_result(
        msg["id"],
        {
            **payload,
            **build_map_dynamic(
                dock=coordinator._dock_pixel,  # noqa: SLF001
                robot=coordinator._robot_pixel,  # noqa: SLF001
                trail=trail,
                trail_types=trail_types,
                trail_seq=len(trail),
                prev_trail=coordinator.snapshot_previous_trail,
                trail_color=coordinator.trail_color,
            ),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): "robovac_mqtt/map/subscribe",
        # entity_id is what the bundled card sends; device_id is the eufy id,
        # kept for scripted callers.
        vol.Exclusive("entity_id", "addr"): str,
        vol.Exclusive("device_id", "addr"): str,
    }
)
@callback
def ws_map_subscribe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Subscribe to live pose / trail / geometry events for one device."""
    coordinator = _resolve(hass, connection, msg)
    if coordinator is None:
        return
    if _refuse_p2p_map(connection, msg, coordinator):
        return

    msg_id = msg["id"]

    @callback
    def _forward(event: dict[str, Any]) -> None:
        connection.send_message(websocket_api.event_message(msg_id, event))

    connection.subscriptions[msg_id] = coordinator.async_add_map_listener(_forward)
    # result before events: the client must see the subscription confirmed first
    connection.send_result(msg_id)
