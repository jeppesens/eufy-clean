# The encrypted P2P map channel

On Tuya-transport robots (`mqtt=False`, e.g. Eufy S1 Pro / T2080A) the map, the
**room list with names**, obstacles, restricted zones, the cleaning path, the
live pose and the current target are on no DPS and never reach the `biz/` MQTT
stream. The app reads them over a local, encrypted Tuya **P2P** channel. A
client can open that channel itself on the LAN with the device local key and
the per-device P2P password from Tuya Cloud.

> [!NOTE]
> Verified end to end on an **Eufy S1 Pro (T2080A)**, fw 7.0.168 and 7.0.170,
> local Tuya (protocol 3.3). Protobuf schemas are already bundled in
> `custom_components/robovac_mqtt/proto/cloud/`.

Code: `custom_components/robovac_mqtt/api/p2p/` (transport and decoding) and
`custom_components/robovac_mqtt/p2p_map.py` (supervision in Home Assistant).

## Why P2P is the only source

| Source | On this device |
| --- | --- |
| DPS 165 `MAP_DATA` (`RoomParams`) | Not emitted (165 is `reserved1` in the Tuya schema) |
| MQTT `biz/` (plaintext protobuf) | Never published: the device is not MQTT-connected (issue #131) |
| P2P | The only channel that carries the map, rooms and path |

## Transport

```
TCP 6668, Tuya protocol 3.3 (frames encrypted with the local key)
  command type 32 = signaling: SDP offer/answer + ICE candidates
    the SDP carries  a=aes-key:<32 hex>  = the reserved cloud session media key

UDP on the LAN, client <-> device
  STUN/ICE (short-term creds), then KCP segments
    conv 0 = control (auth + subscribe)
    conv 5 = file streams (map, path, pose)
```

Two layers: the Tuya local layer protects the type-32 signaling (so `a=aes-key`
is readable); the P2P layer (AES-128-CBC with that key) protects the UDP media.

> [!NOTE]
> Type-32 frames have **no** "3.3" extended header, unlike DP writes. Encrypt the
> payload without it, or the device answers `"parse data error"`.

The robot accepts about three concurrent local TCP connections. The integration
uses two (DP control and P2P signaling), leaving one for the phone app.

## ICE

The device runs a normal ICE agent. Answer its binding requests (Binding Success
+ XOR-MAPPED-ADDRESS + MESSAGE-INTEGRITY keyed by *our* ice-pwd + FINGERPRINT)
and send our own (USERNAME `remote:local`, PRIORITY, ICE-CONTROLLING,
USE-CANDIDATE, integrity keyed by the *device* ice-pwd).

> [!IMPORTANT]
> ICE-CONTROLLING is attribute **`0x802A`** (RFC 8445). Sent as `0x002A` (a
> comprehension-required code) the device rejects every check with
> `420 Unknown Attribute`; the session still opens off the device's own checks
> but consent is never refreshed. Refresh consent every few seconds.

## KCP segments and the integrity tag

```
[ header(24) ] [ data = part of IV(16) | AES-CBC ciphertext ] [ HMAC-SHA1(media_key, header+data) = 20 bytes ]
```

Header, little-endian: `conv u32 | cmd u8 | frg u8 | wnd u16 | ts u32 | sn u32 |
una u32 | len u32`. `cmd`: `0x51` PUSH, `0x52` ACK, `0x53`/`0x54` window ask/tell.

- One KCP **message** is one encrypted record, `IV | AES-CBC(PKCS#7(plain))`.
  A record longer than a segment is split across segments with `frg` counting
  down to 0; rejoin before decrypting. `len` counts the segment's share of the
  record, IV included; there is no trailer.
- **Every segment we send carries the tag, ACKs included.** Data segments from
  the device carry it; the device's ACKs do not. An untagged ACK is silently
  ignored, so the device never retires its 32-segment send window and stalls
  after the first window (the old symptom: the path stops part-way).

## Control channel (conv 0)

Every conversation-0 message is `magic u32 = 0x12345678 | type u32 | flag u32 |
sub u32 | len u32 | payload[len]`, except the auth packet:

```
magic | type u32 = 0 | username[32]="admin" | credential[32] | reserved[32]
credential = md5_hex(f"{device_password}||{local_key}")
```

`device_password` is the `password` field of the Tuya RTC config
(`m.ipc.v4.rtc.config.get`); it is stable per device. After auth:

| Packet | type / sub | Payload | Device reply |
| --- | --- | --- | --- |
| Hello / album query | `2` / `0x000c0064` | album `ipc_sweeper_robot` | the album's file list (`map.bin`, `cleanPath.bin`, `*.stream`) |
| Subscribe | `0x00010003` / `0x000d0064` | conv 5, album, 3 stream names | `5, 1` (streaming on conv 5) |

> [!IMPORTANT]
> The app follows these with a type-4 download-control packet. **Do not send it**:
> it stops the transfer mid-file.

## File streams (conv 5)

Chunks: an 80-byte header then payload. Header fields, little-endian: const `1`
(@0), const `1000` (@4), session counter (u16 @8), chunk index (u32 @12),
stream name (48 bytes @20), payload length (@68), object total length (@72),
last-chunk flag (@76). Join chunks of one stream name up to `total`; records and
chunks do not align, so reassemble from the byte stream.

| Stream | Object | Content |
| --- | --- | --- |
| `map.bin.stream` | length-delimited `MapChannelMsg` | one map aspect, keyed by `map_info.msg_type` (below) |
| `cleanPath.bin.stream` | length-delimited `CompletePath` | LZ4-compressed path points |
| `navPath.bin` / `navPath.bin.stream` | length-delimited `DynamicData` | the current pose (`cur_pose`, cm and rad × 100) |

`MapChannelMsg` aspects (each also carries map id, size, origin and docks):

| `msg_type` | Field | Content |
| --- | --- | --- |
| `MAP_ROOMOUTLINE` | `pixels` | LZ4 bitmap, 1 byte/px: room id << 2 \| pixel type. Room ids 0-31 (0 is a real room); 60 no room, 61 gap, 62 obstacle, 63 unknown. The S1 Pro sends no `MAP_REALTIME`, so this is the map. |
| `ROOM_PARAMS` | `room_params` | **Room list**: `rooms[]` with `id`, `name`, `order`, `custom` |
| `OBSTACLE_INFO` | `obstacles` | Recognised objects (type, points, photo id) |
| `RESTRICT_ZONES` | `restricted_zones` | Virtual walls, no-go and no-mop zones |
| `TEMPORARY_DATA` | `temporary_data` | The current target (`select_rooms_clean`, zones, goto) |

`ROOM_PARAMS.map_id` is the **local** map id (`1` for the first saved map), the
id the firmware accepts in room-clean commands.

Path points are 5 bytes: `x i16 BE | y i16 BE | flags` (cm). Flags low nibble:
0 sweep, 1 mop, 2 sweep+mop, 3 navigate, 4 go home; bit 4 starts a new line.

## Session behaviour

- On subscribe the device sends every map aspect, then the whole path so far,
  then the pose. While it is moving it re-sends the map set, a path increment
  and the pose every ~2 s for as long as the session stays open. An empty path
  object means a new clean started.
- After ~15 s with nothing to send (docked), the device ends the session with a
  type-32 `disconnect` (`close_reason 6`). This is normal: reconnect when the
  robot starts moving, and refresh occasionally while it rests.
- Keep the Tuya socket alive with heartbeats (command 9) while the session runs.

## Initiation recipe

1. Open TCP 6668, protocol 3.3, local key.
2. Fetch a fresh RTC config and adopt its reserved AES key, ICE credentials,
   session id, trace id and uid. Reject malformed identities instead of generating
   a local replacement.
3. Send a type-32 **offer** (no 3.3 header): our SDP (`a=aes-key`, `path:lan`),
   `msg` with `token`/`tcp_token`/`log` from the RTC config. The device answers
   and echoes our key.
4. Send a type-32 **candidate** with our host candidate. The device sends its own.
5. **ICE** as above; once connected, send the conv-0 auth + hello + subscribe.
6. ACK every conv-5 PUSH (tagged), reassemble records by `sn`/`frg`, decrypt,
   split into chunks, decode the objects.

## Robot camera (S1 Pro)

The camera uses conversation 1 for RTP/H.265. Enable it physically on the robot
first, then enter manual control (`WorkStatus.state == 6`). Home Assistant maps
that state to activity `cleaning`, so camera availability must use the raw state.
Viewing the camera does not enter or exit manual control. Leaving manual control
ends the stream and stops cached frames from being returned.

The DP 181 state-set request needs
`setting{mgrState{passEn: Switch{value: true}}}`. An extra message wrapper is
acknowledged successfully but leaves `passEn` false. After authenticating the P2P
control channel, set `passEn`, send `StreamOpen`, then send the video-start burst.
A failed stream-open acknowledgement is advisory; the proven HD start still runs.
The HD burst is sent once. Alternative startup sequences were tried and
discarded (see below). The session has a 30-second startup
allowance, and decoded-frame gaps are limited to ten seconds. Expired frames are
not returned while a session is recovering.

Use HD clarity (`IOCtrl` command 9, channel 0, value 4) before the video starts.
With SD clarity (value 2), captures on this robot omitted periodic IDR keyframes:
RTP packets continued with no sequence gaps, but ffmpeg could not decode later
pictures. HD retained every keyframe in a full-minute live test at 800x600, 10 fps,
with no decoder errors. The video watchdog checks decoded JPEG progress, so
incoming packets alone cannot keep a frozen session alive indefinitely.

The S1 Pro also needs the V2 remote-control envelope on DP 155:
`NewRemoteCtrlV2{method: NORMAL (0), normal{value: direction}}`, with the usual
length prefix. The older `RemoteCtrl{direction}` is acknowledged but does not
move this robot. Keep the `normal` sub-message present for BRAKE (value 0).
The iOS descriptor confirms method field 1, normal field 2, and its value field 1;
two bounded three-second V2 turns through HA visibly rotated the live camera view. Other models retain the older
message until their protocol has been verified.

## The cloud config is single-use

`m.ipc.v4.rtc.config.get` returns, besides the device password and the ICE
servers, a `p2pConfig.session` the cloud has just **reserved on the robot**:
`sessionId`, `iceUfrag`, `icePassword`, `aesKey`, `traceId` and `uid`, valid for
about ten hours. The reservation takes one of the robot's few session slots and is
released only by opening a session with exactly that identity (use `uid` as the
offer's `from`). Opening sessions with a made-up identity instead leaves the
reservation unused, so enough fetches (each Home Assistant restart, each probe)
make the robot refuse every session. Fetch immediately before each session and
use the result; never cache it.

## When the robot refuses sessions

The robot answers every offer and then closes the session with a type-32
`disconnect` carrying `close_reason` / `close_reason_local`. Observed:

| `close_reason` | Meaning |
| --- | --- |
| `6` | Normal: the session sat idle (nothing to send) and the robot ended it |
| `12` | The session could not be created. Seen while the robot is being driven by hand (remote control), and consistent with the SDK's "incoming connection refused: current/max" limit |
| `4` (with `close_reason_local: 7`) | Torn down before it ever reached the connected state, 70 ms after ICE comes up and before any control packet; the SDK uses 4 as its default for that |

The robot only allows a few concurrent sessions, and the video path allocates
large media buffers. Hammering it with sessions it keeps refusing (a reconnect
loop while it is remote controlled, many aborted probes) can leave it refusing
every new session, including the map feed, until it is restarted (hold the
power button, or the power switch). Home Assistant's own feed therefore backs off
while the robot is remote controlled, sessions send a `disconnect` when they
close, and the camera backs off up to 60 s between attempts.

The robot's `DeviceMgrRequest.Control.Method.SoftwareReboot` (DP 196) is
acknowledged but did nothing outside a firmware update.

## Security

Trusted-LAN only, like the rest of the local Tuya transport. The local key and
`device_password` are secrets; never log them. Opening the session is what the
app does on its map view; it does not move the robot.

## Notes from validation

- **Discarded startup variants.** The labels used in the investigation were `b`,
  `c`, `a`, `d`, `e`. `b` (the one kept) selects HD with IOCtrl command 9,
  channel 0, value 4, then starts with command 6 operations 0 and 4. `c`
  repeated it on channel 1; `a`/`d` used operation 3 on channels 0/1; `e` tried
  operations 1/2 on channel 0. None had positive live evidence.
- **SD clarity** (value 2) produced traffic but lost periodic keyframes.
- **Outgoing ACKs must be tagged.** Untagged ACKs caused stalls and
  retransmissions. A separate WebRTC video SDP is unnecessary: the video arrives
  on the application KCP channel.
- **RTP byte 0 may be `0xa8`** although the real header is always 12 bytes on
  this path. Treating its padding/CSRC bits as standard RTP moves the payload
  offset and breaks decoding, so keep this device-specific parsing. An RTP
  sequence gap resets an in-progress H.265 fragment.
- **DP 155 `RemoteCtrl` writes** are acknowledged but do not move the S1 Pro; its
  V2 normal-direction envelope does.
- **A fault is not a prerequisite for the camera**; manual control is.
- **T2080A room order.** `SelectRoomsClean.Room.order` is a zero-based slot on
  this model (see issue #170); starting at one leaves slot zero empty and drops
  the last requested room.
