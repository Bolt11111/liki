"""Synchronized portfolio construction, netting, robust covariance, and stress views."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from collections.abc import Mapping, Sequence

import numpy as np

from .types import BoundedValue, Side, ZERO, decimal


@dataclass(frozen=True)
class StrategyOrder:
    strategy_id: str
    instrument_id: str
    venue: str
    side: Side
    quantity: Decimal
    price: Decimal

    @property
    def signed_quantity(self) -> Decimal:
        return self.side.sign * decimal(self.quantity)


def net_orders(orders: Sequence[StrategyOrder]) -> dict[tuple[str, str], Decimal]:
    result: dict[tuple[str, str], Decimal] = {}
    for order in orders:
        key = order.venue, order.instrument_id
        result[key] = result.get(key, ZERO) + order.signed_quantity
    return {key: quantity for key, quantity in result.items() if quantity != ZERO}


@dataclass(frozen=True)
class PortfolioRisk:
    gross_notional: Decimal
    net_notional: Decimal
    component_variance: Mapping[str, Decimal]
    expected_shortfall: BoundedValue
    liquidity_at_risk: Decimal
    collateral_loss: Decimal
    trapped_capital: Decimal


def shrunk_covariance(returns: Mapping[str, Sequence[float]], shrinkage: float = 0.2) -> tuple[tuple[str, ...], np.ndarray]:
    if not 0 <= shrinkage <= 1:
        raise ValueError("shrinkage must be in [0, 1]")
    names = tuple(sorted(returns))
    if len(names) < 2 or len({len(returns[name]) for name in names}) != 1 or len(returns[names[0]]) < 2:
        raise ValueError("synchronized returns for at least two strategies are required")
    matrix = np.asarray([returns[name] for name in names], dtype=np.float64)
    if not np.isfinite(matrix).all():
        raise ValueError("return samples must be finite")
    sample = np.cov(matrix, ddof=1)
    target = np.eye(len(names)) * float(np.trace(sample) / len(names))
    return names, (1 - shrinkage) * sample + shrinkage * target


def component_risk(weights: Mapping[str, Decimal], covariance: np.ndarray, names: Sequence[str]) -> dict[str, Decimal]:
    vector = np.asarray([float(decimal(weights[name])) for name in names], dtype=np.float64)
    total = float(vector @ covariance @ vector)
    if total <= 0 or not np.isfinite(total):
        raise ValueError("portfolio variance is undefined")
    marginal = covariance @ vector
    return {name: Decimal(str(vector[i] * marginal[i] / total)) for i, name in enumerate(names)}


def reverse_stress(exposures: Mapping[str, Decimal], shock_returns: Mapping[str, Decimal], equity: Decimal) -> Decimal:
    if decimal(equity) <= ZERO:
        raise ValueError("equity must be positive")
    loss = sum((-decimal(exposures[key]) * decimal(shock_returns.get(key, ZERO)) for key in exposures), ZERO)
    return max(ZERO, loss / decimal(equity))


def collateral_and_venue_loss(collateral: Mapping[str, Decimal], depegs: Mapping[str, Decimal], recovery: Mapping[str, Decimal]) -> tuple[Decimal, Decimal]:
    collateral_loss = ZERO
    trapped = ZERO
    for asset, amount in collateral.items():
        value, depeg, recovered = decimal(amount), decimal(depegs.get(asset, ZERO)), decimal(recovery.get(asset, ZERO))
        if not ZERO <= depeg <= Decimal("1") or not ZERO <= recovered <= Decimal("1"):
            raise ValueError("depeg and recovery must be decimal fractions")
        collateral_loss += value * depeg
        trapped += value * (Decimal("1") - recovered)
    return collateral_loss, trapped
