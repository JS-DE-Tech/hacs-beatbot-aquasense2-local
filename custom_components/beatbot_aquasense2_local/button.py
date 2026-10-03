"""Queue a pool parking request."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import BeatbotEntity
from .manager import BeatbotManager


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    manager: BeatbotManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BeatbotParkButton(manager)])


class BeatbotParkButton(BeatbotEntity, ButtonEntity):
    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "park", "Parken")

    @property
    def available(self) -> bool:
        return self.manager.can_park

    async def async_press(self) -> None:
        await self.manager.async_request_park()

