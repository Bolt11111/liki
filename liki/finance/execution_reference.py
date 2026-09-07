"""Independent execution oracles; no production selection, timing or rounding helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext


def _native_round(value: Decimal, increment: Decimal, *, upward: bool = False) -> Decimal:
    numerator, denominator = value.as_integer_ratio()
    step_numerator, step_denominator = increment.as_integer_ratio()
    units, remainder = divmod(numerator * step_denominator, denominator * step_numerator)
    if upward and remainder:
        units += 1
    return Decimal(units) * increment


def sweep_reference(
    *,
    levels: tuple[tuple[Decimal, Decimal], ...],
    requested: Decimal,
    maximum_quantity: Decimal,
    lot_size: Decimal,
    tick_size: Decimal,
    fee_increment: Decimal,
    fee_rate: Decimal,
    impact_bps: Decimal,
    traded_quantity: Decimal,
    side: str,
) -> list[dict[str, Decimal]]:
    if side not in {"BUY", "SELL"}:
        raise ValueError("side must be BUY or SELL")
    inputs = {
        "requested": requested,
        "maximum_quantity": maximum_quantity,
        "lot_size": lot_size,
        "tick_size": tick_size,
        "fee_increment": fee_increment,
        "fee_rate": fee_rate,
        "impact_bps": impact_bps,
        "traded_quantity": traded_quantity,
    }
    for name, value in inputs.items():
        if not value.is_finite():
            raise ValueError(f"{name} must be finite")
        if name in {"lot_size", "tick_size", "fee_increment"}:
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        elif name != "fee_rate" and value < 0:
            raise ValueError(f"{name} must be nonnegative")
    for raw_price, quantity in levels:
        if not raw_price.is_finite() or not quantity.is_finite():
            raise ValueError("level price and quantity must be finite")
        if raw_price <= 0 or quantity < 0:
            raise ValueError("level price must be positive and quantity nonnegative")

    if traded_quantity == 0:
        return []
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        displayed = sum((quantity for _, quantity in levels), Decimal(0))
        remaining = _native_round(min(requested, maximum_quantity, displayed), lot_size)
        allocations: list[tuple[Decimal, Decimal]] = []
        for raw_price, displayed_quantity in levels:
            quantity = _native_round(min(remaining, displayed_quantity), lot_size)
            if quantity:
                allocations.append((raw_price, quantity))
                remaining -= quantity
            if remaining == 0:
                break
        if not allocations:
            return []

        # Impact uses executable lots, not the unswept request or discarded depth dust.
        actual = sum((quantity for _, quantity in allocations), Decimal(0))
        impact = impact_bps * (actual / traded_quantity).sqrt() / Decimal(10000)
        multiplier = Decimal(1) + (impact if side == "BUY" else -impact)
        result = []
        for raw_price, quantity in allocations:
            shifted = raw_price * multiplier
            if shifted <= 0:
                raise ValueError("impact produced a nonpositive price")
            price = _native_round(shifted, tick_size, upward=side == "BUY")
            if price <= 0:
                raise ValueError("tick rounding produced a nonpositive price")
            fee = _native_round(price * quantity * fee_rate, fee_increment, upward=True)
            result.append({"quantity": quantity, "raw_price": raw_price, "price": price, "fee": fee})
        return result


def fee_reference(
    *, fees: list[dict], tiers: list[dict], venue: str, instrument_id: str, when: datetime,
) -> dict[str, str | Decimal]:
    active_tiers = []
    for tier in tiers:
        if tier["effective_from"] <= when and (tier["effective_to"] is None or when < tier["effective_to"]):
            active_tiers.append(tier)
    if len(active_tiers) != 1:
        raise ValueError("unknown or conflicting effective account tier")
    selected_tier = active_tiers[0]
    if selected_tier["available_at"] > when:
        raise ValueError("effective account tier was not yet available")

    matching_fees = []
    for observation in fees:
        schedule = observation["schedule"]
        if (schedule["venue"] != venue or schedule["instrument_id"] != instrument_id
                or schedule["account_tier"] != selected_tier["tier"]
                or schedule["liquidity_role"] != "TAKER"):
            continue
        if schedule["effective_from"] > when:
            continue
        if schedule["effective_to"] is not None and when >= schedule["effective_to"]:
            continue
        matching_fees.append(observation)
    if len(matching_fees) != 1:
        raise ValueError("unknown or conflicting effective taker fee")
    selected_fee = matching_fees[0]
    if selected_fee["available_at"] > when:
        raise ValueError("effective taker fee was not yet available")
    rate = Decimal(selected_fee["schedule"]["rate"])
    if not rate.is_finite():
        raise ValueError("fee rate must be finite")
    return {"fee_version": selected_fee["schedule"]["version"], "rate": rate,
            "account_tier": selected_tier["tier"]}


def latency_reference(intent: dict, sample: dict) -> tuple[datetime, datetime]:
    for component in ("market_data_ms", "signal_ms", "decision_ms", "network_ms"):
        if type(sample[component]) is not int or sample[component] < 0:
            raise ValueError("latency components must be nonnegative integer milliseconds")
    ready = intent["signal_ready_time"] + timedelta(
        milliseconds=sample["market_data_ms"] + sample["signal_ms"] + sample["decision_ms"],
    )
    sent = max(intent["submission_time"], ready)
    return sent, sent + timedelta(milliseconds=sample["network_ms"])
