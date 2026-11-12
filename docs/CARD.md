# The bundled Lovelace card

`eufy-clean-card` is a dependency-free web component shipped inside the integration. It
draws the floor map, sends room, zone and geometry commands, and surfaces the vacuum's
own controls in one card.

This document describes how it is built and how it behaves. For configuration options and
dashboard examples, see the *Zone Cleaning* and *Room Cleaning* sections of the top-level
[`README.md`](../README.md).

---

## Registration

`__init__.py` serves `frontend/` as a static path and registers the card with
`add_extra_js_url`, so no manual resource entry is needed.

Two details are deliberate:

- **The `?v=` query is a content hash** over every file in `frontend/`, not the
  manifest version. The manifest can drift from the shipped bytes; the hash cannot, so a
  changed card always busts the browser cache and an unchanged one never does.
- **Registration is deferred** until the `frontend` integration is set up
  (`async_when_setup`). Registering earlier silently no-ops, and a headless install
  without `frontend` must still load the config entry — so a failure to register the card
  is logged and swallowed rather than failing setup.

The map renderer (`frontend/eufy-map-renderer.js`) is imported on demand by the card
rather than injected, so installs that never draw a map never load it.

---

## Structure

```
EufyCleanCard (HTMLElement, shadow DOM, no build step, no framework)
├── status row      vacuum state, run settings (suction, water level), time, area, battery, quick actions
├── mode bar        Rooms · Zones · No-go · Wall · Parts
├── map surface     <canvas> (client render) or <img> (camera PNG) + an SVG overlay
├── section         per mode: room chips and their settings, or the parts list
└── action row      Clean / Clear
```

`ZoneCleanCard` is the same class registered under a second tag whose default mode is
`zones`.

### Modes

| Mode | Needs a map | Behaviour |
|------|-------------|-----------|
| `rooms` | no | room chips with per-room settings; tapping the map selects a room |
| `zones` | yes | drag rectangles on the map, then clean them |
| `nogo` | yes | draw no-go zones; move, rotate and delete no-go and no-mop zones |
| `wall` | yes | draw, move, rotate and delete virtual walls |
| `parts` | no | consumable wear, with a reset per part |

Modes that need a map surface are hidden when there is none, and the mode bar disappears
entirely if neither a map nor accessories are available. `nogo` and `wall` also need the
vacuum's `nogo_zones_supported` attribute to be `true` (only on robots that accept
`set_nogo_zones`). A configured mode the card cannot offer falls back to `rooms`. Every
gesture belongs to the mode that began it: switching modes drops any in-flight drag, tap
and pointer state, and staged deletions and moves. Unsaved shapes stay with the mode that
drew them and are sent only from it.

### Per-room fields are device-driven

The card renders only the keys the vacuum declares in its `room_clean_options`
attribute — so a device without mop support shows no water-level selector, and a new
per-room field appears without a card change. `hide_edge_mop` is still honoured as a
force-hide.

---

## Map rendering

The card has two map surfaces and prefers the first:

1. **Client render (default).** It subscribes to the map websocket, fetches one geometry
   snapshot and draws grid, rooms, dock, robot and trail on a `<canvas>`, then applies
   pose and trail deltas as they arrive. Pan and zoom are local; room hit-testing is done
   in the browser against `rooms_grid`.
2. **Camera PNG.** The `camera` entity's image, refreshed by polling.

`client_render: false` pins the PNG. If the client render cannot start — no websocket, a
browser without `DecompressionStream`, a renderer that fails to load, a map command error
— the card **falls back to the PNG and says why**: in the console, and in the
`data-map-reason` attribute of the map element (`data-map-surface` names the surface in
use). A silent fallback is indistinguishable from "still loading". `not_found` and
`unknown_command` are not fallbacks: they mean the integration is not loaded yet (HA
starting), so the card shows the PNG meanwhile and retries with the backoff below.

Addressing is by `entity_id`, never by the browser's view of a device id: see
[`MAP_WS_CONTRACT.md`](MAP_WS_CONTRACT.md), *Addressing*.

When the integration reloads, the server ends the subscription with a `gone` event. The
card keeps the last frame and resubscribes after 2 s, doubling to at most 30 s while the
integration is still down, then re-requests the snapshot
([`MAP_WS_CONTRACT.md`](MAP_WS_CONTRACT.md), *Subscription*). A websocket reconnect
(the subscription is made with `resubscribe: false`) takes the same path.

A snapshot re-fetched for a new geometry revision or a reconnect keeps the current pan
and zoom; only a new grid size refits the view. While a snapshot is in flight, trail
events received before its reply are already in it and are dropped; later ones are
applied on top of it.

The canvas animates only while the robot marker is drawn (the halo around an undocked
robot, or a view reset); a docked robot draws on data changes only. A card removed from the
page pauses the renderer and drops the subscription; re-attaching resumes both. The grid is
smoothed with Scale2x at 4x, lowered to 2x or 1x when a 4x layer would exceed 4 MP, which
keeps large maps under mobile canvas limits.

### Coordinate rules

- The payload is in source-grid cells with row 0 first; **the client flips vertically at
  draw time and does nothing else.**
- The renderer's normalized coordinates are `nx = col / width`, `ny = 1 - row / height`,
  and the inverse **floors**. The server's `room_id_at_normalized` must agree exactly, or
  a tap near a boundary highlights one room and cleans another.
- Zone rectangles and shapes are sent **normalized** through `vacuum.send_command`; the
  server converts them to world units with `ny = (height - 1 - row) / height`, one grid
  row from the renderer's frame. The card stores shapes in the server's frame and its
  canvas projection converts, so a shape is drawn on the cells it covers and saved there.

### Map switches

After a multi-map switch the device keeps reporting the **old** frame until the robot
re-localizes. The card gates on a raw-pose movement threshold before adopting the new
map, so a stale frame is not drawn as if it were current. It persists the grounding per
vacuum in the browser (active map, and whether the robot has re-localized on it), so a
reload during that window stays gated, and a switch made while the card was closed is
still caught.

---

## Editing geometry

No-go zones and virtual walls can be drawn on the map; existing no-go zones, no-mop
zones and virtual walls can be dragged, rotated and deleted (no-mop zones cannot be
drawn: a new shape goes out as a no-go zone or a wall). Staged edits are held locally —
deletions as indices into the current geometry, transforms in device units (centimetres
and radians about the centroid) — and applied in one write.

Two constraints come from the device (see [`MAP.md`](MAP.md), *Map operations*):

- the write is **replace-all** across all three categories. The card sends only the
  additions and the `remove_*`/`move_*` indices, never `replace`; the integration merges
  them with the shapes the map carries and writes the complete set;
- indices are only meaningful within **one** geometry revision. A pending deletion
  carried across a revision would delete a different shape, so staged edits are dropped
  when the geometry underneath them changes.

---

## Tests

`tests/frontend/` is a jsdom suite covering **behaviour**: mode switching, hit-testing,
staged edits, fallbacks, command payloads, and the grid raster against the server's
(`golden.test.mjs`). Run it with `npm ci && npm test` in that directory; CI runs the same
on every pull request.

jsdom does no layout and draws nothing on a canvas, so a layout or rendering claim needs
a real browser, not this suite.
