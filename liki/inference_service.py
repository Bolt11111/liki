"""Production Postgres persistence and construction boundary for inference."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from psycopg.types.json import Jsonb

from liki.core import DomainError, content_hash, utcnow
from liki.inference import (
    AttemptStatus,
    InferenceBroker,
    InferenceRequest,
    ProviderRoute,
    RetryPolicy,
    adapter_registry,
    load_provider_routes,
)
from liki.inference.adapters import ProviderTransportError
from liki.inference.backend import ConcurrentModification, IdempotencyConflict, InferenceBackend
from liki.inference.types import ContextManifest, InferenceAttempt, InferenceResult
from liki.store import Credential, Identity, Store

DbRow = dict[str, Any]


class PostgresInferenceBackend(InferenceBackend):
    """Authenticated, evented Postgres source of truth for broker attempts."""

    POLICY_VERSION = "inference-broker-v1"

    def __init__(self, store: Store, credential: Credential, routes: Mapping[str, ProviderRoute]):
        self._store = store
        self._credential = credential
        self._routes = dict(routes)

    def _transaction(self):
        return self._store.transaction(self._credential)

    @staticmethod
    def _request_hash(request: InferenceRequest) -> str:
        return content_hash(request.model_dump(mode="json", exclude={"inference_request_id"}))

    @staticmethod
    def _state(row: DbRow) -> dict[str, Any]:
        return {
            "inference_request_id": row["inference_request_id"],
            "semantic_task_id": row["semantic_task_id"],
            "status": row["status"],
            "context_manifest_hash": row["context_manifest_hash"],
            "completed_attempt_id": row["completed_attempt_id"],
            "final_artifact_id": row["final_artifact_id"],
            "failure_reason": row["failure_reason"],
            "reserved_cost_usd": str(row["reserved_cost_usd"]),
            "accrued_cost_usd": str(row["accrued_cost_usd"]),
        }

    def _transition(
        self,
        conn: Any,
        actor: Identity,
        row: DbRow,
        *,
        state: dict[str, Any],
        event_type: str,
        operation_key: str,
        metadata: dict[str, object] | None = None,
        artifact_ids: tuple[str, ...] = (),
    ) -> None:
        aggregate = self._store.state(conn, "inference_request", row["inference_request_id"])
        self._store.transition(
            conn,
            actor,
            capability="inference",
            kind="inference_request",
            aggregate_id=row["inference_request_id"],
            expected_version=aggregate["version"] if aggregate else 0,
            state=state,
            event_type=event_type,
            operation_key=operation_key,
            task_id=row["semantic_task_id"],
            policy_version=self.POLICY_VERSION,
            metadata=metadata,
            artifact_ids=artifact_ids,
        )

    def create_or_get(self, request: InferenceRequest, manifest: ContextManifest) -> InferenceRequest:
        with self._transaction() as (conn, actor):
            actor.require("inference")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            current = conn.execute(
                "SELECT * FROM inference_requests WHERE idempotency_key=%s FOR UPDATE", (request.idempotency_key,)
            ).fetchone()
            if current:
                if (
                    current["request_hash"] != self._request_hash(request)
                    or current["context_manifest_hash"] != manifest.manifest_hash
                ):
                    raise IdempotencyConflict("idempotency key is bound to different request content or context")
                return InferenceRequest.model_validate(current["request_json"])
            manifest_artifact_id = self._store.put_artifact(
                conn,
                actor,
                manifest.model_dump(mode="json"),
                schema_name="inference/context-manifest-v1",
                classification="INTERNAL",
                policy_version=self.POLICY_VERSION,
            )
            row = {
                "inference_request_id": request.inference_request_id,
                "semantic_task_id": request.semantic_task_id,
                "status": "ADMITTED",
                "context_manifest_hash": manifest.manifest_hash,
                "completed_attempt_id": None,
                "final_artifact_id": None,
                "failure_reason": None,
                "reserved_cost_usd": Decimal("0"),
                "accrued_cost_usd": Decimal("0"),
            }
            self._transition(
                conn, actor, row, state=self._state(row), event_type="INFERENCE_ADMITTED",
                operation_key=f"inference-admit:{request.idempotency_key}",
                metadata={"manifest_hash": manifest.manifest_hash}, artifact_ids=(manifest_artifact_id,),
            )
            conn.execute(
                "INSERT INTO inference_requests(inference_request_id,semantic_task_id,parent_run_id,task_class,criticality,request_json,request_hash,idempotency_key,context_manifest_hash,status,max_call_cost_usd,max_total_attempt_cost_usd) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'ADMITTED',%s,%s)",
                (
                    request.inference_request_id, request.semantic_task_id, request.parent_run_id, request.task_class,
                    request.criticality, Jsonb(request.model_dump(mode="json")), self._request_hash(request),
                    request.idempotency_key, manifest.manifest_hash, request.max_call_cost_usd,
                    request.max_total_attempt_cost_usd,
                ),
            )
            conn.execute(
                "INSERT INTO context_manifests(context_manifest_id,inference_request_id,compiler_version,retrieval_version,required_evidence_classes,candidate_evidence_ids,included_evidence_ids,tool_addressable_evidence_ids,excluded_evidence_json,summary_artifact_ids,truncation_json,egress_decision_json,completeness_status,manifest_hash,manifest_json,manifest_artifact_id,created_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    manifest.context_manifest_id, request.inference_request_id, manifest.compiler_version,
                    manifest.retrieval_version, list(manifest.required_evidence_classes), list(manifest.candidate_evidence_ids),
                    list(manifest.included_evidence_ids), list(manifest.tool_addressable_evidence_ids),
                    Jsonb(manifest.excluded_evidence), list(manifest.summary_artifact_ids), Jsonb(manifest.truncation),
                    Jsonb(manifest.egress_decision), manifest.completeness_status, manifest.manifest_hash,
                    Jsonb(manifest.model_dump(mode="json")), manifest_artifact_id, manifest.created_at,
                ),
            )
            return request

    def completed_result(self, request_id: str) -> InferenceResult | None:
        with self._transaction() as (conn, actor):
            actor.require("inference")
            row = conn.execute(
                "SELECT a.attempt_json FROM inference_requests r JOIN inference_attempts a ON a.inference_attempt_id=r.completed_attempt_id WHERE r.inference_request_id=%s",
                (request_id,),
            ).fetchone()
            if not row:
                return None
            attempt = InferenceAttempt.model_validate(row["attempt_json"])
            return InferenceResult(request_id=request_id, status=attempt.status, artifact=attempt.output_artifact, route_id=attempt.provider_route_id)

    def claim_attempt(self, request_id: str, route_id: str, lease_seconds: float) -> InferenceAttempt:
        if lease_seconds <= 0:
            raise ValueError("attempt lease must be positive")
        route = self._routes.get(route_id)
        if route is None:
            raise ValueError("unregistered inference route")
        with self._transaction() as (conn, actor):
            actor.require("inference")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            request = conn.execute("SELECT * FROM inference_requests WHERE inference_request_id=%s FOR UPDATE", (request_id,)).fetchone()
            if not request:
                raise ValueError("unknown inference request")
            if request["completed_attempt_id"]:
                raise ConcurrentModification("semantic request already completed")
            active = conn.execute(
                "SELECT 1 FROM inference_attempts WHERE inference_request_id=%s AND status='CREATED' AND lease_until>now() FOR UPDATE",
                (request_id,),
            ).fetchone()
            if active:
                raise ConcurrentModification("inference request has an active lease")
            sequence = conn.execute(
                "SELECT COALESCE(MAX(attempt_no), 0) + 1 AS attempt_no, COALESCE(MAX(lease_fence), 0) + 1 AS fence FROM inference_attempts WHERE inference_request_id=%s",
                (request_id,),
            ).fetchone()
            attempt = InferenceAttempt(
                inference_request_id=request_id,
                attempt_no=sequence["attempt_no"],
                provider_route_id=route_id,
                lease_fence=sequence["fence"],
                model_family=route.model_family,
                model_version=route.model_version,
                upstream_correlation_domain=route.upstream_correlation_domain,
                reasoning_effort=InferenceRequest.model_validate(request["request_json"]).preferred_reasoning_effort,
                prompt_manifest_hash=request["context_manifest_hash"],
                pricing_plan_id=route.pricing.price_plan_id,
            )
            state = self._state(request) | {"status": "ATTEMPTING", "active_attempt_id": attempt.inference_attempt_id}
            self._transition(conn, actor, request, state=state, event_type="INFERENCE_ATTEMPT_CLAIMED", operation_key=f"inference-claim:{attempt.inference_attempt_id}", metadata={"route_id": route_id, "lease_fence": attempt.lease_fence})
            conn.execute(
                "INSERT INTO inference_attempts(inference_attempt_id,inference_request_id,attempt_no,provider_route_id,model_family,model_version,reasoning_effort,prompt_manifest_hash,lease_fence,lease_until,status,token_count_method,pricing_plan_id,attempt_json,started_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,now()+(%s * interval '1 second'),'CREATED',%s,%s,%s,%s)",
                (attempt.inference_attempt_id, request_id, attempt.attempt_no, route_id, attempt.model_family, attempt.model_version, attempt.reasoning_effort, attempt.prompt_manifest_hash, attempt.lease_fence, lease_seconds, attempt.usage.token_count_method, attempt.pricing_plan_id, Jsonb(attempt.model_dump(mode="json")), attempt.started_at),
            )
            conn.execute("UPDATE inference_requests SET status='ATTEMPTING' WHERE inference_request_id=%s", (request_id,))
            return attempt

    def reserve_cost(self, request_id: str, attempt_id: str, amount: Decimal) -> bool:
        if amount < 0:
            raise ValueError("cost reservation cannot be negative")
        with self._transaction() as (conn, actor):
            actor.require("inference")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            request = conn.execute("SELECT * FROM inference_requests WHERE inference_request_id=%s FOR UPDATE", (request_id,)).fetchone()
            attempt = conn.execute("SELECT * FROM inference_attempts WHERE inference_attempt_id=%s AND inference_request_id=%s FOR UPDATE", (attempt_id, request_id)).fetchone()
            if not request or not attempt:
                raise ValueError("unknown inference request or attempt")
            if attempt["status"] != AttemptStatus.CREATED:
                return False
            reserved = Decimal(request["reserved_cost_usd"]) - Decimal(attempt["total_cost_usd"]) + amount
            if request["max_total_attempt_cost_usd"] is not None and Decimal(request["accrued_cost_usd"]) + reserved > Decimal(request["max_total_attempt_cost_usd"]):
                return False
            state = self._state(request) | {"reserved_cost_usd": str(reserved)}
            self._transition(conn, actor, request, state=state, event_type="INFERENCE_COST_RESERVED", operation_key=f"inference-reserve:{attempt_id}", metadata={"amount_usd": str(amount)})
            conn.execute("UPDATE inference_requests SET reserved_cost_usd=%s WHERE inference_request_id=%s", (reserved, request_id))
            conn.execute("UPDATE inference_attempts SET total_cost_usd=%s WHERE inference_attempt_id=%s", (amount, attempt_id))
            return True

    def finish_attempt(self, attempt: InferenceAttempt) -> bool:
        with self._transaction() as (conn, actor):
            actor.require("inference")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            request = conn.execute("SELECT * FROM inference_requests WHERE inference_request_id=%s FOR UPDATE", (attempt.inference_request_id,)).fetchone()
            stored = conn.execute("SELECT * FROM inference_attempts WHERE inference_attempt_id=%s FOR UPDATE", (attempt.inference_attempt_id,)).fetchone()
            if not request or not stored:
                return False
            newest = conn.execute("SELECT MAX(lease_fence) AS fence FROM inference_attempts WHERE inference_request_id=%s", (attempt.inference_request_id,)).fetchone()
            stale = (
                stored["lease_fence"] != attempt.lease_fence
                or newest["fence"] != attempt.lease_fence
                or stored["lease_until"] <= utcnow()
                or (request["completed_attempt_id"] and attempt.status in {AttemptStatus.SEMANTIC_ACCEPTED, AttemptStatus.DECISION_USEFUL})
            )
            persisted = attempt
            artifact_id: str | None = None
            if stale:
                persisted = attempt.model_copy(update={"status": AttemptStatus.HIBERNATED, "error_class": "late_result_deduplicated", "output_artifact": None})
            elif persisted.output_artifact is not None:
                artifact_id = self._store.put_artifact(
                    conn, actor, {"attempt_id": attempt.inference_attempt_id, "artifact": persisted.output_artifact},
                    schema_name="inference/response-artifact-v1", classification="INTERNAL", policy_version=self.POLICY_VERSION,
                )
            reservation = Decimal(stored["total_cost_usd"])
            reserved = Decimal(request["reserved_cost_usd"]) - reservation
            accrued = Decimal(request["accrued_cost_usd"]) + persisted.total_cost_usd
            completed = persisted.status in {AttemptStatus.SEMANTIC_ACCEPTED, AttemptStatus.DECISION_USEFUL}
            state = self._state(request) | {
                "status": persisted.status if completed else request["status"],
                "completed_attempt_id": persisted.inference_attempt_id if completed else request["completed_attempt_id"],
                "final_artifact_id": artifact_id if completed else request["final_artifact_id"],
                "reserved_cost_usd": str(reserved), "accrued_cost_usd": str(accrued),
            }
            event_type = "INFERENCE_LATE_RESULT_DEDUPLICATED" if stale else "INFERENCE_ATTEMPT_FINISHED"
            self._transition(conn, actor, request, state=state, event_type=event_type, operation_key=f"inference-finish:{attempt.inference_attempt_id}", artifact_ids=(artifact_id,) if artifact_id else ())
            conn.execute(
                "UPDATE inference_attempts SET provider_request_id=%s,model_family=%s,model_version=%s,provider_reported_model=%s,status=%s,http_status=%s,error_class=%s,input_tokens=%s,output_tokens=%s,billed_tokens=%s,token_count_method=%s,pricing_plan_id=%s,fixed_call_cost_usd=%s,token_cost_usd=%s,total_cost_usd=%s,provider_reported_cost_usd=%s,latency_ms=%s,output_artifact_id=%s,response_hash=%s,attempt_json=%s,completed_at=%s WHERE inference_attempt_id=%s",
                (persisted.provider_request_id, persisted.model_family, persisted.model_version, persisted.provider_reported_model, persisted.status, persisted.http_status, persisted.error_class, persisted.usage.input_tokens, persisted.usage.output_tokens, persisted.billed_tokens, persisted.usage.token_count_method, persisted.pricing_plan_id, persisted.fixed_call_cost_usd, persisted.token_cost_usd, persisted.total_cost_usd, persisted.provider_reported_cost_usd, persisted.latency_ms, artifact_id, persisted.response_hash, Jsonb(persisted.model_dump(mode="json")), persisted.completed_at or utcnow(), persisted.inference_attempt_id),
            )
            conn.execute("UPDATE inference_requests SET reserved_cost_usd=%s,accrued_cost_usd=%s,status=%s,completed_attempt_id=%s,final_artifact_id=%s,completed_at=CASE WHEN %s THEN now() ELSE completed_at END WHERE inference_request_id=%s", (reserved, accrued, state["status"], state["completed_attempt_id"], state["final_artifact_id"], completed, attempt.inference_request_id))
            return not stale

    def append_event(self, request_id: str, event_type: str, payload: dict[str, object]) -> None:
        with self._transaction() as (conn, actor):
            actor.require("inference")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            request = conn.execute("SELECT * FROM inference_requests WHERE inference_request_id=%s FOR UPDATE", (request_id,)).fetchone()
            if not request:
                raise ValueError("unknown inference request")
            self._transition(
                conn, actor, request, state=self._state(request), event_type=event_type,
                operation_key=f"inference-note:{request_id}:{event_type}:{content_hash(payload)}", metadata=payload,
            )

    def hibernate(self, request_id: str, reason: str) -> None:
        if not reason.strip():
            raise ValueError("a hibernation reason is required")
        with self._transaction() as (conn, actor):
            actor.require("inference")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            request = conn.execute("SELECT * FROM inference_requests WHERE inference_request_id=%s FOR UPDATE", (request_id,)).fetchone()
            if not request:
                raise ValueError("unknown inference request")
            if request["completed_attempt_id"]:
                return
            state = self._state(request) | {"status": "HIBERNATED", "failure_reason": reason}
            self._transition(conn, actor, request, state=state, event_type="INFERENCE_HIBERNATED", operation_key=f"inference-hibernate:{request_id}:{content_hash(reason)}", metadata={"reason": reason})
            conn.execute("UPDATE inference_requests SET status='HIBERNATED',failure_reason=%s WHERE inference_request_id=%s", (reason, request_id))

    def revive(self, request_id: str, reason: str) -> bool:
        if not reason.strip():
            raise ValueError("a revival reason is required")
        with self._transaction() as (conn, actor):
            actor.require("inference")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            request = conn.execute("SELECT * FROM inference_requests WHERE inference_request_id=%s FOR UPDATE", (request_id,)).fetchone()
            if not request:
                raise ValueError("unknown inference request")
            if request["status"] != "HIBERNATED" or request["completed_attempt_id"]:
                return False
            state = self._state(request) | {"status": "ADMITTED", "failure_reason": None}
            self._transition(conn, actor, request, state=state, event_type="INFERENCE_REVIVED", operation_key=f"inference-revive:{request_id}:{content_hash(reason)}", metadata={"reason": reason})
            conn.execute("UPDATE inference_requests SET status='ADMITTED',failure_reason=NULL WHERE inference_request_id=%s", (request_id,))
            return True

    def circuit_is_open(self, route_id: str) -> bool:
        with self._transaction() as (conn, actor):
            actor.require("inference")
            row = conn.execute("SELECT is_open FROM inference_route_circuits WHERE provider_route_id=%s", (route_id,)).fetchone()
            return bool(row and row["is_open"])

    def record_route_outcome(self, route_id: str, succeeded: bool, failure_threshold: int) -> None:
        if failure_threshold <= 0:
            raise ValueError("circuit failure threshold must be positive")
        with self._transaction() as (conn, actor):
            actor.require("inference")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            row = conn.execute("SELECT * FROM inference_route_circuits WHERE provider_route_id=%s FOR UPDATE", (route_id,)).fetchone()
            failures = 0 if succeeded else (row["consecutive_failures"] if row else 0) + 1
            is_open = failures >= failure_threshold
            aggregate = self._store.state(conn, "inference_route_circuit", route_id)
            state = {"provider_route_id": route_id, "consecutive_failures": failures, "is_open": is_open}
            self._store.transition(
                conn, actor, capability="inference", kind="inference_route_circuit", aggregate_id=route_id,
                expected_version=aggregate["version"] if aggregate else 0, state=state,
                event_type="INFERENCE_ROUTE_HEALTH_RECORDED", operation_key=f"inference-circuit:{route_id}:{(aggregate or {'version': 0})['version'] + 1}",
                task_id=route_id, policy_version=self.POLICY_VERSION, metadata={"succeeded": succeeded},
            )
            conn.execute(
                "INSERT INTO inference_route_circuits(provider_route_id,consecutive_failures,is_open,aggregate_version) VALUES(%s,%s,%s,1) "
                "ON CONFLICT(provider_route_id) DO UPDATE SET consecutive_failures=EXCLUDED.consecutive_failures,is_open=EXCLUDED.is_open,aggregate_version=inference_route_circuits.aggregate_version+1,updated_at=now()",
                (route_id, failures, is_open),
            )

    def revive_route(self, route_id: str, reason: str) -> bool:
        if not reason.strip():
            raise ValueError("a route revival reason is required")
        with self._transaction() as (conn, actor):
            actor.require("inference")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            row = conn.execute("SELECT * FROM inference_route_circuits WHERE provider_route_id=%s FOR UPDATE", (route_id,)).fetchone()
            if not row or not row["is_open"]:
                return False
            aggregate = self._store.state(conn, "inference_route_circuit", route_id)
            if aggregate is None:
                raise DomainError("INFERENCE_CIRCUIT_PROJECTION_MISSING")
            self._store.transition(
                conn, actor, capability="inference", kind="inference_route_circuit", aggregate_id=route_id,
                expected_version=aggregate["version"], state={"provider_route_id": route_id, "consecutive_failures": 0, "is_open": False},
                event_type="INFERENCE_ROUTE_REVIVED", operation_key=f"inference-circuit-revive:{route_id}:{content_hash(reason)}",
                task_id=route_id, policy_version=self.POLICY_VERSION, metadata={"reason": reason},
            )
            conn.execute("UPDATE inference_route_circuits SET consecutive_failures=0,is_open=false,aggregate_version=aggregate_version+1,updated_at=now() WHERE provider_route_id=%s", (route_id,))
            return True

    def reconcile_attempt_cost(self, request_id: str, attempt_id: str, provider_cost: Decimal) -> bool:
        if provider_cost < 0:
            raise ValueError("provider cost cannot be negative")
        with self._transaction() as (conn, actor):
            actor.require("inference")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            request = conn.execute("SELECT * FROM inference_requests WHERE inference_request_id=%s FOR UPDATE", (request_id,)).fetchone()
            attempt_row = conn.execute("SELECT * FROM inference_attempts WHERE inference_attempt_id=%s AND inference_request_id=%s FOR UPDATE", (attempt_id, request_id)).fetchone()
            if not request or not attempt_row:
                raise ValueError("unknown inference request or attempt")
            attempt = InferenceAttempt.model_validate(attempt_row["attempt_json"])
            if attempt.completed_at is None:
                raise ValueError("cannot reconcile an unfinished inference attempt")
            reconciled = attempt.model_copy(
                update={"provider_reported_cost_usd": provider_cost, "total_cost_usd": provider_cost}
            )
            matches = attempt.total_cost_usd == provider_cost
            event_type = "INFERENCE_BILLING_RECONCILED" if matches else "BILLING_RECONCILIATION_ERROR"
            accrued = Decimal(request["accrued_cost_usd"]) - attempt.total_cost_usd + provider_cost
            state = self._state(request) | {"accrued_cost_usd": str(accrued)}
            self._transition(
                conn, actor, request, state=state, event_type=event_type,
                operation_key=f"inference-reconcile:{attempt_id}:{provider_cost}",
                metadata={"attempt_id": attempt_id, "estimated_cost_usd": str(attempt.total_cost_usd), "provider_cost_usd": str(provider_cost)},
            )
            conn.execute(
                "UPDATE inference_attempts SET provider_reported_cost_usd=%s,total_cost_usd=%s,attempt_json=%s WHERE inference_attempt_id=%s",
                (provider_cost, provider_cost, Jsonb(reconciled.model_dump(mode="json")), attempt_id),
            )
            conn.execute("UPDATE inference_requests SET accrued_cost_usd=%s WHERE inference_request_id=%s", (accrued, request_id))
            return matches

    def mark_decision_useful(self, request_id: str, attempt_id: str, reason: str) -> bool:
        if not reason.strip():
            raise ValueError("a useful-decision reason is required")
        with self._transaction() as (conn, actor):
            actor.require("inference")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            request = conn.execute("SELECT * FROM inference_requests WHERE inference_request_id=%s FOR UPDATE", (request_id,)).fetchone()
            attempt_row = conn.execute("SELECT * FROM inference_attempts WHERE inference_attempt_id=%s AND inference_request_id=%s FOR UPDATE", (attempt_id, request_id)).fetchone()
            if not request or not attempt_row or request["completed_attempt_id"] != attempt_id:
                return False
            attempt = InferenceAttempt.model_validate(attempt_row["attempt_json"])
            if attempt.status == AttemptStatus.DECISION_USEFUL:
                return True
            if attempt.status != AttemptStatus.SEMANTIC_ACCEPTED:
                return False
            useful = attempt.model_copy(update={"status": AttemptStatus.DECISION_USEFUL})
            state = self._state(request) | {"status": AttemptStatus.DECISION_USEFUL}
            self._transition(conn, actor, request, state=state, event_type="INFERENCE_DECISION_USEFUL", operation_key=f"inference-useful:{attempt_id}", metadata={"reason": reason})
            conn.execute("UPDATE inference_attempts SET status=%s,attempt_json=%s WHERE inference_attempt_id=%s", (AttemptStatus.DECISION_USEFUL, Jsonb(useful.model_dump(mode="json")), attempt_id))
            conn.execute("UPDATE inference_requests SET status=%s WHERE inference_request_id=%s", (AttemptStatus.DECISION_USEFUL, request_id))
            return True


class ProviderCredentialResolver:
    """Resolves configured provider secrets from explicit environment or JSON secret files."""

    def __init__(self, *, environment: Mapping[str, str] | None = None, credential_file: Path | None = None):
        self._environment = environment if environment is not None else os.environ
        self._file_credentials: dict[str, str] = {}
        if credential_file is not None:
            loaded = json.loads(credential_file.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in loaded.items()):
                raise ValueError("inference credential file must map key pool IDs to strings")
            self._file_credentials = loaded

    async def __call__(self, route: ProviderRoute) -> str:
        environment_key = "LIKI_INFERENCE_KEY_" + "".join(
            character if character.isalnum() else "_" for character in route.key_pool_id.upper()
        )
        secret = self._environment.get(environment_key) or self._file_credentials.get(route.key_pool_id)
        if not secret:
            raise ProviderTransportError("provider_credential_unavailable", retryable=False)
        return secret


class InferenceService:
    """Constructs a broker only from owner-configured routes and real provider transports."""

    def __init__(
        self,
        store: Store,
        credential: Credential,
        routes: tuple[ProviderRoute, ...],
        client: httpx.AsyncClient,
        key_resolver: ProviderCredentialResolver,
        *,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.client = client
        self.routes = routes
        self.backend = PostgresInferenceBackend(store, credential, {route.route_id: route for route in routes})
        self.broker = InferenceBroker(self.backend, routes, adapter_registry(client, key_resolver), retry_policy=retry_policy)

    @classmethod
    def from_environment(
        cls,
        store: Store,
        credential: Credential,
        *,
        environment: Mapping[str, str] | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> InferenceService:
        values = environment if environment is not None else os.environ
        route_path = values.get("LIKI_INFERENCE_PROVIDER_CONFIG")
        if not route_path:
            raise DomainError("INFERENCE_PROVIDER_CONFIG_MISSING")
        credential_path = values.get("LIKI_INFERENCE_CREDENTIAL_FILE")
        return cls(
            store, credential, load_provider_routes(route_path), httpx.AsyncClient(follow_redirects=False, trust_env=False),
            ProviderCredentialResolver(environment=values, credential_file=Path(credential_path) if credential_path else None),
            retry_policy=retry_policy,
        )

    async def aclose(self) -> None:
        await self.client.aclose()
