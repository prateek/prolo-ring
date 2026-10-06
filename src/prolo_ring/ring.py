"""Read operations against a connected ring: snapshot, device info, profile readback."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from . import protocol as p
from .errors import ProtocolError, Unsupported
from .profile import ProfileFormatError, decode_profile, profile_size
from .transport import Session

# Firmware older than the compact config dump answers these one at a time.
LEGACY_U8_GETS = {
    "sensitivity": p.GET_SENSITIVITY,
    "left_handed": p.GET_LEFTHAND,
    "tx_power_mode": p.GET_TX_POWER_MODE,
    "multi_tap": p.GET_MULTITAP_MODE,
    "auto_sleep_wire": p.GET_AUTO_SLEEP_TIMEOUT,
    "edge_scroll_width": p.GET_EDGE_SCROLL_WIDTH,
}


@dataclass(frozen=True)
class Snapshot:
    config: p.AllConfig
    edge_scroll_step: int | None
    nickname: str
    legacy: bool


def _convert(error: ValueError) -> ProtocolError:
    if isinstance(error, p.UnsupportedReply):
        return Unsupported(str(error))
    return ProtocolError(str(error))


async def _optional(coro: Any) -> Any:
    try:
        return await coro
    except ProtocolError:
        return None


async def read_config(session: Session) -> p.AllConfig:
    reply = await session.request(p.GET_ALL_CONFIG)
    try:
        return p.parse_all_config(reply)
    except ValueError as error:
        raise _convert(error) from error


async def read_u8(session: Session, opcode: int) -> int:
    reply = await session.request(opcode)
    if p.is_error_reply(reply) and opcode != p.GET_AUTO_SLEEP_TIMEOUT:
        raise Unsupported(f"opcode {opcode} answered ERR")
    return p.parse_u8_get(reply, opcode)


async def read_flag_group(session: Session, group: int) -> int:
    reply = await session.request(
        p.GET_FLAG_GROUP, bytes([group]), match=lambda m: m[1] in (group, 0xFF)
    )
    try:
        return p.parse_flag_group(reply, group)
    except ValueError as error:
        raise _convert(error) from error


async def read_config_legacy(session: Session) -> p.AllConfig:
    """Assemble the config from individual GETs. config_version 0 marks the legacy protocol."""
    values: dict[str, Any] = {}
    for field, opcode in LEGACY_U8_GETS.items():
        values[field] = await _optional(read_u8(session, opcode))
    led = await _optional(session.request(p.GET_LED_POWER_MODE, min_len=3))
    flags: dict[str, int] = {}
    for group, name in p.FLAG_GROUPS.items():
        if name == "modnav":
            continue
        value = await _optional(read_flag_group(session, group))
        if value is not None:
            flags[name] = value
    if values["sensitivity"] is None and led is None:
        raise Unsupported("ring answered neither GET_ALL_CONFIG nor the individual GETs")
    return p.AllConfig(
        config_version=0,
        sensitivity=values["sensitivity"] or 0,
        left_handed=bool(values["left_handed"]),
        tx_power_mode=values["tx_power_mode"] or 0,
        multi_tap=bool(values["multi_tap"]),
        led_mode=led[1] if led else 0,
        led_brightness=led[2] if led else 0,
        auto_sleep_wire=p.AUTO_SLEEP_NEVER
        if values["auto_sleep_wire"] is None
        else values["auto_sleep_wire"],
        edge_scroll_width=values["edge_scroll_width"] or 0,
        flags=flags,
    )


async def read_snapshot(session: Session) -> Snapshot:
    legacy = False
    try:
        config = await read_config(session)
    except Unsupported:
        legacy = True
        config = await read_config_legacy(session)
    step = await _optional(read_u8(session, p.GET_EDGE_SCROLL_STEP))
    name = p.parse_user_name(await session.request(p.GET_USER_NAME, min_len=1))
    return Snapshot(config=config, edge_scroll_step=step, nickname=name, legacy=legacy)


async def device_info(session: Session) -> dict[str, Any]:
    firmware = await session.firmware_revision()
    config_version: int | None
    try:
        config_version = (await read_config(session)).config_version
    except Unsupported:
        config_version = None
    # The first keepalive after connect can report a placeholder battery; use the second.
    telemetry = None
    for _ in range(2):
        reply = await _optional(
            session.request(p.PING_KEEPALIVE, p.KEEPALIVE_REQUEST[1:], min_len=4)
        )
        if reply:
            telemetry = p.parse_keepalive(reply)
        await asyncio.sleep(0.3)
    license_reply = await _optional(session.request(p.GET_LICENSE_FLAGS))
    mac_reply = await _optional(session.request(p.GET_MAC_ADDRESS))
    name_reply = await _optional(session.request(p.GET_USER_NAME, min_len=1))
    edition = p.parse_license_flags(license_reply) if license_reply else None
    return {
        "firmware": firmware,
        "address": session.address,
        "firmware_tested": bool(firmware) and p.firmware_base(firmware) == p.TESTED_FIRMWARE,
        "legacy_protocol": config_version is None,
        "config_version": config_version,
        "nickname": p.parse_user_name(name_reply) if name_reply else None,
        "mac_address": p.parse_mac(mac_reply) if mac_reply else None,
        "edition": edition[1] if edition else None,
        "license_flags": edition[0] if edition else None,
        "battery_percent": telemetry.battery_percent if telemetry else None,
        "mode": telemetry.mode if telemetry else None,
    }


def _is_status_reply(reply: bytes) -> bool:
    return len(reply) == 2 and reply[1] in (0xFF, 1, 2, 3, 4)


async def read_profile_blob(session: Session) -> bytes:
    blob = bytearray()
    while len(blob) < p.PROFILE_MAX_SIZE:
        reply = await session.request(
            p.FLASH_PROFILE_READBACK, p.encode_readback(len(blob))[1:], min_len=1
        )
        if not blob and p.is_error_reply(reply):
            raise Unsupported("FLASH_PROFILE_READBACK answered ERR; this firmware has no readback")
        if _is_status_reply(reply) or len(reply) <= 1:
            if not blob:
                raise ProtocolError(f"profile readback failed: {p.status_name(reply[-1])}")
            break
        blob.extend(reply[1:])
        size = profile_size(bytes(blob))
        if size is not None and len(blob) >= size:
            return bytes(blob[:size])
        if len(reply) - 1 < p.READBACK_CHUNK:
            break
    return bytes(blob)


async def read_profile(session: Session) -> dict[str, Any]:
    blob = await read_profile_blob(session)
    try:
        decoded: dict[str, Any] = decode_profile(blob)
    except ProfileFormatError as error:
        decoded = {"decode_error": str(error)}
    flags = {}
    for group, name in p.FLAG_GROUPS.items():
        value = await _optional(read_flag_group(session, group))
        flags[name] = (
            None if value is None else {"raw": f"0x{value:04X}", **p.decode_flags(name, value)}
        )
    return {
        "blob_hex": blob.hex(),
        "blob_size": len(blob),
        "profile": decoded,
        "profile_settings": flags,
    }
