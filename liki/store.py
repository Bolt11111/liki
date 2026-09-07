from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from liki.core import DomainError, content_hash, environment_fingerprint, uid, utcnow

CAPABILITIES = {
    "owner": {"read", "stop", "proposal", "owner_decision", "incident", "notification"},
    "operator": {"read", "stop", "incident", "notification"},
    "research": {"read", "artifact", "research", "task"},
    "evaluator": {"read", "artifact", "evidence", "gate", "snapshot"},
    "sealed_evaluator": {"sealed", "artifact", "evidence", "gate", "snapshot"},
    "inference": {"read", "artifact", "inference"},
    "scheduler": {"read", "task", "incident", "notification"},
    "governance": {"read", "artifact", "proposal", "policy", "incident", "notification"},
    "paper": {"read", "artifact", "paper", "stop", "incident"},
    "data": {"read", "artifact", "evidence", "data"},
    "auditor": {"read"},
}


@dataclass(frozen=True)
class Identity:
    principal_id: str
    role: str
    code_fingerprint: str

    def require(self, capability: str) -> None:
        if capability not in CAPABILITIES.get(self.role, set()):
            raise DomainError("FORBIDDEN", f"Role lacks capability: {capability}")


@dataclass(frozen=True)
class Credential:
    token: str = field(repr=False)


class Store:
    def __init__(self, dsn: str):
        self._dsn = dsn
        self.fingerprint = environment_fingerprint()

    @contextmanager
    def transaction(self, credential: Credential) -> Iterator[tuple[psycopg.Connection[Any], Identity]]:
        with psycopg.connect(self._dsn, row_factory=dict_row) as conn:
            conn.execute("SET LOCAL statement_timeout = '15s'")
            record = conn.execute(
                "SELECT * FROM liki_authenticate(%s)",
                (hashlib.sha256(credential.token.encode()).hexdigest(),),
            ).fetchone()
            if not record:
                raise DomainError("UNAUTHENTICATED")
            identity = Identity(record["principal_id"], record["role"], record["code_fingerprint"])
            yield conn, identity

    @staticmethod
    def state(conn: psycopg.Connection[Any], kind: str, aggregate_id: str) -> dict | None:
        return conn.execute("SELECT * FROM aggregates WHERE aggregate_type=%s AND aggregate_id=%s",
                            (kind, aggregate_id)).fetchone()

    def transition(self, conn: psycopg.Connection[Any], actor: Identity, *, capability: str,
                   kind: str, aggregate_id: str, expected_version: int, state: dict,
                   event_type: str, operation_key: str, task_id: str,
                   policy_version: str, evidence_ids: tuple[str, ...] = (),
                   artifact_ids: tuple[str, ...] = (), metadata: dict | None = None,
                   topic: str | None = None) -> dict:
        actor.require(capability)
        if not all((kind, aggregate_id, operation_key, task_id, policy_version)):
            raise DomainError("INVALID_TRANSITION")
        request = {"kind": kind, "id": aggregate_id, "expected_version": expected_version,
                   "state": state, "event_type": event_type, "actor": actor.principal_id,
                   "task_id": task_id, "policy_version": policy_version,
                   "evidence": evidence_ids, "artifacts": artifact_ids, "metadata": metadata or {}}
        request_hash = content_hash(request)
        # Serialize the audit chain and state comparison in one durable transaction.
        conn.execute("SELECT pg_advisory_xact_lock(71403218)")
        existing = conn.execute("SELECT * FROM event_log WHERE operation_key=%s", (operation_key,)).fetchone()
        if existing:
            if existing["operation_hash"] != request_hash:
                raise DomainError("IDEMPOTENCY_CONFLICT")
            return existing
        current = self.state(conn, kind, aggregate_id)
        actual = current["version"] if current else 0
        if expected_version != actual:
            raise DomainError("CONCURRENT_MODIFICATION")
        for eid in evidence_ids:
            if not conn.execute("SELECT 1 FROM evidence WHERE evidence_id=%s", (eid,)).fetchone():
                raise DomainError("UNKNOWN_EVIDENCE")
        for aid in artifact_ids:
            if not conn.execute("SELECT 1 FROM artifacts WHERE artifact_id=%s", (aid,)).fetchone():
                raise DomainError("UNKNOWN_ARTIFACT")
        last = conn.execute("SELECT event_hash FROM event_log ORDER BY sequence DESC LIMIT 1").fetchone()
        previous = last["event_hash"] if last else "GENESIS"
        envelope = {"event_id": uid("EVT"), "event_type": event_type, "occurred_at_utc": utcnow(),
                    "aggregate_type": kind, "aggregate_id": aggregate_id, "aggregate_version": actual + 1,
                    "principal_id": actor.principal_id, "actor_type": "human" if actor.role == "owner" else "deterministic_service",
                    "task_id": task_id, "branch_id": state.get("branch_id"),
                    "strategy_version_id": state.get("strategy_version_id"),
                    "artifact_ids": list(artifact_ids), "evidence_ids": list(evidence_ids),
                    "gate_id": state.get("gate_id"), "policy_version": policy_version,
                    "code_commit": actor.code_fingerprint, "environment_fingerprint": self.fingerprint,
                    "metadata": {**(metadata or {}), "state_after": state}, "previous_hash": previous,
                    "operation_key": operation_key, "operation_hash": request_hash}
        event_hash = content_hash(envelope)
        keys = list(envelope) + ["event_hash"]
        values = [Jsonb(v) if k == "metadata" else v for k, v in envelope.items()] + [event_hash]
        columns = ",".join(keys)
        placeholders = ",".join(["%s"] * len(keys))
        event = conn.execute(f"INSERT INTO event_log ({columns}) VALUES ({placeholders}) RETURNING *", values).fetchone()
        if event is None:
            raise DomainError("EVENT_APPEND_FAILED")
        conn.execute("INSERT INTO aggregates VALUES (%s,%s,%s,%s) ON CONFLICT (aggregate_type,aggregate_id) "
                     "DO UPDATE SET version=EXCLUDED.version,state=EXCLUDED.state",
                     (kind, aggregate_id, actual + 1, Jsonb(state)))
        if topic:
            conn.execute("INSERT INTO transactional_outbox(outbox_id,event_id,topic,payload) VALUES(%s,%s,%s,%s)",
                         (uid("OUT"), event["event_id"], topic, Jsonb({"event_id": event["event_id"]})))
        return event

    def put_artifact(self, conn: psycopg.Connection[Any], actor: Identity, content: dict, *,
                     schema_name: str, classification: str, policy_version: str) -> str:
        actor.require("artifact")
        if classification == "SECRET" or (classification == "SEALED" and actor.role != "sealed_evaluator"):
            raise DomainError("FORBIDDEN_CLASSIFICATION")
        digest = content_hash(content)
        aid = uid("ART")
        row = conn.execute("INSERT INTO artifacts(artifact_id,content_hash,schema_name,classification,producer_id,"
                           "environment_fingerprint,policy_version,content) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) "
                           "ON CONFLICT(producer_id,content_hash,schema_name) DO NOTHING RETURNING artifact_id",
                           (aid, digest, schema_name, classification, actor.principal_id, self.fingerprint,
                            policy_version, Jsonb(content))).fetchone()
        if row:
            return row["artifact_id"]
        existing = conn.execute("SELECT artifact_id FROM artifacts WHERE producer_id=%s AND content_hash=%s AND schema_name=%s",
                                (actor.principal_id, digest, schema_name)).fetchone()
        if existing is None:
            raise DomainError("ARTIFACT_PERSISTENCE_FAILED")
        return existing["artifact_id"]

    def artifact(self, conn: psycopg.Connection[Any], actor: Identity, artifact_id: str) -> dict:
        row = conn.execute("SELECT * FROM artifacts WHERE artifact_id=%s", (artifact_id,)).fetchone()
        if not row or (row["classification"] == "SEALED" and actor.role != "sealed_evaluator"):
            raise DomainError("NOT_FOUND")
        if content_hash(row["content"]) != row["content_hash"]:
            raise DomainError("ARTIFACT_CORRUPTED")
        return row

    def audit(self, conn: psycopg.Connection[Any]) -> dict:
        conn.execute("SELECT pg_advisory_xact_lock_shared(71403218)")
        previous = "GENESIS"
        count = 0
        reconstructed: dict[tuple[str, str], tuple[int, dict]] = {}
        for record in conn.execute("SELECT * FROM event_log ORDER BY sequence"):
            envelope = {k: v for k, v in record.items() if k not in {"sequence", "ingested_at_utc", "event_hash"}}
            # PostgreSQL's text projection loses the gate ID's original JSON type.
            gate_id = record["metadata"]["state_after"].get("gate_id")
            if record["gate_id"] != (str(gate_id) if gate_id is not None else None):
                raise DomainError("AUDIT_GATE_PROJECTION_MISMATCH")
            envelope["gate_id"] = gate_id
            if record["previous_hash"] != previous or content_hash(envelope) != record["event_hash"]:
                raise DomainError("AUDIT_INTEGRITY_FAILURE")
            key = record["aggregate_type"], record["aggregate_id"]
            prior_version = reconstructed.get(key, (0, {}))[0]
            if record["aggregate_version"] != prior_version + 1:
                raise DomainError("AUDIT_REVISION_GAP")
            reconstructed[key] = record["aggregate_version"], record["metadata"]["state_after"]
            previous = record["event_hash"]
            count += 1
        projections = conn.execute("SELECT * FROM aggregates").fetchall()
        if len(projections) != len(reconstructed):
            raise DomainError("PROJECTION_DRIFT")
        for row in projections:
            if reconstructed.get((row["aggregate_type"], row["aggregate_id"])) != (row["version"], row["state"]):
                raise DomainError("PROJECTION_DRIFT")
        return {"events": count, "head_hash": previous, "aggregates": len(reconstructed), "status": "VERIFIED"}


def migrate(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(71403219)")
        for file in sorted(Path("migrations").glob("*.sql")):
            relation = conn.execute("SELECT to_regclass('public.schema_migrations')").fetchone()
            assert relation is not None
            exists = relation[0]
            previous = conn.execute("SELECT content_hash FROM schema_migrations WHERE version=%s", (file.name,)).fetchone() if exists else None
            digest = hashlib.sha256(file.read_bytes()).hexdigest()
            if previous and previous[0] != digest:
                raise DomainError("MIGRATION_DRIFT")
            if not previous:
                conn.execute(file.read_text())
                conn.execute("INSERT INTO schema_migrations(version,content_hash) VALUES(%s,%s)", (file.name, digest))
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        unprotected = conn.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname='public' AND c.relkind='r' AND NOT c.relrowsecurity"
        ).fetchall()
        if unprotected:
            raise DomainError("MIGRATION_MISSING_WORKLOAD_RLS")
        conn.execute("GRANT USAGE ON SCHEMA public TO liki_app")
        conn.execute("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO liki_app")
        conn.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO liki_app")
        conn.execute("REVOKE INSERT, UPDATE ON principals, service_tokens, schema_migrations FROM liki_app")
        conn.execute("REVOKE SELECT ON service_tokens FROM liki_app")
        conn.execute("REVOKE UPDATE ON event_log, artifacts, evidence, evaluation_snapshots FROM liki_app")


def issue_credential(dsn: str, principal_id: str, role: str, *, duration: timedelta) -> Credential:
    if role not in CAPABILITIES or duration.total_seconds() <= 0:
        raise DomainError("INVALID_PRINCIPAL")
    token = secrets.token_urlsafe(48)
    with psycopg.connect(dsn) as conn:
        conn.execute("INSERT INTO principals(principal_id,role,code_fingerprint) VALUES(%s,%s,%s) "
                     "ON CONFLICT(principal_id) DO NOTHING", (principal_id, role, environment_fingerprint()))
        existing = conn.execute("SELECT role FROM principals WHERE principal_id=%s", (principal_id,)).fetchone()
        if existing is None or existing[0] != role:
            raise DomainError("PRINCIPAL_ROLE_CONFLICT")
        conn.execute("INSERT INTO service_tokens(token_hash,principal_id,expires_at) VALUES(%s,%s,%s)",
                     (hashlib.sha256(token.encode()).hexdigest(), principal_id, utcnow() + duration))
    return Credential(token)
