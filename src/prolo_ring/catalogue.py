"""What the ring can do, mode by mode: the fixed built-in gestures, the assignable ones, and how
each is performed. Written against firmware 1.0.7. Assignable gestures take their action from a
profile; built-in ones never change."""

from __future__ import annotations

from dataclasses import dataclass, field

FIRMWARE = "1.0.7"


@dataclass(frozen=True)
class Gesture:
    name: str  # CLI gesture name, e.g. "cursor.two_finger_tap"; "" for built-ins
    title: str
    how: str
    builtin: str = ""  # fixed action; empty means the profile decides
    # Studio _profileSettings keys that must all be true for the gesture to be active.
    needs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Section:
    key: str  # cursor | navigation | touch | air | system
    title: str
    enter: str
    mode_flag: str | None
    gestures: tuple[Gesture, ...]
    groups: tuple[tuple[str, tuple[Gesture, ...]], ...] = field(default_factory=tuple)


CURSOR = Section(
    "cursor",
    "Cursor",
    "Swipe left on the Modstrip. LED 1 flashes twice.",
    "btnMCursor",
    (
        Gesture("", "Move", "Glide the thumb on the trackpad", "Move the pointer"),
        Gesture("", "Tap", "One light tap", "Left click"),
        Gesture(
            "", "Edge scroll", "Slide along the scroll edge", "Vertical scroll", ("edge_scroll",)
        ),
        Gesture(
            "",
            "Joystick assist",
            "Swipe edge to edge and keep holding",
            "Speed follows distance from center; the outer ring boosts it",
            ("joystick_assist",),
        ),
        Gesture(
            "",
            "Modstrip long hold",
            "Hold the Modstrip",
            "Continuous scroll and pan; double-tap the trackpad to stop",
        ),
        Gesture(
            "",
            "Modstrip hold + move",
            "Hold the Modstrip, move on the trackpad",
            "Click and drag; release both to drop",
            ("mod_track_drag",),
        ),
        Gesture(
            "cursor.two_finger_tap",
            "Two-finger tap",
            "Tap with two fingers on the trackpad",
            needs=("dual_tap_tt",),
        ),
        Gesture(
            "cursor.trackpad_modstrip_tap",
            "Trackpad + Modstrip tap",
            "Tap the trackpad and the Modstrip together",
        ),
        Gesture(
            "cursor.bottom_left_long_hold",
            "Bottom-left hold",
            "Hold the bottom-left corner",
            needs=("bottom_left",),
        ),
        Gesture(
            "cursor.bottom_left_double_tap",
            "Bottom-left double tap",
            "Double-tap the bottom-left corner",
            needs=("bottom_left",),
        ),
        Gesture(
            "cursor.bottom_right_long_hold",
            "Bottom-right hold",
            "Hold the bottom-right corner",
            needs=("bottom_right",),
        ),
        Gesture(
            "cursor.bottom_right_double_tap",
            "Bottom-right double tap",
            "Double-tap the bottom-right corner",
            needs=("bottom_right",),
        ),
        Gesture(
            "cursor.hold_air_tap",
            "Hold + air tap",
            "Hold the trackpad center, tap in the air once",
            needs=("air_taps",),
        ),
        Gesture(
            "cursor.hold_air_double_tap",
            "Hold + air double tap",
            "Hold the trackpad center, tap in the air twice",
            needs=("air_taps",),
        ),
    ),
)

NAVIGATION = Section(
    "navigation",
    "Navigation",
    "Swipe right on the Modstrip. LED 2 flashes twice.",
    "btnMNavigation",
    (
        Gesture("navigation.swipe_up", "Swipe up", "Swipe up; hold to repeat", needs=("chkVS1",)),
        Gesture(
            "navigation.swipe_down", "Swipe down", "Swipe down; hold to repeat", needs=("chkVS1",)
        ),
        Gesture(
            "navigation.swipe_left", "Swipe left", "Swipe left; hold to repeat", needs=("chkHS1",)
        ),
        Gesture(
            "navigation.swipe_right",
            "Swipe right",
            "Swipe right; hold to repeat",
            needs=("chkHS1",),
        ),
        Gesture("navigation.tap", "Tap", "One tap", needs=("chkTG1",)),
        Gesture("navigation.double_tap", "Double tap", "Two taps", needs=("chkTG1",)),
        Gesture("navigation.triple_tap", "Triple tap", "Three taps", needs=("chkTG1",)),
        Gesture("navigation.long_hold", "Long hold", "Hold the trackpad", needs=("nav_long_hold",)),
        Gesture("navigation.pinch_in", "Pinch in", "Two fingers together", needs=("chkPG1",)),
        Gesture("navigation.pinch_out", "Pinch out", "Two fingers apart", needs=("chkPG1",)),
        Gesture(
            "",
            "Edge scroll",
            "Slide along the scroll edge",
            "Vertical scroll",
            ("nav_edge_scroll",),
        ),
        Gesture(
            "",
            "Tap + hold",
            "Tap, then touch and hold",
            "Temporary pointer with joystick assist; needs multi-tap",
        ),
    ),
    (
        (
            "ModNav: hold the Modstrip while gesturing",
            (
                Gesture("modnav.swipe_up", "Mod + swipe up", "", needs=("chkVS4",)),
                Gesture("modnav.swipe_down", "Mod + swipe down", "", needs=("chkVS4",)),
                Gesture("modnav.swipe_left", "Mod + swipe left", "", needs=("chkHS4",)),
                Gesture("modnav.swipe_right", "Mod + swipe right", "", needs=("chkHS4",)),
                Gesture("modnav.tap", "Mod + tap", "", needs=("chkTG4",)),
                Gesture("modnav.double_tap", "Mod + double tap", "", needs=("chkTG4",)),
                Gesture("modnav.triple_tap", "Mod + triple tap", "", needs=("chkTG4",)),
            ),
        ),
    ),
)

TOUCH = Section(
    "touch",
    "Touch",
    "Swipe right and hold on the Modstrip. LED 3 flashes twice.",
    "btnMTouch",
    (
        Gesture("touch.swipe_up", "Swipe up", "Swipe up; hold to repeat", needs=("chkVS2",)),
        Gesture("touch.swipe_down", "Swipe down", "Swipe down; hold to repeat", needs=("chkVS2",)),
        Gesture("touch.swipe_left", "Swipe left", "Swipe left; hold to repeat", needs=("chkHS2",)),
        Gesture(
            "touch.swipe_right", "Swipe right", "Swipe right; hold to repeat", needs=("chkHS2",)
        ),
        Gesture("touch.tap", "Tap", "One tap", needs=("chkTG2",)),
        Gesture("touch.double_tap", "Double tap", "Two taps", needs=("chkTG2",)),
        Gesture("touch.triple_tap", "Triple tap", "Three taps", needs=("chkTG2",)),
        Gesture("touch.long_hold", "Long hold", "Hold the trackpad", needs=("touch_long_hold",)),
        Gesture(
            "",
            "Tap + hold",
            "Tap, then touch and hold",
            "Temporary pointer with joystick assist; needs multi-tap",
        ),
    ),
    (
        (
            "ModTouch: hold the Modstrip while gesturing",
            (
                Gesture("modtouch.swipe_up", "Mod + swipe up", "", needs=("chkVS3",)),
                Gesture("modtouch.swipe_down", "Mod + swipe down", "", needs=("chkVS3",)),
                Gesture("modtouch.swipe_left", "Mod + swipe left", "", needs=("chkHS3",)),
                Gesture("modtouch.swipe_right", "Mod + swipe right", "", needs=("chkHS3",)),
                Gesture("modtouch.tap", "Mod + tap", "", needs=("chkTG3",)),
                Gesture("modtouch.double_tap", "Mod + double tap", "", needs=("chkTG3",)),
                Gesture("modtouch.triple_tap", "Mod + triple tap", "", needs=("chkTG3",)),
            ),
        ),
    ),
)

AIR = Section(
    "air",
    "Air",
    "Swipe left and hold on the Modstrip. All three LEDs flash twice. Pro edition. Tilt the "
    "hand so the charging port faces down; three LEDs light for two seconds while air gestures "
    "are armed, then move sharply.",
    "btnMAir",
    (
        Gesture("air.swipe_up", "Air swipe up", "Sharp upward motion"),
        Gesture("air.swipe_down", "Air swipe down", "Sharp downward motion"),
        Gesture("air.swipe_left", "Air swipe left", "Sharp motion to the left"),
        Gesture("air.swipe_right", "Air swipe right", "Sharp motion to the right"),
        Gesture("air.tap", "Air tap", "One tap in the air"),
        Gesture("air.double_tap", "Air double tap", "Two taps in the air"),
    ),
    (
        (
            "AirTouch: hold the trackpad while gesturing",
            (
                Gesture("airtouch.swipe_up", "Hold + air swipe up", ""),
                Gesture("airtouch.swipe_down", "Hold + air swipe down", ""),
                Gesture("airtouch.swipe_left", "Hold + air swipe left", ""),
                Gesture("airtouch.swipe_right", "Hold + air swipe right", ""),
                Gesture("airtouch.tap", "Hold + air tap", ""),
                Gesture("airtouch.double_tap", "Hold + air double tap", ""),
            ),
        ),
    ),
)

SYSTEM = Section(
    "system",
    "Modstrip commands",
    "Tap the Modstrip the given number of times, then press and hold within two seconds. Any "
    "trackpad touch cancels. The LED bar previews the count.",
    None,
    (
        Gesture("", "Swipe left", "", "Cursor mode"),
        Gesture("", "Swipe right", "", "Navigation mode"),
        Gesture("", "Swipe right + hold", "", "Touch mode"),
        Gesture("", "Swipe left + hold", "", "Air mode"),
        Gesture(
            "", "1× tap + hold", "", "Reconnect, switch to the next remembered host, or unlock"
        ),
        Gesture("", "2× tap + hold", "", "Open a 60-second pairing window"),
        Gesture("", "3× tap + hold", "", "Toggle Device Status and App Status (reboots)"),
        Gesture("", "4× tap + hold", "", "Shut down; only the charger wakes it"),
        Gesture("", "5× tap + hold", "", "Factory reset: clears bonds, settings, and profile"),
        Gesture("", "6× tap + hold", "", "Firmware update mode (DfuTarg)"),
        Gesture("", "7× tap + hold", "", "Toggle desktop and mobile navigation style (re-pair)"),
        Gesture(
            "",
            "Palm hold",
            "Cover the touch surface with the palm",
            "Lock input until 1× tap + hold or the charger",
        ),
    ),
)

SECTIONS: tuple[Section, ...] = (CURSOR, NAVIGATION, TOUCH, AIR, SYSTEM)
