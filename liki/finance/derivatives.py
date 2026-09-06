"""Conservative derivatives valuation and forced-event conversion rules."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from .types import ContractKind, InstrumentSpec, Side, ZERO, decimal


class MarginMode(StrEnum):
    CROSS = "CROSS"
    ISOLATED = "ISOLATED"


@dataclass(frozen=True)
class DerivativePosition:
    side: Side
    contracts: Decimal
    entry_price: Decimal
    spec: InstrumentSpec
    margin_mode: MarginMode
    collateral: Decimal

    def __post_init__(self) -> None:
        for name in ("contracts", "entry_price", "collateral"):
            object.__setattr__(self, name, decimal(getattr(self, name)))
        if self.spec.contract_kind == ContractKind.SPOT or self.contracts <= ZERO or self.entry_price <= ZERO:
            raise ValueError("invalid derivative position")

    def unrealized_pnl(self, mark_price: Decimal) -> Decimal:
        mark = decimal(mark_price)
        if mark <= ZERO:
            raise ValueError("mark must be positive")
        sign = self.side.sign
        if self.spec.contract_kind == ContractKind.LINEAR_PERPETUAL:
            return sign * self.contracts * self.spec.multiplier * (mark - self.entry_price)
        return sign * self.contracts * self.spec.multiplier * (Decimal("1") / self.entry_price - Decimal("1") / mark)

    def notional(self, mark_price: Decimal) -> Decimal:
        return self.contracts * self.spec.multiplier * decimal(mark_price)

    def maintenance_margin(self, mark_price: Decimal) -> Decimal:
        if self.spec.maintenance_margin_rate is None:
            raise ValueError("maintenance margin is unknown; fail closed")
        return self.notional(mark_price) * self.spec.maintenance_margin_rate

    def liquidatable(self, mark_price: Decimal, collateral_haircut: Decimal = ZERO) -> bool:
        haircut = decimal(collateral_haircut)
        if not ZERO <= haircut < Decimal("1"):
            raise ValueError("invalid collateral haircut")
        equity = self.collateral * (Decimal("1") - haircut) + self.unrealized_pnl(mark_price)
        return equity <= self.maintenance_margin(mark_price)

    def funding_payment(self, funding_rate: Decimal, mark_price: Decimal) -> Decimal:
        """Positive funding means longs pay; returned amount is account PnL."""
        return -self.side.sign * self.notional(mark_price) * decimal(funding_rate)


@dataclass(frozen=True)
class ForcedEvent:
    event_type: Literal["LIQUIDATION", "ADL", "DELISTING", "MIGRATION"]
    conversion_price: Decimal
    fee_rate: Decimal
    evidence: Literal["OBSERVED_FACT", "MODEL_ESTIMATE", "UNKNOWN"]

    def convert(self, position: DerivativePosition) -> tuple[Decimal, Decimal]:
        price = decimal(self.conversion_price)
        if price <= ZERO:
            raise ValueError("forced conversion requires a positive documented price")
        pnl = position.unrealized_pnl(price)
        fee = position.notional(price) * decimal(self.fee_rate)
        return pnl, fee
