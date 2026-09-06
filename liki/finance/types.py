"""Strict, serializable financial contracts used by deterministic finance services."""

from __future__ import annotations

from datetime import datetime, UTC
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


DecimalLike = Decimal | str | int
ZERO = Decimal("0")


def decimal(value: DecimalLike) -> Decimal:
    """Parse external numeric values without accepting binary float ambiguity."""
    if isinstance(value, float):
        raise TypeError("binary float is forbidden at an authoritative money boundary")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError("financial value must be finite")
    return result


class FinanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)


class EvidenceKind(StrEnum):
    OBSERVED_FACT = "OBSERVED_FACT"
    DERIVED_VALUE = "DERIVED_VALUE"
    MODEL_ESTIMATE = "MODEL_ESTIMATE"
    UNKNOWN = "UNKNOWN"


class MetricState(StrEnum):
    VALUE = "VALUE"
    UNDEFINED = "UNDEFINED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NUMERIC_ERROR = "NUMERIC_ERROR"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class FidelityTier(StrEnum):
    F0_BAR = "F0_BAR"
    F1_TRADE_BBO = "F1_TRADE_BBO"
    F2_AGG_L2 = "F2_AGG_L2"
    F3_SEQ_L2 = "F3_SEQ_L2"
    F4_ORDER_LEVEL = "F4_ORDER_LEVEL"
    F5_ACCOUNT_OBSERVED = "F5_ACCOUNT_OBSERVED"


class ReproducibilityTier(StrEnum):
    BITWISE = "BITWISE"
    NUMERIC_TOLERANCE = "NUMERIC_TOLERANCE"
    STATISTICAL = "STATISTICAL"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> Decimal:
        return Decimal("1") if self == Side.BUY else Decimal("-1")


class LiquidityRole(StrEnum):
    MAKER = "MAKER"
    TAKER = "TAKER"


class ContractKind(StrEnum):
    SPOT = "SPOT"
    LINEAR_PERPETUAL = "LINEAR_PERPETUAL"
    INVERSE_PERPETUAL = "INVERSE_PERPETUAL"


class Money(FinanceModel):
    amount: Decimal
    currency: str = Field(min_length=1, max_length=16)

    @field_validator("amount", mode="before")
    @classmethod
    def _decimal(cls, value: DecimalLike) -> Decimal:
        return decimal(value)


class BoundedValue(FinanceModel):
    lower: Decimal
    central: Decimal
    upper: Decimal
    evidence_kind: EvidenceKind = EvidenceKind.MODEL_ESTIMATE
    uncertainty_reason: str = Field(min_length=1)

    @field_validator("lower", "central", "upper", mode="before")
    @classmethod
    def _decimal(cls, value: DecimalLike) -> Decimal:
        return decimal(value)

    @model_validator(mode="after")
    def ordered(self) -> BoundedValue:
        if not self.lower <= self.central <= self.upper:
            raise ValueError("bounded value requires lower <= central <= upper")
        return self


class InstrumentSpec(FinanceModel):
    version: str = Field(min_length=1)
    venue: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    contract_kind: ContractKind
    base_currency: str
    quote_currency: str
    settlement_currency: str
    tick_size: Decimal
    lot_size: Decimal
    min_quantity: Decimal
    min_notional: Decimal
    max_quantity: Decimal | None = None
    price_lower: Decimal | None = None
    price_upper: Decimal | None = None
    multiplier: Decimal = Decimal("1")
    initial_margin_rate: Decimal | None = None
    maintenance_margin_rate: Decimal | None = None
    effective_from: datetime
    effective_to: datetime | None = None
    trading_status: Literal["TRADING", "HALTED", "MAINTENANCE"] = "TRADING"

    @field_validator("tick_size", "lot_size", "min_quantity", "min_notional", "max_quantity",
                     "price_lower", "price_upper", "multiplier", "initial_margin_rate",
                     "maintenance_margin_rate", mode="before")
    @classmethod
    def _decimal(cls, value: DecimalLike | None) -> Decimal | None:
        return None if value is None else decimal(value)

    @field_validator("effective_from", "effective_to")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def valid_spec(self) -> InstrumentSpec:
        if min(self.tick_size, self.lot_size, self.min_quantity, self.min_notional, self.multiplier) <= ZERO:
            raise ValueError("instrument increments and multiplier must be positive")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must follow effective_from")
        return self


class FeeSchedule(FinanceModel):
    version: str
    venue: str
    instrument_id: str
    account_tier: str
    liquidity_role: LiquidityRole
    rate: Decimal  # decimal fraction of quote notional, rebate is negative
    effective_from: datetime
    effective_to: datetime | None = None
    source: str = Field(min_length=1)

    @field_validator("rate", mode="before")
    @classmethod
    def _decimal(cls, value: DecimalLike) -> Decimal:
        return decimal(value)

    @field_validator("effective_from", "effective_to")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value


class FXQuote(FinanceModel):
    instrument_id: str
    source: str
    base_currency: str
    quote_currency: str
    bid: Decimal
    ask: Decimal
    observed_at: datetime
    available_at: datetime
    convention: Literal["BID", "ASK", "MID", "MARK"]

    @field_validator("bid", "ask", mode="before")
    @classmethod
    def _decimal(cls, value: DecimalLike) -> Decimal:
        return decimal(value)

    @model_validator(mode="after")
    def valid_quote(self) -> FXQuote:
        if self.bid <= ZERO or self.ask < self.bid:
            raise ValueError("FX quote requires positive bid <= ask")
        if self.available_at < self.observed_at:
            raise ValueError("quote cannot be available before observed")
        return self


def floor_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    return (value / increment).to_integral_value(rounding=ROUND_DOWN) * increment


def ceil_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    return (value / increment).to_integral_value(rounding=ROUND_UP) * increment


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)
