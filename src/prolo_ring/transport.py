"""Bluetooth LE session with the ring in App Status. Every write passes the opcode allowlist."""

from __future__ import annotations

import asyncio
import contextlib
import platform
import sys
from collections.abc import Callable
from typing import Any, Protocol

from . import protocol
from .errors import BluetoothError, ProtocolError, RefusedOpcode, RingNotFound

IS_DARWIN = platform.system() == "Darwin"
# CoreBluetooth replies are slow to surface; Prolo Studio waits at least 8 s on macOS.
DEFAULT_TIMEOUT = 8.0 if IS_DARWIN else 3.0


class GattClient(Protocol):
    async def connect(self) -> Any: ...
    async def disconnect(self) -> Any: ...
    async def start_notify(
        self, char: str, callback: Callable[[Any, bytearray], Any], /
    ) -> Any: ...
    async def stop_notify(self, char: str, /) -> Any: ...
    async def write_gatt_char(
        self, char: str, data: bytes, /, response: bool | None = None
    ) -> Any: ...
    async def read_gatt_char(self, char: str, /) -> bytearray: ...


def log(message: str) -> None:
    print(message, file=sys.stderr)


class Session:
    def __init__(
        self,
        client: GattClient,
        *,
        darwin: bool = IS_DARWIN,
        timeout: float = DEFAULT_TIMEOUT,
        verbose: bool = False,
    ) -> None:
        self.client = client
        self.darwin = darwin
        self.timeout = timeout
        self.verbose = verbose
        self.sent: list[bytes] = []
        self._pending: tuple[asyncio.Future[bytes], Callable[[bytes], bool]] | None = None

    async def __aenter__(self) -> Session:
        try:
            await self.client.connect()
            await self.client.start_notify(protocol.COMMAND_CHAR_UUID, self._on_notify)
        except Exception as error:
            raise _bluetooth_error(error) from error
        return self

    async def __aexit__(self, *exc: object) -> None:
        with contextlib.suppress(Exception):
            await self.client.stop_notify(protocol.COMMAND_CHAR_UUID)
        with contextlib.suppress(Exception):
            await self.client.disconnect()

    def _on_notify(self, _sender: Any, data: bytearray) -> None:
        message = bytes(data)
        if self.verbose:
            log(f"<- {message.hex()}")
        if self._pending and not self._pending[0].done() and self._pending[1](message):
            self._pending[0].set_result(message)

    async def write(self, opcode: int, payload: bytes = b"") -> None:
        if opcode not in protocol.ALLOWED_OPCODES:
            raise RefusedOpcode(
                f"opcode {opcode} is not on the read/settings allowlist", opcode=opcode
            )
        message = protocol.frame(opcode, payload)
        if self.verbose:
            log(f"-> {message.hex()}")
        try:
            await self.client.write_gatt_char(
                protocol.COMMAND_CHAR_UUID, message, response=self.darwin
            )
        except Exception as error:
            raise _bluetooth_error(error) from error
        self.sent.append(message)
        if self.darwin:
            await asyncio.sleep(0.08)

    async def request(
        self,
        opcode: int,
        payload: bytes = b"",
        *,
        min_len: int = 2,
        match: Callable[[bytes], bool] | None = None,
        timeout: float | None = None,
    ) -> bytes:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bytes] = loop.create_future()

        def predicate(message: bytes) -> bool:
            return (
                len(message) >= min_len
                and message[0] == opcode
                and (match is None or match(message))
            )

        self._pending = (future, predicate)
        try:
            await self.write(opcode, payload)
            return await asyncio.wait_for(future, timeout or self.timeout)
        except TimeoutError as error:
            raise ProtocolError(
                f"no reply to opcode {opcode} within {timeout or self.timeout}s", opcode=opcode
            ) from error
        finally:
            self._pending = None

    async def firmware_revision(self) -> str | None:
        try:
            raw = await self.client.read_gatt_char(protocol.FIRMWARE_REVISION_UUID)
        except Exception:
            return None
        return bytes(raw).decode("utf-8", errors="replace").strip()


def _bluetooth_error(error: Exception) -> BluetoothError | RingNotFound:
    name = type(error).__name__
    if "NotFound" in name:
        return RingNotFound(
            f"ring not found: {error}. Put it in App Status (3x Tap + Hold) and "
            "run `prolo-ring rings scan`."
        )
    return BluetoothError(f"{name}: {error}")


def classify(name: str | None) -> str | None:
    lowered = (name or "").lower()
    if "prolo app" in lowered:
        return "app"
    if lowered.startswith("dfutarg"):
        return "dfu"
    if "prolo" in lowered:
        return "device"
    return None


async def scan(timeout: float) -> list[dict[str, Any]]:
    from bleak import BleakScanner

    try:
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
    except Exception as error:
        raise _bluetooth_error(error) from error
    rings = []
    for address, (device, adv) in found.items():
        name = adv.local_name or device.name
        if status := classify(name):
            rings.append(
                {
                    "address": address,
                    "name": name,
                    "status": status,
                    "rssi": adv.rssi,
                    "connectable": status == "app",
                }
            )
    return sorted(rings, key=lambda ring: -(ring["rssi"] or -999))


def open_session(
    address: str, *, timeout: float = DEFAULT_TIMEOUT, verbose: bool = False
) -> Session:
    from bleak import BleakClient

    return Session(
        BleakClient(address, timeout=max(timeout, 10.0)), timeout=timeout, verbose=verbose
    )
