"""Portable, versioned credentials for exactly one AquaSense 2."""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .const import PRODUCT_ID

KEY_FILE_FORMAT = "beatbot_aquasense2_local_key"
MAX_KEY_FILE_BYTES = 16384


class InvalidKeyFile(ValueError):
    """Invalid import. Messages must never contain uploaded values."""


@dataclass(frozen=True)
class RobotCredentials:
    device_id: str
    local_key: str = field(repr=False)
    host: str = ""
    version: float = 3.3

    def as_config(self) -> dict[str, Any]:
        return {"device_id": self.device_id, "local_key": self.local_key,
                "host": self.host, "version": self.version}

    def as_key_file(self) -> dict[str, Any]:
        return {"format": KEY_FILE_FORMAT, "format_version": 1,
                "product_id": PRODUCT_ID, "device_id": self.device_id,
                "local_key": self.local_key, "host": self.host,
                "protocol_version": "3.3"}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidKeyFile("Duplicate field")
        result[key] = value
    return result


def parse_key_file(content: bytes) -> RobotCredentials:
    if len(content) > MAX_KEY_FILE_BYTES:
        raise InvalidKeyFile("File too large")
    try:
        data = json.loads(content.decode("utf-8-sig"), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidKeyFile("Invalid JSON") from None
    if not isinstance(data, dict):
        raise InvalidKeyFile("Expected one robot")
    if data.get("format") != KEY_FILE_FORMAT or type(data.get("format_version")) is not int or data["format_version"] != 1:
        raise InvalidKeyFile("Unsupported file format")
    if data.get("product_id") != PRODUCT_ID or data.get("protocol_version", "3.3") != "3.3":
        raise InvalidKeyFile("Unsupported robot or protocol")
    device_id, local_key = data.get("device_id"), data.get("local_key")
    if not isinstance(device_id, str) or not re.fullmatch(r"[a-zA-Z0-9]{8,64}", device_id):
        raise InvalidKeyFile("Invalid robot ID")
    if not isinstance(local_key, str) or len(local_key) != 16 or not all(32 <= ord(c) <= 126 for c in local_key):
        raise InvalidKeyFile("Invalid local key")
    host = data.get("host", "")
    if not isinstance(host, str):
        raise InvalidKeyFile("Invalid LAN address")
    if host:
        try:
            address = ipaddress.ip_address(host)
            if address.version != 4 or not address.is_private or address.is_loopback or address.is_unspecified or address.is_multicast:
                raise ValueError
        except ValueError:
            raise InvalidKeyFile("Invalid LAN address") from None
    return RobotCredentials(device_id, local_key, host)


def read_key_file(path: Path) -> RobotCredentials:
    with path.open("rb") as source:
        return parse_key_file(source.read(MAX_KEY_FILE_BYTES + 1))
