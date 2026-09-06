"""Transactional persistence adapter for the immutable governance domain.

All mutation entry points receive the authenticated `(conn, actor)` returned by
`Store.transaction`; no caller-supplied producer, reviewer, or owner identity is
accepted as authority. Every method acquires the governance advisory lock before
reading rows or delegating to `Store.transition`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from collections.abc import Iterable
from typing import Any, Literal

import psycopg
from psycopg.types.json import Jsonb

from liki.core import DomainError, content_hash, uid, utcnow
from liki.governance.domain import (
    ApprovalSnapshot,
    ArtifactProvenance,
    AutomatedCheck,
    ChangeClass,
    ChangeSet,
    Classification,
    DriftObservation,
    GovernanceProposal,
    GovernanceReview,
    Incident,
    IncidentStatus,
    LifecycleEvidence,
    ModelRecord,
    ModelValidation,
    OwnerDecision,
    OwnerDelivery,
    ProposalStatus,
    ReplayEvent,
    SynthesisRecord,
    SystemEvolutionTrial,
    _canonical_hash,
    classify_proposal,
    evaluate_promotion,
    transition_incident,
)
from liki.governance.policy import GovernancePolicy
from liki.governance.simulation import run_counterfactual_replay
from liki.outbox import Notification, Outbox
from liki.store import Identity, Store

DbConnection = psycopg.Connection[dict[str, Any]]


class GovernanceService:
    """Persistence facade; all writes are evented, CAS-protected, and auditable."""

    LOCK_KEY = 71403218

    def __init__(self, store: Store):
        self.store = store

    @classmethod
    def _lock(cls, conn: DbConnection) -> None:
        # This must be the first statement in every mutating transaction.
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (cls.LOCK_KEY,))

    def _artifact(
        self,
        conn: DbConnection,
        provenance: ArtifactProvenance,
        *,
        schema_name: str | None = None,
        allowed_roles: frozenset[str] | None = None,
        expected_content: dict[str, object] | None = None,
    ) -> dict:
        row = conn.execute(
            "SELECT a.*, p.role, p.code_fingerprint AS producer_code_fingerprint "
            "FROM artifacts a JOIN principals p ON p.principal_id=a.producer_id WHERE a.artifact_id=%s",
            (provenance.artifact_id,),
        ).fetchone()
        if not row:
            raise DomainError("UNKNOWN_ARTIFACT")
        if content_hash(row["content"]) != row["content_hash"]:
            raise DomainError("ARTIFACT_CORRUPTED")
        if (
            row["content_hash"] != provenance.content_hash
            or row["producer_id"] != provenance.authenticated_principal
            or row["environment_fingerprint"] != provenance.environment_fingerprint
            or row["producer_code_fingerprint"] != provenance.code_fingerprint
        ):
            raise DomainError("FORGED_PROVENANCE")
        if schema_name and row["schema_name"] != schema_name:
            raise DomainError("ARTIFACT_SCHEMA_MISMATCH")
        if allowed_roles and row["role"] not in allowed_roles:
            raise DomainError("ARTIFACT_PRODUCER_ROLE_MISMATCH")
        if expected_content and any(row["content"].get(key) != value for key, value in expected_content.items()):
            raise DomainError("ARTIFACT_CONTENT_MISMATCH")
        return row

    def _artifacts(self, conn: DbConnection, values: tuple[ArtifactProvenance, ...]) -> tuple[str, ...]:
        return tuple(self._artifact(conn, item)["artifact_id"] for item in values)

    def _check(self, conn: DbConnection, check: AutomatedCheck) -> str:
        row = self._artifact(
            conn,
            check.result_artifact,
            schema_name="governance/automated-check-result/v1",
            allowed_roles=frozenset({"evaluator", "sealed_evaluator"}),
            expected_content={"check_id": check.check_id, "check_kind": check.check_kind, "result": check.result},
        )
        executed_at = row["content"].get("executed_at_utc")
        if not isinstance(executed_at, str):
            raise DomainError("AUTOMATED_CHECK_TIMESTAMP_MISSING")
        try:
            recorded_at = datetime.fromisoformat(executed_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise DomainError("AUTOMATED_CHECK_TIMESTAMP_INVALID") from error
        if recorded_at.tzinfo is None or recorded_at.utcoffset() != timedelta(0):
            raise DomainError("AUTOMATED_CHECK_TIMESTAMP_INVALID")
        if recorded_at != check.executed_at:
            raise DomainError("FORGED_AUTOMATED_CHECK_TIMESTAMP")
        return row["artifact_id"]

    def _lifecycle(self, conn: DbConnection, lifecycle: LifecycleEvidence) -> tuple[str, ...]:
        return tuple(
            self._check(conn, check)
            for phase in (lifecycle.replay, lifecycle.tests, lifecycle.shadow, lifecycle.canary)
            for check in phase
        )

    @staticmethod
    def _lifecycle_checks(lifecycle: LifecycleEvidence) -> tuple[tuple[str, AutomatedCheck], ...]:
        checks = tuple(
            (phase, check)
            for phase, values in (
                ("replay", lifecycle.replay),
                ("tests", lifecycle.tests),
                ("shadow", lifecycle.shadow),
                ("canary", lifecycle.canary),
            )
            for check in values
        )
        if len({(phase, check.check_id) for phase, check in checks}) != len(checks):
            raise DomainError("DUPLICATE_LIFECYCLE_CHECK")
        return checks

    @staticmethod
    def _latest_lifecycle_event(conn: DbConnection, proposal_id: str, lifecycle: LifecycleEvidence) -> dict:
        event = conn.execute(
            "SELECT event_id,metadata FROM event_log WHERE aggregate_type='governance_proposal' "
            "AND aggregate_id=%s AND event_type='GOVERNANCE_LIFECYCLE_EVIDENCE' "
            "ORDER BY sequence DESC LIMIT 1",
            (proposal_id,),
        ).fetchone()
        if not event or event["metadata"].get("lifecycle_snapshot_hash") != lifecycle.snapshot_hash():
            raise DomainError("LIFECYCLE_EVIDENCE_NOT_DURABLE")
        return event

    @staticmethod
    def _requires_fresh_revalidation(conn: DbConnection, proposal_id: str, lifecycle: LifecycleEvidence) -> bool:
        delivery = conn.execute(
            "SELECT owner_delivery FROM governance_proposals WHERE proposal_id=%s", (proposal_id,)
        ).fetchone()
        if not delivery or not delivery["owner_delivery"]:
            return False
        delivered_at = OwnerDelivery.model_validate(delivery["owner_delivery"], strict=False).delivered_at
        failure = conn.execute(
            "SELECT max(executed_at) AS failed_at FROM governance_lifecycle_outcomes "
            "WHERE proposal_id=%s AND result='FAIL' AND executed_at >= %s",
            (proposal_id, delivered_at),
        ).fetchone()
        return failure is not None and failure["failed_at"] is not None and any(
            check.executed_at <= failure["failed_at"] for check in lifecycle.checks()
        )

    @staticmethod
    def _proposal(row: dict) -> GovernanceProposal:
        proposal = GovernanceProposal.model_validate(row["package"], strict=False)
        return proposal.model_copy(update={"status": ProposalStatus(row["status"])})

    @staticmethod
    def _snapshot(row: dict) -> ApprovalSnapshot:
        return ApprovalSnapshot.model_validate(row, strict=False)

    @staticmethod
    def _require_effective_policy(conn: DbConnection, policy: GovernancePolicy) -> None:
        row = conn.execute(
            "SELECT content_hash FROM policy_versions WHERE policy_id=%s AND policy_version=%s AND status='EFFECTIVE'",
            (policy.policy_id, policy.policy_version),
        ).fetchone()
        if not row or row["content_hash"] != policy.content_hash:
            raise DomainError("POLICY_NOT_EFFECTIVE")

    def register_policy(
        self,
        conn: DbConnection,
        actor: Identity,
        policy: GovernancePolicy,
        policy_artifact: ArtifactProvenance,
        operation_key: str,
        *,
        effective: bool = False,
    ) -> dict:
        self._lock(conn)
        actor.require("policy")
        artifact = self._artifact(
            conn,
            policy_artifact,
            schema_name="governance/policy-version/v1",
            allowed_roles=frozenset({"governance"}),
            expected_content={
                "policy_id": policy.policy_id,
                "policy_version": policy.policy_version,
                "content_hash": policy.content_hash,
            },
        )
        status = "EFFECTIVE" if effective else "DRAFT"
        event = self.store.transition(
            conn, actor, capability="policy", kind="policy_version", aggregate_id=f"{policy.policy_id}:{policy.policy_version}",
            expected_version=0, state={"status": status, "policy_id": policy.policy_id, "policy_version": policy.policy_version},
            event_type="POLICY_REGISTERED", operation_key=operation_key, task_id=f"governance:{policy.policy_id}",
            policy_version=policy.policy_version, artifact_ids=(artifact["artifact_id"],),
        )
        if effective and conn.execute("SELECT 1 FROM policy_versions WHERE policy_id=%s AND status='EFFECTIVE'", (policy.policy_id,)).fetchone():
            raise DomainError("POLICY_ACTIVATION_REQUIRES_GOVERNANCE")
        if effective:
            conn.execute("UPDATE policy_versions SET status='RETIRED', retired_at=now() WHERE policy_id=%s AND status='EFFECTIVE'", (policy.policy_id,))
        conn.execute(
            "INSERT INTO policy_versions(policy_id,policy_version,content_hash,status,policy_artifact_id,created_by,effective_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,CASE WHEN %s THEN now() ELSE NULL END) ON CONFLICT(policy_id,policy_version) DO NOTHING",
            (policy.policy_id, policy.policy_version, policy.content_hash, status, artifact["artifact_id"], actor.principal_id, effective),
        )
        return event

    def propose(
        self, conn: DbConnection, actor: Identity, proposal: GovernanceProposal, operation_key: str, policy_version: str
    ) -> dict:
        self._lock(conn)
        actor.require("proposal")
        if proposal.authored_by != actor.principal_id:
            raise DomainError("FORGED_PROPOSAL_AUTHOR")
        artifact_ids = self._artifacts(conn, tuple(item.artifact for item in (*proposal.evidence, *proposal.counterevidence)))
        event = self.store.transition(
            conn, actor, capability="proposal", kind="governance_proposal", aggregate_id=proposal.proposal_id,
            expected_version=0, state={"status": proposal.status.value, "proposal_version": proposal.proposal_version},
            event_type="GOVERNANCE_PROPOSED", operation_key=operation_key, task_id=f"governance:{proposal.proposal_id}",
            policy_version=policy_version, artifact_ids=artifact_ids,
        )
        empty = LifecycleEvidence().model_dump(mode="json")
        conn.execute(
            "INSERT INTO governance_proposals(proposal_id,proposal_version,authored_by,package,lifecycle,status,approval_snapshot_hash,created_at) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(proposal_id) DO NOTHING",
            (proposal.proposal_id, proposal.proposal_version, actor.principal_id, Jsonb(proposal.model_dump(mode="json")),
             Jsonb(empty), proposal.status.value, proposal.approval_snapshot.snapshot_hash, proposal.created_at),
        )
        return event

    def classify(
        self, conn: DbConnection, actor: Identity, proposal_id: str, policy: GovernancePolicy,
        expected_version: int, operation_key: str,
    ) -> Classification:
        self._lock(conn)
        actor.require("policy")
        self._require_effective_policy(conn, policy)
        row = conn.execute("SELECT * FROM governance_proposals WHERE proposal_id=%s", (proposal_id,)).fetchone()
        if not row:
            raise DomainError("UNKNOWN_PROPOSAL")
        proposal = self._proposal(row)
        classification = classify_proposal(proposal, policy, actor.principal_id, utcnow())
        self.store.transition(
            conn, actor, capability="policy", kind="governance_proposal", aggregate_id=proposal_id,
            expected_version=expected_version, state={"status": ProposalStatus.CLASSIFIED.value, "proposal_version": proposal.proposal_version},
            event_type="GOVERNANCE_CLASSIFIED", operation_key=operation_key, task_id=f"governance:{proposal_id}",
            policy_version=policy.policy_version, metadata={"classification": classification.model_dump(mode="json")},
        )
        conn.execute("UPDATE governance_proposals SET classification=%s,status=%s,updated_at=now() WHERE proposal_id=%s",
                     (Jsonb(classification.model_dump(mode="json")), ProposalStatus.CLASSIFIED.value, proposal_id))
        return classification

    def record_review(
        self, conn: DbConnection, actor: Identity, review: GovernanceReview,
        evidence_manifest: ArtifactProvenance, expected_version: int, operation_key: str, policy_version: str,
    ) -> dict:
        self._lock(conn)
        actor.require("proposal")
        if review.reviewer_principal != actor.principal_id:
            raise DomainError("FORGED_REVIEWER")
        proposal_row = conn.execute("SELECT * FROM governance_proposals WHERE proposal_id=%s", (review.proposal_id,)).fetchone()
        if not proposal_row:
            raise DomainError("UNKNOWN_PROPOSAL")
        proposal = self._proposal(proposal_row)
        if proposal.authored_by == actor.principal_id:
            raise DomainError("SELF_CERTIFICATION")
        manifest = self._artifact(conn, evidence_manifest, schema_name="governance/evidence-manifest/v1")
        if evidence_manifest.content_hash != review.evidence_manifest_hash:
            raise DomainError("FORGED_EVIDENCE_MANIFEST")
        artifact_ids = (manifest["artifact_id"], *self._artifacts(conn, review.inspected_evidence))
        event = self.store.transition(
            conn, actor, capability="proposal", kind="governance_proposal", aggregate_id=review.proposal_id,
            expected_version=expected_version, state={"status": ProposalStatus.REVIEWING.value, "proposal_version": proposal.proposal_version},
            event_type="GOVERNANCE_REVIEW_RECORDED", operation_key=operation_key, task_id=f"governance:{review.proposal_id}",
            policy_version=policy_version, artifact_ids=artifact_ids,
        )
        conn.execute(
            "INSERT INTO governance_reviews(council_review_id,proposal_id,review,evidence_manifest_artifact_id,created_at) "
            "VALUES(%s,%s,%s,%s,%s) ON CONFLICT(council_review_id) DO NOTHING",
            (review.council_review_id, review.proposal_id, Jsonb(review.model_dump(mode="json")), manifest["artifact_id"], review.created_at),
        )
        conn.execute("UPDATE governance_proposals SET status=%s,updated_at=now() WHERE proposal_id=%s", (ProposalStatus.REVIEWING.value, review.proposal_id))
        return event

    def record_lifecycle(
        self, conn: DbConnection, actor: Identity, proposal_id: str, lifecycle: LifecycleEvidence,
        expected_version: int, operation_key: str, policy_version: str,
    ) -> dict:
        self._lock(conn)
        actor.require("policy")
        row = conn.execute("SELECT * FROM governance_proposals WHERE proposal_id=%s", (proposal_id,)).fetchone()
        if not row:
            raise DomainError("UNKNOWN_PROPOSAL")
        checks = self._lifecycle_checks(lifecycle)
        artifact_ids = self._lifecycle(conn, lifecycle)
        if not lifecycle.has_failure() and self._requires_fresh_revalidation(conn, proposal_id, lifecycle):
            raise DomainError("REVALIDATION_REQUIRES_FRESH_EVIDENCE")
        status = (
            ProposalStatus.FROZEN.value if lifecycle.has_failure() else ProposalStatus.CANARY.value if lifecycle.canary
            else ProposalStatus.SHADOW.value if lifecycle.shadow else ProposalStatus.TESTED.value
            if lifecycle.tests else ProposalStatus.REPLAYED.value
        )
        event = self.store.transition(
            conn, actor, capability="policy", kind="governance_proposal", aggregate_id=proposal_id,
            expected_version=expected_version, state={"status": status},
            event_type="GOVERNANCE_LIFECYCLE_EVIDENCE", operation_key=operation_key, task_id=f"governance:{proposal_id}",
            policy_version=policy_version, artifact_ids=artifact_ids,
            metadata={"lifecycle": lifecycle.model_dump(mode="json"), "lifecycle_snapshot_hash": lifecycle.snapshot_hash()},
        )
        for phase, check in checks:
            conn.execute(
                "INSERT INTO governance_lifecycle_outcomes("
                "lifecycle_event_id,proposal_id,lifecycle_snapshot_hash,phase,check_id,check_kind,result,"
                "result_artifact_id,executed_at,recorded_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    event["event_id"], proposal_id, lifecycle.snapshot_hash(), phase, check.check_id,
                    check.check_kind, check.result, check.result_artifact.artifact_id, check.executed_at,
                    actor.principal_id,
                ),
            )
        conn.execute("UPDATE governance_proposals SET lifecycle=%s,status=%s,updated_at=now() WHERE proposal_id=%s",
                     (Jsonb(lifecycle.model_dump(mode="json")), status, proposal_id))
        return event

    def record_synthesis(
        self, conn: DbConnection, actor: Identity, synthesis: SynthesisRecord,
        expected_version: int, operation_key: str, policy_version: str,
    ) -> dict:
        self._lock(conn)
        actor.require("proposal")
        row = conn.execute("SELECT * FROM governance_proposals WHERE proposal_id=%s", (synthesis.proposal_id,)).fetchone()
        if not row:
            raise DomainError("UNKNOWN_PROPOSAL")
        if synthesis.synthesized_by != actor.principal_id:
            raise DomainError("FORGED_SYNTHESIS_AUTHOR")
        artifact = self._artifact(conn, synthesis.synthesis_artifact)
        event = self.store.transition(
            conn, actor, capability="proposal", kind="governance_proposal", aggregate_id=synthesis.proposal_id,
            expected_version=expected_version, state={"status": ProposalStatus.CANARY.value},
            event_type="GOVERNANCE_SYNTHESIZED", operation_key=operation_key, task_id=f"governance:{synthesis.proposal_id}",
            policy_version=policy_version, artifact_ids=(artifact["artifact_id"],),
        )
        conn.execute("UPDATE governance_proposals SET synthesis=%s,status=%s,updated_at=now() WHERE proposal_id=%s",
                     (Jsonb(synthesis.model_dump(mode="json")), ProposalStatus.CANARY.value, synthesis.proposal_id))
        return event

    def queue_owner_notification(
        self, conn: DbConnection, actor: Identity, proposal_id: str, authoritative_channel: str,
        notification_package: ArtifactProvenance, expected_version: int, operation_key: str, policy_version: str,
    ) -> dict:
        """Atomically queue owner delivery after a complete, verified evidence package."""
        self._lock(conn)
        actor.require("proposal")
        if actor.role != "governance":
            raise DomainError("OWNER_DELIVERY_SERVICE_ONLY")
        row = conn.execute("SELECT * FROM governance_proposals WHERE proposal_id=%s", (proposal_id,)).fetchone()
        if not row:
            raise DomainError("UNKNOWN_PROPOSAL")
        lifecycle = LifecycleEvidence.model_validate(row["lifecycle"], strict=False)
        self._lifecycle(conn, lifecycle)
        if not lifecycle.tests or lifecycle.has_failure():
            raise DomainError("AUTOMATED_CHECKS_NOT_PASSING")
        lifecycle_snapshot_hash = lifecycle.snapshot_hash()
        lifecycle_event = self._latest_lifecycle_event(conn, proposal_id, lifecycle)
        package = self._artifact(
            conn,
            notification_package,
            schema_name="governance/owner-notification-package/v1",
            allowed_roles=frozenset({"governance"}),
            expected_content={
                "proposal_id": proposal_id,
                "channel": authoritative_channel,
                "lifecycle_snapshot_hash": lifecycle_snapshot_hash,
            },
        )
        title = package["content"].get("title")
        message = package["content"].get("message")
        if not isinstance(title, str) or not title.strip() or not isinstance(message, str) or not message.strip():
            raise DomainError("OWNER_NOTIFICATION_PACKAGE_INCOMPLETE")
        proposal = self._proposal(row)
        notification_id = Outbox(self.store).notify(
            conn,
            actor,
            Notification(
                deduplication_key=f"governance-owner-decision:{proposal_id}:{proposal.proposal_version}:{lifecycle_event['event_id']}",
                urgency="CRITICAL" if proposal.declared_class is ChangeClass.RED else "HIGH",
                classification="INTERNAL",
                recipient_ref=authoritative_channel,
                title=title.strip(),
                message=message.strip(),
                required_action="APPROVE or VETO",
                object_id=proposal_id,
            ),
        )
        completed_at = utcnow()
        proposal = proposal.model_copy(update={"complete_evidence_at": completed_at})
        event = self.store.transition(
            conn, actor, capability="proposal", kind="governance_proposal", aggregate_id=proposal_id,
            expected_version=expected_version, state={"status": row["status"]}, event_type="OWNER_NOTIFICATION_QUEUED",
            operation_key=operation_key, task_id=f"governance:{proposal_id}", policy_version=policy_version,
            artifact_ids=(package["artifact_id"],),
            metadata={
                "channel": authoritative_channel,
                "notification_id": notification_id,
                "lifecycle_snapshot_hash": lifecycle_snapshot_hash,
                "lifecycle_event_id": lifecycle_event["event_id"],
            },
        )
        conn.execute("UPDATE governance_proposals SET package=%s,updated_at=now() WHERE proposal_id=%s",
                     (Jsonb(proposal.model_dump(mode="json")), proposal_id))
        return event

    def record_owner_delivery(
        self, conn: DbConnection, actor: Identity, proposal_id: str, authoritative_channel: str,
        expected_version: int, operation_key: str, policy_version: str,
    ) -> OwnerDelivery:
        self._lock(conn)
        actor.require("proposal")
        if actor.role != "governance":
            raise DomainError("OWNER_DELIVERY_SERVICE_ONLY")
        row = conn.execute("SELECT * FROM governance_proposals WHERE proposal_id=%s", (proposal_id,)).fetchone()
        if not row:
            raise DomainError("UNKNOWN_PROPOSAL")
        lifecycle = LifecycleEvidence.model_validate(row["lifecycle"], strict=False)
        self._lifecycle(conn, lifecycle)
        if not lifecycle.tests or lifecycle.has_failure():
            raise DomainError("AUTOMATED_CHECKS_NOT_PASSING")
        lifecycle_snapshot_hash = lifecycle.snapshot_hash()
        lifecycle_event = self._latest_lifecycle_event(conn, proposal_id, lifecycle)
        queued = conn.execute(
            "SELECT metadata->>'notification_id' AS notification_id FROM event_log WHERE aggregate_type='governance_proposal' AND aggregate_id=%s "
            "AND event_type='OWNER_NOTIFICATION_QUEUED' AND metadata->>'channel'=%s AND metadata->>'lifecycle_snapshot_hash'=%s "
            "AND metadata->>'lifecycle_event_id'=%s "
            "ORDER BY occurred_at_utc DESC LIMIT 1",
            (proposal_id, authoritative_channel, lifecycle_snapshot_hash, lifecycle_event["event_id"]),
        ).fetchone()
        if not queued or not queued["notification_id"]:
            raise DomainError("OWNER_NOTIFICATION_NOT_QUEUED")
        receipt = conn.execute(
            "SELECT d.provider_message_id,d.delivered_at FROM notification_deliveries d "
            "JOIN notification_records n ON n.notification_id=d.notification_id "
            "JOIN transactional_outbox o ON o.outbox_id=d.outbox_id "
            "WHERE d.notification_id=%s AND n.recipient_ref=%s AND n.object_id=%s "
            "AND o.topic='telegram.notification' AND o.status='DELIVERED'",
            (queued["notification_id"], authoritative_channel, proposal_id),
        ).fetchone()
        if not receipt:
            raise DomainError("OWNER_DELIVERY_UNCONFIRMED")
        delivery_time = receipt["delivered_at"]
        if delivery_time.tzinfo is None or delivery_time.utcoffset() != timedelta(0):
            raise DomainError("OWNER_DELIVERY_TIMESTAMP_INVALID")
        proposal = self._proposal(row)
        if proposal.complete_evidence_at is None or delivery_time < proposal.complete_evidence_at:
            raise DomainError("OWNER_DELIVERY_BEFORE_COMPLETE_EVIDENCE")
        delivered = OwnerDelivery(
            authoritative_channel=authoritative_channel,
            notification_id=queued["notification_id"],
            provider_message_id=receipt["provider_message_id"],
            delivered_at=delivery_time,
            lifecycle_snapshot_hash=lifecycle_snapshot_hash,
        )
        proposal = proposal.model_copy(update={
            "owner_notification_delivered_at": delivered.delivered_at,
            "promotion_eligible_at": delivered.delivered_at + timedelta(hours=24),
        })
        self.store.transition(
            conn, actor, capability="proposal", kind="governance_proposal", aggregate_id=proposal_id,
            expected_version=expected_version, state={"status": row["status"]}, event_type="OWNER_NOTIFICATION_DELIVERED",
            operation_key=operation_key, task_id=f"governance:{proposal_id}", policy_version=policy_version,
            metadata={
                "notification_id": delivered.notification_id,
                "provider_message_id": delivered.provider_message_id,
                "lifecycle_snapshot_hash": delivered.lifecycle_snapshot_hash,
            },
        )
        conn.execute("UPDATE governance_proposals SET package=%s,owner_delivery=%s,updated_at=now() WHERE proposal_id=%s",
                     (Jsonb(proposal.model_dump(mode="json")), Jsonb(delivered.model_dump(mode="json")), proposal_id))
        return delivered

    def decide(
        self,
        conn: DbConnection,
        actor: Identity,
        proposal_id: str,
        decision: Literal["APPROVE", "VETO"],
        reason: str,
        expected_version: int,
        operation_key: str,
        policy_version: str,
    ) -> OwnerDecision:
        """Record an authenticated owner's decision with a server-created attestation.

        This narrow capability deliberately avoids granting the owner generic
        artifact-write permission. Replays return the original immutable decision.
        """
        self._lock(conn)
        actor.require("owner_decision")
        if actor.role != "owner":
            raise DomainError("OWNER_AUTH_REQUIRED")
        if decision not in {"APPROVE", "VETO"}:
            raise DomainError("INVALID_OWNER_DECISION")
        if not proposal_id or not operation_key or not policy_version or not reason.strip():
            raise DomainError("INVALID_OWNER_DECISION_REQUEST")
        existing = conn.execute(
            "SELECT event_type,principal_id,aggregate_id,metadata FROM event_log WHERE operation_key=%s",
            (operation_key,),
        ).fetchone()
        if existing:
            expected_event = f"OWNER_{decision}"
            metadata = existing["metadata"]
            if (
                existing["event_type"] != expected_event
                or existing["principal_id"] != actor.principal_id
                or existing["aggregate_id"] != proposal_id
                or metadata.get("owner_decision_reason") != reason.strip()
                or metadata.get("owner_expected_version") != expected_version
                or metadata.get("owner_policy_version") != policy_version
            ):
                raise DomainError("IDEMPOTENCY_CONFLICT")
            persisted = conn.execute(
                "SELECT owner_decision FROM governance_proposals WHERE proposal_id=%s", (proposal_id,)
            ).fetchone()
            if not persisted or not persisted["owner_decision"]:
                raise DomainError("OWNER_DECISION_REPLAY_INCONSISTENT")
            return OwnerDecision.model_validate(persisted["owner_decision"], strict=False)
        row = conn.execute("SELECT * FROM governance_proposals WHERE proposal_id=%s", (proposal_id,)).fetchone()
        if not row:
            raise DomainError("UNKNOWN_PROPOSAL")
        if row["owner_decision"]:
            raise DomainError("OWNER_DECISION_ALREADY_RECORDED")
        proposal = self._proposal(row)
        decided_at = utcnow()
        attestation_content = {
            "attestation_kind": "governance-owner-decision/v1",
            "attestation_service": "governance-service",
            "server_environment_fingerprint": self.store.fingerprint,
            "proposal_id": proposal_id,
            "proposal_version": proposal.proposal_version,
            "owner_principal": actor.principal_id,
            "decision": decision,
            "reason": reason.strip(),
            "expected_version": expected_version,
            "operation_key": operation_key,
            "policy_version": policy_version,
            "decided_at_utc": decided_at.isoformat(),
        }
        attestation_id = uid("ART")
        attestation_hash = content_hash(attestation_content)
        conn.execute(
            "INSERT INTO artifacts(artifact_id,content_hash,schema_name,classification,producer_id,"
            "environment_fingerprint,policy_version,content) VALUES(%s,%s,%s,'INTERNAL',%s,%s,%s,%s)",
            (
                attestation_id,
                attestation_hash,
                "governance/server-owner-decision-attestation/v1",
                actor.principal_id,
                self.store.fingerprint,
                policy_version,
                Jsonb(attestation_content),
            ),
        )
        attestation = ArtifactProvenance(
            artifact_id=attestation_id,
            content_hash=attestation_hash,
            authenticated_principal=actor.principal_id,
            environment_fingerprint=self.store.fingerprint,
            code_fingerprint=actor.code_fingerprint,
            classification="INTERNAL",
        )
        result = OwnerDecision(
            proposal_id=proposal_id,
            owner_principal=actor.principal_id,
            approved=decision == "APPROVE",
            vetoed=decision == "VETO",
            decision_artifact=attestation,
            decided_at=decided_at,
        )
        status = ProposalStatus.VETOED.value if result.vetoed else row["status"]
        self.store.transition(
            conn, actor, capability="owner_decision", kind="governance_proposal", aggregate_id=proposal_id,
            expected_version=expected_version, state={"status": status}, event_type=f"OWNER_{decision}", operation_key=operation_key,
            task_id=f"governance:{proposal_id}", policy_version=policy_version, artifact_ids=(attestation_id,),
            metadata={
                "owner_decision_reason": reason.strip(),
                "owner_expected_version": expected_version,
                "owner_policy_version": policy_version,
                "proposal_version": proposal.proposal_version,
            },
        )
        conn.execute("UPDATE governance_proposals SET owner_decision=%s,status=%s,updated_at=now() WHERE proposal_id=%s",
                     (Jsonb(result.model_dump(mode="json")), status, proposal_id))
        return result

    def _current_snapshot(self, conn: DbConnection, proposal: GovernanceProposal) -> ApprovalSnapshot:
        dependencies = []
        for dependency in proposal.approval_snapshot.dependencies:
            row = conn.execute(
                "SELECT policy_version,content_hash FROM policy_versions WHERE policy_id=%s AND status='EFFECTIVE'", (dependency.scope,)
            ).fetchone()
            if not row:
                raise DomainError("POLICY_DEPENDENCY_NOT_REGISTERED")
            dependencies.append({"scope": dependency.scope, "version": row["policy_version"], "content_hash": row["content_hash"]})
        affected = tuple((*proposal.affected_modules, *proposal.affected_paths))
        incidents = conn.execute(
            "SELECT incident_id FROM incidents WHERE status NOT IN ('RESOLVED','CLOSED') "
            "AND (incident->'affected_modules') ?| %s", (list(affected),)
        ).fetchall() if affected else []
        body = {
            "dependencies": sorted(dependencies, key=lambda item: (item["scope"], item["version"])),
            "known_incident_ids": sorted(row["incident_id"] for row in incidents),
            "evidence_hashes": sorted(proposal.approval_snapshot.evidence_hashes),
        }
        return ApprovalSnapshot.model_validate({**body, "snapshot_hash": _canonical_hash(body)}, strict=False)

    def evaluate(
        self, conn: DbConnection, actor: Identity, proposal_id: str, expected_version: int,
        operation_key: str, policy_version: str, change_set_id: str | None = None,
    ) -> ProposalStatus:
        self._lock(conn)
        actor.require("policy")
        row = conn.execute("SELECT * FROM governance_proposals WHERE proposal_id=%s", (proposal_id,)).fetchone()
        if not row or not row["classification"]:
            raise DomainError("PROPOSAL_NOT_CLASSIFIED")
        proposal = self._proposal(row)
        classification = Classification.model_validate(row["classification"], strict=False)
        reviews = tuple(GovernanceReview.model_validate(item["review"], strict=False) for item in conn.execute("SELECT review FROM governance_reviews WHERE proposal_id=%s ORDER BY created_at", (proposal_id,)))
        lifecycle = LifecycleEvidence.model_validate(row["lifecycle"], strict=False)
        synthesis = SynthesisRecord.model_validate(row["synthesis"], strict=False) if row["synthesis"] else None
        delivery = OwnerDelivery.model_validate(row["owner_delivery"], strict=False) if row["owner_delivery"] else None
        owner_decision = OwnerDecision.model_validate(row["owner_decision"], strict=False) if row["owner_decision"] else None
        incidents = tuple(Incident.model_validate(item["incident"], strict=False) for item in conn.execute("SELECT incident FROM incidents WHERE status NOT IN ('RESOLVED','CLOSED')"))
        change_set = None
        if change_set_id:
            change_set_row = conn.execute("SELECT change_set FROM governance_change_sets WHERE change_set_id=%s", (change_set_id,)).fetchone()
            if not change_set_row:
                raise DomainError("UNKNOWN_CHANGE_SET")
            change_set = ChangeSet.model_validate(change_set_row["change_set"], strict=False)
            self._artifacts(conn, change_set.interaction_test_artifacts)
            for check in change_set.interaction_tests:
                self._check(conn, check)
        result = evaluate_promotion(proposal, classification, reviews, lifecycle, self._current_snapshot(conn, proposal), utcnow(), synthesis=synthesis, owner_delivery=delivery, owner_decision=owner_decision, relevant_incidents=incidents, change_set=change_set)
        artifacts = self._lifecycle(conn, lifecycle)
        self.store.transition(
            conn, actor, capability="policy", kind="governance_proposal", aggregate_id=proposal_id,
            expected_version=expected_version, state={"status": result.value}, event_type="GOVERNANCE_REVALIDATED",
            operation_key=operation_key, task_id=f"governance:{proposal_id}", policy_version=policy_version, artifact_ids=artifacts,
            metadata={"fresh_snapshot_hash": self._current_snapshot(conn, proposal).snapshot_hash},
        )
        conn.execute("UPDATE governance_proposals SET status=%s,updated_at=now() WHERE proposal_id=%s", (result.value, proposal_id))
        return result

    def record_change_set(
        self, conn: DbConnection, actor: Identity, change_set: ChangeSet, expected_version: int,
        operation_key: str, policy_version: str,
    ) -> dict:
        self._lock(conn)
        actor.require("policy")
        artifact_ids = self._artifacts(conn, change_set.interaction_test_artifacts)
        check_artifact_ids = tuple(self._check(conn, check) for check in change_set.interaction_tests)
        event = self.store.transition(
            conn, actor, capability="policy", kind="governance_change_set", aggregate_id=change_set.change_set_id,
            expected_version=expected_version, state={"state": change_set.state}, event_type="GOVERNANCE_CHANGE_SET_RECORDED",
            operation_key=operation_key, task_id=f"governance-change-set:{change_set.change_set_id}", policy_version=policy_version,
            artifact_ids=(*artifact_ids, *check_artifact_ids),
        )
        conn.execute(
            "INSERT INTO governance_change_sets(change_set_id,change_set,created_by,state_version,created_at,revalidated_at,promoted_at) "
            "VALUES(%s,%s,%s,1,%s,%s,%s) ON CONFLICT(change_set_id) DO NOTHING",
            (change_set.change_set_id, Jsonb(change_set.model_dump(mode="json")), actor.principal_id, change_set.created_at,
             change_set.revalidated_at, change_set.promoted_at),
        )
        return event

    def activate_policy(
        self, conn: DbConnection, actor: Identity, policy_id: str, policy_version: str, proposal_id: str,
        expected_version: int, operation_key: str,
    ) -> dict:
        """Activate a reviewed policy using the previously effective policy as authority."""
        self._lock(conn)
        actor.require("policy")
        current = conn.execute("SELECT * FROM policy_versions WHERE policy_id=%s AND status='EFFECTIVE'", (policy_id,)).fetchone()
        target = conn.execute("SELECT * FROM policy_versions WHERE policy_id=%s AND policy_version=%s AND status='DRAFT'", (policy_id, policy_version)).fetchone()
        proposal = conn.execute("SELECT status,classification FROM governance_proposals WHERE proposal_id=%s", (proposal_id,)).fetchone()
        if not current or not target or not proposal or proposal["status"] != ProposalStatus.PROMOTED.value:
            raise DomainError("POLICY_DEPLOYMENT_NOT_AUTHORIZED")
        classification = Classification.model_validate(proposal["classification"], strict=False)
        if classification.policy_version != current["policy_version"]:
            raise DomainError("POLICY_SELF_APPROVAL_FORBIDDEN")
        event = self.store.transition(
            conn, actor, capability="policy", kind="policy_version", aggregate_id=f"{policy_id}:{policy_version}",
            expected_version=expected_version, state={"status": "EFFECTIVE", "policy_id": policy_id, "policy_version": policy_version},
            event_type="POLICY_ACTIVATED", operation_key=operation_key, task_id=f"governance:{proposal_id}",
            policy_version=current["policy_version"], artifact_ids=(target["policy_artifact_id"],),
        )
        conn.execute("UPDATE policy_versions SET status='RETIRED',retired_at=now() WHERE policy_id=%s AND status='EFFECTIVE'", (policy_id,))
        conn.execute("UPDATE policy_versions SET status='EFFECTIVE',effective_at=now(),governance_proposal_id=%s WHERE policy_id=%s AND policy_version=%s", (proposal_id, policy_id, policy_version))
        return event

    def schedule_monthly(
        self, conn: DbConnection, actor: Identity, schedule_id: str, due_at: datetime,
        expected_version: int, operation_key: str, policy_version: str,
    ) -> dict:
        """Durably schedule the mandatory monthly review in UTC; recovery is state-based."""
        self._lock(conn)
        actor.require("policy")
        if due_at.tzinfo is None or due_at.utcoffset() != timedelta(0):
            raise DomainError("UTC_REQUIRED")
        event = self.store.transition(
            conn, actor, capability="policy", kind="governance_schedule", aggregate_id=schedule_id,
            expected_version=expected_version, state={"status": "SCHEDULED", "next_due_at": due_at.isoformat()},
            event_type="GOVERNANCE_MONTHLY_SCHEDULED", operation_key=operation_key, task_id=f"governance-schedule:{schedule_id}",
            policy_version=policy_version,
        )
        conn.execute("INSERT INTO governance_schedules(schedule_id,cadence,next_due_at,state_version,status) VALUES(%s,'MONTHLY',%s,1,'SCHEDULED') ON CONFLICT(schedule_id) DO UPDATE SET next_due_at=EXCLUDED.next_due_at,state_version=governance_schedules.state_version+1,status='SCHEDULED',updated_at=now()", (schedule_id, due_at))
        return event

    def schedule_emergency(
        self, conn: DbConnection, actor: Identity, schedule_id: str, due_at: datetime,
        expected_version: int, operation_key: str, policy_version: str,
    ) -> dict:
        """Persist an event-triggered emergency Council meeting without waiting for cadence."""
        self._lock(conn)
        actor.require("incident")
        if due_at.tzinfo is None or due_at.utcoffset() != timedelta(0):
            raise DomainError("UTC_REQUIRED")
        event = self.store.transition(
            conn, actor, capability="incident", kind="governance_schedule", aggregate_id=schedule_id,
            expected_version=expected_version, state={"status": "DUE", "next_due_at": due_at.isoformat()},
            event_type="GOVERNANCE_EMERGENCY_SCHEDULED", operation_key=operation_key, task_id=f"governance-schedule:{schedule_id}",
            policy_version=policy_version,
        )
        conn.execute("INSERT INTO governance_schedules(schedule_id,cadence,next_due_at,state_version,status) VALUES(%s,'EMERGENCY',%s,1,'DUE')", (schedule_id, due_at))
        return event

    def rollback_policy(
        self, conn: DbConnection, actor: Identity, policy_id: str, rollback_to_version: str,
        expected_version: int, operation_key: str,
    ) -> dict:
        """Risk-reducing policy rollback, authorized and recorded under the current policy."""
        self._lock(conn)
        actor.require("policy")
        current = conn.execute("SELECT * FROM policy_versions WHERE policy_id=%s AND status='EFFECTIVE'", (policy_id,)).fetchone()
        target = conn.execute("SELECT * FROM policy_versions WHERE policy_id=%s AND policy_version=%s AND status='RETIRED'", (policy_id, rollback_to_version)).fetchone()
        if not current or not target:
            raise DomainError("ROLLBACK_TARGET_UNAVAILABLE")
        event = self.store.transition(
            conn, actor, capability="policy", kind="policy_version", aggregate_id=f"{policy_id}:{rollback_to_version}",
            expected_version=expected_version, state={"status": "EFFECTIVE", "policy_id": policy_id, "policy_version": rollback_to_version},
            event_type="POLICY_ROLLED_BACK", operation_key=operation_key, task_id=f"governance:{policy_id}",
            policy_version=current["policy_version"], artifact_ids=(target["policy_artifact_id"],),
        )
        conn.execute("UPDATE policy_versions SET status='RETIRED',retired_at=now(),rollback_to_version=%s WHERE policy_id=%s AND status='EFFECTIVE'", (rollback_to_version, policy_id))
        conn.execute("UPDATE policy_versions SET status='EFFECTIVE',effective_at=now() WHERE policy_id=%s AND policy_version=%s", (policy_id, rollback_to_version))
        return event

    def declare_incident(self, conn: DbConnection, actor: Identity, incident: Incident, operation_key: str, policy_version: str) -> dict:
        self._lock(conn)
        actor.require("incident")
        if incident.opened_by != actor.principal_id:
            raise DomainError("FORGED_INCIDENT_AUTHOR")
        artifacts = self._artifacts(conn, incident.evidence)
        event = self.store.transition(conn, actor, capability="incident", kind="incident", aggregate_id=incident.incident_id,
            expected_version=0, state={"status": incident.status.value}, event_type="INCIDENT_DECLARED", operation_key=operation_key,
            task_id=f"incident:{incident.incident_id}", policy_version=policy_version, artifact_ids=artifacts,
            metadata={"severity": incident.severity.value, "owner_notification_required": incident.severity.value in {"SEV0", "SEV1"}},
            topic="governance.incident_notification.requested")
        conn.execute("INSERT INTO incidents(incident_id,incident,severity,status,state_version,opened_by,opened_at) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                     (incident.incident_id, Jsonb(incident.model_dump(mode="json")), incident.severity.value, incident.status.value, incident.state_version, actor.principal_id, incident.opened_at))
        conn.execute("INSERT INTO incident_events(incident_event_id,incident_id,event_id,transition) VALUES(%s,%s,%s,%s)",
                     (uid("INC_EVT"), incident.incident_id, event["event_id"], Jsonb({"to": incident.status.value})))
        return event

    def advance_incident(self, conn: DbConnection, actor: Identity, incident_id: str, to_status: IncidentStatus,
        expected_version: int, operation_key: str, policy_version: str, *, containment_action: str | None = None,
        reconciliation_evidence: Iterable[ArtifactProvenance] = (), root_cause_artifact: ArtifactProvenance | None = None,
        impact_assessment_artifact: ArtifactProvenance | None = None, postmortem_artifact: ArtifactProvenance | None = None,
    ) -> Incident:
        self._lock(conn)
        actor.require("incident")
        row = conn.execute("SELECT * FROM incidents WHERE incident_id=%s", (incident_id,)).fetchone()
        if not row:
            raise DomainError("UNKNOWN_INCIDENT")
        current = Incident.model_validate(row["incident"], strict=False)
        next_incident = transition_incident(
            current, to_status, utcnow(), containment_action=containment_action,
            reconciliation_evidence=reconciliation_evidence, root_cause_artifact=root_cause_artifact,
            impact_assessment_artifact=impact_assessment_artifact, postmortem_artifact=postmortem_artifact,
        )
        artifacts = self._artifacts(conn, next_incident.evidence)
        artifacts += self._artifacts(conn, next_incident.reconciliation_evidence)
        artifacts += self._artifacts(conn, tuple(item for item in (
            next_incident.root_cause_artifact, next_incident.impact_assessment_artifact, next_incident.postmortem_artifact
        ) if item is not None))
        event = self.store.transition(conn, actor, capability="incident", kind="incident", aggregate_id=incident_id,
            expected_version=expected_version, state={"status": to_status.value}, event_type=f"INCIDENT_{to_status.value}",
            operation_key=operation_key, task_id=f"incident:{incident_id}", policy_version=policy_version, artifact_ids=artifacts)
        conn.execute("UPDATE incidents SET incident=%s,status=%s,state_version=%s,updated_at=now() WHERE incident_id=%s",
                     (Jsonb(next_incident.model_dump(mode="json")), to_status.value, next_incident.state_version, incident_id))
        conn.execute("INSERT INTO incident_events(incident_event_id,incident_id,event_id,transition) VALUES(%s,%s,%s,%s)",
                     (uid("INC_EVT"), incident_id, event["event_id"], Jsonb({"from": current.status.value, "to": to_status.value})))
        return next_incident

    def persist_replay(self, conn: DbConnection, actor: Identity, proposal_id: str | None, events: tuple[ReplayEvent, ...],
        input_artifact: ArtifactProvenance, operation_key: str, policy_version: str,
    ) -> dict:
        self._lock(conn)
        actor.require("policy")
        source = self._artifact(conn, input_artifact, schema_name="governance/historical-replay-input/v1")
        for event in events:
            self._artifact(conn, event.source_artifact)
        result = run_counterfactual_replay(events)
        existing = conn.execute(
            "SELECT result_artifact_id,result FROM governance_replays WHERE proposal_id IS NOT DISTINCT FROM %s AND input_hash=%s",
            (proposal_id, result.input_hash),
        ).fetchone()
        if existing:
            return {"result_artifact_id": existing["result_artifact_id"], "result": type(result).model_validate(existing["result"], strict=False)}
        result_id = self.store.put_artifact(conn, actor, result.model_dump(mode="json"), schema_name="governance/replay-result/v1", classification="INTERNAL", policy_version=policy_version)
        self.store.transition(
            conn, actor, capability="policy", kind="governance_replay", aggregate_id=result.input_hash, expected_version=0,
            state={"proposal_id": proposal_id, "input_hash": result.input_hash}, event_type="GOVERNANCE_REPLAY_PERSISTED",
            operation_key=operation_key, task_id=f"governance-replay:{result.input_hash}", policy_version=policy_version,
            artifact_ids=(source["artifact_id"], result_id),
        )
        conn.execute("INSERT INTO governance_replays(replay_id,proposal_id,input_artifact_id,result_artifact_id,input_hash,result,produced_by) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                     (uid("REPLAY"), proposal_id, source["artifact_id"], result_id, result.input_hash, Jsonb(result.model_dump(mode="json")), actor.principal_id))
        return {"result_artifact_id": result_id, "result": result}

    def register_model(self, conn: DbConnection, actor: Identity, record: ModelRecord, record_artifact: ArtifactProvenance,
        operation_key: str, policy_version: str,
    ) -> dict:
        self._lock(conn)
        actor.require("policy")
        if actor.principal_id not in record.developer_principals:
            raise DomainError("FORGED_MODEL_DEVELOPER")
        artifact = self._artifact(conn, record_artifact, schema_name="governance/model-record/v1", expected_content={"model_id": record.model_id, "version": record.version})
        card_artifact_ids: tuple[str, ...] = ()
        if record.model_card:
            card = self._artifact(conn, record.model_card.card_artifact)
            card_artifact_ids = (card["artifact_id"],)
        event = self.store.transition(conn, actor, capability="policy", kind="model", aggregate_id=record.model_id, expected_version=0,
            state={"status": record.status.value, "version": record.version}, event_type="MODEL_REGISTERED", operation_key=operation_key,
            task_id=f"model:{record.model_id}", policy_version=policy_version, artifact_ids=(artifact["artifact_id"], *card_artifact_ids))
        conn.execute("INSERT INTO model_inventory(model_id,version,status,materiality,record,record_artifact_id,created_by,created_at,updated_at,validation_due_at,retired_at,replacement_model_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                     (record.model_id, record.version, record.status.value, record.materiality.value, Jsonb(record.model_dump(mode="json")), artifact["artifact_id"], actor.principal_id, record.created_at, record.updated_at, record.validation_due_at, record.retired_at, record.replacement_model_id))
        if record.model_card:
            conn.execute("INSERT INTO model_cards(model_id,card_artifact_id,card) VALUES(%s,%s,%s)", (record.model_id, card["artifact_id"], Jsonb(record.model_card.model_dump(mode="json"))))
        return event

    def record_model_validation(self, conn: DbConnection, actor: Identity, model_id: str, validation: ModelValidation,
        validation_artifact: ArtifactProvenance,
    ) -> None:
        self._lock(conn)
        actor.require("policy")
        if validation.validator_principal != actor.principal_id:
            raise DomainError("FORGED_VALIDATOR")
        model = conn.execute("SELECT record FROM model_inventory WHERE model_id=%s", (model_id,)).fetchone()
        if not model:
            raise DomainError("UNKNOWN_MODEL")
        record = ModelRecord.model_validate(model["record"], strict=False)
        if actor.principal_id in record.developer_principals:
            raise DomainError("SELF_VALIDATION")
        artifact = self._artifact(conn, validation_artifact, schema_name="governance/model-validation/v1")
        self._artifacts(conn, validation.validation_evidence)
        check_artifact_ids = tuple(self._check(conn, check) for check in (validation.conceptual_soundness, validation.implementation_correctness, validation.sensitivity))
        self.store.transition(
            conn, actor, capability="policy", kind="model_validation", aggregate_id=validation.validation_id,
            expected_version=0, state={"model_id": model_id, "validator_principal": actor.principal_id},
            event_type="MODEL_VALIDATION_RECORDED", operation_key=f"model-validation:{validation.validation_id}",
            task_id=f"model:{model_id}", policy_version="model-risk", artifact_ids=(artifact["artifact_id"], *check_artifact_ids),
        )
        conn.execute("INSERT INTO model_validations(validation_id,model_id,validation,validation_artifact_id,validator_principal,created_at) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(validation_id) DO NOTHING",
                     (validation.validation_id, model_id, Jsonb(validation.model_dump(mode="json")), artifact["artifact_id"], actor.principal_id, validation.completed_at))

    def record_drift(self, conn: DbConnection, actor: Identity, model_id: str, observation: DriftObservation) -> None:
        self._lock(conn)
        actor.require("policy")
        measurement = self._artifact(conn, observation.measurement_artifact, schema_name="governance/drift-measurement/v1")
        row = conn.execute("SELECT * FROM model_inventory WHERE model_id=%s", (model_id,)).fetchone()
        if not row:
            raise DomainError("UNKNOWN_MODEL")
        self.store.transition(
            conn, actor, capability="policy", kind="model_drift", aggregate_id=observation.observation_id,
            expected_version=0, state={"model_id": model_id, "breached": observation.breached},
            event_type="MODEL_DRIFT_RECORDED", operation_key=f"model-drift:{observation.observation_id}",
            task_id=f"model:{model_id}", policy_version="model-risk", artifact_ids=(measurement["artifact_id"],),
        )
        conn.execute("INSERT INTO model_drift_observations(observation_id,model_id,observation,measurement_artifact_id,observed_at) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(observation_id) DO NOTHING",
                     (observation.observation_id, model_id, Jsonb(observation.model_dump(mode="json")), measurement["artifact_id"], observation.observed_at))
        if observation.breached:
            current = self.store.state(conn, "model", model_id)
            if current is None:
                raise DomainError("MODEL_AGGREGATE_MISSING")
            self.store.transition(
                conn, actor, capability="policy", kind="model", aggregate_id=model_id, expected_version=current["version"],
                state={"status": "WATCH", "version": row["version"]}, event_type="MODEL_WATCHED_FOR_DRIFT",
                operation_key=f"model-watch:{model_id}:{observation.observation_id}", task_id=f"model:{model_id}",
                policy_version="model-risk", artifact_ids=(measurement["artifact_id"],),
            )
            conn.execute("UPDATE model_inventory SET status='WATCH',updated_at=now() WHERE model_id=%s AND status NOT IN ('RETIRED','SUSPENDED')", (model_id,))

    def record_system_trial(self, conn: DbConnection, actor: Identity, trial: SystemEvolutionTrial) -> None:
        self._lock(conn)
        actor.require("policy")
        for exposure in (*trial.development_benchmarks, *trial.sealed_benchmark_exposures):
            self._artifact(conn, exposure.evidence)
        artifact_ids = self._artifacts(conn, trial.shadow_outcomes) + self._artifacts(conn, trial.canary_outcomes)
        exposure_artifact_ids = tuple(exposure.evidence.artifact_id for exposure in (*trial.development_benchmarks, *trial.sealed_benchmark_exposures))
        self.store.transition(
            conn, actor, capability="policy", kind="system_evolution_trial", aggregate_id=trial.trial_id,
            expected_version=0, state={"trial_id": trial.trial_id}, event_type="SYSTEM_EVOLUTION_TRIAL_RECORDED",
            operation_key=f"system-evolution-trial:{trial.trial_id}", task_id=f"system-evolution:{trial.trial_id}",
            policy_version="model-risk", artifact_ids=(*artifact_ids, *exposure_artifact_ids),
        )
        conn.execute("INSERT INTO system_evolution_trials(trial_id,trial,produced_by) VALUES(%s,%s,%s) ON CONFLICT(trial_id) DO NOTHING", (trial.trial_id, Jsonb(trial.model_dump(mode="json")), actor.principal_id))
        for exposure in (*trial.development_benchmarks, *trial.sealed_benchmark_exposures):
            conn.execute("INSERT INTO system_benchmark_exposures(trial_id,benchmark_id,evidence_artifact_id,purpose,consumed_at) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                         (trial.trial_id, exposure.benchmark_id, exposure.evidence.artifact_id, exposure.purpose, exposure.consumed_at))
