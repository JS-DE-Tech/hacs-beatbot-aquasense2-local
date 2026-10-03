"""Cleaning preselection and the plug cutoff target."""

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MODE_VALUES
from .entity import BeatbotEntity
from .manager import BeatbotManager


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    manager: BeatbotManager = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BeatbotCleaningMode(manager), BeatbotChargeTarget(manager),
                        BeatbotProgramOption(manager, "floor", "Bereich Boden", ["0", "1", "2"]),
                        BeatbotProgramOption(manager, "wall", "Bereich Wand und Wasserlinie", ["0", "1", "2"]),
                        BeatbotProgramOption(manager, "duration", "MultiZone Dauer", ["Max", "2h", "1h"])])


class BeatbotCleaningMode(BeatbotEntity, SelectEntity):
    _attr_options = list(MODE_VALUES)

    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "mode", "Reinigungsmodus")

    @property
    def current_option(self) -> str | None:
        return self.manager.selected_mode

    @property
    def extra_state_attributes(self) -> dict:
        return {"pending_until_idle": self.manager.mode_pending,
                "last_confirmed_mode": self.manager.last_mode}

    async def async_select_option(self, option: str) -> None:
        await self.manager.async_select_mode(option)


class BeatbotChargeTarget(BeatbotEntity, SelectEntity):
    _attr_options = ["80 %", "100 %"]

    def __init__(self, manager: BeatbotManager) -> None:
        super().__init__(manager, "charge_target", "Ladeziel")

    @property
    def current_option(self) -> str:
        return f"{self.manager.charge_target} %"

    async def async_select_option(self, option: str) -> None:
        await self.manager.async_select_charge_target(int(option.split()[0]))


class BeatbotProgramOption(BeatbotEntity, SelectEntity):
    def __init__(self, manager: BeatbotManager, field: str, name: str, options: list[str]) -> None:
        super().__init__(manager, f"program_{field}", name)
        self.field = field
        self._attr_options = options

    @property
    def current_option(self) -> str:
        field = {"floor": "floor_count", "wall": "wall_count", "duration": "multi_duration"}[self.field]
        return str(getattr(self.manager, field))

    async def async_select_option(self, option: str) -> None:
        await self.manager.async_select_program_option(self.field, option)
