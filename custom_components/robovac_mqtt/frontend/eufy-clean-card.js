/*
 * eufy-clean-card — room + zone cleaning for Eufy (jeppesens/eufy-clean).
 * Vanilla web component, no build; auto-registered by the integration.
 *
 *       type: custom:eufy-clean-card   # custom:zone-clean-card opens in zones mode
 *       vacuum: vacuum.your_robot
 *       camera: camera.your_robot_map   # optional for rooms; required for zones + map taps
 *       # mode: rooms                   # rooms | zones | nogo | wall
 *       # title: Eufy Clean
 *       # client_render: false          # default true: draw from the map websocket API
 *       # device_id: abc123             # when the entity registry carries no device_id
 *       # selects:                      # zones: global setting selects to surface;
 *       #   - select.your_robot_suction_level   #   omit to auto-discover select.<slug>_*
 *
 * Per-room fields are device-driven: the card renders only the keys the vacuum declares in
 * `room_clean_options`. `hide_edge_mop` is still honoured as a force-hide. */

const MAX_ZONES = 10;
const MIN_FRAC = 0.012; // reject degenerate drags smaller than ~1% of the map in either axis
const TAP_FRAC = 0.03; // a press that moves less than this counts as a tap (rooms mode, PNG)
const WEAR_AMBER = "#eda45c";
const WEAR_RED = "#e0726c";
const WEAR_AMBER_AT = 40; // percent remaining where the ramp is fully amber, and turns red
// Tap slop for the client-rendered map, in SCREEN px: a map fraction is wrong once it zooms.
const CR_TAP_SLOP_PX = 8;
// Wheel -> zoom factor for `exp(-deltaY * k)`; must match the renderer's own wheel handler.
const CR_WHEEL_ZOOM = 0.0015;
// Resubscribe backoff after the map subscription ends (`gone`, a reconnect, or the integration
// not loaded yet): doubles up to max.
const CR_RESUB_MIN_MS = 2000;
const CR_RESUB_MAX_MS = 30000;
// Raw-pose delta (device units) beyond which the robot counts as re-localized after a switch.
const POSE_MOVE_THRESHOLD = 5;
const clamp01 = (v) => Math.min(Math.max(v, 0), 1);

// [display label, command value]. Values are the exact keys set_room_custom accepts (see
// const.py CLEAN_TYPE_MAP / MOP_LEVEL_MAP / CLEAN_EXTENT_MAP); "" omits the key entirely.
const MODE_OPTS = [
  ["Default", ""],
  ["Vacuum", "vacuum"],
  ["Mop", "mop"],
  ["Vacuum & Mop", "vacuum and mop"],
  ["Mop after Vacuum", "mopping after sweeping"],
];
const WATER_OPTS = [["Default", ""], ["Low", "low"], ["Middle", "middle"], ["High", "high"]];
const INTENSITY_OPTS = [["Default", ""], ["Quick", "quick"], ["Normal", "normal"], ["Narrow", "narrow"]];
const EDGE_OPTS = [["Default", ""], ["On", "on"], ["Off", "off"]]; // on→true, off→false at dispatch
const PASSES_OPTS = [1, 2, 3];
const DEFAULT_FANS = ["Quiet", "Standard", "Turbo", "Max", "Boost_IQ"];

// [mdi icon, label, tone] per HA vacuum state; tone colours the icon only (see .robostat CSS).
const VAC_STATE_UI = {
  cleaning: ["mdi:robot-vacuum", "Cleaning", "active"],
  returning: ["mdi:home-import-outline", "Returning to dock", "active"],
  paused: ["mdi:pause-circle-outline", "Paused", "idle"],
  docked: ["mdi:home-outline", "Docked", "idle"],
  idle: ["mdi:sleep", "Idle", "idle"],
  error: ["mdi:alert-circle-outline", "Error", "error"],
  unavailable: ["mdi:cloud-off-outline", "Unavailable", "off"],
  unknown: ["mdi:help-circle-outline", "Unknown", "off"],
};

// States in which a run is on, so the header shows what it is running with.
const RUN_STATES = new Set(["cleaning", "paused"]);

// HA VacuumEntityFeature bits (homeassistant/components/vacuum/const.py).
const VAC_FEATURE = { START: 8192, STOP: 8, RETURN_HOME: 16 };

// [start, stop, return-to-dock] enabled per HA vacuum state; disabled, never hidden.
const VAC_BUTTON_STATES = {
  cleaning: [false, true, true],
  returning: [false, true, false],
  paused: [true, true, true],
  docked: [true, false, false],
  idle: [true, false, true],
  error: [true, false, true],
  unavailable: [false, false, false],
  unknown: [false, false, false],
};

// Render a reading in the unit the ENTITY reports (the user can change it): whole units,
// except hours at 1 decimal. A non-zero value that rounds away shows as "<1 min".
const formatMeasure = (value, unit) => {
  if (!unit) return String(value);
  const decimals = unit === "h" ? 1 : 0;
  const rounded = value.toFixed(decimals);
  if (Number(rounded) === 0 && value > 0) return `<${Math.pow(10, -decimals).toFixed(decimals)}\u00a0${unit}`;
  return `${Number(rounded)}\u00a0${unit}`;
};

// HA's own battery-icon rule (frontend src/data/battery.ts): round to the nearest 10.
const batteryIcon = (level, charging) => {
  if (!Number.isFinite(level)) return "mdi:battery-unknown";
  const r = Math.round(Math.min(Math.max(level, 0), 100) / 10) * 10;
  if (charging) return r > 10 ? `mdi:battery-charging-${r}` : "mdi:battery-charging-outline";
  if (level <= 5) return "mdi:battery-alert-variant-outline";
  return r === 100 ? "mdi:battery" : `mdi:battery-${r}`;
};

const titleCase = (s) => String(s).replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

// Escape dynamic text before interpolating into an innerHTML template: room/scene names and
// fan_speed_list are cloud-authored, so unescaped they are a stored DOM-XSS vector.
const esc = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );

const optionsHtml = (pairs, sel) =>
  pairs
    .map(([label, value]) => `<option value="${esc(value)}"${value === sel ? " selected" : ""}>${esc(label)}</option>`)
    .join("");

class EufyCleanCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    // Unsaved shapes per draw mode, {x0,y0,x1,y1} normalized to the WHOLE MAP: a shape is sent
    // under its own mode's key only (see `_zones`).
    this._pending = { zones: [], nogo: [], wall: [] };
    this._drag = null; // in-progress drag (same frame as _zones)
    this._ptrs = new Map(); // live pointers on the overlay: id -> {x,y} client px
    this._nav = null; // in-flight two-pointer pan/pinch (client-render only)
    this._cleanTimes = 1; // passes per zone (Zone.clean_times)
    this._optSig = {}; // per-select option-list signature (zones settings)
    // Restricted geometry the device holds (`robovac_mqtt/map/geometry`), world cm.
    this._editGeo = null;
    this._editGeoSeq = 0; // fetch generation (a late reply must not overwrite a newer one)
    this._editGeoAsked = false; // a fetch went out for this config (`_loadEditGeometry`)
    // Marked for deletion BY INDEX into `_editGeo`: normalized coordinates would clamp an
    // off-map shape, silently moving it.
    this._del = { forbidden: new Set(), ban_mop: new Set(), walls: new Set() };
    this._shapeDrag = null; // in-flight move/rotate of one shape (pending or existing)
    // Staged transforms by index into `_editGeo`, device frame: cm and radians about centroid.
    this._moves = { forbidden: new Map(), ban_mop: new Map(), walls: new Map() };
    this._sel = []; // selected room ids, in tap order = clean order
    this._roomCfg = {}; // id -> {clean_mode, fan_speed, water_level, clean_intensity, clean_times, edge}
    this._roomEls = {}; // id -> dom refs
    this._roomPins = {}; // id -> {nx, ny} tap point for the on-map pin (map-selected rooms)
    this._lastRooms = []; // last rendered room list
    this._roomIdKey = null; // signature of the rendered room-ID set (full-rebuild trigger)
    this._tapStart = null; // press origin while detecting a rooms-mode tap
    this._built = false;
    this._dispatching = false; // in-flight send guard (prevents double-dispatch)
    this._inFlight = null; // what the send that is out holds still: {shapes: Set, geometry} (`_frozen`)
    this._lastImgSrc = "";
    this._entCount = -1;
    // Post-switch gate: the frame stays on the OLD map until the robot re-localizes.
    this._mapSwitchEntity = null; // resolved Switch Map select entity id (or null)
    this._mapSwitchSig = null; // Switch Map option-list signature (rebuild guard)
    this._mapSwitchPending = null; // target label of an in-flight switch (debounce)
    this._mapSwitchPendingAt = 0; // Date.now() of that switch (timeout fallback)
    this._lastActiveMap = null; // last-seen Active Map sensor value (switch detector)
    this._frameUngrounded = false; // true during the un-grounded window after a switch
    this._poseAtSwitch = null; // {x,y} raw pose captured at the switch
    this._frameAck = false; // power-user override, until the next switch re-arms it
    // Resolved-entity-id memo: keeps `set hass` off an O(entities) registry scan per tick.
    // Only non-null hits are cached, re-validated against hass.states so a rename self-heals.
    this._entCache = {};
    this._crMod = null; // the imported eufy-map-renderer module
    this._crRenderer = null; // EufyMapRenderer instance bound to the <canvas>
    this._crUnsub = null; // websocket subscription teardown
    this._crStarting = false; // a start is in flight (double-subscribe guard)
    this._crActive = false; // a geometry snapshot is on screen -> the canvas owns the map
    this._crFailed = false; // permanently fell back to the PNG
    this._crAddr = null; // {entity_id} or {device_id} the map commands are addressed by
    this._crTrailLen = 0; // local trail length, checked against each trail event's `from`
    this._crRevision = null; // last applied GEOMETRY revision (not the PNG's map_revision)
    this._crGridSize = null; // {w, h} of the grid the view was fitted to
    this._crGen = 0; // start generation — orphans in-flight async work after a stop
    this._crGeomSeq = 0; // geometry-fetch sequence — a stale snapshot never wins a race
    this._crPend = null; // in-flight snapshot: {replied, queue of trail events received after it}
    this._crRO = null; // ResizeObserver on .map-wrap
    this._crDark = false; // last theme darkness handed to the renderer
    this._crOnView = null; // renderer -> card callback: the view (pan/zoom) moved
    this._crReadyBound = null; // connection the "ready" (reconnect) listener sits on
    this._crOnReady = null;
    this._crRetryTimer = null; // pending resubscribe (see CR_RESUB_MIN_MS)
    this._crRetryDelay = 0; // next resubscribe delay, ms (0 = CR_RESUB_MIN_MS)
    this._crRecovering = false; // resubscribing: start errors retry, never fall back
    this._crRetryWarned = false; // the current retry streak has been logged
    this._crWarnedWhy = null; // last start bail reason logged (see _warnNotStarted)
    this._partsHtml = null; // last rendered accessory rows (skip identical rebuilds)
    this._nogoOk = null; // last applied No-go/Wall availability (re-apply the mode on a change)
    this._modeWanted = null; // configured No-go/Wall mode held back until the vacuum supports it
  }

  // The zone-clean-card alias overrides this to zones.
  get _defaultMode() {
    return "rooms";
  }

  /** Unsaved shapes of the ACTIVE draw mode; empty (and not assignable) outside one. */
  get _zones() {
    return this._pending[this._mode] || [];
  }

  set _zones(list) {
    if (this._pending[this._mode]) this._pending[this._mode] = list;
  }

  _clearPending() {
    this._pending = { zones: [], nogo: [], wall: [] };
  }

  setConfig(config) {
    if (!config || !config.vacuum) throw new Error("eufy-clean-card: 'vacuum' is required");
    const m = config.mode;
    if (config.client_render !== undefined && typeof config.client_render !== "boolean") {
      throw new Error("eufy-clean-card: 'client_render' must be true or false");
    }
    if (config.device_id !== undefined && typeof config.device_id !== "string") {
      throw new Error("eufy-clean-card: 'device_id' must be a string");
    }
    // Draw modes need a map surface: a camera, or client_render named explicitly. `!== true`
    // rather than `_clientRenderEnabled()`, or the ON-by-default would void the guard.
    const drawMode = (v) => v === "zones" || v === "nogo" || v === "wall";
    if ((drawMode(m) || drawMode(this._defaultMode)) && !config.camera && config.client_render !== true) {
      throw new Error(`eufy-clean-card: 'camera' is required for ${m || this._defaultMode} mode`);
    }
    this._config = {
      title: "Eufy Clean",
      selects: [],
      ...config,
    };
    this._mode = ["zones", "rooms", "nogo", "wall", "parts"].includes(m) ? m : this._defaultMode;
    this._modeWanted = null;
    this._clearPending();
    this._clearDeletions();
    this._editGeo = null;
    this._editGeoSeq++; // the previous vacuum's snapshot reply must not land
    this._editGeoAsked = false;
    this._drag = null;
    this._ptrs.clear();
    this._nav = null;
    this._sel = [];
    this._roomPins = {};
    this._lastActiveMap = null; // re-evaluate the frame gate for the (possibly new) vacuum
    this._frameStore = undefined;
    this._mapSwitchPending = null;
    this._entCache = {}; // vacuum may have changed — drop resolved-sibling memo
    this._roomOptsFor = null; // ...and the room-field memo (hide_edge_mop may have changed too)
    this._lastImgSrc = ""; // force a backdrop refresh so a swapped camera doesn't show the old map
    this._lastCamUpdate = undefined;
    // Tear the renderer down rather than reuse it: geometry re-rasterises only on a `revision`
    // change, so another device at the same revision keeps the old grid.
    this._stopClientRender();
    this._destroyClientRenderer();
    this._crFailed = false;
    this._crActive = false;
    this._crAddr = null;
    this._crTrailLen = 0;
    this._crRevision = null;
    this._crRecovering = false;
    this._crRetryDelay = 0;
    this._crRetryWarned = false;
    this._partsHtml = null;
    if (this._built) {
      this._selectsKey = null; // rebuild zone selects on next sync
      this._roomIdKey = null; // rebuild room list on next sync
      this._els.mapswitch.disabled = false; // don't strand the picker if reconfigured mid-switch
      this._applyMapSurface();
      this._applyMode();
      this._syncDynamic(); // refresh now, don't wait for the next hass tick
      this._maybeStartClientRender();
    }
  }

  set hass(hass) {
    this._hass = hass;
    // Only a changed registry size can turn a sibling-scan miss into a hit; re-arm exactly then.
    const n = hass && hass.entities ? Object.keys(hass.entities).length : 0;
    if (n !== this._entCount) {
      this._entCount = n;
      this._invalidateSiblingMisses();
    }
    if (!this._built) this._build();
    this._syncDynamic();
    this._maybeStartClientRender();
  }

  getCardSize() {
    // Rough row estimate for masonry.
    const hasMap = this._hasMapSurface();
    const n = this._built && this._hass && this._mode === "rooms" ? this._rooms().length : 0;
    return 3 + (hasMap ? 5 : 0) + Math.min(n, 10);
  }

  connectedCallback() {
    this._startPolling();
    if (this._crRenderer && typeof this._crRenderer.resume === "function") this._crRenderer.resume();
    this._maybeStartClientRender();
  }

  disconnectedCallback() {
    clearTimeout(this._pollTimer);
    this._pollTimer = null;
    clearTimeout(this._statusTimer);
    this._statusTimer = null;
    // HA re-parents cards on a view switch; a stale `_ptrs` entry reads as a second finger.
    this._ptrs.clear();
    this._nav = null;
    this._drag = null;
    this._tapStart = null;
    // Drop the subscription with the card, or every re-parent leaks one.
    this._stopClientRender();
    // A detached canvas must not keep animating; `connectedCallback` resumes it.
    if (this._crRenderer && typeof this._crRenderer.pause === "function") this._crRenderer.pause();
    if (this._crRO) {
      try {
        this._crRO.disconnect();
      } catch (e) {
        /* observer already torn down */
      }
      this._crRO = null;
    }
  }

  _hasCamera() {
    return !!(this._config && this._config.camera);
  }

  // Poll faster while the robot moves; no-op when the canvas owns the map (pushed frames).
  _startPolling() {
    clearTimeout(this._pollTimer);
    const tick = () => {
      const active = this._pngActive() && this._vacuumActive();
      if (active) this._refreshMap();
      this._pollTimer = setTimeout(tick, active ? 3000 : 10000);
    };
    this._pollTimer = setTimeout(tick, 3000);
  }

  _vacuumActive() {
    const v = this._hass && this._hass.states[this._config.vacuum];
    const s = v && v.state;
    return s === "cleaning" || s === "returning";
  }

  // Re-point the <img> at the camera image; skipped mid-draw so the backdrop never swaps out
  // under a zone box. Cache-busts on `map_revision` (`entity_picture` is a rotating token).
  _refreshMap() {
    if (!this._built || !this._hass || this._drag || !this._pngActive()) return;
    const cam = this._hass.states[this._config.camera];
    const attrs = (cam && cam.attributes) || {};
    const pic = attrs.entity_picture;
    if (!pic) return;
    const rev = attrs.map_revision;
    const sep = pic.includes("?") ? "&" : "?";
    const src = rev === undefined ? pic + sep + "_=" + Date.now() : pic + sep + "v=" + rev;
    if (src === this._lastImgSrc) return; // same frame — no request at all
    this._els.img.src = src;
    this._lastImgSrc = src;
  }

  /* Client-side map rendering (default on): subscribe to the map websocket API
   * (docs/MAP_WS_CONTRACT.md) and draw on a <canvas> instead of polling the camera PNG. Every
   * failure before the first snapshot degrades to the PNG, never a blank card; after it, errors
   * are logged and the frame kept rather than flapping back mid-clean. Pan/zoom is
   * client-render only, and the renderer takes `bindInput: false` — the overlay owns input. */

  // `=== false`, not truthiness: an absent key means ON; the editor writes it only to say false.
  _clientRenderEnabled() {
    const cfg = this._config;
    return !!cfg && cfg.client_render !== false && !this._crFailed;
  }

  // True while the <img> PNG owns the map surface; gates polling and the backdrop sync.
  _pngActive() {
    return this._hasCamera() && !this._crActive;
  }

  _hasMapSurface() {
    return this._hasCamera() || this._clientRenderEnabled();
  }

  _isDarkTheme() {
    return !!(this._hass && this._hass.themes && this._hass.themes.darkMode);
  }

  // How the map commands address this vacuum. Prefer `entity_id`: it needs no registry in
  // the browser. A configured `device_id:` means the EUFY id, not HA's device-registry UUID.
  _mapAddress() {
    const cfg = this._config || {};
    if (typeof cfg.device_id === "string" && cfg.device_id) {
      return { device_id: cfg.device_id };
    }
    const eid = cfg.vacuum || cfg.camera;
    return eid ? { entity_id: eid } : null;
  }

  /* Fetch the geometry the device already holds, so existing shapes get a delete handle and
   * a stable index. A failure only costs editing them, not drawing new ones. */
  async _fetchEditGeometry() {
    // A live subscription feeds `_setEditGeometry` every snapshot, a save's included.
    if (this._crUnsub) return;
    const conn = this._hass && this._hass.connection;
    const addr = this._crAddr || this._mapAddress();
    if (!conn || !addr || typeof conn.sendMessagePromise !== "function") return;
    this._editGeoAsked = true;
    const seq = ++this._editGeoSeq;
    try {
      const payload = await conn.sendMessagePromise({
        type: "robovac_mqtt/map/geometry",
        ...addr,
      });
      if (seq !== this._editGeoSeq) return; // a newer fetch won the race
      this._setEditGeometry(payload);
    } catch (err) {
      this._setEditGeometry(null);
    }
  }

  _setEditGeometry(payload) {
    const prev = this._editGeo;
    if (!payload || !payload.width || !payload.height) {
      this._editGeo = null;
    } else {
      this._editGeo = {
        revision: payload.revision,
        width: payload.width,
        height: payload.height,
        origin_x: payload.origin_x,
        origin_y: payload.origin_y,
        resolution: payload.resolution || 5,
        forbidden: payload.forbidden_zones || [],
        ban_mop: payload.ban_mop_zones || [],
        walls: payload.virtual_walls || [],
      };
    }
    // A pending deletion is an index within ONE revision; carried across it deletes another.
    const rev = this._editGeo && this._editGeo.revision;
    if (!prev || !this._editGeo || prev.revision !== rev) this._clearDeletions();
    if (this._built && this._isDrawMode()) {
      this._renderOverlay();
      this._syncControls();
    }
  }

  _clearDeletions() {
    this._del.forbidden.clear();
    this._del.ban_mop.clear();
    this._del.walls.clear();
    this._moves.forbidden.clear();
    this._moves.ban_mop.clear();
    this._moves.walls.clear();
  }

  _deletionCount() {
    return this._del.forbidden.size + this._del.ban_mop.size + this._del.walls.size;
  }

  _moveCount() {
    return this._moves.forbidden.size + this._moves.ban_mop.size + this._moves.walls.size;
  }

  /** One existing shape's points with its staged transform applied, in world cm. Same order
   * as the backend's `_move_shapes`: rotate about the STORED centroid, then translate. */
  _applyMove(kind, index, points) {
    const m = this._moves[kind].get(index);
    const pts = (points || []).map((p) => [p[0], p[1]]);
    if (!m || !pts.length) return pts;
    const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
    const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
    const cos = Math.cos(m.rot || 0);
    const sin = Math.sin(m.rot || 0);
    return pts.map(([x, y]) => [
      cx + (x - cx) * cos - (y - cy) * sin + (m.dx || 0),
      cy + (x - cx) * sin + (y - cy) * cos + (m.dy || 0),
    ]);
  }

  /** Stage a transform on an existing shape, accumulating onto whatever is already staged. */
  _stageMove(kind, index, dx, dy, rot) {
    const map = this._moves[kind];
    if (!map) return;
    const m = map.get(index) || { dx: 0, dy: 0, rot: 0 };
    m.dx += dx;
    m.dy += dy;
    m.rot += rot;
    // A shape dragged back to where it started has nothing to send.
    if (Math.abs(m.dx) < 0.5 && Math.abs(m.dy) < 0.5 && Math.abs(m.rot) < 1e-4) {
      map.delete(index);
    } else {
      map.set(index, m);
    }
  }

  /** Normalized delta -> world cm. y FLIPS: map rows count down, world cm count up. */
  _cmDelta(dnx, dny) {
    const g = this._editGeo;
    if (!g) return null;
    const res = g.resolution || 5;
    return { dx: dnx * g.width * res, dy: -dny * g.height * res };
  }

  /** World cm -> whole-map normalized (inverse of `_normalized_to_cm`). Not clamped to 0-1:
   * shapes do sit off the mapped floor, and clamping would draw a lie. */
  _geoNorm(wx, wy) {
    const g = this._editGeo;
    if (!g || !g.width || !g.height) return null;
    const res = g.resolution || 5;
    return {
      x: (wx - g.origin_x) / (g.width * res),
      y: (g.height - 1 - (wy - g.origin_y) / res) / g.height,
    };
  }

  /** Shapes the ACTIVE mode can edit, staged moves applied; all points normalized. */
  _existingShapes() {
    const g = this._editGeo;
    if (!g) return [];
    const kinds = this._isLineMode()
      ? [["walls", g.walls]]
      : [["forbidden", g.forbidden], ["ban_mop", g.ban_mop]];
    const out = [];
    for (const [kind, shapes] of kinds) {
      (shapes || []).forEach((shape, index) => {
        const pts = this._applyMove(kind, index, shape)
          .map((p) => this._geoNorm(p[0], p[1]))
          .filter(Boolean);
        if (pts.length >= 2) {
          out.push({
            kind,
            index,
            pts,
            center: {
              x: pts.reduce((s, p) => s + p.x, 0) / pts.length,
              y: pts.reduce((s, p) => s + p.y, 0) / pts.length,
            },
            doomed: this._del[kind].has(index),
            moved: this._moves[kind].has(index),
          });
        }
      });
    }
    return out;
  }

  /** Toggle a delete mark, or drop an unsaved shape. An existing one is only marked: the
   * write replaces ALL geometry, so every change batches into one Save. */
  _toggleDelete(token) {
    const [kind, raw] = String(token || "").split(":");
    const index = Number(raw);
    if (!Number.isInteger(index) || index < 0 || this._frozen(kind, index)) return;
    if (kind === "new") {
      if (index >= this._zones.length) return;
      this._zones.splice(index, 1);
    } else {
      const set = this._del[kind];
      if (!set) return;
      if (set.has(index)) set.delete(index);
      else set.add(index);
    }
    this._renderOverlay();
    this._syncControls();
  }

  /** While a send is out, the pending shapes it carries hold still: the device gets them as
   * sent. A no-go save also holds the stored geometry, whose indices it renumbers. Shapes
   * drawn meanwhile stay editable. */
  _frozen(kind, index) {
    const f = this._inFlight;
    if (!f) return false;
    return kind === "new" ? f.shapes.has(this._zones[index]) : f.geometry;
  }

  /* Rotating a pending shape: rotated goes on the wire as four corners, unrotated keeps the
   * rect form. In ASPECT-CORRECTED units, or a square shears on a non-square map. */
  _mapAspect() {
    const g = this._editGeo;
    if (g && g.width && g.height) return { w: g.width, h: g.height };
    // No snapshot: the overlay box is inset:0 over the image, so it has the same ratio.
    const ov = this._els && this._els.overlay;
    const r = ov && ov.getBoundingClientRect ? ov.getBoundingClientRect() : null;
    if (r && r.width && r.height) return { w: r.width, h: r.height };
    return { w: 1, h: 1 };
  }

  _shapeCenter(z) {
    return { x: (z.x0 + z.x1) / 2, y: (z.y0 + z.y1) / 2 };
  }

  /** Angle of *p* seen from *c*, measured in aspect-corrected space. */
  _angleAt(c, p) {
    const a = this._mapAspect();
    return Math.atan2((p.y - c.y) * a.h, (p.x - c.x) * a.w);
  }

  /** Corners normalized, rotation applied: four in the server's bbox order (TL, TR, BR, BL),
   * or two for a wall, which turns about its midpoint. */
  _shapeCorners(z, rot) {
    const angle = rot === undefined ? z.rot || 0 : rot;
    const pts = z.line
      ? [{ x: z.x0, y: z.y0 }, { x: z.x1, y: z.y1 }]
      : [
          { x: Math.min(z.x0, z.x1), y: Math.min(z.y0, z.y1) },
          { x: Math.max(z.x0, z.x1), y: Math.min(z.y0, z.y1) },
          { x: Math.max(z.x0, z.x1), y: Math.max(z.y0, z.y1) },
          { x: Math.min(z.x0, z.x1), y: Math.max(z.y0, z.y1) },
        ];
    if (!angle) return pts;
    const c = this._shapeCenter(z);
    const a = this._mapAspect();
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    return pts.map((p) => {
      const dx = (p.x - c.x) * a.w;
      const dy = (p.y - c.y) * a.h;
      return {
        x: c.x + (dx * cos - dy * sin) / a.w,
        y: c.y + (dx * sin + dy * cos) / a.h,
      };
    });
  }

  /** Apply a rotation unless it pushes a corner off the map: the server clamps into 0-1, so
   * an off-map corner would arrive pinned to the edge as a distorted quad. */
  _applyRotation(z, angle) {
    const pts = this._shapeCorners(z, angle);
    if (pts.some((p) => p.x < 0 || p.x > 1 || p.y < 0 || p.y > 1)) return false;
    z.rot = angle;
    return true;
  }

  /** What goes on the wire for one pending shape: a rect's four numbers, or explicit corners. */
  _shapeParam(z) {
    if (!z.rot) return [z.x0, z.y0, z.x1, z.y1];
    return this._shapeCorners(z).map((p) => [p.x, p.y]);
  }

  // Resolved against this module's URL INCLUDING the search string: the `?v=` query busts
  // both files together, so a fresh card can never pair with a cached renderer.
  _rendererUrl() {
    const here = new URL(import.meta.url);
    return new URL("./eufy-map-renderer.js" + here.search, here).href;
  }

  // Split out so tests can substitute a module: the jsdom harness evaluates this file as a
  // classic script, which cannot resolve a dynamic import.
  _loadRenderer() {
    return import(this._rendererUrl());
  }

  // Called from `set hass`, connectedCallback and setConfig; the real work runs once behind an
  // in-flight guard. Every bail is silent, so its reason goes to `_crWhy`.
  _maybeStartClientRender() {
    if (!this._config || this._config.client_render === false) {
      this._crWhy = "client_render is set to false in the card config";
      return;
    }
    if (this._crFailed) {
      this._crWhy = "permanently fell back after an earlier error (see console warnings)";
      return;
    }
    if (this._crStarting) {
      this._crWhy = "start already in flight";
      return;
    }
    if (this._crUnsub) {
      this._crWhy = "already subscribed";
      return;
    }
    if (this._crRetryTimer) return; // a resubscribe after `gone` is scheduled; `_crWhy` says when
    if (!this._built) {
      this._crWhy = "card DOM not built yet";
      return;
    }
    if (!this._hass) {
      this._crWhy = "no hass object yet";
      return;
    }
    if (!this.isConnected) {
      this._crWhy = "card element is not attached to the document";
      return;
    }
    const conn = this._hass.connection;
    if (!conn || typeof conn.subscribeMessage !== "function") {
      this._crWhy = "hass.connection has no subscribeMessage (no live websocket)";
      this._warnNotStarted();
      return;
    }
    // The renderer inflates the grid with DecompressionStream and has no polyfill.
    if (typeof DecompressionStream !== "function") {
      this._crWhy = "this browser has no DecompressionStream — using the camera image";
      this._syncMapSurfaceHint();
      this._warnNotStarted();
      return;
    }
    this._crWhy = "starting";
    this._startClientRender();
  }

  // These bails run on every hass tick: log each reason once.
  _warnNotStarted() {
    if (this._crWarnedWhy === this._crWhy) return;
    this._crWarnedWhy = this._crWhy;
    console.warn(`[eufy-clean-card] client map render not started: ${this._crWhy}`);
  }

  async _startClientRender() {
    const addr = this._mapAddress();
    // Unreachable in practice (setConfig requires `vacuum`); warn rather than bail silently.
    if (!addr) {
      if (!this._crAddrWarned) {
        this._crAddrWarned = true;
        console.warn(
          "[eufy-clean-card] client_render is on but the card has no vacuum or camera " +
            "entity to address the map with; showing the camera image instead."
        );
      }
      return;
    }
    this._crStarting = true;
    const gen = ++this._crGen;
    try {
      if (!this._crRenderer) {
        const mod = await this._loadRenderer();
        if (gen !== this._crGen) return;
        if (!mod || typeof mod.EufyMapRenderer !== "function") {
          throw new Error("eufy-map-renderer exports no EufyMapRenderer");
        }
        this._crMod = mod;
        this._crDark = this._isDarkTheme();
        this._crOnView = () => this._onMapViewChange();
        this._crRenderer = new mod.EufyMapRenderer(this._els.canvas, {
          isDark: this._crDark,
          bindInput: false, // the overlay owns input; see the block comment above
          onViewChange: this._crOnView,
        });
      }
      // `resubscribe: false`: the library's own resubscribe after a reconnect fails silently
      // while the integration is still loading; the "ready" handler resubscribes instead.
      const unsub = await this._hass.connection.subscribeMessage(
        // HAWS keeps calling this until the unsubscribe is acknowledged.
        (ev) => {
          if (gen === this._crGen) this._onMapEvent(ev);
        },
        { type: "robovac_mqtt/map/subscribe", ...addr },
        { resubscribe: false }
      );
      if (gen !== this._crGen || !this.isConnected) {
        // Stopped or detached while the round trip was in flight — don't strand the sub.
        this._callUnsub(unsub);
        return;
      }
      this._crUnsub = unsub;
      this._crAddr = addr;
      this._crWhy = "subscribed; awaiting geometry";
      this._bindConnectionReady();
      // Re-request the snapshot on EVERY subscribe: the subscription carries deltas only.
      await this._fetchGeometry();
    } catch (err) {
      if (gen === this._crGen) this._clientRenderFailed(err); // else: a stopped start
    } finally {
      if (gen === this._crGen) this._crStarting = false;
    }
  }

  // A reconnect drops the subscription (`resubscribe: false`); after an HA restart the
  // integration may not be loaded yet, so resubscribe with the same backoff as `gone`.
  _bindConnectionReady() {
    const conn = this._hass && this._hass.connection;
    if (!conn || typeof conn.addEventListener !== "function" || this._crReadyBound) return;
    this._crOnReady = () => this._onMapGone("the connection was re-established");
    conn.addEventListener("ready", this._crOnReady);
    this._crReadyBound = conn;
  }

  _unbindConnectionReady() {
    const conn = this._crReadyBound;
    if (conn && this._crOnReady && typeof conn.removeEventListener === "function") {
      try {
        conn.removeEventListener("ready", this._crOnReady);
      } catch (e) {
        /* connection already gone */
      }
    }
    this._crReadyBound = null;
    this._crOnReady = null;
  }

  _callUnsub(unsub) {
    if (typeof unsub !== "function") return;
    try {
      const p = unsub();
      if (p && typeof p.catch === "function") p.catch(() => {});
    } catch (e) {
      /* socket already closed */
    }
  }

  async _fetchGeometry() {
    const conn = this._hass && this._hass.connection;
    const addr = this._crAddr || this._mapAddress();
    if (!conn || !addr || !this._crRenderer || !this._crMod) return;
    const seq = ++this._crGeomSeq;
    // The server flushes pending events before it answers, so a trail event received before
    // the reply is in the snapshot; later ones are queued and replayed on top of it.
    const pend = { replied: false, queue: [] };
    this._crPend = pend;
    try {
      const payload = await conn.sendMessagePromise({
        type: "robovac_mqtt/map/geometry",
        ...addr,
      });
      pend.replied = true;
      // A newer snapshot (or a stop) won the race; applying this one would rewind grid and trail.
      if (seq !== this._crGeomSeq) return;
      const geo = await this._crMod.decodeGeometry(payload);
      if (seq !== this._crGeomSeq) return;
      if (!geo || !geo.width || !geo.height) throw new Error("empty map geometry");
      this._crRevision = payload.revision;
      this._crTrailLen = (payload.trail && payload.trail.length) || 0;
      this._crTrailRgb = payload.trail_color || null;
      // Same snapshot the editor wants — no second request for an identical payload.
      this._setEditGeometry(payload);
      this._crRecovering = false;
      this._crRetryDelay = 0;
      this._crRetryWarned = false;
      this._crActive = true;
      this._applyMapSurface(); // show the canvas BEFORE measuring it — a hidden box has no size
      // Fit only a new grid size: a re-fetch (new revision, reconnect) keeps the user's zoom.
      const size = this._crGridSize;
      const resized = !size || size.w !== geo.width || size.h !== geo.height;
      this._crGridSize = { w: geo.width, h: geo.height };
      if (resized) this._setCanvasAspect(geo);
      this._crRenderer.setGeometry(geo);
      if (resized) this._fitCanvasExact();
      else this._refitCanvas();
      this._syncRendererTheme(); // the trail colour arrives with this payload
      this._crWhy = "client render active";
      this._syncMapSurfaceHint();
      this._crPend = null;
      for (const ev of pend.queue) {
        if (this._crPend) break; // a mismatch re-fetched: the rest precede that request's reply
        this._onTrailEvent(ev);
      }
    } catch (err) {
      if (seq !== this._crGeomSeq) return; // a stopped or superseded fetch
      if (this._crPend === pend) this._crPend = null;
      // "No map yet" is not a failure: the one-shot `_crFailed` would lock the canvas out.
      if (err && err.code === "no_map") {
        this._crRecovering = false; // the server answers: the subscription is healthy
        this._crRetryDelay = 0;
        this._crWhy = "the device has no map yet — waiting for the first clean";
        this._syncMapSurfaceHint();
        return;
      }
      this._clientRenderFailed(err);
    }
  }

  _onMapEvent(ev) {
    if (!ev) return;
    // Terminal: the server dropped this subscription (config entry unloading or reloading).
    if (ev.t === "gone") {
      this._onMapGone("the map subscription was ended by the server");
      return;
    }
    if (!this._crRenderer) return;
    try {
      if (ev.t === "geometry") {
        // Geometry revision, NOT the PNG's map_revision (which bumps on pose-only renders).
        if (ev.revision !== this._crRevision) this._fetchGeometry();
        return;
      }
      if (ev.t === "pose") {
        // `dock` rides along only when it changes; `undefined` means "keep what you have".
        this._crRenderer.setPose({ robot: ev.robot, dock: ev.dock });
        return;
      }
      if (ev.t === "trail") {
        const pend = this._crPend;
        if (pend) {
          // A snapshot is on its way: before its reply this event is in it, after it the
          // event is replayed once the snapshot is applied. No second fetch either way.
          if (pend.replied) pend.queue.push(ev);
          return;
        }
        this._onTrailEvent(ev);
      }
    } catch (err) {
      this._clientRenderFailed(err);
    }
  }

  _onTrailEvent(ev) {
    const pts = ev.p || [];
    // One type per point (0 cleaning, 1 transit); absent means all-cleaning.
    const types = ev.types || [];
    if (ev.reset) {
      this._crRenderer.resetTrail(pts, types);
      this._crTrailLen = pts.length;
      return;
    }
    // `from` is the trail length BEFORE these points; on a mismatch re-fetch instead.
    if (ev.from !== this._crTrailLen) {
      this._fetchGeometry();
      return;
    }
    this._crRenderer.appendTrail(pts, types);
    this._crTrailLen += pts.length;
  }

  // The box in the GRID's aspect: it gives .map-wrap its height, so the absolutely positioned
  // overlay covers exactly the drawn map. CSS `aspect-ratio`, not the bitmap's: `resize()`
  // rounds the bitmap, and a box following it would grow or shrink by a pixel per resize.
  _setCanvasAspect(geo) {
    const cv = this._els && this._els.canvas;
    if (!cv || !geo || !geo.width || !geo.height) return;
    cv.width = Math.max(1, Math.floor(geo.width));
    cv.height = Math.max(1, Math.floor(geo.height));
    cv.style.aspectRatio = `${cv.width} / ${cv.height}`;
  }

  // Fill the box edge to edge (`renderer.fit()` insets by 4%): the card's home view.
  _fitCanvasExact() {
    const r = this._crRenderer;
    const cv = this._els && this._els.canvas;
    const st = r && r.state;
    if (!r || !cv || !st || !st.width || !st.height || !cv.getBoundingClientRect) return;
    r.resize(); // backing store to the CSS box * dpr; the aspect is unchanged by it
    r.fitExact();
  }

  // A ResizeObserver fires on ANY reflow, so `refit()` keeps the zoom factor and centre.
  _refitCanvas() {
    const r = this._crRenderer;
    const cv = this._els && this._els.canvas;
    const st = r && r.state;
    if (!r || !cv || !st || !st.width || !st.height || !cv.getBoundingClientRect) return;
    r.resize();
    r.refit();
  }

  _observeMapWrap() {
    if (this._crRO || typeof ResizeObserver !== "function") return;
    const wrap = this._els && this._els.mapWrap;
    if (!wrap) return;
    this._crRO = new ResizeObserver(() => this._refitCanvas());
    this._crRO.observe(wrap);
  }

  // The renderer moved the view; whole-map normalized geometry only needs re-projecting.
  _onMapViewChange() {
    if (!this._built) return;
    this._renderOverlay();
    this._applyTouchAction();
  }

  _resetMapView() {
    if (!this._crActive || !this._crRenderer || typeof this._crRenderer.resetView !== "function") return;
    this._crRenderer.resetView(true); // instant under prefers-reduced-motion; the renderer decides
    this._onMapViewChange();
  }

  // Single owner of which map surface is visible (two block children would stack), outside
  // _syncDynamic so a fallback needs no hass tick.
  _applyMapSurface() {
    if (!this._built) return;
    const cr = this._crActive;
    this._els.canvas.hidden = !cr;
    if (cr) {
      this._els.img.hidden = true;
      this._els.img.removeAttribute("src"); // stop the browser holding the PNG
      this._lastImgSrc = "";
      this._els.nomap.hidden = true;
      this._observeMapWrap();
      return;
    }
    // PNG path: the <img> shows only once the camera has a frame, else the waiting notice.
    const cam = this._hasCamera() && this._hass && this._hass.states[this._config.camera];
    const pic = !!(cam && cam.attributes && cam.attributes.entity_picture);
    if (!pic && this._els.img.hasAttribute("src")) {
      this._els.img.removeAttribute("src");
      this._lastImgSrc = "";
    }
    this._els.img.hidden = !pic;
    this._els.nomap.hidden = pic;
  }

  // Keep the last frame, drop the dead subscription, resubscribe with backoff; the new
  // subscribe re-requests the snapshot.
  _onMapGone(why) {
    this._stopClientRender();
    this._crRecovering = true;
    this._scheduleResubscribe(why);
  }

  _scheduleResubscribe(why) {
    clearTimeout(this._crRetryTimer);
    const delay = this._crRetryDelay || CR_RESUB_MIN_MS;
    this._crRetryDelay = Math.min(delay * 2, CR_RESUB_MAX_MS);
    this._crWhy = `${why}; resubscribing in ${Math.round(delay / 1000)} s`;
    this._syncMapSurfaceHint();
    this._crRetryTimer = setTimeout(() => {
      this._crRetryTimer = null;
      this._maybeStartClientRender();
    }, delay);
  }

  _cancelResubscribe() {
    clearTimeout(this._crRetryTimer);
    this._crRetryTimer = null;
  }

  _stopClientRender() {
    this._cancelResubscribe();
    this._crGen++; // orphan any in-flight start
    this._crGeomSeq++; // ...and any in-flight geometry fetch
    this._crPend = null;
    this._crStarting = false;
    this._unbindConnectionReady();
    const unsub = this._crUnsub;
    this._crUnsub = null;
    this._callUnsub(unsub);
  }

  _destroyClientRenderer() {
    if (this._crRenderer && typeof this._crRenderer.destroy === "function") {
      try {
        this._crRenderer.destroy();
      } catch (e) {
        /* nothing to release */
      }
    }
    this._crRenderer = null;
    // The next renderer starts unthemed and unfitted: force the theme push and the fit.
    this._crTrailCol = undefined;
    this._crGridSize = null;
  }

  /** Put the map-surface reason on the element (not a tooltip): every guard here is a silent
   * `return`, so a PNG fallback would otherwise be indistinguishable from working. */
  _syncMapSurfaceHint() {
    if (!this._built || !this._els.mapWrap) return;
    this._els.mapWrap.setAttribute("data-map-surface", this._crActive ? "canvas" : "png");
    this._els.mapWrap.setAttribute("data-map-reason", this._crWhy || "starting");
  }

  /** Push theme + trail colour only on a change (setTheme re-rasterises the static layer). */
  _syncRendererTheme() {
    if (!this._crRenderer || !this._hass) return;
    const dark = this._isDarkTheme();
    const cam = this._hass.states[this._config.camera];
    // The geometry payload carries it from v3 on; the camera attribute is the older fallback.
    const rgb = this._crTrailRgb || (cam && cam.attributes && cam.attributes.trail_color);
    let trailStr;
    if (Array.isArray(rgb) && rgb.length >= 3) {
      trailStr = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, 1.0)`;
    }
    if (dark === this._crDark && trailStr === this._crTrailCol) return;
    this._crDark = dark;
    this._crTrailCol = trailStr;
    this._crRenderer.setTheme(trailStr ? { trail: trailStr } : null, dark);
  }

  // Fatal (PNG for good) only on the START path — import, subscribe, first snapshot, or a
  // re-attach whose stale frame would freeze. Once live, log and keep the frame. While
  // recovering, for `not_found`/`unknown_command` (the integration is not loaded yet, as
  // during an HA restart) and for 3 (home-assistant-js-websocket's ERR_CONNECTION_LOST: the
  // socket dropped mid-request), retry with backoff instead.
  _clientRenderFailed(err) {
    const code = err && err.code;
    if (this._crRecovering || code === "not_found" || code === "unknown_command" || code === 3) {
      // One warning per streak: the retries repeat every 30 s while the integration is down.
      if (!this._crRetryWarned) console.warn("[eufy-clean-card] map commands failed; retrying", err);
      this._crRetryWarned = true;
      this._crRecovering = true;
      this._stopClientRender();
      this._scheduleResubscribe(`map commands unavailable (${code || (err && err.message) || err})`);
      return;
    }
    if (this._crActive && !this._crStarting) {
      console.warn("[eufy-clean-card] client map render error; keeping the last frame", err);
      return;
    }
    console.warn("[eufy-clean-card] client map render unavailable — falling back to the camera image", err);
    this._crFailed = true;
    this._crActive = false; // hands the surface, the polling and the cache token back to the PNG
    this._crRevision = null;
    this._crTrailLen = 0;
    this._stopClientRender();
    this._destroyClientRenderer();
    this._crMod = null;
    this._applyMapSurface();
    this._applyMode(); // the map surface may have gone away entirely (client_render, no camera)
    // Re-arm the PNG cache token: the camera entity never changed, but <img> must re-point.
    this._lastImgSrc = "";
    this._lastCamUpdate = undefined;
    this._crWhy = `fell back to the camera image: ${(err && err.message) || err}`;
    this._syncMapSurfaceHint();
    this._refreshMap();
    if (this.isConnected) this._startPolling();
  }

  _build() {
    const c = this._config;
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 12px 16px 16px; }
        /* The hidden ATTRIBUTE only hides via the UA's [hidden]{display:none} rule, which any
           author "display:" declaration below outranks — a section such as .rooms{display:flex}
           would stay on screen while marked hidden and keep taking input. This global rule makes
           [hidden] authoritative whatever display a section declares.
           (NB: this <style> lives in a JS template literal — no backticks in these comments.) */
        [hidden] { display: none !important; }
        .title { font-size: 1.1rem; font-weight: 500; margin-bottom: 8px; }

        /* Robot status header — the ROBOT's own live state, at the top of the card. Not to be
           confused with the .status line down in .controls, which reports what the CARD just did
           ("Sent 2 rooms"). Shaped like HA's tile card: a tinted round icon, a primary state line
           and a secondary detail (task status, or the error when there is one). */
        .robostat { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap;
                    padding: 8px 10px; border-radius: 10px; background: var(--secondary-background-color); }
        .rs-icon { flex: 0 0 auto; display: flex; align-items: center; justify-content: center;
                   width: 36px; height: 36px; border-radius: 50%; --mdc-icon-size: 22px;
                   color: var(--state-icon-color, var(--primary-text-color));
                   background: color-mix(in srgb, currentColor 18%, transparent); }
        /* 100px basis (not auto): once the state text can no longer hold it, the whole
           .rs-chips strip wraps to its own row rather than the chips shrinking into
           unreadable stubs. That is the ~300px sidebar / narrow-phone layout. */
        .rs-text { flex: 1 1 100px; min-width: 0; display: flex; flex-direction: column; }
        .rs-state { font-size: 0.95rem; font-weight: 500; color: var(--primary-text-color); }
        .rs-detail { font-size: 0.78rem; color: var(--secondary-text-color);
                     overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        /* Shrinkable and wrapping. With "flex: 1 0 auto" + nowrap the strip can neither shrink
           nor wrap, so in a ~300px column it overflows and the last control — return-to-dock —
           is clipped off the right edge with no scrollbar and no error, reading as a missing
           button. Wrapping drops the buttons to their own line instead. */
        .rs-chips { flex: 1 1 auto; display: flex; flex-wrap: wrap; align-items: center;
                    justify-content: flex-end; gap: 10px; color: var(--secondary-text-color); }
        /* The three controls wrap as ONE unit: without this the strip breaks between
           them and play ends up on a different line from stop and return-to-dock. */
        .rs-actions { flex: 0 0 auto; display: flex; align-items: center; gap: 10px; }
        .rs-chip { flex: 0 0 auto; display: flex; align-items: center; gap: 3px; --mdc-icon-size: 18px;
                   font-size: 0.82rem; color: var(--secondary-text-color); }
        /* Session stats that are NOT from the run in progress are a completed run's totals —
           still worth reading, but dimmed so they are never mistaken for live numbers. */
        .robostat:not(.on-active) .rs-time,
        .robostat:not(.on-active) .rs-area { opacity: 0.6; }
        /* Negative margin cancels the padding, so the 40px touch target costs no header height. */
        .rs-btn { flex: 0 0 auto; font: inherit; background: transparent; border: none; color: inherit;
                  cursor: pointer; padding: 8px; margin: -8px 0; border-radius: 50%;
                  display: flex; align-items: center; justify-content: center; --mdc-icon-size: 22px; }
        .rs-btn:disabled { opacity: 0.35; cursor: default; }
        /* Tone colours the ICON only — the text stays on --primary-text-color, so readability
           never depends on the tint and both themes keep full contrast. The error tint is a 14%
           wash of --error-color over whatever the card background is (light or dark). */
        .robostat.on-active .rs-icon { color: var(--state-active-color, var(--primary-color)); }
        .robostat.on-error .rs-icon { color: var(--error-color, #db4437); }
        .robostat.on-off .rs-icon { color: var(--secondary-text-color); }
        .robostat.on-off .rs-state { color: var(--secondary-text-color); }
        .robostat.on-error { background: color-mix(in srgb, var(--error-color, #db4437) 14%, transparent); }
        .modebar { display: inline-flex; border: 1px solid var(--divider-color); border-radius: 999px;
                   overflow: hidden; margin-bottom: 12px; }
        .modebar button { font: inherit; font-size: 0.85rem; padding: 8px 16px; min-height: 40px; border: none;
                          cursor: pointer; background: transparent; color: var(--primary-text-color); }
        .modebar button.on { background: var(--primary-color); color: var(--text-primary-color, #fff); font-weight: 500; }
        .map-wrap { position: relative; width: 100%; max-width: 520px; margin: 0 auto;
                    border-radius: 8px; overflow: hidden; background: var(--secondary-background-color); }
        .map-wrap img { display: block; width: 100%; height: auto; user-select: none; -webkit-user-drag: none; }
        /* The client-rendered canvas must occupy EXACTLY the box the <img> does — same display,
           same sizing, intrinsic width/height in the grid's aspect — because the overlay above
           it is laid out in normalized (0-1) coordinates over that box. Anything else desyncs
           room pins and zone rectangles from the map they are drawn on. */
        .map-wrap canvas.mapcanvas { display: block; width: 100%; height: auto; user-select: none; }
        /* width/height:100% are REQUIRED — an inline <svg> is a replaced element with a default
           300x150 intrinsic size; inset:0 alone does NOT stretch it. */
        .overlay { position: absolute; inset: 0; width: 100%; height: 100%; touch-action: none; }
        /* Reset-view affordance. Only ever shown while the client-rendered map is off its
           fit, so a user who has zoomed in always has a way back that does not depend on
           reversing the gesture by hand. Above .gate (z-index 2) so the two never fight. */
        .mapreset { position: absolute; top: 8px; right: 8px; z-index: 3; width: 40px; height: 40px;
                    display: flex; align-items: center; justify-content: center; padding: 0;
                    border-radius: 8px; cursor: pointer; --mdc-icon-size: 20px;
                    border: 1px solid var(--divider-color); color: var(--primary-text-color);
                    background: color-mix(in srgb, var(--card-background-color) 92%, transparent);
                    animation: mapreset-in 160ms ease-out; }
        @keyframes mapreset-in { from { opacity: 0; transform: scale(0.9); } to { opacity: 1; transform: none; } }
        /* The one animated transition on this card, and it is opt-out. */
        @media (prefers-reduced-motion: reduce) { .mapreset { animation: none; } }
        .nomap { padding: 40px 12px; text-align: center; color: var(--secondary-text-color); font-size: 0.9rem; }

        /* Switch Map picker (surfaces the fork's select.<slug>_switch_map) */
        .mapbar { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
        .mapbar-label { font-size: 0.7rem; color: var(--secondary-text-color); text-transform: uppercase; letter-spacing: 0.03em; }
        .mapbar select { flex: 0 1 240px; padding: 6px 8px; border-radius: 6px; border: 1px solid var(--divider-color);
                         background: var(--card-background-color); color: var(--primary-text-color); font-size: 0.88rem; }

        /* Post-switch safety banner — the coordinate frame is un-grounded until the robot
           re-localizes, so drawing/tap-select is paused. Floats over the map. */
        .gate { position: absolute; left: 50%; bottom: 10px; transform: translateX(-50%); z-index: 2;
                display: flex; align-items: center; gap: 10px; max-width: calc(100% - 20px);
                padding: 8px 12px; border-radius: 8px; font-size: 0.8rem; line-height: 1.35;
                color: var(--primary-text-color);
                background: color-mix(in srgb, var(--card-background-color) 92%, transparent);
                border: 1px solid var(--warning-color, #d97706); box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3); }
        .gate-msg { flex: 1 1 auto; }
        .gate-ack { flex: 0 0 auto; white-space: nowrap; font: inherit; font-size: 0.8rem; padding: 8px 12px;
                    min-height: 40px; border-radius: 6px; border: 1px solid var(--divider-color); cursor: pointer;
                    background: transparent; color: var(--primary-text-color); }

        /* rooms */
        .rooms { display: flex; flex-direction: column; gap: 8px; margin-top: 12px; }
        .rooms .empty { padding: 28px 12px; text-align: center; color: var(--secondary-text-color); font-size: 0.9rem; }
        .room { border: 1px solid var(--divider-color); border-radius: 10px; overflow: hidden; }
        .room.selected { border-color: var(--primary-color); }
        .chip { width: 100%; display: flex; align-items: center; gap: 10px; padding: 10px 12px;
                font: inherit; text-align: left; background: transparent; color: var(--primary-text-color);
                border: none; cursor: pointer; }
        .room.selected .chip { background: color-mix(in srgb, var(--primary-color) 12%, transparent); }
        .chip .order { display: inline-flex; align-items: center; justify-content: center; min-width: 22px;
                       height: 22px; border-radius: 50%; font-size: 0.78rem; font-weight: 700;
                       background: var(--divider-color); color: var(--primary-text-color); }
        .room.selected .chip .order { background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .chip .rname { flex: 1; font-size: 0.95rem; }
        /* auto-FILL, not auto-fit: the field count is now device-driven (a legacy robot
           declares 3, an X-series 6), and auto-fit collapses the empty tracks so a 2-field
           room stretches its selects across the whole card. auto-fill keeps every field the
           same width and left-packed however many there are. */
        .rset { display: grid; grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); gap: 8px 10px;
                padding: 0 12px 12px; }

        /* shared field styling (rooms per-room + zones global selects) */
        .rset-empty { grid-column: 1 / -1; font-size: 0.8rem; color: var(--secondary-text-color); }
        .field { display: flex; flex-direction: column; gap: 2px; }
        .field label { font-size: 0.7rem; color: var(--secondary-text-color); text-transform: uppercase;
                       letter-spacing: 0.03em; }
        .field select { padding: 6px 8px; border-radius: 6px; border: 1px solid var(--divider-color);
                        background: var(--card-background-color); color: var(--primary-text-color); font-size: 0.88rem; }
        .settings { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                    gap: 8px 12px; margin-top: 12px; }

        .parts { display: flex; flex-direction: column; gap: 8px; margin-top: 12px; }
        .parts .empty { padding: 28px 12px; text-align: center; color: var(--secondary-text-color); font-size: 0.9rem; }
        .part { border: 1px solid var(--divider-color); border-radius: 10px; padding: 10px 12px; }
        .p-head { display: flex; align-items: center; gap: 8px; }
        .p-name { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis;
                  white-space: nowrap; font-size: 0.92rem; }
        .p-val { font-size: 0.92rem; font-variant-numeric: tabular-nums; }
        .p-val.dim { color: var(--secondary-text-color); }
        .p-unit { font-size: 0.78rem; color: var(--secondary-text-color); margin-left: 1px; }
        .p-of { font-size: 0.78rem; color: var(--secondary-text-color); }
        .p-reset { padding: 5px 10px; font-size: 0.82rem; background: var(--secondary-background-color);
                   color: var(--primary-text-color); }
        .p-reset.armed { background: var(--error-color, #d32f2f); color: var(--text-primary-color, #fff); }
        .p-reset:disabled { opacity: 0.45; cursor: default; }
        .p-bar { height: 4px; margin-top: 8px; border-radius: 999px; overflow: hidden;
                 background: var(--divider-color); }
        /* The live colour is an inline color-mix ramp (see _wearColor); these are the
           fallback for a browser that does not support it, where the inline declaration
           is dropped and the bar steps instead of easing. */
        .p-fill { height: 100%; border-radius: 999px; background: var(--primary-color);
                  transition: background-color 240ms ease; }
        .p-fill.warn { background: var(--warning-color, #ffa600); }
        .p-fill.low { background: var(--error-color, #d32f2f); }
        .controls { display: flex; align-items: center; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
        .passes { display: flex; align-items: center; gap: 6px; font-size: 0.85rem; color: var(--secondary-text-color); }
        .passes input { width: 52px; padding: 5px 6px; border-radius: 6px; border: 1px solid var(--divider-color);
                        background: var(--card-background-color); color: var(--primary-text-color); font-size: 0.9rem; }
        .status { flex: 1 1 100%; font-size: 0.82rem; color: var(--secondary-text-color); }
        button.clean, button.ghost { font: inherit; padding: 8px 14px; border-radius: 8px; border: none; cursor: pointer; }
        button.clean:disabled { opacity: 0.45; cursor: default; }
        .clean { background: var(--primary-color); color: var(--text-primary-color, #fff); font-weight: 500; }
        .ghost { background: transparent; color: var(--primary-text-color); border: 1px solid var(--divider-color); }
        /* Keyboard focus ring (mouse/touch clicks stay ring-free via :focus-visible). */
        .modebar button:focus-visible, .chip:focus-visible, .gate-ack:focus-visible, .rs-btn:focus-visible,
        .mapreset:focus-visible,
        button.clean:focus-visible, button.ghost:focus-visible,
        select:focus-visible, input:focus-visible {
          outline: 2px solid var(--primary-color); outline-offset: 2px; }
        rect.zone { fill: var(--primary-color); fill-opacity: 0.22; stroke: var(--primary-color); stroke-width: 2; }
        /* A no-go rectangle must not look like a cleaning target. Red matches the
           colour the map itself already draws existing forbidden zones in. */
        rect.zone.nogo { fill: #d32f2f; fill-opacity: 0.20; stroke: #d32f2f; }
        /* A virtual wall is a LINE, drawn in the same red the map uses for the
           walls it already has, dashed so a pending one reads as not-yet-saved. */
        line.wall { stroke: #d32f2f; stroke-width: 3; stroke-linecap: round; }
        line.wall.draft { stroke-dasharray: 6 4; opacity: 0.85; }
        rect.draft { fill: var(--primary-color); fill-opacity: 0.12; stroke: var(--primary-color); stroke-width: 2; stroke-dasharray: 6 4; }
        /* Geometry the device already has: outlined edge-by-edge rather than as a
           polygon, because on the PNG path overlay coordinates are PERCENTAGES and
           only line/rect/circle accept those — <polygon points> does not. */
        line.edge { stroke: #d32f2f; stroke-width: 1.5; opacity: 0.85; }
        line.edge.mop { stroke: #1e88e5; }
        line.edge.doomed { stroke-dasharray: 5 4; opacity: 0.5; }
        /* Delete handle: an x on a corner of every shape the card can remove. */
        g.del circle { fill: var(--card-background-color, #fff); fill-opacity: 0.95;
                       stroke: #d32f2f; stroke-width: 2; }
        g.del text { fill: #d32f2f; font-size: 13px; font-weight: 700; text-anchor: middle; }
        g.del.doomed circle { fill: #d32f2f; fill-opacity: 0.95; }
        g.del.doomed text { fill: var(--text-primary-color, #fff); }
        /* A rotated pending zone: stroked edges rather than a filled <rect>, which cannot
           be rotated in the percentage coordinates the PNG path uses. */
        line.turned { stroke: var(--primary-color); stroke-width: 2.5; stroke-linecap: round; }
        line.turned.nogo { stroke: #d32f2f; }
        g.rot circle, g.mov circle { fill: var(--card-background-color, #fff); fill-opacity: 0.95;
                       stroke: var(--primary-color); stroke-width: 2; }
        g.rot text, g.mov text { fill: var(--primary-color); font-size: 13px; font-weight: 700;
                       text-anchor: middle; }
        /* A shape carrying an unsaved move reads as pending, like a drawn-but-unsaved one. */
        g.mov.staged circle { fill: var(--primary-color); fill-opacity: 0.95; }
        g.mov.staged text { fill: var(--text-primary-color, #fff); }
        line.edge.moved { stroke-dasharray: 4 3; }
        text.num { fill: var(--text-primary-color, #fff); font-size: 13px; font-weight: 700;
                   paint-order: stroke; stroke: var(--primary-color); stroke-width: 3; }
        circle.pin { fill: var(--primary-color); fill-opacity: 0.92; stroke: var(--text-primary-color, #fff); stroke-width: 2; }
        text.pinnum { fill: var(--text-primary-color, #fff); font-size: 12px; font-weight: 700; text-anchor: middle; }
      </style>
      <ha-card>
        <div class="title"></div>
        <div class="robostat">
          <div class="rs-icon"><ha-icon class="rs-state-icon" aria-hidden="true"></ha-icon></div>
          <div class="rs-text" role="status" aria-live="polite">
            <span class="rs-state"></span>
            <span class="rs-detail" hidden></span>
          </div>
          <div class="rs-chips">
            <div class="rs-chip rs-fan" hidden>
              <ha-icon icon="mdi:fan" aria-hidden="true"></ha-icon>
              <span class="rs-fan-txt"></span>
            </div>
            <div class="rs-chip rs-water" hidden>
              <ha-icon icon="mdi:water-outline" aria-hidden="true"></ha-icon>
              <span class="rs-water-txt"></span>
            </div>
            <div class="rs-chip rs-time" hidden>
              <ha-icon icon="mdi:clock-outline" aria-hidden="true"></ha-icon>
              <span class="rs-time-txt"></span>
            </div>
            <div class="rs-chip rs-area" hidden>
              <ha-icon icon="mdi:texture-box" aria-hidden="true"></ha-icon>
              <span class="rs-area-txt"></span>
            </div>
            <div class="rs-chip rs-batt" hidden>
              <ha-icon class="rs-batt-icon" aria-hidden="true"></ha-icon>
              <span class="rs-batt-txt"></span>
            </div>
            <div class="rs-actions">
              <button class="rs-btn rs-start" type="button" aria-label="Start" disabled hidden>
                <ha-icon icon="mdi:play" aria-hidden="true"></ha-icon>
              </button>
              <button class="rs-btn rs-stop" type="button" aria-label="Stop" disabled hidden>
                <ha-icon icon="mdi:stop" aria-hidden="true"></ha-icon>
              </button>
              <button class="rs-btn rs-home" type="button" aria-label="Return to dock" disabled hidden>
                <ha-icon icon="mdi:home-import-outline" aria-hidden="true"></ha-icon>
              </button>
            </div>
          </div>
        </div>
        <div class="modebar" role="group" aria-label="Cleaning mode" hidden>
          <button class="mode-rooms" type="button" aria-pressed="true">Rooms</button>
          <button class="mode-zones" type="button" aria-pressed="false">Zones</button>
          <button class="mode-nogo" type="button" aria-pressed="false">No-go</button>
          <button class="mode-wall" type="button" aria-pressed="false">Wall</button>
          <!-- Deliberately a short label: the bar is a single row on a 300px sidebar
               column, and "Accessories" alone is wider than the four map tabs together. -->
          <button class="mode-parts" type="button" aria-pressed="false">Parts</button>
        </div>
        <div class="mapbar" hidden>
          <label class="mapbar-label">Map</label>
          <select class="mapswitch" aria-label="Switch map"></select>
        </div>
        <div class="map-wrap">
          <img class="map" alt="vacuum map" />
          <canvas class="mapcanvas" role="img" aria-label="vacuum map" hidden></canvas>
          <svg class="overlay" preserveAspectRatio="none"></svg>
          <button class="mapreset" type="button" aria-label="Reset map view" title="Reset map view" hidden>
            <ha-icon icon="mdi:fit-to-screen-outline" aria-hidden="true"></ha-icon>
          </button>
          <div class="nomap" hidden>Waiting for the map… run a clean once (or edit the map in the app) so it renders.</div>
          <div class="gate" role="alert" hidden>
            <span class="gate-msg"></span>
            <button class="gate-ack" type="button">Enable drawing anyway</button>
          </div>
        </div>
        <div class="rooms"></div>
        <div class="parts" hidden></div>
        <div class="settings" hidden></div>
        <div class="controls">
          <label class="passes" hidden>Passes
            <input class="ct" type="number" min="1" max="10" step="1" value="1" aria-label="Passes per zone" />
          </label>
          <button class="ghost clear" type="button">Clear</button>
          <button class="clean" type="button" disabled>Clean</button>
          <span class="status" role="status" aria-live="polite"></span>
        </div>
      </ha-card>
    `;

    this._els = {
      title: this.shadowRoot.querySelector(".title"),
      robostat: this.shadowRoot.querySelector(".robostat"),
      rsIcon: this.shadowRoot.querySelector(".rs-state-icon"),
      rsState: this.shadowRoot.querySelector(".rs-state"),
      rsDetail: this.shadowRoot.querySelector(".rs-detail"),
      rsChips: this.shadowRoot.querySelector(".rs-chips"),
      rsTime: this.shadowRoot.querySelector(".rs-time"),
      rsTimeTxt: this.shadowRoot.querySelector(".rs-time-txt"),
      rsArea: this.shadowRoot.querySelector(".rs-area"),
      rsAreaTxt: this.shadowRoot.querySelector(".rs-area-txt"),
      rsBatt: this.shadowRoot.querySelector(".rs-batt"),
      rsBattIcon: this.shadowRoot.querySelector(".rs-batt-icon"),
      rsBattTxt: this.shadowRoot.querySelector(".rs-batt-txt"),
      rsFan: this.shadowRoot.querySelector(".rs-fan"),
      rsFanTxt: this.shadowRoot.querySelector(".rs-fan-txt"),
      rsWater: this.shadowRoot.querySelector(".rs-water"),
      rsWaterTxt: this.shadowRoot.querySelector(".rs-water-txt"),
      rsStart: this.shadowRoot.querySelector(".rs-start"),
      rsStop: this.shadowRoot.querySelector(".rs-stop"),
      rsHome: this.shadowRoot.querySelector(".rs-home"),
      modebar: this.shadowRoot.querySelector(".modebar"),
      modeRooms: this.shadowRoot.querySelector(".mode-rooms"),
      modeZones: this.shadowRoot.querySelector(".mode-zones"),
      modeNogo: this.shadowRoot.querySelector(".mode-nogo"),
      modeWall: this.shadowRoot.querySelector(".mode-wall"),
      modeParts: this.shadowRoot.querySelector(".mode-parts"),
      parts: this.shadowRoot.querySelector(".parts"),
      mapbar: this.shadowRoot.querySelector(".mapbar"),
      mapswitch: this.shadowRoot.querySelector(".mapswitch"),
      mapWrap: this.shadowRoot.querySelector(".map-wrap"),
      mapreset: this.shadowRoot.querySelector("button.mapreset"),
      img: this.shadowRoot.querySelector("img.map"),
      canvas: this.shadowRoot.querySelector("canvas.mapcanvas"),
      overlay: this.shadowRoot.querySelector("svg.overlay"),
      nomap: this.shadowRoot.querySelector(".nomap"),
      gate: this.shadowRoot.querySelector(".gate"),
      gateMsg: this.shadowRoot.querySelector(".gate-msg"),
      gateAck: this.shadowRoot.querySelector(".gate-ack"),
      rooms: this.shadowRoot.querySelector(".rooms"),
      settings: this.shadowRoot.querySelector(".settings"),
      passes: this.shadowRoot.querySelector(".passes"),
      ct: this.shadowRoot.querySelector("input.ct"),
      clear: this.shadowRoot.querySelector("button.clear"),
      clean: this.shadowRoot.querySelector("button.clean"),
      status: this.shadowRoot.querySelector(".status"),
    };
    this._els.title.textContent = c.title;

    this._els.modeRooms.addEventListener("click", () => this._setMode("rooms"));
    this._els.modeZones.addEventListener("click", () => this._setMode("zones"));
    this._els.modeNogo.addEventListener("click", () => this._setMode("nogo"));
    this._els.modeWall.addEventListener("click", () => this._setMode("wall"));
    this._els.modeParts.addEventListener("click", () => this._setMode("parts"));
    // Delegated: the rows are rebuilt per tick, so per-row listeners would leak a closure each.
    this._els.parts.addEventListener("click", (e) => {
      const btn = e.target && e.target.closest && e.target.closest("[data-reset]");
      if (btn) this._resetAccessory(btn.getAttribute("data-reset"));
    });

    this._els.rsStart.addEventListener("click", () => {
      if (this._dispatching) return; // or the clear below drops what a send is still writing
      this._clearAll();
      this._callVacuum("start", "Starting");
    });
    this._els.rsStop.addEventListener("click", () => this._callVacuum("stop", "Stopping"));
    this._els.rsHome.addEventListener("click", () => this._callVacuum("return_to_base", "Returning to dock"));

    this._els.rsBatt.addEventListener("click", () => {
      const bId = this._resolveSiblingEntity("sensor", "_battery");
      const target = (this._hass && bId && this._hass.states[bId]) ? bId : this._config.vacuum;
      const event = new Event("hass-more-info", { bubbles: true, cancelable: false, composed: true });
      event.detail = { entityId: target };
      this.dispatchEvent(event);
    });
    this._els.rsBatt.style.cursor = "pointer";

    // Disabled until the active map reflects the pick: a second switch mid-transition ghosts.
    this._els.mapswitch.addEventListener("change", () => {
      if (!this._hass || !this._mapSwitchEntity) return;
      const target = this._els.mapswitch.value;
      this._mapSwitchPending = target;
      this._mapSwitchPendingAt = Date.now();
      this._els.mapswitch.disabled = true;
      this._hass.callService("select", "select_option", {
        entity_id: this._mapSwitchEntity,
        option: target,
      });
    });

    // Override the un-grounded window; remembered, so a reload does not re-lock the map.
    this._els.gateAck.addEventListener("click", () => {
      this._frameAck = true;
      this._frameUngrounded = false;
      if (this._lastActiveMap != null) {
        this._saveFrameStore(this._config.vacuum, { map: this._lastActiveMap, grounded: true });
      }
      this._applyGate();
    });

    const ov = this._els.overlay;
    ov.addEventListener("pointerdown", (e) => this._onOverlayDown(e));
    ov.addEventListener("pointermove", (e) => this._onOverlayMove(e));
    ov.addEventListener("pointerup", (e) => this._onOverlayUp(e));
    ov.addEventListener("pointercancel", (e) => this._onOverlayCancel(e));
    // {passive:false} so the handler MAY preventDefault; it only does when the map zooms.
    ov.addEventListener("wheel", (e) => this._onOverlayWheel(e), { passive: false });
    ov.addEventListener("dblclick", () => this._resetMapView());
    this._els.mapreset.addEventListener("click", () => this._resetMapView());

    this._els.ct.addEventListener("change", () => {
      let n = parseInt(this._els.ct.value, 10);
      if (!Number.isFinite(n)) n = 1;
      n = Math.min(Math.max(n, 1), 10);
      this._cleanTimes = n;
      this._els.ct.value = String(n);
    });
    this._els.clear.addEventListener("click", () => this._clearAll());
    this._els.clean.addEventListener("click", () => this._clean());

    this._selectsKey = null;
    this._selectEls = {};
    this._built = true;
    this._applyMapSurface();
    this._applyMode();
  }

  _isDrawMode(mode) {
    const m = mode || this._mode;
    return m === "zones" || m === "nogo" || m === "wall";
  }

  /** A wall is a LINE between the drag endpoints; the others are rectangles. */
  _isLineMode(mode) {
    return (mode || this._mode) === "wall";
  }

  _setMode(mode) {
    if (!["rooms", "zones", "nogo", "wall", "parts"].includes(mode)) return;
    this._mode = mode;
    this._modeWanted = null;
    // Delete/move marks belong to the mode that made them; leaving without saving discards
    // them. Unsaved shapes stay in their own mode's list.
    this._clearDeletions();
    this._statusSticky = false;
    clearTimeout(this._statusTimer);
    this._applyMode();
    this._syncDynamic();
    // On entry: refresh the delete indices and the snapshot dimensions a rotation needs.
    if (this._isDrawMode()) this._fetchEditGeometry();
  }

  // No-go/Wall editing: only a vacuum reporting `nogo_zones_supported` takes set_nogo_zones.
  _nogoSupported() {
    const v = this._hass && this._config && this._hass.states[this._config.vacuum];
    return !!(v && v.attributes && v.attributes.nogo_zones_supported === true);
  }

  // Show/hide each section for the active mode. With no map surface the card is rooms-only.
  _applyMode() {
    if (!this._built) return;
    const hasCam = this._hasMapSurface();
    if (this._isDrawMode() && !hasCam) this._mode = "rooms"; // can't draw without a map
    const nogoOk = hasCam && this._nogoSupported();
    this._nogoOk = nogoOk;
    if ((this._mode === "nogo" || this._mode === "wall") && !nogoOk) {
      this._modeWanted = this._mode; // restored if the vacuum reports support later
      this._mode = "rooms";
    }
    const accessories = this._accessories();
    if (this._mode === "parts" && !accessories.length) this._mode = "rooms";
    const parts = this._mode === "parts";
    const drawing = this._isDrawMode() && hasCam;
    const zones = this._mode === "zones" && hasCam;
    const nogo = this._mode === "nogo" && hasCam;
    const wall = this._mode === "wall" && hasCam;
    const rooms = this._mode === "rooms";
    // A gesture belongs to the mode that began it: a stale _drag pins _refreshMap.
    this._drag = null;
    this._tapStart = null;
    this._ptrs.clear();
    this._nav = null;
    this._shapeDrag = null;

    // Hiding unavailable tabs keeps the bar one row wide on a narrow column.
    this._els.modeZones.hidden = !hasCam;
    this._els.modeNogo.hidden = !nogoOk;
    this._els.modeWall.hidden = !nogoOk;
    this._els.modeParts.hidden = !accessories.length;
    this._els.modebar.hidden = !hasCam && !accessories.length;
    this._els.modeRooms.classList.toggle("on", rooms);
    this._els.modeZones.classList.toggle("on", zones);
    this._els.modeNogo.classList.toggle("on", nogo);
    this._els.modeWall.classList.toggle("on", wall);
    this._els.modeParts.classList.toggle("on", parts);
    this._els.modeRooms.setAttribute("aria-pressed", String(rooms));
    this._els.modeZones.setAttribute("aria-pressed", String(zones));
    this._els.modeNogo.setAttribute("aria-pressed", String(nogo));
    this._els.modeWall.setAttribute("aria-pressed", String(wall));
    this._els.modeParts.setAttribute("aria-pressed", String(parts));

    this._els.mapWrap.style.display = hasCam && !parts ? "" : "none";
    this._els.overlay.hidden = !hasCam || parts;
    this._els.overlay.style.cursor = drawing ? "crosshair" : "pointer";
    this._applyTouchAction();
    this._els.rooms.hidden = !rooms;
    this._els.parts.hidden = !parts;
    this._els.clean.hidden = parts;
    this._els.clear.hidden = parts;
    if (parts) this._renderAccessories();
    this._els.settings.hidden = !zones;
    this._els.passes.hidden = !zones;
    this._applyGate(); // the post-switch pause owns the cursor + banner when active
    this._renderOverlay(); // repaint the correct overlay content for the mode
    // A configured or restored No-go/Wall mode gets the stored shapes too, not only a mode
    // switch. Deferred past the caller's canvas start, whose snapshot brings them.
    if (nogo || wall) queueMicrotask(() => this._loadEditGeometry());
  }

  /** First read of the stored shapes for this config; after a failed one, only entering the
   * mode reads again (`_setMode`). */
  _loadEditGeometry() {
    if (this._editGeo || this._editGeoAsked || this._crStarting) return;
    this._fetchEditGeometry();
  }

  /* Map gestures. The overlay is the single input owner, because only the card knows what one
   * finger means:
   *   rooms   one finger  -> pan; a press that never travels CR_TAP_SLOP_PX is a room tap
   *   zones   one finger  -> draw a zone; panning needs TWO fingers
   *   both    two fingers -> pinch-zoom about the centroid + pan by the centroid's travel
   *           wheel       -> zoom about the pointer (non-passive, so the page does not scroll)
   *           dbl-click   -> reset to fit, as does the reset button
   * Without client render every branch collapses to no pan, no zoom, no preventDefault. */

  // Narrower than `_crProjecting()`: projection only inverts a transform, a gesture changes one.
  _mapGesturesEnabled() {
    const r = this._crRenderer;
    return !!(
      this._crActive &&
      r &&
      typeof r.panBy === "function" &&
      typeof r.zoomBy === "function"
    );
  }

  _mapInputAllowed() {
    return this._built && this._els.nomap.hidden && !this._frameUngrounded;
  }

  _onOverlayDown(e) {
    if (!this._mapInputAllowed()) return;
    // Check delete handles BEFORE capture/seeding, or a tap on one also starts a zero-size zone.
    const target = e.target;
    const handle =
      target && typeof target.closest === "function" ? target.closest("[data-del]") : null;
    if (handle) {
      if (e.cancelable !== false && typeof e.preventDefault === "function") e.preventDefault();
      this._toggleDelete(handle.getAttribute("data-del"));
      return;
    }
    const grip =
      target && typeof target.closest === "function"
        ? target.closest("[data-rot], [data-mov]")
        : null;
    if (grip) {
      if (e.cancelable !== false && typeof e.preventDefault === "function") e.preventDefault();
      const rot = grip.getAttribute("data-rot");
      this._startShapeDrag(rot ? "rotate" : "move", rot || grip.getAttribute("data-mov"), e);
      return;
    }
    // A shape gesture owns the surface and is not in `_ptrs`; else a second finger draws over it.
    if (this._shapeDrag) return;
    const ov = this._els.overlay;
    // Capture, or a drag off the edge of the card strands `_drag`/`_nav` set forever.
    if (ov.setPointerCapture) {
      try {
        ov.setPointerCapture(e.pointerId);
      } catch (_) {
        /* synthetic event, or a pointer already released */
      }
    }
    this._ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });

    if (this._ptrs.size >= 2) {
      // A second finger always means "move the map": whatever the first began is abandoned.
      this._drag = null;
      this._tapStart = null;
      this._nav = this._mapGesturesEnabled() ? { dist: 0, cx: 0, cy: 0, seeded: false } : null;
      this._renderOverlay();
      return;
    }

    this._nav = null;
    if (this._isDrawMode()) {
      const p = this._mapNormFromClient(e.clientX, e.clientY);
      this._drag = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
      this._renderOverlay();
      return;
    }
    // Screen origin decides tap-vs-drag; the normalized one is where the pin goes.
    const n = this._mapNormFromClient(e.clientX, e.clientY);
    this._tapStart = { nx: n.x, ny: n.y, cx: e.clientX, cy: e.clientY, px: e.clientX, py: e.clientY, moved: false };
  }

  _onOverlayMove(e) {
    if (this._shapeDrag) {
      this._driveShapeDrag(e);
      return;
    }
    if (this._ptrs.has(e.pointerId)) this._ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (this._nav && this._ptrs.size >= 2) {
      this._navMove();
      return;
    }
    if (this._drag) {
      const p = this._mapNormFromClient(e.clientX, e.clientY);
      this._drag.x1 = p.x;
      this._drag.y1 = p.y;
      this._renderOverlay();
      return;
    }
    const t = this._tapStart;
    if (!t) return;
    if (Math.hypot(e.clientX - t.cx, e.clientY - t.cy) > CR_TAP_SLOP_PX) t.moved = true;
    // Pan only once the finger has left the tap slop, so a shaky tap still selects a room.
    if (t.moved && this._mapGesturesEnabled()) {
      this._crRenderer.panBy(e.clientX - t.px, e.clientY - t.py);
      t.px = e.clientX;
      t.py = e.clientY;
    }
  }

  _navMove() {
    const nav = this._nav;
    if (!nav || !this._mapGesturesEnabled()) return;
    const pts = Array.from(this._ptrs.values()).slice(0, 2);
    if (pts.length < 2) return;
    const [a, b] = pts;
    const dist = Math.hypot(a.x - b.x, a.y - b.y);
    const cx = (a.x + b.x) / 2;
    const cy = (a.y + b.y) / 2;
    // The first move only seeds the baseline: a pinch factor is a ratio of two samples.
    if (nav.seeded) {
      if (cx !== nav.cx || cy !== nav.cy) this._crRenderer.panBy(cx - nav.cx, cy - nav.cy);
      if (nav.dist > 0 && dist > 0 && dist !== nav.dist) {
        this._crRenderer.zoomBy(dist / nav.dist, cx, cy);
      }
    }
    nav.dist = dist;
    nav.cx = cx;
    nav.cy = cy;
    nav.seeded = true;
  }

  _onOverlayUp(e) {
    this._ptrs.delete(e.pointerId);
    if (this._ptrs.size > 0) {
      // Re-seed on a lift, or the next move reads the missing finger as one enormous pinch.
      if (this._nav) {
        this._nav.seeded = false;
        this._nav.dist = 0;
      }
      this._drag = null;
      this._tapStart = null;
      return;
    }
    if (this._shapeDrag) {
      this._shapeDrag = null;
      this._syncControls();
      return;
    }
    const nav = this._nav;
    this._nav = null;
    if (nav) {
      // The gesture was a map move, not a selection.
      this._drag = null;
      this._tapStart = null;
      this._renderOverlay();
      return;
    }
    if (this._isDrawMode()) {
      this._finishZone();
      return;
    }
    const t = this._tapStart;
    this._tapStart = null;
    if (!t) return;
    const p = this._mapNormFromClient(e.clientX, e.clientY);
    // Tap vs drag in SCREEN pixels when the map can pan: the normalized point travels WITH
    // the map, so a fraction test would read a long pan as a tap. PNG path keeps fractions.
    const tapped = this._mapGesturesEnabled()
      ? !t.moved
      : Math.hypot(p.x - t.nx, p.y - t.ny) < TAP_FRAC;
    // The event rides along: the renderer hit-tests in client coordinates, the pin is normalized.
    if (tapped) this._resolveRoomTap(p.x, p.y, e);
  }

  _onOverlayCancel(e) {
    this._shapeDrag = null;
    if (e && e.pointerId !== undefined) this._ptrs.delete(e.pointerId);
    else this._ptrs.clear();
    this._drag = null;
    this._tapStart = null;
    if (this._ptrs.size === 0) this._nav = null;
    else if (this._nav) {
      this._nav.seeded = false;
      this._nav.dist = 0;
    }
    this._renderOverlay();
  }

  _onOverlayWheel(e) {
    // PNG path: return BEFORE preventDefault so the dashboard still scrolls over the map.
    if (!this._mapGesturesEnabled() || !this._mapInputAllowed()) return;
    if (e.cancelable !== false && typeof e.preventDefault === "function") e.preventDefault();
    this._crRenderer.zoomBy(Math.exp(-e.deltaY * CR_WHEEL_ZOOM), e.clientX, e.clientY);
  }

  _finishZone() {
    if (!this._drag) return;
    const d = this._drag;
    this._drag = null;
    if (this._isLineMode()) {
      // A wall keeps its endpoints exactly as drawn (sorting them would axis-align every
      // diagonal), so the size test is on LENGTH: a vertical wall has zero width and is valid.
      const len = Math.hypot(d.x1 - d.x0, d.y1 - d.y0);
      if (len >= MIN_FRAC && this._zones.length < MAX_ZONES) {
        this._zones.push({ x0: d.x0, y0: d.y0, x1: d.x1, y1: d.y1, line: true });
      }
    } else {
      const x0 = Math.min(d.x0, d.x1), x1 = Math.max(d.x0, d.x1);
      const y0 = Math.min(d.y0, d.y1), y1 = Math.max(d.y0, d.y1);
      if (x1 - x0 >= MIN_FRAC && y1 - y0 >= MIN_FRAC && this._zones.length < MAX_ZONES) {
        this._zones.push({ x0, y0, x1, y1 });
      }
    }
    this._renderOverlay();
    this._syncControls();
  }

  /* Moving and rotating one shape. Grips, not body drags: one finger on the map already means
   * "draw a new shape" here. A pending shape is edited in place; an existing one by staging a
   * transform against its index, since the device has no move operation. */
  _startShapeDrag(action, token, e) {
    const [kind, raw] = String(token || "").split(":");
    const index = Number(raw);
    if (!Number.isInteger(index) || index < 0 || this._frozen(kind, index)) return;
    let center;
    let base = 0;
    if (kind === "new") {
      const z = this._zones[index];
      if (!z) return;
      center = this._shapeCenter(z);
      base = z.rot || 0;
    } else {
      if (!this._moves[kind] || this._del[kind].has(index)) return; // a doomed shape is not edited
      const shape = this._existingShapes().find(
        (s) => s.kind === kind && s.index === index
      );
      if (!shape) return;
      center = shape.center;
      base = 0; // existing rotation accumulates as a delta, so it starts from zero each grab
    }
    const ov = this._els.overlay;
    if (ov.setPointerCapture) {
      try {
        ov.setPointerCapture(e.pointerId);
      } catch (_) {
        /* synthetic event, or a pointer already released */
      }
    }
    const p = this._mapNormFromClient(e.clientX, e.clientY);
    this._shapeDrag = {
      action,
      kind,
      index,
      zone: kind === "new" ? this._zones[index] : null, // a send's success renumbers `_zones`
      prev: p,
      base,
      grip: this._angleAt(center, p),
    };
  }

  _driveShapeDrag(e) {
    const d = this._shapeDrag;
    if (d.zone) d.index = this._zones.indexOf(d.zone); // -1 once gone: ends below
    if (this._frozen(d.kind, d.index)) {
      this._shapeDrag = null; // a send took this shape (or the stored geometry) mid-drag
      return;
    }
    const p = this._mapNormFromClient(e.clientX, e.clientY);
    if (d.kind === "new") {
      const z = this._zones[d.index];
      if (!z) {
        this._shapeDrag = null;
        return;
      }
      if (d.action === "move") {
        // Bounded: the server clamps into 0-1, so a corner pushed outside arrives elsewhere.
        this._applyTranslation(z, p.x - d.prev.x, p.y - d.prev.y);
      } else {
        this._applyRotation(z, d.base + (this._angleAt(this._shapeCenter(z), p) - d.grip));
      }
    } else {
      const shape = this._existingShapes().find(
        (s) => s.kind === d.kind && s.index === d.index
      );
      if (!shape) {
        this._shapeDrag = null;
        return;
      }
      if (d.action === "move") {
        const cm = this._cmDelta(p.x - d.prev.x, p.y - d.prev.y);
        if (cm) this._stageMove(d.kind, d.index, cm.dx, cm.dy, 0);
      } else {
        // Screen angles run clockwise (y down), the world counter-clockwise: negate the delta.
        const turn = this._angleAt(shape.center, p) - d.grip;
        this._stageMove(d.kind, d.index, 0, 0, -turn);
        d.grip = this._angleAt(shape.center, p);
      }
    }
    d.prev = p;
    this._renderOverlay();
  }

  /** Translate a pending shape, unless it would leave the map. See `_applyRotation`. */
  _applyTranslation(z, dnx, dny) {
    if (!dnx && !dny) return true;
    const moved = { ...z, x0: z.x0 + dnx, y0: z.y0 + dny, x1: z.x1 + dnx, y1: z.y1 + dny };
    const pts = this._shapeCorners(moved);
    if (pts.some((p) => p.x < 0 || p.x > 1 || p.y < 0 || p.y > 1)) return false;
    z.x0 = moved.x0;
    z.y0 = moved.y0;
    z.x1 = moved.x1;
    z.y1 = moved.y1;
    return true;
  }

  // Explicit `selects:` if given, else every `select.<vacuum-slug>_*` entity except the room,
  // schedule and map pickers, matched on the WHOLE suffix (the slug may contain "_room").
  _effectiveSelects() {
    if (this._config.selects && this._config.selects.length) return this._config.selects;
    if (!this._hass) return [];
    const slug = (this._config.vacuum || "").split(".")[1] || "";
    if (!slug) return [];
    const prefix = `select.${slug}_`;
    const skip = new Set(["clean_room", "selected_schedule", "switch_map"]);
    return Object.keys(this._hass.states)
      .filter((e) => e.startsWith(prefix) && !skip.has(e.slice(prefix.length)))
      .sort();
  }

  _rebuildSelects(list) {
    const wrap = this._els.settings;
    wrap.innerHTML = "";
    this._selectEls = {};
    this._optSig = {};
    for (const eid of list || []) {
      const field = document.createElement("div");
      field.className = "field";
      const label = document.createElement("label");
      const sel = document.createElement("select");
      sel.dataset.entity = eid;
      sel.addEventListener("change", () => {
        if (!this._hass) return;
        this._hass.callService("select", "select_option", { entity_id: eid, option: sel.value });
      });
      field.appendChild(label);
      field.appendChild(sel);
      wrap.appendChild(field);
      this._selectEls[eid] = { field, label, sel };
    }
  }

  _syncZoneSelects() {
    const hass = this._hass;
    const eff = this._effectiveSelects();
    const key = eff.join(",");
    if (key !== this._selectsKey) {
      this._rebuildSelects(eff);
      this._selectsKey = key;
    }
    for (const [eid, refs] of Object.entries(this._selectEls || {})) {
      const st = hass.states[eid];
      if (!st) {
        refs.field.style.display = "none";
        continue;
      }
      refs.field.style.display = "";
      const labelTxt = (st.attributes && st.attributes.friendly_name) || eid;
      refs.label.textContent = labelTxt;
      refs.sel.setAttribute("aria-label", labelTxt);
      const opts = (st.attributes && st.attributes.options) || [];
      // Delimiter-joined so ["ab","c"] and ["a","bc"] give different signatures.
      const sig = opts.join("\n");
      if (sig !== this._optSig[eid]) {
        refs.sel.innerHTML = opts.map((o) => `<option value="${esc(o)}">${esc(o)}</option>`).join("");
        this._optSig[eid] = sig;
      }
      if (this.shadowRoot.activeElement !== refs.sel) refs.sel.value = st.state;
    }
  }

  // `rooms` and `segments` carry the same shape, prefer `rooms`. Room ids are numeric.
  _rooms() {
    const v = this._hass && this._hass.states[this._config.vacuum];
    const a = (v && v.attributes) || {};
    const raw = Array.isArray(a.rooms) && a.rooms.length ? a.rooms : Array.isArray(a.segments) ? a.segments : [];
    const out = [];
    for (const r of raw) {
      if (!r || r.id == null) continue;
      const id = Number(r.id);
      if (!Number.isFinite(id)) continue;
      out.push({ id, name: r.name || `Room ${r.id}` });
    }
    return out;
  }

  // [["Default", ""], [label, value], ...]: the VALUE is the device's own spelling, verbatim.
  _optionPairs(list) {
    return [["Default", ""]].concat(list.map((o) => [String(o).replace(/_/g, " "), String(o)]));
  }

  _selectOptions(suffix, fallbackPairs) {
    if (!this._hass || !this._hass.states) return fallbackPairs;
    // Slug hit (O(1)) before the sibling scan: this runs per hass tick.
    const slug = (this._config.vacuum || "").split(".")[1] || "";
    const eid =
      (slug && this._hass.states[`select.${slug}_${suffix}`] && `select.${slug}_${suffix}`) ||
      this._resolveSiblingEntity("select", `_${suffix}`);
    const s = eid && this._hass.states[eid];
    if (s && s.attributes && Array.isArray(s.attributes.options) && s.attributes.options.length) {
      return this._optionPairs(s.attributes.options);
    }
    return fallbackPairs;
  }

  _fanOptions() {
    const v = this._hass && this._hass.states[this._config.vacuum];
    const list = (v && v.attributes && v.attributes.fan_speed_list) || DEFAULT_FANS;
    return this._optionPairs(list);
  }

  // Per-room option vocabularies for THIS device: [[label, value], ...] per field, null for a
  // field the device does not declare (which renders no control). Sources in order:
  // vacuum.attributes.room_clean_options (authoritative — an absent key means the firmware
  // would ignore the field), the matching global select's options, then the built-ins.
  // `passes` is a repeat COUNT, so it is a plain boolean; a declared `edge` maps to EDGE_OPTS.
  _roomFieldOptions() {
    const v = this._hass && this._hass.states[this._config.vacuum];
    const declared = v && v.attributes && v.attributes.room_clean_options;
    // Memoized on the vacuum STATE OBJECT identity; the fallback branch is NOT (other inputs).
    if (declared && this._roomOptsFor === v) return this._roomOptsMemo;
    // hide_edge_mop is a legacy dashboard option: a force-hide override, never a force-show.
    const edgePairs = this._config.hide_edge_mop ? null : EDGE_OPTS;
    if (declared && typeof declared === "object" && !Array.isArray(declared)) {
      const f = (key) =>
        Array.isArray(declared[key]) && declared[key].length ? this._optionPairs(declared[key]) : null;
      this._roomOptsFor = v;
      this._roomOptsMemo = {
        mode: f("clean_mode"),
        fan: f("fan_speed"),
        water: f("water_level"),
        int: f("clean_intensity"),
        edge: declared.edge_mopping ? edgePairs : null,
        passes: !!declared.clean_times,
      };
      return this._roomOptsMemo;
    }
    return {
      mode: this._selectOptions("cleaning_mode", MODE_OPTS),
      fan: this._fanOptions(),
      water: this._selectOptions("water_level", WATER_OPTS),
      int: this._selectOptions("cleaning_intensity", INTENSITY_OPTS),
      edge: edgePairs,
      passes: true,
    };
  }

  _defaultRoomCfg() {
    return { clean_mode: "", fan_speed: "", water_level: "", clean_intensity: "", clean_times: 1, edge: "" };
  }

  // Room list + per-room option vocabularies; a change here forces a full rebuild.
  _computeRoomIdKey(rooms) {
    const sig = (opts) => (opts ? opts.map((o) => String(o[0]) + "=" + String(o[1])).join("|") : "");
    const o = this._roomFieldOptions();
    const optKey = [sig(o.mode), sig(o.fan), sig(o.water), sig(o.int), sig(o.edge), o.passes ? "1" : "0"].join(
      "~"
    );
    return rooms.map((r) => r.id).join(",") + "!" + optKey;
  }

  // Repaint the room list DOM unconditionally; _syncDynamic owns the change detection.
  _rebuildRooms(rooms) {
    const wrap = this._els.rooms;
    if (!wrap) return;
    this._lastRooms = rooms;
    wrap.innerHTML = "";
    this._roomEls = {};

    if (!rooms.length) {
      wrap.innerHTML =
        '<div class="empty">No rooms found yet — run a clean once (or open the Eufy app) so the map and rooms load.</div>';
      return;
    }
    // Device-declared field set: an undeclared field renders nothing at all.
    const opts = this._roomFieldOptions();

    const field = (labelTxt, cls, pairs) =>
      pairs
        ? `<div class="field"><label>${labelTxt}</label><select class="${cls}" aria-label="${esc(labelTxt)}">${optionsHtml(pairs, "")}</select></div>`
        : "";
    const passesField = opts.passes
      ? `<div class="field"><label>Passes</label><select class="f-passes" aria-label="Passes">${PASSES_OPTS.map(
          (n) => `<option value="${n}">${n}</option>`
        ).join("")}</select></div>`
      : "";
    const fields =
      field("Mode", "f-mode", opts.mode) +
      field("Suction", "f-fan", opts.fan) +
      field("Water", "f-water", opts.water) +
      field("Intensity", "f-int", opts.int) +
      passesField +
      field("Edge mop", "f-edge", opts.edge);
    const body = fields || '<div class="rset-empty">No adjustable settings for this room.</div>';

    for (const room of rooms) {
      const id = room.id;
      if (!(id in this._roomCfg)) this._roomCfg[id] = this._defaultRoomCfg();
      const el = document.createElement("div");
      el.className = "room";
      el.setAttribute("role", "group");
      el.setAttribute("aria-label", room.name);
      el.innerHTML = `
        <button class="chip" type="button" aria-expanded="false">
          <span class="order"></span>
          <span class="rname"></span>
        </button>
        <div class="rset" hidden>${body}</div>`;
      const rname = el.querySelector(".rname");
      rname.textContent = room.name;
      const refs = {
        el,
        rname,
        chip: el.querySelector(".chip"),
        order: el.querySelector(".order"),
        rset: el.querySelector(".rset"),
        mode: el.querySelector(".f-mode"),
        fan: el.querySelector(".f-fan"),
        water: el.querySelector(".f-water"),
        int: el.querySelector(".f-int"),
        passes: el.querySelector(".f-passes"),
        edge: el.querySelector(".f-edge"),
      };
      refs.rset.id = `ecc-rset-${id}`;
      refs.chip.setAttribute("aria-controls", refs.rset.id);
      refs.chip.addEventListener("click", () => this._toggleRoom(id));
      // Every field is optional: an unguarded listener on an undeclared one kills the list.
      const on = (el, apply) => el && el.addEventListener("change", () => apply(el.value));
      on(refs.mode, (val) => (this._roomCfg[id].clean_mode = val));
      on(refs.fan, (val) => (this._roomCfg[id].fan_speed = val));
      on(refs.water, (val) => (this._roomCfg[id].water_level = val));
      on(refs.int, (val) => (this._roomCfg[id].clean_intensity = val));
      on(refs.passes, (val) => (this._roomCfg[id].clean_times = parseInt(val, 10) || 1));
      on(refs.edge, (val) => (this._roomCfg[id].edge = val));
      wrap.appendChild(el);
      this._roomEls[id] = refs;
    }
    this._renderSelection();
  }

  // Paint selection + restore saved per-room values; never on a hass tick (open dropdowns).
  _renderSelection() {
    for (const room of this._lastRooms) {
      const refs = this._roomEls[room.id];
      if (!refs) continue;
      const idx = this._sel.indexOf(room.id);
      const on = idx >= 0;
      refs.el.classList.toggle("selected", on);
      refs.order.textContent = on ? String(idx + 1) : "";
      refs.rset.hidden = !on;
      refs.chip.setAttribute("aria-expanded", String(on));
      const c = this._roomCfg[room.id] || this._defaultRoomCfg();
      if (refs.mode) refs.mode.value = c.clean_mode;
      if (refs.fan) refs.fan.value = c.fan_speed;
      if (refs.water) refs.water.value = c.water_level;
      if (refs.int) refs.int.value = c.clean_intensity;
      if (refs.passes) refs.passes.value = String(c.clean_times || 1);
      if (refs.edge) refs.edge.value = c.edge;
    }
  }

  _toggleRoom(id) {
    const i = this._sel.indexOf(id);
    if (i >= 0) this._sel.splice(i, 1);
    else this._sel.push(id);
    this._renderSelection();
    this._renderOverlay(); // refresh pins + order numbers on the map
    this._syncControls();
  }

  // Resolve a tap to a room and toggle it: locally off the renderer's room mask, else via
  // `robovac_mqtt.room_at_point`. Room id 0 is a REAL id — test against null, never truthiness.
  async _resolveRoomTap(nx, ny, ev) {
    if (!this._hass || this._frameUngrounded) return;
    let rid = null;
    if (this._crActive && this._crRenderer && ev) {
      const hit = this._crRenderer.roomAt(ev.clientX, ev.clientY);
      rid = hit === undefined || hit === null ? null : Number(hit);
      if (!Number.isFinite(rid)) rid = null;
      return this._applyRoomTap(rid, nx, ny);
    }
    try {
      const r = await this._hass.callService(
        "robovac_mqtt",
        "room_at_point",
        { x: nx, y: ny },
        { entity_id: this._config.vacuum },
        false,
        true
      );
      // Entity-service responses are keyed by entity_id: { response: { "<id>": {...} } }.
      const resp = (r && r.response) || {};
      const entry =
        resp[this._config.vacuum] ||
        (resp.room_id !== undefined ? resp : Object.values(resp)[0]) ||
        {};
      // "No room there" is null/"" from the service; room id 0 is a real room.
      const raw = entry.room_id;
      rid = raw == null || raw === "" ? null : Number(raw);
      if (!Number.isFinite(rid)) rid = null;
    } catch (err) {
      this._setStatus(`Tap lookup failed: ${err && err.message ? err.message : err}`);
      return;
    }
    this._applyRoomTap(rid, nx, ny);
  }

  _applyRoomTap(rid, nx, ny) {
    const room = rid != null ? this._lastRooms.find((r) => r.id === rid) : null;
    if (!room) {
      this._setStatus("No room there — tap inside a room.");
      return;
    }
    this._roomPins[rid] = { nx, ny };
    this._toggleRoom(rid);
    if (this._sel.includes(rid)) {
      this._setStatus(`${room.name} added`);
    } else {
      delete this._roomPins[rid];
      this._renderOverlay();
      this._setStatus(`${room.name} removed`);
    }
  }

  // Drop the "scan found nothing" markers; only a registry change can turn a miss into a hit.
  _invalidateSiblingMisses() {
    for (const k of Object.keys(this._entCache)) {
      if (k.endsWith(":miss")) delete this._entCache[k];
    }
  }

  // Resolve a per-vacuum entity by DEVICE SIBLING first: a renamed setup has no reliable slug.
  _resolveSiblingEntity(domain, suffix) {
    const hass = this._hass;
    const vac = this._config && this._config.vacuum;
    if (!hass || !vac) return null;
    const states = hass.states || {};
    const cacheKey = `sib:${domain}:${suffix}`;
    const cached = this._entCache[cacheKey];
    if (cached && states[cached] !== undefined) return cached; // still valid — skip the scan
    const ents = hass.entities || {};
    // Cache the MISS too, or the full registry scan re-runs on every `set hass`. The marker
    // guards only that O(n) scan; the O(1) `states[guess]` fallback below always runs.
    const missKey = `${cacheKey}:miss`;
    const scanned = this._entCache[missKey] !== undefined;
    const devId = ents[vac] && ents[vac].device_id;
    const slug = vac.split(".")[1] || "";
    if (devId && !scanned) {
      // A suffix match is not unique ("_cleaning_time" also ends "_total_cleaning_time"):
      // prefer the exact slug id, then the shortest.
      let best = null;
      for (const [eid, e] of Object.entries(ents)) {
        if (!e || e.device_id !== devId || !eid.startsWith(`${domain}.`) || !eid.endsWith(suffix)) continue;
        if (eid === `${domain}.${slug}${suffix}`) {
          best = eid;
          break;
        }
        if (!best || eid.length < best.length) best = eid;
      }
      if (best) {
        this._entCache[cacheKey] = best;
        delete this._entCache[missKey];
        return best;
      }
    }
    const guess = `${domain}.${slug}${suffix}`;
    if (states[guess]) {
      this._entCache[cacheKey] = guess;
      delete this._entCache[missKey];
      return guess;
    }
    // Re-armed whenever the registry changes shape, so an entity created later is found.
    this._entCache[missKey] = 1;
    return null;
  }

  _readPose() {
    const st = this._hass && this._hass.states;
    if (!st) return null;
    const xid = this._resolveSiblingEntity("sensor", "_robot_position_x_raw");
    const yid = this._resolveSiblingEntity("sensor", "_robot_position_y_raw");
    const xs = xid && st[xid];
    const ys = yid && st[yid];
    if (!xs || !ys) return null;
    const x = Number(xs.state);
    const y = Number(ys.state);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    return { x, y };
  }

  // Per-vacuum localStorage memory so the un-grounded state survives a reload. Best-effort.
  _frameKey(vac) {
    return `eufy-clean-card:frame:${vac}`;
  }
  _loadFrameStore(vac) {
    try {
      return JSON.parse(localStorage.getItem(this._frameKey(vac))) || {};
    } catch (e) {
      return {};
    }
  }
  _saveFrameStore(vac, store) {
    try {
      localStorage.setItem(this._frameKey(vac), JSON.stringify(store));
    } catch (e) {
      /* private mode / quota — best effort */
    }
    this._frameStore = store;
  }

  // Is the coordinate frame grounded on the ACTIVE map (mirrors the server-side gate)? A
  // switch is seen on the Active Map sensor, cleared by a pose move, a clean, or the override.
  _updateFrameGate() {
    const hass = this._hass;
    const vac = this._config && this._config.vacuum;
    if (!hass || !vac) return;
    const amId = this._resolveSiblingEntity("sensor", "_active_map");
    const am = amId && hass.states[amId];
    const token = am ? am.state : null;
    if (token == null || token === "unknown" || token === "unavailable" || token === "") {
      this._frameUngrounded = false; // no active-map signal -> nothing to reason about
      return;
    }
    if (this._frameStore === undefined) this._frameStore = this._loadFrameStore(vac);

    const lock = () => {
      this._frameUngrounded = true;
      this._frameAck = false;
      this._poseAtSwitch = this._readPose();
      this._clearPending(); // old-map frame — drop drawn shapes so nothing stale dispatches
      this._drag = null;
      if (this._built) this._renderOverlay();
    };

    if (this._lastActiveMap == null) {
      // First evaluation this session — reconcile against the persisted grounded map.
      const store = this._frameStore || {};
      if (store.map === undefined) {
        this._frameUngrounded = false; // brand-new card: trust the docked robot's current map
      } else if (store.map === token && store.grounded) {
        this._frameUngrounded = false; // same map we last confirmed grounded on
      } else {
        lock(); // active map differs from the last confirmed grounding (maybe while closed)
      }
    } else if (token !== this._lastActiveMap) {
      lock(); // live switch while the card is open
    }
    this._lastActiveMap = token;

    // Clear once the robot has re-localized (moved / cleaning) or the user overrode.
    if (this._frameUngrounded && !this._frameAck) {
      const vs = hass.states[vac];
      const moving = vs && (vs.state === "cleaning" || vs.state === "returning");
      const now = this._readPose();
      // Pose may have been unavailable when lock() ran, so anchor lazily on the first pose.
      if (!this._poseAtSwitch && now) this._poseAtSwitch = now;
      const p0 = this._poseAtSwitch;
      const moved = now && p0 && Math.hypot(now.x - p0.x, now.y - p0.y) > POSE_MOVE_THRESHOLD;
      if (moving || moved) this._frameUngrounded = false;
    }
    if (this._frameAck) this._frameUngrounded = false;

    const grounded = !this._frameUngrounded;
    const cur = this._frameStore || {};
    if (cur.map !== token || cur.grounded !== grounded) {
      this._saveFrameStore(vac, { map: token, grounded });
    }
  }

  _applyGate() {
    if (!this._built) return;
    const gated = !!this._frameUngrounded;
    this._els.gate.hidden = !gated;
    if (gated) {
      this._drag = null;
      this._els.gateMsg.textContent =
        "Map not localized yet — drawing and tap-select are paused. Move the robot or run a clean.";
      this._els.overlay.style.cursor = "not-allowed";
    } else {
      const zones = this._isDrawMode() && this._hasMapSurface();
      this._els.overlay.style.cursor = zones ? "crosshair" : "pointer";
    }
  }

  // Switch Map select: device sibling (its slug can differ), slug guess, lone _switch_map.
  _resolveMapSwitchEntity() {
    const hass = this._hass;
    if (!hass) return null;
    const vac = this._config.vacuum;
    const states = hass.states || {};
    const cached = this._entCache.mapswitch;
    if (cached && states[cached] !== undefined) return cached; // still valid — skip the scan
    const remember = (eid) => {
      if (eid) this._entCache.mapswitch = eid;
      return eid;
    };
    const ents = hass.entities || {};
    const vreg = ents[vac];
    const devId = vreg && vreg.device_id;
    if (devId) {
      for (const [eid, e] of Object.entries(ents)) {
        if (!e || e.device_id !== devId || !eid.startsWith("select.")) continue;
        if (eid.endsWith("_switch_map")) return remember(eid);
        const st = states[eid];
        const fn = st && st.attributes && st.attributes.friendly_name;
        if (fn && /switch map/i.test(fn)) return remember(eid);
      }
    }
    const slug = (vac || "").split(".")[1] || "";
    if (slug && states[`select.${slug}_switch_map`]) return remember(`select.${slug}_switch_map`);
    const all = Object.keys(states).filter((e) => e.startsWith("select.") && e.endsWith("_switch_map"));
    return all.length === 1 ? remember(all[0]) : null;
  }

  // Switch Map picker; shown only when it resolves, is available and offers >1 map.
  _syncMapSwitch() {
    const hass = this._hass;
    const eid = this._resolveMapSwitchEntity();
    const st = eid && hass.states[eid];
    const opts = (st && st.attributes && st.attributes.options) || [];
    const avail = !!st && st.state !== "unknown" && st.state !== "unavailable";
    if (!st || !avail || opts.length < 2) {
      this._mapSwitchEntity = null;
      this._mapSwitchPending = null;
      this._els.mapswitch.disabled = false;
      this._els.mapbar.hidden = true;
      return;
    }
    this._mapSwitchEntity = eid;
    this._els.mapbar.hidden = false;
    const sig = opts.join("\n");
    if (sig !== this._mapSwitchSig) {
      this._els.mapswitch.innerHTML = opts.map((o) => `<option value="${esc(o)}">${esc(o)}</option>`).join("");
      this._mapSwitchSig = sig;
    }
    // Hold the dropdown disabled on the target until the active map reflects it, or 8s.
    if (this._mapSwitchPending != null) {
      const settled = st.state === this._mapSwitchPending || Date.now() - this._mapSwitchPendingAt > 8000;
      if (!settled) {
        this._els.mapswitch.disabled = true;
        if (this._els.mapswitch.value !== this._mapSwitchPending) this._els.mapswitch.value = this._mapSwitchPending;
        return;
      }
      this._mapSwitchPending = null;
      this._els.mapswitch.disabled = false;
    } else if (this._els.mapswitch.disabled) {
      this._els.mapswitch.disabled = false; // nothing in flight — never leave it stranded
    }
    if (this._els.mapswitch.value !== st.state) this._els.mapswitch.value = st.state;
  }

  // Shows "Unavailable" rather than hiding, so a mistyped `vacuum:` is visible. Battery
  // prefers the sibling sensor (HA deprecated the attribute); charging falls back to docked.
  _syncRoboStatus() {
    const els = this._els;
    if (!els || !els.robostat) return;
    const hass = this._hass;
    const v = hass && hass.states[this._config.vacuum];
    const state = v ? String(v.state) : "unavailable";
    const a = (v && v.attributes) || {};
    const live = v && state !== "unavailable";

    const [icon, label, tone] = VAC_STATE_UI[state] || ["mdi:robot-vacuum", titleCase(state), "idle"];
    els.rsIcon.setAttribute("icon", icon);
    els.rsState.textContent = label;
    els.robostat.className = `robostat on-${tone}`;

    // Secondary line: a live error wins, then task status. error_code 0 means "no error".
    const code = Number(a.error_code);
    const hasErr = Number.isFinite(code) ? code > 0 : !!a.error_code;
    const errTxt = hasErr ? a.error_message || `Error ${a.error_code}` : "";
    const task = a.task_status || a.status || "";
    const detail = errTxt || (task ? titleCase(task) : "");
    els.rsDetail.textContent = detail; // textContent: device/cloud text is never parsed as HTML
    els.rsDetail.hidden = !detail;

    // Hidden when neither the sensor nor the attribute reports a number.
    const lvl = live ? this._batteryLevel(v) : null;
    els.rsBatt.hidden = lvl == null;
    if (lvl != null) {
      const charging = this._isCharging(v, lvl);
      const pct = Math.round(lvl);
      els.rsBattIcon.setAttribute("icon", batteryIcon(lvl, charging));
      els.rsBattTxt.textContent = `${pct}%`;
      // The glyph is aria-hidden, so label the group itself.
      els.rsBatt.setAttribute("aria-label", `Battery ${pct}%${charging ? ", charging" : ""}`);
    }

    // Run settings, only while a run is on. The cleaning mode (novel devices) hides the half
    // that is not running instead of taking a chip of its own; the legacy T2266 has no mode or
    // water select, so it shows suction alone.
    const running = live && RUN_STATES.has(state);
    const mode = running ? this._siblingValue("select", "_cleaning_mode").toLowerCase() : "";
    const fan = running && mode !== "mop" && a.fan_speed && a.fan_speed !== "Off" ? String(a.fan_speed) : "";
    const water = running && mode !== "vacuum" ? this._siblingValue("select", "_water_level") : "";
    this._syncSettingChip(els.rsFan, els.rsFanTxt, fan, "Suction");
    this._syncSettingChip(els.rsWater, els.rsWaterTxt, water, "Water level");

    const stale = tone !== "active";
    this._syncStatChip(els.rsTime, els.rsTimeTxt, "_cleaning_time", "Cleaning time", stale, live);
    this._syncStatChip(els.rsArea, els.rsAreaTxt, "_cleaning_area", "Cleaned area", stale, live);

    // Disabled rather than hidden, so the buttons keep a fixed position. A missing
    // supported_features is unknown, not unsupported.
    const feats = Number(a.supported_features);
    const known = Number.isFinite(feats);
    const canStart = !known || (feats & VAC_FEATURE.START) !== 0;
    const canStop = !known || (feats & VAC_FEATURE.STOP) !== 0;
    const canHome = !known || (feats & VAC_FEATURE.RETURN_HOME) !== 0;
    const [startOn, stopOn, homeOn] = VAC_BUTTON_STATES[state] || [false, false, false];
    els.rsStart.hidden = !canStart;
    els.rsStop.hidden = !canStop;
    els.rsHome.hidden = !canHome;
    els.rsStart.disabled = !live || !startOn || this._dispatching;
    els.rsStop.disabled = !live || !stopOn || this._dispatching;
    els.rsHome.disabled = !live || !homeOn || this._dispatching;
  }

  // Battery from the `_battery` sibling sensor (the vacuum entity declares no battery), else
  // the deprecated attribute; null when neither is a number.
  _batteryLevel(v) {
    const id = this._resolveSiblingEntity("sensor", "_battery");
    const st = id && this._hass.states[id];
    const raw = st ? st.state : v && v.attributes && v.attributes.battery_level;
    const lvl = raw === null || raw === undefined || raw === "" ? NaN : Number(raw);
    return Number.isFinite(lvl) ? lvl : null;
  }

  // The `_charging` sibling sensor, else docked below a full (known) battery.
  _isCharging(v, lvl) {
    const id = this._resolveSiblingEntity("binary_sensor", "_charging");
    const st = id && this._hass.states[id];
    if (st) return st.state === "on";
    return !!v && v.state === "docked" && lvl != null && lvl < 100;
  }

  // A sibling entity's state, or "" when it is missing, unknown or unavailable.
  _siblingValue(domain, suffix) {
    const id = this._resolveSiblingEntity(domain, suffix);
    const st = id && this._hass.states[id];
    const v = st ? String(st.state) : "";
    return v === "unknown" || v === "unavailable" ? "" : v;
  }

  // One run-setting chip; an empty value hides it. textContent: option labels are device text.
  _syncSettingChip(chip, txt, value, name) {
    chip.hidden = !value;
    if (!value) return;
    txt.textContent = value;
    chip.setAttribute("aria-label", `${name}: ${value}`);
  }

  // One session-stat chip. Hidden when the sensor is missing, not a number, or exactly 0.
  _syncStatChip(chip, txt, suffix, name, stale, live) {
    const hass = this._hass;
    const id = live ? this._resolveSiblingEntity("sensor", suffix) : null;
    const st = id && hass.states[id];
    const val = st ? Number(st.state) : NaN;
    if (!st || !Number.isFinite(val) || val === 0) {
      chip.hidden = true;
      return;
    }
    const shown = formatMeasure(val, (st.attributes && st.attributes.unit_of_measurement) || "");
    chip.hidden = false;
    txt.textContent = shown;
    // Chips sit OUTSIDE the .rs-text live region, or every tick is announced. The glyph is
    // aria-hidden, so the group carries the label.
    chip.setAttribute("aria-label", stale ? `${name}, last run: ${shown}` : `${name}: ${shown}`);
    if (stale) chip.setAttribute("title", "Last run");
    else chip.removeAttribute("title");
  }

  async _callVacuum(service, saying) {
    if (!this._hass || this._dispatching) return;
    this._dispatching = true;
    try {
      this._syncControls();
      await this._hass.callService("vacuum", service, { entity_id: this._config.vacuum });
      this._setStatus(saying);
    } catch (err) {
      this._setStatus(`Failed: ${err && err.message ? err.message : err}`);
    } finally {
      this._dispatching = false;
      this._syncControls();
    }
  }

  _syncDynamic() {
    const hass = this._hass;
    if (!hass || !this._built) return;

    this._updateFrameGate();

    // The vacuum's state (and so its No-go capability) can arrive after the card is built.
    const nogoOk = this._hasMapSurface() && this._nogoSupported();
    if (nogoOk !== this._nogoOk) {
      if (nogoOk && this._modeWanted && this._mode === "rooms") this._mode = this._modeWanted;
      this._modeWanted = null;
      this._applyMode();
    }

    // Grid colours are baked into the renderer's static layer, so push a theme flip in
    // explicitly (it re-rasterises), and only on a real change.
    if (this._crRenderer) {
      const v = hass.states[this._config.vacuum];
      if (v) {
        const charging = this._isCharging(v, this._batteryLevel(v));
        // "returning" is not docked: that leg is pure transit, when the robot marker matters
        // most. `idle` is standby wherever the robot stopped: undefined leaves it to the
        // renderer's dock-distance test.
        const docked = v.state === "docked" || charging ? true : v.state === "idle" ? undefined : false;
        this._crRenderer.setDockStatus(docked, charging);
      }
      this._syncRendererTheme();
    }

    // backdrop: refresh on a camera change or first paint; _startPolling covers the rest.
    if (this._pngActive()) {
      this._applyMapSurface(); // owns <img>/nomap visibility for both surfaces
      const cam = hass.states[this._config.camera];
      const lu = (cam && cam.last_updated) || "";
      // Defer while dragging: _refreshMap no-ops mid-drag, and the token would be spent.
      if (!this._els.img.hidden && (lu !== this._lastCamUpdate || !this._lastImgSrc) && !this._drag) {
        this._lastCamUpdate = lu;
        this._refreshMap();
      }
    }

    // Full rebuild only when the room-ID set or options change; a rename relabels in place so
    // an open per-room dropdown is not torn down mid-interaction.
    const rooms = this._rooms();
    if (this._crRenderer) this._crRenderer.setRooms(rooms);
    const idKey = this._computeRoomIdKey(rooms);
    if (idKey !== this._roomIdKey) {
      this._lastRooms = rooms;
      const ids = new Set(rooms.map((r) => r.id));
      // Room ids are numeric but object keys are strings, so coerce before the Set check.
      this._sel = this._sel.filter((id) => ids.has(id));
      for (const k of Object.keys(this._roomCfg)) if (!ids.has(Number(k))) delete this._roomCfg[k];
      for (const k of Object.keys(this._roomPins)) if (!ids.has(Number(k))) delete this._roomPins[k];
      this._rebuildRooms(rooms);
      this._roomIdKey = idKey;
    } else {
      for (const room of rooms) {
        const prev = this._lastRooms.find((r) => r.id === room.id);
        const refs = this._roomEls[room.id];
        if (prev && refs && prev.name !== room.name) {
          refs.rname.textContent = room.name;
          refs.el.setAttribute("aria-label", room.name);
        }
      }
      this._lastRooms = rooms;
    }

    if (this._mode === "zones" && this._hasMapSurface()) this._syncZoneSelects();
    if (this._mode === "parts") this._renderAccessories();

    this._syncControls();
    this._syncMapSwitch();
    this._applyGate();
  }

  _syncControls() {
    this._syncRoboStatus(); // Start/Stop/Home follow `_dispatching`
    if (this._mode === "wall" || this._mode === "nogo") {
      // Adds and deletes ride the same replace-all write, so one button commits both.
      const wall = this._mode === "wall";
      const n = this._zones.length;
      const d = this._deletionCount();
      const m = this._moveCount();
      const noun = wall ? "wall" : "no-go zone";
      const plural = (k, word) => `${k} ${word}${k > 1 ? "s" : ""}`;
      this._els.clean.disabled = (n === 0 && d === 0 && m === 0) || this._dispatching;
      const verbs = [];
      if (n) verbs.push(`save ${n}`);
      if (m) verbs.push(`move ${m}`);
      if (d) verbs.push(`delete ${d}`);
      this._els.clean.textContent = !verbs.length
        ? "Save"
        : verbs.length === 1 && n
        ? `Save ${plural(n, noun)}`
        : verbs.length === 1 && d
        ? `Delete ${plural(d, noun)}`
        : verbs.length === 1
        ? `Move ${plural(m, noun)}`
        : `${verbs.join(" + ").replace(/^./, (c) => c.toUpperCase())}`;
      if (!this._statusSticky) {
        const bits = [];
        if (n) bits.push(`${plural(n, noun)} to add`);
        if (m) bits.push(`${m} to move`);
        if (d) bits.push(`${d} to delete`);
        this._els.status.textContent = bits.length
          ? `${bits.join(", ")} — the rest is kept.`
          : wall
          ? "Drag a line across a doorway; drag \u2724 to move one, \u21bb to turn it, x to delete."
          : "Drag on the map to block off an area; drag \u2724 to move one, \u21bb to turn it, x to delete.";
      }
    } else if (this._mode === "parts") {
      if (!this._statusSticky) {
        this._els.status.textContent = "Hours left per part — reset a counter after replacing one.";
      }
    } else if (this._mode === "zones") {
      const n = this._zones.length;
      this._els.clean.disabled = n === 0 || this._dispatching;
      this._els.clean.textContent = n > 0 ? `Clean ${n} zone${n > 1 ? "s" : ""}` : "Clean";
      if (!this._statusSticky) {
        this._els.status.textContent = n ? `${n}/${MAX_ZONES} zones drawn` : "Drag on the map to draw a zone.";
      }
    } else {
      const n = this._sel.length;
      this._els.clean.disabled = n === 0 || this._dispatching;
      this._els.clean.textContent = n > 0 ? `Clean ${n} room${n > 1 ? "s" : ""}` : "Clean";
      if (!this._statusSticky) {
        const how = this._hasMapSurface() ? "Tap rooms on the map or list" : "Tap rooms to select";
        this._els.status.textContent = n
          ? `${n} room${n > 1 ? "s" : ""} selected — order = tap order`
          : `${how}; set each room's options under it.`;
      }
    }
  }

  _setStatus(msg) {
    this._statusSticky = !!msg;
    this._els.status.textContent = msg;
    if (msg) {
      clearTimeout(this._statusTimer);
      this._statusTimer = setTimeout(() => {
        this._statusSticky = false;
        this._syncControls();
      }, 4000);
    }
  }

  // What a send is still writing stays (`_frozen`); the rest is cleared.
  _clearAll() {
    if (this._isDrawMode()) {
      this._zones = this._zones.filter((z, i) => this._frozen("new", i));
      this._drag = null;
      if (!(this._inFlight && this._inFlight.geometry)) this._clearDeletions();
    } else {
      this._sel = [];
      this._roomPins = {};
      this._renderSelection();
    }
    this._renderOverlay();
    this._syncControls();
    this._setStatus("");
  }

  /* Overlay <-> map projection. `_zones` and `_roomPins` are normalized to the WHOLE MAP
   * (origin top-left) — the frame the wire expects; a zone in the viewport frame cleans the
   * wrong area and nothing reports an error. Screen -> stored goes only through
   * `_mapNormFromClient()`, stored -> screen only through `_overlayPos()` / `_overlayRect()`,
   * so the two cannot drift. With no renderer both collapse to the identity box mapping. */

  _crProjecting() {
    return !!(this._crActive && this._crRenderer && typeof this._crRenderer.normalizedAt === "function");
  }

  /* Stored shapes use the integration's frame, `ny = (height - 1 - row) / height` (what
   * `set_nogo_zones` and `zone_clean` convert back, and what `_geoNorm` produces); the
   * renderer's is `ny = 1 - row / height`, one grid row away. The canvas projection converts
   * between them; the PNG overlay uses the stored frame as is. */
  _crRowShift() {
    const st = this._crRenderer && this._crRenderer.state;
    return st && st.height ? 1 / st.height : 0;
  }

  // Offset between the canvas box (what the renderer measures) and the overlay's SVG user
  // units. They coincide today; measured, not assumed.
  _canvasToOverlayOffset() {
    const cv = this._els && this._els.canvas;
    const ov = this._els && this._els.overlay;
    if (!cv || !ov || !cv.getBoundingClientRect || !ov.getBoundingClientRect) return { dx: 0, dy: 0 };
    const c = cv.getBoundingClientRect();
    const o = ov.getBoundingClientRect();
    return { dx: c.left - o.left, dy: c.top - o.top };
  }

  /** Client (viewport) point -> whole-map normalized, clamped to the map. */
  _mapNormFromClient(clientX, clientY) {
    if (this._crProjecting()) {
      const n = this._crRenderer.normalizedAt(clientX, clientY);
      if (n) return { x: clamp01(n.nx), y: clamp01(n.ny - this._crRowShift()) };
    }
    const r = this._els.overlay.getBoundingClientRect();
    if (!r.width || !r.height) return { x: 0, y: 0 };
    return { x: clamp01((clientX - r.left) / r.width), y: clamp01((clientY - r.top) / r.height) };
  }

  /** Whole-map normalized -> SVG attribute strings: percentages on the PNG path, user units
   * (CSS px — the overlay has no viewBox) when client-rendered, where % means the viewport. */
  _overlayPos(nx, ny) {
    if (this._crProjecting()) {
      const p = this._crRenderer.pointForNormalized(nx, ny + this._crRowShift());
      if (p) {
        const off = this._canvasToOverlayOffset();
        return { x: String(p.x + off.dx), y: String(p.y + off.dy) };
      }
    }
    return { x: `${nx * 100}%`, y: `${ny * 100}%` };
  }

  /** As `_overlayPos`, for an axis-aligned rectangle given by two normalized corners. */
  _overlayRect(nx0, ny0, nx1, ny1) {
    if (this._crProjecting()) {
      const shift = this._crRowShift();
      const a = this._crRenderer.pointForNormalized(nx0, ny0 + shift);
      const b = this._crRenderer.pointForNormalized(nx1, ny1 + shift);
      if (a && b) {
        const off = this._canvasToOverlayOffset();
        return {
          x: String(Math.min(a.x, b.x) + off.dx),
          y: String(Math.min(a.y, b.y) + off.dy),
          w: String(Math.abs(b.x - a.x)),
          h: String(Math.abs(b.y - a.y)),
        };
      }
    }
    return {
      x: `${Math.min(nx0, nx1) * 100}%`,
      y: `${Math.min(ny0, ny1) * 100}%`,
      w: `${Math.abs(nx1 - nx0) * 100}%`,
      h: `${Math.abs(ny1 - ny0) * 100}%`,
    };
  }

  /** One delete handle: an x at a corner of a shape. `data-del` is the contract the pointer
   * handler reads back — `new:<i>` drops an unsaved shape, `forbidden|ban_mop|walls:<i>` marks
   * an existing one — and sits on the `<g>` so glyph and circle both resolve. The anchor is
   * clamped into the map box, so a shape off the mapped floor stays reachable. */
  _delHandle(pt, token, doomed) {
    const p = this._overlayPos(clamp01(pt.x), clamp01(pt.y));
    return (
      `<g class="del${doomed ? " doomed" : ""}" data-del="${token}" role="button" ` +
      `aria-label="${doomed ? "Keep" : "Delete"} ${token.split(":")[0]}" tabindex="0">` +
      `<circle cx="${p.x}" cy="${p.y}" r="11" />` +
      `<text x="${p.x}" y="${p.y}" dy="4">${doomed ? "\u21ba" : "\u00d7"}</text></g>`
    );
  }

  /** Rotate and move grips, tagged like the delete handle and clamped into the map box so a
   * shape off the mapped floor can still be grabbed. */
  _rotHandle(pt, token) {
    const p = this._overlayPos(clamp01(pt.x), clamp01(pt.y));
    return (
      `<g class="rot" data-rot="${token}" role="button" aria-label="Rotate ${token.split(":")[0]}" ` +
      `tabindex="0"><circle cx="${p.x}" cy="${p.y}" r="11" />` +
      `<text x="${p.x}" y="${p.y}" dy="4">\u21bb</text></g>`
    );
  }

  _movHandle(pt, token, staged) {
    const p = this._overlayPos(clamp01(pt.x), clamp01(pt.y));
    return (
      `<g class="mov${staged ? " staged" : ""}" data-mov="${token}" role="button" ` +
      `aria-label="Move ${token.split(":")[0]}" tabindex="0">` +
      `<circle cx="${p.x}" cy="${p.y}" r="11" />` +
      `<text x="${p.x}" y="${p.y}" dy="4">\u2724</text></g>`
    );
  }

  /* A view over `sensor.<vac>_<part>_remaining` + `button.<vac>_reset_<part>`, discovered by
   * name under the vacuum's entity prefix. Paired by part KEY, not by order: the two lists are
   * not symmetric (a reset can exist with no life sensor, and the reverse). The key drops a
   * trailing "s" ("Sensor Remaining" pairs with "Reset Sensors"); the label keeps the
   * sensor's own word. */
  _accessories() {
    const hass = this._hass;
    const vac = this._config && this._config.vacuum;
    if (!hass || !vac || !hass.states) return [];
    const slug = vac.split(".")[1] || "";
    if (!slug) return [];
    const sig = `${slug}:${Object.keys(hass.states).length}`;
    // Cached: the row list changes only when entities appear or disappear (values are read
    // fresh per render), and rebuilding it per tick rescans the whole state machine.
    if (this._partsSig === sig && this._partsList) return this._partsList;

    const parts = new Map();
    const norm = (k) => (k.length > 1 && k.endsWith("s") ? k.slice(0, -1) : k);
    const sPrefix = `sensor.${slug}_`;
    const bPrefix = `button.${slug}_reset_`;
    for (const eid of Object.keys(hass.states)) {
      if (eid.startsWith(sPrefix) && eid.endsWith("_remaining")) {
        const raw = eid.slice(sPrefix.length, eid.length - "_remaining".length);
        const k = norm(raw);
        parts.set(k, Object.assign({ key: raw }, parts.get(k), { key: raw, sensor: eid }));
      } else if (eid.startsWith(bPrefix)) {
        const raw = eid.slice(bPrefix.length);
        const k = norm(raw);
        parts.set(k, Object.assign({ key: raw }, parts.get(k), { button: eid }));
      }
    }
    const list = [...parts.values()].sort((a, b) => {
      const av = a.sensor ? 0 : 1;
      const bv = b.sensor ? 0 : 1;
      return av - bv || a.key.localeCompare(b.key);
    });
    this._partsSig = sig;
    this._partsList = list;
    return list;
  }

  /** "side_brush" -> "Side brush". Labels from the part KEY, not `friendly_name`: the key is
   * what the two entities are paired on, so a row cannot mislabel what its Reset acts on. */
  _partName(key) {
    const name = String(key || "").replace(/_/g, " ").trim();
    return name.charAt(0).toUpperCase() + name.slice(1);
  }

  /** Bar colour for *pct* of life left: two `color-mix` segments in oklab (theme blue->amber
   * above WEAR_AMBER_AT, amber->red below), so the ramp never goes muddy. A browser without
   * color-mix drops the declaration and falls back to `.warn`/`.low`. */
  _wearColor(pct) {
    const p = Math.max(0, Math.min(100, Number(pct) || 0));
    if (p >= WEAR_AMBER_AT) {
      const t = Math.round(((100 - p) / (100 - WEAR_AMBER_AT)) * 100);
      return `color-mix(in oklab, ${WEAR_AMBER} ${t}%, var(--primary-color))`;
    }
    const t = Math.round(((WEAR_AMBER_AT - p) / WEAR_AMBER_AT) * 100);
    return `color-mix(in oklab, ${WEAR_RED} ${t}%, ${WEAR_AMBER})`;
  }

  _renderAccessories() {
    const hass = this._hass;
    const list = this._accessories();
    if (!hass || !list.length) {
      this._setPartsHtml(`<div class="empty">No accessory sensors on this vacuum.</div>`);
      return;
    }
    const rows = list.map((part) => {
      const s = part.sensor && hass.states[part.sensor];
      const b = part.button && hass.states[part.button];
      const name = this._partName(part.key);
      const attrs = (s && s.attributes) || {};
      const pct =
        typeof attrs.percent_remaining === "number"
          ? Math.max(0, Math.min(100, attrs.percent_remaining))
          : null;
      // Entity-supplied strings: escaped, any entity matching the name pattern feeds them.
      const value = s && s.state !== "unknown" && s.state !== "unavailable" ? esc(s.state) : null;
      const unit = esc(attrs.unit_of_measurement || "");
      const total = attrs.total_life_hours ? esc(attrs.total_life_hours) : "";
      const level = pct === null ? "" : pct <= 10 ? " low" : pct <= 25 ? " warn" : "";
      const armed = this._partsArmed === part.button;
      const stat = value === null
        ? '<span class="p-val dim">—</span>'
        : `<span class="p-val">${value}<span class="p-unit">${unit}</span></span>` +
          (total ? `<span class="p-of">of ${total}${unit}</span>` : "");
      const bar = pct === null
        ? ""
        : `<div class="p-bar"><div class="p-fill${level}" ` +
          `style="width:${pct}%;background:${this._wearColor(pct)}"></div></div>`;
      const reset = !part.button
        ? ""
        : `<button class="ghost p-reset${armed ? " armed" : ""}" type="button" ` +
          `data-reset="${esc(part.button)}"${b && b.state === "unavailable" ? " disabled" : ""}>` +
          `${armed ? "Confirm" : "Reset"}</button>`;
      return (
        `<div class="part" role="group" aria-label="${esc(name)}">` +
        `<div class="p-head"><span class="p-name">${esc(name)}</span>${stat}${reset}</div>${bar}</div>`
      );
    });
    this._setPartsHtml(rows.join(""));
  }

  // Runs per hass tick: rebuild only on a change, and keep focus on the same Reset button.
  _setPartsHtml(html) {
    const wrap = this._els.parts;
    if (html === this._partsHtml && wrap.innerHTML !== "") return;
    const active = this.shadowRoot.activeElement;
    const focusKey = active && wrap.contains(active) ? active.getAttribute("data-reset") : null;
    wrap.innerHTML = html;
    this._partsHtml = html;
    if (!focusKey) return;
    const next = [...wrap.querySelectorAll("[data-reset]")].find(
      (b) => b.getAttribute("data-reset") === focusKey
    );
    if (next && !next.disabled) next.focus();
  }

  /** Reset one consumable counter: two-tap arm (no undo on the device), self-clearing. */
  _resetAccessory(entityId) {
    if (!this._hass || !entityId) return;
    if (this._partsArmed !== entityId) {
      this._partsArmed = entityId;
      clearTimeout(this._partsArmTimer);
      this._partsArmTimer = setTimeout(() => {
        this._partsArmed = null;
        this._renderAccessories();
      }, 5000);
      this._renderAccessories();
      this._setStatus("Tap Confirm to reset this counter");
      return;
    }
    clearTimeout(this._partsArmTimer);
    this._partsArmed = null;
    const name = this._partName(entityId.split("_reset_").pop());
    this._renderAccessories();
    this._hass
      .callService("button", "press", { entity_id: entityId })
      .then(() => this._setStatus(`${name} counter reset`))
      .catch((err) => this._setStatus(`Could not reset: ${(err && err.message) || err}`));
  }

  _renderOverlay() {
    if (!this._els) return;
    if (this._mode === "rooms") {
      const parts = [];
      this._sel.forEach((id, i) => {
        const p = this._roomPins[id];
        if (!p) return;
        const q = this._overlayPos(p.nx, p.ny);
        parts.push(`<circle class="pin" cx="${q.x}" cy="${q.y}" r="11" />`);
        parts.push(`<text class="pinnum" x="${q.x}" y="${q.y}" dy="4">${i + 1}</text>`);
      });
      this._els.overlay.innerHTML = parts.join("");
      this._syncResetBtn();
      return;
    }
    const parts = [];
    // No-go red matches the map's own forbidden-zone colour, never the clean-target colour.
    const zoneClass = this._mode === "nogo" ? "zone nogo" : "zone";
    // Existing geometry first, so a newly drawn shape stays on top. Editing modes only.
    if (this._mode === "nogo" || this._mode === "wall") {
      for (const shape of this._existingShapes()) {
        const cls =
          `edge${shape.kind === "ban_mop" ? " mop" : ""}` +
          `${shape.doomed ? " doomed" : ""}${shape.moved ? " moved" : ""}`;
        const closed = shape.pts.length > 2; // a wall is an open segment, a zone a closed quad
        const last = closed ? shape.pts.length : shape.pts.length - 1;
        for (let i = 0; i < last; i++) {
          const a = this._overlayPos(shape.pts[i].x, shape.pts[i].y);
          const b = this._overlayPos(
            shape.pts[(i + 1) % shape.pts.length].x,
            shape.pts[(i + 1) % shape.pts.length].y
          );
          parts.push(`<line class="${cls}" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" />`);
        }
        if (this._frozen(shape.kind, shape.index)) continue;
        const token = `${shape.kind}:${shape.index}`;
        parts.push(this._delHandle(shape.pts[0], token, shape.doomed));
        // The backend rejects a shape staged as both moved and deleted.
        if (!shape.doomed) {
          parts.push(this._rotHandle(shape.pts[1], token));
          parts.push(this._movHandle(shape.center, token, shape.moved));
        }
      }
    }
    this._zones.forEach((z, i) => {
      const pts = this._shapeCorners(z);
      if (z.line) {
        const a = this._overlayPos(pts[0].x, pts[0].y);
        const b = this._overlayPos(pts[1].x, pts[1].y);
        parts.push(`<line class="wall" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" />`);
        parts.push(`<text class="num" x="${a.x}" y="${a.y}" dx="6" dy="16">${i + 1}</text>`);
        if (this._frozen("new", i)) return;
        parts.push(this._delHandle(pts[0], `new:${i}`, false));
        parts.push(this._rotHandle(pts[1], `new:${i}`));
        parts.push(this._movHandle(this._shapeCenter(z), `new:${i}`, false));
        return;
      }
      if (z.rot) {
        // A rotated quad is not an SVG <rect>, and <polygon> cannot take the percentage
        // coordinates the PNG path uses — so it is stroked edge by edge.
        for (let k = 0; k < pts.length; k++) {
          const a = this._overlayPos(pts[k].x, pts[k].y);
          const b = this._overlayPos(pts[(k + 1) % pts.length].x, pts[(k + 1) % pts.length].y);
          parts.push(
            `<line class="turned${this._mode === "nogo" ? " nogo" : ""}" ` +
            `x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" />`
          );
        }
      } else {
        const q = this._overlayRect(z.x0, z.y0, z.x1, z.y1);
        parts.push(`<rect class="${zoneClass}" x="${q.x}" y="${q.y}" width="${q.w}" height="${q.h}" />`);
      }
      const label = this._overlayPos(pts[0].x, pts[0].y);
      parts.push(`<text class="num" x="${label.x}" y="${label.y}" dx="6" dy="16">${i + 1}</text>`);
      if (this._frozen("new", i)) return;
      // The number owns corner 0, so delete takes corner 1 and rotate corner 2.
      parts.push(this._delHandle(pts[1], `new:${i}`, false));
      parts.push(this._rotHandle(pts[2], `new:${i}`));
      parts.push(this._movHandle(this._shapeCenter(z), `new:${i}`, false));
    });
    if (this._drag && this._isLineMode()) {
      const d = this._drag;
      const a = this._overlayPos(d.x0, d.y0);
      const b = this._overlayPos(d.x1, d.y1);
      parts.push(`<line class="wall draft" x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}" />`);
    } else if (this._drag) {
      const d = this._drag;
      const q = this._overlayRect(d.x0, d.y0, d.x1, d.y1);
      parts.push(`<rect class="draft" x="${q.x}" y="${q.y}" width="${q.w}" height="${q.h}" />`);
    }
    this._els.overlay.innerHTML = parts.join("");
    this._syncResetBtn();
  }

  _syncResetBtn() {
    const btn = this._els && this._els.mapreset;
    if (!btn) return;
    const r = this._crRenderer;
    btn.hidden = !(this._crActive && r && typeof r.isOffFit === "function" && r.isOffFit());
  }

  // Draw modes claim the one-finger gesture, so no page scroll over the map. Elsewhere
  // `pan-y` keeps the dashboard scrollable until the view is off fit, where a drag pans.
  _applyTouchAction() {
    if (!this._built) return;
    const zones = this._isDrawMode() && this._hasMapSurface();
    const r = this._crRenderer;
    const offFit = !!(this._crActive && r && typeof r.isOffFit === "function" && r.isOffFit());
    this._els.overlay.style.touchAction = zones || offFit ? "none" : "pan-y";
  }

  _clean() {
    if (this._dispatching) return;
    if (this._mode === "nogo" || this._mode === "wall") this._saveNogoZones();
    else if (this._mode === "zones") this._cleanZones();
    else this._cleanRooms();
  }

  /** Save the drawn rectangles as no-go zones. The device replaces ALL restricted geometry in
   * one document, so these go as an ADDITION (never `replace`) or the rest is erased. */
  async _saveNogoZones() {
    const d = this._deletionCount();
    const mv = this._moveCount();
    if (!this._hass || this._frameUngrounded || (this._zones.length === 0 && d === 0 && mv === 0)) {
      return;
    }
    const sent = new Set(this._zones);
    const shapes = this._zones.map((z) => this._shapeParam(z));
    const n = shapes.length;
    const wall = this._isLineMode();
    // Same four numbers either way: `walls` is a LINE, `forbidden` the rectangle they bound.
    const params = {};
    if (n) params[wall ? "walls" : "forbidden"] = shapes;
    // Deletions name shapes by index, so the revision they were read at rides along; the
    // backend refuses a stale write rather than deleting whatever now sits at those indices.
    const ids = (set) => Array.from(set).sort((a, b) => a - b);
    if (this._del.forbidden.size) params.remove_forbidden = ids(this._del.forbidden);
    if (this._del.ban_mop.size) params.remove_ban_mop = ids(this._del.ban_mop);
    if (this._del.walls.size) params.remove_walls = ids(this._del.walls);
    // Move deltas are in the device frame: cm and radians about the shape's centroid.
    const moves = (map) =>
      Array.from(map.entries())
        .sort((a, b) => a[0] - b[0])
        .map(([index, m]) => ({
          index,
          dx: Math.round(m.dx * 10) / 10,
          dy: Math.round(m.dy * 10) / 10,
          rotate: Math.round(m.rot * 10000) / 10000,
        }));
    if (this._moves.forbidden.size) params.move_forbidden = moves(this._moves.forbidden);
    if (this._moves.ban_mop.size) params.move_ban_mop = moves(this._moves.ban_mop);
    if (this._moves.walls.size) params.move_walls = moves(this._moves.walls);
    if ((d || mv) && this._editGeo && this._editGeo.revision !== undefined) {
      params.revision = this._editGeo.revision;
    }
    const noun = wall ? "wall" : "no-go zone";
    const label = `${noun}${n > 1 ? "s" : ""}`;
    const mode = this._mode; // the mode may change while the call is out
    this._dispatching = true;
    this._inFlight = { shapes: sent, geometry: true };
    try {
      this._renderOverlay();
      this._syncControls();
      await this._hass.callService("vacuum", "send_command", {
        entity_id: this._config.vacuum,
        command: "set_nogo_zones",
        params,
      });
      // Only what was sent: a shape drawn meanwhile is still to save.
      this._pending[mode] = this._pending[mode].filter((z) => !sent.has(z));
      this._clearDeletions();
      const done = [];
      if (n) done.push(`saved ${n} ${label}`);
      if (mv) done.push(`moved ${mv}`);
      if (d) done.push(`deleted ${d}`);
      this._setStatus(done.join(", ").replace(/^./, (c) => c.toUpperCase()), true);
      // Re-read: later deletions index against this geometry, and its revision guards the next
      // write. With a live subscription the `geometry` event re-reads it instead.
      this._fetchEditGeometry();
    } catch (err) {
      this._setStatus(`Could not save: ${(err && err.message) || err}`, true);
    } finally {
      this._dispatching = false;
      this._inFlight = null;
      this._renderOverlay();
      this._syncControls();
    }
  }

  async _cleanZones() {
    if (!this._hass || this._frameUngrounded || this._zones.length === 0) return;
    const sent = new Set(this._zones);
    const zones = this._zones.map((z) => this._shapeParam(z));
    const n = zones.length;
    this._dispatching = true;
    this._inFlight = { shapes: sent, geometry: false };
    try {
      this._renderOverlay();
      this._syncControls();
      await this._hass.callService("vacuum", "send_command", {
        entity_id: this._config.vacuum,
        command: "zone_clean",
        params: { zones, clean_times: this._cleanTimes },
      });
      this._pending.zones = this._pending.zones.filter((z) => !sent.has(z));
      this._setStatus(`Sent ${n} zone${n > 1 ? "s" : ""} • passes ${this._cleanTimes}`);
    } catch (err) {
      this._setStatus(`Failed: ${err && err.message ? err.message : err}`);
    } finally {
      this._dispatching = false;
      this._inFlight = null;
      this._renderOverlay();
      this._syncControls();
    }
  }

  async _cleanRooms() {
    if (!this._hass || this._sel.length === 0) return;
    const rooms = this._sel.map((id) => {
      const c = this._roomCfg[id] || this._defaultRoomCfg();
      const r = { id: Number(id) };
      if (c.clean_mode) r.clean_mode = c.clean_mode;
      if (c.fan_speed) r.fan_speed = c.fan_speed;
      if (c.water_level) r.water_level = c.water_level;
      if (c.clean_intensity) r.clean_intensity = c.clean_intensity;
      if (c.clean_times && c.clean_times > 1) r.clean_times = c.clean_times;
      if (c.edge === "on") r.edge_mopping = true;
      else if (c.edge === "off") r.edge_mopping = false;
      return r;
    });
    const n = rooms.length;
    // Per-room customization sends the rich payload (CUSTOMIZE); a plain room_ids list is GENERAL.
    const hasCustom = rooms.some((r) => Object.keys(r).length > 1);
    const params = hasCustom ? { rooms } : { room_ids: this._sel.map(Number) };
    const sent = this._sel.slice();
    this._dispatching = true;
    try {
      this._syncControls();
      await this._hass.callService("vacuum", "send_command", {
        entity_id: this._config.vacuum,
        command: "room_clean",
        params,
      });
      // A room tapped meanwhile stays selected for the next run.
      this._sel = this._sel.filter((id) => !sent.includes(id));
      for (const id of sent) delete this._roomPins[id];
      this._renderSelection();
      this._renderOverlay();
      this._setStatus(`Sent ${n} room${n > 1 ? "s" : ""}${hasCustom ? " • custom settings" : ""}`);
    } catch (err) {
      this._setStatus(`Failed: ${err && err.message ? err.message : err}`);
    } finally {
      this._dispatching = false;
      this._syncControls();
    }
  }

  static getStubConfig(hass) {
    const states = (hass && hass.states) || {};
    const pick = (domain, pred) =>
      Object.keys(states).find((e) => e.startsWith(domain + ".") && (!pred || pred(e)));
    const vacuum = pick("vacuum") || "vacuum.robot";
    const camera = pick("camera", (e) => e.endsWith("_map")) || pick("camera") || "camera.robot_map";
    // No `client_render` key: default-ON. `camera` stays — fallback surface and trail colour.
    return { vacuum, camera }; // selects auto-discovered from the vacuum slug
  }

  static getConfigElement() {
    return document.createElement("eufy-clean-card-editor");
  }
}

// Each distinct URL is a separate module, so this file can be evaluated twice in one page
// (a stale `?v=` alongside the current one). A bare define() would throw and abort the rest
// of the module, so register defensively: first definition wins, later ones no-op.
function defineCard(tag, cls) {
  if (customElements.get(tag)) {
    if (!defineCard._warned) {
      defineCard._warned = true;
      console.warn(
        `[eufy-clean-card] "${tag}" was already registered, so this copy of the card ` +
          "was ignored. The card still works, but it is being loaded twice — check for " +
          "a duplicate Lovelace resource pointing at /robovac_mqtt/eufy-clean-card.js " +
          "(Settings > Dashboards > Resources); the integration registers it for you."
      );
    }
    return false;
  }
  customElements.define(tag, cls);
  return true;
}

defineCard("eufy-clean-card", EufyCleanCard);

// `custom:zone-clean-card` alias: a distinct subclass, since one constructor takes one tag name.
class ZoneCleanCard extends EufyCleanCard {
  get _defaultMode() {
    return "zones";
  }
}
defineCard("zone-clean-card", ZoneCleanCard);

/* Visual config editor — vanilla, no Lit, no dependencies. */
class EufyCleanCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = Object.assign({}, config);
    if (this._built && !this._emitting) this._fill();
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
  }

  _list(domain) {
    const s = (this._hass && this._hass.states) || {};
    return Object.keys(s)
      .filter((e) => e.startsWith(domain + "."))
      .sort();
  }

  _build() {
    if (!this._hass || !this._config) return;
    // NATIVE form controls, deliberately: this is `innerHTML`, not lit-html, so `.value=`
    // property bindings do nothing, and the `ha-*` controls emit `selected`/`closed` rather
    // than `change`. jsdom cannot reproduce either failure, so the suite would stay green.
    const opt = (list, sel) =>
      ['<option value="">— choose —</option>']
        .concat(
          list.map(
            (e) => `<option value="${esc(e)}"${e === sel ? " selected" : ""}>${esc(e)}</option>`
          )
        )
        .join("");
    this.innerHTML = `
      <style>
        .ecce { display: flex; flex-direction: column; gap: 16px; padding: 8px 0; }
        .ecce .row { display: flex; flex-direction: column; gap: 4px; }
        .ecce .fld { font-size: 12px; color: var(--secondary-text-color); }
        .ecce select, .ecce input[type="text"] {
          width: 100%; box-sizing: border-box; padding: 8px;
          font: inherit; color: var(--primary-text-color);
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #ccc); border-radius: 4px;
        }
        .ecce .chk { display: flex; align-items: center; gap: 8px; font-size: 14px; }
        .ecce .hint { font-size: 12px; color: var(--secondary-text-color); }
      </style>
      <div class="ecce">
        <div class="row">
          <label class="fld">Vacuum (required)</label>
          <select class="f-vacuum">${opt(this._list("vacuum"), this._config.vacuum)}</select>
        </div>
        <div class="row">
          <label class="fld">Map camera (needed for Zones, map taps + the backdrop)</label>
          <select class="f-camera">${opt(this._list("camera"), this._config.camera)}</select>
        </div>
        <div class="row">
          <label class="chk"><input type="checkbox" class="f-clientrender"${
            this._config.client_render === false ? "" : " checked"
          } /> Draw the map in the browser</label>
          <div class="hint">Sharper map, pinch-zoom, and no image round trip. Falls back to
            the camera picture automatically if the browser cannot draw it.</div>
        </div>
        <div class="row">
          <label class="fld">Title (optional)</label>
          <input type="text" class="f-title" placeholder="Eufy Clean" value="${esc(
            this._config.title || ""
          )}" />
        </div>
      </div>
    `;
    this.querySelector(".f-vacuum").addEventListener("change", () => this._changed());
    this.querySelector(".f-camera").addEventListener("change", () => this._changed());
    this.querySelector(".f-title").addEventListener("input", () => this._changed());
    this.querySelector(".f-clientrender").addEventListener("change", () => this._changed());
    this._built = true;
    // HA calls setConfig before hass, so the first _fill is a no-op; the markup carries the values.
    this._fill();
  }

  _fill() {
    const v = this.querySelector(".f-vacuum"); if (v) v.value = this._config.vacuum || "";
    const c = this.querySelector(".f-camera"); if (c) c.value = this._config.camera || "";
    // `!== false`, not `=== true`: a missing key means ON, so a keyless card renders CHECKED.
    const cr = this.querySelector(".f-clientrender");
    if (cr) cr.checked = this._config.client_render !== false;
    // title is NOT re-filled: it is edited per keystroke and writing back moves the caret.
  }

  _changed() {
    const val = (q) => {
      const el = this.querySelector(q);
      return el ? el.value : "";
    };
    const cfg = Object.assign({}, this._config);
    cfg.vacuum = val(".f-vacuum");
    const cam = val(".f-camera");
    if (cam) cfg.camera = cam; else delete cfg.camera;

    // hide_edge_mop is not editable here, but is carried through so old dashboards still work.
    const t = val(".f-title").trim();
    if (t) cfg.title = t; else delete cfg.title;

    // Read CHECKED, not `.value` (a checkbox's value is "on"/"" either way). Unchecking
    // writes an explicit `false`; checking deletes the key, since the default is ON.
    const cr = this.querySelector(".f-clientrender");
    if (cr && !cr.checked) cfg.client_render = false; else delete cfg.client_render;

    this._config = cfg;
    this._emitting = true;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: cfg }, bubbles: true, composed: true }));
    this._emitting = false;
  }
}
defineCard("eufy-clean-card-editor", EufyCleanCardEditor);

// True for a robovac_mqtt vacuum: registry platform, else companion entities on the same slug.
function isForkVacuum(hass, entityId) {
  if (!hass || typeof entityId !== "string" || !entityId.startsWith("vacuum.")) return false;
  const reg = hass.entities && hass.entities[entityId];
  if (reg && reg.platform) return reg.platform === "robovac_mqtt";
  const slug = entityId.split(".")[1] || "";
  const st = hass.states || {};
  return !!(st[`camera.${slug}_map`] || st[`sensor.${slug}_active_map`]);
}

window.customCards = window.customCards || [];
// Guarded against double evaluation; no top-level binding (a `const` throws on re-evaluation).
if (!window.customCards.some((c) => c.type === "eufy-clean-card")) {
  window.customCards.push({
    type: "eufy-clean-card",
    name: "Eufy Clean Card",
    description: "Clean rooms with per-room settings (tap them on the map), or draw zones (Eufy — jeppesens/eufy-clean).",
    // HA 2026.6+ "By entity" card picker; ignored on older HA.
    getEntitySuggestion: (hass, entityId) => {
      if (!isForkVacuum(hass, entityId)) return null;
      const slug = entityId.split(".")[1] || "";
      const cam = `camera.${slug}_map`;
      const config = {
        type: "custom:eufy-clean-card",
        vacuum: entityId,
      };
      if (hass.states && hass.states[cam]) config.camera = cam;
      return { config };
    },
  });
  console.info(
    "%c EUFY-CLEAN-CARD %c rooms + zones ",
    "background:#3b82f6;color:#fff;border-radius:3px 0 0 3px;padding:2px 4px",
    "background:#222;color:#fff;border-radius:0 3px 3px 0;padding:2px 4px"
  );
}
