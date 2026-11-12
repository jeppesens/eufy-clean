/*
 * jsdom harness for custom_components/robovac_mqtt/frontend/eufy-map-renderer.js
 *
 * WHAT THIS SUITE CAN AND CANNOT PROVE
 * ------------------------------------
 * jsdom does no layout and ships no 2d context, so nothing here renders a pixel
 * and nothing here may claim that it does. What is covered is (a) the pure
 * functions — inflate, classification, both coordinate transforms — against
 * hand-computed expectations, and (b) the class' state machine: rebuild gating,
 * incremental trail append, render coalescing, the transform matrix, and the
 * no-geometry no-ops.
 *
 * Two stubs exist, and both are asserted honestly:
 *   - a recording 2d context, used ONLY to read back the matrix passed to
 *     setTransform. It proves the flip is a single negative vertical scale and
 *     that cellFromEvent inverts that exact matrix. It proves nothing visual.
 *   - a recording Path2D, used to prove the trail path is APPENDED to rather
 *     than rebuilt. It proves nothing about stroking.
 *
 * Golden-image diffing of a real canvas against render_map_png is the missing
 * half and is out of reach of this harness by construction.
 */
import fs from "node:fs";
import zlib from "node:zlib";

// The module lives outside any package.json, so node would treat its .js as CJS
// and reject the `export` keyword. Importing it as a data: URL evaluates it as a
// real ES module — which is also how the browser will load it. It has no
// imports of its own, so nothing needs resolving relative to the original path.
const SRC = new URL("../../custom_components/robovac_mqtt/frontend/eufy-map-renderer.js", import.meta.url);
const code = fs.readFileSync(SRC, "utf8");
const mod = await import("data:text/javascript;base64," + Buffer.from(code, "utf8").toString("base64"));

const {
  EufyMapRenderer,
  inflateBase64,
  decodeGeometry,
  roomIdAt,
  cellFromEvent,
  worldToCell,
  buildGridImageData,
  ROOM_PALETTE,
  DEFAULT_PALETTE,
  DEFAULT_THEME,
} = mod;

let fail = 0;
const ok = (c, m) => { if (c) console.log("  ok:", m); else { console.error("  FAIL:", m); fail++; } };

// rAF is stubbed as a queue rather than a timer, so the pulse loop can never
// spin and no test waits on the clock: `flushRaf()` runs exactly the frames that
// were scheduled at the moment it is called.
let rafCalls = 0;
let rafQueue = [];
globalThis.requestAnimationFrame = (fn) => { rafCalls++; rafQueue.push(fn); return rafCalls; };
globalThis.cancelAnimationFrame = () => {};
const flushRaf = () => { const q = rafQueue; rafQueue = []; q.forEach((fn) => fn()); };

// --- stubs -------------------------------------------------------------------

class RecPath2D {
  constructor() { this.ops = []; }
  moveTo(x, y) { this.ops.push(["moveTo", x, y]); }
  lineTo(x, y) { this.ops.push(["lineTo", x, y]); }
  quadraticCurveTo(cx, cy, x, y) { this.ops.push(["quadraticCurveTo", cx, cy, x, y]); }
}

function recorderCtx() {
  const calls = [];
  const rec = (name) => (...args) => { calls.push([name, args]); };
  return {
    calls,
    setTransform: rec("setTransform"),
    clearRect: rec("clearRect"),
    drawImage: rec("drawImage"),
    beginPath: rec("beginPath"),
    moveTo: rec("moveTo"),
    lineTo: rec("lineTo"),
    closePath: rec("closePath"),
    fill: rec("fill"),
    stroke: rec("stroke"),
    arc: rec("arc"),
    fillRect: rec("fillRect"),
    save: rec("save"),
    restore: rec("restore"),
    translate: rec("translate"),
    scale: rec("scale"),
    rotate: rec("rotate"),
    fillText: rec("fillText"),
    strokeText: rec("strokeText"),
  };
}

// A host element, not a canvas: getContext yields whatever the test asks for
// (null = the headless case the renderer must survive).
function hostCanvas(ctx, rect = { left: 0, top: 0, width: 400, height: 300 }) {
  return {
    width: rect.width,
    height: rect.height,
    style: {},
    getContext: () => ctx,
    getBoundingClientRect: () => rect,
    addEventListener() {},
    removeEventListener() {},
  };
}

// --- fixtures ----------------------------------------------------------------

// 4x2 grid covering every occupancy value twice: once with no room (row 0) and
// once inside real room 0 (row 1, stored as 1).
const GRID_W = 4;
const GRID_H = 2;
const OCC = new Uint8Array([0, 1, 2, 3, 0, 1, 2, 3]);
const ROOMS = new Uint8Array([0, 0, 0, 0, 1, 1, 1, 1]);
const STATE = {
  v: 1,
  revision: 7,
  width: GRID_W,
  height: GRID_H,
  origin_x: -1200,
  origin_y: -800,
  resolution: 5,
  occupancy: OCC,
  rooms_grid: ROOMS,
  rooms: [{ id: 0, name: "Hallway" }],
  virtual_walls: [],
  forbidden_zones: [],
  ban_mop_zones: [],
  dock: null,
  robot: null,
  trail: [],
  trail_seq: 0,
};

const px = (img, col, row) => {
  const o = (row * img.width + col) * 4;
  return [img.data[o], img.data[o + 1], img.data[o + 2], img.data[o + 3]];
};
// Exact: buildGridImageData writes palette bytes unchanged (no shading).
const same = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);

// ---- 1. inflateBase64 --------------------------------------------------------
console.log("[1] inflateBase64");
{
  const raw = Buffer.from([0, 1, 2, 3, 0, 1, 2, 3, 255, 128, 7]);
  const b64 = zlib.deflateSync(raw).toString("base64"); // zlib.compress, as the server does
  const out = await inflateBase64(b64);
  ok(out instanceof Uint8Array, "returns a Uint8Array");
  ok(same(Array.from(out), Array.from(raw)), "round-trips a zlib.deflateSync fixture byte for byte");

  const big = Buffer.alloc(GRID_W * GRID_H * 2000, 2);
  const outBig = await inflateBase64(zlib.deflateSync(big).toString("base64"));
  ok(outBig.length === big.length, `inflates a multi-chunk payload whole (${outBig.length} B)`);

  ok((await inflateBase64("")).length === 0, "an empty payload yields an empty array, not a throw");

  // The format is zlib, not gzip and not raw deflate — picking either of the
  // other two DecompressionStream modes would fault on the header.
  let gzipThrew = false;
  try { await inflateBase64(zlib.gzipSync(raw).toString("base64")); } catch (_) { gzipThrew = true; }
  ok(gzipThrew, "a gzip payload is rejected (the stream really is 'deflate', not 'gzip')");
  let rawThrew = false;
  try { await inflateBase64(zlib.deflateRawSync(raw).toString("base64")); } catch (_) { rawThrew = true; }
  ok(rawThrew, "a headerless deflate payload is rejected (not 'deflate-raw')");
}

// ---- 2. decodeGeometry -------------------------------------------------------
console.log("[2] decodeGeometry");
{
  const payload = {
    ...STATE,
    occupancy: zlib.deflateSync(Buffer.from(OCC)).toString("base64"),
    rooms_grid: zlib.deflateSync(Buffer.from(ROOMS)).toString("base64"),
  };
  const decoded = await decodeGeometry(payload);
  ok(decoded.occupancy instanceof Uint8Array && same(Array.from(decoded.occupancy), Array.from(OCC)),
    "occupancy inflates to the source bytes");
  ok(decoded.rooms_grid instanceof Uint8Array && same(Array.from(decoded.rooms_grid), Array.from(ROOMS)),
    "rooms_grid inflates to the source bytes");
  ok(decoded.revision === 7 && decoded.origin_x === -1200 && decoded.rooms[0].name === "Hallway",
    "every other field passes through untouched");
  ok(await decodeGeometry(null) === null, "a null payload decodes to null");
}

// ---- 3. roomIdAt — room 0 is REAL -------------------------------------------
console.log("[3] roomIdAt");
{
  ok(roomIdAt(STATE, 0, 1) === 0, "stored 1 resolves to real room id 0 (a real room on legacy)");
  ok(roomIdAt(STATE, 3, 1) === 0, "the whole room-0 row resolves to 0");
  ok(roomIdAt(STATE, 0, 0) === null, "stored 0 is 'no room' -> null, not room 0");
  ok(roomIdAt(STATE, -1, 0) === null, "a negative column is null");
  ok(roomIdAt(STATE, GRID_W, 0) === null, "a column past the width is null");
  ok(roomIdAt(STATE, 0, GRID_H) === null, "a row past the height is null");
  ok(roomIdAt(null, 0, 0) === null, "no state -> null");
  ok(roomIdAt({ width: 2, height: 1 }, 0, 0) === null, "no rooms_grid -> null");
  const hi = { width: 2, height: 1, rooms_grid: new Uint8Array([9, 252]) };
  ok(roomIdAt(hi, 0, 0) === 9 - 1 && roomIdAt(hi, 1, 0) === 251, "stored value maps to id-1 across the range");
  // The distinction the whole design turns on: falsy but present.
  ok(roomIdAt(STATE, 0, 1) !== null && !roomIdAt(STATE, 0, 1),
    "room 0 is falsy AND non-null — callers must test against null, never truthiness");
}

// ---- 4. buildGridImageData ---------------------------------------------------
console.log("[4] buildGridImageData classification");
{
  const img = buildGridImageData(STATE, DEFAULT_PALETTE, false);
  ok(img.width === GRID_W && img.height === GRID_H, "output is one texel per cell");
  ok(img.data.length === GRID_W * GRID_H * 4, "output is RGBA");
  ok(img.data instanceof Uint8ClampedArray, "output is a Uint8ClampedArray");

  // Row 0 — no room anywhere: colour by occupancy alone.
  ok(same(px(img, 0, 0), [0, 0, 0, 0]), "occ 0 with no room = unknown, fully transparent");
  ok(same(px(img, 1, 0), [20, 20, 20, 255]), "occ 1 with no room = wall");
  ok(same(px(img, 2, 0), [200, 200, 200, 255]), "occ 2 with no room = floor");
  ok(same(px(img, 3, 0), [200, 200, 200, 255]), "occ 3 with no room = cleaned floor");

  // Row 1 — every cell is in real room 0 with sub-type 0. The server's rule is
  // `sub_type == 0 OR pv in (2,3)` (map_stream.py:486-492), so sub-type 0 makes
  // the WHOLE row take the room colour, including the unknown and wall cells.
  const hue0 = [...ROOM_PALETTE[0], 255];
  ok(same(px(img, 0, 1), hue0), "occ 0 in a sub-type-0 room takes the room colour");
  ok(same(px(img, 1, 1), hue0), "occ 1 in a sub-type-0 room takes the room colour");
  ok(same(px(img, 2, 1), hue0), "occ 2 inside a room takes the room hue");
  ok(same(px(img, 3, 1), hue0), "occ 3 inside a room takes the room hue");

  // Palette cycling is by REAL id, so room 0 gets hue 0 and id 10 wraps to it.
  const wrap = buildGridImageData(
    { width: 2, height: 1, occupancy: new Uint8Array([2, 2]), rooms_grid: new Uint8Array([2, 11]) },
    DEFAULT_PALETTE, false);
  ok(same(px(wrap, 0, 0), [...ROOM_PALETTE[1], 255]), "real id 1 takes hue 1");
  ok(same(px(wrap, 1, 0), [...ROOM_PALETTE[0], 255]), "real id 10 wraps back onto hue 0");

  // Theme applies to the occupancy colours only; room hues are theme-independent.
  const dark = buildGridImageData(STATE, DEFAULT_PALETTE, true);
  ok(same(px(dark, 1, 0), [100, 104, 109, 255]), "isDark picks the dark wall colour");
  ok(same(px(dark, 2, 1), hue0), "room hues do not change with the theme");

  // Degenerate inputs must produce an empty image, never a throw.
  ok(buildGridImageData(null, DEFAULT_PALETTE, false).data.length === 0, "null state -> empty image");
  ok(buildGridImageData({ width: 0, height: 0 }, DEFAULT_PALETTE, false).data.length === 0,
    "zero-sized state -> empty image");
  const short = buildGridImageData(
    { width: 2, height: 1, occupancy: new Uint8Array([2]), rooms_grid: new Uint8Array(0) },
    DEFAULT_PALETTE, false);
  ok(same(px(short, 1, 0), [0, 0, 0, 0]), "a truncated grid reads as unknown, matching the server's guard");
}

// ---- 4b. sub-type drives the fill, and it must be on the wire ---------------
console.log("[4b] room sub-type in occupancy bits 2-3");
{
  // Same room, same occupancy, DIFFERENT sub-type. Two of the eight
  // (sub_type, pv) combinations diverge if the sub-type is dropped from the
  // wire, which is why it rides in the occupancy byte's bits 2-3.
  const hue0 = [...ROOM_PALETTE[0], 255];
  const mk = (cells) => ({
    width: 4, height: 1,
    occupancy: new Uint8Array(cells),
    rooms_grid: new Uint8Array([1, 1, 1, 1]),
  });
  // sub-type 0 across pv 0..3 -> all room-coloured
  const s0 = buildGridImageData(mk([0, 1, 2, 3]), DEFAULT_PALETTE, false);
  ok(same(px(s0, 0, 0), hue0) && same(px(s0, 1, 0), hue0)
     && same(px(s0, 2, 0), hue0) && same(px(s0, 3, 0), hue0),
    "sub-type 0: every occupancy value takes the room colour");

  // sub-type 1 across pv 0..3 -> only free/cleaned take the room colour
  const s1 = buildGridImageData(mk([(1 << 2) | 0, (1 << 2) | 1, (1 << 2) | 2, (1 << 2) | 3]),
    DEFAULT_PALETTE, false);
  ok(same(px(s1, 0, 0), [0, 0, 0, 0]), "sub-type 1 + occ 0 stays transparent void");
  ok(same(px(s1, 1, 0), [20, 20, 20, 255]), "sub-type 1 + occ 1 stays a wall");
  ok(same(px(s1, 2, 0), hue0) && same(px(s1, 3, 0), hue0),
    "sub-type 1 + occ 2/3 still takes the room colour");
}

// ---- 5. the flip is NOT baked into the image data ---------------------------
console.log("[5] no flip in buildGridImageData");
{
  // Output row 0 must be PAYLOAD row 0. If the flip had been baked in here it
  // would also be applied at draw time and the robot would render mirrored
  // against its own map — the exact failure MAP_WS_CONTRACT warns about.
  const img = buildGridImageData(STATE, DEFAULT_PALETTE, false);
  ok(same(px(img, 1, 0), [20, 20, 20, 255]) && same(px(img, 2, 1), [...ROOM_PALETTE[0], 255]),
    "image row 0 is payload row 0 (the roomless row), row 1 is the room row");

  // A single-row-difference fixture makes it unambiguous.
  const twoRow = buildGridImageData(
    { width: 1, height: 2, occupancy: new Uint8Array([1, 2]), rooms_grid: new Uint8Array([0, 0]) },
    DEFAULT_PALETTE, false);
  ok(same(px(twoRow, 0, 0), [20, 20, 20, 255]), "payload index 0 lands at image row 0, unflipped");
  ok(same(px(twoRow, 0, 1), [200, 200, 200, 255]), "payload index width lands at image row 1, unflipped");
}

// ---- 6. worldToCell ----------------------------------------------------------
console.log("[6] worldToCell");
{
  ok(JSON.stringify(worldToCell(STATE, -1200, -800)) === JSON.stringify({ col: 0, row: 0 }),
    "the origin is cell (0, 0)");
  const c = worldToCell(STATE, -1195, -790);
  ok(c.col === 1 && c.row === 2, "(world - origin) / resolution");
  const half = worldToCell(STATE, -1197.5, -800);
  ok(half.col === 0.5, "sub-cell precision is preserved (not rounded to an index)");
  const negRes = worldToCell({ origin_x: 0, origin_y: 0, resolution: 0 }, 10, 20);
  ok(negRes.col === 2 && negRes.row === 4, "a zero/absent resolution falls back to 5, as the server does");
  ok(worldToCell(null, 0, 0) === null, "no state -> null");
}

// ---- 7. cellFromEvent inverts a known transform ------------------------------
console.log("[7] cellFromEvent");
{
  const t = { x: 10, y: 210, scale: 2 };
  const rect = { left: 5, top: 7, width: 400, height: 300 };
  // Forward map, written out by hand from the documented draw transform:
  //   screenX = t.x + scale * col        screenY = t.y - scale * row
  const fwd = (col, row) => ({ x: rect.left + t.x + t.scale * col, y: rect.top + t.y - t.scale * row });

  const a = fwd(3, 4);
  const cell = cellFromEvent(STATE, t, a.x, a.y, rect);
  ok(cell.col === 3 && cell.row === 4, "inverts the forward map at (3, 4)");

  const b = fwd(0, 0);
  const cell0 = cellFromEvent(STATE, t, b.x, b.y, rect);
  ok(cell0.col === 0 && cell0.row === 0, "inverts the forward map at the origin cell");

  // The flip: a LOWER screen y is a HIGHER row.
  const up = cellFromEvent(STATE, t, a.x, a.y - 20, rect);
  ok(up.row > cell.row, "moving up the screen increases the row (the frame is flipped at draw time)");

  ok(cellFromEvent(STATE, t, -1000, -1000, rect).col < 0,
    "a point outside the grid returns an out-of-range cell for roomIdAt to reject");
  ok(cellFromEvent(null, t, 0, 0, rect) === null, "no state -> null");
  ok(cellFromEvent(STATE, { x: 0, y: 0, scale: 0 }, 0, 0, rect) === null, "a zero scale -> null, not Infinity");
}

// ---- 8. no-geometry calls are no-ops ----------------------------------------
console.log("[8] no-geometry no-ops");
{
  const r = new EufyMapRenderer(hostCanvas(null));
  let threw = null;
  try {
    r.render();
    r.requestRender();
    r.resize();
    r.fit();
    r.zoomBy(2, 0, 0);
    r.setPose({ robot: [1, 1] });
    r.appendTrail([[1, 1], [2, 2]]);
    r.setTheme({ trail: "#fff" }, true);
    r.setGeometry(null);
    r.setGeometry({ width: 0, height: 0 });
    r._onDown({ pointerId: 1, clientX: 0, clientY: 0 });
    r._onWheel({ deltaY: 10, clientX: 0, clientY: 0 });
    r.destroy();
  } catch (e) {
    threw = e;
  }
  ok(threw === null, `every public method survives a missing geometry${threw ? ` (got: ${threw.message})` : ""}`);
  ok(r.state === null, "no geometry was adopted from a degenerate payload");
  ok(r.cellAt(10, 10) === null, "cellAt is null without geometry");
  ok(r.roomAt(10, 10) === null, "roomAt is null without geometry");
  ok(r._trailPoints.length === 0, "appendTrail before geometry adds nothing");
  ok(r.ctx === null, "a host with no 2d context leaves ctx null rather than throwing");
}

// ---- 9. trail append is incremental ------------------------------------------
// Reference: the whole-trail Catmull-Rom build (5 samples per segment, runs broken on a
// jump over 400 cells or a type change, only runs of `want` emitted). The incremental
// trail must emit exactly these ops, without rebuilding on each append.
function refSplineOps(points, types, want) {
  const ops = [];
  if (!points.length) return ops;
  const typeAt = (i) => (types && i < types.length ? types[i] : 0);
  const runs = [];
  let cur = [points[0]];
  let curType = typeAt(0);
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1];
    const b = points[i];
    if ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 > 160000 || typeAt(i) !== curType) {
      runs.push({ pts: cur, type: curType });
      cur = [b];
      curType = typeAt(i);
    } else cur.push(b);
  }
  runs.push({ pts: cur, type: curType });
  const cr = (p0, p1, p2, p3, t) => {
    const t2 = t * t;
    const t3 = t2 * t;
    return [0, 1].map((k) => 0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * t +
      (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2 + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3));
  };
  for (const { pts: run, type } of runs) {
    if (type !== want) continue;
    ops.push(["moveTo", run[0][0] + 0.5, run[0][1] + 0.5]);
    if (run.length === 1) continue;
    if (run.length === 2) {
      ops.push(["lineTo", run[1][0] + 0.5, run[1][1] + 0.5]);
      continue;
    }
    for (let i = 0; i < run.length - 1; i++) {
      const p0 = i === 0 ? run[0] : run[i - 1];
      const p3 = i === run.length - 2 ? run[i + 1] : run[i + 2];
      for (let t = 0.2; t < 1; t += 0.2) {
        const pt = cr(p0, run[i], run[i + 1], p3, t);
        ops.push(["lineTo", pt[0] + 0.5, pt[1] + 0.5]);
      }
      ops.push(["lineTo", run[i + 1][0] + 0.5, run[i + 1][1] + 0.5]);
    }
  }
  return ops;
}
const sameOps = (a, b) =>
  a.length === b.length &&
  a.every((op, i) => op[0] === b[i][0] && Math.abs(op[1] - b[i][1]) < 1e-9 && Math.abs(op[2] - b[i][2]) < 1e-9);

console.log("[9] incremental trail");
{
  globalThis.Path2D = RecPath2D;
  const r = new EufyMapRenderer(hostCanvas(null));
  r.state = { ...STATE }; // ctx is null, so nothing renders; only the path is exercised
  r.resetTrail([[0, 0], [1, 0], [2, 1]]);
  const clean = () => r._trail.paths[0];
  ok(clean() instanceof RecPath2D, "a Path2D is retained");
  ok(clean().ops[0][0] === "moveTo", "the first point is a moveTo");
  ok(clean().ops[0][1] === 0.5 && clean().ops[0][2] === 0.5, "points are drawn at the cell CENTRE (+0.5)");

  const kept = clean();
  r.appendTrail([[3, 1], [4, 2]]);
  ok(clean() === kept, "appending extends the retained Path2D instead of rebuilding it");
  ok(r._trailPoints.length === 5, "the point list grew by exactly the new points");
  ok(r._trailPoints[3][0] === 3 && r._trailPoints[3][1] === 1, "appended points keep their source-grid values");

  const many = Array.from({ length: 1000 }, (_, i) => [i % 97, (i * 7) % 89]);
  r.appendTrail(many);
  const before = clean().ops.length;
  r.appendTrail([[50, 50]]);
  ok(clean() === kept && clean().ops.length - before <= 5,
    `one appended point adds one segment, not a rebuild (${clean().ops.length - before} ops)`);
  ok(r._trail.tail instanceof RecPath2D && r._trail.tail.ops.length <= 6,
    "only the open run's last segment is rebuilt per append");

  const reset = r._trailPoints.length;
  r.resetTrail([[9, 9]]);
  ok(clean() !== kept, "resetTrail replaces the path object");
  ok(r._trailPoints.length === 1 && reset === 1006, "resetTrail discards the old points");

  r.appendTrail([]);
  ok(r._trailPoints.length === 1, "an empty append is a no-op");
  r.appendTrail([[1]]);
  ok(r._trailPoints.length === 1, "a malformed point is skipped, not appended as NaN");

  // Chunked appends of a typed trail with run breaks draw the same spline as one
  // whole-trail build: retained ops + the open tail per type.
  let seed = 7;
  const rnd = (n) => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
  for (let trial = 0; trial < 20; trial++) {
    const pts = [];
    const types = [];
    let x = 100;
    let y = 100;
    for (let i = 0; i < 300; i++) {
      if (rnd(40) === 0) x += 500; // a jump over the break distance
      x += rnd(5) - 2;
      y += rnd(5) - 2;
      pts.push([x, y]);
      types.push(rnd(25) === 0 ? 1 - (types[i - 1] || 0) : (types[i - 1] || 0));
    }
    const t = new EufyMapRenderer(hostCanvas(null));
    t.state = { ...STATE };
    t.resetTrail([], []);
    for (let at = 0; at < pts.length;) {
      const n = 1 + rnd(12);
      t.appendTrail(pts.slice(at, at + n), types.slice(at, at + n));
      at += n;
    }
    const tr = t._trail;
    let equal = true;
    for (const type of [0, 1]) {
      const got = (tr.paths[type] ? tr.paths[type].ops : []).slice();
      if (tr.tail && tr.tailType === type) got.push(...tr.tail.ops.slice(1));
      if (!sameOps(got, refSplineOps(pts, types, type))) equal = false;
    }
    if (!equal) { ok(false, `trial ${trial}: chunked appends match the whole-trail spline`); break; }
    if (trial === 19) ok(true, "20 random chunked typed trails match the whole-trail spline, op for op");
  }
  delete globalThis.Path2D;
}

// ---- 10. static layer rebuilds only on a revision change ---------------------
console.log("[10] static layer gating");
{
  const r = new EufyMapRenderer(hostCanvas(recorderCtx()));
  let builds = 0;
  const realBuild = r._buildStatic.bind(r);
  r._buildStatic = function () { builds++; return realBuild(); };

  r.setGeometry({ ...STATE, revision: 1 });
  ok(builds === 1, "the first geometry rasterises the grid");
  r.setGeometry({ ...STATE, revision: 1, robot: [1, 1] });
  ok(builds === 1, "the same revision reuses the static layer");
  r.setGeometry({ ...STATE, revision: 2 });
  ok(builds === 2, "a new revision rebuilds it");
  r.setTheme({ trail: "#000" }, true);
  ok(builds === 3, "a theme change rebuilds it (grid colours are baked in)");
  // jsdom has no 2d context for the offscreen canvas, so the rasterised layer
  // cannot exist here. That is the honest outcome, and it must not throw.
  ok(r._staticRooms === null && r._staticWalls === null,
    "with no offscreen 2d context the static layers stay null and nothing throws");
}

// ---- 11. render applies the flip exactly once -------------------------------
console.log("[11] the single flip");
{
  const ctx = recorderCtx();
  const rect = { left: 12, top: 20, width: 400, height: 300 };
  const r = new EufyMapRenderer(hostCanvas(ctx, rect));
  r._animate = false; // the pulse halo is not what is under test here
  r.setGeometry({ ...STATE, width: 150, height: 215, robot: [10, 20], dock: [1, 2] });
  r.fit();
  ctx.calls.length = 0;
  r.render();

  const setT = ctx.calls.filter((c) => c[0] === "setTransform");
  ok(setT.length === 3, `setTransform is called 3x: reset, the one flip, reset (${setT.length})`);
  const m = setT[1][1];
  const s = r.transform.scale;
  ok(m[0] === s && m[3] === -s, "the draw matrix is (s, 0, 0, -s, tx, ty): ONE negative vertical scale");
  ok(m[1] === 0 && m[2] === 0, "no shear — the flip is the only non-identity term");
  ok(m[4] === r.transform.x && m[5] === r.transform.y, "translation is the transform's own x/y (dpr 1 here)");
  ok(setT[0][1].join() === "1,0,0,1,0,0" && setT[2][1].join() === "1,0,0,1,0,0",
    "the matrix is reset before clearing and again on the way out");

  // Nothing else may flip: the recorded matrix, applied by hand to a cell, must
  // round-trip back through cellFromEvent to the same cell.
  const dev = (col, row) => ({ x: m[0] * col + m[2] * row + m[4], y: m[1] * col + m[3] * row + m[5] });
  const p = dev(10.5, 20.5);
  const back = cellFromEvent(r.state, r.transform, p.x / r._dpr + rect.left, p.y / r._dpr + rect.top, rect);
  ok(back.col === 10 && back.row === 20, "the robot's own cell survives draw-matrix -> cellFromEvent unchanged");

  // And the flip really is a flip: row 0 draws BELOW row height-1 on screen.
  ok(dev(0, 0).y > dev(0, r.state.height - 1).y, "grid row 0 draws at the bottom, as render_map_png shows it");

  // The robot is drawn at its cell centre, under that same matrix — never
  // pre-flipped into a different frame.
  const fills = ctx.calls.filter((c) => c[0] === "fill");
  const robotFill = fills.find(c => c[1].length > 0 && (c[1][0] === "M12,2C14.65,2 17.19,3.06 19.07,4.93L17.65,6.35C16.15,4.85 14.12,4 12,4C9.88,4 7.84,4.84 6.35,6.35L4.93,4.93C6.81,3.06 9.35,2 12,2M3.66,6.5L5.11,7.94C4.39,9.17 4,10.57 4,12A8,8 0 0,0 12,20A8,8 0 0,0 20,12C20,10.57 19.61,9.17 18.88,7.94L20.34,6.5C21.42,8.12 22,10.04 22,12A10,10 0 0,1 12,22A10,10 0 0,1 2,12C2,10.04 2.58,8.12 3.66,6.5M12,6A6,6 0 0,1 18,12C18,13.59 17.37,15.12 16.24,16.24L14.83,14.83C14.08,15.58 13.06,16 12,16C10.94,16 9.92,15.58 9.17,14.83L7.76,16.24C6.63,15.12 6,13.59 6,12A6,6 0 0,1 12,6M12,8A1,1 0 0,0 11,9A1,1 0 0,0 12,10A1,1 0 0,0 13,9A1,1 0 0,0 12,8Z" || c[1][0] === "M23,12H17V10L20.39,6H17V4H23V6L19.62,10H23V12M15,16H9V14L12.39,10H9V8H15V10L11.62,14H15V16M7,20H1V18L4.39,14H1V12H7V14L3.62,18H7V20Z"));
  const translates = ctx.calls.filter(c => c[0] === "translate");
  const robotTrans = translates.find(c => c[1][0] === 10.5 && c[1][1] === 20.5);
  ok(robotFill && robotTrans, "the robot MDI is drawn at (col+0.5, row+0.5) in the SAME unflipped grid frame");
  
  // The dock has TWO icons: a plain house, and a house with a lightning bolt while
  // the robot is sitting on it charging. The robot here is 18 cells away, so this
  // frame must be the plain one — asserting the bolt would pass only by accident.
  const MDI_HOME = "M10,20V14H14V20H19V12H22L12,3L2,12H5V20H10Z";
  const MDI_HOME_BOLT = "M12 3L2 12H5V20H19V12H22L12 3M11.5 18V14H9L12.5 7V11H15L11.5 18Z";
  const dockFill = fills.find(c => c[1].length > 0 && c[1][0] === MDI_HOME);
  const dockTrans = translates.find(c => c[1][0] === 1.5 && c[1][1] === 2.5);
  ok(dockFill && dockTrans, "the dock MDI is drawn once, in that same frame");
  ok(!fills.some(c => c[1].length > 0 && c[1][0] === MDI_HOME_BOLT),
    "and it is the plain house, not the charging one — the robot is not on the dock");

  // ...and the charging variant is what a docked, charging robot gets.
  ctx.calls.length = 0;
  r.setDockStatus(true, true);
  r.render();
  const charging = ctx.calls.filter((c) => c[0] === "fill");
  ok(charging.some(c => c[1].length > 0 && c[1][0] === MDI_HOME_BOLT),
    "docked + charging draws the lightning-bolt house instead");
}

// ---- 12. fit, zoom and render coalescing ------------------------------------
console.log("[12] viewport + coalescing");
{
  const ctx = recorderCtx();
  const rect = { left: 0, top: 0, width: 400, height: 300 };
  const r = new EufyMapRenderer(hostCanvas(ctx, rect));
  r.setGeometry({ ...STATE, width: 150, height: 215 });
  r.fit();
  const s = Math.min(400 / 150, 300 / 215) * 0.96;
  ok(Math.abs(r.transform.scale - s) < 1e-9, "fit scales to the tighter axis with a 4% margin");
  ok(Math.abs(r.transform.x - (400 - 150 * s) / 2) < 1e-9, "fit centres horizontally");
  ok(Math.abs(r.transform.y - (300 + 215 * s) / 2) < 1e-9, "fit places grid row 0 at the map's bottom edge");

  // Zoom is anchored at the pointer: the cell under it must not move.
  const cellBefore = r.cellAt(120, 90);
  r.zoomBy(2, 120, 90);
  const cellAfter = r.cellAt(120, 90);
  ok(Math.abs(r.transform.scale - s * 2) < 1e-9, "zoomBy multiplies the scale");
  ok(cellBefore.col === cellAfter.col && cellBefore.row === cellAfter.row,
    "the cell under the pointer is unchanged by the zoom (anchored)");
  r.zoomBy(1e9, 120, 90);
  ok(r.transform.scale <= 60, "the scale is clamped at the top");
  r.zoomBy(1e-9, 120, 90);
  ok(r.transform.scale >= 0.2, "the scale is clamped at the bottom");

  // Isolate: drop frames queued by earlier blocks and start from an idle guard.
  rafQueue = [];
  r._animate = false;
  r._raf = 0;
  rafCalls = 0;
  for (let i = 0; i < 5; i++) r.requestRender();
  ok(rafCalls === 1, `5 requestRender calls coalesce into 1 scheduled frame (${rafCalls})`);
  flushRaf();
  ok(rafCalls === 1, "with the pulse off, a drawn frame does not schedule another");
  r.requestRender();
  ok(rafCalls === 2, "the next data change schedules a fresh frame (the guard is released)");
  flushRaf();
}

// ---- 13. devicePixelRatio is capped at 2 ------------------------------------
console.log("[13] dpr cap");
{
  const rect = { left: 0, top: 0, width: 400, height: 300 };
  const r = new EufyMapRenderer(hostCanvas(recorderCtx(), rect));
  r.setGeometry({ ...STATE });
  const realDpr = globalThis.devicePixelRatio;
  globalThis.devicePixelRatio = 3.5;
  r.resize();
  ok(r._dpr === 2, `a 3.5x display is capped at 2 (got ${r._dpr})`);
  ok(r.canvas.width === 800 && r.canvas.height === 600, "the backing store is sized at the capped ratio");
  globalThis.devicePixelRatio = 1.5;
  r.resize();
  ok(r._dpr === 1.5, "a ratio below the cap is used as-is");
  if (realDpr === undefined) delete globalThis.devicePixelRatio; else globalThis.devicePixelRatio = realDpr;
}

// ---- 14. prefers-reduced-motion ---------------------------------------------
console.log("[14] prefers-reduced-motion");
{
  const realMM = globalThis.matchMedia;
  globalThis.matchMedia = (q) => ({ matches: /prefers-reduced-motion/.test(q), media: q });
  const quiet = new EufyMapRenderer(hostCanvas(recorderCtx()));
  ok(quiet._animate === false, "reduced motion disables the self-driven pulse");

  globalThis.matchMedia = () => ({ matches: false });
  const lively = new EufyMapRenderer(hostCanvas(recorderCtx()));
  ok(lively._animate === true, "without the preference the pulse is enabled");

  // A robot pose is what makes the pulse loop self-sustaining. With reduced
  // motion a drawn frame must NOT schedule another; without it, it must.
  quiet.setGeometry({ ...STATE, robot: [1, 1] });
  rafQueue = [];
  quiet._raf = 0;
  rafCalls = 0;
  quiet.requestRender();
  ok(rafCalls === 1, "reduced motion still draws on data change (one frame)");
  flushRaf();
  ok(rafCalls === 1, "reduced motion: a drawn frame schedules no follow-up, even with a live pose");

  lively.setGeometry({ ...STATE, robot: [1, 1] });
  rafQueue = [];
  lively._raf = 0;
  rafCalls = 0;
  lively.requestRender();
  flushRaf();
  ok(rafCalls === 2, "without the preference a live pose keeps the pulse loop running");
  rafQueue = []; // stop the loop; nothing beyond this point depends on it

  if (realMM === undefined) delete globalThis.matchMedia; else globalThis.matchMedia = realMM;
}

// ---- 15. pose + tap dispatch -------------------------------------------------
console.log("[15] pose and room tap");
{
  const rect = { left: 0, top: 0, width: 400, height: 300 };
  const taps = [];
  const r = new EufyMapRenderer(hostCanvas(recorderCtx(), rect), { onRoomTap: (id, cell) => taps.push([id, cell]) });
  r._animate = false;
  r.setGeometry({ ...STATE });
  // A hand-set transform, deliberately far below the fit `setGeometry` computed. The
  // fit is nulled with it: the zoom-out floor is anchored to the last fit, and leaving
  // a stale one would mean these fixtures start out already "below the floor".
  r.transform = { x: 0, y: 300, scale: 10 }; // 4x2 grid, row 0 at screen y 300
  r._fitTransform = null;

  r.setPose({ robot: [2, 1] });
  ok(r.state.robot[0] === 2 && r.state.robot[1] === 1, "setPose adopts the robot cell");
  ok(r.state.dock === null, "an omitted dock keeps its previous value");
  r.setPose({ dock: [0, 0] });
  ok(r.state.dock[0] === 0 && r.state.robot[0] === 2, "a dock-only pose leaves the robot alone");

  // Tap inside room 0 (row 1 -> screen y between 280 and 290).
  r._onDown({ pointerId: 1, clientX: 25, clientY: 285 });
  r._onUp({ pointerId: 1, clientX: 25, clientY: 285 });
  ok(taps.length === 1 && taps[0][0] === 0, "tapping a room-0 cell reports id 0, not 'no room'");
  ok(taps[0][1].col === 2 && taps[0][1].row === 1, "the reported cell is the source-grid cell");

  // Tap on a roomless cell reports nothing at all.
  r._onDown({ pointerId: 2, clientX: 25, clientY: 295 });
  r._onUp({ pointerId: 2, clientX: 25, clientY: 295 });
  ok(taps.length === 1, "a cell with no room dispatches no tap");

  // A drag past the slop is a pan, not a tap.
  const tx = r.transform.x;
  r._onDown({ pointerId: 3, clientX: 25, clientY: 285 });
  r._onMove({ pointerId: 3, clientX: 85, clientY: 285 });
  r._onUp({ pointerId: 3, clientX: 85, clientY: 285 });
  ok(taps.length === 1, "a drag does not fire a room tap");
  ok(Math.abs(r.transform.x - (tx + 60)) < 1e-9, "the drag panned the viewport instead");
}

// ---- 16. two-pointer pinch ---------------------------------------------------
console.log("[16] pinch zoom");
{
  const rect = { left: 0, top: 0, width: 400, height: 300 };
  const r = new EufyMapRenderer(hostCanvas(recorderCtx(), rect));
  r._animate = false;
  r.setGeometry({ ...STATE });
  r.transform = { x: 0, y: 300, scale: 1 };
  r._fitTransform = null; // see [15]: no fit floor in play for this fixture
  r._onDown({ pointerId: 1, clientX: 100, clientY: 100 });
  r._onDown({ pointerId: 2, clientX: 200, clientY: 100 });
  r._onMove({ pointerId: 2, clientX: 200, clientY: 100 }); // first move only seeds the distance
  ok(Math.abs(r.transform.scale - 1) < 1e-9, "the first two-pointer move seeds the pinch without zooming");
  r._onMove({ pointerId: 2, clientX: 300, clientY: 100 }); // 100px -> 200px
  ok(Math.abs(r.transform.scale - 2) < 1e-9, "spreading the fingers 2x doubles the scale");
  r._onUp({ pointerId: 2, clientX: 300, clientY: 100 });
  r._onUp({ pointerId: 1, clientX: 100, clientY: 100 });
  ok(r._pointers.size === 0, "lifting both pointers clears the pointer map");
}

// ---- 17. wheel is non-passive -----------------------------------------------
console.log("[17] wheel");
{
  const listeners = [];
  const canvas = {
    width: 400, height: 300, style: {},
    getContext: () => recorderCtx(),
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 400, height: 300 }),
    addEventListener: (t, fn, opts) => listeners.push([t, fn, opts]),
    removeEventListener: () => {},
  };
  const r = new EufyMapRenderer(canvas);
  const wheel = listeners.find((l) => l[0] === "wheel");
  ok(!!wheel && wheel[2] && wheel[2].passive === false,
    "the wheel listener is registered with {passive:false} so preventDefault works");
  ok(listeners.some((l) => l[0] === "pointerdown") && listeners.some((l) => l[0] === "pointercancel"),
    "pointer handlers (including cancel) are bound");

  r.setGeometry({ ...STATE });
  r._animate = false;
  r.transform = { x: 0, y: 300, scale: 1 };
  r._fitTransform = null; // see [15]: no fit floor in play for this fixture
  let prevented = false;
  wheel[1]({ deltaY: -100, clientX: 10, clientY: 10, cancelable: true, preventDefault: () => { prevented = true; } });
  ok(prevented, "a wheel event over the map is preventDefault'ed (the page must not scroll)");
  ok(r.transform.scale > 1, "scrolling up zooms in");

  const before = r.transform.scale;
  wheel[1]({ deltaY: 100, clientX: 10, clientY: 10, cancelable: true, preventDefault: () => {} });
  ok(r.transform.scale < before, "scrolling down zooms out");

  r.destroy();
  ok(r.state === null && r._trail === null, "destroy releases the geometry and the retained path");
}

// ---- 18. palette hygiene -----------------------------------------------------
console.log("[18] palette");
{
  const hex = (c) => "#" + c.map((v) => v.toString(16).padStart(2, "0")).join("").toUpperCase();
  ok(ROOM_PALETTE.length === 10, "ten room hues");
  ok(!ROOM_PALETTE.some((c) => hex(c) === "#DDDDDD"),
    "#DDDDDD (Tol's designated 'bad data' grey) is NOT a room colour");
  ok(new Set(ROOM_PALETTE.map(hex)).size === 10, "all ten hues are distinct");
  ok(ROOM_PALETTE.every((c) => c.length === 3 && c.every((v) => v >= 0 && v <= 255)), "hues are [r,g,b] bytes");
  ok(DEFAULT_PALETTE.rooms === ROOM_PALETTE, "the default palette reuses the exported hues (one definition)");
  ok(typeof DEFAULT_THEME.trail === "string" && typeof DEFAULT_THEME.robot === "string",
    "overlay colours are CSS strings supplied by the caller, not read from the DOM");
  ok(!code.includes("getComputedStyle") && !code.includes("document.querySelector"),
    "the module never reads a colour or a node out of the DOM");
  ok(!/^\s*import\s/m.test(code), "the module has no imports (loadable standalone in a browser)");
}

// ---- 19. the whole-map normalized frame (P3) ---------------------------------
// THE invariant pan/zoom can break silently. Zone rectangles go to the server as
// fractions OF THE WHOLE MAP and are converted there; the firmware accepts any
// coordinates it is handed, so a fraction that turned out to be of the VIEWPORT
// cleans the wrong part of the flat and nothing reports an error — not the
// service call, not the robot, not a log line. These assertions are numeric on
// purpose: "looks right" is exactly the failure mode.
console.log("[19] whole-map normalized coordinates under pan/zoom");
{
  const rect = { left: 0, top: 0, width: 400, height: 300 };
  const r = new EufyMapRenderer(hostCanvas(recorderCtx(), rect), { bindInput: false });
  r._animate = false;
  r.setGeometry({ ...STATE, width: 150, height: 215 });
  r.fitExact();

  ok(Math.abs(r.transform.scale - 400 / 150) < 1e-12, "fitExact scales to the box WIDTH (no 4% inset)");
  ok(r.transform.x === 0 && r.transform.y === 300,
    "fitExact puts the map's left edge at x=0 and grid row 0 at the box's bottom");

  // (a) DRAW then HIT-TEST, at four different transforms. `pointForNormalized` and
  //     `normalizedAtPoint` are the two directions of ONE projection: whatever the
  //     transform, a stored map coordinate drawn on the overlay must read back as
  //     itself. If these two ever drift, zones land on the wrong floor.
  const probes = [[0, 0], [0.25, 0.4], [0.5, 0.5], [0.9, 0.1], [1, 1]];
  const views = [
    ["at fit", () => {}],
    ["panned", () => r.panBy(-63, 27)],
    ["zoomed 2.5x", () => r.zoomBy(2.5, 260, 195)],
    ["panned again while zoomed", () => r.panBy(41, -18)],
  ];
  let worst = 0;
  for (const [label, move] of views) {
    move();
    let bad = 0;
    for (const [nx, ny] of probes) {
      const p = r.pointForNormalized(nx, ny);
      const back = r.normalizedAtPoint(p.x, p.y);
      worst = Math.max(worst, Math.abs(back.nx - nx), Math.abs(back.ny - ny));
      if (Math.abs(back.nx - nx) > 1e-9 || Math.abs(back.ny - ny) > 1e-9) bad++;
    }
    ok(bad === 0, `${label}: every stored map coordinate draws and hit-tests back to itself`);
  }
  ok(worst < 1e-9, `worst round-trip error across all four views is ${worst.toExponential(2)}`);

  // (b) The frame is MAP-relative, not viewport-relative. Panning by exactly one
  //     cell must move the map coordinate under a FIXED screen point by exactly one
  //     cell — 1/width in nx. A viewport-relative frame would report no change at all,
  //     which is precisely the bug this whole coordinate system exists to prevent.
  r.resetView(false);
  const s = r.transform.scale;
  const before = r.normalizedAtPoint(200, 150);
  r.panBy(s, 0); // the map moves one cell right under a stationary finger
  const after = r.normalizedAtPoint(200, 150);
  ok(Math.abs((before.nx - after.nx) - 1 / r.state.width) < 1e-12,
    "a one-cell pan shifts the map coordinate under a fixed screen point by exactly one cell");
  ok(Math.abs(before.ny - after.ny) < 1e-12, "...and not at all on the untouched axis");

  // (c) Zoom is about the pointer, so the map coordinate under it is invariant.
  r.resetView(false);
  const anchorBefore = r.normalizedAtPoint(137, 211);
  r.zoomBy(3.3, 137, 211);
  const anchorAfter = r.normalizedAtPoint(137, 211);
  ok(Math.abs(anchorBefore.nx - anchorAfter.nx) < 1e-12 &&
     Math.abs(anchorBefore.ny - anchorAfter.ny) < 1e-12,
    "the map coordinate under the zoom anchor does not move");
}

// ---- 20. fit target, clamping and reset (P3) ---------------------------------
console.log("[20] fit target, zoom clamp, pan clamp, reset");
{
  const rect = { left: 0, top: 0, width: 400, height: 300 };
  const r = new EufyMapRenderer(hostCanvas(recorderCtx(), rect), { bindInput: false });
  r._animate = false; // reset is instant, so no rAF is needed to observe it
  r.setGeometry({ ...STATE, width: 150, height: 215 });
  r.fitExact();
  const fit = { ...r.transform };

  ok(r.isOffFit() === false, "a fresh fit is not 'off fit' (the reset affordance stays hidden)");
  r.panBy(40, 0);
  ok(r.isOffFit() === true, "a pan is off fit");
  r.resetView(false);
  ok(Math.abs(r.transform.x - fit.x) < 1e-9 &&
     Math.abs(r.transform.y - fit.y) < 1e-9 &&
     Math.abs(r.transform.scale - fit.scale) < 1e-9,
    "reset restores the fit exactly");
  ok(r.isOffFit() === false, "...and the affordance hides again");

  // Zoom clamps. The floor is the FIT, not MIN_SCALE: zooming out past the whole map
  // just shrinks it into a corner of an empty viewport.
  r.zoomBy(1e9, 200, 150);
  ok(r.transform.scale <= 60 + 1e-9, `zoom in is clamped (${r.transform.scale})`);
  r.zoomBy(1e-9, 200, 150);
  ok(Math.abs(r.transform.scale - fit.scale) < 1e-9,
    "zoom out is clamped at the fit — the whole map is as far out as it goes");

  // Pan clamps: the map can never be pushed entirely off screen, or there is nothing
  // left on it to grab in order to bring it back.
  r.resetView(false);
  r.panBy(1e6, 1e6);
  let mw = r.state.width * r.transform.scale;
  let mh = r.state.height * r.transform.scale;
  const visibleX = Math.min(r.transform.x + mw, rect.width) - Math.max(r.transform.x, 0);
  const visibleY = Math.min(r.transform.y, rect.height) - Math.max(r.transform.y - mh, 0);
  ok(visibleX > 0 && visibleY > 0, `a runaway pan leaves the map on screen (${visibleX}x${visibleY} px)`);
  r.panBy(-1e6, -1e6);
  mw = r.state.width * r.transform.scale;
  mh = r.state.height * r.transform.scale;
  const visX2 = Math.min(r.transform.x + mw, rect.width) - Math.max(r.transform.x, 0);
  const visY2 = Math.min(r.transform.y, rect.height) - Math.max(r.transform.y - mh, 0);
  ok(visX2 > 0 && visY2 > 0, `...in the other direction too (${visX2}x${visY2} px)`);

  // refit: a ResizeObserver fires on ANY reflow, so it must not throw away a zoom the
  // user is in the middle of using.
  r.resetView(false);
  r.zoomBy(4, 120, 90);
  const zoomRatio = r.transform.scale / fit.scale;
  const centre = r.normalizedAtPoint(200, 150); // the map point in the middle of the 400x300 box
  // The ResizeObserver runs refit() AFTER the box changed: the old box must be remembered.
  rect.width = 600;
  rect.height = 450;
  r.refit();
  ok(Math.abs(r.transform.scale / r._fitTransform.scale - zoomRatio) < 1e-9,
    "refit keeps the user's zoom FACTOR across a box resize");
  const at = r.pointForNormalized(centre.nx, centre.ny);
  ok(Math.abs(at.x - 300) < 1e-9 && Math.abs(at.y - 225) < 1e-9,
    `the map point at the centre of the old box is at the centre of the new one (got ${at.x}, ${at.y})`);
  r.resetView(false);
  ok(Math.abs(r.transform.scale - 600 / 150) < 1e-9, "...and the new fit is the new box's width");
}

// ---- 20b. shadows are in bitmap px -------------------------------------------
// Canvas shadows ignore the transform, so a size divided by the zoom scale shrank them to
// nothing when zoomed in; they follow the dpr only.
console.log("[20b] shadow sizes do not follow the zoom");
{
  globalThis.Path2D = RecPath2D;
  const ctx = recorderCtx();
  const seen = [];
  for (const k of ["shadowBlur", "shadowOffsetX", "shadowOffsetY"]) {
    let v = 0;
    Object.defineProperty(ctx, k, {
      get: () => v,
      set: (x) => { v = x; seen.push([k, x, ctx.shadowColor]); },
    });
  }
  const r = new EufyMapRenderer(hostCanvas(ctx), { bindInput: false });
  r._animate = false;
  r.setTheme({ trail: "#f00" }, false);
  r.setGeometry({ ...STATE, trail: [[0, 0], [1, 1], [2, 0]], trail_seq: 3 });
  r._staticRooms = {}; // stand-ins: drawImage is recorded, never rasterised here
  r._staticWalls = {};
  r._dpr = 2;
  const pick = (scale) => {
    r.transform = { x: 0, y: 300, scale };
    seen.length = 0;
    r.render();
    const wall = seen.filter(([, , c]) => c === "rgba(0, 0, 0, 0.4)");
    const trail = seen.filter(([k, , c]) => k === "shadowBlur" && c === "#f00").map(([, x]) => x);
    return { wall: Object.fromEntries(wall.map(([k, x]) => [k, x])), trail };
  };
  for (const scale of [2.5, 20]) {
    const got = pick(scale);
    ok(got.wall.shadowBlur === 20 && got.wall.shadowOffsetX === 6 && got.wall.shadowOffsetY === 6,
      `at scale ${scale} the wall shadow is 10/3/3 bitmap px x dpr, falling down (got ${JSON.stringify(got.wall)})`);
    ok(got.trail.length > 0 && got.trail.every((x) => x === 8),
      `at scale ${scale} the trail glow is 4 px x dpr (got ${got.trail})`);
  }
  delete globalThis.Path2D;
}

// ---- 21. bindInput:false leaves input to the host ---------------------------
// The card's overlay sits above the canvas and takes every pointer event; if the
// renderer bound its own handlers too, a zones-mode drag would draw a rectangle
// AND pan the map out from under it.
console.log("[21] bindInput:false");
{
  const listeners = [];
  const canvas = {
    width: 400, height: 300, style: {},
    getContext: () => recorderCtx(),
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 400, height: 300 }),
    addEventListener: (t, fn, opts) => listeners.push([t, fn, opts]),
    removeEventListener: () => {},
  };
  const r = new EufyMapRenderer(canvas, { bindInput: false });
  ok(listeners.length === 0, "bindInput:false binds no listeners at all");
  ok(typeof r.panBy === "function" && typeof r.zoomBy === "function" && typeof r.resetView === "function",
    "...but the host can still drive the view directly");

  // onViewChange is how the card knows to re-project its overlay.
  let views = 0;
  const r2 = new EufyMapRenderer(hostCanvas(recorderCtx()), { bindInput: false, onViewChange: () => { views++; } });
  r2._animate = false;
  r2.setGeometry({ ...STATE });
  r2.fitExact();
  const afterFit = views;
  ok(afterFit > 0, "a fit notifies the host");
  r2.panBy(5, 5);
  ok(views === afterFit + 1, "a pan notifies the host exactly once");
  r2.zoomBy(1.2, 10, 10);
  ok(views === afterFit + 2, "so does a zoom");
  // A host callback that throws must not take the renderer down mid-gesture.
  const r3 = new EufyMapRenderer(hostCanvas(recorderCtx()), {
    bindInput: false,
    onViewChange: () => { throw new Error("host boom"); },
  });
  r3._animate = false;
  r3.setGeometry({ ...STATE });
  let threw = false;
  try { r3.fitExact(); r3.panBy(1, 1); } catch (_) { threw = true; }
  ok(!threw, "a throwing onViewChange is swallowed");
}

// ---- Y. the dot must not lag the trail -------------------------------------
// Pose (0x6c) and trail (0x67) are separate device channels and a trail point is
// "current pose cell + delta", so it describes a position reached BEFORE the pose
// confirming it — measured ~0.6 s apart live. Leaving the dot on the last pose
// draws the line running out ahead of the robot.
console.log("[Y] robot dot tracks the trail head between poses");
{
  const st = {
    v: 1, revision: 1, width: 8, height: 8, origin_x: 0, origin_y: 0, resolution: 5,
    occupancy: new Uint8Array(64), rooms_grid: new Uint8Array(64),
    rooms: [], virtual_walls: [], forbidden_zones: [], ban_mop_zones: [],
    dock: [0, 0], robot: [1, 1], trail: [], trail_seq: 0,
  };
  const r = new EufyMapRenderer(null, {});
  r.setGeometry(JSON.parse(JSON.stringify(st)));

  r.setPose({ robot: [1, 1] });
  ok(r.state.robot[0] === 1 && r.state.robot[1] === 1, "starts at the pose");

  // trail advances ahead of any new pose
  r.appendTrail([[2, 1], [3, 1], [4, 2]]);
  ok(r.state.robot[0] === 4 && r.state.robot[1] === 2,
    "the dot moves to the head of the trail, not left behind at the last pose");

  // a real pose still wins — it is the measured sample, the trail delta drifts
  r.setPose({ robot: [5, 3] });
  ok(r.state.robot[0] === 5 && r.state.robot[1] === 3,
    "a later pose overrides the trail-head estimate");

  // empty / malformed appends must not move or crash it
  r.appendTrail([]);
  ok(r.state.robot[0] === 5, "an empty append leaves the dot alone");
  r.appendTrail([[6, 4]]);
  ok(r.state.robot[0] === 6 && r.state.robot[1] === 4, "and a later point advances it again");
}

// ---- Z. previous-run trail --------------------------------------------------
// A new clean clears the live trail, so without this the map is blank for the
// first minutes of every session even though the flat has been cleaned many times.
// It is shown ONLY while the live slot is empty: two runs at once read as one
// tangled run, and no colour recovers which line is now and which is history.
console.log("[Z] previous-run trail");
{
  const mk = (prev, live) => ({
    v: 1, revision: 1, width: 8, height: 8, origin_x: 0, origin_y: 0, resolution: 5,
    occupancy: new Uint8Array(64), rooms_grid: new Uint8Array(64),
    rooms: [], virtual_walls: [], forbidden_zones: [], ban_mop_zones: [],
    dock: [0, 0], robot: [1, 1], trail: live, trail_seq: live.length, prev_trail: prev,
  });
  const r = new EufyMapRenderer(null, {});

  r.setGeometry(mk([[1, 1], [2, 2], [3, 3]], []));
  ok(r._prevTrailLen === 3, "previous run is built from the snapshot");
  ok(r._trailPoints.length === 0, "...and is kept separate from the live trail");

  // a live trail arriving must not disturb it
  r.appendTrail([[5, 5], [6, 6]]);
  ok(r._prevTrailLen === 3 && r._trailPoints.length === 2,
    "appending live points leaves the previous run alone");

  // it is snapshot-only: replaced wholesale, never appended to
  r.setGeometry(mk([[7, 7], [8, 8]], []));
  ok(r._prevTrailLen === 2, "a new snapshot replaces the previous run wholesale");

  // absent / too-short is a no-op, not a crash
  r.setGeometry(mk([], []));
  ok(r._prevTrailLen === 0, "an empty previous run clears it");
  r.setGeometry(mk([[1, 1]], []));
  ok(r._prevTrailLen === 0, "a single point is not a path");
  const bare = mk([], []); delete bare.prev_trail;
  r.setGeometry(bare);
  ok(r._prevTrailLen === 0, "a payload with no prev_trail at all is fine (older server)");

  // Only ever ONE trail on the map.
  r.setGeometry(mk([[1, 1], [2, 2], [3, 3]], []));
  ok(r._shouldDrawPrevTrail(), "with nothing in the live slot, the previous run is what the map shows");
  r.appendTrail([[5, 5], [6, 6]]);
  ok(!r._shouldDrawPrevTrail(),
    "the moment the new session lays a point down, the previous run is off the map");

  // A session boundary while the card is open: the reset takes the previous run WITH
  // it. From that moment the only run the map may show is the new one — including
  // while it is still empty, which is the first seconds of every clean. Keeping the
  // old one here is what put it back on screen just as the new session began.
  r.resetTrail([], []);
  ok(r._prevTrailLen === 0, "a reset drops the previous run along with the live one");

  // A snapshot is still free to hand one back: that is the parked case, where the
  // last run is the only run there is to show.
  r.setGeometry(mk([[4, 4], [5, 5]], []));
  ok(r._prevTrailLen === 2 && r._trailPoints.length === 0,
    "a snapshot's own prev_trail is adopted as before");
}

// ---- Z2. one trail colour, and only ever one trail on the map ---------------
// A finished run and a running one are drawn identically, on purpose: only one of
// them is ever on the map, so a second colour would distinguish nothing. What this
// pins is the "only one" half — the demoted run and the live one must never both
// be stroked, whichever slot the run currently sits in.
console.log("[Z2] one trail, one colour");
{
  globalThis.Path2D = RecPath2D;
  const ctx = recorderCtx();
  const strokes = [];
  const rawStroke = ctx.stroke;
  // Only trail strokes wear the trail colour — zones and outlines carry their own —
  // so counting them counts trails, and a trail drawn in ANY other colour counts 0.
  // The live run's open last segment (`_trail.tail`) belongs to the same run: not counted.
  let r = null;
  ctx.stroke = (...args) => {
    const tail = r && r._trail && r._trail.tail;
    if (ctx.strokeStyle === "#f00" && !(tail && args[0] === tail)) strokes.push(ctx.strokeStyle);
    rawStroke(...args);
  };
  r = new EufyMapRenderer(hostCanvas(ctx));
  r._animate = false;
  r.setTheme({ trail: "#f00" }, false);
  r.setGeometry({
    ...STATE, dock: [1, 2], robot: [4, 4],
    trail: [[4, 4], [5, 5], [6, 6]], trail_seq: 3,
    prev_trail: [[1, 1], [2, 2], [3, 3]],
  });

  const drawn = () => { strokes.length = 0; r.render(); return strokes; };

  ok(drawn().length === 1,
    "with a run in the live slot, exactly one trail is stroked — not it and the previous one");
  r.resetTrail([], []);
  ok(drawn().length === 0,
    "a session boundary leaves the map bare: the last run does not linger into the new run");
  r.appendTrail([[7, 7], [8, 8], [9, 9]]);
  ok(drawn().length === 1,
    "and the new session's first points take the map, alone");
  // Parked, nothing live: the previous run is the map's only trail, drawn exactly
  // like a live one — same colour, so this counts it.
  r.setGeometry({
    ...STATE, dock: [1, 2], robot: null, trail: [], trail_seq: 0,
    prev_trail: [[1, 1], [2, 2], [3, 3]],
  });
  ok(drawn().length === 1,
    "with nothing live, the previous run is stroked, in the live trail's own colour");
  delete globalThis.Path2D;
}

// ---- the robot marker does not blink out mid-clean --------------------------
// The status marker must stay visible near the dock: the transit legs run within the
// old 15-cell hide square. An update that carries no robot must not erase it either.
console.log("[17] robot marker visibility");
{
  const MDI_ROBOT = "M12,2C14.65,2 17.19,3.06 19.07,4.93L17.65,6.35C16.15,4.85 14.12,4 12,4C9.88,4 7.84,4.84 6.35,6.35L4.93,4.93C6.81,3.06 9.35,2 12,2M3.66,6.5L5.11,7.94C4.39,9.17 4,10.57 4,12A8,8 0 0,0 12,20A8,8 0 0,0 20,12C20,10.57 19.61,9.17 18.88,7.94L20.34,6.5C21.42,8.12 22,10.04 22,12A10,10 0 0,1 12,22A10,10 0 0,1 2,12C2,10.04 2.58,8.12 3.66,6.5M12,6A6,6 0 0,1 18,12C18,13.59 17.37,15.12 16.24,16.24L14.83,14.83C14.08,15.58 13.06,16 12,16C10.94,16 9.92,15.58 9.17,14.83L7.76,16.24C6.63,15.12 6,13.59 6,12A6,6 0 0,1 12,6M12,8A1,1 0 0,0 11,9A1,1 0 0,0 12,10A1,1 0 0,0 13,9A1,1 0 0,0 12,8Z";
  const MDI_NAV = "M12,2L4.5,20.29L5.21,21L12,18L18.79,21L19.5,20.29L12,2Z";
  const drawnAt = (ctx) => {
    const calls = ctx.calls;
    for (let i = 0; i < calls.length; i++) {
      const [name, args] = calls[i];
      if (name !== "fill" || !args.length) continue;
      if (args[0] !== MDI_ROBOT && args[0] !== MDI_NAV) continue;
      // The translate that positioned this icon is the last one before the fill.
      for (let j = i; j >= 0; j--) {
        if (calls[j][0] === "translate" && calls[j][1][0] !== -12) return calls[j][1];
      }
      return true;
    }
    return null;
  };
  const scene = (extra) => ({ ...STATE, dock: [40, 40], robot: [45, 40], trail: [[45, 40]], ...extra });

  // Five cells from the dock — inside the old box, and cleaning.
  let ctx = recorderCtx();
  let r = new EufyMapRenderer(hostCanvas(ctx));
  r.setGeometry(scene({}));
  r.setDockStatus(false, false);
  r.render();
  ok(!!drawnAt(ctx), "a robot 25 cm from its dock, not docked, is still drawn");

  // Home Assistant says docked: the house stands for it, one icon is enough.
  ctx = recorderCtx();
  r = new EufyMapRenderer(hostCanvas(ctx));
  r.setGeometry(scene({ robot: [40, 40], trail: [[40, 40]] }));
  r.setDockStatus(true, true);
  r.render();
  ok(!drawnAt(ctx), "a robot Home Assistant reports as docked is not drawn twice");

  // ...and that is what decides it, even for a robot sitting right on the dock.
  ctx = recorderCtx();
  r = new EufyMapRenderer(hostCanvas(ctx));
  r.setGeometry(scene({ robot: [40, 40], trail: [[40, 40]] }));
  r.setDockStatus(false, false);
  r.render();
  ok(!!drawnAt(ctx), "Home Assistant's state wins over proximity: not docked, so drawn");

  // Before HA has ever said, proximity is the only signal there is — and it is tight.
  ctx = recorderCtx();
  r = new EufyMapRenderer(hostCanvas(ctx));
  r.setGeometry(scene({ robot: [41, 40], trail: [[41, 40]] }));
  r.render();
  ok(!drawnAt(ctx), "with no dock status yet, a robot ON the dock is taken as parked");

  ctx = recorderCtx();
  r = new EufyMapRenderer(hostCanvas(ctx));
  r.setGeometry(scene({}));
  r.render();
  ok(!!drawnAt(ctx), "...but five cells away is not 'parked', which is the whole bug");

  // A thin update must not erase it: no robot in the event, no trail to fall back on.
  ctx = recorderCtx();
  r = new EufyMapRenderer(hostCanvas(ctx));
  r.setGeometry(scene({ trail: [] }));
  r.setDockStatus(false, false);
  r.render();
  const before = drawnAt(ctx);
  ok(!!before, "drawn from the pose to begin with");
  ctx.calls.length = 0;
  r.setPose({ robot: null });
  r.render();
  const after = drawnAt(ctx);
  ok(!!after, "a pose event carrying no robot leaves the marker where it was");
  ok(after && before && after[0] === before[0] && after[1] === before[1],
    "and leaves it at the SAME cell, not at some fallback");
}

// ---- the pulse loop runs only while a robot marker is drawn -----------------
console.log("[loop] self-driven frames stop when nothing moves");
{
  const r = new EufyMapRenderer(hostCanvas(recorderCtx()));
  r._animate = true;
  r.setGeometry({ ...STATE, dock: [1, 1], robot: [1, 1] });
  r.setDockStatus(true, true);
  rafQueue = [];
  r._raf = 0;
  rafCalls = 0;
  r.requestRender();
  flushRaf();
  ok(rafCalls === 1, `a docked robot draws once and schedules no follow-up (${rafCalls})`);

  r.setDockStatus(false, false);
  flushRaf();
  const n = rafCalls;
  flushRaf();
  ok(rafCalls === n + 1, "an undocked robot keeps the halo loop running");

  r.pause();
  rafQueue = [];
  const paused = rafCalls;
  r.setPose({ robot: [2, 1] });
  r.requestRender();
  ok(rafCalls === paused, "a paused renderer schedules no frame, even on a data change");
  r.resume();
  ok(rafCalls === paused + 1, "resume draws again");
  rafQueue = [];
}

// ---- the static upscale stays inside a pixel budget -------------------------
console.log("[upscale] Scale2x passes follow the grid size");
{
  const { staticUpscalePasses } = mod;
  ok(staticUpscalePasses(150, 215) === 2, "a typical grid keeps the 4x upscale");
  ok(staticUpscalePasses(512, 512) === 2, "512x512 (4 MP at 4x) still gets 4x");
  ok(staticUpscalePasses(800, 800) === 1, "800x800 drops to 2x (10 MP at 4x is over budget)");
  ok(staticUpscalePasses(1500, 1500) === 0, "1500x1500 is not upscaled at all");
  const sizes = [];
  const realCreate = globalThis.OffscreenCanvas;
  globalThis.OffscreenCanvas = class {
    constructor(w, h) { this.width = w; this.height = h; sizes.push([w, h]); }
    getContext() { return null; }
  };
  try {
    const r = new EufyMapRenderer(hostCanvas(null));
    const big = { ...STATE, width: 800, height: 800, occupancy: new Uint8Array(640000), rooms_grid: new Uint8Array(640000) };
    r.state = big;
    r._buildStatic();
    ok(sizes.length > 0 && sizes.every(([w, h]) => w === 1600 && h === 1600),
      `an 800x800 grid builds 1600x1600 layers (got ${JSON.stringify(sizes[0])})`);
    sizes.length = 0;
    r.state = { ...STATE };
    r._buildStatic();
    ok(sizes.length > 0 && sizes.every(([w, h]) => w === GRID_W * 4 && h === GRID_H * 4),
      "a small grid still builds 4x layers");
  } finally {
    if (realCreate === undefined) delete globalThis.OffscreenCanvas; else globalThis.OffscreenCanvas = realCreate;
  }
}

// ---- setRooms redraws only on a change --------------------------------------
console.log("[rooms] an unchanged room list does not redraw");
{
  const r = new EufyMapRenderer(hostCanvas(recorderCtx()));
  r._animate = false;
  r.setGeometry({ ...STATE });
  flushRaf();
  rafQueue = [];
  r._raf = 0;
  rafCalls = 0;
  r.setRooms([{ id: 0, name: "Hallway" }]);
  flushRaf();
  ok(rafCalls === 1, "the first room list draws");
  r.setRooms([{ id: 0, name: "Hallway" }]);
  ok(rafCalls === 1, "an equal list (fresh array) schedules no frame");
  r.setRooms([{ id: 0, name: "Hall" }]);
  ok(rafCalls === 2, "a rename redraws");
  flushRaf();
  r.setRooms([{ id: 0, name: "Hall" }, { id: 1, name: "Kitchen" }]);
  ok(rafCalls === 3, "an added room redraws");
  flushRaf();
}

console.log(fail === 0 ? "\nALL PASSED" : `\n${fail} FAILURES`);
process.exit(fail === 0 ? 0 : 1);
