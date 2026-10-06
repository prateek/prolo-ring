"""Prolo Ring App Status protocol: opcodes, the safety allowlist, and pure encoders/decoders.

Byte layouts are documented in docs/protocol.md. Nothing here touches Bluetooth.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

COMMAND_CHAR_UUID = "b46e428d-e64c-4c44-8020-844bb9b6e7d6"
FIRMWARE_REVISION_UUID = "00002a26-0000-1000-8000-00805f9b34fb"
TESTED_FIRMWARE = "1.0.7"

# Opcodes the CLI uses. Names follow Prolo Studio's identifiers.
SET_USER_NAME = 101
GET_USER_NAME = 102
SET_SENSITIVITY = 103
GET_SENSITIVITY = 104
SET_LEFTHAND = 105
GET_LEFTHAND = 106
GET_TX_POWER_MODE = 108
SET_LED_POWER_MODE = 109
GET_LED_POWER_MODE = 110
SET_MULTITAP_MODE = 111
GET_MULTITAP_MODE = 112
SET_AUTO_SLEEP_TIMEOUT = 113
GET_AUTO_SLEEP_TIMEOUT = 114
GET_EDGE_SCROLL_WIDTH = 116
SET_FLAG_GROUP = 117
GET_FLAG_GROUP = 118
GET_PROTOCOL_INFO = 119
PING_KEEPALIVE = 120
SET_EDGE_SCROLL_STEP = 121
GET_EDGE_SCROLL_STEP = 122
GET_ALL_CONFIG = 123
GET_MAC_ADDRESS = 129
FLASH_PROFILE_READBACK = 133
GET_LICENSE_FLAGS = 205

# The only opcodes the transport will put on the wire. Everything else is refused before
# sending: profile flash (130-132), bulk config write (124), license and edition provisioning
# (126-128, 206, 207), restore/maintenance (200-204), factory modes (210, 211), and OTA (212).
READ_OPCODES = frozenset(
    {
        GET_USER_NAME,
        GET_SENSITIVITY,
        GET_LEFTHAND,
        GET_TX_POWER_MODE,
        GET_LED_POWER_MODE,
        GET_MULTITAP_MODE,
        GET_AUTO_SLEEP_TIMEOUT,
        GET_EDGE_SCROLL_WIDTH,
        GET_FLAG_GROUP,
        GET_PROTOCOL_INFO,
        PING_KEEPALIVE,
        GET_EDGE_SCROLL_STEP,
        GET_ALL_CONFIG,
        GET_MAC_ADDRESS,
        FLASH_PROFILE_READBACK,
        GET_LICENSE_FLAGS,
    }
)
SETTING_WRITE_OPCODES = frozenset(
    {
        SET_USER_NAME,
        SET_SENSITIVITY,
        SET_LEFTHAND,
        SET_LED_POWER_MODE,
        SET_MULTITAP_MODE,
        SET_AUTO_SLEEP_TIMEOUT,
        SET_FLAG_GROUP,
        SET_EDGE_SCROLL_STEP,
    }
)
ALLOWED_OPCODES = READ_OPCODES | SETTING_WRITE_OPCODES

STATUS_NAMES = {
    0x00: "OK",
    0x01: "BAD_LENGTH",
    0x02: "BAD_VALUE",
    0x03: "BUSY",
    0x04: "UNSUPPORTED",
    0xFF: "ERR",
}

FLAG_GROUPS = {1: "mode", 2: "nav", 3: "touch", 4: "modtouch", 5: "cursor", 6: "modnav"}
CURSOR_GROUP = 5

# Cursor flag bits that are device-wide Ring Settings. Every other cursor bit belongs to the
# profile and is rewritten whenever Studio flashes one.
CURSOR_EDGE_SCROLL_INVERT = 0x0100
CURSOR_EDGE_SCROLL_SIDE_LEFT = 0x0400
CURSOR_EDGE_SCROLL_CONTINUOUS = 0x0800
CURSOR_DEVICE_BITS = (
    CURSOR_EDGE_SCROLL_INVERT | CURSOR_EDGE_SCROLL_SIDE_LEFT | CURSOR_EDGE_SCROLL_CONTINUOUS
)

FLAG_BITS: dict[str, dict[int, str]] = {
    "mode": {0x01: "cursor", 0x02: "navigation", 0x04: "touch", 0x08: "air"},
    "nav": {
        0x01: "swipe_horizontal",
        0x02: "swipe_vertical",
        0x04: "tap",
        0x08: "pinch",
        0x10: "edge_scroll",
        0x20: "long_hold",
        0x40: "long_hold_true_hold",
    },
    "touch": {
        0x01: "swipe_horizontal",
        0x02: "swipe_vertical",
        0x04: "tap",
        0x08: "long_hold",
        0x10: "long_hold_true_hold",
    },
    "modtouch": {0x01: "swipe_horizontal", 0x02: "swipe_vertical", 0x04: "tap"},
    "modnav": {0x01: "swipe_horizontal", 0x02: "swipe_vertical", 0x04: "tap"},
    "cursor": {
        0x0001: "edge_scroll",
        0x0002: "bottom_left_long_hold",
        0x0004: "bottom_right_long_hold",
        0x0008: "two_finger_tap",
        0x0010: "bottom_left_true_hold",
        0x0080: "air_taps",
        0x0100: "edge_scroll_invert",
        0x0200: "modstrip_trackpad_drag",
        0x0400: "edge_scroll_left_side",
        0x0800: "edge_scroll_continuous",
        0x4000: "joystick_assist",
        0x8000: "bottom_right_true_hold",
    },
}
MODHOLD_MODES = {
    0: "off",
    1: "continuous_scroll_pan",
    2: "left_click_latched",
    3: "left_click_hold_to_keep",
}
MODTRACK_SPEEDS = {0: "0.5x", 1: "1x", 2: "2x", 3: "3x"}

RUNTIME_MODES = {1: "cursor", 2: "navigation", 3: "touch", 4: "air"}
EDITIONS = {1: "basic", 2: "pro", 4: "founder", 8: "other"}
LED_MODES = {0: "all", 1: "system", 2: "off"}
AUTO_SLEEP_PRESETS = (5, 10, 15, 30, 60, 120, 240)
AUTO_SLEEP_NEVER = 255
NICKNAME_MAX_BYTES = 14
READBACK_CHUNK = 19
PROFILE_MAX_SIZE = 2048


def frame(opcode: int, payload: bytes = b"") -> bytes:
    return bytes([opcode]) + payload


def status_name(code: int) -> str:
    return STATUS_NAMES.get(code, f"UNKNOWN(0x{code:02X})")


class UnsupportedReply(ValueError):
    """The ring answered a GET with status ERR: the opcode is not implemented on this firmware."""


def is_error_reply(message: bytes) -> bool:
    """[op][0xFF], usually followed by stale padding: the ring always notifies a fixed 20-byte
    buffer and only overwrites the leading bytes, so trailing bytes come from earlier replies."""
    return len(message) >= 2 and message[1] == 0xFF


def parse_u8_get(message: bytes, opcode: int) -> int:
    """Single-byte GET replies arrive as [op][val] or, on some firmware, [op][op][val]."""
    if len(message) >= 3 and message[1] == opcode:
        return message[2]
    if len(message) >= 2:
        return message[1]
    raise ValueError(f"reply to opcode {opcode} too short: {message.hex()}")


@dataclass(frozen=True)
class AllConfig:
    config_version: int
    sensitivity: int
    left_handed: bool
    tx_power_mode: int
    multi_tap: bool
    led_mode: int
    led_brightness: int
    auto_sleep_wire: int
    edge_scroll_width: int
    flags: dict[str, int]

    @property
    def auto_sleep_minutes(self) -> int | None:
        return auto_sleep_from_wire(self.auto_sleep_wire, self.config_version)


def parse_all_config(message: bytes) -> AllConfig:
    data = message[1:]
    if len(data) >= 20 and data[0] == GET_ALL_CONFIG:
        data = data[1:]
    if data and data[0] == 0xFF:
        raise UnsupportedReply(
            "GET_ALL_CONFIG answered ERR; this firmware predates the config dump"
        )
    if len(data) < 19:
        raise ValueError(f"config dump needs 19 bytes, got {len(data)}: {message.hex()}")
    if not 1 <= data[0] <= 15:
        raise UnsupportedReply(f"implausible config_version {data[0]} in reply {message.hex()}")
    (
        version,
        sens,
        left,
        tx,
        multi,
        led_mode,
        led_bright,
        sleep,
        width,
        mode,
        nav,
        touch,
        modtouch,
        cursor,
    ) = struct.unpack_from("<9B5H", data)
    return AllConfig(
        config_version=version,
        sensitivity=sens,
        left_handed=bool(left),
        tx_power_mode=tx,
        multi_tap=bool(multi),
        led_mode=led_mode,
        led_brightness=led_bright,
        auto_sleep_wire=sleep,
        edge_scroll_width=width,
        flags={"mode": mode, "nav": nav, "touch": touch, "modtouch": modtouch, "cursor": cursor},
    )


def auto_sleep_to_wire(minutes: int | None, config_version: int) -> int:
    """None means never. config_version >= 3 counts minutes; older firmware counts seconds."""
    if minutes is None:
        return AUTO_SLEEP_NEVER
    if config_version >= 3:
        return max(1, min(254, minutes))
    return max(1, min(254, minutes * 60))


def auto_sleep_from_wire(wire: int, config_version: int) -> int | None:
    if wire == AUTO_SLEEP_NEVER:
        return None
    if config_version >= 3:
        return wire
    return math.ceil(wire / 60)


def decode_flags(group: str, value: int) -> dict[str, object]:
    names = FLAG_BITS.get(group, {})
    decoded: dict[str, object] = {name: bool(value & bit) for bit, name in names.items()}
    if group == "cursor":
        decoded["modstrip_long_hold"] = MODHOLD_MODES[(value >> 5) & 0b11]
        decoded["modstrip_trackpad_speed"] = MODTRACK_SPEEDS[(value >> 12) & 0b11]
    known = sum(names) | (0x3060 if group == "cursor" else 0)
    if extra := value & ~known & 0xFFFF:
        decoded["unknown_bits"] = f"0x{extra:04X}"
    return decoded


def parse_flag_group(message: bytes, group: int) -> int:
    if is_error_reply(message):
        raise UnsupportedReply(f"GET_FLAG_GROUP {group} answered ERR")
    if len(message) < 4 or message[0] != GET_FLAG_GROUP or message[1] != group:
        raise ValueError(f"bad flag group {group} reply: {message.hex()}")
    return struct.unpack_from("<H", message, 2)[0]


def encode_flag_group(group: int, value: int) -> bytes:
    return frame(SET_FLAG_GROUP, struct.pack("<BH", group, value & 0xFFFF))


def apply_cursor_device_bits(
    current: int,
    *,
    invert: bool | None = None,
    left_side: bool | None = None,
    continuous: bool | None = None,
) -> int:
    """Change only the device-wide edge-scroll bits; every profile-owned bit is preserved."""
    value = current
    for flag, bit in (
        (invert, CURSOR_EDGE_SCROLL_INVERT),
        (left_side, CURSOR_EDGE_SCROLL_SIDE_LEFT),
        (continuous, CURSOR_EDGE_SCROLL_CONTINUOUS),
    ):
        if flag is not None:
            value = value | bit if flag else value & ~bit
    assert (value ^ current) & ~CURSOR_DEVICE_BITS == 0
    return value & 0xFFFF


def parse_ack(message: bytes, opcode: int) -> int:
    if len(message) < 2 or message[0] != opcode:
        raise ValueError(f"bad ack for opcode {opcode}: {message.hex()}")
    return message[1]


@dataclass(frozen=True)
class Telemetry:
    battery_percent: int
    mode: str | None


def parse_keepalive(message: bytes) -> Telemetry:
    if len(message) < 4 or message[0] != PING_KEEPALIVE:
        raise ValueError(f"bad keepalive reply: {message.hex()}")
    return Telemetry(battery_percent=message[1], mode=RUNTIME_MODES.get(message[3]))


KEEPALIVE_REQUEST = frame(PING_KEEPALIVE, struct.pack("<H", 0))


def parse_user_name(message: bytes) -> str:
    return message[1:].split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def encode_user_name(name: str) -> bytes:
    raw = name.strip().encode("utf-8")
    if len(raw) > NICKNAME_MAX_BYTES:
        raise ValueError(
            f"nickname is {len(raw)} UTF-8 bytes; the ring allows {NICKNAME_MAX_BYTES}"
        )
    return frame(SET_USER_NAME, raw)


def parse_mac(message: bytes) -> str | None:
    if len(message) < 15 or message[0] != GET_MAC_ADDRESS or message[1] != 1:
        return None
    if not message[2] & 0x02:
        return None
    octets = message[9:15]
    if len(set(octets)) == 1:
        return None
    return ":".join(f"{b:02X}" for b in octets)


def parse_license_flags(message: bytes) -> tuple[int, str]:
    if len(message) < 2:
        raise ValueError(f"bad license flags reply: {message.hex()}")
    flags = message[1] | (message[2] << 8 if len(message) >= 3 else 0)
    return flags, EDITIONS.get(flags, "unknown")


def parse_protocol_info(message: bytes) -> tuple[int, int, int]:
    start = 2 if len(message) >= 5 and message[1] == GET_PROTOCOL_INFO else 1
    if len(message) < start + 3:
        raise ValueError(f"bad protocol info reply: {message.hex()}")
    return message[start], message[start + 1], message[start + 2]


def encode_readback(offset: int, length: int = READBACK_CHUNK) -> bytes:
    return frame(FLASH_PROFILE_READBACK, struct.pack("<HH", offset, min(length, READBACK_CHUNK)))


def firmware_base(revision: str) -> str:
    return revision.strip().split("+", 1)[0]
