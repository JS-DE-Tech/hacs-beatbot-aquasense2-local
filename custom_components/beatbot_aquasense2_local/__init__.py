"""Home Assistant setup for the Beatbot AquaSense 2 local integration."""

from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .manager import BeatbotManager
from .history_view import BeatbotHistoryView

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SELECT, Platform.BUTTON, Platform.SWITCH]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Serve the bundled product picture locally, without a cloud dependency."""
    hass.http.register_view(BeatbotHistoryView(hass))
    await hass.http.async_register_static_paths([
        StaticPathConfig(
            f"/{DOMAIN}/robot.png",
            str(Path(__file__).parent / "assets" / "robot.png"),
            True,
        ),
    ])
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    manager = BeatbotManager(hass, entry)
    await manager.async_initialize()
    hass.data[DOMAIN][entry.entry_id] = manager
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    manager.start()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    manager: BeatbotManager | None = hass.data[DOMAIN].get(entry.entry_id)
    if manager is None:
        return True
    await manager.async_stop()
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
