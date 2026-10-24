"""Actionable problems and desired charging state."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import EVEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            EVProblem(entry.runtime_data, "problem", "Needs attention", "mdi:alert-circle-outline"),
            EVDesired(
                entry.runtime_data, "desired_charging", "Charging permitted", "mdi:ev-station"
            ),
        ]
    )


class EVProblem(EVEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self):
        return self.coordinator.data.get("problem", False)

    @property
    def extra_state_attributes(self):
        return {"reason": self.coordinator.data.get("reason")}


class EVDesired(EVEntity, BinarySensorEntity):
    @property
    def is_on(self):
        return self.coordinator.data.get("desired_charging")
