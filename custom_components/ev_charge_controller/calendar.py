"""Read-only view of planned charging intervals."""

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.util import dt as dt_util

from .entity import EVEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [EVCalendar(entry.runtime_data, "schedule", "Charging schedule", "mdi:calendar-clock")]
    )


class EVCalendar(EVEntity, CalendarEntity):
    _attr_supported_features = 0

    def _events(self):
        plan = self.coordinator.plan
        if not plan:
            return []
        return [
            CalendarEvent(
                start=slot.start,
                end=slot.end,
                summary=f"Charging at {slot.price * 100:.2f}p/kWh",
                description=f"Planned grid energy: {slot.energy_kwh:.2f}kWh; forecast {'provisional' if plan.provisional else 'covered'}",
            )
            for slot in plan.slots
        ]

    @property
    def event(self):
        now = dt_util.utcnow()
        return next((event for event in self._events() if event.end > now), None)

    async def async_get_events(self, hass, start_date, end_date):
        return [
            event for event in self._events() if event.start < end_date and event.end > start_date
        ]
