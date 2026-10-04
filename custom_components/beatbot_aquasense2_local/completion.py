"""Completion events for charging/reminders, independent of valid training runs."""

from math import isfinite

from .runtime import PROGRAMS

SURFACE_WINDOW = 10 * 60


class CompletionTracker:
    def __init__(self) -> None:
        self.active = False
        self.finished = False
        self.emerged_at: float | None = None
        self.program_key: str | None = None

    def dump(self) -> dict:
        return {"active": self.active, "finished": self.finished,
                "emerged_at": self.emerged_at, "program_key": self.program_key}

    def restore(self, saved) -> None:
        if not isinstance(saved, dict):
            return
        self.active = saved.get("active") is True
        self.finished = saved.get("finished") is True
        value = saved.get("emerged_at")
        self.emerged_at = value if type(value) in (float, int) and isfinite(value) else None
        key = saved.get("program_key")
        self.program_key = key if isinstance(key, str) and key in PROGRAMS else None

    def observe(self, state: str | None, position, now: float,
                program_key: str | None = None) -> bool:
        # Freeze the identity when this run is first observed. Program changes
        # and a newly selected preset must not rename the finished run.
        if not self.active and (state in {"cleaning", "diving", "clean_wait"}
                               or not self.finished and state == "emerge"):
            self.program_key = program_key if isinstance(program_key, str) and program_key in PROGRAMS else None
        if state in {"cleaning", "diving", "clean_wait"}:
            self.active, self.finished, self.emerged_at = True, False, None
        elif state == "emerge" and not self.finished:
            self.active, self.emerged_at = True, now
        elif (state == "clean_done" and self.active and not self.finished) or (
            state == "auto_dock" and self.active and not self.finished
            and self.emerged_at is not None and 0 <= now - self.emerged_at <= SURFACE_WINDOW
            and not (type(position) is int and position == 0)
        ):
            self.active, self.finished, self.emerged_at = False, True, None
            return True
        elif (state == "standby" and type(position) is int and position == 0
              or state in {"sleep", "charging", "charge_done", "goto_charge"}):
            self.active, self.finished, self.emerged_at = False, False, None
            self.program_key = None
        return False
