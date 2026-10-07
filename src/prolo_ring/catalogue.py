"""What the ring can do, mode by mode: the fixed built-in gestures, the assignable ones, how each
is performed, where on the ring it happens, and how early a new owner should learn it. Written
against firmware 1.0.7. Assignable gestures take their action from a profile; built-in ones never
change."""

from __future__ import annotations

from dataclasses import dataclass, field

FIRMWARE = "1.0.7"

# Learning tiers. "first" and "next" gestures appear on the learn page's maps; everything is on
# the reference page. labels.toml can override a gesture's tier.
FIRST, NEXT, REFERENCE = "first", "next", "reference"

# Map zones on the trackpad drawing (fingertip is up): center, up, down, left, right, the two
# bottom corners, the scroll edge, the Modstrip bar beneath the pad, pinch, or in the air.
ZONES = ("center", "up", "down", "left", "right", "bl", "br", "edge", "modstrip", "pinch", "air")


@dataclass(frozen=True)
class Gesture:
    name: str  # CLI gesture name, e.g. "cursor.two_finger_tap"; "" for built-ins
    title: str
    how: str
    builtin: str = ""  # fixed action; empty means the profile decides
    # Studio _profileSettings keys that must all be true for the gesture to be active.
    needs: tuple[str, ...] = ()
    tier: str = REFERENCE
    zone: str = ""


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
        Gesture("", "Move", "Glide the thumb", "Move the pointer", tier=FIRST, zone="center"),
        Gesture("", "Tap", "One light tap", "Left click", tier=FIRST, zone="center"),
        Gesture(
            "",
            "Edge scroll",
            "Slide along the scroll edge",
            "Vertical scroll",
            ("edge_scroll",),
            tier=FIRST,
            zone="edge",
        ),
        Gesture(
            "",
            "Joystick assist",
            "Swipe edge to edge and keep holding",
            "Speed follows distance from center; the outer ring boosts it",
            ("joystick_assist",),
            tier=NEXT,
        ),
        Gesture(
            "",
            "Modstrip long hold",
            "Hold the Modstrip",
            "Scroll and pan; double-tap the pad to stop",
            tier=NEXT,
            zone="modstrip",
        ),
        Gesture(
            "",
            "Modstrip hold + move",
            "Hold the Modstrip, move on the trackpad",
            "Click and drag",
            ("mod_track_drag",),
            tier=FIRST,
            zone="modstrip",
        ),
        Gesture(
            "cursor.two_finger_tap",
            "Two-finger tap",
            "Two fingers on the trackpad",
            needs=("dual_tap_tt",),
            tier=NEXT,
            zone="center",
        ),
        Gesture(
            "cursor.trackpad_modstrip_tap",
            "Trackpad + Modstrip tap",
            "Tap the trackpad and the Modstrip together",
            tier=NEXT,
            zone="modstrip",
        ),
        Gesture(
            "cursor.bottom_left_long_hold",
            "Bottom-left hold",
            "Hold the bottom-left corner",
            needs=("bottom_left",),
            tier=FIRST,
            zone="bl",
        ),
        Gesture(
            "cursor.bottom_left_double_tap",
            "Bottom-left double tap",
            "Double-tap the bottom-left corner",
            needs=("bottom_left",),
            tier=NEXT,
            zone="bl",
        ),
        Gesture(
            "cursor.bottom_right_long_hold",
            "Bottom-right hold",
            "Hold the bottom-right corner",
            needs=("bottom_right",),
            tier=FIRST,
            zone="br",
        ),
        Gesture(
            "cursor.bottom_right_double_tap",
            "Bottom-right double tap",
            "Double-tap the bottom-right corner",
            needs=("bottom_right",),
            tier=NEXT,
            zone="br",
        ),
        Gesture(
            "cursor.hold_air_tap",
            "Hold + air tap",
            "Hold the trackpad center, tap in the air once",
            needs=("air_taps",),
            zone="air",
        ),
        Gesture(
            "cursor.hold_air_double_tap",
            "Hold + air double tap",
            "Hold the trackpad center, tap in the air twice",
            needs=("air_taps",),
            zone="air",
        ),
    ),
)

NAVIGATION = Section(
    "navigation",
    "Navigation",
    "Swipe right on the Modstrip. LED 2 flashes twice.",
    "btnMNavigation",
    (
        Gesture(
            "navigation.swipe_up",
            "Swipe up",
            "Hold to repeat",
            needs=("chkVS1",),
            tier=FIRST,
            zone="up",
        ),
        Gesture(
            "navigation.swipe_down",
            "Swipe down",
            "Hold to repeat",
            needs=("chkVS1",),
            tier=FIRST,
            zone="down",
        ),
        Gesture(
            "navigation.swipe_left",
            "Swipe left",
            "Hold to repeat",
            needs=("chkHS1",),
            tier=FIRST,
            zone="left",
        ),
        Gesture(
            "navigation.swipe_right",
            "Swipe right",
            "Hold to repeat",
            needs=("chkHS1",),
            tier=FIRST,
            zone="right",
        ),
        Gesture("navigation.tap", "Tap", "One tap", needs=("chkTG1",), tier=FIRST, zone="center"),
        Gesture(
            "navigation.double_tap",
            "Double tap",
            "Two taps",
            needs=("chkTG1",),
            tier=NEXT,
            zone="center",
        ),
        Gesture(
            "navigation.triple_tap",
            "Triple tap",
            "Three taps",
            needs=("chkTG1",),
            tier=NEXT,
            zone="center",
        ),
        Gesture(
            "navigation.long_hold",
            "Long hold",
            "Hold the trackpad",
            needs=("nav_long_hold",),
            tier=NEXT,
            zone="center",
        ),
        Gesture(
            "navigation.pinch_in",
            "Pinch in",
            "Two fingers together",
            needs=("chkPG1",),
            tier=NEXT,
            zone="pinch",
        ),
        Gesture(
            "navigation.pinch_out",
            "Pinch out",
            "Two fingers apart",
            needs=("chkPG1",),
            tier=NEXT,
            zone="pinch",
        ),
        Gesture(
            "",
            "Edge scroll",
            "Slide along the scroll edge",
            "Vertical scroll",
            ("nav_edge_scroll",),
            tier=NEXT,
            zone="edge",
        ),
        Gesture(
            "",
            "Tap + hold",
            "Tap, then touch and hold",
            "Temporary pointer with joystick assist; needs Multi-tap in Studio",
        ),
    ),
    (
        (
            "With the Modstrip held (ModNav)",
            (
                Gesture(
                    "modnav.swipe_up", "Mod + swipe up", "", needs=("chkVS4",), zone="modstrip"
                ),
                Gesture(
                    "modnav.swipe_down", "Mod + swipe down", "", needs=("chkVS4",), zone="modstrip"
                ),
                Gesture(
                    "modnav.swipe_left", "Mod + swipe left", "", needs=("chkHS4",), zone="modstrip"
                ),
                Gesture(
                    "modnav.swipe_right",
                    "Mod + swipe right",
                    "",
                    needs=("chkHS4",),
                    zone="modstrip",
                ),
                Gesture("modnav.tap", "Mod + tap", "", needs=("chkTG4",), zone="modstrip"),
                Gesture(
                    "modnav.double_tap", "Mod + double tap", "", needs=("chkTG4",), zone="modstrip"
                ),
                Gesture(
                    "modnav.triple_tap", "Mod + triple tap", "", needs=("chkTG4",), zone="modstrip"
                ),
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
        Gesture(
            "touch.swipe_up", "Swipe up", "Hold to repeat", needs=("chkVS2",), tier=FIRST, zone="up"
        ),
        Gesture(
            "touch.swipe_down",
            "Swipe down",
            "Hold to repeat",
            needs=("chkVS2",),
            tier=FIRST,
            zone="down",
        ),
        Gesture(
            "touch.swipe_left",
            "Swipe left",
            "Hold to repeat",
            needs=("chkHS2",),
            tier=NEXT,
            zone="left",
        ),
        Gesture(
            "touch.swipe_right",
            "Swipe right",
            "Hold to repeat",
            needs=("chkHS2",),
            tier=NEXT,
            zone="right",
        ),
        Gesture("touch.tap", "Tap", "One tap", needs=("chkTG2",), tier=FIRST, zone="center"),
        Gesture(
            "touch.double_tap",
            "Double tap",
            "Two taps",
            needs=("chkTG2",),
            tier=NEXT,
            zone="center",
        ),
        Gesture("touch.triple_tap", "Triple tap", "Three taps", needs=("chkTG2",), zone="center"),
        Gesture(
            "touch.long_hold",
            "Long hold",
            "Hold the trackpad",
            needs=("touch_long_hold",),
            zone="center",
        ),
        Gesture(
            "",
            "Tap + hold",
            "Tap, then touch and hold",
            "Temporary pointer with joystick assist; needs Multi-tap in Studio",
        ),
    ),
    (
        (
            "With the Modstrip held (ModTouch)",
            (
                Gesture(
                    "modtouch.swipe_up", "Mod + swipe up", "", needs=("chkVS3",), zone="modstrip"
                ),
                Gesture(
                    "modtouch.swipe_down",
                    "Mod + swipe down",
                    "",
                    needs=("chkVS3",),
                    zone="modstrip",
                ),
                Gesture(
                    "modtouch.swipe_left",
                    "Mod + swipe left",
                    "",
                    needs=("chkHS3",),
                    zone="modstrip",
                ),
                Gesture(
                    "modtouch.swipe_right",
                    "Mod + swipe right",
                    "",
                    needs=("chkHS3",),
                    zone="modstrip",
                ),
                Gesture("modtouch.tap", "Mod + tap", "", needs=("chkTG3",), zone="modstrip"),
                Gesture(
                    "modtouch.double_tap",
                    "Mod + double tap",
                    "",
                    needs=("chkTG3",),
                    zone="modstrip",
                ),
                Gesture(
                    "modtouch.triple_tap",
                    "Mod + triple tap",
                    "",
                    needs=("chkTG3",),
                    zone="modstrip",
                ),
            ),
        ),
    ),
)

# The manual's Air set is left, right, tap, and double tap; the firmware also has IDs for up and
# down swipes, but Studio never offers them, so they are left out here.
AIR = Section(
    "air",
    "Air",
    "Swipe left and hold on the Modstrip. All three LEDs flash twice. Pro edition. Tilt the hand "
    "until the charging port faces down; all three LEDs light for two seconds while air gestures "
    "are armed, then move sharply. LED 3 flicks once when a gesture is recognized.",
    "btnMAir",
    (
        Gesture("air.swipe_left", "Air swipe left", "Sharp motion to the left", zone="air"),
        Gesture("air.swipe_right", "Air swipe right", "Sharp motion to the right", zone="air"),
        Gesture("air.tap", "Air tap", "One tap in the air", zone="air"),
        Gesture("air.double_tap", "Air double tap", "Two taps in the air", zone="air"),
    ),
    (
        (
            "With the trackpad held (AirTouch)",
            (
                Gesture("airtouch.swipe_left", "Hold + air swipe left", "", zone="air"),
                Gesture("airtouch.swipe_right", "Hold + air swipe right", "", zone="air"),
                Gesture("airtouch.tap", "Hold + air tap", "", zone="air"),
                Gesture("airtouch.double_tap", "Hold + air double tap", "", zone="air"),
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
        Gesture("", "Swipe left", "", "Cursor mode", tier=FIRST),
        Gesture("", "Swipe right", "", "Navigation mode", tier=FIRST),
        Gesture("", "Swipe right + hold", "", "Touch mode", tier=FIRST),
        Gesture("", "Swipe left + hold", "", "Air mode", tier=FIRST),
        Gesture(
            "",
            "1× tap + hold",
            "",
            "Reconnect, switch to the next remembered host, or unlock",
            tier=FIRST,
        ),
        Gesture("", "2× tap + hold", "", "Open a 60-second pairing window", tier=FIRST),
        Gesture(
            "",
            "3× tap + hold",
            "",
            "App Status on or off (reboots; mouse input stops while in App Status)",
            tier=NEXT,
        ),
        Gesture("", "4× tap + hold", "", "Shut down; only the charger wakes it"),
        Gesture("", "5× tap + hold", "", "Factory reset: clears bonds, settings, and profile"),
        Gesture("", "6× tap + hold", "", "Firmware update mode"),
        Gesture(
            "",
            "7× tap + hold",
            "",
            "Desktop or mobile navigation style; then forget the ring on the host and pair again",
        ),
        Gesture(
            "",
            "Palm hold",
            "Cover the touch surface with the palm",
            "Lock input until 1× tap + hold or the charger",
            tier=NEXT,
        ),
    ),
)

SECTIONS: tuple[Section, ...] = (CURSOR, NAVIGATION, TOUCH, AIR, SYSTEM)
