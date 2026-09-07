from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from psycopg.types.json import Jsonb
from pydantic import Field

from liki.core import Contract, DomainError, content_hash, uid, utcnow
from liki.store import Credential, Store

POLICY = json.loads(Path("config/runtime_policy.json").read_text())


class Campaign(Contract):
    campaign_id: str
    purpose: str = Field(min_length=1)
    start_rule: str = Field(min_length=1)
    stopping_rule: str = Field(min_length=1)
    horizon_at: datetime
    usd_budget: Decimal = Field(ge=0)
    token_budget: int = Field(ge=0)
    compute_seconds_budget: Decimal = Field(ge=0)
    statistical_budget: int = Field(ge=0)


class Task(Contract):
    task_id: str
    campaign_id: str
    parent_task_id: str | None = None
    purpose: str = Field(min_length=1)
    expected_artifact_schema: str = Field(min_length=1)
    task_class: str
    lane_class: str
    handler: str
    inputs: dict
    budget_usd: Decimal = Field(ge=0)
    voi_lower_bound: Decimal
    novelty: Decimal = Field(ge=0, le=1)
    information_value: Decimal = Field(ge=0)
    max_retries: int = Field(ge=0)
    timeout_sec: int = Field(gt=0)
    independent_if_parent_fails: bool = False
    dependencies: tuple[str, ...] = ()


class Scheduler:
    def __init__(self, store: Store):
        self.store = store

    def campaign(self, credential: Credential, spec: Campaign) -> str:
        if spec.horizon_at.tzinfo is None or spec.horizon_at <= utcnow():
            raise DomainError("INVALID_CAMPAIGN_HORIZON")
        with self.store.transaction(credential) as (conn, actor):
            event = self.store.transition(conn, actor, capability="research", kind="campaign",
                aggregate_id=spec.campaign_id, expected_version=0, state=spec.model_dump(mode="json"),
                event_type="CAMPAIGN_DECLARED", operation_key="campaign:"+spec.campaign_id,
                task_id=spec.campaign_id, policy_version=POLICY["policy_id"])
            conn.execute("INSERT INTO campaigns(campaign_id,purpose,start_rule,stopping_rule,horizon_at,usd_budget,token_budget,compute_seconds_budget,statistical_budget,created_by) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (spec.campaign_id,spec.purpose,spec.start_rule,spec.stopping_rule,spec.horizon_at,spec.usd_budget,spec.token_budget,spec.compute_seconds_budget,spec.statistical_budget,actor.principal_id))
            return event["aggregate_id"]

    def enqueue(self, credential: Credential, task: Task) -> str:
        if task.task_class not in POLICY["class_limits"]:
            raise DomainError("UNKNOWN_RESOURCE_CLASS")
        if task.lane_class not in {"EXPLOIT","ALTERNATIVE","NOVELTY","FALSIFICATION","REPLICATION","DATA_QA","EXECUTION_QA","SYSTEM_QA","GOVERNANCE"}:
            raise DomainError("UNKNOWN_LANE_CLASS")
        if task.voi_lower_bound <= 0 and task.lane_class not in {"DATA_QA","EXECUTION_QA","SYSTEM_QA"}:
            raise DomainError("NO_POSITIVE_INFORMATION_VALUE")
        semantic = content_hash({"handler":task.handler,"inputs":task.inputs,"schema":task.expected_artifact_schema})
        with self.store.transaction(credential) as (conn, actor):
            actor.require("task")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            duplicate = conn.execute("SELECT task_id FROM tasks WHERE campaign_id=%s AND semantic_hash=%s", (task.campaign_id,semantic)).fetchone()
            if duplicate:
                return duplicate["task_id"]
            campaign = conn.execute("SELECT * FROM campaigns WHERE campaign_id=%s FOR UPDATE", (task.campaign_id,)).fetchone()
            if not campaign or campaign["horizon_at"] <= utcnow():
                raise DomainError("CAMPAIGN_UNAVAILABLE")
            if task.parent_task_id:
                parent = conn.execute("SELECT * FROM tasks WHERE task_id=%s FOR UPDATE", (task.parent_task_id,)).fetchone()
                if not parent or parent["campaign_id"] != task.campaign_id or parent["status"] in {"failed","killed","QUARANTINED"}:
                    raise DomainError("INVALID_PARENT")
                if parent["child_allocated_usd"] + task.budget_usd > parent["budget_usd"]:
                    raise DomainError("SUBTREE_BUDGET_EXHAUSTED")
                conn.execute("UPDATE tasks SET child_allocated_usd=child_allocated_usd+%s WHERE task_id=%s",(task.budget_usd,task.parent_task_id))
            else:
                if campaign["allocated_usd"]+task.budget_usd > campaign["usd_budget"]:
                    raise DomainError("CAMPAIGN_BUDGET_EXHAUSTED")
                conn.execute("UPDATE campaigns SET allocated_usd=allocated_usd+%s WHERE campaign_id=%s",(task.budget_usd,task.campaign_id))
            state = {**task.model_dump(mode="json"),"status":"queued"}
            self.store.transition(conn,actor,capability="task",kind="task",aggregate_id=task.task_id,
                expected_version=0,state=state,event_type="TASK_QUEUED",operation_key="task:"+task.task_id,
                task_id=task.task_id,policy_version=POLICY["policy_id"],topic="task.queued")
            conn.execute("INSERT INTO tasks(task_id,campaign_id,parent_task_id,semantic_hash,purpose,expected_artifact_schema,task_class,lane_class,handler,inputs,budget_usd,voi_lower_bound,novelty,information_value,max_retries,timeout_sec,status,independent_if_parent_fails,state_version) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'queued',%s,1)",
                (task.task_id,task.campaign_id,task.parent_task_id,semantic,task.purpose,task.expected_artifact_schema,task.task_class,task.lane_class,task.handler,Jsonb(task.inputs),task.budget_usd,task.voi_lower_bound,task.novelty,task.information_value,task.max_retries,task.timeout_sec,task.independent_if_parent_fails))
            for dependency in task.dependencies:
                target = conn.execute("SELECT campaign_id FROM tasks WHERE task_id=%s",(dependency,)).fetchone()
                if not target or target["campaign_id"] != task.campaign_id:
                    raise DomainError("INVALID_DEPENDENCY")
                conn.execute("INSERT INTO task_dependencies VALUES(%s,%s)",(task.task_id,dependency))
            return task.task_id

    def add_dependency(self, credential: Credential, task_id: str, dependency: str) -> None:
        with self.store.transaction(credential) as (conn, actor):
            actor.require("task")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            cycle = conn.execute("WITH RECURSIVE ancestors(id) AS (SELECT %s::text UNION SELECT d.depends_on FROM task_dependencies d JOIN ancestors a ON d.task_id=a.id) SELECT 1 FROM ancestors WHERE id=%s",(dependency,task_id)).fetchone()
            task = conn.execute("SELECT * FROM tasks WHERE task_id=%s",(task_id,)).fetchone()
            target = conn.execute("SELECT * FROM tasks WHERE task_id=%s",(dependency,)).fetchone()
            if cycle or not task or not target or task["campaign_id"]!=target["campaign_id"] or task["status"]!="queued":
                raise DomainError("INVALID_DEPENDENCY_DAG")
            state = self.store.state(conn,"task",task_id)
            if state is None:
                raise DomainError("TASK_PROJECTION_MISSING")
            self.store.transition(conn,actor,capability="task",kind="task",aggregate_id=task_id,expected_version=state["version"],
                state={**state["state"],"dependencies":sorted(set(state["state"].get("dependencies",[])+[dependency]))},event_type="TASK_DEPENDENCY_ADDED",operation_key=f"dependency:{task_id}:{dependency}",task_id=task_id,policy_version=POLICY["policy_id"])
            conn.execute("INSERT INTO task_dependencies VALUES(%s,%s) ON CONFLICT DO NOTHING",(task_id,dependency))

    def claim(self, credential: Credential, task_class: str) -> dict | None:
        with self.store.transaction(credential) as (conn, actor):
            actor.require("task")
            if actor.role != "scheduler":
                raise DomainError("WORKER_AUTHORITY_REQUIRED")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            now = utcnow()
            running_row = conn.execute("SELECT count(*) AS n FROM resource_leases WHERE released_at IS NULL AND expires_at>%s AND resource_class=%s",(now,task_class)).fetchone()
            assert running_row is not None
            running = running_row["n"]
            if running >= POLICY["class_limits"].get(task_class,0):
                return None
            candidates = conn.execute("SELECT t.* FROM tasks t JOIN campaigns c USING(campaign_id) WHERE t.status IN ('queued','hibernating') AND t.available_at<=%s AND c.horizon_at>%s AND t.task_class=%s "
                "AND NOT EXISTS(SELECT 1 FROM task_dependencies d JOIN tasks p ON p.task_id=d.depends_on WHERE d.task_id=t.task_id AND p.status<>'completed') "
                "AND (t.parent_task_id IS NULL OR t.independent_if_parent_fails OR EXISTS(SELECT 1 FROM tasks p WHERE p.task_id=t.parent_task_id AND p.status NOT IN ('failed','killed','QUARANTINED'))) ORDER BY t.created_at LIMIT 100",(now,now,task_class)).fetchall()
            if not candidates:
                return None
            # Protect novelty and replication before ranking remaining useful work.
            lane_counts = conn.execute("SELECT t.lane_class,count(*) AS n FROM active_task_runs r JOIN tasks t USING(task_id) GROUP BY t.lane_class").fetchall()
            counts = {r["lane_class"]:r["n"] for r in lane_counts}
            total = sum(counts.values())
            novelty_due = Decimal(counts.get("NOVELTY",0)) < Decimal(str(POLICY["exploration_floor"])) * Decimal(total+1)
            protected = [t for t in candidates if t["lane_class"]=="NOVELTY"] if novelty_due else []
            if not protected and not counts.get("REPLICATION",0):
                protected = [t for t in candidates if t["lane_class"]=="REPLICATION"]
            selected = max(protected or candidates,key=lambda t:(t["information_value"]/(t["budget_usd"]+Decimal(1)),(now-t["created_at"]).total_seconds(),t["novelty"]))
            run_id,lease_id,fence = uid("RUN"),uid("LEASE"),uid("FENCE")
            attempts_row = conn.execute("SELECT count(*) AS n FROM active_task_runs WHERE task_id=%s",(selected["task_id"],)).fetchone()
            assert attempts_row is not None
            attempts = attempts_row["n"]
            state = self.store.state(conn,"task",selected["task_id"])
            if state is None:
                raise DomainError("TASK_PROJECTION_MISSING")
            event = self.store.transition(conn,actor,capability="task",kind="task",aggregate_id=selected["task_id"],expected_version=state["version"],
                state={**state["state"],"status":"running","run_id":run_id},event_type="TASK_STARTED",operation_key="run:"+run_id,task_id=selected["task_id"],policy_version=POLICY["policy_id"])
            conn.execute("INSERT INTO active_task_runs(run_id,task_id,parent_task_id,agent_role_id,worker_id,task_class,status,started_at,heartbeat_at,current_action,expected_artifact_schema,active_lease_id,priority,retry_count,max_retries,timeout_sec,why_running,state_version,metadata_json) "
                "VALUES(%s,%s,%s,'deterministic_worker',%s,%s,'running',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s)",
                (run_id,selected["task_id"],selected["parent_task_id"],actor.principal_id,task_class,now,now,selected["handler"],selected["expected_artifact_schema"],lease_id,selected["information_value"],attempts,selected["max_retries"],selected["timeout_sec"],selected["purpose"],Jsonb({})))
            conn.execute("INSERT INTO resource_leases VALUES(%s,%s,%s,%s,%s,%s,NULL,%s)",(lease_id,run_id,actor.principal_id,fence,now+timedelta(seconds=selected["timeout_sec"]),now,task_class))
            conn.execute("UPDATE tasks SET status='running',state_version=%s WHERE task_id=%s",(event["aggregate_version"],selected["task_id"]))
            ids=[t["task_id"] for t in candidates]
            conn.execute("INSERT INTO allocator_decisions(allocation_id,candidate_task_ids,chosen_task_ids,excluded_json,features_json,displaced_task_ids,propensity_json,policy_version,exploration_reason,event_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (uid("ALLOC"),ids,[selected["task_id"]],Jsonb({}),Jsonb({t["task_id"]:{"voi":str(t["voi_lower_bound"]),"cost":str(t["budget_usd"])} for t in candidates}),[i for i in ids if i!=selected["task_id"]],Jsonb({"type":"deterministic","off_policy_inference":"NOT_APPLICABLE"}),POLICY["policy_id"],"protected" if protected else "value_of_information",event["event_id"]))
            return {**selected,"run_id":run_id,"fencing_token":fence,"lease_id":lease_id}

    def heartbeat(self, credential: Credential, run_id: str, fence: str) -> None:
        with self.store.transaction(credential) as (conn, actor):
            row=conn.execute("UPDATE resource_leases SET heartbeat_at=now() WHERE run_id=%s AND fencing_token=%s AND worker_id=%s AND released_at IS NULL AND expires_at>now() RETURNING lease_id",(run_id,fence,actor.principal_id)).fetchone()
            if not row:
                raise DomainError("STALE_LEASE")
            conn.execute("UPDATE active_task_runs SET heartbeat_at=now() WHERE run_id=%s AND status='running'",(run_id,))

    def finish(self, credential: Credential, run_id: str, fence: str, *, artifact_id: str | None, failure: str | None = None) -> str:
        with self.store.transaction(credential) as (conn, actor):
            actor.require("task")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            run=conn.execute("SELECT r.* FROM active_task_runs r JOIN resource_leases l USING(run_id) WHERE r.run_id=%s AND l.fencing_token=%s AND l.worker_id=%s AND l.released_at IS NULL AND l.expires_at>now() FOR UPDATE OF r",(run_id,fence,actor.principal_id)).fetchone()
            if not run:
                raise DomainError("STALE_LEASE")
            if not failure:
                if not artifact_id:
                    raise DomainError("EXPECTED_ARTIFACT_MISSING")
                artifact=self.store.artifact(conn,actor,artifact_id)
                if artifact["schema_name"]!=run["expected_artifact_schema"]:
                    raise DomainError("ARTIFACT_SCHEMA_MISMATCH")
            status="completed" if not failure else "QUARANTINED" if run["retry_count"]>=run["max_retries"] else "hibernating"
            state=self.store.state(conn,"task",run["task_id"])
            if state is None:
                raise DomainError("TASK_PROJECTION_MISSING")
            event=self.store.transition(conn,actor,capability="task",kind="task",aggregate_id=run["task_id"],expected_version=state["version"],state={**state["state"],"status":status,"failure":failure,"artifact_id":artifact_id},event_type="TASK_FINISHED",operation_key="finish:"+run_id,task_id=run["task_id"],policy_version=POLICY["policy_id"],artifact_ids=(artifact_id,) if artifact_id else ())
            conn.execute("UPDATE tasks SET status=%s,state_version=%s,available_at=now()+(%s*interval '1 second') WHERE task_id=%s",(status,event["aggregate_version"],run["timeout_sec"],run["task_id"]))
            conn.execute("UPDATE active_task_runs SET status=%s,completed_at=now(),expected_artifact_id=%s,kill_reason=%s WHERE run_id=%s",("completed" if not failure else "failed",artifact_id,failure,run_id))
            conn.execute("UPDATE resource_leases SET released_at=now() WHERE run_id=%s",(run_id,))
            return status

    def recover(self, credential: Credential) -> int:
        with self.store.transaction(credential) as (conn, actor):
            actor.require("task")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            rows=conn.execute("SELECT r.* FROM active_task_runs r JOIN resource_leases l USING(run_id) WHERE l.released_at IS NULL AND l.expires_at<=now()").fetchall()
            for run in rows:
                state=self.store.state(conn,"task",run["task_id"])
                if state is None:
                    raise DomainError("TASK_PROJECTION_MISSING")
                status="QUARANTINED" if run["retry_count"]>=run["max_retries"] else "queued"
                event=self.store.transition(conn,actor,capability="task",kind="task",aggregate_id=run["task_id"],expected_version=state["version"],state={**state["state"],"status":status,"failure":"LEASE_EXPIRED"},event_type="LEASE_EXPIRED",operation_key="expire:"+run["run_id"],task_id=run["task_id"],policy_version=POLICY["policy_id"])
                conn.execute("UPDATE tasks SET status=%s,state_version=%s WHERE task_id=%s",(status,event["aggregate_version"],run["task_id"]))
                conn.execute("UPDATE active_task_runs SET status='expired',completed_at=now() WHERE run_id=%s",(run["run_id"],))
                conn.execute("UPDATE resource_leases SET released_at=now() WHERE run_id=%s",(run["run_id"],))
            return len(rows)

    @staticmethod
    def activity(run: dict, now: datetime) -> str:
        if run["status"]!="running":
            return run["status"]
        threshold=max(POLICY["stale_heartbeat_min_seconds"],run["timeout_sec"]*float(POLICY["stale_heartbeat_timeout_fraction"]))
        if not run.get("active_lease_id") or not run.get("heartbeat_at") or (now-run["heartbeat_at"]).total_seconds()>threshold or (run.get("lease_expires_at") is not None and run["lease_expires_at"]<=now):
            return "STALE"
        return "Running"
