"""Standard-library tests for the pure EV charging policy."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

POLICY_PATH = Path(__file__).parents[1] / "custom_components" / "ev_charge_controller" / "policy.py"
SPEC = importlib.util.spec_from_file_location("ev_charge_policy", POLICY_PATH)
assert SPEC and SPEC.loader
policy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = policy
SPEC.loader.exec_module(policy)

UTC = timezone.utc
NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Plan:
    slots: tuple[Slot, ...] = ()
    required_battery_kwh: float = 0.0
    shortfall_kwh: float = 0.0
    provisional: bool = False


def snapshot(**overrides):
    values = dict(
        now=NOW,
        tariff="AGILE-24-10-01",
        home=True,
        connected=True,
        switch_on=False,
        charging=False,
        soc=50.0,
        car_limit=90.0,
        complete=False,
        price=0.10,
        price_valid=True,
        vehicle_valid=True,
        effective_power_kw=7.0,
    )
    values.update(overrides)
    return policy.Snapshot(**values)


def intent(**overrides):
    values = dict(monitoring_only=False)
    values.update(overrides)
    return policy.Intent(**values)


def active_plan(**overrides):
    values = dict(
        slots=(Slot(NOW - timedelta(minutes=15), NOW + timedelta(minutes=15)),),
        required_battery_kwh=12.0,
        shortfall_kwh=0.0,
        provisional=False,
    )
    values.update(overrides)
    return Plan(**values)


class PriorityTests(unittest.TestCase):
    def test_pause_manual_hold_and_non_agile_tariff_release_authority(self):
        cases = (
            (intent(automatic_control=False), snapshot(), "Paused"),
            (intent(manual_hold_until=NOW + timedelta(minutes=5)), snapshot(), "Manual hold"),
            (
                intent(tariff_match="AGILE"),
                snapshot(tariff="Intelligent Go"),
                "Released to another tariff",
            ),
            (intent(tariff_match="AGILE"), snapshot(tariff=None), "Released to another tariff"),
        )
        for chosen_intent, observed, status in cases:
            with self.subTest(status=status):
                result = policy.decide(observed, chosen_intent)
                self.assertIsNone(result.desired)
                self.assertEqual(result.status, status)

    def test_expired_manual_hold_does_not_block_control(self):
        result = policy.decide(snapshot(), intent(manual_hold_until=NOW - timedelta(seconds=1)))
        self.assertTrue(result.desired)

    def test_unknown_home_or_cable_inhibits_commands(self):
        for observed in (snapshot(home=None), snapshot(connected=None)):
            with self.subTest(observed=observed):
                result = policy.decide(observed, intent())
                self.assertIsNone(result.desired)
                self.assertTrue(result.problem)

    def test_unplug_clears_boost_and_keeps_normal_request(self):
        result = policy.decide(
            snapshot(connected=False), intent(boost_until=NOW + timedelta(hours=1))
        )
        self.assertIsNone(result.desired)
        self.assertTrue(result.clear_boost)
        self.assertEqual(result.status, "Unplugged")

    def test_away_always_releases_control(self):
        away = policy.decide(snapshot(home=False, switch_on=True, owns_charge=True), intent())
        self.assertIsNone(away.desired)
        self.assertEqual(away.status, "Away")

    def test_monitoring_preserves_proposal_but_labels_no_command_enforcement(self):
        result = policy.decide(snapshot(), intent(monitoring_only=True))
        self.assertTrue(result.desired)
        self.assertEqual(result.status, "Monitoring: Cheap rate")
        self.assertIn("would charge", result.reason)


class CheapTopUpTests(unittest.TestCase):
    def test_manual_rate_boundary_negative_rate_and_free_session(self):
        self.assertTrue(policy.decide(snapshot(price=0.12), intent(max_cheap_rate=12)).desired)
        self.assertTrue(policy.decide(snapshot(price=-0.03), intent(max_cheap_rate=12)).desired)
        free = policy.decide(snapshot(price=0.50, free_session=True), intent(max_cheap_rate=12))
        self.assertTrue(free.desired)
        self.assertEqual(free.status, "Free session")
        self.assertFalse(policy.decide(snapshot(price=0.12001), intent(max_cheap_rate=12)).desired)

    def test_missing_price_never_starts_and_stops_only_confirmed_owned_charge(self):
        idle = policy.decide(snapshot(price=None, price_valid=False), intent())
        active = policy.decide(
            snapshot(price=None, price_valid=False, switch_on=True, owns_charge=True), intent()
        )
        uncertain = policy.decide(
            snapshot(price=None, price_valid=False, home=None, switch_on=True, owns_charge=True),
            intent(),
        )
        self.assertIsNone(idle.desired)
        self.assertFalse(active.desired)
        self.assertIsNone(uncertain.desired)
        self.assertTrue(idle.problem and active.problem and uncertain.problem)

    def test_incomplete_or_invalid_inputs_do_not_start(self):
        for observed in (snapshot(vehicle_valid=False), snapshot(switch_on=None)):
            result = policy.decide(observed, intent())
            self.assertIsNone(result.desired)
            self.assertTrue(result.problem)


class BoostAndPreconditioningTests(unittest.TestCase):
    def test_boost_overrides_price_and_uses_car_limit_by_default(self):
        result = policy.decide(
            snapshot(price=0.50),
            intent(
                mode="cheap_top_up",
                max_cheap_rate=10,
                boost_until=NOW + timedelta(minutes=30),
            ),
        )
        self.assertTrue(result.desired)
        self.assertEqual(result.status, "Boosting")
        self.assertIn("90%", result.reason)

    def test_boost_respects_lower_explicit_target_and_rejects_above_car_limit(self):
        lower = policy.decide(
            snapshot(soc=69),
            intent(
                boost_until=NOW + timedelta(hours=1),
                boost_target=70,
            ),
        )
        blocked = policy.decide(
            snapshot(),
            intent(
                boost_until=NOW + timedelta(hours=1),
                boost_target=95,
            ),
        )
        self.assertTrue(lower.desired)
        self.assertIsNone(blocked.desired)
        self.assertTrue(blocked.problem)

    def test_boost_target_and_timeout_clear_then_timeout_recomputes_normal_mode(self):
        reached = policy.decide(snapshot(soc=90), intent(boost_until=NOW + timedelta(hours=1)))
        timed_out = policy.decide(
            snapshot(price=0.30),
            intent(
                boost_until=NOW,
                mode="cheap_top_up",
                max_cheap_rate=12,
            ),
        )
        self.assertFalse(reached.desired)
        self.assertTrue(reached.clear_boost and reached.target_reached)
        self.assertFalse(timed_out.desired)
        self.assertTrue(timed_out.clear_boost)
        self.assertIn("Boost expired", timed_out.reason)

    def test_vehicle_completion_clears_boost_without_restarting_and_needs_no_car_limit(self):
        result = policy.decide(
            snapshot(complete=True, car_limit=None, soc=79),
            intent(
                boost_until=NOW + timedelta(hours=1),
                mode="cheap_top_up",
            ),
        )
        self.assertFalse(result.desired)
        self.assertTrue(result.clear_boost)
        self.assertFalse(result.target_reached)
        self.assertFalse(result.problem)
        self.assertIn("charge complete", result.reason)

    def test_boost_without_car_limit_uses_completion_and_timeout(self):
        result = policy.decide(
            snapshot(car_limit=None), intent(boost_until=NOW + timedelta(hours=1))
        )
        self.assertTrue(result.desired)
        self.assertFalse(result.problem)
        self.assertIn("timeout", result.reason)

    def test_preconditioning_exception_is_bounded_and_policy_specific(self):
        observed = snapshot(
            preconditioning=True, preconditioning_until=NOW + timedelta(minutes=10), price=0.40
        )
        keep_without_existing = policy.decide(
            observed, intent(preconditioning_policy="keep_existing")
        )
        keep_existing = policy.decide(
            snapshot(
                preconditioning=True,
                preconditioning_until=NOW + timedelta(minutes=10),
                switch_on=True,
                owns_charge=True,
                price=0.40,
            ),
            intent(preconditioning_policy="keep_existing"),
        )
        permit = policy.decide(observed, intent(preconditioning_policy="allow"))
        expired = policy.decide(
            snapshot(preconditioning=True, preconditioning_until=NOW, price=0.40),
            intent(preconditioning_policy="allow"),
        )
        self.assertFalse(keep_without_existing.desired)
        self.assertTrue(keep_existing.desired)
        self.assertTrue(permit.desired)
        self.assertFalse(expired.desired)


class TargetModeTests(unittest.TestCase):
    def test_deadline_charges_selected_slot_above_manual_max_by_default(self):
        result = policy.decide(
            snapshot(price=0.35),
            intent(
                mode="deadline",
                max_cheap_rate=12,
                deadline=NOW + timedelta(hours=3),
            ),
            active_plan(),
        )
        self.assertTrue(result.desired)
        self.assertEqual(result.status, "Deadline plan charging")

    def test_deadline_hard_ceiling_blocks_expensive_price(self):
        result = policy.decide(
            snapshot(price=0.35),
            intent(
                mode="deadline",
                max_cheap_rate=12,
                hard_price_ceiling=True,
                deadline=NOW + timedelta(hours=3),
            ),
            active_plan(),
        )
        self.assertFalse(result.desired)
        self.assertEqual(result.status, "Hard price ceiling")
        self.assertTrue(result.problem)

    def test_deadline_uses_valid_current_price_when_latest_start_arrives(self):
        result = policy.decide(
            snapshot(price=0.35, effective_power_kw=4),
            intent(
                mode="deadline",
                max_cheap_rate=12,
                deadline=NOW + timedelta(hours=2),
            ),
            Plan(required_battery_kwh=8, shortfall_kwh=1),
        )
        self.assertTrue(result.desired)
        self.assertEqual(result.status, "Urgent deadline charging")

    def test_deadline_missing_price_never_uses_unknown_as_free_even_when_urgent(self):
        result = policy.decide(
            snapshot(price=None, price_valid=False, effective_power_kw=4),
            intent(
                mode="deadline",
                deadline=NOW + timedelta(hours=2),
            ),
            Plan(required_battery_kwh=8),
        )
        self.assertIsNone(result.desired)
        self.assertEqual(result.status, "Price unavailable")

    def test_deadline_miss_stops_and_reports_problem(self):
        result = policy.decide(
            snapshot(now=NOW + timedelta(minutes=1)),
            intent(
                mode="deadline",
                deadline=NOW,
            ),
            active_plan(),
        )
        self.assertFalse(result.desired)
        self.assertTrue(result.problem)
        self.assertEqual(result.status, "Deadline missed")

    def test_car_limit_caps_effective_target_but_never_claims_requested_target(self):
        charging = policy.decide(
            snapshot(soc=75, car_limit=80),
            intent(
                mode="deadline",
                target_percent=90,
                deadline=NOW + timedelta(hours=3),
            ),
            active_plan(),
        )
        reached_cap = policy.decide(
            snapshot(soc=80, car_limit=80),
            intent(
                mode="deadline",
                target_percent=90,
                deadline=NOW + timedelta(hours=3),
            ),
            active_plan(),
        )
        self.assertTrue(charging.desired)
        self.assertTrue(charging.problem)
        self.assertFalse(reached_cap.desired)
        self.assertTrue(reached_cap.problem)
        self.assertFalse(reached_cap.target_reached)
        self.assertEqual(reached_cap.status, "Car limit blocks target")

    def test_target_data_missing_and_unknown_mode_are_reported(self):
        missing = policy.decide(snapshot(soc=None), intent(mode="flexible"), active_plan())
        invalid = policy.decide(snapshot(), intent(mode="other"))
        self.assertIsNone(missing.desired)
        self.assertTrue(missing.problem)
        self.assertTrue(invalid.problem)

    def test_flexible_target_uses_selected_cheap_slot_and_hysteresis(self):
        chosen = policy.decide(
            snapshot(price=0.10, soc=70),
            intent(
                mode="flexible",
                target_percent=80,
            ),
            active_plan(),
        )
        maintained = policy.decide(
            snapshot(price=0.10, soc=79),
            intent(
                mode="flexible",
                target_percent=80,
                maintenance_margin=2,
                maintenance_satisfied=True,
            ),
            active_plan(),
        )
        outside_plan = policy.decide(snapshot(price=0.10), intent(mode="flexible"), Plan())
        self.assertTrue(chosen.desired)
        self.assertFalse(maintained.desired)
        self.assertEqual(maintained.status, "Target maintained")
        self.assertFalse(outside_plan.desired)
        self.assertEqual(outside_plan.status, "Waiting for selected slot")

    def test_flexible_target_waits_above_manual_limit_and_for_missing_price(self):
        expensive = policy.decide(
            snapshot(price=0.13), intent(mode="flexible", max_cheap_rate=12), active_plan()
        )
        missing = policy.decide(
            snapshot(price=None, price_valid=False), intent(mode="flexible"), active_plan()
        )
        self.assertFalse(expensive.desired)
        self.assertIsNone(missing.desired)
        self.assertEqual(missing.status, "Price unavailable")

    def test_preconditioning_exception_can_run_after_target_reached(self):
        result = policy.decide(
            snapshot(
                soc=80,
                preconditioning=True,
                preconditioning_until=NOW + timedelta(minutes=10),
                price=0.50,
                switch_on=True,
                owns_charge=True,
            ),
            intent(mode="flexible", target_percent=80, preconditioning_policy="keep_existing"),
            active_plan(),
        )
        self.assertTrue(result.desired)
        self.assertEqual(result.status, "Preconditioning exception active")


if __name__ == "__main__":
    unittest.main()
