from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

import pytest

from liki.finance import (
    Bar, ContractKind, CostComponent, CostKind, CostTreatment, DeterministicBacktest,
    FeeSchedule, FidelityTier, FillModel, InstrumentSpec, LedgerState, LiquidityRole,
    OrderIntent, OrderType, Side, UnknownContractError, independently_reconcile,
)
from tests.finance.test_accounting import NOW, fill


def engine(*, rates=("0.01",), starting_cash="1000"):
    spec = InstrumentSpec(version="v1", venue="x", instrument_id="BTC", contract_kind=ContractKind.SPOT,
        base_currency="BTC", quote_currency="USD", settlement_currency="USD", tick_size="1",
        lot_size="1", min_quantity="1", min_notional="1", effective_from=NOW)
    fees = tuple(FeeSchedule(version=str(i), venue="x", instrument_id="BTC", account_tier="base",
        liquidity_role=LiquidityRole.TAKER, rate=rate, effective_from=NOW, source="published fixture")
        for i, rate in enumerate(rates))
    return DeterministicBacktest(spec, FillModel("v1", FidelityTier.F0_BAR, Decimal("1"), timedelta()),
                                 Decimal(starting_cash), fee_schedules=fees, account_tier="base")


def bars():
    return [Bar(NOW + timedelta(minutes=i), *(Decimal(p) for _ in range(4)), Decimal("10"),
                NOW + timedelta(minutes=i)) for i, p in enumerate(("100", "110"))]


def signal(side):
    def order(history, when):
        return OrderIntent(client_order_id=when.isoformat(), strategy_id="fixture", venue="x",
            instrument_id="BTC", side=side, quantity="1", order_type=OrderType.MARKET,
            information_cutoff_time=when, signal_ready_time=when, order_eligible_time=when,
            submission_time=when)
    return order


def test_missing_and_ambiguous_historical_fee_policy_fail_closed():
    with pytest.raises(UnknownContractError, match="explicit historical fee"):
        engine(rates=())
    with pytest.raises(UnknownContractError, match="found 2"):
        engine(rates=("0.01", "0.02")).run(bars(), signal(Side.BUY))
    current = engine()
    current.fee_schedules = tuple(f.model_copy(update={"effective_from": NOW + timedelta(days=1)})
                                  for f in current.fee_schedules)
    with pytest.raises(UnknownContractError, match="found 0"):
        current.run(bars(), signal(Side.BUY))


def test_golden_backtest_deducts_historical_fees_and_reconciles_independently():
    result = engine().run(bars(), signal(Side.BUY))
    assert result.ledger.cash == Decimal("787.90")
    assert result.ledger.position == 2
    assert result.ledger.fees == Decimal("2.10")
    assert result.equity_curve[-1][1] == Decimal("1007.90")
    assert independently_reconcile(Decimal("1000"), result.ledger.fills, Decimal("110"))["equity"] == Decimal("1007.90")
    assert result.ledger.reconcile(Decimal("110")) == 0


def test_fee_rebate_is_signed_and_not_clamped_to_zero():
    result = engine(rates=("-0.001",)).run(bars(), signal(Side.BUY))
    assert result.ledger.fees == Decimal("-0.210")
    assert result.equity_curve[-1][1] == Decimal("1010.210")


def test_unfunded_short_and_hidden_cash_leverage_are_rejected():
    short = engine().run(bars(), signal(Side.SELL))
    leveraged = engine(starting_cash="50").run(bars(), signal(Side.BUY))
    assert not short.ledger.fills and len(short.rejection_events) == 2
    assert not leveraged.ledger.fills and len(leveraged.rejection_events) == 2


def test_invalid_cost_does_not_partially_mutate_ledger():
    ledger = LedgerState(Decimal("1000"))
    before = deepcopy(ledger)
    invalid = fill("bad", Side.BUY, "1", "100", costs=(CostComponent(
        CostKind.SPREAD, Decimal("1"), CostTreatment.DECOMPOSITION, CostKind.IMPACT),))
    with pytest.raises(ValueError, match="orphan"):
        ledger.apply(invalid)
    assert ledger == before


def test_reconciliation_detects_cash_projection_drift():
    ledger = LedgerState(Decimal("1000"))
    ledger.apply(fill("one", Side.BUY, "1", "100", "1"))
    assert ledger.reconcile(Decimal("110")) == 0
    ledger.cash += 1
    assert ledger.reconcile(Decimal("110")) == 1
