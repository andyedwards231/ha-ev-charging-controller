"""Config-flow coverage using the installed Home Assistant runtime APIs."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom_components.ev_charge_controller import config_flow as cf

CONNECTIONS = {
    cf.CONF_CHARGE_SWITCH: "switch.test_ev_charge",
    cf.CONF_CHARGING_SENSOR: "binary_sensor.test_ev_charging",
    cf.CONF_CABLE_SENSOR: "binary_sensor.test_ev_charge_cable",
    cf.CONF_LOCATION_ENTITY: "device_tracker.test_ev_location",
    cf.CONF_HOME_ZONE: "zone.home",
    cf.CONF_SOC_ENTITY: "sensor.test_ev_battery_level",
    cf.CONF_CAR_LIMIT_ENTITY: "number.test_ev_charge_limit",
    cf.CONF_CURRENT_ENTITY: "number.test_ev_charge_current",
    cf.CONF_RATE_ENTITY: "sensor.octopus_current_rate",
    cf.CONF_TODAY_RATES_ENTITY: "event.octopus_current_day_rates",
    cf.CONF_TOMORROW_RATES_ENTITY: "event.octopus_next_day_rates",
    cf.CONF_TARIFF_ATTRIBUTE: "tariff",
    cf.CONF_TARIFF_MATCH: "AGILE",
    cf.CONF_PRICE_UNIT: "GBP/kWh",
    cf.CONF_FREE_SESSION_ENTITY: "calendar.free_electricity",
    cf.CONF_POWER_ENTITY: "sensor.wall_connector_power",
    cf.CONF_PRECONDITIONING_ENTITY: "binary_sensor.test_ev_preconditioning_enabled",
    cf.CONF_COMPLETION_ENTITY: "sensor.test_ev_charge_completion",
    cf.CONF_COMPLETION_STATE: "complete",
}

OPTIONAL_KEYS = {
    cf.CONF_CAR_LIMIT_ENTITY,
    cf.CONF_CURRENT_ENTITY,
    cf.CONF_TOMORROW_RATES_ENTITY,
    cf.CONF_FREE_SESSION_ENTITY,
    cf.CONF_POWER_ENTITY,
    cf.CONF_PRECONDITIONING_ENTITY,
    cf.CONF_COMPLETION_ENTITY,
}


class FakeFlowHarness:
    """Minimal Home Assistant state and registry data for direct flow steps."""

    def __init__(self, entity_ids: set[str]):
        self.config = SimpleNamespace(time_zone="Europe/London")
        self.states = SimpleNamespace(
            get=lambda entity_id: object() if entity_id in entity_ids else None
        )


def _flow(monkeypatch: pytest.MonkeyPatch, entries: list[object] | None = None):
    """Create a flow with real schemas and isolated Home Assistant collaborators."""
    flow = cf.EVChargeControllerConfigFlow()
    flow.hass = FakeFlowHarness(set(CONNECTIONS.values()))
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}
    flow._async_current_entries = lambda: entries or []
    registry = SimpleNamespace(async_get=lambda entity_id: None)
    monkeypatch.setattr(cf.er, "async_get", lambda hass: registry)
    return flow


def _preferences(**overrides):
    result = {
        cf.CONF_MODE: "cheap_top_up",
        cf.CONF_MAX_CHEAP_RATE: 12,
        cf.CONF_TARGET_PERCENT: 80,
        cf.CONF_HARD_PRICE_CEILING: False,
        cf.CONF_MONITORING_ONLY: True,
        cf.CONF_AUTOMATIC_CONTROL: True,
    }
    result.update(overrides)
    return result


@pytest.mark.asyncio
async def test_setup_walks_connection_steps_and_stores_preferences_as_options(monkeypatch):
    flow = _flow(monkeypatch)

    result = await flow.async_step_user({cf.CONF_NAME: "Test EV"})
    assert result["step_id"] == "vehicle"
    result = await flow.async_step_vehicle(
        {
            key: value
            for key, value in CONNECTIONS.items()
            if key
            in {
                cf.CONF_CHARGE_SWITCH,
                cf.CONF_CHARGING_SENSOR,
                cf.CONF_CABLE_SENSOR,
                cf.CONF_LOCATION_ENTITY,
                cf.CONF_HOME_ZONE,
                cf.CONF_SOC_ENTITY,
                cf.CONF_CAR_LIMIT_ENTITY,
                cf.CONF_CURRENT_ENTITY,
            }
        }
    )
    assert result["step_id"] == "electricity"
    result = await flow.async_step_electricity(
        {
            key: value
            for key, value in CONNECTIONS.items()
            if key
            in {
                cf.CONF_RATE_ENTITY,
                cf.CONF_TODAY_RATES_ENTITY,
                cf.CONF_TOMORROW_RATES_ENTITY,
                cf.CONF_TARIFF_ATTRIBUTE,
                cf.CONF_TARIFF_MATCH,
                cf.CONF_PRICE_UNIT,
                cf.CONF_FREE_SESSION_ENTITY,
            }
        }
    )
    assert result["step_id"] == "model"
    result = await flow.async_step_model({cf.CONF_POWER_ENTITY: CONNECTIONS[cf.CONF_POWER_ENTITY]})
    assert result["step_id"] == "preconditioning"
    result = await flow.async_step_preconditioning(
        {
            key: CONNECTIONS[key]
            for key in (
                cf.CONF_PRECONDITIONING_ENTITY,
                cf.CONF_COMPLETION_ENTITY,
                cf.CONF_COMPLETION_STATE,
            )
        }
    )
    assert result["step_id"] == "preferences"

    result = await flow.async_step_preferences(_preferences())
    assert result["type"] == "create_entry"
    assert result["title"] == "Test EV"
    assert result["data"][cf.CONF_CHARGE_SWITCH] == "switch.test_ev_charge"
    assert cf.CONF_MODE not in result["data"]
    assert result["options"][cf.CONF_MODE] == "cheap_top_up"
    assert result["options"][cf.CONF_CAPACITY_KWH] == 60.0
    assert result["options"][cf.CONF_LEARN_POWER] is False


@pytest.mark.asyncio
async def test_reconfigure_preserves_required_connections_and_clears_omitted_optional_entities(
    monkeypatch,
):
    existing = SimpleNamespace(entry_id="entry-1", title="Test EV", data=dict(CONNECTIONS))
    flow = _flow(monkeypatch, [existing])
    flow._get_reconfigure_entry = lambda: existing
    flow.async_update_and_abort = lambda entry, **kwargs: {
        "type": "abort",
        "entry": entry,
        **kwargs,
    }

    result = await flow.async_step_reconfigure()
    assert result["step_id"] == "vehicle"
    vehicle_keys = (
        cf.CONF_CHARGE_SWITCH,
        cf.CONF_CHARGING_SENSOR,
        cf.CONF_CABLE_SENSOR,
        cf.CONF_LOCATION_ENTITY,
        cf.CONF_HOME_ZONE,
        cf.CONF_SOC_ENTITY,
    )
    await flow.async_step_vehicle({key: CONNECTIONS[key] for key in vehicle_keys})
    electricity_keys = (
        cf.CONF_RATE_ENTITY,
        cf.CONF_TODAY_RATES_ENTITY,
        cf.CONF_TARIFF_ATTRIBUTE,
        cf.CONF_TARIFF_MATCH,
        cf.CONF_PRICE_UNIT,
    )
    await flow.async_step_electricity({key: CONNECTIONS[key] for key in electricity_keys})
    await flow.async_step_model({})
    await flow.async_step_preconditioning({cf.CONF_COMPLETION_STATE: "complete"})
    result = await flow.async_step_finish_reconfigure()

    assert result["type"] == "abort"
    updated = result["data_updates"]
    assert updated[cf.CONF_CHARGE_SWITCH] == "switch.test_ev_charge"
    assert OPTIONAL_KEYS <= updated.keys()
    assert all(updated[key] is None for key in OPTIONAL_KEYS)


@pytest.mark.asyncio
async def test_setup_rejects_duplicate_charge_switch(monkeypatch):
    other = SimpleNamespace(
        entry_id="other", data={cf.CONF_CHARGE_SWITCH: CONNECTIONS[cf.CONF_CHARGE_SWITCH]}
    )
    flow = _flow(monkeypatch, [other])
    flow._data = {cf.CONF_NAME: "Test EV", **CONNECTIONS}

    result = await flow.async_step_preferences(_preferences())

    assert result["type"] == "form"
    assert result["errors"] == {"base": "charge_switch_already_configured"}


@pytest.mark.asyncio
async def test_reconfigure_rejects_duplicate_switch_owned_by_another_entry(monkeypatch):
    current = SimpleNamespace(entry_id="current", title="Test EV", data=dict(CONNECTIONS))
    other = SimpleNamespace(entry_id="other", data={cf.CONF_CHARGE_SWITCH: "switch.other"})
    flow = _flow(monkeypatch, [current, other])
    flow._get_reconfigure_entry = lambda: current
    flow.async_update_and_abort = Mock()
    flow._reconfigure_entry = current
    flow._reconfigure_mode = True
    flow._data = dict(CONNECTIONS)
    flow._data[cf.CONF_CHARGE_SWITCH] = "switch.other"
    flow.hass.states.get = lambda entity_id: (
        object() if entity_id in CONNECTIONS.values() or entity_id == "switch.other" else None
    )

    result = await flow.async_step_finish_reconfigure()

    assert result["type"] == "form"
    assert result["errors"] == {"base": "charge_switch_already_configured"}
    flow.async_update_and_abort.assert_not_called()


@pytest.mark.asyncio
async def test_selected_entities_must_exist_and_match_their_domain(monkeypatch):
    flow = _flow(monkeypatch)
    result = await flow.async_step_vehicle(
        {
            cf.CONF_CHARGE_SWITCH: "sensor.test_ev_charge",
            cf.CONF_CHARGING_SENSOR: "binary_sensor.test_ev_charging",
            cf.CONF_CABLE_SENSOR: "binary_sensor.test_ev_charge_cable",
            cf.CONF_LOCATION_ENTITY: "device_tracker.test_ev_location",
            cf.CONF_HOME_ZONE: "zone.home",
            cf.CONF_SOC_ENTITY: "sensor.test_ev_battery_level",
        }
    )
    assert result["step_id"] == "vehicle"
    assert result["errors"][cf.CONF_CHARGE_SWITCH] == "wrong_entity_domain"

    switch_selector = cf._entity_selector("switch")
    with pytest.raises(Exception):
        switch_selector("sensor.test_ev_charge")


def test_all_numeric_option_groups_reject_nan_and_invalid_values():
    model_values = {
        cf.CONF_CAPACITY_KWH: float("nan"),
        cf.CONF_VOLTAGE: 230,
        cf.CONF_EFFICIENCY: 0.92,
        cf.CONF_FIXED_POWER_KW: 7,
        cf.CONF_LEARN_POWER: False,
        cf.CONF_PLANNING_MARGIN: 0.1,
        cf.CONF_MAINTENANCE_MARGIN: 2,
    }
    assert cf._validate_option_values("model", model_values) == {
        cf.CONF_CAPACITY_KWH: "invalid_number"
    }
    assert cf._validate_option_values(
        "planning", _preferences(**{cf.CONF_MAX_CHEAP_RATE: float("inf")})
    ) == {cf.CONF_MAX_CHEAP_RATE: "invalid_number"}
    assert cf._validate_option_values(
        "planning", _preferences(**{cf.CONF_TARGET_PERCENT: 101})
    ) == {cf.CONF_TARGET_PERCENT: "invalid_number"}


def test_deadlines_keep_explicit_offsets_and_localize_normal_home_times():
    assert cf._parse_deadline("2026-10-25T01:30:00+01:00", "Europe/London") == (
        "2026-10-25T01:30:00+01:00"
    )
    assert cf._parse_deadline("2026-10-25T02:30:00", "Europe/London") == (
        "2026-10-25T02:30:00+00:00"
    )
    with pytest.raises(ValueError):
        cf._parse_deadline("2026-10-25T01:30:00", "Europe/London")
    with pytest.raises(ValueError):
        cf._parse_deadline("2026-03-29T01:30:00", "Europe/London")
    with pytest.raises(ValueError):
        cf._parse_deadline("2026-10-25", "Europe/London")


def test_mode_and_price_unit_selectors_reject_unknown_values():
    with pytest.raises(Exception):
        cf._preferences_schema(cf.DEFAULT_OPTIONS)(_preferences(**{cf.CONF_MODE: "tomorrow"}))
    electricity = cf._connection_schema((cf.CONF_PRICE_UNIT,), {cf.CONF_PRICE_UNIT: "GBP/kWh"})
    with pytest.raises(Exception):
        electricity({cf.CONF_PRICE_UNIT: "USD/kWh"})


@pytest.mark.asyncio
async def test_options_flow_carries_groups_and_requires_deadline_in_deadline_mode(monkeypatch):
    options = dict(cf.DEFAULT_OPTIONS)
    entry = SimpleNamespace(entry_id="entry-1", domain=cf.DOMAIN, options=options)
    hass = SimpleNamespace(
        config=SimpleNamespace(time_zone="Europe/London"),
        config_entries=SimpleNamespace(async_get_known_entry=lambda entry_id: entry),
    )
    flow = cf.EVChargeControllerOptionsFlow()
    flow.hass = hass
    flow.handler = entry.entry_id
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}
    flow.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}

    result = await flow.async_step_init()
    assert result["step_id"] == "planning"
    result = await flow.async_step_planning(_preferences(**{cf.CONF_MODE: "deadline"}))
    assert result["type"] == "form"
    assert result["errors"] == {cf.CONF_DEADLINE: "deadline_required"}

    result = await flow.async_step_planning(
        _preferences(
            **{
                cf.CONF_MODE: "deadline",
                cf.CONF_DEADLINE: "2026-11-01T01:30:00+00:00",
            }
        )
    )
    assert result["step_id"] == "model"
    assert flow._options[cf.CONF_DEADLINE] == "2026-11-01T01:30:00+00:00"

    model = {
        cf.CONF_CAPACITY_KWH: 60,
        cf.CONF_VOLTAGE: 230,
        cf.CONF_EFFICIENCY: 0.92,
        cf.CONF_FIXED_POWER_KW: 7,
        cf.CONF_LEARN_POWER: False,
        cf.CONF_PLANNING_MARGIN: 0.1,
        cf.CONF_MAINTENANCE_MARGIN: 2,
    }
    await flow.async_step_model(model)
    await flow.async_step_preconditioning(
        {
            cf.CONF_PRECONDITIONING_POLICY: "keep_existing",
            cf.CONF_PRECONDITIONING_MINUTES: 60,
        }
    )
    await flow.async_step_control(
        {
            cf.CONF_AUTOMATIC_CONTROL: True,
            cf.CONF_MONITORING_ONLY: True,
            cf.CONF_BOOST_HOURS: 12,
            cf.CONF_EXTERNAL_CHANGE_POLICY: "respect",
            cf.CONF_MANUAL_HOLD_MINUTES: 120,
        }
    )
    result = await flow.async_step_reliability(
        {
            cf.CONF_MAX_RETRIES: 3,
            cf.CONF_RETRY_SECONDS: 60,
            cf.CONF_STALE_MINUTES: 30,
        }
    )
    assert result["type"] == "create_entry"
    assert result["data"][cf.CONF_MODE] == "deadline"
    assert result["data"][cf.CONF_CAPACITY_KWH] == 60
    assert result["data"][cf.CONF_STALE_MINUTES] == 30


@pytest.mark.asyncio
async def test_options_flow_rejects_nan_before_saving(monkeypatch):
    entry = SimpleNamespace(entry_id="entry-1", domain=cf.DOMAIN, options=dict(cf.DEFAULT_OPTIONS))
    flow = cf.EVChargeControllerOptionsFlow()
    flow.hass = SimpleNamespace(
        config=SimpleNamespace(time_zone="Europe/London"),
        config_entries=SimpleNamespace(async_get_known_entry=lambda entry_id: entry),
    )
    flow.handler = entry.entry_id
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}
    flow.async_create_entry = Mock()
    result = await flow.async_step_model(
        {
            cf.CONF_CAPACITY_KWH: float("nan"),
            cf.CONF_VOLTAGE: 230,
            cf.CONF_EFFICIENCY: 0.92,
            cf.CONF_FIXED_POWER_KW: 7,
            cf.CONF_LEARN_POWER: False,
            cf.CONF_PLANNING_MARGIN: 0.1,
            cf.CONF_MAINTENANCE_MARGIN: 2,
        }
    )
    assert result["errors"] == {cf.CONF_CAPACITY_KWH: "invalid_number"}
    flow.async_create_entry.assert_not_called()


@pytest.mark.asyncio
async def test_initial_preferences_reject_nan(monkeypatch):
    flow = _flow(monkeypatch)
    flow._data = {cf.CONF_NAME: "Test EV", **CONNECTIONS}
    result = await flow.async_step_preferences(
        _preferences(**{cf.CONF_MAX_CHEAP_RATE: float("nan")})
    )
    assert result["errors"] == {cf.CONF_MAX_CHEAP_RATE: "invalid_number"}


@pytest.mark.asyncio
async def test_options_seed_from_live_runtime_preferences(monkeypatch):
    saved = dict(cf.DEFAULT_OPTIONS)
    live = {
        **saved,
        cf.CONF_MAX_CHEAP_RATE: 23.5,
        cf.CONF_TARGET_PERCENT: 65,
        cf.CONF_MODE: "deadline",
        cf.CONF_DEADLINE: "2026-10-20T07:30:00+01:00",
    }
    entry = SimpleNamespace(
        entry_id="entry-1",
        domain=cf.DOMAIN,
        options=saved,
        runtime_data=SimpleNamespace(preferences=live),
    )
    flow = cf.EVChargeControllerOptionsFlow()
    flow.hass = SimpleNamespace(
        config=SimpleNamespace(time_zone="Europe/London"),
        config_entries=SimpleNamespace(async_get_known_entry=lambda entry_id: entry),
    )
    flow.handler = entry.entry_id
    flow.async_show_form = lambda **kwargs: {"type": "form", **kwargs}
    result = await flow.async_step_planning()
    assert result["step_id"] == "planning"
    assert flow._options[cf.CONF_MAX_CHEAP_RATE] == 23.5
    assert flow._options[cf.CONF_TARGET_PERCENT] == 65
    assert flow._options[cf.CONF_DEADLINE] == live[cf.CONF_DEADLINE]

    await flow.async_step_model(
        {
            cf.CONF_CAPACITY_KWH: 60,
            cf.CONF_VOLTAGE: 230,
            cf.CONF_EFFICIENCY: 0.92,
            cf.CONF_FIXED_POWER_KW: 7,
            cf.CONF_LEARN_POWER: False,
            cf.CONF_PLANNING_MARGIN: 0.1,
            cf.CONF_MAINTENANCE_MARGIN: 2,
        }
    )
    assert flow._options[cf.CONF_MAX_CHEAP_RATE] == 23.5
    assert flow._options[cf.CONF_TARGET_PERCENT] == 65
    assert flow._options[cf.CONF_DEADLINE] == live[cf.CONF_DEADLINE]
