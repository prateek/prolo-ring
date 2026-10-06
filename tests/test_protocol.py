import struct

import pytest

from prolo_ring import protocol as p
from prolo_ring.profile import ProfileFormatError, decode_profile, profile_size

DUMP = bytes([3, 40, 0, 0, 1, 1, 15, 30, 20]) + struct.pack("<5H", 0xF, 0x7F, 0x17, 0x7, 0x62BF)


@pytest.mark.parametrize("message", [bytes([123]) + DUMP, bytes([123, 123]) + DUMP])
def test_config_dump_parses_single_and_doubled_opcode_replies(message):
    config = p.parse_all_config(message)
    assert config.config_version == 3
    assert config.sensitivity == 40
    assert config.multi_tap is True
    assert config.led_mode == 1 and config.led_brightness == 15
    assert config.auto_sleep_minutes == 30
    assert config.flags == {
        "mode": 0xF,
        "nav": 0x7F,
        "touch": 0x17,
        "modtouch": 0x7,
        "cursor": 0x62BF,
    }


def test_short_config_dump_is_rejected():
    with pytest.raises(ValueError, match="19 bytes"):
        p.parse_all_config(bytes([123]) + DUMP[:10])


@pytest.mark.parametrize(("message", "value"), [(b"\x7a\x20", 32), (b"\x7a\x7a\x20", 32)])
def test_u8_get_accepts_both_reply_shapes(message, value):
    assert p.parse_u8_get(message, 122) == value


@pytest.mark.parametrize(
    ("minutes", "version", "wire"), [(30, 3, 30), (None, 3, 255), (4, 2, 240), (240, 3, 240)]
)
def test_auto_sleep_units_follow_config_version(minutes, version, wire):
    assert p.auto_sleep_to_wire(minutes, version) == wire
    assert p.auto_sleep_from_wire(wire, version) == minutes


def test_cursor_device_bits_never_touch_profile_bits():
    profile_bits = 0x62BF & ~p.CURSOR_DEVICE_BITS
    changed = p.apply_cursor_device_bits(0x62BF, invert=True, left_side=True, continuous=True)
    assert changed == 0x62BF | 0x0D00
    assert changed & ~p.CURSOR_DEVICE_BITS == profile_bits
    assert p.apply_cursor_device_bits(changed, left_side=False) == 0x62BF | 0x0900


def test_cursor_flags_decode_modhold_and_speed_fields():
    decoded = p.decode_flags("cursor", 0x62BF)
    assert decoded["modstrip_long_hold"] == "continuous_scroll_pan"
    assert decoded["modstrip_trackpad_speed"] == "2x"
    assert decoded["edge_scroll_left_side"] is False
    assert "unknown_bits" not in decoded


def test_mac_uses_display_octets_in_wire_order():
    reply = bytes([129, 1, 0x02]) + bytes(6) + bytes.fromhex("D0A1B2C3D4E5")
    assert p.parse_mac(reply) == "D0:A1:B2:C3:D4:E5"
    assert p.parse_mac(bytes([129, 1, 0x00]) + bytes(12)) is None


def test_license_flags_map_exact_values_to_editions():
    assert p.parse_license_flags(bytes([205, 2, 0])) == (2, "pro")
    assert p.parse_license_flags(bytes([205, 3])) == (3, "unknown")


def test_nickname_limit_is_fourteen_utf8_bytes():
    assert p.encode_user_name(" Gold ") == bytes([101]) + b"Gold"
    with pytest.raises(ValueError, match="14"):
        p.encode_user_name("é" * 8)


def blob(*entries: tuple[int, bytes]) -> bytes:
    # The reader walks the payload rather than trusting step_count, so 1 is fine here.
    body = b"".join(struct.pack("<BBH", gid, 1, len(payload)) + payload for gid, payload in entries)
    return bytes([1, 0, len(entries), 0]) + body


def test_profile_decodes_keys_media_mouse_snap_and_delay():
    data = blob(
        (20, bytes([1, 0x08, 0x07])),  # Meta+D
        (25, bytes([2]) + struct.pack("<H", 0x0001)),  # Play/Pause
        (8, bytes([4, 0x01, 0, 0, 0, 0])),  # left button down, 5-byte body
        (55, bytes([6, 0, 4, 0, 120, 0, 0, 0])),  # snap left, then move right 120
        (16, bytes([1, 0x01, 0x2E, 3]) + struct.pack("<H", 100)),  # Ctrl+=, then 100 ms
    )
    profile = decode_profile(data)
    steps = {g["gesture"]: g["steps"] for g in profile["gestures"]}
    assert steps["cursor.two_finger_tap"][0]["keys"] == "Meta+D"
    assert steps["touch.tap"][0]["action"] == "Play/Pause"
    assert steps["cursor.bottom_left_double_tap"][0]["buttons"] == ["left"]
    assert [s["type"] for s in steps["cursor.hold_air_tap"]] == ["snap", "mouse"]
    assert steps["cursor.hold_air_tap"][1]["dx"] == 120
    assert steps["navigation.pinch_out"] == [
        {"type": "key", "keys": "Ctrl+=", "modifiers": 1, "keycode": 0x2E},
        {"type": "delay", "ms": 100},
    ]
    assert profile["gestures"][0]["studio_key"] == "actionDualTapTT"
    assert profile_size(data) == len(data)


def test_profile_rejects_oversized_entries():
    bad = bytes([1, 0, 1, 0]) + struct.pack("<BBH", 20, 17, 2) + bytes([1, 0])
    with pytest.raises(ProfileFormatError, match="steps=17"):
        decode_profile(bad)


# Frames captured from a Kickstarter ring on pre-1.0.7 firmware, 2026-10-06. Every notification
# is 20 bytes; the tail is stale buffer content from earlier replies.
LIVE_TAIL = bytes.fromhex("5fcf440700607b6fb777000cdb41")


def test_live_config_dump_err_is_reported_as_unsupported():
    frame = bytes.fromhex("7bff00000000") + LIVE_TAIL
    with pytest.raises(p.UnsupportedReply, match="ERR"):
        p.parse_all_config(frame)


def test_live_keepalive_license_and_name_frames_decode():
    keepalive = bytes.fromhex("786400010000") + LIVE_TAIL
    assert p.parse_keepalive(keepalive) == p.Telemetry(battery_percent=100, mode="cursor")
    assert p.parse_license_flags(bytes.fromhex("cd0200010000") + LIVE_TAIL) == (2, "pro")
    assert p.parse_user_name(bytes.fromhex("664a6f657900") + LIVE_TAIL) == "Joey"
    assert p.parse_mac(bytes.fromhex("81ff00010000") + LIVE_TAIL) is None
