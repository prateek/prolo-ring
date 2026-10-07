"""Render a cheat sheet from a Prolo Studio profile export, labelled with what each gesture does
on this machine. No ring needed.

Two pages. The learn page teaches the structure: the two-axis Modstrip rule, one trackpad map per
mode with the first-week actions placed where you perform them (fingertip up), and the everyday
commands. The reference page lists every gesture by input family, the full tap ladder with pegs,
and the notes that trip people up."""

from __future__ import annotations

import hashlib
import html
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .catalogue import FIRMWARE, FIRST, NEXT, REFERENCE, SECTIONS, Gesture, Section
from .profile import GESTURES

GESTURES_BY_NAME = {name: key for _id, (name, key) in GESTURES.items()}

MAC_GLYPHS = {
    "ctrl": "⌃",
    "control": "⌃",
    "shift": "⇧",
    "alt": "⌥",
    "option": "⌥",
    "meta": "⌘",
    "win": "⌘",
    "windows": "⌘",
    "cmd": "⌘",
    "command": "⌘",
}
GLYPH_SET = set(MAC_GLYPHS.values())
KEY_LABELS = {
    "Page Up": "PgUp",
    "Page Down": "PgDn",
    "Up": "↑",
    "Down": "↓",
    "Left": "←",
    "Right": "→",
    "Enter": "↩",
    "Return": "↩",
    "Escape": "⎋",
    "Esc": "⎋",
    "Backspace": "⌫",
    "Delete": "⌦",
    "Tab": "⇥",
    "Space": "␣",
    "Home": "↖",
    "End": "↘",
    "PlusKey": "+",
    "MinusKey": "-",
}
# Studio pads some macros with a no-op key step; it carries no meaning for a reader.
NOISE_KEYS = {"Key00", ""}
MOUSE_LABELS = {
    "Mouse Left Click": "Left click",
    "Mouse Right Click": "Right click",
    "Mouse Middle Click": "Middle click",
    "Left Button Down (Hold)": "Hold left button (tap to release)",
    "Right Button Down (Hold)": "Hold right button",
    "Release All": "Release buttons",
    "Scroll Up": "Scroll up",
    "Scroll Down": "Scroll down",
    "Mouse Move": "Move pointer",
    "Snap Cursor - Left Edge": "Snap pointer to left edge",
    "Snap Cursor - Right Edge": "Snap pointer to right edge",
}
MEDIA_LABELS = {
    "Toggle Mute": "Mute",
    "Fast Fwd": "Fast forward",
    "Play/Pause": "Play / pause",
    "Next Track": "Next track",
    "Previous Track": "Previous track",
    "Volume Up": "Volume up",
    "Volume Down": "Volume down",
}
# Consumer codes the ring sends for XR glasses; a Mac ignores them.
XR_ONLY = {"Back", "Home"}

MODE_META = {
    "cursor": {"color": "#1d4ed8", "led": 1, "mnemonic": "Left is the mouse hand: left clicks."},
    "navigation": {
        "color": "#047857",
        "led": 2,
        "mnemonic": "Right is for reading: right navigates.",
    },
    "touch": {"color": "#b45309", "led": 3, "mnemonic": "Right and hold: hold the note, music."},
    "air": {"color": "#6d28d9", "led": 0, "mnemonic": "Left and hold: hold on, lift off."},
    "system": {"color": "#3f3f46", "led": 0, "mnemonic": "Count the taps, then hold."},
}
# The Modstrip ladder: headline action per count, with a peg that rhymes or pictures it.
LADDER_PEGS = {
    "1": "one: back on",
    "2": "two: new",
    "3": "three: Studio",
    "4": "four: lights out",
    "5": "five: wipe it all",
    "6": "six: fix",
    "7": "seven: flip",
}
DANGER_FROM = 4

# Short labels for map slots, where space is tight and position already says most of it.
SHORT = {
    "Tap": "tap",
    "Double tap": "2×",
    "Triple tap": "3×",
    "Long hold": "hold",
    "Two-finger tap": "2 fingers",
    "Move": "glide",
    "Swipe up": "↑",
    "Swipe down": "↓",
    "Swipe left": "←",
    "Swipe right": "→",
    "Edge scroll": "edge",
    "Pinch in": "pinch in",
    "Pinch out": "pinch out",
}
OBVIOUS_HOW = {
    "Hold to repeat",
    "One tap",
    "Two taps",
    "Three taps",
    "Hold the trackpad",
    "Two fingers together",
    "Two fingers apart",
    "Two fingers on the trackpad",
    "One light tap",
    "Glide the thumb",
    "Slide along the scroll edge",
    "Hold the Modstrip",
    "Hold the Modstrip, move on the trackpad",
    "Tap the trackpad and the Modstrip together",
}


@dataclass(frozen=True)
class Row:
    gesture: str
    title: str
    how: str
    action: str
    detail: str
    enabled: bool
    source: str  # "profile", "builtin", or "unassigned"
    glyph: str = ""
    mnemonic: str = ""
    keys: tuple[str, ...] = ()  # keycaps when the action is a chord
    tier: str = REFERENCE
    zone: str = ""
    note: str = ""


@dataclass(frozen=True)
class Sheet:
    title: str
    profile_name: str
    profile_hash: str
    firmware: str
    sections: list[tuple[Section, list[Row], list[tuple[str, list[Row]]]]]
    mode_mnemonics: dict[str, str]


def _squash(text: str) -> str:
    text = text.lower().replace(" ", "").replace("+", "").replace("arrow", "")
    for alias in ("windows", "win", "cmd", "command"):
        text = text.replace(alias, "meta")
    return text.replace("control", "ctrl").replace("option", "alt")


def keycaps(sequence: str) -> tuple[str, ...]:
    parts = [part.strip() for part in sequence.split("+") if part.strip()]
    glyphs = [MAC_GLYPHS[p.lower()] for p in parts if p.lower() in MAC_GLYPHS]
    keys = [
        KEY_LABELS.get(p, p) for p in parts if p.lower() not in MAC_GLYPHS and p not in NOISE_KEYS
    ]
    return tuple(glyphs + keys)


def caps_text(keys: tuple[str, ...]) -> str:
    return "".join(k for k in keys if k in GLYPH_SET) + " ".join(
        k for k in keys if k not in GLYPH_SET
    )


def chord(sequence: str) -> str:
    return caps_text(keycaps(sequence))


def describe(entry: dict[str, Any]) -> str:
    """Turn one Studio action entry into a short phrase."""
    match entry.get("selected"):
        case "radioKeyboard":
            return chord(entry.get("keySequence", ""))
        case "radioMediaControls":
            action = str(entry.get("action", ""))
            return MEDIA_LABELS.get(action, action)
        case "radioMouse":
            action = str(entry.get("mouseAction", ""))
            text = MOUSE_LABELS.get(action, action)
            if action == "Mouse Move":
                text += f" ({entry.get('x', 0)}, {entry.get('y', 0)})"
            return text
        case "radioOpenApp":
            return f"Open {Path(str(entry.get('filePath', ''))).stem or 'app'}"
        case "radioMacro":
            steps = []
            for step in entry.get("macros", []):
                kind = step.get("type", "")
                if kind == "Key Input":
                    steps.append(chord(step.get("keySequence", "")))
                elif kind == "Media Controls":
                    action = str(step.get("action", ""))
                    steps.append(MEDIA_LABELS.get(action, action))
                elif kind == "Delay":
                    steps.append(f"wait {step.get('delay', 0)} ms")
                elif kind == "Text Input":
                    steps.append(f"type {step.get('text', '')!r}")
                else:
                    steps.append(MOUSE_LABELS.get(kind, kind))
            return " → ".join(step for step in steps if step)
        case "radioDisable":
            return ""
    return ""


def _chord_keys(entry: dict[str, Any]) -> tuple[str, ...]:
    if entry.get("selected") == "radioKeyboard":
        return keycaps(entry.get("keySequence", ""))
    if entry.get("selected") == "radioMacro":
        macros = [
            m
            for m in entry.get("macros", [])
            if not (m.get("type") == "Key Input" and m.get("keySequence") in NOISE_KEYS)
        ]
        if len(macros) == 1 and macros[0].get("type") == "Key Input":
            return keycaps(macros[0].get("keySequence", ""))
    return ()


def _alias_adds_meaning(alias: str, entry: dict[str, Any], raw: str) -> bool:
    if not alias:
        return False
    sequence = str(entry.get("keySequence", ""))
    return _squash(alias) not in {_squash(raw), _squash(sequence)}


def _note_for(section: Section, entry: dict[str, Any], alias: str) -> str:
    if alias.lower().startswith("win"):
        return "Windows chord"
    if (
        section.key == "navigation"
        and entry.get("selected") == "radioMediaControls"
        and entry.get("action") in XR_ONLY
    ):
        return "XR glasses code; inert on a Mac"
    return ""


def glyph_for(name: str) -> str:
    tail = name.split(".", 1)[-1] if name else ""
    if "pinch_in" in tail:
        return "pinch-in"
    if "pinch_out" in tail:
        return "pinch-out"
    for direction in ("up", "down", "left", "right"):
        if tail.endswith(f"swipe_{direction}"):
            return f"swipe-{direction}"
    if tail.startswith("bottom_left"):
        return "corner-bl"
    if tail.startswith("bottom_right"):
        return "corner-br"
    if tail.endswith("trackpad_modstrip_tap"):
        return "tap-pad-mod"
    if tail.endswith("triple_tap"):
        return "tap-3"
    if tail.endswith("double_tap"):
        return "tap-2"
    if tail.endswith("long_hold"):
        return "hold"
    if tail.endswith("two_finger_tap"):
        return "tap-two-finger"
    if tail.endswith("tap"):
        return "tap-1"
    return ""


def glyph_for_title(title: str) -> str:
    t = title.lower()
    if "pinch" in t:
        return "pinch-in"
    for direction in ("up", "down", "left", "right"):
        if f"swipe {direction}" in t:
            return f"swipe-{direction}"
    if "triple" in t or "3×" in t:
        return "tap-3"
    if "double" in t or "2×" in t:
        return "tap-2"
    if "modstrip" in t and "hold" in t:
        return "mod-hold"
    if "hold" in t and "tap" not in t:
        return "hold"
    if "two-finger" in t or "two fingers" in t:
        return "tap-two-finger"
    if "tap" in t:
        return "tap-1"
    if "move" in t or "glide" in t:
        return "move"
    if "scroll" in t:
        return "scroll"
    return ""


def load_profile(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    settings = data.get("settings", data) if isinstance(data, dict) else None
    if not isinstance(settings, dict):
        raise ValueError(f"{path} is not a Prolo Studio profile export")
    return settings


def load_labels(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return tomllib.loads(path.read_text())


def build(
    profile: dict[str, Any],
    labels: dict[str, Any],
    *,
    title: str = "Prolo Ring",
    profile_name: str = "",
    profile_hash: str = "",
) -> Sheet:
    flags: dict[str, Any] = profile.get("_profileSettings", {})
    gesture_labels: dict[str, Any] = labels.get("gestures", {})
    mode_labels: dict[str, Any] = labels.get("modes", {})

    def enabled(section: Section, gesture: Gesture) -> bool:
        if section.mode_flag and flags.get(section.mode_flag) is False:
            return False
        return all(flags.get(flag, True) for flag in gesture.needs)

    def row(section: Section, gesture: Gesture) -> Row:
        on = enabled(section, gesture)
        glyph = glyph_for(gesture.name) or glyph_for_title(gesture.title)
        custom = gesture_labels.get(gesture.name) if gesture.name else None
        tier = str(custom.get("tier", gesture.tier)) if isinstance(custom, dict) else gesture.tier
        if not gesture.name:
            peg = LADDER_PEGS.get(gesture.title.split("×")[0], "") if "×" in gesture.title else ""
            return Row(
                "",
                gesture.title,
                gesture.how,
                gesture.builtin,
                "",
                on,
                "builtin",
                glyph,
                peg,
                (),
                tier,
                gesture.zone,
            )
        key = GESTURES_BY_NAME.get(gesture.name)
        entry = profile.get(key, {}) if key else {}
        raw = describe(entry)
        keys = _chord_keys(entry)
        label = custom.get("label") if isinstance(custom, dict) else custom
        mnemonic = str(custom.get("mnemonic", "")) if isinstance(custom, dict) else ""
        alias = str(entry.get("gestureAlias", ""))
        note = _note_for(section, entry, alias)
        if label:
            return Row(
                gesture.name,
                gesture.title,
                gesture.how,
                str(label),
                raw,
                on,
                "profile",
                glyph,
                mnemonic,
                keys,
                tier,
                gesture.zone,
                note,
            )
        if raw:
            if _alias_adds_meaning(alias, entry, raw):
                return Row(
                    gesture.name,
                    gesture.title,
                    gesture.how,
                    alias,
                    raw,
                    on,
                    "profile",
                    glyph,
                    mnemonic,
                    keys,
                    tier,
                    gesture.zone,
                    note,
                )
            return Row(
                gesture.name,
                gesture.title,
                gesture.how,
                raw,
                "",
                on,
                "profile",
                glyph,
                mnemonic,
                keys,
                tier,
                gesture.zone,
                note,
            )
        return Row(
            gesture.name,
            gesture.title,
            gesture.how,
            "",
            "",
            on,
            "unassigned",
            glyph,
            "",
            (),
            tier,
            gesture.zone,
        )

    sections = []
    for section in SECTIONS:
        rows = [row(section, g) for g in section.gestures]
        groups = [(name, [row(section, g) for g in gs]) for name, gs in section.groups]
        sections.append((section, rows, groups))
    mnemonics: dict[str, str] = {}
    for key, meta in MODE_META.items():
        custom = mode_labels.get(key)
        default = str(meta["mnemonic"])
        mnemonics[key] = (
            str(custom.get("mnemonic", default)) if isinstance(custom, dict) else default
        )
    return Sheet(
        labels.get("title", title), profile_name, profile_hash, FIRMWARE, sections, mnemonics
    )


def render_markdown(sheet: Sheet) -> str:
    out = [f"# {sheet.title}", ""]
    if sheet.profile_name:
        out.append(
            f"Profile `{sheet.profile_name}` ({sheet.profile_hash}), firmware {sheet.firmware}."
        )
        out.append("")
    for section, rows, groups in sheet.sections:
        out += [
            f"## {section.title}",
            "",
            f"*{sheet.mode_mnemonics[section.key]}* {section.enter}",
            "",
        ]
        out += _md_table(rows)
        for name, group_rows in groups:
            out += ["", f"### {name}", "", *_md_table(group_rows)]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _md_table(rows: list[Row]) -> list[str]:
    lines = ["| Gesture | How | Does |", "| --- | --- | --- |"]
    for r in rows:
        action = r.action or "—"
        if r.detail:
            action += f" ({r.detail})"
        if r.mnemonic:
            action += f" · _{r.mnemonic}_"
        if not r.enabled:
            action = f"~~{action}~~ off"
        lines.append(f"| {r.title} | {r.how} | {action} |")
    return lines


# Inline SVG symbols, one per gesture glyph, referenced with <use>. Monochrome, currentColor.
GLYPHS = """
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
<defs>
<symbol id="g-swipe-up" viewBox="0 0 24 24"><circle cx="12" cy="19.5" r="2.5"/><path d="M12 16V5M6.5 10.5L12 5l5.5 5.5" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="g-swipe-down" viewBox="0 0 24 24"><circle cx="12" cy="4.5" r="2.5"/><path d="M12 8v11M6.5 13.5L12 19l5.5-5.5" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="g-swipe-left" viewBox="0 0 24 24"><circle cx="19.5" cy="12" r="2.5"/><path d="M16 12H5M10.5 6.5L5 12l5.5 5.5" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="g-swipe-right" viewBox="0 0 24 24"><circle cx="4.5" cy="12" r="2.5"/><path d="M8 12h11M13.5 6.5L19 12l-5.5 5.5" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="g-tap-1" viewBox="0 0 24 24"><circle cx="12" cy="12" r="5"/></symbol>
<symbol id="g-tap-2" viewBox="0 0 24 24"><circle cx="7" cy="12" r="4"/><circle cx="17" cy="12" r="4"/></symbol>
<symbol id="g-tap-3" viewBox="0 0 24 24"><circle cx="4.5" cy="12" r="3.2"/><circle cx="12" cy="12" r="3.2"/><circle cx="19.5" cy="12" r="3.2"/></symbol>
<symbol id="g-tap-two-finger" viewBox="0 0 24 24"><circle cx="8" cy="8.5" r="4"/><circle cx="16" cy="15.5" r="4"/></symbol>
<symbol id="g-tap-pad-mod" viewBox="0 0 24 24"><circle cx="9" cy="12" r="4.5"/><rect x="17" y="4" width="4" height="16" rx="2"/></symbol>
<symbol id="g-hold" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="2.6"/><circle cx="12" cy="12" r="4"/></symbol>
<symbol id="g-mod-hold" viewBox="0 0 24 24"><rect x="3" y="4" width="6" height="16" rx="3"/><path d="M13 12h8M17 8l4 4-4 4" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="g-corner-bl" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="4" fill="none" stroke="currentColor" stroke-width="2"/><path d="M5 13v4a2 2 0 0 0 2 2h4z"/></symbol>
<symbol id="g-corner-br" viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="4" fill="none" stroke="currentColor" stroke-width="2"/><path d="M19 13v4a2 2 0 0 1-2 2h-4z"/></symbol>
<symbol id="g-pinch-in" viewBox="0 0 24 24"><circle cx="12" cy="12" r="2.2"/><path d="M2.5 12H8M5 9l3 3-3 3M21.5 12H16M19 9l-3 3 3 3" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="g-pinch-out" viewBox="0 0 24 24"><circle cx="12" cy="12" r="2.2"/><path d="M8.5 12H3M5.5 9L2.5 12l3 3M15.5 12H21M18.5 9l3 3-3 3" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="g-move" viewBox="0 0 24 24"><path d="M12 3v18M3 12h18M8 7l4-4 4 4M8 17l4 4 4-4M7 8l-4 4 4 4M17 8l4 4-4 4" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="g-scroll" viewBox="0 0 24 24"><rect x="8.5" y="3" width="7" height="18" rx="3.5" fill="none" stroke="currentColor" stroke-width="2.4"/><path d="M12 7v4" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/></symbol>
</defs>
</svg>
"""

CSS = """
:root { --fg: #18181b; --muted: #52525b; --faint: #a1a1aa; --line: #d4d4d8; --danger: #b91c1c; }
* { box-sizing: border-box; }
body { margin: 0; padding: 0; color: var(--fg); background: #e4e4e7;
       font: 12.5px/1.3 -apple-system, "SF Pro Text", Inter, "Segoe UI", sans-serif;
       -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.page { width: 1180px; margin: 16px auto; padding: 22px 26px; background: #fff; break-after: page; }
.page:last-child { break-after: auto; }
header { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin-bottom: 10px; }
header h1 { margin: 0; font-size: 24px; letter-spacing: -0.01em; }
header h1 small { font-size: 13px; font-weight: 500; color: var(--muted); margin-left: 10px; }
header .meta { color: var(--muted); font-size: 11px; }
kbd { display: inline-block; min-width: 20px; padding: 0 5px; margin-left: 2px; border-radius: 4px;
      border: 1px solid #a1a1aa; border-bottom-width: 2px; background: #fff; color: var(--fg);
      text-align: center; font: 11.5px/1.35 -apple-system, "SF Pro Text", Inter, sans-serif; }
.glyph { width: 22px; height: 22px; flex: none; color: var(--mode, #3f3f46); }
.tag { display: inline-block; padding: 0 5px; border-radius: 4px; font-size: 10px; font-weight: 700;
       letter-spacing: .03em; vertical-align: middle; }
.tag.danger { background: var(--danger); color: #fff; }
.note { display: block; font-size: 9.5px; font-weight: 500; color: var(--muted); }

/* Learn page */
.compass { display: grid; grid-template-columns: 1fr auto 1fr; gap: 14px; align-items: center;
           border: 2px solid var(--line); border-radius: 12px; padding: 10px 16px; margin-bottom: 12px; }
.compass .side { display: flex; flex-direction: column; gap: 8px; }
.compass .side.r { align-items: flex-end; text-align: right; }
.compass .side.r .mode { flex-direction: row-reverse; }
.compass .mode { display: flex; align-items: center; gap: 10px; }
.compass .mode .glyph { width: 28px; height: 28px; color: #fff; background: var(--mode); border-radius: 8px; padding: 4px; }
.compass .mode b { font-size: 15px; color: var(--mode); }
.compass .mode .hold { font-size: 11px; color: var(--muted); }
.compass .mode .mn { display: block; font-size: 11.5px; color: var(--muted); }
.compass .strip { text-align: center; }
.compass .strip .bar { width: 150px; height: 26px; border-radius: 13px; background: #27272a; margin: 0 auto 6px;
                       display: flex; align-items: center; justify-content: center; color: #fff; font-size: 11px; letter-spacing: .08em; }
.compass .strip .leds { font-size: 11px; color: var(--muted); }
.compass .strip .leds b { color: var(--fg); }
.maps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.map-card { border: 2px solid var(--mode); border-radius: 12px; padding: 10px 12px 8px; }
.map-card h2 { margin: 0 0 2px; font-size: 16px; color: var(--mode); display: flex; align-items: center; gap: 8px; }
.map-card h2 .led { margin-left: auto; font-size: 11px; color: var(--muted); font-weight: 500; }
.map-card p.enter { margin: 0 0 4px; color: var(--muted); font-size: 11px; min-height: 28px; }
.map { position: relative; height: 262px; margin: 4px 0 4px; }
.map svg.pad { position: absolute; inset: 0; width: 100%; height: 100%; }
.slot { position: absolute; font-size: 11px; line-height: 1.3; }
.slot .ln { display: flex; align-items: baseline; gap: 5px; white-space: nowrap; }
.slot .ln .g { color: var(--muted); font-size: 10px; }
.slot .ln b { font-weight: 650; }
.slot .ln.off b { text-decoration: line-through; color: var(--faint); }
.slot.up { top: 1%; left: 43.7%; transform: translateX(-50%); }
.slot.up .ln, .slot.down .ln, .slot.center .ln { justify-content: center; }
.slot.left { top: 32%; left: 2%; transform: translateY(-50%); }
.slot.right { top: 32%; left: 65%; transform: translate(-100%, -50%); }
.slot.right .ln { justify-content: flex-end; }
.slot.center { top: 53%; left: 43.7%; transform: translate(-50%, -50%); }
.slot.down { top: 76%; left: 43.7%; transform: translate(-50%, -50%); }
.slot.pinch { top: 76%; left: 2%; transform: translateY(-50%); }
.slot.bl { bottom: 0; left: 6%; }
.slot.br { bottom: 0; left: 73%; transform: translateX(-100%); }
.slot.br .ln { justify-content: flex-end; }
.slot.edge { top: 44%; left: 68.7%; transform: translate(-50%, -50%) rotate(90deg); white-space: nowrap; }
.slot.edge .ln .g { display: none; }
.slot.edge .ln b { font-weight: 600; font-size: 10px; color: var(--muted); }
.corner-name { font-size: 9.5px; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; }
.fingertip { position: absolute; top: 1px; left: 15.5%; font-size: 10px; color: var(--muted); }
.modbar { border-top: 1px dashed var(--line); margin-top: 2px; padding-top: 5px; font-size: 11px; display: grid; grid-template-columns: auto 1fr; gap: 2px 8px; align-items: baseline; }
.modbar .lead { color: var(--mode); font-weight: 700; grid-column: 1 / -1; }
.modbar .ln { display: contents; }
.modbar .ln .g { color: var(--muted); font-size: 10px; white-space: nowrap; } .modbar .ln b { font-weight: 650; }
.air-card { border: 2px solid var(--mode); border-radius: 12px; padding: 10px 12px; display: grid; grid-template-columns: 1fr 2.4fr; gap: 12px; align-items: start; margin-top: 12px; }
.air-card h2 { margin: 0 0 4px; font-size: 16px; color: var(--mode); }
.air-card p { margin: 0; font-size: 11.5px; color: var(--muted); }
.air-card .lines { display: flex; flex-wrap: wrap; gap: 4px 16px; margin-top: 6px; }
.air-card .ln { display: flex; gap: 6px; align-items: baseline; white-space: nowrap; font-size: 11.5px; }
.air-card .ln .g { color: var(--muted); font-size: 10px; } .air-card .ln b { font-weight: 650; }
.daily { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 12px; }
.cmd { border: 1px solid var(--line); border-radius: 10px; padding: 8px 10px; display: grid; grid-template-columns: 54px 1fr; gap: 10px; align-items: center; }
.cmd .bar, .ladder .bar { display: flex; gap: 3px; }
.cmd .bar i, .ladder .bar i { width: 14px; height: 10px; border-radius: 2px; background: #e4e4e7; border: 1px solid #d4d4d8; }
.cmd .bar i.on, .ladder .bar i.on { background: #52525b; border-color: #52525b; }
.cmd .bar i.bright, .ladder .bar i.bright { background: #09090b; border-color: #09090b; }
.cmd b { display: block; font-size: 12.5px; } .cmd span { font-size: 11px; color: var(--muted); }
.cmd .peg, .ladder .peg { font-size: 10.5px; color: var(--mode, var(--muted)); font-style: italic; }
footer { margin-top: 10px; color: var(--muted); font-size: 10.5px; display: flex; gap: 16px; flex-wrap: wrap; }

/* Reference page */
.ref { display: grid; grid-template-columns: 1fr 1fr 1fr 250px; gap: 12px; align-items: start; }
.ref > div { display: flex; flex-direction: column; gap: 12px; }
.panel { border: 1px solid var(--line); border-top: 3px solid var(--mode, #3f3f46); border-radius: 8px; padding: 8px 12px 10px; break-inside: avoid; }
.panel h2 { margin: 0 0 4px; font-size: 14px; color: var(--mode, var(--fg)); }
.panel h3 { margin: 8px 0 2px; font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: .07em; }
.g { display: grid; grid-template-columns: 22px 1fr auto; gap: 0 8px; }
.g .row { display: contents; }
.g .row > * { padding: 3px 0; border-top: 1px solid #ececef; }
.g .row:first-child > * { border-top: 0; }
.g .glyph { width: 18px; height: 18px; margin-top: 1px; }
.g .gest b { font-weight: 600; font-size: 11.5px; }
.g .gest .how, .g .gest .mn { color: var(--muted); font-size: 10px; }
.g .gest .mn { font-style: italic; color: var(--mode); }
.g .act { text-align: right; font-weight: 650; font-size: 11.5px; max-width: 150px; }
.g .act.plain { font-weight: 500; color: var(--muted); }
.g .act .caps { display: block; }
.g .row.off .act, .g .row.off .gest b { text-decoration: line-through; color: var(--faint); }
.g .row.off .act::after { content: "off"; text-decoration: none; display: inline-block; margin-left: 5px; padding: 0 4px; border-radius: 3px; background: #3f3f46; color: #fff; font-size: 9.5px; font-weight: 700; }
.unassigned { font-size: 10.5px; color: var(--muted); margin: 4px 0 0; }
.ladder { margin: 0; padding: 0; list-style: none; }
.ladder li { display: grid; grid-template-columns: 54px 1fr; gap: 10px; align-items: center; padding: 5px 0; border-top: 1px solid #ececef; }
.ladder li:first-child { border-top: 0; }
.ladder .what { font-weight: 650; font-size: 12px; } .ladder .what span { font-weight: 500; color: var(--muted); }
.ladder li.danger .what { color: var(--danger); }
.notes { margin: 0; padding-left: 16px; font-size: 11px; color: var(--muted); }
.notes li { margin: 2px 0; }
section[data-active="true"] { box-shadow: 0 0 0 3px var(--mode); }
.row[data-last="true"] > *, .ln[data-last="true"] { background: #fef3c7; }
@page { size: letter landscape; margin: 7mm; }
@media print {
  body { background: #fff; }
  .page { width: auto; margin: 0; padding: 4px 2px; }
  .maps { gap: 10px; } .map { height: 236px; }
  header h1 { font-size: 20px; }
}
"""

# The trackpad as seen with the finger pointing up: pad, scroll edge on its right side, the two
# bottom corners, and the Modstrip beside it. Slots are positioned over this in CSS.
MAP_SVG = """
<svg class="pad" viewBox="0 0 300 262" preserveAspectRatio="none" aria-hidden="true">
  <rect x="46" y="30" width="170" height="186" rx="24" fill="#fafafa" stroke="var(--mode)" stroke-width="2.5"/>
  <rect x="198" y="42" width="16" height="162" rx="7" fill="#fff" stroke="var(--mode)" stroke-width="1.5" stroke-dasharray="4 3"/>
  <path d="M46 178v14a24 24 0 0 0 24 24h22z M216 178v14a24 24 0 0 1-24 24h-22z" fill="var(--mode)" opacity=".22"/>
  <rect x="250" y="30" width="32" height="186" rx="11" fill="#f4f4f5" stroke="#52525b" stroke-width="2"/>
  <text x="266" y="123" text-anchor="middle" font-size="9.5" font-weight="700" fill="#52525b" transform="rotate(-90 266 123)" font-family="-apple-system, Inter, sans-serif">MODSTRIP</text>
</svg>
"""


def _kbd(keys: tuple[str, ...]) -> str:
    return "".join(f"<kbd>{html.escape(k)}</kbd>" for k in keys)


def _glyph(name: str, extra: str = "") -> str:
    if not name:
        return f'<span class="glyph {extra}"></span>'
    return f'<svg class="glyph {extra}" aria-hidden="true"><use href="#g-{name}"/></svg>'


def _action_html(r: Row, *, caps_on_own_line: bool = True) -> str:
    e = html.escape
    if r.source == "builtin":
        return e(r.action)
    if r.source == "unassigned":
        return "—"
    if r.keys and r.action == caps_text(r.keys):
        return _kbd(r.keys)
    if r.keys:
        caps = (
            f'<span class="caps">{_kbd(r.keys)}</span>' if caps_on_own_line else f" {_kbd(r.keys)}"
        )
        return f"{e(r.action)}{caps}"
    return e(r.action)


def _line(r: Row, short: str = "", *, notes: bool = True) -> str:
    """One compact 'gesture → action' line for maps, cards, and bars."""
    e = html.escape
    off = "" if r.enabled else " off"
    note = f'<span class="note">{e(r.note)}</span>' if notes and r.note else ""
    return (
        f'<div class="ln{off}" data-gesture="{e(r.gesture)}"><span class="g">{e(short or r.title)}</span>'
        f"<b>{_action_html(r, caps_on_own_line=False)}</b>{note}</div>"
    )


def _map_card(
    sheet: Sheet, section: Section, rows: list[Row], groups: list[tuple[str, list[Row]]]
) -> str:
    e = html.escape
    m = MODE_META[section.key]
    featured = [
        r
        for r in rows
        if r.tier in (FIRST, NEXT) and r.zone and r.zone != "air" and r.source != "unassigned"
    ]
    by_zone: dict[str, list[Row]] = {}
    for r in featured:
        by_zone.setdefault(r.zone, []).append(r)

    def slot(zone: str, heading: str = "") -> str:
        items = by_zone.get(zone, [])
        if not items:
            return ""
        lines = [f'<div class="corner-name">{e(heading)}</div>'] if heading else []
        for r in items:
            if zone in ("bl", "br"):
                label = "hold" if "hold" in r.title.lower() else "2×"
            else:
                label = SHORT.get(r.title, r.title)
            lines.append(_line(r, label, notes=False))
        return f'<div class="slot {zone}">{"".join(lines)}</div>'

    mod_rows = by_zone.get("modstrip", []) + [
        r for _n, grs in groups for r in grs if r.tier in (FIRST, NEXT) and r.source != "unassigned"
    ]
    modbar = ""
    if mod_rows:
        modbar = (
            '<div class="modbar"><span class="lead">Modstrip</span>'
            + "".join(
                _line(r, r.title.replace("Modstrip ", "").replace("Mod + ", "+ "), notes=False)
                for r in mod_rows
            )
            + "</div>"
        )
    return (
        f'<section class="map-card" data-mode="{section.key}" style="--mode:{m["color"]}">'
        f'<h2>{e(section.title)}<span class="led">LED {m["led"]}</span></h2>'
        f'<p class="enter">{e(sheet.mode_mnemonics[section.key])} {e(section.enter.split(".")[0])}.</p>'
        f'<div class="map">{MAP_SVG}<div class="fingertip">fingertip ↑</div>'
        f"{slot('up')}{slot('left')}{slot('right')}{slot('center')}{slot('down')}{slot('pinch')}"
        f"{slot('edge')}{slot('bl', 'bottom-left')}{slot('br', 'bottom-right')}</div>{modbar}</section>"
    )


def _compass(sheet: Sheet) -> str:
    e = html.escape

    def mode(key: str, glyph: str, hold: bool) -> str:
        m = MODE_META[key]
        title = {"cursor": "Cursor", "navigation": "Navigation", "touch": "Touch", "air": "Air"}[
            key
        ]
        hold_txt = '<span class="hold">+ hold</span>' if hold else ""
        return (
            f'<div class="mode" data-mode="{key}" style="--mode:{m["color"]}">{_glyph(glyph)}'
            f'<div><b>{title}</b> {hold_txt}<span class="mn">{e(sheet.mode_mnemonics[key])}</span></div></div>'
        )

    return (
        '<div class="compass">'
        f'<div class="side">{mode("cursor", "swipe-left", False)}{mode("air", "swipe-left", True)}</div>'
        '<div class="strip"><div class="bar">MODSTRIP</div>'
        '<div class="leds"><b>Mode N flashes LED N</b>: Cursor 1 · Navigation 2 · Touch 3 · Air all three.<br>'
        "Left is the mouse hand; right is the reading hand. Add a hold to go further.</div></div>"
        f'<div class="side r">{mode("navigation", "swipe-right", False)}{mode("touch", "swipe-right", True)}</div>'
        "</div>"
    )


def _bars(n: int) -> str:
    lit = ((n - 1) % 3) + 1
    bright = n > 3
    return (
        '<div class="bar">'
        + "".join(
            f'<i class="{"on bright" if (i < lit and bright) else "on" if i < lit else ""}"></i>'
            for i in range(3)
        )
        + "</div>"
    )


def _count(r: Row) -> int:
    head = r.title.split("×")[0]
    return int(head) if head.isdigit() else 0


def _daily_commands(system_rows: list[Row]) -> str:
    e = html.escape
    cards = []
    for r in system_rows:
        n = _count(r)
        if r.tier in (FIRST, NEXT) and (n or "palm" in r.title.lower()):
            bar = (
                _bars(n)
                if n
                else '<div class="bar"><i class="on bright"></i><i class="on bright"></i><i class="on bright"></i></div>'
            )
            peg = f'<div class="peg">{e(r.mnemonic)}</div>' if r.mnemonic else ""
            cards.append(
                f'<div class="cmd">{bar}<div><b>{e(r.title)}</b><span>{e(r.action)}</span>{peg}</div></div>'
            )
    return f'<div class="daily">{"".join(cards)}</div>'


def _family(rows: list[Row]) -> list[tuple[str, list[Row]]]:
    """Group reference rows by input family so similar motions sit together."""
    buckets: dict[str, list[Row]] = {
        "Swipes · hold any swipe to repeat": [],
        "Taps": [],
        "Corners": [],
        "Edge and Modstrip": [],
        "Pinch": [],
        "In the air": [],
        "Other": [],
    }
    for r in rows:
        t = r.title.lower()
        if r.zone == "air" or "air" in t:
            buckets["In the air"].append(r)
        elif "swipe" in t:
            buckets["Swipes · hold any swipe to repeat"].append(r)
        elif r.zone in ("bl", "br"):
            buckets["Corners"].append(r)
        elif r.zone in ("edge", "modstrip") or "modstrip" in t or "scroll" in t:
            buckets["Edge and Modstrip"].append(r)
        elif "pinch" in t:
            buckets["Pinch"].append(r)
        elif "tap" in t or "hold" in t:
            buckets["Taps"].append(r)
        else:
            buckets["Other"].append(r)
    return [(name, rs) for name, rs in buckets.items() if rs]


def _rows_html(rows: list[Row]) -> str:
    e = html.escape
    assigned = [r for r in rows if r.source != "unassigned"]
    unassigned = [r for r in rows if r.source == "unassigned"]
    out = ['<div class="g">']
    for r in assigned:
        cls = "row" if r.enabled else "row off"
        gest = f"<b>{e(r.title)}</b>"
        show_how = (
            r.how
            and r.how not in OBVIOUS_HOW
            and (r.source == "builtin" or r.zone in ("", "edge", "modstrip"))
        )
        if show_how:
            gest += f'<div class="how">{e(r.how)}</div>'
        if r.mnemonic:
            gest += f'<div class="mn">{e(r.mnemonic)}</div>'
        note = f'<span class="note">{e(r.note)}</span>' if r.note else ""
        act_cls = "act plain" if r.source == "builtin" else "act"
        detail = (
            f'<div class="how">{e(r.detail)}</div>'
            if r.detail and not r.keys and r.source == "profile"
            else ""
        )
        out.append(
            f'<div class="{cls}" data-gesture="{e(r.gesture)}">{_glyph(r.glyph)}'
            f'<div class="gest">{gest}</div><div class="{act_cls}">{_action_html(r)}{note}{detail}</div></div>'
        )
    out.append("</div>")
    if unassigned:
        out.append(
            f'<p class="unassigned">Unassigned: {e(", ".join(r.title for r in unassigned))}</p>'
        )
    return "".join(out)


def _ladder(rows: list[Row]) -> str:
    e = html.escape
    items = []
    for r in rows:
        n = _count(r)
        if n:
            danger = " danger" if n >= DANGER_FROM else ""
            tag = ' <span class="tag danger">careful</span>' if danger else ""
            peg = f'<div class="peg">{e(r.mnemonic)}</div>' if r.mnemonic else ""
            items.append(
                f'<li class="l{danger}">{_bars(n)}<div><div class="what">{e(r.title)}{tag} '
                f"<span>{e(r.action)}</span></div>{peg}</div></li>"
            )
        elif "palm" in r.title.lower():
            items.append(
                '<li><div class="bar"><i class="on bright"></i><i class="on bright"></i><i class="on bright"></i></div>'
                f'<div><div class="what">{e(r.title)} <span>{e(r.action)}</span></div>'
                f'<div class="peg">{e(r.how)}</div></div></li>'
            )
    return f'<ul class="ladder">{"".join(items)}</ul>'


def render_html(sheet: Sheet) -> str:
    e = html.escape
    by_key = {section.key: (section, rows, groups) for section, rows, groups in sheet.sections}
    system, system_rows, _ = by_key["system"]
    meta = f"firmware {e(sheet.firmware)}"
    if sheet.profile_name:
        meta = f"profile {e(sheet.profile_name)} · " + meta

    page1 = [
        '<div class="page learn">',
        f'<header><h1>{e(sheet.title)}<small>learn page</small></h1><span class="meta">{meta}</span></header>',
        _compass(sheet),
        '<div class="maps">',
    ]
    for key in ("cursor", "navigation", "touch"):
        section, rows, groups = by_key[key]
        page1.append(_map_card(sheet, section, rows, groups))
    page1.append("</div>")
    air, air_rows, air_groups = by_key["air"]
    air_assigned = [
        r for r in air_rows + [r for _n, g in air_groups for r in g] if r.source != "unassigned"
    ]
    air_lines = (
        "".join(_line(r) for r in air_assigned)
        or '<div class="ln"><span class="g">nothing assigned in this profile</span></div>'
    )
    page1.append(
        f'<section class="air-card" data-mode="air" style="--mode:{MODE_META["air"]["color"]}">'
        f"<div><h2>Air</h2><p>{e(sheet.mode_mnemonics['air'])}</p></div>"
        f'<div><p>{e(air.enter)}</p><div class="lines">{air_lines}</div></div></section>'
    )
    page1.append(_daily_commands(system_rows))
    page1.append(
        "<footer><span>Light touch: glide, don't press.</span>"
        "<span>Struck-through actions are switched off in this profile.</span>"
        "<span>Everything else, and the full tap ladder, is on the reference page.</span></footer></div>"
    )

    page2 = [
        '<div class="page reference">',
        f'<header><h1>{e(sheet.title)}<small>reference page</small></h1><span class="meta">{meta}</span></header>',
        '<div class="ref">',
    ]
    for key in ("cursor", "navigation", "touch"):
        section, rows, groups = by_key[key]
        m = MODE_META[key]
        page2.append(
            f'<div><section class="panel" data-mode="{key}" style="--mode:{m["color"]}">'
            f"<h2>{e(section.title)}</h2>"
        )
        for name, rs in _family(rows):
            page2.append(f"<h3>{e(name)}</h3>{_rows_html(rs)}")
        for name, group_rows in groups:
            page2.append(f"<h3>{e(name)}</h3>{_rows_html(group_rows)}")
        page2.append("</section></div>")
    m = MODE_META["air"]
    page2.append(
        f'<div><section class="panel" data-mode="air" style="--mode:{m["color"]}"><h2>Air</h2>'
        f'<p class="unassigned">{e(air.enter)}</p>{_rows_html(air_rows)}'
    )
    for name, group_rows in air_groups:
        page2.append(f"<h3>{e(name)}</h3>{_rows_html(group_rows)}")
    page2.append("</section>")
    page2.append(
        f'<section class="panel" data-mode="system" style="--mode:{MODE_META["system"]["color"]}">'
        f'<h2>Modstrip tap ladder</h2><p class="unassigned">{e(system.enter)}</p>{_ladder(system_rows)}</section>'
    )
    page2.append(
        '<section class="panel"><h2>Worth knowing</h2><ul class="notes">'
        "<li>A recognized gesture ticks the mode's LED once; that tick is your confirmation.</li>"
        "<li>The ring starts in the mode it was last in.</li>"
        "<li>Hold left button latches a drag; a single tap releases it.</li>"
        "<li>Tap + hold temporary pointer needs Multi-tap recognition on in Studio.</li>"
        "<li>Chords marked Windows were authored for Windows; ⌘ is what a Mac receives.</li>"
        "<li>In App Status the ring is not a mouse; 3× tap + hold brings it back.</li>"
        "</ul></section></div>"
    )
    page2.append("</div></div>")

    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en"><head><meta charset="utf-8">',
            f"<title>{e(sheet.title)}</title>",
            f"<style>{CSS}</style></head><body>",
            GLYPHS,
            *page1,
            *page2,
            "</body></html>\n",
        ]
    )


def render(profile_path: Path, labels_path: Path | None, fmt: str) -> str:
    raw = profile_path.read_bytes()
    sheet = build(
        load_profile(profile_path),
        load_labels(labels_path),
        profile_name=profile_path.name,
        profile_hash=hashlib.sha256(raw).hexdigest()[:12],
    )
    return render_html(sheet) if fmt == "html" else render_markdown(sheet)
