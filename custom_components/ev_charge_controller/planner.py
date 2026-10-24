"""Pure price normalization and cheapest-period charging planner."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class RateSlot:
    """One UTC rate interval. ``price`` is always GBP per grid kWh."""

    start: datetime
    end: datetime
    price: float


@dataclass(frozen=True)
class PlannedSlot:
    """A selected (possibly partial) UTC interval and its grid energy."""

    start: datetime
    end: datetime
    price: float
    energy_kwh: float


@dataclass(frozen=True)
class Plan:
    slots: tuple[PlannedSlot, ...]
    required_battery_kwh: float
    planned_battery_kwh: float
    shortfall_kwh: float
    estimated_cost: float
    max_price: float | None
    coverage_end: datetime | None
    provisional: bool
    completion: bool


def _as_utc(value: Any, name: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"invalid {name} timestamp: {value!r}") from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime or ISO timestamp")
    return value.astimezone(timezone.utc)


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _unit_factor(unit: str) -> float:
    normalized = unit.strip().lower().replace("£", "gbp").replace(" ", "")
    if normalized in {"gbp/kwh", "gbpperkwh"}:
        return 1.0
    if normalized in {"p/kwh", "pperkwh", "pence/kwh"}:
        return 0.01
    raise ValueError(f"unsupported price unit: {unit!r}")


def normalize_rates(
    records: Iterable[Mapping[str, Any]], unit: str = "GBP/kWh"
) -> tuple[RateSlot, ...]:
    """Validate provider rate records and return sorted, deduplicated UTC slots.

    Octopus event records normally use ``value_inc_vat``; ``value`` is accepted
    as a fallback. Any overlap between distinct intervals is rejected because
    the planner cannot safely decide which published price is authoritative.
    """
    factor = _unit_factor(unit)
    slots: dict[tuple[datetime, datetime], RateSlot] = {}
    try:
        iterator = iter(records)
    except TypeError as exc:
        raise ValueError("rate records must be iterable") from exc
    for index, record in enumerate(iterator):
        if not isinstance(record, Mapping):
            raise ValueError(f"rate record {index} must be a mapping")
        if "start" not in record or "end" not in record:
            raise ValueError(f"rate record {index} is missing start or end")
        start = _as_utc(record["start"], f"record {index} start")
        end = _as_utc(record["end"], f"record {index} end")
        if end <= start:
            raise ValueError(f"rate record {index} end must be after start")
        raw_price = record.get("value_inc_vat", record.get("value"))
        if raw_price is None:
            raise ValueError(f"rate record {index} is missing value_inc_vat or value")
        price = _finite_number(raw_price, f"record {index} price") * factor
        key = (start, end)
        existing = slots.get(key)
        if existing is not None and not math.isclose(
            existing.price, price, rel_tol=0, abs_tol=1e-12
        ):
            raise ValueError("duplicate rate intervals have conflicting prices")
        slots[key] = RateSlot(start, end, price)

    ordered = tuple(sorted(slots.values(), key=lambda slot: (slot.start, slot.end, slot.price)))
    for previous, current in zip(ordered, ordered[1:]):
        if current.start < previous.end:
            raise ValueError("rate intervals overlap")
    return ordered


def _prior_keys(
    previous: Iterable[RateSlot | PlannedSlot],
) -> set[tuple[datetime, datetime, float]]:
    keys: set[tuple[datetime, datetime, float]] = set()
    for slot in previous:
        keys.add(
            (
                _as_utc(slot.start, "previous start"),
                _as_utc(slot.end, "previous end"),
                _finite_number(slot.price, "previous price"),
            )
        )
    return keys


def plan_charging(
    rates: Iterable[RateSlot],
    now: datetime,
    target_soc: float,
    current_soc: float,
    capacity_kwh: float,
    power_kw: float,
    efficiency: float,
    margin: float = 0.1,
    deadline: datetime | None = None,
    price_ceiling: float | None = None,
    car_limit: float | None = None,
    previous: Iterable[RateSlot | PlannedSlot] = (),
) -> Plan:
    """Select cheapest available intervals for a requested battery target.

    ``target_soc``, ``current_soc`` and ``car_limit`` are percentages.
    ``price_ceiling`` is GBP/kWh. Power is grid-side kW; the conservative
    planning rate is ``power_kw * efficiency / (1 + margin)`` battery kW.
    ``PlannedSlot.energy_kwh`` and cost use grid energy, including losses.
    """
    now_utc = _as_utc(now, "now")
    deadline_utc = _as_utc(deadline, "deadline") if deadline is not None else None
    target = _finite_number(target_soc, "target_soc")
    current = _finite_number(current_soc, "current_soc")
    capacity = _finite_number(capacity_kwh, "capacity_kwh")
    power = _finite_number(power_kw, "power_kw")
    eff = _finite_number(efficiency, "efficiency")
    delay_margin = _finite_number(margin, "margin")
    if not 0 <= target <= 100 or not 0 <= current <= 100:
        raise ValueError("state-of-charge percentages must be between 0 and 100")
    if capacity <= 0 or power <= 0:
        raise ValueError("capacity_kwh and power_kw must be greater than zero")
    if not 0 < eff <= 1:
        raise ValueError("efficiency must be greater than zero and at most one")
    if delay_margin < 0:
        raise ValueError("margin must not be negative")
    if car_limit is not None:
        limit = _finite_number(car_limit, "car_limit")
        if not 0 <= limit <= 100:
            raise ValueError("car_limit must be between 0 and 100")
        target = min(target, limit)
    ceiling = _finite_number(price_ceiling, "price_ceiling") if price_ceiling is not None else None

    required = max(0.0, (target - current) * capacity / 100.0)
    normalized_rates: list[RateSlot] = []
    for index, slot in enumerate(rates):
        start = _as_utc(slot.start, f"rate {index} start")
        end = _as_utc(slot.end, f"rate {index} end")
        price = _finite_number(slot.price, f"rate {index} price")
        if end <= start:
            raise ValueError(f"rate {index} end must be after start")
        normalized_rates.append(RateSlot(start, end, price))
    normalized_rates.sort(key=lambda slot: (slot.start, slot.end, slot.price))
    # Apply the same overlap invariant to callers that construct RateSlot directly.
    for left, right in zip(normalized_rates, normalized_rates[1:]):
        if right.start < left.end:
            raise ValueError("rate intervals overlap")
    # Coverage describes the continuous forecast available from this instant.
    # A later interval after a gap cannot support a deadline plan through that gap.
    coverage_end: datetime | None = None
    for slot in normalized_rates:
        if slot.start <= now_utc < slot.end:
            coverage_end = slot.end
            break
        if slot.start > now_utc:
            break
    if coverage_end is not None:
        for slot in normalized_rates:
            if slot.start <= coverage_end < slot.end:
                coverage_end = slot.end
            elif slot.start > coverage_end:
                break
    is_provisional = bool(
        deadline_utc is not None and (coverage_end is None or coverage_end < deadline_utc)
    )

    if required <= 1e-12:
        return Plan((), required, 0.0, 0.0, 0.0, None, coverage_end, is_provisional, True)

    prior = _prior_keys(previous)
    candidates: list[tuple[RateSlot, datetime, datetime, bool]] = []
    for slot in normalized_rates:
        start = max(slot.start, now_utc)
        end = min(slot.end, deadline_utc) if deadline_utc is not None else slot.end
        if end <= start or (ceiling is not None and slot.price > ceiling):
            continue
        previous_match = any(
            old_start < end
            and start < old_end
            and math.isclose(old_price, slot.price, rel_tol=0, abs_tol=1e-12)
            for old_start, old_end, old_price in prior
        )
        candidates.append((slot, start, end, previous_match))

    # Margins increase the time reserved for the requested battery energy.
    # Price is ranked on grid kWh; under constant power and efficiency this is
    # equivalent to ranking by battery kWh, including negative prices.
    effective_battery_kw = power * eff / (1.0 + delay_margin)
    remaining_battery = required
    picked: list[PlannedSlot] = []
    # For equal prices, retain matching previous intervals, then prefer earlier
    # adjacent slots. Stable chronological ordering resolves every remaining tie.
    candidates.sort(key=lambda item: (item[0].price, not item[3], item[1], item[2]))
    for slot, start, end, _was_previous in candidates:
        if remaining_battery <= 1e-12:
            break
        available_hours = (end - start).total_seconds() / 3600.0
        reserved_hours = min(available_hours, remaining_battery / effective_battery_kw)
        if reserved_hours <= 0:
            continue
        selected_end = start.replace() + (end - start) * (reserved_hours / available_hours)
        # The reserved duration includes the conservative margin. Its grid
        # energy estimate uses the configured power and includes conversion loss.
        grid_energy = reserved_hours * power
        picked.append(PlannedSlot(start, selected_end, slot.price, grid_energy))
        remaining_battery = max(0.0, remaining_battery - reserved_hours * effective_battery_kw)

    picked.sort(key=lambda slot: (slot.start, slot.end))
    # Merge contiguous selected periods with the same price. This preserves the
    # energy total while making the schedule easier to display and execute.
    merged: list[PlannedSlot] = []
    for slot in picked:
        if (
            merged
            and merged[-1].end == slot.start
            and math.isclose(merged[-1].price, slot.price, rel_tol=0, abs_tol=1e-12)
        ):
            previous_slot = merged[-1]
            merged[-1] = PlannedSlot(
                previous_slot.start,
                slot.end,
                slot.price,
                previous_slot.energy_kwh + slot.energy_kwh,
            )
        else:
            merged.append(slot)

    planned_battery = sum(slot.energy_kwh * eff for slot in merged)
    # The estimate can exceed the requested amount because the selected runtime
    # includes the configured conservative margin.
    shortfall = max(
        0.0,
        required
        - sum(
            min(
                slot.energy_kwh * eff,
                (slot.end - slot.start).total_seconds() / 3600 * effective_battery_kw,
            )
            for slot in merged
        ),
    )
    cost = sum(slot.energy_kwh * slot.price for slot in merged)
    max_selected = max((slot.price for slot in merged), default=None)
    return Plan(
        tuple(merged),
        required,
        planned_battery,
        shortfall,
        cost,
        max_selected,
        coverage_end,
        is_provisional,
        shortfall <= 1e-9,
    )
