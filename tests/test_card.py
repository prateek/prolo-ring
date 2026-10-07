import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from prolo_ring import card, cheatsheet, cli

FACTORY = Path(__file__).resolve().parents[1] / "profiles" / "factory-default.json"
# What macOS's NSImage is known to render, from the keyboard overlay that already ships.
ALLOWED = {"svg", "rect", "text", "circle", "g"}


def sheet():
    return cheatsheet.build(cheatsheet.load_profile(FACTORY), {})


def tags(svg: str) -> set[str]:
    root = ET.fromstring(svg)
    return {el.tag.split("}")[-1] for el in root.iter()}


@pytest.mark.parametrize("mode", card.CARD_MODES)
def test_every_card_is_well_formed_and_uses_only_safe_elements(mode):
    svg = card.render_card(sheet(), mode)
    assert svg.startswith("<svg ")
    assert tags(svg) <= ALLOWED, tags(svg) - ALLOWED


def test_cursor_card_places_corner_actions_and_modstrip_actions():
    svg = card.render_card(sheet(), "cursor")
    assert "bottom-right" in svg and "Right click" in svg
    assert "bottom-left" in svg and "Middle click" in svg
    assert "Click and drag" in svg  # Modstrip hold + move
    assert "⌘D" in svg  # two-finger tap, as text rather than keycaps
    assert "fingertip" in svg


def test_cards_are_mode_sized_and_all_tiles_four():
    root = ET.fromstring(card.render_card(sheet(), "touch"))
    assert (root.get("width"), root.get("height")) == ("600", "420")
    everything = ET.fromstring(card.render_card(sheet(), "all"))
    assert everything.get("width") == str(card.W * 2 + 16)
    assert sum(1 for el in everything.iter() if el.tag.split("}")[-1] == "g") == 4


def test_system_card_has_the_ladder_with_pegs():
    svg = card.render_card(sheet(), "system")
    assert "5× tap + hold" in svg and "five: wipe it all" in svg
    assert "Palm hold" in svg


def test_disabled_actions_render_faint(tmp_path):
    profile = json.loads(FACTORY.read_text())
    profile["settings"]["_profileSettings"]["bottom_right"] = False
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile))
    svg = card.render_card(cheatsheet.build(cheatsheet.load_profile(path), {}), "cursor")
    faint_right_click = f'fill="{card.FAINT}" text-anchor="end">Right click'
    assert faint_right_click in svg


def test_long_actions_are_clipped():
    assert card._clip("Snap pointer to left edge → Move pointer", 20) == "Snap pointer to lef…"


def test_cli_writes_an_svg_card(tmp_path, capsys):
    out = tmp_path / "touch.svg"
    code = cli.main(
        [
            "--json",
            "cheatsheet",
            "render",
            "--profile",
            str(FACTORY),
            "--format",
            "svg",
            "--mode",
            "touch",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["data"]["format"] == "svg"
    assert out.read_text().startswith("<svg ") and "Volume up" in out.read_text()
