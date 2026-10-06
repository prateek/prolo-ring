# prolo-ring

Unofficial command-line tool for the [Prolo Ring](https://proloring.com), a Bluetooth ring mouse. It reads the ring's device facts, Ring Settings, and gesture profile, and changes Ring Settings, using the same Bluetooth LE protocol as Prolo Studio.

Not affiliated with or endorsed by Prolo. Built against firmware 1.0.7 and Prolo Studio 1.0.7.

## Install

Requires [uv](https://docs.astral.sh/uv/). Run it without installing:

```sh
uvx --from git+https://github.com/prateek/prolo-ring prolo-ring --help
```

Or install it on your `PATH`:

```sh
uv tool install git+https://github.com/prateek/prolo-ring
```

On macOS, the terminal app you run it from needs Bluetooth access (System Settings → Privacy & Security → Bluetooth).

## Quick start

Put the ring in **App Status**: 3x Tap + Hold on the Modstrip until the LEDs sweep upward. It then advertises as "Prolo App Ring" and stops acting as a mouse. Run 3x Tap + Hold again when you're done to return to Device Status.

```sh
prolo-ring doctor                      # Python, Bluetooth, config, and whether a ring is visible
prolo-ring rings scan                  # nearby rings with address and status
prolo-ring init                        # save the only App Status ring nearby as the default
prolo-ring device info                 # firmware, edition, battery, mode, MAC, nickname
prolo-ring settings get                # every Ring Setting
prolo-ring settings set cursor-speed 60 --dry-run
prolo-ring settings set cursor-speed 60
prolo-ring profile read --out ring-profile.bin
```

The ring address comes from `--address`, then `$PROLO_RING_ADDRESS`, then `$XDG_CONFIG_HOME/prolo-ring/config.toml` (default `~/.config/prolo-ring/config.toml`). On macOS the address is a CoreBluetooth UUID rather than a MAC; `device info` reports the real MAC.

## Commands

| Command | What it does |
| --- | --- |
| `doctor [--no-scan]` | Reports versions, config, the resolved ring address, Bluetooth health, and next steps. Works with no ring and no address. |
| `rings scan` | Lists rings advertising nearby. `status` is `app` (connectable), `device` (normal mouse mode), or `dfu` (firmware update mode). |
| `init [ADDRESS]` | Saves the default ring. Without an address it picks the single App Status ring nearby. |
| `device info` | Firmware revision, whether it's the tested version, config version, nickname, MAC, edition, battery percent, and current mode. |
| `device dump` | `device info`, `settings get`, and `profile read` in one connection. Prefer this: the ring stops advertising after each disconnect, so every separate command costs a 2x Tap + Hold. |
| `settings list` | Every setting, its accepted values, and whether it is writable. No ring needed. |
| `settings get [NAME]` | Reads all settings, or one. |
| `settings set NAME VALUE [--dry-run] [--force]` | Changes one setting, then reads it back and reports `verified`. `--dry-run` reads the current value and shows the bytes without writing. Writes are refused on firmware other than 1.0.7 unless you pass `--force`. |
| `profile read [--out FILE]` | Reads back the flashed gesture profile, decodes each gesture's steps, and reports the profile's mode and gesture-group flags. |
| `raw get OPCODE [--payload HEX]` | Escape hatch: sends one read opcode and prints the reply bytes. |

Writable settings: `cursor-speed`, `left-handed`, `multi-tap`, `led-mode`, `led-brightness`, `auto-sleep`, `edge-scroll-step`, `edge-scroll-invert`, `edge-scroll-side`, `edge-scroll-style`, `nickname`. Read-only: `config-version`, `extended-range`, `edge-scroll-width`.

## Older firmware

Rings shipped before firmware 1.0.7 answer ERR to the config dump, MAC, flag-group, and profile-readback opcodes and expose no firmware-revision characteristic. The CLI detects this and reads settings one opcode at a time; results carry `"legacy_protocol": true`, unavailable settings read as `null`, and `profile read` exits 5 with code `unsupported`. Writes need `--force` because the firmware can't be identified. Update the ring in Prolo Studio to get the full surface. See the hardware notes at the top of [docs/protocol.md](docs/protocol.md).

## Safety

The tool only sends read opcodes and the Ring Settings writes Prolo Studio itself sends. The transport refuses every other opcode before any byte reaches the ring: profile flashing, bulk config writes, license and edition provisioning, factory reset and maintenance, factory test and shipping modes, and firmware update. The edge-scroll settings change only their own bits of the cursor flag group and leave the profile-owned bits alone.

Profiles are flashed with Prolo Studio. [docs/flashing.md](docs/flashing.md) explains what flashing from JSON would take and why it is deferred.

## JSON output

Pass `--json` for machine-readable output on stdout. Diagnostics and `--verbose` frame logs go to stderr.

Success:

```json
{"ok": true, "data": {"firmware": "1.0.7", "setting": "cursor-speed", "before": 40, "requested": 60, "writes": ["673c"], "dry_run": false, "after": 60, "verified": true}}
```

Error:

```json
{"ok": false, "error": {"code": "ring_not_found", "message": "ring not found: ...", "details": {}}}
```

`data` is a list for `rings scan` and `settings list`, and an object for everything else. `settings get` maps setting names to values. `profile read` returns `blob_hex`, `blob_size`, `profile` (header and `gestures`, each with `gesture`, `gesture_id`, `studio_key`, and `steps`), and `profile_settings` (decoded flag groups).

Exit codes: 0 ok, 2 usage, 3 ring not found, 4 Bluetooth error, 5 protocol error (timeout or malformed reply), 6 refused opcode.

## Reference

- [docs/protocol.md](docs/protocol.md): the Bluetooth protocol, byte by byte, including the binary profile format and gesture IDs.
- [profiles/factory-default.json](profiles/factory-default.json): the Factory Default profile exported from Prolo Studio 1.0.7.
- [skills/prolo-ring](skills/prolo-ring/SKILL.md): agent skill for driving this CLI.

## Development

```sh
uv sync
make check          # ruff format and lint, pyright, pytest
make install-local  # uv tool install --editable .
```

Tests run against a simulated ring (`tests/fake_ring.py`) and need no hardware.
