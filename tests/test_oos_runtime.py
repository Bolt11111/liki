"""Real-process, PostgreSQL and authenticated HTTP acceptance for signed G7."""

import base64
import time
from copy import deepcopy
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from liki.backtest_gate import BacktestPlan, QuoteReplayData
from liki.core import canonical, content_hash, uid, utcnow
from liki.data.models import RawPayload
from liki.finance.economics_contracts import EconomicsPolicy, ExecutionTape
from liki.server import create_app
from tests.test_data_service import manifest
from tests.test_economics_runtime import EconomicsRuntime
from tests.test_oos_gate import declaration_body, future_inputs
from tests.test_research_runtime import Runtime
from tests.test_server import headers


class OOSRuntime(EconomicsRuntime):
    g7_failure = None

    def call(self, action, body, role="evaluator", *, error=None):
        body = deepcopy(body)
        if action == "artifact" and body["schema_name"] == "strategy-v1":
            body["content"]["research_contract"]["horizon_seconds"] = 1
        return super().call(action, body, role, error=error)

    def persist_oos(self, data, model, snapshot_id, start, end, fidelity):
        raw = RawPayload.from_bytes(provider="binance", uri="fixture://g7/" + snapshot_id,
            content=canonical(data).encode(), retrieved_at=utcnow())
        body = manifest(raw, snapshot_id).model_dump(mode="json")
        body.update(content_hash=content_hash(data), schema_hash=content_hash(model.model_json_schema()),
            start_time=start, end_time=end, as_of_time=raw.retrieved_at, fetched_at=raw.retrieved_at, fidelity_tier=fidelity)
        if self.g7_failure == "normalized" and model == ExecutionTape:
            body["content_hash"] = "sha256:" + "0" * 64
        if self.g7_failure == "provider" and model == ExecutionTape:
            body["provider"] = "not-the-raw-provider"
        result = Runtime.call(self, "dataset", {"manifest": body,
            "raw_payloads": [{"metadata": raw.model_dump(mode="json"), "payload_base64": base64.b64encode(raw.payload_bytes).decode()}],
            "operation_key": uid("DATAOP"), "task_id": self.campaign_id, "policy_version": "v1"}, "data")
        return result["artifact_id"]

    def finalize_snapshot(self, body):
        with self.store.transaction(self.credentials["auditor"]) as (conn, actor):
            g5_plan = self.store.artifact(conn, actor, body["gate_input_artifact_ids"]["5"][0])
            policy = self.store.artifact(conn, actor, self.policy_id)
            development = self.store.artifact(conn, actor, self.execution_dataset)
        start = utcnow() + timedelta(seconds=5)
        self.oos_trial_id = uid("TRIAL")
        declaration = declaration_body(start=start)
        declaration.update(snapshot_id=body["snapshot_id"], candidate_artifact_id=self.candidate_artifact["artifact_id"],
            candidate_hash=self.candidate_artifact["content_hash"],
            g5_configuration_hash=content_hash(BacktestPlan.model_validate(g5_plan["content"]).model_dump(mode="json")),
            g6_policy_hash=content_hash(EconomicsPolicy.model_validate(policy["content"]).model_dump(mode="json")), quote_dataset_snapshot_id=uid("DATA"),
            g6_execution_tape_hash=development["content"]["content_hash"],
            execution_dataset_snapshot_id=uid("DATA"), trial_event_id=self.oos_trial_id,
            trial_family_id=self.family_id, code_hash=self.store.fingerprint)
        if self.g7_failure == "policy":
            declaration["g6_policy_hash"] = "changed-policy"
        if self.g7_failure == "horizon":
            declaration["event_horizon_seconds"] = 0
        self.declaration_artifact = self.artifact(declaration, "research/oos-declaration-v1")
        trial = {"trial_event_id": self.oos_trial_id, "campaign_id": self.campaign_id,
            "trial_family_id": self.family_id, "strategy_version_id": self.candidate_id, "trial_type": "window",
            "selection_reason": "Prospective test-only chronological protocol",
            "semantic_configuration": {"g7_declaration_hash": self.declaration_artifact["content_hash"]},
            "dataset_snapshot_ids": [declaration["quote_dataset_snapshot_id"], declaration["execution_dataset_snapshot_id"]],
            "metric_ids": ["net-return", "benchmark-excess", "minimum-fill-ratio"], "operation_key": uid("TRIALOP")}
        if self.g7_failure == "trial":
            trial["semantic_configuration"] = {"g7_declaration_hash": "not-the-declaration"}
        self.call("trial", trial, "research")
        if self.g7_failure == "budget":
            for _ in range(9):
                self.call("trial", {**trial, "trial_event_id": uid("TRIAL"), "operation_key": uid("TRIALOP")}, "research")
        # Await the declared test-only timestamps; never backdate the persisted declaration.
        time.sleep(max(0, (start + timedelta(seconds=6) - utcnow()).total_seconds()) + .01)
        quotes, tape = future_inputs(start)
        if self.g7_failure == "friction":
            tape["fees"][0]["schedule"]["rate"] = "0.15"
        quotes = QuoteReplayData.model_validate(quotes).model_dump(mode="json")
        self.oos_quotes = self.persist_oos(quotes, QuoteReplayData, declaration["quote_dataset_snapshot_id"],
            quotes["quotes"][0]["timestamp"], quotes["quotes"][-1]["timestamp"], "F1_TRADE_BBO")
        tape["g5_dataset_artifact_id"] = self.oos_quotes
        tape = ExecutionTape.model_validate(tape).model_dump(mode="json")
        self.oos_tape = self.persist_oos(tape, ExecutionTape, declaration["execution_dataset_snapshot_id"],
            tape["books"][0]["event_time"], tape["books"][-1]["event_time"], "F2_AGG_L2")
        if self.g7_failure == "late_declaration":
            declaration["method_rationale"] += "; selected after inspection"
            declaration["trial_event_id"] = uid("TRIAL")
            self.declaration_artifact = self.artifact(declaration, "research/oos-declaration-v1")
            self.call("trial", {**trial, "trial_event_id": declaration["trial_event_id"], "operation_key": uid("TRIALOP"),
                "semantic_configuration": {"g7_declaration_hash": self.declaration_artifact["content_hash"]}}, "research")
        plan = self.artifact({"declaration_artifact_id": self.declaration_artifact["artifact_id"],
            "quote_dataset_artifact_id": self.oos_quotes, "execution_dataset_artifact_id": self.oos_tape}, "research/oos-plan-v1")
        body["gate_input_artifact_ids"]["7"] = [plan["artifact_id"], self.declaration_artifact["artifact_id"], self.oos_quotes, self.oos_tape]
        body["statistical_method_versions"]["oos"] = "chronological-fixed-program-v1"
        return body


@pytest.fixture
def oos_runtime(store, credentials, database, tmp_path):
    return OOSRuntime(store, credentials, database, tmp_path)


def through_g6(runtime):
    runtime.candidate()
    snapshot = runtime.snapshot()
    runtime.call("verify", runtime.verification(snapshot, 7), error="GATE_DEPENDENCY_UNSATISFIED")
    for gate in range(7):
        request = runtime.decision(snapshot, gate, gate)
        result = runtime.call("decide", request)
        assert result["decision"] == "PASS", (result, runtime.report(request["evidence_ids"][0]))
    return snapshot


def test_signed_g7_cli_replay_audit_exposure_and_operator_reads(oos_runtime):
    runtime = oos_runtime
    snapshot = through_g6(runtime)
    client = TestClient(create_app(runtime.store))
    g6_before = client.get("/execution-economics/" + runtime.candidate_id, headers=headers(runtime.credentials)).json()
    request = runtime.verification(snapshot, 7)
    runtime.call("verify", request, "research", error="FORBIDDEN")
    with runtime.store.transaction(runtime.credentials["auditor"]) as (conn, _):
        old_key = conn.execute("SELECT e.operation_key FROM verifier_executions v JOIN event_log e USING(event_id) WHERE v.gate_id=0").fetchone()["operation_key"]
    runtime.call("verify", {**request, "operation_key": old_key}, error="IDEMPOTENCY_CONFLICT")
    with runtime.store.transaction(runtime.credentials["auditor"]) as (conn, _):
        assert conn.execute("SELECT count(*) n FROM artifacts WHERE schema_name='validation/oos-report-v1'").fetchone()["n"] == 0
    result = runtime.call("verify", request)
    assert runtime.call("verify", request) == result
    report = runtime.report(result["evidence_id"])
    assert report["unknowns"] == [] and all(report["checks"].values()), report
    repeated = runtime.call("verify", runtime.verification(snapshot, 7))
    assert runtime.report(repeated["evidence_id"])["package_hash"] == report["package_hash"]
    decision = {"strategy_version_id": runtime.candidate_id, "snapshot_id": snapshot, "gate_id": 7,
        "expected_version": 7, "evidence_ids": [result["evidence_id"]], "metrics": [], "operation_key": uid("GATE")}
    outcome = runtime.call("decide", decision)
    assert outcome["decision"] == "PASS" and outcome["status"] == "OOS_VALIDATED" and outcome["version"] == 8
    assert runtime.call("decide", decision) == outcome and runtime.call("verify", request) == result
    assert client.get("/out-of-sample/" + runtime.candidate_id).status_code == 401
    response = client.get("/out-of-sample/" + runtime.candidate_id, headers=headers(runtime.credentials))
    assert response.status_code == 200
    package = response.json()["package"]["content"]
    assert package["score"]["net_return_range"] == ["0.007918", "0.008919"]
    assert package["trial_history"]["campaign_raw_trials"] == 2
    assert package["trial_history"]["remaining_budget"] == 8
    assert package["g6_package_hash"] == g6_before["package"]["content_hash"]
    assert runtime.oos_quotes in package["input_artifacts"] and runtime.oos_tape in package["input_artifacts"]
    with runtime.store.transaction(runtime.credentials["auditor"]) as (conn, actor):
        exposure = conn.execute("SELECT * FROM evidence WHERE evidence_id=%s", (result["evidence_id"],)).fetchone()
        assert exposure["role"] == "VALIDATION" and exposure["contamination_tags"] == ["saw_g7_result"]
        execution = conn.execute("SELECT manifest FROM verifier_executions WHERE gate_id=7 ORDER BY created_at DESC LIMIT 1").fetchone()["manifest"]
        assert all(runtime.store.artifact(conn, actor, aid)["content_hash"] == digest for aid, digest in execution["input_artifacts"].items())
    child_id = uid("SV")
    runtime.call("register", {"object_id": child_id, "object_type": "strategy_version", "campaign_id": runtime.campaign_id,
        "artifact_id": runtime.candidate_artifact["artifact_id"], "parents": {runtime.candidate_id: "parameter_variant_of"}}, "research")
    child_trial = uid("TRIAL")
    runtime.call("trial", {"trial_event_id": child_trial, "campaign_id": runtime.campaign_id,
        "trial_family_id": runtime.family_id, "strategy_version_id": child_id, "trial_type": "parameter",
        "selection_reason": "Test-only tuning after G7 inspection", "semantic_configuration": {"threshold": "1"},
        "dataset_snapshot_ids": [runtime.oos_quotes], "metric_ids": ["net-return"], "operation_key": uid("OP")}, "research")
    with runtime.store.transaction(runtime.credentials["auditor"]) as (conn, _):
        assert "saw_g7_result" in conn.execute("SELECT contamination_tags FROM trial_events WHERE trial_event_id=%s", (child_trial,)).fetchone()["contamination_tags"]
    sibling_id, sibling_trial = uid("SV"), uid("TRIAL")
    runtime.call("register", {"object_id": sibling_id, "object_type": "strategy_version", "campaign_id": runtime.campaign_id,
        "artifact_id": runtime.candidate_artifact["artifact_id"]}, "research")
    runtime.call("trial", {"trial_event_id": sibling_trial, "campaign_id": runtime.campaign_id,
        "trial_family_id": runtime.family_id, "strategy_version_id": sibling_id, "trial_type": "parameter",
        "selection_reason": "Same-family exposure cannot disappear by omitting a parent edge",
        "semantic_configuration": {"threshold": "2"}, "dataset_snapshot_ids": [runtime.oos_quotes],
        "metric_ids": ["net-return"], "operation_key": uid("OP")}, "research")
    with runtime.store.transaction(runtime.credentials["auditor"]) as (conn, _):
        assert "saw_g7_result" in conn.execute("SELECT contamination_tags FROM trial_events WHERE trial_event_id=%s", (sibling_trial,)).fetchone()["contamination_tags"]
    assert client.get("/execution-economics/" + runtime.candidate_id, headers=headers(runtime.credentials)).json() == g6_before
    assert runtime.call("audit", {}, "auditor")["status"] == "VERIFIED"
    runtime.call("verify", runtime.verification(snapshot, 8), error="INVALID_REQUEST")


@pytest.mark.parametrize("failure,reason", [("trial", "PREDECLARED_SCIENTIFIC_TRIAL"), ("policy", "FROZEN_CONFIGURATION"),
    ("normalized", "NORMALIZED_DATA"), ("budget", "TRIAL_BUDGET_EXHAUSTED"),
    ("provider", "RAW_RETRIEVAL_PROVENANCE"),
    ("late_declaration", "NOT_PROSPECTIVELY_PREDECLARED")])
def test_g7_unknown_dependencies_produce_signed_blocked_not_fake_oos(oos_runtime, failure, reason):
    runtime = oos_runtime
    runtime.g7_failure = failure
    snapshot = through_g6(runtime)
    request = runtime.decision(snapshot, 7, 7)
    report = runtime.report(request["evidence_ids"][0])
    assert reason in canonical(report["unknowns"]), report
    assert not any(report["checks"].values()) and "package_artifact_id" not in report
    assert runtime.call("decide", request)["decision"] == "BLOCKED"
    assert runtime.call("audit", {}, "auditor")["status"] == "VERIFIED"


def test_g7_oos_loss_is_signed_fail_not_unknown(oos_runtime):
    runtime = oos_runtime
    runtime.g7_failure = "friction"
    snapshot = through_g6(runtime)
    request = runtime.decision(snapshot, 7, 7)
    report = runtime.report(request["evidence_ids"][0])
    assert report["unknowns"] == [] and report["hard_invalidity"], report
    assert "G7_OOS_AFTER_FRICTION_EDGE_FAILED" in report["failure_reasons"]
    assert runtime.call("decide", request)["decision"] == "FAIL"
