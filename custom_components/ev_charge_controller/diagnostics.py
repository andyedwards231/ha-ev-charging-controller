"""Redacted diagnostics; never include GPS coordinates or credentials."""

from homeassistant.components.diagnostics import async_redact_data


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    return async_redact_data(
        {
            "settings": dict(coordinator.preferences),
            "state": coordinator.data,
            "connections": dict(entry.data),
        },
        {
            "name",
            "location_entity",
            "home_zone",
            "rate_entity",
            "today_rates_entity",
            "tomorrow_rates_entity",
        },
    )
