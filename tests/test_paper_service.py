from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest

from liki.core import DomainError, uid, utcnow
from liki.finance import ContractKind, FeeSchedule, FidelityTier, FillModel, InstrumentSpec, LiquidityRole, OrderIntent, OrderType, RiskEnvelope, Side
from liki.finance.execution import MarketSnapshot
from liki.paper_service import PaperFill, PaperRunSpec, PaperRunStatus, PaperService, StopRequest, StopScope


def now_contracts():
    now = utcnow()
    instrument = InstrumentSpec(version="i1", venue="paper-x", instrument_id="BTC-USD", contract_kind=ContractKind.SPOT, base_currency="BTC", quote_currency="USD", settlement_currency="USD", tick_size="1", lot_size="1", min_quantity="1", min_notional="1", effective_from=now - timedelta(days=1))
    envelope = RiskEnvelope(version="risk-v1", max_order_notional="100", max_position_notional="100", max_portfolio_notional="100", stale_after_seconds=60)
    fee_schedules = tuple(
        FeeSchedule(version=f"fee-{role.value.lower()}-v1", venue="paper-x", instrument_id="BTC-USD", account_tier="base", liquidity_role=role, rate="0.001", effective_from=now - timedelta(days=1), source="fixture")
        for role in (LiquidityRole.MAKER, LiquidityRole.TAKER)
    )
    run = PaperRunSpec(paper_run_id=uid("RUN"), policy_version="paper-v1", reporting_currency="USD", risk_envelope=envelope, fill_model={"version": "fill-v1", "minimum_fidelity": "F1_TRADE_BBO", "participation_limit": "1", "latency_microseconds": 0, "stress_multiplier": "1"}, instruments=(instrument,), fee_schedules=fee_schedules, fee_account_tier="base")
    snapshot = MarketSnapshot(now, Decimal("9"), Decimal("10"), Decimal("100"), FidelityTier.F1_TRADE_BBO)
    return now, instrument, envelope, run, snapshot


def order(now, client_id, quantity="5", strategy="strategy-a"):
    return OrderIntent(client_order_id=client_id, strategy_id=strategy, venue="paper-x", instrument_id="BTC-USD", side=Side.BUY, quantity=quantity, order_type=OrderType.MARKET, information_cutoff_time=now, signal_ready_time=now, order_eligible_time=now, submission_time=now)


def active_service(store, credentials):
    now, instrument, envelope, run, snapshot = now_contracts()
    service = PaperService(store)
    service.start_run(credentials["paper"], run, "start:" + run.paper_run_id)
    assert service.reconcile(credentials["paper"], run.paper_run_id, "reconcile:" + run.paper_run_id, market_data_valid=True) == PaperRunStatus.ACTIVE
    return service, now, instrument, envelope, run, snapshot


def test_paper_starts_reconcile_only_and_research_cannot_order(store, credentials):
    now, instrument, envelope, run, snapshot = now_contracts()
    service = PaperService(store)
    service.start_run(credentials["paper"], run, "start:" + run.paper_run_id)
    with pytest.raises(DomainError, match="PAPER_RECONCILIATION_REQUIRED"):
        service.submit(credentials["paper"], run.paper_run_id, order(now, uid("client")), instrument, snapshot, envelope, "portfolio")
    with pytest.raises(DomainError, match="capability"):
        service.reconcile(credentials["research"], run.paper_run_id, "bad:" + run.paper_run_id, market_data_valid=True)


def test_atomic_risk_headroom_and_client_intent_idempotency(store, credentials):
    service, now, instrument, envelope, run, snapshot = active_service(store, credentials)
    intents = [order(now, uid("a"), "6"), order(now, uid("b"), "6")]
    def submit(intent):
        try:
            return service.submit(credentials["paper"], run.paper_run_id, intent, instrument, snapshot, envelope, "portfolio")
        except DomainError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, intents))
    assert outcomes.count("PRETRADE_REJECTED") == 1
    assert sum(isinstance(item, str) and item.startswith("PORD-") for item in outcomes) == 1
    accepted = next(item for item in outcomes if item.startswith("PORD-"))
    original = intents[outcomes.index(accepted)]
    assert service.submit(credentials["paper"], run.paper_run_id, original, instrument, snapshot, envelope, "portfolio") == accepted


def test_partial_fill_converts_risk_cancel_releases_working_and_fill_is_idempotent(store, credentials):
    service, now, instrument, envelope, run, snapshot = active_service(store, credentials)
    order_id = service.submit(credentials["paper"], run.paper_run_id, order(now, uid("partial"), "8"), instrument, snapshot, envelope, "portfolio")
    fill = PaperFill(uid("external-fill"), now, Decimal("10"), Decimal("3"), Decimal("0.03"), LiquidityRole.TAKER, "fill-v1")
    first = service.record_fill(credentials["paper"], order_id, fill, "USD")
    assert service.record_fill(credentials["paper"], order_id, fill, "USD") == first
    service.cancel(credentials["paper"], order_id, "cancel:" + order_id)
    with store.transaction(credentials["auditor"]) as (conn, _):
        reservation = conn.execute("SELECT working_amount,position_amount,released_amount,state FROM risk_reservations r JOIN paper_orders o USING(reservation_id) WHERE o.paper_order_id=%s", (order_id,)).fetchone()
        assert reservation == {"working_amount": Decimal("0"), "position_amount": Decimal("30.0"), "released_amount": Decimal("50.0"), "state": "CONVERTED"}
        position = conn.execute("SELECT quantity FROM paper_positions WHERE paper_run_id=%s", (run.paper_run_id,)).fetchone()
        assert position["quantity"] == Decimal("3")


def test_fill_admission_rejects_forged_policy_inputs_and_preserves_exact_replay(store, credentials):
    service, now, instrument, envelope, run, snapshot = active_service(store, credentials)
    order_id = service.submit(credentials["paper"], run.paper_run_id, order(now, uid("pinned-fill"), "5"), instrument, snapshot, envelope, "portfolio")
    valid = PaperFill(uid("accepted-fill"), now, Decimal("10"), Decimal("1"), Decimal("0.01"), LiquidityRole.TAKER, "fill-v1")

    with pytest.raises(DomainError, match="EXECUTION_CONFIG_NOT_PINNED"):
        service.record_fill(credentials["paper"], order_id, PaperFill(uid("forged-model"), now, Decimal("10"), Decimal("1"), Decimal("0.01"), LiquidityRole.TAKER, "forged-v1"), "USD")
    with pytest.raises(DomainError, match="FEE_CONFIG_NOT_PINNED"):
        service.record_fill(credentials["paper"], order_id, PaperFill(uid("forged-fee"), now, Decimal("10"), Decimal("1"), Decimal("0"), LiquidityRole.TAKER, "fill-v1"), "USD")
    with pytest.raises(DomainError, match="FILL_QUOTE_CURRENCY_MISMATCH"):
        service.record_fill(credentials["paper"], order_id, PaperFill(uid("forged-quote"), now, Decimal("10"), Decimal("1"), Decimal("0.01"), LiquidityRole.TAKER, "fill-v1"), "EUR")
    with pytest.raises(DomainError, match="FILL_VENUE_INCREMENT_MISMATCH"):
        service.record_fill(credentials["paper"], order_id, PaperFill(uid("forged-quantity"), now, Decimal("10"), Decimal("1.5"), Decimal("0.015"), LiquidityRole.TAKER, "fill-v1"), "USD")
    with pytest.raises(DomainError, match="EXECUTION_CONFIG_NOT_PINNED"):
        service.simulate_order(credentials["paper"], order_id, snapshot, FillModel("fill-v1", FidelityTier.F1_TRADE_BBO, Decimal("0.5"), timedelta()), run.fee_schedules[1], "USD")

    accepted = service.record_fill(credentials["paper"], order_id, valid, "USD")
    assert service.record_fill(credentials["paper"], order_id, valid, "USD") == accepted


def test_restart_and_scoped_stop_block_intents_without_flattening(store, credentials):
    service, now, instrument, envelope, run, snapshot = active_service(store, credentials)
    assert service.restart(credentials["paper"], run.paper_run_id, "restart:" + run.paper_run_id) == PaperRunStatus.RECONCILE_ONLY
    with pytest.raises(DomainError, match="PAPER_RECONCILIATION_REQUIRED"):
        service.submit(credentials["paper"], run.paper_run_id, order(now, "after-restart"), instrument, snapshot, envelope, "portfolio")
    service.reconcile(credentials["paper"], run.paper_run_id, "reconcile-2:" + run.paper_run_id, market_data_valid=True)
    service.stop(credentials["owner"], run.paper_run_id, StopRequest(scope=StopScope.GLOBAL, reason_code="OWNER_STOP"), "stop:" + run.paper_run_id)
    with pytest.raises(DomainError, match="PAPER_STOP_ACTIVE"):
        service.submit(credentials["paper"], run.paper_run_id, order(now, "stopped"), instrument, snapshot, envelope, "portfolio")
    with pytest.raises(DomainError, match="MANUAL_STOP_REQUIRES_OWNER"):
        service.stop(credentials["paper"], run.paper_run_id, StopRequest(scope=StopScope.STRATEGY, scope_id="strategy-a", reason_code="NO"), "bad-stop:" + run.paper_run_id)


def test_unknown_order_remains_reserved_and_blocks_reconciliation(store, credentials):
    service, now, instrument, envelope, run, snapshot = active_service(store, credentials)
    order_id = service.submit(credentials["paper"], run.paper_run_id, order(now, uid("unknown")), instrument, snapshot, envelope, "portfolio")
    service.mark_unknown(credentials["paper"], order_id, "TRANSPORT_TIMEOUT", "unknown:" + order_id)
    assert service.reconcile(credentials["paper"], run.paper_run_id, "blocked:" + run.paper_run_id, market_data_valid=True) == PaperRunStatus.RECONCILE_ONLY
    with store.transaction(credentials["auditor"]) as (conn, _):
        assert conn.execute("SELECT state FROM risk_reservations r JOIN paper_orders o USING(reservation_id) WHERE o.paper_order_id=%s", (order_id,)).fetchone()["state"] == "UNRECONCILED"


def test_mutation_retries_are_idempotent_and_key_reuse_fails_closed(store, credentials):
    service, now, instrument, envelope, run, snapshot = active_service(store, credentials)
    reconcile_key = "repeat-reconcile:" + run.paper_run_id
    assert service.reconcile(credentials["paper"], run.paper_run_id, reconcile_key, market_data_valid=True) == PaperRunStatus.ACTIVE
    assert service.reconcile(credentials["paper"], run.paper_run_id, reconcile_key, market_data_valid=True) == PaperRunStatus.ACTIVE
    with pytest.raises(DomainError, match="IDEMPOTENCY_CONFLICT"):
        service.reconcile(credentials["paper"], run.paper_run_id, reconcile_key, market_data_valid=False)
    stop_key = "repeat-stop:" + run.paper_run_id
    stop_id = service.stop(credentials["owner"], run.paper_run_id, StopRequest(scope=StopScope.VENUE, scope_id="paper-x", reason_code="TEST"), stop_key)
    assert service.stop(credentials["owner"], run.paper_run_id, StopRequest(scope=StopScope.VENUE, scope_id="paper-x", reason_code="TEST"), stop_key) == stop_id
    with store.transaction(credentials["auditor"]) as (conn, _):
        assert conn.execute("SELECT count(*) AS n FROM emergency_stop_events WHERE emergency_stop_id=%s", (stop_id,)).fetchone()["n"] == 1


def test_repeated_unknown_reconciliation_does_not_accept_changed_reason(store, credentials):
    service, now, instrument, envelope, run, snapshot = active_service(store, credentials)
    order_id = service.submit(credentials["paper"], run.paper_run_id, order(now, uid("unknown-repeat")), instrument, snapshot, envelope, "portfolio")
    operation_key = "unknown:" + order_id
    service.mark_unknown(credentials["paper"], order_id, "TIMEOUT", operation_key)
    service.mark_unknown(credentials["paper"], order_id, "TIMEOUT", operation_key)
    with pytest.raises(DomainError, match="IDEMPOTENCY_CONFLICT"):
        service.mark_unknown(credentials["paper"], order_id, "DIFFERENT_REASON", operation_key)


def test_out_of_order_fill_is_rejected_before_persistent_ledger_mutation(store, credentials):
    service, now, instrument, envelope, run, snapshot = active_service(store, credentials)
    first_order = service.submit(credentials["paper"], run.paper_run_id, order(now, uid("first")), instrument, snapshot, envelope, "portfolio")
    service.record_fill(credentials["paper"], first_order, PaperFill(uid("first-fill"), now, Decimal("10"), Decimal("1"), Decimal("0.01"), LiquidityRole.TAKER, "fill-v1"), "USD")
    second_order = service.submit(credentials["paper"], run.paper_run_id, order(now, uid("second")), instrument, snapshot, envelope, "portfolio")
    with pytest.raises(DomainError, match="FILL_TIME_REGRESSION"):
        service.record_fill(credentials["paper"], second_order, PaperFill(uid("late-fill"), now - timedelta(seconds=1), Decimal("10"), Decimal("1"), Decimal("0.01"), LiquidityRole.TAKER, "fill-v1"), "USD")


def test_local_simulator_is_fee_aware_and_never_requires_network(store, credentials):
    service, now, instrument, envelope, run, snapshot = active_service(store, credentials)
    order_id = service.submit(credentials["paper"], run.paper_run_id, order(now, uid("simulated"), "2"), instrument, snapshot, envelope, "portfolio")
    schedule = run.fee_schedules[1]
    fill_id = service.simulate_order(credentials["paper"], order_id, snapshot, FillModel("fill-v1", FidelityTier.F1_TRADE_BBO, Decimal("1"), timedelta()), schedule, "USD")
    assert fill_id is not None
    with store.transaction(credentials["auditor"]) as (conn, _):
        assert conn.execute("SELECT fee_amount FROM paper_fills WHERE paper_fill_id=%s", (fill_id,)).fetchone()["fee_amount"] == Decimal("0.020")


def test_fill_before_submission_is_rejected_before_ledger_mutation(store, credentials):
    service, now, instrument, envelope, run, snapshot = active_service(store, credentials)
    order_id = service.submit(credentials["paper"], run.paper_run_id, order(now, uid("causal")), instrument, snapshot, envelope, "portfolio")
    early = PaperFill(uid("early"), now - timedelta(seconds=1), Decimal("10"), Decimal("1"), Decimal("0.01"), LiquidityRole.TAKER, "fill-v1")
    with pytest.raises(DomainError, match="FILL_CAUSALITY_VIOLATION"):
        service.record_fill(credentials["paper"], order_id, early, "USD")


def test_global_safety_latch_cancels_only_risk_increasing_orders_and_blocks_future_runs(store, credentials):
    service, now, instrument, envelope, run, snapshot = active_service(store, credentials)
    established = service.submit(credentials["paper"], run.paper_run_id, order(now, uid("establish")), instrument, snapshot, envelope, "portfolio")
    service.record_fill(credentials["paper"], established, PaperFill(uid("establish-fill"), now, Decimal("10"), Decimal("5"), Decimal("0.05"), LiquidityRole.TAKER, "fill-v1"), "USD")
    risky = service.submit(credentials["paper"], run.paper_run_id, order(now, uid("risky")), instrument, snapshot, envelope, "portfolio")
    reducing_intent = order(now, uid("reduce")).model_copy(update={"side": Side.SELL, "reduce_only": True})
    reducing = service.submit(credentials["paper"], run.paper_run_id, reducing_intent, instrument, snapshot, envelope, "reduction")
    request = StopRequest(scope=StopScope.GLOBAL, reason_code="OWNER_GLOBAL_STOP")
    stop_key = "global-stop:" + run.paper_run_id
    latch = service.emergency_stop(credentials["owner"], request, stop_key)
    assert service.emergency_stop(credentials["owner"], request, stop_key) == latch
    with store.transaction(credentials["auditor"]) as (conn, _):
        assert conn.execute("SELECT final_state FROM paper_orders WHERE paper_order_id=%s", (risky,)).fetchone()["final_state"] == "CANCELLED"
        assert conn.execute("SELECT final_state FROM paper_orders WHERE paper_order_id=%s", (reducing,)).fetchone()["final_state"] == "ACKNOWLEDGED"
    _, _, _, future, _ = now_contracts()
    future = future.model_copy(update={"paper_run_id": uid("RUN")})
    service.start_run(credentials["paper"], future, "start:" + future.paper_run_id)
    service.reconcile(credentials["paper"], future.paper_run_id, "reconcile:" + future.paper_run_id, market_data_valid=True)
    with pytest.raises(DomainError, match="PAPER_RECONCILIATION_REQUIRED"):
        service.submit(credentials["paper"], future.paper_run_id, order(now, uid("blocked")), instrument, snapshot, envelope, "portfolio")
    service.release_emergency_stop(credentials["owner"], latch, "OWNER_EXPLICIT_REARM", "global-release:" + run.paper_run_id)
    with pytest.raises(DomainError, match="PAPER_RECONCILIATION_REQUIRED"):
        service.submit(credentials["paper"], future.paper_run_id, order(now, uid("still-fenced")), instrument, snapshot, envelope, "portfolio")
    assert service.reconcile(credentials["paper"], future.paper_run_id, "reconcile-after-release:" + future.paper_run_id, market_data_valid=True) == PaperRunStatus.ACTIVE
