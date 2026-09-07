"""Primary Decimal ledger. This module intentionally does not share math with reference.py."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .types import LiquidityRole, Side, ZERO, decimal


class CostKind(StrEnum):
    FEE = "FEE"
    FUNDING = "FUNDING"
    BORROW = "BORROW"
    IMPLEMENTATION_SHORTFALL = "IMPLEMENTATION_SHORTFALL"
    SPREAD = "SPREAD"
    IMPACT = "IMPACT"
    TRANSFER = "TRANSFER"
    LIQUIDATION = "LIQUIDATION"


class CostTreatment(StrEnum):
    ADDITIVE = "ADDITIVE"
    DECOMPOSITION = "DECOMPOSITION"
    DIAGNOSTIC = "DIAGNOSTIC"


@dataclass(frozen=True)
class CostComponent:
    kind: CostKind
    amount: Decimal
    treatment: CostTreatment
    parent: CostKind | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", decimal(self.amount))
        if self.treatment == CostTreatment.DECOMPOSITION and self.parent is None:
            raise ValueError("decomposition needs a parent cost kind")
        if self.treatment != CostTreatment.DECOMPOSITION and self.parent is not None:
            raise ValueError("only decompositions may name a parent")


@dataclass(frozen=True)
class Fill:
    fill_id: str
    order_id: str
    timestamp: datetime
    side: Side
    quantity: Decimal
    price: Decimal
    liquidity_role: LiquidityRole
    fee: Decimal = ZERO
    costs: tuple[CostComponent, ...] = ()

    def __post_init__(self) -> None:
        for name in ("quantity", "price", "fee"):
            value = decimal(getattr(self, name))
            if name != "fee" and value < ZERO:
                raise ValueError(f"{name} must not be negative")
            object.__setattr__(self, name, value)
        if self.quantity <= ZERO or self.price <= ZERO:
            raise ValueError("fill price and quantity must be positive")


@dataclass
class LedgerState:
    cash: Decimal
    position: Decimal = ZERO
    average_entry: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    fees: Decimal = ZERO
    other_costs: Decimal = ZERO
    fills: list[Fill] = field(default_factory=list)
    starting_cash: Decimal = field(init=False)

    def __post_init__(self) -> None:
        for name in ("cash", "position", "average_entry", "realized_pnl", "fees", "other_costs"):
            setattr(self, name, decimal(getattr(self, name)))
        self.starting_cash = self.cash

    def apply(self, fill: Fill) -> None:
        if any(existing.fill_id == fill.fill_id for existing in self.fills):
            raise ValueError("duplicate fill id")
        additive = self._additive_costs(fill.costs)
        signed = fill.side.sign * fill.quantity
        if self.position == ZERO or self.position * signed > ZERO:
            new_abs = abs(self.position) + fill.quantity
            self.average_entry = ((abs(self.position) * self.average_entry) + fill.quantity * fill.price) / new_abs
        elif abs(signed) >= abs(self.position):
            closed = abs(self.position)
            self.realized_pnl += closed * (fill.price - self.average_entry) * (Decimal("1") if self.position > ZERO else Decimal("-1"))
            self.average_entry = fill.price if abs(signed) > abs(self.position) else ZERO
        else:
            self.realized_pnl += fill.quantity * (fill.price - self.average_entry) * (Decimal("1") if self.position > ZERO else Decimal("-1"))
        self.position += signed
        self.cash -= signed * fill.price
        self.cash -= fill.fee
        self.fees += fill.fee
        self.cash -= additive
        self.other_costs += additive
        self.fills.append(fill)

    @staticmethod
    def _additive_costs(costs: tuple[CostComponent, ...]) -> Decimal:
        parents = {c.kind for c in costs if c.treatment == CostTreatment.ADDITIVE}
        for c in costs:
            if c.treatment == CostTreatment.DECOMPOSITION and c.parent in parents:
                continue
            if c.treatment == CostTreatment.DECOMPOSITION:
                raise ValueError("orphan decomposition cannot be authoritative cost")
        return sum((c.amount for c in costs if c.treatment == CostTreatment.ADDITIVE), ZERO)

    def equity(self, mark_price: Decimal) -> Decimal:
        return self.cash + self.position * decimal(mark_price)

    def unrealized_pnl(self, mark_price: Decimal) -> Decimal:
        return self.position * (decimal(mark_price) - self.average_entry)

    def reconcile(self, mark_price: Decimal) -> Decimal:
        expected = (self.starting_cash + self.realized_pnl + self.unrealized_pnl(mark_price)
                    - self.fees - self.other_costs)
        return self.equity(mark_price) - expected


@dataclass(frozen=True)
class TransactionCostAnalysis:
    benchmark_price: Decimal
    side: Side
    quantity: Decimal
    fill_price: Decimal
    explicit_fee: Decimal
    spread: Decimal = ZERO
    impact: Decimal = ZERO
    delay: Decimal = ZERO
    opportunity_cost: Decimal = ZERO

    def __post_init__(self) -> None:
        for field_name in ("benchmark_price", "quantity", "fill_price", "explicit_fee", "spread", "impact", "delay", "opportunity_cost"):
            object.__setattr__(self, field_name, decimal(getattr(self, field_name)))
        if self.quantity < ZERO or self.benchmark_price <= ZERO or self.fill_price <= ZERO:
            raise ValueError("invalid TCA measurement")

    @property
    def implementation_shortfall(self) -> Decimal:
        return self.side.sign * (self.fill_price - self.benchmark_price) * self.quantity + self.explicit_fee

    @property
    def decomposition_residual(self) -> Decimal:
        return self.implementation_shortfall - (self.explicit_fee + self.spread + self.impact + self.delay + self.opportunity_cost)
