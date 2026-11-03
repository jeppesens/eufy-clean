# The encrypted P2P map channel

On Tuya-transport robots (`mqtt=False`, e.g. Eufy S1 Pro / T2080A) the map, the
**room list with names**, obstacles, live position and current target are not on
any DPS and never reach the `biz/` MQTT stream. The app reads them over a local,
encrypted Tuya **P2P** channel. A client can open that channel itself on the LAN
with only the device local key.

> [!NOTE]
> Verified end to end on an **Eufy S1 Pro (T2080A), fw 7.0.170**, local Tuya
> (protocol 3.3). Protobuf schemas are already bundled in
> `custom_components/robovac_mqtt/proto/cloud/`.

## Why P2P is the only source

| Source | On this device |
| --- | --- |
| DPS 165 `MAP_DATA` (`RoomParams`) | Not emitted (a full `DP_QUERY` returns only small legacy DPS) |
| MQTT `biz/` (plaintext protobuf) | Never published: the device is not MQTT-connected (issue #131) |
| P2P | The only channel that carries rooms |

## Transport

```
TCP 6668, Tuya protocol 3.3 (frames encrypted with the local key)
  command type 32 = signaling: SDP offer/answer + ICE candidates
    the SDP carries  a=aes-key:<32 hex>  = the session key, CHOSEN BY THE OFFERER

UDP on the LAN, client <-> device
  STUN/ICE (short-term creds), then KCP segments
    conv 0 = control (auth + subscribe)
    conv 5 = map (device pushes it)
```

Two layers: the Tuya local layer protects the type-32 signaling (so `a=aes-key`
is readable); the P2P layer (AES-128-CBC with that key) protects the UDP media.

> [!NOTE]
> Type-32 frames have **no** "3.3" extended header, unlike DP writes. Encrypt the
> payload without it, or the device answers `"parse data error"`.

## KCP segment and the integrity tag

```
[ header(24) ] [ data = IV(16) | AES-CBC ciphertext ] [ HMAC-SHA1(media_key, header+data) = 20 bytes ]
               \_______ KCP len bytes ______________/
```

- `media_key` = the session AES key. The tag covers the whole segment.
- The device silently drops any data segment with a missing or wrong tag: `una`
  never advances, nothing comes back.
- ACKs (`cmd 0x52`, `len 0`, 24 bytes) carry no tag.
- KCP `len` **includes** the 16-byte IV, so `ciphertext = len - 16`. Read `len`
  as ciphertext-only and the last block decrypts to garbage and 4 bytes look like
  a trailer. There is no 4-byte trailer.

Header, little-endian: `conv u32 | cmd u8 | frg u8 | wnd u16 | ts u32 | sn u32 |
una u32 | len u32`. `cmd`: `0x51` PUSH, `0x52` ACK.

> [!NOTE]
> Same framing as the PyPI package
> [`tuya-ipc-p2p-sdk`](https://pypi.org/project/tuya-ipc-p2p-sdk/)
> (`transport/relay_framing.py`, `crypto.py`). It targets the TCP relay; the
> direct-LAN payload is the `segment | tag` above, no `f6` wrapper.

## Control channel (conv 0)

The client sends a burst of KCP PUSH records. The first is the auth packet:

```
magic u32 = 0x12345678 | type u32 = 1 | username[32]="admin" | credential[32] | reserved[32]
credential = md5_hex(f"{device_password}||{local_key}")
```

`device_password` is the `password` field of the Tuya RTC config
(`m.ipc.v4.rtc.config.get`); it is stable per device. After auth, a fixed set of
control commands follows; the device answers on conv 0, then streams conv 5.
Reference: `control.py` in `tuya-ipc-p2p-sdk`.

## Map channel (conv 5)

The conv-5 stream is chunks: an 80-byte header then payload. Header fields
(little-endian): const `1`, const `1000`, session counter (u16 @8), chunk index
(u32 @12), stream name (48 bytes @20, e.g. `map.bin.stream`), payload len (@68),
total len (@72), single-chunk flag (@76). Concatenate chunk payloads of one
stream name up to `total`. Each `map.bin.stream` object is a length-delimited
`MapChannelMsg`, keyed by `map_info.msg_type`:

| `msg_type` | Field | Content |
| --- | --- | --- |
| `MAP_ROOMOUTLINE` | `pixels` | LZ4 room bitmap |
| `ROOM_PARAMS` | `room_params` | **Room list**: `rooms[]` with `id`, `name`, `custom` |
| `OBSTACLE_INFO` | `obstacles` | Objects + coordinates |
| `RESTRICT_ZONES` | `restricted_zones` | Virtual walls / no-go |
| `TEMPORARY_DATA` | `temporary_data` | Current selection (`select_rooms_clean`) |

`ROOM_PARAMS.map_id` is the **local** map id (small saved-map index, `1` for the
first map), the id the firmware accepts in room-clean commands.

## Initiation recipe

1. Open TCP 6668, protocol 3.3, local key.
2. Generate the AES media key, ICE ufrag/pwd, a `sessionid`/`trace_id`.
3. Send a type-32 **offer** (no 3.3 header): our SDP (`a=aes-key`, `path:lan`),
   `msg` with `token`/`tcp_token`/`log` (synthetic is fine on the LAN). The device
   answers and echoes our key.
4. Send a type-32 **candidate** with our host candidate. The device sends its own.
5. **ICE**: answer the device's STUN binds (Binding Success + XOR-MAPPED +
   MESSAGE-INTEGRITY keyed by *our* ice-pwd + FINGERPRINT), send ours (integrity
   keyed by the *device* ice-pwd) with USE-CANDIDATE.
6. Send the **conv-0** burst (tagged PUSH), starting with the auth packet.
7. ACK the device's conv-5 PUSH. Reassemble by sn, decrypt each record, split into
   chunks, decode `MapChannelMsg`. `ROOM_PARAMS` gives the rooms.

## Security

Trusted-LAN only, like the rest of the local Tuya transport. The local key and
`device_password` are secrets; never log them. Opening the session is what the
app does on its map view; it does not move the robot.

## What this unlocks

For `mqtt=False` devices, none of this is otherwise reachable without the app:
room list with names, live map image, live position/path, obstacles, restricted
zones, and the robot-side current target (`TEMPORARY_DATA`). All local, no cloud.
Room *cleaning* already works over local DPS and does not need this channel.
