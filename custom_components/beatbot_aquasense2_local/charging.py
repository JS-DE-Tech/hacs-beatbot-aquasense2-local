"""Persistent two-hour plan after an acknowledged cleaning completion."""

from math import isfinite
from typing import Any

COOLDOWN_SECONDS = 2 * 3600


class CooldownCharging:
    def __init__(self) -> None:
        self.state = "idle"
        self.deadline: float | None = None
        self.seen_run = False
        self.completed_at: float | None = None

    def dump(self) -> dict:
        return {"policy_version": 2, "state": self.state, "deadline": self.deadline,
                "seen_run": self.seen_run, "completed_at": self.completed_at}

    def restore(self, saved: Any) -> None:
        # Old sleep-based plans do not contain the actual completion time.
        if not isinstance(saved, dict) or saved.get("policy_version") != 2:
            return
        states = {"idle", "waiting_for_battery", "cooling", "charging", "manual", "complete", "starting", "start_uncertain"}
        self.state = saved.get("state") if saved.get("state") in states else "idle"
        for field in ("deadline", "completed_at"):
            value = saved.get(field)
            setattr(self, field, value if type(value) in (int, float) and isfinite(value) else None)
        if self.state == "cooling" and self.deadline is None:
            self.state = "idle"
        if self.state == "starting":
            self.state = "start_uncertain"  # Never repeat an ambiguous service call after restart.
        self.seen_run = saved.get("seen_run") is True

    def manual(self) -> None:
        self.state, self.deadline, self.seen_run = "manual", None, False
        self.completed_at = None

    def observe(self, status: str | None, battery: int | None, now: float,
                completion: bool = False, target: int = 100) -> None:
        if completion:
            self.seen_run = False
            self.state, self.deadline, self.completed_at = "waiting_for_battery", None, now
        elif status in {"cleaning", "diving", "clean_wait"}:
            self.seen_run = True
            if self.state != "charging":
                self.state, self.deadline, self.completed_at = "idle", None, None
        if self.state == "waiting_for_battery" and type(battery) is int and 0 <= battery <= 100:
            if battery < target:
                self.state, self.deadline = "cooling", now + COOLDOWN_SECONDS
            else:
                self.state, self.deadline = "idle", None

    def due(self, now: float) -> bool:
        return self.state == "cooling" and self.deadline is not None and now >= self.deadline
