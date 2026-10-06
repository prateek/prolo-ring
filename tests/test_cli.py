import json
import struct

import pytest

from prolo_ring import cli, protocol, transport
from prolo_ring.errors import RefusedOpcode

from .fake_ring import FakeRing


@pytest.fixture
def ring(monkeypatch, tmp_path):
    fake = FakeRing()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("PROLO_RING_ADDRESS", "AA:BB:CC:DD:EE:FF")
    monkeypatch.setattr(
        cli,
        "open_session",
        lambda address, **kw: transport.Session(fake, darwin=False, timeout=1.0),
    )
    return fake


def run(capsys, *argv):
    code = cli.main(["--json", *argv])
    return code, json.loads(capsys.readouterr().out)


def test_settings_get_reports_every_setting(ring, capsys):
    ring.nickname = b"Gold"
    code, out = run(capsys, "settings", "get")
    assert code == 0
    assert out["data"]["cursor-speed"] == 40
    assert out["data"]["auto-sleep"] == "never"
    assert out["data"]["edge-scroll-side"] == "right"
    assert out["data"]["nickname"] == "Gold"


def test_settings_set_writes_one_byte_and_verifies(ring, capsys):
    code, out = run(capsys, "settings", "set", "cursor-speed", "60")
    assert code == 0
    assert out["data"]["before"] == 40
    assert out["data"]["after"] == 60
    assert out["data"]["verified"] is True
    assert out["data"]["writes"] == ["673c"]
    assert bytes.fromhex("673c") in ring.writes


def test_dry_run_reads_but_never_writes(ring, capsys):
    code, out = run(capsys, "settings", "set", "led-brightness", "50", "--dry-run")
    assert code == 0
    assert out["data"]["writes"] == ["6d0032"]
    assert ring.led == [0, 15]
    assert all(w[0] in protocol.READ_OPCODES for w in ring.writes)


def test_edge_scroll_side_changes_only_its_cursor_bit(ring, capsys):
    code, out = run(capsys, "settings", "set", "edge-scroll-side", "left")
    assert code == 0 and out["data"]["verified"] is True
    assert ring.flags[5] == 0x62BF | 0x0400
    assert {g: v for g, v in ring.flags.items() if g != 5} == {
        1: 0x000F,
        2: 0x007F,
        3: 0x0017,
        4: 0x0007,
        6: 0x0007,
    }


def test_auto_sleep_refuses_non_preset_minutes(ring, capsys):
    code, out = run(capsys, "settings", "set", "auto-sleep", "7")
    assert code == 2
    assert out["error"]["code"] == "usage"
    assert ring.auto_sleep == 255


def test_untested_firmware_blocks_writes_without_force(ring, capsys):
    ring.firmware = "1.0.3"
    code, out = run(capsys, "settings", "set", "multi-tap", "off")
    assert code == 2
    assert "untested" in out["error"]["message"]
    assert ring.multi_tap == 1
    code, out = run(capsys, "settings", "set", "multi-tap", "off", "--force")
    assert code == 0 and ring.multi_tap == 0


def test_doubled_opcode_replies_are_understood(monkeypatch, ring, capsys):
    ring.doubled = True
    code, out = run(capsys, "settings", "get", "edge-scroll-step")
    assert code == 0 and out["data"] == {"setting": "edge-scroll-step", "value": 32}


def test_device_info_reports_edition_battery_and_mac(ring, capsys):
    code, out = run(capsys, "device", "info")
    assert code == 0
    assert out["data"]["edition"] == "pro"
    assert out["data"]["battery_percent"] == 87
    assert out["data"]["mode"] == "cursor"
    assert out["data"]["mac_address"] == "D0:A1:B2:C3:D4:E5"
    assert out["data"]["firmware_tested"] is True


def test_profile_read_stops_at_profile_end(ring, capsys, tmp_path):
    payload = bytes([2]) + struct.pack("<H", 0x0001)
    ring.profile = bytes([1, 0, 1, 0]) + struct.pack("<BBH", 25, 1, len(payload)) + payload
    out_file = tmp_path / "profile.bin"
    code, out = run(capsys, "profile", "read", "--out", str(out_file))
    assert code == 0
    assert out["data"]["profile"]["gestures"][0]["steps"][0]["action"] == "Play/Pause"
    assert out["data"]["profile_settings"]["cursor"]["raw"] == "0x62BF"
    assert out_file.read_bytes() == ring.profile


def test_raw_get_only_sends_read_opcodes(ring, capsys):
    code, out = run(capsys, "raw", "get", "212")
    assert code == 2
    assert out["error"]["code"] == "usage"
    assert ring.writes == []


@pytest.mark.parametrize("opcode", [124, 126, 130, 131, 132, 200, 202, 206, 207, 210, 211, 212])
async def test_transport_refuses_dangerous_opcodes_before_sending(opcode):
    fake = FakeRing()
    session = transport.Session(fake, darwin=False, timeout=0.1)
    with pytest.raises(RefusedOpcode):
        await session.write(opcode, b"\x00")
    assert fake.writes == []


def test_doctor_runs_without_bluetooth_or_address(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("PROLO_RING_ADDRESS", raising=False)
    code, out = run(capsys, "doctor", "--no-scan")
    assert code == 0
    assert out["data"]["target"]["source"] == "missing"
    assert out["data"]["ready"] is False
    assert out["data"]["auth_required"] is False


def test_init_saves_the_only_app_status_ring(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    async def fake_scan(_timeout):
        return [
            {"address": "U-1", "name": "Prolo App Ring", "status": "app", "rssi": -50},
            {"address": "U-2", "name": "Prolo Ring", "status": "device", "rssi": -40},
        ]

    monkeypatch.setattr(cli, "scan", fake_scan)
    code, out = run(capsys, "init")
    assert code == 0 and out["data"]["address"] == "U-1"
    assert (tmp_path / "prolo-ring" / "config.toml").read_text() == 'address = "U-1"\n'


def test_settings_list_needs_no_ring(capsys):
    code, out = run(capsys, "settings", "list")
    assert code == 0
    assert {"cursor-speed", "nickname", "edge-scroll-width"} <= {r["name"] for r in out["data"]}
