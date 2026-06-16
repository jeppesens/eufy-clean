# Changelog

## [1.11.0] - 2026-06-15
### Added
- **Live floor map camera entity** (`camera.<device>_map`) streams the robot's floor plan in real-time via the MQTT `biz/` topic (protocol-41 map stream). No Tuya developer account or additional credentials needed — works with a standard Eufy account.
  - Map updates automatically during cleaning runs (~7 s refresh); also triggered by any map edit (no-go zones etc.) in the Eufy app
  - **Room-coloured rendering**: rooms are colour-coded from RoomOutline data (MapBackup); the lower 2 sub-type bits are used to distinguish confirmed floor pixels (always room colour) from boundary pixels (lidar-checked), giving clean room interiors while preserving wall/obstacle detail
  - **Correct room ID decoding**: RoomOutline pixel values encode the room ID in the upper 6 bits (`pixel >> 2`); the lower 2 bits are sub-type flags. Previously the raw byte was used as the ID, causing labels to appear in the wrong rooms
  - **Room name labels**: room names from `RoomParams` are rendered at the centroid of each room in a small bitmap font, correctly positioned by accumulating centroids in output pixel space during the Y-flip/scale pass
  - **No-go zones and virtual walls**: forbidden zones (red outlines), ban-mop zones (orange outlines), and virtual walls (red lines) from `RestrictedZone` are rendered as overlays on the map
  - **Status badges**: a coloured badge appears at the top-right of the robot marker when docked — lightning bolt (charging, suppressed at 100% battery), water drop (washing), snowflake-style (drying), dust icon (emptying), cross (station activity)
  - **Dock icon**: gold circle with lightning bolt marks the dock position; robot marker snaps to dock position when docked
  - **Live robot position**: robot marker tracks position (~2 s update rate from DynamicData stream) in two styles — orange with googly eyes (default) or plain black dot (configurable via the integration options)
  - **Cleaning trail**: continuous orange line traces the robot's path for the current clean run. Trail clears on new session start and survives HA restarts
  - **Persistent map**: last known map image and full raw `MapData` (room pixels, room names, zones, RoomOutline geometry) saved to HA storage and restored on restart — room colours and labels are available immediately without needing a map edit or cleaning run
  - Pure-Python implementation — no native LZ4 library or PIL required; fully compatible with HA's Python 3.13+ container environment
- **Vacuum control buttons**: `Start Cleaning`, `Pause`, and `Return to Base` button entities mirror the main controls in the Eufy app and can be used in automations or dashboard cards
- Off-peak charging control: `switch.off_peak_charging` enables/disables the schedule, `time.off_peak_charging_start` and `time.off_peak_charging_end` set the window — all three write to DPS 176 and stay hidden until the device reports it supports the feature
- `number.voice_volume` now appears on novel-protocol devices (X/L/C-series, DPS 161) in addition to scalar devices where it already existed
- `select.voice` lets you pick from 17 language/voice packs on novel-protocol devices (DPS 162): Chinese, English Female/Male, German, Japanese, Spanish, Italian, French, Portuguese (Brazil), Turkish, Russian, Arabic, Korean, Dutch, Polish, Thai, Vietnamese
- Integration title now uses the robot's cloud device name (e.g. "Robovac") instead of the account email address; updated automatically on startup without requiring reconfiguration
- Integration options (gear icon) now include error notifications: toggle desktop (HA bell) on/off, and select a mobile device from a dropdown of discovered Companion App notify services (or type a custom service name) — leave blank to skip mobile alerts
- Map rendering now uses Pillow for significantly faster PNG encoding, scaling, and drawing — benefits low-end hardware (Raspberry Pi etc.); Pillow is auto-installed by HA as a declared dependency
- Map options (gear icon on the integration) now use radio button selectors instead of a text box: map image size (256 / 512 / 1024 / 2048 px) and robot marker style (Googly Eyes / Dot)
- Robot marker is slightly smaller and now renders googly eyes in the default style; the "Dot" style draws a plain dark circle for a cleaner look

### Known Limitations
- **Robot position not shown on first install**: the robot's position only appears on the map after it sends its first pose update (typically when a cleaning run starts or completes). The dock position is learned and persisted after the first docking event, so subsequent restarts show the robot at the dock. There is no MQTT command to request the robot's current position while it is idle in the dock, and no known workaround.

### Fixed
- Dock icon replaced with a gold pixel-art house shape (solid fill, 1 px dark border, centred door opening) — the previous semicircle looked like a cup or charging indicator, especially when placed against a wall
- Status badge (charging lightning bolt, emptying, drying, washing) reduced in size and moved closer to the robot marker so it no longer creates a large yellow halo when the robot is docked
- Charging badge now disappears immediately when battery reaches 100% — previously the map had to be closed and reopened to clear it
- Cleaning trail no longer draws straight through-wall lines during fast-mapping or when pose updates are infrequent — trail segments longer than 2 m (400 map pixels) are skipped rather than connected
- DND and Off-Peak Charging start time entities renamed from "Start" to "Begin" so they sort before the "End" entities on the HA device configuration page
- `sensor.work_mode` no longer resets to "unknown" when the vacuum docks — now retains the last known mode (e.g. "Zone", "Auto") until a new clean starts
- `sensor.cleaning_area` no longer resets to 0 after docking — retains the last run's area until a new clean begins
- Added `sensor.total_cleaning_area`, `sensor.total_cleaning_time`, `sensor.total_cleaning_count` from the `user_total` stats the device already sends (was parsed but never exposed)
- Added `sensor.dock_firmware_version` — dock station firmware version from DPS 169 (was already decoded but ignored)
- `select.clean_room` now shows "None" when idle instead of "unknown", and reflects the active room when a room clean is running
- `select.scene` renamed to "Scene/Task" to cover both Eufy app versions, now shows "None" when idle instead of "unknown"
- Fixed false error in HA logs: clean MQTT disconnect (rc=0) now logged at debug level instead of warning
- `sensor.active_cleaning_target` now shows "None" when idle instead of "unavailable", which better reflects that the sensor is working but has no active target
- Room clean now correctly applies the selected cleaning mode — the `area_clean_param` field in the clean command was previously ignored, causing room/area cleans to always use default settings


