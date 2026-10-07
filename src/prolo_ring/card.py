"""Overlay cards: one compact SVG per mode, drawn with rects, circles, and text only so macOS's
NSImage renders it the way it renders the keyboard sheets. A card shows the trackpad with the
first-week actions placed where they are performed, the Modstrip actions, and how to switch
mode. `all` tiles the four modes; `system` is the Modstrip tap ladder."""

from __future__ import annotations

from html import escape

from .catalogue import FIRST, NEXT
from .cheatsheet import DANGER_FROM, MODE_META, SHORT, Row, Sheet, caps_text

MODES = ("cursor", "navigation", "touch", "air")
CARD_MODES = (*MODES, "system", "all")
W, H = 600, 420
BG, PANEL, FG, DIM, FAINT = "#17191d", "#1f2329", "#f2f3f5", "#9aa1ac", "#3a3f47"
FONT = "-apple-system, Helvetica, Arial, sans-serif"
MAX_ACTION = 24
# A bare arrow key reads as a direction, not an action, so name it.
ARROWS = {"↑": "Arrow ↑", "↓": "Arrow ↓", "←": "Arrow ←", "→": "Arrow →"}
DIRECTIONS = ("up", "down", "left", "right")


def _t(
    x: float,
    y: float,
    text: str,
    *,
    size: float = 12,
    fill: str = FG,
    weight: int = 400,
    anchor: str = "start",
    extra: str = "",
) -> str:
    return (
        f'<text x="{x:g}" y="{y:g}" font-size="{size:g}" font-weight="{weight}" fill="{fill}" '
        f'text-anchor="{anchor}"{extra}>{escape(text)}</text>'
    )


def _rect(
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    rx: float = 0,
    fill: str = "none",
    stroke: str = "",
    width: float = 1,
    dash: str = "",
    opacity: float = 1,
) -> str:
    attrs = f'x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{rx:g}" fill="{fill}"'
    if stroke:
        attrs += f' stroke="{stroke}" stroke-width="{width:g}"'
    if dash:
        attrs += f' stroke-dasharray="{dash}"'
    if opacity != 1:
        attrs += f' opacity="{opacity:g}"'
    return f"<rect {attrs}/>"


def _clip(text: str, limit: int = MAX_ACTION) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def action_text(r: Row) -> str:
    if r.source == "unassigned":
        return "—"
    if r.keys and r.action == caps_text(r.keys):
        text = caps_text(r.keys)
        return ARROWS.get(text, text)
    if r.keys:
        return f"{r.action}  {caps_text(r.keys)}"
    return r.action


def _led_dots(x: float, y: float, led: int, color: str) -> str:
    out = []
    for i in range(3):
        lit = led == 0 or led == i + 1  # Air lights all three
        out.append(
            f'<circle cx="{x + i * 16:g}" cy="{y:g}" r="5.5" fill="{color if lit else FAINT}"/>'
        )
    return "".join(out)


def _pair(
    x: float,
    y: float,
    label: str,
    action: str,
    *,
    anchor: str = "start",
    enabled: bool = True,
    gap: float = 6,
) -> str:
    """A 'label  action' pair on one baseline; label dim, action bright."""
    fill = FG if enabled else FAINT
    if anchor == "end":
        return _t(x, y, action, size=12.5, fill=fill, weight=600, anchor="end") + _t(
            x - 7.2 * len(action) - gap, y, label, size=10.5, fill=DIM, anchor="end"
        )
    if anchor == "middle":
        return _t(x, y, label, size=10.5, fill=DIM, anchor="middle") + _t(
            x, y + 14, action, size=12.5, fill=fill, weight=600, anchor="middle"
        )
    return _t(x, y, label, size=10.5, fill=DIM) + _t(
        x + 6.2 * len(label) + gap, y, action, size=12.5, fill=fill, weight=600
    )


def _featured(rows: list[Row]) -> dict[str, list[Row]]:
    by_zone: dict[str, list[Row]] = {}
    for r in rows:
        if r.tier in (FIRST, NEXT) and r.zone and r.source != "unassigned":
            by_zone.setdefault(r.zone, []).append(r)
    return by_zone


def _label_for(r: Row, zone: str) -> str:
    if zone in ("bl", "br"):
        return "hold" if "hold" in r.title.lower() else "2×"
    if zone in DIRECTIONS:
        return "swipe"
    return SHORT.get(r.title, r.title)


def _map(sheet: Sheet, mode: str, ox: float, oy: float) -> str:
    """Trackpad map at origin (ox, oy), 300 wide by 240 tall, plus corner notes beneath."""
    _section, rows, _groups = next(s for s in sheet.sections if s[0].key == mode)
    color = MODE_META[mode]["color"]
    zones = _featured(rows)
    out = [
        _rect(ox, oy, 300, 240, rx=22, fill=PANEL, stroke=color, width=2),
        _rect(ox + 274, oy + 16, 14, 208, rx=7, fill="none", stroke=color, width=1.2, dash="4 3"),
        _rect(ox + 2, oy + 204, 60, 34, rx=14, fill=color, opacity=0.28),
        _rect(ox + 238, oy + 204, 60, 34, rx=14, fill=color, opacity=0.28),
        _t(ox + 150, oy - 6, "fingertip ↑", size=10, fill=DIM, anchor="middle"),
    ]
    cx = ox + 150
    if zones.get("up"):
        r = zones["up"][0]
        out.append(
            _pair(
                cx,
                oy + 22,
                _label_for(r, "up"),
                _clip(action_text(r)),
                anchor="middle",
                enabled=r.enabled,
            )
        )
    if zones.get("down"):
        r = zones["down"][0]
        out.append(
            _pair(
                cx,
                oy + 192,
                _label_for(r, "down"),
                _clip(action_text(r)),
                anchor="middle",
                enabled=r.enabled,
            )
        )
    if zones.get("left"):
        r = zones["left"][0]
        out.append(
            _pair(
                ox + 14,
                oy + 80,
                _label_for(r, "left"),
                _clip(action_text(r), 16),
                enabled=r.enabled,
            )
        )
    if zones.get("right"):
        r = zones["right"][0]
        out.append(
            _pair(
                ox + 266,
                oy + 80,
                _label_for(r, "right"),
                _clip(action_text(r), 16),
                anchor="end",
                enabled=r.enabled,
            )
        )
    center = zones.get("center", [])[:4]
    y = oy + 120 - (len(center) - 1) * 8
    for r in center:
        out.append(_t(cx - 6, y, _label_for(r, "center"), size=10.5, fill=DIM, anchor="end"))
        out.append(
            _t(
                cx + 4,
                y,
                _clip(action_text(r), 20),
                size=12.5,
                fill=FG if r.enabled else FAINT,
                weight=600,
            )
        )
        y += 16
    y = oy + 160
    for r in zones.get("pinch", [])[:2]:
        out.append(
            _pair(
                ox + 266,
                y,
                _label_for(r, "pinch"),
                _clip(action_text(r), 14),
                anchor="end",
                enabled=r.enabled,
            )
        )
        y += 14
    if zones.get("edge"):
        out.append(_t(ox + 281, oy + 10, "scroll", size=8.5, fill=DIM, anchor="middle"))
    # Corner notes sit under the pad, aligned with their corners.
    y = oy + 258
    for zone, x, anchor in (("bl", ox + 4, "start"), ("br", ox + 296, "end")):
        items = zones.get(zone, [])
        if not items:
            continue
        out.append(
            _t(
                x,
                y,
                "bottom-left" if zone == "bl" else "bottom-right",
                size=9.5,
                fill=DIM,
                anchor=anchor,
                extra=' letter-spacing="0.5"',
            )
        )
        yy = y + 15
        for r in items[:2]:
            out.append(
                _pair(
                    x,
                    yy,
                    _label_for(r, zone),
                    _clip(action_text(r), 18),
                    anchor=anchor,
                    enabled=r.enabled,
                )
            )
            yy += 15
    return "".join(out)


def _modstrip_column(sheet: Sheet, mode: str, x: float, y: float) -> str:
    _section, rows, groups = next(s for s in sheet.sections if s[0].key == mode)
    zones = _featured(rows)
    held = zones.get("modstrip", []) + [
        r for _n, grs in groups for r in grs if r.tier in (FIRST, NEXT) and r.source != "unassigned"
    ]
    out = [_t(x, y, "MODSTRIP", size=10.5, fill=DIM, weight=700, extra=' letter-spacing="1.2"')]
    yy = y + 20
    if not held:
        out.append(_t(x, yy, "Hold it while gesturing for the", size=11, fill=DIM))
        out.append(_t(x, yy + 14, "Mod set; see the reference sheet.", size=11, fill=DIM))
        return "".join(out)
    for r in held[:5]:
        label = r.title.replace("Modstrip ", "").replace("Mod + ", "+ ")
        out.append(_t(x, yy, label, size=10.5, fill=DIM))
        out.append(
            _t(
                x,
                yy + 14,
                _clip(action_text(r), 36),
                size=12.5,
                fill=FG if r.enabled else FAINT,
                weight=600,
            )
        )
        yy += 34
    return "".join(out)


def _switch_strip(x: float, y: float, current: str) -> str:
    entries = (
        ("cursor", "← swipe", "Cursor"),
        ("navigation", "swipe →", "Navigation"),
        ("touch", "swipe → hold", "Touch"),
        ("air", "← swipe hold", "Air"),
    )
    out = [_t(x, y, "SWITCH MODE", size=10.5, fill=DIM, weight=700, extra=' letter-spacing="1.2"')]
    yy = y + 20
    for key, gesture, name in entries:
        color = MODE_META[key]["color"]
        on = key == current
        out.append(_rect(x, yy - 10, 4, 13, rx=2, fill=color if on else FAINT))
        out.append(_t(x + 12, yy, gesture, size=10.5, fill=DIM))
        out.append(
            _t(x + 100, yy, name, size=12, fill=color if on else FG, weight=700 if on else 500)
        )
        yy += 18
    return "".join(out)


def _header(sheet: Sheet, mode: str, title: str) -> str:
    m = MODE_META[mode]
    return "".join(
        [
            _t(22, 38, title, size=24, fill=m["color"], weight=700),
            _led_dots(W - 22 - 32, 32, int(m["led"]), m["color"]),
            _t(22, 60, sheet.mode_mnemonics[mode], size=13, fill=DIM),
        ]
    )


def render_card(sheet: Sheet, mode: str) -> str:
    if mode == "all":
        return render_all(sheet)
    if mode == "system":
        return render_system(sheet)
    section = next(s for s in sheet.sections if s[0].key == mode)[0]
    body = [_header(sheet, mode, section.title)]
    body.append(_t(22, 78, section.enter.split(".")[0] + ".", size=11.5, fill=FG))
    if mode == "air":
        body.append(_air_body(sheet))
    else:
        body.append(_map(sheet, mode, 22, 104))
        body.append(_modstrip_column(sheet, mode, 350, 118))
    body.append(_switch_strip(350, 290 if mode != "air" else 220, mode))
    body.append(
        _t(
            22,
            H - 14,
            "1× tap + hold reconnects or unlocks · 2× pairs · palm locks",
            size=10,
            fill=DIM,
        )
    )
    return _svg(W, H, "".join(body))


def _air_body(sheet: Sheet) -> str:
    _section, rows, groups = next(s for s in sheet.sections if s[0].key == "air")
    out = []
    steps = (
        "Tilt the hand until the charging port faces down.",
        "All three LEDs light for two seconds: armed.",
        "Move sharply. LED 3 flicks once when recognized.",
    )
    y = 110
    for i, step in enumerate(steps, 1):
        out.append(_t(22, y, f"{i}", size=14, fill=MODE_META["air"]["color"], weight=700))
        out.append(_t(40, y, step, size=12, fill=FG))
        y += 22
    assigned = [r for r in rows + [r for _n, g in groups for r in g] if r.source != "unassigned"]
    y += 10
    out.append(
        _t(22, y, "ASSIGNED", size=10.5, fill=DIM, weight=700, extra=' letter-spacing="1.2"')
    )
    y += 20
    if not assigned:
        out.append(_t(22, y, "Nothing yet in this profile.", size=12, fill=DIM))
    for r in assigned[:6]:
        out.append(_pair(22, y, r.title, _clip(action_text(r), 26), enabled=r.enabled))
        y += 17
    return "".join(out)


def render_system(sheet: Sheet) -> str:
    rows = next(s for s in sheet.sections if s[0].key == "system")[1]
    out = [
        _t(22, 38, "Modstrip", size=24, fill=FG, weight=700),
        _t(22, 60, "Tap N times, then press and hold within two seconds.", size=13, fill=DIM),
    ]
    y = 96
    for r in rows:
        head = r.title.split("×")[0]
        if head.isdigit():
            n = int(head)
            lit = ((n - 1) % 3) + 1
            danger = n >= DANGER_FROM
            for i in range(3):
                fill = ("#ef4444" if danger else "#e4e4e7") if i < lit else FAINT
                out.append(_rect(22 + i * 18, y - 10, 14, 10, rx=2, fill=fill))
            out.append(_t(84, y, r.title, size=12.5, fill="#f87171" if danger else FG, weight=700))
            out.append(_t(190, y, _clip(r.action, 56), size=11.5, fill="#fca5a5" if danger else FG))
            if r.mnemonic:
                out.append(
                    _t(190, y + 13, r.mnemonic, size=10, fill=DIM, extra=' font-style="italic"')
                )
            y += 36
        elif "palm" in r.title.lower():
            for i in range(3):
                out.append(_rect(22 + i * 18, y - 10, 14, 10, rx=2, fill="#e4e4e7"))
            out.append(_t(84, y, r.title, size=12.5, fill=FG, weight=700))
            out.append(_t(190, y, _clip(r.action, 56), size=11.5, fill=FG))
            y += 24
    out.append(_rect(22, y, W - 44, 1, fill=FAINT))
    out.append(
        _t(
            22,
            y + 18,
            "Any trackpad touch cancels. Red counts reboot, wipe, or update the ring.",
            size=10.5,
            fill=DIM,
        )
    )
    return _svg(W, H, "".join(out))


def render_all(sheet: Sheet) -> str:
    gap = 16
    cards = []
    for i, mode in enumerate(MODES):
        inner = render_card(sheet, mode)
        start = inner.index(">", inner.index("<svg")) + 1
        body = inner[start : inner.rindex("</svg>")]
        x = (i % 2) * (W + gap)
        y = (i // 2) * (H + gap)
        cards.append(f'<g transform="translate({x} {y})">{body}</g>')
    return _svg(W * 2 + gap, H * 2 + gap, "".join(cards), background=False)


def _svg(width: int, height: int, body: str, *, background: bool = True) -> str:
    bg = _rect(0, 0, width, height, rx=18, fill=BG) if background else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" font-family="{FONT}">{bg}{body}</svg>\n'
    )
