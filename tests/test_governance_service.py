from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json

import psycopg
import pytest

from liki.core import DomainError, uid
from liki.governance import (
    ApprovalSnapshot,
    ArtifactProvenance,
    AutomatedCheck,
    ChangeClass,
    EvidenceReference,
    GovernanceProposal,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    LifecycleEvidence,
    SnapshotDependency,
    load_governance_policy,
)
from liki.governance.domain import ReplayEvent
from liki.governance_service import GovernanceService
from liki.outbox import Outbox
from liki.store import issue_credential


NOW = datetime(2026, 9, 6, tzinfo=UTC)


def provenance(store, credential, content, schema, *, classification="INTERNAL", policy="test"):
    with store.transaction(credential) as (conn, actor):
        artifact_id = store.put_artifact(conn, actor, content, schema_name=schema, classification=classification, policy_version=policy)
        row = conn.execute("SELECT * FROM artifacts WHERE artifact_id=%s", (artifact_id,)).fetchone()
        return ArtifactProvenance(
            artifact_id=artifact_id,
            content_hash=row["content_hash"],
            authenticated_principal=actor.principal_id,
            environment_fingerprint=row["environment_fingerprint"],
            code_fingerprint=actor.code_fingerprint,
            classification=row["classification"],
        )


def approval_snapshot(policy, evidence_hash):
    dependency = SnapshotDependency(scope=policy.policy_id, version=policy.policy_version, content_hash=policy.content_hash)
    body = {"dependencies": [dependency.model_dump(mode="json")], "known_incident_ids": [], "evidence_hashes": [evidence_hash]}
    return ApprovalSnapshot(
        dependencies=(dependency,), evidence_hashes=(evidence_hash,),
        snapshot_hash="sha256:" + sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    )


def install_policy(service, store, credentials):
    policy = load_governance_policy()
    with store.transaction(credentials["governance"]) as (conn, _):
        if conn.execute("SELECT 1 FROM policy_versions WHERE policy_id=%s AND policy_version=%s", (policy.policy_id, policy.policy_version)).fetchone():
            return policy
    artifact = provenance(store, credentials["governance"], {"policy_id": policy.policy_id, "policy_version": policy.policy_version, "content_hash": policy.content_hash}, "governance/policy-version/v1")
    with store.transaction(credentials["governance"]) as (conn, actor):
        service.register_policy(conn, actor, policy, artifact, uid("policy"), effective=True)
    return policy


def make_proposal(store, credentials, policy):
    evidence = provenance(store, credentials["governance"], {"finding": "measured"}, "governance/evidence/v1")
    with store.transaction(credentials["governance"]) as (_, actor):
        return GovernanceProposal(
            proposal_id=uid("proposal"), proposal_version=1, authored_by=actor.principal_id,
            declared_class=ChangeClass.GREEN, problem="Measured scheduling waste", proposed_change="Tighten a bounded timeout",
            affected_modules=("scheduler",), evidence=(EvidenceReference(role="evidence", artifact=evidence),),
            historical_replay_plan="Replay historical scheduler events", risk_if_changed="May defer work", risk_if_not_changed="Waste continues",
            rollback_plan="Restore prior value", approval_snapshot=approval_snapshot(policy, evidence.content_hash), created_at=NOW,
        )


def test_service_rejects_forged_producer_and_owner_veto_is_durable(store, credentials):
    service = GovernanceService(store)
    policy = install_policy(service, store, credentials)
    proposal = make_proposal(store, credentials, policy)
    forged = proposal.model_copy(update={"evidence": (EvidenceReference(role="evidence", artifact=proposal.evidence[0].artifact.model_copy(update={"authenticated_principal": "forged"})),)})
    with store.transaction(credentials["governance"]) as (conn, actor):
        with pytest.raises(DomainError, match="FORGED_PROVENANCE"):
            service.propose(conn, actor, forged, uid("forged"), policy.policy_version)
        service.propose(conn, actor, proposal, uid("proposal"), policy.policy_version)
    operation_key = uid("veto")
    with store.transaction(credentials["owner"]) as (conn, actor):
        decision = service.decide(conn, actor, proposal.proposal_id, "VETO", "Owner rejects this change", 1, operation_key, policy.policy_version)
        assert decision.vetoed
        attestation = store.artifact(conn, actor, decision.decision_artifact.artifact_id)
        assert attestation["schema_name"] == "governance/server-owner-decision-attestation/v1"
        assert attestation["content"]["proposal_id"] == proposal.proposal_id
        assert attestation["content"]["proposal_version"] == proposal.proposal_version
        assert attestation["content"]["owner_principal"] == actor.principal_id
        assert attestation["content"]["decision"] == "VETO"
    with store.transaction(credentials["owner"]) as (conn, actor):
        replay = service.decide(conn, actor, proposal.proposal_id, "VETO", "Owner rejects this change", 1, operation_key, policy.policy_version)
        assert replay == decision
        with pytest.raises(DomainError, match="IDEMPOTENCY_CONFLICT"):
            service.decide(conn, actor, proposal.proposal_id, "VETO", "Changed reason", 1, operation_key, policy.policy_version)
        with pytest.raises(DomainError, match="capability: artifact"):
            store.put_artifact(conn, actor, {"untrusted": "owner write"}, schema_name="anything/v1", classification="INTERNAL", policy_version=policy.policy_version)
    with store.transaction(credentials["auditor"]) as (conn, _):
        assert conn.execute("SELECT status FROM governance_proposals WHERE proposal_id=%s", (proposal.proposal_id,)).fetchone()["status"] == "VETOED"


def test_spoofed_automated_check_and_stale_concurrent_writer_are_rejected(store, credentials, database):
    service = GovernanceService(store)
    policy = install_policy(service, store, credentials)
    proposal = make_proposal(store, credentials, policy)
    with store.transaction(credentials["governance"]) as (conn, actor):
        service.propose(conn, actor, proposal, uid("proposal"), policy.policy_version)
    spoof = provenance(store, credentials["evaluator"], {"check_id": "check", "check_kind": "integration", "result": "FAIL"}, "governance/automated-check-result/v1")
    check = AutomatedCheck(check_id="check", check_kind="integration", result="PASS", result_artifact=spoof, executed_at=NOW)
    with store.transaction(credentials["governance"]) as (conn, actor):
        with pytest.raises(DomainError, match="ARTIFACT_CONTENT_MISMATCH"):
            service.record_lifecycle(conn, actor, proposal.proposal_id, LifecycleEvidence(tests=(check,)), 1, uid("check"), policy.policy_version)

    classifier = issue_credential(database["test_owner_dsn"], uid("classifier"), "governance", duration=timedelta(hours=1))

    def classify_once(_):
        try:
            with store.transaction(classifier) as (conn, actor):
                service.classify(conn, actor, proposal.proposal_id, policy, 1, uid("classify"))
            return "ok"
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(classify_once, range(2))) == ["CONCURRENT_MODIFICATION", "ok"]


def test_incident_freezes_revalidation_and_replay_is_persisted_with_real_history(store, credentials, database):
    service = GovernanceService(store)
    policy = install_policy(service, store, credentials)
    proposal = make_proposal(store, credentials, policy)
    classifier = issue_credential(database["test_owner_dsn"], uid("classifier"), "governance", duration=timedelta(hours=1))
    with store.transaction(credentials["governance"]) as (conn, actor):
        service.propose(conn, actor, proposal, uid("proposal"), policy.policy_version)
    with store.transaction(classifier) as (conn, actor):
        service.classify(conn, actor, proposal.proposal_id, policy, 1, uid("classify"))
    incident_evidence = provenance(store, credentials["governance"], {"incident": "control-plane"}, "governance/incident-evidence/v1")
    with store.transaction(credentials["governance"]) as (conn, actor):
        incident = Incident(incident_id=uid("incident"), severity=IncidentSeverity.SEV1, status=IncidentStatus.OPEN, incident_type="control-plane", opened_at=NOW, opened_by=actor.principal_id, affected_modules=("scheduler",), evidence=(incident_evidence,))
        service.declare_incident(conn, actor, incident, uid("incident"), policy.policy_version)
    with store.transaction(credentials["governance"]) as (conn, actor):
        assert service.evaluate(conn, actor, proposal.proposal_id, 2, uid("evaluate"), policy.policy_version).value == "FROZEN"

    reconciliation = provenance(store, credentials["governance"], {"reconciled": True}, "governance/reconciliation/v1")
    root_cause = provenance(store, credentials["governance"], {"cause": "tested"}, "governance/root-cause/v1")
    impact = provenance(store, credentials["governance"], {"impact": "bounded"}, "governance/impact/v1")
    postmortem = provenance(store, credentials["governance"], {"postmortem": "complete"}, "governance/postmortem/v1")
    with store.transaction(credentials["governance"]) as (conn, actor):
        service.advance_incident(conn, actor, incident.incident_id, IncidentStatus.CONTAINED, 1, uid("contain"), policy.policy_version)
        service.advance_incident(conn, actor, incident.incident_id, IncidentStatus.RECONCILING, 2, uid("reconcile"), policy.policy_version)
        service.advance_incident(conn, actor, incident.incident_id, IncidentStatus.RESOLVED, 3, uid("resolve"), policy.policy_version, reconciliation_evidence=(reconciliation,), root_cause_artifact=root_cause, impact_assessment_artifact=impact)
        closed = service.advance_incident(conn, actor, incident.incident_id, IncidentStatus.CLOSED, 4, uid("close"), policy.policy_version, postmortem_artifact=postmortem)
        assert closed.status is IncidentStatus.CLOSED

    historical_input = provenance(store, credentials["governance"], {"source": "historical decision log"}, "governance/historical-replay-input/v1")
    source = provenance(store, credentials["governance"], {"branch": "historic"}, "governance/historical-event/v1")
    event = ReplayEvent(branch_id="historic", actual_decision="ADVANCE", counterfactual_decision="KILLED", later_outcome="LATE_DEATH", compute_cost_usd=4.0, statistical_capital=2.0, source_artifact=source)
    with store.transaction(credentials["governance"]) as (conn, actor):
        result = service.persist_replay(conn, actor, proposal.proposal_id, (event,), historical_input, uid("replay"), policy.policy_version)
        assert result["result"].late_deaths_prevented == 1
    with store.transaction(credentials["auditor"]) as (conn, _):
        assert conn.execute("SELECT count(*) AS n FROM governance_replays").fetchone()["n"] >= 1


def test_monthly_and_emergency_governance_schedules_are_durable(store, credentials):
    service = GovernanceService(store)
    with store.transaction(credentials["governance"]) as (conn, actor):
        service.schedule_monthly(conn, actor, uid("monthly"), NOW, 0, uid("schedule"), "1.0.0")
    with store.transaction(credentials["scheduler"]) as (conn, actor):
        service.schedule_emergency(conn, actor, uid("emergency"), NOW, 0, uid("emergency"), "1.0.0")
    with store.transaction(credentials["auditor"]) as (conn, _):
        statuses = {row["status"] for row in conn.execute("SELECT status FROM governance_schedules")}
        assert {"SCHEDULED", "DUE"} <= statuses


def test_owner_delivery_is_outbox_backed_and_binds_real_check_and_receipt_times(store, credentials, database):
    service = GovernanceService(store)
    policy = install_policy(service, store, credentials)
    proposal = make_proposal(store, credentials, policy)
    with store.transaction(credentials["governance"]) as (conn, actor):
        service.propose(conn, actor, proposal, uid("proposal"), policy.policy_version)

    check_artifact = provenance(
        store,
        credentials["evaluator"],
        {"check_id": "acceptance", "check_kind": "integration", "result": "PASS", "executed_at_utc": NOW.isoformat()},
        "governance/automated-check-result/v1",
    )
    check = AutomatedCheck(
        check_id="acceptance", check_kind="integration", result="PASS", result_artifact=check_artifact, executed_at=NOW
    )
    lifecycle = LifecycleEvidence(tests=(check,))
    with store.transaction(credentials["governance"]) as (conn, actor):
        service.record_lifecycle(conn, actor, proposal.proposal_id, lifecycle, 1, uid("lifecycle"), policy.policy_version)

    with store.transaction(credentials["governance"]) as (conn, actor):
        with pytest.raises(DomainError, match="OWNER_NOTIFICATION_NOT_QUEUED"):
            service.record_owner_delivery(conn, actor, proposal.proposal_id, "owner-secure", 2, uid("premature-receipt"), policy.policy_version)

    package = provenance(
        store,
        credentials["governance"],
        {
            "proposal_id": proposal.proposal_id,
            "channel": "owner-secure",
            "lifecycle_snapshot_hash": lifecycle.snapshot_hash(),
            "title": "Governance decision required",
            "message": "Please approve or veto the reviewed proposal.",
        },
        "governance/owner-notification-package/v1",
    )
    with store.transaction(credentials["governance"]) as (conn, actor):
        service.queue_owner_notification(conn, actor, proposal.proposal_id, "owner-secure", package, 2, uid("queue-owner"), policy.policy_version)
    with store.transaction(credentials["auditor"]) as (conn, _):
        notification_id = conn.execute("SELECT notification_id FROM notification_records WHERE object_id=%s", (proposal.proposal_id,)).fetchone()["notification_id"]
    with psycopg.connect(database["test_owner_dsn"]) as conn:
        conn.execute("UPDATE transactional_outbox SET available_at=now()+interval '1 day' WHERE topic='telegram.notification' AND payload->>'notification_id'<>%s", (notification_id,))
    lease = Outbox(store).claim(credentials["scheduler"], ("telegram.notification",))
    assert lease and lease.payload == {"notification_id": notification_id}
    assert Outbox(store).finish(credentials["scheduler"], lease, receipt="provider-message-1") == "DELIVERED"
    with store.transaction(credentials["governance"]) as (conn, actor):
        delivery = service.record_owner_delivery(conn, actor, proposal.proposal_id, "owner-secure", 3, uid("receipt"), policy.policy_version)
        assert delivery.provider_message_id == "provider-message-1"
        assert delivery.lifecycle_snapshot_hash == lifecycle.snapshot_hash()


def test_lifecycle_failure_is_immutable_and_requires_fresh_notification_receipt(store, credentials, database):
    service = GovernanceService(store)
    policy = install_policy(service, store, credentials)
    proposal = make_proposal(store, credentials, policy)
    with store.transaction(credentials["governance"]) as (conn, actor):
        service.propose(conn, actor, proposal, uid("proposal"), policy.policy_version)

    def verified_check(check_id, result, executed_at):
        artifact = provenance(
            store,
            credentials["evaluator"],
            {"check_id": check_id, "check_kind": "integration", "result": result, "executed_at_utc": executed_at.isoformat()},
            "governance/automated-check-result/v1",
        )
        return AutomatedCheck(check_id=check_id, check_kind="integration", result=result, result_artifact=artifact, executed_at=executed_at)

    accepted_lifecycle = LifecycleEvidence(tests=(verified_check("acceptance-v1", "PASS", NOW),))
    with store.transaction(credentials["governance"]) as (conn, actor):
        service.record_lifecycle(conn, actor, proposal.proposal_id, accepted_lifecycle, 1, uid("accepted-lifecycle"), policy.policy_version)
    initial_package = provenance(
        store,
        credentials["governance"],
        {"proposal_id": proposal.proposal_id, "channel": "owner-secure", "lifecycle_snapshot_hash": accepted_lifecycle.snapshot_hash(), "title": "Governance decision required", "message": "Please approve or veto the reviewed proposal."},
        "governance/owner-notification-package/v1",
    )
    with store.transaction(credentials["governance"]) as (conn, actor):
        service.queue_owner_notification(conn, actor, proposal.proposal_id, "owner-secure", initial_package, 2, uid("initial-notification"), policy.policy_version)
    with store.transaction(credentials["auditor"]) as (conn, _):
        initial_notification_id = conn.execute("SELECT notification_id FROM notification_records WHERE object_id=%s ORDER BY created_at DESC LIMIT 1", (proposal.proposal_id,)).fetchone()["notification_id"]
    with psycopg.connect(database["test_owner_dsn"]) as conn:
        conn.execute("UPDATE transactional_outbox SET available_at=now()+interval '1 day' WHERE topic='telegram.notification' AND payload->>'notification_id'<>%s", (initial_notification_id,))
    lease = Outbox(store).claim(credentials["scheduler"], ("telegram.notification",))
    assert lease and lease.payload == {"notification_id": initial_notification_id}
    assert Outbox(store).finish(credentials["scheduler"], lease, receipt="provider-message-initial") == "DELIVERED"
    with store.transaction(credentials["governance"]) as (conn, actor):
        initial_delivery = service.record_owner_delivery(conn, actor, proposal.proposal_id, "owner-secure", 3, uid("initial-receipt"), policy.policy_version)

    failed_at = initial_delivery.delivered_at + timedelta(seconds=1)
    failed_lifecycle = LifecycleEvidence(tests=(verified_check("acceptance-v2", "FAIL", failed_at),))
    with store.transaction(credentials["governance"]) as (conn, actor):
        service.record_lifecycle(conn, actor, proposal.proposal_id, failed_lifecycle, 4, uid("failed-lifecycle"), policy.policy_version)
    with store.transaction(credentials["auditor"]) as (conn, _):
        immutable_failure = conn.execute("SELECT metadata FROM event_log WHERE aggregate_id=%s AND event_type='GOVERNANCE_LIFECYCLE_EVIDENCE' ORDER BY occurred_at_utc DESC LIMIT 1", (proposal.proposal_id,)).fetchone()
        assert immutable_failure["metadata"]["lifecycle"]["tests"][0]["result"] == "FAIL"
        outcomes = conn.execute("SELECT phase,result FROM governance_lifecycle_outcomes WHERE proposal_id=%s ORDER BY executed_at", (proposal.proposal_id,)).fetchall()
        assert outcomes == [{"phase": "tests", "result": "PASS"}, {"phase": "tests", "result": "FAIL"}]

    with store.transaction(credentials["governance"]) as (conn, actor):
        with pytest.raises(DomainError, match="REVALIDATION_REQUIRES_FRESH_EVIDENCE"):
            service.record_lifecycle(conn, actor, proposal.proposal_id, accepted_lifecycle, 5, uid("reused-lifecycle"), policy.policy_version)

    revalidated_lifecycle = LifecycleEvidence(tests=(verified_check("acceptance-v3", "PASS", failed_at + timedelta(seconds=1)),))
    with store.transaction(credentials["governance"]) as (conn, actor):
        service.record_lifecycle(conn, actor, proposal.proposal_id, revalidated_lifecycle, 5, uid("revalidated-lifecycle"), policy.policy_version)
        with pytest.raises(DomainError, match="OWNER_NOTIFICATION_NOT_QUEUED"):
            service.record_owner_delivery(conn, actor, proposal.proposal_id, "owner-secure", 6, uid("old-receipt"), policy.policy_version)
    replacement_package = provenance(
        store,
        credentials["governance"],
        {"proposal_id": proposal.proposal_id, "channel": "owner-secure", "lifecycle_snapshot_hash": revalidated_lifecycle.snapshot_hash(), "title": "Governance decision required", "message": "A revalidated evidence package requires a new decision window."},
        "governance/owner-notification-package/v1",
    )
    with store.transaction(credentials["governance"]) as (conn, actor):
        service.queue_owner_notification(conn, actor, proposal.proposal_id, "owner-secure", replacement_package, 6, uid("replacement-notification"), policy.policy_version)
    with store.transaction(credentials["auditor"]) as (conn, _):
        replacement_notification_id = conn.execute("SELECT notification_id FROM notification_records WHERE object_id=%s ORDER BY created_at DESC LIMIT 1", (proposal.proposal_id,)).fetchone()["notification_id"]
    assert replacement_notification_id != initial_notification_id


def test_monthly_schedule_race_rejects_stale_writer(store, credentials):
    service = GovernanceService(store)
    schedule_id = uid("monthly-race")

    def schedule_once(_: int) -> str:
        try:
            with store.transaction(credentials["governance"]) as (conn, actor):
                service.schedule_monthly(conn, actor, schedule_id, NOW, 0, uid("monthly-op"), "1.0.0")
            return "ok"
        except DomainError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(schedule_once, range(2))) == ["CONCURRENT_MODIFICATION", "ok"]
