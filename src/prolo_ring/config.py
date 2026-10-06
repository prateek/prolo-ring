"""Locate the ring to talk to: flag, environment, then the user config file."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

ENV_ADDRESS = "PROLO_RING_ADDRESS"


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "prolo-ring" / "config.toml"


@dataclass(frozen=True)
class Target:
    address: str | None
    source: str  # "flag", "env", "config", or "missing"


def load_config(path: Path | None = None) -> dict:
    path = path or config_path()
    if not path.is_file():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def resolve_target(flag: str | None, path: Path | None = None) -> Target:
    if flag:
        return Target(flag, "flag")
    if env := os.environ.get(ENV_ADDRESS):
        return Target(env, "env")
    if address := load_config(path).get("address"):
        return Target(str(address), "config")
    return Target(None, "missing")


def save_address(address: str, path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    escaped = address.replace("\\", "\\\\").replace('"', '\\"')
    path.write_text(f'address = "{escaped}"\n')
    return path
