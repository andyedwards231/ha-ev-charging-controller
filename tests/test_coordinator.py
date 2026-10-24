"""Coordinator tests using the local Home Assistant runtime and isolated storage."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType

import pytest
import pytest_asyncio
from homeassistant.config_entries import SOURCE_USER, ConfigEntry
from homeassistant.core import HomeAssistant

COMPONENT_ROOT = Path(__file__).parents[1] / "custom_components"
sys.path.insert(0, str(COMPONENT_ROOT))

from ev_charge_controller import coordinator as coordinator_module  # noqa: E402
from ev_charge_controller.const import DOMAIN  # noqa: E402

UTC = timezone.utc
ENTITY = {
    "charge_switch": "switch.test_ev_charge",
    "charging_sensor": "binary_sensor.test_ev_charging",
    "cable_sensor": "binary_sensor.test_ev_charge_cable",
    "location_entity": "device_tracker.test_ev_location",
    "home_zone": "zone.home",
    "soc_entity": "sensor.test_ev_battery_level",
    "car_limit_entity": "number.test_ev_charge_limit",
    "current_entity": "number.test_ev_charge_current",
    "preconditioning_entity": "binary_sensor.test_ev_preconditioning_enabled",
    "completion_entity": "sensor.test_ev_charge_complete",
    "rate_entity": "sensor.agile_current_rate",
    "today_rates_entity": "event.agile_current_day_rates",
    "tomorrow_rates_entity": "event.agile_next_day_rates",
    "free_session_entity": "calendar.free_session",
    "power_entity": "sensor.wall_connector_power",
    "tariff_attribute": "tariff",
    "tariff_match": "AGILE",
    "price_unit": "GBP/kWh",
}


class MemoryStore:
    """Store stand-in that never opens or writes Home Assistant .storage."""

    records: dict[str, dict] = {}

    def __init__(self, _hass, _version, key, **_kwargs):
        self.key = key

    async def async_load(self):
        saved = self.records.get(self.key)
        return dict(saved) if saved is not None else None

    def async_delay_save(self, data_func, _delay):
        self.records[self.key] = data_func()

    async def async_save(self, data):
        self.records[self.key] = dict(data)


@pytest_asyncio.fixture
async def hass(tmp_path):
    app = HomeAssistant(str(tmp_path))
    await app.async_start()
    yield app
    await app.async_stop()


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch):
    MemoryStore.records.clear()
    monkeypatch.setattr(coordinator_module, "Store", MemoryStore)


def make_entry(*, options=None, entry_id="policy-test"):
    return ConfigEntry(
        created_at=datetime.now(UTC),
        data=ENTITY,
        disabled_by=None,
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        entry_id=entry_id,
        minor_version=1,
        modified_at=datetime.now(UTC),
        options=options or {},
        pref_disable_new_entities=None,
        pref_disable_polling=None,
        source=SOURCE_USER,
        subentries_data=(),
        title="Test EV Charge Controller",
        unique_id=f"test_ev-{entry_id}",
        version=1,
    )


async def seed_entities(
    hass,
    *,
    price="0.08",
    switch="off",
    charging="off",
    soc="50",
    car_limit="90",
    completion="not_complete",
    price_start=None,
    price_end=None,
    soc_attrs=None,
    rate_tariff="AGILE-24-10-01",
):
    now = datetime.now(UTC)
    start = price_start or (now - timedelta(minutes=5))
    end = price_end or (now + timedelta(minutes=25))
    fresh_attrs = {"data_last_retrieved": now.isoformat()}
    hass.states.async_set(ENTITY["charge_switch"], switch)
    hass.states.async_set(ENTITY["charging_sensor"], charging)
    hass.states.async_set(ENTITY["cable_sensor"], "on")
    hass.states.async_set(ENTITY["location_entity"], "home")
    hass.states.async_set(ENTITY["home_zone"], "0", {"friendly_name": "Home"})
    hass.states.async_set(ENTITY["soc_entity"], soc, {**fresh_attrs, **(soc_attrs or {})})
    hass.states.async_set(ENTITY["car_limit_entity"], car_limit, fresh_attrs)
    hass.states.async_set(ENTITY["current_entity"], "16", fresh_attrs)
    hass.states.async_set(ENTITY["preconditioning_entity"], "off")
    hass.states.async_set(ENTITY["completion_entity"], completion)
    hass.states.async_set(
        ENTITY["rate_entity"],
        price,
        {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "tariff": rate_tariff,
        },
    )
    hass.states.async_set(ENTITY["today_rates_entity"], "unknown", {"rates": []})
    hass.states.async_set(ENTITY["tomorrow_rates_entity"], "unknown", {"rates": []})
    hass.states.async_set(ENTITY["free_session_entity"], "off", {})
    hass.states.async_set(ENTITY["power_entity"], "0", {**fresh_attrs, "unit_of_measurement": "W"})


async def registered_switch_calls(hass):
    calls = []

    async def record(call):
        calls.append((call.service, call.data["entity_id"]))

    hass.services.async_register("switch", "turn_on", record)
    hass.services.async_register("switch", "turn_off", record)
    return calls


async def make_coordinator(
    hass, *, options=None, entry_id="policy-test", saved=None, seed_kwargs=None
):
    await seed_entities(hass, **(seed_kwargs or {}))
    calls = await registered_switch_calls(hass)
    entry = make_entry(options=options, entry_id=entry_id)
    store_key = f"{DOMAIN}.{entry.entry_id}.intent"
    if saved is not None:
        MemoryStore.records[store_key] = saved
    coordinator = coordinator_module.EVCoordinator(hass, entry)
    await coordinator.async_initialize()
    return coordinator, calls, entry, store_key


@pytest.mark.asyncio
async def test_monitoring_only_never_calls_switch_services(hass):
    coordinator, calls, _, _ = await make_coordinator(hass, options={"monitoring_only": True})
    assert calls == []
    assert coordinator.decision.desired is True
    assert coordinator.data["status"].startswith("Monitoring:")
    assert coordinator.data["managed_tariff"] is True

    await coordinator.async_reconcile()
    assert calls == []
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_start_and_stop_service_acknowledgement_wait_for_observed_feedback(hass):
    coordinator, calls, _, _ = await make_coordinator(hass, options={"monitoring_only": False})
    assert calls == [("turn_on", ENTITY["charge_switch"])]
    assert coordinator.pending is not None
    assert coordinator.last_command["result"] == "requested"
    assert coordinator.owns_charge is False

    now = datetime.now(UTC)
    hass.states.async_set(ENTITY["charge_switch"], "on")
    hass.states.async_set(ENTITY["charging_sensor"], "on", {"data_last_retrieved": now.isoformat()})
    await coordinator.async_reconcile()
    assert coordinator.pending is None
    assert coordinator.last_command["result"] == "confirmed"
    assert coordinator.owns_charge is True

    rate_state = hass.states.get(ENTITY["rate_entity"])
    hass.states.async_set(ENTITY["rate_entity"], "0.30", dict(rate_state.attributes))
    await coordinator.async_reconcile()
    assert calls[-1] == ("turn_off", ENTITY["charge_switch"])
    assert coordinator.pending is not None
    assert coordinator.last_command["result"] == "requested"

    now = datetime.now(UTC)
    hass.states.async_set(ENTITY["charge_switch"], "off")
    # Until charging feedback also reports off, a switch service acknowledgement
    # is not treated as confirmation of stopped charging.
    await coordinator.async_reconcile()
    assert coordinator.pending is not None
    hass.states.async_set(
        ENTITY["charging_sensor"], "off", {"data_last_retrieved": now.isoformat()}
    )
    await coordinator.async_reconcile()
    assert coordinator.pending is None
    assert coordinator.owns_charge is False
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_retries_stop_after_configured_bounded_attempts(hass):
    coordinator, calls, _, _ = await make_coordinator(
        hass,
        options={"monitoring_only": False, "max_retries": 2, "retry_seconds": 1},
    )
    assert len(calls) == 1
    for expected_count in (2, 3):
        coordinator.pending["next_attempt"] = datetime.now(UTC) - timedelta(seconds=1)
        await coordinator.async_reconcile()
        assert len(calls) == expected_count
    coordinator.pending["next_attempt"] = datetime.now(UTC) - timedelta(seconds=1)
    await coordinator.async_reconcile()
    assert len(calls) == 3
    assert coordinator.pending["attempts"] == 3
    assert coordinator.command_error
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_tariff_handover_cancels_pending_retry_and_issues_no_further_call(hass):
    coordinator, calls, _, _ = await make_coordinator(
        hass,
        options={"monitoring_only": False, "retry_seconds": 1},
    )
    assert len(calls) == 1
    coordinator.pending["next_attempt"] = datetime.now(UTC) - timedelta(seconds=1)
    rate = hass.states.get(ENTITY["rate_entity"])
    hass.states.async_set(
        ENTITY["rate_entity"], rate.state, {**rate.attributes, "tariff": "Intelligent Go"}
    )
    await hass.async_block_till_done()
    assert coordinator.pending is None
    await coordinator.async_reconcile()
    assert len(calls) == 1
    assert coordinator.decision.desired is None
    assert coordinator.owns_charge is False
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_pause_cancels_pending_retries_without_a_switch_call(hass):
    coordinator, calls, _, _ = await make_coordinator(hass, options={"monitoring_only": False})
    assert len(calls) == 1
    await coordinator.async_change(automatic_control=False)
    assert coordinator.pending is None
    assert coordinator.decision.desired is None
    assert len(calls) == 1
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_stale_soc_suspends_target_mode_and_does_not_issue_start(hass):
    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    await seed_entities(hass, soc_attrs={"data_last_retrieved": old})
    calls = await registered_switch_calls(hass)
    entry = make_entry(
        options={
            "mode": "deadline",
            "monitoring_only": False,
            "deadline": (datetime.now(UTC) + timedelta(hours=5)).isoformat(),
        }
    )
    coordinator = coordinator_module.EVCoordinator(hass, entry)
    await coordinator.async_initialize()
    assert coordinator.snapshot.soc is None
    assert coordinator.decision.problem is True
    assert calls == []
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_boost_target_does_not_mark_lower_deadline_request_complete(hass):
    saved = {
        "preferences": {},
        "options_baseline": {},
        "boost_until": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "boost_target": 60.0,
    }
    coordinator, _, _, store_key = await make_coordinator(
        hass,
        options={
            "mode": "deadline",
            "monitoring_only": True,
            "target_percent": 80.0,
            "deadline": (datetime.now(UTC) + timedelta(hours=5)).isoformat(),
        },
        saved=saved,
    )
    # Current SOC has to reach the boost target, while remaining below the
    # requested deadline target.
    hass.states.async_set(
        ENTITY["soc_entity"],
        "60",
        {
            "data_last_retrieved": datetime.now(UTC).isoformat(),
        },
    )
    await coordinator.async_reconcile()
    assert coordinator.boost_until is None
    assert coordinator.request_completed is False
    assert coordinator.decision.target_reached is False
    assert MemoryStore.records[store_key]["request_completed"] is False
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_startup_restores_intent_and_unload_cleans_subscriptions(hass):
    deadline = (datetime.now(UTC) + timedelta(hours=4)).isoformat()
    boost_until = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    saved = {
        "preferences": {"target_percent": 85.0, "deadline": deadline},
        "options_baseline": {},
        "boost_until": boost_until,
        "boost_target": 75.0,
        "manual_hold_until": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        "request_completed": True,
        "maintenance_satisfied": True,
    }
    coordinator, calls, _, store_key = await make_coordinator(hass, saved=saved)
    assert coordinator.preferences["target_percent"] == 85.0
    assert coordinator.preferences["deadline"] == deadline
    assert coordinator.boost_until == datetime.fromisoformat(boost_until)
    assert coordinator.boost_target == 75.0
    assert coordinator.manual_hold_until is not None
    assert coordinator.request_completed is True
    assert coordinator.maintenance_satisfied is True
    assert calls == []
    assert len(coordinator.unsubscribers) == 2

    await coordinator.async_shutdown()
    assert coordinator.closed is True
    assert coordinator.pending is None
    assert coordinator.unsubscribers == []
    saved_after_unload = MemoryStore.records[store_key]
    assert saved_after_unload["request_completed"] is True
    assert saved_after_unload["boost_target"] == 75.0


@pytest.mark.asyncio
async def test_expired_boost_clears_under_manual_hold_and_non_agile_tariff(hass):
    expired = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    held = (datetime.now(UTC) + timedelta(minutes=15)).isoformat()
    saved = {
        "preferences": {},
        "options_baseline": {},
        "boost_until": expired,
        "boost_target": 70.0,
        "manual_hold_until": held,
    }
    coordinator, calls, _, _ = await make_coordinator(
        hass,
        options={"monitoring_only": False},
        saved=saved,
        seed_kwargs={"rate_tariff": "Intelligent Go"},
    )
    assert coordinator.boost_until is None
    assert coordinator.boost_target is None
    assert coordinator.manual_hold_until is not None
    assert coordinator.decision.desired is None
    assert calls == []
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_unplug_clears_boost_and_manual_hold_while_paused(hass):
    saved = {
        "preferences": {},
        "options_baseline": {},
        "boost_until": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "boost_target": 70.0,
        "manual_hold_until": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
    }
    coordinator, calls, _, _ = await make_coordinator(
        hass,
        options={"automatic_control": False, "monitoring_only": False},
        saved=saved,
    )
    hass.states.async_set(ENTITY["cable_sensor"], "off")
    await coordinator.async_reconcile()
    assert coordinator.boost_until is None
    assert coordinator.boost_target is None
    assert coordinator.manual_hold_until is None
    assert coordinator.decision.status == "Paused"
    assert calls == []
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_completed_deadline_request_does_not_override_pause_or_tariff_release(hass):
    saved = {"preferences": {}, "options_baseline": {}, "request_completed": True}
    paused, paused_calls, _, _ = await make_coordinator(
        hass,
        options={"mode": "deadline", "automatic_control": False, "monitoring_only": False},
        saved=saved,
        entry_id="completed-paused",
    )
    assert paused.decision.status == "Paused"
    assert paused.decision.desired is None
    assert paused_calls == []
    await paused.async_shutdown()

    released, released_calls, _, _ = await make_coordinator(
        hass,
        options={"mode": "deadline", "automatic_control": True, "monitoring_only": False},
        saved=saved,
        entry_id="completed-tariff",
        seed_kwargs={"rate_tariff": "Intelligent Go"},
    )
    assert released.decision.status == "Released to another tariff"
    assert released.decision.desired is None
    assert released_calls == []
    await released.async_shutdown()


@pytest.mark.asyncio
async def test_changing_requested_target_clears_persisted_completion(hass):
    options = {
        "mode": "deadline",
        "monitoring_only": True,
        "deadline": (datetime.now(UTC) + timedelta(hours=5)).isoformat(),
    }
    saved = {"preferences": {}, "options_baseline": dict(options), "request_completed": True}
    coordinator, calls, _, store_key = await make_coordinator(
        hass,
        options=options,
        saved=saved,
    )
    assert coordinator.request_completed is True
    await coordinator.async_change(target_percent=85.0)
    assert coordinator.request_completed is False
    assert MemoryStore.records[store_key]["request_completed"] is False
    assert calls == []
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_malformed_forecast_never_starts_target_charging(hass):
    await seed_entities(hass)
    malformed = [{"start": "not-a-date", "end": "also-not-a-date", "value": 0.01}]
    hass.states.async_set(ENTITY["today_rates_entity"], "on", {"rates": malformed})
    calls = await registered_switch_calls(hass)
    entry = make_entry(
        options={
            "mode": "deadline",
            "monitoring_only": False,
            "deadline": (datetime.now(UTC) + timedelta(minutes=20)).isoformat(),
        }
    )
    coordinator = coordinator_module.EVCoordinator(hass, entry)
    await coordinator.async_initialize()
    await coordinator.async_reconcile()
    assert calls == [], (calls, coordinator.decision, coordinator.data)
    assert coordinator.data["problem"] is True
    assert coordinator.decision.desired is not True
    assert coordinator.data["forecast_available"] is False
    assert coordinator.data["forecast_cost"] is None
    assert "Forecast withheld" in coordinator.data["forecast_basis"]
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_second_start_within_two_minutes_creates_manual_hold(hass):
    coordinator, calls, _, _ = await make_coordinator(
        hass,
        options={"monitoring_only": True},
        seed_kwargs={"price": "0.30"},
    )
    assert coordinator.decision.desired is False
    assert calls == []
    hass.states.async_set(ENTITY["charge_switch"], "on")
    await hass.async_block_till_done()
    assert coordinator.manual_hold_until is None

    hass.states.async_set(ENTITY["charge_switch"], "off")
    await hass.async_block_till_done()
    hass.states.async_set(ENTITY["charge_switch"], "on")
    await hass.async_block_till_done()
    assert coordinator.manual_hold_until is not None
    assert coordinator.pending is None
    assert calls == []
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_turning_off_a_wanted_charge_still_holds(hass):
    coordinator, calls, _, _ = await make_coordinator(hass, options={"monitoring_only": False})
    now = datetime.now(UTC)
    hass.states.async_set(ENTITY["charge_switch"], "on")
    hass.states.async_set(
        ENTITY["charging_sensor"], "on", {"data_last_retrieved": now.isoformat()}
    )
    await coordinator.async_reconcile()
    assert coordinator.owns_charge is True
    hass.states.async_set(ENTITY["charge_switch"], "off")
    await hass.async_block_till_done()
    assert coordinator.manual_hold_until is not None
    assert calls == [("turn_on", ENTITY["charge_switch"])]
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_expired_live_price_stops_confirmed_owned_charge(hass):
    coordinator, calls, _, _ = await make_coordinator(
        hass,
        options={"monitoring_only": False},
    )
    assert calls == [("turn_on", ENTITY["charge_switch"])]
    now = datetime.now(UTC)
    hass.states.async_set(ENTITY["charge_switch"], "on")
    hass.states.async_set(ENTITY["charging_sensor"], "on", {"data_last_retrieved": now.isoformat()})
    await coordinator.async_reconcile()
    assert coordinator.owns_charge is True

    rate = hass.states.get(ENTITY["rate_entity"])
    hass.states.async_set(
        ENTITY["rate_entity"],
        rate.state,
        {
            **rate.attributes,
            "start": (now - timedelta(hours=1)).isoformat(),
            "end": (now - timedelta(seconds=1)).isoformat(),
        },
    )
    await coordinator.async_reconcile()
    assert calls[-1] == ("turn_off", ENTITY["charge_switch"])
    assert coordinator.decision.status == "Price unavailable"
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_failed_service_calls_also_obey_retry_bound(hass):
    await seed_entities(hass)
    calls = []

    async def fail_start(call):
        calls.append((call.service, call.data["entity_id"]))
        raise RuntimeError("mocked service failure")

    async def record_stop(call):
        calls.append((call.service, call.data["entity_id"]))

    hass.services.async_register("switch", "turn_on", fail_start)
    hass.services.async_register("switch", "turn_off", record_stop)
    entry = make_entry(options={"monitoring_only": False, "max_retries": 1, "retry_seconds": 1})
    coordinator = coordinator_module.EVCoordinator(hass, entry)
    await coordinator.async_initialize()
    assert len(calls) == 1
    assert coordinator.last_command["result"] == "failed"
    coordinator.pending["next_attempt"] = datetime.now(UTC) - timedelta(seconds=1)
    await coordinator.async_reconcile()
    assert len(calls) == 2
    coordinator.pending["next_attempt"] = datetime.now(UTC) - timedelta(seconds=1)
    await coordinator.async_reconcile()
    assert len(calls) == 2
    assert coordinator.command_error
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_away_state_never_dispatches_a_switch_command(hass):
    await seed_entities(hass)
    hass.states.async_set(ENTITY["location_entity"], "not_home")
    calls = await registered_switch_calls(hass)
    entry = make_entry(options={"monitoring_only": False})
    coordinator = coordinator_module.EVCoordinator(hass, entry)
    await coordinator.async_initialize()
    assert coordinator.snapshot.home is False
    assert coordinator.decision.status == "Away"
    assert coordinator.decision.desired is None
    assert calls == []
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_reload_keeps_runtime_rate_override_but_applies_changed_target_option(hass):
    original_options = {
        "mode": "cheap_top_up",
        "target_percent": 80.0,
        "monitoring_only": True,
    }
    coordinator, calls, entry, store_key = await make_coordinator(
        hass,
        options=original_options,
        entry_id="options-baseline-reload",
    )
    await coordinator.async_change(max_cheap_rate=7.0)
    assert coordinator.preferences["max_cheap_rate"] == 7.0
    assert calls == []

    # Simulate a Home Assistant options-flow update before the next startup.
    object.__setattr__(entry, "options", {**original_options, "target_percent": 85.0})
    await coordinator.async_shutdown()
    assert MemoryStore.records[store_key]["options_baseline"] == original_options

    restarted = coordinator_module.EVCoordinator(hass, entry)
    await restarted.async_initialize()
    assert restarted.preferences["target_percent"] == 85.0
    assert restarted.preferences["max_cheap_rate"] == 7.0
    assert calls == []
    await restarted.async_shutdown()


@pytest.mark.asyncio
async def test_live_price_mismatch_with_selected_current_forecast_blocks_start(hass):
    now = datetime.now(UTC)
    start, end = now - timedelta(minutes=2), now + timedelta(minutes=28)
    await seed_entities(hass, price="0.30", price_start=start, price_end=end)
    hass.states.async_set(
        ENTITY["today_rates_entity"],
        "on",
        {
            "tariff_code": "AGILE-24-10-01",
            "rates": [
                {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "value_inc_vat": 0.01,
                }
            ],
        },
    )
    calls = await registered_switch_calls(hass)
    entry = make_entry(
        options={
            "mode": "deadline",
            "monitoring_only": False,
            "target_percent": 51.0,
            "deadline": (now + timedelta(hours=6)).isoformat(),
        },
        entry_id="live-forecast-price-mismatch",
    )
    coordinator = coordinator_module.EVCoordinator(hass, entry)
    await coordinator.async_initialize()
    assert calls == []
    assert coordinator.data["problem"] is True
    assert coordinator.decision.desired is not True
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_deadline_keeps_todays_slots_when_tomorrow_is_unavailable(hass):
    now = datetime.now(UTC)
    start, end = now - timedelta(minutes=5), now + timedelta(minutes=25)
    coordinator, calls, _, _ = await make_coordinator(
        hass,
        options={
            "mode": "deadline",
            "monitoring_only": True,
            "target_percent": 80,
            "deadline": (now + timedelta(hours=8)).isoformat(),
        },
        seed_kwargs={"price": "0.08", "price_start": start, "price_end": end},
    )
    hass.states.async_set(
        ENTITY["today_rates_entity"],
        "on",
        {
            "tariff_code": "AGILE-24-10-01",
            "rates": [{"start": start.isoformat(), "end": end.isoformat(), "value": 0.08}],
        },
    )
    hass.states.async_set(ENTITY["tomorrow_rates_entity"], "unavailable", {})
    await coordinator.async_reconcile()
    assert coordinator.plan is not None
    assert len(coordinator.plan.slots) == 1
    assert coordinator.plan.shortfall_kwh > 0
    assert coordinator.plan.completion is False
    assert coordinator.data["rates_complete"] is False
    assert "Tomorrow rates are unavailable" in coordinator.data["rates_warning"]
    assert "replan when new rates arrive" in coordinator.data["rates_warning"]
    assert calls == []
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_current_amps_change_plan_duration_and_cost(hass):
    now = datetime.now(UTC)
    first_start, first_end = now - timedelta(minutes=5), now + timedelta(hours=1)
    second_end = now + timedelta(hours=2)
    coordinator, _, _, _ = await make_coordinator(
        hass,
        options={
            "mode": "deadline",
            "monitoring_only": True,
            "target_percent": 60,
            "deadline": (now + timedelta(hours=4)).isoformat(),
        },
        seed_kwargs={"soc": "50", "price": "0.1", "price_start": first_start, "price_end": first_end},
    )
    hass.states.async_set(
        ENTITY["today_rates_entity"],
        "on",
        {
            "tariff_code": "AGILE-24-10-01",
            "rates": [
                {"start": first_start.isoformat(), "end": first_end.isoformat(), "value": 0.1},
                {"start": first_end.isoformat(), "end": second_end.isoformat(), "value": 0.2},
            ],
        },
    )
    await coordinator.async_reconcile()
    slow_duration = sum((slot.end - slot.start).total_seconds() for slot in coordinator.plan.slots)
    slow_cost = coordinator.plan.estimated_cost
    hass.states.async_set(ENTITY["current_entity"], "32", {"data_last_retrieved": now.isoformat()})
    await coordinator.async_reconcile()
    fast_duration = sum((slot.end - slot.start).total_seconds() for slot in coordinator.plan.slots)
    assert fast_duration < slow_duration
    assert coordinator.plan.estimated_cost != pytest.approx(slow_cost)
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_learned_power_fraction_scales_with_current_amps(hass):
    coordinator, _, _, _ = await make_coordinator(hass, options={"learn_power": True})
    coordinator.learned_power_ratio = 0.5
    now = datetime.now(UTC)
    slow_power = coordinator._read(now)[2]
    hass.states.async_set(ENTITY["current_entity"], "32", {"data_last_retrieved": now.isoformat()})
    fast_power = coordinator._read(now)[2]
    assert fast_power == pytest.approx(slow_power * 2)
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_top_up_forecast_is_observational_and_uses_eligible_slots(hass):
    now = datetime.now(UTC)
    slot_start = now + timedelta(hours=1)
    slot_end = now + timedelta(hours=2)
    coordinator, calls, _, _ = await make_coordinator(
        hass,
        options={"mode": "cheap_top_up", "monitoring_only": True, "max_cheap_rate": 12},
        seed_kwargs={
            "price": "0.3",
            "soc": "50",
            "car_limit": "52",
            "price_end": slot_start,
        },
    )
    hass.states.async_set(
        ENTITY["today_rates_entity"],
        "on",
        {
            "tariff_code": "AGILE-24-10-01",
            "rates": [
                {"start": slot_start.isoformat(), "end": slot_end.isoformat(), "value": 0.08},
                {
                    "start": slot_end.isoformat(),
                    "end": (slot_end + timedelta(hours=1)).isoformat(),
                    "value": 0.09,
                },
            ],
        },
    )
    await coordinator.async_reconcile()
    assert coordinator.decision.desired is False
    assert coordinator.data["schedule"] == []
    assert coordinator.data["forecast_completion"] is not None
    assert coordinator.data["forecast_soc"] == 52
    assert len(coordinator.data["forecast_schedule"]) == 1
    assert coordinator.data["forecast_schedule"][0]["price_pence"] == pytest.approx(8)
    assert coordinator.data["forecast_completion"] == coordinator.data["forecast_schedule"][0]["end"]
    assert calls == []
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_known_slots_after_a_price_gap_can_forecast_target_completion(hass):
    now = datetime.now(UTC)
    gap_end = now + timedelta(hours=2)
    coordinator, calls, _, _ = await make_coordinator(
        hass,
        options={
            "mode": "deadline",
            "monitoring_only": True,
            "target_percent": 52,
            "deadline": (now + timedelta(hours=4)).isoformat(),
        },
        seed_kwargs={"soc": "50", "price": "0.3", "price_end": now + timedelta(minutes=30)},
    )
    hass.states.async_set(
        ENTITY["today_rates_entity"], "on",
        {"rates": [{"start": gap_end.isoformat(),
                    "end": (gap_end + timedelta(hours=1)).isoformat(), "value": 0.08}]},
    )
    await coordinator.async_reconcile()
    assert coordinator.data["rates_complete"] is False
    assert coordinator.data["forecast_soc"] == 52
    assert coordinator.data["forecast_completion"] == coordinator.data["forecast_schedule"][-1]["end"]
    assert calls == []
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_deadline_coverage_warning_when_both_days_end_before_deadline(hass):
    now = datetime.now(UTC)
    today_end = now + timedelta(hours=24)
    tomorrow_end = now + timedelta(hours=48)
    coordinator, _, _, _ = await make_coordinator(
        hass,
        options={
            "mode": "deadline",
            "monitoring_only": True,
            "deadline": (now + timedelta(hours=72)).isoformat(),
        },
        seed_kwargs={"price": "0.08", "price_start": now - timedelta(minutes=5), "price_end": today_end},
    )
    hass.states.async_set(
        ENTITY["today_rates_entity"],
        "on",
        {
            "tariff_code": "AGILE-24-10-01",
            "rates": [
                {
                    "start": (now - timedelta(minutes=5)).isoformat(),
                    "end": today_end.isoformat(),
                    "value": 0.08,
                }
            ],
        },
    )
    hass.states.async_set(
        ENTITY["tomorrow_rates_entity"],
        "on",
        {
            "tariff_code": "AGILE-24-10-01",
            "rates": [
                {
                    "start": today_end.isoformat(),
                    "end": tomorrow_end.isoformat(),
                    "value": 0.09,
                }
            ],
        },
    )
    await coordinator.async_reconcile()
    assert coordinator.data["rates_complete"] is False
    assert "deadline is later" in coordinator.data["rates_warning"]
    assert "deadline is later" in coordinator.data["reason"]
    await coordinator.async_shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("entity_id", "state"),
    [
        (ENTITY["soc_entity"], "unavailable"),
        (ENTITY["car_limit_entity"], "unavailable"),
        (ENTITY["current_entity"], "0"),
    ],
)
async def test_invalid_forecast_inputs_publish_null_metrics(hass, entity_id, state):
    coordinator, _, _, _ = await make_coordinator(hass)
    hass.states.async_set(entity_id, state)
    await coordinator.async_reconcile()
    assert coordinator.data["forecast_soc"] is None
    assert coordinator.data["forecast_cost"] is None
    assert coordinator.data["forecast_grid_energy_kwh"] is None
    assert coordinator.data["forecast_completion"] is None
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_no_eligible_prices_reports_zero_cost_and_a_clear_warning(hass):
    coordinator, _, _, _ = await make_coordinator(
        hass, seed_kwargs={"price": "0.3", "soc": "50", "car_limit": "90"}
    )
    assert coordinator.data["forecast_cost"] == 0
    assert coordinator.data["forecast_grid_energy_kwh"] == 0
    assert coordinator.data["forecast_soc"] == 50
    assert "No eligible published prices" in coordinator.data["rates_warning"]
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_idle_forecast_cache_skips_unchanged_coordinator_updates(hass, monkeypatch):
    coordinator, _, _, _ = await make_coordinator(hass)
    updates = []
    monkeypatch.setattr(coordinator, "async_set_updated_data", updates.append)
    first_forecast = coordinator.data["forecast_series"]
    await coordinator.async_reconcile()
    assert updates == []
    assert coordinator.data["forecast_series"] is first_forecast
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_forecast_rates_stop_at_seven_day_horizon(hass):
    coordinator, _, _, _ = await make_coordinator(hass)
    now = datetime.now(UTC)
    far_rate = coordinator_module.RateSlot(
        now + timedelta(days=8), now + timedelta(days=8, hours=1), 0.01
    )
    forecast = coordinator._build_forecast(now, [far_rate], 3.68, True)
    assert forecast["rates"] == []
    assert forecast["forecast_schedule"] == []
    assert forecast["forecast_completion"] is None
    assert forecast["forecast_cost"] == 0
    assert "No eligible published prices" in forecast["forecast_basis"]
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_active_forecast_cache_refreshes_after_five_minutes(hass):
    coordinator, _, _, _ = await make_coordinator(
        hass, seed_kwargs={"charging": "on"}
    )
    cache_value = coordinator._forecast_cache_data
    cache_time = coordinator._forecast_cache_at
    _, rates, power, _, _, _, _, rates_warning, rates_complete, amps = coordinator._read(
        datetime.now(UTC)
    )
    within_ttl = coordinator._forecast(
        cache_time + timedelta(minutes=4),
        rates,
        power,
        amps,
        rates_complete,
        rates_warning,
    )
    assert within_ttl is cache_value
    refreshed = coordinator._forecast(
        cache_time + timedelta(minutes=5, seconds=1),
        rates,
        power,
        amps,
        rates_complete,
        rates_warning,
    )
    assert refreshed is not cache_value
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_completed_deadline_latch_keeps_forecast_flat_after_soc_falls(hass):
    coordinator, _, _, _ = await make_coordinator(
        hass,
        options={
            "mode": "deadline",
            "monitoring_only": True,
            "target_percent": 80,
            "deadline": (datetime.now(UTC) + timedelta(hours=4)).isoformat(),
        },
        seed_kwargs={"soc": "75"},
    )
    coordinator.request_completed = True
    await coordinator.async_reconcile()
    assert coordinator.data["forecast_available"] is True
    assert coordinator.data["forecast_soc"] == 75
    assert coordinator.data["forecast_schedule"] == []
    assert coordinator.data["forecast_completion"] is None
    assert "request is complete" in coordinator.data["forecast_basis"]
    assert len(coordinator.data["forecast_series"]) == 2
    assert {point["soc"] for point in coordinator.data["forecast_series"]} == {75}
    assert "No eligible published prices" not in (coordinator.data["rates_warning"] or "")
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_satisfied_flexible_maintenance_forecast_stays_flat_in_band(hass):
    coordinator, _, _, _ = await make_coordinator(
        hass,
        options={
            "mode": "flexible",
            "monitoring_only": True,
            "target_percent": 80,
            "maintenance_margin": 2,
        },
        seed_kwargs={"soc": "79"},
    )
    coordinator.maintenance_satisfied = True
    await coordinator.async_reconcile()
    assert coordinator.data["forecast_available"] is True
    assert coordinator.data["forecast_soc"] == 79
    assert len(coordinator.data["forecast_series"]) == 2
    assert "No eligible published prices" not in (coordinator.data["rates_warning"] or "")
    assert coordinator.data["forecast_schedule"] == []
    assert coordinator.data["forecast_completion"] is None
    assert "maintenance is satisfied" in coordinator.data["forecast_basis"]
    await coordinator.async_shutdown()


async def start_unplugged(hass, **options):
    """Controller watching a disconnected car, with active control enabled."""
    seed = {"switch": "off", "charging": "off", **options.pop("seed", {})}
    await seed_entities(hass, **seed)
    hass.states.async_set(ENTITY["cable_sensor"], "off")
    calls = await registered_switch_calls(hass)
    entry = make_entry(
        options={"monitoring_only": False, "external_change_policy": "respect", **options},
        entry_id=options.get("mode", "cheap") + "-plugin",
    )
    coordinator = coordinator_module.EVCoordinator(hass, entry)
    await coordinator.async_initialize()
    return coordinator, calls


async def car_starts_charging(hass):
    """The vehicle enables charging after the cable is already connected."""
    now = datetime.now(UTC)
    hass.states.async_set(ENTITY["charge_switch"], "on")
    hass.states.async_set(
        ENTITY["charging_sensor"], "on", {"data_last_retrieved": now.isoformat()}
    )
    await hass.async_block_till_done()


async def car_stops_charging(hass):
    """Observed end of a charge, so the next start is a separate attempt."""
    now = datetime.now(UTC)
    hass.states.async_set(ENTITY["charge_switch"], "off")
    hass.states.async_set(
        ENTITY["charging_sensor"], "off", {"data_last_retrieved": now.isoformat()}
    )
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_plug_in_autostart_stops_when_the_rate_is_too_high(hass):
    coordinator, calls = await start_unplugged(hass, seed={"price": "0.30"})
    assert coordinator.decision.status == "Unplugged"
    assert calls == []

    hass.states.async_set(ENTITY["cable_sensor"], "on")
    await hass.async_block_till_done()
    await coordinator.async_reconcile()
    assert coordinator.manual_hold_until is None
    assert coordinator.decision.desired is False
    assert calls == []

    await car_starts_charging(hass)
    assert coordinator.manual_hold_until is None
    await coordinator.async_reconcile()
    assert calls == [("turn_off", ENTITY["charge_switch"])]
    assert coordinator.decision.status == "Waiting for cheap rate"
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_plug_in_autostart_stops_outside_a_selected_slot(hass):
    now = datetime.now(UTC)
    current_end = now + timedelta(minutes=25)
    coordinator, calls = await start_unplugged(
        hass,
        mode="flexible",
        seed={"price": "0.10", "price_start": now - timedelta(minutes=5), "price_end": current_end},
    )
    hass.states.async_set(
        ENTITY["today_rates_entity"],
        "on",
        {
            "rates": [
                {
                    "start": (now - timedelta(minutes=5)).isoformat(),
                    "end": current_end.isoformat(),
                    "value_inc_vat": 0.10,
                },
                {
                    "start": current_end.isoformat(),
                    "end": (current_end + timedelta(hours=8)).isoformat(),
                    "value_inc_vat": 0.01,
                },
            ]
        },
    )
    hass.states.async_set(ENTITY["cable_sensor"], "on")
    await hass.async_block_till_done()
    await coordinator.async_reconcile()
    assert coordinator.decision.status == "Waiting for selected slot"
    assert coordinator.decision.desired is False
    assert calls == []

    await car_starts_charging(hass)
    assert coordinator.manual_hold_until is None
    await coordinator.async_reconcile()
    assert calls == [("turn_off", ENTITY["charge_switch"])]
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_enabled_switch_is_stopped_on_plug_in_before_the_car_starts(hass):
    coordinator, calls = await start_unplugged(hass, seed={"price": "0.30", "switch": "on"})
    hass.states.async_set(ENTITY["cable_sensor"], "on")
    await hass.async_block_till_done()
    await coordinator.async_reconcile()
    assert calls == [("turn_off", ENTITY["charge_switch"])]
    assert coordinator.manual_hold_until is None

    hass.states.async_set(ENTITY["charge_switch"], "off")
    await hass.async_block_till_done()
    await coordinator.async_reconcile()
    await car_starts_charging(hass)
    assert coordinator.manual_hold_until is None
    await coordinator.async_reconcile()
    assert calls[-1] == ("turn_off", ENTITY["charge_switch"])
    assert coordinator.decision.status == "Waiting for cheap rate"
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_switch_enable_reported_before_cable_event_still_stops(hass):
    coordinator, calls = await start_unplugged(hass, seed={"price": "0.30"})
    hass.states.async_set(ENTITY["charge_switch"], "on")
    await hass.async_block_till_done()
    hass.states.async_set(ENTITY["cable_sensor"], "on")
    await hass.async_block_till_done()
    assert coordinator.manual_hold_until is None
    await coordinator.async_reconcile()
    assert calls == [("turn_off", ENTITY["charge_switch"])]
    assert coordinator.decision.desired is False
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_second_start_within_two_minutes_overrides_the_stop(hass):
    coordinator, calls = await start_unplugged(hass, seed={"price": "0.30"})
    hass.states.async_set(ENTITY["cable_sensor"], "on")
    await hass.async_block_till_done()
    await car_starts_charging(hass)
    await coordinator.async_reconcile()
    assert calls == [("turn_off", ENTITY["charge_switch"])]
    assert coordinator.manual_hold_until is None

    await car_stops_charging(hass)
    await car_starts_charging(hass)
    assert coordinator.manual_hold_until is not None
    await coordinator.async_reconcile()
    assert calls == [("turn_off", ENTITY["charge_switch"])]
    assert coordinator.decision.status == "Manual hold"
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_start_again_after_two_minutes_is_stopped(hass):
    coordinator, calls = await start_unplugged(hass, seed={"price": "0.30"})
    hass.states.async_set(ENTITY["cable_sensor"], "on")
    await hass.async_block_till_done()
    await car_starts_charging(hass)
    await coordinator.async_reconcile()
    await car_stops_charging(hass)
    coordinator.unwanted_start_at = datetime.now(UTC) - timedelta(minutes=2)
    await car_starts_charging(hass)
    assert coordinator.manual_hold_until is None
    await coordinator.async_reconcile()
    assert calls[-1] == ("turn_off", ENTITY["charge_switch"])
    assert coordinator.decision.status == "Waiting for cheap rate"
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_unplug_clears_the_repeat_window(hass):
    coordinator, calls = await start_unplugged(hass, seed={"price": "0.30"})
    hass.states.async_set(ENTITY["cable_sensor"], "on")
    await hass.async_block_till_done()
    await car_starts_charging(hass)
    await coordinator.async_reconcile()
    await car_stops_charging(hass)
    hass.states.async_set(ENTITY["cable_sensor"], "off")
    await hass.async_block_till_done()
    await coordinator.async_reconcile()
    hass.states.async_set(ENTITY["cable_sensor"], "on")
    await hass.async_block_till_done()
    await car_starts_charging(hass)
    assert coordinator.manual_hold_until is None
    await coordinator.async_reconcile()
    assert calls[-1] == ("turn_off", ENTITY["charge_switch"])
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_charging_sensor_restart_within_two_minutes_is_an_override(hass):
    coordinator, calls = await start_unplugged(hass, seed={"price": "0.30", "switch": "on"})
    hass.states.async_set(ENTITY["cable_sensor"], "on")
    await hass.async_block_till_done()
    now = datetime.now(UTC)
    hass.states.async_set(
        ENTITY["charging_sensor"], "on", {"data_last_retrieved": now.isoformat()}
    )
    await hass.async_block_till_done()
    assert coordinator.manual_hold_until is None
    await coordinator.async_reconcile()
    assert calls == [("turn_off", ENTITY["charge_switch"])]

    hass.states.async_set(
        ENTITY["charging_sensor"], "off", {"data_last_retrieved": datetime.now(UTC).isoformat()}
    )
    await hass.async_block_till_done()
    hass.states.async_set(
        ENTITY["charging_sensor"], "on", {"data_last_retrieved": datetime.now(UTC).isoformat()}
    )
    await hass.async_block_till_done()
    assert coordinator.manual_hold_until is not None
    await coordinator.async_reconcile()
    assert calls == [("turn_off", ENTITY["charge_switch"])]
    assert coordinator.decision.status == "Manual hold"
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_cheap_plug_in_autostart_is_not_stopped(hass):
    coordinator, calls = await start_unplugged(hass, seed={"price": "0.08"})
    hass.states.async_set(ENTITY["cable_sensor"], "on")
    await hass.async_block_till_done()
    await car_starts_charging(hass)
    assert coordinator.manual_hold_until is None
    await coordinator.async_reconcile()
    assert calls == []
    assert coordinator.decision.desired is True
    assert coordinator.owns_charge is True
    await coordinator.async_shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("first,second", [("charge_switch", "charging_sensor"), ("charging_sensor", "charge_switch")])
async def test_delayed_charging_feedback_after_stop_is_not_a_second_start(hass, first, second):
    coordinator, calls = await start_unplugged(hass, seed={"price": "0.30"})
    hass.states.async_set(ENTITY["cable_sensor"], "on")
    await hass.async_block_till_done()
    hass.states.async_set(ENTITY[first], "on")
    await hass.async_block_till_done()
    await coordinator.async_reconcile()
    assert calls == [("turn_off", ENTITY["charge_switch"])]
    hass.states.async_set(ENTITY[first], "off")
    await hass.async_block_till_done()
    # The other source's first report arrives after the first reports stopping.
    hass.states.async_set(ENTITY[second], "on")
    await hass.async_block_till_done()
    assert coordinator.manual_hold_until is None
    await coordinator.async_reconcile()
    assert coordinator.decision.desired is False
    # A further start from the same source is a real repeat, so it still holds.
    hass.states.async_set(ENTITY[second], "off")
    await hass.async_block_till_done()
    hass.states.async_set(ENTITY[second], "on")
    await hass.async_block_till_done()
    assert coordinator.manual_hold_until is not None
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_released_tariff_starts_do_not_create_hold_on_return_to_agile(hass):
    coordinator, calls = await start_unplugged(
        hass, seed={"price": "0.30", "rate_tariff": "INTELLIGENT"}
    )
    hass.states.async_set(ENTITY["cable_sensor"], "on")
    await hass.async_block_till_done()
    await coordinator.async_reconcile()
    await car_starts_charging(hass)
    await car_stops_charging(hass)
    await car_starts_charging(hass)
    assert coordinator.manual_hold_until is None
    assert calls == []
    rate = hass.states.get(ENTITY["rate_entity"])
    hass.states.async_set(ENTITY["rate_entity"], rate.state, {**rate.attributes, "tariff": "AGILE"})
    await hass.async_block_till_done()
    await coordinator.async_reconcile()
    assert calls == [("turn_off", ENTITY["charge_switch"])]
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_delayed_other_source_after_restart_is_not_a_repeat(hass):
    coordinator, calls = await start_unplugged(hass, seed={"price": "0.30"})
    hass.states.async_set(ENTITY["cable_sensor"], "on")
    await hass.async_block_till_done()
    hass.states.async_set(ENTITY["charge_switch"], "on")
    await hass.async_block_till_done()
    await coordinator.async_reconcile()
    hass.states.async_set(ENTITY["charge_switch"], "off")
    await hass.async_block_till_done()
    entry = coordinator.entry
    await coordinator.async_shutdown()
    restored = coordinator_module.EVCoordinator(hass, entry)
    await restored.async_initialize()
    hass.states.async_set(ENTITY["charging_sensor"], "on")
    await hass.async_block_till_done()
    assert restored.manual_hold_until is None
    hass.states.async_set(ENTITY["charging_sensor"], "off")
    await hass.async_block_till_done()
    hass.states.async_set(ENTITY["charging_sensor"], "on")
    await hass.async_block_till_done()
    assert restored.manual_hold_until is not None
    await restored.async_shutdown()


@pytest.mark.asyncio
async def test_tariff_change_before_reconcile_cannot_record_external_starts(hass):
    coordinator, calls = await start_unplugged(hass, seed={"price": "0.30"})
    hass.states.async_set(ENTITY["cable_sensor"], "on")
    await hass.async_block_till_done()
    await coordinator.async_reconcile()
    await car_starts_charging(hass)
    await car_stops_charging(hass)
    rate = hass.states.get(ENTITY["rate_entity"])
    hass.states.async_set(ENTITY["rate_entity"], rate.state, {**rate.attributes, "tariff": "INTELLIGENT"})
    await car_starts_charging(hass)
    assert coordinator.manual_hold_until is None
    assert coordinator.unwanted_start_at is None
    await coordinator.async_reconcile()
    assert coordinator.decision.desired is None
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_restart_on_other_tariff_clears_saved_repeat_history(hass):
    coordinator, calls = await start_unplugged(hass, seed={"price": "0.30"})
    hass.states.async_set(ENTITY["cable_sensor"], "on")
    await hass.async_block_till_done()
    await car_starts_charging(hass)
    await car_stops_charging(hass)
    assert coordinator.unwanted_start_at is not None
    entry = coordinator.entry
    await coordinator.async_shutdown()
    rate = hass.states.get(ENTITY["rate_entity"])
    hass.states.async_set(ENTITY["rate_entity"], rate.state, {**rate.attributes, "tariff": "INTELLIGENT"})
    restored = coordinator_module.EVCoordinator(hass, entry)
    await restored.async_initialize()
    assert restored.unwanted_start_at is None
    assert restored.unwanted_start_sources == set()
    hass.states.async_set(ENTITY["rate_entity"], rate.state, rate.attributes)
    await hass.async_block_till_done()
    await restored.async_reconcile()
    await car_starts_charging(hass)
    assert restored.manual_hold_until is None
    await restored.async_shutdown()
