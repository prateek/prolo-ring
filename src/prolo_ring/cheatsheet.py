"""Render a cheat sheet from a Prolo Studio profile export, labelled with what each gesture does
on this machine. No ring needed."""

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

STUDIO_KEYS = {key: name for name, key in GESTURES.values() if key}


def _squash(text: str) -> str:
    return text.replace(" ", "").lower()


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


@dataclass(frozen=True)
class Row:
    gesture: str
    title: str
    how: str
    action: str
    detail: str
    enabled: bool
    source: str  # "profile", "builtin", or "unassigned"


@dataclass(frozen=True)
class Sheet:
    title: str
    profile_name: str
    profile_hash: str
    firmware: str
    sections: list[tuple[Section, list[Row], list[tuple[str, list[Row]]]]]


def chord(sequence: str) -> str:
    parts = [part.strip() for part in sequence.split("+") if part.strip()]
    glyphs = [MAC_GLYPHS[p.lower()] for p in parts if p.lower() in MAC_GLYPHS]
    keys = [KEY_LABELS.get(p, p) for p in parts if p.lower() not in MAC_GLYPHS]
    return "".join(glyphs) + " ".join(keys)


def describe(entry: dict[str, Any]) -> str:
    """Turn one Studio action entry into a short phrase."""
    match entry.get("selected"):
        case "radioKeyboard":
            return chord(entry.get("keySequence", ""))
        case "radioMediaControls":
            return str(entry.get("action", ""))
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
                    steps.append(str(step.get("action", "")))
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

    def enabled(section: Section, gesture: Gesture) -> bool:
        if section.mode_flag and flags.get(section.mode_flag) is False:
            return False
        return all(flags.get(flag, True) for flag in gesture.needs)

    def row(section: Section, gesture: Gesture) -> Row:
        on = enabled(section, gesture)
        if not gesture.name:
            return Row("", gesture.title, gesture.how, gesture.builtin, "", on, "builtin")
        key = GESTURES_BY_NAME.get(gesture.name)
        entry = profile.get(key, {}) if key else {}
        raw = describe(entry)
        label = gesture_labels.get(gesture.name)
        if isinstance(label, dict):
            label = label.get("label")
        alias = entry.get("gestureAlias", "")
        if label:
            return Row(gesture.name, gesture.title, gesture.how, str(label), raw, on, "profile")
        if raw:
            detail = alias if alias and _squash(alias) != _squash(raw) else ""
            return Row(gesture.name, gesture.title, gesture.how, raw, detail, on, "profile")
        return Row(gesture.name, gesture.title, gesture.how, "", "", on, "unassigned")

    sections = []
    for section in SECTIONS:
        rows = [row(section, g) for g in section.gestures]
        groups = [(name, [row(section, g) for g in gs]) for name, gs in section.groups]
        sections.append((section, rows, groups))
    return Sheet(labels.get("title", title), profile_name, profile_hash, FIRMWARE, sections)


GESTURES_BY_NAME = {name: key for _id, (name, key) in GESTURES.items()}


def render_markdown(sheet: Sheet) -> str:
    out = [f"# {sheet.title}", ""]
    if sheet.profile_name:
        out.append(
            f"Profile `{sheet.profile_name}` ({sheet.profile_hash}), firmware {sheet.firmware}."
        )
        out.append("")
    for section, rows, groups in sheet.sections:
        out += [f"## {section.title}", "", section.enter, ""]
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
        if not r.enabled:
            action = f"~~{action}~~ off"
        lines.append(f"| {r.title} | {r.how} | {action} |")
    return lines


CSS = """
:root { --fg: #1d1d1f; --muted: #8a8a8e; --line: #e3e3e6; --accent: #0a84ff; }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px; font: 14px/1.4 -apple-system, "SF Pro Text", Inter, sans-serif;
       color: var(--fg); background: #fff; }
header { display: flex; align-items: baseline; gap: 12px; margin-bottom: 18px; }
header h1 { margin: 0; font-size: 22px; }
header .meta { color: var(--muted); font-size: 12px; }
main { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; }
section { border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px;
          break-inside: avoid; }
section[data-active="true"] { border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent); }
h2 { margin: 0 0 2px; font-size: 16px; }
h3 { margin: 10px 0 2px; font-size: 12px; color: var(--muted); text-transform: uppercase;
     letter-spacing: .04em; }
p.enter { margin: 0 0 8px; color: var(--muted); font-size: 12px; }
table { width: 100%; border-collapse: collapse; }
td { padding: 3px 4px; vertical-align: top; border-top: 1px solid var(--line); }
td.g { width: 34%; font-weight: 600; }
td.h { width: 30%; color: var(--muted); font-size: 12px; }
td.a .detail { color: var(--muted); font-size: 12px; margin-left: 4px; }
tr.off { opacity: .4; }
tr.off td.a::after { content: " off"; color: var(--muted); font-size: 11px; }
tr[data-last="true"] td { background: #fff4d6; }
@media print {
  body { padding: 0; font-size: 12px; }
  main { grid-template-columns: 1fr 1fr; gap: 10px; }
  section { border-radius: 0; }
}
"""


def render_html(sheet: Sheet) -> str:
    e = html.escape
    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{e(sheet.title)}</title>",
        f"<style>{CSS}</style></head><body>",
        f"<header><h1>{e(sheet.title)}</h1>",
    ]
    meta = f"firmware {e(sheet.firmware)}"
    if sheet.profile_name:
        meta = f"profile {e(sheet.profile_name)} · {e(sheet.profile_hash)} · " + meta
    parts.append(f'<span class="meta">{meta}</span></header><main>')
    for section, rows, groups in sheet.sections:
        parts.append(f'<section data-mode="{section.key}"><h2>{e(section.title)}</h2>')
        parts.append(f'<p class="enter">{e(section.enter)}</p>')
        parts.append(_html_table(rows))
        for name, group_rows in groups:
            parts.append(f"<h3>{e(name)}</h3>{_html_table(group_rows)}")
        parts.append("</section>")
    parts.append("</main></body></html>\n")
    return "\n".join(parts)


def _html_table(rows: list[Row]) -> str:
    e = html.escape
    body = []
    for r in rows:
        cls = "" if r.enabled else ' class="off"'
        detail = f'<span class="detail">{e(r.detail)}</span>' if r.detail else ""
        action = e(r.action) if r.action else '<span class="detail">unassigned</span>'
        body.append(
            f'<tr{cls} data-gesture="{e(r.gesture)}"><td class="g">{e(r.title)}</td>'
            f'<td class="h">{e(r.how)}</td><td class="a">{action}{detail}</td></tr>'
        )
    return "<table>" + "".join(body) + "</table>"


def render(profile_path: Path, labels_path: Path | None, fmt: str) -> str:
    raw = profile_path.read_bytes()
    sheet = build(
        load_profile(profile_path),
        load_labels(labels_path),
        profile_name=profile_path.name,
        profile_hash=hashlib.sha256(raw).hexdigest()[:12],
    )
    return render_html(sheet) if fmt == "html" else render_markdown(sheet)
