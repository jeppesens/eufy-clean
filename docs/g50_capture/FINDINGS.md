# G50 (T2210) DPS capture findings

Captured live 2026-06-02 against real robot via Docker dev HA. Robot idle/charging on socket.

## Baseline (idle, charging, ~99%)

| DPS | Value | Meaning (hypothesis) | Form |
|---|---|---|---|
| 102 | 1 | **Suction** (0=Quiet,1=Standard,2=Turbo,3=Max) | int scalar |
| 104 | 99 | **Battery %** (app ~100% on charge) | int scalar |
| 107 | `{"en":true,"start_t":"2200","end_t":"0800"}` | **DND** (en + HHMM strings) | JSON |
| 150 | `{"side_brush":6209,"roller_brush":6209,"dust_filter":6209,"mop":0,"roller_brush_cover":6208,"sensors":1355}` | accessory usage counters | JSON |
| 151 | `{"l":[{"e":true,"t":"1400","r":"246","s":2,"f":2,"id":...}]}` | schedule | JSON |
| 154 | 2 | clean-type / mode? (NOT suction) | int scalar |
| 177 | (scalar) | error code | int scalar |
| 109 | 960 | clean stats? | int |
| 110 | 16 | clean stats? | int |
| 111 | 9 | clean stats? | int |
| 138 | 2 | ? | int |
| 135 | 1 | ? | int |
| 170 | `ctg_set_mode2:0` | ? | string |
| 127 | `{"status":"O","cid":551,"sid":551,"version":10}` | ? | JSON |
| 1,2,3,5,15,103,106,108,118,122,136,137,139,142,155,161 | misc | unknown scalars | int/None |

## Confirmed mappings

### Suction = DPS 102 ✅
Toggled Quiet→Standard→Turbo→Max, DPS 102 = 0→1→2→3. Plain int.
Scale: `0=Quiet, 1=Standard, 2=Turbo, 3=Max`.

### BoostIQ = DPS 118 ✅
Toggled off→on, DPS 118 = 0→1. Plain int bool. `0=off, 1=on`.

### Cleaning Mode (path pattern) = DPS 154 ✅
Toggled Arranged→Random→Arranged→Random, DPS 154 = 1→2→1→2. Plain int.
Scale: `1=Arranged, 2=Random`. NOTE: on X10 this DPS is base64 protobuf CleanParam —
on G50 it's a bare int. This is the core decode mismatch.

### Battery = DPS 104 (strong) ✅
Observed 99→98 drifting live while idle on charge. Plain int %.

### DND = DPS 107 ✅
Toggled off→on, then times to 2100-0900. DPS 107 JSON:
`{"en": bool, "start_t": "HHMM", "end_t": "HHMM"}`.

### Child Lock = DPS 139 ✅
Toggled on→off, DPS 139 = 1→0. Plain int bool. `0=off, 1=on`. Baseline 0.

## Summary — G50 target map (all scalar/JSON, NO protobuf)

| Feature | DPS | Form | Scale / shape |
|---|---|---|---|
| Battery % | 104 | int | 0-100 |
| Suction | 102 | int | 0=Quiet 1=Standard 2=Turbo 3=Max |
| BoostIQ | 118 | int bool | 0/1 |
| Cleaning mode (path) | 154 | int | 1=Arranged 2=Random |
| DND | 107 | JSON | {en:bool, start_t:"HHMM", end_t:"HHMM"} |
| Child lock | 139 | int bool | 0/1 |
| Accessories | 150 | JSON | usage counters (see below) |
| Error code | 177 | int | scalar (NOT protobuf on G50) |

### Auto-Return Cleaning = DPS 135 ✅ (app "Cleaning Preference" section)
Toggled off→on, DPS 135 = 0→1. Plain int bool. Canonical Tuya `auto_return`
("when battery low, return to dock; resume at 80%"). Entity named "Auto-Return
Cleaning".

### Accessory reset = DPS 150 JSON {<key>: 0} ✅ (captured via /req; HA verified)
App reset sends e.g. {"150": "{\"sensors\":0}"}. Reset any accessory by writing
DPS 150 with that field zeroed: dust_filter / roller_brush / side_brush / sensors.
Verified live: HA "Reset Side Brush" -> app shows 100% after refresh.

### *** Accessory calibration SOLVED (app data 2026-06-02) ***
Counters in DPS 150 are MINUTES USED. Per-accessory MAX LIFE (hours), from app:
| Accessory | DPS150 key | counter(min) | max(h) | calc remaining | app |
|---|---|---|---|---|---|
| Sensors | sensors | 1355 | 35 | 12.4h / 37% | 13h / 37% ✓ |
| Filter | dust_filter | 6209 | 200 | 96.5h / 48% | 94h / 48% ✓ |
| Side brush | side_brush | 6209 | 250 | 146.5h / 58% | 147h / 58% ✓ |
| Rolling brush | roller_brush | 6209 | 360 | 256.5h / 71% | 257h / 71% ✓ |
% remaining = 1 − used_min / (max_h*60). G50 maxes (35/200/250/360h) DIFFER from
X-series ACCESSORY_MAX_LIFE. Need a G_SERIES_ACCESSORY_MAX_LIFE dict (hours).
roller_brush_cover (6208) = "Brush Guard" (no fixed life, replace 3-6mo). mop=0 (N/A).

### Volume = DPS 111 ✅
Toggled muted/20/70/100/50%, DPS 111 = 0/2/7/10/5. Scale 0-10 = 0-100% in 10% steps.
Baseline 9 = 90% (matched app). New entity opportunity (number/select).

### Language / voice pack (low priority, NOT a target feature)
Language change (English↔Deutsch) did not emit a clear scalar in-window (likely emits
on voice-pack download complete). DPS 127 `{"status":"O"→"F",...,"cid":551}` appears to
track the voice-pack download job. Leave unmapped.

### Activity Log Upload = DPS 142 ✅ (diagnostic, low priority)
Toggled on→off, DPS 142 = 1→0. Plain int bool. Baseline 0.

### Find My Robot = DPS 103 ✅
Start→Stop, DPS 103 = 1→0. Plain int bool. Baseline 0.
NOTE: X10 FIND_ROBOT = DPS 160. G50 uses 103. Plan said find_robot "works" — verify
the existing switch actually drives 103 on G50, not 160.

### *** WORK STATE = DPS 15 — CONFIRMED end-to-end ***
**The G50 sends NO DPS 153 (WorkStatus protobuf) at all.** X10 derives activity from
the WorkStatus proto on 153; G50 has none. State lives in scalar **DPS 15** (+ DPS 5
task flag). Confirmed via a CLEAN run from main screen (no manual pad):
Start→cleaning, Pause→paused, Recharge→returning, dock→charging.

| DPS 15 | Activity | Evidence |
|---|---|---|
| 0, 1 | idle/standby | baseline; after task end |
| 2 | cleaning (active) | auto-clean, stable 15=2/5=1 (no manual pad) |
| 4 | returning (go home) | pressed Recharge → 15=4/5=3 |
| 5 | docked/charging | reached dock, "Charging" → 15=5, 5→0 |
| 7 | paused (resumable) | pressed Pause → 15=7/5=1; also manual-pad idle-between-presses |

| DPS 5 | Task flag |
|---|---|
| 0 | no task / idle |
| 1 | active cleaning |
| 3 | returning |
| 2 | paused (seen run 1) |

GOTCHA: the manual-control screen puts the robot in repeated press-to-move, so DPS 15
flaps 2↔7 there (moving vs paused-between-presses). Ignore manual-pad data for the
state map — the clean main-screen run above is authoritative.
DPS 2 = movement/active echo (toggles 0/1 during motion), not state.

Charging boolean (binary_sensor.g50_charging) = (DPS 15 == 5).
This means the vacuum entity's activity mapping needs a G-series path too (bigger than
the original plan, which assumed state already worked).

### Battery = DPS 104 CONFIRMED ✅
Read 86 at dock; app showed 86%. Direct % int.

### Find My Robot (manual screen) confirmed DPS 103 (see above).

### Clean stats: DPS 109 / 110 — VERIFIED against TWO live runs + app history
- **DPS 109 = cleaning TIME (seconds)**: run1 300 → app 5 min; run2 780 → app 13 min.
- **DPS 110 = cleaning AREA (m²)**: run1 4 → app 43 ft²; run2 3 → app 32 ft².
(Initially mapped backwards from a single run; the 2nd run — 11 min in a small
bathroom, 109 climbing to 780 while 110 stuck at 3 — exposed the swap, and the
app history "32 ft² | 13 min" confirmed it.) cleaning_time uses 109 as-is (seconds),
cleaning_area uses 110 (m²). Error 7002 ("MACHINE PICKED UP") verified on DPS 106
this session by lifting the robot.

### Detangle roller brush = {"153": 1} ✅ (captured via /req; HA button verified)
Write DPS 153 = 1 starts roller-brush detangle. (153 reads as 0 in /res — it's a
write-only command DP on the G50, distinct from its X-series WORK_STATUS meaning.)
Exposed as a "Detangle Roller Brush" button, gated to scalar devices.

### (historical) Detangle roller brush — earlier thought NOT capturable via /res
Pressed twice; ran loudly both times; ZERO change in any received DPS (stayed 15=5/5=0
docked). We only subscribe to the device `/res` state topic, never the app→device `/req`
command topic. One-shot maintenance actions (detangle, and likely empty/wash/dry on
other models) leave no persistent state bit → invisible to capture. Implement as a
BUTTON entity sending an outbound command, derived by analogy with api/commands.py +
verified by live write-test. Cannot be reverse-engineered from this capture method.

### Ecosystem research + architecture decisions (2026-06-02)
- The G50 scalar DPS ARE the canonical **Tuya** robovac schema (validated vs
  `damacus/robovac` which has a `T2210.py`="G50"). Confirmed names: 102=fan_speed,
  103=locate, 104=battery, 107=do_not_disturb, 118=boost_iq, 5=mode, 15=status.
  Canonical also says: 2=start_pause, 3=direction, 101=return_home, 106=error_code.
- **Movement commands (validated, not yet live-tested):** start/pause=DPS 2,
  return_home=DPS 101, direction=DPS 3, mode=DPS 5.
- **Re-verify:** our error DPS (177) vs canonical 106; 135 we called "cleaning
  preference" but canonical = auto_return; suction labels (app showed Quiet/Std/
  Turbo/Max — empirical wins for T2210, but canonical-G is Std/Turbo/Max/Boost_IQ).
- **PR #110** (jeppesens, OPEN) adds a Tuya-CLOUD "legacy" layer (string DPS 15,
  cloud transport) with `api_type` "novel"/"legacy" dispatch. The G50 is a THIRD
  variant: Tuya scalar (INT) over MQTT. We mirror #110's naming/structure but keep
  our own value-shape path. #110's key-presence checkApiType would MISCLASSIFY the
  G50 as novel (G50 reuses DPS 153/154/155/160/177 numbers with scalar values) —
  so we detect by VALUE SHAPE instead (DPS 153/154 int-not-base64 -> scalar).
- **PR base = jeppesens/main** (martijnpoppen is a different TS/Homey codebase).
- DESIGN (implemented): `VacuumState.api_type` ("novel"/"scalar"/"legacy"),
  classified cloud-side by `EufyLogin.checkApiType(dps)` and seeded by the
  coordinator at init. const G_SERIES_* renamed SCALAR_*. Entities/commands gate
  on api_type, not model. No model hardcoding.
- ALIGNMENT: `main` already had `checkApiType` + a per-device `apiType` field
  (dormant #110 groundwork, unconsumed) but its key-presence check MISCLASSIFIED
  the G50 as "novel" (G50 carries protobuf DPS *numbers* 153/154 with int values).
  We fixed `checkApiType` to be value-shape based (returns novel/scalar/legacy via
  utils.is_protobuf_dps_value) and wired its `apiType` through the coordinator —
  reusing the maintainer's mechanism instead of a parallel one. Pionaur's C28
  (T211A) fork work is a protobuf device + findModel MQTT fallback; no overlap.

### Outbound commands — live-tested results (2026-06-02)
WORKING (verified via /req send + /res echo on real robot):
- Suction (102), BoostIQ (118), Child lock (139), Cleaning pattern (154),
  Volume (111), DND (107 JSON). All scalar writes; robot echoes new value.
MOVEMENT — SOLVED ✅ (captured from the app's own /req, then verified from HA):
- **start/clean = {"5": 1}** (DPS 5 work-mode = 1)
- **go home = {"5": 3}** (DPS 5 work-mode = 3)
- **pause = {"122": 1}**
- **resume = {"122": 2}**  (NOT 0 — DPS 122 is multi-valued: 1=pause, 2=resume)
- All four verified live from the HA UI (robot physically started/paused/resumed/
  returned). DPS 2 (Tuya START_PAUSE) and DPS 101 (RETURN_HOME) are ACKed but
  IGNORED by G50 firmware — the app drives DPS 5 + 122 instead.
- METHOD THAT CRACKED IT: temporarily subscribed the MQTT client to the device's
  /req topic (where the app publishes) and read the app's exact command payloads.
  Non-destructive. (Reverted after capture — do not ship the /req subscription.)
- DPS 122 also a /res motion flag (1=stationary). Parser maps 122==1 while
  mid-clean -> activity "paused" so HA reflects pause + offers resume.
- EARLIER GOTCHA (resolved): blind DPS-2 attempts had left the Anker cloud/app on
  a stale "Home Clean" state; using the app's real commands behaves cleanly.

### CAPTURE METHOD LIMITS (important for future sessions)
- Robot pushes FULL DPS dumps periodically (~every 70-84s when idle), plus an immediate
  dump on most state-changing settings toggles. On-change is reliable for persistent
  settings; transient/one-shot actions can be missed between periodic dumps.
- We see ONLY `/res` (device→cloud state). Outbound commands (`/req`) are not observable
  here → command formats must be derived from code + confirmed by write-test.

### Schedule = DPS 151 JSON (partial)
Emits on Save. Structure: `{"l":[ {entry}, ... ]}`, each entry:
`{"e":bool enabled, "t":"HHMM", "r":"<days>", "s":suction 0-3, "f":pattern 1=Arranged/2=Random, "id":unix-ts}`
Confirmed: t (0930=09:30), s (0=Quiet, matches DPS 102 scale), f (1/2 matches DPS 154), e, id.
`r` = SOLVED: concatenated string of day DIGITS, 1=Mon..7=Sun (NOT a bitmask).
  "15"=Mon+Fri, "246"=Tue+Thu+Sat, "134567"=all-but-Tuesday. Verified across 3 saves.
Note: app shows "timed out" on save but device DOES receive it (/res confirms) — app
cloud-ack timeout only, cosmetic.

### Unknown scalars still unmapped (low priority)
Unmapped: **108, 136, 137, 138, 170**. (Everything else observed is in `SCALAR_DPS`.)
- Not in any public Tuya schema: `damacus/robovac`'s `T2210` maps only the basics
  (2,3,5,15,101,102,103,104,106); its base `RobovacCommand` enum is string-keyed with
  no numeric for these.
- `170="ctg_set_mode2:0"` is a command-channel echo (`ctg` = category, `set_mode2`),
  tied to a settings write, not a state — nothing to surface.
- `108, 136, 137, 138` had no observed app control to diff against during capture
  (136/137 sit beside 135/139, so likely sibling setting toggles; 138 read a stable 2).
- Mapping any of these needs another live capture toggling the specific app control
  that drives them. Low value (no user-facing feature gated on them) — left unmapped.
