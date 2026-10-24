"""UI-configured EV charging using existing Home Assistant integrations."""

from __future__ import annotations

import probatio as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, MODES, PLATFORMS
from .coordinator import EVCoordinator
from .frontend import async_setup_frontend

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register actions once, independent of loaded entry count."""
    await async_setup_frontend(hass)

    async def set_request(call: ServiceCall):
        entry = hass.config_entries.async_get_entry(call.data["config_entry_id"])
        if (
            entry is None
            or entry.domain != DOMAIN
            or not isinstance(entry.runtime_data, EVCoordinator)
        ):
            raise HomeAssistantError("The EV Charge Controller entry is not loaded")
        coordinator = entry.runtime_data
        updates = {key: value for key, value in call.data.items() if key != "config_entry_id"}
        if updates.get("mode", coordinator.preferences["mode"]) == "deadline":
            deadline = updates.get("deadline", coordinator.preferences.get("deadline"))
            if not deadline:
                raise HomeAssistantError("Deadline mode requires a ready-by date and time")
        try:
            await coordinator.async_change(**updates)
        except ValueError as exc:
            raise HomeAssistantError(str(exc)) from exc

    schema = vol.Schema(
        {
            vol.Required("config_entry_id"): cv.string,
            vol.Optional("mode"): vol.In(MODES),
            vol.Optional("target_percent"): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
            vol.Optional("deadline"): cv.datetime,
            vol.Optional("max_cheap_rate"): vol.All(
                vol.Coerce(float), vol.Range(min=-100, max=200)
            ),
            vol.Optional("hard_price_ceiling"): cv.boolean,
        }
    )
    if not hass.services.has_service(DOMAIN, "set_request"):
        hass.services.async_register(DOMAIN, "set_request", set_request, schema=schema)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one controller; entity selection is validated by the config flow."""
    coordinator = EVCoordinator(hass, entry)
    entry.runtime_data = coordinator
    try:
        await coordinator.async_initialize()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await coordinator.async_shutdown()
        raise
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry):
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Keep a working coordinator if Home Assistant cannot unload its platforms.
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.async_shutdown()
    return True
