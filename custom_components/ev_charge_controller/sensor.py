"""Explain charging decisions and expose plan estimates."""

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.entity import EntityCategory

from .entity import EVEntity

SENSORS = (
    ("status", "Status", None, None, "mdi:information-outline"),
    ("next_start", "Next planned start", None, SensorDeviceClass.TIMESTAMP, "mdi:clock-start"),
    (
        "estimated_completion",
        "Estimated completion",
        None,
        SensorDeviceClass.TIMESTAMP,
        "mdi:clock-check",
    ),
    ("estimated_cost", "Estimated remaining cost", "GBP", SensorDeviceClass.MONETARY, "mdi:cash"),
    ("required_energy", "Required battery energy", "kWh", SensorDeviceClass.ENERGY, "mdi:battery"),
    ("shortfall", "Planned energy shortfall", "kWh", SensorDeviceClass.ENERGY, "mdi:battery-alert"),
    ("planned_maximum_pence", "Planned maximum rate", "p/kWh", None, "mdi:cash-clock"),
    ("power_kw", "Estimated charging power", "kW", SensorDeviceClass.POWER, "mdi:flash"),
    ("learned_power_kw", "Learned charging power", "kW", SensorDeviceClass.POWER, "mdi:flash"),
)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [EVSensor(entry.runtime_data, *description) for description in SENSORS]
        + [EVPlan(entry.runtime_data, "plan", "Charging plan", "mdi:calendar-multiple")]
    )


class EVSensor(EVEntity, SensorEntity):
    def __init__(self, coordinator, key, name, unit, device_class, icon):
        super().__init__(coordinator, key, name, icon)
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        if key in ("power_kw", "learned_power_kw"):
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        return self.coordinator.data.get(self.key)

    @property
    def extra_state_attributes(self):
        if self.key == "status":
            return {
                key: value
                for key, value in self.coordinator.data.items()
                if key
                not in (
                    "schedule",
                    "rates",
                    "forecast_schedule",
                    "forecast_series",
                    "status",
                )
                and (not key.startswith("forecast_") or key == "forecast_coverage_end")
            }
        return None


class EVPlan(EVEntity, SensorEntity):
    @property
    def native_value(self):
        return len(self.coordinator.data.get("schedule", []))

    @property
    def extra_state_attributes(self):
        return {
            "schedule": self.coordinator.data.get("schedule", []),
            "rates": self.coordinator.data.get("rates", []),
            "forecast_schedule": self.coordinator.data.get("forecast_schedule", []),
            "forecast_series": self.coordinator.data.get("forecast_series", []),
            "forecast_soc": self.coordinator.data.get("forecast_soc"),
            "forecast_cost": self.coordinator.data.get("forecast_cost"),
            "forecast_grid_energy_kwh": self.coordinator.data.get("forecast_grid_energy_kwh"),
            "forecast_shortfall_kwh": self.coordinator.data.get("forecast_shortfall_kwh"),
            "forecast_completion": self.coordinator.data.get("forecast_completion"),
            "forecast_available": self.coordinator.data.get("forecast_available"),
            "forecast_target": self.coordinator.data.get("forecast_target"),
            "forecast_basis": self.coordinator.data.get("forecast_basis"),
            "rates_warning": self.coordinator.data.get("rates_warning"),
            "rates_complete": self.coordinator.data.get("rates_complete"),
            "provisional": self.coordinator.data.get("provisional"),
            "forecast_coverage_end": self.coordinator.data.get("forecast_coverage_end"),
            "forecast_horizon_end": self.coordinator.data.get("forecast_horizon_end"),
        }
