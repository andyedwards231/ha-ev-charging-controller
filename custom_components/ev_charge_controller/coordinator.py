"""Read connected entities, maintain intent and reconcile one command path."""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import timedelta

from homeassistant.core import callback
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import DEFAULTS, DOMAIN, ENTITY_KEYS, MODES
from .planner import RateSlot, plan_charging
from .policy import Decision, Intent, Snapshot, decide
from .provider import (
    apply_free_session,
    boolean,
    fresh,
    number,
    published_rates_report,
    rate_snapshot,
    timestamp,
)

_LOGGER = logging.getLogger(__name__)


def _continuous_coverage_end(rates, now):
    """Return the end of published price coverage continuous from ``now``."""
    ordered = sorted(rates, key=lambda slot: slot.start)
    coverage_end = next(
        (slot.end for slot in ordered if slot.start <= now < slot.end), None
    )
    if coverage_end is None:
        return None
    for slot in ordered:
        if slot.start <= coverage_end < slot.end:
            coverage_end = slot.end
        elif slot.start > coverage_end:
            break
    return coverage_end


class EVCoordinator(DataUpdateCoordinator):
    """One serialized controller per charging switch; no direct cloud requests."""

    def __init__(self, hass, entry):
        super().__init__(hass, _LOGGER, name=entry.title, config_entry=entry)
        self.entry = entry
        self.preferences = {**DEFAULTS, **entry.options}
        self.options_baseline = dict(entry.options)
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.intent")
        self.lock = asyncio.Lock()
        self.plan = None
        self.decision = Decision(None, "Starting", "Waiting for connected entities.")
        self.snapshot = None
        self.boost_until = None
        self.boost_target = None
        self.manual_hold_until = None
        self.unwanted_start_at = None
        self.unwanted_start_open = False
        self.unwanted_start_sources = set()
        self.preconditioning_until = None
        self.preconditioning_seen = False
        self.maintenance_satisfied = False
        self.request_completed = False
        self.owns_charge = False
        self.pending = None
        self.last_command = None
        self.command_error = None
        self.learned_power = None
        self.learned_power_ratio = None
        self._forecast_cache_signature = None
        self._forecast_cache_at = None
        self._forecast_cache_data = None
        self._schedule_cache_signature = None
        self._schedule_cache_data = None
        self._schedule_cache_at = None
        self.charging_since = None
        self.power_samples = 0
        self.unsubscribers = []
        self.boundary_cancel = None
        self.debounce_cancel = None
        self.closed = False
        self.tasks = set()
        self.data = {}

    async def async_initialize(self):
        saved = await self.store.async_load() or {}
        baseline = saved.get("options_baseline", {})
        for key, value in saved.get("preferences", {}).items():
            if key in DEFAULTS or key == "deadline":
                if self.entry.options.get(key, DEFAULTS.get(key)) == baseline.get(
                    key, DEFAULTS.get(key)
                ):
                    self.preferences[key] = value
        for name in (
            "boost_until",
            "manual_hold_until",
            "preconditioning_until",
            "unwanted_start_at",
        ):
            setattr(self, name, timestamp(saved.get(name)))
        for name in (
            "boost_target",
            "maintenance_satisfied",
            "request_completed",
            "preconditioning_seen",
            "learned_power",
            "learned_power_ratio",
            "unwanted_start_open",
        ):
            if name in saved:
                setattr(self, name, saved[name])
        self.unwanted_start_sources = set(saved.get("unwanted_start_sources", []))
        if any(
            self.entry.options.get(key, DEFAULTS.get(key)) != baseline.get(key, DEFAULTS.get(key))
            for key in ("mode", "target_percent", "deadline")
        ):
            self.request_completed = self.maintenance_satisfied = False
        # Ownership and old command attempts are deliberately not restored.
        ids = [self.entry.data[key] for key in ENTITY_KEYS if self.entry.data.get(key)]
        self.unsubscribers.append(
            async_track_state_change_event(self.hass, ids, self._state_changed)
        )
        self.unsubscribers.append(
            async_track_time_interval(self.hass, self._tick, timedelta(seconds=30))
        )
        await self.async_reconcile()

    @callback
    def _tick(self, _now):
        self._schedule()

    @callback
    def _schedule(self):
        if self.closed:
            return
        if self.debounce_cancel:
            self.debounce_cancel.cancel()
        self.debounce_cancel = self.hass.loop.call_later(0.2, self._run)

    @callback
    def _run(self):
        self.debounce_cancel = None
        if not self.closed:
            task = self.hass.async_create_task(self.async_reconcile())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    @callback
    def _state_changed(self, event):
        new = event.data.get("new_state")
        old = event.data.get("old_state")
        entity_id = event.data["entity_id"]
        now = dt_util.utcnow()
        if entity_id == self.entry.data.get("rate_entity"):
            tariff = (
                new.attributes.get(self.entry.data.get("tariff_attribute", "tariff"))
                if new
                else None
            )
            if (
                not tariff
                or self.entry.data.get("tariff_match", "AGILE").casefold()
                not in str(tariff).casefold()
            ):
                self.pending = None
                self.owns_charge = False
                self._clear_start_repeat()
        if entity_id == self.entry.data.get("cable_sensor") and boolean(new) is False:
            self._clear_start_repeat()
        if entity_id == self.entry.data.get("charge_switch") and old and new:
            old_value, value = boolean(old), boolean(new)
            expected = self.pending and self.pending["desired"] == value
            if old_value is False and value is True and not expected:
                # First unrequested start is stopped. A second start within
                # two minutes is someone overriding that stop.
                if self._register_unwanted_start(now, "switch"):
                    self._begin_manual_hold(now)
                elif self.pending and self.pending["desired"] is False:
                    self.pending["next_attempt"] = now
            elif (
                old_value is True
                and value is False
                and not expected
                and self.decision.desired is True
                # Tessie can optimistically report on, then poll the old off
                # state before charging starts. Keep awaiting confirmation;
                # an explicit HA user action still takes effect immediately.
                and (self.pending is None or new.context.user_id is not None)
                and self._external_change_context()
            ):
                self._begin_manual_hold(now)
            if value is False:
                self._close_start_session()
        if entity_id == self.entry.data.get("charging_sensor") and old and new:
            was_charging, charging_now = boolean(old), boolean(new)
            if was_charging is False and charging_now is True:
                if self._register_unwanted_start(now, "charging"):
                    self._begin_manual_hold(now)
            elif charging_now is False:
                self._close_start_session()
        self._schedule()

    def _managed_tariff(self):
        """Use the current tariff, including changes not yet reconciled."""
        rate = self._state("rate_entity")
        tariff = rate.attributes.get(self.entry.data.get("tariff_attribute", "tariff")) if rate else None
        match = self.entry.data.get("tariff_match", "AGILE")
        return bool(tariff and match and match.casefold() in str(tariff).casefold())

    def _external_change_context(self):
        """Whether a manual switch change is allowed to inhibit control."""
        return bool(
            self.snapshot
            and self.snapshot.home is True
            and self.preferences["automatic_control"]
            and self._managed_tariff()
            and self.preferences["external_change_policy"] == "respect"
            and not self._completion()
            and not self.snapshot.preconditioning
        )

    def _can_track_external_start(self):
        """Whether an unrequested charge start should count toward an override."""
        if not self._external_change_context() or self.decision.desired is True:
            return False
        if self.manual_hold_until is not None and self.snapshot.now < self.manual_hold_until:
            return False
        return boolean(self._state("cable_sensor")) is True

    def _register_unwanted_start(self, now, source):
        """Record a charge start. True when it repeats inside the override window."""
        if not self._can_track_external_start():
            return False
        window = timedelta(minutes=self.preferences["repeat_start_minutes"])
        within_window = (
            self.unwanted_start_at is not None
            and timedelta(0) <= now - self.unwanted_start_at < window
        )
        # Switch and charging feedback can arrive in either order, even after
        # the stop acknowledgement. Require a repeat from the same source;
        # the first report from the other source belongs to the same attempt.
        if within_window and source not in self.unwanted_start_sources:
            self.unwanted_start_sources.add(source)
            self._persist()
            return False
        if self.unwanted_start_open:
            return False
        repeated = within_window
        if repeated:
            self.unwanted_start_at = None
            self.unwanted_start_open = False
            self.unwanted_start_sources.clear()
        else:
            self.unwanted_start_at = now
            self.unwanted_start_open = True
            self.unwanted_start_sources = {source}
        self._persist()
        return repeated

    def _close_start_session(self):
        """The current start has stopped, so a later start is a new attempt."""
        if self.unwanted_start_open:
            self.unwanted_start_open = False
            self._persist()

    def _clear_start_repeat(self):
        """Unplugging ends the repeat window. The next plug-in starts fresh."""
        if self.unwanted_start_at is not None or self.unwanted_start_open:
            self.unwanted_start_at = None
            self.unwanted_start_open = False
            self.unwanted_start_sources.clear()
            self._persist()

    def _begin_manual_hold(self, now):
        if not self._external_change_context():
            return
        self.manual_hold_until = now + timedelta(minutes=self.preferences["manual_hold_minutes"])
        self.pending = None
        self.owns_charge = False
        self.unwanted_start_at = None
        self.unwanted_start_open = False
        self.unwanted_start_sources.clear()
        self._persist()

    def _state(self, key):
        entity_id = self.entry.data.get(key)
        return self.hass.states.get(entity_id) if entity_id else None

    def _completion(self):
        state = self._state("completion_entity")
        return bool(
            state
            and fresh(state, dt_util.utcnow(), self.preferences["stale_minutes"])
            and state.state == self.entry.data.get("completion_state", "complete")
        )

    def _home(self, now):
        location = self._state("location_entity")
        zone = self._state("home_zone")
        if (
            location is None
            or zone is None
            or not fresh(location, now, self.preferences["stale_minutes"])
        ):
            return None
        if location.state in ("unknown", "unavailable"):
            return None
        if self.entry.data.get("home_zone") == "zone.home":
            return location.state == "home"
        return location.state.casefold() == str(zone.attributes.get("friendly_name", "")).casefold()

    def _intent(self):
        values = {
            key: self.preferences[key]
            for key in Intent.__dataclass_fields__
            if key in self.preferences
        }
        values.update(
            deadline=timestamp(self.preferences.get("deadline")),
            boost_until=self.boost_until,
            boost_target=self.boost_target,
            manual_hold_until=self.manual_hold_until,
            tariff_match=self.entry.data.get("tariff_match", "AGILE"),
            maintenance_satisfied=self.maintenance_satisfied,
        )
        return Intent(**values)

    def _read(self, now):
        opts = self.preferences
        rate_state = self._state("rate_entity")
        price, valid, start, end = rate_snapshot(
            rate_state, now, self.entry.data.get("price_unit", "GBP/kWh")
        )
        tariff = (
            rate_state.attributes.get(self.entry.data.get("tariff_attribute", "tariff"))
            if rate_state
            else None
        )
        tariff = str(tariff) if tariff else None
        soc_state = self._state("soc_entity")
        soc = number(soc_state) if fresh(soc_state, now, opts["stale_minutes"]) else None
        if soc is not None and not 0 <= soc <= 100:
            soc = None
        limit_state = self._state("car_limit_entity")
        limit = number(limit_state) if fresh(limit_state, now, opts["stale_minutes"]) else None
        if limit is not None and not 0 <= limit <= 100:
            limit = None
        charging_state = self._state("charging_sensor")
        charging = (
            boolean(charging_state) if fresh(charging_state, now, opts["stale_minutes"]) else None
        )
        cable_state = self._state("cable_sensor")
        connected = boolean(cable_state) if fresh(cable_state, now, opts["stale_minutes"]) else None
        switch_state = self._state("charge_switch")
        switch_on = (
            boolean(switch_state) if fresh(switch_state, now, opts["stale_minutes"]) else None
        )
        precondition = self._state("preconditioning_entity")
        preconditioning = boolean(precondition) is True and fresh(
            precondition, now, opts["stale_minutes"]
        )
        if preconditioning and not self.preconditioning_seen:
            self.preconditioning_until = now + timedelta(minutes=opts["preconditioning_minutes"])
            self.preconditioning_seen = True
            self._persist()
        elif not preconditioning and (precondition is None or boolean(precondition) is False):
            self.preconditioning_seen = False
            self.preconditioning_until = None
        current = self._state("current_entity")
        amps = number(current) if fresh(current, now, opts["stale_minutes"]) else None
        power = opts["fixed_power_kw"]
        power_valid = True
        if self.entry.data.get("current_entity"):
            power = amps * opts["voltage"] / 1000 if amps is not None and amps > 0 else 0
            power_valid = power > 0
        measured_state = self._state("power_entity")
        measured = (
            number(measured_state) if fresh(measured_state, now, opts["stale_minutes"]) else None
        )
        if measured is not None:
            unit = measured_state.attributes.get("unit_of_measurement")
            if unit == "W":
                measured /= 1000
            elif unit != "kW":
                measured = None
        if charging and not preconditioning:
            self.charging_since = self.charging_since or now
        else:
            self.charging_since = None
        if (
            opts.get("learn_power")
            and measured is not None
            and measured >= 0.5
            and power > 0
            and self.charging_since
            and now - self.charging_since >= timedelta(minutes=5)
        ):
            sample = min(measured, power)
            self.learned_power = (
                sample if self.learned_power is None else 0.9 * self.learned_power + 0.1 * sample
            )
            ratio = sample / power
            self.learned_power_ratio = (
                ratio
                if self.learned_power_ratio is None
                else 0.9 * self.learned_power_ratio + 0.1 * ratio
            )
            self.power_samples += 1
        if opts.get("learn_power") and self.learned_power_ratio is not None and power > 0:
            # Apply the learned fraction to today's configured current. Keeping
            # an old absolute kW value here would cap a later increase in amps.
            power *= max(0.1, min(1.0, self.learned_power_ratio))
        free = self._state("free_session_entity")

        def calendar_time(value):
            parsed = dt_util.parse_datetime(value) if isinstance(value, str) else value
            return dt_util.as_utc(parsed) if parsed else None

        free_start = calendar_time(free.attributes.get("start_time")) if free else None
        free_end = calendar_time(free.attributes.get("end_time")) if free else None
        free_valid = fresh(free, now, opts["stale_minutes"]) if free else False
        free_active = bool(
            free_valid
            and free.state == "on"
            and free_start
            and free_end
            and free_start <= now < free_end
        )
        rates_error = None
        rates_warning = None
        try:
            rates, warnings, rates_complete = published_rates_report(
                [self._state("today_rates_entity"), self._state("tomorrow_rates_entity")],
                tariff,
                self.entry.data.get("price_unit", "GBP/kWh"),
            )
            rates_warning = "; ".join(warnings) if warnings else None
            if any(warning.startswith("Today rates are invalid") for warning in warnings):
                rates_error = "Today's published rates are malformed; target charging is suspended until refreshed rates arrive."
            # A changed live price must never leave an old selected slot actionable.
            current_slots = [slot for slot in rates if slot.start <= now < slot.end]
            if valid and any(abs(slot.price - price) > 0.000001 for slot in current_slots):
                rates_error = (
                    "Current price and published forecast disagree; waiting for refreshed rates."
                )
            # The valid current period remains usable when event forecasts lag.
            if valid and start and end and not any(slot.start <= now < slot.end for slot in rates):
                rates = tuple(
                    sorted((*rates, RateSlot(start, end, price)), key=lambda slot: slot.start)
                )
            rates = apply_free_session(
                rates, free_start if free_valid else None, free_end if free_valid else None
            )
        except (TypeError, ValueError) as exc:
            rates, rates_warning, rates_complete, rates_error = (), str(exc), False, str(exc)
        snapshot = Snapshot(
            now=now,
            tariff=tariff,
            home=self._home(now),
            connected=connected,
            switch_on=switch_on,
            charging=charging,
            soc=soc,
            car_limit=limit,
            complete=self._completion(),
            price=(min(price, 0.0) if price is not None else 0.0) if free_active else price,
            price_valid=valid or free_active,
            free_session=free_active,
            preconditioning=preconditioning,
            preconditioning_until=self.preconditioning_until,
            vehicle_valid=charging is not None,
            owns_charge=self.owns_charge,
            effective_power_kw=power * opts["efficiency"] / (1 + opts["planning_margin"]),
        )
        return snapshot, rates, power, power_valid, end, free_end, rates_error, rates_warning, rates_complete, amps

    def _control_decision(self, snap, intent, plan, power_valid, rates_error):
        """Apply the same control rules when planning and before dispatch."""
        decision = decide(snap, intent, plan)
        # Completion is the car's explicit state, not absence of current.
        if snap.complete and decision.desired is True and not snap.preconditioning:
            decision = Decision(
                False,
                "Car charge complete",
                "The car reports charging complete.",
                clear_boost=True,
            )
        if (
            intent.mode in ("deadline", "flexible")
            and (rates_error or not power_valid)
            and not self.boost_until
            and not (snap.preconditioning and decision.desired is True)
            and decision.desired is not None
        ):
            decision = Decision(
                False if snap.owns_charge and snap.switch_on else None,
                "Planner unavailable",
                rates_error or "Charging current is unavailable or zero.",
                problem=True,
            )
        if (
            self.request_completed
            and intent.mode == "deadline"
            and decision.desired is not None
            and (not self.boost_until or decision.clear_boost)
            and not (snap.preconditioning and decision.desired is True)
        ):
            decision = Decision(
                False if snap.home is True and snap.connected is True else None,
                "Target reached",
                "The deadline request is complete; change the request to charge again.",
                clear_boost=decision.clear_boost,
            )
        return decision

    async def async_reconcile(self):
        async with self.lock:
            if self.closed:
                return
            now = dt_util.utcnow()
            if not self._managed_tariff():
                self._clear_start_repeat()
            (
                snap,
                rates,
                power,
                power_valid,
                price_end,
                free_end,
                rates_error,
                rates_warning,
                rates_complete,
                amps,
            ) = self._read(now)
            if snap.connected is False:
                self.boost_until = self.boost_target = self.manual_hold_until = None
                self.unwanted_start_at = None
                self.unwanted_start_open = False
                self.unwanted_start_sources.clear()
                self.owns_charge = False
                self.pending = None
                self._persist()
            elif self.boost_until and self.boost_until <= now:
                self.boost_until = None
                self.boost_target = None
                self._persist()
            intent = self._intent()
            previous = self.plan.slots if self.plan else ()
            self.plan = None
            if intent.mode in ("deadline", "flexible") and snap.soc is not None and power_valid:
                try:
                    self.plan = plan_charging(
                        rates,
                        now,
                        intent.target_percent,
                        snap.soc,
                        self.preferences["capacity_kwh"],
                        power,
                        self.preferences["efficiency"],
                        self.preferences["planning_margin"],
                        intent.deadline if intent.mode == "deadline" else None,
                        intent.max_cheap_rate / 100
                        if intent.mode == "flexible" or intent.hard_price_ceiling
                        else None,
                        snap.car_limit,
                        previous,
                    )
                except ValueError as exc:
                    rates_error = str(exc)
            if intent.mode == "deadline" and intent.deadline is not None:
                coverage_end = _continuous_coverage_end(rates, now)
                deadline_covered = coverage_end is not None and coverage_end >= intent.deadline
                rates_complete = deadline_covered and rates_error is None
                if not deadline_covered:
                    coverage_text = (
                        f"Published prices currently cover through {coverage_end.isoformat()}"
                        if coverage_end
                        else "Published prices do not cover the current time"
                    )
                    deadline_warning = (
                        f"{coverage_text}; the deadline is later. The plan uses available prices "
                        "and will replan when new rates arrive."
                    )
                    rates_warning = "; ".join(
                        part for part in (rates_warning, deadline_warning) if part
                    )
            planner_reached = snap.soc is not None and snap.soc >= intent.target_percent
            if intent.mode == "flexible" and planner_reached:
                self.maintenance_satisfied = True
                self._persist()
            elif (
                intent.mode == "flexible"
                and snap.soc is not None
                and snap.soc < intent.target_percent - intent.maintenance_margin
            ):
                self.maintenance_satisfied = False
            if intent.mode == "deadline" and planner_reached:
                self.request_completed = True
                self._persist()
            decision = self._control_decision(snap, intent, self.plan, power_valid, rates_error)
            if decision.clear_boost and self.boost_until:
                self.boost_until = None
                self.boost_target = None
                self._persist()
            if rates_warning:
                decision = Decision(
                    decision.desired,
                    decision.status,
                    f"{decision.reason} Price coverage: {rates_warning}",
                    decision.problem,
                    decision.clear_boost,
                    decision.target_reached,
                )
            self.snapshot, self.decision = snap, decision
            # A start seen before this decision is not unwanted when charging is allowed.
            if decision.desired is True:
                self._clear_start_repeat()
            if intent.monitoring_only or not intent.automatic_control or decision.desired is None:
                self.pending = None
                self.owns_charge = False
            else:
                await self._actuate(decision, snap)
            self._publish(now, power, rates_error, rates_warning, rates_complete, rates, amps)
            boundaries = [
                price_end,
                free_end,
                intent.deadline,
                self.boost_until,
                self.manual_hold_until,
                self.preconditioning_until,
            ]
            if self.plan:
                boundaries.extend(
                    point for slot in self.plan.slots for point in (slot.start, slot.end)
                )
            if self.pending:
                boundaries.append(self.pending["next_attempt"])
            self._arm_boundary(now, boundaries)

    async def _actuate(self, decision, snap):
        desired = decision.desired
        confirmed = snap.switch_on == desired and (
            snap.charging is True or snap.complete or snap.preconditioning
            if desired
            else snap.charging is False
        )
        if confirmed:
            if self.pending and self.pending["desired"] == desired:
                self.last_command["result"] = "confirmed"
            self.owns_charge = desired
            self.pending = None
            self.command_error = None
            return
        # Expensive-period/target stops apply even to adopted charging on Agile.
        # An already enabled switch with no power still needs a bounded retry.
        if self.pending and self.pending["desired"] != desired:
            self.pending = None
        if self.pending is None:
            self.pending = {"desired": desired, "attempts": 0, "next_attempt": snap.now}
        pending = self.pending
        if snap.now < pending["next_attempt"]:
            return
        if pending["attempts"] >= 1 + self.preferences["max_retries"]:
            self.command_error = "Charging did not confirm after the bounded command attempts. Resume or replan to retry."
            return
        # Re-read authority immediately before dispatch; no cloud action is made
        # by tests, which register only mocked switch services.
        (
            latest,
            latest_rates,
            latest_power,
            latest_power_valid,
            _,
            _,
            latest_error,
            _,
            _,
            _,
        ) = self._read(dt_util.utcnow())
        latest_intent = self._intent()
        latest_plan = self.plan
        if (
            latest_intent.mode in ("deadline", "flexible")
            and latest.soc is not None
            and desired is True
            and not self.boost_until
            and not latest.preconditioning
        ):
            if not latest_power_valid or latest_error:
                self.pending = None
                return
            latest_plan = plan_charging(
                latest_rates,
                latest.now,
                latest_intent.target_percent,
                latest.soc,
                self.preferences["capacity_kwh"],
                latest_power,
                self.preferences["efficiency"],
                self.preferences["planning_margin"],
                latest_intent.deadline if latest_intent.mode == "deadline" else None,
                latest_intent.max_cheap_rate / 100
                if latest_intent.mode == "flexible" or latest_intent.hard_price_ceiling
                else None,
                latest.car_limit,
                latest_plan.slots if latest_plan else (),
            )
        latest_decision = self._control_decision(
            latest, latest_intent, latest_plan, latest_power_valid, latest_error
        )
        if (
            latest_intent.monitoring_only
            or not latest_intent.automatic_control
            or latest_decision.desired != desired
            or latest.home is not True
            or latest.connected is not True
        ):
            self.pending = None
            return
        pending["attempts"] += 1
        pending["next_attempt"] = snap.now + timedelta(
            seconds=self.preferences["retry_seconds"] * min(4, pending["attempts"])
        )
        self.last_command = {
            "desired": desired,
            "attempt": pending["attempts"],
            "at": snap.now.isoformat(),
            "result": "requested",
        }
        try:
            async with asyncio.timeout(30):
                await self.hass.services.async_call(
                    "switch",
                    "turn_on" if desired else "turn_off",
                    {"entity_id": self.entry.data["charge_switch"]},
                    blocking=True,
                )
        except Exception as exc:  # HA service errors remain visible and bounded.
            self.command_error = str(exc)
            self.last_command["result"] = "failed"

    def _forecast_signature(
        self, now, rates, power, amps, rates_complete, rates_warning, rates_error
    ):
        rate_state = tuple(
            (
                slot.start,
                slot.end,
                slot.price,
                "active" if slot.start <= now < slot.end else "future" if slot.start > now else "past",
            )
            for slot in rates
        )
        deadline = timestamp(self.preferences.get("deadline"))
        plan_slots = tuple(
            (
                slot.price,
                "active" if slot.start <= now < slot.end else "future" if slot.start > now else "past",
            )
            for slot in (self.plan.slots if self.plan else ())
        )
        return (
            rate_state,
            plan_slots,
            self.snapshot.soc,
            self.snapshot.car_limit,
            self.snapshot.price,
            power,
            amps,
            self.snapshot.charging,
            rates_complete,
            rates_warning,
            self.preferences.get("mode"),
            self.preferences.get("target_percent"),
            self.preferences.get("capacity_kwh"),
            self.preferences.get("efficiency"),
            self.preferences.get("planning_margin"),
            self.preferences.get("max_cheap_rate"),
            self.preferences.get("hard_price_ceiling"),
            deadline,
            bool(deadline and now >= deadline),
            self.plan.completion if self.plan else None,
            self.request_completed,
            self.maintenance_satisfied,
            self._managed_tariff(),
            rates_error,
        )

    def _forecast(self, now, rates, power, amps, rates_complete, rates_warning, rates_error=None):
        """Return a cached dashboard projection, refreshing at meaningful changes."""
        signature = self._forecast_signature(
            now, rates, power, amps, rates_complete, rates_warning, rates_error
        )
        active = self.snapshot.charging is True
        if (
            signature == self._forecast_cache_signature
            and self._forecast_cache_data is not None
            and self._forecast_cache_at is not None
            and (not active or now - self._forecast_cache_at < timedelta(minutes=5))
        ):
            return self._forecast_cache_data

        forecast = self._build_forecast(now, rates, power, rates_complete, rates_error)
        self._forecast_cache_signature = signature
        self._forecast_cache_at = now
        self._forecast_cache_data = forecast
        return forecast

    def _build_forecast(self, now, rates, power, rates_complete, rates_error=None):
        """Build a dashboard projection without changing the charging decision."""
        horizon = now + timedelta(days=7)
        in_horizon = [slot for slot in rates if slot.end > now and slot.start < horizon]
        rates_data = [
            {
                "start": max(now, slot.start).isoformat(),
                "end": min(horizon, slot.end).isoformat(),
                "price_pence": round(slot.price * 100, 4),
            }
            for slot in in_horizon[:400]
        ]
        if rates_error:
            return {
                "rates": rates_data,
                "forecast_schedule": [],
                "forecast_series": [],
                "forecast_soc": None,
                "forecast_cost": None,
                "forecast_grid_energy_kwh": None,
                "forecast_shortfall_kwh": None,
                "forecast_completion": None,
                "forecast_target": None,
                "forecast_available": False,
                "forecast_basis": f"Forecast withheld because {rates_error}",
                "rates_complete": rates_complete,
                "forecast_horizon_end": min(
                    max((slot.end for slot in in_horizon), default=now), horizon
                ).isoformat(),
            }
        car_limit = self.snapshot.car_limit
        target = car_limit
        if target is not None and self.preferences["mode"] != "cheap_top_up":
            target = min(target, self.preferences["target_percent"])
        soc = self.snapshot.soc
        capacity = self.preferences["capacity_kwh"]
        valid_capacity = (
            isinstance(capacity, (int, float)) and math.isfinite(capacity) and capacity > 0
        )
        efficiency = self.preferences["efficiency"]
        margin = self.preferences["planning_margin"]
        valid_efficiency = (
            isinstance(efficiency, (int, float))
            and math.isfinite(efficiency)
            and 0 < efficiency <= 1
            and isinstance(margin, (int, float))
            and math.isfinite(margin)
            and margin >= 0
        )
        blocked = (
            self.preferences["mode"] != "cheap_top_up"
            and car_limit is not None
            and self.preferences["target_percent"] > car_limit
        )
        valid_soc = isinstance(soc, (int, float)) and 0 <= soc <= 100
        valid_power = isinstance(power, (int, float)) and math.isfinite(power) and power > 0
        valid_limit = isinstance(car_limit, (int, float)) and 0 <= car_limit <= 100
        if (
            not valid_limit
            or not valid_soc
            or not valid_power
            or not valid_capacity
            or not valid_efficiency
        ):
            if not valid_limit:
                reason = "Waiting for a current car charge limit."
            elif not valid_soc:
                reason = "Waiting for a fresh battery reading."
            elif not valid_power:
                reason = "Waiting for a valid charging power estimate."
            elif not valid_capacity:
                reason = "Battery capacity is invalid."
            else:
                reason = "Charging efficiency or planning margin is invalid."
            return {
                "rates": rates_data,
                "forecast_schedule": [],
                "forecast_series": [],
                "forecast_soc": None,
                "forecast_cost": None,
                "forecast_grid_energy_kwh": None,
                "forecast_shortfall_kwh": None,
                "forecast_completion": None,
                "forecast_target": target if valid_limit else None,
                "forecast_available": False,
                "forecast_basis": reason,
                "rates_complete": rates_complete,
                "forecast_horizon_end": min(
                    max((slot.end for slot in in_horizon), default=now), horizon
                ).isoformat(),
            }

        battery_kw = power * efficiency / (1 + margin)
        required = max(0.0, (target - soc) * capacity / 100)
        maintenance_active = (
            self.preferences["mode"] == "flexible"
            and self.maintenance_satisfied
            and soc >= target - max(0.0, self.preferences["maintenance_margin"])
        )
        if (self.preferences["mode"] == "deadline" and self.request_completed) or maintenance_active:
            reached = soc >= target
            coverage_end = min(max((slot.end for slot in in_horizon), default=now), horizon)
            flat_series = [{"time": now.isoformat(), "soc": round(soc, 2), "cost": 0.0}]
            if coverage_end > now:
                flat_series.append(
                    {"time": coverage_end.isoformat(), "soc": round(soc, 2), "cost": 0.0}
                )
            reason = (
                "The deadline request is complete; the forecast stays flat until the request changes."
                if self.preferences["mode"] == "deadline"
                else "Flexible maintenance is satisfied; the forecast stays flat until SOC leaves its maintenance band."
            )
            return {
                "rates": rates_data,
                "forecast_schedule": [],
                "forecast_series": flat_series,
                "forecast_soc": round(soc, 2),
                "forecast_cost": 0.0,
                "forecast_grid_energy_kwh": 0.0,
                "forecast_shortfall_kwh": round(required, 4),
                "forecast_completion": now.isoformat() if reached else None,
                "forecast_target": target,
                "forecast_available": True,
                "forecast_basis": reason,
                "rates_complete": rates_complete,
                "forecast_horizon_end": coverage_end.isoformat(),
            }
        remaining = required
        forecast_slots = []
        mode = self.preferences["mode"]
        if mode == "cheap_top_up":
            eligible = [
                slot
                for slot in in_horizon
                if slot.price * 100 <= self.preferences["max_cheap_rate"]
            ]
            eligible.sort(key=lambda slot: slot.start)
            for slot in eligible:
                if remaining <= 1e-9:
                    break
                start = max(now, slot.start)
                end = min(horizon, slot.end)
                if end <= start:
                    continue
                duration = min((end - start).total_seconds() / 3600, remaining / battery_kw)
                slot_end = start + timedelta(hours=duration)
                forecast_slots.append((start, slot_end, slot.price, duration * power))
                remaining = max(0.0, remaining - duration * battery_kw)
            basis = (
                "Observational top-up forecast: eligible published slots are followed in time order; "
                "live charging still follows the current rate and existing policy."
            )
        else:
            for slot in self.plan.slots if self.plan else ():
                start = max(now, slot.start)
                end = min(horizon, slot.end)
                if end <= start:
                    continue
                available_duration = (end - start).total_seconds() / 3600
                duration = min(available_duration, remaining / battery_kw)
                if duration <= 0:
                    break
                end = start + timedelta(hours=duration)
                grid_energy = duration * power
                forecast_slots.append((start, end, slot.price, grid_energy))
                remaining = max(0.0, remaining - duration * battery_kw)
            basis = "Projection follows the selected plan using conservative battery-side power."

        forecast_slots.sort(key=lambda item: item[0])
        battery_soc = soc
        cost = 0.0
        grid_energy = 0.0
        series = [{"time": now.isoformat(), "soc": round(battery_soc, 2), "cost": 0.0}]
        for start, end, price, energy in forecast_slots:
            duration = (end - start).total_seconds() / 3600
            energy = min(energy, duration * power)
            if start > now:
                series.append(
                    {"time": start.isoformat(), "soc": round(battery_soc, 2), "cost": round(cost, 4)}
                )
            cost += energy * price
            grid_energy += energy
            battery_soc = min(target, battery_soc + duration * battery_kw * 100 / capacity)
            series.append(
                {"time": end.isoformat(), "soc": round(battery_soc, 2), "cost": round(cost, 4)}
            )
        coverage_end = min(max((slot.end for slot in in_horizon), default=now), horizon)
        if coverage_end > now and (not series or series[-1]["time"] != coverage_end.isoformat()):
            series.append(
                {"time": coverage_end.isoformat(), "soc": round(battery_soc, 2), "cost": round(cost, 4)}
            )
        # A bounded set of rates and slots produces at most 801 points; thin
        # only if a provider publishes unusually fine-grained intervals.
        if len(series) > 400:
            stride = (len(series) - 1) / 399
            series = [series[round(index * stride)] for index in range(400)]
        achieved = max(0.0, (battery_soc - soc) * capacity / 100)
        shortfall = max(0.0, required - achieved)
        completion_at = now if required <= 1e-9 else None
        if completion_at is None and shortfall <= 1e-6 and forecast_slots:
            completion_at = forecast_slots[-1][1]
        # Missing prices make the estimate provisional, but do not invalidate
        # a target covered entirely by selected, known-price intervals.
        if blocked:
            completion_at = None
        if completion_at is None and not forecast_slots and required > 1e-9:
            basis += " No eligible published prices are available for this forecast."
        if blocked:
            basis += " The requested target is above the car charge limit."
        return {
            "rates": rates_data,
            "forecast_schedule": [
                {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "price_pence": round(price * 100, 4),
                    "grid_energy_kwh": round(energy, 4),
                }
                for start, end, price, energy in forecast_slots[:400]
            ],
            "forecast_series": series,
            "forecast_soc": round(battery_soc, 2),
            "forecast_cost": round(cost, 4),
            "forecast_grid_energy_kwh": round(grid_energy, 4),
            "forecast_shortfall_kwh": round(shortfall, 4),
            "forecast_completion": completion_at.isoformat() if completion_at else None,
            "forecast_target": target,
            "forecast_available": True,
            "forecast_basis": basis,
            "rates_complete": rates_complete,
            "forecast_horizon_end": coverage_end.isoformat(),
        }

    def _publish(self, now, power, rates_error, rates_warning, rates_complete, rates, amps):
        snap = self.snapshot
        plan = self.plan
        status, reason = self.decision.status, self.decision.reason
        if self.pending and not self.preferences["monitoring_only"]:
            status = "Charging requested" if self.pending["desired"] else "Stop requested"
            reason += " Awaiting charging feedback."
        elif (
            self.decision.desired is True
            and snap.charging
            and not self.preferences["monitoring_only"]
        ):
            status = "Charging confirmed"
        if self.command_error:
            status, reason = "Command failed", self.command_error
        if self.preferences["monitoring_only"] and not status.startswith("Monitoring:"):
            status = f"Monitoring: {status}"
        forecast = self._forecast(
            now, rates, power, amps, rates_complete, rates_warning, rates_error
        )
        signature = self._forecast_cache_signature
        if (
            signature == self._schedule_cache_signature
            and self._schedule_cache_data is not None
            and self._schedule_cache_at == self._forecast_cache_at
        ):
            schedule = self._schedule_cache_data
        else:
            schedule = [
                {
                    "start": slot.start.isoformat(),
                    "end": slot.end.isoformat(),
                    "price_pence": slot.price * 100,
                    "grid_energy_kwh": slot.energy_kwh,
                }
                for slot in plan.slots
                if slot.start < now + timedelta(days=7)
            ][:400] if plan else []
            self._schedule_cache_signature = signature
            self._schedule_cache_data = schedule
            self._schedule_cache_at = self._forecast_cache_at
        next_slot = next(
            (
                slot
                for slot in schedule
                if timestamp(slot["end"]) and timestamp(slot["end"]) > now
            ),
            None,
        )
        if (
            forecast["forecast_cost"] == 0
            and forecast["forecast_grid_energy_kwh"] == 0
            and (forecast["forecast_shortfall_kwh"] or 0) > 0
            and not (self.preferences["mode"] == "deadline" and self.request_completed)
            and not (
                self.preferences["mode"] == "flexible"
                and self.maintenance_satisfied
                and snap.soc is not None
                and snap.soc >= self.preferences["target_percent"]
                - max(0.0, self.preferences["maintenance_margin"])
            )
        ):
            no_slots_warning = "No eligible published prices are available; the forecast has no charging slots."
            rates_warning = "; ".join(
                part for part in (rates_warning, no_slots_warning) if part
            )
        if rates_warning:
            forecast["rates_warning"] = rates_warning
        self.data = {
            "status": status,
            "reason": reason,
            "problem": bool(
                self.decision.problem
                or self.command_error
                or rates_error
                or (plan and plan.shortfall_kwh > 1e-9 and not plan.provisional)
            ),
            "desired_charging": self.decision.desired,
            "observed_charging": snap.charging,
            "observed_switch": snap.switch_on,
            "connected": snap.connected,
            "home": snap.home,
            "current_amps": amps,
            "managed_tariff": self._managed_tariff(),
            "power_basis": "learned fraction of current-amp estimate"
            if self.preferences.get("learn_power") and self.learned_power_ratio is not None
            else "current amps and configured voltage"
            if self.entry.data.get("current_entity")
            else "configured fixed power",
            "owns_charge": self.owns_charge,
            "tariff": snap.tariff,
            "price_pence": snap.price * 100 if snap.price is not None else None,
            "price_valid": snap.price_valid,
            "soc": snap.soc,
            "car_limit": snap.car_limit,
            "requested_target": self.preferences["target_percent"],
            "effective_target": min(self.preferences["target_percent"], snap.car_limit)
            if snap.car_limit is not None
            else self.preferences["target_percent"],
            "vehicle_cap_known": snap.car_limit is not None,
            "next_start": timestamp(next_slot["start"]) if next_slot else None,
            "estimated_completion": timestamp(schedule[-1]["end"])
            if schedule and plan and plan.completion
            else None,
            "estimated_cost": plan.estimated_cost if plan else None,
            "required_energy": plan.required_battery_kwh if plan else None,
            "shortfall": plan.shortfall_kwh if plan else None,
            "planned_maximum_pence": plan.max_price * 100
            if plan and plan.max_price is not None
            else None,
            "provisional": plan.provisional if plan else True,
            "forecast_coverage_end": plan.coverage_end if plan else None,
            "rates_warning": forecast.get("rates_warning", rates_warning),
            "schedule": schedule,
            "last_command": self.last_command,
            "manual_hold_until": self.manual_hold_until,
            "boost_until": self.boost_until,
            "preconditioning_until": self.preconditioning_until,
            "power_kw": power,
            "learned_power_kw": self.learned_power,
            "learned_power_ratio": self.learned_power_ratio,
            "freshness_basis": "Provider timestamps where available; otherwise Home Assistant last_reported",
            **forecast,
        }
        if self.data != getattr(self, "_published_data", None):
            self._published_data = self.data
            self.async_set_updated_data(self.data)

    @callback
    def _arm_boundary(self, now, boundaries):
        if self.boundary_cancel:
            self.boundary_cancel()
            self.boundary_cancel = None
        future = [point for point in boundaries if point and point > now]
        if future:
            self.boundary_cancel = async_track_point_in_utc_time(self.hass, self._tick, min(future))

    async def async_change(self, **updates):
        if "mode" in updates and updates["mode"] not in MODES:
            raise ValueError("Invalid charging mode")
        for key in ("target_percent", "boost_target"):
            if key in updates and updates[key] is not None and not 0 <= float(updates[key]) <= 100:
                raise ValueError(f"{key} must be between 0 and 100")
        if "max_cheap_rate" in updates and not -100 <= float(updates["max_cheap_rate"]) <= 200:
            raise ValueError("Maximum cheap rate must be between -100 and 200p/kWh")
        if "deadline" in updates and updates["deadline"] is not None:
            from .config_flow import _parse_deadline

            parsed = timestamp(_parse_deadline(updates["deadline"], self.hass.config.time_zone))
            if parsed is None:
                raise ValueError("Deadline must include its timezone")
            updates["deadline"] = parsed.isoformat()
        async with self.lock:
            if any(key in updates for key in ("mode", "target_percent", "deadline")):
                self.request_completed = self.maintenance_satisfied = False
            self.preferences.update(updates)
            self.pending = None
            self.command_error = None
            if updates.get("automatic_control") is False or updates.get("monitoring_only") is True:
                self.owns_charge = False
            self._persist()
        await self.async_reconcile()

    async def async_boost(self, enabled, target=None):
        async with self.lock:
            self.boost_until = (
                dt_util.utcnow() + timedelta(hours=self.preferences["boost_hours"])
                if enabled
                else None
            )
            self.boost_target = target if enabled else None
            self.pending = None
            self.command_error = None
            self._persist()
        await self.async_reconcile()

    async def async_resume(self):
        async with self.lock:
            self.manual_hold_until = None
            self.unwanted_start_at = None
            self.unwanted_start_open = False
            self.unwanted_start_sources.clear()
            self.pending = None
            self.command_error = None
            self._persist()
        await self.async_reconcile()

    async def async_reset_learning(self):
        self.learned_power = None
        self.learned_power_ratio = None
        self.power_samples = 0
        self._persist()
        await self.async_reconcile()

    @callback
    def _persist(self):
        def snapshot():
            return {
                "preferences": dict(self.preferences),
                "options_baseline": dict(self.options_baseline),
                "boost_until": self.boost_until.isoformat() if self.boost_until else None,
                "boost_target": self.boost_target,
                "manual_hold_until": self.manual_hold_until.isoformat()
                if self.manual_hold_until
                else None,
                "unwanted_start_at": self.unwanted_start_at.isoformat()
                if self.unwanted_start_at
                else None,
                "unwanted_start_open": self.unwanted_start_open,
                "unwanted_start_sources": sorted(self.unwanted_start_sources),
                "preconditioning_until": self.preconditioning_until.isoformat()
                if self.preconditioning_until
                else None,
                "preconditioning_seen": self.preconditioning_seen,
                "maintenance_satisfied": self.maintenance_satisfied,
                "request_completed": self.request_completed,
                "learned_power": self.learned_power,
                "learned_power_ratio": self.learned_power_ratio,
            }

        self.store.async_delay_save(snapshot, 1)

    async def async_shutdown(self):
        self.closed = True
        for task in tuple(self.tasks):
            if task is not asyncio.current_task():
                task.cancel()
        if self.tasks:
            await asyncio.gather(
                *(task for task in tuple(self.tasks) if task is not asyncio.current_task()),
                return_exceptions=True,
            )
        if self.debounce_cancel:
            self.debounce_cancel.cancel()
        if self.boundary_cancel:
            self.boundary_cancel()
        for unsubscribe in self.unsubscribers:
            unsubscribe()
        self.unsubscribers.clear()
        self.pending = None
        # Persist current intent without changing the car during unload.
        await self.store.async_save(
            {
                "preferences": dict(self.preferences),
                "options_baseline": dict(self.options_baseline),
                "boost_until": self.boost_until.isoformat() if self.boost_until else None,
                "boost_target": self.boost_target,
                "manual_hold_until": self.manual_hold_until.isoformat()
                if self.manual_hold_until
                else None,
                "unwanted_start_at": self.unwanted_start_at.isoformat()
                if self.unwanted_start_at
                else None,
                "unwanted_start_open": self.unwanted_start_open,
                "unwanted_start_sources": sorted(self.unwanted_start_sources),
                "preconditioning_until": self.preconditioning_until.isoformat()
                if self.preconditioning_until
                else None,
                "preconditioning_seen": self.preconditioning_seen,
                "maintenance_satisfied": self.maintenance_satisfied,
                "request_completed": self.request_completed,
                "learned_power": self.learned_power,
                "learned_power_ratio": self.learned_power_ratio,
            }
        )
