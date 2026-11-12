# Map websocket contract (v3)

The wire format between the integration's map websocket commands
(`websocket_api.py`, `api/map_geometry.py`) and any client that draws the map itself —
the bundled card's renderer among them. **Both ends code against this file.** Do not
infer the shape from the renderer.

See [`MAP.md`](MAP.md) for how the data reaches the coordinator in the first place.

---

## Coordinate frame — read this first

There is exactly **one** frame on the wire: **source-grid cells**, indexed
`row * width + col`, with **row 0 = grid array row 0**.

`render_map_png` *displays* that frame flipped (`_to_out` computes `height - 1 - my`)
and flips the grid image with it, so the PNG's top edge is the grid's *last* row.
`_robot_pixel`, `_dock_pixel` and every `_robot_trail` entry are already in the
**unflipped** source frame; the PNG renderer flips them at draw time.

**A client must therefore flip vertically at draw time and do nothing else.** It must
not flip the payload, and it must not flip pose or trail separately from the grid.

World centimetres convert as `cell = (world - origin) / resolution`.

`dock`, `robot`, `trail` and `prev_trail` cells may be fractional: legacy devices place
them to two decimals, the same value in the snapshot and in events; whole cells are sent
as integers. Draw a point at `p + 0.5` either way and do not round it.

---

## Two revisions, deliberately separate

| Attribute | Meaning |
|-----------|---------|
| `coordinator.map_revision` | the **PNG frame token**: bumps on every re-render, including the pose-only ones that fire every ~2 s while cleaning |
| `coordinator.map_geometry_revision` | what this contract's `revision` means: bumps only when the map's own geometry changes |

The geometry revision is gated on a **content signature** — dimensions, origin,
resolution, a CRC of both pixel planes, the room table and the wall/zone counts.

Two rules follow from that, and both are load-bearing:

- **Identity comparison is not a substitute.** The novel/biz path reassigns `_map_data`
  on every map frame, so an `is`-comparison gates nothing there and every viewer would
  re-fetch the geometry once per frame.
- **Geometry must not be published from the renderer.** It is published from
  `coordinator._set_map_data()`, the single funnel through which `_map_data` is
  assigned. Publishing it from `_async_rerender_map` (where `map_revision` bumps)
  would tie geometry updates to the PNG, so making the render lazy would stop every
  browser from ever seeing a new map, with no error anywhere. Geometry events flow and
  dedupe correctly with `render_map_png` never called, and must keep doing so.

---

## Server API

```python
# custom_components/robovac_mqtt/api/map_geometry.py
def build_map_static(map_data: MapData, *, revision: int) -> dict: ...
def build_map_dynamic(
    *,
    dock: Sequence[float] | None = None,
    robot: Sequence[float] | None = None,
    trail: Sequence[Sequence[float]] | None = None,
    trail_seq: int = 0,
    trail_types: list[int] | None = None,
    prev_trail: Sequence[Sequence[float]] | None = None,
    trail_color: tuple[int, int, int] | list[int] | None = None,
) -> dict: ...
def build_map_geometry(map_data: MapData, *, revision: int, **live) -> dict: ...
```

These are pure and synchronous with no Home Assistant imports — but
**`build_map_static` must not run on the event loop**. It walks every cell twice in
Python (occupancy expansion plus room-mask re-registration), on the order of 50 ms for a
400x400 grid, which at one request per client is a visible stall.
`EufyCleanCoordinator.async_map_static_geometry()` runs it in an executor and caches the
result per `map_geometry_revision`: concurrent requests at one revision wait for the
same build, and every later client at that revision costs nothing.

`build_map_dynamic` is a handful of small lists and is meant to be taken **on the loop,
last** — after the executor hop and after `flush_map_events()`. That ordering is what
keeps the snapshot's `trail_seq` from falling behind an event the client has already
received.

---

## Geometry payload

`robovac_mqtt/map/geometry` → result:

```jsonc
{
  "v": 3,                  // 2 added trail_types/prev_trail; 3 adds trail_color
  "revision": 42,          // coordinator.map_geometry_revision, NOT map_revision
  "width": 150, "height": 215,
  "origin_x": -1200, "origin_y": -800, "resolution": 5,
  "occupancy":  "<base64(zlib(bytes[width*height]))>", // per byte: sub_type << 2 | pv
                                                       // pv: 0 unknown, 1 wall, 2 floor, 3 cleaned
  "rooms_grid": "<base64(zlib(bytes[width*height]))>", // 0 = no room, else real_room_id + 1
  "rooms": [{"id": 0, "name": "Kitchen"}],             // real ids; id 0 is REAL on legacy
  "room_polygons": {"0": [[col, row], ...]},           // vector outlines; legacy only
  "virtual_walls":   [[[x0,y0],[x1,y1]]],              // world cm
  "forbidden_zones": [[[x,y],[x,y],[x,y],[x,y]]],      // world cm
  "ban_mop_zones":   [[[x,y],[x,y],[x,y],[x,y]]],      // world cm
  "dock":  [col,row] | null,
  "robot": [col,row] | null,
  "trail": [[col,row], ...],
  "trail_types": [0, 1, ...], // one per trail point: 0 cleaning, 1 transit (v2)
  "trail_seq": 949,
  "prev_trail": [[col,row], ...], // the last finished run (v2); see below
  "trail_color": [246,245,244] | null  // the configured trail colour (v3)
}
```

Errors: `invalid_format` when neither address is given, `not_found` when no loaded
device matches (or its entry is unloading), and `no_map` when the device has no decoded
map: not yet, or never on a scalar device, which has no map. A robot on the local P2P
map feed answers `not_supported` to both commands: its map has no geometry payload.

### `room_polygons`

True vector outlines per room — `{"<real_room_id>": [[col, row], ...]}`, up to 32
vertices — in the **same source-grid frame as every other coordinate here** (row 0 =
grid row 0; the client applies the display flip). Keys are real room ids as strings, so
`"0"` is a real room and never means "no room".

Legacy devices only: the outlines come from the live `m/m/i` room channel, not from the
cloud map blob, which carries no equivalent. They arrive push-based a few seconds after
subscribe. Values keep two decimals of sub-cell precision — rounding them to whole cells
visibly squares off the outlines. Novel devices have no such channel, so the field is
present and empty there.

The field is additive and optional: a client that ignores it renders as it did before v2.

### The occupancy byte carries the room sub-type

Bits 0-1 are the occupancy value; **bits 2-3 are the room mask's sub-type**, and they
are not optional. `render_map_png` paints the room colour when
`sub_type == 0 OR pv in (2, 3)`. A client that sees only `pv` cannot evaluate the first
disjunct, so every in-room cell with `sub_type == 0` and a `pv` of 0 or 1 would render
as void or wall on the client and room-coloured on the server — interior walls appearing
from nowhere. Two of the eight `(sub_type, pv)` combinations diverge without it.

The sub-type rides in `occupancy` rather than in `rooms_grid` so that `rooms_grid` stays
purely about room identity (keeping the hit-test invariant intact) and the room-id
ceiling does not shrink. The two spare bits are free in practice: deflate absorbs the
extra entropy, and the compressed `occupancy` is the same size either way.

### Two grids, deliberately not merged

`occupancy` is `raw_pixels` expanded from 2 bits to 1 byte per cell.

`rooms_grid` is `room_pixels >> 2`, re-registered onto the occupancy grid's frame using
the renderer's own offset, with `room_id_offset` **already subtracted**, then `+1` so
that 0 can mean "no room".

They ship separately because merging them loses information: the renderer paints a cell
as wall when `sub_type != 0 and pv == 1`, yet `MapData.room_id_at_normalized` still
returns that cell's room id. A merged grid would have to pick one, and the client's
hit-test would then silently disagree with the server's. `room_id_offset` must **never**
appear in room ids on the wire.

Room ids are guarded to `0..254` (the `+1` must fit in a byte); a map exceeding that
ships `rooms_grid` as all zeroes and logs a warning.

**Both ends floor.** Normalized coordinates are fractions of the whole grid —
`nx = col / width`, `ny = 1 - row / height` — and the inverse is `floor`, never `round`,
because a cell owns the half-open span of its own width. The card does this in `roomIdAt`
and `cellFromEvent`; `MapData.room_id_at_normalized` must match it exactly, or a tap near
a room boundary highlights one room and cleans another.

### `trail_types` and `prev_trail`

`trail_types` has the length and order of `trail`: 0 = cleaning, 1 = transit. Only the
legacy 0x67 channel reports a type; every other point is 0.

`prev_trail` is the last finished run, for a client to draw dimmed. It is snapshot-only
(no event carries it) and empty whenever there is a live trail or the robot is cleaning,
returning or paused.

### `trail_color`

The same option the camera publishes as an attribute. It rides this payload as well
because a dashboard that draws the map in the browser need not have a camera entity
configured at all, and reading a documented option off one would silently ignore it
there. The camera attribute remains the fallback for an older backend, and is still the
only source on the PNG path.

---

## Addressing: send `entity_id`

Both commands take **either** `entity_id` (preferred) or `device_id`, exclusively.

`device_id` here means the **Eufy** device id — the value `coordinator.device_id` holds.
It is *not* Home Assistant's device-registry UUID, which is what a browser sees as
`hass.entities[<entity>].device_id`. Those are different id spaces, and passing the HA
UUID resolves nothing.

The bundled card therefore sends `entity_id`, and the server walks
entity → HA device → `identifiers={(DOMAIN, eufy_device_id)}`. The card always knows its
own configured entity ids, so this needs no registry lookup in the browser.

A client must **warn** when it cannot resolve its own address rather than returning
silently: a silent return is indistinguishable from "retry later", and leaves the card
sitting on the PNG fallback forever with nothing logged.

---

## Subscription

`robovac_mqtt/map/subscribe` → `send_result` immediately, then events:

```jsonc
{"t": "geometry", "revision": 43}                      // re-fetch geometry
{"t": "pose",  "robot": [col,row], "dock": [col,row]}  // dock only when it changes
{"t": "trail", "from": 1372, "p": [[col,row], ...], "types": [0, ...]}  // append-only
{"t": "trail", "from": 0, "reset": true, "p": [...], "types": [...]}     // session reset or re-projection
{"t": "gone"}                                          // terminal: subscription ended
```

`types` is `trail_types` for the points in `p`, same length and order.

`from` is the trail length *before* these points. A client whose local length differs
from `from` has missed events and must re-request the geometry.

A `reset` **replaces** the whole trail rather than appending. Besides a new cleaning
session it also fires when the map frame moves under the points already sent — the grid
grew and every cell was re-indexed ([`MAP.md`](MAP.md), *Frame changes*). A client must
therefore draw the list it is given and never merge it into what it already holds.

Pose and trail events are throttled server-side to **at most 2 Hz**, serialized once and
fanned out to all subscribers.

`gone` is the last event of a subscription. The server sends it to every map subscriber
when the config entry unloads or reloads (an options save reloads it), then drops the
subscription; nothing follows it. Commands addressed to the device answer `not_found`
until the entry is set up again.

---

## Client responsibilities

- Re-request the geometry snapshot on **every** subscribe, including re-subscribes.
- Subscribe with `subscribeMessage(..., { resubscribe: false })` and resubscribe yourself:
  the library's own resubscribe after a reconnect fails silently when the integration is
  not loaded yet (an HA restart accepts websocket connections before it is).
- On `gone`, and on the connection's `ready` event after a reconnect, unsubscribe, keep
  the last frame, and subscribe again after a delay with backoff (the bundled card: 2 s,
  doubling to at most 30 s). The new subscribe re-requests the snapshot as above.
- Treat `not_found` and `unknown_command` from either command as retryable with the same
  backoff, on the first subscribe as on a resubscribe: they mean the entry is reloading or
  the integration is not loaded yet, not a reason to fall back to the PNG.
- Treat `no_map` from the geometry command as "no decoded map yet": keep the subscription
  and fetch the geometry again on the next `geometry` event.
- Treat `not_supported` from either command as final: show the camera image.
- Hit-test rooms client-side: sample `rooms_grid`, subtract 1, send the **id**.
- Zone rectangles keep the existing contract: send **normalized** coordinates via
  `vacuum.send_command` and let the server convert. Do not reimplement
  `_zone_quads_to_blob_units` in JavaScript.

---

## Payload size

Representative figures for a 150x215 grid (32 250 cells, 6 rooms) with a trail of a few
thousand points, taken mid-clean:

| part | bytes |
|---|---|
| `occupancy` (deflate + base64) | ~1 600 |
| `rooms_grid` (deflate + base64) | ~1 150 |
| full JSON payload, uncompressed | ~27 000 |
| **full payload after `permessage-deflate`** | **~8 200** |
| live pose + trail | ~40 B/s while cleaning |

The snapshot is dominated by the trail, and it is sent **once per map change**, against a
PNG of ~208 KiB re-sent every ~2 s on the camera path.

**Do not "optimise" the trail encoding.** As raw JSON the trail is the large majority of
the payload, which looks alarming and invites a binary format. It is not worth doing: a
real trail is a *walk* — successive points differ by about one cell — so deflate already
reduces it by roughly 5x. A synthetic trail of uniformly random points does not compress
and will mislead anyone who re-measures with one.
