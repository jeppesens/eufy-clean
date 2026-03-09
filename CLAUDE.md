# Eufy Clean - Home Assistant Integration

Home Assistant custom component (`robovac_mqtt`) for controlling Eufy robot vacuums via MQTT.
Installed via HACS. Domain: `robovac_mqtt`. Codeowners: @jeppesens, @m11tch.

## Architecture

Three-layer design: **HA Entities** -> **Coordinator** -> **API (HTTP + MQTT + Protobuf)**

```
HA Entities (vacuum, sensor, select, switch, number, button, binary_sensor)
    |
    |  self.coordinator.data (VacuumState)        # read state
    |  self.coordinator.async_send_command(cmd)    # send commands
    v
EufyCleanCoordinator (push-based via MQTT, NOT polling)
    |
    |  update_state(state, dps) -> (new_state, changes)   # inbound
    |  build_command("start_auto") -> {dps_key: value}    # outbound
    v
API Layer
    - HTTP: EufyLogin (api/cloud.py + api/http.py) - login, get MQTT creds & device list
    - MQTT: EufyCleanClient (api/client.py) - Paho MQTT, TLS 1.2, port 8883
    - Protobuf: encode/decode (utils.py) - serialize/deserialize DPS values
```

## Directory Structure

```
custom_components/robovac_mqtt/
├── __init__.py          # Entry point: async_setup_entry, creates coordinators per device
├── config_flow.py       # HA config UI: email/password login
├── const.py             # DPS_MAP, device models, enums, error codes (100+), API URLs
├── coordinator.py       # EufyCleanCoordinator: MQTT lifecycle, state mgmt, dock debounce
├── models.py            # VacuumState, AccessoryState, CleaningPreferences dataclasses
├── utils.py             # decode()/encode_message() for protobuf serialization
├── vacuum.py            # StateVacuumEntity: start/stop/pause/return/locate/fan_speed
├── sensor.py            # Battery, error, task status, cleaning stats, consumables
├── select.py            # Scene/room selection, dock config dropdowns
├── switch.py            # Auto-empty, auto-wash, find robot toggles
├── number.py            # Numeric controls (wash frequency value)
├── button.py            # Action triggers (wash mop, dry, empty dust, reset consumables)
├── binary_sensor.py     # Binary state (charging)
├── controllers/
│   ├── ca.pem           # CA certificate for MQTT TLS
│   └── key.key          # Client key for mutual TLS
├── api/
│   ├── __init__.py      # Package marker
│   ├── http.py          # EufyHTTPClient: REST login, device discovery
│   ├── cloud.py         # EufyLogin: orchestrates login flow, retrieves MQTT creds
│   ├── client.py        # EufyCleanClient: Paho MQTT wrapper, connect/send/receive
│   ├── commands.py      # build_command() dispatcher + protobuf command builders
│   └── parser.py        # update_state(): DPS -> VacuumState mapping (most complex file)
└── proto/cloud/         # 37 .proto files + generated *_pb2.py (pre-compiled, not built)
    ├── work_status.proto      # Vacuum state (mode, charging, cleaning, dock activity)
    ├── station.proto          # Dock status, water levels, auto-config
    ├── control.proto          # ModeCtrlRequest, SelectRoomsClean, AutoClean
    ├── clean_param.proto      # Fan speed, water level, clean type/extent
    ├── consumable.proto       # Accessory wear tracking (filter, brushes, mop, etc.)
    ├── scene.proto            # Predefined cleaning scenes
    ├── error_code.proto       # Error code list
    ├── stream.proto           # RoomParams (map/room data)
    ├── universal_data.proto   # UniversalDataResponse (map/room data, alternate format)
    └── map_edit.proto         # MapEditRequest (per-room custom settings)
```

## Protobuf Data Flow

### Inbound: MQTT message -> VacuumState

```
MQTT broker publishes to: cmd/eufy_home/{model}/{device_id}/res
    |
    v
JSON wrapper: { "head": {...}, "payload": { "data": { DPS_KEY: base64_value, ... } } }
    |
    v
parser.py: update_state(current_state, dps_dict)
    |  Dispatches by DPS key to:
    |    _process_work_status()     -> activity, task_status, charging, trigger, dock, scene
    |    _process_station_status()  -> dock_status, water levels, auto config
    |    _process_other_dps()       -> battery, fan_speed, error, accessories, map, scenes
    v
utils.py: decode(ProtoType, base64_value)
    1. base64 decode -> raw bytes
    2. Strip varint length prefix (if has_length=True)
    3. ProtoType().FromString(bytes) -> typed protobuf message
    |
    v
Map protobuf fields to VacuumState fields (e.g., WorkStatus.state=5 -> activity="cleaning")
    |
    v
dataclasses.replace(state, **changes) -> new VacuumState
```

### Outbound: Command -> MQTT

```
Entity calls: coordinator.async_send_command(build_command("start_auto"))
    |
    v
commands.py: build_command() -> { DPS_KEY: encoded_value }
    |  Uses encode(ProtoType, data_dict) or encode_message(proto_msg)
    |    1. ProtoType(**data).SerializeToString()
    |    2. Prepend varint length prefix
    |    3. base64 encode -> string
    v
client.py: send_command(data_payload)
    Wraps in JSON: { "head": {cmd: 65537, ...}, "payload": {data: payload, device_sn: ...} }
    Publishes to: cmd/eufy_home/{model}/{device_id}/req
```

## DPS (Device Property Set) Mapping

DPS keys are numeric strings that route to specific protobuf message types:

| DPS Key | Name | Protobuf Type | Direction |
|---------|------|---------------|-----------|
| "152" | PLAY_PAUSE | ModeCtrlRequest | Send |
| "153" | WORK_MODE | WorkStatus | Receive |
| "154" | CLEANING_PARAMETERS | CleanParam | Receive |
| "155" | DIRECTION | — | (unused) |
| "156" | MULTI_MAP_SW | — | (unused) |
| "158" | CLEAN_SPEED | (plain int index) | Both |
| "160" | FIND_ROBOT | (plain bool) | Both |
| "163" | BATTERY_LEVEL | (plain int) | Receive |
| "164" | MAP_EDIT | MapEditRequest | Send |
| "165" | MAP_DATA | UniversalDataResponse / RoomParams | Receive |
| "166" | MAP_STREAM | — | (unused) |
| "167" | CLEANING_STATISTICS | CleanStatistics | Receive |
| "168" | ACCESSORIES_STATUS | ConsumableResponse/Request | Both |
| "169" | MAP_MANAGE | — | (unused) |
| "170" | MAP_EDIT_REQUEST | MapEditRequest | Send |
| "173" | STATION_STATUS / GO_HOME | StationResponse (recv) / StationRequest (send) | Both |
| "176" | UNSETTING | — | (unused) |
| "177" | ERROR_CODE | ErrorCode | Receive |
| "180" | SCENE_INFO | SceneResponse | Receive |

## Key State Mappings

**WorkStatus.state** (int) -> activity (string):
- 0,1 = "idle" (standby/sleep)
- 2 = "error" (fault)
- 3 = "docked" (charging)
- 4 = "cleaning" (positioning)
- 5 = "cleaning" (active clean, or "docked" if drying)
- 7 = "returning" (go home)

**Dock status** is debounced by 2 seconds in the coordinator to avoid flickering between states during rapid transitions.

**Trigger source** (WorkStatus.trigger.source): 1=app, 2=button, 3=schedule, 4=robot, 5=remote_control. Falls back to mode inference if trigger field missing.

## Entity Pattern

All entities inherit `CoordinatorEntity[EufyCleanCoordinator]`:

```python
# Reading state - entities use lambda accessors
RoboVacSensor(coordinator, value_fn=lambda s: s.battery_level, ...)

# Sending commands
await self.coordinator.async_send_command(build_command("start_auto"))
await self.coordinator.async_send_command(build_command("scene_clean", scene_id=42))
await self.coordinator.async_send_command(build_command("room_clean", room_ids=[1,2], map_id=3))

# Availability - sensors check received_fields to avoid showing unsupported features
availability_fn=lambda s: "dock_status" in s.received_fields
```

## Startup Flow

1. `config_flow.py` collects email/password
2. `__init__.py:async_setup_entry()` creates `EufyLogin`, calls `init()` (HTTP login + get devices)
3. For each device: creates `EufyCleanCoordinator`, calls `initialize()` (MQTT connect)
4. Forwards setup to all 7 platforms (vacuum, sensor, select, switch, number, button, binary_sensor)
5. MQTT messages arrive via push -> coordinator updates `VacuumState` -> entities auto-refresh

## Supported Device Series

- **X-Series**: T2261, T2262, T2266, T2276, T2320, T2351 (X8, X8 Pro, X9 Pro, X10 Pro Omni)
- **G-Series**: T2210-T2278 (G20, G30, G35, G40, G50, etc.)
- **L-Series**: T2190, T2267, T2268, T2278 (L60, L70)
- **C-Series**: T1250, T2117, T2118, T2120, T2128, T2130, T2132, T2280, T2292 (legacy + C20)
- **S-Series**: T2119, T2080 (RoboVac 11S, S1)

Full model mapping in `const.py:EUFY_CLEAN_DEVICES`.

## Key Constants (`const.py`)

**`EUFY_CLEAN_CONTROL`** (int enum) - Command codes used by `build_command()`:
- 0=AUTO, 1=SELECT_ROOMS, 2=SELECT_ZONES, 3=SPOT, 4=GOTO, 5=RC, 6=GOHOME, 9=FAST_MAPPING, 10=GOWASH, 12=STOP, 13=PAUSE, 14=RESUME, 24=SCENE_CLEAN

**Custom room parameter maps** (used by `set_room_custom` command):
- `CLEAN_TYPE_MAP`: "vacuum"/"mop"/"vacuum_mop" → protobuf `CleanType`
- `CLEAN_EXTENT_MAP`: "fast"/"standard"/"deep" → protobuf `CleanExtent`
- `MOP_LEVEL_MAP`: "low"/"middle"/"high" → protobuf `MopMode`

**`DOCK_ACTIVITY_STATES`** - Tuple of dock operation strings ("Washing", "Drying", "Emptying dust", etc.) used by coordinator to detect active dock operations.

**Series lists** (`EUFY_CLEAN_X_SERIES`, `_G_SERIES`, `_L_SERIES`, `_C_SERIES`, `_S_SERIES`) - Used for feature gating per device series.

**`EUFY_CLEAN_APP_TRIGGER_MODES`** - Mode IDs (1-9) that imply app as trigger source when `WorkStatus.trigger` is missing.

## Development Notes

- **Test suite** in `tests/` with ~20 test files (pytest + asyncio) covering entities, parser, coordinator, and config flow
- Proto files are **pre-compiled** (`*_pb2.py` + `*_pb2.pyi` stubs) - do not regenerate at build time
- Some DPS keys overlap: "153" = both WORK_MODE and WORK_STATUS; "173" = both GO_HOME (send) and STATION_STATUS (receive)
- Error codes: 100+ entries in `const.py:EUFY_CLEAN_ERROR_CODES`
- MQTT uses mutual TLS with device-specific certificates from the Eufy cloud API
- The `has_length` parameter in decode/encode controls whether a varint length prefix is present
- Accessory max lifespans defined in `const.py:ACCESSORY_MAX_LIFE` (hours)
