"""Source validation and exact free-session boundaries."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from ev_charge_controller.planner import RateSlot, plan_charging
from ev_charge_controller.provider import (
    apply_free_session,
    fresh,
    number,
    published_rates,
    published_rates_report,
    rate_snapshot,
)

BASE = datetime(2026, 10, 11, tzinfo=timezone.utc)


def test_free_session_preserves_negative_prices_and_fills_only_known_window():
    rates = (
        RateSlot(BASE, BASE + timedelta(hours=1), -0.02),
        RateSlot(BASE + timedelta(hours=2), BASE + timedelta(hours=3), 0.20),
    )
    start, end = BASE + timedelta(minutes=30), BASE + timedelta(minutes=150)
    result = apply_free_session(rates, start, end)
    assert [(s.start - BASE, s.end - BASE, s.price) for s in result] == [
        (timedelta(), timedelta(minutes=30), -0.02),
        (timedelta(minutes=30), timedelta(hours=1), -0.02),
        (timedelta(hours=1), timedelta(hours=2), 0),
        (timedelta(hours=2), timedelta(minutes=150), 0),
        (timedelta(minutes=150), timedelta(hours=3), 0.20),
    ]
    assert apply_free_session((), start, end) == (RateSlot(start, end, 0),)


def test_unavailable_nonfinite_stale_and_expired_sources_are_not_free():
    state = SimpleNamespace(state="nan", attributes={}, last_reported=BASE)
    assert number(state) is None
    assert rate_snapshot(state, BASE, "GBP/kWh")[1] is False
    state.state = "0.05"
    state.attributes = {
        "start": BASE.isoformat(),
        "end": (BASE + timedelta(minutes=30)).isoformat(),
        "timestamp": (BASE - timedelta(hours=1)).isoformat(),
    }
    assert fresh(state, BASE, 30) is False
    assert rate_snapshot(state, BASE + timedelta(minutes=30), "GBP/kWh")[1] is False


def test_forecast_from_old_tariff_is_excluded():
    state = SimpleNamespace(
        state="updated",
        attributes={
            "tariff_code": "OLD",
            "rates": [{"start": BASE, "end": BASE + timedelta(minutes=30), "value_inc_vat": 0.01}],
        },
    )
    assert published_rates([state], "AGILE", "GBP/kWh") == ()


def test_unknown_tomorrow_does_not_discard_today_and_reports_partial_coverage():
    today = SimpleNamespace(
        state="on",
        attributes={
            "tariff_code": "AGILE",
            "rates": [
                {"start": BASE, "end": BASE + timedelta(hours=1), "value_inc_vat": 0.1}
            ],
        },
    )
    tomorrow = SimpleNamespace(state="unknown", attributes={})

    rates, warnings, complete = published_rates_report([today, tomorrow], "AGILE", "GBP/kWh")

    assert len(rates) == 1
    assert "Tomorrow rates are unknown" in warnings[0]
    assert complete is False


def test_malformed_tomorrow_keeps_valid_today_prices():
    today = SimpleNamespace(
        state="on",
        attributes={
            "rates": [{"start": BASE, "end": BASE + timedelta(hours=1), "value": 0.1}]
        },
    )
    tomorrow = SimpleNamespace(
        state="on", attributes={"rates": [{"start": "bad", "end": "also bad", "value": 0.2}]}
    )

    rates, warnings, complete = published_rates_report([today, tomorrow], "AGILE", "GBP/kWh")

    assert len(rates) == 1
    assert any("Tomorrow rates are invalid" in warning for warning in warnings)
    assert complete is False


def test_partial_overlap_excludes_both_intervals_and_keeps_unrelated_rates():
    from ev_charge_controller.provider import published_rates_report

    today = SimpleNamespace(
        state="on",
        attributes={
            "rates": [
                {"start": BASE, "end": BASE + timedelta(hours=1), "value": 0.2},
                {
                    "start": BASE + timedelta(hours=2),
                    "end": BASE + timedelta(hours=3),
                    "value": 0.1,
                },
            ]
        },
    )
    tomorrow = SimpleNamespace(
        state="on",
        attributes={
            "rates": [
                {
                    "start": BASE + timedelta(minutes=30),
                    "end": BASE + timedelta(hours=1, minutes=30),
                    "value": 0.4,
                }
            ]
        },
    )

    rates, warnings, complete = published_rates_report([today, tomorrow], "AGILE", "GBP/kWh")

    assert [(slot.start, slot.end, slot.price) for slot in rates] == [
        (BASE + timedelta(hours=2), BASE + timedelta(hours=3), 0.1)
    ]
    assert any("excluded because their prices are ambiguous" in warning for warning in warnings)
    assert complete is False
    plan = plan_charging(rates, BASE, 10, 0, 1, 1, 1, margin=0)
    assert all(slot.price != 0.2 for slot in plan.slots)
    assert all(slot.start >= BASE + timedelta(hours=2) for slot in plan.slots)


def test_chained_overlaps_exclude_all_ambiguous_rates():
    from ev_charge_controller.provider import published_rates_report

    today = SimpleNamespace(
        state="on",
        attributes={
            "rates": [
                {"start": BASE, "end": BASE + timedelta(hours=1), "value": 0.2},
                {
                    "start": BASE + timedelta(hours=1, minutes=30),
                    "end": BASE + timedelta(hours=2, minutes=30),
                    "value": 0.4,
                },
                {
                    "start": BASE + timedelta(hours=4),
                    "end": BASE + timedelta(hours=5),
                    "value": 0.15,
                },
            ]
        },
    )
    tomorrow = SimpleNamespace(
        state="on",
        attributes={
            "rates": [
                {
                    "start": BASE + timedelta(minutes=45),
                    "end": BASE + timedelta(hours=1, minutes=45),
                    "value": 0.3,
                }
            ]
        },
    )

    rates, warnings, complete = published_rates_report([today, tomorrow], "AGILE", "GBP/kWh")

    assert [(slot.start, slot.end, slot.price) for slot in rates] == [
        (BASE + timedelta(hours=4), BASE + timedelta(hours=5), 0.15)
    ]
    assert any("Overlapping rate intervals" in warning for warning in warnings)
    assert complete is False


def test_conflicting_exact_duplicate_intervals_are_both_excluded():
    from ev_charge_controller.provider import published_rates_report

    today = SimpleNamespace(
        state="on",
        attributes={
            "rates": [
                {"start": BASE, "end": BASE + timedelta(hours=1), "value": 0.2},
                {
                    "start": BASE + timedelta(hours=2),
                    "end": BASE + timedelta(hours=3),
                    "value": 0.15,
                },
            ]
        },
    )
    tomorrow = SimpleNamespace(
        state="on",
        attributes={
            "rates": [{"start": BASE, "end": BASE + timedelta(hours=1), "value": 0.25}]
        },
    )

    rates, warnings, complete = published_rates_report([today, tomorrow], "AGILE", "GBP/kWh")

    assert [(slot.start, slot.end, slot.price) for slot in rates] == [
        (BASE + timedelta(hours=2), BASE + timedelta(hours=3), 0.15)
    ]
    assert any("Conflicting duplicate" in warning for warning in warnings)
    assert complete is False
