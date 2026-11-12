import { JSDOM } from "jsdom";
import { cardSource } from "./harness.mjs";

// See harness.mjs: the card is a real ES module, jsdom can only run classic scripts.
const code = cardSource();

const dom = new JSDOM(`<!doctype html><html><body></body></html>`, {
  runScripts: "dangerously",
  url: "https://localhost/",
  pretendToBeVisual: true,
});
const { window } = dom;
const { document } = window;

// run the card inside the jsdom window
const s = document.createElement("script");
s.textContent = code;
document.body.appendChild(s);

let fail = 0;
const ok = (c, m) => { if (c) console.log("  ok:", m); else { console.error("  FAIL:", m); fail++; } };

// ---- build a fake hass -------------------------------------------------------
function makeHass() {
  return {
    states: {
      "vacuum.robot": {
        state: "docked",
        attributes: {
          fan_speed_list: ["Quiet", "Standard", "Turbo", "Max"],
          rooms: [{ id: 0, name: "Living Room" }, { id: 1, name: "Kitchen" }, { id: 2, name: "Hall" }],
          nogo_zones_supported: true,
        },
        last_updated: "t0",
      },
      "camera.robot_map": { state: "idle", attributes: { entity_picture: "/pic.png" }, last_updated: "c0" },
      "sensor.robot_active_map": { state: "1", attributes: {} },
      "sensor.robot_robot_position_x_raw": { state: "10", attributes: {} },
      "sensor.robot_robot_position_y_raw": { state: "20", attributes: {} },
      "select.robot_switch_map": { state: "Map 1", attributes: { options: ["Map 1", "Map 2"] } },
      "select.robot_cleaning_mode": { state: "vacuum", attributes: { options: ["vacuum", "mop"] } },
      // Consumables: one life sensor per part, one reset button per part. The sensor-cleaning
      // pair is named "Sensor Remaining" / "Reset Sensors", so the keys differ by a plural.
      // Plus the asymmetries the card must survive: a reset with no life sensor
      // (`reset_dust_bag`) and an unavailable reset.
      "sensor.robot_filter_remaining": {
        state: "153",
        attributes: {
          friendly_name: "Robot Filter Remaining", unit_of_measurement: "h",
          percent_remaining: 76, total_life_hours: 200,
        },
      },
      "sensor.robot_side_brush_remaining": {
        state: "17",
        attributes: {
          friendly_name: "Robot Side Brush Remaining", unit_of_measurement: "h",
          percent_remaining: 9, total_life_hours: 180,
        },
      },
      "sensor.robot_sensor_remaining": {
        state: "25",
        attributes: {
          friendly_name: "Robot Sensor Remaining", unit_of_measurement: "h",
          percent_remaining: 83, total_life_hours: 30,
        },
      },
      "button.robot_reset_filter": { state: "unknown", attributes: { friendly_name: "Robot Reset Filter" } },
      "button.robot_reset_side_brush": { state: "unknown", attributes: { friendly_name: "Robot Reset Side Brush" } },
      "button.robot_reset_sensors": { state: "unavailable", attributes: { friendly_name: "Robot Reset Sensors" } },
      "button.robot_reset_dust_bag": { state: "unknown", attributes: { friendly_name: "Robot Reset Dust Bag" } },
    },
    entities: {
      "vacuum.robot": { device_id: "dev1", platform: "robovac_mqtt" },
      "sensor.robot_active_map": { device_id: "dev1" },
      "sensor.robot_robot_position_x_raw": { device_id: "dev1" },
      "sensor.robot_robot_position_y_raw": { device_id: "dev1" },
      "select.robot_switch_map": { device_id: "dev1" },
    },
    _calls: [],
    callService(domain, service, data, target, a, b) {
      this._calls.push({ domain, service, data, target });
      if (domain === "robovac_mqtt" && service === "room_at_point") {
        // simulate a legacy room 0 being under the point
        return Promise.resolve({ response: { "vacuum.robot": { room_id: 0, room_name: "Living Room" } } });
      }
      return Promise.resolve({});
    },
  };
}

// ---- 1. card constructs + setConfig + hass ----------------------------------
console.log("[1] card lifecycle");
const Card = window.customElements.get("eufy-clean-card");
ok(!!Card, "eufy-clean-card is defined");
const card = new Card();
card.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
card.hass = makeHass();
document.body.appendChild(card);
const sr = card.shadowRoot;
ok(!!sr.querySelector("ha-card"), "renders ha-card");

// ---- 2. aria wiring ----------------------------------------------------------
console.log("[2] accessibility");
ok(sr.querySelector(".status").getAttribute("aria-live") === "polite", "status has aria-live=polite");
ok(sr.querySelector(".modebar").getAttribute("role") === "group", "modebar role=group");
ok(sr.querySelector(".mode-rooms").getAttribute("aria-pressed") === "true", "rooms toggle aria-pressed=true");
ok(sr.querySelector(".mode-zones").getAttribute("aria-pressed") === "false", "zones toggle aria-pressed=false");
ok(sr.querySelector(".gate").getAttribute("role") === "alert", "gate role=alert");
ok(sr.querySelector(".mapswitch").getAttribute("aria-label") === "Switch map", "mapswitch aria-label");
const firstSel = sr.querySelector(".rooms .room select.f-mode");
ok(firstSel && firstSel.getAttribute("aria-label") === "Mode", "per-room select has aria-label");
const firstGroup = sr.querySelector(".rooms .room");
ok(firstGroup && firstGroup.getAttribute("role") === "group", "room is role=group");
ok(firstGroup && firstGroup.getAttribute("aria-label") === "Living Room", "room group aria-label = name");
ok(!!sr.querySelector("style").textContent.includes(":focus-visible"), "focus-visible styles present");

// ---- 3. rooms rendered (incl. room 0) ---------------------------------------
console.log("[3] rooms");
const roomEls = sr.querySelectorAll(".rooms .room");
ok(roomEls.length === 3, "3 rooms rendered (incl. id 0)");

// ---- 4. mode toggle updates aria + touch-action -----------------------------
console.log("[4] mode toggle");
card._setMode("zones");
ok(sr.querySelector(".mode-zones").getAttribute("aria-pressed") === "true", "zones aria-pressed after toggle");
ok(card._els.overlay.style.touchAction === "none", "zones locks touch-action:none");
card._setMode("rooms");
ok(card._els.overlay.style.touchAction === "pan-y", "rooms allows touch-action:pan-y");

// ---- 5. room-0 tap select (the bug fix) -------------------------------------
console.log("[5] room-0 tap");
await card._resolveRoomTap(0.5, 0.5);
ok(card._sel.includes(0), "tapping room 0 selects it (not discarded as 'no room')");

// ---- 6. entity-resolution cache --------------------------------------------
console.log("[6] entity cache");
ok(card._entCache["sib:sensor:_active_map"] === "sensor.robot_active_map", "sibling resolution cached");
ok(card._entCache.mapswitch === "select.robot_switch_map", "mapswitch resolution cached");

// ---- 7. getCardSize dynamic -------------------------------------------------
console.log("[7] getCardSize");
const sz = card.getCardSize();
ok(sz === 3 + 5 + 3, `getCardSize reflects header+camera+rooms (${sz})`);

// ---- 8. editor has no edge-mop toggle ---------------------------------------
// The editor has no edge-mop toggle; the device declares the field (`room_clean_options`).
// A dashboard that set the old key must keep working and not be rewritten on an unrelated edit.
console.log("[8] editor edge-mop removed + config migration");
const Editor = window.customElements.get("eufy-clean-card-editor");
const ed = new Editor();
document.body.appendChild(ed);
ed.setConfig({ vacuum: "vacuum.robot", hide_edge_mop: true }); // HA calls setConfig BEFORE hass
ed.hass = makeHass();
let emitted = null;
ed.addEventListener("config-changed", (e) => (emitted = e.detail.config));
ok(!ed.querySelector(".f-edge-mop"), "edge-mop checkbox is gone from the editor");
// Title is the vehicle for "an unrelated edit" now: the editor's Default-mode select went
// with the CANVAS_DEFAULT Stage 2 rebuild (`mode:` and `selects:` are still honoured from
// YAML, they just have no editor control). Any surviving field would do -- the assertion
// is about hide_edge_mop surviving an edit that has nothing to do with it.
ed.querySelector(".f-title").value = "Kitchen Bot";
ed.querySelector(".f-title").dispatchEvent(new window.Event("input"));
ok(emitted && emitted.title === "Kitchen Bot", "an unrelated editor edit still emits");
ok(emitted && emitted.hide_edge_mop === true, "a pre-existing hide_edge_mop is carried through untouched");

// ---- 8b. the editor uses NATIVE controls, and shows the config it was given ----
// Reported from Firefox: dropdowns unselectable, Save greyed out, Title blank. Cause was an
// editor built out of ha-select / ha-switch / ha-textfield inside an `innerHTML` string:
//   - `.value="${...}"` is not a property binding there, it is a dead attribute, so every
//     field rendered empty no matter what the config said;
//   - ha-select emits `selected`/`closed`, never a plain `change`, so nothing ever reached
//     _changed() and HA never saw a config-changed -> Save stayed disabled;
//   - `mwc-list-item` is not guaranteed to be registered, so the lists could be empty.
// jsdom cannot see any of that (an unknown element still answers querySelector and takes a
// .value), so these assert the SHAPE that made it unreproducible: native controls only.
console.log("[8b] editor uses native controls and reflects its config");
const ed2 = new Editor();
document.body.appendChild(ed2);
ed2.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map", title: "Robot" });
ed2.hass = makeHass();
ok(!ed2.querySelector("ha-select, ha-textfield, ha-switch, mwc-list-item, ha-list-item"),
   "no HA-internal form components in the editor");
ok(ed2.querySelector("select.f-vacuum") && ed2.querySelector("select.f-camera"),
   "vacuum + camera are native <select>");
ok(ed2.querySelector('input.f-title[type="text"]'), "title is a native text input");
ok(ed2.querySelector('input.f-clientrender[type="checkbox"]'), "client_render is a native checkbox");
// The values must be in the MARKUP: HA calls setConfig before hass, so the setConfig->_fill
// path is a no-op on the first render and cannot be what supplies them.
ok(ed2.querySelector(".f-vacuum").value === "vacuum.robot", "vacuum select shows the configured entity");
ok(ed2.querySelector(".f-camera").value === "camera.robot_map", "camera select shows the configured entity");
ok(ed2.querySelector(".f-title").value === "Robot", "title input shows the configured title");
// _clientRenderEnabled() treats a missing key as ON since 1.16.21, so NO key means ON. Rendering it
// checked (the `!== false` the rebuild shipped) told the user the opposite of the truth.
ok(ed2.querySelector(".f-clientrender").checked === true, "no client_render key renders CHECKED (default on)");
const edOn = new Editor();
document.body.appendChild(edOn);
edOn.setConfig({ vacuum: "vacuum.robot", client_render: false });
edOn.hass = makeHass();
ok(edOn.querySelector(".f-clientrender").checked === false, "client_render:false renders unchecked");

// Every control must reach _changed(), or Save never lights up.
for (const [sel, ev, set, check, label] of [
  [".f-vacuum", "change", (el) => (el.value = ""), (c) => c.vacuum === "", "vacuum"],
  [".f-camera", "change", (el) => (el.value = ""), (c) => c.camera === undefined, "camera (cleared)"],
  // The rebuilt _changed() read no checkbox at all, so this switch was decorative:
  // toggling it emitted a config with the key untouched. Assert BOTH directions.
  [".f-clientrender", "change", (el) => (el.checked = false), (c) => c.client_render === false, "client_render off pins false"],
  [".f-clientrender", "change", (el) => (el.checked = true), (c) => !("client_render" in c), "client_render on drops the key"],
  [".f-title", "input", (el) => (el.value = "Hoover"), (c) => c.title === "Hoover", "title"],
]) {
  let got = null;
  const h = (e) => (got = e.detail.config);
  ed2.addEventListener("config-changed", h);
  const el = ed2.querySelector(sel);
  set(el);
  el.dispatchEvent(new window.Event(ev));
  ed2.removeEventListener("config-changed", h);
  ok(!!got, `${label}: emits config-changed on '${ev}'`);
  ok(got && check(got), `${label}: the emitted config carries the new value`);
}

// ---- 9. entity suggestion ---------------------------------------------------
console.log("[9] custom card registration");
const reg = window.customCards.find((c) => c.type === "eufy-clean-card");
ok(!!reg, "registered in window.customCards");
ok(typeof reg.getEntitySuggestion === "function", "getEntitySuggestion present");
const sug = reg.getEntitySuggestion(makeHass(), "vacuum.robot");
ok(sug && sug.config && sug.config.vacuum === "vacuum.robot", "suggests config for fork vacuum");
// CANVAS_DEFAULT.md Stage 2: NEW cards get the canvas, existing dashboards do not.
ok(!("client_render" in sug.config), "a suggested card carries no client_render key (it is the default)");
const stub = window.customElements.get("eufy-clean-card").getStubConfig(makeHass());
ok(!("client_render" in stub), "nor does a card added from the picker");
ok(!!stub.camera, "...and it still carries a camera: the fallback AND the trail colour");

// ---- 10. mode isolation (no leakage between rooms + zones) ------------------
console.log("[10] mode isolation");
const css = sr.querySelector("style").textContent;
// Root cause of the reported leak: `.rooms{display:flex}` outranked the UA `[hidden]` rule, so
// the room list stayed on screen in zones mode. Assert the global override that fixes the class.
ok(/\[hidden\]\s*\{\s*display:\s*none\s*!important/.test(css), "global [hidden]{display:none!important} rule present");
// ...and that .rooms still declares its own display, i.e. the global rule is genuinely doing the
// overriding (rather than the leak having been "fixed" by dropping the flex layout).
ok(/\.rooms \{[^}]*display: flex/.test(css), ".rooms still declares display:flex (global rule is what overrides it)");
// The header strip must be able to WRAP. jsdom does no layout, so this asserts the
// declaration, not the result: with `flex: 1 0 auto` and nowrap the strip measured
// 349px inside a 300px card in Chrome and clipped the return-to-dock button.
ok(/\.rs-chips \{[^}]*flex-wrap: wrap/.test(css), ".rs-chips declares flex-wrap: wrap");
ok(!/\.rs-chips \{[^}]*flex: 1 0 auto/.test(css), ".rs-chips is not flex-shrink:0 any more");

// give BOTH modes content, then check each mode shows only its own
card._sel = [0];
card._roomPins[0] = { nx: 0.5, ny: 0.5 };
card._pending.zones = [{ x0: 0.1, y0: 0.1, x1: 0.4, y1: 0.4 }];

card._setMode("zones");
ok(card._els.rooms.hidden === true, "zones: room list hidden");
ok(card._els.settings.hidden === false, "zones: settings shown");
ok(card._els.passes.hidden === false, "zones: passes shown");
ok(sr.querySelectorAll(".rooms .room").length > 0, "zones: room DOM still exists (only hidden, not rebuilt)");
ok(sr.querySelector(".overlay circle.pin") === null, "zones: no room pins on the map");
ok(sr.querySelector(".overlay rect.zone") !== null, "zones: zone rect drawn");

card._setMode("rooms");
ok(card._els.rooms.hidden === false, "rooms: room list shown");
ok(card._els.settings.hidden === true, "rooms: zone settings hidden");
ok(card._els.passes.hidden === true, "rooms: zone passes hidden");
ok(sr.querySelector(".overlay rect.zone") === null, "rooms: no zone rects on the map");
ok(sr.querySelector(".overlay circle.pin") !== null, "rooms: room pin drawn");
card._setMode("zones");
ok(sr.querySelector(".overlay rect.zone") !== null, "zones again: the unsaved zone is still there");
card._clearAll();
card._setMode("rooms");
card._clearAll();

// ---- 11. robot status header -------------------------------------------------
console.log("[11] robot status header");
const hdr = sr.querySelector(".robostat");
ok(!!hdr, "status header rendered");
ok(sr.querySelector(".rs-text").getAttribute("aria-live") === "polite", "header text is a polite live region");
ok(sr.querySelector(".rs-text").getAttribute("role") === "status", "header text role=status");
ok(hdr.compareDocumentPosition(sr.querySelector(".controls .status")) & 4, "header sits ABOVE the bottom .status line");

const h = makeHass();
const setVac = (state, attrs) => {
  if (state === null) delete h.states["vacuum.robot"];
  else h.states["vacuum.robot"] = { state, attributes: Object.assign({ rooms: [] }, attrs), last_updated: "t" + state };
  card.hass = h;
};
const icon = () => sr.querySelector(".rs-state-icon").getAttribute("icon");
const stateTxt = () => sr.querySelector(".rs-state").textContent;
const detail = () => sr.querySelector(".rs-detail");
const batt = () => sr.querySelector(".rs-batt");

setVac("cleaning", { task_status: "cleaning_room" });
ok(icon() === "mdi:robot-vacuum", "cleaning -> mdi:robot-vacuum");
ok(stateTxt() === "Cleaning", "cleaning -> 'Cleaning'");
ok(hdr.classList.contains("on-active"), "cleaning -> active tone");
ok(detail().hidden === false && detail().textContent === "Cleaning room", "task_status shown as secondary detail");

setVac("docked", {});
ok(icon() === "mdi:home-outline", "docked -> mdi:home-outline");
ok(stateTxt() === "Docked" && hdr.classList.contains("on-idle"), "docked -> 'Docked' / idle tone");
ok(detail().hidden === true, "no detail line when there is nothing to say");

setVac("returning", {});
ok(icon() === "mdi:home-import-outline", "returning -> mdi:home-import-outline");
ok(stateTxt() === "Returning to dock", "returning -> 'Returning to dock'");

setVac("paused", {});
ok(icon() === "mdi:pause-circle-outline" && stateTxt() === "Paused", "paused -> pause icon + 'Paused'");

setVac("error", { error_code: 42, error_message: "Wheel stuck" });
ok(icon() === "mdi:alert-circle-outline", "error -> mdi:alert-circle-outline");
ok(stateTxt() === "Error" && hdr.classList.contains("on-error"), "error -> 'Error' / error tone");
ok(detail().textContent === "Wheel stuck", "error message surfaced as the detail");
ok(/\.robostat\.on-error \.rs-icon \{ color: var\(--error-color/.test(css), "error tone themed from --error-color");
ok(/\.rs-state \{[^}]*color: var\(--primary-text-color\)/.test(css), "state text keeps --primary-text-color (contrast)");

setVac("docked", { error_code: 0, error_message: "" });
ok(detail().hidden === true, "error_code 0 is NOT treated as an error");

// battery: absent -> hidden; sibling sensor -> shown; charging -> charging glyph
ok(batt().hidden === true, "battery hidden when no battery sensor/attribute");
h.states["sensor.robot_battery"] = { state: "78", attributes: {} };
card.hass = h;
ok(batt().hidden === false, "battery shown once the sibling sensor exists");
ok(sr.querySelector(".rs-batt-txt").textContent === "78%", "battery percentage rendered");
ok(sr.querySelector(".rs-batt-icon").getAttribute("icon") === "mdi:battery-charging-80",
  "docked below 100% with no charging sensor -> assumed charging");
setVac("cleaning", {}); // off the dock -> plain glyph
ok(sr.querySelector(".rs-batt-icon").getAttribute("icon") === "mdi:battery-80", "78% -> mdi:battery-80 (HA rounding)");
ok(batt().getAttribute("aria-label") === "Battery 78%", "battery group is aria-labelled");
h.states["binary_sensor.robot_charging"] = { state: "on", attributes: {} };
card.hass = h;
ok(sr.querySelector(".rs-batt-icon").getAttribute("icon") === "mdi:battery-charging-80", "charging -> mdi:battery-charging-80");
ok(batt().getAttribute("aria-label") === "Battery 78%, charging", "charging reflected in the aria-label");

setVac("unavailable", {});
ok(icon() === "mdi:cloud-off-outline" && stateTxt() === "Unavailable", "unavailable -> cloud-off + 'Unavailable'");
ok(hdr.classList.contains("on-off"), "unavailable -> muted tone");

setVac(null); // entity gone entirely
ok(icon() === "mdi:cloud-off-outline" && stateTxt() === "Unavailable", "missing entity degrades to 'Unavailable'");
ok(batt().hidden === true, "battery hidden when the vacuum entity is gone");

setVac("mowing_the_lawn", {}); // unknown state -> humanized fallback, never blank
ok(stateTxt() === "Mowing the lawn" && icon() === "mdi:robot-vacuum", "unknown state falls back to a humanized label");

// ---- 12. session stat chips (elapsed time + cleaned area) -------------------
console.log("[12] session stat chips");
const h2 = makeHass();
const setVac2 = (state, attrs) => {
  h2.states["vacuum.robot"] = {
    state,
    attributes: Object.assign({ rooms: [], supported_features: 8 | 16 }, attrs),
    last_updated: "u" + state + Math.random(),
  };
  card.hass = h2;
};
const timeChip = () => sr.querySelector(".rs-time");
const areaChip = () => sr.querySelector(".rs-area");

setVac2("cleaning", {});
ok(timeChip().hidden === true, "time chip hidden when the sensor doesn't exist");
ok(areaChip().hidden === true, "area chip hidden when the sensor doesn't exist");

// Both sensors exist AND the lifetime totals do too — the resolver must not confuse them,
// since "sensor.robot_total_cleaning_time" also ends with "_cleaning_time".
h2.states["sensor.robot_total_cleaning_time"] = { state: "999", attributes: { unit_of_measurement: "h" } };
h2.states["sensor.robot_total_cleaning_area"] = { state: "888", attributes: { unit_of_measurement: "m²" } };
h2.states["sensor.robot_cleaning_time"] = { state: "5.0", attributes: { unit_of_measurement: "min" } };
h2.states["sensor.robot_cleaning_area"] = { state: "7", attributes: { unit_of_measurement: "m²" } };
h2.entities["sensor.robot_total_cleaning_time"] = { device_id: "dev1" };
h2.entities["sensor.robot_total_cleaning_area"] = { device_id: "dev1" };
h2.entities["sensor.robot_cleaning_time"] = { device_id: "dev1" };
h2.entities["sensor.robot_cleaning_area"] = { device_id: "dev1" };
card._entCache = {}; // registry changed — drop memoized resolutions
setVac2("cleaning", {});
ok(timeChip().hidden === false, "time chip shown once the session sensor exists");
ok(sr.querySelector(".rs-time-txt").textContent === "5 min", "5.0 min renders as '5 min'");
ok(sr.querySelector(".rs-area-txt").textContent === "7 m²", "7 renders as '7 m²'");
ok(card._resolveSiblingEntity("sensor", "_cleaning_time") === "sensor.robot_cleaning_time",
  "session sensor wins over the lifetime total with the same suffix");
ok(timeChip().getAttribute("aria-label") === "Cleaning time: 5 min", "live chip is aria-labelled");
ok(timeChip().hasAttribute("title") === false, "live chip has no 'Last run' affordance");

// Unit is read from the ENTITY, never assumed.
h2.states["sensor.robot_cleaning_time"] = { state: "1.75", attributes: { unit_of_measurement: "h" } };
setVac2("cleaning", {});
ok(sr.querySelector(".rs-time-txt").textContent === "1.8 h", "hours keep one decimal");
h2.states["sensor.robot_cleaning_time"] = { state: "320", attributes: { unit_of_measurement: "s" } };
setVac2("cleaning", {});
ok(sr.querySelector(".rs-time-txt").textContent === "320 s", "seconds render whole");

// A run too short to round to a whole unit must not read as zero.
h2.states["sensor.robot_cleaning_time"] = { state: "0.4", attributes: { unit_of_measurement: "min" } };
setVac2("cleaning", {});
ok(sr.querySelector(".rs-time-txt").textContent === "<1 min", "0.4 min renders '<1 min', not '0 min'");
h2.states["sensor.robot_cleaning_time"] = { state: "0.02", attributes: { unit_of_measurement: "h" } };
setVac2("cleaning", {});
ok(sr.querySelector(".rs-time-txt").textContent === "<0.1 h", "the floor message uses the entity's own precision");

// Exactly zero says nothing (fresh restart) -> hidden. Non-zero while docked is last run's total.
h2.states["sensor.robot_cleaning_time"] = { state: "0", attributes: { unit_of_measurement: "min" } };
setVac2("docked", {});
ok(timeChip().hidden === true, "a zero session value is hidden, not rendered as '0 min'");
ok(areaChip().hidden === false, "a non-zero value survives docking (last run's total)");
ok(areaChip().getAttribute("title") === "Last run", "a stale chip is marked as last run");
ok(areaChip().getAttribute("aria-label") === "Cleaned area, last run: 7 m²", "stale aria-label says so");
ok(/\.robostat:not\(\.on-active\) \.rs-area \{ opacity/.test(sr.querySelector("style").textContent),
  "stale chips are dimmed by CSS, not by hiding them");

h2.states["sensor.robot_cleaning_time"] = { state: "unavailable", attributes: {} };
setVac2("cleaning", {});
ok(timeChip().hidden === true, "an unavailable sensor hides its chip");

setVac2("unavailable", {});
ok(timeChip().hidden === true && areaChip().hidden === true, "an unavailable robot shows no session stats");

// ---- 12b. run settings: suction and water level while a run is on ----------------------------
console.log("[12b] run setting chips");
const fanChip = () => sr.querySelector(".rs-fan");
const waterChip = () => sr.querySelector(".rs-water");
const fanTxt = () => sr.querySelector(".rs-fan-txt").textContent;
const waterTxt = () => sr.querySelector(".rs-water-txt").textContent;

// Legacy shape first: no mode or water select, so suction alone.
setVac2("cleaning", { fan_speed: "Turbo" });
ok(fanChip().hidden === false && fanTxt() === "Turbo", "suction shown while cleaning");
ok(fanChip().getAttribute("aria-label") === "Suction: Turbo", "suction chip is labelled");
ok(waterChip().hidden === true, "no water chip without a water level select");

h2.states["select.robot_cleaning_mode"] = { state: "Vacuum and mop", attributes: {} };
h2.states["select.robot_water_level"] = { state: "Medium", attributes: {} };
h2.entities["select.robot_cleaning_mode"] = { device_id: "dev1" };
h2.entities["select.robot_water_level"] = { device_id: "dev1" };
card._entCache = {};
setVac2("cleaning", { fan_speed: "Turbo" });
ok(waterChip().hidden === false && waterTxt() === "Medium", "water level shown while vacuuming and mopping");
ok(waterChip().getAttribute("aria-label") === "Water level: Medium", "water chip is labelled");
ok(fanChip().compareDocumentPosition(timeChip()) & 4, "run settings come before the session stats");

setVac2("paused", { fan_speed: "Turbo" });
ok(!fanChip().hidden && !waterChip().hidden, "a paused run still shows its settings");
for (const st of ["docked", "returning", "idle", "error", "unavailable"]) {
  setVac2(st, { fan_speed: "Turbo" });
  ok(fanChip().hidden && waterChip().hidden, `${st}: no run settings`);
}

h2.states["select.robot_cleaning_mode"].state = "Vacuum";
setVac2("cleaning", { fan_speed: "Turbo" });
ok(!fanChip().hidden && waterChip().hidden, "vacuum-only hides the water chip");
h2.states["select.robot_cleaning_mode"].state = "Mop";
setVac2("cleaning", { fan_speed: "Turbo" });
ok(fanChip().hidden && !waterChip().hidden, "mop-only hides the suction chip");

h2.states["select.robot_cleaning_mode"].state = "unavailable";
h2.states["select.robot_water_level"].state = "unavailable";
setVac2("cleaning", { fan_speed: "Off" });
ok(fanChip().hidden, "suction Off is not shown");
ok(waterChip().hidden, "an unavailable water level is not shown");
setVac2("cleaning", {});
ok(fanChip().hidden, "no fan_speed attribute, no suction chip");

// ---- 13. header stop / return-to-dock buttons -------------------------------
console.log("[13] header controls");
const stopBtn = () => sr.querySelector(".rs-stop");
const homeBtn = () => sr.querySelector(".rs-home");
ok(stopBtn().getAttribute("aria-label") === "Stop", "stop button is aria-labelled");
ok(homeBtn().getAttribute("aria-label") === "Return to dock", "home button is aria-labelled");
ok(stopBtn().compareDocumentPosition(sr.querySelector(".map-wrap")) & 4,
  "controls sit ABOVE the map (reachable without scrolling)");

// [state, stop enabled, home enabled]
for (const [st, stopOn, homeOn] of [
  ["cleaning", true, true],
  ["returning", true, false],
  ["paused", true, true],
  ["docked", false, false],
  ["idle", false, true],
  ["error", false, true],
]) {
  setVac2(st, {});
  ok(stopBtn().disabled === !stopOn, `${st}: stop ${stopOn ? "enabled" : "disabled"}`);
  ok(homeBtn().disabled === !homeOn, `${st}: return-to-dock ${homeOn ? "enabled" : "disabled"}`);
  ok(stopBtn().hidden === false && homeBtn().hidden === false, `${st}: both buttons stay in place`);
}
setVac2("unavailable", {});
ok(stopBtn().disabled === true && homeBtn().disabled === true, "unavailable: both disabled");

// A device that doesn't declare the feature gets no button at all (rather than a dead one).
setVac2("cleaning", { supported_features: 8 });
ok(stopBtn().hidden === false, "STOP declared -> stop button rendered");
ok(homeBtn().hidden === true, "RETURN_HOME not declared -> no return-to-dock button");
setVac2("cleaning", { supported_features: 8 | 16 });

h2._calls.length = 0;
// One at a time: _callVacuum holds the _dispatching guard until the service resolves, so a
// second click in the same tick is deliberately swallowed (no double-dispatch).
stopBtn().dispatchEvent(new window.MouseEvent("click"));
await new Promise((r) => setTimeout(r, 0));
homeBtn().dispatchEvent(new window.MouseEvent("click"));
await new Promise((r) => setTimeout(r, 0));
ok(h2._calls.some((c) => c.domain === "vacuum" && c.service === "stop"), "stop calls vacuum.stop");
ok(h2._calls.some((c) => c.domain === "vacuum" && c.service === "return_to_base"),
  "return-to-dock calls vacuum.return_to_base");
ok(h2._calls.every((c) => c.data.entity_id === "vacuum.robot"), "both target the card's vacuum");

// ---- 14. room fields are device-driven --------------------------------------
console.log("[14] device-driven room fields");
const fieldSet = () => Array.from(sr.querySelectorAll(".rooms .room:first-child .rset select")).map((e) => e.className);
const rooms3 = [{ id: 0, name: "Hallway" }, { id: 1, name: "Kitchen" }];

// No room_clean_options attribute (older integration) -> today's full fallback set.
h2.states["vacuum.robot"] = { state: "docked", attributes: { rooms: rooms3, fan_speed_list: ["Quiet", "Max"] }, last_updated: "r0" };
card.hass = h2;
ok(fieldSet().join(",") === "f-mode,f-fan,f-water,f-int,f-passes,f-edge",
  "no declared options -> full fallback field set");

// A legacy robot declares suction / water / repeats only: its customRooms document has no
// clean mode, intensity or edge-mop at all, and the firmware silently ignores what it
// doesn't declare — so those must not render.
h2.states["vacuum.robot"] = {
  state: "docked",
  last_updated: "r1",
  attributes: {
    rooms: rooms3,
    fan_speed_list: ["Off", "Quiet", "Standard", "Turbo", "Max"],
    room_clean_options: { fan_speed: ["Quiet", "Standard", "Turbo", "Max"], water_level: ["Low", "Mid", "High"], clean_times: true },
  },
};
card.hass = h2;
ok(fieldSet().join(",") === "f-fan,f-water,f-passes", "legacy declares 3 fields -> exactly 3 render");
ok(sr.querySelector(".rooms .room:first-child .f-int") === null, "an undeclared field renders nothing at all");
const fanVals = Array.from(sr.querySelectorAll(".rooms .room:first-child .f-fan option")).map((o) => o.value);
ok(fanVals.join(",") === ",Quiet,Standard,Turbo,Max",
  "suction uses the declared per-room vocabulary, not fan_speed_list (which carries 'Off')");
const waterVals = Array.from(sr.querySelectorAll(".rooms .room:first-child .f-water option")).map((o) => o.value);
ok(waterVals.join(",") === ",Low,Mid,High", "water uses the device's own spelling ('Mid', not 'Middle')");

// Selecting + dispatching a room must still work with the reduced field set.
card._sel = [];
card._toggleRoom(0);
sr.querySelector(".rooms .room:first-child .f-fan").value = "Turbo";
sr.querySelector(".rooms .room:first-child .f-fan").dispatchEvent(new window.Event("change"));
h2._calls.length = 0;
await card._cleanRooms();
const roomCall = h2._calls.find((c) => c.service === "send_command");
ok(!!roomCall && roomCall.data.params.rooms[0].fan_speed === "Turbo", "the reduced set still dispatches its values");
ok(roomCall && !("clean_mode" in roomCall.data.params.rooms[0]), "undeclared fields are absent from the payload");

// A device that declares nothing still gets a panel that reads the same as any other room.
h2.states["vacuum.robot"] = {
  state: "docked",
  last_updated: "r2",
  attributes: { rooms: rooms3, fan_speed_list: [], room_clean_options: {} },
};
card.hass = h2;
ok(fieldSet().length === 0, "no declared options -> no selects");
ok(sr.querySelector(".rooms .room:first-child .rset-empty") !== null, "an empty field set shows the empty-state copy");

// Changing the declared option set must rebuild the rows (the rebuild key covers it).
h2.states["vacuum.robot"] = {
  state: "docked",
  last_updated: "r3",
  attributes: { rooms: rooms3, fan_speed_list: [], room_clean_options: { fan_speed: ["Quiet"], clean_times: true } },
};
card.hass = h2;
ok(fieldSet().join(",") === "f-fan,f-passes", "a changed option set triggers a room-list rebuild");
ok(/repeat\(auto-fill, minmax\(118px, 1fr\)\)/.test(sr.querySelector("style").textContent),
  "the field grid is auto-fill, so a short field set stays left-packed instead of stretching");

// ---- 15. loading the card twice must not throw ------------------------------
// Loading the module twice must not re-`define` the element. Each distinct URL is its
// own module, so a stale `?v=` or a manual Lovelace resource evaluates this file twice
// against one shared registry; an unguarded define() throws and aborts the module.
//
// Evaluate via window.Function so the card's top-level `const`s land in function
// scope, matching how the browser scopes a module — while customElements and
// window.customCards stay shared, which is the condition that actually broke.
console.log("[15] double load is idempotent");

const cardsBefore = window.customCards.filter((c) => c.type === "eufy-clean-card").length;
ok(cardsBefore === 1, "card is listed once after the first load");
const OrigCard = window.customElements.get("eufy-clean-card");

let threw = null;
try {
  new window.Function(code)();
} catch (e) {
  threw = e;
}
ok(threw === null, `a second evaluation does not throw${threw ? ` (got: ${threw.message})` : ""}`);
ok(
  window.customCards.filter((c) => c.type === "eufy-clean-card").length === 1,
  "the card picker still lists the card exactly once"
);
ok(window.customElements.get("eufy-clean-card") !== undefined, "eufy-clean-card is still registered");
ok(window.customElements.get("zone-clean-card") !== undefined, "zone-clean-card is still registered");
ok(window.customElements.get("eufy-clean-card-editor") !== undefined, "the editor is still registered");

// The first definition must survive — a later copy must not replace the working one.
ok(
  window.customElements.get("eufy-clean-card") === OrigCard,
  "the originally registered class is the one still in the registry"
);

// And an already-rendered card keeps working after the duplicate load.
card.hass = makeHass();
ok(sr.querySelector(".rooms") !== null || sr.querySelector(".zones") !== null,
  "an existing card instance still renders after the second load");

// ---- 16. map refresh caches on map_revision, not wall-clock -----------------
// The image URL keys on `map_revision`, so an unchanged map is not re-downloaded.
// entity_picture alone is no key: its token rotates and the camera state never changes.
console.log("[16] map image caching");
{
  const h = makeHass();
  const c2 = new Card();
  c2.setConfig({ type: "custom:eufy-clean-card", vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c2);
  h.states["camera.robot_map"] = { state: "idle", attributes: { entity_picture: "/pic.png", map_revision: 7 }, last_updated: "c1" };
  c2.hass = h;
  const img = c2.shadowRoot.querySelector(".mapimg") || c2.shadowRoot.querySelector("img");
  const first = img && img.getAttribute("src");
  ok(/v=7/.test(first || ""), `src keyed on map_revision (got ${first})`);

  // same frame -> identical src, so the browser reuses its cache and issues no request
  h.states["camera.robot_map"] = { state: "idle", attributes: { entity_picture: "/pic.png", map_revision: 7 }, last_updated: "c2" };
  c2.hass = h;
  c2._refreshMap();
  ok(img.getAttribute("src") === first, "unchanged frame does not change src (no re-download)");

  // new frame -> new src
  h.states["camera.robot_map"] = { state: "idle", attributes: { entity_picture: "/pic.png", map_revision: 8 }, last_updated: "c3" };
  c2.hass = h;
  c2._refreshMap();
  ok(/v=8/.test(img.getAttribute("src")), "a new frame changes src");

  // older integration without the attribute still refreshes (time-based fallback)
  h.states["camera.robot_map"] = { state: "idle", attributes: { entity_picture: "/pic.png" }, last_updated: "c4" };
  c2.hass = h;
  c2._refreshMap();
  ok(/_=\d+/.test(img.getAttribute("src")), "falls back to a time bust when map_revision is absent");
}

// ---- 17. sibling-entity misses are not re-scanned every tick ----------------
console.log("[17] sibling lookup miss caching");
{
  const h = makeHass();
  const c3 = new Card();
  c3.setConfig({ type: "custom:eufy-clean-card", vacuum: "vacuum.robot" });
  document.body.appendChild(c3);
  c3.hass = h;
  // The card runs inside jsdom's realm, so patch WINDOW's Object.entries — patching
  // Node's would count nothing and make this assertion pass trivially.
  let scans = 0;
  const realEntries = window.Object.entries;
  window.Object.entries = function (o) { if (o === h.entities) scans++; return realEntries(o); };
  try {
    c3._resolveSiblingEntity("sensor", "_does_not_exist");
    ok(scans === 1, `the first lookup does scan the registry (was ${scans})`);
    for (let i = 0; i < 25; i++) c3._resolveSiblingEntity("sensor", "_does_not_exist");
    ok(scans === 1, `25 further lookups re-scan zero times (total scans ${scans})`);
    // an entity appearing in states must still resolve immediately (O(1) path)
    h.states["sensor.robot_late_arrival"] = { state: "1", attributes: {} };
    ok(c3._resolveSiblingEntity("sensor", "_late_arrival") === "sensor.robot_late_arrival",
      "a newly present state entity still resolves without waiting");
  } finally {
    window.Object.entries = realEntries;
  }
}


// ---- no-go zone mode ------------------------------------------------------
console.log("[nogo] no-go mode draws restricted rectangles and saves them");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  const root = c.shadowRoot;

  ok(!!root.querySelector(".mode-nogo"), "a No-go mode button exists");

  c._setMode("nogo");
  ok(root.querySelector(".mode-nogo").getAttribute("aria-pressed") === "true",
    "no-go aria-pressed after toggle");
  ok(root.querySelector(".mode-zones").getAttribute("aria-pressed") === "false",
    "zones is released when no-go is picked");
  // Clean settings belong to a CLEANING zone; a no-go zone has neither.
  ok(c._els.settings.hidden === true, "clean settings hidden in no-go mode");
  ok(c._els.passes.hidden === true, "passes hidden in no-go mode");

  // Draw one rectangle the same way zones mode does.
  c._zones = [{ x0: 0.1, y0: 0.2, x1: 0.4, y1: 0.5 }];
  c._syncControls();
  ok(/Save 1 no-go zone/.test(c._els.clean.textContent),
    `the action reads as Save, not Clean (got "${c._els.clean.textContent}")`);

  c._renderOverlay();
  ok(/class="zone nogo"/.test(c._els.overlay.innerHTML),
    "a no-go rectangle is drawn in the restricted style, not the cleaning style");

  h._calls.length = 0;
  await c._saveNogoZones();
  const call = h._calls.find((x) => x.domain === "vacuum" && x.service === "send_command");
  ok(!!call, "saving calls vacuum.send_command");
  // A missing/undefined target is what HA rejects with "must contain at least one of
  // entity_id, device_id, ...", and a permissive fake callService hides it entirely.
  ok(call.data.entity_id === "vacuum.robot",
    `the call targets the configured vacuum (got ${JSON.stringify(call.data.entity_id)})`);
  ok(call.data.command === "set_nogo_zones", "the command is set_nogo_zones");
  ok(JSON.stringify(call.data.params.forbidden) === JSON.stringify([[0.1, 0.2, 0.4, 0.5]]),
    "the drawn rectangle is sent as a normalized forbidden rect");
  // Never send `replace` from the card: the backend merges, and a stray replace
  // would erase the device's existing walls and no-mop zones.
  ok(call.data.params.replace === undefined, "the card never sends replace:true");
  ok(c._zones.length === 0, "the pending rectangles are cleared after a successful save");
}


// ---- virtual wall mode ----------------------------------------------------
console.log("[wall] wall mode draws a line and saves it as a virtual wall");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;

  ok(!!c.shadowRoot.querySelector(".mode-wall"), "a Wall mode button exists");
  c._setMode("wall");
  ok(c._isLineMode() === true, "wall mode is a line mode");
  ok(c._isDrawMode() === true, "wall mode still drags out a shape");

  // A purely VERTICAL wall: zero width, which the rectangle rule would reject.
  c._drag = { x0: 0.5, y0: 0.2, x1: 0.5, y1: 0.8 };
  c._finishZone();
  ok(c._zones.length === 1, "a zero-width vertical wall is accepted");
  ok(c._zones[0].line === true, "it is stored as a line, not a box");

  // A DIAGONAL wall must keep its endpoints, not be flattened into a bounding box.
  c._zones = [];
  c._drag = { x0: 0.8, y0: 0.2, x1: 0.2, y1: 0.8 };
  c._finishZone();
  ok(c._zones[0].x0 === 0.8 && c._zones[0].y0 === 0.2,
    "the first endpoint is kept as drawn (not min-sorted)");
  ok(c._zones[0].x1 === 0.2 && c._zones[0].y1 === 0.8,
    "the second endpoint is kept as drawn");

  c._renderOverlay();
  ok(/<line class="wall"/.test(c._els.overlay.innerHTML),
    "a wall renders as a line element, not a rect");

  c._syncControls();
  ok(/Save 1 wall/.test(c._els.clean.textContent),
    `the action reads as Save N wall (got "${c._els.clean.textContent}")`);

  h._calls.length = 0;
  await c._saveNogoZones();
  const call = h._calls.find((x) => x.domain === "vacuum" && x.service === "send_command");
  ok(!!call, "saving calls vacuum.send_command");
  ok(call.data.entity_id === "vacuum.robot", "the call targets the configured vacuum");
  ok(call.data.command === "set_nogo_zones", "walls ride the same command");
  // The KEY is what distinguishes a wall from a zone — same four numbers otherwise.
  ok(Array.isArray(call.data.params.walls), "the shape is sent under `walls`");
  ok(call.data.params.forbidden === undefined,
    "a wall is NOT sent as a forbidden rectangle");
  ok(JSON.stringify(call.data.params.walls) === JSON.stringify([[0.8, 0.2, 0.2, 0.8]]),
    "the diagonal endpoints survive to the service call");
}


// ---- auto-discovered zone selects ------------------------------------------
console.log("[selects] auto-discovery skips the pickers by exact suffix");
{
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.living_room", camera: "camera.robot_map" });
  const st = { state: "x", attributes: { options: ["x"] } };
  c._hass = {
    states: Object.fromEntries([
      "select.living_room_suction_level",
      "select.living_room_water_level",
      "select.living_room_clean_room",
      "select.living_room_selected_schedule",
      "select.living_room_switch_map",
      "select.kitchen_suction_level",
    ].map((e) => [e, st])),
  };
  const got = c._effectiveSelects();
  ok(JSON.stringify(got) === JSON.stringify(["select.living_room_suction_level", "select.living_room_water_level"]),
    `a vacuum slug containing "_room" keeps its setting selects (got ${JSON.stringify(got)})`);
}

// ---- No-go and Wall only where the vacuum can take them --------------------
console.log("[nogo] No-go and Wall need the vacuum's nogo_zones_supported");
{
  const h = makeHass();
  delete h.states["vacuum.robot"].attributes.nogo_zones_supported;
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map", mode: "nogo" });
  document.body.appendChild(c);
  c.hass = h;
  const root = c.shadowRoot;
  ok(root.querySelector(".mode-nogo").hidden === true && root.querySelector(".mode-wall").hidden === true,
    "without the attribute the No-go and Wall tabs are hidden");
  ok(root.querySelector(".mode-zones").hidden === false, "Zones still shows (it needs only a map)");
  ok(c._mode === "rooms", "a configured `mode: nogo` falls back to rooms");

  // The vacuum's attributes can arrive after the card is built (HA starting up).
  const h2 = makeHass();
  c.hass = h2;
  ok(root.querySelector(".mode-nogo").hidden === false && root.querySelector(".mode-wall").hidden === false,
    "the tabs appear once the vacuum reports support");
  ok(c._mode === "nogo", "and the configured mode is restored");

  h2.states["vacuum.robot"].attributes.nogo_zones_supported = false;
  c.hass = { ...h2 };
  ok(root.querySelector(".mode-nogo").hidden === true && c._mode === "rooms",
    "`false` hides them again and leaves the mode");
  c.remove();
}

// ---- unsaved shapes stay with the mode that drew them ----------------------
// One Save sends the active mode's shapes under that mode's key: a pending wall carried into
// No-go would go out as a forbidden rectangle over the wall's whole bounding box.
console.log("[modes] unsaved shapes stay with the mode that drew them");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  const saved = () => h._calls.filter((x) => x.service === "send_command").pop();

  c._setMode("wall");
  c._drag = { x0: 0.2, y0: 0.2, x1: 0.8, y1: 0.8 };
  c._finishZone();
  c._setMode("zones");
  c._drag = { x0: 0.3, y0: 0.3, x1: 0.5, y1: 0.5 };
  c._finishZone();
  c._setMode("nogo");
  ok(c._zones.length === 0, "No-go starts without the wall or the zone drawn elsewhere");
  ok(!/<line class="wall"|class="zone"/.test(c._els.overlay.innerHTML),
    "neither is drawn in No-go");
  ok(c._els.clean.disabled === true, "and there is nothing to save");
  c._drag = { x0: 0.6, y0: 0.1, x1: 0.9, y1: 0.3 };
  c._finishZone();
  ok(/Save 1 no-go zone/.test(c._els.clean.textContent), "the count is No-go's own");
  await c._saveNogoZones();
  let call = saved();
  ok(JSON.stringify(call.data.params) === JSON.stringify({ forbidden: [[0.6, 0.1, 0.9, 0.3]] }),
    `only the no-go zone is sent, as forbidden (got ${JSON.stringify(call.data.params)})`);

  c._setMode("wall");
  ok(c._zones.length === 1 && c._zones[0].line === true, "the unsaved wall is still in Wall");
  await c._saveNogoZones();
  call = saved();
  ok(JSON.stringify(call.data.params) === JSON.stringify({ walls: [[0.2, 0.2, 0.8, 0.8]] }),
    `the wall is sent as a wall only (got ${JSON.stringify(call.data.params)})`);

  // A mode switch while a save is out clears the saved mode's list, not the new one's.
  c._drag = { x0: 0.1, y0: 0.6, x1: 0.4, y1: 0.6 };
  c._finishZone();
  let release;
  const realCall = h.callService;
  h.callService = function (domain, service, data) {
    this._calls.push({ domain, service, data });
    return new Promise((res) => (release = res));
  };
  const out = c._saveNogoZones();
  c._setMode("nogo");
  c._drag = { x0: 0.6, y0: 0.6, x1: 0.8, y1: 0.8 };
  c._finishZone();
  release({});
  await out;
  ok(c._zones.length === 1, "the no-go zone drawn meanwhile survives the wall's save");
  c._setMode("wall");
  ok(c._zones.length === 0, "and the saved wall is cleared");
  h.callService = realCall;

  c._setMode("zones");
  ok(c._zones.length === 1 && !c._zones[0].line, "the cleaning zone waited in Zones");
  await c._cleanZones();
  call = saved();
  ok(call.data.command === "zone_clean" &&
     JSON.stringify(call.data.params.zones) === JSON.stringify([[0.3, 0.3, 0.5, 0.5]]),
    "Zones cleans its own zone only");
  c.remove();
}

// ---- input while a send is out ---------------------------------------------
// A legacy write over MQTT takes seconds. What the user adds meanwhile was never sent and
// stays pending; what the send carries, and the stored geometry a save rewrites, hold still.
console.log("[inflight] a send clears only what it carried");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  let settle;
  h.callService = function (domain, service, data) {
    this._calls.push({ domain, service, data });
    if (service !== "send_command") return Promise.resolve({});
    return new Promise((res, rej) => (settle = { res, rej }));
  };
  const draw = (x0, y0, x1, y1) => {
    c._drag = { x0, y0, x1, y1 };
    c._finishZone();
  };
  const handles = () =>
    [...c._els.overlay.querySelectorAll("[data-del], [data-rot], [data-mov]")].map(
      (g) => g.getAttribute("data-del") || g.getAttribute("data-rot") || g.getAttribute("data-mov")
    );

  c._setMode("nogo");
  c._setEditGeometry(geometrySnapshot(7));
  draw(0.1, 0.2, 0.4, 0.5);
  const first = c._zones[0];
  c._toggleDelete("forbidden:1");
  let out = c._saveNogoZones();
  ok(handles().length === 0, `the grips go as the save leaves (got ${JSON.stringify(handles())})`);
  draw(0.6, 0.6, 0.8, 0.8);
  const second = c._zones[1];
  ok(c._zones.length === 2, "a shape can be drawn while the save is out");
  ok(handles().length === 3 && handles().every((t) => t === "new:1"),
    `only the new shape offers grips meanwhile (got ${JSON.stringify(handles())})`);
  c._toggleDelete("new:0");
  c._toggleDelete("forbidden:0");
  c._startShapeDrag("move", "new:0", { clientX: 5, clientY: 5, pointerId: 1 });
  ok(c._zones[0] === first && c._shapeDrag === null && c._deletionCount() === 1,
    "the sent shape and the stored geometry ignore edits");
  settle.res({});
  await out;
  ok(c._zones.length === 1 && c._zones[0] === second,
    "the save drops the shape it sent and keeps the one drawn meanwhile");
  ok(c._els.status.textContent === "Saved 1 no-go zone, deleted 1",
    `the status counts what was sent (got "${c._els.status.textContent}")`);
  ok(c._deletionCount() === 0, "the sent deletion is cleared");
  ok(/Save 1 no-go zone/.test(c._els.clean.textContent) && c._els.clean.disabled === false,
    `the new shape is still to save (got "${c._els.clean.textContent}")`);
  ok(handles().includes("new:0") && handles().includes("forbidden:0"),
    "and every grip is back");

  // A failed save keeps both.
  out = c._saveNogoZones();
  draw(0.1, 0.1, 0.3, 0.3);
  settle.rej(new Error("timeout"));
  await out;
  ok(c._zones.length === 2 && c._zones[0] === second,
    "a failed save keeps the sent shape and the one drawn meanwhile");

  c._setMode("wall");
  draw(0.1, 0.1, 0.5, 0.1);
  out = c._saveNogoZones();
  draw(0.1, 0.6, 0.5, 0.6);
  ok(handles().length === 3 && handles().every((t) => t === "new:1"),
    `a wall being saved offers no grips, one drawn meanwhile does (got ${JSON.stringify(handles())})`);
  settle.res({});
  await out;
  ok(c._zones.length === 1 && c._zones[0].y0 === 0.6, "the save keeps the wall drawn meanwhile");

  c._setMode("zones");
  draw(0.3, 0.3, 0.5, 0.5);
  out = c._cleanZones();
  draw(0.6, 0.1, 0.9, 0.3);
  settle.res({});
  await out;
  ok(c._zones.length === 1 && c._zones[0].x0 === 0.6,
    "a zone clean keeps the zone drawn meanwhile");
  ok(c._els.status.textContent === "Sent 1 zone • passes 1",
    `and counts only the zone it sent (got "${c._els.status.textContent}")`);
  out = c._cleanZones();
  settle.rej(new Error("timeout"));
  await out;
  ok(handles().includes("new:0"), "a failed zone clean gives the zone its grips back");
  c._toggleDelete("new:0");
  ok(c._zones.length === 0, "and lets it be edited again");
  // A zone clean does not rewrite the stored geometry: it stays editable meanwhile.
  draw(0.3, 0.3, 0.5, 0.5);
  out = c._cleanZones();
  c._setMode("nogo");
  c._setEditGeometry(geometrySnapshot(8));
  c._toggleDelete("forbidden:0");
  ok(c._deletionCount() === 1, "stored geometry can be marked while a zone clean is out");
  settle.res({});
  await out;

  c._setMode("rooms");
  c._applyRoomTap(0, 0.2, 0.2);
  out = c._cleanRooms();
  c._applyRoomTap(2, 0.7, 0.7);
  settle.res({});
  await out;
  ok(JSON.stringify(c._sel) === "[2]", `a room tapped meanwhile stays selected (got ${JSON.stringify(c._sel)})`);
  ok(JSON.stringify(Object.keys(c._roomPins)) === '["2"]',
    `only the sent room loses its pin (got ${JSON.stringify(Object.keys(c._roomPins))})`);
  ok(c._els.status.textContent === "Sent 1 room", `the count is the sent room (got "${c._els.status.textContent}")`);
  c.remove();
}

console.log("[inflight] a running grip drag, Clear and the header hold still too");
{
  const h = makeHass();
  h.states["vacuum.robot"].state = "paused"; // Start, Stop and Home all offered
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  let settle;
  h.callService = function (domain, service, data) {
    this._calls.push({ domain, service, data });
    if (service !== "send_command") return Promise.resolve({});
    return new Promise((res, rej) => (settle = { res, rej }));
  };
  const draw = (x0, y0, x1, y1) => {
    c._drag = { x0, y0, x1, y1 };
    c._finishZone();
  };
  // No layout in jsdom: pin the projection a grip drag reads.
  let at = { x: 0.5, y: 0.5 };
  c._mapNormFromClient = () => at;
  const step = (x, y) => {
    at = { x, y };
    c._onOverlayMove({ clientX: 2, clientY: 2, pointerId: 4 });
  };

  c._setMode("nogo");
  c._setEditGeometry(geometrySnapshot(7));
  draw(0.4, 0.4, 0.6, 0.6);
  const sent = c._zones[0];
  c._toggleDelete("forbidden:1");
  c._startShapeDrag("move", "new:0", { clientX: 1, clientY: 1, pointerId: 4 });
  const header = () => [c._els.rsStart, c._els.rsStop, c._els.rsHome].map((b) => b.disabled);
  ok(JSON.stringify(header()) === "[false,false,false]", "the header is live before the save");
  let out = c._saveNogoZones();
  step(0.6, 0.6);
  ok(sent.x0 === 0.4 && sent.y0 === 0.4 && c._shapeDrag === null,
    `a grip drag running when Save fires stops and leaves the sent shape as sent (got ${sent.x0}, ${sent.y0})`);
  ok(c._els.rsStart.disabled && c._els.rsStop.disabled && c._els.rsHome.disabled,
    "Start, Stop and Home are disabled while the save is out");
  draw(0.1, 0.1, 0.2, 0.2);
  c._els.rsStart.dispatchEvent(new window.Event("click"));
  ok(!h._calls.some((x) => x.service === "start"), "a Start click meanwhile sends nothing");
  ok(c._zones.length === 2 && c._deletionCount() === 1, "and wipes nothing, not even a shape drawn meanwhile");
  c._clearAll();
  ok(c._zones.length === 1 && c._zones[0] === sent && c._deletionCount() === 1,
    "Clear meanwhile drops only what the save does not carry");
  settle.res({});
  await out;
  ok(JSON.stringify(header()) === "[false,false,false]", "and live again once it is done");

  c._startShapeDrag("move", "forbidden:0", { clientX: 1, clientY: 1, pointerId: 4 });
  draw(0.1, 0.1, 0.2, 0.2);
  out = c._saveNogoZones();
  step(0.7, 0.7);
  ok(c._moveCount() === 0 && c._shapeDrag === null,
    "a drag on stored geometry stages no move once a save rewrites it");
  settle.res({});
  await out;

  // The send's success drops the sent shape from under a drag on one drawn meanwhile.
  const at3 = (z) => JSON.stringify([z.x0, z.x1].map((v) => +v.toFixed(3)));
  for (const mode of ["nogo", "zones"]) {
    c._setMode(mode);
    c._clearAll();
    draw(0.1, 0.1, 0.2, 0.2);
    out = mode === "nogo" ? c._saveNogoZones() : c._cleanZones();
    draw(0.4, 0.4, 0.5, 0.5);
    draw(0.7, 0.7, 0.8, 0.8);
    const [, held, other] = c._zones;
    at = { x: 0.45, y: 0.45 };
    c._startShapeDrag("move", "new:1", { clientX: 1, clientY: 1, pointerId: 4 });
    settle.res({});
    await out;
    step(0.55, 0.45);
    ok(at3(held) === "[0.5,0.6]" && at3(other) === "[0.7,0.8]",
      `${mode}: the drag keeps moving its shape once the send lands (got ${at3(held)}, ${at3(other)})`);
    c._zones.splice(c._zones.indexOf(held), 1);
    step(0.65, 0.45);
    ok(at3(other) === "[0.7,0.8]" && c._shapeDrag === null, `${mode}: and ends when its shape is gone`);
  }
  c.remove();
}

console.log("[inflight] an error while a send starts leaves nothing disabled");
{
  const h = makeHass();
  h.states["vacuum.robot"].state = "paused";
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  const header = () => [c._els.rsStart, c._els.rsStop, c._els.rsHome].map((b) => b.disabled);
  const cases = [
    ["a no-go save", "nogo", "_renderOverlay", () => c._saveNogoZones()],
    ["a no-go save", "nogo", "_syncControls", () => c._saveNogoZones()],
    ["a zone clean", "zones", "_renderOverlay", () => c._cleanZones()],
    ["a zone clean", "zones", "_syncControls", () => c._cleanZones()],
    ["a room clean", "rooms", "_syncControls", () => c._cleanRooms()],
    ["a header call", "rooms", "_syncControls", () => c._callVacuum("start", "Starting")],
  ];
  for (const [what, mode, method, send] of cases) {
    c._dispatching = false; // each case on its own
    c._inFlight = null;
    c._setMode(mode);
    if (mode === "rooms") c._sel = ["0"];
    else c._zones = [{ x0: 0.1, y0: 0.1, x1: 0.2, y1: 0.2 }];
    let armed = true;
    c[method] = function () {
      if (armed) {
        armed = false;
        throw new Error("render bug");
      }
      return Object.getPrototypeOf(this)[method].call(this);
    };
    try {
      await send();
    } catch (_) {
      /* the throw may escape: what counts is the state it leaves */
    }
    delete c[method];
    c._syncControls();
    ok(c._dispatching === false && c._inFlight === null && JSON.stringify(header()) === "[false,false,false]",
      `${what} whose first ${method} throws ends the send (got ${c._dispatching}, ${JSON.stringify(header())})`);
  }
  c.remove();
}

// ---- deleting geometry: pending shapes and the device's own ----------------
// A snapshot in the shape `robovac_mqtt/map/geometry` serves: world-cm points, plus the
// revision every delete index is relative to. 150x215 cells at 5 cm, origin (520, 1350).
function geometrySnapshot(revision = 3) {
  return {
    revision,
    width: 150,
    height: 215,
    origin_x: 520,
    origin_y: 1350,
    resolution: 5,
    forbidden_zones: [
      [[600, 1900], [700, 1900], [700, 1800], [600, 1800]],
      // Deliberately OFF the mapped floor, like the real T2266's own zone: its
      // normalized x is > 1, which is exactly the case a coordinate round trip
      // would clamp — and thereby move — if deletions were sent as coordinates.
      [[1210, 1563], [1360, 1563], [1360, 1413], [1210, 1413]],
    ],
    ban_mop_zones: [],
    virtual_walls: [[[600, 1500], [640, 1700]]],
  };
}

console.log("[del] pending shapes carry an x that removes them");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  c._setMode("nogo");
  c._zones = [
    { x0: 0.1, y0: 0.2, x1: 0.4, y1: 0.5 },
    { x0: 0.5, y0: 0.5, x1: 0.7, y1: 0.7 },
  ];
  c._renderOverlay();
  const handles = c._els.overlay.querySelectorAll("[data-del]");
  ok(handles.length === 2, `one delete handle per pending shape (got ${handles.length})`);
  ok(handles[0].getAttribute("data-del") === "new:0", "a pending shape is tagged new:<index>");

  // Tapping the glyph INSIDE the handle must resolve to the handle, not to the map.
  const glyph = handles[1].querySelector("text");
  c._onOverlayDown({ target: glyph, clientX: 5, clientY: 5, pointerId: 1 });
  ok(c._zones.length === 1, "the tapped pending shape is dropped");
  ok(c._zones[0].x0 === 0.1, "and it is the right one — the untapped shape survives");
  ok(c._drag === null, "a tap on the handle does not also start drawing a zone");
}

console.log("[del] existing device geometry can be marked and unmarked");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  c._setMode("nogo");
  c._setEditGeometry(geometrySnapshot());
  c._renderOverlay();

  const handles = [...c._els.overlay.querySelectorAll("[data-del]")].map((g) =>
    g.getAttribute("data-del")
  );
  ok(JSON.stringify(handles) === JSON.stringify(["forbidden:0", "forbidden:1"]),
    `both existing no-go zones get a handle (got ${JSON.stringify(handles)})`);
  ok(/class="edge"/.test(c._els.overlay.innerHTML),
    "an existing zone is outlined edge by edge (percentages rule out <polygon>)");
  ok(!/<polygon/.test(c._els.overlay.innerHTML),
    "and never as a polygon, whose points attribute cannot take percentages");

  c._toggleDelete("forbidden:1");
  ok(c._del.forbidden.has(1), "tapping x marks that zone for deletion");
  ok(/edge doomed/.test(c._els.overlay.innerHTML), "a marked zone is drawn as doomed");
  ok(/Delete 1 no-go zone/.test(c._els.clean.textContent),
    `the action offers the delete (got "${c._els.clean.textContent}")`);

  c._toggleDelete("forbidden:1");
  ok(!c._del.forbidden.has(1), "tapping it again unmarks — nothing is destroyed until Save");

  // Walls are a different category and only visible in wall mode.
  c._toggleDelete("forbidden:0");
  c._setMode("wall");
  ok(c._deletionCount() === 0, "leaving the mode discards its marks");
  c._setEditGeometry(geometrySnapshot());
  c._renderOverlay();
  const wallHandles = [...c._els.overlay.querySelectorAll("[data-del]")].map((g) =>
    g.getAttribute("data-del")
  );
  ok(JSON.stringify(wallHandles) === JSON.stringify(["walls:0"]),
    `wall mode offers the walls, not the zones (got ${JSON.stringify(wallHandles)})`);
}

console.log("[del] a save sends indices and the revision they were read at");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  c._setMode("nogo");
  c._setEditGeometry(geometrySnapshot(7));
  c._zones = [{ x0: 0.1, y0: 0.2, x1: 0.4, y1: 0.5 }];
  c._toggleDelete("forbidden:1");
  ok(/Save 1 \+ delete 1/.test(c._els.clean.textContent),
    `one write does both (got "${c._els.clean.textContent}")`);

  h._calls.length = 0;
  await c._saveNogoZones();
  const call = h._calls.find((x) => x.domain === "vacuum" && x.service === "send_command");
  ok(!!call, "saving calls vacuum.send_command");
  const p = call.data.params;
  ok(JSON.stringify(p.forbidden) === JSON.stringify([[0.1, 0.2, 0.4, 0.5]]),
    "the new zone still rides as a normalized rect");
  ok(JSON.stringify(p.remove_forbidden) === JSON.stringify([1]),
    `the deletion rides as an INDEX, not coordinates (got ${JSON.stringify(p.remove_forbidden)})`);
  ok(p.revision === 7, "and carries the revision the index was read at");
  ok(p.replace === undefined, "still never replace:true — the backend merges");
  ok(c._deletionCount() === 0, "marks are cleared after a successful save");
}

console.log("[del] deleting alone is a valid write, and stale marks are dropped");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  c._setMode("nogo");
  c._setEditGeometry(geometrySnapshot(2));
  c._toggleDelete("forbidden:0");
  ok(c._els.clean.disabled === false,
    "the action is live with nothing drawn — a deletion is a change too");

  // A new revision renumbers everything; a mark made against the old one would
  // delete a different zone, so it must not survive.
  c._setEditGeometry(geometrySnapshot(3));
  ok(c._deletionCount() === 0, "a geometry revision change clears pending marks");
  ok(c._els.clean.disabled === true, "and the action goes back to nothing to do");

  c._toggleDelete("forbidden:0");
  h._calls.length = 0;
  await c._saveNogoZones();
  const call = h._calls.find((x) => x.domain === "vacuum" && x.service === "send_command");
  ok(!!call, "a delete-only save still dispatches");
  ok(call.data.params.forbidden === undefined,
    "with no `forbidden` key at all when nothing was drawn");
  ok(JSON.stringify(call.data.params.remove_forbidden) === JSON.stringify([0]),
    "carrying only the removal");
}

console.log("[del] a new vacuum starts without the old one's geometry and marks");
{
  const h = makeHass();
  h.states["vacuum.other"] = h.states["vacuum.robot"];
  const asked = []; // geometry requests: {entity_id, reply}
  h.connection = {
    sendMessagePromise: (m) => new Promise((reply) => asked.push({ entity_id: m.entity_id, reply })),
  };
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map", mode: "nogo" });
  document.body.appendChild(c);
  c.hass = h;
  c._setMode("nogo"); // the snapshot request for vacuum.robot goes out
  c._setEditGeometry(geometrySnapshot(4));
  c._toggleDelete("forbidden:0");
  c._stageMove("forbidden", 1, 10, 0, 0);
  delete h.connection; // no read for the new vacuum, whose reply would supersede the old one
  c.setConfig({ vacuum: "vacuum.other", camera: "camera.robot_map", mode: "nogo" });
  ok(c._editGeo === null && c._deletionCount() === 0 && c._moveCount() === 0,
    "setConfig drops the previous vacuum's snapshot, delete and move marks");
  ok(c._els.clean.textContent === "Save" && c._els.clean.disabled,
    `and Save has nothing to send (got "${c._els.clean.textContent}")`);
  asked.filter((r) => r.entity_id === "vacuum.robot").forEach((r) => r.reply(geometrySnapshot(4)));
  await new Promise((r) => setTimeout(r, 0));
  ok(c._editGeo === null, "a late snapshot of the previous vacuum does not land");
  c.remove();
}

// ---- rotating a pending shape ---------------------------------------------
console.log("[rot] a zone can be turned, and a turned zone travels as four corners");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  c._setMode("nogo");
  // A SQUARE map, so a quarter turn has an exact expected answer.
  c._setEditGeometry({
    revision: 1, width: 100, height: 100, origin_x: 0, origin_y: 0, resolution: 5,
    forbidden_zones: [], ban_mop_zones: [], virtual_walls: [],
  });
  c._zones = [{ x0: 0.4, y0: 0.3, x1: 0.6, y1: 0.7 }];

  ok(JSON.stringify(c._shapeParam(c._zones[0])) === JSON.stringify([0.4, 0.3, 0.6, 0.7]),
    "an unrotated zone keeps the four-number rect form every existing caller sends");

  ok(c._applyRotation(c._zones[0], Math.PI / 2) === true, "a quarter turn is accepted");
  const pts = c._shapeCorners(c._zones[0]);
  const near = (a, b) => Math.abs(a - b) < 1e-9;
  // Turning a 0.2 x 0.4 box 90 degrees about its centre (0.5, 0.5) gives a 0.4 x 0.2 box.
  ok(pts.length === 4, "still four corners");
  ok(near(Math.min(...pts.map((p) => p.x)), 0.3) && near(Math.max(...pts.map((p) => p.x)), 0.7),
    `the width and height swap on a quarter turn (x span ${JSON.stringify(pts.map((p) => p.x))})`);
  ok(near(Math.min(...pts.map((p) => p.y)), 0.4) && near(Math.max(...pts.map((p) => p.y)), 0.6),
    "and so does the y span");

  const param = c._shapeParam(c._zones[0]);
  ok(param.length === 4 && Array.isArray(param[0]) && param[0].length === 2,
    "a rotated zone goes on the wire as four [x, y] corners, not a bounding box");

  c._renderOverlay();
  ok(/class="turned nogo"/.test(c._els.overlay.innerHTML),
    "it is stroked edge by edge — an SVG <rect> cannot be rotated in percentages");
  ok(!/class="zone nogo"/.test(c._els.overlay.innerHTML),
    "and the axis-aligned rect is not drawn as well");
  ok(!!c._els.overlay.querySelector("[data-rot]"), "a rotate grip is offered");

  h._calls.length = 0;
  await c._saveNogoZones();
  const call = h._calls.find((x) => x.domain === "vacuum" && x.service === "send_command");
  const sent = call.data.params.forbidden[0];
  ok(sent.length === 4 && Array.isArray(sent[0]),
    `the corners survive to the service call (got ${JSON.stringify(sent)})`);
}

console.log("[rot] the turn is square on a non-square map, and stops at the edge");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  c._setMode("nogo");
  // 150 x 215 cells — the real T2266 map. Rotating in raw normalized coordinates here
  // would shear the shape; the aspect correction is what stops that.
  c._setEditGeometry({
    revision: 1, width: 150, height: 215, origin_x: 520, origin_y: 1350, resolution: 5,
    forbidden_zones: [], ban_mop_zones: [], virtual_walls: [],
  });
  const z = { x0: 0.4, y0: 0.45, x1: 0.6, y1: 0.55 };
  c._zones = [z];
  const side = (a, b) => Math.hypot((a.x - b.x) * 150, (a.y - b.y) * 215); // cells, not fractions
  const before = c._shapeCorners(z);
  const w0 = side(before[0], before[1]);
  const h0 = side(before[1], before[2]);
  c._applyRotation(z, 0.7);
  const after = c._shapeCorners(z);
  const w1 = side(after[0], after[1]);
  const h1 = side(after[1], after[2]);
  ok(Math.abs(w1 - w0) < 1e-6 && Math.abs(h1 - h0) < 1e-6,
    `side lengths are preserved on a non-square map (${w0.toFixed(3)}x${h0.toFixed(3)} -> ${w1.toFixed(3)}x${h1.toFixed(3)})`);
  ok(Math.abs(after[0].x - after[1].x) > 1e-6 && Math.abs(after[0].y - after[1].y) > 1e-6,
    "and the shape really did turn");

  // A shape against the edge cannot be turned off the map: the server clamps every
  // coordinate into 0-1, so a corner pushed outside would arrive distorted, silently.
  const edge = { x0: 0.0, y0: 0.0, x1: 0.3, y1: 0.1 };
  c._zones = [edge];
  ok(c._applyRotation(edge, Math.PI / 2) === false, "a turn that leaves the map is refused");
  ok(!edge.rot, "and the shape keeps the angle it had");
}

console.log("[rot] the grip drives a rotation instead of drawing a new zone");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  c._setMode("nogo");
  c._setEditGeometry({
    revision: 1, width: 100, height: 100, origin_x: 0, origin_y: 0, resolution: 5,
    forbidden_zones: [], ban_mop_zones: [], virtual_walls: [],
  });
  c._zones = [{ x0: 0.4, y0: 0.4, x1: 0.6, y1: 0.6 }];
  c._renderOverlay();
  const grip = c._els.overlay.querySelector("[data-rot]");
  ok(!!grip, "the grip is in the overlay");

  // The overlay has no layout in jsdom, so drive the projection directly: both points are
  // read through _mapNormFromClient, which the stub below pins.
  const seen = [{ x: 0.6, y: 0.6 }, { x: 0.4, y: 0.6 }];
  let call = 0;
  const real = c._mapNormFromClient;
  c._mapNormFromClient = () => seen[Math.min(call++, seen.length - 1)];
  c._onOverlayDown({ target: grip.querySelector("text"), clientX: 1, clientY: 1, pointerId: 9 });
  ok(c._shapeDrag && c._shapeDrag.action === "rotate", "pressing the grip starts a rotation");
  ok(c._drag === null, "and does NOT start drawing a zone");
  c._onOverlayMove({ clientX: 2, clientY: 2, pointerId: 9 });
  ok(Math.abs(c._zones[0].rot - Math.PI / 2) < 1e-9,
    `dragging the grip a quarter of the way round turns the shape by 90 degrees (got ${c._zones[0].rot})`);
  c._onOverlayUp({ clientX: 2, clientY: 2, pointerId: 9 });
  ok(c._shapeDrag === null, "releasing ends the rotation");
  c._mapNormFromClient = real;
}


// ---- moving shapes ---------------------------------------------------------
console.log("[mov] a pending shape moves with the grip and stays on the map");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  c._setMode("nogo");
  c._setEditGeometry({
    revision: 1, width: 100, height: 100, origin_x: 0, origin_y: 0, resolution: 5,
    forbidden_zones: [], ban_mop_zones: [], virtual_walls: [],
  });
  c._zones = [{ x0: 0.4, y0: 0.4, x1: 0.6, y1: 0.6 }];
  c._renderOverlay();
  const grip = c._els.overlay.querySelector("[data-mov]");
  ok(!!grip, "a pending shape offers a move grip");
  ok(grip.getAttribute("data-mov") === "new:0", "tagged like the other grips");

  const seen = [{ x: 0.5, y: 0.5 }, { x: 0.55, y: 0.6 }];
  let call = 0;
  const real = c._mapNormFromClient;
  c._mapNormFromClient = () => seen[Math.min(call++, seen.length - 1)];
  c._onOverlayDown({ target: grip.querySelector("circle"), clientX: 1, clientY: 1, pointerId: 4 });
  ok(c._shapeDrag && c._shapeDrag.action === "move", "the grip starts a move");
  ok(c._drag === null, "and never starts drawing a new shape");
  c._onOverlayMove({ clientX: 2, clientY: 2, pointerId: 4 });
  const z = c._zones[0];
  ok(Math.abs(z.x0 - 0.45) < 1e-9 && Math.abs(z.y0 - 0.5) < 1e-9,
    `the shape follows the finger (got ${z.x0.toFixed(3)}, ${z.y0.toFixed(3)})`);
  ok(Math.abs(z.x1 - z.x0 - 0.2) < 1e-9, "and keeps its size");

  // The server clamps normalized coordinates into 0-1, so a shape pushed past the edge
  // would arrive squashed against it. The step is refused instead.
  seen.push({ x: 5, y: 5 });
  c._onOverlayMove({ clientX: 3, clientY: 3, pointerId: 4 });
  ok(z.x1 <= 1 && z.y1 <= 1, "a move that would leave the map is refused");
  c._onOverlayUp({ clientX: 3, clientY: 3, pointerId: 4 });
  ok(c._shapeDrag === null, "releasing ends the move");
  c._mapNormFromClient = real;
}

console.log("[mov] an existing shape is staged as a world-cm delta, not new coordinates");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  c._setMode("nogo");
  // 150 x 215 cells at 5 cm: one normalized unit is 750 cm across and 1075 cm down.
  c._setEditGeometry({
    revision: 5, width: 150, height: 215, origin_x: 520, origin_y: 1350, resolution: 5,
    forbidden_zones: [[[600, 1900], [700, 1900], [700, 1800], [600, 1800]]],
    ban_mop_zones: [], virtual_walls: [[[600, 1500], [640, 1700]]],
  });
  c._renderOverlay();
  const grip = c._els.overlay.querySelector("[data-mov]");
  ok(grip && grip.getAttribute("data-mov") === "forbidden:0",
    "an existing zone offers a move grip tagged by category and index");

  const seen = [{ x: 0.2, y: 0.2 }, { x: 0.3, y: 0.3 }];
  let call = 0;
  const real = c._mapNormFromClient;
  c._mapNormFromClient = () => seen[Math.min(call++, seen.length - 1)];
  c._onOverlayDown({ target: grip, clientX: 1, clientY: 1, pointerId: 7 });
  c._onOverlayMove({ clientX: 2, clientY: 2, pointerId: 7 });
  c._onOverlayUp({ clientX: 2, clientY: 2, pointerId: 7 });
  const staged = c._moves.forbidden.get(0);
  ok(!!staged, "the transform is staged against the shape's index");
  // 0.1 of the width = 0.1 * 150 * 5 = 75 cm right; 0.1 of the height DOWN the image is
  // 0.1 * 215 * 5 = 107.5 cm DOWN in world cm, i.e. negative — the map counts rows down,
  // the device counts centimetres up.
  ok(Math.abs(staged.dx - 75) < 1e-6, `dx is world cm (got ${staged.dx})`);
  ok(Math.abs(staged.dy + 107.5) < 1e-6, `dy is world cm and flips sign (got ${staged.dy})`);

  ok(/edge moved/.test(c._els.overlay.innerHTML), "the moved shape is drawn as pending");
  ok(/Move 1 no-go zone/.test(c._els.clean.textContent),
    `the action offers the move (got "${c._els.clean.textContent}")`);

  h._calls.length = 0;
  await c._saveNogoZones();
  const call2 = h._calls.find((x) => x.domain === "vacuum" && x.service === "send_command");
  const p = call2.data.params;
  ok(JSON.stringify(p.move_forbidden) === JSON.stringify([{ index: 0, dx: 75, dy: -107.5, rotate: 0 }]),
    `the move rides as {index, dx, dy, rotate} (got ${JSON.stringify(p.move_forbidden)})`);
  ok(p.revision === 5, "guarded by the revision it was read at");
  ok(p.forbidden === undefined, "and sends no new shape when none was drawn");
  ok(c._moveCount() === 0, "staged moves are cleared after a successful save");
  c._mapNormFromClient = real;
}

console.log("[mov] rotating an existing shape stages a world angle");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  c._setMode("nogo");
  c._setEditGeometry({
    revision: 1, width: 100, height: 100, origin_x: 0, origin_y: 0, resolution: 5,
    forbidden_zones: [[[100, 100], [200, 100], [200, 200], [100, 200]]],
    ban_mop_zones: [], virtual_walls: [],
  });
  c._renderOverlay();
  const grip = c._els.overlay.querySelector("[data-rot]");
  ok(grip && grip.getAttribute("data-rot") === "forbidden:0",
    "an existing zone offers a rotate grip too");

  const shape = c._existingShapes()[0];
  const seen = [
    { x: shape.center.x + 0.1, y: shape.center.y },
    { x: shape.center.x, y: shape.center.y + 0.1 },
  ];
  let call = 0;
  const real = c._mapNormFromClient;
  c._mapNormFromClient = () => seen[Math.min(call++, seen.length - 1)];
  c._onOverlayDown({ target: grip, clientX: 1, clientY: 1, pointerId: 3 });
  c._onOverlayMove({ clientX: 2, clientY: 2, pointerId: 3 });
  const staged = c._moves.forbidden.get(0);
  // A quarter turn clockwise on screen is a quarter turn COUNTER-clockwise in the
  // device's world, whose y axis points the other way.
  ok(staged && Math.abs(staged.rot + Math.PI / 2) < 1e-9,
    `the staged world angle is the negated screen angle (got ${staged && staged.rot})`);
  c._onOverlayUp({ clientX: 2, clientY: 2, pointerId: 3 });
  c._mapNormFromClient = real;
}

console.log("[mov] a shape marked for deletion is not movable, and moves clear with the mode");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  c._setMode("nogo");
  c._setEditGeometry({
    revision: 1, width: 100, height: 100, origin_x: 0, origin_y: 0, resolution: 5,
    forbidden_zones: [[[100, 100], [200, 100], [200, 200], [100, 200]]],
    ban_mop_zones: [], virtual_walls: [],
  });
  c._toggleDelete("forbidden:0");
  c._renderOverlay();
  ok(!c._els.overlay.querySelector("[data-mov]"),
    "a doomed shape offers no move grip — the backend rejects moving and removing the same one");

  c._toggleDelete("forbidden:0");
  c._stageMove("forbidden", 0, 30, 0, 0);
  ok(c._moveCount() === 1, "a staged move counts as an edit");
  c._setMode("wall");
  ok(c._moveCount() === 0, "leaving the mode discards staged moves");

  // A move dragged back to where it started is not a move at all.
  c._setMode("nogo");
  c._setEditGeometry({
    revision: 1, width: 100, height: 100, origin_x: 0, origin_y: 0, resolution: 5,
    forbidden_zones: [[[100, 100], [200, 100], [200, 200], [100, 200]]],
    ban_mop_zones: [], virtual_walls: [],
  });
  c._stageMove("forbidden", 0, 30, 0, 0);
  c._stageMove("forbidden", 0, -30, 0, 0);
  ok(c._moveCount() === 0, "a shape returned to its origin stages nothing");
}


// ---- accessories: the Parts tab -------------------------------------------
const WEAR_SEG = 40; // mirrors WEAR_AMBER_AT in the card
console.log("[parts] the accessory tab lists consumables and resets them");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  const root = c.shadowRoot;

  const tab = root.querySelector(".mode-parts");
  ok(!!tab, "a Parts tab exists");
  // The bar is one row on a 300px sidebar column, so the label has to stay short.
  ok(tab.textContent.trim().length <= 5,
    `the label is short (got "${tab.textContent.trim()}")`);
  ok(tab.hidden === false, "it shows when the vacuum has accessory entities");

  c._setMode("parts");
  ok(tab.getAttribute("aria-pressed") === "true", "parts aria-pressed after toggle");
  ok(root.querySelector(".mode-rooms").getAttribute("aria-pressed") === "false",
    "rooms is released");
  // Not a map mode: the map, the overlay and the clean action have nothing to do here.
  ok(c._els.mapWrap.style.display === "none", "the map is hidden");
  ok(c._els.overlay.hidden === true, "and so is its overlay");
  ok(c._els.clean.hidden === true, "the clean action is hidden — each row acts on its own");
  ok(c._els.rooms.hidden === true, "the room list is hidden");
  ok(c._els.parts.hidden === false, "the parts list is shown");

  const rows = c._els.parts.querySelectorAll(".part");
  ok(rows.length === 4, `one row per part, sensors first (got ${rows.length})`);
  const names = [...rows].map((r) => r.querySelector(".p-name").textContent);
  ok(JSON.stringify(names) === JSON.stringify(["Filter", "Sensor", "Side brush", "Dust bag"]),
    `rows are named without the device prefix (got ${JSON.stringify(names)})`);
  ok(/153/.test(rows[0].textContent) && /of 200h/.test(rows[0].textContent),
    "a row shows hours left and the full life");
  ok(/^width:76%/.test(rows[0].querySelector(".p-fill").getAttribute("style") || ""),
    "the wear bar is the reported percentage");
  ok(rows[2].querySelector(".p-fill").className.includes("low"),
    "a nearly-worn part is flagged for browsers without color-mix");
  // "Sensor Remaining" and "Reset Sensors" are one part: hours, bar and Reset in one row.
  ok(/25/.test(rows[1].textContent) && !!rows[1].querySelector(".p-fill") &&
     rows[1].querySelector("[data-reset]").getAttribute("data-reset") === "button.robot_reset_sensors",
    "the sensor-cleaning counter and its Reset Sensors button share one row");
  ok(rows[1].querySelector("[data-reset]").disabled === true,
    "and an unavailable reset button is disabled");

  // The bar eases from the theme's blue to amber to red as a part wears, rather than
  // stepping at two thresholds — a part at 30 % should read as approaching something.
  const fresh = c._wearColor(100);
  const worn = c._wearColor(70);
  const half = c._wearColor(WEAR_SEG - 1);
  const dead = c._wearColor(0);
  ok(/var\(--primary-color\)/.test(fresh) && /\b0%/.test(fresh),
    `a full part is the theme's own blue, not a hard-coded one (got "${fresh}")`);
  ok(/var\(--primary-color\)/.test(worn) && !/\b0%/.test(worn),
    `a partly worn one is mixed off it (got "${worn}")`);
  ok(/oklab/.test(worn), "mixed in oklab, so the middle of the ramp does not go grey");
  ok(!/var\(--primary-color\)/.test(half) && !/var\(--primary-color\)/.test(dead),
    "past the amber point the blue is gone entirely");
  ok(/100%/.test(c._wearColor(WEAR_SEG)),
    "and the two segments meet at a full amber, with no jump between them");
  ok(/100%/.test(dead) && dead.includes("#e0726c"),
    `a spent part is the full red (got "${dead}")`);
  // Monotonic: every step toward zero must move further along the ramp, or the colour
  // would wobble back toward "healthy" as the part gets worse.
  const pctOf = (s) => Number((s.match(/ (\d+)%/) || [0, 0])[1]);
  let monotonic = true;
  for (let p = 100; p > WEAR_SEG; p -= 5) {
    if (pctOf(c._wearColor(p)) > pctOf(c._wearColor(p - 5))) monotonic = false;
  }
  for (let p = WEAR_SEG - 1; p > 0; p -= 5) {
    if (pctOf(c._wearColor(p)) > pctOf(c._wearColor(p - 5))) monotonic = false;
  }
  ok(monotonic, "the ramp only ever moves one way as life is used up");
  // `reset_dust_bag` has no life sensor at all — it must still be offered, and last.
  ok(!rows[3].querySelector(".p-fill"), "a reset-only entry shows no bar");
  ok(!!rows[3].querySelector('[data-reset="button.robot_reset_dust_bag"]'), "but still offers its reset");
}

console.log("[parts] a reset is armed before it fires");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  c._setMode("parts");
  h._calls.length = 0;

  const btn = c._els.parts.querySelector('[data-reset="button.robot_reset_filter"]');
  ok(!!btn, "the filter row offers a reset");
  btn.click();
  // A reset throws away the wear history with no undo, so one mis-tap must not do it.
  ok(h._calls.length === 0, "the first tap sends nothing");
  const armed = c._els.parts.querySelector('[data-reset="button.robot_reset_filter"]');
  ok(/Confirm/.test(armed.textContent), "it asks for confirmation instead");

  armed.click();
  const call = h._calls.find((x) => x.domain === "button" && x.service === "press");
  ok(!!call, "the second tap presses the button entity");
  ok(call.data.entity_id === "button.robot_reset_filter", "the right one");
  ok(c._partsArmed === null, "and the arm is spent");
}

console.log("[parts] the tab hides itself on a vacuum with no accessories");
{
  const h = makeHass();
  for (const eid of Object.keys(h.states)) {
    if (/_remaining$/.test(eid) || /button\.robot_reset_/.test(eid)) delete h.states[eid];
  }
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  ok(c.shadowRoot.querySelector(".mode-parts").hidden === true,
    "no accessory entities, no tab");
  c._setMode("parts");
  ok(c._mode === "rooms", "and asking for the mode falls back to rooms rather than an empty tab");
}

console.log("[parts] entity-supplied strings are escaped");
{
  const h = makeHass();
  // Discovery is by name pattern, so any entity matching `*_remaining` supplies these.
  const s = h.states["sensor.robot_filter_remaining"];
  s.state = '<img src=x onerror="window.__xss=1">';
  s.attributes.unit_of_measurement = "<b>h</b>";
  s.attributes.total_life_hours = '"><i>200</i>';
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  c._setMode("parts");
  const row = c._els.parts.querySelector(".part");
  ok(!c._els.parts.querySelector("img, b, i"), "no markup from the entity is parsed into elements");
  ok(row.textContent.includes('<img src=x onerror="window.__xss=1">'), "the state shows as literal text");
  ok(row.textContent.includes("<b>h</b>") && row.textContent.includes('"><i>200</i>'),
    "unit and total life show as literal text");
  ok(window.__xss === undefined, "nothing ran");
  c.remove();
}

console.log("[parts] a hass tick keeps focus on the Reset button");
{
  const h = makeHass();
  const c = document.createElement("eufy-clean-card");
  c.setConfig({ vacuum: "vacuum.robot", camera: "camera.robot_map" });
  document.body.appendChild(c);
  c.hass = h;
  c._setMode("parts");
  const sel = '[data-reset="button.robot_reset_filter"]';
  c._els.parts.querySelector(sel).click(); // arm: the button reads Confirm
  const armed = c._els.parts.querySelector(sel);
  armed.focus();
  ok(c.shadowRoot.activeElement === armed, "the armed Confirm button has focus");

  c.hass = { ...h }; // an unrelated tick: nothing in the rows changed
  ok(c._els.parts.querySelector(sel) === armed, "an unchanged tick does not rebuild the rows");
  ok(c.shadowRoot.activeElement === armed, "and focus stays on Confirm");

  const h2 = makeHass();
  h2.states["sensor.robot_filter_remaining"].state = "152";
  c.hass = h2; // a real change rebuilds the rows
  const rebuilt = c._els.parts.querySelector(sel);
  ok(rebuilt !== armed && /152/.test(c._els.parts.textContent), "a changed value rebuilds the rows");
  ok(c.shadowRoot.activeElement === rebuilt, "and focus moves to the same Reset button in the new rows");
  c.remove();
}

console.log(fail === 0 ? "\nALL PASSED" : `\n${fail} FAILURES`);
process.exit(fail === 0 ? 0 : 1);