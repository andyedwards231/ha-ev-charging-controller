"""Entity contract and config-entry lifecycle tests with memory-only storage."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from homeassistant.config_entries import SOURCE_USER, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

COMPONENT_ROOT = Path(__file__).parents[1] / "custom_components"
sys.path.insert(0, str(COMPONENT_ROOT))

import ev_charge_controller as integration  # noqa: E402
from ev_charge_controller import (  # noqa: E402
    binary_sensor,
    button,
    number,
    select,
    sensor,
    switch,
)
from ev_charge_controller import (  # noqa: E402
    calendar as calendar_platform,
)
from ev_charge_controller import (  # noqa: E402
    coordinator as coordinator_module,
)
from ev_charge_controller import (  # noqa: E402
    datetime as datetime_platform,
)
from ev_charge_controller.const import DOMAIN, PLATFORMS  # noqa: E402
from ev_charge_controller.planner import PlannedSlot  # noqa: E402

UTC = timezone.utc
ENTITY_DATA = {
    "charge_switch": "switch.test_charge",
    "charging_sensor": "binary_sensor.test_charging",
    "cable_sensor": "binary_sensor.test_cable",
    "location_entity": "device_tracker.test_car",
    "home_zone": "zone.home",
    "soc_entity": "sensor.test_soc",
    "rate_entity": "sensor.test_rate",
}


class MemoryStore:
    """Store replacement that keeps values in memory and never touches .storage."""

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
def memory_only_store(monkeypatch):
    MemoryStore.records.clear()
    monkeypatch.setattr(coordinator_module, "Store", MemoryStore)


def make_entry(entry_id="entity-contract"):
    now = datetime.now(UTC)
    return ConfigEntry(
        created_at=now,
        data=ENTITY_DATA,
        disabled_by=None,
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        entry_id=entry_id,
        minor_version=1,
        modified_at=now,
        options={},
        pref_disable_new_entities=None,
        pref_disable_polling=None,
        source=SOURCE_USER,
        subentries_data=(),
        title="Test EV",
        unique_id=f"vehicle-{entry_id}",
        version=1,
    )


class EntityCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(
            hass, logging.getLogger("entity-test"), config_entry=entry, name="Entity test"
        )
        self.entry = entry
        self.closed = False
        self.preferences = {
            "automatic_control": True,
            "monitoring_only": True,
            "hard_price_ceiling": False,
            "max_cheap_rate": 12.0,
            "target_percent": 80.0,
            "mode": "deadline",
            "deadline": (datetime.now(UTC) + timedelta(hours=4)).isoformat(),
        }
        self.boost_until = None
        self.data = {
            "status": "Waiting for a cheap slot",
            "reason": "The request is above the current rate.",
            "problem": True,
            "desired_charging": False,
            "schedule": [{"start": "2026-10-11T00:00:00+00:00", "price_pence": 5.0}],
            "provisional": True,
            "forecast_coverage_end": "2026-10-11T03:00:00+00:00",
            "requested_target": 90,
            "effective_target": 80,
            "owns_charge": False,
            "price_valid": True,
            "soc": 60,
            "last_command": None,
            "estimated_cost": 1.23,
            "required_energy": 12.5,
            "shortfall": 0.5,
            "planned_maximum_pence": 8.0,
        }
        self.plan = SimpleNamespace(
            slots=(
                PlannedSlot(
                    datetime(2026, 10, 11, 0, tzinfo=UTC),
                    datetime(2026, 10, 11, 1, tzinfo=UTC),
                    0.05,
                    7.0,
                ),
                PlannedSlot(
                    datetime(2026, 10, 11, 2, tzinfo=UTC),
                    datetime(2026, 10, 11, 3, tzinfo=UTC),
                    0.08,
                    7.0,
                ),
            ),
            provisional=True,
        )
        self.async_change = AsyncMock()
        self.async_boost = AsyncMock()
        self.async_resume = AsyncMock()
        self.async_reset_learning = AsyncMock()


async def collect_platform(hass, entry, platform):
    entities = []
    await platform.async_setup_entry(hass, entry, entities.extend)
    return entities


@pytest.mark.asyncio
async def test_sensor_status_and_plan_match_dashboard_contract(hass):
    entry = make_entry()
    entry.runtime_data = EntityCoordinator(hass, entry)
    entities = await collect_platform(hass, entry, sensor)
    by_key = {entity.key: entity for entity in entities}

    assert by_key["status"].native_value == "Waiting for a cheap slot"
    assert by_key["status"].extra_state_attributes == {
        key: value
        for key, value in entry.runtime_data.data.items()
        if key
        not in ("status", "schedule", "rates", "forecast_schedule", "forecast_series")
        and (not key.startswith("forecast_") or key == "forecast_coverage_end")
    }
    assert by_key["estimated_cost"].native_value == 1.23
    assert by_key["estimated_cost"].native_unit_of_measurement == "GBP"
    assert by_key["required_energy"].native_unit_of_measurement == "kWh"
    assert by_key["planned_maximum_pence"].native_unit_of_measurement == "p/kWh"
    assert by_key["next_start"].device_class == "timestamp"

    plan = by_key["plan"]
    assert plan.native_value == 1  # One upcoming interval in the dashboard data.
    assert plan.extra_state_attributes["schedule"] == entry.runtime_data.data["schedule"]
    assert plan.extra_state_attributes["provisional"] is True
    assert plan.extra_state_attributes["forecast_coverage_end"] == "2026-10-11T03:00:00+00:00"
    assert "forecast_schedule" in plan.extra_state_attributes
    assert "forecast_series" in plan.extra_state_attributes
    assert "forecast_completion" in plan.extra_state_attributes
    assert "forecast_available" in plan.extra_state_attributes


@pytest.mark.asyncio
async def test_binary_entities_expose_problem_and_desired_state(hass):
    entry = make_entry()
    entry.runtime_data = EntityCoordinator(hass, entry)
    entities = await collect_platform(hass, entry, binary_sensor)
    by_key = {entity.key: entity for entity in entities}
    assert by_key["problem"].is_on is True
    assert by_key["problem"].extra_state_attributes["reason"] == entry.runtime_data.data["reason"]
    assert by_key["desired_charging"].is_on is False


@pytest.mark.asyncio
async def test_switch_number_select_and_datetime_controls_call_preferences(hass):
    entry = make_entry()
    coordinator = entry.runtime_data = EntityCoordinator(hass, entry)

    switch_entities = {entity.key: entity for entity in await collect_platform(hass, entry, switch)}
    assert switch_entities["automatic_control"].is_on is True
    assert switch_entities["monitoring_only"].is_on is True
    await switch_entities["automatic_control"].async_turn_off()
    coordinator.async_change.assert_awaited_with(automatic_control=False)
    await switch_entities["monitoring_only"].async_turn_off()
    coordinator.async_change.assert_awaited_with(monitoring_only=False)
    await switch_entities["boost"].async_turn_on()
    coordinator.async_boost.assert_awaited_with(True)
    await switch_entities["hard_price_ceiling"].async_turn_on()
    coordinator.async_change.assert_awaited_with(hard_price_ceiling=True)

    numbers = {entity.key: entity for entity in await collect_platform(hass, entry, number)}
    assert numbers["max_cheap_rate"].native_value == 12.0
    assert numbers["max_cheap_rate"].native_unit_of_measurement == "p/kWh"
    assert numbers["target_percent"].native_unit_of_measurement == "%"
    await numbers["target_percent"].async_set_native_value(85)
    coordinator.async_change.assert_awaited_with(target_percent=85)

    mode = (await collect_platform(hass, entry, select))[0]
    assert mode.current_option == "deadline"
    assert mode.options == ["cheap_top_up", "deadline", "flexible"]
    await mode.async_select_option("flexible")
    coordinator.async_change.assert_awaited_with(mode="flexible")

    deadline = (await collect_platform(hass, entry, datetime_platform))[0]
    assert deadline.native_value == datetime.fromisoformat(coordinator.preferences["deadline"])
    requested_deadline = datetime(2026, 10, 12, 8, tzinfo=UTC)
    await deadline.async_set_value(requested_deadline)
    coordinator.async_change.assert_awaited_with(deadline=requested_deadline)


@pytest.mark.asyncio
async def test_buttons_replan_resume_and_reset_learning(hass):
    entry = make_entry()
    coordinator = entry.runtime_data = EntityCoordinator(hass, entry)
    buttons = {entity.key: entity for entity in await collect_platform(hass, entry, button)}
    for key in ("replan", "resume"):
        await buttons[key].async_press()
    assert coordinator.async_resume.await_count == 2
    await buttons["reset_learning"].async_press()
    coordinator.async_reset_learning.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_calendar_filters_boundaries_and_is_read_only(hass):
    entry = make_entry()
    coordinator = entry.runtime_data = EntityCoordinator(hass, entry)
    base = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=1)
    coordinator.plan = SimpleNamespace(
        slots=(
            PlannedSlot(base, base + timedelta(hours=1), 0.05, 7.0),
            PlannedSlot(base + timedelta(hours=2), base + timedelta(hours=3), 0.08, 7.0),
        ),
        provisional=True,
    )
    entity = (await collect_platform(hass, entry, calendar_platform))[0]
    assert entity.supported_features == 0
    assert entity.event.summary == "Charging at 5.00p/kWh"
    assert entity.event.description == "Planned grid energy: 7.00kWh; forecast provisional"

    query_start = base + timedelta(hours=1)
    query_end = base + timedelta(hours=3)
    events = await entity.async_get_events(hass, query_start, query_end)
    assert len(events) == 1
    assert events[0].start == base + timedelta(hours=2)
    assert events[0].end == query_end

    coordinator.plan = SimpleNamespace(
        slots=(
            PlannedSlot(query_start - timedelta(hours=1), query_start, 0.05, 1),
            PlannedSlot(query_end, query_end + timedelta(hours=1), 0.05, 1),
        ),
        provisional=False,
    )
    assert await entity.async_get_events(hass, query_start, query_end) == []


@pytest.mark.asyncio
async def test_integration_setup_and_unload_use_platform_lifecycle_and_memory_store(
    hass, monkeypatch
):
    entry = make_entry("lifecycle-test")
    forward = AsyncMock(return_value=None)
    unload = AsyncMock(return_value=True)
    manager = SimpleNamespace(async_forward_entry_setups=forward, async_unload_platforms=unload)
    monkeypatch.setattr(hass, "config_entries", manager)

    assert await integration.async_setup_entry(hass, entry) is True
    coordinator = entry.runtime_data
    assert coordinator_module.Store is MemoryStore
    assert coordinator.closed is False
    forward.assert_awaited_once_with(entry, PLATFORMS)

    assert await integration.async_unload_entry(hass, entry) is True
    assert coordinator.closed is True
    unload.assert_awaited_once_with(entry, PLATFORMS)
    assert f"{DOMAIN}.{entry.entry_id}.intent" in MemoryStore.records


@pytest.mark.asyncio
async def test_integration_setup_failure_shuts_down_coordinator(hass, monkeypatch):
    entry = make_entry("failed-setup-test")
    forward = AsyncMock(side_effect=RuntimeError("platform setup failed"))
    monkeypatch.setattr(hass, "config_entries", SimpleNamespace(async_forward_entry_setups=forward))

    with pytest.raises(RuntimeError, match="platform setup failed"):
        await integration.async_setup_entry(hass, entry)
    assert entry.runtime_data.closed is True
    assert f"{DOMAIN}.{entry.entry_id}.intent" in MemoryStore.records


@pytest.mark.asyncio
async def test_platform_setup_collectors_publish_expected_counts(hass):
    entry = make_entry()
    entry.runtime_data = EntityCoordinator(hass, entry)
    counts = {}
    for name, platform in (
        ("switch", switch),
        ("number", number),
        ("select", select),
        ("datetime", datetime_platform),
        ("sensor", sensor),
        ("binary_sensor", binary_sensor),
        ("button", button),
        ("calendar", calendar_platform),
    ):
        counts[name] = len(await collect_platform(hass, entry, platform))
    assert counts == {
        "switch": 4,
        "number": 2,
        "select": 1,
        "datetime": 1,
        "sensor": 10,
        "binary_sensor": 2,
        "button": 3,
        "calendar": 1,
    }


@pytest.mark.asyncio
async def test_failed_platform_unload_keeps_coordinator_running(hass, monkeypatch):
    entry = make_entry("failed-unload")
    monkeypatch.setattr(
        hass,
        "config_entries",
        SimpleNamespace(
            async_forward_entry_setups=AsyncMock(),
            async_unload_platforms=AsyncMock(return_value=False),
        ),
    )
    await integration.async_setup_entry(hass, entry)
    assert await integration.async_unload_entry(hass, entry) is False
    assert entry.runtime_data.closed is False
    await entry.runtime_data.async_shutdown()
