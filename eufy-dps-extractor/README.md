# eufy-dps-extractor

Dockerized tool to decompile the eufy Clean (EufyHome) Android APK and extract device property definitions, DPS mappings, and per-model Thing Model schemas.

Built for extending the [eufy-clean](https://github.com/jeppesens/eufy-clean) Home Assistant integration.

## Quick Start

### 1. Get the APK

Download `com.eufylife.smarthome` from APKMirror. You want the latest version for the most complete model coverage.

> **Important:** You want `com.eufylife.smarthome` (eufy Clean/EufyHome), NOT `com.oceanwing.smarthome` (eufy Life — their health/scale products).

APKMirror delivers `.apkm` files (app bundles). This is fine — the tool handles them automatically.

### 2. Run

```bash
mkdir -p apk output

# Drop your APK/APKM in the apk/ folder
cp ~/Downloads/com.eufylife.smarthome_*.apkm apk/

# Build and run
docker compose up --build
```

Or without compose:

```bash
docker build -t eufy-dps-extractor .
docker run --rm \
  -v "$(pwd)/apk:/apk:ro" \
  -v "$(pwd)/output:/output" \
  eufy-dps-extractor
```

### 3. Results

Everything lands in `output/<apk-name>/`:

```
output/<apk-name>/
  REPORT.md                   Summary with next steps
  dps_extracted.json          Structured JSON from Java decompilation
  grep_results/               Raw grep output (8 passes)
  vacuum_sources/             Decompiled .java files related to vacuum/DP
  assets/                     JSON/config files with DP schemas
  jadx_warnings.log           Decompiler warnings
```

## What It Does

1. **Extracts** `base.apk` and split APKs from `.apkm`/`.xapk`/`.apks` bundles
2. **Decompiles** Java bytecode using [jadx](https://github.com/skylot/jadx)
3. **Runs 8 grep passes** across decompiled source looking for DP ID assignments, Tuya SDK calls, constant declarations, mode strings, etc.
4. **Copies** all vacuum-related decompiled source files for manual inspection
5. **Runs a Python deep-scan** that builds a unified DP table from all sources
6. **Generates** a report with exploration commands

## Important: ThingModel Files (Manual Extraction)

The Java decompilation is useful for older Tuya-local models, but **newer AIOT models (X-series, newer G-series) store their complete DPS definitions in bundled asset files**, not in Java code. The base APK only contains ~150 Java router classes.

The real data lives in `split_install_time_asset_pack.apk`:

| Asset | Content |
|-------|---------|
| `assets/Documents/ThingModel/T*_thing.json` | Complete Thing Model: all properties, actions, events per model |
| `assets/Documents/JavaScript/T*.js` | Per-model JS bundles with protobuf encode/decode and DPS-to-property mapping |
| `assets/accessory/T*_accessory_json.json` | Consumable/accessory definitions per model (in `base.apk`) |

To extract these manually after the Docker run:

```bash
docker compose run --rm --entrypoint bash extractor -c "
  cd /work && mkdir -p bundle_extracted
  unzip -q -o /apk/*.apkm -d bundle_extracted/

  # Thing Model JSONs (the gold mine)
  mkdir -p /output/thing_models
  unzip -o bundle_extracted/split_install_time_asset_pack.apk \
    'assets/Documents/ThingModel/*' -d /tmp/pack
  cp /tmp/pack/assets/Documents/ThingModel/*.json /output/thing_models/

  # Per-model JS bundles
  mkdir -p /output/js_bundles
  unzip -o bundle_extracted/split_install_time_asset_pack.apk \
    'assets/Documents/JavaScript/*' -d /tmp/pack
  cp /tmp/pack/assets/Documents/JavaScript/*.js /output/js_bundles/

  # Accessory definitions
  mkdir -p /output/accessory_models
  unzip -o bundle_extracted/base.apk 'assets/accessory/*' -d /tmp/base
  cp /tmp/base/assets/accessory/*.json /output/accessory_models/

  echo 'Done. Files in /output/{thing_models,js_bundles,accessory_models}/'
"
```

### ThingModel Structure

Each `T*_thing.json` defines the complete device interface:

```json
{
  "properties": [
    {
      "identifier": "ecl_status_battery",
      "access_mode": "R",
      "data_type": {"type": "int", "specs": {"min": 0, "max": 100}}
    }
  ],
  "actions": [
    {
      "identifier": "ecl_start_auto_clean",
      "input_data": [...],
      "output_data": [...]
    }
  ],
  "events": [...]
}
```

### Exploring ThingModel Data

```bash
# List all properties for a model
python3 -c "
import json
with open('output/thing_models/T2351_thing.json') as f:
    data = json.load(f)
print(f'{len(data[\"properties\"])} properties, {len(data[\"actions\"])} actions')
for p in sorted(data['properties'], key=lambda x: x['identifier']):
    dtype = p.get('data_type', {})
    print(f'  {p[\"identifier\"]:55s} {p.get(\"access_mode\",\"?\"):5s} {dtype.get(\"type\",\"\")}')
"

# Cross-model comparison
python3 -c "
import json, glob, os
all_props = {}
for f in sorted(glob.glob('output/thing_models/*.json')):
    model = os.path.basename(f).replace('_thing.json', '')
    data = json.load(open(f))
    for p in data['properties']:
        all_props.setdefault(p['identifier'], []).append(model)
    print(f'{model}: {len(data[\"properties\"]):4d} properties, {len(data[\"actions\"]):4d} actions')
print(f'\nUnique properties across all models: {len(all_props)}')
"
```

### JS Bundle Analysis

The per-model JS bundles (e.g., `T2351.js`) contain the DPS key to Thing Model property mapping. After beautifying with `npx prettier`:

- Search for `this.map={` — the complete DPS key → property mapping
- Search for `controlDevice` — outgoing command encoding
- Search for `deviceStatus` — incoming data decoding

### Results from APK v3.18.1

| Model | Properties | Actions | Series |
|-------|-----------|---------|--------|
| T2265 | 197 | 107 | G-series |
| T2267 | 197 | 107 | L60 |
| T2268 | 197 | 107 | L70 |
| T2275 | 197 | 107 | G-series |
| T2276 | 197 | 117 | X10 Pro Omni |
| T2277 | 197 | 107 | G-series |
| T2278 | 197 | 107 | L-series |
| T2320 | 197 | 107 | X-series |
| T2351 | 254 | 131 | X10 Pro Omni |
| T2352 | 281 | 138 | X-series |
| T2353 | 274 | 138 | X-series |

284 unique properties and 155 unique actions across all models.

Key property categories:
- `ecl_status_*` (41) — battery, state, charging, cleaning_mode, trigger_source, scene info
- `ecl_clean_param_*` (18) — fan_suction, clean_type, clean_extent, mop_mode_level
- `ecl_consumable_*` (30) — filter, brushes, dustbag, mop, dirty water reservoir
- `ecl_station_*` (25) — wash frequency, dry duration, dust collection, water levels
- `ecl_unisetting_*` (31) — pet_mode, poop_avoidance, AI see, smart_follow, child_lock
- `ecl_device_info_*` (31) — hardware/software versions, protocol capabilities

Key actions:
- Cleaning: `ecl_start_auto_clean`, `ecl_start_room_clean`, `ecl_start_zone_clean`, `ecl_start_scene_clean`, `ecl_stop_clean`, `ecl_continue_or_pause`
- Dock: `ecl_start_go_home`, `ecl_start_go_wash`, `ecl_start_dry`, `ecl_start_dust_collection`
- Settings: `ecl_update_clean_param`, `ecl_update_station_setting`, `ecl_toggle_boost_iq`, `ecl_toggle_do_not_disturb`

## Two Protocol Generations

Eufy vacuums use two different protocols:

1. **Tuya local API** (older: 11S, 15C, 30C, G10, G30) — numeric DP IDs (2, 3, 5, 15, 101-122) over Tuya local protocol. The Java decompilation + grep passes target this format.

2. **MQTT + Thing Model** (newer: X10 Pro, X-series, newer G/L-series) — `ecl_*` property identifiers communicated via protobuf over MQTT. The ThingModel JSON files define these completely.

## Requirements

- Docker (or Docker Desktop)
- The eufy Clean APK file (`.apk` or `.apkm` from APKMirror)
