---
name: prolo-ring
description: Read and change a Prolo Ring's settings with the prolo-ring CLI over Bluetooth. Use when asked about the ring's firmware, edition, battery, or MAC; to check or change Ring Settings such as cursor speed, auto-sleep, LEDs, multi-tap, edge scroll, or nickname; or to read back the gesture profile flashed on the ring.
---

# prolo-ring

`prolo-ring` talks to a Prolo Ring in **App Status** over Bluetooth LE. Profile flashing stays in Prolo Studio; this CLI reads profiles and changes Ring Settings only.

## Run it

Use the installed command when `command -v prolo-ring` finds it. Otherwise prefix every command below with `uvx --from git+https://github.com/prateek/prolo-ring`:

```sh
prolo-ring --json doctor
uvx --from git+https://github.com/prateek/prolo-ring prolo-ring --json doctor
```

Pass `--json` whenever you parse output. Success is `{"ok": true, "data": ...}`; failure is `{"ok": false, "error": {"code", "message", "details"}}` with a nonzero exit.

## Order of work

1. **Doctor.** `prolo-ring --json doctor` reports the resolved address, Bluetooth health, nearby rings, and `next_steps`. Act on `next_steps` before going further.
2. **App Status.** Commands that connect need the ring in App Status. If `rings scan` shows no ring with `"status": "app"`, ask the user to do 3x Tap + Hold on the Modstrip; the ring stops working as a mouse until they do it again. This is a physical step only the user can perform.
3. **Address.** `prolo-ring --json rings scan`, then `prolo-ring init` (picks the only App Status ring) or `prolo-ring init <address>`. On macOS the address is a CoreBluetooth UUID.
4. **Read.** `device info` for firmware, edition, battery, mode, MAC; `settings get` for every setting; `profile read` for the flashed gestures.
5. **Write, dry run first.** `settings set <name> <value> --dry-run` shows the current value and the exact bytes. Run it without `--dry-run` only when the user asked for that change, then confirm `"verified": true` in the result.
6. **Hand back.** Remind the user to return the ring to Device Status (3x Tap + Hold) for normal use.

## Rules

- Change a setting only when the user asked for that specific change. Report `before`, `after`, and `verified`.
- Writes refuse firmware other than 1.0.7. Pass `--force` only with the user's go-ahead after telling them the protocol is untested on their firmware; suggest updating firmware in Prolo Studio instead.
- To change gesture mappings, edit the Studio JSON (start from `profiles/factory-default.json` in the repo) and have the user Import and Flash it in Prolo Studio. The CLI cannot flash, by design.
- `raw get <opcode>` is a repair hatch for read opcodes only. Prefer the named commands.
- On exit code 3 or 5, the ring is usually asleep, out of range, or in Device Status: ask the user to wake it and confirm App Status, then rescan.

## Examples

```sh
prolo-ring --json settings get auto-sleep
prolo-ring --json settings set auto-sleep 30 --dry-run
prolo-ring --json profile read --out /tmp/ring-profile.bin
```

`prolo-ring settings list` describes every setting and its accepted values without a ring. `prolo-ring cheatsheet render --profile <studio-export.json> [--labels labels.toml]` renders a per-mode cheat sheet from a profile, also without a ring. Protocol details live in the repo's `docs/protocol.md`.
