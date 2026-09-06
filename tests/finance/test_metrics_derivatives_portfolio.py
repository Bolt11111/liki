from datetime import datetime, UTC
from decimal import Decimal

import numpy as np
import pytest

from liki.finance import ContractKind, DerivativePosition, InstrumentSpec, MarginMode, MetricState, Side, StrategyOrder, collateral_and_venue_loss, component_risk, expected_shortfall, max_drawdown, net_orders, sharpe, shrunk_covariance, simple_returns


NOW = datetime(2025, 1, 1, tzinfo=UTC)


def perp(kind=ContractKind.LINEAR_PERPETUAL):
    return InstrumentSpec(version="1", venue="x", instrument_id="BTC", contract_kind=kind, base_currency="BTC", quote_currency="USD", settlement_currency="USD", tick_size="1", lot_size="1", min_quantity="1", min_notional="1", multiplier="1", maintenance_margin_rate="0.1", effective_from=NOW)


def test_metric_known_answers_registry_and_exception_states():
    assert simple_returns([Decimal("100"), Decimal("110"), Decimal("99")]) == [Decimal("0.1"), Decimal("-0.1")]
    assert max_drawdown([Decimal("100"), Decimal("120"), Decimal("90")]).value == Decimal("-0.25")
    assert expected_shortfall([Decimal("0.1"), Decimal("-0.2"), Decimal("-0.1")], Decimal("0.5")).value == Decimal("-0.2")
    assert sharpe([Decimal("0.01")], 252).state == MetricState.INSUFFICIENT_DATA
    assert sharpe([Decimal("0.01"), Decimal("0.01")], 252).state == MetricState.UNDEFINED
    with pytest.raises(TypeError):
        simple_returns([Decimal("1"), 1.1])


def test_linear_inverse_margin_funding_and_collateral_stress():
    linear = DerivativePosition(Side.BUY, Decimal("2"), Decimal("100"), perp(), MarginMode.ISOLATED, Decimal("30"))
    assert linear.unrealized_pnl(Decimal("90")) == Decimal("-20")
    assert linear.funding_payment(Decimal("0.01"), Decimal("90")) == Decimal("-1.80")
    assert linear.liquidatable(Decimal("90")) is True
    inverse = DerivativePosition(Side.SELL, Decimal("100"), Decimal("100"), perp(ContractKind.INVERSE_PERPETUAL), MarginMode.CROSS, Decimal("2"))
    assert inverse.unrealized_pnl(Decimal("200")) == Decimal("-0.5")
    assert collateral_and_venue_loss({"USDT": Decimal("100")}, {"USDT": Decimal("0.1")}, {"USDT": Decimal("0.7")}) == (Decimal("10.0"), Decimal("30.0"))


def test_synchronized_netting_shrinkage_and_reverse_stress():
    orders = [StrategyOrder("a", "BTC", "x", Side.BUY, Decimal("2"), Decimal("100")), StrategyOrder("b", "BTC", "x", Side.SELL, Decimal("1"), Decimal("100"))]
    assert net_orders(orders) == {("x", "BTC"): Decimal("1")}
    names, covariance = shrunk_covariance({"a": [0.01, 0.02, -0.01], "b": [0.01, 0.02, -0.01]}, 0.3)
    assert np.linalg.det(covariance) > 0
    contributions = component_risk({"a": Decimal("0.5"), "b": Decimal("0.5")}, covariance, names)
    assert abs(sum(contributions.values()) - Decimal("1")) < Decimal("0.000001")
