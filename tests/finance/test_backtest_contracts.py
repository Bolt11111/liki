from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from liki.finance import Bar, CausalHistory, ContractKind, DeterministicBacktest, FXQuote, FeeSchedule, FidelityTier, FillModel, InstrumentSpec, LiquidityRole, Money, OrderIntent, OrderType, Side, TransactionCostAnalysis, UnknownContractError, convert_at, effective_at, fee_amount, select_fee


NOW = datetime(2025, 1, 1, tzinfo=UTC)


def test_effective_dates_and_fee_tier_selection_fail_closed():
    old = FeeSchedule(version="1", venue="x", instrument_id="BTC", account_tier="base", liquidity_role=LiquidityRole.TAKER, rate="0.001", effective_from=NOW - timedelta(days=1), effective_to=NOW, source="published")
    new = FeeSchedule(version="2", venue="x", instrument_id="BTC", account_tier="base", liquidity_role=LiquidityRole.TAKER, rate="0.002", effective_from=NOW, source="published")
    assert select_fee([old, new], venue="x", instrument_id="BTC", account_tier="base", liquidity_role=LiquidityRole.TAKER, when=NOW).rate == Decimal("0.002")
    with pytest.raises(UnknownContractError):
        effective_at([old, old], NOW - timedelta(hours=1))
    assert fee_amount(new, Decimal("100")).amount == Decimal("0.200")


def test_fx_availability_and_tca_residual_are_explicit():
    quote = FXQuote(instrument_id="USDT-USD", source="source", base_currency="USDT", quote_currency="USD", bid="0.99", ask="1.01", observed_at=NOW, available_at=NOW, convention="BID")
    assert convert_at(quote, Money(amount="100", currency="USDT"), "USD", NOW).amount == Decimal("99.00")
    with pytest.raises(UnknownContractError):
        convert_at(quote, Money(amount="100", currency="USDT"), "USD", NOW - timedelta(seconds=1))
    tca = TransactionCostAnalysis(Decimal("100"), Side.BUY, Decimal("2"), Decimal("101"), Decimal("1"), spread=Decimal("1"))
    assert tca.implementation_shortfall == Decimal("3")
    assert tca.decomposition_residual == Decimal("1")


def test_backtest_is_deterministic_and_signal_cannot_receive_current_bar_close():
    spec = InstrumentSpec(version="1", venue="x", instrument_id="BTC", contract_kind=ContractKind.SPOT, base_currency="BTC", quote_currency="USD", settlement_currency="USD", tick_size="1", lot_size="1", min_quantity="1", min_notional="1", effective_from=NOW - timedelta(days=1))
    bars = [
        Bar(NOW, Decimal("100"), Decimal("110"), Decimal("90"), Decimal("109"), Decimal("10"), NOW),
        Bar(NOW + timedelta(minutes=1), Decimal("120"), Decimal("121"), Decimal("119"), Decimal("120"), Decimal("10"), NOW + timedelta(minutes=1)),
    ]
    seen = []
    def signal(history, decision_time):
        seen.append((history.all(), decision_time))
        if not history.all():
            return None
        return OrderIntent(client_order_id="buy", strategy_id="s", venue="x", instrument_id="BTC", side=Side.BUY, quantity="1", order_type=OrderType.MARKET, information_cutoff_time=decision_time, signal_ready_time=decision_time, order_eligible_time=decision_time, submission_time=decision_time)
    fees = [FeeSchedule(version="1", venue="x", instrument_id="BTC", account_tier="base",
                        liquidity_role=LiquidityRole.TAKER, rate="0.001", effective_from=NOW,
                        source="published test fixture")]
    engine = DeterministicBacktest(spec, FillModel("f1", FidelityTier.F0_BAR, Decimal("1"), timedelta()),
                                   Decimal("1000"), fee_schedules=fees, account_tier="base")
    first, second = engine.run(bars, signal), engine.run(bars, signal)
    assert first.equity_curve == second.equity_curve
    assert seen[0][0] == ()
    assert seen[1][0][0].close == Decimal("109")
    assert first.ledger.fills[0].price == Decimal("120")
    assert first.ledger.fees == Decimal("0.120")
    assert first.equity_curve[-1][1] == Decimal("999.880")


def test_revised_or_late_market_data_is_not_an_available_signal_input():
    bars = [
        Bar(NOW - timedelta(minutes=2), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), NOW - timedelta(minutes=2), revised=True),
        Bar(NOW - timedelta(minutes=1), Decimal("2"), Decimal("2"), Decimal("2"), Decimal("2"), Decimal("1"), NOW + timedelta(minutes=1)),
    ]
    assert CausalHistory(bars, NOW).all() == ()
