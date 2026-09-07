"""Hand-derived G6 execution fixtures, never production market observations."""

import json
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from liki.core import canonical
from liki.finance.economics import evaluate_economics
from liki.finance.economics_contracts import EconomicsPolicy, ExecutionTape
from tests.test_backtest_gate import quote_data, run
from tests.test_data_service import NOW


def profitable_quotes():
    data = quote_data()
    for row, price in zip(data["quotes"], [100, 90, 80, 70, 71, 80, 90], strict=True):
        row.update(bid=str(price - 1), ask=str(price + 1))
    return data


def economics_tape(data=None):
    data = data or profitable_quotes()
    start = data["quotes"][0]["timestamp"]
    quotes = [{**data["quotes"][0], "timestamp": start - timedelta(minutes=1)}] + data["quotes"]
    return {"schema_version": "execution-economics-tape-v1", "venue": "binance", "instrument_id": "BTCUSDT",
        "g5_dataset_artifact_id": "data", "base_fee_tier": "base",
        "rules": [{"specification": {**data["instrument"], "effective_from": start - timedelta(minutes=1)},
            "available_at": start - timedelta(minutes=1), "fee_increment": "0.001", "max_order_notional": "100000",
            "max_position_quantity": "10000", "message_limit": 100, "message_window_ms": 1000,
            "max_price_deviation_bps": "10000", "supported_order_types": ["MARKET"]}],
        "fees": [{"available_at": start - timedelta(minutes=1), "schedule": {**data["fees"][0]["schedule"],
            "rate": "0.001", "effective_from": start - timedelta(minutes=1)}}],
        "account_tiers": [{"tier": "base", "effective_from": start - timedelta(minutes=1),
            "effective_to": None, "available_at": start - timedelta(minutes=1), "basis": "CONSERVATIVE_BASE",
            "source": "test-only published base schedule; no hypothetical volume tier"}],
        "books": [{"event_time": row["timestamp"], "available_at": row["timestamp"],
            "volume_window_start": row["timestamp"] - timedelta(minutes=1), "traded_quantity": "100",
            "bids": [{"price": row["bid"], "quantity": "10"}, {"price": str(Decimal(row["bid"]) - 1), "quantity": "20"}],
            "asks": [{"price": row["ask"], "quantity": "10"}, {"price": str(Decimal(row["ask"]) + 1), "quantity": "20"}],
            "fidelity": "F2_AGG_L2", "sequence_status": "SNAPSHOT_ONLY", "outage": False} for row in quotes],
        "latency_samples": [{"sample_id": f"test-measurement-{index}", "signal_ms": 1,
            "decision_ms": 2, "network_ms": ms, "acknowledgement_ms": ms, "cancel_ms": ms, "market_data_ms": 1}
            for index, ms in enumerate((1, 10, 100))],
        "evidence_kind": "HISTORICAL_PUBLIC", "latency_source": "test-only measured-sample fixture",
        "limitations": ["Test-only public-depth fixture; not actual market calibration or readiness evidence"]}


def economics_policy():
    return {"version": "v1", "size_multipliers": ["0.5", "1", "3"], "participation_limit": "0.1",
        "displayed_depth_fraction": "1", "adverse_depth_fraction": "0.2", "stale_after_ms": 61000,
        "acknowledgement_timeout_ms": 50, "max_gap_ms": 60000, "minimum_fidelity": "F2_AGG_L2",
        "minimum_fill_ratio": "1", "minimum_worst_net_return": "0", "minimum_worst_excess_return": "0",
        "impact": {"version": "v1", "lower_bps": "0", "central_bps": "1", "upper_bps": "2",
            "calibration_raw_hashes": ["training"], "validation_raw_hashes": ["validation"],
            "rationale": "Test-only independent square-root residual-impact observations"}}


def impact_samples(training=True):
    start = NOW - timedelta(days=10 if training else 8)
    return {"schema_version": "execution-impact-samples-v1", "venue": "binance", "instrument_id": "BTCUSDT",
        "observations": [{"episode_id": f"{'training' if training else 'validation'}-{i}",
            "timestamp": start + timedelta(minutes=i), "available_at": start + timedelta(minutes=i),
            "participation": "1", "residual_impact_bps": value}
            for i, value in enumerate(("0", "1", "2") if training else ("0.5", "1", "1.5"))],
        "measurement_basis": "ISOLATED_RESIDUAL_EXCLUDING_FEES_SPREAD_DEPTH_TIMING",
        "evidence": "MODEL_ESTIMATE", "source": "test-only calibration corpus"}


def evaluate(tape=None, policy=None, g5=None):
    return evaluate_economics(json.loads(canonical(g5 or run(profitable_quotes()))),
        ExecutionTape.model_validate(tape or economics_tape()), EconomicsPolicy.model_validate(policy or economics_policy()))


def intended(result, bound="central_bps", adverse=False, rotation=0):
    return next(x for x in result["scenarios"] if x["size_multiplier"] == 1 and x["impact_bound"] == bound
                and x["adverse_fill"] == adverse and x["latency_rotation"] == rotation)["candidate"]


def test_g6_golden_profit_costs_and_capacity_are_independently_reconciled():
    result = evaluate()
    candidate = intended(result)
    # One unit bought at 81 plus one adverse native tick, fee .082; final mid 90.
    assert candidate["net_pnl"] == Decimal("7.918")
    assert candidate["cash"] == Decimal("917.918") and candidate["position"] == 1
    assert candidate["costs"] == {"fee": Decimal(".082"), "spread": Decimal("1"),
        "depth_slippage": 0, "endogenous_impact": Decimal("1"), "timing": 0, "implementation_shortfall": Decimal("2.082")}
    assert candidate["gross_decision_price_pnl"] == 10
    assert candidate["ledger"][-1]["independent"]["cash"] == candidate["cash"]
    assert result["unknowns"] == [] and not result["hard_invalidity"]
    assert len(result["scenarios"]) == 54 and len(result["capacity_curve"]) == 3
    assert result["capacity_curve"][1]["net_return_range"] == [Decimal(".007918"), Decimal(".008919")]
    assert result["latency_percentiles"]["network_ms"] == {"50": 10, "95": 100, "99": 100}


def test_known_friction_erases_apparent_profit_without_double_counting():
    tape = economics_tape()
    tape["fees"][0]["schedule"]["rate"] = "0.15"
    result = evaluate(tape)
    candidate = intended(result)
    assert candidate["gross_decision_price_pnl"] == 10 and candidate["net_pnl"] == Decimal("-4.30")
    assert "G6_AFTER_FRICTION_EDGE_FAILED" in result["failure_reasons"]
    assert candidate["net_pnl"] == candidate["gross_decision_price_pnl"] - candidate["costs"]["implementation_shortfall"]


def test_g6_does_not_modify_g5_or_depend_on_ambient_decimal_context():
    g5 = run(profitable_quotes())
    before = canonical(g5)
    with localcontext() as context:
        context.prec = 8
        low = canonical(evaluate(g5=g5))
    with localcontext() as context:
        context.prec = 64
        high = canonical(evaluate(g5=g5))
    assert low == high and before == canonical(g5)


@pytest.mark.parametrize("failure", ["fee", "tier", "rule", "fidelity", "sequence", "gap", "overlapping_volume", "derivative", "fx"])
def test_unknown_material_inputs_never_become_zero_or_false_precision(failure):
    tape = economics_tape()
    match failure:
        case "fee":
            tape["fees"][0]["available_at"] = NOW + timedelta(days=1)
        case "tier":
            tape["account_tiers"][0]["available_at"] = NOW + timedelta(days=1)
        case "rule":
            tape["rules"].append(deepcopy(tape["rules"][0]))
        case "fidelity":
            for row in tape["books"]:
                row["fidelity"] = "F1_TRADE_BBO"
        case "sequence":
            for row in tape["books"]:
                row["sequence_status"] = "GAP"
        case "gap":
            tape["books"].pop(3)
        case "overlapping_volume":
            tape["books"][3]["volume_window_start"] -= timedelta(minutes=1)
        case "derivative":
            tape["rules"][0]["specification"]["contract_kind"] = "LINEAR_PERPETUAL"
        case "fx":
            tape["rules"][0]["specification"]["settlement_currency"] = "USD"
    with pytest.raises(ValueError):
        evaluate(tape)


def test_every_latency_sample_including_an_interior_spike_is_stressed():
    tape = economics_tape()
    tape["latency_samples"][1]["network_ms"] = 1000000
    result = evaluate(tape)
    spike = intended(result, rotation=1)
    assert spike["fills"] == [] and spike["orders"][0]["reason"] == "LATENCY_BEYOND_EVALUATION_WINDOW"
    assert "G6_EXECUTABLE_CAPACITY_FAILED" in result["failure_reasons"]


def test_zero_and_sublot_depth_do_not_fabricate_fills():
    for depth in ("0", "0.999"):
        tape = economics_tape()
        for book in tape["books"]:
            for level in book["asks"] + book["bids"]:
                level["quantity"] = depth
        result = evaluate(tape)
        assert not intended(result)["fills"] and result["hard_invalidity"]


def test_missing_cost_and_invalid_optimistic_policy_rejected():
    policy = economics_policy()
    del policy["impact"]["upper_bps"]
    with pytest.raises(ValueError):
        evaluate(policy=policy)
    policy = economics_policy()
    policy["minimum_worst_net_return"] = "-1"
    with pytest.raises(ValueError):
        evaluate(policy=policy)


@pytest.mark.parametrize("fault", ["fee", "latency", "quantity", "price"])
def test_independent_path_detects_execution_faults_instead_of_reconciling_corrupted_inputs(monkeypatch, fault):
    from liki.finance import economics

    if fault == "fee":
        original = economics._fee

        def wrong_fee(tape, when):
            schedule, tier = original(tape, when)
            return schedule.model_copy(update={"rate": Decimal("0")}), tier

        monkeypatch.setattr(economics, "_fee", wrong_fee)
    elif fault == "latency":
        original_latency = economics.latency_reference

        def wrong_latency(intent, sample):
            sent, arrival = original_latency(intent, sample)
            return sent, arrival + timedelta(milliseconds=1)

        monkeypatch.setattr(economics, "latency_reference", wrong_latency)
    else:
        original_sweep = economics.sweep

        def wrong_sweep(**kwargs):
            rows = original_sweep(**kwargs)
            if rows:
                rows[0][fault] += 1
            return rows

        monkeypatch.setattr(economics, "sweep", wrong_sweep)
    with pytest.raises(ValueError, match="INDEPENDENT_EXECUTION"):
        evaluate()


def test_coarse_data_cannot_be_relabelled_as_validated_sequence_or_account_fills():
    for fidelity in ("F3_SEQ_L2", "F4_ORDER_LEVEL", "F5_ACCOUNT_OBSERVED"):
        tape = economics_tape()
        for row in tape["books"]:
            row.update(fidelity=fidelity, sequence_status="VALIDATED")
        with pytest.raises(ValueError):
            evaluate(tape)


def test_g6_cannot_silently_change_cash_currency_of_g5_result():
    tape = economics_tape()
    tape["rules"][0]["specification"].update(quote_currency="EUR", settlement_currency="EUR")
    with pytest.raises(ValueError, match="ECONOMIC_UNIT_MISMATCH"):
        evaluate(tape)
