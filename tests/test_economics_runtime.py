"""G0–G6 acceptance uses real CLI processes, database transactions, and HTTP reads."""

import base64
import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from liki.backtest_gate import QuoteReplayData
from liki.core import canonical, content_hash, uid
from liki.data.models import RawPayload
from liki.finance.economics_contracts import ExecutionTape, ImpactSampleSet
from liki.server import create_app
from tests.test_backtest_gate import plan_body, program
from tests.test_backtest_runtime import BacktestRuntime
from tests.test_data_service import NOW, manifest
from tests.test_economics_gate import economics_policy, economics_tape, impact_samples, profitable_quotes
from tests.test_research_runtime import Runtime
from tests.test_server import headers


class EconomicsRuntime(BacktestRuntime):
    g6_failure = None

    def persist_source(self, data, model, start, end, *, fidelity="F2_AGG_L2"):
        raw = RawPayload.from_bytes(provider="binance", uri="fixture://g6/" + data["schema_version"],
            content=canonical(data).encode(), retrieved_at=NOW)
        body = manifest(raw, uid("DATA")).model_dump(mode="json")
        body.update(content_hash=content_hash(data), schema_hash=content_hash(model.model_json_schema()),
                    start_time=start, end_time=end, fidelity_tier=fidelity)
        aid = Runtime.call(self, "dataset", {"manifest": body,
            "raw_payloads": [{"metadata": raw.model_dump(mode="json"),
                              "payload_base64": base64.b64encode(raw.payload_bytes).decode()}],
            "operation_key": uid("DATAOP"), "task_id": self.campaign_id, "policy_version": "v1"}, "data")["artifact_id"]
        return aid, raw.content_hash

    def call(self, action, body, role="evaluator", *, error=None):
        body = deepcopy(body)
        if action == "dataset":
            data = QuoteReplayData.model_validate(profitable_quotes())
            aid, _ = self.persist_source(data.model_dump(mode="json"), QuoteReplayData,
                data.quotes[0].timestamp, data.quotes[-1].timestamp, fidelity="F1_TRADE_BBO")
            return {"artifact_id": aid}
        if action == "artifact" and body["schema_name"] == "strategy-v1":
            body["content"]["backtest_strategy"] = program()
        if action == "snapshot":
            g5 = plan_body()
            g5.update(candidate_artifact_id=self.candidate_artifact["artifact_id"],
                candidate_hash=self.candidate_artifact["content_hash"], snapshot_id=body["snapshot_id"],
                dataset_artifact_id=self.dataset_id, code_hash=self.store.fingerprint,
                environment_fingerprint=self.store.fingerprint)
            body["gate_input_artifact_ids"]["5"] = [self.artifact(g5, "research/backtest-plan-v1")["artifact_id"]]
            policy = economics_policy()
            for training, key in ((True, "calibration_raw_hashes"), (False, "validation_raw_hashes")):
                samples = impact_samples(training)
                if self.g6_failure == "calibration_leakage" and not training:
                    samples["observations"][0]["episode_id"] = "training-0"
                if self.g6_failure == "validation_failure" and not training:
                    samples["observations"][0]["residual_impact_bps"] = "5"
                values = ImpactSampleSet.model_validate(samples).model_dump(mode="json")
                _, digest = self.persist_source(values, ImpactSampleSet,
                    values["observations"][0]["timestamp"], values["observations"][-1]["timestamp"])
                policy["impact"][key] = [digest]
            tape = economics_tape()
            tape["g5_dataset_artifact_id"] = self.dataset_id
            if self.g6_failure == "friction":
                tape["fees"][0]["schedule"]["rate"] = "0.15"
            if self.g6_failure == "fee":
                tape["fees"][0]["schedule"]["account_tier"] = "unavailable-tier"
            if self.g6_failure == "fidelity":
                policy["minimum_fidelity"] = "F3_SEQ_L2"
            if self.g6_failure == "synthetic":
                tape["evidence_kind"] = "SYNTHETIC"
            if self.g6_failure == "binding":
                tape["g5_dataset_artifact_id"] = "another-data-snapshot"
            if self.g6_failure == "units":
                tape["rules"][0]["specification"].update(base_currency="ETH", quote_currency="EUR", settlement_currency="EUR")
            if self.g6_failure == "market":
                tape["books"][3]["asks"][0]["price"] = "1"
                tape["books"][3]["bids"][0]["price"] = "0.5"
                tape["books"][3]["bids"][1]["price"] = "0.1"
            values = ExecutionTape.model_validate(tape).model_dump(mode="json")
            self.execution_dataset, _ = self.persist_source(values, ExecutionTape,
                values["books"][0]["event_time"], values["books"][-1]["event_time"])
            if self.g6_failure == "cost":
                del policy["impact"]["upper_bps"]
            if self.g6_failure == "raw":
                policy["impact"]["calibration_raw_hashes"] = ["sha256:" + "0" * 64]
            self.policy_id = self.artifact(policy, "execution/economics-policy-v1", "governance")["artifact_id"]
            plan = {"candidate_artifact_id": self.candidate_artifact["artifact_id"],
                "candidate_hash": self.candidate_artifact["content_hash"], "snapshot_id": body["snapshot_id"],
                "execution_dataset_artifact_id": self.execution_dataset, "policy_artifact_id": self.policy_id,
                "code_hash": self.store.fingerprint, "protocol_version": "depth-execution-economics-v1",
                "hidden_liquidity": "NONE_ASSUMED", "queue_assumption": "NO_PASSIVE_FILLS",
                "funding": "NOT_APPLICABLE_SPOT", "borrow_financing": "NOT_APPLICABLE_FULLY_FUNDED_LONG_ONLY",
                "liquidation": "NOT_APPLICABLE_NO_MARGIN"}
            if self.g6_failure == "code":
                plan["code_hash"] = "unexecuted-code"
            aid = self.artifact(plan, "research/economics-plan-v1")["artifact_id"]
            body["gate_input_artifact_ids"]["6"] = [aid, self.execution_dataset, self.policy_id]
            if self.g6_failure != "untrusted_policy":
                body["calibration_artifact_ids"].append(self.policy_id)
            body = self.finalize_snapshot(body)
        return Runtime.call(self, action, body, role, error=error)

    def finalize_snapshot(self, body):
        return body


@pytest.fixture
def economics_runtime(store, credentials, database, tmp_path):
    return EconomicsRuntime(store, credentials, database, tmp_path)


def through_g5(runtime):
    runtime.candidate()
    snapshot = runtime.snapshot()
    runtime.call("verify", runtime.verification(snapshot, 6), error="GATE_DEPENDENCY_UNSATISFIED")
    for gate in range(6):
        assert runtime.call("decide", runtime.decision(snapshot, gate, gate))["decision"] == "PASS"
    return snapshot


def test_g6_signed_cli_provenance_replay_idempotency_and_operator_api(economics_runtime):
    runtime = economics_runtime
    snapshot = through_g5(runtime)
    client = TestClient(create_app(runtime.store))
    g5_before = client.get("/backtests/" + runtime.candidate_id, headers=headers(runtime.credentials)).json()
    request = runtime.verification(snapshot, 6)
    with runtime.store.transaction(runtime.credentials["auditor"]) as (conn, _):
        operation_key = conn.execute("SELECT e.operation_key FROM verifier_executions v JOIN event_log e USING(event_id) WHERE v.gate_id=0").fetchone()["operation_key"]
    runtime.call("verify", {**request, "operation_key": operation_key}, error="IDEMPOTENCY_CONFLICT")
    with runtime.store.transaction(runtime.credentials["auditor"]) as (conn, _):
        assert conn.execute("SELECT count(*) n FROM artifacts WHERE schema_name='execution/economics-report-v1'").fetchone()["n"] == 0
    result = runtime.call("verify", request)
    assert runtime.call("verify", request) == result
    report = runtime.report(result["evidence_id"])
    assert report["unknowns"] == [] and all(report["checks"].values()), report
    again = runtime.call("verify", runtime.verification(snapshot, 6))
    assert runtime.report(again["evidence_id"])["package_hash"] == report["package_hash"]
    decision = {"strategy_version_id": runtime.candidate_id, "snapshot_id": snapshot, "gate_id": 6,
        "expected_version": 6, "evidence_ids": [result["evidence_id"]], "metrics": [], "operation_key": uid("GATE")}
    applied = runtime.call("decide", decision)
    assert applied["decision"] == "PASS" and applied["status"] == "ECONOMICALLY_VALIDATED" and applied["version"] == 7
    assert runtime.call("decide", decision) == applied
    assert runtime.call("verify", request) == result
    assert client.get("/execution-economics/" + runtime.candidate_id).status_code == 401
    response = client.get("/execution-economics/" + runtime.candidate_id, headers=headers(runtime.credentials))
    assert response.status_code == 200
    package = response.json()["package"]["content"]
    assert len(package["capacity_curve"]) == 3 and len(package["scenarios"]) == 54
    assert package["g5_package_hash"] == g5_before["package"]["content_hash"]
    assert package["calibration"]["bounds"] == ["0", "1", "2"]
    assert set(package["calibration"]["training_episodes"]).isdisjoint(package["calibration"]["validation_episodes"])
    assert runtime.execution_dataset in package["input_artifacts"] and runtime.policy_id in package["input_artifacts"]
    with runtime.store.transaction(runtime.credentials["auditor"]) as (conn, actor):
        execution = conn.execute("SELECT manifest FROM verifier_executions WHERE gate_id=6 ORDER BY created_at DESC LIMIT 1").fetchone()["manifest"]
        assert execution["input_artifacts"][report["package_artifact_id"]] == report["package_hash"]
        assert all(runtime.store.artifact(conn, actor, aid)["content_hash"] == digest for aid, digest in execution["input_artifacts"].items())
    assert client.get("/backtests/" + runtime.candidate_id, headers=headers(runtime.credentials)).json() == g5_before
    assert runtime.call("audit", {}, "auditor")["status"] == "VERIFIED"


@pytest.mark.parametrize("failure,reason", [("fee", "effective contract"), ("cost", "upper_bps"),
    ("code", "G6_PLAN_BINDING_MISMATCH"), ("binding", "G6_NORMALIZED_DATA_OR_G5_BINDING_MISMATCH"),
    ("raw", "G6_PERSISTED_RAW_SOURCE_MISSING"), ("fidelity", "EXECUTION_FIDELITY_INSUFFICIENT"),
    ("units", "G6_G5_ECONOMIC_UNIT_MISMATCH"), ("market", "G6_G5_MARKET_OBSERVATION_CONFLICT"),
    ("synthetic", "G6_SYNTHETIC_LIQUIDITY_NOT_ECONOMIC_EVIDENCE"),
    ("calibration_leakage", "G6_IMPACT_CALIBRATION_LEAKAGE"), ("validation_failure", "G6_IMPACT_HOLDOUT_VALIDATION_FAILED"),
    ("untrusted_policy", "G6_UNTRUSTED_OR_UNPINNED_POLICY")])
def test_g6_unknown_or_untrusted_dependencies_are_signed_blocked(economics_runtime, failure, reason):
    runtime = economics_runtime
    runtime.g6_failure = failure
    snapshot = through_g5(runtime)
    request = runtime.decision(snapshot, 6, 6)
    report = runtime.report(request["evidence_ids"][0])
    assert reason in canonical(report["unknowns"])
    assert not any(report["checks"].values()) and "package_artifact_id" not in report
    assert runtime.call("decide", request)["decision"] == "BLOCKED"
    assert runtime.call("audit", {}, "auditor")["status"] == "VERIFIED"


def test_g6_known_cost_failure_is_fail_not_missing_information(economics_runtime):
    runtime = economics_runtime
    runtime.g6_failure = "friction"
    snapshot = through_g5(runtime)
    request = runtime.decision(snapshot, 6, 6)
    report = runtime.report(request["evidence_ids"][0])
    assert report["unknowns"] == [] and report["hard_invalidity"]
    assert "G6_AFTER_FRICTION_EDGE_FAILED" in report["failure_reasons"]
    assert runtime.call("decide", request)["decision"] == "FAIL"


def test_g6_rejects_forged_reports_and_caller_metrics(economics_runtime):
    runtime = economics_runtime
    snapshot = through_g5(runtime)
    runtime.call("verify", runtime.verification(snapshot, 6), "research", error="FORBIDDEN")
    request = runtime.decision(snapshot, 6, 6)
    unsigned_id = uid("UNSIGNED")
    with runtime.store.transaction(runtime.credentials["evaluator"]) as (conn, actor):
        aid = runtime.store.put_artifact(conn, actor, json.loads(canonical({"snapshot_id": snapshot,
            "checks": dict.fromkeys(("historical_fees", "funding_borrow_known", "fill_fidelity", "capacity_stress", "latency_constraints"), True)})),
            schema_name="verified-gate-report-v1", classification="INTERNAL", policy_version="v1")
        conn.execute("INSERT INTO evidence VALUES(%s,%s,'execution_economics','DERIVED_VALUE','DEVELOPMENT',now(),'{}',%s,now())",
                     (unsigned_id, aid, actor.principal_id))
    runtime.call("decide", {**request, "evidence_ids": [unsigned_id], "operation_key": uid("FORGED")}, error="UNVERIFIED_GATE_EVIDENCE")
    request["metrics"] = [{"metric_id": "made-up-profit", "metric_version": "v1", "unit": "USDT",
        "status": "VALUE", "value": "999999", "reason": "invented"}]
    assert runtime.call("decide", request)["reason"] == "METRICS_NOT_BOUND_TO_EVIDENCE"
