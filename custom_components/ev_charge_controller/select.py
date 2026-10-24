"""Charging strategy selection."""

from homeassistant.components.select import SelectEntity

from .const import MODES
from .entity import EVEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([EVMode(entry.runtime_data, "mode", "Charging mode", "mdi:calendar-clock")])


class EVMode(EVEntity, SelectEntity):
    _attr_options = list(MODES)
    _attr_translation_key = "mode"

    @property
    def current_option(self):
        return self.coordinator.preferences["mode"]

    async def async_select_option(self, option):
        await self.coordinator.async_change(mode=option)
