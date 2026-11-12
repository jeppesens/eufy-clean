/*
 * card-clientrender.test.mjs — the opt-in client-side map renderer path of eufy-clean-card.
 *
 * jsdom has no canvas and does no layout, so nothing here asserts pixels. What it asserts is
 * the WIRING and the FALLBACK, which is where this feature can fail silently:
 *
 *   - flag off  -> the PNG path is untouched and nothing is subscribed
 *   - flag on   -> exactly one subscription, a geometry snapshot on EVERY subscribe
 *   - a mismatched trail `from` re-fetches instead of splicing a bad run into the path
 *   - every failure trigger (import, command error, empty map) lands back on the <img>
 *   - the canvas fills its box EXACTLY (no fit() inset), which is what keeps the normalized
 *     SVG overlay in register with the map underneath it
 *   - the gestures: which finger means what in which mode, and — the one that fails silently
 *     — that a zone drawn zoomed describes the same floor as the same zone drawn at fit
 *
 * The renderer CLASS is stubbed: renderer.test.mjs covers its behaviour, and jsdom cannot
 * resolve a real dynamic import from a classic script anyway. Its PROJECTION, however, is not
 * stubbed — the stub calls the real module's exported `cellFromPoint`/`pointFromCell`/
 * `cellToNormalized`/`normalizedToCell`/`roomIdAt`. A second copy of that maths here would
 * make the coordinate assertions below test the copy instead of the thing they guard.
 */
import fs from "node:fs";
import { JSDOM } from "jsdom";
import { cardSource, CARD_MODULE_URL } from "./harness.mjs";

// The renderer lives outside any package.json, so node would treat its .js as CJS and reject
// `export`. Importing it as a data: URL evaluates it as a real ES module, exactly as a browser
// would; it has no imports of its own, so nothing needs resolving relative to its path.
const RENDERER_SRC = new URL(
  "../../custom_components/robovac_mqtt/frontend/eufy-map-renderer.js",
  import.meta.url
);
const rmod = await import(
  "data:text/javascript;base64," +
    Buffer.from(fs.readFileSync(RENDERER_SRC, "utf8"), "utf8").toString("base64")
);
const { cellFromPoint, pointFromCell, cellToNormalized, normalizedToCell, roomIdAt } = rmod;

const dom = new JSDOM(`<!doctype html><html><body></body></html>`, {
  runScripts: "dangerously",
  url: "https://localhost/",
  pretendToBeVisual: true,
});
const { window } = dom;
const { document } = window;
// jsdom has no DecompressionStream, and the card now pre-flights it before starting the
// client renderer — a browser without it can only fail, and failing would spend the
// one-shot `_crFailed`. The renderer itself is stubbed in this suite, so the capability
// is stubbed too; the pre-flight's own behaviour is asserted in section 12.
window.DecompressionStream = class DecompressionStream {};
const s = document.createElement("script");
s.textContent = cardSource();
document.body.appendChild(s);

let fail = 0;
const ok = (c, m) => {
  if (c) console.log("  ok:", m);
  else {
    console.error("  FAIL:", m);
    fail++;
  }
};
// Flush the card's async start chain (import -> subscribe -> geometry -> decode).
const settle = async (n = 6) => {
  for (let i = 0; i < n; i++) await new Promise((r) => setTimeout(r, 0));
};

// Fake timers for the card's resubscribe backoff: `body` gets `retry()` (the pending
// resubscribe timer of `card`, or undefined) and `fire(t)` (run it and settle).
async function withRetryTimers(body) {
  const realSet = window.setTimeout;
  const realClear = window.clearTimeout;
  let timers = [];
  window.setTimeout = (fn, ms) => {
    const t = { fn, ms, id: timers.length + 1000 };
    timers.push(t);
    return t.id;
  };
  window.clearTimeout = (id) => {
    timers = timers.filter((t) => t.id !== id);
  };
  const ctl = {
    card: null,
    retry: () => timers.find((t) => ctl.card && t.id === ctl.card._crRetryTimer),
    pending: (id) => timers.some((t) => t.id === id),
    fire: async (t) => {
      timers = timers.filter((x) => x !== t);
      t.fn();
      await settle();
    },
  };
  try {
    await body(ctl);
  } finally {
    window.setTimeout = realSet;
    window.clearTimeout = realClear;
  }
}

const Card = window.customElements.get("eufy-clean-card");

// ---- stubs -------------------------------------------------------------------------------

function makeConnection() {
  const conn = {
    sent: [], // every sendMessagePromise payload
    subs: [], // every subscribeMessage: {cb, msg, unsubbed}
    ready: [], // registered "ready" (reconnect) listeners
    geometry: null, // (msg) => Promise — defaulted below, overridden per test
    subscribeError: null,
    sendMessagePromise(msg) {
      conn.sent.push(msg);
      if (msg.type === "robovac_mqtt/map/geometry") {
        return conn.geometry ? conn.geometry(msg) : Promise.resolve(null);
      }
      return Promise.resolve(null);
    },
    subscribeMessage(cb, msg, opts) {
      if (conn.subscribeError) return Promise.reject(conn.subscribeError);
      const rec = { cb, msg, opts, unsubbed: 0 };
      conn.subs.push(rec);
      return Promise.resolve(() => {
        rec.unsubbed++;
      });
    },
    addEventListener(type, fn) {
      if (type === "ready") conn.ready.push(fn);
    },
    removeEventListener(type, fn) {
      if (type === "ready") conn.ready = conn.ready.filter((f) => f !== fn);
    },
    emitReady() {
      conn.ready.slice().forEach((f) => f());
    },
    emit(ev) {
      conn.subs.forEach((r) => r.cb(ev));
    },
    geomRequests() {
      return conn.sent.filter((m) => m.type === "robovac_mqtt/map/geometry");
    },
  };
  conn.geometry = async () => geom(11); // a healthy map unless a test says otherwise
  return conn;
}

function makeHass(conn) {
  return {
    connection: conn,
    themes: { darkMode: false },
    states: {
      "vacuum.robot": {
        state: "docked",
        attributes: {
          fan_speed_list: ["Quiet", "Standard"],
          rooms: [{ id: 0, name: "Hallway" }, { id: 1, name: "Kitchen" }],
          nogo_zones_supported: true,
        },
        last_updated: "t0",
      },
      "camera.robot_map": {
        state: "idle",
        attributes: { entity_picture: "/pic.png", map_revision: 7 },
        last_updated: "c0",
      },
    },
    entities: {
      "vacuum.robot": { device_id: "dev-vac", platform: "robovac_mqtt" },
      "camera.robot_map": { device_id: "dev-cam" },
    },
    _calls: [],
    callService(domain, service, data, target) {
      this._calls.push({ domain, service, data, target });
      if (domain === "robovac_mqtt" && service === "room_at_point") {
        return Promise.resolve({ response: { "vacuum.robot": { room_id: 1, room_name: "Kitchen" } } });
      }
      return Promise.resolve({});
    },
  };
}

// A geometry payload in the wire shape of docs/MAP_WS_CONTRACT.md. `occupancy` is left an
// opaque string (nothing here rasterises), but `rooms_grid` is REAL, already-inflated bytes
// so the room hit-test can be exercised geometrically at a non-identity transform.
//
// 4 wide x 3 tall, stored as `real_id + 1` so 0 can mean "no room". Grid row 0 draws at the
// BOTTOM (the renderer flips once, at draw time):
//
//   grid row 2 (drawn top)     0 0 0 0    no room
//   grid row 1                 1 1 2 2    room 0 | room 1
//   grid row 0 (drawn bottom)  1 1 2 2    room 0 | room 1
//
// Room id 0 is a REAL room on legacy maps, which is why it is the left half here and not a
// convenient "nothing".
const ROOMS_GRID = new Uint8Array([1, 1, 2, 2, 1, 1, 2, 2, 0, 0, 0, 0]);
const geom = (revision, trail = []) => ({
  v: 1,
  revision,
  width: 4,
  height: 3,
  origin_x: -100,
  origin_y: -50,
  resolution: 5,
  occupancy: "occ",
  rooms_grid: ROOMS_GRID,
  rooms: [{ id: 0, name: "Hallway" }, { id: 1, name: "Kitchen" }],
  virtual_walls: [],
  forbidden_zones: [],
  ban_mop_zones: [],
  dock: [1, 1],
  robot: [2, 2],
  trail,
  trail_seq: trail.length,
});

function makeRendererModule() {
  const calls = [];
  // A recording fake of EufyMapRenderer. The bookkeeping (which method the card called, and
  // when) is the point; the COORDINATE maths is delegated to the real module's exported pure
  // functions, so the projection asserted here is the projection that ships.
  class EufyMapRenderer {
    constructor(canvas, options) {
      this.canvas = canvas;
      this.options = options || {};
      this.state = null;
      this.transform = { x: 0, y: 0, scale: 1 };
      this._fit = null;
      this.fitCalls = 0;
      calls.push(["construct"]);
    }
    _rect() {
      return this.canvas && this.canvas.getBoundingClientRect
        ? this.canvas.getBoundingClientRect()
        : null;
    }
    _emit() {
      if (typeof this.options.onViewChange === "function") this.options.onViewChange();
    }
    setGeometry(g) {
      this.state = g;
      calls.push(["setGeometry", g && g.revision]);
    }
    setPose(p) {
      calls.push(["setPose", p]);
    }
    appendTrail(p) {
      calls.push(["appendTrail", (p || []).length]);
    }
    resetTrail(p) {
      calls.push(["resetTrail", (p || []).length]);
    }
    setTheme(theme, isDark) {
      calls.push(["setTheme", isDark, theme]);
    }
    setRooms(rooms) {
      calls.push(["setRooms", rooms && Object.keys(rooms).length]);
    }
    // The fake must implement `setDockStatus`; a missing method throws out of `set hass`.
    setDockStatus(isDocked, isCharging) {
      calls.push(["setDockStatus", isDocked, isCharging]);
    }
    pause() {
      calls.push(["pause"]);
    }
    resume() {
      calls.push(["resume"]);
    }
    fit() {
      this.fitCalls++;
      calls.push(["fit"]);
    }
    // Mirrors the real fitExact(): fill the box edge to edge, grid row 0 at the bottom.
    // renderer.test.mjs [19] pins those numbers on the real implementation.
    fitExact() {
      calls.push(["fitExact"]);
      const rect = this._rect();
      if (!this.state || !rect || !rect.width) return;
      this._fit = { x: 0, y: rect.height, scale: rect.width / this.state.width };
      this.transform = { ...this._fit };
      this._emit();
    }
    // Mirrors the real refit(): the box is unchanged here, so an off-fit view is kept.
    refit() {
      calls.push(["refit"]);
      if (!this.isOffFit()) this.fitExact();
    }
    resetView(animate) {
      calls.push(["resetView", animate]);
      if (!this._fit) return;
      this.transform = { ...this._fit };
      this._emit();
    }
    isOffFit() {
      const f = this._fit;
      const t = this.transform;
      if (!f) return false;
      return (
        Math.abs(t.scale - f.scale) > f.scale * 1e-3 ||
        Math.abs(t.x - f.x) > 0.5 ||
        Math.abs(t.y - f.y) > 0.5
      );
    }
    panBy(dx, dy) {
      calls.push(["panBy", dx, dy]);
      this.transform.x += dx;
      this.transform.y += dy;
      this._emit();
    }
    zoomBy(factor, clientX, clientY) {
      calls.push(["zoomBy", factor, clientX, clientY]);
      const rect = this._rect();
      if (!rect) return;
      const x = clientX - rect.left;
      const y = clientY - rect.top;
      this.transform.x = x - (x - this.transform.x) * factor;
      this.transform.y = y - (y - this.transform.y) * factor;
      this.transform.scale *= factor;
      this._emit();
    }
    cellAt(clientX, clientY) {
      const rect = this._rect();
      if (!this.state || !rect) return null;
      const c = cellFromPoint(this.transform, clientX - rect.left, clientY - rect.top);
      return { col: Math.floor(c.col), row: Math.floor(c.row) };
    }
    // `_room` is an explicit override used by the tests that only care that the card sends
    // the id through untouched (including id 0). Without it the real mask is consulted.
    roomAt(clientX, clientY) {
      if (this._room !== undefined) return this._room;
      const cell = this.cellAt(clientX, clientY);
      return cell ? roomIdAt(this.state, cell.col, cell.row) : null;
    }
    normalizedAt(clientX, clientY) {
      const rect = this._rect();
      if (!this.state || !rect) return null;
      const c = cellFromPoint(this.transform, clientX - rect.left, clientY - rect.top);
      return cellToNormalized(this.state, c.col, c.row);
    }
    pointForNormalized(nx, ny) {
      if (!this.state || !this.transform.scale) return null;
      const c = normalizedToCell(this.state, nx, ny);
      return c ? pointFromCell(this.transform, c.col, c.row) : null;
    }
    resize() {
      calls.push(["resize"]);
    }
    requestRender() {}
    destroy() {
      calls.push(["destroy"]);
    }
  }
  return {
    calls,
    mod: {
      EufyMapRenderer,
      // The real one inflates `occupancy`; the fixture's rooms_grid is already bytes.
      decodeGeometry: async (payload) => (payload ? Object.assign({}, payload) : null),
    },
  };
}

// --- pointer/wheel plumbing -----------------------------------------------------------------
// jsdom has no PointerEvent, and no layout: the overlay's own rect is all zeros, so every test
// that projects through it hands it the box a real browser would give it (the same 520x390
// .map-wrap box `mount()` gives the canvas).
const OVERLAY_RECT = { left: 0, top: 0, width: 520, height: 390, right: 520, bottom: 390 };
function layoutOverlay(card, rect = OVERLAY_RECT) {
  card._els.overlay.getBoundingClientRect = () => rect;
}
function ptrEvent(type, id, x, y) {
  const e = new window.Event(type, { bubbles: true, cancelable: true });
  e.pointerId = id;
  e.clientX = x;
  e.clientY = y;
  return e;
}
const down = (card, id, x, y) => card._els.overlay.dispatchEvent(ptrEvent("pointerdown", id, x, y));
const move = (card, id, x, y) => card._els.overlay.dispatchEvent(ptrEvent("pointermove", id, x, y));
const up = (card, id, x, y) => card._els.overlay.dispatchEvent(ptrEvent("pointerup", id, x, y));
function wheel(card, deltaY, x, y) {
  const e = new window.Event("wheel", { bubbles: true, cancelable: true });
  e.deltaY = deltaY;
  e.clientX = x;
  e.clientY = y;
  card._els.overlay.dispatchEvent(e);
  return e;
}
/** Drag one finger from A to B in `steps` moves (a single move never leaves the tap slop). */
function drag(card, [x0, y0], [x1, y1], steps = 4, id = 1) {
  down(card, id, x0, y0);
  for (let i = 1; i <= steps; i++) {
    move(card, id, x0 + ((x1 - x0) * i) / steps, y0 + ((y1 - y0) * i) / steps);
  }
  up(card, id, x1, y1);
}
/** The client point at which the renderer draws its own normalized coordinate (nx,ny). */
function screenOf(card, nx, ny) {
  const p = card._crRenderer.pointForNormalized(nx, ny);
  return [p.x, p.y];
}
/** The client point at which the card draws a STORED coordinate (the overlay sits at 0,0). */
function overlayOf(card, nx, ny) {
  const p = card._overlayPos(nx, ny);
  return [Number(p.x), Number(p.y)];
}

// Build a mounted card. `cfg` extras merge over the base config; `load` overrides the
// renderer import (omit to exercise the REAL dynamic import, which jsdom cannot resolve);
// `tune` gets the stub connection before hass is handed over.
async function mount(cfg = {}, load, tune) {
  const conn = makeConnection();
  if (tune) tune(conn);
  const hass = makeHass(conn);
  const card = new Card();
  card.setConfig(Object.assign({ vacuum: "vacuum.robot", camera: "camera.robot_map" }, cfg));
  document.body.appendChild(card);
  if (load !== undefined) card._loadRenderer = load;
  card.hass = hass;
  // jsdom does no layout, so hand the canvas the box a real browser would give it:
  // width:100% of the 520px .map-wrap cap, height from the 4x3 grid's aspect. Set after
  // `set hass` because that is what builds the shadow DOM, and before the async start
  // chain settles because that is what measures it.
  card._els.canvas.getBoundingClientRect = () => ({ left: 0, top: 0, width: 520, height: 390 });
  await settle();
  return { card, conn, hass };
}

// ---- 1. flag OFF: the PNG path is untouched ------------------------------------------------
console.log("[1] client_render:false — the explicit opt-out, no longer the default");
{
  const { card, conn } = await mount({ client_render: false });
  ok(conn.subs.length === 0, "no map subscription when opted out");
  ok(conn.sent.length === 0, "no geometry request when opted out");
  ok(card._crRenderer === null, "no renderer instantiated");
  ok(card._els.canvas.hidden === true, "the canvas is not in the layout");
  ok(card._els.img.hidden === false, "the <img> still owns the map surface");
  ok(/\/pic\.png\?v=7/.test(card._els.img.getAttribute("src") || ""), "PNG still keyed on map_revision");
  ok(card._pngActive() === true, "the PNG polling path stays active");
  card.remove();
}

// ---- 1b. NO key at all: the 1.16.21 default --------------------------------------------------
// The flip itself. Case 1 proves `false` still opts out and case 2 proves `true` still opts in;
// neither would notice the runtime default reverting, because both name the key.
console.log("[1b] no client_render key — canvas by default (1.16.21)");
{
  const r = makeRendererModule();
  const { card, conn } = await mount(undefined, () => Promise.resolve(r.mod));

  ok(card._clientRenderEnabled() === true, "a card with no client_render key is enabled");
  ok(conn.subs.length === 1, "it subscribes to the map feed unprompted");
  ok(conn.geomRequests().length === 1, "...and asks for the geometry snapshot");
  ok(card._crWhy !== "client_render is set to false in the card config",
     "the opt-out reason is not what stopped it");
  card.remove();
}

// A draw mode still demands a camera even though the canvas would supply a surface: the
// default must not silently delete that guard (see setConfig).
{
  const card = new Card();
  let threw = null;
  try {
    card.setConfig({ vacuum: "vacuum.robot", mode: "zones" });
  } catch (e) {
    threw = e;
  }
  ok(threw !== null, "zones + no camera + no explicit flag still throws");
  ok(/'camera' is required/.test(threw ? threw.message : ""), "...with the camera message");

  const okCard = new Card();
  okCard.setConfig({ vacuum: "vacuum.robot", mode: "zones", client_render: true });
  ok(okCard._config.mode === "zones", "naming the flag explicitly still goes camera-less");
}

// ---- 2. flag ON: subscribe once + snapshot on subscribe ------------------------------------
console.log("[2] client_render on: transport");
{
  const r = makeRendererModule();
  const { card, conn, hass } = await mount({ client_render: true }, () => Promise.resolve(r.mod));

  ok(conn.subs.length === 1, "subscribes exactly once");
  ok(conn.subs[0].msg.type === "robovac_mqtt/map/subscribe", "subscribes to robovac_mqtt/map/subscribe");
  ok(conn.subs[0].msg.entity_id === "vacuum.robot", "addressed by entity_id, not a registry device id");
  ok(conn.subs[0].msg.device_id === undefined, "no device_id is sent — it is a different id space");
  ok(conn.subs[0].opts && conn.subs[0].opts.resubscribe === false,
    "the library's own resubscribe is off (the card resubscribes on reconnect)");
  ok(conn.geomRequests().length === 1, "requests the geometry snapshot on subscribe");
  ok(conn.geomRequests()[0].entity_id === "vacuum.robot", "geometry request carries the same address");

  // repeated hass ticks must not open a second subscription
  hass.states["vacuum.robot"] = Object.assign({}, hass.states["vacuum.robot"], { last_updated: "t1" });
  card.hass = hass;
  card.hass = hass;
  await settle();
  ok(conn.subs.length === 1, "repeated `set hass` does not double-subscribe");
  ok(conn.geomRequests().length === 1, "...and does not re-request geometry");
  card.remove();
}

// ---- 3. geometry applied: the canvas takes the <img>'s exact box ---------------------------
console.log("[3] geometry -> canvas owns the map surface");
{
  const r = makeRendererModule();
  const { card } = await mount({ client_render: true }, () => Promise.resolve(r.mod), (c) => {
    c.geometry = async () => geom(11, [[0, 0], [1, 0], [2, 0]]);
  });

  ok(card._crActive === true, "the client renderer is active once a snapshot lands");
  ok(card._els.canvas.hidden === false, "canvas shown");
  ok(card._els.img.hidden === true, "the <img> is out of the layout (never both at once)");
  ok(!card._els.img.hasAttribute("src"), "the PNG src is dropped so the browser stops holding it");
  ok(card._els.nomap.hidden === true, "the 'waiting for the map' notice is cleared");
  ok(card._els.canvas.width === 4 && card._els.canvas.height === 3,
    "canvas intrinsic size = the grid's aspect (this is what gives .map-wrap its height)");

  const t = card._crRenderer.transform;
  ok(t.x === 0 && t.y === 390 && t.scale === 130,
    `the grid fills the box edge to edge (x=${t.x} y=${t.y} scale=${t.scale})`);
  ok(!r.calls.some((c) => c[0] === "fit"),
    "renderer.fit() is NOT used — its 4% inset + centring would desync every normalized overlay coord");

  // the PNG polling must be off while the canvas owns the map
  ok(card._pngActive() === false, "the PNG path reports itself inactive");
  card._refreshMap();
  ok(!card._els.img.hasAttribute("src"), "_refreshMap is a no-op — a client-rendered card never pulls the image");
  card.remove();
}

// ---- 4. live events -------------------------------------------------------------------------
console.log("[4] pose / trail / geometry events");
{
  const r = makeRendererModule();
  const { card, conn } = await mount({ client_render: true }, () => Promise.resolve(r.mod), (c) => {
    c.geometry = async () => geom(11, [[0, 0], [1, 0]]); // local trail length starts at 2
  });
  ok(card._crTrailLen === 2, "local trail length seeded from the snapshot");

  conn.emit({ t: "pose", robot: [3, 1], dock: [1, 1] });
  const pose = r.calls.filter((c) => c[0] === "setPose").pop();
  ok(pose && pose[1].robot[0] === 3, "a pose event drives the renderer");
  conn.emit({ t: "pose", robot: [3, 2] });
  const pose2 = r.calls.filter((c) => c[0] === "setPose").pop();
  ok(pose2 && pose2[1].dock === undefined,
    "a pose without a dock passes `undefined` through (the renderer keeps the last dock)");

  // matching `from` appends
  conn.emit({ t: "trail", from: 2, p: [[2, 0], [3, 0]] });
  await settle(2);
  ok(r.calls.filter((c) => c[0] === "appendTrail").length === 1, "a matching trail event appends");
  ok(card._crTrailLen === 4, "local trail length advances by the appended points");
  ok(conn.geomRequests().length === 1, "...and does not re-fetch geometry");

  // mismatched `from` = missed events -> re-fetch, never a bad append
  conn.emit({ t: "trail", from: 99, p: [[9, 9]] });
  await settle();
  ok(r.calls.filter((c) => c[0] === "appendTrail").length === 1,
    "a mismatched `from` does NOT append (that would splice an unrelated run into the path)");
  ok(conn.geomRequests().length === 2, "a mismatched `from` re-requests the geometry snapshot");
  ok(card._crTrailLen === 2, "the trail length is re-seeded from the fresh snapshot");

  // reset burst
  conn.emit({ t: "trail", from: 0, reset: true, p: [[0, 0]] });
  await settle(2);
  ok(r.calls.filter((c) => c[0] === "resetTrail").length >= 1, "a reset event rebuilds the trail");
  ok(card._crTrailLen === 1, "trail length follows the reset");

  // geometry revision events
  const before = conn.geomRequests().length;
  conn.emit({ t: "geometry", revision: 11 });
  await settle(2);
  ok(conn.geomRequests().length === before, "a geometry event for the revision already applied is ignored");
  conn.geometry = async () => geom(12);
  conn.emit({ t: "geometry", revision: 12 });
  await settle();
  ok(conn.geomRequests().length === before + 1, "a NEW geometry revision re-fetches the snapshot");
  ok(card._crRevision === 12, "the applied revision is tracked");
  card.remove();
}

// ---- 4b. trail events while a snapshot is in flight -------------------------------------------
// On a slow link a trail batch lands just ahead of every snapshot reply. Re-fetching on each
// `from` mismatch then discards the snapshot in flight, and no snapshot is ever applied.
console.log("[4b] trail events while a snapshot is in flight");
{
  const r = makeRendererModule();
  const { card, conn } = await mount({ client_render: true }, () => Promise.resolve(r.mod), (c) => {
    c.geometry = async () => geom(11, [[0, 0], [1, 0]]);
  });
  const deferred = () => {
    let resolve;
    const promise = new Promise((res) => (resolve = res));
    return { promise, resolve };
  };
  const reply = deferred();
  const decoded = deferred();
  conn.geometry = () => reply.promise;
  const realDecode = r.mod.decodeGeometry;
  r.mod.decodeGeometry = async (p) => {
    await decoded.promise;
    return realDecode(p);
  };
  const appends = () => r.calls.filter((c) => c[0] === "appendTrail").map((c) => c[1]);
  const before = conn.geomRequests().length;

  conn.emit({ t: "geometry", revision: 12 });
  ok(conn.geomRequests().length === before + 1, "a new revision requests a snapshot");
  // Before the reply: the server flushed these into the snapshot it is about to send.
  conn.emit({ t: "trail", from: 5, p: [[5, 0]] });
  conn.emit({ t: "trail", from: 6, p: [[6, 0], [7, 0]] });
  await settle(2);
  ok(conn.geomRequests().length === before + 1, "a `from` mismatch does not start a second fetch");
  ok(appends().length === 0, "nothing is appended ahead of the snapshot");

  reply.resolve(geom(12, [[0, 0], [1, 0], [2, 0], [3, 0], [4, 0], [5, 0], [6, 0], [7, 0]]));
  await settle(2);
  // After the reply, before the snapshot is applied: these continue it.
  conn.emit({ t: "trail", from: 8, p: [[8, 0], [9, 0]] });
  ok(appends().length === 0, "an event after the reply waits for the snapshot");
  decoded.resolve();
  await settle();
  ok(card._crRevision === 12, "the snapshot in flight is applied, not discarded");
  ok(JSON.stringify(appends()) === "[2]", `only the events after the reply are appended (got ${JSON.stringify(appends())})`);
  ok(card._crTrailLen === 10, `the trail length continues from the snapshot (got ${card._crTrailLen})`);
  ok(conn.geomRequests().length === before + 1, "one snapshot request in all");

  r.mod.decodeGeometry = realDecode;
  conn.geometry = async () => geom(12, []);
  conn.emit({ t: "trail", from: 10, p: [[10, 0]] });
  ok(card._crTrailLen === 11 && conn.geomRequests().length === before + 1,
    "with nothing in flight a matching event appends directly");

  // A gap among the replayed events re-fetches once; the events after it are in that reply.
  const reply2 = deferred();
  const decoded2 = deferred();
  conn.geometry = () => reply2.promise;
  r.mod.decodeGeometry = async (p) => {
    await decoded2.promise;
    return realDecode(p);
  };
  conn.emit({ t: "geometry", revision: 13 });
  const base = conn.geomRequests().length;
  reply2.resolve(geom(13, [[0, 0]]));
  await settle(2);
  conn.emit({ t: "trail", from: 5, p: [[5, 0]] });
  conn.emit({ t: "trail", from: 6, p: [[6, 0]] });
  conn.emit({ t: "trail", from: 7, p: [[7, 0]] });
  r.mod.decodeGeometry = realDecode;
  conn.geometry = async () => geom(13, [[0, 0]]);
  decoded2.resolve();
  await settle();
  ok(conn.geomRequests().length === base + 1,
    `a replayed gap starts one fetch, not one per queued event (got ${conn.geomRequests().length - base})`);
  card.remove();
}

// ---- 5. a reconnect resubscribes with backoff and re-requests the snapshot ------------------
// After an HA restart the socket is back before the integration is: the subscribe and the
// snapshot then fail with `unknown_command`/`not_found` until it has loaded.
console.log("[5] reconnect");
await withRetryTimers(async (ctl) => {
  const r = makeRendererModule();
  const { card, conn } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
  ctl.card = card;
  ok(conn.ready.length === 1, "a connection 'ready' listener is registered");
  ok(conn.geomRequests().length === 1, "one snapshot so far");

  conn.emitReady();
  ok(conn.subs[0].unsubbed === 1, "the subscription the reconnect dropped is released");
  ok(card._crActive === true && card._crFailed === false, "the last frame stays meanwhile");
  ok(ctl.retry() && ctl.retry().ms === 2000, "a resubscribe is scheduled in 2 s");

  conn.subscribeError = { code: "unknown_command", message: "Unknown command." };
  await ctl.fire(ctl.retry());
  ok(card._crFailed === false, "an integration still loading is retried, not a fallback");
  ok(ctl.retry() && ctl.retry().ms === 4000, "the next try backs off to 4 s");

  conn.subscribeError = null;
  conn.geometry = async () => {
    throw { code: "not_found", message: "No Eufy vacuum for entity vacuum.robot" };
  };
  await ctl.fire(ctl.retry());
  ok(card._crFailed === false && ctl.retry() && ctl.retry().ms === 8000,
    "a `not_found` snapshot while it loads is retried too");

  conn.geometry = async () => geom(12);
  await ctl.fire(ctl.retry());
  const live = conn.subs.filter((s) => !s.unsubbed);
  ok(live.length === 1, "exactly one live subscription once the integration answers");
  ok(card._crRevision === 12 && card._crRecovering === false, "the fresh snapshot is applied");
  ok(conn.ready.length === 1, "one 'ready' listener, re-bound by the new subscription");
  ok(ctl.retry() === undefined, "no retry left pending");
  card.remove();
});

// A card created while the integration is still loading starts in the same retry loop
// rather than spending the one-shot fallback. So does one whose socket drops mid-start:
// home-assistant-js-websocket rejects every open request with code 3 (ERR_CONNECTION_LOST).
console.log("[5b] start while the integration is not loaded yet, or the socket drops");
const LOST = { code: 3, message: "Connection lost" };
for (const [label, tune] of [
  ["`not_found` on subscribe", (c) => {
    c.subscribeError = { code: "not_found", message: "No Eufy vacuum for entity vacuum.robot" };
  }],
  ["`unknown_command` on subscribe", (c) => {
    c.subscribeError = { code: "unknown_command", message: "Unknown command." };
  }],
  ["a lost connection on subscribe", (c) => {
    c.subscribeError = LOST;
  }],
  ["a lost connection on the first snapshot", (c) => {
    c.geometry = async () => {
      throw LOST;
    };
  }],
]) {
  await withRetryTimers(async (ctl) => {
    const r = makeRendererModule();
    const { card, conn } = await mount({ client_render: true }, () => Promise.resolve(r.mod), tune);
    ctl.card = card;
    ok(card._crFailed === false, `${label}: not a permanent fallback`);
    ok(card._els.img.hidden === false, `${label}: the PNG shows while it retries`);
    ok(ctl.retry() && ctl.retry().ms === 2000, `${label}: a retry is scheduled`);
    conn.subscribeError = null;
    conn.geometry = async () => geom(11);
    if (ctl.retry()) await ctl.fire(ctl.retry());
    ok(card._crActive === true && card._els.canvas.hidden === false,
      `${label}: the canvas comes up once it answers`);
    card.remove();
  });
}

// ---- 6. room taps resolve locally, by id ----------------------------------------------------
console.log("[6] room tap by id");
{
  const r = makeRendererModule();
  const { card, hass } = await mount({ client_render: true }, () => Promise.resolve(r.mod));

  card._crRenderer._room = 1;
  await card._resolveRoomTap(0.5, 0.5, { clientX: 100, clientY: 100 });
  ok(card._sel.includes(1), "the tapped room id is selected");
  ok(hass._calls.every((c) => c.service !== "room_at_point"),
    "no robovac_mqtt.room_at_point round trip on the client-rendered path");

  // room id 0 is a REAL room on legacy maps — it must never be truthiness-tested away
  card._crRenderer._room = 0;
  await card._resolveRoomTap(0.2, 0.2, { clientX: 20, clientY: 20 });
  ok(card._sel.includes(0), "room id 0 selects (never collapsed to 'no room')");

  card._crRenderer._room = null;
  const n = card._sel.length;
  await card._resolveRoomTap(0.9, 0.9, { clientX: 400, clientY: 300 });
  ok(card._sel.length === n, "a tap on no room changes nothing");

  // zones keep the existing contract: normalized coords via vacuum.send_command
  card._setMode("zones");
  card._zones = [{ x0: 0.1, y0: 0.2, x1: 0.4, y1: 0.5 }];
  await card._cleanZones();
  const zc = hass._calls.filter((c) => c.service === "send_command").pop();
  ok(zc && zc.data.command === "zone_clean", "zone clean still goes through vacuum.send_command");
  ok(zc && JSON.stringify(zc.data.params.zones) === JSON.stringify([[0.1, 0.2, 0.4, 0.5]]),
    "zone coordinates are still NORMALIZED (no conversion ported to JS)");
  card.remove();
}

// ---- 7. teardown ----------------------------------------------------------------------------
console.log("[7] unsubscribe on disconnect");
{
  const r = makeRendererModule();
  const { card, conn, hass } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
  ok(conn.subs.length === 1 && conn.subs[0].unsubbed === 0, "subscribed while mounted");

  card.remove();
  await settle(2);
  ok(conn.subs[0].unsubbed === 1, "unsubscribed on disconnect");
  ok(conn.ready.length === 0, "the reconnect listener is removed too (no leak per re-attach)");

  // HA re-parents cards on every view switch — re-attaching must re-subscribe exactly once
  document.body.appendChild(card);
  card.hass = hass;
  await settle();
  ok(conn.subs.length === 2, "re-attaching subscribes again, exactly once");
  ok(conn.geomRequests().length === 2, "...and re-requests the snapshot with it");
  card.remove();

  // A re-attach whose start now FAILS must fall back, not leave the previous mount's frame
  // frozen on the canvas with no PNG behind it. NOT `no_map`: that one is expected and
  // retryable (section 16), so it deliberately does NOT fall back.
  conn.geometry = async () => {
    throw { code: "unknown_error", message: "boom" };
  };
  document.body.appendChild(card);
  card.hass = hass;
  await settle();
  ok(card._crFailed === true, "a failing re-attach falls back rather than freezing the old frame");
  ok(card._els.img.hidden === false && /\/pic\.png/.test(card._els.img.getAttribute("src") || ""),
    "...and the PNG is showing again");
  card.remove();
}

// ---- 8. fallbacks: every trigger lands on the <img> ------------------------------------------
console.log("[8] fallback to the PNG");
const expectPng = (card, conn, label) => {
  ok(card._crFailed === true, `${label}: marked failed`);
  ok(card._crActive === false, `${label}: the canvas never takes the surface`);
  ok(card._els.canvas.hidden === true, `${label}: canvas hidden`);
  ok(card._els.img.hidden === false, `${label}: the <img> is showing`);
  ok(/\/pic\.png\?v=7/.test(card._els.img.getAttribute("src") || ""), `${label}: PNG src restored`);
  ok(card._pngActive() === true, `${label}: PNG polling resumes`);
};
{
  // 8a — the dynamic import rejects (older integration serving no renderer, CSP, offline)
  const { card, conn } = await mount({ client_render: true }, () => Promise.reject(new Error("404")));
  expectPng(card, conn, "import rejects");
  ok(conn.subs.length === 0, "import rejects: nothing was subscribed");
  card.remove();
}
{
  // 8b — the REAL import, unstubbed. jsdom cannot resolve a dynamic import from a classic
  // script, so this exercises the genuine failure path rather than a mocked one.
  const { card, conn } = await mount({ client_render: true });
  ok(card._rendererUrl() === new URL("./eufy-map-renderer.js?v=1.2.3", CARD_MODULE_URL).href,
    `the renderer URL carries the card's own ?v= cache-bust (${card._rendererUrl()})`);
  expectPng(card, conn, "real import fails");
  card.remove();
}
{
  // 8c — the module loads but exports nothing usable
  const { card, conn } = await mount({ client_render: true }, () => Promise.resolve({}));
  expectPng(card, conn, "module has no EufyMapRenderer");
  card.remove();
}
{
  // 8d — the subscribe command errors with anything but `not_found`/`unknown_command`
  // (those mean the integration is still loading: [5b])
  const r = makeRendererModule();
  const { card, conn } = await mount({ client_render: true }, () => Promise.resolve(r.mod), (c) => {
    c.subscribeError = { code: "unknown_error", message: "boom" };
  });
  expectPng(card, conn, "subscribe errors");
  card.remove();
}
{
  // 8e — the geometry command errors. `no_map` is EXCLUDED on purpose: it is the expected
  // first-run state and is retryable, which section 16 pins. Anything else is fatal.
  const r = makeRendererModule();
  const { card, conn } = await mount({ client_render: true }, () => Promise.resolve(r.mod), (c) => {
    c.geometry = async () => {
      throw { code: "unknown_error", message: "boom" };
    };
  });
  expectPng(card, conn, "geometry errors");
  ok(conn.subs[0].unsubbed === 1, "geometry errors: the subscription is dropped, not left dangling");
  card.remove();
}
{
  // 8f — no geometry arrives at all
  const r = makeRendererModule();
  const { card, conn } = await mount({ client_render: true }, () => Promise.resolve(r.mod), (c) => {
    c.geometry = async () => null;
  });
  expectPng(card, conn, "empty geometry");
  card.remove();
}
{
  // 8g — an event handler throwing AFTER a frame is drawn keeps that frame rather than
  // flapping back to the PNG mid-clean.
  const r = makeRendererModule();
  const { card, conn } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
  card._crRenderer.setPose = () => {
    throw new Error("boom");
  };
  conn.emit({ t: "pose", robot: [0, 0] });
  ok(card._crFailed === false && card._crActive === true,
    "a late error keeps the last drawn frame instead of falling back mid-clean");
  card.remove();
}

// ---- 9. device id resolution -----------------------------------------------------------------
console.log("[9] device id");
{
  // camera not in the entity registry -> fall through to the vacuum
  const r = makeRendererModule();
  const conn = makeConnection();
  const hass = makeHass(conn);
  // The frontend entity registry is now irrelevant to addressing: an install where
  // hass.entities carries nothing at all must still work. That absence is exactly
  // what left the card silently on the PNG before, with no warning and no retry.
  hass.entities = {};
  const card = new Card();
  card.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map", client_render: true });
  document.body.appendChild(card);
  card._loadRenderer = () => Promise.resolve(r.mod);
  card.hass = hass;
  await settle();
  ok(conn.subs.length === 1, "subscribes with no entity registry present at all");
  ok(conn.subs[0].msg.entity_id === "vacuum.robot", "addressed by the configured vacuum entity");
  card.remove();
}
{
  // explicit escape hatch wins over the registry
  const r = makeRendererModule();
  const { card, conn } = await mount(
    { client_render: true, device_id: "explicit-dev" },
    () => Promise.resolve(r.mod)
  );
  ok(conn.subs[0].msg.device_id === "explicit-dev", "an explicit device_id (the EUFY id) still addresses directly");
  ok(conn.subs[0].msg.entity_id === undefined, "...and then no entity_id is sent");
  card.remove();
}
{
  // There is no longer an "unaddressable" state to fall into: `vacuum` is required
  // by setConfig, so an address always exists. Previously this returned silently,
  // which is precisely how a real bug hid — the card sat on the PNG forever with
  // _crFailed false, so nothing was logged and nothing usefully retried.
  const r2 = makeRendererModule();
  const conn2 = makeConnection();
  const hass2 = makeHass(conn2);
  hass2.entities = {};
  const card2 = new Card();
  card2.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map", client_render: true });
  document.body.appendChild(card2);
  card2._loadRenderer = () => Promise.resolve(r2.mod);
  card2.hass = hass2;
  await settle();
  ok(conn2.subs.length === 1, "an empty registry no longer blocks the client renderer");
  ok(card2._crFailed === false, "...and nothing has failed");
  card2.remove();
}

/* ---- 11. gestures: ROOMS mode -----------------------------------------------------------------
 *
 * The gesture MODEL, which is a product decision and not an implementation detail:
 *   ROOMS  one finger  -> pan the map; a press that never travels the tap slop is a room tap
 *   ZONES  one finger  -> draw a zone; PANNING NEEDS TWO FINGERS ([12])
 *   both   two fingers -> pinch-zoom + pan; wheel -> zoom; dbl-click / the button -> fit
 */
console.log("[11] gestures: rooms mode pans on one finger");
{
  const r = makeRendererModule();
  const { card } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
  layoutOverlay(card);
  const rr = card._crRenderer;
  ok(rr.transform.scale === 130 && rr.transform.x === 0 && rr.transform.y === 390,
    "the fixture starts at fit (4x3 grid in a 520x390 box)");
  ok(card._els.overlay.style.touchAction === "pan-y",
    "at fit the dashboard still scrolls when a finger lands on the map");
  ok(card._els.mapreset.hidden === true, "and there is nothing to reset yet");

  // A press that barely moves is a tap, not a pan.
  down(card, 1, 400, 350);
  up(card, 1, 402, 351);
  ok(card._sel.includes(1), "a tap selects the room under it (the right half is room 1)");
  ok(rr.transform.x === 0, "...and moves the map not at all");

  // A real drag pans, and selects nothing.
  card._sel = [];
  card._roomPins = {};
  drag(card, [400, 350], [340, 350]);
  ok(Math.abs(rr.transform.x - -60) < 1e-9, `one finger pans in rooms mode (x=${rr.transform.x})`);
  ok(card._sel.length === 0, "a pan is not a tap — nothing is selected");

  // Off fit, the affordance appears and the map takes the touch gesture.
  ok(card._els.mapreset.hidden === false, "the reset affordance appears once the view is off fit");
  ok(card._els.overlay.style.touchAction === "none",
    "a moved map owns the touch gesture (otherwise the pan fights the dashboard scroll)");
  card._els.mapreset.click();
  ok(rr.transform.x === 0 && rr.transform.y === 390 && rr.transform.scale === 130,
    "the reset button returns to fit exactly");
  ok(card._els.mapreset.hidden === true, "...the affordance hides again");
  ok(card._els.overlay.style.touchAction === "pan-y", "...and the dashboard scrolls over the map again");

  // Wheel zooms, and must stop the page scrolling while it does.
  const s0 = rr.transform.scale;
  const ev = wheel(card, -100, 260, 195);
  ok(ev.defaultPrevented, "a wheel over a client-rendered map is preventDefault'ed");
  ok(rr.transform.scale > s0, "scrolling up zooms in");
  const zoomedIn = rr.transform.scale;
  const ev2 = wheel(card, 100, 260, 195);
  ok(ev2.defaultPrevented, "so is a wheel the other way");
  // exp(-d*k) is its own inverse for -d, so a notch in and back out lands exactly where it started
  ok(rr.transform.scale < zoomedIn && Math.abs(rr.transform.scale - s0) < 1e-9,
    "scrolling back down lands exactly on the scale it started from");
  card._resetMapView();

  // Two fingers pinch, in either mode.
  card._sel = [];
  down(card, 1, 100, 100);
  down(card, 2, 300, 100);
  ok(card._nav !== null && card._tapStart === null,
    "a second finger starts a map navigation and abandons the pending tap");
  move(card, 2, 300, 100); // the first move only seeds the baseline
  const s1 = rr.transform.scale;
  ok(s1 === 130, "the seeding move does not zoom");
  move(card, 2, 500, 100); // 200px apart -> 400px apart
  ok(Math.abs(rr.transform.scale - s1 * 2) < 1e-9, "spreading the fingers 2x doubles the scale");
  up(card, 2, 500, 100);
  ok(card._nav !== null, "lifting one of two fingers keeps the navigation alive");
  up(card, 1, 100, 100);
  ok(card._ptrs.size === 0 && card._nav === null, "lifting the last finger ends it");
  ok(card._sel.length === 0, "a two-finger gesture never selects a room");
  card.remove();
}

// ---- 12. gestures: ZONES mode ------------------------------------------------------------------
console.log("[12] gestures: zones mode draws on one finger, pans on two");
{
  const r = makeRendererModule();
  const { card } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
  layoutOverlay(card);
  const rr = card._crRenderer;
  card._setMode("zones");
  ok(card._els.overlay.style.touchAction === "none",
    "zones mode always owns the touch gesture — the whole mode is a one-finger drag");

  const home = { ...rr.transform };
  drag(card, [130, 325], [390, 130]);
  ok(card._zones.length === 1, "a one-finger drag draws a zone");
  ok(rr.transform.x === home.x && rr.transform.y === home.y && rr.transform.scale === home.scale,
    "...and does NOT pan the map: one finger is already spoken for in this mode");
  const z = card._zones[0];
  ok(Math.abs(z.x0 - 0.25) < 1e-9 && Math.abs(z.x1 - 0.75) < 1e-9,
    `the zone is stored in whole-map normalized coords (x ${z.x0}..${z.x1})`);

  // A second finger abandons a half-drawn zone rather than drawing it over a moving map.
  down(card, 1, 200, 200);
  ok(card._drag !== null, "the first finger starts a zone");
  down(card, 2, 300, 200);
  ok(card._drag === null && card._nav !== null,
    "a second finger abandons the half-drawn zone and moves the map instead");
  move(card, 1, 200, 200); // seed: centroid 250, 100px apart
  move(card, 1, 240, 200); // centroid 270, 60px apart
  move(card, 2, 340, 200); // centroid 290, 100px apart again
  up(card, 1, 240, 200);
  up(card, 2, 340, 200);
  ok(card._zones.length === 1, "a two-finger gesture in zones mode commits no zone");
  ok(rr.transform.x !== home.x, "...it moved the map instead");
  ok(Math.abs(rr.transform.scale - home.scale) < 1e-9,
    "a pinch that ends at the starting separation ends at the starting scale");
  card.remove();
}

/* ---- 13. THE INVARIANT ------------------------------------------------------------------------
 *
 * Zone rectangles reach `vacuum.send_command` as fractions OF THE WHOLE MAP and the server
 * converts them (`_zone_quads_to_blob_units`, deliberately not ported to JS). The firmware
 * accepts whatever coordinates it is handed, so a fraction that turned out to be of the
 * VIEWPORT cleans the wrong part of the flat and NOTHING reports an error. Before pan/zoom the
 * two frames coincided; they do not any more, and only numbers can tell them apart.
 */
console.log("[13] zones are whole-map coordinates at every pan/zoom");
{
  const r = makeRendererModule();
  const { card } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
  layoutOverlay(card);
  const rr = card._crRenderer;
  card._setMode("zones");

  // (a) `_overlayPos` (what is DRAWN) and `_mapNormFromClient` (what is STORED) are the two
  //     directions of ONE projection. At any transform, a stored coordinate must draw and
  //     read back as itself; if they ever drift, zones land on the wrong floor.
  const probes = [[0.1, 0.2], [0.25, 0.8], [0.5, 0.5], [0.9, 0.35]];
  const views = [
    ["at fit", () => {}],
    ["panned", () => rr.panBy(-37, 21)],
    ["zoomed 3x", () => rr.zoomBy(3, 260, 195)],
    ["panned while zoomed", () => rr.panBy(64, -12)],
  ];
  for (const [label, moveView] of views) {
    moveView();
    let worst = 0;
    for (const [nx, ny] of probes) {
      const [cx, cy] = overlayOf(card, nx, ny);
      const back = card._mapNormFromClient(cx, cy);
      worst = Math.max(worst, Math.abs(back.x - nx), Math.abs(back.y - ny));
    }
    ok(worst < 1e-9, `${label}: a map coordinate draws and reads back as itself (worst ${worst.toExponential(2)})`);
  }

  // (b) The whole point: the SAME FLOOR RECTANGLE, drawn zoomed and panned, stores the same
  //     normalized coordinates as it does at fit.
  rr.resetView(false);
  card._zones = [];
  const A = [0.25, 0.3];
  const B = [0.7, 0.75];
  drag(card, screenOf(card, A[0], A[1]), screenOf(card, B[0], B[1]));
  const atFit = card._zones[0];
  ok(!!atFit, "a zone was drawn at fit");

  card._zones = [];
  rr.zoomBy(3.5, 300, 210);
  rr.panBy(-45, 33);
  drag(card, screenOf(card, A[0], A[1]), screenOf(card, B[0], B[1]));
  const zoomed = card._zones[0];
  const dz = zoomed
    ? Math.max(...["x0", "y0", "x1", "y1"].map((k) => Math.abs(zoomed[k] - atFit[k])))
    : Infinity;
  ok(dz < 1e-9, `the same floor rectangle stores the same coords zoomed as at fit (max delta ${dz})`);

  // (c) Stated the other way round: a FIXED SCREEN POINT is NOT a fixed map coordinate. If it
  //     were, the frame would be viewport-relative — which is exactly the silent bug.
  rr.resetView(false);
  const fixed = card._mapNormFromClient(300, 210);
  rr.panBy(-130, 0); // exactly one cell at the fit scale
  const moved = card._mapNormFromClient(300, 210);
  ok(Math.abs(moved.x - fixed.x - 1 / 4) < 1e-12,
    "a one-cell pan moves the map coordinate under a fixed screen point by exactly one cell");

  // ...and what actually goes on the wire is still the plain normalized rectangle.
  rr.resetView(false);
  card._zones = [{ x0: 0.1, y0: 0.2, x1: 0.4, y1: 0.5 }];
  rr.zoomBy(2.2, 100, 100);
  await card._cleanZones();
  const zc = card._hass._calls.filter((c) => c.service === "send_command").pop();
  ok(zc && JSON.stringify(zc.data.params.zones) === JSON.stringify([[0.1, 0.2, 0.4, 0.5]]),
    "a zoomed card still sends the UNCONVERTED normalized rectangle (no JS transform)");
  card.remove();
}

// ---- 13b. a shape on the canvas is where the renderer fills it, and is saved there --------
// Stored coordinates are in the integration's frame (`_normalized_to_cm`), which sits one grid
// row away from the renderer's. Without the conversion an existing shape's outline and handles
// draw one row above the renderer's fill of it, and a drawn shape is saved one row below.
console.log("[13b] canvas shapes round-trip to the same cell");
{
  const r = makeRendererModule();
  const { card, hass } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
  layoutOverlay(card);
  const rr = card._crRenderer;
  const g = geom(11); // 4 x 3 cells of 5 cm, origin (-100, -50)
  const res = g.resolution;
  // World cm of the integration's `_normalized_to_cm`, the inverse of what the card stores.
  const toCm = (nx, ny) => [g.origin_x + nx * g.width * res, g.origin_y + (g.height - 1 - ny * g.height) * res];
  const cellOf = ([wx, wy]) => [(wx - g.origin_x) / res, (wy - g.origin_y) / res];
  const near = (a, b) => Math.abs(a[0] - b[0]) < 1e-6 && Math.abs(a[1] - b[1]) < 1e-6;

  // An existing forbidden zone over cells (1..2, 1..2), as the snapshot serves it.
  const zone = [[-95, -45], [-85, -45], [-85, -35], [-95, -35]];
  card._setMode("nogo");
  card._setEditGeometry({ ...g, forbidden_zones: [zone], ban_mop_zones: [], virtual_walls: [] });
  rr.zoomBy(2, 260, 195);
  const edges = [...card._els.overlay.querySelectorAll("line.edge")].map((l) =>
    [Number(l.getAttribute("x1")), Number(l.getAttribute("y1"))]);
  const fills = zone.map(([wx, wy]) => {
    const c = cellOf([wx, wy]);
    return screenOf(card, c[0] / g.width, 1 - c[1] / g.height);
  });
  ok(edges.length === 4 && edges.every((p, i) => near(p, fills[i])),
    `the outline sits on the renderer's fill of the same shape (got ${JSON.stringify(edges)}, fill ${JSON.stringify(fills)})`);

  // Draw over cells (1..3, 0..2) on the zoomed canvas and save it.
  rr.resetView(false);
  const at = (col, row) => screenOf(card, col / g.width, 1 - row / g.height);
  drag(card, at(1, 2), at(3, 0));
  const box = card._els.overlay.querySelector("rect.zone");
  const [bx, by, bw, bh] = ["x", "y", "width", "height"].map((k) => Number(box && box.getAttribute(k)));
  ok(near([bx, by], at(1, 2)) && near([bx + bw, by + bh], at(3, 0)),
    `the drawn rectangle is drawn where the finger went (got ${[bx, by, bw, bh]})`);
  hass._calls.length = 0;
  await card._saveNogoZones();
  const sent = hass._calls.find((c) => c.service === "send_command").data.params.forbidden[0];
  const a = cellOf(toCm(sent[0], sent[1]));
  const b = cellOf(toCm(sent[2], sent[3]));
  ok(near(a, [1, 2]) && near(b, [3, 0]),
    `the saved rectangle lands on the cells it was drawn over (got ${JSON.stringify([a, b])})`);
  card.remove();
}

// ---- 13c. repeated resizes of a fractional-width box are stable ----------------------------
// The REAL renderer on the card's canvas, with a layout model of `.mapcanvas` (width: 100%,
// height: auto): the box height follows CSS `aspect-ratio` when set, else the bitmap's ratio.
// A ResizeObserver calls resize() on every box change, so a bitmap that moves the box loops.
console.log("[13c] resize() is stable on a fractional width");
{
  const { card } = await mount({ client_render: false });
  const cv = card._els.canvas;
  const ctx = { setTransform() {}, clearRect() {} };
  cv.getContext = () => ctx;
  const BOX_W = 383.2;
  cv.getBoundingClientRect = () => {
    const m = /^\s*([\d.]+)\s*\/\s*([\d.]+)\s*$/.exec(cv.style.aspectRatio || "");
    const h = m ? (BOX_W * Number(m[2])) / Number(m[1]) : (BOX_W * cv.height) / cv.width;
    return { left: 0, top: 0, width: BOX_W, height: h };
  };
  const realDpr = globalThis.devicePixelRatio; // the renderer module reads node's global
  globalThis.devicePixelRatio = 2;
  try {
    const run = () => {
      const rr = new rmod.EufyMapRenderer(cv, { bindInput: false });
      const sizes = [];
      for (let i = 0; i < 12; i++) {
        rr.resize();
        sizes.push(`${cv.width}x${cv.height}@${cv.getBoundingClientRect().height.toFixed(2)}`);
      }
      rr.destroy();
      return sizes;
    };
    card._setCanvasAspect({ width: 150, height: 215 });
    ok(cv.style.aspectRatio === "150 / 215", `the card pins the box to the grid's aspect (got "${cv.style.aspectRatio}")`);
    const pinned = run();
    ok(new Set(pinned.slice(1)).size === 1 && pinned[1] === "766x1099@549.25",
      `the bitmap and the box settle at once (got ${pinned.slice(0, 3)} ...)`);
    // Control: without the CSS aspect the model reproduces the creeping box.
    cv.style.aspectRatio = "";
    cv.width = 150;
    cv.height = 215;
    const free = run();
    ok(new Set(free).size > 2, `without it the box keeps moving (got ${free.slice(0, 3)} ...)`);
  } finally {
    if (realDpr === undefined) delete globalThis.devicePixelRatio;
    else globalThis.devicePixelRatio = realDpr;
  }
  card.remove();
}

// ---- 14. the PNG path has no pan/zoom at all ---------------------------------------------------
// The default for every current user. It must behave byte for byte as it did before P3.
console.log("[14] PNG mode: no pan, no zoom");
{
  const { card } = await mount();
  layoutOverlay(card);
  ok(card._crRenderer === null, "no renderer exists");
  ok(card._mapGesturesEnabled() === false, "so no gesture is enabled");
  ok(card._els.mapreset.hidden === true, "no reset affordance is ever shown");
  ok(card._els.overlay.style.touchAction === "pan-y",
    "the dashboard scrolls over the map exactly as before");
  const ev = wheel(card, -100, 260, 195);
  ok(!ev.defaultPrevented,
    "a wheel over the PNG is NOT preventDefault'ed — the page scrolls as it always has");

  // The pre-P3 tap test, unchanged: a fraction-of-the-box drag is not a tap...
  card._sel = [];
  drag(card, [400, 350], [200, 350]);
  await settle(2);
  ok(card._sel.length === 0, "a drag across the PNG selects nothing");
  // ...and a tap still resolves through the server round trip.
  down(card, 1, 400, 350);
  up(card, 1, 401, 351);
  await settle(2);
  ok(card._sel.includes(1), "a tap still resolves through robovac_mqtt.room_at_point");
  card.remove();
}

// ---- 15. the room hit-test survives a non-identity transform -----------------------------------
console.log("[15] room hit-test under pan + zoom");
{
  const r = makeRendererModule();
  const { card } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
  layoutOverlay(card);
  const rr = card._crRenderer;
  // Tap the screen point at which a given MAP coordinate is currently drawn.
  const tapMap = (nx, ny) => {
    const [x, y] = screenOf(card, nx, ny);
    down(card, 1, x, y);
    up(card, 1, x, y);
  };

  card._sel = [];
  card._roomPins = {};
  tapMap(0.25, 0.75); // left half -> room 0, which is a REAL room on legacy maps
  ok(card._sel.includes(0), "room id 0 resolves at fit (never collapsed to 'no room')");

  rr.zoomBy(2.7, 180, 260);
  rr.panBy(-58, 41);
  card._sel = [];
  card._roomPins = {};
  tapMap(0.25, 0.75);
  ok(card._sel.includes(0), "...and still resolves after a zoom and a pan");
  card._sel = [];
  card._roomPins = {};
  tapMap(0.625, 0.5);
  ok(card._sel.includes(1), "the neighbouring room resolves at the same transform");
  const n = card._sel.length;
  tapMap(0.25, 0.1); // grid row 2 carries no room
  ok(card._sel.length === n, "a tap on a roomless cell changes nothing");
  ok(card._hass._calls.every((c) => c.service !== "room_at_point"),
    "still no server round trip per tap, at any transform");
  card.remove();
}

// ---- 10. config validation --------------------------------------------------------------------
console.log("[10] setConfig validation");
{
  const bad = (cfg, label) => {
    let threw = false;
    try {
      new Card().setConfig(cfg);
    } catch (e) {
      threw = true;
    }
    ok(threw, label);
  };
  bad({ vacuum: "vacuum.robot", client_render: "yes" }, "client_render must be a boolean");
  bad({ vacuum: "vacuum.robot", device_id: 42 }, "device_id must be a string");
  let threw = false;
  try {
    new Card().setConfig({ vacuum: "vacuum.robot", client_render: true, mode: "zones" });
  } catch (e) {
    threw = true;
  }
  ok(!threw, "client_render supplies the map surface zones mode requires (no camera needed)");
}


// ---- 16. "no map yet" is not a failure ------------------------------------------------------
// This is the state EVERY install starts in: the robot has never cleaned, so the coordinator
// has no map to serve and `ws_map_geometry` answers `no_map`. Treating that as a permanent
// failure spends the one-shot `_crFailed` and makes the canvas unreachable for the life of
// the card — for a brand-new user, on their very first load.
console.log("[16] no_map is retryable, not fatal");
{
  const r = makeRendererModule();
  const { card, conn } = await mount({ client_render: true }, () => Promise.resolve(r.mod), (c) => {
    c.geometry = async () => {
      const err = new Error("No map decoded yet for Test Vac");
      err.code = "no_map";
      throw err;
    };
  });

  ok(card._crFailed === false, "the card is NOT marked permanently failed");
  ok(card._crActive === false, "and the canvas does not take the surface");
  ok(conn.subs.length === 1, "the subscription stays open, so the retry can be pushed");
  ok(/no map yet/.test(card._crWhy || ""), `the reason says so (got "${card._crWhy}")`);
  ok(card._els.img.hidden === false, "the PNG shows meanwhile");

  // The coordinator fires a geometry event the moment it decodes a map. That is the retry.
  conn.geometry = async () => geom(3);
  conn.subs[0].cb({ t: "geometry", revision: 3 });
  await settle();
  ok(card._crActive === true, "a later geometry event brings the canvas up");
  ok(card._els.canvas.hidden === false, "and the canvas takes the surface");
  card.remove();
}

// ---- 17. capability pre-flight --------------------------------------------------------------
console.log("[17] a browser without DecompressionStream never starts");
{
  const saved = window.DecompressionStream;
  delete window.DecompressionStream;
  const realWarn = window.console.warn;
  const warned = [];
  window.console.warn = (...a) => warned.push(a.join(" "));
  try {
    const r = makeRendererModule();
    const { card, conn, hass } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
    card.hass = hass; // a second tick takes the same bail
    const logged = warned.filter((w) => /not started: .*DecompressionStream/.test(w));
    ok(logged.length === 1, `the reason is logged to the console once (got ${logged.length})`);
    ok(conn.subs.length === 0, "nothing is subscribed");
    ok(card._crRenderer === null, "the renderer is never even imported");
    ok(card._crFailed === false,
      "and the one-shot failure flag is NOT spent — a different browser is not punished");
    ok(/DecompressionStream/.test(card._crWhy || ""), `the reason names it (got "${card._crWhy}")`);
    ok(card._els.img.hidden === false, "the PNG owns the surface");
    card.remove();
  } finally {
    window.DecompressionStream = saved;
    window.console.warn = realWarn;
  }
}

// ---- 18. trail colour rides the geometry payload --------------------------------------------
console.log("[18] trail colour rides the geometry payload");
{
  const r = makeRendererModule();
  const withColor = (rev) => Object.assign(geom(rev), { trail_color: [10, 20, 30] });
  const { card } = await mount({ client_render: true }, () => Promise.resolve(r.mod), (c) => {
    c.geometry = async () => withColor(11);
  });
  ok(JSON.stringify(card._crTrailRgb) === JSON.stringify([10, 20, 30]),
    "the payload colour is kept");
  const theme = r.calls.filter((c) => c[0] === "setTheme").pop();
  ok(theme && theme[2] && /rgba\(10, 20, 30/.test(theme[2].trail),
    `the renderer is themed from it (got ${theme && JSON.stringify(theme[2])})`);
  card.remove();
}

// ---- 18a. dock status handed to the renderer -------------------------------------------------
// The vacuum entity has no battery attribute (battery is the `_battery` sensor), and `idle` is
// standby wherever the robot stopped, so only the renderer's dock distance can tell parked.
console.log("[18a] dock status");
{
  const r = makeRendererModule();
  const { card, hass } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
  const dockStatus = (state, extra = {}) => {
    const h = { ...hass, states: { ...hass.states, ...extra } };
    h.states["vacuum.robot"] = { ...hass.states["vacuum.robot"], state };
    card.hass = h;
    const c = r.calls.filter((x) => x[0] === "setDockStatus").pop();
    return [c[1], c[2]];
  };
  const batt = (v) => ({ "sensor.robot_battery": { state: String(v), attributes: {} } });
  const chg = (on) => ({ "binary_sensor.robot_charging": { state: on ? "on" : "off", attributes: {} } });

  let s = dockStatus("idle");
  ok(s[0] === undefined && s[1] === false, `idle leaves parked to the dock distance (got ${s})`);
  s = dockStatus("idle", batt(100));
  ok(s[0] === undefined, "...also at a full battery");
  s = dockStatus("docked", batt(80));
  ok(s[0] === true && s[1] === true, `docked below full charges (battery from the sensor) (got ${s})`);
  s = dockStatus("docked", batt(100));
  ok(s[0] === true && s[1] === false, `docked at full does not (got ${s})`);
  s = dockStatus("docked");
  ok(s[0] === true && s[1] === false, "docked with no battery reading is not called charging");
  s = dockStatus("idle", chg(true));
  ok(s[0] === true && s[1] === true, "a charging sensor that is on means parked");
  s = dockStatus("cleaning", batt(50));
  ok(s[0] === false, "cleaning is never parked");
  card.remove();
}

// ---- 18b. a renderer rebuilt by setConfig gets the trail colour again ---------------------
console.log("[18b] a renderer rebuilt by setConfig is themed again");
{
  const r = makeRendererModule();
  const { card } = await mount({ client_render: true }, () => Promise.resolve(r.mod), (c) => {
    c.geometry = async () => Object.assign(geom(11), { trail_color: [10, 20, 30] });
  });
  card.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map", client_render: true });
  await settle();
  const built = r.calls.map((c) => c[0]).lastIndexOf("construct");
  const theme = r.calls.slice(built).find((c) => c[0] === "setTheme");
  ok(built > 0 && theme && theme[2] && /rgba\(10, 20, 30/.test(theme[2].trail),
    `the new renderer is themed with the payload colour (got ${theme && JSON.stringify(theme[2])})`);
  card.remove();
}

// ---- 18c. a re-fetched snapshot keeps the user's zoom -------------------------------------
console.log("[18c] a re-fetched snapshot keeps the view");
{
  const r = makeRendererModule();
  const { card, conn } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
  const rr = card._crRenderer;
  const fits = () => r.calls.filter((c) => c[0] === "fitExact").length;
  const fitsBefore = fits();
  rr.zoomBy(3, 260, 195);
  const zoomed = { ...rr.transform };
  conn.geometry = async () => geom(12);
  conn.emit({ t: "geometry", revision: 12 });
  await settle();
  ok(card._crRevision === 12, "the new revision is applied");
  ok(fits() === fitsBefore, "the same grid size is not fitted again");
  ok(rr.transform.scale === zoomed.scale && rr.transform.x === zoomed.x && rr.transform.y === zoomed.y,
    "the zoomed view stays where the user put it");
  conn.geometry = async () => Object.assign(geom(13), { width: 5 });
  conn.emit({ t: "geometry", revision: 13 });
  await settle();
  ok(fits() === fitsBefore + 1, "a snapshot with a new grid size is fitted");
  card.remove();
}

// ---- 19. the map surface says which one it is -----------------------------------------------
console.log("[19] the surface and its reason are on the element");
{
  const r = makeRendererModule();
  const { card } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
  ok(card._els.mapWrap.getAttribute("data-map-surface") === "canvas",
    "the canvas surface is marked on the map wrap");
  ok(card._els.mapWrap.getAttribute("data-map-reason") === "client render active",
    `and the reason is on the element (got "${card._els.mapWrap.getAttribute("data-map-reason")}")`);
  ok(!card._els.mapWrap.title, "no hover tooltip over the map");
  card.remove();
}
{
  const { card } = await mount({ client_render: true }, () => Promise.reject(new Error("404")));
  ok(card._els.mapWrap.getAttribute("data-map-surface") === "png",
    "a fallback marks the PNG surface");
  ok(/404/.test(card._els.mapWrap.getAttribute("data-map-reason") || ""),
    `and carries the reason it fell back (got "${card._els.mapWrap.getAttribute("data-map-reason")}")`);
  card.remove();
}

// ---- 20. `gone`: the server ended the subscription -----------------------------------------
// The integration sends `{t: "gone"}` and drops the subscription when its config entry
// unloads or reloads. The card keeps its frame and resubscribes with backoff (2 s -> 30 s).
console.log("[20] a `gone` event resubscribes with backoff");
{
  // Fake timers: capture the card's setTimeout calls instead of waiting on the clock.
  const realSet = window.setTimeout;
  const realClear = window.clearTimeout;
  let timers = [];
  window.setTimeout = (fn, ms) => {
    const t = { fn, ms, id: timers.length + 1000 };
    timers.push(t);
    return t.id;
  };
  window.clearTimeout = (id) => {
    timers = timers.filter((t) => t.id !== id);
  };
  let card = null;
  const retryTimers = () => timers.filter((t) => card && t.id === card._crRetryTimer);
  const fire = async (t) => {
    timers = timers.filter((x) => x !== t);
    t.fn();
    await settle();
  };
  try {
    const r = makeRendererModule();
    const m = await mount({ client_render: true }, () => Promise.resolve(r.mod));
    card = m.card;
    const conn = m.conn;
    ok(conn.subs.length === 1 && card._crActive === true, "subscribed and drawing");
    const geoBefore = conn.geomRequests().length;

    conn.subs[0].cb({ t: "gone" });
    ok(conn.subs[0].unsubbed === 1, "the dead subscription is dropped");
    ok(card._crActive === true && card._crFailed === false, "the last frame stays; nothing falls back");
    let pending = retryTimers();
    ok(pending.length === 1 && pending[0].ms === 2000, `a resubscribe is scheduled in 2 s (got ${pending.map((t) => t.ms)})`);
    card.hass = card._hass; // a hass tick must not jump the queue
    ok(conn.subs.length === 1, "a hass tick does not resubscribe before the delay");

    // The integration is still reloading: the subscribe errors. That retries, it is not fatal.
    conn.subscribeError = { code: "unknown_command", message: "not loaded" };
    await fire(pending[0]);
    ok(card._crFailed === false, "a failed resubscribe while recovering is not a permanent fallback");
    pending = retryTimers();
    ok(pending.length === 1 && pending[0].ms === 4000, `the next try backs off to 4 s (got ${pending.map((t) => t.ms)})`);
    for (let i = 0; i < 5; i++) {
      await fire(retryTimers()[0]);
    }
    ok(retryTimers()[0].ms === 30000, `the backoff caps at 30 s (got ${retryTimers()[0].ms})`);

    // The integration is back.
    conn.subscribeError = null;
    await fire(retryTimers()[0]);
    ok(conn.subs.length === 2 && conn.subs[1].unsubbed === 0, "resubscribed once the server answers");
    ok(conn.geomRequests().length === geoBefore + 1, "and the snapshot is re-requested");
    ok(card._crRecovering === false && card._crRetryDelay === 0, "the backoff resets after a snapshot");
    ok(retryTimers().length === 0, "no retry left pending");

    // A detach cancels a pending resubscribe.
    conn.subs[1].cb({ t: "gone" });
    ok(retryTimers().length === 1 && retryTimers()[0].ms === 2000, "a second `gone` starts again at 2 s");
    const pendingId = retryTimers()[0].id;
    card.remove();
    ok(!timers.some((t) => t.id === pendingId), "removing the card cancels the pending resubscribe");
  } finally {
    window.setTimeout = realSet;
    window.clearTimeout = realClear;
  }
}

// ---- 21. a detached card stops the renderer's frames -----------------------------------------
console.log("[21] detach pauses the renderer, re-attach resumes it");
{
  const r = makeRendererModule();
  const { card, hass } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
  card.remove();
  ok(r.calls.some((c) => c[0] === "pause"), "disconnect pauses the renderer (no frames on a detached canvas)");
  document.body.appendChild(card);
  card.hass = hass;
  await settle();
  ok(r.calls.some((c) => c[0] === "resume"), "re-attach resumes it");
  card.remove();
}

// ---- 22. work of a stopped start or an older snapshot never lands --------------------------
// setConfig and a detach stop the start in flight; its subscribe, snapshot and events can
// still answer afterwards, and must not act on the start that replaced it.
console.log("[22] a stopped start or an older snapshot never lands");
const deferred = () => {
  let res, rej;
  const p = new Promise((a, b) => ((res = a), (rej = b)));
  return { p, res, rej };
};
// Subscribes that answer only when the test says so; `pend[i]` settles the i-th one.
const holdSubscribes = (pend) => (c) => {
  c.subscribeMessage = (cb, msg, opts) => {
    const rec = { cb, msg, opts, unsubbed: 0 };
    c.subs.push(rec);
    const d = deferred();
    pend.push({ res: () => d.res(() => rec.unsubbed++), rej: d.rej });
    return d.p;
  };
};
const RECONFIG = { vacuum: "vacuum.robot", camera: "camera.robot_map", client_render: true };
{
  const pend = [];
  const r = makeRendererModule();
  const { card, conn } = await mount({ client_render: true }, () => Promise.resolve(r.mod), holdSubscribes(pend));
  card.setConfig(RECONFIG);
  await settle();
  pend[1].res();
  await settle();
  ok(card._crActive === true && conn.geomRequests().length === 1, "the new start subscribes and draws");
  pend[0].res();
  await settle();
  ok(conn.subs[0].unsubbed === 1, "the subscribe of the stopped start is released when it answers");
  ok(conn.geomRequests().length === 1, "and fetches no snapshot");
  card.remove();
}
{
  const pend = [];
  const r = makeRendererModule();
  const { card, conn, hass } = await mount({ client_render: true }, () => Promise.resolve(r.mod), holdSubscribes(pend));
  card.setConfig(RECONFIG);
  await settle();
  pend[0].rej({ code: "unknown_error", message: "old subscribe failed" });
  await settle();
  pend[1].res();
  await settle();
  ok(card._crFailed === false && card._crActive === true,
    "a failed subscribe of the stopped start does not fail the new one");
  card.remove();
  // Detached while the subscribe is out: the failure lands after the card left.
  document.body.appendChild(card);
  card.hass = hass;
  await settle();
  card.remove();
  pend.at(-1).rej({ code: "unknown_error", message: "late failure" });
  await settle();
  document.body.appendChild(card);
  card.hass = hass;
  await settle();
  pend.at(-1).res();
  await settle();
  ok(card._crFailed === false && card._crActive === true && conn.subs.at(-1).unsubbed === 0,
    "a subscribe failing after a detach leaves the re-attached card drawing");
  card.remove();
}
for (const [label, stop, restart] of [
  ["setConfig", (card) => card.setConfig(RECONFIG), () => {}],
  ["a detach", (card) => card.remove(), (card, hass) => {
    document.body.appendChild(card);
    card.hass = hass;
  }],
]) {
  const first = deferred();
  let n = 0;
  const r = makeRendererModule();
  const { card, hass } = await mount({ client_render: true }, () => Promise.resolve(r.mod), (c) => {
    c.geometry = () => (++n === 1 ? first.p : Promise.resolve(geom(11)));
  });
  stop(card);
  first.rej({ code: "unknown_error", message: "old request failed" });
  await settle();
  restart(card, hass);
  await settle();
  ok(card._crFailed === false && card._crActive === true && card._els.canvas.hidden === false,
    `${label} while the first snapshot is out: its failure does not fail the next start`);
  card.remove();
}
{
  const r = makeRendererModule();
  const { card, conn } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
  const older = deferred();
  const gate = deferred();
  const realDecode = r.mod.decodeGeometry;
  const decoded = [];
  r.mod.decodeGeometry = async (p) => {
    decoded.push(p.revision);
    if (p.revision === 12) await gate.p;
    return realDecode(p);
  };
  const applied = () => r.calls.filter((c) => c[0] === "setGeometry").map((c) => c[1]);
  // A newer snapshot overtakes one still decoding.
  conn.geometry = async () => geom(12);
  conn.emit({ t: "geometry", revision: 12 });
  await settle();
  conn.geometry = async () => geom(13);
  conn.emit({ t: "geometry", revision: 13 });
  await settle();
  gate.res();
  await settle();
  ok(card._crRevision === 13 && applied().at(-1) === 13,
    `a snapshot decoded after a newer one is dropped (applied ${JSON.stringify(applied())})`);
  // A reply that is already stale when it arrives is not even decoded.
  conn.geometry = () => older.p;
  conn.emit({ t: "geometry", revision: 14 });
  conn.geometry = async () => geom(15);
  conn.emit({ t: "geometry", revision: 15 });
  await settle();
  older.res(geom(14));
  await settle();
  ok(card._crRevision === 15 && !decoded.includes(14),
    `a reply overtaken before it arrives is not decoded (decoded ${JSON.stringify(decoded)})`);
  card.remove();
}
await withRetryTimers(async (ctl) => {
  const r = makeRendererModule();
  const { card, conn } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
  ctl.card = card;
  const old = conn.subs[0];
  card.setConfig(RECONFIG);
  await settle();
  const before = r.calls.length;
  // HAWS keeps calling the old callback until its unsubscribe is acknowledged.
  old.cb({ t: "pose", robot: [3, 1] });
  old.cb({ t: "trail", from: card._crTrailLen, p: [[1, 1]] });
  old.cb({ t: "gone" });
  ok(r.calls.length === before, "events of the previous subscription do not reach the new renderer");
  ok(conn.subs[1].unsubbed === 0 && !ctl.retry(), "and its late `gone` leaves the new subscription alone");
  card.remove();
});

// ---- 23. the editor reads the canvas snapshot -------------------------------------------------
// With the canvas live every snapshot already feeds the editor's geometry, and a `geometry`
// event re-fetches after a save; a second request would only race the first.
console.log("[23] the editor reuses the canvas snapshot");
{
  const r = makeRendererModule();
  const { card, conn } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
  card._setMode("nogo");
  await settle();
  ok(conn.geomRequests().length === 1 && card._editGeo && card._editGeo.revision === 11,
    "No-go mode edits the canvas snapshot without a request of its own");
  card._zones = [{ x0: 0.1, y0: 0.1, x1: 0.3, y1: 0.3 }];
  await card._saveNogoZones();
  await settle();
  ok(conn.geomRequests().length === 1, "a save waits for the geometry event");
  conn.geometry = async () => geom(12);
  conn.emit({ t: "geometry", revision: 12 });
  await settle();
  ok(conn.geomRequests().length === 2 && card._editGeo.revision === 12, "which brings the new revision");
  card.remove();
}

console.log("[23b] while the canvas resubscribes, a save re-reads the revision itself");
await withRetryTimers(async (ctl) => {
  const r = makeRendererModule();
  let rev = 11;
  const { card, conn } = await mount({ client_render: true }, () => Promise.resolve(r.mod), (c) => {
    c.geometry = async () => geom(rev);
  });
  ctl.card = card;
  card._setMode("nogo");
  await settle();
  conn.emit({ t: "gone" });
  card._zones = [{ x0: 0.1, y0: 0.1, x1: 0.3, y1: 0.3 }];
  rev = 12;
  await card._saveNogoZones();
  await settle();
  ok(card._crActive && !card._crUnsub && ctl.retry() && card._editGeo.revision === 12,
    `no subscription delivers the geometry event, so the save reads it (got revision ${card._editGeo.revision})`);
  card.remove();
});

// ---- 24. a configured No-go/Wall mode reads the stored shapes ---------------------------------
// Without them the shapes on the device have no delete or move grips.
console.log("[24] a configured No-go mode reads the stored shapes without a mode switch");
{
  const ZONE = [[[0, 0], [10, 0], [10, 10], [0, 10]]];
  const geomZ = (rev) => Object.assign(geom(rev), { forbidden_zones: ZONE });
  const grips = (card) => (card._els.overlay.innerHTML.match(/data-(del|mov|rot)="forbidden:0"/g) || []).length;
  const tune = (c) => {
    c.geometry = async () => geomZ(5);
  };
  {
    const { card, conn } = await mount({ client_render: false, mode: "nogo" }, undefined, tune);
    layoutOverlay(card);
    card._renderOverlay();
    ok(conn.geomRequests().length === 1 && card._editGeo && card._editGeo.revision === 5 && grips(card) === 3,
      `on the camera image, at load (got ${conn.geomRequests().length} requests, ${grips(card)} grips)`);
    card.remove();
  }
  {
    const fails = () => Promise.reject(new Error("import failed"));
    const { card, conn } = await mount({ client_render: true, mode: "nogo" }, fails, tune);
    ok(card._crFailed && conn.geomRequests().length === 1 && card._editGeo && card._editGeo.revision === 5,
      `after the canvas falls back for good (got ${conn.geomRequests().length} requests)`);
    card.remove();
  }
  {
    const r = makeRendererModule();
    const { card, conn, hass } = await mount({ client_render: true, mode: "nogo" }, () => Promise.resolve(r.mod), tune);
    ok(card._crActive && conn.geomRequests().length === 1 && card._editGeo.revision === 5,
      `with the canvas starting, its snapshot is the only read (got ${conn.geomRequests().length})`);
    conn.emit({ t: "gone" });
    const vac = hass.states["vacuum.robot"];
    const off = { ...vac, attributes: { ...vac.attributes, nogo_zones_supported: false } };
    card.hass = { ...hass, states: { ...hass.states, "vacuum.robot": off } };
    card.hass = hass;
    await settle();
    ok(card._mode === "nogo" && conn.geomRequests().length === 1,
      "a mode restored while resubscribing keeps the snapshot it has");
    card.remove();
  }
  {
    const conn = makeConnection();
    let down = true;
    conn.geometry = async () => {
      if (down) throw new Error("timeout");
      return geomZ(5);
    };
    const hass = makeHass(conn);
    const vac = hass.states["vacuum.robot"];
    const unsupported = { ...vac, attributes: { ...vac.attributes, nogo_zones_supported: false } };
    hass.states["vacuum.robot"] = unsupported;
    const cfg = { vacuum: "vacuum.robot", camera: "camera.robot_map", client_render: false, mode: "nogo" };
    const card = new Card();
    card.setConfig(cfg);
    document.body.appendChild(card);
    card.hass = hass;
    await settle();
    const tick = (v) => {
      card.hass = { ...hass, states: { ...hass.states, "vacuum.robot": v } };
    };
    ok(card._mode === "rooms" && conn.geomRequests().length === 0, "nothing is read while the mode is held back");
    tick(vac);
    await settle();
    ok(card._mode === "nogo" && conn.geomRequests().length === 1, "the mode restored by the vacuum's support reads them");
    tick(unsupported);
    tick(vac);
    await settle();
    ok(conn.geomRequests().length === 1, `a failed read is not repeated by later ticks (got ${conn.geomRequests().length})`);
    down = false;
    card._setMode("rooms");
    card._setMode("nogo");
    await settle();
    ok(conn.geomRequests().length === 2 && card._editGeo.revision === 5, "entering the mode reads again");
    card.setConfig(cfg);
    await settle();
    ok(conn.geomRequests().length === 3 && card._editGeo.revision === 5, "and so does a new config");
    card.remove();
  }
}

// ---- 25. `not_supported` is final ------------------------------------------------------------
// A robot on the P2P map feed has no geometry payload; the server answers `not_supported`.
console.log("[25] not_supported falls back to the camera image");
{
  // a geometry re-fetch while drawing
  const r = makeRendererModule();
  const { card, conn } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
  ok(card._crActive === true, "drawing before the refusal");
  conn.geometry = async () => {
    const err = new Error("No map geometry");
    err.code = "not_supported";
    throw err;
  };
  conn.subs[0].cb({ t: "geometry", revision: 99 });
  await settle();
  expectPng(card, conn, "not_supported while drawing");
  card.remove();
}
{
  // a resubscribe after the entry reloaded
  const realSet = window.setTimeout;
  const realClear = window.clearTimeout;
  let timers = [];
  window.setTimeout = (fn, ms) => {
    const t = { fn, ms, id: timers.length + 1000 };
    timers.push(t);
    return t.id;
  };
  window.clearTimeout = (id) => {
    timers = timers.filter((t) => t.id !== id);
  };
  try {
    const r = makeRendererModule();
    const { card, conn } = await mount({ client_render: true }, () => Promise.resolve(r.mod));
    conn.subs[0].cb({ t: "gone" });
    conn.subscribeError = { code: "not_supported", message: "No map geometry" };
    const pending = timers.find((t) => t.id === card._crRetryTimer);
    ok(pending !== undefined, "a resubscribe is scheduled");
    timers = timers.filter((t) => t !== pending);
    pending.fn();
    await settle();
    expectPng(card, conn, "not_supported on resubscribe");
    ok(!timers.some((t) => t.id === card._crRetryTimer), "no further resubscribe is scheduled");
    card.remove();
  } finally {
    window.setTimeout = realSet;
    window.clearTimeout = realClear;
  }
}

console.log(fail === 0 ? "\nALL PASSED" : `\n${fail} FAILURES`);
process.exit(fail === 0 ? 0 : 1);
