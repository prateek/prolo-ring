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
        self.address: str | None = None
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


REFRESH_HINT = (
    "put the ring in App Status (3x Tap + Hold on the Modstrip) or refresh its 60-second "
    "advertising window (2x Tap + Hold), then retry"
)


def pick_ring(address: str | None, seen: dict[str, tuple[Any, str | None]]) -> Any:
    """Choose the device to connect to from scan results: the saved address if it is advertising
    in App Status, else the only App Status ring in range. The ring's address rotates between
    boots on CoreBluetooth, so the saved one is a preference, not a requirement."""
    apps = {addr: device for addr, (device, name) in seen.items() if classify(name) == "app"}
    if address in apps:
        return apps[address]
    if len(apps) == 1:
        (device,) = apps.values()
        if address and address in seen:
            log(f"ring at {address} is not in App Status; using {device.address} instead")
        return device
    if address in seen:
        raise RingNotFound(
            f"ring at {address} is advertising as {seen[address][1]!r}, not in App Status; "
            "3x Tap + Hold on the Modstrip, then retry",
            address=address,
        )
    if len(apps) > 1:
        raise RingNotFound(
            f"{len(apps)} rings in App Status; pass --address with one of {sorted(apps)}",
            rings=sorted(apps),
        )
    raise RingNotFound(f"no ring in App Status within range; {REFRESH_HINT}", address=address)


async def find_ring(address: str | None, *, scan_timeout: float, verbose: bool = False) -> Any:
    from bleak import BleakScanner

    seen: dict[str, tuple[Any, str | None]] = {}

    def wanted(device: Any, adv: Any) -> bool:
        name = adv.local_name or device.name
        seen[device.address] = (device, name)
        return device.address == address and classify(name) == "app"

    try:
        device = await BleakScanner.find_device_by_filter(wanted, timeout=scan_timeout)
    except Exception as error:
        raise _bluetooth_error(error) from error
    if verbose:
        log(f"scan saw {len(seen)} devices; ring matched directly: {device is not None}")
    return device if device is not None else pick_ring(address, seen)


async def open_session(
    address: str | None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    scan_timeout: float = 15.0,
    verbose: bool = False,
) -> Session:
    """Scan, then connect with the device object the scan returned. On CoreBluetooth a second
    discovery by address string is unreliable, and the ring only advertises briefly."""
    from bleak import BleakClient

    device = await find_ring(address, scan_timeout=scan_timeout, verbose=verbose)
    session = Session(
        BleakClient(device, timeout=max(timeout, 10.0)), timeout=timeout, verbose=verbose
    )
    session.address = device.address
    return session
