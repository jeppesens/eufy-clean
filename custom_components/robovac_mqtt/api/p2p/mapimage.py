"""Adapt the live :class:`~.mapdata.P2PMap` to the shared map model and renderer.

The renderer and the coordinate helpers (tap-a-room, zone conversion) work on a
``MapData`` grid; the room outline the S1 Pro streams already carries the pixel
type in its low 2 bits, so it serves as both the base map and the room mask.
"""

from __future__ import annotations

from ..map_render import MapOverlay
from ..map_stream import MapData
from .mapdata import P2PMap

RESOLUTION_CM = 5  # MapInfo carries no resolution; every Eufy map is 5 cm/px


def build_map_data(state: P2PMap) -> MapData | None:
    """Return a ``MapData`` for ``state``, or None until a map has arrived."""
    if not state.has_map:
        return None
    room_names = {
        room["id"]: room["name"] or f"Room {room['id'] + 1}" for room in state.rooms
    }
    if state.realtime is not None:
        raw, width, height = state.realtime, state.realtime_width, state.realtime_height
        origin_x, origin_y = state.realtime_origin_x, state.realtime_origin_y
    else:
        raw, width, height = b"", state.width, state.height
        origin_x, origin_y = state.origin_x, state.origin_y
    return MapData(
        raw_pixels=raw,
        width=width,
        height=height,
        origin_x=origin_x,
        origin_y=origin_y,
        resolution=RESOLUTION_CM,
        room_pixels=state.outline,
        room_outline_width=state.width if state.outline else 0,
        room_outline_height=state.height if state.outline else 0,
        room_outline_origin_x=state.origin_x,
        room_outline_origin_y=state.origin_y,
        room_names=room_names,
        virtual_walls=list(state.virtual_walls),
        forbidden_zones=list(state.forbidden_zones),
        ban_mop_zones=list(state.ban_mop_zones),
    )


def world_to_grid(md: MapData, x_cm: float, y_cm: float) -> tuple[float, float]:
    res = md.resolution or RESOLUTION_CM
    return (x_cm - md.origin_x) / res, (y_cm - md.origin_y) / res


def build_overlay(
    md: MapData,
    state: P2PMap,
    *,
    robot_status: str | None = None,
    robot_style: str = "googly",
    docked: bool = False,
) -> MapOverlay:
    """Project the dynamic parts of ``state`` (pose, path, obstacles) onto ``md``."""
    dock = state.dock
    pose = state.pose
    robot = heading = None
    if docked and dock is not None:
        robot = world_to_grid(md, dock.x, dock.y)
    elif pose is not None:
        robot = world_to_grid(md, pose.x, pose.y)
        heading = pose.theta / 100
    return MapOverlay(
        robot=robot,
        robot_heading=heading,
        robot_status=robot_status,
        robot_style=robot_style,
        dock=world_to_grid(md, dock.x, dock.y) if dock is not None else None,
        path=[(*world_to_grid(md, x, y), flags) for x, y, flags in state.path],
        obstacles=[
            (*world_to_grid(md, *o.points[0]), o.object_type) for o in state.obstacles if o.points
        ],
        target_rooms=frozenset(state.target_room_ids),
        target_zones=[[world_to_grid(md, *p) for p in quad] for quad in state.target_zones],
    )
