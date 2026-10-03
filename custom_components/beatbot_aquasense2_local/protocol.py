"""TinyTuya transport. All functions in this module run in an executor."""

from __future__ import annotations

import base64
import ipaddress
import threading
from dataclasses import dataclass
from typing import Any

import tinytuya
from tinytuya import scanner

from .const import IDLE_STATES, MODE_VALUES, PARK_ACTIVE_STATES, PARK_DONE_STATES, PRODUCT_ID, STATUS_VALUES, VALUE_MODES
from .runtime import Program

SOCKET_TIMEOUT = 2
SOCKET_RETRY_LIMIT = 1
MAX_DISCOVERY_SECONDS = 12


class BeatbotConnectionError(Exception):
    """The robot did not return a usable LAN response."""


def discover(device_id: str | None = None, seconds: int = 12) -> list[dict[str, Any]]:
    """Listen for the AquaSense 2 product; never return keys or tokens."""
    if type(seconds) is not int or not 1 <= seconds <= MAX_DISCOVERY_SECONDS:
        raise ValueError("Discovery duration must be between 1 and 12 seconds")
    kwargs: dict[str, Any] = {}
    if device_id:
        kwargs["wantids"] = [device_id]
        kwargs["tuyadevices"] = [{"id": device_id, "key": "", "name": "Beatbot"}]
    found = scanner.devices(
        verbose=False,
        scantime=seconds,
        color=False,
        poll=False,
        forcescan=False,
        byID=True,
        show_timer=False,
        **kwargs,
    )
    result = []
    for item in found.values():
        if item.get("productKey") != PRODUCT_ID:
            continue
        host = item.get("ip", "")
        try:
            if not ipaddress.ip_address(host).is_private:
                continue
        except ValueError:
            continue
        result.append({"device_id": item.get("id") or item.get("gwId"), "host": host,
                       "version": str(item.get("version", "3.3"))})
    return [item for item in result if item["device_id"]]


def decode_mode(value: Any) -> str | None:
    """DP132 is a four-byte, big-endian raw Tuya value."""
    try:
        raw = base64.b64decode(value, validate=True)
        if len(raw) != 4:
            return None
        return VALUE_MODES.get(int.from_bytes(raw, "big"))
    except (TypeError, ValueError):
        return None


def encode_mode(mode: str) -> str:
    return base64.b64encode(MODE_VALUES[mode].to_bytes(4, "big")).decode("ascii")


def status_name(dps: dict[str, Any]) -> str | None:
    """The actual AquaSense 2 exposes numeric work status at DP165."""
    value = dps.get("165")
    if type(value) is int:
        return STATUS_VALUES.get(value)
    value = dps.get("5")
    return value if isinstance(value, str) and value in STATUS_VALUES.values() else None


def decode_filter_basket_missing(value: Any) -> bool | None:
    """Only tested DP107 values: 2 missing basket, 0 clear.

    Do not guess bitmap combinations or equate another fault with a present
    basket. Unknown codes and malformed responses stay unknown.
    """
    if type(value) is not int:
        return None
    return {0: False, 2: True}.get(value)


@dataclass(slots=True)
class PollResult:
    dps: dict[str, Any]
    mode_confirmed: bool = False
    park_sent: bool = False
    park_echo: bool = False


class LocalBeatbot:
    """One robot; create a short-lived socket per poll."""

    def __init__(self, device_id: str, host: str, local_key: str, version: float = 3.3) -> None:
        self.device_id = device_id
        self.host = host
        self.local_key = local_key
        self.version = version
        self._stop = threading.Event()

    def request_stop(self) -> None:
        """Cooperatively skip further commands; never close a worker's socket here."""
        self._stop.set()

    def clear_stop(self) -> None:
        self._stop.clear()

    def _check_stop(self) -> None:
        if self._stop.is_set():
            raise BeatbotConnectionError("Transport stopping")

    def poll(self, park_due: bool = False, mode_to_set: str | Program | None = None) -> PollResult:
        self._check_stop()
        device = tinytuya.Device(self.device_id, self.host, self.local_key, version=self.version)
        device.set_socketTimeout(SOCKET_TIMEOUT)
        # TinyTuya counts connection attempts here: zero skips socket creation.
        device.set_socketRetryLimit(SOCKET_RETRY_LIMIT)
        device.set_socketPersistent(True)
        try:
            response = device.status()
            self._check_stop()
            if not isinstance(response, dict) or not isinstance(response.get("dps"), dict):
                raise BeatbotConnectionError("No valid status response")
            dps = response["dps"]
            result = PollResult(dps=dps)
            state = status_name(dps)
            if mode_to_set and state in IDLE_STATES:
                program = mode_to_set if isinstance(mode_to_set, Program) else Program(mode_to_set)
                result.mode_confirmed = True
                for dp, value in program.writes().items():
                    self._check_stop()
                    written = device.set_value(dp, value)
                    confirmed = (isinstance(written, dict)
                                 and isinstance(written.get("dps"), dict)
                                 and written["dps"].get(dp) == value)
                    if not confirmed:
                        result.mode_confirmed = False
                        break
                # Never merge control echoes into the pre-write observation.
            # The app itself refuses parking while the robot is out of the pool.
            position = dps.get("154")
            in_pool = type(position) is int and position != 0
            if park_due and in_pool and state in PARK_ACTIVE_STATES and state not in PARK_DONE_STATES:
                self._check_stop()
                result.park_sent = True
                written = device.set_value("152", 1)
                result.park_echo = (
                    isinstance(written, dict)
                    and isinstance(written.get("dps"), dict)
                    and written["dps"].get("152") == 1
                )
            return result
        finally:
            device.close()
