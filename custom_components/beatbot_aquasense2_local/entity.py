"""Shared AquaSense 2 device identity and state updates."""

from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN
from .manager import BeatbotManager


class BeatbotEntity(Entity):
    """Base class for entities belonging to one local robot."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, manager: BeatbotManager, key: str, name: str) -> None:
        self.manager = manager
        self._attr_unique_id = f"{manager.client.device_id}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manager.client.device_id)},
            manufacturer="Beatbot",
            model="AquaSense 2",
            name=manager.entry.title,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.manager.subscribe(self.async_write_ha_state))
