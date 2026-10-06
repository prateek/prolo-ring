import json
from pathlib import Path

from prolo_ring import cheatsheet, cli

FACTORY = Path(__file__).resolve().parents[1] / "profiles" / "factory-default.json"


def rows_by_gesture(sheet):
    rows = {}
    for _section, section_rows, groups in sheet.sections:
        for row in section_rows:
            rows[row.gesture] = row
        for _name, group_rows in groups:
            for row in group_rows:
                rows[row.gesture] = row
    return rows


def test_factory_profile_renders_mac_chords_media_and_builtins():
    md = cheatsheet.render(FACTORY, None, "md")
    assert "| Two-finger tap |" in md and "⌘D" in md
    assert "(Win + D)" not in md  # the alias only restates the chord
    assert "| Tap | One tap | Play / pause |" in md
    assert "⌃=" in md and "Key00" not in md  # pinch out sends Control on a Mac; no padding step
    assert "| 5× tap + hold |" in md and "Factory reset" in md and "five: wipe" in md


def test_disabled_modes_and_groups_are_dimmed_not_hidden(tmp_path):
    profile = json.loads(FACTORY.read_text())
    profile["settings"]["_profileSettings"].update({"btnMAir": False, "dual_tap_tt": False})
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile))
    sheet = cheatsheet.build(cheatsheet.load_profile(path), {})
    rows = rows_by_gesture(sheet)
    assert rows["cursor.two_finger_tap"].enabled is False
    assert rows["air.tap"].enabled is False
    assert rows["touch.tap"].enabled is True
    assert "~~⌘D~~ off" in cheatsheet.render_markdown(sheet)


def test_labels_replace_the_chord_and_keep_it_as_detail(tmp_path):
    labels = tmp_path / "labels.toml"
    labels.write_text(
        'title = "Ring at the desk"\n'
        "[gestures]\n"
        '"cursor.two_finger_tap" = "Raycast"\n'
        '"navigation.long_hold" = { label = "Push to talk", mnemonic = "hold to speak" }\n'
        "[modes.cursor]\n"
        'mnemonic = "Left is for looking."\n'
    )
    sheet = cheatsheet.build(cheatsheet.load_profile(FACTORY), cheatsheet.load_labels(labels))
    assert sheet.title == "Ring at the desk"
    assert sheet.mode_mnemonics["cursor"] == "Left is for looking."
    rows = rows_by_gesture(sheet)
    assert (rows["cursor.two_finger_tap"].action, rows["cursor.two_finger_tap"].detail) == (
        "Raycast",
        "⌘D",
    )
    assert rows["cursor.two_finger_tap"].keys == ("⌘", "D")
    assert rows["navigation.long_hold"].mnemonic == "hold to speak"


def test_aliases_that_add_meaning_become_the_label():
    rows = rows_by_gesture(cheatsheet.build(cheatsheet.load_profile(FACTORY), {}))
    assert rows["navigation.long_hold"].action == "Push To Talk"
    assert rows["navigation.long_hold"].keys == ("⌃", "⌘")
    assert rows["cursor.bottom_left_double_tap"].action == "Drag Lock"
    assert rows["cursor.bottom_left_double_tap"].detail == "Hold left button"
    assert rows["modnav.swipe_up"].action == "PgUp"  # "Page Up" alias restates the key


def test_unassigned_gestures_are_reported_as_such():
    rows = rows_by_gesture(cheatsheet.build(cheatsheet.load_profile(FACTORY), {}))
    assert rows["air.tap"].source == "unassigned"
    assert rows["touch.triple_tap"].action == ""


def test_glyphs_follow_the_gesture_shape():
    assert cheatsheet.glyph_for("navigation.swipe_up") == "swipe-up"
    assert cheatsheet.glyph_for("touch.triple_tap") == "tap-3"
    assert cheatsheet.glyph_for("cursor.two_finger_tap") == "tap-two-finger"
    assert cheatsheet.glyph_for("navigation.pinch_out") == "pinch-out"
    assert cheatsheet.glyph_for_title("3× tap + hold") == "tap-3"
    assert cheatsheet.glyph_for_title("Palm hold") == "hold"


def test_html_carries_keycaps_glyphs_and_live_view_hooks():
    page = cheatsheet.render(FACTORY, None, "html")
    assert page.startswith("<!doctype html>")
    assert 'data-mode="cursor"' in page and 'data-mode="system"' in page
    assert "<kbd>⌘</kbd><kbd>D</kbd>" in page
    assert '<use href="#g-swipe-up"/>' in page
    # The factory flags disable Touch long hold, so that row is dimmed; Air rows stay enabled
    # even though nothing is assigned to them.
    assert '<div class="row off" data-gesture="touch.long_hold">' in page
    assert '<div class="row" data-gesture="air.tap">' in page
    assert "five: wipe" in page and 'class="ring"' in page


def test_describe_handles_macros_mouse_apps_and_padding():
    macro = {
        "selected": "radioMacro",
        "macros": [
            {"type": "Key Input", "keySequence": "Ctrl+Shift+A"},
            {"type": "Delay", "delay": 100},
            {"type": "Text Input", "text": "hi"},
        ],
    }
    assert cheatsheet.describe(macro) == "⌃⇧A → wait 100 ms → type 'hi'"
    padded = {
        "selected": "radioMacro",
        "macros": [
            {"type": "Key Input", "keySequence": "Ctrl+="},
            {"type": "Key Input", "keySequence": "Key00"},
        ],
    }
    assert cheatsheet.describe(padded) == "⌃="
    assert cheatsheet.keycaps("Meta+D") == ("⌘", "D")
    assert (
        cheatsheet.describe({"selected": "radioMouse", "mouseAction": "Left Button Down (Hold)"})
        == "Hold left button"
    )
    assert (
        cheatsheet.describe({"selected": "radioOpenApp", "filePath": "/Applications/Obsidian.app"})
        == "Open Obsidian"
    )
    assert cheatsheet.describe({"selected": "radioDisable"}) == ""


def test_cli_writes_the_sheet_to_out(tmp_path, capsys):
    out = tmp_path / "sheet.html"
    code = cli.main(
        ["--json", "cheatsheet", "render", "--profile", str(FACTORY), "--out", str(out)]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["data"]["format"] == "html"
    assert out.read_text().startswith("<!doctype html>")


def test_cli_streams_markdown_to_stdout(capsys):
    code = cli.main(["cheatsheet", "render", "--profile", str(FACTORY), "--format", "md"])
    assert code == 0
    assert capsys.readouterr().out.startswith("# Prolo Ring")


def test_cli_rejects_a_file_that_is_not_a_profile(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("[]")
    code = cli.main(["--json", "cheatsheet", "render", "--profile", str(bad)])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "usage"
