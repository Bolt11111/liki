from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

import liki.finance.backtest as backtest
from liki.backtest_gate import BacktestPlan, QuoteReplayData, StrategyProgram, replay
from liki.finance import Bar, FidelityTier, Money, OrderIntent, OrderType, Side, UnknownContractError
from liki.finance.contracts import TimeInForce
from liki.finance.execution import MarketSnapshot
from tests.finance.test_accounting import NOW
from tests.finance.test_backtest_costs import bars, engine, signal
from tests.test_backtest_gate import plan_body, program, quote_data


def quote(index, *, bid="99", ask="101", quantity="10"):
    when = NOW + timedelta(minutes=index)
    snapshot = MarketSnapshot(when, Decimal(bid), Decimal(ask), Decimal(quantity),
                              FidelityTier.F1_TRADE_BBO)
    mid = (snapshot.bid + snapshot.ask) / 2
    return Bar(when, mid, mid, mid, mid, snapshot.available_quantity, when,
               FidelityTier.F1_TRADE_BBO, quote=snapshot)


def quote_engine(*, starting_cash="1000", latency=0, participation="1", stress="1"):
    current = engine(starting_cash=starting_cash)
    current.fill_model = replace(current.fill_model, minimum_fidelity=FidelityTier.F1_TRADE_BBO,
        latency=timedelta(seconds=latency), participation_limit=Decimal(participation),
        stress_multiplier=Decimal(stress))
    return current


def order(index, *, side=Side.BUY, **changes):
    when = NOW + timedelta(minutes=index)
    original = signal(side)(None, when)
    return OrderIntent.model_validate({**original.model_dump(), **changes})


def scripted(*intents):
    by_time = {intent.information_cutoff_time: intent for intent in intents}
    return lambda history, when: by_time.get(when)


def test_adverse_sell_costs_reject_without_creating_negative_cash():
    current = quote_engine(starting_cash="203.01")
    current.slippage_bps = Decimal("10000")
    result = current.run([quote(0), quote(1)], scripted(order(0), order(1, side=Side.SELL)))

    # Buying costs 101 + 1.01 + 101; selling would return 99 - .99 - 99.
    assert result.ledger.cash == Decimal("0")
    assert result.ledger.position == Decimal("1")
    assert result.ledger.fees == Decimal("1.01")
    assert result.ledger.other_costs == Decimal("101")
    assert result.equity_curve[-1][1] == Decimal("100")
    assert len(result.ledger.fills) == 1
    assert [row["state"] for row in result.orders] == ["FILLED", "REJECTED"]
    assert len(result.rejection_events) == 1
    assert all(row["cash"] >= 0 for row in result.observations)


@pytest.mark.parametrize("side", [Side.BUY, Side.SELL])
def test_native_price_bands_validate_executable_price_not_midpoint(side):
    current = quote_engine()
    if side == Side.BUY:
        current.spec = current.spec.model_copy(update={"price_upper": Decimal("100")})
        result = current.run([quote(0)], scripted(order(0)))
        assert not result.ledger.fills
        assert result.ledger.cash == Decimal("1000")
        assert result.ledger.position == 0
    else:
        current.spec = current.spec.model_copy(update={"price_lower": Decimal("100")})
        result = current.run([quote(0, bid="100", ask="102"), quote(1)],
                             scripted(order(0), order(1, side=Side.SELL)))
        assert len(result.ledger.fills) == 1
        assert result.ledger.fills[0].price == Decimal("102")
        assert result.ledger.cash == Decimal("896.98")
        assert result.ledger.position == 1
    assert result.orders[-1]["state"] == "REJECTED"
    assert len(result.rejection_events) == 1


def test_order_preserves_requested_and_normalized_quantity_with_consistent_filled_state():
    requested = order(0, quantity="1.5")
    result = quote_engine().run([quote(0)], scripted(requested))
    recorded = result.orders[0]

    assert Decimal(recorded["intent"]["quantity"]) == Decimal("1.5")
    assert Decimal(recorded["normalized_intent"]["quantity"]) == Decimal("1")
    assert recorded["filled_quantity"] == Decimal(recorded["normalized_intent"]["quantity"])
    assert recorded["state"] == "FILLED"
    assert requested.quantity == Decimal("1.5")
    assert result.ledger.position == Decimal("1")
    assert result.ledger.cash == Decimal("897.99")
    assert not result.rejection_events


@pytest.mark.parametrize("unaligned", ["candidate", "benchmark"])
def test_g5_native_program_rejects_non_lot_aligned_quantity(unaligned):
    plan, candidate = plan_body(), program()
    if unaligned == "candidate":
        candidate["quantity"] = "1.5"
    else:
        plan["benchmark"]["quantity"] = "1.5"
    with pytest.raises(ValueError, match="lot|native|quantity"):
        replay(BacktestPlan.model_validate(plan), QuoteReplayData.model_validate(quote_data()),
               StrategyProgram.model_validate(candidate))


def test_deferred_partial_orders_share_each_observations_participation_budget():
    first, second = order(0, quantity="3"), order(1, quantity="2")
    observations = [quote(i, quantity="4") for i in range(4)]
    result = quote_engine(latency=60, participation="0.5").run(
        observations, scripted(first, second))

    assert [(fill.order_id, fill.timestamp, fill.quantity) for fill in result.ledger.fills] == [
        (first.client_order_id, observations[1].timestamp, Decimal("2")),
        (first.client_order_id, observations[2].timestamp, Decimal("1")),
        (second.client_order_id, observations[2].timestamp, Decimal("1")),
        (second.client_order_id, observations[3].timestamp, Decimal("1")),
    ]
    for observation in observations:
        consumed = sum((fill.quantity for fill in result.ledger.fills
                        if fill.timestamp == observation.timestamp), Decimal("0"))
        assert consumed <= Decimal("2")
    assert [row["state"] for row in result.orders] == ["FILLED", "FILLED"]
    assert [row["filled_quantity"] for row in result.orders] == [Decimal("3"), Decimal("2")]
    assert [Decimal(row["normalized_intent"]["quantity"]) for row in result.orders] == [
        Decimal("3"), Decimal("2")]
    assert sum(event["state"] == "PARTIALLY_FILLED" for event in result.events) == 2
    assert result.ledger.position == Decimal("5")
    assert result.ledger.fees == Decimal("5.05")
    assert result.ledger.cash == Decimal("489.95")
    assert not result.rejection_events


def test_fok_insufficient_executable_quantity_never_partially_fills():
    result = quote_engine().run([quote(0, quantity="1")],
        scripted(order(0, quantity="2", time_in_force=TimeInForce.FOK)))
    assert not result.ledger.fills
    assert result.orders[0]["state"] == "CANCELLED"
    assert result.orders[0]["filled_quantity"] == 0
    assert result.ledger.cash == Decimal("1000")
    assert result.ledger.fees == 0


def test_marketable_post_only_limit_rejects_instead_of_taking_liquidity():
    result = quote_engine().run([quote(0)], scripted(order(0, order_type=OrderType.LIMIT,
        limit_price="101", post_only=True)))
    assert not result.ledger.fills
    assert result.orders[0]["state"] == "REJECTED"
    assert result.ledger.cash == Decimal("1000")
    assert len(result.rejection_events) == 1


@pytest.mark.parametrize("side", [Side.BUY, Side.SELL])
def test_adverse_stress_cannot_fill_beyond_limit(side):
    current = quote_engine(stress="3")
    if side == Side.BUY:
        result = current.run([quote(0)], scripted(order(0, order_type=OrderType.LIMIT,
            limit_price="101")))
        assert not result.ledger.fills
        assert result.ledger.cash == Decimal("1000")
    else:
        result = current.run([quote(0), quote(1)], scripted(order(0),
            order(1, side=Side.SELL, order_type=OrderType.LIMIT, limit_price="99")))
        assert len(result.ledger.fills) == 1
        assert result.ledger.fills[0].price == Decimal("103")
        assert result.ledger.cash == Decimal("895.97")
        assert result.ledger.position == 1
    assert result.orders[-1]["state"] == "REJECTED"
    assert len(result.rejection_events) == 1


def test_independent_fee_check_detects_fault_in_primary_calculator(monkeypatch):
    monkeypatch.setattr(backtest, "fee_amount",
                        lambda schedule, notional: Money(amount="0", currency="QUOTE"))
    with pytest.raises(UnknownContractError, match="independent fee accounting disagreement"):
        quote_engine().run([quote(0)], scripted(order(0)))


def test_declared_information_cutoff_cannot_lag_consumed_history():
    def stale_signal(history, when):
        if not history.all():
            return None
        assert history.latest().available_at == NOW
        return order(1, information_cutoff_time=NOW - timedelta(seconds=1))

    with pytest.raises(ValueError, match="cutoff"):
        quote_engine().run([quote(0), quote(1)], stale_signal)


@pytest.mark.parametrize("field", ["timestamp", "available_at"])
def test_naive_market_timestamps_cannot_enter_execution_replay(field):
    observation = bars()[0]
    with pytest.raises(ValueError, match="naive|aware"):
        invalid = replace(observation, **{field: NOW.replace(tzinfo=None)})
        engine().run([invalid], signal(Side.BUY))


@pytest.mark.parametrize("fidelity", [FidelityTier.F1_TRADE_BBO, FidelityTier.F3_SEQ_L2,
                                    FidelityTier.F4_ORDER_LEVEL])
def test_relabeling_ohlc_cannot_fabricate_higher_fidelity_quotes(fidelity):
    relabeled = replace(bars()[0], fidelity=fidelity)
    with pytest.raises(UnknownContractError, match="bid/ask"):
        quote_engine().run([relabeled], signal(Side.BUY))
