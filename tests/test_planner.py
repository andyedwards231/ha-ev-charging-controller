"""Standard-library tests for the pure EV charging planner."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path

PLANNER_PATH = (
    Path(__file__).parents[1] / "custom_components" / "ev_charge_controller" / "planner.py"
)
SPEC = importlib.util.spec_from_file_location("ev_charge_planner", PLANNER_PATH)
assert SPEC and SPEC.loader
planner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = planner
SPEC.loader.exec_module(planner)

UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def rate(start_hour: int, end_hour: int, price: float):
    return planner.RateSlot(
        BASE + timedelta(hours=start_hour), BASE + timedelta(hours=end_hour), price
    )


class NormalizeRatesTests(unittest.TestCase):
    def test_octopus_values_are_converted_sorted_and_deduplicated(self):
        records = [
            {
                "start": "2026-01-01T00:30:00+00:00",
                "end": "2026-01-01T01:00:00Z",
                "value_inc_vat": 5,
            },
            {"start": "2025-12-31T16:00:00-08:00", "end": "2025-12-31T16:30:00-08:00", "value": 4},
            {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:30:00Z", "value": 4},
        ]
        slots = planner.normalize_rates(records, unit="p/kWh")
        self.assertEqual(len(slots), 2)
        self.assertEqual([slot.price for slot in slots], [0.04, 0.05])
        self.assertEqual(slots[0].start, BASE)

    def test_rejects_naive_invalid_missing_nonfinite_and_conflicting_data(self):
        cases = [
            (
                [{"start": "2026-01-01T00:00:00", "end": "2026-01-01T00:30:00Z", "value": 1}],
                "GBP/kWh",
            ),
            ([{"start": "bad", "end": "2026-01-01T00:30:00Z", "value": 1}], "GBP/kWh"),
            ([{"start": BASE, "end": BASE, "value": 1}], "GBP/kWh"),
            (
                [{"start": BASE, "end": BASE + timedelta(minutes=30), "value": float("nan")}],
                "GBP/kWh",
            ),
            ([{"start": BASE, "end": BASE + timedelta(minutes=30)}], "GBP/kWh"),
            ([{"start": BASE, "end": BASE + timedelta(minutes=30), "value": 1}], "USD/kWh"),
            (
                [
                    {"start": BASE, "end": BASE + timedelta(hours=1), "value": 1},
                    {
                        "start": BASE + timedelta(minutes=30),
                        "end": BASE + timedelta(hours=2),
                        "value": 1,
                    },
                ],
                "GBP/kWh",
            ),
            (
                [
                    {"start": BASE, "end": BASE + timedelta(minutes=30), "value": 1},
                    {"start": BASE, "end": BASE + timedelta(minutes=30), "value": 2},
                ],
                "GBP/kWh",
            ),
        ]
        for records, unit in cases:
            with self.subTest(records=records, unit=unit), self.assertRaises(ValueError):
                planner.normalize_rates(records, unit)


class PlanChargingTests(unittest.TestCase):
    def test_clips_current_and_deadline_intervals_and_reports_grid_cost(self):
        now = BASE + timedelta(minutes=15)
        deadline = BASE + timedelta(hours=1, minutes=45)
        plan = planner.plan_charging(
            [rate(0, 1, 0.10), rate(1, 2, 0.20)],
            now,
            target_soc=15,
            current_soc=0,
            capacity_kwh=10,
            power_kw=1,
            efficiency=1,
            margin=0,
            deadline=deadline,
        )
        self.assertEqual(
            [(slot.start, slot.end) for slot in plan.slots],
            [
                (now, BASE + timedelta(hours=1)),
                (BASE + timedelta(hours=1), deadline),
            ],
        )
        self.assertAlmostEqual(plan.estimated_cost, 0.225)
        self.assertAlmostEqual(plan.required_battery_kwh, 1.5)
        self.assertTrue(plan.completion)

    def test_cheapest_allocation_handles_negative_and_equal_rates_and_prior_plan(self):
        previous = [rate(2, 3, 0.0)]
        plan = planner.plan_charging(
            [rate(0, 1, -0.02), rate(1, 2, 0.0), rate(2, 3, 0.0)],
            BASE,
            target_soc=15,
            current_soc=0,
            capacity_kwh=10,
            power_kw=1,
            efficiency=1,
            margin=0,
            previous=previous,
        )
        self.assertEqual(plan.slots[0].start, BASE)
        self.assertEqual(plan.slots[1].start, BASE + timedelta(hours=2))
        self.assertAlmostEqual(plan.estimated_cost, -0.02)

    def test_price_ceiling_car_limit_and_unreachable_forecast(self):
        plan = planner.plan_charging(
            [rate(0, 1, 0.10), rate(1, 2, 0.30)],
            BASE,
            target_soc=90,
            current_soc=70,
            capacity_kwh=60,
            power_kw=1,
            efficiency=1,
            margin=0,
            deadline=BASE + timedelta(hours=3),
            price_ceiling=0.20,
            car_limit=80,
        )
        self.assertAlmostEqual(plan.required_battery_kwh, 6.0)
        self.assertAlmostEqual(plan.planned_battery_kwh, 1.0)
        self.assertAlmostEqual(plan.shortfall_kwh, 5.0)
        self.assertFalse(plan.completion)
        self.assertTrue(plan.provisional)
        self.assertEqual(plan.max_price, 0.10)
        self.assertEqual(plan.coverage_end, BASE + timedelta(hours=2))

    def test_coverage_stops_at_gaps_and_missing_current_period(self):
        deadline = BASE + timedelta(hours=2, minutes=30)
        gap_plan = planner.plan_charging(
            [rate(0, 1, 0.1), rate(1.5, 3, 0.1)],
            BASE,
            target_soc=75,
            current_soc=0,
            capacity_kwh=4,
            power_kw=1,
            efficiency=1,
            margin=0,
            deadline=deadline,
        )
        self.assertEqual(gap_plan.coverage_end, BASE + timedelta(hours=1))
        self.assertTrue(gap_plan.provisional)
        self.assertEqual(
            [(slot.start, slot.end) for slot in gap_plan.slots],
            [
                (BASE, BASE + timedelta(hours=1)),
                (BASE + timedelta(hours=1, minutes=30), BASE + timedelta(hours=2, minutes=30)),
            ],
        )
        self.assertAlmostEqual(gap_plan.shortfall_kwh, 1.0)
        self.assertFalse(gap_plan.completion)

        missing_current = planner.plan_charging(
            [rate(0.5, 2, 0.1)],
            BASE,
            target_soc=10,
            current_soc=0,
            capacity_kwh=1,
            power_kw=1,
            efficiency=1,
            margin=0,
            deadline=BASE + timedelta(hours=1.5),
        )
        self.assertIsNone(missing_current.coverage_end)
        self.assertTrue(missing_current.provisional)

    def test_duplicate_direct_rate_slots_are_rejected(self):
        duplicate = rate(0, 1, 0.1)
        with self.assertRaisesRegex(ValueError, "overlap"):
            planner.plan_charging([duplicate, duplicate], BASE, 80, 20, 60, 7, 0.9)

    def test_zero_need_and_no_forecast_are_explicit(self):
        complete = planner.plan_charging([], BASE, 50, 60, 60, 7, 0.9)
        self.assertTrue(complete.completion)
        self.assertEqual(complete.slots, ())
        self.assertIsNone(complete.coverage_end)
        missing = planner.plan_charging(
            [], BASE, 60, 50, 60, 7, 0.9, deadline=BASE + timedelta(hours=2)
        )
        self.assertEqual(missing.shortfall_kwh, 6.0)
        self.assertFalse(missing.completion)
        self.assertTrue(missing.provisional)

    def test_dst_transition_inputs_are_compared_as_real_elapsed_time(self):
        # London falls back from BST to GMT: both local 01:30 values are distinct.
        first = datetime.fromisoformat("2026-10-25T01:30:00+01:00")
        second = datetime.fromisoformat("2026-10-25T01:30:00+00:00")
        slots = planner.normalize_rates(
            [
                {
                    "start": first,
                    "end": datetime.fromisoformat("2026-10-25T01:00:00+00:00"),
                    "value": 0.1,
                },
                {
                    "start": second,
                    "end": datetime.fromisoformat("2026-10-25T02:00:00+00:00"),
                    "value": 0.2,
                },
            ]
        )
        self.assertEqual(slots[0].start, datetime(2026, 10, 25, 0, 30, tzinfo=UTC))
        self.assertEqual(slots[1].start, datetime(2026, 10, 25, 1, 30, tzinfo=UTC))

    def test_small_schedule_matches_exhaustive_cheapest_duration_cost(self):
        # Three one-hour periods; a 1.5-hour request must use the cheapest full
        # hour and half of the next-cheapest hour.
        prices = [0.24, -0.01, 0.07]
        plan = planner.plan_charging(
            [rate(i, i + 1, p) for i, p in enumerate(prices)], BASE, 15, 0, 10, 1, 1, margin=0
        )
        oracle = sum(sorted(prices)[:1]) + sorted(prices)[1] * 0.5
        self.assertAlmostEqual(
            sum((slot.end - slot.start).total_seconds() / 3600 for slot in plan.slots), 1.5
        )
        self.assertAlmostEqual(plan.estimated_cost, oracle)
        self.assertAlmostEqual(plan.shortfall_kwh, 0)

    def test_unequal_partial_slots_match_exhaustive_subset_oracle(self):
        durations = [0.5, 1.25, 2.0, 0.75]
        prices = [0.08, 0.12, 0.13, -0.02]
        ceiling = 0.12
        required_hours = 2.0  # 70% car limit minus current 50%, on a 10 kWh pack.
        eligible = [
            (duration, price) for duration, price in zip(durations, prices) if price <= ceiling
        ]

        # Enumerate each possible chosen interval subset. Within each subset,
        # remove its most expensive excess duration, allowing a partial final slot.
        oracle_costs = []
        for count in range(1, len(eligible) + 1):
            for subset in combinations(eligible, count):
                if sum(duration for duration, _ in subset) < required_hours:
                    continue
                remaining = required_hours
                cost = 0.0
                for duration, price in sorted(subset, key=lambda item: item[1]):
                    used = min(duration, remaining)
                    cost += used * price
                    remaining -= used
                    if remaining <= 1e-12:
                        break
                if remaining <= 1e-12:
                    oracle_costs.append(cost)
        self.assertTrue(oracle_costs)

        rates = [
            planner.RateSlot(
                BASE + timedelta(hours=sum(durations[:i])),
                BASE + timedelta(hours=sum(durations[: i + 1])),
                price,
            )
            for i, price in enumerate(prices)
        ]
        plan = planner.plan_charging(
            rates,
            BASE,
            target_soc=95,
            current_soc=50,
            capacity_kwh=10,
            power_kw=1,
            efficiency=1,
            margin=0,
            price_ceiling=ceiling,
            car_limit=70,
        )
        self.assertAlmostEqual(plan.required_battery_kwh, required_hours)
        self.assertAlmostEqual(plan.estimated_cost, min(oracle_costs))
        self.assertAlmostEqual(sum(slot.energy_kwh for slot in plan.slots), required_hours)
        self.assertTrue(all(slot.price <= ceiling for slot in plan.slots))

    def test_invalid_inputs_are_rejected(self):
        invalid_calls = [
            {"target_soc": 110},
            {"power_kw": 0},
            {"efficiency": 0},
            {"margin": -0.1},
            {"car_limit": 101},
            {"price_ceiling": float("inf")},
        ]
        for overrides in invalid_calls:
            args = dict(target_soc=80, current_soc=20, capacity_kwh=60, power_kw=7, efficiency=0.9)
            args.update(overrides)
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                planner.plan_charging([], BASE, **args)


if __name__ == "__main__":
    unittest.main()
