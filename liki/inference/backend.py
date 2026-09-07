"""Durable broker persistence contract and a SQLite implementation restricted to tests.

The production adapter belongs in the persistence workstream.  It must provide the
same atomic semantics; this module deliberately provides no production fallback.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol, runtime_checkable

from .types import AttemptStatus, ContextManifest, InferenceAttempt, InferenceRequest, InferenceResult, utcnow


class ConcurrentModification(RuntimeError):
    """A lease fence or request projection was superseded by another worker."""


class IdempotencyConflict(ValueError):
    """One idempotency key was reused for a different semantic request/context."""


@runtime_checkable
class InferenceBackend(Protocol):
    """Atomic source-of-truth contract required by the broker in every environment."""

    def create_or_get(self, request: InferenceRequest, manifest: ContextManifest) -> InferenceRequest: ...

    def completed_result(self, request_id: str) -> InferenceResult | None: ...

    def claim_attempt(self, request_id: str, route_id: str, lease_seconds: float) -> InferenceAttempt: ...

    def reserve_cost(self, request_id: str, attempt_id: str, amount: Decimal) -> bool: ...

    def finish_attempt(self, attempt: InferenceAttempt) -> bool: ...

    def append_event(self, request_id: str, event_type: str, payload: dict[str, object]) -> None: ...

    def hibernate(self, request_id: str, reason: str) -> None: ...

    def revive(self, request_id: str, reason: str) -> bool: ...

    def circuit_is_open(self, route_id: str) -> bool: ...

    def record_route_outcome(self, route_id: str, succeeded: bool, failure_threshold: int) -> None: ...

    def revive_route(self, route_id: str, reason: str) -> bool: ...

    def reconcile_attempt_cost(self, request_id: str, attempt_id: str, provider_cost: Decimal) -> bool: ...

    def mark_decision_useful(self, request_id: str, attempt_id: str, reason: str) -> bool: ...


class SQLiteTestInferenceBackend(InferenceBackend):
    """Test-only durable backend. Production must use transactional Postgres storage."""

    def __init__(self, path: str = ":memory:") -> None:
        self.connection = sqlite3.connect(path, isolation_level=None)
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(
            """
            CREATE TABLE inference_requests (
                request_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
                request_json TEXT NOT NULL, manifest_json TEXT NOT NULL, status TEXT NOT NULL,
                reserved_cost TEXT NOT NULL DEFAULT '0', accrued_cost TEXT NOT NULL DEFAULT '0',
                completed_attempt_id TEXT, failure_reason TEXT
            );
            CREATE TABLE inference_attempts (
                attempt_id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES inference_requests(request_id),
                attempt_no INTEGER NOT NULL, route_id TEXT NOT NULL, fence INTEGER NOT NULL,
                lease_until TEXT NOT NULL, reservation TEXT NOT NULL DEFAULT '0', attempt_json TEXT NOT NULL,
                UNIQUE(request_id, attempt_no)
            );
            CREATE TABLE inference_events (
                event_id INTEGER PRIMARY KEY, request_id TEXT NOT NULL, event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE route_circuits (
                route_id TEXT PRIMARY KEY, failures INTEGER NOT NULL DEFAULT 0, is_open INTEGER NOT NULL DEFAULT 0
            );
            """
        )

    def create_or_get(self, request: InferenceRequest, manifest: ContextManifest) -> InferenceRequest:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT request_json, manifest_json FROM inference_requests WHERE idempotency_key=?",
                (request.idempotency_key,),
            ).fetchone()
            if row:
                prior = InferenceRequest.model_validate_json(row[0])
                prior_manifest = ContextManifest.model_validate_json(row[1])
                if prior.semantic_task_id != request.semantic_task_id or prior_manifest.manifest_hash != manifest.manifest_hash:
                    raise IdempotencyConflict("idempotency key is already bound to another semantic request or context")
                self.connection.execute("COMMIT")
                return prior
            self.connection.execute(
                "INSERT INTO inference_requests(request_id,idempotency_key,request_json,manifest_json,status) VALUES (?,?,?,?,?)",
                (request.inference_request_id, request.idempotency_key, request.model_dump_json(), manifest.model_dump_json(), "ADMITTED"),
            )
            self.connection.execute(
                "INSERT INTO inference_events(request_id,event_type,payload_json,created_at) VALUES (?,?,?,?)",
                (
                    request.inference_request_id,
                    "inference_admitted",
                    json.dumps({"manifest_hash": manifest.manifest_hash}, sort_keys=True),
                    utcnow().isoformat(),
                ),
            )
            self.connection.execute("COMMIT")
            return request
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def completed_result(self, request_id: str) -> InferenceResult | None:
        row = self.connection.execute(
            """SELECT a.attempt_json FROM inference_requests r
               JOIN inference_attempts a ON a.attempt_id=r.completed_attempt_id WHERE r.request_id=?""",
            (request_id,),
        ).fetchone()
        if not row:
            return None
        attempt = InferenceAttempt.model_validate_json(row[0])
        return InferenceResult(
            request_id=request_id,
            status=attempt.status,
            artifact=attempt.output_artifact,
            route_id=attempt.provider_route_id,
        )

    def claim_attempt(self, request_id: str, route_id: str, lease_seconds: float) -> InferenceAttempt:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            request_row = self.connection.execute(
                "SELECT request_json, manifest_json, completed_attempt_id FROM inference_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            if not request_row:
                raise ValueError("unknown inference request")
            if request_row[2]:
                raise ConcurrentModification("semantic request already completed")
            row = self.connection.execute(
                "SELECT COUNT(*), MAX(fence) FROM inference_attempts WHERE request_id=?", (request_id,)
            ).fetchone()
            no, fence = int(row[0]) + 1, int(row[1] or 0) + 1
            request = InferenceRequest.model_validate_json(request_row[0])
            manifest = ContextManifest.model_validate_json(request_row[1])
            attempt = InferenceAttempt(
                inference_request_id=request_id,
                attempt_no=no,
                provider_route_id=route_id,
                lease_fence=fence,
                model_family="pending_route_resolution",
                reasoning_effort=request.preferred_reasoning_effort,
                prompt_manifest_hash=manifest.manifest_hash,
            )
            lease_until = (utcnow() + timedelta(seconds=lease_seconds)).isoformat()
            self.connection.execute(
                "INSERT INTO inference_attempts VALUES (?,?,?,?,?,?,?,?)",
                (attempt.inference_attempt_id, request_id, no, route_id, fence, lease_until, "0", attempt.model_dump_json()),
            )
            self.connection.execute("UPDATE inference_requests SET status='ATTEMPTING' WHERE request_id=?", (request_id,))
            self.connection.execute("COMMIT")
            return attempt
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def reserve_cost(self, request_id: str, attempt_id: str, amount: Decimal) -> bool:
        if amount < 0:
            raise ValueError("cost reservation cannot be negative")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT request_json,reserved_cost,accrued_cost FROM inference_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            attempt = self.connection.execute(
                "SELECT reservation FROM inference_attempts WHERE attempt_id=? AND request_id=?", (attempt_id, request_id)
            ).fetchone()
            if not row or not attempt:
                raise ValueError("unknown inference request or attempt")
            request = InferenceRequest.model_validate_json(row[0])
            # Spent attempts remain charged. Only this attempt's prior reservation may be replaced.
            outstanding_reservations = Decimal(row[1]) - Decimal(attempt[0]) + amount
            committed_total = Decimal(row[2]) + outstanding_reservations
            if (
                request.max_total_attempt_cost_usd is not None
                and committed_total > request.max_total_attempt_cost_usd
            ):
                self.connection.execute("ROLLBACK")
                return False
            self.connection.execute(
                "UPDATE inference_requests SET reserved_cost=? WHERE request_id=?",
                (str(outstanding_reservations), request_id),
            )
            self.connection.execute("UPDATE inference_attempts SET reservation=? WHERE attempt_id=?", (str(amount), attempt_id))
            self.connection.execute("COMMIT")
            return True
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def finish_attempt(self, attempt: InferenceAttempt) -> bool:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT fence, lease_until, reservation, attempt_json FROM inference_attempts WHERE attempt_id=?",
                (attempt.inference_attempt_id,),
            ).fetchone()
            newest_fence = self.connection.execute(
                "SELECT MAX(fence) FROM inference_attempts WHERE request_id=?", (attempt.inference_request_id,)
            ).fetchone()
            completed = self.connection.execute(
                "SELECT completed_attempt_id,reserved_cost,accrued_cost FROM inference_requests WHERE request_id=?", (attempt.inference_request_id,)
            ).fetchone()
            if not row or not completed:
                self.connection.execute("ROLLBACK")
                return False
            reservation = Decimal(row[2])
            lease_until = datetime.fromisoformat(row[1])
            stale = (
                int(row[0]) != attempt.lease_fence
                or int(newest_fence[0]) != attempt.lease_fence
                or utcnow() > lease_until
                or (
                    completed[0]
                    and attempt.status in {AttemptStatus.SEMANTIC_ACCEPTED, AttemptStatus.DECISION_USEFUL}
                )
            )
            if stale:
                stored = InferenceAttempt.model_validate_json(row[3])
                if stored.status != AttemptStatus.CREATED:
                    self.connection.execute("ROLLBACK")
                    return False
                deduplicated = attempt.model_copy(
                    update={
                        "status": AttemptStatus.HIBERNATED,
                        "error_class": "late_result_deduplicated",
                        "output_artifact": None,
                    }
                )
                self.connection.execute(
                    "UPDATE inference_attempts SET attempt_json=? WHERE attempt_id=?",
                    (deduplicated.model_dump_json(), attempt.inference_attempt_id),
                )
                self.connection.execute(
                    "UPDATE inference_requests SET reserved_cost=?, accrued_cost=? WHERE request_id=?",
                    (
                        str(Decimal(completed[1]) - reservation),
                        str(Decimal(completed[2]) + deduplicated.total_cost_usd),
                        attempt.inference_request_id,
                    ),
                )
                self.connection.execute(
                    "INSERT INTO inference_events(request_id,event_type,payload_json,created_at) VALUES (?,?,?,?)",
                    (
                        attempt.inference_request_id,
                        "late_result_deduplicated",
                        json.dumps({"attempt_id": attempt.inference_attempt_id}),
                        utcnow().isoformat(),
                    ),
                )
                self.connection.execute("COMMIT")
                return False
            self.connection.execute("UPDATE inference_attempts SET attempt_json=? WHERE attempt_id=?", (attempt.model_dump_json(), attempt.inference_attempt_id))
            self.connection.execute(
                "UPDATE inference_requests SET reserved_cost=?, accrued_cost=? WHERE request_id=?",
                (str(Decimal(completed[1]) - reservation), str(Decimal(completed[2]) + attempt.total_cost_usd), attempt.inference_request_id),
            )
            if attempt.status in {AttemptStatus.SEMANTIC_ACCEPTED, AttemptStatus.DECISION_USEFUL}:
                self.connection.execute(
                    "UPDATE inference_requests SET status=?, completed_attempt_id=? WHERE request_id=?",
                    (attempt.status, attempt.inference_attempt_id, attempt.inference_request_id),
                )
            self.connection.execute("COMMIT")
            return True
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def append_event(self, request_id: str, event_type: str, payload: dict[str, object]) -> None:
        self.connection.execute(
            "INSERT INTO inference_events(request_id,event_type,payload_json,created_at) VALUES (?,?,?,?)",
            (request_id, event_type, json.dumps(payload, sort_keys=True, default=str), utcnow().isoformat()),
        )

    def hibernate(self, request_id: str, reason: str) -> None:
        changed = self.connection.execute(
            "UPDATE inference_requests SET status='HIBERNATED', failure_reason=? "
            "WHERE request_id=? AND completed_attempt_id IS NULL",
            (reason, request_id),
        ).rowcount
        if changed:
            self.append_event(request_id, "inference_hibernated", {"reason": reason})

    def revive(self, request_id: str, reason: str) -> bool:
        changed = self.connection.execute(
            "UPDATE inference_requests SET status='ADMITTED', failure_reason=NULL "
            "WHERE request_id=? AND status='HIBERNATED' AND completed_attempt_id IS NULL",
            (request_id,),
        ).rowcount
        if changed:
            self.append_event(request_id, "inference_revived", {"reason": reason})
        return bool(changed)

    def circuit_is_open(self, route_id: str) -> bool:
        row = self.connection.execute("SELECT is_open FROM route_circuits WHERE route_id=?", (route_id,)).fetchone()
        return bool(row and row[0])

    def record_route_outcome(self, route_id: str, succeeded: bool, failure_threshold: int) -> None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute("SELECT failures FROM route_circuits WHERE route_id=?", (route_id,)).fetchone()
            failures = 0 if succeeded else int(row[0] if row else 0) + 1
            self.connection.execute(
                "INSERT INTO route_circuits(route_id,failures,is_open) VALUES (?,?,?) "
                "ON CONFLICT(route_id) DO UPDATE SET failures=excluded.failures,is_open=excluded.is_open",
                (route_id, failures, int(failures >= failure_threshold)),
            )
            self.connection.execute("COMMIT")
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def revive_route(self, route_id: str, reason: str) -> bool:
        if not reason.strip():
            raise ValueError("a route revival reason is required")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT is_open FROM route_circuits WHERE route_id=?", (route_id,)
            ).fetchone()
            if not row:
                self.connection.execute("COMMIT")
                return False
            self.connection.execute(
                "UPDATE route_circuits SET failures=0,is_open=0 WHERE route_id=?", (route_id,)
            )
            self.connection.execute("COMMIT")
            return True
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def reconcile_attempt_cost(self, request_id: str, attempt_id: str, provider_cost: Decimal) -> bool:
        row = self.connection.execute("SELECT attempt_json FROM inference_attempts WHERE attempt_id=? AND request_id=?", (attempt_id, request_id)).fetchone()
        if not row:
            raise ValueError("unknown inference attempt")
        attempt = InferenceAttempt.model_validate_json(row[0])
        if provider_cost < 0:
            raise ValueError("provider cost cannot be negative")
        reconciled = attempt.model_copy(update={"provider_reported_cost_usd": provider_cost})
        self.connection.execute(
            "UPDATE inference_attempts SET attempt_json=? WHERE attempt_id=?",
            (reconciled.model_dump_json(), attempt_id),
        )
        if attempt.total_cost_usd == provider_cost:
            self.append_event(request_id, "billing_reconciled", {"attempt_id": attempt_id})
            return True
        self.append_event(
            request_id,
            "BILLING_RECONCILIATION_ERROR",
            {"attempt_id": attempt_id, "estimated_cost_usd": str(attempt.total_cost_usd), "provider_cost_usd": str(provider_cost)},
        )
        return False

    def mark_decision_useful(self, request_id: str, attempt_id: str, reason: str) -> bool:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT attempt_json FROM inference_attempts WHERE attempt_id=? AND request_id=?",
                (attempt_id, request_id),
            ).fetchone()
            accepted = self.connection.execute(
                "SELECT completed_attempt_id FROM inference_requests WHERE request_id=?", (request_id,)
            ).fetchone()
            if not row or not accepted or accepted[0] != attempt_id:
                self.connection.execute("ROLLBACK")
                return False
            attempt = InferenceAttempt.model_validate_json(row[0])
            if attempt.status == AttemptStatus.DECISION_USEFUL:
                self.connection.execute("COMMIT")
                return True
            if attempt.status != AttemptStatus.SEMANTIC_ACCEPTED:
                self.connection.execute("ROLLBACK")
                return False
            self.connection.execute(
                "UPDATE inference_attempts SET attempt_json=? WHERE attempt_id=?",
                (attempt.model_copy(update={"status": AttemptStatus.DECISION_USEFUL}).model_dump_json(), attempt_id),
            )
            self.connection.execute(
                "UPDATE inference_requests SET status=? WHERE request_id=?",
                (AttemptStatus.DECISION_USEFUL, request_id),
            )
            self.connection.execute(
                "INSERT INTO inference_events(request_id,event_type,payload_json,created_at) VALUES (?,?,?,?)",
                (request_id, "inference_decision_useful", json.dumps({"attempt_id": attempt_id, "reason": reason}), utcnow().isoformat()),
            )
            self.connection.execute("COMMIT")
            return True
        except Exception:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise
