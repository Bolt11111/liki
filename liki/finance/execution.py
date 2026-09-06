"""Canonical paper-order lifecycle, causality checks, fills, and atomic reservation contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field, field_validator, model_validator

from .contracts import OrderType, TimeInForce, VenueOrder, rounded_order, validate_order
from .types import FidelityTier, FinanceModel, InstrumentSpec, LiquidityRole, Side, ZERO, decimal


class OrderState(StrEnum):
    INTENT = "INTENT"
    PRETRADE_VALIDATED = "PRETRADE_VALIDATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    UNKNOWN_RECONCILING = "UNKNOWN_RECONCILING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    AMENDED = "AMENDED"
    CANCEL_PENDING = "CANCEL_PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class StopScope(StrEnum):
    STRATEGY_STOP = "STRATEGY_STOP"
    VENUE_STOP = "VENUE_STOP"
    PAPER_GLOBAL_STOP = "PAPER_GLOBAL_STOP"
    FUTURE_LIVE_GLOBAL_STOP = "FUTURE_LIVE_GLOBAL_STOP"


class StopAction(StrEnum):
    BLOCK_NEW = "BLOCK_NEW"
    CANCEL_WORKING = "CANCEL_WORKING"
    RECONCILE = "RECONCILE"
    REDUCE_FLATTEN = "REDUCE_FLATTEN"


class EmergencyStop(FinanceModel):
    """Immutable stop command; flattening requires a separately configured policy."""

    stop_id: str = Field(min_length=1)
    scope: StopScope
    actions: frozenset[StopAction]
    actor_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    activated_at: datetime
    policy_version: str = Field(min_length=1)
    strategy_id: str | None = None
    venue: str | None = None

    @model_validator(mode="after")
    def scoped(self) -> EmergencyStop:
        if not self.actions:
            raise ValueError("emergency stop needs at least one action")
        if self.scope == StopScope.STRATEGY_STOP and not self.strategy_id:
            raise ValueError("strategy stop needs strategy_id")
        if self.scope == StopScope.VENUE_STOP and not self.venue:
            raise ValueError("venue stop needs venue")
        if self.scope in {StopScope.PAPER_GLOBAL_STOP, StopScope.FUTURE_LIVE_GLOBAL_STOP} and (self.strategy_id or self.venue):
            raise ValueError("global stop cannot have strategy or venue scope")
        if StopAction.REDUCE_FLATTEN in self.actions and StopAction.RECONCILE not in self.actions:
            raise ValueError("reduce/flatten requires reconciliation")
        return self

    def applies_to(self, intent: OrderIntent) -> bool:
        return self.scope == StopScope.PAPER_GLOBAL_STOP or (
            self.scope == StopScope.STRATEGY_STOP and self.strategy_id == intent.strategy_id
        ) or (self.scope == StopScope.VENUE_STOP and self.venue == intent.venue)


def emergency_stop(*, stop_id: str, scope: StopScope, actions: frozenset[StopAction], actor_id: str,
                   reason: str, activated_at: datetime, policy_version: str, strategy_id: str | None = None,
                   venue: str | None = None) -> EmergencyStop:
    """Build an inference-free paper stop; this financial package has no live path."""
    if scope == StopScope.FUTURE_LIVE_GLOBAL_STOP:
        raise ValueError("future live stop is reserved; live execution is unavailable")
    return EmergencyStop(stop_id=stop_id, scope=scope, actions=actions, actor_id=actor_id, reason=reason,
                         activated_at=activated_at, policy_version=policy_version, strategy_id=strategy_id, venue=venue)


def enforce_emergency_stops(intent: OrderIntent, stops: tuple[EmergencyStop, ...]) -> None:
    """Pure pretrade guard; the store must atomically read active stops and risk headroom."""
    matching = [stop for stop in stops if stop.applies_to(intent) and StopAction.BLOCK_NEW in stop.actions]
    if matching:
        raise ValueError(f"order blocked by emergency stop: {matching[0].stop_id}")


TERMINAL = {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.EXPIRED}
TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.INTENT: {OrderState.PRETRADE_VALIDATED, OrderState.REJECTED},
    OrderState.PRETRADE_VALIDATED: {OrderState.SUBMITTED, OrderState.REJECTED},
    OrderState.SUBMITTED: {OrderState.ACKNOWLEDGED, OrderState.UNKNOWN_RECONCILING, OrderState.REJECTED},
    OrderState.UNKNOWN_RECONCILING: {OrderState.ACKNOWLEDGED, OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.EXPIRED},
    OrderState.ACKNOWLEDGED: {OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCEL_PENDING, OrderState.CANCELLED, OrderState.EXPIRED, OrderState.UNKNOWN_RECONCILING},
    OrderState.PARTIALLY_FILLED: {OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.AMENDED, OrderState.CANCEL_PENDING, OrderState.CANCELLED, OrderState.EXPIRED},
    OrderState.AMENDED: {OrderState.ACKNOWLEDGED, OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED},
    OrderState.CANCEL_PENDING: {OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.CANCELLED, OrderState.UNKNOWN_RECONCILING},
}


class OrderIntent(FinanceModel):
    client_order_id: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    venue: str
    instrument_id: str
    side: Side
    quantity: Decimal
    order_type: OrderType
    limit_price: Decimal | None = None
    information_cutoff_time: datetime
    signal_ready_time: datetime
    order_eligible_time: datetime
    submission_time: datetime
    reduce_only: bool = False
    post_only: bool = False
    time_in_force: TimeInForce = TimeInForce.GTC

    @field_validator("quantity", "limit_price", mode="before")
    @classmethod
    def _decimal(cls, value: object) -> Decimal | None:
        return None if value is None else decimal(value)  # type: ignore[arg-type]

    @model_validator(mode="after")
    def causal_order(self) -> OrderIntent:
        if self.quantity <= ZERO:
            raise ValueError("order quantity must be positive")
        if not self.information_cutoff_time <= self.signal_ready_time <= self.order_eligible_time <= self.submission_time:
            raise ValueError("causality timestamps are out of order")
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit order requires limit price")
        if self.order_type == OrderType.MARKET and self.limit_price is not None:
            raise ValueError("market order cannot include limit price")
        return self

    def venue_order(self) -> VenueOrder:
        return VenueOrder(self.side, self.quantity, self.order_type, self.limit_price, self.reduce_only, self.post_only, self.time_in_force)


@dataclass(frozen=True)
class MarketSnapshot:
    timestamp: datetime
    bid: Decimal
    ask: Decimal
    available_quantity: Decimal
    fidelity: FidelityTier
    book_sequence_valid: bool = True
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("market timestamp must be aware")
        for name in ("bid", "ask", "available_quantity"):
            object.__setattr__(self, name, decimal(getattr(self, name)))
        if self.bid <= ZERO or self.ask < self.bid or self.available_quantity < ZERO:
            raise ValueError("invalid market snapshot")


@dataclass(frozen=True)
class SimulatedFill:
    quantity: Decimal
    price: Decimal
    role: LiquidityRole
    uncertainty: str | None = None


@dataclass(frozen=True)
class FillModel:
    version: str
    minimum_fidelity: FidelityTier
    participation_limit: Decimal
    latency: timedelta
    queue_assumption: str | None = None
    stress_multiplier: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if not ZERO < self.participation_limit <= Decimal("1") or self.latency < timedelta(0) or self.stress_multiplier < Decimal("1"):
            raise ValueError("invalid fill model bounds")
        if self.minimum_fidelity in {FidelityTier.F3_SEQ_L2, FidelityTier.F4_ORDER_LEVEL} and not self.queue_assumption:
            raise ValueError("queue-sensitive model requires explicit assumption")

    def simulate(self, order: OrderIntent, snapshot: MarketSnapshot) -> SimulatedFill | None:
        if snapshot.timestamp < order.submission_time + self.latency:
            return None
        if snapshot.fidelity < self.minimum_fidelity:
            raise ValueError("insufficient market-data fidelity for fill model")
        if self.minimum_fidelity >= FidelityTier.F2_AGG_L2 and not snapshot.book_sequence_valid:
            raise ValueError("unresolved order-book sequence gap")
        executable = min(order.quantity, snapshot.available_quantity * self.participation_limit)
        if executable <= ZERO:
            return None
        limit = order.limit_price
        marketable = order.order_type == OrderType.MARKET or (
            limit is not None and ((order.side == Side.BUY and limit >= snapshot.ask) or (order.side == Side.SELL and limit <= snapshot.bid))
        )
        if marketable:
            base = snapshot.ask if order.side == Side.BUY else snapshot.bid
            half_spread = (snapshot.ask - snapshot.bid) / Decimal("2")
            price = base + (half_spread * (self.stress_multiplier - Decimal("1")) * order.side.sign)
            return SimulatedFill(executable, price, LiquidityRole.TAKER)
        # A touched limit is not proof of a fill: only observed executable volume qualifies.
        if limit is None:
            raise ValueError("non-marketable market order is invalid")
        touched = (order.side == Side.BUY and limit >= snapshot.bid) or (order.side == Side.SELL and limit <= snapshot.ask)
        if not touched or snapshot.available_quantity == ZERO:
            return None
        uncertainty = "aggregate-depth queue position is unobserved" if snapshot.fidelity < FidelityTier.F4_ORDER_LEVEL else None
        return SimulatedFill(executable, limit, LiquidityRole.MAKER, uncertainty)


@dataclass(frozen=True)
class OrderRecord:
    intent: OrderIntent
    state: OrderState = OrderState.INTENT
    filled_quantity: Decimal = ZERO
    raw_venue_status: str | None = None

    def transition(self, target: OrderState, *, raw_venue_status: str | None = None, fill_quantity: Decimal = ZERO) -> OrderRecord:
        if target not in TRANSITIONS.get(self.state, set()):
            raise ValueError(f"invalid order transition {self.state} -> {target}")
        fill_quantity = decimal(fill_quantity)
        if fill_quantity < ZERO or self.filled_quantity + fill_quantity > self.intent.quantity:
            raise ValueError("invalid cumulative fill quantity")
        cumulative = self.filled_quantity + fill_quantity
        if target == OrderState.FILLED and cumulative != self.intent.quantity:
            raise ValueError("FILLED requires complete quantity")
        if target == OrderState.PARTIALLY_FILLED and not ZERO < cumulative < self.intent.quantity:
            raise ValueError("PARTIALLY_FILLED requires partial quantity")
        return replace(self, state=target, filled_quantity=cumulative, raw_venue_status=raw_venue_status or self.raw_venue_status)


class RiskEnvelope(FinanceModel):
    version: str
    max_order_notional: Decimal
    max_position_notional: Decimal
    max_portfolio_notional: Decimal
    stale_after_seconds: int = Field(ge=0)
    mode: Literal["PAPER", "RESEARCH"] = "PAPER"

    @field_validator("max_order_notional", "max_position_notional", "max_portfolio_notional", mode="before")
    @classmethod
    def _decimal(cls, value: object) -> Decimal:
        value = decimal(value)  # type: ignore[arg-type]
        if value <= ZERO:
            raise ValueError("risk limits must be positive")
        return value


@dataclass(frozen=True)
class Reservation:
    reservation_id: str
    client_order_id: str
    amount: Decimal
    normalized_quantity: Decimal
    normalized_limit_price: Decimal | None
    expires_at: datetime
    envelope_version: str
    state: Literal["HELD", "RELEASED", "CONVERTED"] = "HELD"


def pretrade_check(intent: OrderIntent, spec: InstrumentSpec, snapshot: MarketSnapshot, envelope: RiskEnvelope,
                   current_position: Decimal, current_portfolio_notional: Decimal, now: datetime) -> Reservation:
    if envelope.mode != "PAPER":
        raise ValueError("only paper execution is permitted")
    if intent.submission_time > now or snapshot.timestamp < intent.order_eligible_time:
        raise ValueError("order or market observation is not yet eligible")
    if now - snapshot.timestamp > timedelta(seconds=envelope.stale_after_seconds):
        raise ValueError("stale market data")
    reference = snapshot.ask if intent.side == Side.BUY else snapshot.bid
    normalized = rounded_order(intent.venue_order(), spec)
    validate_order(normalized, spec, reference, current_position)
    order_notional = normalized.quantity * reference * spec.multiplier
    resulting = abs(current_position + intent.side.sign * normalized.quantity) * reference * spec.multiplier
    if order_notional > envelope.max_order_notional or resulting > envelope.max_position_notional:
        raise ValueError("risk envelope exceeded")
    if current_portfolio_notional + order_notional > envelope.max_portfolio_notional:
        raise ValueError("portfolio envelope exceeded")
    return Reservation(intent.client_order_id, intent.client_order_id, order_notional, normalized.quantity,
                       normalized.limit_price, now + timedelta(minutes=5), envelope.version)


class AtomicReservationStore(Protocol):
    """Persistence owner must implement this in one serializable DB transaction."""
    def check_and_hold(self, reservation: Reservation, pool_id: str, remaining_headroom: Decimal) -> None: ...
    def release_or_convert(self, reservation_id: str, state: Literal["RELEASED", "CONVERTED"], actual: Decimal) -> None: ...
