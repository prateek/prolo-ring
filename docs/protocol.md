# Prolo Ring App Status protocol

Byte-level notes for the Bluetooth LE protocol Prolo Studio 1.0.7 (build 20260821) uses to configure a ring on firmware 1.0.7. `prolo-ring` implements the read path and the Ring Settings writes described here; the profile flash path is documented but deliberately not implemented (see [flashing.md](flashing.md)).

**Provenance.** These notes come from static inspection of the Studio 1.0.7 macOS build for interoperability with hardware we own: the bundled Python bytecode was loaded and disassembled, never executed. No vendor code is included in this repository. Studio identifiers (`MW.` = its main window class, `SW.` = its settings window, `op` = its opcode module) are kept where they explain behavior. Nothing here is endorsed by Prolo.

**Safety.** Opcodes in [section 8](#8-dangerous--unused-opcodes-cli-should-refuse) can change the ring's edition, factory state, or firmware. `prolo-ring` refuses them before sending, and anyone building on these notes should do the same.

Conventions: multi-byte integers are little-endian. "u8/u16/i8" are unsigned/signed widths. Opcode names are Studio's identifiers.

Confidence: **[sure]** read directly from Studio's bytecode; **[likely]** strong inference; **[unknown]** not determinable from Studio because Studio never exercises that path. Confirmations against a live ring are marked **[verified]**.

---

## 1. Discovery and connection

### Ring states and advertised names
- **Device Status** (normal BLE HID): advertises `Prolo Ring`, or `Prolo Ring (<nickname>)`.
- **App Status** (Studio-configurable): advertises `Prolo App Ring`, or `Prolo App Ring (<nickname>)`.
  Users toggle Device/App Status by tapping the Modstrip three times and holding the
  last touch; "2x tap + press hold" re-advertises (help/tutorial text). Two flashes of all
  three LEDs after boot/wake indicate App Status.
- **DFU bootloader**: advertises `DfuTarg` (see section 9).
- Name format helpers: `RingRegistry.app_name_for_nickname` -> `"<base> (<nick>)"`,
  `device_name_for_nickname` -> `"Prolo Ring (<nick>)"`. `_strip_product_wrapper` also
  accepts `" · "`, `" - "`, `" — "` separators when parsing names.

### Scanning [sure]
- one-shot
  `BleakScanner.discover(timeout=max(0.25, timeout))`. **No service-UUID filter.**
  Keeps devices whose name, lowercased, *contains* `"prolo app"`. Device Status rings
  are never offered.
- lists all matches; the user picks one (double-click or button).
  Already-registered addresses get a `• Registered` suffix. No RSSI sort, no auto-pick.
- Post-flash reconnect reuses the same discovery; if the
  registered address is absent and exactly one App-Mode ring is visible it uses that one.

### Connect [sure]
1. `BleakClient(address)` with bleak's default connect timeout; `await connect()`.
   **No `pair()` call, no explicit bonding**, no MTU request, no explicit service discovery.
2. `start_notify(GESTURE_CHAR_UUID, notification_handler)`.
3. `read_gatt_char("00002a26-0000-1000-8000-00805f9b34fb")` (Firmware Revision String),
   decoded UTF-8 and stripped.
4. Compatibility: compare `major.minor.patch` (text before any `+`) against
   `FIRMWARE_REQUIRED_VERSION = "1.0.7"`; must be equal [`op.version_base`,
   `op.is_firmware_compatible`]. On mismatch Studio shows the "firmware update required"
   dialog and returns False. If the read throws, Studio assumes `"1.0.0"` and continues.
5. If `fetch_info`: run the info sequence (section 3).
- On macOS the "address" is a CoreBluetooth UUID; that is why Studio asks the ring for its
  real MAC (GET_MAC_ADDRESS) at registration.
- Disconnect: `stop_notify` then `disconnect()`.

### GATT
- Single custom characteristic `GESTURE_CHAR_UUID = b46e428d-e64c-4c44-8020-844bb9b6e7d6`:
  write (commands) + notify (responses and live events). Studio never names the parent
  service UUID; it addresses the characteristic directly. **[unknown]** service UUID.
- Studio writes both with and without response, so the characteristic evidently
  supports both [likely].

### Write mode and platform quirks [sure]
| Path | Write mode | Extra delays / timeouts |
|---|---|---|
| `MW.ble_exchange_notify` (request/response helper) | `response=True` on Darwin, `False` elsewhere | Darwin: wait timeout = `max(timeout, 8.0)` s, 80 ms sleep after write. Other OSes: the caller's timeout, no sleep |
| `MW.handleSetInfo`, `handleSetPower`, `handleRenameDevice`, `handlePingKeepAlive`, legacy GETs | bleak default (`response=None`, which in the bundled bleak means "with response if the characteristic has the `write` property") | none. No response is awaited |
| Flash BEGIN/DATA/COMMIT/READBACK | `response=True` on Darwin, `False` elsewhere | see section 6/7 |
| OTA_START | `response=True` on Darwin, else `False` | 60 ms sleep, then disconnect |

### MTU assumption [sure]
Studio assumes a 20-byte ATT payload (default MTU 23): flash DATA packets are checked
`<= 20` bytes ("20 bytes MTU"); readback asks for at most 19 data bytes so the response
fits ` + 19`.

---

## 2. Framing

### Requests (host -> ring) [sure]
`[payload...]`. No length field, no checksum, no sequence number.

### Responses / notifications (ring -> host) [sure]
Byte 0 is always the opcode (or a gesture/report ID for live events). Variants seen in
Studio's parsers:
- **SET-style ack**: `[status u8]`, `status` as below
  [`MW.advanced_set_flag_group`, `advanced_set_edge_scroll_width/step`, flash ops].
- **GET single u8**: either `[value]` or `[value]`.
  says "firmware may use [OP][OP][val] or [OP][val]": if `len >= 3` and `byte1 == op`,
  value = byte2; else value = byte1. The legacy notification handler only knows
  `[value]` (reads byte 1).
- **GET_PROTOCOL_INFO**: same doubled-opcode tolerance (section 3).
- **GET_ALL_CONFIG**: `[123][19 bytes]` or `[123][123][19 bytes]` (section 5).

### Status codes [sure] (`op.PROLO_STATUS_*`, flash status_names)
| Value | Name |
|---|---|
| 0x00 | OK / SUCCESS |
| 0x01 | BAD_LENGTH |
| 0x02 | BAD_VALUE |
| 0x03 | BUSY |
| 0x04 | UNSUPPORTED |
| 0xFF | ERR |

FLASH_PROFILE_COMMIT reuses the status byte with its own meanings
: 0 SUCCESS, 1 CRC_MISMATCH, 2 SIZE_INVALID,
3 FLASH_WRITE_ERROR, 4 CORRUPT_BLOB.

### `BLE_NOTIFY_SILENT_FIRST` [sure]
Frozen set: {115 SET_EDGE_SCROLL_WIDTH, 116 GET_EDGE_SCROLL_WIDTH, 121 SET_EDGE_SCROLL_STEP,
122 GET_EDGE_SCROLL_STEP, 117 SET_FLAG_GROUP, 118 GET_FLAG_GROUP, 119 GET_PROTOCOL_INFO,
123 GET_ALL_CONFIG, 124 SET_ALL_CONFIG, 125 GET_UPGRADE_INFO, 126/127/128 LICENSE_TOKEN_*,
129 GET_MAC_ADDRESS}. In `MW.notification_handler`, a notification whose byte 0 is in this
set and that did **not** satisfy the pending request predicate is dropped silently.
These opcodes are only ever consumed through `ble_exchange_notify`.

### Request/response matching [sure]
- One pending slot `_ble_wait = (future, predicate)`; the previous slot is restored
  afterwards, so effectively one outstanding request at a time.
- Each notification first goes to the predicate; if it returns true, the future resolves
  with the raw bytes and the handler stops.
- Predicates (all require `byte0 == opcode`):

| Request | Min length | Extra check | Timeout (non-Darwin) |
|---|---|---|---|
| PING_KEEPALIVE | 4 | | 1.5 s (1.2 s in retry loops) |
| GET_USER_NAME | 1 | | 2.0 s |
| GET_LICENSE_FLAGS | 2 | | 2.0 s |
| GET_ALL_CONFIG | 20 | | 2.5 s |
| GET_PROTOCOL_INFO | 4 | | 3.0 s |
| GET_EDGE_SCROLL_WIDTH/STEP | 2 | | 3.0 s |
| GET_FLAG_GROUP | 4 | `byte1 == group_id` | 3.0 s |
| SET_FLAG_GROUP / SET_EDGE_SCROLL_* | 2 | | 3.0 s |
| GET_MAC_ADDRESS | 15 | | 4.0 s, 4 attempts 0.45 s apart (plus 0.5 s initial wait on Darwin) |

On Darwin every one of these waits at least 8 s.
- Flash ops use a separate mechanism: `flash_expected_opcode` + an `asyncio.Event`;
  any notification with byte 0 in {130,131,132,133} that equals the expected opcode is
  stored and signals the event.
- Timeouts return None; Studio never retries generically.

### Keepalive / runtime telemetry [sure]
- Request:
  `struct '<BH'` = `[0x78][0x00][0x00]` (opcode 120 + u16 zero), 3 bytes.
- Cadence: a `QTimer` (`batTimer`) fires every **30 000 ms** from app start; it writes the
  ping only while connected and does not wait for the reply (the reply arrives via the
  notification handler). During info loading Studio also sends it synchronously.
- Response: at least 4 bytes:

| Offset | Type | Meaning |
|---|---|---|
| 0 | u8 | 0x78 |
| 1 | u8 | battery percent (0..100) |
| 2 | u8 | **[unknown]** (never read) |
| 3 | u8 | current mode: 1 Cursor, 2 Navigation, 3 Touch, 4 Air (`_runtime_mode_name`); other values mean "telemetry not ready" |

  Studio heuristics: it ignores the first sample after connect, and it treats an early
  `100` as a startup placeholder until 60 s have elapsed. These suggest the firmware
  reports stale or placeholder battery right after connect [likely].
- **Is it required?** [unknown]. Studio uses it for battery and mode display; nothing in Studio
  suggests the link drops without it, but nothing rules that out either.

### Unsolicited notifications (App Status, live) [sure]
Dispatch is on byte 0:
- **1..5: raw pointer reports** (`len >= 6`), layout
  `[type][buttons u8][dx i8][dy i8][scroll i8][pan i8]`.
  type 1 = press (buttons bitmask: 1 left, 2 right, 4 middle), 2 = release (buttons=0 means
  release all), 3 = move (dx, dy), 4 = vertical scroll, 5 = horizontal pan. These match
  gm IDs 1..5 (CURSOR_PRESS/RELEASE/MOVE/SCROLL/PAN). Studio injects them with pynput,
  applying gain 2 and a clamp of +/-127.
- **Gesture IDs** (byte 0 in `gesture_map`, section 6): Studio runs the locally assigned
  action. MOD_SWIPE_LEFT/RIGHT/RIGHT_HOLD/LEFT_HOLD (62/61/63/64) also update the displayed
  mode to Cursor/Navigation/Touch/Air.
- **89 / 29** (NAV/TOUCH_TAP_HOLD_JOYSTICK): built-in gestures, displayed only.
- **Opcodes 104, 106, 108, 110, 112, 114, 102, 205** are also handled unsolicited. They are
  the legacy GET replies (section 4).
- Anything else is logged as "Unknown opcode".
Studio only reads byte 0 of a gesture notification; whether the ring sends more bytes is
[unknown].

---

## 3. Handshake / info

### Connect-time sequence [sure]
1. Keepalive (1.5 s).
2. GET_ALL_CONFIG. If that fails, fall back to `_handle_get_info_legacy`: fire-and-forget
   single-byte writes of 104, 114, 106, 108, 112, 110, 102, 205 spaced 60 ms apart, with
   replies parsed by the notification handler. Then up to 3 keepalives and a full profile
   readback.
3. GET_EDGE_SCROLL_STEP; GET_FLAG_GROUP(6 = MODNAV) (neither is in the compact dump).
4. GET_USER_NAME; GET_LICENSE_FLAGS.
5. Up to 3 keepalive retries (60 ms apart) until telemetry is ready.
6. Full profile readback (section 6).

Studio **never sends** GET_DEVICE_INFO (100), GET_PROTOCOL_INFO (119; a helper exists
but nothing calls it), GET_UPGRADE_INFO (125), or GET_CONFIG_DUMP (201).

### GET_PROTOCOL_INFO (119) [sure helper, unused]
Request `[0x77]`. Response: if `len >= 5` and `byte1 == 0x77`, data starts at offset 2;
otherwise at offset 1. Studio returns a 3-tuple of u8 `(d0, d1, d2)` from there
. Constants `EXPECTED_PROTOCOL_VER = 3` and
`EXPECTED_CONFIG_VER = 2` exist but are never compared against anything. By the
names, d0 is the protocol version and d1 the config version [likely]; d2 is [unknown].

### GET_DEVICE_INFO (100), GET_UPGRADE_INFO (125) [unknown]
Defined only. No layout is recoverable from Studio.

### GET_USER_NAME (102) / SET_USER_NAME (101) [sure]
- GET request `[0x66]`. Response `[0x66][utf-8 bytes...]`; Studio takes everything after
  byte 0 up to the first `0x00` (if any) [`MW._fast_get_user_name`, notification handler].
  An empty string means no nickname.
- SET request `[0x65][utf-8 nickname]`, with no length byte and no terminator
. Studio enforces **<= 14 UTF-8 bytes**
 and trims whitespace.
  An empty payload clears the nickname. Fire-and-forget; Studio verifies by re-reading via
  handleGetInfo. Advertised names change only "after restart or status change".

### GET_MAC_ADDRESS (129) [sure]
Request `[0x81]`. Response is at least 15 bytes:

| Offset | Len | Meaning |
|---|---|---|
| 0 | 1 | 0x81 |
| 1 | 1 | proto; must be 1 |
| 2 | 1 | flags; bit 1 (0x02) = display MAC valid (required). Other bits [unknown] |
| 3 | 6 | "current" MAC |
| 9 | 6 | "display" MAC |

Display format: bytes **in wire order**, each as 2-digit uppercase hex, joined with `:`
(no byte reversal;). Studio rejects all-zero, all-0xFF,
or all-identical-octet display MACs. The difference between "current" and "display" is
[unknown]; current may be a rotating/private address [likely].

### GET_LICENSE_FLAGS (205) — read only [sure]
Request `[0xCD]`. Response `[0xCD][lo][hi?]`. Studio forms `flags = lo | (hi << 8)` when
byte 2 is present; the legacy handler reads only byte 1.
Edition mapping is by **exact value** (`op.edition`): 1 Basic, 2 Pro, 4 Founder,
8 Other, 0 Error; any other value maps to "Error". Profile flashing is enabled
only for editions `founder`, `pro`, `special`, `special edition`
.

### Battery
Only via the keepalive response byte 1 (section 2). Studio does not use the standard
Battery Service.

---

## 4. Ring settings

"Live" means Studio writes it immediately via its own opcode when the user saves
Ring Settings (`SW.handleGeneralSave`, only fields that changed). SET writes for the
legacy u8 settings are fire-and-forget (no ack awaited). Studio verifies by re-reading
GET_ALL_CONFIG.

| Setting | SET | GET | SET payload | GET reply | Values / UI | Default |
|---|---|---|---|---|---|---|
| Cursor speed ("sensitivity") | 103 | 104 | `[0x67][u8]` | `[0x68][u8]` | slider 10..150 | 40 |
| Left-handed | 105 | 106 | `[0x69][0/1]` | `[0x6A][0/1]` | checkbox | 0 |
| TX power ("Extended Bluetooth range") | 107 | 108 | `[0x6B][0/1]` | `[0x6C][0/1]` | 1 = extended. **UI hidden in 1.0.7** and `handleExtendedRange` is never connected, so Studio only displays it from the compact dump | n/a |
| LED power mode | 109 | 110 | `[0x6D][mode u8][brightness u8]` | `[0x6E][mode][brightness]` | mode 0 "All LEDs", 1 "System LEDs only", 2 "All LEDs off (legacy)" (display only, cannot be chosen); brightness is a percent, presets 15/30/50/75/100, Studio clamps 10..100 when displaying | mode 0, brightness 15 |
| Multi-tap | 111 | 112 | `[0x6F][0/1]` | `[0x70][0/1]` | checkbox (enables double/triple taps and tap+hold temporary cursor) | 1 |
| Auto-sleep | 113 | 114 | `[0x71][u8]` | `[0x72][u8]` | see below | 255 (Never) |
| Edge scroll width | 115 | 116 | `[0x73][percent u8]` | `[0x74][u8]` or `[0x74][0x74][u8]` | Studio reads it only from the compact dump and **never writes it** | 20 (`DEFAULT_ADVANCED_EDGE_SCROLL_WIDTH`) |
| Edge scroll step | 121 | 122 | `[0x79][step_px u8]` | `[0x7A][u8]` or doubled | slider 1..80, labelled "step_px". Ack `[0x79][status]` awaited | 32 |
| Flag group | 117 | 118 | `struct '<BBH'` = `[0x75][group][flags lo][flags hi]` | `[0x76][group][lo][hi]` | see below. Ack `[0x75][status]` awaited | see below |

Bytes are written `& 0xFF` with no range validation beyond what the UI controls allow.

### Auto-sleep encoding [sure]
UI choices (`settingsui`): 5 min=5, 10=10, 15=15, 30=30, 1 hour=60, 2 hours=120,
4 hours=240, Never=255. The wire encoding depends on `config_version` from the compact dump:
- `config_version >= 3`: wire byte = **minutes**, clamped 1..254; 255 = never.
- `config_version < 3` (older firmware): wire byte = **seconds**, so Studio sends
  `min(254, minutes*60)` and decodes `ceil(sec/60)`. Studio refuses to save anything other
  than 1-4 min or Never on such firmware ("update the ring firmware to use auto-sleep values
  longer than 4 minutes").
Since every UI preset is >= 5 min, firmware 1.0.7 presumably reports config_version >= 3 [likely].

### Flag groups (SET/GET_FLAG_GROUP) [sure]
Group IDs (`PROLO_CFG_GROUP_*`): 1 MODE, 2 NAV, 3 TOUCH, 4 MODTOUCH, 5 CURSOR, 6 MODNAV.
Each value is a u16 bitfield.

**MODE (1)**: 0x01 CURSOR_EN, 0x02 NAV_EN, 0x04 TOUCH_EN, 0x08 AIR_EN. Default 0x000F.

**NAV (2)**: 0x01 SWIPE_H_EN, 0x02 SWIPE_V_EN, 0x04 TAP_EN, 0x08 PINCH_EN,
0x10 EDGE_SCROLL_EN, 0x20 LONG_HOLD_EN, 0x40 LONG_HOLD_TRUE_HOLD_EN (0 = one-time action,
1 = "Hold until release (Push-to-Talk)"). Default 0x007F.

**TOUCH (3)**: 0x01 SWIPE_H_EN, 0x02 SWIPE_V_EN, 0x04 TAP_EN, 0x08 LONG_HOLD_EN,
0x10 LONG_HOLD_TRUE_HOLD_EN. Default 0x0017. Studio clears LONG_HOLD_EN and sets TRUE_HOLD
in its defaults.

**MODTOUCH (4)**: uses the TOUCH bit names; only 0x01/0x02/0x04 are used. Default 0x0007.

**MODNAV (6)**: 0x01 SWIPE_H_EN, 0x02 SWIPE_V_EN, 0x04 TAP_EN. Default 0x0007.

**CURSOR (5)**:

| Bit | Name (opcodes) | Meaning | Owner |
|---|---|---|---|
| 0x0001 | EDGE_SCROLL_EN | edge scroll in Cursor mode | profile |
| 0x0002 | EDGEHOLD_BOTTOM_LEFT_EN | bottom-left virtual button long hold | profile |
| 0x0004 | EDGEHOLD_BOTTOM_RIGHT_EN | bottom-right virtual button long hold | profile |
| 0x0008 | T2F_TAP_TRACK_TRACK_EN | two-finger tap | profile |
| 0x0010 | T2F_TAP_MOD_TRACK_EN in `opcodes`, but **Studio 1.0.7 uses it as `CURSOR_FLAG_VBUTTON_BL_TRUE_HOLD_EN`** (bottom-left hold = true hold), injected by `settingswindow._ensure_studio_106_opcode_constants` | bottom-left true-hold | profile |
| 0x0020, 0x0040 | MODHOLD_MODE_BIT0/1 | 2-bit field (bits 5-6): Modstrip long hold mode: 0 Off, 1 Continuous Scroll/Pan (scroll latch), 2 Left Click Hold Latched, 3 Left Click Hold Hold-to-Keep | profile |
| 0x0080 | AIRTOUCH_IN_CURSOR_EN | air taps while in Cursor | profile |
| 0x0100 | EDGE_SCROLL_INVERT_EN | invert edge scroll | device (Ring Settings) |
| 0x0200 | MODTRACK_DRAG_EN | Mod + Trackpad drag | profile |
| 0x0400 | EDGE_SCROLL_SIDE_LEFT_EN | 0 = right, 1 = left | device |
| 0x0800 | EDGE_SCROLL_STYLE_CONTINUOUS_EN | 0 = stepped, 1 = continuous | device |
| 0x1000, 0x2000 | MODTRACK_SPEED_BIT0/1 | 2-bit field (bits 12-13): 0 = 0.5x, 1 = 1x, 2 = 2x, 3 = 3x. **Studio never writes it** (preserves it) | n/a |
| 0x4000 | JOYSTICK_ASSIST_EN | joystick assist | profile |
| 0x8000 | VBUTTON_BR_TRUE_HOLD_EN | bottom-right hold = true hold | profile |

Default cursor flags (`DEFAULT_ADVANCED_CURSOR_FLAGS`) =
0x0001|0x0002|0x0004|0x0008|0x0010|0x0080|0x0200|0x0020|0x2000|0x4000 = **0x62BF**
(modhold mode 1, modtrack speed 2, right side, stepped).

**Who writes what**:
- *Ring Settings page* (live): sensitivity, multitap, auto-sleep, left-hand, LED; plus a
  read-modify-write of CURSOR touching only 0x0100/0x0400/0x0800; plus SET_EDGE_SCROLL_STEP
.
- *Advanced page* (`SW.handleModeSave`, live): writes MODE, NAV, MODNAV, TOUCH, MODTOUCH as
  values rebuilt from checkboxes (bits outside the UI are cleared), and a read-modify-write of
  CURSOR covering every bit except the modtrack-speed field; then SET_EDGE_SCROLL_STEP.
- *Profile flash* (`MW.apply_profile_settings_to_connected_ring`, called by
  `FlashDialog.handleBtnFlash` right before flashing): reads all six groups, then for each
  group clears the profile-owned mask and ORs in the profile's values. Masks: MODE 0x000F
  (always written as all four modes enabled); NAV 0x007F; TOUCH 0x001F; MODNAV 0x0007;
  MODTOUCH 0x0007; CURSOR 0x0001|0x0002|0x0004|0x0008|0x0010|0x0060|0x0080|0x8000|0x0200|0x4000
  = 0xC2FF. The modhold mode comes from the profile key `modstrip_long_hold_mode`
  (default 1). Device-wide bits 0x0100/0x0400/0x0800/0x3000 are preserved.
  These flag values are **not** part of the binary profile blob.

---

## 5. GET_ALL_CONFIG (123) and SET_ALL_CONFIG (124)

Request `[0x7B]`. Response `[0x7B][19 bytes]`, or `[0x7B][0x7B][19 bytes]` (if the payload after
byte 0 is >= 20 bytes and starts with 0x7B, Studio strips that byte). Extra trailing bytes are
ignored.

| Off | Type | Field | Notes |
|---|---|---|---|
| 0 | u8 | config_version | drives the auto-sleep units |
| 1 | u8 | sensitivity | 10..150 |
| 2 | u8 (bool) | left_handed | |
| 3 | u8 | tx_power_mode | 1 = extended range |
| 4 | u8 (bool) | multi_tap | |
| 5 | u8 | led_mode | 0/1 (2 legacy) |
| 6 | u8 | led_brightness | percent |
| 7 | u8 | auto_sleep | wire units (section 4) |
| 8 | u8 | edge_scroll_width | percent |
| 9 | u16 | mode_flags | group 1 |
| 11 | u16 | nav_flags | group 2 |
| 13 | u16 | touch_flags | group 3 |
| 15 | u16 | modtouch_flags | group 4 |
| 17 | u16 | cursor_flags | group 5 |

Not included: MODNAV flags (group 6), edge scroll step, nickname, license. Studio
fetches those separately.

**SET_ALL_CONFIG (124)**: defined and listed in the silent set, but **never sent** by
Studio. Its payload is [unknown]; presumably it mirrors the 19-byte dump [likely] but
that is unverified. Do not implement.

---

## 6. Profile readback (READ-ONLY path)

### Request/response [sure]
- Request `struct '<BHH'` = `[0x85][offset u16][length u16]`, length capped at **19**.
- Response `[0x85][data...]`; data = bytes 1..end (up to 19).
- Error: response is exactly 2 bytes and byte 1 is in {0xFF,1,2,3,4}. Studio treats that as a
  status (so a genuine 1-byte data chunk equal to one of those values is indistinguishable;
  this ambiguity exists in the protocol itself).
- Timeout 5 s (8 s Darwin). Studio sleeps 0.1 s (0.2 s Darwin) after the write before waiting,
  plus 20 ms between chunks on Darwin.

### Full read loop [sure]
`PROFILE_MAX_SIZE = 2048`. Starting at offset 0, request 19 bytes at a time and append.
Stop when:
1. a status/empty reply arrives; if data was already received this is normal end-of-profile
   (log text: "BAD_VALUE ... (end of profile)"), and if no data was received it is an error;
2. the header plus every entry header have been walked and the exact size is known, in
   which case trailing bytes are trimmed;
3. a chunk shorter than 19 bytes arrives; or
4. offset reaches 2048.

### Binary profile format [sure]
```
Header (4 bytes, struct 'BBBB'):
  0 version   u8   = 1 (PROFILE_VERSION_CURRENT)
  1 flags     u8   = 0 (Studio writes 0, ignores on read)
  2 entry_cnt u8
  3 reserved  u8   = 0
Entries, back-to-back, entry_cnt of them:
  struct 'BBH' (native alignment; H sits at offset 2, so no padding; little-endian on all Studio targets):
  0 gesture_id     u8   (section 6 table)
  1 step_count     u8   (<= 16; reader rejects > 16)
  2 payload_length u16  (reader rejects > 200)
  4 payload        payload_length bytes = sequence of steps
```
Total blob <= 2048 bytes. Studio's reader walks steps until the payload is exhausted rather
than trusting step_count, and only logs a mismatch.

### Step encodings
| Type byte | Name | Body | Notes |
|---|---|---|---|
| 1 | STEP_KEY | `[modifiers u8][keycode u8]` | keycode = USB HID Keyboard/Keypad usage ID (page 0x07); 0 = modifier-only tap |
| 2 | STEP_CONSUMER | `[code u16 LE]` | **bitmask, not a consumer usage ID** (table below) |
| 3 | STEP_DELAY | `[ms u16 LE]` | Studio clamps 0..1000 ms; UI step 50, default 100 |
| 4 | STEP_MOUSE | writer: `[buttons u8][dx i8][dy i8][wheel i8][pad u8=0]` (5 bytes) | reader also accepts a legacy 4-byte body (heuristic `_mouse_step_body_len`: if the byte after 4 looks like a step type 1..6, the body is 4 bytes) |
| 5 | STEP_STYLUS | same body as mouse | reader only; Studio never writes it |
| 6 | STEP_MOUSE_SNAP | writer: `[target u8]` | reader also accepts a u16 LE target. Targets: 0 left edge, 1 right edge, 2 top-left, 3 top-right, 4 bottom-left, 5 bottom-right |
| 0 | (resync) | reader treats a 0 byte as the start of an un-typed 4/5-byte mouse body | legacy tolerance |

**Modifier mask**: 0x01 LCtrl, 0x02 LShift, 0x04 LAlt, 0x08 LGUI (Meta/Win/Cmd). Only
left-side modifiers are produced. Token aliases: ctrl/control, shift, alt/option,
meta/win/windows/cmd/command.

**Key codes**: standard HID usages, for example A=0x04 ... Z=0x1D, 1..9=0x1E..0x26, 0=0x27,
Enter 0x28, Esc 0x29, Backspace 0x2A, Tab 0x2B, Space 0x2C, `-` 0x2D, `=` 0x2E, `[` 0x2F,
`]` 0x30, `\` 0x31, `;` 0x33, `'` 0x34, `` ` `` 0x35, `,` 0x36, `.` 0x37, `/` 0x38,
CapsLock 0x39, F1..F12 0x3A..0x45, PrintScreen 0x46, ScrollLock 0x47, Pause 0x48,
Insert 0x49, Home 0x4A, PgUp 0x4B, Delete 0x4C, End 0x4D, PgDn 0x4E, Right 0x4F, Left 0x50,
Down 0x51, Up 0x52, NumLock 0x53. Studio's table covers 0x04..0x53 (no keypad, F13+, or
non-US keys). "Plus" is encoded as Shift + 0x2E; on read, Shift+0x2E becomes `PlusKey`.

**Consumer bitmask** (STEP_CONSUMER):
| Code | Action |
|---|---|
| 0x0001 | Play/Pause |
| 0x0002 | Next Track |
| 0x0004 | Previous Track |
| 0x0008 | Volume Up |
| 0x0010 | Volume Down |
| 0x0020 | Toggle Mute |
| 0x0040 | Fast Fwd (alias Forward) |
| 0x0080 | Back (aliases BACK, Rewind) |
| 0x0100 | Home |
| 0x0200 | Menu |

The values look like bit positions in a consumer-control input report that the firmware
maps to usages [likely].

**Mouse buttons**: 0x01 left, 0x02 right, 0x04 middle. Studio compiles UI actions as follows
: a click becomes press then release (2 steps);
"Button Down (Hold)" becomes a press only; "Release All" becomes buttons 0; Scroll Up/Down
becomes wheel +3/-3; Mouse Move becomes dx/dy clamped to -128..127.

**Text input** (macro type "Text Input"): one STEP_KEY per character, using a US layout
(lowercase -> key; uppercase -> Shift+key; shifted symbols `!@#$%^&*()_{}|:"~<>?` ->
Shift+base). Printable ASCII 32..126 only. On read, runs of >= 2 such key steps collapse back
into a Text Input string. Press-then-release pairs
collapse back into clicks.

### Reverse mapping to JSON [sure]
For each entry the gesture ID maps to a JSON action key through `gesture_map` (unknown IDs are
skipped). Parsed steps become:
- a single key step -> `{"selected":"radioKeyboard","keySequence":"Ctrl+Shift+A"}`
  (modifiers ordered Ctrl, Shift, Alt, Meta; joined with `+`);
- a single consumer step -> `{"selected":"radioMediaControls","action":<name>}`;
- a single mouse/snap step -> `{"selected":"radioMouse","mouseAction":<label>,"x":dx,"y":dy}`;
- anything else, including a lone delay -> `{"selected":"radioMacro","macros":[...]}` with
  items `{"type":"Key Input","keySequence"}`, `{"type":"Media Controls","action"}`,
  `{"type":"Delay","delay":ms}`, `{"type":<mouse label>,"mouseAction","x","y"}`,
  `{"type":"Text Input","text"}`.
The result is stored as profile "Ring Snapshot" plus a `profile_settings` block taken from
Studio's local advanced snapshot, **not** from the ring blob.

### Gesture IDs (`op.gm`) and JSON keys (`MW.gesture_map`, labels from `MW.gesture_name`) [sure]
| ID | gm constant | JSON action key | Studio label |
|---|---|---|---|
| 0 | GESTURE_NONE | n/a | |
| 1 | CURSOR_PRESS | n/a (raw report) | |
| 2 | CURSOR_RELEASE | n/a (raw report) | |
| 3 | CURSOR_MOVE | n/a (raw report) | |
| 4 | CURSOR_SCROLL | n/a (raw report) | |
| 5 | CURSOR_PAN | n/a (raw report) | |
| 6 | CURSOR_BL_LONGHOLD | actionTrackpadLongHold | Cursor > Bottom-Left Long Hold |
| 7 | CURSOR_BR_LONGHOLD | actionTrackpadLongHoldR | Cursor > Bottom-Right Long Hold |
| 8 | CURSOR_BL_DOUBLETAP | actionDoubleTapBLC | Cursor > Bottom-Left Double Tap |
| 9 | CURSOR_BR_DOUBLETAP | actionDoubleTapBRC | Cursor > Bottom-Right Double Tap |
| 10 | CURSOR_DUAL_MOD_TRACK | actionDualTapMT | Cursor > Trackpad + Modstrip Tap |
| 11 | CURSOR_SWIPE_UP | actionCursorSwipeUp | Navigation > Swipe Up |
| 12 | CURSOR_SWIPE_DOWN | actionCursorSwipeDown | Navigation > Swipe Down |
| 13 | CURSOR_SWIPE_RIGHT | actionCursorSwipeRight | Navigation > Swipe Right |
| 14 | CURSOR_SWIPE_LEFT | actionCursorSwipeLeft | Navigation > Swipe Left |
| 15 | CURSOR_PINCH_IN | actionPinchIn | Navigation > Pinch In |
| 16 | CURSOR_PINCH_OUT | actionPinchOut | Navigation > Pinch Out |
| 17 | CURSOR_SINGLE_TAP | actionNavTap | Navigation > Tap |
| 18 | CURSOR_DOUBLE_TAP | actionNavDoubleTap | Navigation > Double Tap |
| 19 | CURSOR_TRIPLE_TAP | actionNavTripleTap | Navigation > Triple Tap |
| 20 | CURSOR_DUAL_TRACK_TRACK | actionDualTapTT | Cursor > Two-Finger Tap |
| 21 | TOUCH_SWIPE_UP | actionSwipeUp | Touch > Swipe Up |
| 22 | TOUCH_SWIPE_DOWN | actionSwipeDown | Touch > Swipe Down |
| 23 | TOUCH_SWIPE_RIGHT | actionSwipeRight | Touch > Swipe Right |
| 24 | TOUCH_SWIPE_LEFT | actionSwipeLeft | Touch > Swipe Left |
| 25 | TOUCH_SINGLE_TAP | actionTouchTap | Touch > Tap |
| 26 | TOUCH_DOUBLE_TAP | actionTouchDoubleTap | Touch > Double Tap |
| 27 | TOUCH_TRIPLE_TAP | actionTouchTripleTap | Touch > Triple Tap |
| 28 | TOUCH_LONG_HOLD | actionTouchLongHold | Touch / Media > Long Hold |
| 29 | TOUCH_TAP_HOLD_JOYSTICK | n/a (built-in) | Touch > Tap + Hold Temporary Cursor |
| 30 | NAV_LONG_HOLD | actionNavLongHold | Navigation > Long Hold |
| 31 | MODTOUCH_SWIPE_UP | actionMHSwipeUp | Touch > Mod Hold+Swipe Up |
| 32 | MODTOUCH_SWIPE_DOWN | actionMHSwipeDown | Touch > Mod Hold+Swipe Down |
| 33 | MODTOUCH_SWIPE_RIGHT | actionMHSwipeRight | Touch > Mod Hold+Swipe Right |
| 34 | MODTOUCH_SWIPE_LEFT | actionMHSwipeLeft | Touch > Mod Hold+Swipe Left |
| 35 | MODTOUCH_SINGLE_TAP | actionMHTap | Touch > Mod Hold+Tap |
| 36 | MODTOUCH_DOUBLE_TAP | actionMHDoubleTap | Touch > Mod Hold+Double Tap |
| 37 | MODTOUCH_TRIPLE_TAP | actionMHTripleTap | Touch > Mod Hold+Triple Tap |
| 41 | AIR_SWIPE_UP | actionGestureSwipeUp | Air > Swipe Up |
| 42 | AIR_SWIPE_DOWN | actionGestureSwipeDown | Air > Swipe Down |
| 43 | AIR_SWIPE_RIGHT | actionGestureSwipeRight | Air > Swipe Right |
| 44 | AIR_SWIPE_LEFT | actionGestureSwipeLeft | Air > Swipe Left |
| 45 | AIR_PUSH | n/a | |
| 46 | AIR_PULL | n/a | |
| 47 | AIR_SINGLE_TAP | actionGestureSingleTap | Air > Single Tap |
| 48 | AIR_DOUBLE_TAP | actionGestureDoubleTap | Air > Double Tap |
| 49 | AIR_TRIPLE_TAP | n/a | |
| 51 | AIRTOUCH_SWIPE_UP | actionMHGestureSwipeUp | Air > Track Hold+Swipe Up |
| 52 | AIRTOUCH_SWIPE_DOWN | actionMHGestureSwipeDown | Air > Track Hold+Swipe Down |
| 53 | AIRTOUCH_SWIPE_RIGHT | actionMHGestureSwipeRight | Air > Track Hold+Swipe Right |
| 54 | AIRTOUCH_SWIPE_LEFT | actionMHGestureSwipeLeft | Air > Track Hold+Swipe Left |
| 55 | AIRTOUCH_CURSOR_SINGLE_TAP | actionLongHoldAirTap | Cursor > Hold + Air Tap |
| 56 | AIRTOUCH_CURSOR_DOUBLE_TAP | actionLongHoldAir2xTap | Cursor > Hold + Air Double Tap |
| 57 | AIRTOUCH_SINGLE_TAP | actionMHGestureSingleTap | Air > Track Hold+Single Tap |
| 58 | AIRTOUCH_DOUBLE_TAP | actionMHGestureDoubleTap | Air > Track Hold+Double Tap |
| 59 | AIRTOUCH_TRIPLE_TAP | n/a | |
| 61 | MOD_SWIPE_RIGHT | actionModiferSwipeRight (sic) | System > Mod Swipe Right (also switches to Navigation) |
| 62 | MOD_SWIPE_LEFT | actionModiferSwipeLeft (sic) | System > Mod Swipe Left (also switches to Cursor) |
| 63 | MOD_SWIPE_RIGHT_HOLD | actionSwipeRightHold | System > Mod Swipe Right & Hold (also switches to Touch) |
| 64 | MOD_SWIPE_LEFT_HOLD | actionSwipeLeftHold | System > Mod Swipe Left & Hold (also switches to Air) |
| 65 | MOD_SINGLE_TAP | n/a | |
| 66 | MOD_SINGLE_TAP_HOLD | actionX1Tap | System > Mod 1x Tap+Press Hold |
| 67 | MOD_DOUBLE_TAP | n/a | |
| 68 | MOD_DOUBLE_TAP_HOLD | actionX2Tap | System > Mod 2x Tap+Press Hold |
| 69 | MOD_THREE_TAP | n/a | |
| 70 | MOD_THREE_TAP_HOLD | actionX3Tap | System > Mod 3x Tap+Press Hold |
| 71 | MOD_FOUR_TAP | n/a | |
| 72 | MOD_FOUR_TAP_HOLD | actionX4Tap | System > Mod 4x Tap+Press Hold |
| 73 | MOD_FIVE_TAP | n/a | |
| 74 | MOD_FIVE_TAP_HOLD | actionX5Tap | System > Mod 5x Tap+Press Hold |
| 75 | MOD_SIX_TAP | n/a | |
| 76 | MOD_SIX_TAP_HOLD | actionX6Tap | System > Mod 6x Tap+Press Hold |
| 77 | MOD_PALM_HOLD | actionPalmHold | System > Palm Hold |
| 78 | MOD_SEVEN_TAP_HOLD | actionX7Tap | System > Mod 7x Tap+Press Hold |
| 81 | (MODNAV_SWIPE_UP, fallback, not in gm) | actionMNSwipeUp | Navigation > Mod + Swipe Up |
| 82 | (MODNAV_SWIPE_DOWN) | actionMNSwipeDown | Navigation > Mod + Swipe Down |
| 83 | (MODNAV_SWIPE_RIGHT) | actionMNSwipeRight | Navigation > Mod + Swipe Right |
| 84 | (MODNAV_SWIPE_LEFT) | actionMNSwipeLeft | Navigation > Mod + Swipe Left |
| 85 | (MODNAV_SINGLE_TAP) | actionMNTap | Navigation > Mod + Tap |
| 86 | (MODNAV_DOUBLE_TAP) | actionMNDoubleTap | Navigation > Mod + Double Tap |
| 87 | (MODNAV_TRIPLE_TAP) | actionMNTripleTap | Navigation > Mod + Triple Tap |
| 89 | NAV_TAP_HOLD_JOYSTICK | n/a (built-in) | Navigation > Tap + Hold Temporary Cursor |

Notes: IDs 11-19 are named `CURSOR_*` in `gm` but Studio presents them as Navigation-mode
gestures. IDs 81-87 come from `_gm(name, fallback)` because `opcodes.gm` lacks them.
The JSON keys are Studio's internal schema; an independent CLI can choose its own names.

---

## 7. Flash write path (describe only; do NOT implement)


1. Pre-steps: Studio requires a Pro/Founder/Special edition; validates macros (<= 16
   firmware steps per gesture: `MAX_PROFILE_MACRO_STEPS`; a click costs 2 steps, a Text
   Input costs 1 per character, Open App costs 0 and is not stored); pushes the profile flag
   groups via `apply_profile_settings_to_connected_ring`.
2. Build the blob (section 6); reject if empty or > 2048 bytes. `crc = zlib.crc32(blob) & 0xFFFFFFFF`.
3. **BEGIN**: `struct '<BH' + '<I'` = `[0x82][size u16][crc32 u32]` (7 bytes).
   Reply `[0x82][status]`; 0 = OK.
4. **DATA**: for each chunk of <= **17** bytes: `[0x83][offset u16][data...]` (<= 20 bytes).
   Reply `[0x83][status]`. 50 ms between chunks; waits 0.1 s (0.2 s Darwin) after each write.
5. **COMMIT**: `[0x84]`. Reply `[0x84][result]`: 0 SUCCESS, 1 CRC_MISMATCH, 2 SIZE_INVALID,
   3 FLASH_WRITE_ERROR, 4 CORRUPT_BLOB. Timeout 5 s (10 s Darwin).
6. After an accepted COMMIT **the ring restarts** ("The ring is restarting") and Studio runs a
   reconnect loop (re-scan for App-Mode advertising, up to several GATT attempts).

Risks: the write replaces every on-ring gesture binding at once; the ring reboots; there is
no read-before-write diff in the protocol; a bad blob (wrong step lengths, step_count > 16,
payload > 200) would be rejected or misparsed. The CRC only guards transport, not semantics.
The flag-group writes in step 1 happen even if the flash later fails. The edition
gating is client-side only; Studio does not show whether the firmware enforces it [unknown].

---

## 8. Dangerous / unused opcodes (CLI should refuse)

Studio **defines but never sends** any of these except OTA_START, so their payloads and
replies are [unknown]. Purposes are inferred from names only:

| Op | Name | Inferred effect / reason to refuse |
|---|---|---|
| 124 | SET_ALL_CONFIG | bulk overwrite of all settings; layout unverified |
| 126-128 | LICENSE_TOKEN_BEGIN/DATA/COMMIT | upload a signed license token (edition upgrade); likely the "Upgrade to Pro" path, server-issued |
| 200 | RESTORE_DEFAULTS | factory-reset config |
| 201 | GET_CONFIG_DUMP | maintenance dump; probably harmless but undocumented |
| 202 | RESTORE_CONFIG | write a raw config dump back |
| 203 | ENABLE_DISABLE_HID_DEBUG | toggles a HID debug mode; may change HID behaviour |
| 204 | GET_HID_DEBUG_STATUS | read-only, undocumented |
| 206 | SET_LICENSE_FLAGS | directly sets the edition flags (factory) |
| 207 | ADD_LICENSE | factory license provisioning |
| 210 | ENTER_AGING_TEST_MODE | factory burn-in mode |
| 211 | ENTER_SHIPPING_MODE | deep power-off/ship mode; ring may need a charger to wake |
| 212 | OTA_START | sent by Studio as the single byte `[0xD4]`; the ring reboots into the Nordic DFU bootloader (`DfuTarg`). Studio then drops the client. After DFU, firmware 1.0.7 does a one-time clean reset that **clears stored Bluetooth bonds** and returns to pairing mode (firmwareupdatedialog text) |

---

## 9. Firmware DFU (brief) [sure]
- Standard **Nordic nRF5 SDK Secure DFU** (SDK 12+), driven directly over bleak with no
  nrfutil dongle. Service `0xFE59`; Control Point `8EC90001-F315-4F60-9FB8-838830DAEA50`
  (notify + write); Packet `8EC90002-...` (write without response); buttonless UUIDs
  `8EC90003`/`8EC90004` are defined but Studio uses OTA_START instead.
- Discovery: `BleakScanner.discover(timeout>=0.5)`, name lowercased equals or starts with
  `dfutarg`, sorted by RSSI. Studio refuses if more than one is nearby.
  Connect: `BleakClient(device, timeout>=3.0)`.
- Opcodes: CREATE 0x01, SET_PRN 0x02 (PRN = 12), CALC_CHECKSUM 0x03, EXECUTE 0x04,
  SELECT 0x06, response 0x60; objects: command 1, data 2. Packet size =
  `max(20, min(max_write_without_response_size, 96 on macOS / 128 elsewhere))`.
  Packet writes retry up to 5 times.
- Package: nrfutil zip with `manifest.json` (application / bootloader / softdevice /
  softdevice_bootloader -> `bin_file`, `dat_file`). URL template
  `https://downloads.proloring.com/FW_{version}.zip` (currently `FW_1.0.7.zip`). The
  bootloader validates the signed init packet.

---

## 10. Open questions and confidence

1. **Service UUID** of the gesture characteristic: unknown (Studio never names it). Low
   impact; resolve by enumerating GATT on a real ring.
2. **Keepalive byte 2**, and whether the ring needs pings to stay connected: unknown.
   Medium confidence that pings are optional (Studio sends them only every 30 s and
   uses them for telemetry).
3. **Whether legacy SETs (103..113, 101) send an ack**: Studio never waits for one. If they
   do, it would look like `[status]`. Unknown.
4. **Doubled-opcode GET replies**: Studio tolerates both forms for edge-scroll GETs,
   PROTOCOL_INFO and ALL_CONFIG. Which form firmware 1.0.7 actually uses is unknown, so a
   CLI should accept both.
5. **GET_DEVICE_INFO, GET_UPGRADE_INFO, SET_ALL_CONFIG, maintenance opcodes**: layouts unknown.
6. **GET_PROTOCOL_INFO third byte**, and whether firmware 1.0.7 reports protocol 3 / config 2
   or config 3. The auto-sleep UI only makes sense for config >= 3, which suggests the
   `EXPECTED_CONFIG_VER = 2` constant is stale. Medium confidence.
7. **CURSOR bit 0x0010**: `opcodes` names it T2F_TAP_MOD_TRACK_EN, but Studio 1.0.7 drives it
   as "bottom-left true hold". Treat the Studio 1.0.7 meaning as current (medium-high confidence).
8. **Readback end-of-profile**: from the log text, the ring appears to answer BAD_VALUE (0x02)
   past the end [likely]. A 1-byte final chunk whose value is 1-4 or 0xFF would be misread as
   an error. Bounding the read by the walked entry sizes (as Studio does) avoids that.
9. **Mouse step body length** on the ring is 5 bytes (writer) but the reader also accepts 4:
   older firmware or profiles may use 4. Medium confidence.
10. **'BBH' entry header** uses native byte order; little-endian on every platform Studio
    ships for (macOS arm64/x86_64, Windows). High confidence.
11. Edition value combinations other than exactly 1/2/4/8 map to "Error" in Studio. Whether
    real rings ever report combined bits is unknown.
