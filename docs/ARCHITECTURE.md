# Eufy Clean — Architecture Guide

> **Audience**: contributors, and anyone reviewing or extending this integration.
>
> Companion documents: [`MAP.md`](MAP.md) (how the floor map is obtained and drawn),
> [`MAP_WS_CONTRACT.md`](MAP_WS_CONTRACT.md) (the map websocket wire format). End-user
> documentation — entities, services, configuration — is in the top-level
> [`README.md`](../README.md).

---

## Layers

```
HA entity platforms  vacuum · sensor · select · switch · number · button ·
                     binary_sensor · camera · time · update
        │  read  coordinator.data  (VacuumState)
        │  write coordinator.async_send_command(...)
        ▼
EufyCleanCoordinator          one per device; push-driven (Tuya cloud devices are polled)
        │  inbound  update_state(state, dps) -> (new_state, changes)
        │  outbound build_command(...)       -> {dps_key: value}
        ▼
Transport + codec layer
        HTTP      api/http.py, api/cloud.py       login, device list, credentials
        MQTT      api/client.py                   AWS IoT, mutual TLS, port 8883
        Tuya      api/tuya_cloud.py, api/tuya_thing.py, api/local_tuya.py,
                  api/tuya_mqtt.py, api/tuya_storage.py
        Codec     utils.py, proto/cloud/*         protobuf encode/decode
```

Everything above the coordinator is transport-agnostic: entities read a `VacuumState`
and call `async_send_command()`. Everything below it is selected per device by the
device's **API type**.

---

## Device API types

`EufyLogin.checkApiType()` classifies each device from its first DPS snapshot, by the
*shape* of the values rather than by model number:

| API type | Datapoint values | Transport | Typical models |
|----------|------------------|-----------|----------------|
| `novel` | base64 protobuf on DPS 152–180 | Eufy AWS IoT MQTT | X8 Pro, X9 Pro, X10 Pro Omni, newer G/L series |
| `scalar` | plain ints / numeric strings / JSON on the same DPS numbers | Eufy AWS IoT MQTT | G50 and similar Tuya-derived models |
| `legacy` | no protobuf datapoints at all; string/bool/int on low DPS numbers | Tuya Cloud, Tuya LAN, Tuya mobile MQTT | RoboVac 11S/15C/30C, T2266 X8 Pro Hybrid |

The type is stored on the coordinator as `coordinator.api_type` and on
`VacuumState.api_type`. The entity capability gate treats anything that is not
`scalar` as `novel` (see *Capability gating* below); platforms add or drop the
legacy-only entities by `coordinator.api_type` themselves.

Model → name and capability metadata live in `const.py:EUFY_CLEAN_DEVICES` and
`profiles.py`.

---

## Startup flow

1. **`config_flow.py`** collects email + password (and re-authentication when a stored
   session expires).
2. **`__init__.py:async_setup_entry()`**
   - builds an `EufyLogin` and calls `init()` — HTTP login, then device discovery;
   - creates one `EufyCleanCoordinator` per discovered vacuum and calls `initialize()`;
     a vacuum whose `initialize()` fails is left out, and MQTT vacuums left out while
     Eufy logins are on hold make the entry reload once the hold-off ends;
   - stores them in `hass.data[DOMAIN][entry.entry_id]`;
   - forwards setup to every platform in `PLATFORMS`.
   (`async_setup()` registers the map websocket commands, and the frontend card once
   `frontend` is up.)
3. **`api/cloud.py:EufyLogin.init()`**
   - `api/http.py` authenticates against the Eufy user API and fetches the device list;
   - retrieves the MQTT credentials (client certificate, private key, endpoint, thing
     name) and merges the cloud device list for model names, aliases and firmware;
   - for `legacy` devices, additionally logs into Tuya Cloud (`api/tuya_cloud.py`) and
     the Tuya Thing SDK session (`api/tuya_thing.py`).
4. **`api/client.py:EufyCleanClient.connect()`** writes the certificate and key to temp
   files, connects to AWS IoT over mutual TLS and subscribes to the device topic.
5. Device messages arrive by push. Each one updates `VacuumState`; entities re-render
   through `CoordinatorEntity`.

Sessions are cached by `auth_store.py` so a restart does not re-login; Eufy rate-limits
logins aggressively.

---

## Novel transport — MQTT + protobuf

### Topics

| Direction | Topic |
|-----------|-------|
| Subscribe (device → HA) | `cmd/eufy_home/{model}/{device_id}/res` |
| Publish (HA → device) | `cmd/eufy_home/{model}/{device_id}/req` |

### Envelope

```json
{
  "head": { "client_id": "...", "cmd": 65537, "cmd_status": 2,
            "version": "1.0.0.1", "timestamp": 1704326400000 },
  "payload": "{\"account_id\": \"...\", \"data\": {\"152\": \"base64...\"},
               \"device_sn\": \"...\", \"protocol\": 2, \"t\": 1704326400000}"
}
```

`payload` is a JSON string whose `data` object is the **DPS dictionary**: datapoint id
(string) → value. On novel devices each value is a base64 protobuf message.

### Protobuf codec (`utils.py`)

```
encode:  message.SerializeToString() → prepend varint length → base64
decode:  base64 → strip varint length prefix → MessageType.FromString()
```

The `has_length` argument controls the varint prefix; a few datapoints omit it.

### Datapoint map

Defined in `const.py:DPS_MAP`.

| DPS | Key | Direction | Protobuf type | Purpose |
|-----|-----|-----------|---------------|---------|
| 152 | `PLAY_PAUSE` | write | `ModeCtrlRequest` | main control channel: start, pause, stop, go home, room/zone/scene clean |
| 153 | `WORK_STATUS` | read | `WorkStatus` | activity, charging, mode, trigger, scene, station sub-status |
| 154 | `CLEANING_PARAMETERS` | both | `CleanParam` | global cleaning defaults (fan speed, clean type, water level) |
| 155 | `DIRECTION` | write | — | directional / joystick control |
| 156 | `MULTI_MAP_SW` | write | — | multi-map switch |
| 158 | `CLEAN_SPEED` | both | int index | fan speed: 0 Quiet, 1 Standard, 2 Turbo, 3 Max |
| 160 | `FIND_ROBOT` | both | bool | "find my robot" beep |
| 163 | `BATTERY_LEVEL` | read | int | battery percentage |
| 164 | `MAP_EDIT` | write | `MapEditRequest` | map edits |
| 165 | `MAP_DATA` | read | `UniversalDataResponse` / `RoomParams` | room list and map id |
| 166 | `MAP_STREAM` | read | — | map stream channel |
| 167 | `CLEANING_STATISTICS` | read | `CleanStatistics` | duration and area |
| 168 | `ACCESSORIES_STATUS` | both | `ConsumableResponse` / `ConsumableRequest` | consumable wear and resets |
| 169 | `MAP_MANAGE` | write | — | map management |
| 170 | `MAP_EDIT_REQUEST` | write | `MapEditRequest` | per-room cleaning parameters |
| 173 | `STATION_STATUS` / `GO_HOME` | both | `StationResponse` / `StationRequest` | dock status and dock actions |
| 176 | `UNSETTING` | write | — | miscellaneous settings |
| 177 | `ERROR_CODE` | read | `ErrorCode` | error codes (`const.py:EUFY_CLEAN_ERROR_CODES`) |
| 180 | `SCENE_INFO` | read | `SceneResponse` | cleaning scenes |

Two datapoints carry different messages per direction: 153 is both `WORK_MODE` and
`WORK_STATUS`, and 173 is `GO_HOME` outbound but `STATION_STATUS` inbound.

### Global vs per-room cleaning parameters

- **DPS 154** holds the *global* defaults used by a plain auto clean.
- **DPS 170** holds *per-room* overrides — fan speed, water level, clean mode, clean
  intensity, edge mopping — and takes precedence during a room clean.

A room clean with custom parameters is therefore a two-step sequence:

```
1.  DPS 170   MapEditRequest.SET_ROOMS_CUSTOM   per-room parameters
2.  DPS 152   ModeCtrlRequest, mode = CUSTOMIZE  "clean these rooms with those parameters"
```

Without custom parameters only step 2 is sent, with `mode = GENERAL`, and the device
uses its own stored per-room defaults.

Two input shapes are accepted: `rooms` (a list of dicts, one per room, each carrying its
own settings) or `room_ids` (a list of ints plus one set of parameters applied to all).

---

## Scalar transport

Scalar devices use the same MQTT envelope and datapoint numbers, but the values are
plain integers, numeric strings or JSON documents instead of protobuf. `api/parser.py`
detects this from `state.api_type` and hands the whole dictionary to
`api/parser_scalar.py`; commands are built by the scalar branches in
`api/commands.py`.

They are vacuum-only — no dock station, no map — so most station and map entities are
filtered out before they reach the registry.

---

## Legacy (Tuya) transport

Legacy devices are Tuya devices wearing an Eufy badge. The integration reaches them
through up to four channels, chosen per datapoint:

| Channel | Module | Carries |
|---------|--------|---------|
| Tuya Cloud API | `api/tuya_cloud.py` | state polling, all control writes, map operations on DPS 124 |
| Tuya Thing SDK session | `api/tuya_thing.py` | the session used for storage access and the mobile MQTT channel |
| Tuya LAN (tinytuya, port 6668) | `api/local_tuya.py` | push state updates and most writes, without cloud polling |
| Tuya mobile MQTT | `api/tuya_mqtt.py` | the live robot pose, cleaning trail and map metadata |

Inbound values are parsed by `api/legacy_parser.py`; outbound commands are built by
`api/legacy_commands.py`.

Two transport rules matter when touching this path:

- **Map operations (DPS 124) must go over the cloud.** A LAN write is accepted by the
  device and then silently ignored.
- **The LAN transport is push-only.** There is no periodic state poll; a write that
  the device does not announce back is caught by one `status()` re-read shortly after
  the write.

The floor map itself is not on any datapoint — see [`MAP.md`](MAP.md).

---

## Inbound data flow

```
MQTT / LAN / cloud message
    → coordinator: JSON parse, extract the DPS dictionary
    → coordinator: api_type == "legacy" → api/legacy_parser.py:update_state_legacy()
                   otherwise           → api/parser.py:update_state(current_state, dps)
                         api_type == "scalar" → api/parser_scalar.py
                         otherwise            → the protobuf handlers below
    → (new_state, changes)
    → coordinator: dock-status debounce, trail bookkeeping, map refresh triggers
    → async_set_updated_data(state) → entities re-render
```

Protobuf handler routing inside `api/parser.py`:

| DPS | Handler | Produces |
|-----|---------|----------|
| 153 | `_process_work_status()` | activity, task status, charging, trigger source, dock status, scene |
| 173 | `_process_station_status()` | dock status, water levels, dock auto-config |
| 163 | — | `battery_level` |
| 158 | `_map_clean_speed()` | `fan_speed` |
| 177 | `ErrorCode` | `error_code`, `error_message`, `error_codes`, `warn_codes` |
| 168 | `_parse_accessories()` | filter / brush / mop wear |
| 167 | `CleanStatistics` | `cleaning_time`, `cleaning_area` |
| 180 | `_parse_scene_info()` | `scenes` |
| 165 | `_parse_map_data()` | `rooms`, `map_id` |
| 160 | — | `find_robot` |

### State mappings

`WorkStatus.state` → `activity`:

| Value | Meaning | activity |
|-------|---------|----------|
| 0, 1 | standby / sleep | `idle` |
| 2 | fault | `error` |
| 3 | charging | `docked` |
| 4 | positioning | `cleaning` |
| 5 | cleaning (washing/drying at the dock, or a user pause) | `cleaning` / `docked` / `paused` |
| 6 | remote control | `cleaning` |
| 8 | cleaning (alternate) | `cleaning` |
| 7 | go home | `returning` |
| 15 | paused | `paused` |

`WorkStatus.trigger.source` → `trigger_source`: 1 app, 2 button, 3 schedule, 4 robot,
5 remote control. When the field is absent, the source is inferred from the mode id
(`const.py:EUFY_CLEAN_APP_TRIGGER_MODES`).

### Dock-status debounce

Dock sub-states change faster than they should be shown. The coordinator holds a new
`dock_status` for 2 seconds before committing it: during the window entities keep the
previous value, and a newer status restarts the timer. `const.py:DOCK_ACTIVITY_STATES`
lists the states that count as an active dock operation.

---

## Outbound data flow

```
entity action
    → build_command("name", **params)      api/commands.py (novel / scalar)
                                           api/legacy_commands.py (legacy)
    → {dps_key: encoded_value}
    → coordinator.async_send_command(dps)
    → transport: MQTT publish / Tuya cloud write / LAN write
```

`build_command()` is the single dispatcher. The main routes:

| Command | DPS | Message |
|---------|-----|---------|
| `start_auto` | 152 | `ModeCtrlRequest`, control 0 (AUTO) |
| `play` / `resume` | 152 | control 14 |
| `pause` | 152 | control 13 |
| `stop` | 152 | control 12 |
| `return_to_base` / `go_home` | 152 | control 6 |
| `clean_spot` | 152 | control 3 |
| `room_clean` | 152 | `SelectRoomsClean` |
| `scene_clean` | 152 | control 24 |
| `set_room_custom` | 170 | `MapEditRequest` |
| `set_fan_speed` | 158 | int index |
| `locate` / `find_robot` | 160 | bool |
| `go_dry` / `stop_dry` / `go_selfcleaning` / `collect_dust` | 173 | `StationRequest` |
| `set_auto_cfg` | 173 | `StationRequest` |
| `reset_accessory` | 168 | `ConsumableRequest` |

Control codes are `const.py:EUFY_CLEAN_CONTROL`. Per-room parameter vocabularies are
`CLEAN_TYPE_MAP`, `CLEAN_EXTENT_MAP` and `MOP_LEVEL_MAP` in the same file.

---

## State model (`models.py`)

```
VacuumState
├── api_type: str                  "novel" | "scalar" | "legacy"
├── activity: str                  idle | cleaning | paused | docked | returning | error
├── battery_level: int
├── fan_speed: str                 Quiet | Standard | Turbo | Max
├── error_code: int / error_message: str
├── error_codes: list[int] / warn_codes: list[int]  # Novel only; empty on scalar and legacy
├── charging: bool
├── cleaning_time: int             seconds
├── cleaning_area: int             m²
├── task_status: str               human-readable detail, e.g. "Washing Mop"
├── find_robot: bool
├── map_id: int / map_url: str | None
├── rooms: list[dict]              [{id, name}, ...]
├── scenes: list[dict]             [{id, name, type}, ...]
├── status_code: int               raw WorkStatus.state
├── dock_status: str | None
├── station_clean_water / station_waste_water: int
├── dock_auto_cfg: dict            auto-empty, auto-wash settings
├── trigger_source: str
├── current_scene_id: int / current_scene_name: str | None
├── accessories: AccessoryState    consumable wear hours
├── preferences: CleaningPreferences
├── raw_dps: dict                  every raw datapoint, for diagnostics
└── received_fields: set[str]      fields the device has actually reported
```

State is immutable: parsers return a `changes` dict and the coordinator applies
`dataclasses.replace()`.

`received_fields` (maintained by `track_received_field`) is what makes entity
availability honest — a device that never reports `dock_status` gets an unavailable dock
sensor rather than a fabricated one. Consumable lifespans and wire keys are the
per-model `AccessorySpec` entries in `profiles.py`.

---

## Entity layer

Every entity is a `CoordinatorEntity[EufyCleanCoordinator]`:

```python
# read
RoboVacSensor(coordinator, value_fn=lambda s: s.battery_level, ...)

# availability
availability_fn=lambda s: "dock_status" in s.received_fields

# write
await self.coordinator.async_send_command(build_command("start_auto"))
await self.coordinator.async_send_command(build_command("scene_clean", scene_id=42))
await self.coordinator.async_send_command(
    build_command("room_clean", room_ids=[1, 2], map_id=3))
```

### Capability gating

Entities declare which API types they support, either as a class attribute or as a
constructor argument on the generic classes:

```python
supported_api_types = ("novel",)   # or ("scalar",)
```

Each platform's `async_setup_entry` passes its candidates through
`entity.filter_supported_entities()`, so an unsupported entity never reaches the
registry at all. `entity.py:effective_api_type()` folds `legacy` and unknown types into
`novel`.

### Platforms

| Platform | Contents |
|----------|----------|
| `vacuum.py` | the main `StateVacuumEntity`: start, pause, stop, return, locate, fan speed, `send_command`, room/zone/scene services |
| `sensor.py` | battery, error, task status, trigger source, cleaning statistics, water levels, consumable remaining life |
| `select.py` | scene and room selection, cleaning mode, suction level, dock configuration |
| `switch.py` | auto-empty, auto-wash, boost, find-robot toggles |
| `number.py` | numeric settings such as wash frequency and voice volume |
| `button.py` | dock actions (wash, dry, empty dust) and consumable resets |
| `binary_sensor.py` | charging |
| `camera.py` | the server-rendered floor-map PNG ([`MAP.md`](MAP.md)) |
| `time.py` | Do Not Disturb and off-peak charging times |
| `update.py` | firmware version and OTA install (Tuya devices) |

Services are declared in `services.yaml`; user-facing strings in `strings.json` and
`translations/en.json`.

---

## Directory map

```
custom_components/robovac_mqtt/
├── __init__.py            setup / teardown, coordinator construction, frontend registration
├── config_flow.py         login and re-authentication UI
├── auth_store.py          cached sessions
├── const.py               datapoint map, models, enums, error codes, API URLs
├── coordinator.py         MQTT lifecycle, state management, map and trail state
├── entity.py              API-type capability gate
├── models.py              VacuumState and friends
├── profiles.py            per-model capability metadata
├── utils.py               protobuf and varint codec helpers
├── diagnostics.py         redacted diagnostics dump
├── websocket_api.py       map websocket commands (MAP_WS_CONTRACT.md)
├── _orphan_cleanup.py     removes registry entries for devices that disappeared
├── <platform>.py          the entity platforms listed above
├── api/
│   ├── http.py            Eufy REST login and device discovery
│   ├── cloud.py           login orchestration, API-type classification
│   ├── client.py          AWS IoT MQTT client
│   ├── commands.py        build_command() for novel and scalar devices
│   ├── parser.py          inbound datapoint → VacuumState
│   ├── parser_scalar.py   scalar datapoint parsing
│   ├── legacy_commands.py legacy command builders
│   ├── legacy_parser.py   legacy datapoint parsing
│   ├── tuya_cloud.py      Tuya Cloud API client
│   ├── tuya_thing.py      Tuya Thing SDK session
│   ├── tuya_storage.py    map file download from Tuya cloud storage
│   ├── tuya_mqtt.py       Tuya mobile MQTT: live pose, trail, map metadata
│   ├── tuya_map.py        map blob decoder
│   ├── local_tuya.py      Tuya LAN transport
│   ├── map_stream.py      map decoding and PNG rendering
│   └── map_geometry.py    map websocket payload builder
├── frontend/              the bundled Lovelace card
└── proto/cloud/           protobuf schemas and pre-compiled modules
```

Protobuf modules are **pre-compiled and committed** (`*_pb2.py` plus `.pyi` stubs); they
are not generated at build or install time.

---

## Tests

`tests/` holds the pytest suite (pytest + asyncio, `pytest-homeassistant-custom-component`),
one file per module under test. Run everything with `python run_tests.py`.
