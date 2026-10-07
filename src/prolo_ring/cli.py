"""prolo-ring command line: discover, read, and change Ring Settings on a Prolo Ring."""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import platform
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from . import cheatsheet, config, protocol, ring, settings, transport
from .errors import ProloError, ProtocolError, UsageError

# Replaced in tests with fakes.
open_session: Callable[..., Awaitable[transport.Session]] = transport.open_session
scan: Callable[[float], Awaitable[list[dict[str, Any]]]] = transport.scan

EPILOG = """\
The ring must be in App Status for any command that connects: 3x Tap + Hold on the
Modstrip until the LEDs sweep upward; it then advertises as "Prolo App Ring".
Return to Device Status (3x Tap + Hold again) for normal mouse use.

Start with:
  prolo-ring --json doctor
  prolo-ring --json rings scan
  prolo-ring init --address <address>

Exit codes: 0 ok, 2 usage, 3 ring not found, 4 Bluetooth error, 5 protocol error,
6 refused opcode. Docs: https://github.com/prateek/prolo-ring
"""


def version() -> str:
    try:
        return importlib.metadata.version("prolo-ring")
    except importlib.metadata.PackageNotFoundError:
        return "0+unknown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prolo-ring",
        description=__doc__,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON on stdout")
    parser.add_argument(
        "--address",
        help=f"ring address (overrides ${config.ENV_ADDRESS} and "
        "the config file); a CoreBluetooth UUID on macOS",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=transport.DEFAULT_TIMEOUT,
        help="seconds to wait for each ring reply (default: %(default)s)",
    )
    parser.add_argument(
        "--scan-timeout",
        type=float,
        default=15.0,
        help="seconds to look for the ring before connecting (default: %(default)s)",
    )
    parser.add_argument("--verbose", action="store_true", help="log raw frames to stderr")
    parser.add_argument("--version", action="version", version=f"prolo-ring {version()}")
    commands = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    doctor = commands.add_parser("doctor", help="check Python, Bluetooth, config, and the ring")
    doctor.add_argument("--no-scan", action="store_true", help="skip the Bluetooth scan")
    doctor.add_argument("--scan-timeout", type=float, default=5.0)

    rings = commands.add_parser("rings", help="discover rings").add_subparsers(
        dest="action", required=True, metavar="<action>"
    )
    rings_scan = rings.add_parser("scan", help="list nearby rings and their status")
    rings_scan.add_argument("--scan-timeout", type=float, default=8.0)

    init = commands.add_parser("init", help="save the default ring address")
    init.add_argument("--scan-timeout", type=float, default=8.0)
    init.add_argument(
        "ring_address",
        nargs="?",
        metavar="ADDRESS",
        help="address to save; omit to pick the only App Status ring nearby",
    )

    device = commands.add_parser("device", help="device facts").add_subparsers(
        dest="action", required=True, metavar="<action>"
    )
    device.add_parser("info", help="firmware, edition, battery, mode, MAC, nickname")
    device.add_parser("dump", help="info, settings, and profile in a single connection")

    group = commands.add_parser("settings", help="Ring Settings").add_subparsers(
        dest="action", required=True, metavar="<action>"
    )
    group.add_parser("list", help="describe every setting (no ring needed)")
    get = group.add_parser("get", help="read all settings, or one")
    get.add_argument("name", nargs="?")
    put = group.add_parser("set", help="change one setting and verify it")
    put.add_argument("name", choices=list(settings.SETTINGS), metavar="NAME")
    put.add_argument("value")
    put.add_argument(
        "--dry-run",
        action="store_true",
        help="read the current value and show the bytes without writing",
    )
    put.add_argument(
        "--force",
        action="store_true",
        help=f"allow writes on firmware other than {protocol.TESTED_FIRMWARE}",
    )

    prof = commands.add_parser("profile", help="gesture profile (read-only)").add_subparsers(
        dest="action", required=True, metavar="<action>"
    )
    read = prof.add_parser("read", help="read back the flashed profile and its flag groups")
    read.add_argument("--out", type=Path, help="also write the raw profile blob to this file")

    sheet = commands.add_parser(
        "cheatsheet", help="render a cheat sheet from a profile (no ring needed)"
    ).add_subparsers(dest="action", required=True, metavar="<action>")
    sheet_render = sheet.add_parser("render", help="Studio profile export to HTML or Markdown")
    sheet_render.add_argument(
        "--profile", type=Path, required=True, help="Prolo Studio profile export (JSON)"
    )
    sheet_render.add_argument(
        "--labels", type=Path, help="TOML: optional title, and [gestures] name = label"
    )
    sheet_render.add_argument("--format", choices=["html", "md", "svg"], default="html")
    sheet_render.add_argument(
        "--mode",
        choices=["cursor", "navigation", "touch", "air", "system", "all"],
        default="cursor",
        help="which overlay card to draw for --format svg (default: %(default)s)",
    )
    sheet_render.add_argument("--out", type=Path, help="write the sheet here instead of stdout")

    raw = commands.add_parser("raw", help="escape hatch for read opcodes").add_subparsers(
        dest="action", required=True, metavar="<action>"
    )
    raw_get = raw.add_parser("get", help="send a read opcode and print the reply bytes")
    raw_get.add_argument("opcode", type=int, help=f"one of {sorted(protocol.READ_OPCODES)}")
    raw_get.add_argument("--payload", default="", help="hex payload after the opcode")
    return parser


async def with_session(
    args: argparse.Namespace, work: Callable[[transport.Session], Awaitable[Any]]
) -> Any:
    session = await open_session(
        config.resolve_target(args.address).address,
        timeout=args.timeout,
        scan_timeout=args.scan_timeout,
        verbose=args.verbose,
    )
    async with session:
        return await work(session)


async def dump_ring(session: transport.Session) -> dict[str, Any]:
    """Everything readable in one connection: the ring stops advertising after a disconnect."""
    out: dict[str, Any] = {
        "device": await ring.device_info(session),
        "settings": await settings.get_settings(session),
    }
    try:
        out["profile"] = await ring.read_profile(session)
    except ProtocolError as error:
        out["profile"] = {"error": {"code": error.code, "message": error.message}}
    return out


async def cmd_doctor(args: argparse.Namespace) -> dict[str, Any]:
    target = config.resolve_target(args.address)
    report: dict[str, Any] = {
        "version": version(),
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
        "bleak": importlib.metadata.version("bleak"),
        "auth_required": False,
        "config": {"path": str(config.config_path()), "exists": config.config_path().is_file()},
        "target": {"address": target.address, "source": target.source},
        "bluetooth": {"checked": False},
        "next_steps": [],
    }
    if not args.no_scan:
        try:
            found = await scan(args.scan_timeout)
            report["bluetooth"] = {
                "checked": True,
                "ok": True,
                "rings": found,
                "target_visible": any(r["address"] == target.address for r in found),
            }
        except ProloError as error:
            report["bluetooth"] = {"checked": True, "ok": False, "error": error.message}
    steps = report["next_steps"]
    bt = report["bluetooth"]
    if bt.get("ok") is False:
        steps.append(
            "Turn Bluetooth on and grant this terminal Bluetooth access "
            "(System Settings > Privacy & Security > Bluetooth on macOS)."
        )
    if bt.get("ok") and not any(r["status"] == "app" for r in bt["rings"]):
        steps.append("No ring in App Status: 3x Tap + Hold on the Modstrip, then rescan.")
    if not target.address:
        steps.append("Save the ring with `prolo-ring init`.")
    report["ready"] = bool(target.address) and not steps
    return report


async def cmd_init(args: argparse.Namespace) -> dict[str, Any]:
    address = args.ring_address or args.address
    if not address:
        app_rings = [r for r in await scan(args.scan_timeout) if r["status"] == "app"]
        if len(app_rings) != 1:
            raise UsageError(
                f"found {len(app_rings)} rings in App Status; pass the address "
                "from `prolo-ring rings scan`",
                rings=app_rings,
            )
        address = app_rings[0]["address"]
    path = config.save_address(address)
    return {"address": address, "config": str(path)}


async def cmd_settings_set(args: argparse.Namespace) -> dict[str, Any]:
    async def work(session: transport.Session) -> dict[str, Any]:
        firmware = await session.firmware_revision()
        tested = bool(firmware) and protocol.firmware_base(firmware) == protocol.TESTED_FIRMWARE
        if not (tested or args.force or args.dry_run):
            raise UsageError(
                f"ring firmware {firmware!r} is untested (expected "
                f"{protocol.TESTED_FIRMWARE}); update it in Prolo Studio or pass "
                "--force",
                firmware=firmware,
            )
        result = await settings.set_setting(session, args.name, args.value, dry_run=args.dry_run)
        return {"firmware": firmware, **result}

    return await with_session(args, work)


async def cmd_settings_get(args: argparse.Namespace) -> dict[str, Any]:
    values = await with_session(args, settings.get_settings)
    if args.name:
        if args.name not in values:
            raise UsageError(f"unknown setting {args.name!r}; known: {', '.join(values)}")
        return {"setting": args.name, "value": values[args.name]}
    return values


def cmd_settings_list() -> list[dict[str, Any]]:
    rows = [
        {"name": s.name, "values": s.values, "writable": True, "description": s.help}
        for s in settings.SETTINGS.values()
    ]
    rows += [
        {"name": name, "values": "", "writable": False, "description": "read-only"}
        for name in settings.READ_ONLY
    ]
    return rows


async def cmd_profile_read(args: argparse.Namespace) -> dict[str, Any]:
    result = await with_session(args, ring.read_profile)
    if args.out:
        args.out.write_bytes(bytes.fromhex(result["blob_hex"]))
        result["out"] = {"path": str(args.out), "bytes": result["blob_size"]}
    return result


async def cmd_raw_get(args: argparse.Namespace) -> dict[str, Any]:
    if args.opcode not in protocol.READ_OPCODES:
        raise UsageError(f"raw get only sends read opcodes: {sorted(protocol.READ_OPCODES)}")
    try:
        payload = bytes.fromhex(args.payload)
    except ValueError as error:
        raise UsageError(f"--payload must be hex: {error}") from error

    async def work(session: transport.Session) -> dict[str, Any]:
        reply = await session.request(args.opcode, payload, min_len=1)
        return {
            "opcode": args.opcode,
            "request": protocol.frame(args.opcode, payload).hex(),
            "reply": reply.hex(),
        }

    return await with_session(args, work)


def cmd_cheatsheet_render(args: argparse.Namespace) -> dict[str, Any] | None:
    try:
        text = cheatsheet.render(args.profile, args.labels, args.format, mode=args.mode)
    except (OSError, ValueError) as error:
        raise UsageError(f"cannot render the cheat sheet: {error}") from error
    if args.out:
        args.out.write_text(text)
        return {"out": str(args.out), "bytes": len(text.encode()), "format": args.format}
    if args.json:
        return {"format": args.format, "document": text}
    sys.stdout.write(text)
    return None


async def dispatch(args: argparse.Namespace) -> Any:
    match (args.command, getattr(args, "action", None)):
        case ("doctor", _):
            return await cmd_doctor(args)
        case ("rings", "scan"):
            return await scan(args.scan_timeout)
        case ("init", _):
            return await cmd_init(args)
        case ("device", "info"):
            return await with_session(args, ring.device_info)
        case ("device", "dump"):
            return await with_session(args, dump_ring)
        case ("settings", "list"):
            return cmd_settings_list()
        case ("settings", "get"):
            return await cmd_settings_get(args)
        case ("settings", "set"):
            return await cmd_settings_set(args)
        case ("profile", "read"):
            return await cmd_profile_read(args)
        case ("raw", "get"):
            return await cmd_raw_get(args)
        case ("cheatsheet", "render"):
            return cmd_cheatsheet_render(args)
    raise UsageError(f"unknown command {args.command}")


def render(value: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(value, dict):
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{pad}{key}:")
                lines.append(render(item, indent + 1))
            else:
                lines.append(f"{pad}{key}: {item}")
        return "\n".join(lines)
    if isinstance(value, list):
        return "\n".join(
            f"{pad}-\n{render(item, indent + 1)}" if isinstance(item, dict) else f"{pad}- {item}"
            for item in value
        )
    return f"{pad}{value}"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        data = asyncio.run(dispatch(args))
    except ProloError as error:
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": error.code,
                            "message": error.message,
                            "details": error.details,
                        },
                    },
                    default=str,
                )
            )
        else:
            print(f"prolo-ring: {error.message}", file=sys.stderr)
        return error.exit_code
    except KeyboardInterrupt:
        return 130
    if data is None:
        return 0
    if args.json:
        print(json.dumps({"ok": True, "data": data}, default=str))
    else:
        print(render(data))
    return 0
