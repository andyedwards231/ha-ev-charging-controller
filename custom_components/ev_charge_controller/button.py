"""Replanning, manual-hold reset and learned-speed reset."""

from homeassistant.components.button import ButtonEntity

from .entity import EVEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            EVButton(entry.runtime_data, key, name, icon)
            for key, name, icon in (
                ("replan", "Replan", "mdi:calendar-refresh"),
                ("resume", "Resume after manual change", "mdi:play"),
                ("reset_learning", "Reset learned charging power", "mdi:restore"),
            )
        ]
    )


class EVButton(EVEntity, ButtonEntity):
    async def async_press(self):
        if self.key == "reset_learning":
            await self.coordinator.async_reset_learning()
        else:
            # Both replan and resume permit a fresh bounded attempt after errors.
            await self.coordinator.async_resume()
