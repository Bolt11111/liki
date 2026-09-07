"""Golden chronological validation cases; market fixtures are test-only."""

import json
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal, localcontext

import pytest

from liki.backtest_gate import QuoteReplayData
from liki.core import canonical, content_hash
from liki.finance.economics_contracts import ExecutionTape
from liki.statistics.oos import OOSDeclaration, evaluate_oos
from tests.test_backtest_gate import run
from tests.test_data_service import NOW
from tests.test_economics_gate import economics_tape, evaluate, profitable_quotes


def future_inputs(start=NOW + timedelta(days=1), interval=timedelta(seconds=1)):
    quotes = profitable_quotes()
    for i, row in enumerate(quotes["quotes"]):
        row.update(timestamp=start + i * interval, available_at=start + i * interval)
    tape = economics_tape(quotes)
    for i, book in enumerate(tape["books"]):
        when = start + (i - 1) * interval
        book.update(event_time=when, available_at=when, volume_window_start=when - interval)
    return quotes, tape


def declaration_body(g5=None, g6=None, start=NOW + timedelta(days=1)):
    return {"protocol_version": "chronological-fixed-program-v1", "snapshot_id": "snapshot",
        "candidate_artifact_id": "candidate", "candidate_hash": "candidate-hash",
        "g5_configuration_hash": content_hash(g5["configuration"] if g5 else run(profitable_quotes())["configuration"]),
        "g6_policy_hash": content_hash(g6["policy"] if g6 else evaluate()["policy"]),
        "g6_execution_tape_hash": content_hash(ExecutionTape.model_validate(economics_tape()).model_dump(mode="json")),
        "quote_dataset_snapshot_id": "oos-quotes", "execution_dataset_snapshot_id": "oos-depth",
        "trial_event_id": "oos-trial", "trial_family_id": "family", "test_start": start,
        "observation_interval_ms": 1000, "observations": 7, "event_horizon_seconds": 1, "embargo_seconds": 1,
        "method_rationale": "Frozen lagged program; chronological future observations with horizon-derived separation",
        "fitting": "NONE_FROZEN_G5_PROGRAM", "initial_state": "CASH_ONLY_COLD_START",
        "scoring": "ALL_G6_SCENARIOS_AT_INTENDED_SIZE", "code_hash": "code"}


def calculate(declaration=None, quotes=None, tape=None, g5=None, g6=None):
    default_quotes, default_tape = future_inputs()
    return evaluate_oos(OOSDeclaration.model_validate(declaration or declaration_body()),
        json.loads(canonical(g5 or run(profitable_quotes()))), json.loads(canonical(g6 or evaluate())),
        QuoteReplayData.model_validate(quotes or default_quotes), ExecutionTape.model_validate(tape or default_tape),
        ExecutionTape.model_validate(economics_tape()))


def test_oos_golden_replays_frozen_program_after_friction_without_development_pnl():
    result = calculate()
    # The independently reconciled single unit costs 82.082 and is marked at 90.
    assert result["score"]["net_return_range"] == [Decimal(".007918"), Decimal(".008919")]
    assert not result["hard_invalidity"] and all(result["checks"].values())
    assert len(result["execution_economics"]["scenarios"]) == 54
    assert result["intent_generation"]["configuration"]["starting_cash"] == "1000"
    assert result["split"]["test_start"] > result["split"]["development_event_end"]
    candidate = next(row["candidate"] for row in result["execution_economics"]["scenarios"]
                     if row["size_multiplier"] == 1 and row["impact_bound"] == "central_bps")
    assert candidate["ledger"][-1]["independent"]["cash"] == candidate["cash"]


def test_oos_cannot_hide_after_cost_failure_by_g5_profitability():
    quotes, tape = future_inputs()
    tape["fees"][0]["schedule"]["rate"] = "0.15"
    result = calculate(quotes=quotes, tape=tape)
    assert result["hard_invalidity"] and "G7_OOS_AFTER_FRICTION_EDGE_FAILED" in result["failure_reasons"]


def test_oos_repeatability_and_immutable_upstream_under_decimal_contexts():
    g5, g6 = run(profitable_quotes()), evaluate()
    original = canonical([g5, g6])
    with localcontext() as ctx:
        ctx.prec = 8
        first = canonical(calculate(g5=g5, g6=g6))
    with localcontext() as ctx:
        ctx.prec = 64
        second = canonical(calculate(g5=g5, g6=g6))
    assert first == second and canonical([g5, g6]) == original


def test_oos_cannot_retune_both_development_and_validation_latency_after_declaration():
    quotes, tape = future_inputs()
    development = economics_tape()
    for source in (tape, development):
        for sample in source["latency_samples"]:
            sample["network_ms"] = 1000
    with pytest.raises(ValueError, match="FROZEN_CONFIGURATION"):
        evaluate_oos(OOSDeclaration.model_validate(declaration_body()),
            json.loads(canonical(run(profitable_quotes()))), json.loads(canonical(evaluate())),
            QuoteReplayData.model_validate(quotes), ExecutionTape.model_validate(tape),
            ExecutionTape.model_validate(development))


@pytest.mark.parametrize("fault,reason", [("grid", "OBSERVATION_GRID"), ("overlap", "EMBARGO_OVERLAP"),
    ("policy", "FROZEN_CONFIGURATION"), ("program", "FROZEN_CONFIGURATION"), ("latency", "ASSUMPTIONS_RETUNED"),
    ("currency", "ECONOMIC_UNIT"), ("synthetic", "ASSUMPTIONS_RETUNED"), ("quotes", "OBSERVATION_CONFLICT"),
    ("depth_grid", "EXECUTION_GRID"), ("warmup", "POST_WARMUP")])
def test_oos_fail_closed_for_leakage_retuning_and_conflicting_sources(fault, reason):
    quotes, tape = future_inputs()
    declaration = declaration_body()
    g5, g6 = run(profitable_quotes()), evaluate()
    if fault == "grid":
        quotes["quotes"].pop(3)
    elif fault == "overlap":
        declaration["test_start"] = NOW + timedelta(seconds=2)
        quotes, tape = future_inputs(declaration["test_start"])
    elif fault == "policy":
        g6["policy"]["minimum_worst_net_return"] = "0.5"
    elif fault == "program":
        g5["configuration"]["starting_cash"] = "2000"
    elif fault == "latency":
        tape["latency_samples"][0]["network_ms"] = 0
    elif fault == "currency":
        quotes["instrument"].update(quote_currency="EUR", settlement_currency="EUR")
    elif fault == "synthetic":
        tape["evidence_kind"] = "SYNTHETIC"
    elif fault == "quotes":
        quotes["quotes"][3]["ask"] = "100"
    elif fault == "depth_grid":
        tape["books"].pop(2)
    elif fault == "warmup":
        g5["strategy"]["lookback"] = 7
    with pytest.raises(ValueError, match=reason):
        calculate(declaration, quotes, tape, g5, g6)


@pytest.mark.parametrize("field,value", [("embargo_seconds", 0), ("observation_interval_ms", 0),
    ("observations", 2), ("observations", True), ("event_horizon_seconds", 10),
    ("fitting", "REFIT_AFTER_OOS"), ("scoring", "BEST_SCENARIO")])
def test_oos_declaration_rejects_undefined_or_adaptive_protocols(field, value):
    body = deepcopy(declaration_body())
    body[field] = value
    with pytest.raises(ValueError):
        OOSDeclaration.model_validate(body)
