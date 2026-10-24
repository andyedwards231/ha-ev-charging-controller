"""Automatic control, monitoring and boost switches."""

from homeassistant.components.switch import SwitchEntity

from .entity import EVEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            EVSwitch(entry.runtime_data, key, name, icon)
            for key, name, icon in (
                ("automatic_control", "Automatic control", "mdi:ev-station"),
                ("monitoring_only", "Monitoring only", "mdi:eye-outline"),
                ("boost", "Boost", "mdi:lightning-bolt"),
                ("hard_price_ceiling", "Hard deadline price ceiling", "mdi:cash-lock"),
            )
        ]
    )


class EVSwitch(EVEntity, SwitchEntity):
    @property
    def is_on(self):
        if self.key == "boost":
            return self.coordinator.boost_until is not None
        return bool(self.coordinator.preferences[self.key])

    async def _set(self, value):
        if self.key == "boost":
            await self.coordinator.async_boost(value)
        else:
            await self.coordinator.async_change(**{self.key: value})

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)
