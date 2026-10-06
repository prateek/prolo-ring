"""Error types that map to stable JSON error codes and process exit codes."""

from __future__ import annotations


class ProloError(Exception):
    code = "error"
    exit_code = 1

    def __init__(self, message: str, **details: object) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class UsageError(ProloError):
    code = "usage"
    exit_code = 2


class RingNotFound(ProloError):
    code = "ring_not_found"
    exit_code = 3


class BluetoothError(ProloError):
    code = "bluetooth"
    exit_code = 4


class ProtocolError(ProloError):
    code = "protocol"
    exit_code = 5


class RefusedOpcode(ProloError):
    """Raised before any byte is sent when an opcode is outside the safe allowlist."""

    code = "refused"
    exit_code = 6
