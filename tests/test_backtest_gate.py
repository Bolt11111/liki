from copy import deepcopy
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from liki.backtest_gate import BacktestPlan, QuoteReplayData, StrategyProgram, replay
from liki.core import canonical
from tests.test_data_service import NOW


def quote_data():
    start = NOW - timedelta(minutes=6)
    return {"schema_version": "spot-quote-tape-v1", "instrument": {
        "version": "v1", "venue": "binance", "instrument_id": "BTCUSDT", "contract_kind": "SPOT",
        "base_currency": "BTC", "quote_currency": "USDT", "settlement_currency": "USDT",
        "tick_size": "1", "lot_size": "1", "min_quantity": "1", "min_notional": "1",
        "effective_from": start}, "specification_available_at": start,
        "fees": [{"available_at": start, "schedule": {"version": "v1", "venue": "binance",
            "instrument_id": "BTCUSDT", "account_tier": "base", "liquidity_role": "TAKER",
            "rate": "0.01", "effective_from": start, "source": "hand-derived test-only schedule"}}],
        "quotes": [{"timestamp": start + timedelta(minutes=i), "available_at": start + timedelta(minutes=i),
                    "bid": str(price - 1), "ask": str(price + 1), "executable_quantity": "10"}
                   for i, price in enumerate([100, 110, 120, 105, 106, 114, 90])],
        "quantity_semantics": "executable-base-quantity-at-observation"}


def program():
    return {"algorithm": "lagged-momentum-v1", "quantity": "1", "lookback": 1, "threshold": "0"}


def plan_body():
    return {"candidate_artifact_id": "candidate", "candidate_hash": "candidate-hash", "snapshot_id": "snapshot",
        "dataset_artifact_id": "data", "protocol_version": "spot-quote-protocol-v1", "code_hash": "code",
        "environment_fingerprint": "environment", "seed": 0, "reproducibility": "BITWISE",
        "starting_cash": "1000", "account_tier": "base", "execution_model_version": "v1",
        "participation_limit": "1", "latency_seconds": 0, "maximum_observation_gap_seconds": 60,
        "costs": {"version": "v1", "slippage_bps": "10", "impact_bps": "20",
            "estimate_reason": "Test-only explicit conservative fixture, not calibrated market impact",
            "fee": "HISTORICAL_SCHEDULE", "spread": "OBSERVED_BBO_EMBEDDED_IN_FILL",
            "funding": "NOT_APPLICABLE_SPOT", "borrow": "NOT_APPLICABLE_UNLEVERED_LONG_ONLY",
            "financing": "NOT_APPLICABLE_FULLY_FUNDED", "transfer": "NOT_APPLICABLE_SINGLE_VENUE_NO_TRANSFERS",
            "liquidation": "NOT_APPLICABLE_NO_MARGIN", "other": "NOT_APPLICABLE_SUPPORTED_PROTOCOL"},
        "benchmark": {**program(), "algorithm": "buy-hold-v1"}, "tail_confidence": "0.95",
        "scenarios": [{"name": "whole-test-window", "start": NOW - timedelta(minutes=6),
                       "end": NOW + timedelta(seconds=1)}]}


def run(data=None, plan=None):
    return replay(BacktestPlan.model_validate(plan or plan_body()),
                  QuoteReplayData.model_validate(data or quote_data()), StrategyProgram.model_validate(program()))


def test_golden_protocol_has_independent_finances_benchmark_and_complete_outputs():
    result = run()
    candidate, benchmark = result["candidate"], result["benchmark"]
    # Buy 121, sell 105, buy 115; mark the remaining unit at 90.
    assert candidate["net_pnl"] == Decimal("-45.433")
    assert candidate["cost_components"] == {"fee": Decimal("3.41"), "spread": Decimal("3"),
                                              "slippage": Decimal("0.341"), "impact": Decimal("0.682")}
    assert candidate["gross_pnl_before_execution_costs"] == Decimal("-38")
    assert candidate["turnover_notional"] == Decimal("341")
    assert candidate["observations"][-1]["cash"] == Decimal("864.567")
    assert candidate["observations"][-1]["position"] == 1
    assert candidate["observations"][-1]["reference"]["equity"] == Decimal("954.567")
    assert candidate["scenario_slices"][0]["net_pnl"] == candidate["net_pnl"]
    assert benchmark["net_pnl"] == Decimal("-12.313")
    assert [row["state"] for row in candidate["orders"]] == ["FILLED"] * 3
    assert candidate["holding_times"] == [{"quantity": Decimal("1"), "seconds": Decimal("120.0"), "censored": False},
                                          {"quantity": Decimal("1"), "seconds": Decimal("60.0"), "censored": True}]
    assert len(candidate["observations"]) == 7 and len(candidate["events"]) == 9
    assert candidate["drawdown"]["state"] == candidate["tail_loss"]["state"] == "VALUE"
    assert len(candidate["leverage"]) == len(candidate["capacity_observations"]) == 7


def test_protocol_replay_is_byte_identical_across_ambient_decimal_contexts():
    with localcontext() as context:
        context.prec = 8
        low = canonical(run())
    with localcontext() as context:
        context.prec = 50
        high = canonical(run())
    assert low == high


@pytest.mark.parametrize("field", ["starting_cash", "participation_limit", "tail_confidence"])
def test_binary_float_inputs_cannot_be_authoritative_financial_values(field):
    plan = plan_body()
    plan[field] = 0.1
    with pytest.raises(TypeError, match="binary float"):
        run(plan=plan)


def test_non_native_strategy_target_is_explicitly_unsupported():
    strategy = {**program(), "quantity": "1.5"}
    with pytest.raises(ValueError, match="native quantity"):
        replay(BacktestPlan.model_validate(plan_body()), QuoteReplayData.model_validate(quote_data()),
               StrategyProgram.model_validate(strategy))


@pytest.mark.parametrize("component", ["fee", "spread", "slippage_bps", "impact_bps", "funding", "borrow",
                                       "financing", "transfer", "liquidation", "other"])
def test_missing_cost_never_defaults_to_zero(component):
    plan = plan_body()
    del plan["costs"][component]
    with pytest.raises(ValueError):
        run(plan=plan)


@pytest.mark.parametrize("mutation", ["late_fee", "missing_fee", "duplicate_fee", "late_spec", "expired_spec",
                                     "late_quote", "duplicate_quote", "gap", "tick", "derivative", "fx"])
def test_unsupported_or_noncausal_replay_inputs_fail_closed(mutation):
    data = quote_data()
    match mutation:
        case "late_fee":
            data["fees"][0]["available_at"] = NOW
        case "missing_fee":
            data["fees"] = []
        case "duplicate_fee":
            data["fees"].append(deepcopy(data["fees"][0]))
        case "late_spec":
            data["specification_available_at"] = NOW
        case "expired_spec":
            data["instrument"]["effective_to"] = NOW
        case "late_quote":
            data["quotes"][0]["available_at"] = NOW
        case "duplicate_quote":
            data["quotes"].append(data["quotes"][-1])
        case "gap":
            data["quotes"].pop(1)
        case "tick":
            data["instrument"]["tick_size"] = "2"
        case "derivative":
            data["instrument"]["contract_kind"] = "LINEAR_PERPETUAL"
        case "fx":
            data["instrument"]["settlement_currency"] = "USD"
    with pytest.raises(ValueError):
        run(data)


def test_strategy_history_cannot_consume_the_current_quote():
    data = quote_data()
    changed = deepcopy(data)
    changed["quotes"][2].update(bid="9", ask="11")
    original, perturbed = run(data)["candidate"], run(changed)["candidate"]
    assert original["orders"][0]["intent"] == perturbed["orders"][0]["intent"]
    assert original["fills"][0]["price"] == 121 and perturbed["fills"][0]["price"] == 11


def test_delayed_and_partial_orders_retain_terminal_ledger_states():
    plan, data = plan_body(), quote_data()
    plan["latency_seconds"] = 60
    result = run(data, plan)
    benchmark = result["benchmark"]
    assert benchmark["fills"][0]["price"] == 111
    assert benchmark["fills"][0]["timestamp"] == data["quotes"][1]["timestamp"]
    assert any(row["reason"] == "END_OF_REPLAY" for row in result["candidate"]["events"])
    data["quotes"][0]["executable_quantity"] = "0"
    plan["latency_seconds"] = 0
    result = run(data, plan)
    assert result["benchmark"]["orders"][0]["state"] == "CANCELLED"
    assert result["benchmark"]["fills"][0]["price"] == 111


def test_predeclared_regime_windows_partition_pnl_without_resetting_positions():
    plan = plan_body()
    split = NOW - timedelta(minutes=3)
    plan["scenarios"] = [
        {"name": "rising-quote-regime", "start": NOW - timedelta(minutes=6), "end": split},
        {"name": "falling-quote-regime", "start": split, "end": NOW + timedelta(seconds=1)},
    ]
    candidate = run(plan=plan)["candidate"]
    slices = candidate["scenario_slices"]
    assert [item["observations"] for item in slices] == [3, 4]
    assert slices[0]["net_pnl"] == Decimal("-2.573")
    assert slices[1]["net_pnl"] == Decimal("-42.860")
    assert sum(item["net_pnl"] for item in slices) == candidate["net_pnl"]
    assert candidate["observations"][3]["position"] == 1
