from datetime import datetime, timedelta, UTC
from decimal import Decimal

import pytest

from liki.finance import FidelityTier, FillModel, InstrumentSpec, OrderIntent, OrderRecord, OrderState, OrderType, RiskEnvelope, Side, StopAction, StopScope, emergency_stop, enforce_emergency_stops, pretrade_check
from liki.finance.execution import MarketSnapshot
from liki.finance.types import ContractKind


NOW = datetime(2025, 1, 1, tzinfo=UTC)


def spec():
    return InstrumentSpec(version="v1", venue="x", instrument_id="BTC-USD", contract_kind=ContractKind.SPOT, base_currency="BTC", quote_currency="USD", settlement_currency="USD", tick_size="0.25", lot_size="0.1", min_quantity="0.1", min_notional="10", effective_from=NOW - timedelta(days=1))


def intent(order_type=OrderType.LIMIT, quantity="1", limit="100"):
    return OrderIntent(client_order_id="id-1", strategy_id="s", venue="x", instrument_id="BTC-USD", side=Side.BUY, quantity=quantity, order_type=order_type, limit_price=limit if order_type == OrderType.LIMIT else None, information_cutoff_time=NOW, signal_ready_time=NOW, order_eligible_time=NOW, submission_time=NOW)


def test_venue_rounding_pretrade_and_paper_only_envelope():
    snapshot = MarketSnapshot(NOW, Decimal("99.9"), Decimal("100"), Decimal("10"), FidelityTier.F1_TRADE_BBO)
    reserve = pretrade_check(intent(quantity="1.01"), spec(), snapshot, RiskEnvelope(version="r1", max_order_notional="1000", max_position_notional="1000", max_portfolio_notional="2000", stale_after_seconds=2), Decimal("0"), Decimal("0"), NOW)
    assert reserve.amount == Decimal("100.0")
    assert reserve.normalized_quantity == Decimal("1.0")
    assert reserve.normalized_limit_price == Decimal("100")
    with pytest.raises(ValueError, match="stale"):
        pretrade_check(intent(), spec(), snapshot, RiskEnvelope(version="r1", max_order_notional="1000", max_position_notional="1000", max_portfolio_notional="2000", stale_after_seconds=1), Decimal("0"), Decimal("0"), NOW + timedelta(seconds=2))


def test_lifecycle_timeout_reconciliation_and_partial_fill_invariants():
    record = OrderRecord(intent()).transition(OrderState.PRETRADE_VALIDATED).transition(OrderState.SUBMITTED).transition(OrderState.UNKNOWN_RECONCILING)
    record = record.transition(OrderState.PARTIALLY_FILLED, fill_quantity=Decimal("0.4"))
    assert record.filled_quantity == Decimal("0.4")
    with pytest.raises(ValueError, match="FILLED requires"):
        record.transition(OrderState.FILLED)
    assert record.transition(OrderState.FILLED, fill_quantity=Decimal("0.6")).state == OrderState.FILLED


def test_fill_model_has_latency_partial_fills_and_fidelity_sequence_guards():
    snapshot = MarketSnapshot(NOW + timedelta(seconds=1), Decimal("99"), Decimal("100"), Decimal("2"), FidelityTier.F1_TRADE_BBO)
    model = FillModel("f1", FidelityTier.F1_TRADE_BBO, Decimal("0.25"), timedelta(seconds=1))
    filled = model.simulate(intent(OrderType.MARKET, "5"), snapshot)
    assert filled is not None and filled.quantity == Decimal("0.50") and filled.price == Decimal("100")
    assert model.simulate(intent(), snapshot) is not None  # This limit is marketable.
    strict = FillModel("f3", FidelityTier.F3_SEQ_L2, Decimal("1"), timedelta(), "bounded FIFO")
    with pytest.raises(ValueError, match="fidelity"):
        strict.simulate(intent(), snapshot)
    bad_book = MarketSnapshot(NOW, Decimal("99"), Decimal("100"), Decimal("2"), FidelityTier.F3_SEQ_L2, False)
    with pytest.raises(ValueError, match="sequence"):
        strict.simulate(intent(), bad_book)


def test_causality_forbids_signal_after_eligibility():
    with pytest.raises(ValueError, match="causality"):
        OrderIntent(client_order_id="late", strategy_id="s", venue="x", instrument_id="i", side=Side.BUY, quantity="1", order_type=OrderType.MARKET, information_cutoff_time=NOW, signal_ready_time=NOW + timedelta(seconds=2), order_eligible_time=NOW, submission_time=NOW + timedelta(seconds=3))


def test_paper_emergency_stop_blocks_only_its_scope_without_implicit_flatten():
    stop = emergency_stop(stop_id="stop-1", scope=StopScope.STRATEGY_STOP, actions=frozenset({StopAction.BLOCK_NEW, StopAction.CANCEL_WORKING, StopAction.RECONCILE}), actor_id="operator", reason="accounting disagreement", activated_at=NOW, policy_version="risk-v1", strategy_id="s")
    with pytest.raises(ValueError, match="stop-1"):
        enforce_emergency_stops(intent(), (stop,))
    other = intent().model_copy(update={"strategy_id": "unaffected"})
    enforce_emergency_stops(other, (stop,))
    assert StopAction.REDUCE_FLATTEN not in stop.actions


def test_global_stop_and_reserved_live_stop_are_fail_closed():
    global_stop = emergency_stop(stop_id="global", scope=StopScope.PAPER_GLOBAL_STOP, actions=frozenset({StopAction.BLOCK_NEW, StopAction.RECONCILE}), actor_id="operator", reason="data corruption", activated_at=NOW, policy_version="risk-v1")
    with pytest.raises(ValueError, match="global"):
        enforce_emergency_stops(intent(), (global_stop,))
    with pytest.raises(ValueError, match="reserved"):
        emergency_stop(stop_id="live", scope=StopScope.FUTURE_LIVE_GLOBAL_STOP, actions=frozenset({StopAction.BLOCK_NEW}), actor_id="operator", reason="test", activated_at=NOW, policy_version="risk-v1")
