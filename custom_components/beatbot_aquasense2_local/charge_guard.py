"""Keep robot commands blocked until an observed power cycle after charging."""

from datetime import datetime, timedelta
from typing import Any

# Observed automatic power-off takes about 1–2 hours after unplugging.
# Leave a further 15 minutes without traffic before checking reachability.
POST_CHARGE_SILENCE = timedelta(hours=2, minutes=15)
POST_CHARGE_PROBE_INTERVAL = timedelta(minutes=5)
OFF_CONFIRMATION_DELAY = timedelta(minutes=5)


class ChargeCommandGuard:
    """Silence is not offline evidence; only failed probes count as evidence."""

    def __init__(self) -> None:
        self.phase = "ready"
        self.next_poll_at: datetime | None = None
        self.offline_since: datetime | None = None

    @property
    def blocked(self) -> bool:
        return self.phase != "ready"

    def dump(self) -> dict:
        return {"phase": self.phase,
                "next_poll_at": self.next_poll_at.isoformat() if self.next_poll_at else None}

    def restore(self, saved: Any) -> None:
        if not isinstance(saved, dict):
            return
        if saved.get("phase") not in {"ready", "charging", "waiting_off", "waiting_return"}:
            return
        self.phase = saved["phase"]
        try:
            deadline = datetime.fromisoformat(saved.get("next_poll_at"))
            self.next_poll_at = deadline if deadline.tzinfo else None
        except (TypeError, ValueError):
            self.next_poll_at = None
        # HA downtime must not turn a single missed probe into a power cycle.
        self.offline_since = None

    def charging_observed(self) -> None:
        self.phase = "charging"
        self.next_poll_at = self.offline_since = None

    def switch_observed(self, state: str | None, now: datetime) -> None:
        if not self.blocked:
            return
        if state == "on":
            # Resume battery monitoring immediately, but never robot commands.
            self.charging_observed()
        elif state == "off" and self.phase == "charging":
            self.phase = "waiting_off"
            self.next_poll_at = now + POST_CHARGE_SILENCE
            self.offline_since = None
        elif state != "off":
            self.offline_since = None
        if self.phase in {"waiting_off", "waiting_return"} and self.next_poll_at is None:
            self.next_poll_at = now + POST_CHARGE_SILENCE

    def poll_due(self, now: datetime) -> bool:
        return self.next_poll_at is None or now >= self.next_poll_at

    def probe_started(self, now: datetime) -> None:
        if self.phase in {"waiting_off", "waiting_return"}:
            self.next_poll_at = now + POST_CHARGE_PROBE_INTERVAL

    def probe_failed(self, now: datetime, *, switch_off: bool, eligible: bool) -> None:
        if self.phase != "waiting_off" or not switch_off or not eligible:
            self.offline_since = None
            return
        if self.offline_since is None:
            self.offline_since = now
        elif now - self.offline_since >= OFF_CONFIRMATION_DELAY:
            self.phase = "waiting_return"
            self.offline_since = None

    def probe_succeeded(self, *, switch_off: bool, charging: bool) -> None:
        self.offline_since = None
        if self.phase == "waiting_return" and switch_off and not charging:
            self.phase = "ready"
            self.next_poll_at = None
