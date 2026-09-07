"""Authenticated deterministic executions, not caller-authored gate verdicts."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

import psycopg
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from psycopg.types.json import Jsonb
from pydantic import Field, ValidationError, model_validator

from liki.core import Contract, DomainError, canonical, content_hash, environment_fingerprint, uid
from liki.store import Credential, Store

VERIFIER_VERSION = "deterministic-gates-v5"


def verifier_code_hash() -> str:
    return environment_fingerprint()


class ResearchContract(Contract):
    objective: str = Field(min_length=1)
    hypothesis: str = Field(min_length=1)
    metric_id: str = Field(min_length=1)
    metric_version: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    lower: Decimal | None = None
    upper: Decimal | None = None
    dataset_snapshot_ids: tuple[str, ...] = Field(min_length=1)
    evaluator_version: str = Field(min_length=1)
    mode: Literal["RESEARCH", "SHADOW", "PAPER"]
    strategy_version_id: str = Field(min_length=1)
    campaign_id: str = Field(min_length=1)
    market: str = Field(min_length=1)
    horizon_seconds: int = Field(gt=0)
    constraints: tuple[str, ...] = Field(min_length=1)
    expected_artifacts: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def bounded_objective(self) -> ResearchContract:
        if self.lower is None and self.upper is None:
            raise ValueError("objective requires a predeclared bound")
        if self.lower is not None and self.upper is not None and self.lower > self.upper:
            raise ValueError("objective bounds are reversed")
        if any(not value.strip() for value in (
            self.objective, self.hypothesis, self.market, *self.constraints, *self.expected_artifacts
        )):
            raise ValueError("contract text must not be blank")
        return self


def provision_verifier(
    administrative_dsn: str, *, principal_id: str, key_id: str, public_key: bytes
) -> None:
    """Administrative enrollment only; application workloads cannot authorize keys."""
    Ed25519PublicKey.from_public_bytes(public_key)
    with psycopg.connect(administrative_dsn) as conn:
        principal = conn.execute(
            "SELECT role,enabled FROM principals WHERE principal_id=%s", (principal_id,)
        ).fetchone()
        if not principal or principal[0] not in {"evaluator", "sealed_evaluator"} or not principal[1]:
            raise DomainError("INVALID_VERIFIER_PRINCIPAL")
        conn.execute(
            "INSERT INTO verifier_keys(verifier_key_id,principal_id,verifier_version,public_key,"
            "code_hash) VALUES(%s,%s,%s,%s,%s)",
            (key_id, principal_id, VERIFIER_VERSION, public_key, verifier_code_hash()),
        )


class VerificationRunner:
    def __init__(self, store: Store, key_id: str, signing_key: Ed25519PrivateKey):
        self.store = store
        self.key_id = key_id
        self._signing_key = signing_key

    def research_contract(
        self, credential: Credential, *, snapshot_id: str, strategy_version_id: str,
        operation_key: str,
    ) -> str:
        return self.execute(credential, snapshot_id=snapshot_id,
                            strategy_version_id=strategy_version_id, gate_id=0,
                            operation_key=operation_key)

    def execute(
        self, credential: Credential, *, snapshot_id: str, strategy_version_id: str,
        gate_id: Literal[0, 1, 2, 3, 4, 5, 6, 7], operation_key: str,
    ) -> str:
        from liki.evaluation import EVIDENCE_CLASSES, EvaluationSnapshot, REQUIRED_CHECKS

        if gate_id not in range(8):
            raise DomainError("VERIFIER_GATE_NOT_SUPPORTED")

        with self.store.transaction(credential) as (conn, actor):
            actor.require("gate")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            key = conn.execute(
                "SELECT * FROM verifier_keys WHERE verifier_key_id=%s", (self.key_id,)
            ).fetchone()
            if (not key or not key["enabled"] or key["principal_id"] != actor.principal_id
                    or key["code_hash"] != verifier_code_hash()
                    or key["code_hash"] != self.store.fingerprint
                    or key["verifier_version"] != VERIFIER_VERSION
                    or bytes(key["public_key"]) != self._signing_key.public_key().public_bytes_raw()):
                raise DomainError("UNAUTHORIZED_VERIFIER")
            row = conn.execute(
                "SELECT * FROM evaluation_snapshots WHERE snapshot_id=%s", (snapshot_id,)
            ).fetchone()
            if not row or conn.execute(
                "SELECT 1 FROM snapshot_invalidations WHERE snapshot_id=%s", (snapshot_id,)
            ).fetchone():
                raise DomainError("STALE_EVALUATION_SNAPSHOT")
            snapshot = EvaluationSnapshot.model_validate(row["manifest"])
            obj = conn.execute(
                "SELECT * FROM research_objects WHERE object_id=%s", (strategy_version_id,)
            ).fetchone()
            if not obj or obj["artifact_id"] != snapshot.candidate_artifact_id:
                raise DomainError("CANDIDATE_SNAPSHOT_MISMATCH")
            if obj["created_by"] == actor.principal_id:
                raise DomainError("SELF_CERTIFICATION")
            prior = self.store.state(conn, "candidate", strategy_version_id)
            state_version = prior["version"] if prior else 0
            if prior and prior["state"].get("snapshot_id") != snapshot_id:
                raise DomainError("EVALUATION_REENTRY_REQUIRED")
            if (gate_id != (prior["state"]["gate_id"] + 1 if prior else 0)
                    or prior and prior["state"]["status"] in {
                        "FAILED", "BLOCKED", "BORDERLINE_FRONTIER", "SUSPENDED"
                    }):
                # A retry may return its immutable execution after its decision was applied.
                previous = conn.execute("SELECT metadata FROM event_log WHERE operation_key=%s",
                                        (operation_key,)).fetchone()
                if previous:
                    eid = previous["metadata"]["state_after"].get("evidence_id")
                    execution = conn.execute(
                        "SELECT v.* FROM verifier_executions v JOIN evidence e "
                        "ON e.artifact_id=v.report_artifact_id WHERE e.evidence_id=%s", (eid,)
                    ).fetchone()
                    if (execution and execution["snapshot_id"] == snapshot_id
                            and execution["strategy_version_id"] == strategy_version_id
                            and execution["gate_id"] == gate_id
                            and execution["verifier_key_id"] == self.key_id):
                        return eid
                    raise DomainError("IDEMPOTENCY_CONFLICT")
                raise DomainError("GATE_DEPENDENCY_UNSATISFIED")
            artifact = self.store.artifact(conn, actor, obj["artifact_id"])
            if artifact["content_hash"] != snapshot.candidate_hash:
                raise DomainError("CANDIDATE_HASH_MISMATCH")
            inputs = [artifact] + [
                self.store.artifact(conn, actor, aid) for aid in snapshot.dataset_snapshot_ids
            ] + [
                self.store.artifact(conn, actor, aid)
                for aid in snapshot.gate_input_artifact_ids.get(str(gate_id), ())
            ]
            derived_report = None
            if gate_id:
                if gate_id == 5:
                    from liki.backtest_gate import check_backtest
                    derived_report = check_backtest(self.store, conn, actor, row, obj)
                elif gate_id == 6:
                    from liki.economics_gate import check_economics
                    derived_report = check_economics(self.store, conn, actor, row, obj)
                elif gate_id == 7:
                    from liki.oos_gate import check_oos
                    derived_report = check_oos(self.store, conn, actor, row, obj)
                else:
                    from liki.early_gate_checks import check_gate
                    derived_report = check_gate(self.store, conn, actor, row, obj, gate_id,
                        tuple(dict.fromkeys(snapshot.dataset_snapshot_ids
                            + snapshot.gate_input_artifact_ids.get(str(gate_id), ()))))
                inputs.extend(self.store.artifact(conn, actor, aid)
                              for aid in derived_report["input_artifacts"])
                if gate_id == 4:
                    from liki.early_gate_checks import EarlyGatePlan
                    upstream = [self.store.artifact(conn, actor, aid)
                                for aid in snapshot.gate_input_artifact_ids.get("3", ())]
                    plans = [a for a in upstream if a["schema_name"] == "research/early-gate-plan-v1"]
                    current = [a for a in inputs if a["schema_name"] == "research/early-gate-plan-v1"]
                    current = list({a["artifact_id"]: a for a in current}.values())
                    try:
                        if len(plans) != 1 or len(current) != 1:
                            raise ValueError("missing or ambiguous upstream test")
                        g3 = EarlyGatePlan.model_validate(plans[0]["content"]).g3
                        g4 = EarlyGatePlan.model_validate(current[0]["content"]).g4
                        if g3 is None or g4 is None:
                            raise ValueError("wrong gate plan")
                        minimum = g3.minimum_viable_test.minimum_observations
                        derived_report["derived_metrics"]["minimum_test_observations"] = minimum
                        if g4.minimum_samples < minimum:
                            raise ValueError("cheap proxy cannot lower its declared test minimum")
                    except (ValueError, ValidationError):
                        derived_report["checks"]["sample_available"] = False
                        derived_report["unknowns"].append("G4_MINIMUM_TEST_NOT_HONORED")
                    inputs.extend(plans)
                    for artifact_row in plans:
                        for name in ("input_artifacts", "referenced_input_artifacts"):
                            derived_report[name][artifact_row["artifact_id"]] = artifact_row["content_hash"]
            binding = {
                "strategy_version_id": strategy_version_id, "snapshot_id": snapshot_id,
                "snapshot_hash": row["content_hash"], "gate_id": gate_id,
                "candidate_state_version": state_version,
                "input_artifacts": {a["artifact_id"]: a["content_hash"] for a in inputs},
            }
            input_hash = content_hash(binding)
            previous = conn.execute(
                "SELECT e.metadata FROM event_log e WHERE operation_key=%s", (operation_key,)
            ).fetchone()
            if previous:
                state = previous["metadata"]["state_after"]
                if state.get("input_hash") != input_hash or state.get("verifier_key_id") != self.key_id:
                    raise DomainError("IDEMPOTENCY_CONFLICT")
                return state["evidence_id"]
            checks = dict.fromkeys(REQUIRED_CHECKS[0], False)
            errors: list[str] = []
            try:
                contract = ResearchContract.model_validate(artifact["content"].get("research_contract"))
            except ValidationError as exc:
                errors = [".".join(map(str, err["loc"])) + ":" + err["type"] for err in exc.errors()]
            else:
                checks["measurable_objective"] = (
                    snapshot.metric_versions.get(contract.metric_id) == contract.metric_version
                )
                checks["data_evaluator_defined"] = (
                    contract.evaluator_version == snapshot.evaluator_version
                    and contract.dataset_snapshot_ids == snapshot.dataset_snapshot_ids
                    and all(
                        a["schema_name"] == "data/dataset-manifest-v1" and conn.execute(
                            "SELECT 1 FROM dataset_manifests WHERE manifest_artifact_id=%s",
                            (a["artifact_id"],),
                        ).fetchone() for a in inputs[1:1 + len(snapshot.dataset_snapshot_ids)]
                    )
                )
                checks["permitted_conduct"] = contract.mode in {"RESEARCH", "SHADOW", "PAPER"}
                checks["lineage_present"] = (
                    contract.strategy_version_id == strategy_version_id
                    and contract.campaign_id == obj["campaign_id"]
                )
            execution_id, evidence_id = uid("VERIFY"), uid("EVID")
            report = {
                "verifier_execution_id": execution_id,
                "snapshot_id": snapshot_id, "checks": checks, "metrics": [],
                "hard_invalidity": not all(checks.values()), "unknowns": [], "errors": errors,
                **(derived_report or {}),
            }
            report_id = self.store.put_artifact(
                conn, actor, report, schema_name="verified-gate-report-v1",
                classification="INTERNAL", policy_version=snapshot.gate_policy_versions[str(gate_id)],
            )
            manifest = {
                **binding, "input_hash": input_hash, "report_artifact_id": report_id,
                "report_hash": content_hash(report), "verifier_key_id": self.key_id,
                "verifier_execution_id": execution_id, "verifier_version": VERIFIER_VERSION,
                "code_hash": key["code_hash"], "environment_fingerprint": self.store.fingerprint,
            }
            signature = self._signing_key.sign(canonical(manifest).encode())
            event = self.store.transition(
                conn, actor, capability="gate", kind="verifier_execution", aggregate_id=execution_id,
                expected_version=0, state={"input_hash": input_hash, "evidence_id": evidence_id,
                                           "verifier_key_id": self.key_id},
                event_type="DETERMINISTIC_VERIFICATION_EXECUTED", operation_key=operation_key,
                task_id=obj["campaign_id"], policy_version=snapshot.gate_policy_versions[str(gate_id)],
                artifact_ids=(report_id,) + tuple(manifest["input_artifacts"]),
            )
            conn.execute(
                "INSERT INTO verifier_executions(verifier_execution_id,verifier_key_id,snapshot_id,"
                "strategy_version_id,gate_id,input_hash,report_artifact_id,report_hash,manifest,"
                "signature,event_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (execution_id, self.key_id, snapshot_id, strategy_version_id, gate_id, input_hash, report_id,
                 content_hash(report), Jsonb(manifest), signature, event["event_id"]),
            )
            conn.execute(
                "INSERT INTO evidence VALUES(%s,%s,%s,'DERIVED_VALUE',"
                "%s,now(),%s,%s,now())",
                (evidence_id, report_id, EVIDENCE_CLASSES[gate_id],
                 "VALIDATION" if gate_id == 7 else "DEVELOPMENT",
                 ["saw_g7_result"] if gate_id == 7 else [], actor.principal_id),
            )
            return evidence_id


def verify_execution(store: Store, conn, actor, artifact: dict, request, snapshot_row: dict) -> None:
    row = conn.execute(
        "SELECT v.*,k.public_key,k.principal_id,k.verifier_version,k.code_hash,k.enabled "
        "FROM verifier_executions v JOIN verifier_keys k USING(verifier_key_id) "
        "WHERE v.report_artifact_id=%s", (artifact["artifact_id"],),
    ).fetchone()
    if not row or not row["enabled"]:
        raise DomainError("UNVERIFIED_GATE_EVIDENCE")
    manifest = row["manifest"]
    expected = {
        "snapshot_id": request.snapshot_id, "strategy_version_id": request.strategy_version_id,
        "gate_id": request.gate_id, "snapshot_hash": snapshot_row["content_hash"],
        "report_artifact_id": artifact["artifact_id"], "report_hash": artifact["content_hash"],
        "verifier_key_id": row["verifier_key_id"],
        "verifier_execution_id": row["verifier_execution_id"],
        "verifier_version": row["verifier_version"], "code_hash": row["code_hash"],
        "candidate_state_version": request.expected_version,
    }
    if (any(manifest.get(key) != value for key, value in expected.items())
            or row["principal_id"] != artifact["producer_id"]
            or any(row[key] != expected[key] for key in (
                "snapshot_id", "strategy_version_id", "gate_id", "report_hash"
            ))):
        raise DomainError("VERIFIER_BINDING_MISMATCH")
    try:
        Ed25519PublicKey.from_public_bytes(bytes(row["public_key"])).verify(
            bytes(row["signature"]), canonical(manifest).encode()
        )
    except (InvalidSignature, ValueError) as exc:
        raise DomainError("INVALID_VERIFIER_SIGNATURE") from exc
    input_artifacts = manifest.get("input_artifacts")
    if not isinstance(input_artifacts, dict) or not input_artifacts:
        raise DomainError("VERIFIER_INPUT_MISSING")
    binding = {key: manifest[key] for key in (
        "strategy_version_id", "snapshot_id", "snapshot_hash", "gate_id", "input_artifacts",
        "candidate_state_version",
    )}
    if content_hash(binding) != manifest.get("input_hash") or row["input_hash"] != manifest["input_hash"]:
        raise DomainError("VERIFIER_INPUT_MISMATCH")
    for aid, digest in input_artifacts.items():
        if store.artifact(conn, actor, aid)["content_hash"] != digest:
            raise DomainError("VERIFIER_INPUT_MISMATCH")
    candidate = snapshot_row["manifest"]["candidate_artifact_id"]
    if input_artifacts.get(candidate) != snapshot_row["manifest"]["candidate_hash"]:
        raise DomainError("VERIFIER_CANDIDATE_NOT_BOUND")
    if request.gate_id == 1:
        from liki.early_gate_checks import check_gate
        obj = conn.execute("SELECT * FROM research_objects WHERE object_id=%s",
                           (request.strategy_version_id,)).fetchone()
        fresh = check_gate(store, conn, actor, snapshot_row, obj, 1,
                           tuple(aid for aid in input_artifacts if aid != candidate))
        if any(artifact["content"].get(key) != value for key, value in fresh.items()):
            raise DomainError("STALE_FAMILY_SCREEN")
