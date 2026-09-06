from datetime import UTC, datetime, timedelta

from liki.governance import AutomatedCheck, Incident, IncidentSeverity, IncidentStatus
from liki.reliability_service import CorrectiveAction, ReliabilityService, SliDefinition
from tests.test_governance_service import provenance


NOW = datetime(2026, 9, 6, tzinfo=UTC)


def check(store, credentials, check_id):
    artifact = provenance(store, credentials["evaluator"], {
        "check_id": check_id, "check_kind": "regression", "result": "PASS", "executed_at_utc": NOW.isoformat(),
    }, "governance/automated-check-result/v1")
    return AutomatedCheck(check_id=check_id, check_kind="regression", result="PASS", result_artifact=artifact, executed_at=NOW)


def test_incident_lifecycle_preserves_evidence_and_blocks_promotion(store, credentials):
    service = ReliabilityService(store)
    evidence = provenance(store, credentials["governance"], {"failure": "reconciliation"}, "reliability/incident-evidence/v1")
    with store.transaction(credentials["governance"]) as (conn, actor):
        incident = Incident(incident_id="incident-1", severity=IncidentSeverity.SEV1, status=IncidentStatus.OPEN,
                            incident_type="reconciliation", opened_at=NOW, opened_by=actor.principal_id,
                            affected_modules=("paper",), evidence=(evidence,))
        service.declare_incident(conn, actor, incident, "declare", "reliability-v1", owner_recipient="owner-channel")
        assert service.promotion_blockers(conn) == ("incident:incident-1",)
        service.contain(conn, actor, incident.incident_id, "stop paper run", evidence, "contain", "reliability-v1")
        service.begin_reconciliation(conn, actor, incident.incident_id, "reconcile", "reliability-v1")
        completion = provenance(store, credentials["governance"], {"fix": "reconciled"}, "reliability/action/v1")
        service.record_corrective_action(conn, actor, incident.incident_id, CorrectiveAction(
            corrective_action_id="fix-1", description="repair state", completion_artifact=completion,
            regression_checks=(check(store, credentials, "regression-1"),), verified_at=NOW,
        ), "correct", "reliability-v1")
        root = provenance(store, credentials["governance"], {"root": "upstream"}, "reliability/root/v1")
        impact = provenance(store, credentials["governance"], {"impact": "paper only"}, "reliability/impact/v1")
        service.resolve(conn, actor, incident.incident_id, (evidence,), root, impact, "resolve", "reliability-v1")
        postmortem = provenance(store, credentials["governance"], {"learning": "add check"}, "reliability/incident-postmortem/v1")
        service.close(conn, actor, incident.incident_id, postmortem, "close", "reliability-v1")
        remediation = provenance(store, credentials["governance"], {"remediation": "verified"}, "reliability/incident-remediation/v1")
        service.lift_incident_freeze(conn, actor, incident.incident_id, remediation, "unfreeze", "reliability-v1")
        assert service.promotion_blockers(conn) == ()


def test_slo_windows_use_deterministic_integer_error_budget_and_freeze(store, credentials):
    service = ReliabilityService(store)
    definition_artifact = provenance(store, credentials["governance"], {"sli": "scheduler"}, "reliability/sli-definition/v1")
    definition = SliDefinition(sli_id="scheduler-sli", service_scope="SCHEDULER_PROGRESS", target_basis_points=9900,
                               window_seconds=3600, breach_threshold=2, policy_version="reliability-v1", definition_artifact=definition_artifact)
    with store.transaction(credentials["governance"]) as (conn, actor):
        service.define_sli(conn, actor, definition, "define-sli")
        measurement = provenance(store, credentials["governance"], {"run": "failed"}, "reliability/sli-measurement/v1")
        service.record_sample(conn, actor, definition.sli_id, "sample-1", NOW - timedelta(minutes=1), False, measurement)
        first = service.evaluate_sli(conn, actor, definition.sli_id, NOW, "evaluate-1")
        second = service.evaluate_sli(conn, actor, definition.sli_id, NOW + timedelta(seconds=1), "evaluate-2")
        assert first["compliance_basis_points"] == 0
        assert first["error_budget_consumed_basis_points"] == 10000
        assert second["status"] == "BREACHED"
        assert service.promotion_blockers(conn) == ("sli:scheduler-sli",)
        remediation = provenance(store, credentials["governance"], {"remediation": "capacity"}, "reliability/slo-remediation/v1")
        service.lift_sli_freeze(conn, actor, definition.sli_id, remediation)
        assert service.promotion_blockers(conn) == ()
