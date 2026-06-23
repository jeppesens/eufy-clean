/*
 * eufy-clean-card  —  room + zone cleaning for Eufy (jeppesens/eufy-clean)
 * ----------------------------------------------------------------------------
 * One card, two modes:
 *
 *   ROOMS — pick rooms (tap them on the live map OR in the list), give each its OWN
 *           settings (suction, water, mode, intensity, passes, edge-mop), hit Clean.
 *           Per-room settings are held in the card (no helper entities) and embedded
 *           in the command. Map taps are resolved to a room server-side via the
 *           integration's `robovac_mqtt.room_at_point` response service (an entity
 *           service — registered under the integration domain, not `vacuum`).
 *
 *   ZONES — rubber-band up to 10 free-form boxes on the live map and clean those.
 *
 * BUNDLED CARD: this file ships inside the eufy-clean integration and is
 * auto-registered on setup — no www/ copy, no Lovelace "Resources" entry. Drop
 * it on a dashboard:
 *
 *       type: custom:eufy-clean-card
 *       vacuum: vacuum.your_robot
 *       camera: camera.your_robot_map   # optional for rooms; required for ZONES + map taps
 *       # mode: rooms                    # optional initial mode: rooms | zones
 *       # title: Eufy Clean              # optional
 *       # selects:                       # optional (ZONES) — global setting selects to surface.
 *       #   - select.your_robot_suction_level   #   Omit to auto-discover select.<vacuum-slug>_*.
 *
 * Backward compat: the old `type: custom:zone-clean-card` keeps working — it's an
 * alias of this same card that simply opens in ZONES mode (and still requires a camera).
 *
 * How it dispatches (both ride the integration's existing send_command handlers):
 *   ROOMS → vacuum.send_command { command: room_clean,
 *              params: { rooms: [ {id, fan_speed?, water_level?, clean_mode?,
 *                                  clean_intensity?, clean_times?, edge_mopping?}, ... ] } }
 *           (or { room_ids:[...] } when nothing is customized → a plain GENERAL clean).
 *   ZONES → vacuum.send_command { command: zone_clean, params: { zones, clean_times } }
 *
 * Vanilla web component — no Lit, no build, themes itself from HA CSS variables.
 * The map only renders after the robot has cleaned once (or you edit the map in the app).
 */

const MAX_ZONES = 10;
const MIN_FRAC = 0.012; // reject degenerate drags smaller than ~1% of the map in either axis
const TAP_FRAC = 0.03; // a press that moves less than this counts as a tap (rooms mode)
const clamp01 = (v) => Math.min(Math.max(v, 0), 1);

// --- per-room setting vocabularies: [display label, command value] -------------------------
// Values are the EXACT keys the integration's set_room_custom builder accepts (see
// const.py CLEAN_TYPE_MAP / MOP_LEVEL_MAP / CLEAN_EXTENT_MAP). "" = leave at device default
// (the key is omitted from the payload entirely).
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

// Escape dynamic text before interpolating it into an innerHTML template. Select options
// are user/cloud-authored — room names (Clean Room), scene names (Scene/Task), and
// fan_speed_list — decoded from MQTT, so unescaped they're a stored DOM-XSS vector.
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
    // zones state
    this._zones = []; // committed zones: {x0,y0,x1,y1} normalized
    this._drag = null; // in-progress drag
    this._cleanTimes = 1; // passes per zone (Zone.clean_times)
    this._optSig = {}; // per-select option-list signature (zones settings)
    // rooms state
    this._sel = []; // selected room ids, in tap order = clean order
    this._roomCfg = {}; // id -> {clean_mode, fan_speed, water_level, clean_intensity, clean_times, edge}
    this._roomEls = {}; // id -> dom refs
    this._roomPins = {}; // id -> {nx, ny} tap point for the on-map pin (map-selected rooms)
    this._lastRooms = []; // last rendered room list
    this._roomIdKey = null; // signature of the rendered room-ID set (full-rebuild trigger)
    this._tapStart = null; // press origin while detecting a rooms-mode tap
    // shared
    this._built = false;
    this._dispatching = false; // in-flight send guard (prevents double-dispatch)
    this._lastImgSrc = "";
  }

  // ROOMS for eufy-clean-card; the zone-clean-card alias overrides this to ZONES.
  get _defaultMode() {
    return "rooms";
  }

  setConfig(config) {
    if (!config || !config.vacuum) throw new Error("eufy-clean-card: 'vacuum' is required");
    const m = config.mode;
    // Zones needs a live map to draw on. If this card defaults to (or is configured
    // for) zones, a camera is required — fail loudly rather than silently demote to
    // rooms (preserves the old zone-clean-card behaviour for the alias).
    if ((m === "zones" || this._defaultMode === "zones") && !config.camera) {
      throw new Error("eufy-clean-card: 'camera' is required for zones mode");
    }
    this._config = {
      title: "Eufy Clean",
      selects: [],
      ...config,
    };
    this._mode = m === "zones" || m === "rooms" ? m : this._defaultMode;
    // transient selections reset on (re)configure; per-room setting choices are kept
    this._zones = [];
    this._drag = null;
    this._sel = [];
    this._roomPins = {};
    if (this._built) {
      this._selectsKey = null; // rebuild zone selects on next sync
      this._roomIdKey = null; // rebuild room list on next sync
      this._applyMode();
      this._syncDynamic(); // refresh now, don't wait for the next hass tick
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._built) this._build();
    this._syncDynamic();
  }

  getCardSize() {
    return 8;
  }

  connectedCallback() {
    this._startPolling();
  }

  disconnectedCallback() {
    clearTimeout(this._pollTimer);
    this._pollTimer = null;
    clearTimeout(this._statusTimer);
    this._statusTimer = null;
  }

  _hasCamera() {
    return !!(this._config && this._config.camera);
  }

  // Keep the map fresh while the robot moves; just re-check while it's parked. Stops when the
  // card leaves the DOM. (No-op when no camera is configured.)
  _startPolling() {
    clearTimeout(this._pollTimer);
    const tick = () => {
      const active = this._hasCamera() && this._vacuumActive();
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

  // Re-fetch the camera image with a fresh cache-bust. Skipped mid-draw so the backdrop never
  // swaps out from under an in-progress zone box.
  _refreshMap() {
    if (!this._built || !this._hass || this._drag || !this._hasCamera()) return;
    const cam = this._hass.states[this._config.camera];
    const pic = cam && cam.attributes && cam.attributes.entity_picture;
    if (!pic) return;
    const src = pic + (pic.includes("?") ? "&" : "?") + "_=" + Date.now();
    this._els.img.src = src;
    this._lastImgSrc = src;
  }

  // --- one-time DOM skeleton + listeners -----------------------------------------------------
  _build() {
    const c = this._config;
    this.shadowRoot.innerHTML = `
      <style>
        ha-card { padding: 12px 16px 16px; }
        .title { font-size: 1.1rem; font-weight: 500; margin-bottom: 8px; }
        .modebar { display: inline-flex; border: 1px solid var(--divider-color); border-radius: 999px;
                   overflow: hidden; margin-bottom: 12px; }
        .modebar button { font: inherit; font-size: 0.85rem; padding: 6px 16px; border: none; cursor: pointer;
                          background: transparent; color: var(--primary-text-color); }
        .modebar button.on { background: var(--primary-color); color: var(--text-primary-color, #fff); font-weight: 500; }
        .map-wrap { position: relative; width: 100%; max-width: 520px; margin: 0 auto;
                    border-radius: 8px; overflow: hidden; background: var(--secondary-background-color); }
        .map-wrap img { display: block; width: 100%; height: auto; user-select: none; -webkit-user-drag: none; }
        /* width/height:100% are REQUIRED — an inline <svg> is a replaced element with a default
           300x150 intrinsic size; inset:0 alone does NOT stretch it. */
        .overlay { position: absolute; inset: 0; width: 100%; height: 100%; touch-action: none; }
        .overlay[hidden] { display: none; }
        .nomap { padding: 40px 12px; text-align: center; color: var(--secondary-text-color); font-size: 0.9rem; }

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
        .rset { display: grid; grid-template-columns: repeat(auto-fit, minmax(118px, 1fr)); gap: 8px 10px;
                padding: 0 12px 12px; }
        .rset[hidden] { display: none; }

        /* shared field styling (rooms per-room + zones global selects) */
        .field { display: flex; flex-direction: column; gap: 2px; }
        .field label { font-size: 0.7rem; color: var(--secondary-text-color); text-transform: uppercase;
                       letter-spacing: 0.03em; }
        .field select { padding: 6px 8px; border-radius: 6px; border: 1px solid var(--divider-color);
                        background: var(--card-background-color); color: var(--primary-text-color); font-size: 0.88rem; }
        .settings { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                    gap: 8px 12px; margin-top: 12px; }
        .settings[hidden] { display: none; }

        .controls { display: flex; align-items: center; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
        .passes { display: flex; align-items: center; gap: 6px; font-size: 0.85rem; color: var(--secondary-text-color); }
        .passes[hidden] { display: none; }
        .passes input { width: 52px; padding: 5px 6px; border-radius: 6px; border: 1px solid var(--divider-color);
                        background: var(--card-background-color); color: var(--primary-text-color); font-size: 0.9rem; }
        .status { flex: 1 1 100%; font-size: 0.82rem; color: var(--secondary-text-color); }
        button.clean, button.ghost { font: inherit; padding: 8px 14px; border-radius: 8px; border: none; cursor: pointer; }
        button.clean:disabled { opacity: 0.45; cursor: default; }
        .clean { background: var(--primary-color); color: var(--text-primary-color, #fff); font-weight: 500; }
        .ghost { background: transparent; color: var(--primary-text-color); border: 1px solid var(--divider-color); }
        rect.zone { fill: var(--primary-color); fill-opacity: 0.22; stroke: var(--primary-color); stroke-width: 2; }
        rect.draft { fill: var(--primary-color); fill-opacity: 0.12; stroke: var(--primary-color); stroke-width: 2; stroke-dasharray: 6 4; }
        text.num { fill: var(--text-primary-color, #fff); font-size: 13px; font-weight: 700;
                   paint-order: stroke; stroke: var(--primary-color); stroke-width: 3; }
        circle.pin { fill: var(--primary-color); fill-opacity: 0.92; stroke: var(--text-primary-color, #fff); stroke-width: 2; }
        text.pinnum { fill: var(--text-primary-color, #fff); font-size: 12px; font-weight: 700; text-anchor: middle; }
      </style>
      <ha-card>
        <div class="title"></div>
        <div class="modebar" hidden>
          <button class="mode-rooms" type="button">Rooms</button>
          <button class="mode-zones" type="button">Zones</button>
        </div>
        <div class="map-wrap">
          <img class="map" alt="vacuum map" />
          <svg class="overlay" preserveAspectRatio="none"></svg>
          <div class="nomap" hidden>Waiting for the map… run a clean once (or edit the map in the app) so it renders.</div>
        </div>
        <div class="rooms"></div>
        <div class="settings" hidden></div>
        <div class="controls">
          <span class="passes" hidden>Passes
            <input class="ct" type="number" min="1" max="10" step="1" value="1" />
          </span>
          <button class="ghost clear" type="button">Clear</button>
          <button class="clean" type="button" disabled>Clean</button>
          <span class="status"></span>
        </div>
      </ha-card>
    `;

    this._els = {
      title: this.shadowRoot.querySelector(".title"),
      modebar: this.shadowRoot.querySelector(".modebar"),
      modeRooms: this.shadowRoot.querySelector(".mode-rooms"),
      modeZones: this.shadowRoot.querySelector(".mode-zones"),
      mapWrap: this.shadowRoot.querySelector(".map-wrap"),
      img: this.shadowRoot.querySelector("img.map"),
      overlay: this.shadowRoot.querySelector("svg.overlay"),
      nomap: this.shadowRoot.querySelector(".nomap"),
      rooms: this.shadowRoot.querySelector(".rooms"),
      settings: this.shadowRoot.querySelector(".settings"),
      passes: this.shadowRoot.querySelector(".passes"),
      ct: this.shadowRoot.querySelector("input.ct"),
      clear: this.shadowRoot.querySelector("button.clear"),
      clean: this.shadowRoot.querySelector("button.clean"),
      status: this.shadowRoot.querySelector(".status"),
    };
    this._els.title.textContent = c.title;

    // mode toggle
    this._els.modeRooms.addEventListener("click", () => this._setMode("rooms"));
    this._els.modeZones.addEventListener("click", () => this._setMode("zones"));

    // overlay pointer handlers (mouse + touch): draw boxes in zones, tap-to-pick in rooms
    const ov = this._els.overlay;
    const toFrac = (e) => {
      const r = ov.getBoundingClientRect();
      return { x: clamp01((e.clientX - r.left) / r.width), y: clamp01((e.clientY - r.top) / r.height) };
    };
    ov.addEventListener("pointerdown", (e) => {
      if (!this._els.nomap.hidden) return; // no map yet
      if (this._mode === "zones") {
        ov.setPointerCapture(e.pointerId);
        const p = toFrac(e);
        this._drag = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
        this._renderOverlay();
      } else {
        this._tapStart = toFrac(e); // rooms: remember where the press began (tap vs scroll)
      }
    });
    ov.addEventListener("pointermove", (e) => {
      if (!this._drag) return; // only a zone drag tracks movement
      const p = toFrac(e);
      this._drag.x1 = p.x;
      this._drag.y1 = p.y;
      this._renderOverlay();
    });
    const finishZone = () => {
      if (!this._drag) return;
      const d = this._drag;
      this._drag = null;
      const x0 = Math.min(d.x0, d.x1), x1 = Math.max(d.x0, d.x1);
      const y0 = Math.min(d.y0, d.y1), y1 = Math.max(d.y0, d.y1);
      if (x1 - x0 >= MIN_FRAC && y1 - y0 >= MIN_FRAC && this._zones.length < MAX_ZONES) {
        this._zones.push({ x0, y0, x1, y1 });
      }
      this._renderOverlay();
      this._syncControls();
    };
    ov.addEventListener("pointerup", (e) => {
      if (this._mode === "zones") {
        finishZone();
        return;
      }
      const start = this._tapStart;
      this._tapStart = null;
      if (!start) return;
      const p = toFrac(e);
      if (Math.hypot(p.x - start.x, p.y - start.y) < TAP_FRAC) this._resolveRoomTap(p.x, p.y);
    });
    ov.addEventListener("pointercancel", () => {
      this._drag = null;
      this._tapStart = null;
      this._renderOverlay();
    });

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
    this._applyMode();
  }

  // --- mode -----------------------------------------------------------------------------------
  _setMode(mode) {
    if (mode !== "rooms" && mode !== "zones") return;
    this._mode = mode;
    // drop any sticky status from the mode we're leaving so the prompt repaints
    this._statusSticky = false;
    clearTimeout(this._statusTimer);
    this._applyMode();
    this._syncDynamic();
  }

  // Show/hide each section for the active mode. With no camera, the card is rooms-only (no map,
  // no toggle). The map overlay is interactive in BOTH modes when a map exists.
  _applyMode() {
    if (!this._built) return;
    const hasCam = this._hasCamera();
    if (this._mode === "zones" && !hasCam) this._mode = "rooms"; // can't draw zones without a map
    const zones = this._mode === "zones" && hasCam;
    const rooms = this._mode === "rooms";

    this._els.modebar.hidden = !hasCam; // only meaningful when a map exists
    this._els.modeRooms.classList.toggle("on", rooms);
    this._els.modeZones.classList.toggle("on", zones);

    this._els.mapWrap.style.display = hasCam ? "" : "none";
    this._els.overlay.hidden = !hasCam; // hidden only when there's no map at all
    this._els.overlay.style.cursor = zones ? "crosshair" : "pointer";
    this._els.rooms.hidden = !rooms;
    this._els.settings.hidden = !zones; // global setting selects belong to zones
    this._els.passes.hidden = !zones; // single passes input belongs to zones
    this._renderOverlay(); // repaint the correct overlay content for the mode
  }

  // --- zones: settings selects (unchanged behaviour) -----------------------------------------
  // Effective select list: explicit `selects:` if given, else auto-discover every
  // `select.<vacuum-slug>_*` entity so the card is plug-in with just vacuum + camera.
  _effectiveSelects() {
    if (this._config.selects && this._config.selects.length) return this._config.selects;
    if (!this._hass) return [];
    const slug = this._config.vacuum.split(".")[1] || "";
    if (!slug) return [];
    return Object.keys(this._hass.states)
      .filter((e) => e.startsWith(`select.${slug}_`))
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
      refs.label.textContent = (st.attributes && st.attributes.friendly_name) || eid;
      const opts = (st.attributes && st.attributes.options) || [];
      // Delimiter-joined (not "") so ["ab","c"] and ["a","bc"] don't collapse to the
      // same signature and skip a real <option> rebuild. Newlines never occur in HA
      // select option values, so they're a safe separator.
      const sig = opts.join("\n");
      if (sig !== this._optSig[eid]) {
        refs.sel.innerHTML = opts.map((o) => `<option value="${esc(o)}">${esc(o)}</option>`).join("");
        this._optSig[eid] = sig;
      }
      if (this.shadowRoot.activeElement !== refs.sel) refs.sel.value = st.state;
    }
  }

  // --- rooms ----------------------------------------------------------------------------------
  // Pull the cleanable rooms from the vacuum entity's attributes (id + name). Both `rooms` and
  // `segments` carry the same shape; prefer `rooms`. All Eufy room ids are numeric.
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

  _fanOptions() {
    const v = this._hass && this._hass.states[this._config.vacuum];
    const list = (v && v.attributes && v.attributes.fan_speed_list) || DEFAULT_FANS;
    const pretty = (s) => String(s).replace(/_/g, " ");
    return [["Default", ""]].concat(list.map((s) => [pretty(s), s]));
  }

  _defaultRoomCfg() {
    return { clean_mode: "", fan_speed: "", water_level: "", clean_intensity: "", clean_times: 1, edge: "" };
  }

  _rebuildRooms(rooms) {
    const wrap = this._els.rooms;
    wrap.innerHTML = "";
    this._roomEls = {};
    if (!rooms.length) {
      wrap.innerHTML =
        '<div class="empty">No rooms found yet — run a clean once (or open the Eufy app) so the map and rooms load.</div>';
      return;
    }
    const fanOpts = this._fanOptions();
    const field = (labelTxt, cls, pairs) =>
      `<div class="field"><label>${labelTxt}</label><select class="${cls}">${optionsHtml(pairs, "")}</select></div>`;
    const passesField = `<div class="field"><label>Passes</label><select class="f-passes">${PASSES_OPTS.map(
      (n) => `<option value="${n}">${n}</option>`
    ).join("")}</select></div>`;

    for (const room of rooms) {
      const id = room.id;
      if (!(id in this._roomCfg)) this._roomCfg[id] = this._defaultRoomCfg();
      const el = document.createElement("div");
      el.className = "room";
      el.innerHTML = `
        <button class="chip" type="button">
          <span class="order"></span>
          <span class="rname"></span>
        </button>
        <div class="rset" hidden>
          ${field("Mode", "f-mode", MODE_OPTS)}
          ${field("Suction", "f-fan", fanOpts)}
          ${field("Water", "f-water", WATER_OPTS)}
          ${field("Intensity", "f-int", INTENSITY_OPTS)}
          ${passesField}
          ${field("Edge mop", "f-edge", EDGE_OPTS)}
        </div>`;
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
      refs.chip.addEventListener("click", () => this._toggleRoom(id));
      refs.mode.addEventListener("change", () => (this._roomCfg[id].clean_mode = refs.mode.value));
      refs.fan.addEventListener("change", () => (this._roomCfg[id].fan_speed = refs.fan.value));
      refs.water.addEventListener("change", () => (this._roomCfg[id].water_level = refs.water.value));
      refs.int.addEventListener("change", () => (this._roomCfg[id].clean_intensity = refs.int.value));
      refs.passes.addEventListener("change", () => (this._roomCfg[id].clean_times = parseInt(refs.passes.value, 10) || 1));
      refs.edge.addEventListener("change", () => (this._roomCfg[id].edge = refs.edge.value));
      wrap.appendChild(el);
      this._roomEls[id] = refs;
    }
    this._renderSelection();
  }

  // Paint selection state + restore each selected room's saved setting values. Cheap; called on
  // toggle and on room-list rebuild (NOT on every hass tick, so open dropdowns aren't disturbed).
  _renderSelection() {
    for (const room of this._lastRooms) {
      const refs = this._roomEls[room.id];
      if (!refs) continue;
      const idx = this._sel.indexOf(room.id);
      const on = idx >= 0;
      refs.el.classList.toggle("selected", on);
      refs.order.textContent = on ? String(idx + 1) : "";
      refs.rset.hidden = !on;
      const c = this._roomCfg[room.id] || this._defaultRoomCfg();
      refs.mode.value = c.clean_mode;
      refs.fan.value = c.fan_speed;
      refs.water.value = c.water_level;
      refs.int.value = c.clean_intensity;
      refs.passes.value = String(c.clean_times || 1);
      refs.edge.value = c.edge;
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

  // Resolve a tap on the live map to a room (server-side hit-test against the room mask) and
  // toggle it. No client-side geometry needed — the integration owns the mask + transforms.
  async _resolveRoomTap(nx, ny) {
    if (!this._hass) return;
    let rid = 0;
    try {
      const r = await this._hass.callService(
        "robovac_mqtt",
        "room_at_point",
        { x: nx, y: ny },
        { entity_id: this._config.vacuum },
        false,
        true
      );
      // Entity-service responses are keyed by entity_id, e.g.
      // { response: { "vacuum.alfred": { room_id, room_name } } } — unwrap that
      // (with a direct / first-value fallback just in case).
      const resp = (r && r.response) || {};
      const entry =
        resp[this._config.vacuum] ||
        (resp.room_id !== undefined ? resp : Object.values(resp)[0]) ||
        {};
      rid = Number(entry.room_id) || 0;
    } catch (err) {
      this._setStatus(`Tap lookup failed: ${err && err.message ? err.message : err}`);
      return;
    }
    // Only real, listed rooms are selectable; background/unmapped pixels (rid 0 or the
    // mask's background id) resolve to nothing.
    const room = rid ? this._lastRooms.find((r) => r.id === rid) : null;
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

  // --- per-hass-update sync (image, rooms, zones selects, status) ----------------------------
  _syncDynamic() {
    const hass = this._hass;
    if (!hass || !this._built) return;

    // backdrop — show/hide + an INSTANT refresh whenever the camera entity changes (last_updated)
    // or on first paint. Between those, _startPolling keeps it fresh.
    if (this._hasCamera()) {
      const cam = hass.states[this._config.camera];
      const pic = cam && cam.attributes && cam.attributes.entity_picture;
      if (pic) {
        this._els.img.hidden = false;
        this._els.nomap.hidden = true;
        const lu = cam.last_updated || "";
        if (lu !== this._lastCamUpdate || !this._lastImgSrc) {
          this._lastCamUpdate = lu;
          this._refreshMap();
        }
      } else {
        this._els.img.removeAttribute("src");
        this._lastImgSrc = "";
        this._els.img.hidden = true;
        this._els.nomap.hidden = false;
      }
    }

    // rooms — full rebuild only when the room-ID SET changes; a pure rename updates labels in
    // place so an open per-room dropdown isn't torn down mid-interaction.
    const rooms = this._rooms();
    const idKey = rooms.map((r) => r.id).join(",");
    if (idKey !== this._roomIdKey) {
      this._lastRooms = rooms;
      const ids = new Set(rooms.map((r) => r.id));
      // drop selection/config/pins for rooms that no longer exist (ids are numeric; object keys
      // are strings, so coerce before the Set check)
      this._sel = this._sel.filter((id) => ids.has(id));
      for (const k of Object.keys(this._roomCfg)) if (!ids.has(Number(k))) delete this._roomCfg[k];
      for (const k of Object.keys(this._roomPins)) if (!ids.has(Number(k))) delete this._roomPins[k];
      this._rebuildRooms(rooms);
      this._roomIdKey = idKey;
    } else {
      for (const room of rooms) {
        const prev = this._lastRooms.find((r) => r.id === room.id);
        const refs = this._roomEls[room.id];
        if (prev && refs && prev.name !== room.name) refs.rname.textContent = room.name;
      }
      this._lastRooms = rooms;
    }

    // zones settings selects (only while that mode is showing them)
    if (this._mode === "zones" && this._hasCamera()) this._syncZoneSelects();

    this._syncControls();
  }

  _syncControls() {
    if (this._mode === "zones") {
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
        const how = this._hasCamera() ? "Tap rooms on the map or list" : "Tap rooms to select";
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

  _clearAll() {
    if (this._mode === "zones") {
      this._zones = [];
      this._drag = null;
    } else {
      this._sel = [];
      this._roomPins = {};
      this._renderSelection();
    }
    this._renderOverlay();
    this._syncControls();
    this._setStatus("");
  }

  // --- overlay render -------------------------------------------------------------------------
  _renderOverlay() {
    if (!this._els) return;
    if (this._mode === "rooms") {
      // numbered pins for rooms picked on the map (list-picked rooms have no pin)
      const parts = [];
      this._sel.forEach((id, i) => {
        const p = this._roomPins[id];
        if (!p) return;
        const x = p.nx * 100, y = p.ny * 100;
        parts.push(`<circle class="pin" cx="${x}%" cy="${y}%" r="11" />`);
        parts.push(`<text class="pinnum" x="${x}%" y="${y}%" dy="4">${i + 1}</text>`);
      });
      this._els.overlay.innerHTML = parts.join("");
      return;
    }
    const parts = [];
    this._zones.forEach((z, i) => {
      const x = z.x0 * 100, y = z.y0 * 100, w = (z.x1 - z.x0) * 100, h = (z.y1 - z.y0) * 100;
      parts.push(`<rect class="zone" x="${x}%" y="${y}%" width="${w}%" height="${h}%" />`);
      parts.push(`<text class="num" x="${x}%" y="${y}%" dx="6" dy="16">${i + 1}</text>`);
    });
    if (this._drag) {
      const d = this._drag;
      const x = Math.min(d.x0, d.x1) * 100, y = Math.min(d.y0, d.y1) * 100;
      const w = Math.abs(d.x1 - d.x0) * 100, h = Math.abs(d.y1 - d.y0) * 100;
      parts.push(`<rect class="draft" x="${x}%" y="${y}%" width="${w}%" height="${h}%" />`);
    }
    this._els.overlay.innerHTML = parts.join("");
  }

  // --- dispatch -------------------------------------------------------------------------------
  _clean() {
    if (this._dispatching) return;
    if (this._mode === "zones") this._cleanZones();
    else this._cleanRooms();
  }

  async _cleanZones() {
    if (!this._hass || this._zones.length === 0) return;
    const zones = this._zones.map((z) => [z.x0, z.y0, z.x1, z.y1]);
    const n = zones.length;
    this._dispatching = true;
    this._syncControls();
    try {
      await this._hass.callService("vacuum", "send_command", {
        entity_id: this._config.vacuum,
        command: "zone_clean",
        params: { zones, clean_times: this._cleanTimes },
      });
      this._zones = [];
      this._renderOverlay();
      this._setStatus(`Sent ${n} zone${n > 1 ? "s" : ""} • passes ${this._cleanTimes}`);
    } catch (err) {
      this._setStatus(`Failed: ${err && err.message ? err.message : err}`);
    } finally {
      this._dispatching = false;
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
    // Any per-room customization → send the rich per-room payload (CUSTOMIZE). Otherwise a plain
    // room_ids list → a GENERAL clean (matches the integration's own "don't force CUSTOMIZE" rule).
    const hasCustom = rooms.some((r) => Object.keys(r).length > 1);
    const params = hasCustom ? { rooms } : { room_ids: this._sel.map(Number) };
    this._dispatching = true;
    this._syncControls();
    try {
      await this._hass.callService("vacuum", "send_command", {
        entity_id: this._config.vacuum,
        command: "room_clean",
        params,
      });
      this._sel = [];
      this._roomPins = {};
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
    return { vacuum, camera }; // selects auto-discovered from the vacuum slug
  }

  static getConfigElement() {
    return document.createElement("eufy-clean-card-editor");
  }
}

customElements.define("eufy-clean-card", EufyCleanCard);

// Backward-compat alias: existing `type: custom:zone-clean-card` dashboards keep working and open
// in ZONES mode. Same card, different default — a distinct subclass is required because a custom
// element constructor can only be registered under one tag name.
class ZoneCleanCard extends EufyCleanCard {
  get _defaultMode() {
    return "zones";
  }
}
customElements.define("zone-clean-card", ZoneCleanCard);

/* ------------------------------------------------------------------------------------------
 * Visual config editor — vanilla, no Lit, no dependencies.
 * ---------------------------------------------------------------------------------------- */
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
    const opt = (list, sel) =>
      ['<option value="">— choose —</option>']
        .concat(list.map((e) => `<option value="${esc(e)}"${e === sel ? " selected" : ""}>${esc(e)}</option>`))
        .join("");
    const modeOpt = (sel) =>
      [["rooms", "Rooms"], ["zones", "Zones"]]
        .map(([v, l]) => `<option value="${v}"${v === sel ? " selected" : ""}>${l}</option>`)
        .join("");
    const picks = this._list("select");
    this.innerHTML = `
      <style>
        .ecce { display: flex; flex-direction: column; gap: 12px; padding: 4px 2px; }
        .ecce label.fld { font-size: 0.85rem; font-weight: 500; display: block; margin-bottom: 2px; }
        .ecce select, .ecce input[type=text] { width: 100%; padding: 7px 8px; box-sizing: border-box;
          border: 1px solid var(--divider-color, #ccc); border-radius: 6px;
          background: var(--card-background-color, #fff); color: var(--primary-text-color, #000); }
        .ecce .hint { font-size: 0.75rem; color: var(--secondary-text-color, #888); margin-top: 2px; }
        .ecce .picks { display: flex; flex-direction: column; gap: 4px; max-height: 180px; overflow: auto;
          border: 1px solid var(--divider-color, #ccc); border-radius: 6px; padding: 8px; }
        .ecce .picks label { font-weight: 400; font-size: 0.85rem; display: flex; gap: 8px; align-items: center; margin: 0; }
      </style>
      <div class="ecce">
        <div><label class="fld">Vacuum (required)</label>
          <select class="f-vacuum">${opt(this._list("vacuum"), this._config.vacuum)}</select></div>
        <div><label class="fld">Map camera (needed for Zones, map taps + the backdrop)</label>
          <select class="f-camera">${opt(this._list("camera"), this._config.camera)}</select></div>
        <div><label class="fld">Default mode</label>
          <select class="f-mode">${modeOpt(this._config.mode || "rooms")}</select></div>
        <div><label class="fld">Title</label>
          <input type="text" class="f-title" placeholder="Eufy Clean" value="${(this._config.title || "").replace(/"/g, "&quot;")}" /></div>
        <div>
          <label class="fld">Zones: setting selects</label>
          <div class="picks">${
            picks
              .map((e) => {
                const on = (this._config.selects || []).includes(e);
                return `<label><input type="checkbox" value="${e}"${on ? " checked" : ""}/> ${e}</label>`;
              })
              .join("") || '<span class="hint">No select entities found.</span>'
          }</div>
          <div class="hint">Leave all unchecked to auto-discover the vacuum's selects. (Zones mode only.)</div>
        </div>
      </div>
    `;
    this.querySelector(".f-vacuum").addEventListener("change", () => this._changed());
    this.querySelector(".f-camera").addEventListener("change", () => this._changed());
    this.querySelector(".f-mode").addEventListener("change", () => this._changed());
    this.querySelector(".f-title").addEventListener("input", () => this._changed());
    this.querySelectorAll(".picks input[type=checkbox]").forEach((cb) =>
      cb.addEventListener("change", () => this._changed())
    );
    this._built = true;
  }

  _fill() {
    const v = this.querySelector(".f-vacuum"); if (v) v.value = this._config.vacuum || "";
    const c = this.querySelector(".f-camera"); if (c) c.value = this._config.camera || "";
    const m = this.querySelector(".f-mode"); if (m) m.value = this._config.mode || "rooms";
    // title + checkboxes intentionally left untouched to avoid cursor/scroll jumps
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
    const mode = val(".f-mode");
    if (mode && mode !== "rooms") cfg.mode = mode; else delete cfg.mode;
    const t = val(".f-title").trim();
    if (t) cfg.title = t; else delete cfg.title;
    const checked = Array.from(this.querySelectorAll(".picks input:checked")).map((c) => c.value);
    if (checked.length) cfg.selects = checked; else delete cfg.selects;
    this._config = cfg;
    this._emitting = true;
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: cfg }, bubbles: true, composed: true }));
    this._emitting = false;
  }
}
customElements.define("eufy-clean-card-editor", EufyCleanCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "eufy-clean-card",
  name: "Eufy Clean Card",
  description: "Clean rooms with per-room settings (tap them on the map), or draw zones (Eufy — jeppesens/eufy-clean).",
});
console.info(
  "%c EUFY-CLEAN-CARD %c rooms + zones ",
  "background:#3b82f6;color:#fff;border-radius:3px 0 0 3px;padding:2px 4px",
  "background:#222;color:#fff;border-radius:0 3px 3px 0;padding:2px 4px"
);
