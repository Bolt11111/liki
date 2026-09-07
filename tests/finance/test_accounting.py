from datetime import datetime, UTC
from decimal import Decimal

import pytest
from hypothesis import given, strategies as st

from liki.finance import CostComponent, CostKind, CostTreatment, Fill, LedgerState, LiquidityRole, Side, independently_reconcile


NOW = datetime(2025, 1, 1, tzinfo=UTC)


def fill(identifier: str, side: Side, quantity: str, price: str, fee: str = "0", costs=()):
    return Fill(identifier, "order-" + identifier, NOW, side, Decimal(quantity), Decimal(price), LiquidityRole.TAKER, Decimal(fee), costs)


def test_hand_calculated_golden_ledger_and_cost_nonoverlap():
    ledger = LedgerState(Decimal("1000"))
    ledger.apply(fill("1", Side.BUY, "2", "100", "1", (CostComponent(CostKind.IMPLEMENTATION_SHORTFALL, Decimal("3"), CostTreatment.ADDITIVE), CostComponent(CostKind.SPREAD, Decimal("2"), CostTreatment.DECOMPOSITION, CostKind.IMPLEMENTATION_SHORTFALL))))
    ledger.apply(fill("2", Side.SELL, "1", "120", "1"))
    assert ledger.cash == Decimal("915")
    assert ledger.position == Decimal("1")
    assert ledger.realized_pnl == Decimal("20")
    assert ledger.equity(Decimal("110")) == Decimal("1025")
    assert ledger.fees == Decimal("2") and ledger.other_costs == Decimal("3")


def test_orphan_decomposition_and_duplicate_fill_fail_closed():
    ledger = LedgerState(Decimal("0"))
    with pytest.raises(ValueError, match="orphan"):
        ledger.apply(fill("1", Side.BUY, "1", "1", costs=(CostComponent(CostKind.SPREAD, Decimal("1"), CostTreatment.DECOMPOSITION, CostKind.IMPACT),)))
    ledger.apply(fill("2", Side.BUY, "1", "1"))
    with pytest.raises(ValueError, match="duplicate"):
        ledger.apply(fill("2", Side.BUY, "1", "1"))


@given(st.lists(st.tuples(st.sampled_from([Side.BUY, Side.SELL]), st.integers(1, 5), st.integers(1, 500)), min_size=1, max_size=20))
def test_primary_and_independent_fifo_reconcile_marked_equity(trades):
    ledger = LedgerState(Decimal("10000"))
    for index, (side, quantity, price) in enumerate(trades):
        ledger.apply(fill(str(index), side, str(quantity), str(price), "0.01"))
    reference = independently_reconcile(Decimal("10000"), ledger.fills, Decimal("123.45"))
    assert ledger.position == reference["position"]
    assert ledger.equity(Decimal("123.45")) == reference["equity"]
