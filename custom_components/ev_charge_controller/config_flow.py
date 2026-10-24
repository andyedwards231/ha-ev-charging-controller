"""Config and options flows for EV Charge Controller."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import probatio as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

DOMAIN = "ev_charge_controller"

CONF_NAME = "name"
CONF_CHARGE_SWITCH = "charge_switch"
CONF_CHARGING_SENSOR = "charging_sensor"
CONF_CABLE_SENSOR = "cable_sensor"
CONF_LOCATION_ENTITY = "location_entity"
CONF_HOME_ZONE = "home_zone"
CONF_SOC_ENTITY = "soc_entity"
CONF_CAR_LIMIT_ENTITY = "car_limit_entity"
CONF_CURRENT_ENTITY = "current_entity"
CONF_PRECONDITIONING_ENTITY = "preconditioning_entity"
CONF_COMPLETION_ENTITY = "completion_entity"
CONF_COMPLETION_STATE = "completion_state"
CONF_RATE_ENTITY = "rate_entity"
CONF_TODAY_RATES_ENTITY = "today_rates_entity"
CONF_TOMORROW_RATES_ENTITY = "tomorrow_rates_entity"
CONF_TARIFF_ATTRIBUTE = "tariff_attribute"
CONF_TARIFF_MATCH = "tariff_match"
CONF_PRICE_UNIT = "price_unit"
CONF_FREE_SESSION_ENTITY = "free_session_entity"
CONF_POWER_ENTITY = "power_entity"
CONF_LEARN_POWER = "learn_power"

CONF_CAPACITY_KWH = "capacity_kwh"
CONF_VOLTAGE = "voltage"
CONF_EFFICIENCY = "efficiency"
CONF_FIXED_POWER_KW = "fixed_power_kw"
CONF_PLANNING_MARGIN = "planning_margin"
CONF_PRECONDITIONING_POLICY = "preconditioning_policy"
CONF_PRECONDITIONING_MINUTES = "preconditioning_minutes"
CONF_BOOST_HOURS = "boost_hours"
CONF_MAX_RETRIES = "max_retries"
CONF_RETRY_SECONDS = "retry_seconds"
CONF_MANUAL_HOLD_MINUTES = "manual_hold_minutes"
CONF_EXTERNAL_CHANGE_POLICY = "external_change_policy"
CONF_MAINTENANCE_MARGIN = "maintenance_margin"
CONF_STALE_MINUTES = "stale_minutes"
CONF_MAX_CHEAP_RATE = "max_cheap_rate"
CONF_TARGET_PERCENT = "target_percent"
CONF_MODE = "mode"
CONF_HARD_PRICE_CEILING = "hard_price_ceiling"
CONF_MONITORING_ONLY = "monitoring_only"
CONF_AUTOMATIC_CONTROL = "automatic_control"
CONF_DEADLINE = "deadline"

DEFAULT_OPTIONS: dict[str, Any] = {
    CONF_CAPACITY_KWH: 60.0,
    CONF_VOLTAGE: 230,
    CONF_EFFICIENCY: 0.92,
    CONF_FIXED_POWER_KW: 7.0,
    CONF_LEARN_POWER: False,
    CONF_PLANNING_MARGIN: 0.1,
    CONF_PRECONDITIONING_POLICY: "keep_existing",
    CONF_PRECONDITIONING_MINUTES: 60,
    CONF_BOOST_HOURS: 12,
    CONF_MAX_RETRIES: 3,
    CONF_RETRY_SECONDS: 60,
    CONF_MANUAL_HOLD_MINUTES: 120,
    CONF_EXTERNAL_CHANGE_POLICY: "respect",
    CONF_MAINTENANCE_MARGIN: 2,
    CONF_STALE_MINUTES: 30,
    CONF_MAX_CHEAP_RATE: 12,
    CONF_TARGET_PERCENT: 80,
    CONF_MODE: "cheap_top_up",
    CONF_HARD_PRICE_CEILING: False,
    CONF_MONITORING_ONLY: True,
    CONF_AUTOMATIC_CONTROL: True,
    CONF_DEADLINE: None,
}

_ENTITY_DOMAINS: dict[str, str] = {
    CONF_CHARGE_SWITCH: "switch",
    CONF_CHARGING_SENSOR: "binary_sensor",
    CONF_CABLE_SENSOR: "binary_sensor",
    CONF_LOCATION_ENTITY: "device_tracker",
    CONF_HOME_ZONE: "zone",
    CONF_SOC_ENTITY: "sensor",
    CONF_CAR_LIMIT_ENTITY: "number",
    CONF_CURRENT_ENTITY: "number",
    CONF_PRECONDITIONING_ENTITY: "binary_sensor",
    CONF_COMPLETION_ENTITY: "sensor",
    CONF_RATE_ENTITY: "sensor",
    CONF_TODAY_RATES_ENTITY: "event",
    CONF_TOMORROW_RATES_ENTITY: "event",
    CONF_FREE_SESSION_ENTITY: "calendar",
    CONF_POWER_ENTITY: "sensor",
}

_OPTIONAL_CONNECTIONS = {
    CONF_CAR_LIMIT_ENTITY,
    CONF_CURRENT_ENTITY,
    CONF_PRECONDITIONING_ENTITY,
    CONF_COMPLETION_ENTITY,
    CONF_TOMORROW_RATES_ENTITY,
    CONF_FREE_SESSION_ENTITY,
    CONF_POWER_ENTITY,
}

_OPTION_RANGES: dict[str, tuple[float, float]] = {
    CONF_CAPACITY_KWH: (5, 250),
    CONF_VOLTAGE: (100, 500),
    CONF_EFFICIENCY: (0.5, 1),
    CONF_FIXED_POWER_KW: (0.5, 50),
    CONF_PLANNING_MARGIN: (0, 0.5),
    CONF_MAINTENANCE_MARGIN: (0, 20),
    CONF_PRECONDITIONING_MINUTES: (1, 240),
    CONF_BOOST_HOURS: (1, 72),
    CONF_MAX_RETRIES: (0, 10),
    CONF_RETRY_SECONDS: (5, 900),
    CONF_MANUAL_HOLD_MINUTES: (1, 1440),
    CONF_STALE_MINUTES: (1, 240),
    CONF_MAX_CHEAP_RATE: (-100, 200),
    CONF_TARGET_PERCENT: (0, 100),
}


def _entity_selector(domain: str) -> selector.EntitySelector:
    """Return an entity selector constrained to its expected domain."""
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain))


def _connection_schema(fields: tuple[str, ...], values: Mapping[str, Any]) -> vol.Schema:
    """Build a connection step schema with saved values as defaults."""
    schema: dict[Any, Any] = {}
    for key in fields:
        default = values.get(key)
        marker = vol.Optional if key in _OPTIONAL_CONNECTIONS else vol.Required
        if key == CONF_NAME:
            schema[marker(key, default=default or "EV Charge Controller")] = selector.TextSelector()
        elif key == CONF_COMPLETION_STATE:
            schema[marker(key, default=default or "complete")] = selector.TextSelector()
        elif key in _ENTITY_DOMAINS:
            if key in _OPTIONAL_CONNECTIONS:
                if default:
                    schema[marker(key, default=default)] = _entity_selector(_ENTITY_DOMAINS[key])
                else:
                    schema[marker(key)] = _entity_selector(_ENTITY_DOMAINS[key])
            else:
                if default:
                    schema[marker(key, default=default)] = _entity_selector(_ENTITY_DOMAINS[key])
                else:
                    schema[marker(key)] = _entity_selector(_ENTITY_DOMAINS[key])
        elif key == CONF_TARIFF_ATTRIBUTE:
            schema[marker(key, default=default or "tariff")] = selector.TextSelector()
        elif key == CONF_TARIFF_MATCH:
            schema[marker(key, default=default or "AGILE")] = selector.TextSelector()
        elif key == CONF_PRICE_UNIT:
            schema[marker(key, default=default or "GBP/kWh")] = selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["GBP/kWh", "p/kWh"], mode=selector.SelectSelectorMode.DROPDOWN
                )
            )
    return vol.Schema(schema)


def _number(
    minimum: float,
    maximum: float,
    step: float = 1,
    unit: str | None = None,
) -> selector.NumberSelector:
    """Create a bounded numeric selector."""
    config: dict[str, Any] = {
        "min": minimum,
        "max": maximum,
        "step": step,
        "mode": selector.NumberSelectorMode.BOX,
    }
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(selector.NumberSelectorConfig(**config))


def _select(options: list[str], key: str) -> selector.SelectSelector:
    """Create a translated dropdown selector."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            mode=selector.SelectSelectorMode.DROPDOWN,
            translation_key=key,
        )
    )


def _options_schema(step_id: str, values: Mapping[str, Any]) -> vol.Schema:
    """Create one grouped options schema, with the saved settings as defaults."""
    schema: dict[Any, Any] = {}

    def required(key: str, selector_obj: Any) -> None:
        schema[vol.Required(key, default=values.get(key, DEFAULT_OPTIONS[key]))] = selector_obj

    if step_id == "planning":
        required(CONF_MODE, _select(["cheap_top_up", "deadline", "flexible"], CONF_MODE))
        required(CONF_MAX_CHEAP_RATE, _number(-100, 200, 0.1, "p/kWh"))
        required(CONF_TARGET_PERCENT, _number(0, 100, 1, "%"))
        if values.get(CONF_DEADLINE):
            schema[vol.Optional(CONF_DEADLINE, default=values[CONF_DEADLINE])] = (
                selector.DateTimeSelector()
            )
        else:
            schema[vol.Optional(CONF_DEADLINE)] = selector.DateTimeSelector()
        required(CONF_HARD_PRICE_CEILING, selector.BooleanSelector())
    elif step_id == "model":
        required(CONF_CAPACITY_KWH, _number(5, 250, 0.1, "kWh"))
        required(CONF_VOLTAGE, _number(100, 500, 1, "V"))
        required(CONF_EFFICIENCY, _number(0.5, 1, 0.01))
        required(CONF_FIXED_POWER_KW, _number(0.5, 50, 0.1, "kW"))
        required(CONF_LEARN_POWER, selector.BooleanSelector())
        required(CONF_PLANNING_MARGIN, _number(0, 0.5, 0.01))
        required(CONF_MAINTENANCE_MARGIN, _number(0, 20, 1, "%"))
    elif step_id == "preconditioning":
        required(
            CONF_PRECONDITIONING_POLICY,
            _select(["disabled", "keep_existing", "allow"], CONF_PRECONDITIONING_POLICY),
        )
        required(CONF_PRECONDITIONING_MINUTES, _number(1, 240, 1, "min"))
    elif step_id == "control":
        required(CONF_AUTOMATIC_CONTROL, selector.BooleanSelector())
        required(CONF_MONITORING_ONLY, selector.BooleanSelector())
        required(CONF_BOOST_HOURS, _number(1, 72, 1, "h"))
        required(
            CONF_EXTERNAL_CHANGE_POLICY,
            _select(["respect", "enforce"], CONF_EXTERNAL_CHANGE_POLICY),
        )
        required(CONF_MANUAL_HOLD_MINUTES, _number(1, 1440, 1, "min"))
    elif step_id == "reliability":
        required(CONF_MAX_RETRIES, _number(0, 10, 1))
        required(CONF_RETRY_SECONDS, _number(5, 900, 1, "s"))
        required(CONF_STALE_MINUTES, _number(1, 240, 1, "min"))
    else:
        raise ValueError(f"Unknown options step: {step_id}")
    return vol.Schema(schema)


def _parse_deadline(value: Any, time_zone: Any = None) -> str | None:
    """Validate and normalize the optional datetime selector value."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        if "T" not in value and " " not in value:
            raise ValueError("invalid_deadline")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as err:
            raise ValueError("invalid_deadline") from err
    else:
        raise ValueError("invalid_deadline")
    if parsed.tzinfo is None:
        if time_zone is None:
            raise ValueError("invalid_deadline")
        tz = dt_util.get_time_zone(time_zone) if isinstance(time_zone, str) else time_zone
        if tz is None:
            raise ValueError("invalid_deadline")
        first = parsed.replace(tzinfo=tz, fold=0)
        second = parsed.replace(tzinfo=tz, fold=1)
        # Local wall times in DST gaps or overlaps need an explicit offset.
        if first.utcoffset() != second.utcoffset():
            raise ValueError("invalid_deadline")
        round_trip = first.astimezone(dt_util.UTC).astimezone(tz).replace(tzinfo=None)
        if round_trip != parsed:
            raise ValueError("invalid_deadline")
        parsed = first
    return parsed.isoformat()


def _validate_option_values(step_id: str, values: Mapping[str, Any]) -> dict[str, str]:
    """Reject non-finite and out-of-range numeric option values."""
    step_keys = {
        "planning": (CONF_MAX_CHEAP_RATE, CONF_TARGET_PERCENT),
        "model": (
            CONF_CAPACITY_KWH,
            CONF_VOLTAGE,
            CONF_EFFICIENCY,
            CONF_FIXED_POWER_KW,
            CONF_PLANNING_MARGIN,
            CONF_MAINTENANCE_MARGIN,
        ),
        "preconditioning": (CONF_PRECONDITIONING_MINUTES,),
        "control": (CONF_BOOST_HOURS, CONF_MANUAL_HOLD_MINUTES),
        "reliability": (CONF_MAX_RETRIES, CONF_RETRY_SECONDS, CONF_STALE_MINUTES),
    }
    errors: dict[str, str] = {}
    for key in step_keys[step_id]:
        value = values.get(key)
        try:
            number = float(value)
        except TypeError, ValueError:
            errors[key] = "invalid_number"
            continue
        minimum, maximum = _OPTION_RANGES[key]
        if not math.isfinite(number) or not minimum <= number <= maximum:
            errors[key] = "invalid_number"
    return errors


class EVChargeControllerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure EV Charge Controller and its connected Home Assistant entities."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._reconfigure_entry: config_entries.ConfigEntry | None = None
        self._reconfigure_mode = False

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Start setup with the controller name."""
        if user_input is not None:
            errors = self._validate_connection_values(user_input, (CONF_NAME,))
            if errors:
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema(
                        {
                            vol.Required(
                                CONF_NAME, default="EV Charge Controller"
                            ): selector.TextSelector()
                        }
                    ),
                    errors=errors,
                )
            self._data.update(user_input)
            return await self.async_step_vehicle()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_NAME, default="EV Charge Controller"): selector.TextSelector()}
            ),
        )

    async def async_step_vehicle(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Select vehicle controls and telemetry."""
        return await self._async_connection_step(
            "vehicle",
            (
                CONF_CHARGE_SWITCH,
                CONF_CHARGING_SENSOR,
                CONF_CABLE_SENSOR,
                CONF_LOCATION_ENTITY,
                CONF_HOME_ZONE,
                CONF_SOC_ENTITY,
                CONF_CAR_LIMIT_ENTITY,
                CONF_CURRENT_ENTITY,
            ),
            "electricity",
            user_input,
        )

    async def async_step_electricity(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Select Octopus prices and tariff metadata."""
        return await self._async_connection_step(
            "electricity",
            (
                CONF_RATE_ENTITY,
                CONF_TODAY_RATES_ENTITY,
                CONF_TOMORROW_RATES_ENTITY,
                CONF_TARIFF_ATTRIBUTE,
                CONF_TARIFF_MATCH,
                CONF_PRICE_UNIT,
                CONF_FREE_SESSION_ENTITY,
            ),
            "model",
            user_input,
        )

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Select optional measured charging power."""
        return await self._async_connection_step(
            "model", (CONF_POWER_ENTITY,), "preconditioning", user_input
        )

    async def async_step_preconditioning(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Select optional preconditioning and completion feedback."""
        return await self._async_connection_step(
            "preconditioning",
            (CONF_PRECONDITIONING_ENTITY, CONF_COMPLETION_ENTITY, CONF_COMPLETION_STATE),
            "finish_reconfigure" if self._reconfigure_mode else "preferences",
            user_input,
        )

    async def async_step_finish_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Validate the full reconfiguration and update the existing entry."""
        assert self._reconfigure_entry is not None
        errors = await self._async_validate_entities(self._data)
        if errors:
            return self.async_show_form(
                step_id="preconditioning",
                data_schema=_connection_schema(
                    (CONF_PRECONDITIONING_ENTITY, CONF_COMPLETION_ENTITY, CONF_COMPLETION_STATE),
                    self._data,
                ),
                errors=errors,
            )
        if self._duplicate_switch(
            self._data[CONF_CHARGE_SWITCH], exclude_entry_id=self._reconfigure_entry.entry_id
        ):
            return self.async_show_form(
                step_id="preconditioning",
                data_schema=_connection_schema(
                    (CONF_PRECONDITIONING_ENTITY, CONF_COMPLETION_ENTITY, CONF_COMPLETION_STATE),
                    self._data,
                ),
                errors={"base": "charge_switch_already_configured"},
            )
        # async_update_and_abort merges data_updates into the old entry data.
        # Explicit None values are therefore needed to clear omitted optionals.
        for key in _OPTIONAL_CONNECTIONS:
            self._data.setdefault(key, None)
        return self.async_update_and_abort(
            self._reconfigure_entry,
            data_updates=self._data,
        )

    async def async_step_preferences(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Set initial charging preferences and create the config entry."""
        if user_input is not None:
            option_errors = _validate_option_values("planning", user_input)
            if option_errors:
                return self.async_show_form(
                    step_id="preferences",
                    data_schema=self._preferences_schema(DEFAULT_OPTIONS),
                    errors=option_errors,
                )
            errors = await self._async_validate_entities(self._data)
            if errors:
                return self.async_show_form(
                    step_id="preferences",
                    data_schema=self._preferences_schema(user_input),
                    errors=errors,
                )
            if self._duplicate_switch(self._data[CONF_CHARGE_SWITCH]):
                return self.async_show_form(
                    step_id="preferences",
                    data_schema=self._preferences_schema(user_input),
                    errors={"base": "charge_switch_already_configured"},
                )
            self._data.update(user_input)
            options = dict(DEFAULT_OPTIONS)
            options.update(
                {key: self._data.pop(key) for key in tuple(self._data) if key in DEFAULT_OPTIONS}
            )
            try:
                options[CONF_DEADLINE] = _parse_deadline(
                    options.get(CONF_DEADLINE), self.hass.config.time_zone
                )
            except ValueError:
                return self.async_show_form(
                    step_id="preferences",
                    data_schema=self._preferences_schema(user_input),
                    errors={CONF_DEADLINE: "invalid_deadline"},
                )
            if options[CONF_MODE] == "deadline" and options[CONF_DEADLINE] is None:
                return self.async_show_form(
                    step_id="preferences",
                    data_schema=self._preferences_schema(user_input),
                    errors={CONF_DEADLINE: "deadline_required"},
                )
            return self.async_create_entry(
                title=self._data[CONF_NAME], data=self._data, options=options
            )
        return self.async_show_form(
            step_id="preferences", data_schema=self._preferences_schema(DEFAULT_OPTIONS)
        )

    @staticmethod
    def _preferences_schema(values: Mapping[str, Any]) -> vol.Schema:
        """Build the initial preferences form."""
        return vol.Schema(
            {
                vol.Required(
                    CONF_MODE, default=values.get(CONF_MODE, DEFAULT_OPTIONS[CONF_MODE])
                ): _select(["cheap_top_up", "deadline", "flexible"], CONF_MODE),
                vol.Required(
                    CONF_MAX_CHEAP_RATE, default=values.get(CONF_MAX_CHEAP_RATE, 12)
                ): _number(-100, 200, 0.1, "p/kWh"),
                vol.Required(
                    CONF_TARGET_PERCENT, default=values.get(CONF_TARGET_PERCENT, 80)
                ): _number(0, 100, 1, "%"),
                vol.Optional(CONF_DEADLINE): selector.DateTimeSelector(),
                vol.Required(
                    CONF_HARD_PRICE_CEILING, default=values.get(CONF_HARD_PRICE_CEILING, False)
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_MONITORING_ONLY, default=values.get(CONF_MONITORING_ONLY, True)
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_AUTOMATIC_CONTROL, default=values.get(CONF_AUTOMATIC_CONTROL, True)
                ): selector.BooleanSelector(),
            }
        )

    async def _async_connection_step(
        self,
        step_id: str,
        fields: tuple[str, ...],
        next_step: str,
        user_input: dict[str, Any] | None,
    ) -> config_entries.ConfigFlowResult:
        """Collect and validate one group of entity connections."""
        if user_input is not None:
            if self._reconfigure_mode:
                for key in fields:
                    if key in _OPTIONAL_CONNECTIONS:
                        self._data.pop(key, None)
            self._data.update(
                {key: value for key, value in user_input.items() if value not in (None, "")}
            )
            errors = await self._async_validate_entities(self._data, fields)
            errors.update(self._validate_connection_values(self._data, fields))
            if errors:
                return self.async_show_form(
                    step_id=step_id,
                    data_schema=_connection_schema(fields, self._data),
                    errors=errors,
                )
            return await getattr(self, f"async_step_{next_step}")()
        return self.async_show_form(
            step_id=step_id,
            data_schema=_connection_schema(fields, self._data),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Reconfigure all required and optional entity connections."""
        self._reconfigure_entry = self._get_reconfigure_entry()
        self._data = dict(self._reconfigure_entry.data)
        self._data[CONF_NAME] = self._reconfigure_entry.title
        self._reconfigure_mode = True
        self.title_placeholders = {"name": self._reconfigure_entry.title}
        return await self.async_step_vehicle()

    async def _async_validate_entities(
        self, data: Mapping[str, Any], fields: tuple[str, ...] | None = None
    ) -> dict[str, str]:
        """Check selected entities still exist and have their expected domains."""
        registry = er.async_get(self.hass)
        errors: dict[str, str] = {}
        keys = fields if fields is not None else tuple(_ENTITY_DOMAINS)
        for key in keys:
            if key not in _ENTITY_DOMAINS:
                continue
            domain = _ENTITY_DOMAINS[key]
            entity_id = data.get(key)
            if not entity_id:
                if key not in _OPTIONAL_CONNECTIONS:
                    errors[key] = "required_entity"
                continue
            if not isinstance(entity_id, str) or "." not in entity_id:
                errors[key] = "invalid_entity"
                continue
            if entity_id.split(".", 1)[0] != domain:
                errors[key] = "wrong_entity_domain"
                continue
            if self.hass.states.get(entity_id) is None and registry.async_get(entity_id) is None:
                errors[key] = "entity_not_found"
        return errors

    def _duplicate_switch(self, entity_id: str, exclude_entry_id: str | None = None) -> bool:
        """Return whether another entry already owns this charging switch."""
        return any(
            entry.entry_id != exclude_entry_id and entry.data.get(CONF_CHARGE_SWITCH) == entity_id
            for entry in self._async_current_entries()
        )

    @staticmethod
    def _validate_connection_values(
        data: Mapping[str, Any], fields: tuple[str, ...]
    ) -> dict[str, str]:
        """Validate free-text values and the supported rate units."""
        errors: dict[str, str] = {}
        for key in (CONF_NAME, CONF_TARIFF_ATTRIBUTE, CONF_TARIFF_MATCH, CONF_COMPLETION_STATE):
            if key in fields and not str(data.get(key, "")).strip():
                errors[key] = "required_text"
        if CONF_PRICE_UNIT in fields and data.get(CONF_PRICE_UNIT) not in ("GBP/kWh", "p/kWh"):
            errors[CONF_PRICE_UNIT] = "invalid_price_unit"
        return errors

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> EVChargeControllerOptionsFlow:
        """Create the grouped options editor."""
        return EVChargeControllerOptionsFlow()


class EVChargeControllerOptionsFlow(config_entries.OptionsFlow):
    """Edit controller preferences and advanced behavior in groups."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Open the first options group."""
        return await self.async_step_planning(user_input)

    async def async_step_planning(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit charging mode, target and price policy."""
        return await self._async_options_step("planning", "model", user_input)

    async def async_step_model(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit the charging model assumptions."""
        return await self._async_options_step("model", "preconditioning", user_input)

    async def async_step_preconditioning(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit preconditioning exceptions."""
        return await self._async_options_step("preconditioning", "control", user_input)

    async def async_step_control(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit ownership, monitoring and boost settings."""
        return await self._async_options_step("control", "reliability", user_input)

    async def async_step_reliability(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Edit retries and stale-input limits."""
        return await self._async_options_step("reliability", None, user_input)

    async def _async_options_step(
        self,
        step_id: str,
        next_step: str | None,
        user_input: dict[str, Any] | None,
    ) -> config_entries.ConfigFlowResult:
        """Save one group and continue, preserving all other option values."""
        if user_input is not None:
            options = getattr(self, "_options", None)
            if options is None:
                options = self._current_options()
            errors = _validate_option_values(step_id, user_input)
            if errors:
                return self.async_show_form(
                    step_id=step_id,
                    data_schema=_options_schema(step_id, options),
                    errors=errors,
                )
            options.update(user_input)
            if step_id == "planning":
                try:
                    options[CONF_DEADLINE] = _parse_deadline(
                        user_input.get(CONF_DEADLINE), self.hass.config.time_zone
                    )
                except ValueError:
                    return self.async_show_form(
                        step_id=step_id,
                        data_schema=_options_schema(step_id, options),
                        errors={CONF_DEADLINE: "invalid_deadline"},
                    )
                if options[CONF_MODE] == "deadline" and options[CONF_DEADLINE] is None:
                    return self.async_show_form(
                        step_id=step_id,
                        data_schema=_options_schema(step_id, options),
                        errors={CONF_DEADLINE: "deadline_required"},
                    )
            self._options = options
            if next_step is None:
                return self.async_create_entry(title="", data=options)
            return await getattr(self, f"async_step_{next_step}")()
        options = getattr(self, "_options", None)
        if options is None:
            options = self._current_options()
            self._options = options
        return self.async_show_form(
            step_id=step_id,
            data_schema=_options_schema(step_id, options),
        )

    def _current_options(self) -> dict[str, Any]:
        """Combine saved settings with live preferences restored from storage."""
        options = {**DEFAULT_OPTIONS, **self.config_entry.options}
        runtime_data = getattr(self.config_entry, "runtime_data", None)
        preferences = getattr(runtime_data, "preferences", None)
        if isinstance(preferences, Mapping):
            options.update(
                {key: value for key, value in preferences.items() if key in DEFAULT_OPTIONS}
            )
        return options
