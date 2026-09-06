"""Authenticated incident and reliability SLO persistence."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from psycopg.types.json import Jsonb
from pydantic import Field

from liki.core import Contract, DomainError, content_hash, uid, utcnow
from liki.governance import ArtifactProvenance, AutomatedCheck, Incident, IncidentSeverity, IncidentStatus, transition_incident
from liki.outbox import Notification, Outbox
from liki.store import Identity, Store


class SliDefinition(Contract):
    sli_id: str = Field(min_length=1)
    service_scope: Literal["CONTROL_PLANE", "SCHEDULER_PROGRESS", "INFERENCE_ROUTE", "EVALUATOR_BACKTEST", "MARKET_DATA_FRESHNESS", "PAPER_RECONCILIATION", "EVIDENCE_DURABILITY"]
    target_basis_points: int = Field(ge=0, le=10000)
    window_seconds: int = Field(ge=60, le=31536000)
    breach_threshold: int = Field(ge=1)
    policy_version: str = Field(min_length=1)
    definition_artifact: ArtifactProvenance


class CorrectiveAction(Contract):
    corrective_action_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    completion_artifact: ArtifactProvenance
    regression_checks: tuple[AutomatedCheck, ...] = Field(min_length=1)
    verified_at: datetime


class ReliabilityService:
    LOCK_KEY = 71403218

    def __init__(self, store: Store):
        self.store = store
        self.outbox = Outbox(store)

    @classmethod
    def _lock(cls, conn: Any) -> None:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (cls.LOCK_KEY,))

    @staticmethod
    def _incident_actor(actor: Identity) -> None:
        actor.require("incident")

    @staticmethod
    def _governance(actor: Identity) -> None:
        if actor.role != "governance":
            raise DomainError("FORBIDDEN", "Reliability configuration requires governance authority")

    @staticmethod
    def _artifact(conn: Any, value: ArtifactProvenance, *, schema: str | None = None) -> dict[str, Any]:
        row = conn.execute(
            "SELECT a.*,p.code_fingerprint AS producer_code_fingerprint FROM artifacts a JOIN principals p "
            "ON p.principal_id=a.producer_id WHERE a.artifact_id=%s", (value.artifact_id,)
        ).fetchone()
        if not row:
            raise DomainError("UNKNOWN_ARTIFACT")
        if content_hash(row["content"]) != row["content_hash"]:
            raise DomainError("ARTIFACT_CORRUPTED")
        if (row["content_hash"] != value.content_hash or row["producer_id"] != value.authenticated_principal
                or row["environment_fingerprint"] != value.environment_fingerprint
                or row["producer_code_fingerprint"] != value.code_fingerprint):
            raise DomainError("FORGED_PROVENANCE")
        if schema and row["schema_name"] != schema:
            raise DomainError("ARTIFACT_SCHEMA_MISMATCH")
        return row

    def _check(self, conn: Any, check: AutomatedCheck) -> str:
        row = self._artifact(conn, check.result_artifact, schema="governance/automated-check-result/v1")
        if (row["content"].get("check_id"), row["content"].get("check_kind"), row["content"].get("result")) != (check.check_id, check.check_kind, check.result):
            raise DomainError("ARTIFACT_CONTENT_MISMATCH")
        if check.result != "PASS":
            raise DomainError("REGRESSION_CHECK_FAILED")
        recorded_at = row["content"].get("executed_at_utc")
        if not isinstance(recorded_at, str):
            raise DomainError("AUTOMATED_CHECK_TIMESTAMP_MISSING")
        try:
            executed_at = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise DomainError("AUTOMATED_CHECK_TIMESTAMP_INVALID") from error
        if executed_at.tzinfo is None or executed_at.utcoffset() != timedelta(0) or executed_at != check.executed_at:
            raise DomainError("FORGED_AUTOMATED_CHECK_TIMESTAMP")
        return row["artifact_id"]

    @staticmethod
    def _incident(conn: Any, incident_id: str) -> tuple[dict[str, Any], Incident]:
        row = conn.execute("SELECT * FROM incidents WHERE incident_id=%s FOR UPDATE", (incident_id,)).fetchone()
        if not row:
            raise DomainError("UNKNOWN_INCIDENT")
        return row, Incident.model_validate(row["incident"], strict=False)

    def _transition_incident(self, conn: Any, actor: Identity, row: dict[str, Any], before: Incident, after: Incident,
                             event_type: str, operation_key: str, policy_version: str, artifact_ids: tuple[str, ...]) -> None:
        self.store.transition(conn, actor, capability="incident", kind="incident", aggregate_id=after.incident_id,
            expected_version=row["state_version"], state={"status": after.status.value, "severity": after.severity.value},
            event_type=event_type, operation_key=operation_key, task_id=f"incident:{after.incident_id}",
            policy_version=policy_version, artifact_ids=artifact_ids)
        conn.execute("UPDATE incidents SET incident=%s,status=%s,state_version=%s,updated_at=now() WHERE incident_id=%s",
                     (Jsonb(after.model_dump(mode="json")), after.status.value, after.state_version, after.incident_id))

    def declare_incident(self, conn: Any, actor: Identity, incident: Incident, operation_key: str, policy_version: str,
                         owner_recipient: str | None = None) -> str | None:
        self._lock(conn)
        self._incident_actor(actor)
        if incident.opened_by != actor.principal_id or incident.status is not IncidentStatus.OPEN:
            raise DomainError("FORGED_INCIDENT_DECLARATION")
        evidence_ids = tuple(self._artifact(conn, item)["artifact_id"] for item in incident.evidence)
        notification_id = None
        if incident.severity in {IncidentSeverity.SEV0, IncidentSeverity.SEV1}:
            if not owner_recipient:
                raise DomainError("OWNER_NOTIFICATION_RECIPIENT_REQUIRED")
            notification_id = self.outbox.notify(conn, actor, Notification(
                deduplication_key=f"incident:{incident.incident_id}", urgency="CRITICAL" if incident.severity is IncidentSeverity.SEV0 else "HIGH",
                classification="INTERNAL", recipient_ref=owner_recipient, title=f"{incident.severity.value} incident declared",
                message=f"Incident {incident.incident_id} requires owner awareness.", object_id=incident.incident_id,
            ))
        self.store.transition(conn, actor, capability="incident", kind="incident", aggregate_id=incident.incident_id,
            expected_version=0, state={"status": "OPEN", "severity": incident.severity.value}, event_type="INCIDENT_DECLARED",
            operation_key=operation_key, task_id=f"incident:{incident.incident_id}", policy_version=policy_version, artifact_ids=evidence_ids)
        conn.execute("INSERT INTO incidents(incident_id,incident,severity,status,state_version,opened_by,opened_at) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                     (incident.incident_id, Jsonb(incident.model_dump(mode="json")), incident.severity.value, incident.status.value,
                      incident.state_version, actor.principal_id, incident.opened_at))
        for artifact_id in evidence_ids:
            conn.execute("INSERT INTO incident_evidence_snapshots(incident_id,artifact_id,captured_by,captured_at) VALUES(%s,%s,%s,%s)",
                         (incident.incident_id, artifact_id, actor.principal_id, utcnow()))
        if incident.severity in {IncidentSeverity.SEV0, IncidentSeverity.SEV1}:
            conn.execute("INSERT INTO incident_promotion_freezes(incident_id,reason,frozen_by,frozen_at) VALUES(%s,%s,%s,%s)",
                         (incident.incident_id, "material incident pending reconciliation", actor.principal_id, utcnow()))
        return notification_id

    def contain(self, conn: Any, actor: Identity, incident_id: str, action: str, evidence: ArtifactProvenance,
                operation_key: str, policy_version: str) -> Incident:
        self._lock(conn)
        self._incident_actor(actor)
        row, incident = self._incident(conn, incident_id)
        artifact = self._artifact(conn, evidence)
        after = transition_incident(incident, IncidentStatus.CONTAINED, utcnow(), containment_action=action)
        self._transition_incident(conn, actor, row, incident, after, "INCIDENT_CONTAINED", operation_key, policy_version, (artifact["artifact_id"],))
        conn.execute("INSERT INTO incident_evidence_snapshots(incident_id,artifact_id,captured_by,captured_at) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                     (incident_id, artifact["artifact_id"], actor.principal_id, utcnow()))
        return after

    def begin_reconciliation(self, conn: Any, actor: Identity, incident_id: str, operation_key: str, policy_version: str) -> Incident:
        self._lock(conn)
        self._incident_actor(actor)
        row, incident = self._incident(conn, incident_id)
        after = transition_incident(incident, IncidentStatus.RECONCILING, utcnow())
        self._transition_incident(conn, actor, row, incident, after, "INCIDENT_RECONCILIATION_STARTED", operation_key, policy_version, ())
        return after

    def record_corrective_action(self, conn: Any, actor: Identity, incident_id: str, action: CorrectiveAction,
                                 operation_key: str, policy_version: str) -> Incident:
        self._lock(conn)
        self._governance(actor)
        row, incident = self._incident(conn, incident_id)
        if incident.status is not IncidentStatus.RECONCILING:
            raise DomainError("INCIDENT_NOT_RECONCILING")
        completion = self._artifact(conn, action.completion_artifact)
        regression_ids = tuple(self._check(conn, check) for check in action.regression_checks)
        after = incident.model_copy(update={"corrective_action_ids": (*incident.corrective_action_ids, action.corrective_action_id),
                                           "state_version": incident.state_version + 1})
        self._transition_incident(conn, actor, row, incident, after, "INCIDENT_CORRECTIVE_ACTION_VERIFIED", operation_key,
                                  policy_version, (completion["artifact_id"], *regression_ids))
        conn.execute("INSERT INTO incident_corrective_actions(corrective_action_id,incident_id,action_description,completion_artifact_id,regression_artifact_ids,verified_by,verified_at) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                     (action.corrective_action_id, incident_id, action.description, completion["artifact_id"], list(regression_ids), actor.principal_id, action.verified_at))
        return after

    def resolve(self, conn: Any, actor: Identity, incident_id: str, reconciliation_evidence: tuple[ArtifactProvenance, ...],
                root_cause: ArtifactProvenance, impact_assessment: ArtifactProvenance, operation_key: str,
                policy_version: str) -> Incident:
        self._lock(conn)
        self._governance(actor)
        row, incident = self._incident(conn, incident_id)
        if not incident.corrective_action_ids:
            raise DomainError("CORRECTIVE_ACTION_REQUIRED")
        completed = conn.execute("SELECT corrective_action_id FROM incident_corrective_actions WHERE incident_id=%s", (incident_id,)).fetchall()
        if set(incident.corrective_action_ids) != {item["corrective_action_id"] for item in completed}:
            raise DomainError("UNVERIFIED_CORRECTIVE_ACTION")
        artifacts = tuple(self._artifact(conn, item)["artifact_id"] for item in reconciliation_evidence)
        root = self._artifact(conn, root_cause)
        impact = self._artifact(conn, impact_assessment)
        after = transition_incident(incident, IncidentStatus.RESOLVED, utcnow(), reconciliation_evidence=reconciliation_evidence,
                                   root_cause_artifact=root_cause, impact_assessment_artifact=impact_assessment)
        self._transition_incident(conn, actor, row, incident, after, "INCIDENT_RESOLVED", operation_key, policy_version,
                                  (*artifacts, root["artifact_id"], impact["artifact_id"]))
        return after

    def close(self, conn: Any, actor: Identity, incident_id: str, postmortem: ArtifactProvenance | None,
              operation_key: str, policy_version: str) -> Incident:
        self._lock(conn)
        self._governance(actor)
        row, incident = self._incident(conn, incident_id)
        artifact_ids: tuple[str, ...] = ()
        if postmortem:
            artifact_ids = (self._artifact(conn, postmortem, schema="reliability/incident-postmortem/v1")["artifact_id"],)
        after = transition_incident(incident, IncidentStatus.CLOSED, utcnow(), postmortem_artifact=postmortem)
        self._transition_incident(conn, actor, row, incident, after, "INCIDENT_CLOSED", operation_key, policy_version, artifact_ids)
        return after

    def reopen(self, conn: Any, actor: Identity, incident_id: str, evidence: ArtifactProvenance,
               operation_key: str, policy_version: str) -> Incident:
        self._lock(conn)
        self._incident_actor(actor)
        row, incident = self._incident(conn, incident_id)
        if incident.status is not IncidentStatus.RESOLVED:
            raise DomainError("ONLY_RESOLVED_INCIDENTS_MAY_REOPEN")
        artifact = self._artifact(conn, evidence, schema="reliability/incident-reopen-evidence/v1")
        after = transition_incident(incident, IncidentStatus.OPEN, utcnow())
        self._transition_incident(conn, actor, row, incident, after, "INCIDENT_REOPENED", operation_key,
                                  policy_version, (artifact["artifact_id"],))
        conn.execute(
            "INSERT INTO incident_evidence_snapshots(incident_id,artifact_id,captured_by,captured_at) "
            "VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (incident_id, artifact["artifact_id"], actor.principal_id, utcnow()),
        )
        return after

    def link_recurrence(self, conn: Any, actor: Identity, incident_id: str, related_incident_id: str,
                        relationship_artifact: ArtifactProvenance, operation_key: str, policy_version: str) -> None:
        self._lock(conn)
        self._incident_actor(actor)
        row, incident = self._incident(conn, incident_id)
        self._incident(conn, related_incident_id)
        artifact = self._artifact(conn, relationship_artifact, schema="reliability/incident-cause-link/v1")
        self._transition_incident(conn, actor, row, incident, incident.model_copy(
            update={"state_version": incident.state_version + 1}
        ), "INCIDENT_RECURRENCE_LINKED", operation_key, policy_version, (artifact["artifact_id"],))
        conn.execute("INSERT INTO incident_cause_links(incident_id,related_incident_id,relationship_artifact_id,linked_by,linked_at) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                     (incident_id, related_incident_id, artifact["artifact_id"], actor.principal_id, utcnow()))

    def define_sli(self, conn: Any, actor: Identity, definition: SliDefinition, operation_key: str) -> None:
        self._lock(conn)
        self._governance(actor)
        artifact = self._artifact(conn, definition.definition_artifact, schema="reliability/sli-definition/v1")
        self.store.transition(conn, actor, capability="policy", kind="reliability_sli", aggregate_id=definition.sli_id,
            expected_version=0, state={"sli_id": definition.sli_id, "scope": definition.service_scope}, event_type="SLI_DEFINED",
            operation_key=operation_key, task_id=f"sli:{definition.sli_id}", policy_version=definition.policy_version,
            artifact_ids=(artifact["artifact_id"],))
        conn.execute("INSERT INTO reliability_sli_definitions(sli_id,service_scope,target_basis_points,window_seconds,breach_threshold,policy_version,definition_artifact_id,created_by,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                     (definition.sli_id, definition.service_scope, definition.target_basis_points, definition.window_seconds,
                      definition.breach_threshold, definition.policy_version, artifact["artifact_id"], actor.principal_id, utcnow()))

    def record_sample(self, conn: Any, actor: Identity, sli_id: str, sample_id: str, observed_at: datetime,
                      is_good: bool, measurement: ArtifactProvenance) -> None:
        self._lock(conn)
        if actor.role not in {"governance", "scheduler", "operator"}:
            raise DomainError("FORBIDDEN")
        if observed_at.tzinfo is None or observed_at.utcoffset() != timedelta(0):
            raise DomainError("UTC_REQUIRED")
        if not conn.execute("SELECT 1 FROM reliability_sli_definitions WHERE sli_id=%s", (sli_id,)).fetchone():
            raise DomainError("UNKNOWN_SLI")
        artifact = self._artifact(conn, measurement, schema="reliability/sli-measurement/v1")
        conn.execute("INSERT INTO reliability_sli_samples(sample_id,sli_id,observed_at,is_good,measurement_artifact_id,recorded_by) VALUES(%s,%s,%s,%s,%s,%s)",
                     (sample_id, sli_id, observed_at, is_good, artifact["artifact_id"], actor.principal_id))

    def evaluate_sli(self, conn: Any, actor: Identity, sli_id: str, window_end: datetime, operation_key: str) -> dict[str, Any]:
        self._lock(conn)
        if actor.role not in {"governance", "scheduler", "operator"}:
            raise DomainError("FORBIDDEN")
        definition = conn.execute("SELECT * FROM reliability_sli_definitions WHERE sli_id=%s FOR UPDATE", (sli_id,)).fetchone()
        if not definition:
            raise DomainError("UNKNOWN_SLI")
        if window_end.tzinfo is None or window_end.utcoffset() != timedelta(0):
            raise DomainError("UTC_REQUIRED")
        window_start = window_end - timedelta(seconds=definition["window_seconds"])
        counts = conn.execute("SELECT count(*) AS total,count(*) FILTER(WHERE is_good) AS good FROM reliability_sli_samples WHERE sli_id=%s AND observed_at>%s AND observed_at<=%s",
                              (sli_id, window_start, window_end)).fetchone()
        if not counts or counts["total"] == 0:
            raise DomainError("SLI_WINDOW_HAS_NO_SAMPLES")
        total, good = int(counts["total"]), int(counts["good"])
        compliance = good * 10000 // total
        status = "COMPLIANT" if compliance >= definition["target_basis_points"] else "BREACHED"
        actual_error = 10000 - compliance
        allowed_error = 10000 - int(definition["target_basis_points"])
        error_budget = 0 if actual_error == 0 else 10000 if allowed_error == 0 else min(
            10000, actual_error * 10000 // allowed_error
        )
        window_id = f"SLO:{sli_id}:{int(window_start.timestamp())}:{int(window_end.timestamp())}"
        if conn.execute("SELECT 1 FROM reliability_slo_windows WHERE window_id=%s", (window_id,)).fetchone():
            raise DomainError("SLI_WINDOW_ALREADY_EVALUATED")
        self.store.transition(conn, actor, capability="incident", kind="reliability_sli", aggregate_id=sli_id,
            expected_version=(self.store.state(conn, "reliability_sli", sli_id) or {"version": 0})["version"],
            state={"sli_id": sli_id, "status": status, "window_id": window_id}, event_type="SLI_WINDOW_EVALUATED",
            operation_key=operation_key, task_id=f"sli:{sli_id}", policy_version=definition["policy_version"])
        conn.execute("INSERT INTO reliability_slo_windows(window_id,sli_id,window_start,window_end,total_samples,good_samples,compliance_basis_points,target_basis_points,error_budget_consumed_basis_points,status,evaluated_by,evaluated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                     (window_id, sli_id, window_start, window_end, total, good, compliance, definition["target_basis_points"], error_budget,
                      status, actor.principal_id, utcnow()))
        if status == "BREACHED":
            recent = conn.execute(
                "SELECT count(*) AS count FROM reliability_slo_windows "
                "WHERE sli_id=%s AND status='BREACHED' AND evaluated_at > COALESCE("
                "(SELECT max(lifted_at) FROM reliability_promotion_freezes WHERE sli_id=%s), '-infinity'::timestamptz)",
                (sli_id, sli_id),
            ).fetchone()["count"]
            if recent >= definition["breach_threshold"]:
                conn.execute("INSERT INTO reliability_promotion_freezes(freeze_id,sli_id,triggering_window_id,frozen_by,frozen_at) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(sli_id) WHERE lifted_at IS NULL DO NOTHING",
                             (uid("SLOFREEZE"), sli_id, window_id, actor.principal_id, utcnow()))
        return {"window_id": window_id, "status": status, "compliance_basis_points": compliance,
                "error_budget_consumed_basis_points": error_budget, "window_start": window_start, "window_end": window_end}

    def promotion_blockers(self, conn: Any) -> tuple[str, ...]:
        rows = conn.execute("SELECT 'incident:' || incident_id AS blocker FROM incident_promotion_freezes WHERE lifted_at IS NULL UNION ALL SELECT 'sli:' || sli_id FROM reliability_promotion_freezes WHERE lifted_at IS NULL ORDER BY blocker").fetchall()
        return tuple(row["blocker"] for row in rows)

    def lift_sli_freeze(self, conn: Any, actor: Identity, sli_id: str, remediation: ArtifactProvenance) -> None:
        self._lock(conn)
        self._governance(actor)
        artifact = self._artifact(conn, remediation, schema="reliability/slo-remediation/v1")
        updated = conn.execute("UPDATE reliability_promotion_freezes SET lifted_at=%s,lift_artifact_id=%s WHERE sli_id=%s AND lifted_at IS NULL RETURNING freeze_id",
                               (utcnow(), artifact["artifact_id"], sli_id)).fetchone()
        if not updated:
            raise DomainError("NO_ACTIVE_SLI_FREEZE")

    def lift_incident_freeze(self, conn: Any, actor: Identity, incident_id: str, remediation: ArtifactProvenance,
                             operation_key: str, policy_version: str) -> None:
        self._lock(conn)
        self._governance(actor)
        row, incident = self._incident(conn, incident_id)
        if incident.status not in {IncidentStatus.RESOLVED, IncidentStatus.CLOSED}:
            raise DomainError("INCIDENT_NOT_RESOLVED")
        artifact = self._artifact(conn, remediation, schema="reliability/incident-remediation/v1")
        if not conn.execute("SELECT 1 FROM incident_promotion_freezes WHERE incident_id=%s AND lifted_at IS NULL", (incident_id,)).fetchone():
            raise DomainError("NO_ACTIVE_INCIDENT_FREEZE")
        after = incident.model_copy(update={"state_version": incident.state_version + 1})
        self._transition_incident(conn, actor, row, incident, after, "INCIDENT_PROMOTION_FREEZE_LIFTED", operation_key,
                                  policy_version, (artifact["artifact_id"],))
        updated = conn.execute("UPDATE incident_promotion_freezes SET lifted_at=%s,lift_artifact_id=%s WHERE incident_id=%s AND lifted_at IS NULL RETURNING incident_id",
                               (utcnow(), artifact["artifact_id"], incident_id)).fetchone()
        assert updated
