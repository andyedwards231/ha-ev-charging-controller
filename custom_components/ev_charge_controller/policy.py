"""Pure charge-control policy decisions.

This module deliberately has no Home Assistant dependencies. Prices are GBP/kWh;
user-entered cheap-rate settings are pence/kWh. It returns intent only and never
issues commands.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class Snapshot:
    """Validated observations needed to make one decision."""

    now: datetime
    tariff: str | None = None
    home: bool | None = None
    connected: bool | None = None
    switch_on: bool | None = None
    charging: bool | None = None
    soc: float | None = None
    car_limit: float | None = None
    # Vehicle-reported charge completion, not snapshot/input completeness.
    complete: bool = False
    price: float | None = None
    price_valid: bool = False
    free_session: bool = False
    preconditioning: bool = False
    preconditioning_until: datetime | None = None
    vehicle_valid: bool = True
    owns_charge: bool = False
    # Conservative battery-side power used for deadline urgency fallback.
    effective_power_kw: float = 0.0


@dataclass(frozen=True)
class Intent:
    """Persisted user choices and temporary requests."""

    automatic_control: bool = True
    monitoring_only: bool = True
    mode: str = "cheap_top_up"
    max_cheap_rate: float = 12.0
    target_percent: float = 80.0
    deadline: datetime | None = None
    hard_price_ceiling: bool = False
    boost_until: datetime | None = None
    boost_target: float | None = None
    manual_hold_until: datetime | None = None
    tariff_match: str = "AGILE"
    preconditioning_policy: str = "keep_existing"
    maintenance_margin: float = 2.0
    maintenance_satisfied: bool = False


@dataclass(frozen=True)
class Decision:
    """Desired switch state and an explanation; ``None`` means release/no action."""

    desired: bool | None
    status: str
    reason: str
    problem: bool = False
    clear_boost: bool = False
    target_reached: bool = False


def _valid_percent(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and 0.0 <= value <= 100.0


def _safe_owned_stop(snapshot: Snapshot) -> bool:
    """Whether the observations are trustworthy enough to stop our own charge."""
    return (
        snapshot.home is True
        and snapshot.connected is True
        and snapshot.switch_on is True
        and snapshot.owns_charge
    )


def _held(snapshot: Snapshot, intent: Intent) -> bool:
    return intent.manual_hold_until is not None and snapshot.now < intent.manual_hold_until


def _tariff_matches(tariff: str | None, match: str) -> bool:
    return bool(tariff and match and match.casefold() in tariff.casefold())


def _price_under_manual_limit(snapshot: Snapshot, intent: Intent) -> bool:
    return (
        snapshot.price_valid
        and snapshot.price is not None
        and math.isfinite(snapshot.price)
        and snapshot.price * 100.0 <= intent.max_cheap_rate
    )


def _inside_plan(snapshot: Snapshot, plan: Any) -> bool:
    if plan is None:
        return False
    for slot in getattr(plan, "slots", ()):
        start, end = getattr(slot, "start", None), getattr(slot, "end", None)
        if isinstance(start, datetime) and isinstance(end, datetime):
            try:
                if start <= snapshot.now < end:
                    return True
            except TypeError:
                # Naive timestamps are invalid plan data, never an invitation to
                # charge. The planner normally guarantees timezone awareness.
                return False
    return False


def _plan_value(plan: Any, name: str, default: float = 0.0) -> float:
    value = getattr(plan, name, default) if plan is not None else default
    try:
        number = float(value)
    except TypeError, ValueError:
        return default
    return number if math.isfinite(number) else default


def _effective_target(snapshot: Snapshot, intent: Intent) -> tuple[float, bool]:
    capped = snapshot.car_limit is not None and snapshot.car_limit < intent.target_percent
    return (
        min(intent.target_percent, snapshot.car_limit)
        if snapshot.car_limit is not None
        else intent.target_percent
    ), capped


def _monitoring(decision: Decision) -> Decision:
    if decision.desired is None:
        return Decision(
            None,
            f"Monitoring: {decision.status}",
            f"Monitoring only; no command: {decision.reason}",
            decision.problem,
            decision.clear_boost,
            decision.target_reached,
        )
    proposed = "charge" if decision.desired else "stop charging"
    return Decision(
        decision.desired,
        f"Monitoring: {decision.status}",
        f"Monitoring only; would {proposed}: {decision.reason}",
        decision.problem,
        decision.clear_boost,
        decision.target_reached,
    )


def _decide_active(snapshot: Snapshot, intent: Intent, plan: Any) -> Decision:
    # A confirmed unplug ends a boost, while ordinary requests remain saved.
    if snapshot.connected is False:
        return Decision(None, "Unplugged", "The vehicle is disconnected.", clear_boost=True)
    if snapshot.connected is not True:
        return Decision(
            None, "Waiting for connection data", "Cable state is unknown.", problem=True
        )

    if snapshot.home is False:
        return Decision(None, "Away", "Charging control is released while away.")
    if snapshot.home is not True:
        return Decision(None, "Waiting for location data", "Home state is unknown.", problem=True)

    if snapshot.switch_on is None:
        return Decision(
            None, "Waiting for switch data", "Charging switch state is unknown.", problem=True
        )
    if not snapshot.vehicle_valid or (
        snapshot.car_limit is not None and not _valid_percent(snapshot.car_limit)
    ):
        if _safe_owned_stop(snapshot):
            return Decision(
                False,
                "Vehicle data unavailable",
                "Stop the controller-owned charge because required inputs are incomplete.",
                problem=True,
            )
        return Decision(
            None,
            "Vehicle data unavailable",
            "Required vehicle or control inputs are incomplete.",
            problem=True,
        )

    # Boost has priority over preconditioning and the selected charging mode.
    boost_clear_reason: str | None = None
    if intent.boost_until is not None:
        if snapshot.now >= intent.boost_until:
            boost_clear_reason = "Boost expired"
        elif snapshot.complete:
            boost_clear_reason = "Vehicle reported charge complete"
        if boost_clear_reason is None:
            if snapshot.soc is None or not _valid_percent(snapshot.soc):
                return Decision(
                    None,
                    "Boost waiting for battery data",
                    "Boost is suspended until a valid battery reading is available.",
                    problem=True,
                )
            boost_target = intent.boost_target
            if boost_target is None:
                if snapshot.car_limit is None or not _valid_percent(snapshot.car_limit):
                    return Decision(
                        True,
                        "Boosting",
                        "Charge until the car reports complete or the boost timeout expires; car limit is unavailable.",
                    )
                boost_target = snapshot.car_limit
            if not _valid_percent(boost_target):
                return Decision(
                    None,
                    "Invalid boost target",
                    "The boost target must be between 0 and 100%.",
                    problem=True,
                )
            if snapshot.car_limit is not None and boost_target > snapshot.car_limit:
                return Decision(
                    None,
                    "Boost blocked by car limit",
                    f"Boost target {boost_target:g}% exceeds the car limit of {snapshot.car_limit:g}%.",
                    problem=True,
                )
            if snapshot.soc >= boost_target:
                boost_clear_reason = "Boost target reached"
            else:
                return Decision(
                    True,
                    "Boosting",
                    f"Charge to {boost_target:g}% regardless of price until the boost expires.",
                )

    # Preconditioning only grants a bounded exception. Expiry is explicit in
    # the snapshot so a stale sensor cannot hold this exception open.
    if snapshot.preconditioning:
        policy = intent.preconditioning_policy
        within_bound = (
            snapshot.preconditioning_until is not None
            and snapshot.now < snapshot.preconditioning_until
        )
        permitted = policy == "allow" and within_bound
        keep_existing = (
            policy == "keep_existing"
            and within_bound
            and snapshot.owns_charge
            and snapshot.switch_on is True
        )
        if permitted or keep_existing:
            decision = Decision(
                True,
                "Preconditioning exception active",
                "An existing bounded preconditioning exception permits grid use; charging may continue up to the car limit.",
            )
            return _after_boost_clear(
                decision,
                boost_clear_reason,
                target_reached=bool(
                    boost_clear_reason == "Boost target reached"
                    and snapshot.soc is not None
                    and snapshot.soc >= intent.target_percent
                ),
            )

    if boost_clear_reason == "Boost target reached":
        return Decision(
            False,
            "Boost target reached",
            "Battery reached the boost target.",
            clear_boost=True,
            target_reached=bool(snapshot.soc is not None and snapshot.soc >= intent.target_percent),
        )

    if snapshot.complete:
        reached = (
            _valid_percent(snapshot.soc) and snapshot.soc >= intent.target_percent
            if _valid_percent(intent.target_percent)
            else False
        )
        decision = Decision(
            False,
            "Vehicle reports charge complete",
            "The vehicle reports that charging is complete.",
            problem=intent.mode in ("deadline", "flexible") and not reached,
            target_reached=reached,
        )
        return _after_boost_clear(decision, boost_clear_reason, target_reached=reached)

    return _after_boost_clear(_decide_mode(snapshot, intent, plan), boost_clear_reason)


def _after_boost_clear(
    decision: Decision, reason: str | None, target_reached: bool | None = None
) -> Decision:
    if reason is None:
        return decision
    return Decision(
        decision.desired,
        decision.status,
        f"{reason}; {decision.reason}",
        decision.problem,
        clear_boost=True,
        target_reached=decision.target_reached if target_reached is None else target_reached,
    )


def _decide_mode(snapshot: Snapshot, intent: Intent, plan: Any) -> Decision:
    mode = intent.mode
    if mode == "cheap_top_up":
        if snapshot.free_session:
            return Decision(True, "Free session", "A verified free session permits charging.")
        if not snapshot.price_valid or snapshot.price is None or not math.isfinite(snapshot.price):
            if _safe_owned_stop(snapshot):
                return Decision(
                    False,
                    "Price unavailable",
                    "The valid price expired; stop the controller-owned price-based charge.",
                    problem=True,
                )
            return Decision(
                None,
                "Price unavailable",
                "No new price-based charge can start until the live price is valid.",
                problem=True,
            )
        if _price_under_manual_limit(snapshot, intent):
            return Decision(
                True,
                "Cheap rate",
                f"Current rate {snapshot.price * 100:g}p/kWh is within the {intent.max_cheap_rate:g}p/kWh limit.",
            )
        return Decision(
            False,
            "Waiting for cheap rate",
            f"Current rate {snapshot.price * 100:g}p/kWh exceeds the {intent.max_cheap_rate:g}p/kWh limit.",
        )

    if mode not in {"deadline", "flexible"}:
        return Decision(None, "Invalid mode", f"Unknown charging mode: {mode!r}.", problem=True)

    if not _valid_percent(intent.target_percent):
        return Decision(
            None, "Invalid target", "The requested target must be between 0 and 100%.", problem=True
        )

    if snapshot.soc is None or not _valid_percent(snapshot.soc):
        return Decision(
            None,
            "Battery data unavailable",
            "Target charging is suspended until battery data is valid.",
            problem=True,
        )

    effective_target, capped = _effective_target(snapshot, intent)
    cap_note = (
        f"Requested {intent.target_percent:g}%; car limit is {snapshot.car_limit:g}%. "
        if capped
        else ""
    )
    if snapshot.soc >= intent.target_percent:
        return Decision(
            False,
            "Target reached",
            f"{cap_note}Requested target reached.",
            problem=capped,
            target_reached=not capped,
        )
    if capped and snapshot.soc >= effective_target:
        return Decision(
            False,
            "Car limit blocks target",
            cap_note + "The car limit prevents the requested target.",
            problem=True,
            target_reached=False,
        )

    if mode == "flexible":
        restart_at = effective_target - max(0.0, intent.maintenance_margin)
        if intent.maintenance_satisfied and snapshot.soc >= restart_at:
            return Decision(
                False, "Target maintained", f"{cap_note}Battery is within the maintenance margin."
            )
        if not snapshot.price_valid or snapshot.price is None or not math.isfinite(snapshot.price):
            if _safe_owned_stop(snapshot):
                return Decision(
                    False,
                    "Price unavailable",
                    "Stop the controller-owned flexible charge until price data is valid.",
                    problem=True,
                )
            return Decision(
                None,
                "Price unavailable",
                "Flexible charging is waiting for a valid live price.",
                problem=True,
            )
        if snapshot.price * 100.0 > intent.max_cheap_rate:
            return Decision(
                False,
                "Waiting for cheap rate",
                f"{cap_note}Current rate {snapshot.price * 100:g}p/kWh exceeds the {intent.max_cheap_rate:g}p/kWh limit.",
            )
        if not _inside_plan(snapshot, plan):
            return Decision(
                False,
                "Waiting for selected slot",
                f"{cap_note}Current rate is eligible, but this period is not selected by the planner.",
            )
        return Decision(
            True,
            "Flexible target charging",
            f"{cap_note}Charging in a selected period under the manual rate limit.",
            problem=capped,
        )

    # Deadline requests are one-shot. A missing deadline cannot be interpreted
    # as an unlimited request.
    if intent.deadline is None:
        return Decision(
            None,
            "Deadline unavailable",
            "Target-by-deadline mode requires a deadline.",
            problem=True,
        )
    if snapshot.now >= intent.deadline:
        return Decision(
            False,
            "Deadline missed",
            f"{cap_note}The deadline passed before the requested target was reached.",
            problem=True,
        )

    if not snapshot.price_valid or snapshot.price is None or not math.isfinite(snapshot.price):
        if _safe_owned_stop(snapshot):
            return Decision(
                False,
                "Price unavailable",
                "Stop the controller-owned deadline charge until the live price is valid.",
                problem=True,
            )
        return Decision(
            None,
            "Price unavailable",
            "Deadline charging is waiting for a valid live price.",
            problem=True,
        )

    under_ceiling = snapshot.price * 100.0 <= intent.max_cheap_rate
    if intent.hard_price_ceiling and not under_ceiling:
        return Decision(
            False,
            "Hard price ceiling",
            f"{cap_note}Current rate exceeds the hard {intent.max_cheap_rate:g}p/kWh ceiling.",
            problem=True,
        )

    if _inside_plan(snapshot, plan):
        price_note = (
            f" Current rate {snapshot.price * 100:g}p/kWh exceeds the normal top-up ceiling to meet the deadline."
            if not under_ceiling
            else f" Current rate is {snapshot.price * 100:g}p/kWh."
        )
        return Decision(
            True,
            "Deadline plan charging",
            f"{cap_note}This is a selected charging period for the deadline target.{price_note}",
            problem=capped,
        )

    # As published coverage runs out, use a valid current price when waiting
    # would leave less time than the conservative battery-side charge duration.
    required = max(0.0, _plan_value(plan, "required_battery_kwh"))
    power = snapshot.effective_power_kw
    urgent = False
    if required > 0 and math.isfinite(power) and power > 0:
        latest_start = intent.deadline - timedelta(hours=required / power)
        urgent = snapshot.now >= latest_start
    if urgent:
        return Decision(
            True,
            "Urgent deadline charging",
            f"{cap_note}Waiting would risk missing the target; the current valid rate is permitted.",
            problem=capped,
        )

    plan_shortfall = max(0.0, _plan_value(plan, "shortfall_kwh"))
    if intent.hard_price_ceiling and plan_shortfall > 1e-9:
        return Decision(
            False,
            "Ceiling prevents completion",
            f"{cap_note}The hard price ceiling leaves {plan_shortfall:g} kWh unplanned.",
            problem=True,
        )
    if getattr(plan, "provisional", False):
        return Decision(
            False,
            "Waiting for tomorrow's prices",
            f"{cap_note}No selected period is active; later prices are not published yet.",
            problem=capped,
        )
    if plan_shortfall > 1e-9:
        return Decision(
            False,
            "Deadline plan shortfall",
            f"{cap_note}{plan_shortfall:g} kWh remains unplanned before the deadline.",
            problem=True,
        )
    return Decision(
        False,
        "Waiting for selected slot",
        f"{cap_note}Waiting for the next selected deadline period.",
        problem=capped,
    )


def decide(snapshot: Snapshot, intent: Intent, plan: Any | None = None) -> Decision:
    """Evaluate ownership, safety exceptions, and the selected charging mode.

    ``plan`` is intentionally duck typed; the pure planner's ``Plan`` object
    supplies ``slots``, ``required_battery_kwh``, ``shortfall_kwh`` and
    ``provisional``. ``desired=None`` means this controller has no action.
    Monitoring-only preserves the proposed desired state for display, while
    the caller is responsible for enforcing that no command is sent.
    """
    if not intent.automatic_control:
        return Decision(
            None, "Paused", "Automatic control is paused; charging state is left unchanged."
        )
    if _held(snapshot, intent):
        return Decision(
            None,
            "Manual hold",
            "A temporary manual hold is active; charging state is left unchanged.",
        )
    if not _tariff_matches(snapshot.tariff, intent.tariff_match):
        tariff = snapshot.tariff if snapshot.tariff is not None else "unknown"
        return Decision(
            None,
            "Released to another tariff",
            f"Tariff {tariff!r} does not match {intent.tariff_match!r}; control is released.",
        )

    decision = _decide_active(snapshot, intent, plan)
    return _monitoring(decision) if intent.monitoring_only else decision
