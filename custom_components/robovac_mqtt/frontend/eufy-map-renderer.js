/*
 * eufy-map-renderer — dependency-free ES module, handed already-decoded geometry
 * (docs/MAP_WS_CONTRACT.md).
 *
 * FRAME: source-grid cells indexed `row * width + col`, row 0 = array row 0;
 * occupancy, rooms_grid, dock, robot and every trail point are in it, and world cm
 * converts as `(world - origin) / resolution`. Display flips vertically EXACTLY ONCE
 * — the negative vertical scale in the single `ctx.setTransform()` of `render()`;
 * flipping anywhere else mirrors the robot against its own map, silently.
 */

// Qualitative room hues, colour-blind-safe; no grey (the unknown cell is transparent).
export const ROOM_PALETTE = [
  [122, 164, 214], // #7aa4d6
  [165, 211, 150], // #a5d396
  [212, 172, 142], // #d4ac8e
  [183, 161, 207], // #b7a1cf
  [142, 212, 194], // #8ed4c2
  [227, 215, 140], // #e3d78c
  [224, 153, 153], // #e09999
  [160, 156, 222], // #a09cde
  [232, 185, 137], // #e8b989
  [217, 145, 181], // #d991b5
];

// Grid cell colours: bare [r,g,b(,a)] is theme-independent, {light,dark} picks on `isDark`.
export const DEFAULT_PALETTE = {
  rooms: ROOM_PALETTE,
  unknown: [0, 0, 0, 0],
  wall: { light: [20, 20, 20], dark: [100, 104, 109] },
  floor: { light: [200, 200, 200], dark: [72, 78, 88] },
  cleaned: { light: [200, 200, 200], dark: [72, 78, 88] },
};

// Overlay colours as CSS strings; resolved by the caller, never read from the DOM.
export const DEFAULT_THEME = {
  trail: "rgba(255, 255, 255, 1.0)",
  roomOutline: "rgba(255, 255, 255, 0.35)",
  robot: "#0ea5e9",
  robotRing: "rgba(14, 165, 233, 0.35)",
  dock: "#0ea5e9",
  virtualWall: "#d32f2f",
  forbiddenZone: "rgba(220, 50, 50, 0.22)",
  forbiddenZoneEdge: "#dc3232",
  banMopZone: "rgba(255, 165, 0, 0.22)",
  banMopZoneEdge: "#ffa500",
};

const MAX_DPR = 2;      // capped: a 3x phone would triple the fill rate for nothing
const MIN_SCALE = 0.2;
const MAX_SCALE = 60;
const TAP_SLOP_PX = 6;  // a press moving less than this is a tap, not a pan
const TRAIL_PX = 2;     // screen px; divided by scale at draw time to stay constant
// Point types on the legacy 0x67 PATH channel: 0 = cleaning, 1 = transit.
const TRAIL_TYPE_CLEAN = 0;
const TRAIL_TYPE_TRANSIT = 1;
// Dash rhythm for transit legs, in screen px (divided by scale like TRAIL_PX).
const TRAIL_DASH_ON = 5;
const TRAIL_DASH_OFF = 4;
const ROOM_OUTLINE_PX = 1; // screen px, like TRAIL_PX
// CSS px of the map `_clampPan` keeps inside the viewport per axis (or half the map).
const MIN_VISIBLE_PX = 48;
const VIEW_ANIM_MS = 220; // view-reset tween; skipped under prefers-reduced-motion
const EMPTY = new Uint8Array(0);
// Pixel budget of one upscaled static layer. iOS Safari blanks a canvas above 16.7 MP, and
// the static build holds two layers plus intermediates.
const STATIC_LAYER_MAX_PX = 4 * 1024 * 1024;
// A trail run breaks on a jump above 400 cells (20 m); sparse delivery makes smaller gaps normal.
const TRAIL_BREAK_SQ = 400 * 400;

const MDI_HOME = "M10,20V14H14V20H19V12H22L12,3L2,12H5V20H10Z";
const MDI_HOME_LIGHTNING_BOLT = "M12 3L2 12H5V20H19V12H22L12 3M11.5 18V14H9L12.5 7V11H15L11.5 18Z";
const MDI_ROBOT = "M12,2C14.65,2 17.19,3.06 19.07,4.93L17.65,6.35C16.15,4.85 14.12,4 12,4C9.88,4 7.84,4.84 6.35,6.35L4.93,4.93C6.81,3.06 9.35,2 12,2M3.66,6.5L5.11,7.94C4.39,9.17 4,10.57 4,12A8,8 0 0,0 12,20A8,8 0 0,0 20,12C20,10.57 19.61,9.17 18.88,7.94L20.34,6.5C21.42,8.12 22,10.04 22,12A10,10 0 0,1 12,22A10,10 0 0,1 2,12C2,10.04 2.58,8.12 3.66,6.5M12,6A6,6 0 0,1 18,12C18,13.59 17.37,15.12 16.24,16.24L14.83,14.83C14.08,15.58 13.06,16 12,16C10.94,16 9.92,15.58 9.17,14.83L7.76,16.24C6.63,15.12 6,13.59 6,12A6,6 0 0,1 12,6M12,8A1,1 0 0,0 11,9A1,1 0 0,0 12,10A1,1 0 0,0 13,9A1,1 0 0,0 12,8Z";
const MDI_NAVIGATE = "M12,2L4.5,20.29L5.21,21L12,18L18.79,21L19.5,20.29L12,2Z";
// Fallback dock-proximity radius (see `_robotIsParked`), in grid cells of 5 cm each.
const DOCK_PARKED_CELLS = 3;

function makeIconPath(svgStr) {
  return typeof Path2D === "function" ? new Path2D(svgStr) : svgStr;
}
let PATH_HOME, PATH_HOME_LIGHTNING_BOLT, PATH_ROBOT, PATH_NAVIGATE;

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

function themeColor(entry, isDark) {
  if (!entry) return [0, 0, 0, 0];
  if (Array.isArray(entry)) return entry;
  return (isDark ? entry.dark : entry.light) || [0, 0, 0, 0];
}

function prefersReducedMotion() {
  try {
    return !!(globalThis.matchMedia && globalThis.matchMedia("(prefers-reduced-motion: reduce)").matches);
  } catch (_) {
    return false;
  }
}

function createOffscreen(w, h) {
  if (typeof OffscreenCanvas === "function") return new OffscreenCanvas(w, h);
  if (typeof document !== "undefined" && document.createElement) {
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h;
    return c;
  }
  return null;
}

/**
 * base64 -> zlib-inflate -> bytes. Python's `zlib.compress` emits a zlib stream
 * (RFC 1950) = DecompressionStream's "deflate"; "deflate-raw"/"gzip" throw on it.
 */
export async function inflateBase64(str) {
  if (!str) return EMPTY;
  const bin = atob(str);
  const packed = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) packed[i] = bin.charCodeAt(i);

  const ds = new DecompressionStream("deflate");
  const writer = ds.writable.getWriter();
  // Not awaited: a big chunk blocks on backpressure until the reader below drains it.
  // Errors still surface — a corrupt stream faults the readable, so read() rejects.
  writer.write(packed).catch(() => {});
  writer.close().catch(() => {});

  const reader = ds.readable.getReader();
  const chunks = [];
  let total = 0;
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    chunks.push(value);
    total += value.length;
  }
  const out = new Uint8Array(total);
  let at = 0;
  for (const c of chunks) {
    out.set(c, at);
    at += c.length;
  }
  return out;
}

/** Inflate the two grids of a geometry message; everything else copied untouched. */
export async function decodeGeometry(payload) {
  if (!payload) return null;
  const [occupancy, rooms_grid] = await Promise.all([
    inflateBase64(payload.occupancy),
    inflateBase64(payload.rooms_grid),
  ]);
  return Object.assign({}, payload, { occupancy, rooms_grid });
}

/**
 * Room id under a source-grid cell, else null. `rooms_grid` stores `real_room_id + 1`
 * so stored 0 can mean "no room": real room id 0 exists, so never truthiness-test it.
 */
export function roomIdAt(state, col, row) {
  if (!state || !state.rooms_grid) return null;
  const c = Math.floor(col);
  const r = Math.floor(row);
  if (!Number.isFinite(c) || !Number.isFinite(r)) return null;
  if (c < 0 || r < 0 || c >= state.width || r >= state.height) return null;
  const stored = state.rooms_grid[r * state.width + c];
  if (!(stored > 0)) return null;
  return stored - 1;
}

/**
 * Canvas-local CSS px -> CONTINUOUS grid cell; exact inverse of `render()`'s flipped
 * transform, so rows grow upwards from `transform.y`. Unrounded (the hit-test floors).
 */
export function cellFromPoint(transform, x, y) {
  return {
    col: (x - transform.x) / transform.scale,
    row: (transform.y - y) / transform.scale,
  };
}

/** CONTINUOUS source-grid cell -> canvas-local CSS pixel. Inverse of `cellFromPoint`. */
export function pointFromCell(transform, col, row) {
  return {
    x: transform.x + col * transform.scale,
    y: transform.y - row * transform.scale,
  };
}

/** Screen point -> source-grid cell INDEX (floored); may land outside the grid. */
export function cellFromEvent(state, transform, clientX, clientY, rect) {
  if (!state || !transform || !transform.scale) return null;
  const c = cellFromPoint(transform, clientX - (rect ? rect.left : 0), clientY - (rect ? rect.top : 0));
  return { col: Math.floor(c.col), row: Math.floor(c.row) };
}

/* WHOLE-MAP normalized coordinates: fractions of the whole grid, origin top-left,
 * never of the visible viewport — zone rectangles reach the server this way and the
 * firmware accepts whatever it is given, so a viewport fraction cleans the wrong area.
 *     nx = col / width          col = nx * width
 *     ny = 1 - row / height     row = (1 - ny) * height
 * The `1 -` is `render()`'s flip; pixels enter and leave only through
 * `cellFromPoint`/`pointFromCell`, which keeps the result viewport-independent.
 */

export function cellToNormalized(state, col, row) {
  if (!state || !state.width || !state.height) return null;
  return { nx: col / state.width, ny: 1 - row / state.height };
}

export function normalizedToCell(state, nx, ny) {
  if (!state || !state.width || !state.height) return null;
  return { col: nx * state.width, row: (1 - ny) * state.height };
}

/** World cm -> grid cell, `(world - origin) / resolution`. Unrounded (sub-cell). */
export function worldToCell(state, wx, wy) {
  if (!state) return null;
  const res = state.resolution || 5;
  return { col: (wx - state.origin_x) / res, row: (wy - state.origin_y) / res };
}

/** Scale2x smoothing of blocky pixel art. `src32` is 32-bit RGBA pixels. */
function scale2x(width, height, src32) {
  const nw = width * 2;
  const nh = height * 2;
  const dst32 = new Uint32Array(nw * nh);
  
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const p = src32[y * width + x];
      const t = y === 0 ? p : src32[(y - 1) * width + x];
      const b = y === height - 1 ? p : src32[(y + 1) * width + x];
      const l = x === 0 ? p : src32[y * width + (x - 1)];
      const r = x === width - 1 ? p : src32[y * width + (x + 1)];
      
      let A = p, B = p, C = p, D = p;
      if (t !== b && l !== r) {
        A = (l === t) ? l : p;
        B = (r === t) ? r : p;
        C = (l === b) ? l : p;
        D = (r === b) ? r : p;
      }
      
      const dstIdx = (y * 2) * nw + (x * 2);
      dst32[dstIdx] = A;
      dst32[dstIdx + 1] = B;
      dst32[dstIdx + nw] = C;
      dst32[dstIdx + nw + 1] = D;
    }
  }
  return { width: nw, height: nh, data: dst32 };
}

/** Scale2x passes for a w x h grid: 2 (4x) while a layer fits STATIC_LAYER_MAX_PX, else 1 or 0. */
export function staticUpscalePasses(width, height) {
  const cells = width * height;
  if (cells * 16 <= STATIC_LAYER_MAX_PX) return 2;
  if (cells * 4 <= STATIC_LAYER_MAX_PX) return 1;
  return 0;
}

function catmullRom(p0, p1, p2, p3, t) {
  const t2 = t * t;
  const t3 = t2 * t;
  return [
    0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
    0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3),
  ];
}

/**
 * Catmull-Rom trail built point by point, O(1) per point. A run breaks on a jump over
 * TRAIL_BREAK_SQ or a type change; each type draws into its own retained Path2D in
 * `paths[type]`. A segment is final once the point after its end arrives and is appended
 * then; the open run's last segment lives in `tail`, rebuilt by `refreshTail()`.
 * Points sit at the cell centre (+0.5). With no Path2D (headless) only the run is tracked.
 */
export class SplineTrail {
  constructor(newPath) {
    this._newPath = newPath;
    this.paths = { [TRAIL_TYPE_CLEAN]: newPath() };
    this.tail = null;
    this.tailType = TRAIL_TYPE_CLEAN;
    this._run = []; // the open run's last <= 4 points
    this._runLen = 0;
    this._runType = TRAIL_TYPE_CLEAN;
  }

  _path(type) {
    if (!(type in this.paths)) this.paths[type] = this._newPath();
    return this.paths[type];
  }

  // Run point by absolute index; the window holds the last `_run.length` of `_runLen`.
  _at(i) {
    return this._run[i - (this._runLen - this._run.length)];
  }

  // Segment i -> i+1 of the open run. `last` clamps p3 to the end point.
  _segment(path, i, last) {
    if (!path) return;
    const p1 = this._at(i);
    const p2 = this._at(i + 1);
    if (this._runLen === 2) {
      path.lineTo(p2[0] + 0.5, p2[1] + 0.5);
      return;
    }
    const p0 = i === 0 ? p1 : this._at(i - 1);
    const p3 = last ? p2 : this._at(i + 2);
    for (let t = 0.2; t < 1; t += 0.2) {
      const pt = catmullRom(p0, p1, p2, p3, t);
      path.lineTo(pt[0] + 0.5, pt[1] + 0.5);
    }
    path.lineTo(p2[0] + 0.5, p2[1] + 0.5);
  }

  push(p, type) {
    const last = this._run.length ? this._run[this._run.length - 1] : null;
    const dx = last ? p[0] - last[0] : 0;
    const dy = last ? p[1] - last[1] : 0;
    if (!last || type !== this._runType || dx * dx + dy * dy > TRAIL_BREAK_SQ) {
      this.finish();
      this._run = [p];
      this._runLen = 1;
      this._runType = type;
      const path = this._path(type);
      if (path) path.moveTo(p[0] + 0.5, p[1] + 0.5);
      return;
    }
    this._run.push(p);
    if (this._run.length > 4) this._run.shift();
    this._runLen++;
    // With this point as its p3, the segment ending one point back is final.
    if (this._runLen >= 3) this._segment(this._path(type), this._runLen - 3, false);
  }

  /** Close the open run: its last segment moves from `tail` into the retained path. */
  finish() {
    if (this._runLen >= 2) this._segment(this._path(this._runType), this._runLen - 2, true);
    this._run = [];
    this._runLen = 0;
    this.tail = null;
  }

  refreshTail() {
    this.tail = null;
    if (this._runLen < 2) return;
    const tail = this._newPath();
    if (!tail) return;
    const from = this._at(this._runLen - 2);
    tail.moveTo(from[0] + 0.5, from[1] + 0.5);
    this._segment(tail, this._runLen - 2, true);
    this.tail = tail;
    this.tailType = this._runType;
  }
}

/**
 * Rasterise `occupancy` + `rooms_grid` into RGBA, one texel per cell. Mirrors the
 * server's classifier: room colour when the cell has a room AND (sub-type 0 OR
 * occupancy free/cleaned), else occupancy alone (0 unknown/transparent, 1 wall,
 * 2/3 floor); sub-type is bits 2-3 of the occupancy byte. NO FLIP HERE.
 */
export function buildGridImageData(state, palette, isDark) {
  const pal = palette || DEFAULT_PALETTE;
  const width = state && state.width > 0 ? Math.floor(state.width) : 0;
  const height = state && state.height > 0 ? Math.floor(state.height) : 0;
  const data = new Uint8ClampedArray(width * height * 4);
  if (!width || !height) return { data, width, height };

  const occ = state.occupancy || EMPTY;
  const rooms = state.rooms_grid || EMPTY;
  const hues = pal.rooms && pal.rooms.length ? pal.rooms : ROOM_PALETTE;
  const wall = themeColor(pal.wall, isDark);
  const floor = themeColor(pal.floor, isDark);
  const cleaned = themeColor(pal.cleaned, isDark);
  const unknown = pal.unknown || [0, 0, 0, 0];

  const cells = width * height;
  for (let i = 0, o = 0; i < cells; i++, o += 4) {
    const cell = occ[i] || 0;
    const pv = cell & 3;
    const subType = (cell >> 2) & 3;
    const stored = rooms[i] || 0; // stored, not real: real id 0 is stored as 1
    let c;

    if (stored > 0 && (subType === 0 || pv === 2 || pv === 3)) {
      c = hues[(stored - 1) % hues.length];
    } else if (pv === 1) {
      c = wall;
    } else if (pv === 2) {
      c = floor;
    } else if (pv === 3) {
      c = cleaned;
    } else {
      c = unknown;
    }

    data[o] = c[0];
    data[o + 1] = c[1];
    data[o + 2] = c[2];
    data[o + 3] = c.length > 3 ? c[3] : 255;
  }
  return { data, width, height };
}

export class EufyMapRenderer {
  /**
   * @param {{palette?:object, theme?:object, isDark?:boolean,
   *          bindInput?:boolean, onViewChange?:()=>void,
   *          onRoomTap?:(id:number, cell:{col:number,row:number})=>void}} [options]
   * `bindInput: false` leaves pointer/wheel listeners unbound; the host then drives
   * `panBy`/`zoomBy`/`resetView` (the card's overlay already gets every event).
   */
  constructor(canvas, options = {}) {
    this.canvas = canvas || null;
    this.ctx = null;
    try {
      this.ctx = this.canvas && this.canvas.getContext ? this.canvas.getContext("2d") : null;
    } catch (_) {
      this.ctx = null; // jsdom and headless hosts have no 2d context; stay a no-op
    }

    this.state = null;
    this.palette = options.palette || DEFAULT_PALETTE;
    this.theme = Object.assign({}, DEFAULT_THEME, options.theme || {});
    this.isDark = !!options.isDark;
    this.onRoomTap = typeof options.onRoomTap === "function" ? options.onRoomTap : null;

    // transform.x/.y are CSS pixels; .y is the screen y of grid ROW 0, i.e. the
    // bottom of the drawn map, because the draw transform flips vertically.
    this.transform = { x: 0, y: 0, scale: 1 };
    // Last `fit()`/`fitExact()`: reset target, zoom-out floor, `isOffFit()` baseline.
    this._fitTransform = null;
    this._viewBox = null; // {width, height} of the box the current view was laid out for
    this._viewAnim = null;
    this.onViewChange = typeof options.onViewChange === "function" ? options.onViewChange : null;

    this._staticRooms = null; // floor + room fills, Scale2x-upscaled
    this._staticWalls = null; // walls + void, drawn over the trail with a shadow
    this._staticRevision = null;
    this._trail = null; // SplineTrail of the live run
    this._trailPoints = [];
    this._trailTypes = [];
    this._roomPolygons = null;
    this._roomsSig = "";
    this._dpr = 1;
    this._raf = 0;
    this._paused = false; // host detached: no frames until `resume()`
    this._pointers = new Map();
    this._drag = null;
    this._pinchDist = 0;
    // With reduced motion the renderer draws strictly on data change.
    this._animate = !prefersReducedMotion();
    this._off = [];
    if (options.bindInput !== false) this._bind();
  }

  destroy() {
    if (this._raf && typeof cancelAnimationFrame === "function") cancelAnimationFrame(this._raf);
    this._raf = 0;
    for (const off of this._off) {
      try { off(); } catch (_) { /* element already gone */ }
    }
    this._off = [];
    this._viewAnim = null;
    this._staticRooms = null;
    this._staticWalls = null;
    this._trail = null;
    this._trailPoints = [];
    this._trailTypes = [];
    this._roomPolygons = null;
    this._prevTrailPath = null;
    this._prevTrailLen = 0;
    this.state = null;
  }

  setTheme(theme, isDark) {
    this.theme = Object.assign({}, DEFAULT_THEME, theme || {});
    if (isDark !== undefined) this.isDark = !!isDark;
    // Grid colours are baked into the static layer, so it must be re-rasterised.
    this._staticRevision = null;
    if (this.state) this._buildStatic();
    this.requestRender();
  }

  /** Adopt a decoded payload; the static grid rebuilds ONLY when `revision` changes. */
  setGeometry(geometry) {
    if (!geometry || !geometry.width || !geometry.height) return;
    const first = this.state === null;
    this.state = geometry;
    if (geometry.revision !== this._staticRevision) this._buildStatic();
    // 0x65 ROOM channel outlines (legacy only), already in the same cell frame.
    this._roomPolygons = this._buildRoomOutlines(geometry.room_polygons);
    // AFTER resetTrail, which clears the previous run: the snapshot's prev_trail wins.
    this.resetTrail(geometry.trail || [], geometry.trail_types || []);
    this._buildPrevTrail(geometry.prev_trail || []);
    if (first) this.fit();
    this.requestRender();
  }

  /** `{robot?: [col,row]|null, dock?: [col,row]|null}`; omitted keys keep their value. */
  setPose(pose) {
    if (!this.state || !pose) return;
    if (pose.robot !== undefined) {
      // `robot: null` is a real event (pose cleared at session start); guard indexing.
      if (pose.robot && this.state.robot) {
        const dx = pose.robot[0] - this.state.robot[0];
        const dy = pose.robot[1] - this.state.robot[1];
        if (Math.abs(dx) > 0.1 || Math.abs(dy) > 0.1) {
          this._robotDx = dx;
          this._robotDy = dy;
        }
      }
      this.state.robot = pose.robot;
    }
    if (pose.dock !== undefined) this.state.dock = pose.dock;
    this.requestRender();
  }

  /** @param {Array<{id: number, name: string}>} rooms  Redraws only when an id or name changes. */
  setRooms(rooms) {
    const list = rooms || [];
    const sig = list.map((r) => `${r && r.id}\u0000${r && r.name}`).join("\u0001");
    this._rooms = list;
    if (sig === this._roomsSig) return;
    this._roomsSig = sig;
    this.requestRender();
  }

  /** Append trail points; the spline grows by the new segments only. */
  appendTrail(points, types) {
    if (!this.state || !points || !points.length) return;
    if (!this._trail) this._trail = new SplineTrail(() => this._newPath());
    let last = null;
    for (let i = 0; i < points.length; i++) {
      const p = points[i];
      if (!p || p.length < 2) continue;
      const pt = [p[0], p[1]];
      // Types ride in lockstep; a missing or short array means "all cleaning".
      const type = Array.isArray(types) && i < types.length ? types[i] : 0;
      this._trailPoints.push(pt);
      this._trailTypes.push(type);
      this._trail.push(pt, type);
      last = p;
    }
    this._trail.refreshTail();
    // Advance the dot to the trail head: trail (0x67) runs ahead of pose (0x6c), so the
    // dot would otherwise lag the line. `setPose` overrides on the next real pose.
    if (last) {
      if (this.state.robot) {
        const dx = last[0] - this.state.robot[0];
        const dy = last[1] - this.state.robot[1];
        if (Math.abs(dx) > 0.1 || Math.abs(dy) > 0.1) {
          this._robotDx = dx;
          this._robotDy = dy;
        }
      }
      this.state.robot = [last[0], last[1]];
    }
    this.requestRender();
  }

  /** Rebuild the path from scratch (new session); the previous run goes with it. */
  resetTrail(points, types) {
    this._buildPrevTrail([]);
    this._trail = new SplineTrail(() => this._newPath());
    this._trailPoints = [];
    this._trailTypes = [];
    if (points && points.length) this.appendTrail(points, types);
    else this.requestRender();
  }

  /** Backing store to the CSS box * dpr. The host keeps the box out of the bitmap's
   * influence (the card sets the canvas' CSS `aspect-ratio`): with `height: auto` alone the
   * rounded bitmap would size the box, and every resize would move it by a pixel. */
  resize() {
    if (!this.canvas || !this.ctx || !this.canvas.getBoundingClientRect) return;
    const rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    this._dpr = Math.min(globalThis.devicePixelRatio || 1, MAX_DPR);
    const w = Math.max(1, Math.round(rect.width * this._dpr));
    const h = Math.max(1, Math.round(rect.height * this._dpr));
    // Assigning a size clears the bitmap even when it is unchanged.
    if (this.canvas.width !== w) this.canvas.width = w;
    if (this.canvas.height !== h) this.canvas.height = h;
    this.requestRender();
  }

  _rect() {
    if (!this.canvas || !this.canvas.getBoundingClientRect) return null;
    const rect = this.canvas.getBoundingClientRect();
    return rect && rect.width && rect.height ? rect : null;
  }

  /** Adopt a fit transform: it becomes the reset target AND the zoom-out floor. */
  _setFit(t) {
    this._fitTransform = { x: t.x, y: t.y, scale: t.scale };
    this.transform = { x: t.x, y: t.y, scale: t.scale };
    this._viewAnim = null;
    this._emitView();
    this.requestRender();
  }

  _emitView() {
    if (!this.onViewChange) return;
    try {
      this.onViewChange();
    } catch (_) {
      /* a throwing host must not take the renderer down */
    }
  }

  /** Lowest scale a zoom may reach: the fit scale. Never snaps the view UP. */
  _minScale() {
    const floor = this._fitTransform
      ? Math.max(MIN_SCALE, this._fitTransform.scale)
      : MIN_SCALE;
    return Math.min(floor, this.transform.scale);
  }

  /** Scale and centre the whole grid inside the canvas, with a 4% margin. */
  fit() {
    if (!this.state) return;
    const rect = this._rect();
    if (!rect) return;
    this._viewBox = { width: rect.width, height: rect.height };
    const { width: w, height: h } = this.state;
    const scale = clamp(Math.min(rect.width / w, rect.height / h) * 0.96, MIN_SCALE, MAX_SCALE);
    this._setFit({
      x: (rect.width - w * scale) / 2,
      // Bottom edge of the map: grid row 0 sits here and rows grow upwards.
      y: (rect.height + h * scale) / 2,
      scale,
    });
  }

  /** Fill the box EDGE TO EDGE — no inset, no centring. The framing the card uses. */
  fitExact() {
    if (!this.state) return;
    const rect = this._rect();
    if (!rect) return;
    // Not clamped to MAX_SCALE: MAX_SCALE bounds only what the USER may zoom to.
    const scale = Math.max(rect.width / this.state.width, MIN_SCALE);
    this._viewBox = { width: rect.width, height: rect.height };
    this._setFit({ x: 0, y: rect.height, scale });
  }

  isOffFit() {
    const f = this._fitTransform;
    const t = this.transform;
    if (!f) return false;
    return (
      Math.abs(t.scale - f.scale) > f.scale * 1e-3 ||
      Math.abs(t.x - f.x) > 0.5 ||
      Math.abs(t.y - f.y) > 0.5
    );
  }

  /** Refit a new box size while KEEPING the user's view: a reflow must not undo a zoom. The
   * centre is read in the box the view was laid out for: the box has already changed. */
  refit() {
    const prev = this._fitTransform;
    const wasOff = this.isOffFit();
    const box = this._viewBox || this._rect();
    const centre = wasOff && box ? this.normalizedAtPoint(box.width / 2, box.height / 2) : null;
    const ratio = wasOff && prev ? this.transform.scale / prev.scale : 1;
    this.fitExact();
    if (!wasOff || !centre || !this._fitTransform) return;
    const rect = this._rect();
    if (!rect) return;
    this.transform.scale = clamp(this._fitTransform.scale * ratio, this._minScale(), MAX_SCALE);
    const cell = normalizedToCell(this.state, centre.nx, centre.ny);
    this.transform.x = rect.width / 2 - cell.col * this.transform.scale;
    this.transform.y = rect.height / 2 + cell.row * this.transform.scale;
    this._clampPan();
    this._emitView();
    this.requestRender();
  }

  resetView(animate = true) {
    const to = this._fitTransform;
    if (!to) {
      this.fitExact();
      return;
    }
    if (!animate || !this._animate || typeof requestAnimationFrame !== "function") {
      this._setFit(to);
      return;
    }
    this._viewAnim = {
      from: { x: this.transform.x, y: this.transform.y, scale: this.transform.scale },
      to: { x: to.x, y: to.y, scale: to.scale },
      t0: Date.now(),
    };
    this.requestRender();
  }

  _stepViewAnim() {
    const a = this._viewAnim;
    if (!a) return false;
    const k = clamp((Date.now() - a.t0) / VIEW_ANIM_MS, 0, 1);
    const e = 1 - (1 - k) * (1 - k); // ease-out quad
    this.transform.x = a.from.x + (a.to.x - a.from.x) * e;
    this.transform.y = a.from.y + (a.to.y - a.from.y) * e;
    this.transform.scale = a.from.scale + (a.to.scale - a.from.scale) * e;
    this._emitView();
    if (k >= 1) {
      this._viewAnim = null;
      return false;
    }
    return true;
  }

  /** Keep a sliver of the map on screen; otherwise a pan can lose it entirely. */
  _clampPan() {
    if (!this.state) return;
    const rect = this._rect();
    if (!rect) return;
    const t = this.transform;
    const mw = this.state.width * t.scale;
    const mh = this.state.height * t.scale;
    const keepX = Math.min(MIN_VISIBLE_PX, mw / 2, rect.width / 2);
    const keepY = Math.min(MIN_VISIBLE_PX, mh / 2, rect.height / 2);
    t.x = clamp(t.x, keepX - mw, rect.width - keepX);
    // Vertical: row 0 sits at t.y and rows grow UPWARDS, so the map spans [t.y - mh, t.y].
    t.y = clamp(t.y, keepY, rect.height - keepY + mh);
  }

  panBy(dx, dy) {
    if (!this.state) return;
    this._viewAnim = null;
    this.transform.x += dx;
    this.transform.y += dy;
    this._clampPan();
    this._emitView();
    this.requestRender();
  }

  panTo(x, y) {
    if (!this.state) return;
    this._viewAnim = null;
    this.transform.x = x;
    this.transform.y = y;
    this._clampPan();
    this._emitView();
    this.requestRender();
  }

  zoomBy(factor, clientX, clientY) {
    if (!this.state) return;
    const rect = this._rect();
    if (!rect) return;
    this._viewAnim = null;
    const lo = this._minScale();
    // `Math.max(MAX_SCALE, lo)`: a fit above MAX_SCALE must not invert the clamp.
    const next = clamp(this.transform.scale * factor, lo, Math.max(MAX_SCALE, lo));
    const f = next / this.transform.scale;
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    // Anchor at the pointer; screen-space maths, so the flipped axis needs no case.
    this.transform.x = x - (x - this.transform.x) * f;
    this.transform.y = y - (y - this.transform.y) * f;
    this.transform.scale = next;
    this._clampPan();
    this._emitView();
    this.requestRender();
  }

  cellAt(clientX, clientY) {
    const rect = this._rect();
    if (!this.state || !rect) return null;
    return cellFromEvent(this.state, this.transform, clientX, clientY, rect);
  }

  /** @returns {number|null} real room id under the point — 0 is a valid answer. */
  roomAt(clientX, clientY) {
    const cell = this.cellAt(clientX, clientY);
    if (!cell) return null;
    return roomIdAt(this.state, cell.col, cell.row);
  }

  /** Canvas-local CSS pixel -> WHOLE-MAP normalized (0-1). Unclamped. */
  normalizedAtPoint(x, y) {
    if (!this.state || !this.transform.scale) return null;
    const c = cellFromPoint(this.transform, x, y);
    return cellToNormalized(this.state, c.col, c.row);
  }

  /** Client (viewport) coordinates -> whole-map normalized (0-1). */
  normalizedAt(clientX, clientY) {
    const rect = this._rect();
    if (!rect) return null;
    return this.normalizedAtPoint(clientX - rect.left, clientY - rect.top);
  }

  /** Whole-map normalized -> canvas-local CSS px; the only overlay positioner. */
  pointForNormalized(nx, ny) {
    if (!this.state || !this.transform.scale) return null;
    const c = normalizedToCell(this.state, nx, ny);
    if (!c) return null;
    return pointFromCell(this.transform, c.col, c.row);
  }

  requestRender() {
    if (!this.ctx || !this.state || this._raf || this._paused) return;
    const schedule = typeof requestAnimationFrame === "function"
      ? requestAnimationFrame
      : (fn) => setTimeout(fn, 16);
    this._raf = schedule(() => {
      this._raf = 0;
      // The tween rides the same coalescing guard, so frames cannot stack.
      const animating = this._stepViewAnim();
      this.render();
      // Tween and pulse halo are the only self-driven motion; a parked robot has no halo.
      if (animating || this._pulsing()) this.requestRender();
    });
  }

  /** The halo animates only while a robot marker is drawn (not parked) and motion is allowed. */
  _pulsing() {
    if (!this._animate || !this.state) return false;
    const robot = this._robotPosition();
    return !!robot && !this._robotIsParked(robot);
  }

  /** Stop self-driven frames (card detached); data changes and `resume()` draw again. */
  pause() {
    if (this._raf && typeof cancelAnimationFrame === "function") cancelAnimationFrame(this._raf);
    this._raf = 0;
    this._paused = true;
  }

  resume() {
    if (!this._paused) return;
    this._paused = false;
    this.requestRender();
  }

  render() {
    const ctx = this.ctx;
    const st = this.state;
    if (!ctx || !st) return;
    const d = this._dpr;
    const t = this.transform;

    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);

    // THE FLIP, applied exactly once to everything below: the negative vertical scale
    // puts grid row 0 at `t.y` and grows rows upwards, for grid, dock, robot and trail.
    ctx.setTransform(t.scale * d, 0, 0, -t.scale * d, t.x * d, t.y * d);

    if (this._staticRooms) {
      ctx.imageSmoothingEnabled = true; // bilinear on the Scale2x-upscaled layers
      ctx.drawImage(this._staticRooms, 0, 0, st.width, st.height); 
      this._drawRoomOutlines(ctx);
      
      ctx.save();
      this._drawPrevTrail(ctx);
      this._drawTrail(ctx);
      ctx.restore();
      
      if (this._staticWalls) {
        ctx.save();
        // Wall drop shadow. Shadows are in bitmap px, untouched by the transform (and its
        // flip), so they scale with the dpr only and a positive Y falls down the screen.
        ctx.shadowColor = "rgba(0, 0, 0, 0.4)";
        ctx.shadowBlur = 10 * d;
        ctx.shadowOffsetX = 3 * d;
        ctx.shadowOffsetY = 3 * d;
        
        ctx.drawImage(this._staticWalls, 0, 0, st.width, st.height);
        ctx.restore();
      }
      
      this._drawRoomLabels(ctx);
    } else {
      this._drawPrevTrail(ctx);
      this._drawTrail(ctx);
    }
    this._drawVectors(ctx);
    this._drawDock(ctx);
    this._drawRobot(ctx);

    ctx.setTransform(1, 0, 0, 1, 0, 0);
  }

  _drawRoomLabels(ctx) {
    if (!this._rooms || !this._rooms.length || !this._roomCentroids) return;
    const s = this.transform.scale;
    
    const fontSize = Math.max(11, Math.min(18, 9 + s * 1.5));
    
    for (const room of this._rooms) {
      const cent = this._roomCentroids[room.id];
      if (!cent) continue;
      
      ctx.save();
      ctx.translate(cent.x + 0.5, cent.y + 0.5);
      ctx.scale(1 / s, -1 / s);
      
      ctx.font = `800 ${fontSize}px sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(0, 0, 0, 0.75)";
      ctx.lineJoin = "round";
      ctx.strokeText(room.name, 0, 0);
      
      ctx.fillStyle = "#ffffff";
      ctx.fillText(room.name, 0, 0);
      
      ctx.restore();
    }
  }

  _drawVectors(ctx) {
    const st = this.state;
    const s = this.transform.scale;
    const poly = (pts, fill, edge) => {
      if (!pts || pts.length < 2) return;
      ctx.beginPath();
      pts.forEach((p, i) => {
        const c = worldToCell(st, p[0], p[1]);
        if (i === 0) ctx.moveTo(c.col, c.row);
        else ctx.lineTo(c.col, c.row);
      });
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.strokeStyle = edge;
      ctx.lineWidth = 1.5 / s;
      ctx.stroke();
    };
    (st.forbidden_zones || []).forEach((z) => poly(z, this.theme.forbiddenZone, this.theme.forbiddenZoneEdge));
    (st.ban_mop_zones || []).forEach((z) => poly(z, this.theme.banMopZone, this.theme.banMopZoneEdge));
    const walls = st.virtual_walls || [];
    if (walls.length) {
      ctx.beginPath();
      for (const w of walls) {
        if (!w || w.length < 2) continue;
        const a = worldToCell(st, w[0][0], w[0][1]);
        const b = worldToCell(st, w[1][0], w[1][1]);
        ctx.moveTo(a.col, a.row);
        ctx.lineTo(b.col, b.row);
      }
      ctx.strokeStyle = this.theme.virtualWall;
      ctx.lineWidth = 2 / s;
      ctx.stroke();
    }
  }

  _buildPrevTrail(points) {
    this._prevTrailPath = null;
    this._prevTrailLen = 0;
    if (!points || points.length < 2) return;
    const trail = new SplineTrail(() => this._newPath());
    for (const p of points) if (p && p.length >= 2) trail.push([p[0], p[1]], TRAIL_TYPE_CLEAN);
    trail.finish();
    this._prevTrailPath = trail.paths[TRAIL_TYPE_CLEAN];
    this._prevTrailLen = points.length;
  }

  /** Previous run draws ONLY when the live slot is empty (same colour would tangle). */
  _shouldDrawPrevTrail() {
    return this._trailPoints.length === 0;
  }

  _drawPrevTrail(ctx) {
    if (!this._prevTrailPath || this._prevTrailLen < 2) return;
    if (!this._shouldDrawPrevTrail()) return;
    ctx.save();
    ctx.strokeStyle = this.theme.trail;
    ctx.lineWidth = TRAIL_PX / this.transform.scale;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    
    ctx.shadowColor = this.theme.trail;
    ctx.shadowBlur = 4 * this._dpr; // bitmap px, see render()
    ctx.shadowOffsetX = 0;
    ctx.shadowOffsetY = 0;

    ctx.stroke(this._prevTrailPath);
    ctx.restore();
  }

  /**
   * One retained Path2D of every room's outline ring, from the device's own vectors.
   * Does NOT replace the grid fill: a ring has no furniture voids. Null if none.
   */
  _buildRoomOutlines(polygons) {
    if (!polygons) return null;
    const ids = Object.keys(polygons);
    if (!ids.length) return null;
    const path = this._newPath();
    if (!path) return null;
    let any = false;
    for (const id of ids) {
      const ring = polygons[id];
      if (!Array.isArray(ring) || ring.length < 3) continue;
      path.moveTo(ring[0][0] + 0.5, ring[0][1] + 0.5);
      for (let i = 1; i < ring.length; i++) path.lineTo(ring[i][0] + 0.5, ring[i][1] + 0.5);
      path.closePath();
      any = true;
    }
    return any ? path : null;
  }

  _currentTrailType() {
    const types = this._trailTypes;
    return types && types.length ? types[types.length - 1] : TRAIL_TYPE_CLEAN;
  }

  _drawRoomOutlines(ctx) {
    if (!this._roomPolygons) return;
    ctx.save();
    ctx.strokeStyle = this.theme.roomOutline;
    ctx.lineWidth = ROOM_OUTLINE_PX / this.transform.scale;
    ctx.lineJoin = "round";
    ctx.stroke(this._roomPolygons);
    ctx.restore();
  }

  _drawTrail(ctx) {
    const trail = this._trail;
    if (!trail || this._trailPoints.length < 2) return;
    const clean = trail.paths[TRAIL_TYPE_CLEAN];
    const transit = trail.paths[TRAIL_TYPE_TRANSIT];
    ctx.save();
    ctx.strokeStyle = this.theme.trail;
    ctx.lineWidth = TRAIL_PX / this.transform.scale;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    
    ctx.shadowColor = this.theme.trail;
    ctx.shadowBlur = 4 * this._dpr; // bitmap px, see render()
    ctx.shadowOffsetX = 0;
    ctx.shadowOffsetY = 0;

    // One stroke per retained path: per-segment strokes darken every overlap of a
    // translucent trail. The open run's last segment (`tail`) is the only extra stroke.
    if (clean) ctx.stroke(clean);
    if (trail.tail && trail.tailType === TRAIL_TYPE_CLEAN) ctx.stroke(trail.tail);

    // Transit legs are DASHED: the robot drove there, it did not clean there.
    if (transit || (trail.tail && trail.tailType === TRAIL_TYPE_TRANSIT)) {
      const s = this.transform.scale;
      ctx.setLineDash([TRAIL_DASH_ON / s, TRAIL_DASH_OFF / s]);
      if (transit) ctx.stroke(transit);
      if (trail.tail && trail.tailType === TRAIL_TYPE_TRANSIT) ctx.stroke(trail.tail);
      ctx.setLineDash([]);
    }
    ctx.restore();
  }

  _drawDock(ctx) {
    if (!PATH_HOME) {
      PATH_HOME = makeIconPath(MDI_HOME);
      PATH_HOME_LIGHTNING_BOLT = makeIconPath(MDI_HOME_LIGHTNING_BOLT);
    }
    const dock = this.state.dock;
    if (!dock) return; // null until the novel/MQTT path captures one from a pose
    const s = this.transform.scale;
    const iconSizePx = Math.max(36, 6 * s);
    const scale = iconSizePx / 24;
    
    ctx.save();
    ctx.translate(dock[0] + 0.5, dock[1] + 0.5);
    ctx.scale(scale / s, -scale / s);
    ctx.translate(-12, -12); // MDI viewBox is 24x24
    
    const isDocked = this._robotIsParked(this._robotPosition());
    const isCharging = this._isCharging || false;

    const path = (isDocked && isCharging) ? PATH_HOME_LIGHTNING_BOLT : PATH_HOME;
    const color = isDocked ? this.theme.dock : "rgba(128, 128, 128, 0.7)";

    ctx.shadowColor = "rgba(255, 255, 255, 1)";
    ctx.shadowBlur = 5;
    ctx.strokeStyle = "rgba(255, 255, 255, 0.9)";
    ctx.lineWidth = 1.5;
    ctx.stroke(path);

    ctx.fillStyle = color;
    ctx.fill(path);
    ctx.restore();
  }

  setDockStatus(isDocked, isCharging) {
    if (this._isDocked !== isDocked || this._isCharging !== isCharging) {
      this._isDocked = isDocked;
      this._isCharging = isCharging;
      this.requestRender();
    }
  }

  /**
   * Newest pose, else the live trail head, else the last known cell — a pose may be
   * null and the stream goes quiet when stopped, so the marker must not blink out.
   */
  _robotPosition() {
    let robot = this.state && this.state.robot;
    if (!robot && this._trailPoints && this._trailPoints.length > 0) {
      robot = this._trailPoints[this._trailPoints.length - 1];
    }
    if (!robot) return this._lastRobot || null;
    this._lastRobot = robot;
    return robot;
  }

  /**
   * Is the robot parked? The one rule both icons use. HA's `setDockStatus` is
   * authoritative; the proximity test is a tight fallback, so a transit leg near the
   * dock cannot hide the robot marker.
   */
  _robotIsParked(robot) {
    if (this._isDocked !== undefined) return !!this._isDocked;
    const dock = this.state && this.state.dock;
    if (!dock || !robot) return false;
    return Math.hypot(robot[0] - dock[0], robot[1] - dock[1]) < DOCK_PARKED_CELLS;
  }

  _drawRobot(ctx) {
    if (!PATH_ROBOT) {
      PATH_ROBOT = makeIconPath(MDI_ROBOT);
      PATH_NAVIGATE = makeIconPath(MDI_NAVIGATE);
    }
    const robot = this._robotPosition();
    if (!robot) return;

    // Parked: the dock icon already stands for the robot, so don't stack two.
    if (this._robotIsParked(robot)) return;

    // The newest trail point carries the current activity; the pose carries no type.
    const transit = this._currentTrailType() === TRAIL_TYPE_TRANSIT;
    const icon = transit ? PATH_NAVIGATE : PATH_ROBOT;
    const bodyColour = this.theme.robot;
    const ringColour = this.theme.robotRing;

    const s = this.transform.scale;
    const x = robot[0] + 0.5;
    const y = robot[1] + 0.5;
    const iconSizePx = Math.max(36, 6 * s);
    
    if (this._animate) {
      const phase = (Date.now() % 1600) / 1600;
      ctx.beginPath();
      const radius = iconSizePx * 0.55;
      ctx.arc(x, y, (radius + phase * radius * 0.8) / s, 0, Math.PI * 2);
      ctx.fillStyle = ringColour;
      ctx.globalAlpha = 1 - phase;
      ctx.fill();
      ctx.globalAlpha = 1;
    }
    
    ctx.save();
    ctx.translate(x, y);
    const scale = iconSizePx / 24;
    ctx.scale(scale / s, -scale / s);
    
    // Face the direction of movement. The two icon paths face OPPOSITE ways in their
    // own 24x24 boxes, so the arrow takes an extra half turn and the vacuum does not.
    if (this._robotDx !== undefined && this._robotDy !== undefined) {
      const angle = Math.atan2(-this._robotDy, this._robotDx);
      ctx.rotate(angle - Math.PI / 2 + (transit ? Math.PI : 0));
    }
    
    ctx.translate(-12, -12);
    
    ctx.shadowColor = "rgba(255, 255, 255, 1)";
    ctx.shadowBlur = 5;
    ctx.strokeStyle = "rgba(255, 255, 255, 0.9)";
    ctx.lineWidth = 1.5;
    ctx.stroke(icon);

    ctx.fillStyle = bodyColour;
    ctx.fill(icon);
    ctx.restore();
  }

  _buildStatic() {
    this._staticRooms = null;
    this._staticWalls = null;
    this._staticRevision = null;
    this._roomCentroids = null;
    const st = this.state;
    if (!st) return;
    const img = buildGridImageData(st, this.palette, this.isDark);
    if (!img.width || !img.height) return;
    this._staticRevision = st.revision;
    
    if (st.rooms_grid) {
      const counts = {}, sumX = {}, sumY = {};
      const width = img.width, height = img.height;
      for (let r = 0; r < height; r++) {
        for (let c = 0; c < width; c++) {
          const id = st.rooms_grid[r * width + c];
          if (id > 0) {
            const realId = id - 1;
            counts[realId] = (counts[realId] || 0) + 1;
            sumX[realId] = (sumX[realId] || 0) + c;
            sumY[realId] = (sumY[realId] || 0) + r;
          }
        }
      }
      this._roomCentroids = {};
      for (const id in counts) {
        this._roomCentroids[id] = { x: sumX[id] / counts[id], y: sumY[id] / counts[id] };
      }
    }

    const width = img.width;
    const height = img.height;
    const occ = st.occupancy || EMPTY;
    const rooms = st.rooms_grid || EMPTY;
    
    const dataRooms = new Uint8ClampedArray(width * height * 4);
    const dataWalls = new Uint8ClampedArray(width * height * 4);
    
    for (let i = 0, o = 0; i < width * height; i++, o += 4) {
      const pv = occ[i] & 3;
      if (pv === 0 || pv === 1) { // Unknown or Wall
        dataWalls[o] = img.data[o];
        dataWalls[o+1] = img.data[o+1];
        dataWalls[o+2] = img.data[o+2];
        dataWalls[o+3] = img.data[o+3];
      } else { // Room or Floor
        dataRooms[o] = img.data[o];
        dataRooms[o+1] = img.data[o+1];
        dataRooms[o+2] = img.data[o+2];
        dataRooms[o+3] = img.data[o+3];
      }
    }

    // Scale2x smooths the jagged 5 cm grid into vector-like edges: two passes (4x) within
    // the pixel budget, fewer on a large grid.
    let rooms32 = new Uint32Array(dataRooms.buffer);
    let walls32 = new Uint32Array(dataWalls.buffer);
    let currentW = width;
    let currentH = height;
    const passes = staticUpscalePasses(width, height);

    for (let i = 0; i < passes; i++) {
      const resR = scale2x(currentW, currentH, rooms32);
      const resW = scale2x(currentW, currentH, walls32);
      rooms32 = resR.data;
      walls32 = resW.data;
      currentW = resR.width;
      currentH = resR.height;
    }

    const cvRooms = createOffscreen(currentW, currentH);
    if (cvRooms && cvRooms.getContext) {
      // null when the browser refuses the canvas size: no static layer, no throw.
      const c = cvRooms.getContext("2d");
      if (c && c.createImageData) {
        const idata = c.createImageData(currentW, currentH);
        idata.data.set(new Uint8ClampedArray(rooms32.buffer));
        c.putImageData(idata, 0, 0);
        this._staticRooms = cvRooms;
      }
    }
    
    const cvWalls = createOffscreen(currentW, currentH);
    if (cvWalls && cvWalls.getContext) {
      const c = cvWalls.getContext("2d");
      if (c && c.createImageData) {
        const idata = c.createImageData(currentW, currentH);
        idata.data.set(new Uint8ClampedArray(walls32.buffer));
        c.putImageData(idata, 0, 0);
        this._staticWalls = cvWalls;
      }
    }
  }

  _newPath() {
    return typeof Path2D === "function" ? new Path2D() : null;
  }

  _bind() {
    const el = this.canvas;
    if (!el || !el.addEventListener) return;
    const on = (type, fn, opts) => {
      el.addEventListener(type, fn, opts);
      this._off.push(() => el.removeEventListener(type, fn, opts));
    };
    on("pointerdown", (e) => this._onDown(e));
    on("pointermove", (e) => this._onMove(e));
    on("pointerup", (e) => this._onUp(e));
    on("pointercancel", (e) => this._onUp(e));
    // Not passive: the page must not scroll while the map is being zoomed.
    on("wheel", (e) => this._onWheel(e), { passive: false });
    on("dblclick", () => this.resetView(true));
  }

  _onDown(e) {
    if (!this.state) return;
    if (this.canvas.setPointerCapture) {
      try { this.canvas.setPointerCapture(e.pointerId); } catch (_) { /* not capturable */ }
    }
    this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (this._pointers.size === 1) {
      this._drag = { x: e.clientX, y: e.clientY, tx: this.transform.x, ty: this.transform.y, moved: false };
    } else {
      this._drag = null;
      this._pinchDist = 0;
    }
  }

  _onMove(e) {
    if (!this.state || !this._pointers.has(e.pointerId)) return;
    this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (this._pointers.size >= 2) {
      const [a, b] = Array.from(this._pointers.values());
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      if (this._pinchDist) this.zoomBy(dist / this._pinchDist, (a.x + b.x) / 2, (a.y + b.y) / 2);
      this._pinchDist = dist;
      return;
    }
    if (!this._drag) return;
    const dx = e.clientX - this._drag.x;
    const dy = e.clientY - this._drag.y;
    if (Math.hypot(dx, dy) > TAP_SLOP_PX) this._drag.moved = true;
    this.panTo(this._drag.tx + dx, this._drag.ty + dy);
  }

  _onUp(e) {
    if (!this._pointers.has(e.pointerId)) return;
    this._pointers.delete(e.pointerId);
    if (this._pointers.size > 0) {
      this._pinchDist = 0;
      return;
    }
    const drag = this._drag;
    this._drag = null;
    this._pinchDist = 0;
    if (!drag || drag.moved || !this.onRoomTap) return;
    const cell = this.cellAt(e.clientX, e.clientY);
    if (!cell) return;
    const id = roomIdAt(this.state, cell.col, cell.row);
    // `id` may legitimately be 0 (a real room on legacy) — test against null.
    if (id !== null) this.onRoomTap(id, cell);
  }

  _onWheel(e) {
    if (!this.state) return;
    if (e.cancelable !== false && e.preventDefault) e.preventDefault();
    // Trackpad pinch arrives as ctrlKey+deltaY; both want the same response.
    this.zoomBy(Math.exp(-e.deltaY * 0.0015), e.clientX, e.clientY);
  }
}
