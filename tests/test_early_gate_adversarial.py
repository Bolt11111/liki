from datetime import timedelta

import pytest

from liki.core import uid
from liki.early_gate_checks import (
    CapacityObservation,
    G3Plan,
    G4Evidence,
    G4Plan,
    GatePolicy,
    UniverseMembershipRow,
    _gate_four,
    _gate_three,
)
from tests.test_early_gate_checks import (
    NOW,
    _artifact,
    _base,
    _plan,
    _report,
    _snapshot_with_id,
)


def test_g2_empty_feature_evidence_cannot_prove_point_in_time_validity(store, credentials):
    _, candidate_id, _, candidate_artifact, dataset_id = _base(store, credentials)
    labels = _artifact(store, credentials["data"], {
        "dataset_snapshot_ids": [dataset_id],
        "rows": [{
            "label_id": "next-return", "decision_time": NOW.isoformat(),
            "outcome_end_time": (NOW + timedelta(hours=1)).isoformat(),
            "label_available_at": (NOW + timedelta(hours=1)).isoformat(),
        }],
    }, "data/label-timing-v1")
    universe = _artifact(store, credentials["data"], {
        "dataset_snapshot_ids": [dataset_id],
        "rows": [{
            "instrument_id": "BTCUSDT", "effective_from": (NOW - timedelta(days=1)).isoformat(),
            "source_available_at": (NOW - timedelta(days=1)).isoformat(),
            "decision_time": NOW.isoformat(),
        }],
    }, "data/universe-membership-v1")
    valid_features = [{
        "feature_id": "lag", "version": "1", "decision_time": NOW.isoformat(),
        "latest_source_timestamp_used": NOW.isoformat(),
    }]
    reports = []
    for rows in (valid_features, []):
        features = _artifact(store, credentials["data"], {
            "dataset_snapshot_ids": [dataset_id], "rows": rows,
        }, "data/feature-timing-v1")
        snapshot_id = uid("SNAP")
        plan_id = _plan(
            store, credentials, candidate_artifact=candidate_artifact,
            snapshot_id=snapshot_id, gate_id=2,
            body={"g2": {
                "dataset_snapshot_ids": [dataset_id], "feature_timing_artifact_id": features,
                "label_timing_artifact_id": labels, "universe_artifact_id": universe,
            }},
        )
        snapshot, obj = _snapshot_with_id(
            store, credentials, candidate_id, candidate_artifact, dataset_id, snapshot_id,
        )
        reports.append(_report(
            store, credentials, snapshot, obj, 2,
            (plan_id, dataset_id, features, labels, universe),
        ))

    valid, empty = reports
    assert all(valid["checks"].values())
    assert not valid["hard_invalidity"] and not valid["unknowns"]
    assert empty["checks"]["point_in_time"] is False
    assert empty["hard_invalidity"] or empty["unknowns"]


def _economics():
    return {
        "samples": [{
            "sample_id": "a", "dataset_snapshot_id": "dataset-A",
            "observed_at": NOW.isoformat(), "gross_pnl": "12", "fee": "1",
            "spread": "1", "slippage": "1", "funding": "0", "borrow": "0",
            "impact": "1", "other": "0", "currency": "USD",
        }],
        "benchmarks": [{
            "sample_id": "a", "dataset_snapshot_id": "dataset-A", "benchmark_id": "buy-hold",
            "benchmark_version": "v1", "after_cost_pnl": "4", "currency": "USD",
        }],
        "capacity": [{
            "sample_id": "a", "requested_notional": "100", "executable_notional": "100",
            "planned_notional": "90", "currency": "USD",
        }],
    }


def _economics_report(evidence, dataset_ids=("dataset-A",)):
    plan = G4Plan.model_validate({
        "minimum_samples": 1,
        "cost_bounds": {name: ["0", "2"] for name in (
            "fee", "spread", "slippage", "funding", "borrow", "impact", "other",
        )},
        "capacity_limit": "100", "currency": "USD",
        "benchmark_id": "buy-hold", "benchmark_version": "v1",
    })
    policy = GatePolicy.model_validate({
        "policy_version": "v1", "cooldown_hours": {"soft": 6, "medium": 24, "hard": 72},
        "default_failure_severity": "medium",
        "g4_mean_after_cost_lower": "0", "g4_mean_excess_after_cost_lower": "0",
    })
    return _gate_four(plan, policy, {
        "economics": {"schema_name": "finance/cheap-economics-v1", "content": evidence},
    }, snapshot_dataset_ids=dataset_ids)


def test_g4_unambiguous_matched_evidence_retains_exact_economics():
    evidence = _economics()
    G4Evidence.model_validate(evidence)
    checks, hard_invalidity, unknowns, metrics = _economics_report(evidence)
    assert all(checks.values()) and not hard_invalidity and not unknowns
    assert metrics["mean_after_cost_pnl"] == "8"
    assert metrics["mean_excess_after_cost_pnl"] == "4"


@pytest.mark.parametrize("collection", ["benchmarks", "capacity"])
@pytest.mark.parametrize("reverse", [False, True], ids=["contradiction-first", "contradiction-last"])
def test_g4_duplicate_contradictory_ids_never_win_by_row_order(collection, reverse):
    evidence = _economics()
    original = evidence[collection][0]
    conflicting = {**original, **(
        {"after_cost_pnl": "20"} if collection == "benchmarks"
        else {"executable_notional": "95"}
    )}
    evidence[collection] = [conflicting, original]
    if reverse:
        evidence[collection].reverse()
    try:
        G4Evidence.model_validate(evidence)
    except ValueError:
        return
    checks, hard_invalidity, _, _ = _economics_report(evidence)
    assert hard_invalidity is True
    assert not all(checks.values())


def test_g4_benchmark_must_match_its_samples_dataset_not_merely_the_snapshot_set():
    evidence = _economics()
    evidence["benchmarks"][0]["dataset_snapshot_id"] = "dataset-B"
    checks, hard_invalidity, unknowns, _ = _economics_report(
        evidence, dataset_ids=("dataset-A", "dataset-B"),
    )
    assert checks["benchmark_compared"] is False
    assert hard_invalidity or unknowns


def test_capacity_observation_rejects_executable_notional_above_requested():
    observation = _economics()["capacity"][0]
    observation["requested_notional"] = "80"
    with pytest.raises(ValueError):
        CapacityObservation.model_validate(observation)


def test_g4_impossible_capacity_cannot_certify_a_planned_trade():
    evidence = _economics()
    evidence["capacity"][0]["requested_notional"] = "80"
    checks, hard_invalidity, unknowns, _ = _economics_report(evidence)
    assert checks["capacity_feasible"] is False
    assert hard_invalidity or unknowns


def _mechanism_plan():
    return {
        "basis": "MECHANISM", "mechanism": "Inventory pressure temporarily moves prices",
        "payer": "Impatient liquidity takers", "market_structure": "central-limit-order-book",
        "horizon_seconds": 3600,
        "prediction": {
            "outcome_id": "next-return", "prediction": "Positive conditional mean",
            "disconfirming_outcome": "Nonpositive conditional mean", "measurement_method": "Mean",
        },
        "minimum_viable_test": {
            "test_id": "cheap-mean", "dataset_snapshot_ids": ["dataset-A"],
            "sample_unit": "event", "minimum_observations": 10, "outcome_id": "next-return",
        },
        "constraints": ["No live orders"],
    }


def test_g3_nonblank_required_prose_is_a_valid_contract():
    plan = G3Plan.model_validate(_mechanism_plan())
    assert plan.prediction.outcome_id == plan.minimum_viable_test.outcome_id
    assert plan.constraints == ("No live orders",)


@pytest.mark.parametrize("blank", ["", " \t\n"], ids=["empty", "whitespace"])
@pytest.mark.parametrize("field", [
    "mechanism", "payer", "market_structure", "prediction.prediction",
    "prediction.disconfirming_outcome", "prediction.measurement_method",
    "minimum_viable_test.sample_unit", "constraints",
])
def test_g3_rejects_blank_required_prose(field, blank):
    content = _mechanism_plan()
    if field == "constraints":
        content["constraints"].append(blank)
    elif "." in field:
        parent, name = field.split(".")
        content[parent][name] = blank
    else:
        content[field] = blank
    with pytest.raises(ValueError):
        G3Plan.model_validate(content)


@pytest.mark.parametrize("observations", [None, [], ["  "], [1], "not-a-list"])
def test_empirical_pattern_must_actually_declare_observations(observations):
    content = _mechanism_plan()
    content.update({"basis": "EMPIRICAL", "mechanism": None, "payer": None,
                    "empirical_pattern_artifact_id": "pattern"})
    checks, unknowns, _ = _gate_three(G3Plan.model_validate(content), {
        "pattern": {"schema_name": "research/empirical-pattern-v1", "content": {
            "dataset_snapshot_ids": ["dataset-A"], "observations": observations,
        }},
    }, snapshot_dataset_ids=("dataset-A",))
    assert not checks["empirical_or_mechanism_basis"] and unknowns


def test_open_ended_universe_membership_roundtrips_explicit_null():
    row = UniverseMembershipRow(instrument_id="BTCUSDT", effective_from=NOW,
        effective_to=None, source_available_at=NOW, decision_time=NOW)
    assert UniverseMembershipRow.model_validate(row.model_dump(mode="json")) == row
