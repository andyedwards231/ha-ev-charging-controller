"""Persistent charging preferences for ordinary HA dashboards."""

from homeassistant.components.number import NumberEntity, NumberMode

from .entity import EVEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            EVNumber(
                entry.runtime_data, "max_cheap_rate", "Maximum cheap rate", "p/kWh", -100, 200, 0.1
            ),
            EVNumber(entry.runtime_data, "target_percent", "Planner target", "%", 0, 100, 1),
        ]
    )


class EVNumber(EVEntity, NumberEntity):
    def __init__(self, coordinator, key, name, unit, minimum, maximum, step):
        super().__init__(
            coordinator,
            key,
            name,
            "mdi:cash" if key == "max_cheap_rate" else "mdi:battery-charging",
        )
        self._attr_native_unit_of_measurement = unit
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_native_step = step
        self._attr_mode = NumberMode.BOX

    @property
    def native_value(self):
        return self.coordinator.preferences[self.key]

    async def async_set_native_value(self, value):
        await self.coordinator.async_change(**{self.key: value})
