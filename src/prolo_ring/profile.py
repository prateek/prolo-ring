"""Decode the binary gesture profile read back from the ring (read-only; there is no encoder)."""

from __future__ import annotations

import struct
from typing import Any

# gesture id -> (CLI name, Prolo Studio export key or None)
GESTURES: dict[int, tuple[str, str | None]] = {
    6: ("cursor.bottom_left_long_hold", "actionTrackpadLongHold"),
    7: ("cursor.bottom_right_long_hold", "actionTrackpadLongHoldR"),
    8: ("cursor.bottom_left_double_tap", "actionDoubleTapBLC"),
    9: ("cursor.bottom_right_double_tap", "actionDoubleTapBRC"),
    10: ("cursor.trackpad_modstrip_tap", "actionDualTapMT"),
    11: ("navigation.swipe_up", "actionCursorSwipeUp"),
    12: ("navigation.swipe_down", "actionCursorSwipeDown"),
    13: ("navigation.swipe_right", "actionCursorSwipeRight"),
    14: ("navigation.swipe_left", "actionCursorSwipeLeft"),
    15: ("navigation.pinch_in", "actionPinchIn"),
    16: ("navigation.pinch_out", "actionPinchOut"),
    17: ("navigation.tap", "actionNavTap"),
    18: ("navigation.double_tap", "actionNavDoubleTap"),
    19: ("navigation.triple_tap", "actionNavTripleTap"),
    20: ("cursor.two_finger_tap", "actionDualTapTT"),
    21: ("touch.swipe_up", "actionSwipeUp"),
    22: ("touch.swipe_down", "actionSwipeDown"),
    23: ("touch.swipe_right", "actionSwipeRight"),
    24: ("touch.swipe_left", "actionSwipeLeft"),
    25: ("touch.tap", "actionTouchTap"),
    26: ("touch.double_tap", "actionTouchDoubleTap"),
    27: ("touch.triple_tap", "actionTouchTripleTap"),
    28: ("touch.long_hold", "actionTouchLongHold"),
    30: ("navigation.long_hold", "actionNavLongHold"),
    31: ("modtouch.swipe_up", "actionMHSwipeUp"),
    32: ("modtouch.swipe_down", "actionMHSwipeDown"),
    33: ("modtouch.swipe_right", "actionMHSwipeRight"),
    34: ("modtouch.swipe_left", "actionMHSwipeLeft"),
    35: ("modtouch.tap", "actionMHTap"),
    36: ("modtouch.double_tap", "actionMHDoubleTap"),
    37: ("modtouch.triple_tap", "actionMHTripleTap"),
    41: ("air.swipe_up", "actionGestureSwipeUp"),
    42: ("air.swipe_down", "actionGestureSwipeDown"),
    43: ("air.swipe_right", "actionGestureSwipeRight"),
    44: ("air.swipe_left", "actionGestureSwipeLeft"),
    45: ("air.push", None),
    46: ("air.pull", None),
    47: ("air.tap", "actionGestureSingleTap"),
    48: ("air.double_tap", "actionGestureDoubleTap"),
    49: ("air.triple_tap", None),
    51: ("airtouch.swipe_up", "actionMHGestureSwipeUp"),
    52: ("airtouch.swipe_down", "actionMHGestureSwipeDown"),
    53: ("airtouch.swipe_right", "actionMHGestureSwipeRight"),
    54: ("airtouch.swipe_left", "actionMHGestureSwipeLeft"),
    55: ("cursor.hold_air_tap", "actionLongHoldAirTap"),
    56: ("cursor.hold_air_double_tap", "actionLongHoldAir2xTap"),
    57: ("airtouch.tap", "actionMHGestureSingleTap"),
    58: ("airtouch.double_tap", "actionMHGestureDoubleTap"),
    61: ("system.modstrip_swipe_right", "actionModiferSwipeRight"),
    62: ("system.modstrip_swipe_left", "actionModiferSwipeLeft"),
    63: ("system.modstrip_swipe_right_hold", "actionSwipeRightHold"),
    64: ("system.modstrip_swipe_left_hold", "actionSwipeLeftHold"),
    66: ("system.tap1_hold", "actionX1Tap"),
    68: ("system.tap2_hold", "actionX2Tap"),
    70: ("system.tap3_hold", "actionX3Tap"),
    72: ("system.tap4_hold", "actionX4Tap"),
    74: ("system.tap5_hold", "actionX5Tap"),
    76: ("system.tap6_hold", "actionX6Tap"),
    77: ("system.palm_hold", "actionPalmHold"),
    78: ("system.tap7_hold", "actionX7Tap"),
    81: ("modnav.swipe_up", "actionMNSwipeUp"),
    82: ("modnav.swipe_down", "actionMNSwipeDown"),
    83: ("modnav.swipe_right", "actionMNSwipeRight"),
    84: ("modnav.swipe_left", "actionMNSwipeLeft"),
    85: ("modnav.tap", "actionMNTap"),
    86: ("modnav.double_tap", "actionMNDoubleTap"),
    87: ("modnav.triple_tap", "actionMNTripleTap"),
}

MODIFIERS = ((0x01, "Ctrl"), (0x02, "Shift"), (0x04, "Alt"), (0x08, "Meta"))

# USB HID Keyboard/Keypad page usage IDs, named the way Studio's key sequences spell them.
KEY_NAMES: dict[int, str] = {
    **{0x04 + i: chr(ord("A") + i) for i in range(26)},
    **{0x1E + i: str(i + 1) for i in range(9)},
    0x27: "0",
    0x28: "Enter",
    0x29: "Esc",
    0x2A: "Backspace",
    0x2B: "Tab",
    0x2C: "Space",
    0x2D: "-",
    0x2E: "=",
    0x2F: "[",
    0x30: "]",
    0x31: "\\",
    0x33: ";",
    0x34: "'",
    0x35: "`",
    0x36: ",",
    0x37: ".",
    0x38: "/",
    0x39: "CapsLock",
    **{0x3A + i: f"F{i + 1}" for i in range(12)},
    0x46: "PrintScreen",
    0x47: "ScrollLock",
    0x48: "Pause",
    0x49: "Insert",
    0x4A: "Home",
    0x4B: "Page Up",
    0x4C: "Delete",
    0x4D: "End",
    0x4E: "Page Down",
    0x4F: "Right",
    0x50: "Left",
    0x51: "Down",
    0x52: "Up",
    0x53: "NumLock",
}

# STEP_CONSUMER carries a firmware bitmask, not a HID consumer usage ID.
CONSUMER_ACTIONS = {
    0x0001: "Play/Pause",
    0x0002: "Next Track",
    0x0004: "Previous Track",
    0x0008: "Volume Up",
    0x0010: "Volume Down",
    0x0020: "Toggle Mute",
    0x0040: "Fast Fwd",
    0x0080: "Back",
    0x0100: "Home",
    0x0200: "Menu",
}

SNAP_TARGETS = {
    0: "left_edge",
    1: "right_edge",
    2: "top_left",
    3: "top_right",
    4: "bottom_left",
    5: "bottom_right",
}
MOUSE_BUTTONS = ((0x01, "left"), (0x02, "right"), (0x04, "middle"))

STEP_KEY, STEP_CONSUMER, STEP_DELAY, STEP_MOUSE, STEP_STYLUS, STEP_SNAP = 1, 2, 3, 4, 5, 6
MAX_STEPS = 16
MAX_PAYLOAD = 200


class ProfileFormatError(ValueError):
    pass


def key_sequence(modifiers: int, keycode: int) -> str:
    parts = [name for bit, name in MODIFIERS if modifiers & bit]
    if keycode:
        parts.append(KEY_NAMES.get(keycode, f"0x{keycode:02X}"))
    return "+".join(parts)


def _mouse_body_len(payload: bytes, at: int) -> int:
    """Mouse steps carry a 5-byte body; older blobs use 4. Prefer 4 when byte 4 starts a step."""
    if at + 5 <= len(payload) and not (at + 4 < len(payload) and 1 <= payload[at + 4] <= 6):
        return 5
    return 4


def decode_steps(payload: bytes) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    at = 0
    while at < len(payload):
        kind = payload[at]
        at += 1
        if kind == STEP_KEY:
            mods, code = payload[at], payload[at + 1]
            steps.append(
                {
                    "type": "key",
                    "keys": key_sequence(mods, code),
                    "modifiers": mods,
                    "keycode": code,
                }
            )
            at += 2
        elif kind == STEP_CONSUMER:
            (code,) = struct.unpack_from("<H", payload, at)
            steps.append(
                {
                    "type": "media",
                    "action": CONSUMER_ACTIONS.get(code, f"0x{code:04X}"),
                    "code": code,
                }
            )
            at += 2
        elif kind == STEP_DELAY:
            (ms,) = struct.unpack_from("<H", payload, at)
            steps.append({"type": "delay", "ms": ms})
            at += 2
        elif kind in (STEP_MOUSE, STEP_STYLUS, 0):
            size = _mouse_body_len(payload, at)
            buttons, dx, dy, wheel = struct.unpack_from("<Bbbb", payload, at)
            steps.append(
                {
                    "type": "stylus" if kind == STEP_STYLUS else "mouse",
                    "buttons": [n for bit, n in MOUSE_BUTTONS if buttons & bit],
                    "dx": dx,
                    "dy": dy,
                    "wheel": wheel,
                }
            )
            at += size
        elif kind == STEP_SNAP:
            target = payload[at]
            steps.append({"type": "snap", "target": SNAP_TARGETS.get(target, target)})
            at += 1
        else:
            raise ProfileFormatError(f"unknown step type {kind} at payload offset {at - 1}")
    return steps


def decode_profile(blob: bytes) -> dict[str, Any]:
    if len(blob) < 4:
        raise ProfileFormatError(f"profile is {len(blob)} bytes; header needs 4")
    version, flags, count, _reserved = struct.unpack_from("<4B", blob)
    gestures: list[dict[str, Any]] = []
    at = 4
    for _ in range(count):
        if at + 4 > len(blob):
            raise ProfileFormatError(f"entry header at {at} runs past the {len(blob)}-byte blob")
        gesture_id, step_count, length = struct.unpack_from("<BBH", blob, at)
        at += 4
        if step_count > MAX_STEPS or length > MAX_PAYLOAD or at + length > len(blob):
            raise ProfileFormatError(
                f"invalid entry for gesture {gesture_id}: steps={step_count} payload={length}"
            )
        name, studio_key = GESTURES.get(gesture_id, (f"unknown.{gesture_id}", None))
        gestures.append(
            {
                "gesture_id": gesture_id,
                "gesture": name,
                "studio_key": studio_key,
                "steps": decode_steps(blob[at : at + length]),
            }
        )
        at += length
    return {
        "version": version,
        "flags": flags,
        "entry_count": count,
        "size": at,
        "gestures": gestures,
    }


def profile_size(blob: bytes) -> int | None:
    """Exact profile length once the header and every entry header are present, else None."""
    if len(blob) < 4:
        return None
    at, count = 4, blob[2]
    for _ in range(count):
        if at + 4 > len(blob):
            return None
        at += 4 + struct.unpack_from("<H", blob, at + 2)[0]
    return at
