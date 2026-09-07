from datetime import timedelta

import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from psycopg.types.json import Jsonb

from liki.core import DomainError, uid, utcnow
from liki.data_service import DataService
from liki.evaluation import EvaluationSnapshot, Evaluator, GateInput, REQUIRED_CHECKS
from liki.research import Research, ResearchObject
from liki.scheduler import Scheduler
from liki.verification import VerificationRunner, provision_verifier
from tests.test_data_service import manifest, payload
from tests.test_scheduler import campaign


def verified_candidate(store, credentials, database, *, contract_changes=None):
    cid = campaign(Scheduler(store), credentials["research"])
    raw = payload()
    dataset = DataService(store).persist_dataset(
        credentials["data"], manifest(raw, uid("DATA")), (raw,),
        operation_key=uid("OP"), task_id=cid, policy_version="v1",
    )
    candidate_id = uid("SV")
    contract = {
        "objective": "Positive after-cost out-of-sample return",
        "hypothesis": "Lagged returns predict subsequent return",
        "metric_id": "net-return", "metric_version": "v1", "unit": "decimal-return",
        "lower": "0", "dataset_snapshot_ids": [dataset], "evaluator_version": "v1",
        "mode": "RESEARCH", "strategy_version_id": candidate_id, "campaign_id": cid,
        "market": "BTCUSDT spot", "horizon_seconds": 3600,
        "constraints": ["No leverage or live orders"], "expected_artifacts": ["backtest-ledger"],
        **(contract_changes or {}),
    }
    with store.transaction(credentials["research"]) as (conn, actor):
        aid = store.put_artifact(conn, actor, {"research_contract": contract},
                                 schema_name="strategy-v1", classification="INTERNAL", policy_version="v1")
        artifact = store.artifact(conn, actor, aid)
    obj = ResearchObject(object_id=candidate_id, object_type="strategy_version",
                         campaign_id=cid, artifact_id=aid)
    Research(store).register(credentials["research"], obj)
    snapshot = EvaluationSnapshot(
        snapshot_id=uid("SNAP"), candidate_artifact_id=aid,
        candidate_hash=artifact["content_hash"], dataset_snapshot_ids=(dataset,),
        feature_registry_version="v1", label_registry_version="v1", evaluator_version="v1",
        metric_versions={"net-return": "v1"}, gate_policy_versions={str(i): "v1" for i in range(14)},
        execution_model_version="v1", cost_model_version="v1", risk_model_version="v1",
        statistical_method_versions={}, environment_fingerprint=store.fingerprint,
        inference_route_ids=(), rules_by_gate={}, calibration_artifact_ids=(),
        minimum_forward_opportunities=10, forward_evaluation_at=utcnow() + timedelta(days=1),
    )
    Evaluator(store).snapshot(credentials["evaluator"], snapshot)
    signing_key, key_id = Ed25519PrivateKey.generate(), uid("KEY")
    with store.transaction(credentials["evaluator"]) as (_, actor):
        principal = actor.principal_id
    provision_verifier(database["test_owner_dsn"], principal_id=principal, key_id=key_id,
                       public_key=signing_key.public_key().public_bytes_raw())
    return obj, snapshot, VerificationRunner(store, key_id, signing_key)


def execute(store, credentials, obj, snapshot, runner):
    operation_key = uid("OP")
    eid = runner.research_contract(credentials["evaluator"], snapshot_id=snapshot.snapshot_id,
                                   strategy_version_id=obj.object_id, operation_key=operation_key)
    assert runner.research_contract(credentials["evaluator"], snapshot_id=snapshot.snapshot_id,
                                     strategy_version_id=obj.object_id, operation_key=operation_key) == eid
    request = GateInput(strategy_version_id=obj.object_id, snapshot_id=snapshot.snapshot_id,
                        gate_id=0, expected_version=0, evidence_ids=(eid,), metrics=(), operation_key=uid("OP"))
    return request


def test_authentic_execution_passes_and_remains_idempotent(store, credentials, database):
    obj, snapshot, runner = verified_candidate(store, credentials, database)
    request = execute(store, credentials, obj, snapshot, runner)
    evaluator = Evaluator(store)
    result = evaluator.gate(credentials["evaluator"], request)
    assert result["decision"] == "PASS"
    assert evaluator.gate(credentials["evaluator"], request) == result
    with pytest.raises(DomainError, match="GATE_DEPENDENCY_UNSATISFIED"):
        evaluator.gate(credentials["evaluator"], request.model_copy(update={
            "gate_id": 3, "expected_version": 1, "operation_key": uid("OP"),
        }))
    with store.transaction(credentials["auditor"]) as (conn, _):
        assert store.audit(conn)["status"] == "VERIFIED"


@pytest.mark.parametrize("changes", [
    {"lower": None}, {"mode": "LIVE"}, {"campaign_id": "renamed"},
    {"dataset_snapshot_ids": ["not-pinned"]}, {"objective": "   "},
    {"evaluator_version": "other"}, {"metric_version": "other"},
])
def test_invalid_research_contract_cannot_be_certified(store, credentials, database, changes):
    obj, snapshot, runner = verified_candidate(store, credentials, database, contract_changes=changes)
    request = execute(store, credentials, obj, snapshot, runner)
    assert Evaluator(store).gate(credentials["evaluator"], request)["decision"] == "FAIL"


def test_unsigned_boolean_evidence_is_rejected_without_advancing_state(store, credentials, database):
    obj, snapshot, _ = verified_candidate(store, credentials, database)
    with store.transaction(credentials["evaluator"]) as (conn, actor):
        aid = store.put_artifact(conn, actor, {"snapshot_id": snapshot.snapshot_id,
            "checks": dict.fromkeys(REQUIRED_CHECKS[0], True)}, schema_name="gate-report-v1",
            classification="INTERNAL", policy_version="v1")
        eid = uid("EVID")
        conn.execute("INSERT INTO evidence VALUES(%s,%s,'research_contract','DERIVED_VALUE',"
                     "'DEVELOPMENT',now(),'{}',%s,now())", (eid, aid, actor.principal_id))
    request = GateInput(strategy_version_id=obj.object_id, snapshot_id=snapshot.snapshot_id,
                        gate_id=0, expected_version=0, evidence_ids=(eid,), metrics=(), operation_key=uid("OP"))
    with pytest.raises(DomainError, match="UNVERIFIED_GATE_EVIDENCE"):
        Evaluator(store).gate(credentials["evaluator"], request)
    with store.transaction(credentials["auditor"]) as (conn, _):
        assert store.state(conn, "candidate", obj.object_id) is None


def test_unenrolled_key_cannot_execute_or_enroll_via_application_login(store, credentials, database):
    obj, snapshot, runner = verified_candidate(store, credentials, database)
    impostor = VerificationRunner(store, runner.key_id, Ed25519PrivateKey.generate())
    with pytest.raises(DomainError, match="UNAUTHORIZED_VERIFIER"):
        impostor.research_contract(credentials["evaluator"], snapshot_id=snapshot.snapshot_id,
                                   strategy_version_id=obj.object_id, operation_key=uid("OP"))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with store.transaction(credentials["evaluator"]) as (conn, actor):
            conn.execute("INSERT INTO verifier_keys(verifier_key_id,principal_id,verifier_version,"
                         "public_key,code_hash) VALUES(%s,%s,'fake',%s,'sha256:fake')",
                         (uid("KEY"), actor.principal_id, b"x" * 32))


def test_forged_execution_signature_and_rebinding_are_rejected(store, credentials, database):
    obj, snapshot, runner = verified_candidate(store, credentials, database)
    request = execute(store, credentials, obj, snapshot, runner)
    with store.transaction(credentials["evaluator"]) as (conn, actor):
        original = conn.execute("SELECT v.* FROM verifier_executions v JOIN evidence e "
                                "ON e.artifact_id=v.report_artifact_id WHERE e.evidence_id=%s",
                                (request.evidence_ids[0],)).fetchone()
        report = store.artifact(conn, actor, original["report_artifact_id"])["content"]
        report["forged"] = True
        aid = store.put_artifact(conn, actor, report, schema_name="verified-gate-report-v1",
                                 classification="INTERNAL", policy_version="v1")
        artifact = store.artifact(conn, actor, aid)
        manifest_copy = {**original["manifest"], "report_artifact_id": aid,
                         "report_hash": artifact["content_hash"], "verifier_execution_id": uid("VERIFY")}
        conn.execute("INSERT INTO verifier_executions(verifier_execution_id,verifier_key_id,snapshot_id,"
                     "strategy_version_id,gate_id,input_hash,report_artifact_id,report_hash,manifest,"
                     "signature,event_id) VALUES(%s,%s,%s,%s,0,%s,%s,%s,%s,%s,%s)",
                     (manifest_copy["verifier_execution_id"], runner.key_id, snapshot.snapshot_id,
                      obj.object_id, original["input_hash"], aid, artifact["content_hash"],
                      Jsonb(manifest_copy), bytes(original["signature"]), original["event_id"]))
        eid = uid("EVID")
        conn.execute("INSERT INTO evidence VALUES(%s,%s,'research_contract','DERIVED_VALUE',"
                     "'DEVELOPMENT',now(),'{}',%s,now())", (eid, aid, actor.principal_id))
    with pytest.raises(DomainError, match="INVALID_VERIFIER_SIGNATURE"):
        Evaluator(store).gate(credentials["evaluator"], request.model_copy(update={"evidence_ids": (eid,)}))


def test_revoked_verifier_key_is_not_gate_authority(store, credentials, database):
    obj, snapshot, runner = verified_candidate(store, credentials, database)
    request = execute(store, credentials, obj, snapshot, runner)
    with psycopg.connect(database["test_owner_dsn"]) as conn:
        conn.execute("UPDATE verifier_keys SET enabled=false WHERE verifier_key_id=%s", (runner.key_id,))
    with pytest.raises(DomainError, match="UNVERIFIED_GATE_EVIDENCE"):
        Evaluator(store).gate(credentials["evaluator"], request)
