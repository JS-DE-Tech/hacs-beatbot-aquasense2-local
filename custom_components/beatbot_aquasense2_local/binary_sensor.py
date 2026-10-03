"""Current LAN reachability."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import BeatbotEntity
from .manager import BeatbotManager


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    manager: BeatbotManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BeatbotOnline(manager), BeatbotBatteryInsufficient(manager),
                        BeatbotFilterBasketMissing(manager), BeatbotFilterCleaningRequired(manager)])


class BeatbotFilterCleaningRequired(BeatbotEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:filter-check-outline"

    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "filter_cleaning_required", "Filterkorb reinigen")

    @property
    def is_on(self) -> bool:
        return self.manager.filter_cleaning_required


class BeatbotOnline(BeatbotEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "online", "Lokal erreichbar")

    @property
    def is_on(self) -> bool:
        return self.manager.online


class BeatbotBatteryInsufficient(BeatbotEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:battery-alert-variant-outline"

    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "battery_insufficient", "Akku für Programm zu niedrig")

    @property
    def extra_state_attributes(self) -> dict:
        program = self.manager.selected_program
        return self.manager.runtime.battery_estimate(program.key if program else None,
                                                    self.manager.battery, stale=self.manager.battery_stale)

    @property
    def is_on(self) -> bool | None:
        return self.extra_state_attributes["insufficient"]

    @property
    def available(self) -> bool:
        return self.is_on is not None


class BeatbotFilterBasketMissing(BeatbotEntity, BinarySensorEntity):
    """Fresh local basket warning, not a promise based on an old clear state."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:filter-remove"

    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "filter_basket_missing", "Filterkorb fehlt")

    @property
    def is_on(self) -> bool | None:
        return None if self.manager.fault_stale else self.manager.filter_basket_missing

    @property
    def available(self) -> bool:
        return self.is_on is not None

    @property
    def extra_state_attributes(self) -> dict:
        return {"source": "local_DP107", "raw_fault_code": self.manager.fault_code,
                "last_known_filter_basket_missing": self.manager.filter_basket_missing,
                "stale": self.manager.fault_stale,
                "last_seen": self.manager.fault_seen.isoformat() if self.manager.fault_seen else None,
                "supported_codes": {"0": "clear", "2": "filter_basket_missing"}}
