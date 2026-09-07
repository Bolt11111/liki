"""Effective-dated contract selection and venue-native validation."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from collections.abc import Iterable

from .types import FXQuote, FeeSchedule, InstrumentSpec, LiquidityRole, Money, Side, ZERO, ceil_to_increment, floor_to_increment


class UnknownContractError(ValueError):
    """Fail-closed signal for missing historical instrument, fee, or FX policy."""


def effective_at[T: InstrumentSpec | FeeSchedule](contracts: Iterable[T], when: datetime) -> T:
    matches = [c for c in contracts if c.effective_from <= when and (c.effective_to is None or when < c.effective_to)]
    if len(matches) != 1:
        raise UnknownContractError(f"expected one effective contract at {when.isoformat()}, found {len(matches)}")
    return matches[0]


def select_fee(
    schedules: Iterable[FeeSchedule], *, venue: str, instrument_id: str, account_tier: str,
    liquidity_role: LiquidityRole, when: datetime,
) -> FeeSchedule:
    eligible = [s for s in schedules if (s.venue, s.instrument_id, s.account_tier, s.liquidity_role) ==
                (venue, instrument_id, account_tier, liquidity_role)]
    return effective_at(eligible, when)


def fee_amount(schedule: FeeSchedule, notional: Decimal) -> Money:
    """Calculate a signed fee/rebate only from a historically selected schedule."""
    if notional < ZERO:
        raise ValueError("notional must not be negative")
    return Money(amount=notional * schedule.rate, currency="QUOTE")


def convert_at(quote: FXQuote, amount: Money, reporting_currency: str, valuation_time: datetime) -> Money:
    """Convert only information available at valuation time; no implicit stablecoin parity."""
    if quote.available_at > valuation_time:
        raise UnknownContractError("FX quote was not available at valuation time")
    if amount.currency == reporting_currency:
        return amount
    if amount.currency == quote.base_currency and reporting_currency == quote.quote_currency:
        rate = quote.bid if quote.convention in {"BID", "MID", "MARK"} else quote.ask
        return Money(amount=amount.amount * rate, currency=reporting_currency)
    if amount.currency == quote.quote_currency and reporting_currency == quote.base_currency:
        rate = quote.ask if quote.convention in {"ASK", "MID", "MARK"} else quote.bid
        return Money(amount=amount.amount / rate, currency=reporting_currency)
    raise UnknownContractError("FX quote currencies do not match conversion")


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(StrEnum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class VenueOrder:
    """Small dependency-free canonical order input for deterministic validation."""

    def __init__(self, side: Side, quantity: Decimal, order_type: OrderType, limit_price: Decimal | None,
                 reduce_only: bool = False, post_only: bool = False, time_in_force: TimeInForce = TimeInForce.GTC):
        self.side, self.quantity, self.order_type = side, quantity, order_type
        self.limit_price, self.reduce_only, self.post_only, self.time_in_force = limit_price, reduce_only, post_only, time_in_force


def rounded_order(order: VenueOrder, spec: InstrumentSpec) -> VenueOrder:
    """Use an adverse direction: buys pay up; sells receive down; quantity never grows."""
    quantity = floor_to_increment(order.quantity, spec.lot_size)
    if quantity < spec.min_quantity:
        raise ValueError("quantity rounds below venue minimum")
    price = order.limit_price
    if order.order_type == OrderType.LIMIT:
        if price is None or price <= ZERO:
            raise ValueError("limit order needs positive limit price")
        price = ceil_to_increment(price, spec.tick_size) if order.side == Side.BUY else floor_to_increment(price, spec.tick_size)
    return VenueOrder(order.side, quantity, order.order_type, price, order.reduce_only, order.post_only, order.time_in_force)


def validate_order(order: VenueOrder, spec: InstrumentSpec, reference_price: Decimal, current_position: Decimal = ZERO) -> None:
    if spec.trading_status != "TRADING":
        raise ValueError("instrument is not tradeable")
    if reference_price <= ZERO:
        raise ValueError("reference price must be positive")
    rounded = rounded_order(order, spec)
    if spec.max_quantity is not None and rounded.quantity > spec.max_quantity:
        raise ValueError("quantity exceeds venue maximum")
    price = rounded.limit_price or reference_price
    if spec.price_lower is not None and price < spec.price_lower or spec.price_upper is not None and price > spec.price_upper:
        raise ValueError("price violates venue band")
    if price * rounded.quantity * spec.multiplier < spec.min_notional:
        raise ValueError("notional below venue minimum")
    if rounded.reduce_only and abs(current_position + rounded.side.sign * rounded.quantity) > abs(current_position):
        raise ValueError("reduce-only order can increase exposure")
