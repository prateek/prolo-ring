"""Read operations against a connected ring: snapshot, device info, profile readback."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from . import protocol as p
from .errors import ProtocolError
from .profile import ProfileFormatError, decode_profile, profile_size
from .transport import Session


@dataclass(frozen=True)
class Snapshot:
    config: p.AllConfig
    edge_scroll_step: int
    nickname: str


async def read_config(session: Session) -> p.AllConfig:
    reply = await session.request(p.GET_ALL_CONFIG, min_len=20)
    try:
        return p.parse_all_config(reply)
    except ValueError as error:
        raise ProtocolError(str(error)) from error


async def read_snapshot(session: Session) -> Snapshot:
    config = await read_config(session)
    step = p.parse_u8_get(await session.request(p.GET_EDGE_SCROLL_STEP), p.GET_EDGE_SCROLL_STEP)
    name = p.parse_user_name(await session.request(p.GET_USER_NAME, min_len=1))
    return Snapshot(config=config, edge_scroll_step=step, nickname=name)


async def read_flag_group(session: Session, group: int) -> int:
    reply = await session.request(
        p.GET_FLAG_GROUP, bytes([group]), min_len=4, match=lambda m: m[1] == group
    )
    return p.parse_flag_group(reply, group)


async def _optional(coro: Any) -> Any:
    try:
        return await coro
    except ProtocolError:
        return None


async def device_info(session: Session) -> dict[str, Any]:
    firmware = await session.firmware_revision()
    config = await read_config(session)
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
    mac_reply = await _optional(session.request(p.GET_MAC_ADDRESS, min_len=15))
    name_reply = await _optional(session.request(p.GET_USER_NAME, min_len=1))
    edition = p.parse_license_flags(license_reply) if license_reply else None
    return {
        "firmware": firmware,
        "firmware_tested": bool(firmware) and p.firmware_base(firmware) == p.TESTED_FIRMWARE,
        "config_version": config.config_version,
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
