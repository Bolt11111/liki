from datetime import UTC, datetime, timedelta

from liki.core import uid
from liki.data_service import DataService
from liki.early_gate_checks import check_gate
from liki.evaluation import EvaluationSnapshot, Evaluator
from liki.research import Research, ResearchObject, Trial
from tests.test_data_service import manifest, payload
from tests.test_scheduler import campaign
from liki.scheduler import Scheduler


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _artifact(store, credential, content, schema_name, policy_version="v1"):
    with store.transaction(credential) as (conn, actor):
        return store.put_artifact(
            conn, actor, content, schema_name=schema_name, classification="INTERNAL",
            policy_version=policy_version,
        )


def _policy(store, credentials, *, g4=True):
    body = {
        "policy_version": "v1",
        "cooldown_hours": {"soft": 6, "medium": 24, "hard": 72},
        "default_failure_severity": "medium",
    }
    if g4:
        body.update({"g4_mean_after_cost_lower": "0", "g4_mean_excess_after_cost_lower": "0"})
    return _artifact(store, credentials["governance"], body, "governance/early-gate-policy-v1")


def _base(store, credentials):
    campaign_id = campaign(Scheduler(store), credentials["research"])
    raw = payload()
    dataset_id = DataService(store).persist_dataset(
        credentials["data"], manifest(raw, uid("DATA")), (raw,), operation_key=uid("OP"),
        task_id=campaign_id, policy_version="v1",
    )
    candidate_id = uid("SV")
    candidate_artifact_id = _artifact(
        store, credentials["research"], {"strategy": "lagged-sign", "version": "1"}, "strategy-v1"
    )
    Research(store).register(
        credentials["research"], ResearchObject(
            object_id=candidate_id, object_type="strategy_version", campaign_id=campaign_id,
            artifact_id=candidate_artifact_id,
        )
    )
    with store.transaction(credentials["evaluator"]) as (conn, actor):
        candidate_artifact = store.artifact(conn, actor, candidate_artifact_id)
    return campaign_id, candidate_id, candidate_artifact_id, candidate_artifact, dataset_id


def _plan(store, credentials, *, candidate_artifact, snapshot_id, gate_id, body):
    return _artifact(
        store, credentials["research"],
        {
            "candidate_artifact_id": candidate_artifact["artifact_id"],
            "candidate_hash": candidate_artifact["content_hash"],
            "snapshot_id": snapshot_id,
            "gate_id": gate_id,
            **body,
        },
        "research/early-gate-plan-v1",
    )


def _report(store, credentials, snapshot, obj, gate_id, artifact_ids):
    with store.transaction(credentials["evaluator"]) as (conn, actor):
        return check_gate(store, conn, actor, snapshot, obj, gate_id, artifact_ids)


def test_g1_uses_candidate_hash_and_trial_cache_from_authenticated_database(store, credentials):
    campaign_id, candidate_id, candidate_artifact_id, candidate_artifact, dataset_id = _base(store, credentials)
    policy_id = _policy(store, credentials)
    snapshot_id = uid("SNAP")
    plan_id = _plan(store, credentials, candidate_artifact=candidate_artifact, snapshot_id=snapshot_id, gate_id=1, body={
        "g1": {
            "family_id": "crypto:btc:1h:trend:lag:hour", "family_key": {
                "asset_class": "crypto", "market": "BTCUSDT", "timeframe": "1h",
                "strategy_family": "trend", "signal_family": "lag", "holding_period_bucket": "hour",
            }, "trial_type": "hypothesis", "semantic_configuration": {"rule": "lagged-sign"},
            "dataset_snapshot_ids": [dataset_id], "metric_ids": ["simple-return"],
        },
    })
    snapshot = EvaluationSnapshot(
        snapshot_id=snapshot_id, candidate_artifact_id=candidate_artifact_id,
        candidate_hash=candidate_artifact["content_hash"], dataset_snapshot_ids=(dataset_id,),
        feature_registry_version="v1", label_registry_version="v1", evaluator_version="v1", metric_versions={},
        gate_policy_versions={str(index): "v1" for index in range(14)}, execution_model_version="v1",
        cost_model_version="v1", risk_model_version="v1", statistical_method_versions={},
        environment_fingerprint=store.fingerprint, inference_route_ids=(), rules_by_gate={},
        calibration_artifact_ids=(), minimum_forward_opportunities=1,
        forward_evaluation_at=NOW + timedelta(days=1),
    )
    Evaluator(store).snapshot(credentials["evaluator"], snapshot)
    with store.transaction(credentials["evaluator"]) as (conn, _):
        snapshot_row = conn.execute("SELECT * FROM evaluation_snapshots WHERE snapshot_id=%s", (snapshot_id,)).fetchone()
        obj = conn.execute("SELECT * FROM research_objects WHERE object_id=%s", (candidate_id,)).fetchone()
    missing = _report(store, credentials, snapshot_row, obj, 1, (plan_id, policy_id))
    assert not missing["checks"]["family_history_checked"] and not missing["hard_invalidity"]
    assert "G1_DECLARED_TRIAL_NOT_BOUND" in missing["unknowns"]
    Research(store).trial(credentials["research"], Trial(
        trial_event_id=uid("TRIAL"), campaign_id=campaign_id,
        trial_family_id="crypto:btc:1h:trend:lag:hour", strategy_version_id=candidate_id,
        trial_type="hypothesis", selection_reason="predeclared", semantic_configuration={"rule": "lagged-sign"},
        dataset_snapshot_ids=(dataset_id,), metric_ids=("simple-return",), operation_key=uid("OP"),
    ))
    with store.transaction(credentials["evaluator"]) as (conn, _):
        snapshot_row = conn.execute("SELECT * FROM evaluation_snapshots WHERE snapshot_id=%s", (snapshot_id,)).fetchone()
        obj = conn.execute("SELECT * FROM research_objects WHERE object_id=%s", (candidate_id,)).fetchone()
    report = _report(store, credentials, snapshot_row, obj, 1, (plan_id, policy_id))
    assert all(report["checks"].values())
    assert report["hard_invalidity"] is False
    assert report["input_artifacts"][candidate_artifact_id] == candidate_artifact["content_hash"]

    cached_candidate_artifact = _artifact(
        store, credentials["research"], {"strategy": "different-wrapper", "version": "1"}, "strategy-v1"
    )
    cached_candidate_id = uid("SV")
    Research(store).register(
        credentials["research"], ResearchObject(
            object_id=cached_candidate_id, object_type="strategy_version", campaign_id=campaign_id,
            artifact_id=cached_candidate_artifact,
        )
    )
    Research(store).trial(
        credentials["research"], Trial(
            trial_event_id=uid("TRIAL"), campaign_id=campaign_id,
            trial_family_id="other-family", strategy_version_id=cached_candidate_id,
            trial_type="hypothesis", selection_reason="predeclared",
            semantic_configuration={"rule": "lagged-sign"}, dataset_snapshot_ids=(dataset_id,),
            metric_ids=("simple-return",), operation_key=uid("OP"),
        )
    )
    cached_report = _report(store, credentials, snapshot_row, obj, 1, (plan_id, policy_id))
    assert cached_report["checks"]["not_duplicate"] is False
    assert cached_report["hard_invalidity"] is False
    assert "EQUIVALENT_RESEARCH_NOT_CONCLUSIVELY_REJECTED" in cached_report["unknowns"]
    assert cached_report["derived_metrics"]["equivalent_experiment_count"] == 1

    duplicate_id = uid("SV")
    Research(store).register(
        credentials["research"], ResearchObject(
            object_id=duplicate_id, object_type="strategy_version", campaign_id=campaign_id,
            artifact_id=candidate_artifact_id,
        )
    )
    duplicate_report = _report(store, credentials, snapshot_row, obj, 1, (plan_id, policy_id))
    assert duplicate_report["checks"]["not_duplicate"] is False
    assert duplicate_report["hard_invalidity"] is False
    assert "EQUIVALENT_RESEARCH_NOT_CONCLUSIVELY_REJECTED" in duplicate_report["unknowns"]


def test_g2_revalidates_real_manifest_and_timing_rows(store, credentials):
    _, candidate_id, _, candidate_artifact, dataset_id = _base(store, credentials)
    features = _artifact(store, credentials["data"], {"dataset_snapshot_ids": [dataset_id], "rows": [{
        "feature_id": "lag", "version": "1", "decision_time": NOW.isoformat(),
        "latest_source_timestamp_used": NOW.isoformat(),
    }]}, "data/feature-timing-v1")
    labels = _artifact(store, credentials["data"], {"dataset_snapshot_ids": [dataset_id], "rows": [{
        "label_id": "next-return", "decision_time": NOW.isoformat(),
        "outcome_end_time": (NOW + timedelta(hours=1)).isoformat(),
        "label_available_at": (NOW + timedelta(hours=1)).isoformat(),
    }]}, "data/label-timing-v1")
    universe = _artifact(store, credentials["data"], {"dataset_snapshot_ids": [dataset_id], "rows": [{
        "instrument_id": "BTCUSDT", "effective_from": (NOW - timedelta(days=1)).isoformat(),
        "source_available_at": (NOW - timedelta(days=1)).isoformat(),
        "decision_time": NOW.isoformat(),
    }]}, "data/universe-membership-v1")
    snapshot_id = uid("SNAP")
    plan_id = _plan(store, credentials, candidate_artifact=candidate_artifact, snapshot_id=snapshot_id, gate_id=2, body={
        "g2": {"dataset_snapshot_ids": [dataset_id], "feature_timing_artifact_id": features,
               "label_timing_artifact_id": labels, "universe_artifact_id": universe},
    })
    snapshot, obj = _snapshot_with_id(store, credentials, candidate_id, candidate_artifact, dataset_id, snapshot_id)
    report = _report(store, credentials, snapshot, obj, 2, (plan_id, dataset_id, features, labels, universe))
    assert all(report["checks"].values()) and not report["unknowns"]


def _snapshot_with_id(store, credentials, candidate_id, candidate_artifact, dataset_id, snapshot_id):
    snapshot = EvaluationSnapshot(
        snapshot_id=snapshot_id, candidate_artifact_id=candidate_artifact["artifact_id"],
        candidate_hash=candidate_artifact["content_hash"], dataset_snapshot_ids=(dataset_id,),
        feature_registry_version="v1", label_registry_version="v1", evaluator_version="v1", metric_versions={},
        gate_policy_versions={str(index): "v1" for index in range(14)}, execution_model_version="v1",
        cost_model_version="v1", risk_model_version="v1", statistical_method_versions={},
        environment_fingerprint=store.fingerprint, inference_route_ids=(), rules_by_gate={},
        calibration_artifact_ids=(), minimum_forward_opportunities=1,
        forward_evaluation_at=NOW + timedelta(days=1),
    )
    Evaluator(store).snapshot(credentials["evaluator"], snapshot)
    with store.transaction(credentials["evaluator"]) as (conn, _):
        return (
            conn.execute("SELECT * FROM evaluation_snapshots WHERE snapshot_id=%s", (snapshot_id,)).fetchone(),
            conn.execute("SELECT * FROM research_objects WHERE object_id=%s", (candidate_id,)).fetchone(),
        )


def test_g3_allows_typed_empirical_basis_without_mechanism_narrative(store, credentials):
    _, candidate_id, _, candidate_artifact, dataset_id = _base(store, credentials)
    empirical = _artifact(store, credentials["research"], {
        "dataset_snapshot_ids": [dataset_id], "observations": ["immutable-source-row"]
    }, "research/empirical-pattern-v1")
    snapshot_id = uid("SNAP")
    plan_id = _plan(store, credentials, candidate_artifact=candidate_artifact, snapshot_id=snapshot_id, gate_id=3, body={
        "g3": {"basis": "EMPIRICAL", "empirical_pattern_artifact_id": empirical,
               "market_structure": "central-limit-order-book", "horizon_seconds": 3600,
               "prediction": {"outcome_id": "next-return", "prediction": "positive conditional mean",
                              "disconfirming_outcome": "nonpositive conditional mean", "measurement_method": "mean"},
               "minimum_viable_test": {"test_id": "cheap-mean", "dataset_snapshot_ids": [dataset_id],
                                        "sample_unit": "event", "minimum_observations": 10,
                                        "outcome_id": "next-return"}, "constraints": ["no live orders"]},
    })
    snapshot, obj = _snapshot_with_id(store, credentials, candidate_id, candidate_artifact, dataset_id, snapshot_id)
    report = _report(store, credentials, snapshot, obj, 3, (plan_id, empirical))
    assert all(report["checks"].values()) and not report["hard_invalidity"]


def test_g4_derives_after_cost_and_capacity_from_decimal_samples(store, credentials):
    _, candidate_id, _, candidate_artifact, dataset_id = _base(store, credentials)
    policy_id = _policy(store, credentials)
    economics = _artifact(store, credentials["evaluator"], {
        "samples": [{"sample_id": "a", "dataset_snapshot_id": dataset_id, "observed_at": NOW.isoformat(),
                     "gross_pnl": "12", "fee": "1", "spread": "1", "slippage": "1", "funding": "0",
                     "borrow": "0", "impact": "1", "other": "0", "currency": "USD"}],
        "benchmarks": [{"sample_id": "a", "dataset_snapshot_id": dataset_id, "benchmark_id": "buy-hold",
                        "benchmark_version": "v1", "after_cost_pnl": "4", "currency": "USD"}],
        "capacity": [{"sample_id": "a", "requested_notional": "100", "executable_notional": "100",
                      "planned_notional": "90", "currency": "USD"}],
    }, "finance/cheap-economics-v1")
    snapshot_id = uid("SNAP")
    plan_id = _plan(store, credentials, candidate_artifact=candidate_artifact, snapshot_id=snapshot_id, gate_id=4, body={
        "g4": {"minimum_samples": 1, "cost_bounds": {key: ["0", "2"] for key in (
            "fee", "spread", "slippage", "funding", "borrow", "impact", "other")},
               "capacity_limit": "100", "currency": "USD", "benchmark_id": "buy-hold", "benchmark_version": "v1"},
    })
    snapshot, obj = _snapshot_with_id(store, credentials, candidate_id, candidate_artifact, dataset_id, snapshot_id)
    report = _report(store, credentials, snapshot, obj, 4, (plan_id, policy_id, economics))
    assert all(report["checks"].values())
    assert report["derived_metrics"]["mean_after_cost_pnl"] == "8"
    assert report["derived_metrics"]["mean_excess_after_cost_pnl"] == "4"

    bad_economics = _artifact(store, credentials["evaluator"], {
        **_artifact_content(store, credentials, economics),
        "samples": [{"sample_id": "a", "dataset_snapshot_id": dataset_id, "observed_at": NOW.isoformat(),
                     "gross_pnl": "12", "fee": "3", "spread": "1", "slippage": "1", "funding": "0",
                     "borrow": "0", "impact": "1", "other": "0", "currency": "USD"}],
    }, "finance/cheap-economics-v1")
    bad_report = _report(store, credentials, snapshot, obj, 4, (plan_id, policy_id, bad_economics))
    assert bad_report["checks"]["cost_bounds"] is False and bad_report["hard_invalidity"] is True


def _artifact_content(store, credentials, artifact_id):
    with store.transaction(credentials["evaluator"]) as (conn, actor):
        return store.artifact(conn, actor, artifact_id)["content"]
