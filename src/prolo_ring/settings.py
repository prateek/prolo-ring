"""Ring Settings: the device-wide preferences Prolo Studio writes live, outside any profile."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import protocol as p
from .errors import ProtocolError, UsageError
from .ring import Snapshot, read_flag_group, read_snapshot
from .transport import Session

Write = tuple[int, bytes]
# Settings whose writes the ring acknowledges with [op][status]; the rest are fire-and-forget
# and are confirmed by reading the setting back.
ACKED = frozenset({p.SET_EDGE_SCROLL_STEP, p.SET_FLAG_GROUP})


def parse_bool(text: str) -> bool:
    lowered = text.strip().lower()
    if lowered in ("on", "true", "yes", "1", "enabled"):
        return True
    if lowered in ("off", "false", "no", "0", "disabled"):
        return False
    raise UsageError(f"expected on/off, got {text!r}")


def parse_int(text: str, low: int, high: int) -> int:
    try:
        value = int(text)
    except ValueError as error:
        raise UsageError(f"expected an integer {low}..{high}, got {text!r}") from error
    if not low <= value <= high:
        raise UsageError(f"value {value} is outside {low}..{high}")
    return value


def parse_choice(text: str, choices: tuple[str, ...]) -> str:
    if text.lower() not in choices:
        raise UsageError(f"expected one of {', '.join(choices)}, got {text!r}")
    return text.lower()


def parse_auto_sleep(text: str, snap: Snapshot) -> int | None:
    if text.lower() == "never":
        return None
    minutes = parse_int(text, 1, 254)
    if snap.config.config_version < 3:
        if minutes > 4:
            raise UsageError(
                "this firmware stores auto-sleep in seconds and only supports "
                "1-4 minutes or never; update the ring firmware for longer values"
            )
    elif minutes not in p.AUTO_SLEEP_PRESETS:
        raise UsageError(f"choose never or one of {', '.join(map(str, p.AUTO_SLEEP_PRESETS))}")
    return minutes


@dataclass(frozen=True)
class Setting:
    name: str
    help: str
    values: str
    read: Callable[[Snapshot], Any]
    # Returns the target value and the planned writes; may read the live cursor flags.
    plan: Callable[[str, Snapshot, int], tuple[Any, list[Write]]]
    needs_cursor_flags: bool = False


def _u8(op: int, value: int) -> list[Write]:
    return [(op, bytes([value]))]


def _cursor(value: int) -> list[Write]:
    return [(p.SET_FLAG_GROUP, p.encode_flag_group(p.CURSOR_GROUP, value)[1:])]


def _led(snap: Snapshot, mode: int | None = None, brightness: int | None = None) -> list[Write]:
    c = snap.config
    return [
        (
            p.SET_LED_POWER_MODE,
            bytes(
                [
                    c.led_mode if mode is None else mode,
                    c.led_brightness if brightness is None else brightness,
                ]
            ),
        )
    ]


def _plan_bool(op: int) -> Callable[[str, Snapshot, int], tuple[Any, list[Write]]]:
    def plan(text: str, _snap: Snapshot, _cursor_flags: int) -> tuple[Any, list[Write]]:
        value = parse_bool(text)
        return value, _u8(op, int(value))

    return plan


def _plan_u8(
    op: int, low: int, high: int
) -> Callable[[str, Snapshot, int], tuple[Any, list[Write]]]:
    def plan(text: str, _snap: Snapshot, _cursor_flags: int) -> tuple[Any, list[Write]]:
        value = parse_int(text, low, high)
        return value, _u8(op, value)

    return plan


def _plan_led_mode(text: str, snap: Snapshot, _flags: int) -> tuple[Any, list[Write]]:
    mode = parse_choice(text, ("all", "system"))
    return mode, _led(snap, mode=0 if mode == "all" else 1)


def _plan_led_brightness(text: str, snap: Snapshot, _flags: int) -> tuple[Any, list[Write]]:
    value = parse_int(text, 10, 100)
    return value, _led(snap, brightness=value)


def _plan_auto_sleep(text: str, snap: Snapshot, _flags: int) -> tuple[Any, list[Write]]:
    minutes = parse_auto_sleep(text, snap)
    wire = p.auto_sleep_to_wire(minutes, snap.config.config_version)
    return ("never" if minutes is None else minutes), _u8(p.SET_AUTO_SLEEP_TIMEOUT, wire)


def _plan_nickname(text: str, _snap: Snapshot, _flags: int) -> tuple[Any, list[Write]]:
    try:
        payload = p.encode_user_name(text)[1:]
    except ValueError as error:
        raise UsageError(str(error)) from error
    return text.strip(), [(p.SET_USER_NAME, payload)]


def _plan_edge_invert(text: str, _snap: Snapshot, flags: int) -> tuple[Any, list[Write]]:
    value = parse_bool(text)
    return value, _cursor(p.apply_cursor_device_bits(flags, invert=value))


def _plan_edge_side(text: str, _snap: Snapshot, flags: int) -> tuple[Any, list[Write]]:
    side = parse_choice(text, ("left", "right"))
    return side, _cursor(p.apply_cursor_device_bits(flags, left_side=side == "left"))


def _plan_edge_style(text: str, _snap: Snapshot, flags: int) -> tuple[Any, list[Write]]:
    style = parse_choice(text, ("stepped", "continuous"))
    return style, _cursor(p.apply_cursor_device_bits(flags, continuous=style == "continuous"))


def _cursor_flags(snap: Snapshot) -> int:
    return snap.config.flags["cursor"]


SETTINGS: dict[str, Setting] = {
    s.name: s
    for s in (
        Setting(
            "cursor-speed",
            "Pointer speed",
            "10..150",
            lambda s: s.config.sensitivity,
            _plan_u8(p.SET_SENSITIVITY, 10, 150),
        ),
        Setting(
            "left-handed",
            "Reverse Air-mode orientation for the left hand",
            "on|off",
            lambda s: s.config.left_handed,
            _plan_bool(p.SET_LEFTHAND),
        ),
        Setting(
            "multi-tap",
            "Recognize double/triple taps and Tap + Hold cursor",
            "on|off",
            lambda s: s.config.multi_tap,
            _plan_bool(p.SET_MULTITAP_MODE),
        ),
        Setting(
            "led-mode",
            "Which LEDs stay active",
            "all|system",
            lambda s: p.LED_MODES.get(s.config.led_mode, s.config.led_mode),
            _plan_led_mode,
        ),
        Setting(
            "led-brightness",
            "Brightness of active LEDs, percent",
            "10..100",
            lambda s: s.config.led_brightness,
            _plan_led_brightness,
        ),
        Setting(
            "auto-sleep",
            "Minutes idle before sleep",
            f"never|{'|'.join(map(str, p.AUTO_SLEEP_PRESETS))}",
            lambda s: s.config.auto_sleep_minutes or "never",
            _plan_auto_sleep,
        ),
        Setting(
            "edge-scroll-step",
            "Edge scroll step size in pixels",
            "1..80",
            lambda s: s.edge_scroll_step,
            _plan_u8(p.SET_EDGE_SCROLL_STEP, 1, 80),
        ),
        Setting(
            "edge-scroll-invert",
            "Invert edge scroll direction",
            "on|off",
            lambda s: bool(_cursor_flags(s) & p.CURSOR_EDGE_SCROLL_INVERT),
            _plan_edge_invert,
            needs_cursor_flags=True,
        ),
        Setting(
            "edge-scroll-side",
            "Trackpad side used for edge scroll",
            "left|right",
            lambda s: "left" if _cursor_flags(s) & p.CURSOR_EDGE_SCROLL_SIDE_LEFT else "right",
            _plan_edge_side,
            needs_cursor_flags=True,
        ),
        Setting(
            "edge-scroll-style",
            "Edge scroll behavior",
            "stepped|continuous",
            lambda s: (
                "continuous" if _cursor_flags(s) & p.CURSOR_EDGE_SCROLL_CONTINUOUS else "stepped"
            ),
            _plan_edge_style,
            needs_cursor_flags=True,
        ),
        Setting(
            "nickname",
            "Ring nickname shown in advertised names after restart",
            f"text, at most {p.NICKNAME_MAX_BYTES} UTF-8 bytes",
            lambda s: s.nickname,
            _plan_nickname,
        ),
    )
}

READ_ONLY = {
    "config-version": lambda s: s.config.config_version,
    "extended-range": lambda s: s.config.tx_power_mode == 1,
    "edge-scroll-width": lambda s: s.config.edge_scroll_width,
}


def lookup(name: str) -> Setting:
    if name not in SETTINGS:
        hint = " (read-only)" if name in READ_ONLY else ""
        raise UsageError(f"unknown setting {name!r}{hint}; writable: {', '.join(SETTINGS)}")
    return SETTINGS[name]


def snapshot_values(snap: Snapshot) -> dict[str, Any]:
    values = {name: setting.read(snap) for name, setting in SETTINGS.items()}
    values.update({name: read(snap) for name, read in READ_ONLY.items()})
    return values


async def get_settings(session: Session) -> dict[str, Any]:
    return snapshot_values(await read_snapshot(session))


async def set_setting(session: Session, name: str, text: str, *, dry_run: bool) -> dict[str, Any]:
    setting = lookup(name)
    before = await read_snapshot(session)
    flags = await read_flag_group(session, p.CURSOR_GROUP) if setting.needs_cursor_flags else 0
    target, writes = setting.plan(text, before, flags)
    result: dict[str, Any] = {
        "setting": name,
        "before": setting.read(before),
        "requested": target,
        "writes": [p.frame(op, payload).hex() for op, payload in writes],
        "dry_run": dry_run,
    }
    if dry_run:
        return result
    for op, payload in writes:
        if op in ACKED:
            status = p.parse_ack(await session.request(op, payload), op)
            if status != 0:
                raise ProtocolError(f"ring rejected {name}: {p.status_name(status)}", status=status)
        else:
            await session.write(op, payload)
    await asyncio.sleep(0.3)
    after = setting.read(await read_snapshot(session))
    result.update(after=after, verified=after == target)
    return result
