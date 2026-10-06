"""Render a cheat sheet from a Prolo Studio profile export, labelled with what each gesture does
on this machine. No ring needed.

The HTML is built for recall, not lookup: four colour-coded modes with a mnemonic each, gestures
anchored to a drawing of the ring, a glyph per gesture, chords as keycaps, and the Modstrip tap
ladder drawn as the LED bar the ring shows while you tap."""

from __future__ import annotations

import hashlib
import html
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .catalogue import FIRMWARE, SECTIONS, Gesture, Section
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
    "Left Button Down (Hold)": "Hold left button",
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

MODE_META = {
    "cursor": {"color": "#2563eb", "leds": "●○○", "mnemonic": "Swipe left: point and click."},
    "navigation": {
        "color": "#059669",
        "leds": "○●○",
        "mnemonic": "Swipe right: read, browse, present.",
    },
    "touch": {"color": "#d97706", "leds": "○○●", "mnemonic": "Right and hold: tunes and volume."},
    "air": {"color": "#7c3aed", "leds": "●●●", "mnemonic": "Left and hold: lift off the surface."},
    "system": {"color": "#52525b", "leds": "", "mnemonic": "Count the taps, then hold."},
}
# Rhyme pegs for the Modstrip ladder: the count is the cue, the rhyme is the action.
LADDER_PEGS = {
    "1": "one: back on",
    "2": "two: pair new",
    "3": "three: App or free",
    "4": "four: to the floor",
    "5": "five: wipe",
    "6": "six: fix",
    "7": "seven: switch style",
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


def glyph_for(name: str) -> str:
    tail = name.split(".", 1)[-1] if name else ""
    if "pinch_in" in tail:
        return "pinch-in"
    if "pinch_out" in tail:
        return "pinch-out"
    for direction in ("up", "down", "left", "right"):
        if tail.endswith(f"swipe_{direction}"):
            return f"swipe-{direction}"
    if tail.endswith("triple_tap"):
        return "tap-3"
    if tail.endswith("double_tap"):
        return "tap-2"
    if tail.endswith("long_hold"):
        return "hold"
    if tail.endswith("two_finger_tap") or tail.endswith("modstrip_tap"):
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
        if not gesture.name:
            peg = LADDER_PEGS.get(gesture.title.split("×")[0], "") if "×" in gesture.title else ""
            return Row(
                "", gesture.title, gesture.how, gesture.builtin, "", on, "builtin", glyph, peg
            )
        key = GESTURES_BY_NAME.get(gesture.name)
        entry = profile.get(key, {}) if key else {}
        raw = describe(entry)
        keys = _chord_keys(entry)
        custom = gesture_labels.get(gesture.name)
        label = custom.get("label") if isinstance(custom, dict) else custom
        mnemonic = str(custom.get("mnemonic", "")) if isinstance(custom, dict) else ""
        alias = str(entry.get("gestureAlias", ""))
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
            )
        return Row(gesture.name, gesture.title, gesture.how, "", "", on, "unassigned", glyph)

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
<symbol id="g-hold" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="2.6"/><circle cx="12" cy="12" r="4"/></symbol>
<symbol id="g-pinch-in" viewBox="0 0 24 24"><path d="M3.5 3.5l6 6M20.5 20.5l-6-6M3.5 20.5l6-6M20.5 3.5l-6 6" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/><circle cx="12" cy="12" r="2.4"/></symbol>
<symbol id="g-pinch-out" viewBox="0 0 24 24"><path d="M9.5 9.5l-6-6M14.5 14.5l6 6M9.5 14.5l-6 6M14.5 9.5l6-6" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/><circle cx="12" cy="12" r="2.4"/></symbol>
<symbol id="g-move" viewBox="0 0 24 24"><path d="M12 3v18M3 12h18M8 7l4-4 4 4M8 17l4 4 4-4M7 8l-4 4 4 4M17 8l4 4-4 4" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="g-scroll" viewBox="0 0 24 24"><rect x="8.5" y="3" width="7" height="18" rx="3.5" fill="none" stroke="currentColor" stroke-width="2.4"/><path d="M12 7v4" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/></symbol>
</defs>
</svg>
"""

# A schematic of the ring from the thumb's side, worn on the right index finger: trackpad in the
# middle, Modstrip at the edge, LEDs on the rim. The legend beside it names each zone.
RING_SVG = """
<svg viewBox="0 0 320 230" class="ring" role="img" aria-label="Ring layout">
  <rect x="22" y="30" width="276" height="150" rx="36" fill="#f4f4f5" stroke="#a1a1aa" stroke-width="2"/>
  <rect x="60" y="54" width="150" height="102" rx="10" fill="#fff" stroke="#3f3f46" stroke-width="2"/>
  <rect x="190" y="54" width="20" height="102" fill="#e0f2fe"/>
  <rect x="60" y="130" width="34" height="26" rx="6" fill="#fde68a"/>
  <rect x="176" y="130" width="34" height="26" rx="6" fill="#fde68a"/>
  <rect x="226" y="54" width="22" height="102" rx="6" fill="#ede9fe" stroke="#6d28d9" stroke-width="2"/>
  <circle cx="276" cy="80" r="4.5" fill="#71717a"/><circle cx="276" cy="105" r="4.5" fill="#71717a"/><circle cx="276" cy="130" r="4.5" fill="#71717a"/>
  <g font-family="-apple-system, Inter, sans-serif" font-size="11" fill="#27272a">
    <text x="135" y="100" text-anchor="middle" font-weight="700" font-size="12">TRACKPAD</text>
    <text x="135" y="116" text-anchor="middle" fill="#71717a">thumb</text>
    <text x="237" y="108" text-anchor="middle" font-weight="700" fill="#6d28d9" transform="rotate(-90 237 108)">MODSTRIP</text>
    <text x="200" y="48" text-anchor="middle" fill="#0369a1" font-size="10">scroll edge</text>
    <text x="77" y="172" text-anchor="middle" font-size="10">corner BL</text>
    <text x="193" y="172" text-anchor="middle" font-size="10">corner BR</text>
    <text x="276" y="154" text-anchor="middle" fill="#52525b" font-size="10">LEDs</text>
    <text x="160" y="205" text-anchor="middle" fill="#71717a">Modstrip: left index finger · Trackpad: right thumb · charging pad inside the band</text>
  </g>
</svg>
"""

CSS = """
:root { --fg: #18181b; --muted: #71717a; --line: #e4e4e7; --soft: #fafafa; }
* { box-sizing: border-box; }
body { margin: 0; padding: 20px 24px; color: var(--fg); background: #fff;
       font: 13px/1.35 -apple-system, "SF Pro Text", Inter, "Segoe UI", sans-serif; }
header { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; margin-bottom: 4px; }
header h1 { margin: 0; font-size: 24px; letter-spacing: -0.01em; }
header .meta { color: var(--muted); font-size: 11px; }
p.key { margin: 0 0 12px; color: var(--muted); font-size: 11.5px; }
p.key kbd { font-size: 10.5px; min-width: 16px; padding: 0 4px; }
.modes { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px; }
.mode-tab { border-radius: 10px; padding: 9px 12px; color: #fff; display: flex; gap: 10px; align-items: center; }
.mode-tab .leds { font-size: 16px; letter-spacing: 2px; }
.mode-tab b { font-size: 15px; display: block; }
.mode-tab .mn { font-size: 12px; opacity: .92; display: block; }
.layout { display: grid; grid-template-columns: 290px 1fr 1fr 270px; gap: 14px; align-items: start; }
.layout > div { display: flex; flex-direction: column; gap: 14px; }
.panel { border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; background: #fff; break-inside: avoid; }
.panel h2 { margin: 0 0 4px; font-size: 15px; display: flex; align-items: center; gap: 8px; }
.panel h2 .swatch { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.panel h2 .leds { font-size: 13px; letter-spacing: 2px; margin-left: auto; }
.panel p.enter { margin: 0 0 8px; color: var(--muted); font-size: 11.5px; }
.panel h3 { margin: 10px 0 4px; font-size: 10.5px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
.ring { width: 100%; height: auto; display: block; margin: 2px 0 8px; }
.legend { margin: 0; padding: 0; list-style: none; font-size: 12px; }
.legend li { padding: 3px 0; border-top: 1px solid var(--line); display: flex; gap: 8px; }
.legend li b { min-width: 92px; flex: none; }
.g { display: grid; grid-template-columns: 30px 1fr auto; gap: 0 10px; }
.g .row { display: contents; }
.g .row > * { padding: 5px 0; border-top: 1px solid var(--line); }
.g .row:first-child > * { border-top: 0; }
.g .glyph { width: 24px; height: 24px; padding: 4px; border-radius: 7px; margin-top: 1px;
            color: var(--mode, #52525b); background: color-mix(in srgb, var(--mode, #52525b) 13%, #fff); }
.g .glyph.blank { background: none; }
.g .gest { min-width: 0; }
.g .gest b { font-weight: 600; font-size: 12.5px; }
.g .gest .how { color: var(--muted); font-size: 11px; }
.g .gest .mn { color: var(--mode, var(--muted)); font-size: 11px; font-style: italic; }
.g .act { text-align: right; font-weight: 650; font-size: 13px; max-width: 190px; }
.g .act.plain { font-weight: 500; font-size: 12px; color: #3f3f46; }
.g .act .caps { display: block; margin-top: 2px; }
.g .act.unassigned { font-weight: 400; color: #a1a1aa; }
.g .row.off > * { opacity: .38; }
.g .row.off .act::after { content: "off"; display: inline-block; margin-left: 6px; padding: 0 5px;
                          border-radius: 4px; background: #e4e4e7; color: #3f3f46; font-size: 10px; font-weight: 600; }
kbd { display: inline-block; min-width: 21px; padding: 1px 5px; margin-left: 2px; border-radius: 5px;
      border: 1px solid #d4d4d8; border-bottom-width: 2px; background: var(--soft); color: var(--fg);
      text-align: center; font: 11.5px/1.3 -apple-system, "SF Pro Text", Inter, sans-serif; }
.ladder { margin: 0; padding: 0; list-style: none; }
.ladder li { display: grid; grid-template-columns: 54px 1fr; gap: 10px; align-items: center; padding: 5px 0; border-top: 1px solid var(--line); }
.ladder li:first-child { border-top: 0; }
.ladder .bar { display: flex; gap: 3px; }
.ladder .bar i { width: 14px; height: 9px; border-radius: 2px; background: #e4e4e7; }
.ladder .bar i.on { background: #52525b; }
.ladder .bar i.bright { background: #0a0a0a; box-shadow: 0 0 0 1px #0a0a0a; }
.ladder .peg { font-size: 11px; color: var(--muted); font-style: italic; }
.ladder .what { font-weight: 600; font-size: 12.5px; }
.ladder .what span { font-weight: 500; color: #3f3f46; }
.ladder .hint { font-size: 11px; color: var(--muted); }
.swipes { display: grid; grid-template-columns: 1fr 1fr; gap: 5px 10px; margin: 4px 0 10px; font-size: 12.5px; }
.swipes div { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.swipes svg { width: 20px; height: 20px; flex: none; }
.swipes small { color: var(--muted); font-size: 11px; }
footer { margin-top: 12px; color: var(--muted); font-size: 11px; display: flex; gap: 18px; flex-wrap: wrap; }
section[data-active="true"] { box-shadow: 0 0 0 2px var(--mode); }
.row[data-last="true"] > * { background: #fef3c7; }
@page { size: landscape; margin: 9mm; }
@media print {
  body { padding: 0; font-size: 11.5px; }
  .layout { grid-template-columns: 235px 1fr 1fr 225px; gap: 9px; }
  .panel { padding: 8px 10px; border-radius: 6px; }
  header h1 { font-size: 20px; }
}
"""


def _kbd(keys: tuple[str, ...]) -> str:
    return "".join(f"<kbd>{html.escape(k)}</kbd>" for k in keys)


def _glyph(name: str, extra: str = "") -> str:
    if not name:
        return f'<span class="glyph blank {extra}"></span>'
    return f'<svg class="glyph {extra}" aria-hidden="true"><use href="#g-{name}"/></svg>'


def _gesture_rows(rows: list[Row]) -> str:
    e = html.escape
    out = ['<div class="g">']
    for r in rows:
        cls = "row" if r.enabled else "row off"
        gest = f"<b>{e(r.title)}</b>"
        if r.how and r.how.lower() != r.title.lower() and r.source != "unassigned":
            gest += f'<div class="how">{e(r.how)}</div>'
        if r.mnemonic:
            gest += f'<div class="mn">{e(r.mnemonic)}</div>'
        if r.source == "builtin":
            act = f'<div class="act plain">{e(r.action)}</div>'
        elif r.source == "unassigned":
            act = '<div class="act unassigned">—</div>'
        elif r.keys and r.action == caps_text(r.keys):
            act = f'<div class="act">{_kbd(r.keys)}</div>'
        elif r.keys:
            act = f'<div class="act">{e(r.action)}<span class="caps">{_kbd(r.keys)}</span></div>'
        else:
            detail = f'<div class="how">{e(r.detail)}</div>' if r.detail else ""
            act = f'<div class="act">{e(r.action)}{detail}</div>'
        out.append(
            f'<div class="{cls}" data-gesture="{e(r.gesture)}">{_glyph(r.glyph)}'
            f'<div class="gest">{gest}</div>{act}</div>'
        )
    out.append("</div>")
    return "".join(out)


def _ladder(rows: list[Row]) -> str:
    e = html.escape
    items = []
    for r in rows:
        count = r.title.split("×")[0] if "×" in r.title else ""
        if count.isdigit():
            n = int(count)
            lit = ((n - 1) % 3) + 1
            bars = "".join(
                f'<i class="{"on bright" if (i < lit and n > 3) else "on" if i < lit else ""}"></i>'
                for i in range(3)
            )
            peg = f'<div class="peg">{e(r.mnemonic)}</div>' if r.mnemonic else ""
            items.append(
                f'<li><div class="bar" title="{n} taps">{bars}</div>'
                f'<div><div class="what">{e(r.title)} <span>{e(r.action)}</span></div>{peg}</div></li>'
            )
        elif "palm" in r.title.lower():
            items.append(
                '<li><div class="bar"><i class="on bright"></i><i class="on bright"></i>'
                f'<i class="on bright"></i></div><div><div class="what">{e(r.title)} '
                f'<span>{e(r.action)}</span></div><div class="hint">{e(r.how)}</div></div></li>'
            )
    return f'<ul class="ladder">{"".join(items)}</ul>'


def _mode_swipes(rows: list[Row]) -> str:
    e = html.escape
    glyph = {
        "Swipe left": "swipe-left",
        "Swipe right": "swipe-right",
        "Swipe right + hold": "swipe-right",
        "Swipe left + hold": "swipe-left",
    }
    out = ['<div class="swipes">']
    for r in rows:
        if r.title in glyph:
            mode = r.action.split()[0]
            color = MODE_META.get(mode.lower(), {}).get("color", "#52525b")
            hold = "<small>+ hold</small>" if "hold" in r.title else ""
            out.append(
                f'<div style="color:{color}">{_glyph(glyph[r.title])}'
                f'<span style="color:var(--fg)"><b>{e(mode)}</b></span>{hold}</div>'
            )
    out.append("</div>")
    return "".join(out)


def render_html(sheet: Sheet) -> str:
    e = html.escape
    by_key = {section.key: (section, rows, groups) for section, rows, groups in sheet.sections}
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{e(sheet.title)}</title>",
        f"<style>{CSS}</style></head><body>",
        GLYPHS,
        f"<header><h1>{e(sheet.title)}</h1>",
    ]
    meta = f"firmware {e(sheet.firmware)}"
    if sheet.profile_name:
        meta = f"profile {e(sheet.profile_name)} · {e(sheet.profile_hash)} · " + meta
    parts.append(f'<span class="meta">{meta}</span></header>')
    parts.append(
        '<p class="key">Colour is the mode · dots are the LEDs you will see · '
        "<kbd>⌘</kbd><kbd>D</kbd> is what the ring sends · dimmed rows are off in this profile</p>"
    )

    parts.append('<div class="modes">')
    for key in ("cursor", "navigation", "touch", "air"):
        section = by_key[key][0]
        m = MODE_META[key]
        parts.append(
            f'<div class="mode-tab" data-mode="{key}" style="background:{m["color"]}">'
            f'<span class="leds">{m["leds"]}</span><div><b>{e(section.title)}</b>'
            f'<span class="mn">{e(sheet.mode_mnemonics[key])}</span></div></div>'
        )
    parts.append("</div>")

    parts.append('<div class="layout">')
    system, system_rows, _ = by_key["system"]
    parts.append('<div><section class="panel" data-mode="anatomy"><h2>Where things are</h2>')
    parts.append(RING_SVG)
    parts.append(
        '<ul class="legend">'
        "<li><b>Trackpad</b><span>pointer, taps, swipes; the bottom corners are hot zones</span></li>"
        "<li><b>Scroll edge</b><span>slide along it to scroll without leaving Cursor</span></li>"
        "<li><b>Modstrip</b><span>mode swipes, system commands, Mod-held gestures</span></li>"
        "<li><b>LEDs</b><span>flash the mode number; count the bar while you tap</span></li>"
        "</ul></section>"
    )
    parts.append(
        f'<section class="panel" data-mode="system" style="--mode:{MODE_META["system"]["color"]}">'
        f'<h2>Modstrip</h2><p class="enter">{e(sheet.mode_mnemonics["system"])} '
        f"{e(system.enter)}</p>{_mode_swipes(system_rows)}{_ladder(system_rows)}</section></div>"
    )
    for pair in (("cursor", "air"), ("navigation", "touch")):
        parts.append("<div>")
        for key in pair:
            section, rows, groups = by_key[key]
            m = MODE_META[key]
            parts.append(
                f'<section class="panel" data-mode="{key}" style="--mode:{m["color"]}">'
                f'<h2><span class="swatch" style="background:{m["color"]}"></span>'
                f'{e(section.title)}<span class="leds" style="color:{m["color"]}">{m["leds"]}</span>'
                f'</h2><p class="enter">{e(section.enter)}</p>{_gesture_rows(rows)}'
            )
            for name, group_rows in groups:
                parts.append(f"<h3>{e(name)}</h3>{_gesture_rows(group_rows)}")
            parts.append("</section>")
        parts.append("</div>")
    parts.append(
        '<div><section class="panel" data-mode="leds"><h2>Reading the LEDs</h2><ul class="legend">'
        "<li><b>Mode flash</b><span>LED 1, 2, or 3 twice; all three for Air</span></li>"
        "<li><b>Tap preview</b><span>bar grows 1→2→3, then brighter 1→2→3 for taps 4 to 6</span></li>"
        "<li><b>Accepted</b><span>the preview bar flashes three times</span></li>"
        "<li><b>Cancelled</b><span>sweep down 3→2→1, then dark</span></li>"
        "<li><b>Pairing</b><span>all three breathe, then a dim pulse every 5 s</span></li>"
        "<li><b>Connected</b><span>slot bar, then all three solid, then fade</span></li>"
        "<li><b>Charging</b><span>battery bar breathes for 20 s; three solid bars is full</span></li>"
        "<li><b>Low battery</b><span>three fast blinks, then it powers off</span></li>"
        "</ul></section>"
        '<section class="panel" data-mode="help"><h2>When it misbehaves</h2><ul class="legend">'
        "<li><b>Nothing lights</b><span>cable on a 5 V wall charger for 10 min; rub the contacts</span></li>"
        "<li><b>Won't pair</b><span>forget it on the host, then 2× tap + hold</span></li>"
        "<li><b>Pointer dead</b><span>tap the Modstrip to wake; swipe left; 1× tap + hold unlocks</span></li>"
        "<li><b>Studio can't see it</b><span>3× tap + hold for App Status; 2× to re-advertise</span></li>"
        "<li><b>Lock it</b><span>palm over the surface; the charger or 1× tap + hold unlocks</span></li>"
        "</ul></section></div>"
    )
    parts.append("</div>")
    parts.append(
        "<footer><span>Light touch: the surface is sensitive, glide rather than press.</span>"
        "<span>Dimmed gestures are switched off in this profile; change that in Prolo Studio.</span>"
        "</footer></body></html>\n"
    )
    return "\n".join(parts)


def render(profile_path: Path, labels_path: Path | None, fmt: str) -> str:
    raw = profile_path.read_bytes()
    sheet = build(
        load_profile(profile_path),
        load_labels(labels_path),
        profile_name=profile_path.name,
        profile_hash=hashlib.sha256(raw).hexdigest()[:12],
    )
    return render_html(sheet) if fmt == "html" else render_markdown(sheet)
