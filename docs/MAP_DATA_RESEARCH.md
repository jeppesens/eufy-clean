# Map Data Retrieval — Research & Findings

Comprehensive reverse-engineering research into retrieving floor plan map pixel data from AIOT-generation Eufy vacuums (T2351 X10 Pro Omni and similar).

> [!NOTE]
> This research was conducted against a T2351 (X10 Pro Omni) with firmware v3.4.85. Findings apply to all AIOT/MQTT-based Eufy vacuums (X-series, newer G-series) that use the Tuya Thing Model platform. Older Tuya-local models (G30, 11S, etc.) use a different protocol and are not covered here.

## TL;DR

Map pixel data for AIOT devices is **not accessible** through any currently known cloud or local API. The data exists and the protobuf decoding pipeline is fully understood, but all retrieval paths are blocked by Tuya's AIOT permission system. The rendering code is ready — only the data source is missing.

---

## Architecture: How Map Data Flows

```
┌─────────────┐     DPS 170 (MAP_GET_ALL)      ┌────────────┐
│  Eufy App    │ ─────────────────────────────►  │  Vacuum    │
│  (Android)   │                                 │  (T2351)   │
│              │  ◄─── ThingP2P (ICE/STUN) ───  │            │
│              │     MapChannelMsg{CompleteMap}   │            │
└──────┬───────┘                                 └────────────┘
       │
       │  Thing Model Action (protocol 4)
       │  ecl_request_clean_record
       │  ecl_request_clean_record_detail
       ▼
┌─────────────┐
│ Tuya Cloud   │  Returns: clean_record_list with download_url
│ (AIOT)       │  OR inline CleanRecordData with map pixels
└─────────────┘
```

**Map pixel data travels via two paths:**
1. **Real-time**: ThingP2P SDK (ICE/STUN NAT traversal) → `MapChannelMsg{CompleteMap}` with LZ4-compressed SLAM + room partition pixels
2. **Historical**: Thing model action `ecl_request_clean_record_detail` → inline `CleanRecordData` with `stream.Map` + `stream.RoomOutline`

Both paths are blocked for third-party access (see [Blockers](#blockers) below).

---

## What We Know

### Protobuf Data Chain (Complete)

The full decoding pipeline from raw bytes to rendered PNG is understood:

```
CleanRecordData
  ├── stream.Map (field 10)           ← LZ4 compressed, 2-bit SLAM pixels
  │     1 byte = 4 pixels: 0=unknown, 1=obstacle, 2=free, 3=carpet
  ├── stream.RoomOutline (field 11)   ← LZ4 compressed, room partition pixels
  │     1 byte = 1 pixel: low 2 bits = pixel type, high 6 bits = room ID
  ├── stream.RoomParams (field 3)     ← Room names and IDs
  └── p2p.CompleteMap (field 20)      ← Combined format (P2P channel)
        ├── MapPixels map (field 8)
        ├── MapPixels room_outline (field 9)
        └── stream.RoomParams room_params (field 12)
```

Proto files: `clean_record.proto`, `stream.proto`, `p2pdata.proto` (all in `proto/cloud/`)

### DPS Keys Related to Maps

| DPS Key | Name | Proto Type | Direction | Notes |
|---------|------|-----------|-----------|-------|
| "165" | MAP_DATA | UniversalDataResponse / RoomParams | Receive | Room names and IDs only (no pixels) |
| "170" | MAP_EDIT_REQUEST | MapEditRequest / MultiMapsManageRequest | Send | MAP_GET_ALL (method=7) triggers P2P response |
| "172" | MULTI_MAPS_MANAGE | MultiMapsManageResponse | Receive | Confirmation only (no pixel data via MQTT) |

### Thing Model Actions

| Action | Input | Output | Notes |
|--------|-------|--------|-------|
| `ecl_request_clean_record` | string (empty) | `{clean_record_list: [{id, download_url, extend, ...}]}` | List of records with S3 URLs |
| `ecl_request_clean_record_detail` | string (record ID) | `binaryData` (CleanRecordData protobuf) | **Inline map pixels!** |
| `ecl_get_all_map_data` | — | Via P2P only | Sends DPS 170, response via ThingP2P |

### Local Socket (Port 9668)

| Property | Value |
|----------|-------|
| Transport | TLS 1.3 (AES-256-GCM-SHA384) |
| Protocol | Varint-delimited protobuf |
| Purpose | **Pairing verification only** (one-shot) |

**Auth flow:**
1. Client sends `BtAppMsg{GetProductInfo{get: true, remedy_field{distribute_version2: 1}}}` (varint-delimited)
2. Device responds with 12-char ASCII challenge
3. Client sends `SocketVerify{random: challenge, device_sn: "...", user_id: "..."}` (varint-delimited)
4. Device responds with `SocketBroadcast{is_bind: true}` (3 bytes: `020801`)
5. **Connection closes immediately** — no data channel

The `socket.proto` module only defines: `SocketVerify`, `SocketBroadcast`, `SocketTransData{Distribute}`. No map data exchange.

---

## Blockers

### 1. MQTT Protocol 4 (Thing Model Actions) — Silently Dropped

The Eufy cloud MQTT broker (`aiot-mqtt-eu.anker.com:8883`) **only forwards protocol 2 (DPS) messages** to the device. Protocol 4 (thing model actions) are silently dropped — zero responses observed.

Tested formats:
- Eufy wrapper + snake_case (`action_code`, `input_params`)
- Eufy wrapper + camelCase (`actionCode`, `inputParams`)
- Standard TuyaLink format on `tylink/{deviceId}/thing/action/execute`

### 2. AIOT HTTP API — Only 2 Endpoints

The AIOT API at `aiot-clean-api-pr.eufylife.com` only exposes:
- `POST /app/devicerelation/get_device_list`
- `POST /app/devicemanage/get_user_mqtt_info`

Clean record endpoints exist on a Tuya backend behind the AIOT proxy (returns 401 with `token` header instead of 404), but require a Tuya-specific token that cannot be obtained through the Eufy auth flow.

**30+ endpoint variations tested** across `aiot-clean-api-pr.eufylife.com`, `aiot-clean-api-eu.eufylife.com`, `appliances-api-eu.eufylife.com`, `api.eufylife.com`, `home-api.eufylife.com`.

### 3. Tuya Mobile API — PERMISSION_DENIED

Authentication to the Tuya mobile API works with `eh-{eufy_user_id}` as the Tuya UID:
- Token endpoint: `a1.tuyaeu.com/api.json` action `tuya.m.user.uid.token.create`
- Login: `tuya.m.user.uid.password.login` with deterministic AES-derived password
- Session obtained successfully

But the X10 device is in the **AIOT namespace**, not the standard Tuya namespace:
- `tuya.m.device.get` → PERMISSION_DENIED
- `tuya.m.device.media.latest` → PERMISSION_DENIED
- `tuya.m.rtc.session.init` → PERMISSION_DENIED

The upstream eufy-clean project confirms: *"Devices like the X10 are not supported by the Tuya Cloud API"* (see `Login.ts`).

### 4. Tuya IoT Platform (iot.tuya.com) — Incompatible

The "Link Tuya App Account" feature only supports **Tuya Smart** and **Smart Life** apps. EufyHome uses a custom Tuya namespace (`yx5v9uc3ef9wg3v9atje`) that cannot be linked.

### 5. ThingP2P — NAT Traversal via Cloud Signaling

The P2P SDK (`libThingP2PSDK.so`) uses ICE/STUN for NAT traversal. Source paths:
```
C6588_tuya-p2p-sdk/src/ice/src/imm_ice.c
C6588_tuya-p2p-sdk/src/ice/src/imm_stun_auth.c
C6588_tuya-p2p-sdk/src/ice/src/imm_nat_detector.c
C6588_tuya-p2p-sdk/src/ice/src/imm_relay_session.c
```

P2P session setup requires `tuya.m.rtc.session.init` → **PERMISSION_DENIED**.

No static port on the device — only port 53 (DNS) and 9668 (TLS pairing) are open.

---

## Tuya Authentication Details

For anyone continuing this research, here are the working Tuya auth credentials extracted from the Eufy app (via [Rjevski/eufy-clean-local-key-grabber](https://github.com/Rjevski/eufy-clean-local-key-grabber) and upstream [martijnpoppen/eufy-clean](https://github.com/martijnpoppen/eufy-clean)):

| Key | Value |
|-----|-------|
| TUYA_CLIENT_ID | `yx5v9uc3ef9wg3v9atje` |
| APPSECRET | `s8x78u7xwymasd9kqa7a73pjhxqsedaj` |
| BMP_SECRET | `cepev5pfnhua4dkqkdpmnrdxx378mpjr` |
| HMAC_KEY | `A_{BMP_SECRET}_{APPSECRET}` |
| Tuya UID | `eh-{eufy_user_id}` (the `eh-` prefix is critical) |
| Password | AES-128-CBC encrypt of zero-padded UID, then MD5 of uppercase hex |
| Endpoint | `https://a1.tuyaeu.com/api.json` (EU region) |
| Login action | `tuya.m.user.uid.password.login` |

**RSA key length bug**: `math.ceil(n.bit_length() / 8)` — NOT `// 8 + 1`.

---

## APK Analysis (com.eufylife.smarthome 3.18.1)

### Native Libraries

| Library | Size | Purpose |
|---------|------|---------|
| `libThingP2PSDK.so` | 1.6 MB | Tuya P2P SDK (ICE/STUN NAT traversal) |
| `libThingP2PFileTransSDK.so` | 291 KB | P2P file transfer (queryAlbumFile, startDownloadFiles) |
| `libnative-lib.so` | 8.6 MB | Eufy protobuf logic (stripped, no exports) |
| `libMapBeautyJni.so` | 805 KB | Map rendering (CTransformGridMap2D) |

### Proto Namespaces

`libnative-lib.so` contains both `proto.cloud` (V1) and `proto.cloudV2` protobuf descriptors. V2 types include:
- `CleanRecordDesc`, `CleanStatistics`, `MapEditRequest`, `MultiMapsManageRequest`
- `MediaManagerRequest/Response` (with `BindMediaSvc` and `Control.FileInfo{filepath, id}`)
- `DeviceMgrRequest/Response` (with `Control.Method`)

Additional proto files not in the open-source repo:
- `proto/cloud/clean_record_wrap.proto` — debug wrapper with inline desc + data
- `proto/cloudV2/clean_record_v2.proto`
- `proto/cloudV2/media_manager_v2.proto`
- `proto/cloudV2/device_manager_v2.proto`
- `proto/cloudV2/map_manage_v2.proto`

### JS Bundles

- `T2351.js` — Device-specific protobuf encode/decode (beautified: 64K lines). Socket module confirms port 9668 is pairing only.
- `CleanLocalPackage/*.bundle` — Hermes bytecode for Unity 3D map rendering
- `index.android.bundle` — Hermes bytecode loader (730 KB)

---

## Potential Future Approaches

1. **Android Emulator + Frida**: Hook `ThingP2PSDK.connect()` to capture P2P signaling credentials and the ICE/STUN session parameters. Replicate in Python.

2. **Monitor community projects**: [tinytuya](https://github.com/jasonacox/tinytuya), [tuya-vacuum](https://github.com/jaidenlabelle/tuya-vacuum), [bropat/eufy-security-client](https://github.com/bropat/eufy-security-client) for ThingP2P Python implementations.

3. **Reverse ThingP2P signaling**: The SDK uses ICE/STUN with Tuya's signaling servers. If the session parameters can be extracted, a direct P2P connection to the device is possible without the Tuya cloud.

4. **`ecl_map_support_download`**: This RW boolean property exists in the thing model but is not mapped to any DPS key. If it can be set (via protocol 4 or another mechanism), the device might push map data through MQTT DPS instead of P2P.

---

*Research conducted March 2026 on T2351 (X10 Pro Omni), firmware v3.4.85, APK com.eufylife.smarthome 3.18.1.*
