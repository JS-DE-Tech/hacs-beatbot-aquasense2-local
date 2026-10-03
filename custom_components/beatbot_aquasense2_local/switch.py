"""A robot-scoped proxy for its configured charging plug."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import BeatbotEntity
from .manager import BeatbotManager


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    manager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BeatbotChargingSwitch(manager), BeatbotCompletionSwitch(manager)])


class BeatbotCompletionSwitch(BeatbotEntity, SwitchEntity):
    _attr_icon = "mdi:bell-check-outline"

    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "completion_notifications", "Fertigmeldung")

    @property
    def is_on(self) -> bool:
        return self.manager.completion_notifications

    async def async_turn_on(self, **kwargs) -> None:
        await self.manager.async_set_completion_notifications(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.manager.async_set_completion_notifications(False)


class BeatbotChargingSwitch(BeatbotEntity, SwitchEntity):
    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "charging_switch", "Ladestation")

    @property
    def available(self) -> bool:
        entity_id = self.manager.charger_switch
        state = self.hass.states.get(entity_id) if entity_id else None
        return state is not None and state.state in {"on", "off"}

    @property
    def is_on(self) -> bool:
        return bool(self.manager.charger_switch and self.hass.states.is_state(self.manager.charger_switch, "on"))

    async def async_turn_on(self, **kwargs) -> None:
        await self.manager.async_set_charging(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.manager.async_set_charging(False)
