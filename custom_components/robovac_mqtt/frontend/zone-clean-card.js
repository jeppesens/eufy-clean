/*
 * zone-clean-card  —  draw-a-box zone cleaning for Eufy (jeppesens/eufy-clean)
 * ----------------------------------------------------------------------------
 * Draw boxes on the live map, pick your settings, hit Clean.
 *
 * BUNDLED CARD: this file ships inside the eufy-clean integration and is
 * auto-registered on setup — there is no www/ copy and no Lovelace "Resources"
 * entry to add. Just drop the card on a dashboard:
 *
 *       type: custom:zone-clean-card
 *       vacuum: vacuum.your_robot
 *       camera: camera.your_robot_map
 *       # title: Zone Clean        # optional
 *       # selects:                 # optional — if omitted, every select.<vacuum-slug>_*
 *       #   - select.your_robot_suction_level   #   entity is auto-surfaced. List them to
 *       #   - select.your_robot_water_level     #   pick/order a specific subset.
 *
 * What it does (and nothing more):
 *   1. shows the vacuum's live map camera as a backdrop
 *   2. lets you rubber-band up to 10 zones on it
 *   3. surfaces the vacuum's setting `select` entities (you change them live; the zone clean
 *      runs with whatever they're set to — no params embedded)
 *   4. fires vacuum.send_command { command: zone_clean, params: { zones, clean_times } }
 *
 * It pairs with the integration's `zone_clean` send_command handler, which takes NORMALIZED
 * (0-1) rects of the rendered map image (top-left origin) and converts them to world-cm
 * itself. Because this card draws on the image at its natural aspect ratio, the drawn
 * fraction IS the image fraction — no letterbox correction needed. Brand-agnostic otherwise:
 * any vacuum + camera + select entities work.
 *
 * Note: the map only renders after the robot has cleaned once (or you edit the map in the app).
 */

const MAX_ZONES = 10;
const MIN_FRAC = 0.012; // reject degenerate drags smaller than ~1% of the map in either axis
const clamp01 = (v) => Math.min(Math.max(v, 0), 1);

class ZoneCleanCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._zones = [];          // committed zones: {x0,y0,x1,y1} normalized
    this._drag = null;         // in-progress drag: {x0,y0,x1,y1} normalized
    this._cleanTimes = 1;      // passes per zone (Zone.clean_times)
    this._built = false;
    this._lastImgSrc = "";
    this._optSig = {};         // per-select option-list signature, to avoid rebuilding while open
  }

  setConfig(config) {
    if (!config || !config.vacuum) throw new Error("zone-clean-card: 'vacuum' is required");
    if (!config.camera) throw new Error("zone-clean-card: 'camera' is required");
    this._config = {
      title: "Zone Clean",
      selects: [],
      ...config,
    };
    this._zones = [];
    this._drag = null;
    if (this._built) this._selectsKey = null; // config changed at runtime -> rebuild on next sync
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
  }

  // Keep the map fresh. The camera re-renders the map WITHOUT always bumping the
  // entity's last_updated, so refreshing only on a state change leaves it stale (the
  // "stale map" symptom). Poll the image on a cadence instead: ~3s while the robot is
  // moving (matches the fork's ~2s render throttle), and just re-check (no re-fetch)
  // every 10s while it's parked — the map doesn't change when docked, and a real state
  // change still refreshes instantly via _syncDynamic. Stops when the card leaves the DOM.
  _startPolling() {
    clearTimeout(this._pollTimer);
    const tick = () => {
      const active = this._vacuumActive();
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

  // Re-fetch the camera image with a fresh cache-bust so the latest render shows.
  // Skipped mid-draw so the backdrop never swaps out from under an in-progress box.
  _refreshMap() {
    if (!this._built || !this._hass || this._drag) return;
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
        .map-wrap { position: relative; width: 100%; max-width: 520px; margin: 0 auto;
                    border-radius: 8px; overflow: hidden; background: var(--secondary-background-color); }
        .map-wrap img { display: block; width: 100%; height: auto; user-select: none; -webkit-user-drag: none; }
        /* width/height:100% are REQUIRED — an inline <svg> is a replaced element with a
           default 300x150 intrinsic size, and inset:0 alone does NOT stretch it (so it'd
           sit at 300x150 in the top-left, and only that corner would be drawable). */
        .overlay { position: absolute; inset: 0; width: 100%; height: 100%;
                   touch-action: none; cursor: crosshair; }
        .nomap { padding: 40px 12px; text-align: center; color: var(--secondary-text-color);
                 font-size: 0.9rem; }
        .settings { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                    gap: 8px 12px; margin-top: 12px; }
        .field { display: flex; flex-direction: column; gap: 2px; }
        .field label { font-size: 0.72rem; color: var(--secondary-text-color); text-transform: uppercase;
                       letter-spacing: 0.03em; }
        .field select { padding: 6px 8px; border-radius: 6px; border: 1px solid var(--divider-color);
                        background: var(--card-background-color); color: var(--primary-text-color);
                        font-size: 0.9rem; }
        .controls { display: flex; align-items: center; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
        .passes { display: flex; align-items: center; gap: 6px; font-size: 0.85rem;
                  color: var(--secondary-text-color); }
        .passes input { width: 52px; padding: 5px 6px; border-radius: 6px;
                        border: 1px solid var(--divider-color); background: var(--card-background-color);
                        color: var(--primary-text-color); font-size: 0.9rem; }
        .status { flex: 1 1 100%; font-size: 0.82rem; color: var(--secondary-text-color); }
        button { font: inherit; padding: 8px 14px; border-radius: 8px; border: none; cursor: pointer; }
        button:disabled { opacity: 0.45; cursor: default; }
        .clean { background: var(--primary-color); color: var(--text-primary-color, #fff); font-weight: 500; }
        .ghost { background: transparent; color: var(--primary-text-color); border: 1px solid var(--divider-color); }
        rect.zone { fill: var(--primary-color); fill-opacity: 0.22; stroke: var(--primary-color); stroke-width: 2; }
        rect.draft { fill: var(--primary-color); fill-opacity: 0.12; stroke: var(--primary-color);
                     stroke-width: 2; stroke-dasharray: 6 4; }
        text.num { fill: var(--text-primary-color, #fff); font-size: 13px; font-weight: 700;
                   paint-order: stroke; stroke: var(--primary-color); stroke-width: 3; }
      </style>
      <ha-card>
        <div class="title"></div>
        <div class="map-wrap">
          <img class="map" alt="vacuum map" />
          <svg class="overlay" preserveAspectRatio="none"></svg>
          <div class="nomap" hidden>Waiting for the map… run a clean once (or edit the map in the app) so it renders.</div>
        </div>
        <div class="settings"></div>
        <div class="controls">
          <span class="passes">Passes
            <input class="ct" type="number" min="1" max="10" step="1" value="1" />
          </span>
          <button class="ghost clear">Clear</button>
          <button class="clean" disabled>Clean</button>
          <span class="status"></span>
        </div>
      </ha-card>
    `;

    this._els = {
      title: this.shadowRoot.querySelector(".title"),
      img: this.shadowRoot.querySelector("img.map"),
      overlay: this.shadowRoot.querySelector("svg.overlay"),
      nomap: this.shadowRoot.querySelector(".nomap"),
      settings: this.shadowRoot.querySelector(".settings"),
      ct: this.shadowRoot.querySelector("input.ct"),
      clear: this.shadowRoot.querySelector("button.clear"),
      clean: this.shadowRoot.querySelector("button.clean"),
      status: this.shadowRoot.querySelector(".status"),
    };
    this._els.title.textContent = c.title;

    // draw handlers (pointer events = mouse + touch)
    const ov = this._els.overlay;
    const toFrac = (e) => {
      const r = ov.getBoundingClientRect();
      return { x: clamp01((e.clientX - r.left) / r.width), y: clamp01((e.clientY - r.top) / r.height) };
    };
    ov.addEventListener("pointerdown", (e) => {
      if (this._els.nomap.hidden === false) return; // no map yet
      ov.setPointerCapture(e.pointerId);
      const p = toFrac(e);
      this._drag = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
      this._renderOverlay();
    });
    ov.addEventListener("pointermove", (e) => {
      if (!this._drag) return;
      const p = toFrac(e);
      this._drag.x1 = p.x;
      this._drag.y1 = p.y;
      this._renderOverlay();
    });
    const finish = (e) => {
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
    ov.addEventListener("pointerup", finish);
    ov.addEventListener("pointercancel", finish);

    this._els.ct.addEventListener("change", () => {
      let n = parseInt(this._els.ct.value, 10);
      if (!Number.isFinite(n)) n = 1;
      n = Math.min(Math.max(n, 1), 10);
      this._cleanTimes = n;
      this._els.ct.value = String(n);
    });
    this._els.clear.addEventListener("click", () => {
      this._zones = [];
      this._drag = null;
      this._renderOverlay();
      this._syncControls();
      this._setStatus("");
    });
    this._els.clean.addEventListener("click", () => this._clean());

    this._selectsKey = null;
    this._selectEls = {};
    this._built = true;
  }

  // --- settings selects ----------------------------------------------------------------------
  // Effective select list: explicit `selects:` if given, else auto-discover every
  // `select.<vacuum-slug>_*` entity so the card is plug-in with just vacuum + camera.
  _effectiveSelects() {
    if (this._config.selects && this._config.selects.length) return this._config.selects;
    if (!this._hass) return [];
    const slug = (this._config.vacuum.split(".")[1] || "");
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
        this._hass.callService("select", "select_option", {
          entity_id: eid,
          option: sel.value,
        });
      });
      field.appendChild(label);
      field.appendChild(sel);
      wrap.appendChild(field);
      this._selectEls[eid] = { field, label, sel };
    }
  }

  // --- per-hass-update sync (image, selects, status) -----------------------------------------
  _syncDynamic() {
    const hass = this._hass;
    if (!hass) return;
    const cam = hass.states[this._config.camera];

    // backdrop — show/hide + an INSTANT refresh whenever the camera entity changes
    // (last_updated) or on first paint. Between those, _startPolling() keeps it fresh
    // (the camera re-renders the map without always bumping last_updated).
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

    // settings selects — (re)build the controls if the effective list changed
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
      const fname = (st.attributes && st.attributes.friendly_name) || eid;
      refs.label.textContent = fname;
      const opts = (st.attributes && st.attributes.options) || [];
      const sig = opts.join("");
      if (sig !== this._optSig[eid]) {
        refs.sel.innerHTML = opts.map((o) => `<option value="${o}">${o}</option>`).join("");
        this._optSig[eid] = sig;
      }
      // don't fight the user if the dropdown is open / focused
      if (this.shadowRoot.activeElement !== refs.sel) refs.sel.value = st.state;
    }

    this._syncControls();
  }

  _syncControls() {
    const n = this._zones.length;
    this._els.clean.disabled = n === 0;
    this._els.clean.textContent = n > 0 ? `Clean ${n} zone${n > 1 ? "s" : ""}` : "Clean";
    if (!this._statusSticky) {
      this._els.status.textContent = n
        ? `${n}/${MAX_ZONES} zones drawn`
        : "Drag on the map to draw a zone.";
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

  // --- overlay render ------------------------------------------------------------------------
  _renderOverlay() {
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

  // --- dispatch ------------------------------------------------------------------------------
  async _clean() {
    if (!this._hass || this._zones.length === 0) return;
    const zones = this._zones.map((z) => [z.x0, z.y0, z.x1, z.y1]);
    const n = zones.length;
    this._els.clean.disabled = true;
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
    }
    this._syncControls();
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
    return document.createElement("zone-clean-card-editor");
  }
}

customElements.define("zone-clean-card", ZoneCleanCard);

/* ------------------------------------------------------------------------------------------
 * Visual config editor — vanilla, no Lit, no dependencies. Renders in the dashboard card
 * editor so you can pick entities by clicking instead of writing YAML.
 * ---------------------------------------------------------------------------------------- */
class ZoneCleanCardEditor extends HTMLElement {
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
    return Object.keys(s).filter((e) => e.startsWith(domain + ".")).sort();
  }

  _build() {
    if (!this._hass || !this._config) return;
    const opt = (list, sel) =>
      ['<option value="">— choose —</option>']
        .concat(list.map((e) => `<option value="${e}"${e === sel ? " selected" : ""}>${e}</option>`))
        .join("");
    const picks = this._list("select");
    this.innerHTML = `
      <style>
        .zcce { display: flex; flex-direction: column; gap: 12px; padding: 4px 2px; }
        .zcce label.fld { font-size: 0.85rem; font-weight: 500; display: block; margin-bottom: 2px; }
        .zcce select, .zcce input[type=text] { width: 100%; padding: 7px 8px; box-sizing: border-box;
          border: 1px solid var(--divider-color, #ccc); border-radius: 6px;
          background: var(--card-background-color, #fff); color: var(--primary-text-color, #000); }
        .zcce .hint { font-size: 0.75rem; color: var(--secondary-text-color, #888); margin-top: 2px; }
        .zcce .picks { display: flex; flex-direction: column; gap: 4px; max-height: 180px; overflow: auto;
          border: 1px solid var(--divider-color, #ccc); border-radius: 6px; padding: 8px; }
        .zcce .picks label { font-weight: 400; font-size: 0.85rem; display: flex; gap: 8px; align-items: center; margin: 0; }
      </style>
      <div class="zcce">
        <div><label class="fld">Vacuum (required)</label>
          <select class="f-vacuum">${opt(this._list("vacuum"), this._config.vacuum)}</select></div>
        <div><label class="fld">Map camera (required)</label>
          <select class="f-camera">${opt(this._list("camera"), this._config.camera)}</select></div>
        <div><label class="fld">Title</label>
          <input type="text" class="f-title" placeholder="Zone Clean" value="${(this._config.title || "").replace(/"/g, "&quot;")}" /></div>
        <div>
          <label class="fld">Setting selects</label>
          <div class="picks">${
            picks.map((e) => {
              const on = (this._config.selects || []).includes(e);
              return `<label><input type="checkbox" value="${e}"${on ? " checked" : ""}/> ${e}</label>`;
            }).join("") || '<span class="hint">No select entities found.</span>'
          }</div>
          <div class="hint">Leave all unchecked to auto-discover the vacuum's selects.</div>
        </div>
      </div>
    `;
    this.querySelector(".f-vacuum").addEventListener("change", () => this._changed());
    this.querySelector(".f-camera").addEventListener("change", () => this._changed());
    this.querySelector(".f-title").addEventListener("input", () => this._changed());
    this.querySelectorAll(".picks input[type=checkbox]").forEach((cb) =>
      cb.addEventListener("change", () => this._changed())
    );
    this._built = true;
  }

  _fill() {
    const v = this.querySelector(".f-vacuum"); if (v) v.value = this._config.vacuum || "";
    const c = this.querySelector(".f-camera"); if (c) c.value = this._config.camera || "";
    // title + checkboxes intentionally left untouched to avoid cursor/scroll jumps
  }

  _changed() {
    const val = (q) => { const el = this.querySelector(q); return el ? el.value : ""; };
    const cfg = Object.assign({}, this._config);
    cfg.vacuum = val(".f-vacuum");
    cfg.camera = val(".f-camera");
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
customElements.define("zone-clean-card-editor", ZoneCleanCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "zone-clean-card",
  name: "Zone Clean Card",
  description: "Draw zones on the live map and clean them (Eufy — smcneece/jeppesens eufy-clean).",
});
console.info("%c ZONE-CLEAN-CARD %c standalone ", "background:#3b82f6;color:#fff;border-radius:3px 0 0 3px;padding:2px 4px", "background:#222;color:#fff;border-radius:0 3px 3px 0;padding:2px 4px");
