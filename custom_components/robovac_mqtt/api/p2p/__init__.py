"""Local, encrypted Tuya P2P client.

Opens the P2P map channel on the LAN with the device local key and streams the
map, rooms, obstacles, restricted zones and the robot's path for robots that
expose them nowhere else (``mqtt=False`` devices such as the S1 Pro). See
``docs/P2P_MAP_CHANNEL.md`` for the protocol.
"""

from __future__ import annotations

from .session import P2PError, P2PRefused, P2PSession

__all__ = ["P2PError", "P2PRefused", "P2PSession"]
