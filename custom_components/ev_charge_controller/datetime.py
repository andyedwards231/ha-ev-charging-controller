"""Optional ready-by datetime, applicable only in deadline mode."""

from homeassistant.components.datetime import DateTimeEntity

from .entity import EVEntity
from .provider import timestamp


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [EVDeadline(entry.runtime_data, "deadline", "Ready by", "mdi:calendar-clock")]
    )


class EVDeadline(EVEntity, DateTimeEntity):
    @property
    def native_value(self):
        return timestamp(self.coordinator.preferences.get("deadline"))

    async def async_set_value(self, value):
        await self.coordinator.async_change(deadline=value)
