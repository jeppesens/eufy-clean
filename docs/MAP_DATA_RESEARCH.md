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

The full decoding pipeline from raw bytes to rendered PNG is understood and implemented in `map_renderer.py`:

```
CleanRecordData (clean_record.proto)
  ├── stream.Map (field 10)           ← LZ4 compressed, 2-bit SLAM pixels
  │     1 byte = 4 pixels: 0=unknown, 1=obstacle, 2=free, 3=carpet
  ├── stream.RoomOutline (field 11)   ← LZ4 compressed, room partition pixels
  │     1 byte = 1 pixel: low 2 bits = pixel type, high 6 bits = room ID (0-31 valid, 60-63 special)
  ├── stream.RoomParams (field 3)     ← Room names, IDs, smart mode settings
  ├── stream.RestrictedZone (field 1) ← No-go zones
  ├── bytes path_data (field 6)       ← Cleaning path (uncompressed, header: 0xAA 0x03 [4B map_id] [4B releases])
  └── p2p.CompleteMap (field 20)      ← Combined format (P2P channel only)
        ├── MapPixels map (field 8)        ← Same LZ4 format as stream.Map
        ├── MapPixels room_outline (field 9)
        ├── stream.RoomParams room_params (field 12)
        ├── stream.ObstacleInfo obstacles (field 10)
        ├── stream.RestrictedZone restricted_zones (field 11)
        └── uint32 map_width/map_height/releases, Point origin, repeated Pose docks
```

Proto files: `clean_record.proto`, `stream.proto`, `p2pdata.proto`, `multi_maps.proto` (all in `proto/cloud/`)

### DPS Keys Related to Maps

| DPS Key | Name | Proto Type | Direction | Notes |
|---------|------|-----------|-----------|-------|
| "165" | MAP_DATA | UniversalDataResponse / RoomParams | Receive | Room names and IDs only — **no pixels via MQTT** |
| "166" | MAP_STREAM | DebugInfo | Receive | Debug log switch, not map pixels |
| "170" | MAP_EDIT_REQUEST | MapEditRequest / MultiMapsManageRequest | Send | MAP_GET_ALL (method=7) triggers P2P response |
| "172" | MULTI_MAPS_MANAGE | MultiMapsManageResponse | Receive | Confirmation only — pixel data via P2P only |

**Confirmed by live test**: Sending MAP_GET_ALL on DPS 170 via MQTT produces 14 DPS response messages (153, 154, 156, 158, 159, 161, 166, 167, 168, 173, 176, 177) but **no DPS 165 or 170/172 with map data**. The device acknowledges the command but sends pixel data only via P2P.

### DPS-to-Property Mapping (from T2351.js `this.map`)

The T2351.js file defines which thing model properties map to which DPS keys. Map-related:

```javascript
170: { ecl_map_edit_method: "method", ecl_map_edit_seq: "seq",
       ecl_map_edit_result: "result", ecl_map_edit_fail_code: "failCode.value" }
172: { ecl_multi_maps_manage_method: "method", ecl_multi_maps_manage_seq: "seq",
       ecl_multi_maps_manage_result: "result" }
176: { ..., ecl_unisetting_unistate_map_valid: "unistate.mapValid.value",
       ecl_unisetting_unistate_live_map_state_bits: "unistate.liveMap.stateBits", ... }
```

**Not in any DPS mapping** (thing model only, no DPS key):
- `ecl_map_support_download` (bool, RW)
- `ecl_map_type` (int, RW)
- `ecl_map_beauty_project_id`, `ecl_map_beauty_path`, `ecl_map_beauty_furniture`
- `ecl_3d_map_style`

### Thing Model Actions (T2351_thing.json — 131 actions total)

| Action | Input | Output | In controlDevice? | Notes |
|--------|-------|--------|-------------------|-------|
| `ecl_request_clean_record` | string (empty) | `{clean_record_list: [{id, download_url, extend, ...}]}` | **No** | Cloud-side, returns S3 URLs |
| `ecl_request_clean_record_detail` | string (record ID) | `binaryData` (CleanRecordData protobuf) | **No** | **Inline map pixels!** |
| `ecl_get_all_map_data` | — | Triggers DPS 170 | **Yes** (dp="170") | Response via ThingP2P only |
| `ecl_map_channel_connect` | — | — | **Not found in JS** | May initiate P2P stream |
| `ecl_socket_verify` | {random, deviceSn, userId} | — | **Yes** (binaryData, no dp) | Socket pairing only |
| `keepAliveRequest` | {timestamp, forceSync} | — | **Yes** (binaryData, no dp) | Socket keepalive |

> [!IMPORTANT]
> Actions **not in `controlDevice`** (like `ecl_request_clean_record`) are handled entirely by the native Tuya SDK — the JS code only processes the response. These are dispatched as thing model actions (protocol 4) by the native layer.

---

## Local Socket Protocol (Port 9668)

### Discovery

Port scan results from the device LAN:
- **Port 53**: DNS server (resolves queries — captive portal)
- **Port 9668**: TLS 1.3 (AES-256-GCM-SHA384) — pairing socket
- **All other ports closed** (tested 1-100, 443-450, 6660-6670, 8080-8090, 8443-8450, 8880-8890, 9660-9680, 10000-10010, 20000-20010, 34567-34570, 48000-48010, 54321-54325, 55555-55560)

### Raw Protocol (verified)

**Connect:**
```python
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
tls = ctx.wrap_socket(socket.socket(), server_hostname='<device_ip>')
tls.connect(('<device_ip>', 9668))
```

**Step 1 — Client sends GetProductInfo (varint-delimited protobuf):**
```
Raw bytes: 0e 0a0c 0801 1a020801 22040a025345 2801
Decoded:    ^len  ^BtAppMsg{get_product_info{get:true, remedy_field{distribute_version2:1}, country{code:"SE"}, support_ack:true}}
```
Note: `support_ack` (field 5, bool) is NOT in our proto file but IS set by the app. Without it, older firmware may not respond.

**Step 2 — Device responds with 12-char ASCII challenge:**
```
Raw bytes (example): 4d5279626c686d6f784f3930
ASCII:               MRyblhmoxO90
```
This is NOT protobuf-wrapped — raw 12 ASCII bytes.

**Step 3 — Client sends SocketVerify (varint-delimited protobuf):**
```python
verify = SocketVerify(random="MRyblhmoxO90", device_sn="AMP96Y0E44500770",
                      user_id="09936d1d67af16abec2b47a96cbe93db5686c6c8")
tls.sendall(varint_encode(len(raw)) + raw)
```

**Step 4 — Device responds with auth result:**
```
Raw bytes: 02 0801
Decoded:   ^len=2  ^SocketBroadcast{is_bind: true}
```

> [!CAUTION]
> The 3 bytes `020801` decode as BOTH `SocketBroadcast{is_bind: true}` AND `ProductInfo{ret: E_FAIL(1)}`. The T2351.js uses `decodeSocketBroadcastStatus()` for both `ecl_decode_socket_broadcast` and `ecl_decode_socket_verify`, confirming `is_bind=true` is the correct interpretation — this is a **success** response.

**Step 5 — Connection closes immediately.** Every message type sent after auth causes immediate close:
- KeepAliveRequest, MAP_GET_ALL, BtAppMsg.Ack (all types 0-4), BtAppMsg.GetApList
- SocketTransData{E_DP}, AppInfo, raw bytes, JSON, empty bytes
- Tested both varint-delimited and raw formats

The socket.proto module in T2351.js only defines encode/decode for: `SocketVerify`, `SocketBroadcast`, `SocketTransData.Distribute` (WiFi setup), `BtAppMsg.Ack`, `GetProductInfo` variants. **No map data functions.**

---

## Blockers

### 1. MQTT Protocol 4 (Thing Model Actions) — Silently Dropped

The Eufy cloud MQTT broker (`aiot-mqtt-eu.anker.com:8883`) **only forwards protocol 2 (DPS) messages**. Protocol 4 (thing model actions) are silently dropped — zero responses after 15s wait.

**MQTT message format (protocol 2 — works):**
```json
{
  "head": { "client_id": "...", "cmd": 65537, "cmd_status": 2, ... },
  "payload": "{\"account_id\":\"...\",\"data\":{\"170\":\"AggH\"},\"device_sn\":\"...\",\"protocol\":2,\"t\":...}"
}
```

**MQTT message format (protocol 4 — silently dropped):**
```json
{
  "head": { "client_id": "...", "cmd": 65537, "cmd_status": 2, ... },
  "payload": "{\"account_id\":\"...\",\"data\":{\"action_code\":\"ecl_request_clean_record\",\"input_params\":\"\"},\"device_sn\":\"...\",\"protocol\":4,\"t\":...}"
}
```

Tested variations: snake_case fields, camelCase fields (`actionCode`/`inputParams`), TuyaLink topic (`tylink/{deviceId}/thing/action/execute`), with/without `pv` field, with/without `msgId`.

### 2. AIOT HTTP API — Only 2 Endpoints Exist

Base URL: `https://aiot-clean-api-pr.eufylife.com`

**Working endpoints:**
```
POST /app/devicerelation/get_device_list   (headers: x-auth-token + gtoken)
POST /app/devicemanage/get_user_mqtt_info  (headers: x-auth-token + gtoken)
```

**Key discovery about routing:** The AIOT server has two auth routing layers:
- `x-auth-token` header → AIOT routes → 404 for unknown paths
- `token` header (without x-auth-token) → Tuya backend → **401 "token error"** for ALL `/app/devicemanage/*` paths

The 401 (not 404) confirms the clean record endpoint **exists** on the Tuya backend but requires a Tuya-specific token we cannot obtain.

**Tested 30+ endpoint variations:**
```
POST /app/devicemanage/get_clean_record_list  → 404 (AIOT) / 401 (Tuya backend)
POST /app/cleanrecord/get_list                → 404
POST /app/sweeper/get_clean_record            → 404
POST /app/device/get_clean_record             → 404
POST /app/devicemanage/thing_model_action     → 404
POST /app/thing/action/execute                → 404
POST /v1/device/clean_record/list             → 404
GET  /v1/device/{sn}/clean_records            → 404
```

Also tested: `appliances-api-eu.eufylife.com` (alternate V1 host, same result), `aiot-clean-api-eu.eufylife.com` (EU variant, same result).

### 3. Tuya Mobile API — PERMISSION_DENIED

**Working Tuya auth flow** (Python):
```python
# 1. Get token
treq(base, "tuya.m.user.uid.token.create",
     data={"uid": f"eh-{eufy_user_id}", "countryCode": "EU"})

# 2. Derive password
padded = f"eh-{uid}".zfill(16 * math.ceil(len(f"eh-{uid}") / 16))
encrypted = AES_CBC_128(key=PW_KEY, iv=PW_IV).update(padded.encode())  # NO finalize()!
password = md5(encrypted.hex().upper().encode()).hexdigest()

# 3. RSA encrypt password (key from token response)
rsa_encrypted = pow(int.from_bytes(password.encode(), "big"),
                    int(token["exponent"]), int(token["publicKey"]))
# Key length: math.ceil(n.bit_length() / 8)  — NOT //8+1

# 4. Login
treq(base, "tuya.m.user.uid.password.login",
     data={"uid": f"eh-{uid}", "createGroup": True, "ifencrypt": 1,
           "passwd": rsa_encrypted.hex(), "countryCode": "EU",
           "options": '{"group": 1}', "token": token["token"]})
# → Returns: {sid: "...", domain: {mobileApiUrl: "https://a1.tuyaeu.com"}}
```

**Session works, but device access blocked:**
```
tuya.m.device.get               → PERMISSION_DENIED
tuya.m.device.media.latest v2.0 → PERMISSION_DENIED (correct params: {devId, start:"0", size:"5"})
tuya.m.device.media.detail v2.0 → PERMISSION_DENIED (correct params: {devId, gwId, subRecordId, start, size})
tuya.m.rtc.session.init         → PERMISSION_DENIED (P2P session setup)
tuya.m.ipc.config.get           → PERMISSION_DENIED
tuya.m.device.dp.publish        → PERMISSION_DENIED
s.m.dev.dp.get                  → PERMISSION_DENIED
```

The device exists in Tuya's system (PERMISSION_DENIED, not NOT_FOUND) but is in the **AIOT namespace**, not our `eh-` session's scope. The upstream `martijnpoppen/eufy-clean` project confirms in `Login.ts`:
```typescript
// Devices like the X10 are not supported by the Tuya Cloud API
```

### 4. Tuya IoT Platform (iot.tuya.com) — Incompatible

The "Link Tuya App Account" QR code scan only works with **Tuya Smart** and **Smart Life** apps. EufyHome uses a custom Tuya namespace (`yx5v9uc3ef9wg3v9atje`) that cannot be linked to a Tuya developer project.

### 5. ThingP2P — NAT Traversal via Cloud Signaling

The P2P SDK (`libThingP2PSDK.so`) uses ICE/STUN for NAT traversal:
```
Build: C6588_tuya-p2p-sdk/src/ice/src/
Files: imm_ice.c, imm_stun_auth.c, imm_stun_session.c,
       imm_nat_detector.c, imm_relay_session.c, imm_frame.c
```

P2P session setup requires `tuya.m.rtc.session.init` → **PERMISSION_DENIED**.

`libThingP2PFileTransSDK.so` JNI exports:
```
initP2pFileTransSDK, createP2pFileTransfer, connect, disconnect,
queryAlbumFile, startDownloadFiles, startGetFilesStream,
appendDownloadFile, cancelUpDownloadFile, deleteAlbumFile,
getSessionId, setSessionId, getSDKVersion
```

No static port on the device — the P2P connection is dynamically negotiated through the cloud signaling server.

---

## Tuya Authentication Details

For anyone continuing this research, here are the working Tuya auth credentials extracted from the Eufy app (via [Rjevski/eufy-clean-local-key-grabber](https://github.com/Rjevski/eufy-clean-local-key-grabber) and upstream [martijnpoppen/eufy-clean](https://github.com/martijnpoppen/eufy-clean)):

| Key | Value |
|-----|-------|
| TUYA_CLIENT_ID | `yx5v9uc3ef9wg3v9atje` |
| APPSECRET | `s8x78u7xwymasd9kqa7a73pjhxqsedaj` |
| BMP_SECRET | `cepev5pfnhua4dkqkdpmnrdxx378mpjr` |
| EUFY_HMAC_KEY | `A_cepev5pfnhua4dkqkdpmnrdxx378mpjr_s8x78u7xwymasd9kqa7a73pjhxqsedaj` |
| Tuya UID format | `eh-{eufy_user_id}` (**the `eh-` prefix is critical** — without it, login works but devices are empty) |
| Password derivation | AES-128-CBC encrypt zero-padded UID → hex uppercase → MD5 hexdigest |
| AES Key | `[36, 78, 109, 138, 86, 172, 135, 145, 36, 67, 45, 139, 108, 188, 162, 196]` |
| AES IV | `[119, 36, 86, 242, 167, 102, 76, 243, 57, 44, 53, 151, 233, 62, 87, 71]` |
| API endpoint | `https://a1.tuyaeu.com/api.json` (EU region) |
| Token action | `tuya.m.user.uid.token.create` |
| Login action | `tuya.m.user.uid.password.login` (NOT `.login.reg`) |
| HMAC signing | Sort query params, filter to `SIGNATURE_RELEVANT_PARAMETERS`, join with `||`, HMAC-SHA256 with EUFY_HMAC_KEY |

**Critical implementation notes:**
- RSA key length: `math.ceil(n.bit_length() / 8)` — NOT `// 8 + 1` (off-by-one produces wrong ciphertext)
- AES password: use `encryptor.update()` only — do NOT call `encryptor.finalize()` (extra PKCS7 padding block changes the hash)
- The `shuffled_md5` for postData signing: `hash[8:16] + hash[0:8] + hash[24:32] + hash[16:24]`

---

## APK Analysis (com.eufylife.smarthome 3.18.1)

### Extracting from APK

The APK is an `.apkm` bundle (ZIP containing `base.apk` + split APKs). Use the `eufy-dps-extractor/` Docker tooling or manually:
```bash
unzip eufy.apkm -d extracted/
# base.apk (139MB) — main code
# split_config.arm64_v8a.apk (53MB) — native .so libs (114 files)
# split_install_time_asset_pack.apk (129MB) — JS bundles, thing models, assets
```

### Native Libraries (split_config.arm64_v8a.apk)

| Library | Size | Purpose | Exports |
|---------|------|---------|---------|
| `libThingP2PSDK.so` | 1.6 MB | Tuya P2P SDK (ICE/STUN NAT traversal) | ThingP2PInit, ThingP2PConnect/v2/v3, ThingP2PSendData, ThingP2PRecvData, ThingP2PSetSignaling, ThingP2PSetHttpResult |
| `libThingP2PFileTransSDK.so` | 291 KB | P2P file transfer | queryAlbumFile, startDownloadFiles, startGetFilesStream |
| `libnative-lib.so` | 8.6 MB | Eufy protobuf logic | **Stripped** — no dynamic symbol table, no JNI exports. Contains `eufyprotibufutils`, `DeviceBaseLogic`, `parseProtoStream`, `CoverageRemoveP2pOutFw` as internal symbols |
| `libMapBeautyJni.so` | 805 KB | Map rendering (C++) | `GetMap2DForDevice`, `CTransformGridMap2D` — grid map manipulation, room ID extraction, downsampling |
| `libnetwork-android.so` | — | Socket management | `create_socket_connection`, `CreateSocket2` |

### Proto Namespaces in libnative-lib.so

Contains both `proto.cloud` (V1) and `proto.cloudV2` protobuf descriptors.

**V2 proto files referenced (NOT in the open-source repo):**
```
proto/cloudV2/clean_record_v2.proto
proto/cloudV2/clean_record_wrap_v2.proto
proto/cloudV2/media_manager_v2.proto
proto/cloudV2/device_manager_v2.proto
proto/cloudV2/map_manage_v2.proto
proto/cloudV2/multi_maps_v2.proto
proto/cloudV2/work_status_v2.proto
proto/cloudV2/clean_param_v2.proto
proto/cloudV2/clean_statistics_v2.proto
proto/cloudV2/unisetting_v2.proto
proto/cloudV2/undisturbed_v2.proto
proto/cloudV2/keepalive_v2.proto
proto/cloudV2/stream_wrap_v2.proto
proto/cloudV2/app_device_info_v2.proto
proto/cloudV2/video_manager_v2.proto
proto/cloudV2/error_code_v2.proto
proto/cloudV2/consumable_v2.proto
```

**V2 message types of interest:**
```
proto.cloudV2.MediaManagerRequest.Control{Method: RECORD_START/RECORD_STOP/CAPTURE}
proto.cloudV2.MediaManagerResponse.Control.FileInfo{filepath, id}
proto.cloudV2.MediaManagerRequest.BindMediaSvc{seq, c, d, g, j, user_account}
proto.cloudV2.DeviceMgrRequest.Control{Method}
proto.cloudV2.DeviceMgrResponse.Control{Result}
proto.cloudV2.DeviceMgrSetting
proto.cloudV2.MultiMapsManageResponse.CompleteMaps  (same as V1)
```

### JS Bundles (split_install_time_asset_pack.apk)

| File | Size | Format | Content |
|------|------|--------|---------|
| `assets/Documents/JavaScript/T2351.js` | 1.4 MB | Minified JS (beautifiable with prettier) | Device-specific protobuf encode/decode, DPS-to-property mapping, controlDevice/deviceStatus handlers |
| `assets/Documents/ThingModel/T2351_thing.json` | 182 KB | JSON | Thing model definition: 131 actions, properties, events |
| `assets/yoo/CleanLocalPackage/*.bundle` | ~100 bundles | Hermes bytecode | Unity 3D map rendering components (cannot be decompiled without hermes-dec) |
| `assets/index.android.bundle` | 730 KB | Hermes bytecode v94 | React Native loader (no relevant strings) |

### T2351.js Analysis Methodology

The T2351.js file is the key to understanding the device protocol. After beautifying with `npx prettier`:

1. **DPS mapping**: Search for `this.map={` — contains the complete DPS key → thing model property mapping
2. **Outgoing commands**: `controlDevice()` switch — shows which actions encode protobuf on which DPS keys
3. **Incoming data**: `deviceStatus()` switch — shows how DPS and thing model responses are decoded
4. **Socket protocol**: Module 40 (`"../protobuf/socket"`) — `encodeSocketVerify`, `decodeSocketBroadcastStatus`
5. **Protobuf encoding**: Module 27 (`"../protobuf/ble"`) — `getX10AIotProductInfo`, `getAckData`, `encodeSocketVerify`

Key insight: Actions in `controlDevice` that set `r.dp = "NNN"` are DPS commands (protocol 2). Actions that only set `r.binaryData` without `r.dp` are socket/BLE commands. Actions NOT in `controlDevice` at all (like `ecl_request_clean_record`) are thing model actions handled by the native Tuya SDK.

### Java Classes (from jadx decompile — heavily obfuscated, only router code visible)

Key Android router paths:
```
/cleanrecords/clean_records_list_path → CleaningRecordsListActivity (params: deviceId)
/cleanrecords/clean_records_detail_path → CleaningRecordsDetailActivity (params: deviceId, clean_record_data)
/clean_rn_bridge/route → Rn2NativeRouteImpl
/clean_rn_bridge/route_native_support → RNNativeSupportImpl
/clean_rn_bridge/tuya_settings_support → TuyaSettingsSupportImpl
/tuya/TuyaProvider/path → TuyaProviderIml
/map_operate/mopping/map_manager → MapManagerActivity (params: deviceId, map_id)
```

---

## Potential Future Approaches

1. **Android Emulator + Frida**: Hook `ThingP2PSDK.connect()` and `ThingP2PSetSignaling()` to capture the ICE/STUN session credentials. Then replicate the P2P handshake in Python. Target classes: `com.thingclips.smart.p2p.p2psdk.ThingP2PSDK` (JNI), `com.thingclips.smart.p2pfiletrans.jni.ThingP2pFileTransSDKJni`.

2. **Ghidra analysis of libnative-lib.so**: The binary is stripped but still contains string references and protobuf descriptor tables. Focus on `DeviceBaseLogic`, `parseProtoStream`, and cross-references to `CleanRecordData` and `MapChannelMsg` to trace the data flow from P2P receive to JS callback.

3. **Monitor community projects**: [tinytuya](https://github.com/jasonacox/tinytuya) (has some P2P support), [tuya-vacuum](https://github.com/jaidenlabelle/tuya-vacuum) (cloud API maps), [bropat/eufy-security-client](https://github.com/bropat/eufy-security-client) (P2P for cameras — similar SDK).

4. **Reverse ThingP2P signaling**: The SDK uses ICE/STUN with Tuya's signaling servers. The `ThingP2PSetSignaling()` function takes signaling data from the Tuya mobile API (`tuya.m.rtc.session.init`). If this can be captured (via Frida or MITM), the signaling parameters could be replayed to establish a direct P2P connection.

5. **`ecl_map_support_download`**: This RW boolean property exists in the thing model but is not mapped to any DPS key. If it can be set (via protocol 4 or another mechanism), the device might push map data through MQTT DPS instead of P2P. Could test by sending it as a `setProperty` thing model action if protocol 4 ever becomes available.

6. **V2 proto extraction**: Use `protoc --decode_raw` on the binary protobuf descriptors embedded in `libnative-lib.so` to reconstruct the V2 proto files. The string table contains full field names and type paths.

---

## Existing Code (Ready for Data)

The following code exists in this repo and is ready to render map images as soon as data becomes available:

| File | Purpose |
|------|---------|
| `map_renderer.py` | Full rendering pipeline: LZ4 decompressor, pixel decoders, PNG renderer with room colors, robot/dock overlays, room name labels |
| `api/local.py` | TLS socket client for port 9668 (auth works, no data channel) |
| `api/commands.py` | `build_get_map_command()` for DPS 170 MAP_GET_ALL |
| `camera.py` | HA camera entity that displays the rendered map PNG |
| `proto/cloud/clean_record.proto` | CleanRecordData with Map + RoomOutline + CompleteMap |
| `proto/cloud/p2pdata.proto` | MapChannelMsg, CompleteMap, MapPixels, MapInfo |
| `proto/cloud/multi_maps.proto` | MultiMapsManageRequest/Response with CompleteMaps |

---

*Research conducted March 2026 on T2351 (X10 Pro Omni), firmware v3.4.85, APK com.eufylife.smarthome 3.18.1.*
