"""Read and validate connected entities without making provider requests."""

from __future__ import annotations

import math
from datetime import datetime, timezone

from .planner import RateSlot, normalize_rates


def number(state):
    """Do not turn unknown, unavailable or non-finite values into zero."""
    if state is None:
        return None
    try:
        value = float(state.state)
    except TypeError, ValueError:
        return None
    return value if math.isfinite(value) else None


def boolean(state):
    if state is None or state.state not in ("on", "off"):
        return None
    return state.state == "on"


def timestamp(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    return value.astimezone(timezone.utc)


def fresh(state, now, minutes):
    """Prefer explicit telemetry timestamps, otherwise state last_reported.

    State last_reported is HA's last source report, not proof of fresh cloud
    telemetry. It is deliberately exposed as an estimate in diagnostics.
    """
    if state is None or state.state in ("unknown", "unavailable"):
        return False
    for key in ("data_last_retrieved", "last_updated", "timestamp"):
        value = timestamp(state.attributes.get(key))
        if value:
            return 0 <= (now - value).total_seconds() <= minutes * 60
    value = getattr(state, "last_reported", state.last_updated)
    return 0 <= (now - value).total_seconds() <= minutes * 60


def rate_snapshot(state, now, unit):
    value = number(state)
    if value is None:
        return None, False, None, None
    factor = 0.01 if unit == "p/kWh" else 1.0
    start = timestamp(state.attributes.get("start"))
    end = timestamp(state.attributes.get("end"))
    return value * factor, bool(start and end and start <= now < end), start, end


def published_rates(states, tariff, unit):
    return published_rates_report(states, tariff, unit)[0]


def published_rates_report(states, tariff, unit):
    """Return valid source slots plus warnings without losing good-day data.

    The two event entities publish independently. An empty, unavailable or
    malformed tomorrow event must not erase valid rates already published for
    today. Overlapping intervals remain excluded because their authoritative
    price cannot be determined safely.
    """
    slots_by_source = []
    warnings = []
    source_names = ("today", "tomorrow")
    for index, state in enumerate(states):
        source_name = source_names[index] if index < len(source_names) else f"source {index + 1}"
        if state is None or state.state in ("unknown", "unavailable"):
            warnings.append(f"{source_name.title()} rates are {state.state if state else 'missing'}.")
            slots_by_source.append(())
            continue
        source_tariff = state.attributes.get("tariff_code")
        if source_tariff and source_tariff != tariff:
            warnings.append(f"{source_name.title()} rates are for a different tariff.")
            slots_by_source.append(())
            continue
        records = state.attributes.get("rates") or []
        if not records:
            warnings.append(f"{source_name.title()} rates are empty.")
            slots_by_source.append(())
            continue
        try:
            slots_by_source.append(normalize_rates(records, unit))
        except (TypeError, ValueError) as exc:
            warnings.append(f"{source_name.title()} rates are invalid: {exc}")
            slots_by_source.append(())

    candidates = []
    for source_name, source_slots in zip(source_names, slots_by_source):
        for slot in source_slots:
            candidates.append((source_name, slot))

    # Identical intervals and prices are a single authoritative value. Conflicting
    # duplicates and every interval in a partial overlap are ambiguous, so remove
    # all of them rather than keeping whichever source happened to be visited first.
    grouped = {}
    for source_name, slot in candidates:
        key = (slot.start, slot.end)
        grouped.setdefault(key, []).append((source_name, slot))
    unique = sorted(
        ((key, items[0]) for key, items in grouped.items()),
        key=lambda item: (item[1][1].start, item[1][1].end),
    )
    ambiguous_keys = {
        key
        for key, items in grouped.items()
        if any(abs(item[1].price - items[0][1].price) > 1e-12 for item in items[1:])
    }
    if ambiguous_keys:
        warnings.append("Conflicting duplicate rate intervals were excluded as ambiguous.")
    partial_overlap_found = False
    for index, (left_key, (_, left)) in enumerate(unique):
        for right_key, (_, right) in unique[index + 1 :]:
            if right.start >= left.end:
                break
            if left.start < right.end and right.start < left.end:
                ambiguous_keys.add(left_key)
                ambiguous_keys.add(right_key)
                partial_overlap_found = True
    if partial_overlap_found:
        warnings.append("Overlapping rate intervals were excluded because their prices are ambiguous.")
    accepted = [slot for key, (_, slot) in unique if key not in ambiguous_keys]
    ordered = tuple(sorted(accepted, key=lambda slot: (slot.start, slot.end)))
    for left, right in zip(ordered, ordered[1:]):
        if left.end < right.start:
            warnings.append("Published rates contain a gap; the plan uses available prices only.")
            break
    return ordered, warnings, not warnings


def apply_free_session(rates, start, end):
    """Split published intervals at confirmed session boundaries."""
    if start is None or end is None or end <= start:
        return rates
    output = []
    for slot in rates:
        cuts = sorted(
            {
                slot.start,
                slot.end,
                max(slot.start, min(start, slot.end)),
                max(slot.start, min(end, slot.end)),
            }
        )
        for left, right in zip(cuts, cuts[1:]):
            price = min(slot.price, 0.0) if start <= left and right <= end else slot.price
            output.append(RateSlot(left, right, price))
    cursor = start
    gaps = []
    for slot in output:
        if slot.end <= start or slot.start >= end:
            continue
        if slot.start > cursor:
            gaps.append(RateSlot(cursor, min(slot.start, end), 0.0))
        cursor = max(cursor, min(slot.end, end))
    if cursor < end:
        gaps.append(RateSlot(cursor, end, 0.0))
    return tuple(sorted((*output, *gaps), key=lambda slot: slot.start))
