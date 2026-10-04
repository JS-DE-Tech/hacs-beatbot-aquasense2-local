"""Last known values remain visible while the robot is underwater or asleep."""

from datetime import datetime, timezone
from math import ceil

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, VERIFIED_STATUS_VALUES
from .entity import BeatbotEntity
from .manager import BeatbotManager


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    manager: BeatbotManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        BeatbotBattery(manager),
        BeatbotLastMode(manager),
        BeatbotCleaningState(manager),
        BeatbotStatus(manager),
        BeatbotParkState(manager),
        BeatbotChargeState(manager),
        BeatbotRuntime(manager, False),
        BeatbotRuntime(manager, True),
        BeatbotCooldown(manager),
        BeatbotChargeCountdown(manager),
        BeatbotBatteryConsumption(manager),
    ])


class BeatbotBattery(BeatbotEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "battery", "Akkustand")

    @property
    def native_value(self) -> int | None:
        return self.manager.battery

    @property
    def available(self) -> bool:
        return self.manager.battery is not None

    @property
    def extra_state_attributes(self) -> dict:
        return {"stale": self.manager.battery_stale,
                "battery_seen": self.manager.battery_seen.isoformat() if self.manager.battery_seen else None,
                "last_seen": self.manager.last_seen.isoformat() if self.manager.last_seen else None}


class BeatbotLastMode(BeatbotEntity, SensorEntity):
    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "last_mode", "Letzter Reinigungsmodus")

    @property
    def native_value(self) -> str | None:
        return self.manager.last_mode

    @property
    def available(self) -> bool:
        return self.manager.last_mode is not None

    @property
    def extra_state_attributes(self) -> dict:
        return {"stale": not self.manager.online, "mode_change_pending": self.manager.mode_pending}


class BeatbotStatus(BeatbotEntity, SensorEntity):
    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "status", "Roboterstatus")

    @property
    def native_value(self) -> str | None:
        return self.manager.robot_status

    @property
    def available(self) -> bool:
        return self.manager.robot_status is not None

    @property
    def extra_state_attributes(self) -> dict:
        return {"stale": not self.manager.online,
                "last_seen": self.manager.last_seen.isoformat() if self.manager.last_seen else None}


class BeatbotCleaningState(BeatbotEntity, SensorEntity):
    """Human-readable feedback from DP165, including cleaning completion."""

    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "cleaning_state", "Reinigungsstatus")

    @property
    def native_value(self) -> str | None:
        return "Ausgeschaltet" if self.manager.inferred_off else self.manager.cleaning_state

    @property
    def available(self) -> bool:
        return self.manager.cleaning_state is not None

    @property
    def extra_state_attributes(self) -> dict:
        return {"stale": not self.manager.online,
                "inferred_off": self.manager.inferred_off,
                "inference": "offline_idle_5_minutes" if self.manager.inferred_off else None,
                "last_reported_status": self.manager.robot_status,
                "status_mapping_verified": self.manager.robot_status in VERIFIED_STATUS_VALUES,
                "diving_started_at": self.manager.diving_started_at.isoformat() if self.manager.diving_started_at else None,
                "diving_display_elapsed": self.manager.diving_started_at is not None and self.manager.cleaning_state == "Reinigt",
                "last_seen": self.manager.last_seen.isoformat() if self.manager.last_seen else None}


class BeatbotParkState(BeatbotEntity, SensorEntity):
    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "park_state", "Parkauftrag")

    @property
    def native_value(self) -> str:
        return self.manager.park_state

    @property
    def extra_state_attributes(self) -> dict:
        return {"pending": self.manager.park_pending,
                "requested_at": self.manager.park_requested_at.isoformat() if self.manager.park_requested_at else None}


class BeatbotChargeState(BeatbotEntity, SensorEntity):
    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "charge_state", "Ladeüberwachung")

    @property
    def native_value(self) -> str:
        return self.manager.charge_state

    @property
    def extra_state_attributes(self) -> dict:
        return {"switch_entity": self.manager.charger_switch,
                "target_percent": self.manager.charge_target}


class BeatbotRuntime(BeatbotEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = "min"

    def __init__(self, manager: BeatbotManager, remaining: bool) -> None:
        super().__init__(manager, "remaining_runtime" if remaining else "estimated_runtime",
                         "Geschätzte Restzeit" if remaining else "Geschätzte Programmdauer")
        self.remaining = remaining
        # HA duration device class excludes timers updated solely by passing time.
        if remaining:
            self._attr_device_class = None

    @property
    def extra_state_attributes(self) -> dict:
        if self.remaining:
            result = self.manager.runtime.remaining(datetime.now(timezone.utc).timestamp())
        else:
            program = self.manager.selected_program
            result = self.manager.runtime.estimate(program.key if program else None)
        return {**result, "estimated": True, "robot_online": self.manager.online,
                "method": "manual" if result.get("manual_seconds") is not None else "median_last_10_completed_runs",
                "minimum_samples": 0 if result.get("manual_seconds") is not None else 2}

    @property
    def native_value(self) -> int | None:
        attributes = self.extra_state_attributes
        seconds = attributes["remaining_seconds" if self.remaining else "estimated_seconds"]
        return ceil(seconds / 60) if seconds is not None else None


class BeatbotCooldown(BeatbotEntity, SensorEntity):
    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "cooldown", "Ladeplanung")

    @property
    def native_value(self) -> str:
        return self.manager.cooldown.state if self.manager.charger_switch else "not_configured"

    @property
    def extra_state_attributes(self) -> dict:
        deadline = self.manager.cooldown.deadline
        remaining = (max(0, ceil(deadline - datetime.now(timezone.utc).timestamp()))
                     if deadline is not None and self.manager.cooldown.state == "cooling" else None)
        return {"scheduled_start": datetime.fromtimestamp(deadline, timezone.utc).isoformat() if deadline else None,
                "cooldown_hours": 2, "battery_below_percent": self.manager.charge_target,
                "remaining_seconds": remaining, "completion_required": True,
                "uses_last_known_battery": True, "switch_entity": self.manager.charger_switch}


class BeatbotChargeCountdown(BeatbotEntity, SensorEntity):
    _attr_icon = "mdi:timer-sand"

    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "charge_countdown", "Zeit bis Laden")

    @property
    def native_value(self) -> str | None:
        deadline = self.manager.cooldown.deadline
        if not self.manager.charger_switch or self.manager.cooldown.state != "cooling" or deadline is None:
            return None
        remaining = max(0, ceil(deadline - datetime.now(timezone.utc).timestamp()))
        return f"{remaining // 3600:02}:{remaining // 60 % 60:02}:{remaining % 60:02}"


class BeatbotBatteryConsumption(BeatbotEntity, SensorEntity):
    """Consumption in battery percentage points, learned per selected program."""

    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:battery-minus-outline"

    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "estimated_battery_consumption", "Geschätzter Akkuverbrauch")

    @property
    def extra_state_attributes(self) -> dict:
        program = self.manager.selected_program
        return {**self.manager.runtime.battery_estimate(program.key if program else None,
                                                       self.manager.battery, stale=self.manager.battery_stale),
                "estimated": True, "minimum_samples": 2,
                "method": "median_consumption_max_plus_reserve", "unit": "percentage_points"}

    @property
    def native_value(self) -> float | None:
        return self.extra_state_attributes["estimated_consumption_percent"]
