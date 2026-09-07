"""Real-process G0–G5 acceptance; market observations are explicit test-only fixtures."""

import base64
import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from liki.backtest_gate import QuoteReplayData
from liki.core import canonical, content_hash, uid
from liki.data.models import RawPayload
from liki.server import create_app
from tests.test_backtest_gate import plan_body, program, quote_data
from tests.test_data_service import NOW
from tests.test_research_runtime import Runtime
from tests.test_server import headers


class BacktestRuntime(Runtime):
    failure = None

    def call(self, action, body, role="evaluator", *, error=None):
        body = deepcopy(body)
        if action == "dataset":
            data = QuoteReplayData.model_validate(quote_data())
            raw = RawPayload.from_bytes(provider="binance", uri="fixture://g5/hand-verified-quotes",
                content=canonical(data.model_dump(mode="json")).encode(), retrieved_at=NOW)
            body["raw_payloads"] = [{"metadata": raw.model_dump(mode="json"),
                                    "payload_base64": base64.b64encode(raw.payload_bytes).decode()}]
            body["manifest"].update(content_hash=content_hash(data.model_dump(mode="json")),
                schema_hash=content_hash(QuoteReplayData.model_json_schema()), raw_payload_hashes=[raw.content_hash],
                start_time=data.quotes[0].timestamp, end_time=data.quotes[-1].timestamp,
                fidelity_tier="F1_TRADE_BBO", candle_semantics="point observations; no intrabar inference",
                timestamp_semantics="actual quote availability time")
            if self.failure == "normalized_hash":
                body["manifest"]["content_hash"] = "sha256:" + "0" * 64
        if action == "artifact" and body["schema_name"] == "strategy-v1":
            body["content"]["backtest_strategy"] = program()
        if action == "snapshot":
            plan = plan_body()
            plan.update(candidate_artifact_id=self.candidate_artifact["artifact_id"],
                candidate_hash=self.candidate_artifact["content_hash"], snapshot_id=body["snapshot_id"],
                dataset_artifact_id=self.dataset_id, code_hash=self.store.fingerprint,
                environment_fingerprint=self.store.fingerprint)
            if self.failure == "cost":
                del plan["costs"]["impact_bps"]
            if self.failure == "code":
                plan["code_hash"] = "unexecuted-code-version"
            if self.failure == "candidate":
                plan["candidate_hash"] = "different-candidate"
            aid = self.artifact(plan, "research/backtest-plan-v1")["artifact_id"]
            body["gate_input_artifact_ids"]["5"] = [] if self.failure == "plan" else [aid]
        return super().call(action, body, role, error=error)

    def report(self, evidence_id):
        with self.store.transaction(self.credentials["auditor"]) as (conn, actor):
            row = conn.execute("SELECT artifact_id FROM evidence WHERE evidence_id=%s", (evidence_id,)).fetchone()
            return self.store.artifact(conn, actor, row["artifact_id"])["content"]


@pytest.fixture
def backtest_runtime(store, credentials, database, tmp_path):
    return BacktestRuntime(store, credentials, database, tmp_path)


def through_g4(runtime):
    runtime.candidate()
    snapshot = runtime.snapshot()
    for gate in range(5):
        assert runtime.call("decide", runtime.decision(snapshot, gate, gate))["decision"] == "PASS"
    return snapshot


def test_signed_cli_backtest_replays_persisted_data_and_audits_complete_package(backtest_runtime):
    runtime = backtest_runtime
    snapshot = through_g4(runtime)
    verify = runtime.verification(snapshot, 5)
    with runtime.store.transaction(runtime.credentials["auditor"]) as (conn, _):
        used_key = conn.execute("SELECT e.operation_key FROM verifier_executions v JOIN event_log e USING(event_id) "
                                "WHERE v.gate_id=0").fetchone()["operation_key"]
    runtime.call("verify", {**verify, "operation_key": used_key}, error="IDEMPOTENCY_CONFLICT")
    with runtime.store.transaction(runtime.credentials["auditor"]) as (conn, _):
        assert conn.execute("SELECT count(*) AS n FROM artifacts WHERE schema_name='backtest/protocol-report-v1'").fetchone()["n"] == 0
        assert conn.execute("SELECT count(*) AS n FROM verifier_executions WHERE gate_id=5").fetchone()["n"] == 0
    evidence = runtime.call("verify", verify)
    assert runtime.call("verify", verify) == evidence
    report = runtime.report(evidence["evidence_id"])
    assert all(report["checks"].values()) and report["unknowns"] == []
    with runtime.store.transaction(runtime.credentials["auditor"]) as (conn, actor):
        package_row = runtime.store.artifact(conn, actor, report["package_artifact_id"])
        package = package_row["content"]
        assert package["candidate"]["net_pnl"] == "-45.433"
        assert package["benchmark"]["net_pnl"] == "-12.313"
        assert package["candidate"]["observations"][-1]["reference"]["equity"] == "954.567"
        assert len(package["candidate"]["fills"]) == 3
        assert package_row["content_hash"] == report["package_hash"]
        raw = conn.execute("SELECT artifact_id FROM data_raw_payloads").fetchone()["artifact_id"]
        assert raw in package["input_artifacts"] and raw in report["input_artifacts"]
        execution = conn.execute("SELECT * FROM verifier_executions WHERE gate_id=5").fetchone()
        assert execution["manifest"]["input_artifacts"][report["package_artifact_id"]] == report["package_hash"]
        assert execution["manifest"]["candidate_state_version"] == 5
        assert conn.execute("SELECT count(*) AS n FROM verifier_executions WHERE gate_id=5").fetchone()["n"] == 1
    again = runtime.call("verify", runtime.verification(snapshot, 5))
    assert runtime.report(again["evidence_id"])["package_hash"] == report["package_hash"]
    decision = {"strategy_version_id": runtime.candidate_id, "snapshot_id": snapshot, "gate_id": 5,
        "expected_version": 5, "evidence_ids": [evidence["evidence_id"]], "metrics": [], "operation_key": uid("GATE")}
    result = runtime.call("decide", decision)
    assert result["status"] == "BACKTESTED" and result["version"] == 6
    assert runtime.call("decide", decision) == result
    assert runtime.call("verify", verify) == evidence
    runtime.call("verify", runtime.verification(snapshot, 7), error="GATE_DEPENDENCY_UNSATISFIED")
    runtime.call("verify", runtime.verification(snapshot, 8), error="INVALID_REQUEST")
    client = TestClient(create_app(runtime.store))
    history = client.get("/gates/" + runtime.candidate_id, headers=headers(runtime.credentials)).json()
    assert [row["state_after"] for row in history][-1] == "BACKTESTED"
    assert client.get("/backtests/" + runtime.candidate_id).status_code == 401
    response = client.get("/backtests/" + runtime.candidate_id, headers=headers(runtime.credentials))
    assert response.status_code == 200
    assert response.json()["package"]["content_hash"] == report["package_hash"]
    assert response.json()["package"]["content"]["candidate"]["net_pnl"] == "-45.433"
    assert client.get("/backtests/missing", headers=headers(runtime.credentials)).status_code == 404
    assert runtime.call("audit", {}, "auditor")["status"] == "VERIFIED"


@pytest.mark.parametrize("failure,reason", [("cost", "impact_bps"), ("code", "G5_PLAN_BINDING_MISMATCH"),
    ("candidate", "G5_PLAN_BINDING_MISMATCH"), ("plan", "G5_PLAN_MISSING"),
    ("normalized_hash", "G5_NORMALIZED_DATA_MISMATCH")])
def test_invalid_protocol_dependencies_produce_signed_blocked_not_empty_success(backtest_runtime, failure, reason):
    runtime = backtest_runtime
    runtime.failure = failure
    snapshot = through_g4(runtime)
    request = runtime.decision(snapshot, 5, 5)
    report = runtime.report(request["evidence_ids"][0])
    assert reason in canonical(report["unknowns"])
    assert not any(report["checks"].values()) and "package_artifact_id" not in report
    assert runtime.call("decide", request)["decision"] == "BLOCKED"
    with runtime.store.transaction(runtime.credentials["auditor"]) as (conn, _):
        assert conn.execute("SELECT count(*) AS n FROM artifacts WHERE schema_name='backtest/protocol-report-v1'").fetchone()["n"] == 0
    response = TestClient(create_app(runtime.store)).get("/backtests/" + runtime.candidate_id,
                                                       headers=headers(runtime.credentials)).json()
    assert response["package"] is None and response["report"]["content"]["unknowns"] == report["unknowns"]
    assert runtime.call("audit", {}, "auditor")["status"] == "VERIFIED"


def test_g5_rejects_unsigned_caller_reports_and_caller_metrics(backtest_runtime):
    runtime = backtest_runtime
    snapshot = through_g4(runtime)
    runtime.call("verify", runtime.verification(snapshot, 5), "research", error="FORBIDDEN")
    request = runtime.decision(snapshot, 5, 5)
    unsigned_id = uid("UNSIGNED")
    with runtime.store.transaction(runtime.credentials["evaluator"]) as (conn, actor):
        aid = runtime.store.put_artifact(conn, actor, json.loads(canonical({"snapshot_id": snapshot,
            "checks": dict.fromkeys(("deterministic_replay", "complete_order_ledger", "dual_accounting", "all_costs_explicit"), True)})),
            schema_name="verified-gate-report-v1", classification="INTERNAL", policy_version="v1")
        # Evidence registration cannot create a verifier execution/signature.
        conn.execute("INSERT INTO evidence VALUES(%s,%s,'backtest','DERIVED_VALUE','DEVELOPMENT',now(),'{}',%s,now())",
                     (unsigned_id, aid, actor.principal_id))
    runtime.call("decide", {**request, "evidence_ids": [unsigned_id], "operation_key": uid("FORGED")},
                 error="UNVERIFIED_GATE_EVIDENCE")
    request["metrics"] = [{"metric_id": "caller-profit", "metric_version": "v1", "unit": "USDT",
                           "status": "VALUE", "value": "9999999", "reason": "invented"}]
    assert runtime.call("decide", request)["reason"] == "METRICS_NOT_BOUND_TO_EVIDENCE"
    assert runtime.call("audit", {}, "auditor")["status"] == "VERIFIED"
