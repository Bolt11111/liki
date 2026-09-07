"""Bounded deterministic read models for authenticated operators."""

from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

from psycopg import sql

from liki.core import DomainError, utcnow
from liki.scheduler import Scheduler
from liki.store import Credential, Store


def exact_numbers(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: exact_numbers(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [exact_numbers(item) for item in value]
    return value


class Operations:
    def __init__(self, store: Store):
        self.store = store

    def status(self, credential: Credential) -> dict:
        with self.store.transaction(credential) as (conn, actor):
            actor.require("read")
            clock = conn.execute("SELECT now() AS time").fetchone()
            assert clock is not None
            database_time = clock["time"]
            counters = {}
            for name, table in (("campaigns", "campaigns"), ("tasks", "tasks"),
                                ("artifacts", "artifacts"), ("events", "event_log")):
                count = conn.execute(sql.SQL("SELECT count(*) AS n FROM {}").format(
                    sql.Identifier(table))).fetchone()
                assert count is not None
                counters[name] = count["n"]
            incidents = conn.execute("SELECT severity,count(*) AS count FROM incidents "
                                    "WHERE status NOT IN ('RESOLVED','CLOSED') GROUP BY severity").fetchall()
            active = conn.execute("SELECT count(*) AS count FROM active_task_runs r "
                                  "JOIN resource_leases l ON l.lease_id=r.active_lease_id "
                                  "WHERE r.status='running' AND l.released_at IS NULL "
                                  "AND l.expires_at>now()").fetchone()
            assert active is not None
            return {"mode": "RESEARCH", "real_money_execution": "PROHIBITED",
                    "database": "CONNECTED", "as_of": database_time, "role": actor.role,
                    "counts": counters, "active_leased_runs": active["count"], "open_incidents": incidents,
                    "production_acceptance": "NOT_ACCEPTED"}

    def coverage(self, credential: Credential) -> dict:
        with self.store.transaction(credential) as (_, actor):
            actor.require("read")
        registry = json.loads(Path("requirements_registry.json").read_text())
        requirements = registry["requirements"]
        return {"srs_version": registry["srs_version"], "source_hash": registry["source_hash"],
                "total": len(requirements), "counts": dict(Counter(r["status"] for r in requirements)),
                "requirements": [{k: r[k] for k in ("requirement_id", "source_anchor", "status",
                                     "owning_module", "implementation_refs", "test_refs",
                                     "acceptance_evidence")} for r in requirements]}

    def query(self, credential: Credential, query: str, params: tuple = ()) -> list[dict]:
        with self.store.transaction(credential) as (conn, actor):
            actor.require("read")
            return [exact_numbers(row) for row in conn.execute(query, params).fetchall()]

    def one(self, credential: Credential, query: str, params: tuple) -> dict:
        rows = self.query(credential, query, params)
        if not rows:
            raise DomainError("NOT_FOUND")
        return rows[0]

    def queues(self, credential: Credential) -> dict:
        return {"as_of": utcnow(), "queues": self.query(credential,
            "SELECT task_class,lane_class,status,count(*) AS count,min(created_at) AS oldest_at "
            "FROM tasks GROUP BY task_class,lane_class,status ORDER BY task_class,lane_class,status")}

    def activity(self, credential: Credential, *, run_id: str | None = None,
                 agent_id: str | None = None) -> list[dict]:
        query = ("SELECT r.run_id,r.task_id,r.parent_task_id,r.agent_role_id,r.worker_id,"
                 "r.task_class,r.status,r.started_at,r.heartbeat_at,r.completed_at,r.current_action,"
                 "r.expected_artifact_schema,r.expected_artifact_id,r.active_lease_id,r.priority,"
                 "r.retry_count,r.max_retries,r.timeout_sec,r.why_running,r.state_version,"
                 "l.expires_at AS lease_expires_at FROM active_task_runs r "
                 "LEFT JOIN resource_leases l ON l.lease_id=r.active_lease_id ")
        params: tuple = ()
        if run_id:
            query += "WHERE r.run_id=%s "
            params = (run_id,)
        elif agent_id:
            query += "WHERE r.worker_id=%s "
            params = (agent_id,)
        query += "ORDER BY r.created_at DESC LIMIT 200"
        now = utcnow()
        return [{**r, "activity_state": Scheduler.activity(r, now)}
                for r in self.query(credential, query, params)]

    def research_object(self, credential: Credential, object_id: str, kind: str) -> dict:
        return self.one(credential,
            "SELECT r.object_id,r.object_type,r.campaign_id,r.artifact_id,r.created_at,"
            "a.schema_name,a.content_hash,a.content FROM research_objects r "
            "JOIN artifacts a USING(artifact_id) WHERE object_id=%s AND object_type=%s "
            "AND a.classification<>'SEALED'", (object_id, kind))

    def lineage(self, credential: Credential, object_id: str) -> list[dict]:
        self.one(credential, "SELECT r.object_id FROM research_objects r JOIN artifacts a USING(artifact_id) "
                 "WHERE r.object_id=%s AND a.classification<>'SEALED'", (object_id,))
        return self.query(credential,
            "WITH RECURSIVE ancestors(id) AS (SELECT %s::text UNION SELECT l.parent_id "
            "FROM lineage_edges l JOIN ancestors a ON l.child_id=a.id) "
            "SELECT l.parent_id,l.child_id,l.edge_type FROM lineage_edges l "
            "JOIN ancestors x ON x.id=l.child_id "
            "JOIN research_objects p ON p.object_id=l.parent_id JOIN artifacts pa ON pa.artifact_id=p.artifact_id "
            "JOIN research_objects c ON c.object_id=l.child_id JOIN artifacts ca ON ca.artifact_id=c.artifact_id "
            "WHERE pa.classification<>'SEALED' AND ca.classification<>'SEALED' LIMIT 500", (object_id,))

    def paper_status(self, credential: Credential) -> dict:
        return {"real_money_execution": "PROHIBITED", "runs": self.query(credential,
            "SELECT paper_run_id,status,policy_version,reporting_currency,reconciled_at,created_at "
            "FROM paper_runs ORDER BY created_at DESC LIMIT 100"), "stops": self.query(credential,
            "SELECT emergency_stop_id,paper_run_id,scope_type,scope_id,reason_code,automatic,created_at "
            "FROM emergency_stop_events WHERE active ORDER BY created_at DESC LIMIT 100"),
            "safety_latches": self.query(credential, "SELECT safety_latch_id,scope_type,scope_id,"
                "reason_code,automatic,created_at FROM paper_safety_latches WHERE active "
                "ORDER BY created_at DESC LIMIT 100")}

    def statistical_capital(self, credential: Credential, campaign_id: str) -> dict:
        campaign = self.one(credential, "SELECT campaign_id,statistical_budget FROM campaigns WHERE campaign_id=%s",
                            (campaign_id,))
        rows = self.query(credential,
            "SELECT count(*) FILTER(WHERE NOT infrastructure_retry) AS scientific_trials,"
            "count(*) FILTER(WHERE infrastructure_retry) AS infrastructure_retries,"
            "count(DISTINCT trial_family_id) AS trial_families FROM trial_events WHERE campaign_id=%s",
            (campaign_id,))
        return {**campaign, **rows[0]}
