"""Safety decisions kept independent of HA and network I/O."""

from datetime import datetime


def charge_cutoff_due(
    switch_is_on: bool,
    fresh_battery: int | None,
    target: int,
    charge_started_at: datetime | None,
    sample_at: datetime,
) -> bool:
    """A stored battery value must never cut power after a later plug-on event."""
    return (
        switch_is_on
        and charge_started_at is not None
        and sample_at >= charge_started_at
        and type(fresh_battery) is int
        and 0 <= fresh_battery <= 100
        and fresh_battery >= target
    )
