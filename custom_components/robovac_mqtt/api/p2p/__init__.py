"""Local, encrypted Tuya P2P client.

Opens the P2P map channel on the LAN with the device local key and returns the
room list for robots that expose it nowhere else (``mqtt=False`` devices such as
the S1 Pro). See ``docs/P2P_MAP_CHANNEL.md`` for the protocol.
"""

from __future__ import annotations

from .session import fetch_rooms, fetch_snapshot

__all__ = ["fetch_rooms", "fetch_snapshot"]
