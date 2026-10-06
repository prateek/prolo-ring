"""A simulated ring in App Status that answers the opcodes the way docs/protocol.md describes."""

from __future__ import annotations

import struct
from collections.abc import Callable
from typing import Any

COMMAND_CHAR = "b46e428d-e64c-4c44-8020-844bb9b6e7d6"
FIRMWARE_CHAR = "00002a26-0000-1000-8000-00805f9b34fb"


class FakeRing:
    def __init__(
        self,
        *,
        firmware: str = "1.0.7",
        config_version: int = 3,
        doubled_replies: bool = False,
        profile: bytes = b"",
    ) -> None:
        self.firmware = firmware
        self.doubled = doubled_replies
        self.profile = profile
        self.sensitivity = 40
        self.left_handed = 0
        self.tx_power = 0
        self.multi_tap = 1
        self.led = [0, 15]
        self.auto_sleep = 255
        self.edge_width = 20
        self.edge_step = 32
        self.nickname = b""
        self.config_version = config_version
        self.flags = {1: 0x000F, 2: 0x007F, 3: 0x0017, 4: 0x0007, 5: 0x62BF, 6: 0x0007}
        self.writes: list[bytes] = []
        self.connected = False
        self._callback: Callable[[Any, bytearray], Any] | None = None

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def start_notify(self, char: str, callback: Callable[[Any, bytearray], Any], /) -> None:
        assert char == COMMAND_CHAR
        self._callback = callback

    async def stop_notify(self, char: str, /) -> None:
        self._callback = None

    async def read_gatt_char(self, char: str, /) -> bytearray:
        assert char == FIRMWARE_CHAR
        return bytearray(self.firmware.encode())

    def _reply(self, data: bytes) -> None:
        assert self._callback is not None
        self._callback(None, bytearray(data))

    def _get(self, op: int, value: bytes) -> None:
        self._reply(bytes([op, op]) + value if self.doubled else bytes([op]) + value)

    async def write_gatt_char(
        self, char: str, data: bytes, /, response: bool | None = None
    ) -> None:
        assert char == COMMAND_CHAR
        self.writes.append(bytes(data))
        op, body = data[0], bytes(data[1:])
        match op:
            case 123:
                dump = struct.pack(
                    "<9B5H",
                    self.config_version,
                    self.sensitivity,
                    self.left_handed,
                    self.tx_power,
                    self.multi_tap,
                    self.led[0],
                    self.led[1],
                    self.auto_sleep,
                    self.edge_width,
                    *(self.flags[g] for g in (1, 2, 3, 4, 5)),
                )
                self._get(op, dump)
            case 122:
                self._get(op, bytes([self.edge_step]))
            case 102:
                self._reply(bytes([op]) + self.nickname + b"\x00")
            case 118:
                group = body[0]
                self._reply(struct.pack("<BBH", op, group, self.flags[group]))
            case 117:
                group, value = struct.unpack("<BH", body)
                self.flags[group] = value
                self._reply(bytes([op, 0]))
            case 121:
                self.edge_step = body[0]
                self._reply(bytes([op, 0]))
            case 103:
                self.sensitivity = body[0]
            case 105:
                self.left_handed = body[0]
            case 109:
                self.led = [body[0], body[1]]
            case 111:
                self.multi_tap = body[0]
            case 113:
                self.auto_sleep = body[0]
            case 101:
                self.nickname = body
            case 120:
                self._reply(bytes([op, 87, 0, 1]))
            case 205:
                self._reply(bytes([op, 2, 0]))
            case 129:
                self._reply(bytes([op, 1, 0x02]) + bytes(6) + bytes.fromhex("D0A1B2C3D4E5"))
            case 133:
                offset, length = struct.unpack("<HH", body)
                chunk = self.profile[offset : offset + length]
                self._reply(bytes([op]) + chunk if chunk else bytes([op, 0x02]))
            case _:
                raise AssertionError(f"fake ring got unexpected opcode {op}")
