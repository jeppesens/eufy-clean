# The floor map

How the integration obtains a floor map, what it decodes it into, how the live robot
position and cleaning trail are tracked, and how all of that reaches a dashboard.

Companion documents: [`ARCHITECTURE.md`](ARCHITECTURE.md) for the transports,
and [`MAP_WS_CONTRACT.md`](MAP_WS_CONTRACT.md) for the websocket wire format.

---

## Overview

```
             ┌──────────────────────────── novel devices ──────────────────────────┐
             │ Eufy MQTT  biz/ protocol-41 frames  → api/map_stream.py             │
             │ DPS 165    room list, map id        → api/parser.py                 │
             └─────────────────────────────────────────────────────────────────────┘
             ┌─────────────────────────── legacy devices ──────────────────────────┐
             │ Tuya cloud storage   map blob        → api/tuya_storage.py           │
             │                                        api/tuya_map.py               │
             │ Tuya mobile MQTT     live channels    → api/tuya_mqtt.py              │
             └─────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
                              MapData  (api/map_stream.py)
                     grid · rooms · dock · robot · trail · restricted geometry
                                          │
                    ┌─────────────────────┴─────────────────────┐
                    ▼                                           ▼
         render_map_png (Pillow)                    build_map_static / _dynamic
         → camera.<vacuum>_map                      → robovac_mqtt/map/* websocket
         a PNG, re-rendered every ~2 s              a compact geometry snapshot plus
         while cleaning                             pose and trail events
```

Scalar devices report no map at all; the camera entity and the map websocket are gated
off for them.

---

## `MapData`

The single decoded representation both renderers consume, regardless of which transport
produced it:

| Field | Meaning |
|-------|---------|
| `width`, `height` | grid dimensions in cells |
| `origin_x`, `origin_y`, `resolution` | world frame: `cell = (world_cm - origin) / resolution` |
| `raw_pixels` | occupancy, 2 bits per cell: 0 unknown, 1 wall, 2 floor, 3 cleaned |
| `room_pixels` | room mask; the low two bits are a sub-type, the rest the room id |
| `rooms` | `[{id, name}, ...]`, real device room ids |
| `room_polygons` | vector room outlines, legacy only |
| `room_id_offset` | offset to subtract before a room id leaves the module |
| `dock`, `robot` | positions in grid cells |
| `trail`, `trail_types` | the cleaning path and per-point type |
| `virtual_walls`, `forbidden_zones`, `ban_mop_zones` | restricted geometry, world cm |

Two invariants matter everywhere downstream:

- **Room id 0 is a real room.** Never test a room id for truthiness; test membership in
  the room table.
- **`room_id_offset` is internal.** It must be subtracted before ids appear on the wire,
  in a service call, or in an entity attribute.

---

## Novel devices

The map arrives on the same MQTT connection as everything else, as `biz/`
protocol-41 frames: a JSON envelope carrying a channel id and a hex payload
(`parse_biz_protocol41`). Channels carry the occupancy grid, the room mask, the map
description, the dock and the robot pose; `api/map_stream.py` decodes them into
`MapData`.

The room list and the active map id also arrive on DPS 165 as `UniversalDataResponse` or
`RoomParams`, which is what populates `VacuumState.rooms` for the room-selection
entities.

---

## Legacy (Tuya) devices

### The map is a file, not a datapoint

No datapoint carries the map. The map lives as an object in Tuya cloud storage, and
`api/tuya_storage.py` fetches it in three steps:

1. `tuya.m.dev.common.file.list` — enumerate the device's stored objects;
2. `smartlife.m.dev.storage.config.get` — obtain short-lived S3 credentials;
3. a SigV4 presigned `GET` for the object itself.

Both API calls are undocumented and their field names are unstable, so lookups accept
every known alias and the whole path degrades cleanly to "no map" rather than raising.

### The blob format

`api/tuya_map.py` decodes it:

- a `0pam` magic and a 24-byte header (dimensions, origin, resolution, map id);
- an LZ4-compressed grid of **signed bytes** — `-1` unmapped, `-7` obstacle, `-12` wall,
  and any value `>= 0` a room cell whose id is `cell // 4`;
- a trailer of tagged sections carrying the room table, virtual walls, forbidden zones
  and no-mop zones.

Decompression is bounded (maximum dimensions and a decompression-ratio budget), because
the blob is attacker-influenceable input.

### Freshness

DPS 125 carries a `cid` that identifies the stored map. It is a **signal, not a
selector**: the device rewrites the stored object without bumping the `cid` — including
at the *start* of a clean, not only after one. The coordinator therefore:

- treats a changed `cid` as "definitely re-fetch";
- additionally polls for freshness after the robot stops, since a rewrite at an
  unchanged `cid` is otherwise invisible;
- rate-limits re-fetch attempts for a `cid` that keeps failing, and caps consecutive
  failures, so a broken map cannot turn into a login storm;
- adopts the first `cid` it sees for a map it already holds, instead of downloading it
  again.

### Live pose, trail and metadata

`api/tuya_mqtt.py` subscribes to the Tuya mobile MQTT topic `m/m/i/<device_id>` using a
session derived from the Thing SDK login. Frames are plaintext and start `55 aa`; byte
10 selects the channel:

| Channel | Content |
|---------|---------|
| `0x64` | map parameters: dimensions, origin and dock, as six little-endian uint32 |
| `0x65` | room outline polygons, per room |
| `0x67` | the dense cleaning path |
| `0x68` | forbidden zones — one four-corner quad each, 0.5 cm units |
| `0x69` | virtual walls — one two-point segment each, 0.5 cm units |
| `0x6c` | the live robot pose |
| `0x6e` | no-mop zones |
| `0x70` / `0x71` | per-room custom settings, and the master switch that enables them |
| `0x72` / `0x73` | selective-room selection and cleaning order |
| `0x75` | the dock pose |

**Pose (`0x6c`)** is a bare length-prefixed `Pose`: `x`/`y` in 0.5 cm, `theta` in
milliradians, relative to the dock.

**Trail (`0x67`)** is a dense stream of points, one 32-bit big-endian bitfield each:
two 15-bit sign-magnitude coordinates (Y then X) plus a two-bit type in the high bits —
0 cleaning, 1 transit. The points are in **the pose's own frame and unit**, so they need
no separate transform and no anchoring to the last known pose. The frame header carries a
cumulative byte offset, which is what lets the coordinator detect a gap.

**Placement.** Both convert to grid cells the same way:

```
col = dock_col + x / 10
row = dock_row - y / 10
```

with a small constant offset because the pose origin is the robot's centre while the map
marks the dock contacts.

### Stream behaviour the coordinator relies on

- The device publishes **only while the robot is moving**. A parked robot is silent, and
  silence is not an error.
- **A cleared category is announced by silence**, not by an empty frame: if no-go zones
  are deleted, the channel simply stops carrying them.
- The publish window **decays** mid-clean and is renewed by a periodic keepalive write
  (DPS 121) over the cloud; the coordinator sends it on a timer and gives up after a few
  consecutive failures rather than re-logging in forever.

### Frame changes

The dock pose on `0x75` is **map-relative**, so when the device grows or rewrites the
map the whole frame shifts underneath the points already held. The coordinator
differences consecutive frames, re-projects the cells it is holding, and emits a trail
`reset` — which is why a websocket client must draw the list it is given rather than
merging it into its own (see [`MAP_WS_CONTRACT.md`](MAP_WS_CONTRACT.md)).

A jump larger than a sanity threshold is treated as a frame change rather than as
movement.

---

## Trail lifetime

The trail belongs to a cleaning *session*, not to a connection:

- it is cleared when a new session starts;
- it survives a Home Assistant restart, because it is persisted with the map state;
- a brief dock visit mid-clean (auto-empty, a pause) does **not** clear it — a dock visit
  only ends the session after a grace period;
- the previous session's trail is kept and drawn only when it is the only trail there is,
  so a new run never draws on top of the old one.

Points further apart than a maximum step are treated as a jump and not joined; a few
consecutive rejections in a row are tolerated before the point is taken anyway, so a
genuinely teleporting robot still tracks.

---

## Map operations (legacy)

Map edits go out on DPS 124 as JSON commands, and **must be sent over the Tuya cloud**:
a LAN write is accepted by the device and then silently ignored.

Two properties of that datapoint shape the API:

- `setNogoZones` is **replace-all** across no-go zones, virtual walls *and* no-mop zones
  at once. Anything not resent is deleted, so the coordinator always rebuilds the full
  set from current state and sends it whole.
- A virtual wall is a two-point line whose endpoints carry direction; they must never be
  sorted or normalised.

Per-room settings behave the same way: `customRooms` is replace-all, and one unacceptable
value voids the entire write. Room *renames* are the exception — they address a single
room.

The `set_nogo_zones` service therefore addresses existing shapes **by index** into the
current geometry revision, refuses to move and remove the same index in one call, and
re-reads the geometry before writing so a stale index cannot delete the wrong shape.

---

## Rendering

### Server-side PNG (`camera.py`)

`render_map_png` draws the grid, room fills, room labels, restricted geometry, the dock,
the robot and the trail with Pillow, and the camera entity serves the result. The render
is repeated every ~2 s while cleaning, and `coordinator.map_revision` bumps on every
frame. The camera publishes the revision in its `map_revision` attribute at most once
every 10 s (the last frame is always written), which bounds the recorder rows a clean
adds.

The PNG is displayed **flipped** relative to the source grid: row 0 of the array is the
bottom of the image. Positions stored in `MapData` are always in the *unflipped* source
frame, and the renderer flips them at draw time.

### Websocket geometry

Instead of re-fetching a ~208 KiB image every couple of seconds, a client can fetch
one compact geometry snapshot and then receive pose and trail deltas over a websocket
subscription. `api/map_geometry.py` builds the payload and `websocket_api.py` serves it.

`coordinator.map_geometry_revision` — distinct from `map_revision` — bumps only when the
map's own geometry changes, gated on a content signature, so viewers re-fetch the
snapshot only when there is something new in it. The full wire format, the coordinate
rules and the reasons the two grids are shipped separately are in
[`MAP_WS_CONTRACT.md`](MAP_WS_CONTRACT.md).

---

## Where the code lives

| Concern | Module |
|---------|--------|
| Blob download | `api/tuya_storage.py` |
| Blob decode | `api/tuya_map.py` |
| Live channels | `api/tuya_mqtt.py` |
| Frame decode, `MapData`, PNG | `api/map_stream.py` |
| Websocket payload | `api/map_geometry.py` |
| Websocket commands | `websocket_api.py` |
| Map/trail state, freshness, re-projection | `coordinator.py` |
| Map edit commands | `api/legacy_commands.py`, `api/commands.py` |
| Camera entity | `camera.py` |
