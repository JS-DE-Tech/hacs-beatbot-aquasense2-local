"""Program identities and conservative, persistent runtime learning (no HA I/O)."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from statistics import median
from math import isfinite
from typing import Any

from .const import MODE_VALUES

MULTI_DURATIONS = ("Max", "2h", "1h")
RUNNING = {"cleaning", "diving", "emerge", "return_trip"}
READY = {"standby", "charging", "charge_done", "sleep", "clean_done", "dock", "clean_wait"}
MAX_EDGE_GAP = 90  # Seconds: never learn an unbounded underwater completion delay.
MAX_RUN = 12 * 3600
SURFACE_WINDOW = 10 * 60  # Observed Boden return-to-edge phase, not an offline completion timer.


def raw_number(value: Any) -> int | None:
    try:
        raw = base64.b64decode(value, validate=True)
        return int.from_bytes(raw, "big") if len(raw) == 4 else None
    except (TypeError, ValueError):
        return None


def encode_raw(value: int) -> str:
    return base64.b64encode(value.to_bytes(4, "big")).decode("ascii")


@dataclass(frozen=True)
class Program:
    mode: str
    floor: int = 1
    wall: int = 1
    duration: str = "Max"

    def __post_init__(self) -> None:
        if self.mode not in MODE_VALUES:
            raise ValueError("Unknown mode")
        if type(self.floor) is not int or type(self.wall) is not int:
            raise ValueError("Invalid repetitions")
        if self.floor not in range(3) or self.wall not in range(3) or not (self.floor or self.wall):
            raise ValueError("At least one area must be selected")
        if self.duration not in MULTI_DURATIONS:
            raise ValueError("Invalid duration")

    @property
    def key(self) -> str:
        if self.mode == "Bereich":
            return f"Bereich:floor={self.floor}:wall={self.wall}"
        if self.mode == "MultiZone":
            return f"MultiZone:{self.duration}"
        return self.mode

    def writes(self) -> dict[str, Any]:
        result: dict[str, Any] = {"132": encode_raw(MODE_VALUES[self.mode])}
        if self.mode == "Bereich":
            result.update({"114": self.floor, "115": self.wall,
                           "106": "/".join(name for name, count in
                                           (("clean_floor", self.floor), ("clean_wall", self.wall)) if count)})
        elif self.mode == "MultiZone":
            result["131"] = encode_raw(MULTI_DURATIONS.index(self.duration))
        return result

    @classmethod
    def from_dps(cls, dps: dict[str, Any]) -> Program | None:
        mode = next((name for name, value in MODE_VALUES.items() if value == raw_number(dps.get("132"))), None)
        if mode is None:
            return None
        try:
            if mode == "Bereich":
                areas = dps.get("106")
                if not isinstance(areas, str) or not areas or any(area not in {"clean_floor", "clean_wall"} for area in areas.split("/")):
                    return None
                return cls(mode, floor=dps.get("114") if "clean_floor" in areas.split("/") else 0,
                           wall=dps.get("115") if "clean_wall" in areas.split("/") else 0)
            if mode == "MultiZone":
                value = raw_number(dps.get("131"))
                if value not in (0, 1, 2):
                    return None
                return cls(mode, duration=MULTI_DURATIONS[value])
            return cls(mode)
        except ValueError:
            return None


class RuntimeLearner:
    """Learn bounded starts and acknowledged ends, isolated by program.

    Runtime is wall-clock time. Paused/manual parking/uncertain runs are excluded.
    Offline gaps during a run are fine, but neither endpoint may be unbounded.
    Device DP9 is deliberately not used until its lifecycle is verified live.
    """

    def __init__(self) -> None:
        self.history: dict[str, list[float]] = {}
        self.battery_history: dict[str, list[int]] = {}
        self.imported_samples: dict[str, str] = {}
        self.manual_seconds: dict[str, float] = {}
        self.active: dict[str, Any] | None = None
        self.previous_state: str | None = None
        self.previous_at: float | None = None
        self.last_result = "waiting_for_run"
        self._ready_battery: tuple[float, int] | None = None

    def dump(self) -> dict:
        return {"history": self.history, "battery_history": self.battery_history,
                "manual_seconds": self.manual_seconds,
                "imported_samples": self.imported_samples, "active": self.active,
                "previous_state": self.previous_state, "previous_at": self.previous_at,
                "last_result": self.last_result}

    def restore(self, saved: Any) -> None:
        if not isinstance(saved, dict):
            return
        history = saved.get("history", {})
        if not isinstance(history, dict):
            history = {}
        for key, samples in history.items():
            if isinstance(key, str) and isinstance(samples, list):
                self.history[key] = [float(v) for v in samples if type(v) in (int, float) and 60 <= v <= MAX_RUN][-10:]
        battery_history = saved.get("battery_history", {})
        if isinstance(battery_history, dict):
            for key, samples in battery_history.items():
                if isinstance(key, str) and isinstance(samples, list):
                    self.battery_history[key] = [v for v in samples if type(v) is int and 0 <= v <= 100][-10:]
        imported = saved.get("imported_samples", {})
        if isinstance(imported, dict):
            self.imported_samples = {k: v for k, v in imported.items() if isinstance(k, str) and isinstance(v, str)}
        manual = saved.get("manual_seconds", {})
        if isinstance(manual, dict):
            self.manual_seconds = {k: float(v) for k, v in manual.items()
                                   if k in PROGRAMS and type(v) in (int, float) and 60 <= v <= MAX_RUN}
        active = saved.get("active")
        if isinstance(active, dict) and isinstance(active.get("key"), str) and type(active.get("start")) in (int, float) and isfinite(active["start"]):
            self.active = dict(active)
            # A restart can hide pauses, aborts or an entire second run.
            self.active["eligible"] = False
        self.last_result = "restarted" if self.active else "waiting_for_run"

    def cancel_training(self, reason: str) -> None:
        if self.active:
            self.active["eligible"] = False
        self.last_result = reason

    def observe(self, state: str | None, program: Program | None, now: float,
                parking: bool = False, battery: int | None = None,
                position: int | None = None) -> bool:
        """Return True only for a confirmed, uninterrupted natural completion."""
        if state is None:
            return False
        completed = False
        if state in READY and type(battery) is int and 0 <= battery <= 100:
            self._ready_battery = (now, battery)
        gap = now - self.previous_at if self.previous_at is not None else None
        bounded = gap is not None and 0 <= gap <= MAX_EDGE_GAP
        if self.active and (now - self.active["start"] > MAX_RUN or now < self.active["start"]):
            self.active = None
            self.last_result = "expired"
        if state in RUNNING and self.active is None:
            if program:
                if battery is None and self._ready_battery and bounded and self.previous_state in READY:
                    when, value = self._ready_battery
                    if 0 <= now - when <= MAX_EDGE_GAP:
                        battery = value
                self.active = {"key": program.key, "start": now,
                               "eligible": bounded and self.previous_state in READY,
                               "paused": False, "start_battery": battery,
                               "seen_work": state in {"cleaning", "diving"}}
                self.last_result = "tracking" if self.active["eligible"] else "start_uncertain"
        if self.active:
            if program and program.key != self.active["key"]:
                self.cancel_training("program_changed")
            if parking:
                self.cancel_training("parking_excluded")
            if state == "paused":
                self.active["paused"] = True
                self.cancel_training("pause_excluded")
            if state in RUNNING:
                self.active["paused"] = False
            if state in {"cleaning", "diving"}:
                self.active["seen_work"] = True
                self.active.pop("surface_at", None)
            if state == "emerge":
                self.active["surface_at"] = now
            surface_at = self.active.get("surface_at")
            surfaced = (type(surface_at) in (int, float) and 0 <= now - surface_at <= SURFACE_WINDOW)
            # Verified on Boden only. auto_dock by itself is NOT an end proof.
            natural_park = (state == "auto_dock" and self.active["key"] == "Boden"
                            and surfaced and position != 0 and self.active.get("seen_work", False))
            explicit_end = state == "clean_done" and bounded and self.previous_state in RUNNING
            if state == "clean_done" or state == "auto_dock":
                elapsed = now - self.active["start"]
                if self.active["eligible"] and (explicit_end or natural_park) and 60 <= elapsed <= MAX_RUN:
                    samples = self.history.setdefault(self.active["key"], [])
                    samples.append(elapsed)
                    del samples[:-10]
                    start_battery = self.active.get("start_battery")
                    if (type(start_battery) is int and type(battery) is int
                            and 0 <= battery <= start_battery <= 100):
                        samples = self.battery_history.setdefault(self.active["key"], [])
                        samples.append(start_battery - battery)
                        del samples[:-10]
                    self.last_result = "learned"
                    completed = True
                else:
                    self.last_result = "completion_uncertain_or_interrupted"
                self.active = None
            elif state in {"standby", "charging", "charge_done", "sleep", "dock", "remote_control", "goto_charge"}:
                # The observed surface sequence briefly reports standby while
                # still in the pool. Dry standby/pickup never extends a run.
                if not (state == "standby" and position in (1, 2) and surfaced):
                    self.active = None
                    self.last_result = "aborted_or_unconfirmed"
        self.previous_state, self.previous_at = state, now
        return completed

    def import_samples(self, samples: list[dict]) -> int:
        """Validated imports are explicit, deduplicated and never overwrite history."""
        # Check the whole batch before mutation; conflicting IDs are an error.
        for sample in samples:
            fingerprint = sample["fingerprint"]
            if sample["id"] in self.imported_samples and self.imported_samples[sample["id"]] != fingerprint:
                raise ValueError("Conflicting sample ID")
        added = 0
        for sample in samples:
            sample_id = sample["id"]
            if sample_id in self.imported_samples:
                continue
            history = self.history.setdefault(sample["key"], [])
            history.append(sample["duration_seconds"])
            del history[:-10]
            if sample["battery_used"] is not None:
                history = self.battery_history.setdefault(sample["key"], [])
                history.append(sample["battery_used"])
                del history[:-10]
            self.imported_samples[sample_id] = sample["fingerprint"]
            added += 1
        return added

    def battery_estimate(self, key: str | None, battery: int | None, *, stale: bool) -> dict:
        samples = self.battery_history.get(key, [])
        expected = median(samples) if len(samples) >= 2 else None
        # Conservatively compare with the largest of the last ten observations,
        # plus a five-percentage-point reserve. Never promise sufficient charge.
        required = max(samples) + 5 if expected is not None else None
        insufficient = (battery < required if required is not None and type(battery) is int
                        and 0 <= battery <= 100 and not stale else None)
        return {"program": key, "battery_sample_count": len(samples),
                "estimated_consumption_percent": expected, "required_battery_percent": required,
                "reserve_percent": 5, "insufficient": insufficient,
                "battery_stale": stale, "current_battery_percent": battery,
                "learning_state": "learned" if len(samples) >= 3 else "preliminary" if len(samples) == 2 else "learning"}

    def estimate(self, key: str | None) -> dict:
        samples = self.history.get(key, [])
        count = len(samples)
        manual = self.manual_seconds.get(key)
        return {"program": key, "sample_count": count,
                "learning_state": "manual" if manual is not None else "learned" if count >= 3 else "preliminary" if count == 2 else "learning",
                "manual_seconds": manual,
                "estimated_seconds": manual if manual is not None else median(samples) if count >= 2 else None,
                "min_seconds": min(samples) if samples else None,
                "max_seconds": max(samples) if samples else None}

    def remaining(self, now: float) -> dict:
        active = self.active
        result = self.estimate(active["key"] if active else None)
        result.update({"remaining_seconds": None, "overdue": False,
                       "last_learning_result": self.last_result,
                       "start_uncertain": bool(active and not active["eligible"])})
        if active and active["eligible"] and not active.get("paused", False) and 0 <= now - active["start"] <= MAX_RUN and result["estimated_seconds"] is not None:
            remaining = result["estimated_seconds"] - (now - active["start"])
            result["overdue"] = remaining <= 0
            # Zero is not a completion acknowledgement.
            result["remaining_seconds"] = max(0, remaining)
        return result


PROGRAMS = {program.key: program for program in (
    Program("Boden"), Program("Standard"), Program("ECO"),
    *(Program("Bereich", floor, wall) for floor in range(3) for wall in range(3) if floor or wall),
    *(Program("MultiZone", duration=duration) for duration in MULTI_DURATIONS),
)}


def program_label(key: str) -> str:
    program = PROGRAMS[key]
    if program.mode == "Bereich":
        return f"Bereich: Boden ×{program.floor}, Wand ×{program.wall}"
    if program.mode == "MultiZone":
        return f"MultiZone: {program.duration}"
    return program.mode
