"""Authenticated persistence for the model-risk lifecycle."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from psycopg.types.json import Jsonb
from pydantic import Field, model_validator

from liki.core import Contract, DomainError, content_hash, utcnow
from liki.governance import (
    ArtifactProvenance,
    AutomatedCheck,
    DriftObservation,
    ModelRecord,
    ModelStatus,
    ModelValidation,
    assess_model_admission,
    find_common_dependencies,
)
from liki.store import Identity, Store


class EffectiveChallenge(Contract):
    challenge_id: str = Field(min_length=1)
    validation_id: str = Field(min_length=1)
    challenger_model_id: str | None = Field(default=None, min_length=1)
    challenge_artifact: ArtifactProvenance
    validator_principal: str = Field(min_length=1)
    checks: tuple[AutomatedCheck, ...] = Field(min_length=7)
    completed_at: datetime

    @model_validator(mode="after")
    def covers_required_challenge(self) -> EffectiveChallenge:
        required = {
            "conceptual_soundness", "data_appropriateness", "implementation_correctness",
            "benchmark_challenger", "sensitivity", "outcome_analysis", "limitations_misuse",
        }
        if not required.issubset({check.check_kind for check in self.checks}):
            raise ValueError("effective challenge is missing a required validation dimension")
        if any(check.result != "PASS" for check in self.checks):
            raise ValueError("effective challenge requires passing checks")
        return self


class ModelUseException(Contract):
    exception_id: str = Field(min_length=1)
    limitation: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    compensating_control: str = Field(min_length=1)
    expires_at: datetime
    approval_artifact: ArtifactProvenance


EvidenceRole = Literal["DEVELOPMENT", "VALIDATION", "MONITORING", "DEVELOPMENT_USED"]


class ModelRiskService:
    """Complements inventory registration with challenge, evidence, and retirement controls."""

    LOCK_KEY = 71403218

    def __init__(self, store: Store):
        self.store = store

    @classmethod
    def _lock(cls, conn: Any) -> None:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (cls.LOCK_KEY,))

    @staticmethod
    def _require_governance(actor: Identity) -> None:
        if actor.role != "governance":
            raise DomainError("FORBIDDEN", "Model-risk lifecycle requires governance authority")

    @staticmethod
    def _artifact(conn: Any, value: ArtifactProvenance, *, schema: str | None = None,
                  allowed_roles: frozenset[str] | None = None) -> dict[str, Any]:
        row = conn.execute(
            "SELECT a.*,p.role,p.code_fingerprint AS producer_code_fingerprint FROM artifacts a "
            "JOIN principals p ON p.principal_id=a.producer_id WHERE a.artifact_id=%s", (value.artifact_id,)
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
        if allowed_roles and row["role"] not in allowed_roles:
            raise DomainError("ARTIFACT_PRODUCER_ROLE_MISMATCH")
        return row

    def _check(self, conn: Any, check: AutomatedCheck) -> str:
        row = self._artifact(conn, check.result_artifact,
                             schema="governance/automated-check-result/v1",
                             allowed_roles=frozenset({"evaluator", "sealed_evaluator"}))
        content = row["content"]
        if (content.get("check_id"), content.get("check_kind"), content.get("result")) != (
            check.check_id, check.check_kind, check.result
        ):
            raise DomainError("ARTIFACT_CONTENT_MISMATCH")
        executed_at = content.get("executed_at_utc")
        if not isinstance(executed_at, str):
            raise DomainError("AUTOMATED_CHECK_TIMESTAMP_MISSING")
        try:
            recorded_at = datetime.fromisoformat(executed_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise DomainError("AUTOMATED_CHECK_TIMESTAMP_INVALID") from error
        if recorded_at.tzinfo is None or recorded_at.utcoffset() != timedelta(0) or recorded_at != check.executed_at:
            raise DomainError("FORGED_AUTOMATED_CHECK_TIMESTAMP")
        return row["artifact_id"]

    @staticmethod
    def _record(conn: Any, model_id: str) -> tuple[dict[str, Any], ModelRecord]:
        row = conn.execute("SELECT * FROM model_inventory WHERE model_id=%s FOR UPDATE", (model_id,)).fetchone()
        if not row:
            raise DomainError("UNKNOWN_MODEL")
        return row, ModelRecord.model_validate(row["record"], strict=False)

    @staticmethod
    def _append_unique(values: tuple[ArtifactProvenance, ...], value: ArtifactProvenance) -> tuple[ArtifactProvenance, ...]:
        return values if any(item.content_hash == value.content_hash for item in values) else (*values, value)

    @staticmethod
    def _without(values: tuple[ArtifactProvenance, ...], value: ArtifactProvenance) -> tuple[ArtifactProvenance, ...]:
        return tuple(item for item in values if item.content_hash != value.content_hash)

    @staticmethod
    def _updated_record(record: ModelRecord, evidence: ArtifactProvenance, role: EvidenceRole) -> ModelRecord:
        updates: dict[str, object] = {"updated_at": utcnow()}
        if role == "DEVELOPMENT":
            updates["development_evidence"] = ModelRiskService._append_unique(record.development_evidence, evidence)
        elif role == "VALIDATION":
            updates["validation_evidence"] = ModelRiskService._append_unique(record.validation_evidence, evidence)
        elif role == "MONITORING":
            updates["monitoring_evidence"] = ModelRiskService._append_unique(record.monitoring_evidence, evidence)
        else:
            updates["validation_evidence"] = ModelRiskService._without(record.validation_evidence, evidence)
            updates["recalibration_consumed_evidence"] = ModelRiskService._append_unique(
                record.recalibration_consumed_evidence, evidence
            )
        return record.model_copy(update=updates)

    def link_evidence(self, conn: Any, actor: Identity, model_id: str, evidence: ArtifactProvenance,
                      role: EvidenceRole, operation_key: str, policy_version: str) -> ModelRecord:
        self._lock(conn)
        self._require_governance(actor)
        if role not in {"DEVELOPMENT", "VALIDATION", "MONITORING", "DEVELOPMENT_USED"}:
            raise DomainError("INVALID_MODEL_EVIDENCE_ROLE")
        _, record = self._record(conn, model_id)
        artifact = self._artifact(conn, evidence)
        existing = conn.execute(
            "SELECT evidence_role FROM model_evidence_links WHERE model_id=%s AND artifact_id=%s", (model_id, artifact["artifact_id"])
        ).fetchall()
        existing_roles = {item["evidence_role"] for item in existing}
        if role == "VALIDATION" and existing_roles & {"DEVELOPMENT", "DEVELOPMENT_USED"}:
            raise DomainError("CONTAMINATED_VALIDATION_EVIDENCE")
        if role == "DEVELOPMENT_USED" and "VALIDATION" not in existing_roles:
            raise DomainError("ONLY_VALIDATION_EVIDENCE_CAN_BE_RECALIBRATION_CONSUMED")
        updated = self._updated_record(record, evidence, role)
        current = self.store.state(conn, "model", model_id)
        if not current:
            raise DomainError("MODEL_AGGREGATE_MISSING")
        self.store.transition(conn, actor, capability="policy", kind="model", aggregate_id=model_id,
            expected_version=current["version"], state={"status": updated.status.value, "version": updated.version},
            event_type="MODEL_EVIDENCE_LINKED", operation_key=operation_key, task_id=f"model:{model_id}",
            policy_version=policy_version, artifact_ids=(artifact["artifact_id"],), metadata={"role": role})
        conn.execute("INSERT INTO model_evidence_links(evidence_link_id,model_id,artifact_id,evidence_role,prior_evidence_role,linked_by,linked_at) "
                     "VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(model_id,artifact_id,evidence_role) DO NOTHING",
                     (operation_key, model_id, artifact["artifact_id"], role, "VALIDATION" if role == "DEVELOPMENT_USED" else None,
                      actor.principal_id, utcnow()))
        conn.execute("UPDATE model_inventory SET record=%s,updated_at=%s WHERE model_id=%s",
                     (Jsonb(updated.model_dump(mode="json")), updated.updated_at, model_id))
        return updated

    def record_effective_challenge(self, conn: Any, actor: Identity, model_id: str, challenge: EffectiveChallenge,
                                   operation_key: str, policy_version: str) -> None:
        self._lock(conn)
        self._require_governance(actor)
        _, record = self._record(conn, model_id)
        validation = conn.execute("SELECT * FROM model_validations WHERE validation_id=%s AND model_id=%s", (challenge.validation_id, model_id)).fetchone()
        if not validation:
            raise DomainError("UNKNOWN_MODEL_VALIDATION")
        if challenge.validator_principal != validation["validator_principal"] or challenge.validator_principal in record.developer_principals:
            raise DomainError("INEFFECTIVE_CHALLENGE")
        if conn.execute("SELECT 1 FROM model_effective_challenges WHERE model_id=%s AND validation_id=%s", (model_id, challenge.validation_id)).fetchone():
            raise DomainError("EFFECTIVE_CHALLENGE_ALREADY_RECORDED")
        artifact = self._artifact(conn, challenge.challenge_artifact, schema="model-risk/effective-challenge/v1",
                                  allowed_roles=frozenset({"evaluator", "sealed_evaluator"}))
        if any(artifact["content"].get(key) != value for key, value in {
            "challenge_id": challenge.challenge_id,
            "model_id": model_id,
            "validation_id": challenge.validation_id,
            "validator_principal": challenge.validator_principal,
        }.items()):
            raise DomainError("ARTIFACT_CONTENT_MISMATCH")
        check_ids = tuple(self._check(conn, check) for check in challenge.checks)
        current = self.store.state(conn, "model", model_id)
        if not current:
            raise DomainError("MODEL_AGGREGATE_MISSING")
        self.store.transition(conn, actor, capability="policy", kind="model", aggregate_id=model_id,
            expected_version=current["version"], state={"status": record.status.value, "version": record.version},
            event_type="MODEL_EFFECTIVE_CHALLENGE_RECORDED", operation_key=operation_key, task_id=f"model:{model_id}",
            policy_version=policy_version, artifact_ids=(artifact["artifact_id"], *check_ids), metadata={"validation_id": challenge.validation_id})
        conn.execute("INSERT INTO model_effective_challenges(challenge_id,model_id,validation_id,challenger_model_id,challenge_artifact_id,validator_principal,created_at) "
                     "VALUES(%s,%s,%s,%s,%s,%s,%s)", (challenge.challenge_id, model_id, challenge.validation_id,
                     challenge.challenger_model_id, artifact["artifact_id"], challenge.validator_principal, challenge.completed_at))

    def approve(self, conn: Any, actor: Identity, model_id: str, validation_id: str, expected_version: int,
                operation_key: str, policy_version: str) -> ModelRecord:
        self._lock(conn)
        self._require_governance(actor)
        row, record = self._record(conn, model_id)
        validation_row = conn.execute("SELECT validation FROM model_validations WHERE validation_id=%s AND model_id=%s", (validation_id, model_id)).fetchone()
        challenge = conn.execute("SELECT 1 FROM model_effective_challenges WHERE model_id=%s AND validation_id=%s", (model_id, validation_id)).fetchone()
        if not validation_row or not challenge:
            raise DomainError("MODEL_VALIDATION_OR_EFFECTIVE_CHALLENGE_MISSING")
        validation = ModelValidation.model_validate(validation_row["validation"], strict=False)
        decision = assess_model_admission(record, validation)
        if not decision.admissible:
            raise DomainError("MODEL_ADMISSION_REJECTED", "; ".join(decision.reasons))
        current = self.store.state(conn, "model", model_id)
        if not current:
            raise DomainError("MODEL_AGGREGATE_MISSING")
        approved = record.model_copy(update={"status": ModelStatus.APPROVED, "validation_status": "VALIDATED",
                                             "validation_evidence": validation.validation_evidence, "updated_at": utcnow()})
        self.store.transition(conn, actor, capability="policy", kind="model", aggregate_id=model_id,
            expected_version=expected_version, state={"status": "APPROVED", "version": row["version"]},
            event_type="MODEL_APPROVED", operation_key=operation_key, task_id=f"model:{model_id}", policy_version=policy_version,
            artifact_ids=tuple(item.artifact_id for item in validation.validation_evidence), metadata={"validation_id": validation_id})
        conn.execute("UPDATE model_inventory SET status='APPROVED',record=%s,updated_at=%s WHERE model_id=%s",
                     (Jsonb(approved.model_dump(mode="json")), approved.updated_at, model_id))
        for evidence in validation.validation_evidence:
            conn.execute(
                "INSERT INTO model_evidence_links(evidence_link_id,model_id,artifact_id,evidence_role,linked_by,linked_at) "
                "VALUES(%s,%s,%s,'VALIDATION',%s,%s) ON CONFLICT(model_id,artifact_id,evidence_role) DO NOTHING",
                (f"model-validation:{validation_id}:{evidence.artifact_id}", model_id, evidence.artifact_id,
                 actor.principal_id, approved.updated_at),
            )
        return approved

    def record_drift(self, conn: Any, actor: Identity, model_id: str, observation: DriftObservation,
                     expected_version: int, operation_key: str, policy_version: str) -> None:
        self._lock(conn)
        self._require_governance(actor)
        row, record = self._record(conn, model_id)
        artifact = self._artifact(conn, observation.measurement_artifact, schema="governance/drift-measurement/v1")
        current = self.store.state(conn, "model", model_id)
        if not current:
            raise DomainError("MODEL_AGGREGATE_MISSING")
        status = ModelStatus.WATCH if observation.breached and record.status not in {ModelStatus.RETIRED, ModelStatus.SUSPENDED} else record.status
        updated = record.model_copy(update={"status": status, "updated_at": utcnow()})
        self.store.transition(conn, actor, capability="policy", kind="model", aggregate_id=model_id,
            expected_version=expected_version, state={"status": status.value, "version": row["version"]},
            event_type="MODEL_DRIFT_BREACH" if observation.breached else "MODEL_DRIFT_RECORDED", operation_key=operation_key,
            task_id=f"model:{model_id}", policy_version=policy_version, artifact_ids=(artifact["artifact_id"],),
            metadata={"drift_kind": observation.drift_kind, "breached": observation.breached})
        conn.execute("INSERT INTO model_drift_observations(observation_id,model_id,observation,measurement_artifact_id,observed_at) VALUES(%s,%s,%s,%s,%s)",
                     (observation.observation_id, model_id, Jsonb(observation.model_dump(mode="json")), artifact["artifact_id"], observation.observed_at))
        conn.execute("UPDATE model_inventory SET status=%s,record=%s,updated_at=%s WHERE model_id=%s",
                     (status.value, Jsonb(updated.model_dump(mode="json")), updated.updated_at, model_id))

    def retire(self, conn: Any, actor: Identity, model_id: str, retirement_artifact: ArtifactProvenance,
               expected_version: int, operation_key: str, policy_version: str, replacement_model_id: str | None = None) -> ModelRecord:
        self._lock(conn)
        self._require_governance(actor)
        row, record = self._record(conn, model_id)
        if record.status is ModelStatus.RETIRED:
            raise DomainError("MODEL_ALREADY_RETIRED")
        if replacement_model_id:
            replacement = conn.execute("SELECT status FROM model_inventory WHERE model_id=%s", (replacement_model_id,)).fetchone()
            if not replacement or replacement["status"] != "APPROVED":
                raise DomainError("INVALID_MODEL_REPLACEMENT")
        artifact = self._artifact(conn, retirement_artifact, schema="model-risk/retirement/v1")
        retired_at = utcnow()
        retired = record.model_copy(update={"status": ModelStatus.RETIRED, "retired_at": retired_at,
                                            "replacement_model_id": replacement_model_id, "updated_at": retired_at})
        self.store.transition(conn, actor, capability="policy", kind="model", aggregate_id=model_id, expected_version=expected_version,
            state={"status": "RETIRED", "version": row["version"]}, event_type="MODEL_RETIRED", operation_key=operation_key,
            task_id=f"model:{model_id}", policy_version=policy_version, artifact_ids=(artifact["artifact_id"],))
        conn.execute("UPDATE model_inventory SET status='RETIRED',record=%s,updated_at=%s,retired_at=%s,replacement_model_id=%s WHERE model_id=%s",
                     (Jsonb(retired.model_dump(mode="json")), retired_at, retired_at, replacement_model_id, model_id))
        conn.execute("INSERT INTO model_retirements(model_id,retirement_artifact_id,retired_by,replacement_model_id,retired_at) VALUES(%s,%s,%s,%s,%s)",
                     (model_id, artifact["artifact_id"], actor.principal_id, replacement_model_id, retired_at))
        return retired

    def grant_exception(self, conn: Any, actor: Identity, model_id: str, exception: ModelUseException,
                        operation_key: str, policy_version: str) -> None:
        self._lock(conn)
        self._require_governance(actor)
        row, record = self._record(conn, model_id)
        if record.status is ModelStatus.RETIRED or exception.expires_at <= utcnow():
            raise DomainError("INVALID_MODEL_EXCEPTION")
        artifact = self._artifact(conn, exception.approval_artifact, schema="model-risk/use-exception/v1")
        current = self.store.state(conn, "model", model_id)
        if not current:
            raise DomainError("MODEL_AGGREGATE_MISSING")
        self.store.transition(conn, actor, capability="policy", kind="model", aggregate_id=model_id,
            expected_version=current["version"], state={"status": record.status.value, "version": row["version"]},
            event_type="MODEL_USE_EXCEPTION_GRANTED", operation_key=operation_key, task_id=f"model:{model_id}",
            policy_version=policy_version, artifact_ids=(artifact["artifact_id"],), metadata={"exception_id": exception.exception_id})
        conn.execute("INSERT INTO model_use_exceptions(exception_id,model_id,limitation,reason,compensating_control,expires_at,approved_by,approval_artifact_id,created_at) "
                     "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)", (exception.exception_id, model_id, exception.limitation,
                     exception.reason, exception.compensating_control, exception.expires_at, actor.principal_id,
                     artifact["artifact_id"], utcnow()))

    def aggregate_dependencies(self, conn: Any) -> dict[str, tuple[str, ...]]:
        rows = conn.execute("SELECT record FROM model_inventory WHERE status <> 'RETIRED' ORDER BY model_id").fetchall()
        return find_common_dependencies(ModelRecord.model_validate(row["record"], strict=False) for row in rows)
