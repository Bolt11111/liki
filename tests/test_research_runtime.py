"""Acceptance fixtures drive real CLI processes, PostgreSQL, and the operator API."""

import base64
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from liki.core import canonical, uid, utcnow
from liki.server import create_app
from liki.verification import provision_verifier
from tests.test_data_service import NOW, manifest, payload
from tests.test_server import headers


class Runtime:
    def __init__(self, store, credentials, database, directory):
        self.store, self.credentials, self.directory = store, credentials, directory
        self.env = {**os.environ, "LIKI_DATABASE_URL": database["test_app_dsn"]}
        self.files = {}
        for role, credential in credentials.items():
            path = directory / (role + ".token")
            path.write_text(credential.token)
            path.chmod(0o600)
            self.files[role] = path
        self.key_id = uid("KEY")
        self.key_file = directory / "verifier.key"
        key = Ed25519PrivateKey.generate()
        self.key_file.write_bytes(key.private_bytes_raw())
        self.key_file.chmod(0o600)
        with store.transaction(credentials["evaluator"]) as (_, actor):
            principal = actor.principal_id
        provision_verifier(database["test_owner_dsn"], principal_id=principal,
            key_id=self.key_id, public_key=key.public_key().public_bytes_raw())

    def call(self, action, body, role="evaluator", *, error=None):
        request_file = self.directory / (uid("request") + ".json")
        request_file.write_text(canonical({"action": action, "payload": body}))
        result = subprocess.run([sys.executable, "-m", "liki.research_runtime",
            "--credential-file", str(self.files[role]), "--request-file", str(request_file),
            "--verifier-key-id", self.key_id, "--verifier-key-file", str(self.key_file)],
            env=self.env, text=True, capture_output=True, timeout=30)
        assert not result.stderr, result.stderr
        response = json.loads(result.stdout)
        for credential in self.credentials.values():
            assert credential.token not in result.stdout
        if error:
            assert result.returncode == 1 and response["error"] == error, response
        else:
            assert result.returncode == 0, response
        return response

    def artifact(self, content, schema, role="research", policy="v1"):
        return self.call("artifact", {"content": content, "schema_name": schema,
            "classification": "INTERNAL", "policy_version": policy}, role)

    def candidate(self):
        self.campaign_id, self.candidate_id = uid("CAM"), uid("SV")
        self.call("campaign", {"campaign_id": self.campaign_id,
            "purpose": "Test-only predeclared early-screen campaign", "start_rule": "explicit",
            "stopping_rule": "G4 then stop; no orders", "horizon_at": utcnow() + timedelta(days=1),
            "usd_budget": "0", "token_budget": 0, "compute_seconds_budget": "60",
            "statistical_budget": 10}, "research")
        raw = payload()
        self.dataset_id = self.call("dataset", {
            "manifest": manifest(raw, uid("DATA")).model_dump(mode="json"),
            "raw_payloads": [{"metadata": raw.model_dump(mode="json"),
                              "payload_base64": base64.b64encode(raw.payload_bytes).decode()}],
            "operation_key": uid("OP"), "task_id": self.campaign_id, "policy_version": "v1",
        }, "data")["artifact_id"]
        self.candidate_artifact = self.artifact({"research_contract": {
            "objective": "Test after-cost conditional mean", "hypothesis": "Lagged signal predicts next return",
            "metric_id": "net-return", "metric_version": "v1", "unit": "decimal-return", "lower": "0",
            "dataset_snapshot_ids": [self.dataset_id], "evaluator_version": "v1", "mode": "RESEARCH",
            "strategy_version_id": self.candidate_id, "campaign_id": self.campaign_id,
            "market": "BTCUSDT spot", "horizon_seconds": 3600, "constraints": ["No live orders"],
            "expected_artifacts": ["early-screen-report"],
        }}, "strategy-v1")
        self.call("register", {"object_id": self.candidate_id, "object_type": "strategy_version",
            "campaign_id": self.campaign_id, "artifact_id": self.candidate_artifact["artifact_id"]}, "research")
        self.family_id = uid("FAMILY")
        self.call("trial", {"trial_event_id": uid("TRIAL"), "campaign_id": self.campaign_id,
            "trial_family_id": self.family_id, "strategy_version_id": self.candidate_id,
            "trial_type": "hypothesis", "selection_reason": "predeclared fixture",
            "semantic_configuration": {"signal": "lagged-sign"},
            "dataset_snapshot_ids": [self.dataset_id], "metric_ids": ["net-return"],
            "operation_key": uid("OP")}, "research")

    def snapshot(self, *, missing_plan=None, fee="1", basis="EMPIRICAL", sample_count=10, minimum_samples=10):
        snapshot_id = uid("SNAP")
        def artifact(body, schema, role="research"):
            return self.artifact(body, schema, role)["artifact_id"]
        policy = artifact({"policy_version": "v1", "cooldown_hours": {"soft": 6, "medium": 24, "hard": 72},
            "default_failure_severity": "medium", "g4_mean_after_cost_lower": "0",
            "g4_mean_excess_after_cost_lower": "0"}, "governance/early-gate-policy-v1", "governance")
        datasets = [self.dataset_id]
        timing = {}
        for name, rows in {
            "feature-timing": [{"feature_id": "lag", "version": "v1", "decision_time": NOW,
                                "latest_source_timestamp_used": NOW}],
            "label-timing": [{"label_id": "next-return", "decision_time": NOW,
                              "outcome_end_time": NOW + timedelta(hours=1),
                              "label_available_at": NOW + timedelta(hours=1)}],
            "universe-membership": [{"instrument_id": "BTCUSDT", "effective_from": NOW,
                                     "source_available_at": NOW, "decision_time": NOW}],
        }.items():
            timing[name] = artifact({"dataset_snapshot_ids": datasets, "rows": rows}, "data/" + name + "-v1", "data")
        empirical = artifact({"dataset_snapshot_ids": datasets, "observations": ["test-only lagged event"]},
                             "research/empirical-pattern-v1")
        economics = artifact({
            "samples": [{"sample_id": str(i), "dataset_snapshot_id": self.dataset_id, "observed_at": NOW,
                "gross_pnl": "12", "fee": fee, "spread": "1", "slippage": "1", "funding": "0",
                "borrow": "0", "impact": "1", "other": "0", "currency": "USD"} for i in range(sample_count)],
            "benchmarks": [{"sample_id": str(i), "dataset_snapshot_id": self.dataset_id,
                "benchmark_id": "buy-hold", "benchmark_version": "v1", "after_cost_pnl": "4", "currency": "USD"}
                for i in range(sample_count)],
            "capacity": [{"sample_id": str(i), "requested_notional": "100", "executable_notional": "100",
                "planned_notional": "90", "currency": "USD"} for i in range(sample_count)],
        }, "finance/cheap-economics-v1", "evaluator")
        plans = {
            1: {"family_id": self.family_id, "family_key": {"asset_class": "crypto", "market": "BTCUSDT",
                "timeframe": "1h", "strategy_family": "trend", "signal_family": "lag", "holding_period_bucket": "hour"},
                "trial_type": "hypothesis", "semantic_configuration": {"signal": "lagged-sign"},
                "dataset_snapshot_ids": datasets, "metric_ids": ["net-return"]},
            2: {"dataset_snapshot_ids": datasets, "feature_timing_artifact_id": timing["feature-timing"],
                "label_timing_artifact_id": timing["label-timing"], "universe_artifact_id": timing["universe-membership"]},
            3: {"basis": basis, **({"empirical_pattern_artifact_id": empirical} if basis == "EMPIRICAL" else {
                "mechanism": "inventory pressure", "payer": "liquidity demanders"}),
                "market_structure": "central-limit-order-book", "horizon_seconds": 3600,
                "prediction": {"outcome_id": "next-return", "prediction": "positive conditional mean",
                    "disconfirming_outcome": "nonpositive conditional mean", "measurement_method": "mean"},
                "minimum_viable_test": {"test_id": "cheap-mean", "dataset_snapshot_ids": datasets,
                    "sample_unit": "event", "minimum_observations": 10, "outcome_id": "next-return"},
                "constraints": ["No live orders"]},
            4: {"minimum_samples": minimum_samples, "cost_bounds": {name: ["0", "2"] for name in (
                "fee", "spread", "slippage", "funding", "borrow", "impact", "other")},
                "capacity_limit": "100", "currency": "USD", "benchmark_id": "buy-hold", "benchmark_version": "v1"},
        }
        inputs = {"1": [policy], "2": list(timing.values()), "3": [empirical], "4": [policy, economics]}
        for gate, plan in plans.items():
            if gate != missing_plan:
                inputs[str(gate)].append(artifact({"candidate_artifact_id": self.candidate_artifact["artifact_id"],
                    "candidate_hash": self.candidate_artifact["content_hash"], "snapshot_id": snapshot_id,
                    "gate_id": gate, "g" + str(gate): plan}, "research/early-gate-plan-v1"))
        self.call("snapshot", {"snapshot_id": snapshot_id, "candidate_artifact_id": self.candidate_artifact["artifact_id"],
            "candidate_hash": self.candidate_artifact["content_hash"], "dataset_snapshot_ids": datasets,
            "feature_registry_version": "v1", "label_registry_version": "v1", "evaluator_version": "v1",
            "metric_versions": {"net-return": "v1"}, "gate_policy_versions": {str(i): "v1" for i in range(14)},
            "execution_model_version": "v1", "cost_model_version": "v1", "risk_model_version": "v1",
            "statistical_method_versions": {}, "environment_fingerprint": self.store.fingerprint,
            "inference_route_ids": [], "rules_by_gate": {}, "calibration_artifact_ids": [],
            "minimum_forward_opportunities": 10, "forward_evaluation_at": utcnow() + timedelta(days=1),
            "gate_input_artifact_ids": inputs})
        return snapshot_id

    def verification(self, snapshot_id, gate):
        return {"strategy_version_id": self.candidate_id, "snapshot_id": snapshot_id,
                "gate_id": gate, "operation_key": uid("VERIFY")}

    def decision(self, snapshot_id, gate, version):
        verify = self.verification(snapshot_id, gate)
        evidence = self.call("verify", verify)
        assert self.call("verify", verify) == evidence
        return {"strategy_version_id": self.candidate_id, "snapshot_id": snapshot_id, "gate_id": gate,
                "expected_version": version, "evidence_ids": [evidence["evidence_id"]],
                "metrics": [], "operation_key": uid("GATE")}


@pytest.fixture
def runtime(store, credentials, database, tmp_path):
    runtime = Runtime(store, credentials, database, tmp_path)
    runtime.candidate()
    return runtime


@pytest.mark.parametrize("basis", ["EMPIRICAL", "MECHANISM"])
def test_cli_campaign_reaches_g4_with_signed_evidence_and_audited_read_models(runtime, basis):
    snapshot = runtime.snapshot(basis=basis)
    for gate in range(5):
        request = runtime.decision(snapshot, gate, gate)
        result = runtime.call("decide", request)
        assert result["decision"] == "PASS"
        assert runtime.call("decide", request) == result
    assert result["status"] == "PROXY_SURVIVOR" and result["version"] == 5
    runtime.call("verify", runtime.verification(snapshot, 6), error="INVALID_REQUEST")
    client = TestClient(create_app(runtime.store))
    history = client.get("/gates/" + runtime.candidate_id, headers=headers(runtime.credentials)).json()
    assert [row["gate_id"] for row in history] == list(range(5))
    assert [row["state_after"] for row in history] == ["CONTRACTED", "SCREENED", "DATA_VALID", "FEASIBLE", "PROXY_SURVIVOR"]
    assert len({row["event_id"] for row in history}) == 5
    with runtime.store.transaction(runtime.credentials["auditor"]) as (conn, actor):
        executions = conn.execute("SELECT * FROM verifier_executions ORDER BY created_at").fetchall()
        assert len(executions) == 5
        for gate, execution in enumerate(executions):
            assert execution["manifest"]["candidate_state_version"] == gate
            assert runtime.dataset_id in execution["manifest"]["input_artifacts"]
        report = runtime.store.artifact(conn, actor, executions[-1]["report_artifact_id"])["content"]
        assert report["derived_metrics"]["mean_after_cost_pnl"] == "8"
        assert report["derived_metrics"]["mean_excess_after_cost_pnl"] == "4"
    assert runtime.call("audit", {}, "auditor")["status"] == "VERIFIED"


def test_blocked_dependency_reentry_replays_from_g0_without_rewriting_history(runtime):
    old = runtime.snapshot(missing_plan=3)
    for gate in range(4):
        result = runtime.call("decide", runtime.decision(old, gate, gate))
    assert result["decision"] == "BLOCKED" and result["reason"] == "MATERIAL_UNKNOWNS"
    runtime.call("verify", runtime.verification(old, 4), error="GATE_DEPENDENCY_UNSATISFIED")
    new = runtime.snapshot()
    request = {"strategy_version_id": runtime.candidate_id, "snapshot_id": new,
               "expected_version": 4, "reason": "Missing predeclared plan supplied", "operation_key": uid("REENTRY")}
    reentry = runtime.call("reenter", request)
    assert reentry["gate_id"] == -1 and reentry["version"] == 5
    assert runtime.call("reenter", request) == reentry
    runtime.call("verify", runtime.verification(new, 4), error="GATE_DEPENDENCY_UNSATISFIED")
    for gate in range(5):
        assert runtime.call("decide", runtime.decision(new, gate, gate + 5))["decision"] == "PASS"
    with runtime.store.transaction(runtime.credentials["auditor"]) as (conn, _):
        assert conn.execute("SELECT count(*) AS n FROM gate_decisions").fetchone()["n"] == 9
        assert conn.execute("SELECT count(*) AS n FROM event_log WHERE event_type='EVALUATION_REENTERED'").fetchone()["n"] == 1
    outcomes = TestClient(create_app(runtime.store)).get("/gates/outcomes", headers=headers(runtime.credentials)).json()
    assert sum(row["count"] for row in outcomes if row["decision"] == "BLOCKED") == 1
    assert not any(row["decision"] == "FAIL" for row in outcomes)
    assert runtime.call("audit", {}, "auditor")["status"] == "VERIFIED"


def test_fatal_cost_fact_fails_before_backtest_and_cannot_be_downgraded_by_forged_metrics(runtime):
    snapshot = runtime.snapshot(fee="3")
    for gate in range(4):
        assert runtime.call("decide", runtime.decision(snapshot, gate, gate))["decision"] == "PASS"
    request = runtime.decision(snapshot, 4, 4)
    request["metrics"] = [{"metric_id": "forged", "metric_version": "v1", "unit": "USD",
                            "status": "VALUE", "value": "100", "reason": "unbound"}]
    result = runtime.call("decide", request)
    assert result["decision"] == "FAIL" and result["reason"] == "HARD_INVALIDITY"
    runtime.call("reenter", {"strategy_version_id": runtime.candidate_id, "snapshot_id": snapshot,
        "expected_version": 5, "reason": "Try again", "operation_key": uid("REENTRY")},
        error="REENTRY_REQUIRES_BLOCKED_DEPENDENCY")
    with runtime.store.transaction(runtime.credentials["auditor"]) as (conn, _):
        assert not conn.execute("SELECT 1 FROM verifier_executions WHERE gate_id>=5").fetchone()
    from liki.early_gate_checks import G1Plan, GatePolicy, _gate_one
    equivalent_id, other_family = uid("SV"), uid("FAMILY")
    artifact = runtime.artifact({"strategy": "equivalent wrapper"}, "strategy-v1")
    runtime.call("register", {"object_id": equivalent_id, "object_type": "strategy_version",
        "campaign_id": runtime.campaign_id, "artifact_id": artifact["artifact_id"]}, "research")
    runtime.call("trial", {"trial_event_id": uid("TRIAL"), "campaign_id": runtime.campaign_id,
        "trial_family_id": other_family, "strategy_version_id": equivalent_id, "trial_type": "hypothesis",
        "selection_reason": "cross-family equivalent regression", "semantic_configuration": {"signal": "lagged-sign"},
        "dataset_snapshot_ids": [runtime.dataset_id], "metric_ids": ["net-return"], "operation_key": uid("OP")}, "research")
    plan = G1Plan.model_validate({"family_id": other_family, "family_key": {"asset_class": "crypto",
        "market": "BTCUSDT", "timeframe": "1h", "strategy_family": "trend", "signal_family": "lag",
        "holding_period_bucket": "hour"}, "trial_type": "hypothesis", "semantic_configuration": {"signal": "lagged-sign"},
        "dataset_snapshot_ids": [runtime.dataset_id], "metric_ids": ["net-return"]})
    policy = GatePolicy(policy_version="v1", cooldown_hours={"soft": 6, "medium": 24, "hard": 72},
                        default_failure_severity="medium")
    with runtime.store.transaction(runtime.credentials["evaluator"]) as (conn, _):
        checks, hard_invalidity, metrics = _gate_one(conn, plan, policy,
            strategy_version_id=equivalent_id, candidate_hash=artifact["content_hash"])
        assert checks["family_history_checked"] and not checks["no_known_invalidity"]
        assert hard_invalidity and metrics["prior_failure_count"] == 1
    assert runtime.call("audit", {}, "auditor")["status"] == "VERIFIED"


def test_concurrent_siblings_roles_and_stale_family_screen_fail_closed(runtime):
    snapshot = runtime.snapshot()
    request = runtime.decision(snapshot, 0, 0)
    runtime.call("decide", request, "research", error="FORBIDDEN")
    runtime.call("verify", runtime.verification(snapshot, 0), "research", error="FORBIDDEN")
    def decide(key):
        from liki.evaluation import Evaluator, GateInput
        from liki.core import DomainError
        try:
            return Evaluator(runtime.store).gate(runtime.credentials["evaluator"],
                GateInput.model_validate({**request, "operation_key": key}))["decision"]
        except DomainError as error:
            return error.code
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(decide, [uid("GATE"), uid("GATE")])) == ["CONCURRENT_MODIFICATION", "PASS"]
    screen = runtime.decision(snapshot, 1, 1)
    runtime.call("register", {"object_id": uid("SV"), "object_type": "strategy_version",
        "campaign_id": runtime.campaign_id, "artifact_id": runtime.candidate_artifact["artifact_id"]}, "research")
    runtime.call("decide", screen, error="STALE_FAMILY_SCREEN")
    with pytest.raises(psycopg.Error):
        with runtime.store.transaction(runtime.credentials["evaluator"]) as (conn, _):
            conn.execute("UPDATE gate_decisions SET decision='FAIL'")
    assert runtime.call("audit", {}, "auditor")["status"] == "VERIFIED"


@pytest.mark.parametrize("sample_count,minimum_samples", [(1, 1), (1, 10)])
def test_g4_cannot_lower_or_underfill_the_predeclared_g3_test(runtime, sample_count, minimum_samples):
    snapshot = runtime.snapshot(sample_count=sample_count, minimum_samples=minimum_samples)
    for gate in range(4):
        assert runtime.call("decide", runtime.decision(snapshot, gate, gate))["decision"] == "PASS"
    result = runtime.call("decide", runtime.decision(snapshot, 4, 4))
    assert result["decision"] == "BLOCKED"
    assert runtime.call("audit", {}, "auditor")["status"] == "VERIFIED"


def test_runtime_rejects_a_family_plan_not_bound_to_its_registered_trial(runtime):
    runtime.family_id = uid("UNRELATED-FAMILY")
    snapshot = runtime.snapshot()
    assert runtime.call("decide", runtime.decision(snapshot, 0, 0))["decision"] == "PASS"
    request = runtime.decision(snapshot, 1, 1)
    assert runtime.call("decide", request)["decision"] == "BLOCKED"
    with runtime.store.transaction(runtime.credentials["auditor"]) as (conn, actor):
        evidence = conn.execute("SELECT artifact_id FROM evidence WHERE evidence_id=%s",
                                (request["evidence_ids"][0],)).fetchone()
        report = runtime.store.artifact(conn, actor, evidence["artifact_id"])["content"]
        assert "G1_DECLARED_TRIAL_NOT_BOUND" in report["unknowns"]


def test_old_signed_report_cannot_be_reused_after_snapshot_round_trip(runtime):
    first = runtime.snapshot(missing_plan=1)
    old_request = runtime.decision(first, 0, 0)
    assert runtime.call("decide", old_request)["decision"] == "PASS"
    assert runtime.call("decide", runtime.decision(first, 1, 1))["decision"] == "BLOCKED"
    second = runtime.snapshot(missing_plan=1)
    def reenter(snapshot, version):
        runtime.call("reenter", {"strategy_version_id": runtime.candidate_id, "snapshot_id": snapshot,
            "expected_version": version, "reason": "Dependency evidence revision", "operation_key": uid("REENTRY")})
    reenter(second, 2)
    assert runtime.call("decide", runtime.decision(second, 0, 3))["decision"] == "PASS"
    assert runtime.call("decide", runtime.decision(second, 1, 4))["decision"] == "BLOCKED"
    reenter(first, 5)
    runtime.call("decide", {**old_request, "expected_version": 6, "operation_key": uid("GATE")},
                 error="VERIFIER_BINDING_MISMATCH")
    with runtime.store.transaction(runtime.credentials["auditor"]) as (conn, _):
        assert runtime.store.state(conn, "candidate", runtime.candidate_id)["version"] == 6
        assert conn.execute("SELECT count(*) AS n FROM gate_decisions").fetchone()["n"] == 4
    assert runtime.call("audit", {}, "auditor")["status"] == "VERIFIED"


def test_cli_rejects_unsafe_key_files_and_redacts_invalid_payload(runtime):
    runtime.files["evaluator"].chmod(0o644)
    runtime.call("audit", {}, error="SECRET_FILE_PERMISSIONS_UNSAFE")
    runtime.files["evaluator"].chmod(0o600)
    response = runtime.call("verify", {"credential": "must-not-be-echoed"}, error="INVALID_REQUEST")
    assert "must-not-be-echoed" not in canonical(response)
