from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from psycopg.types.json import Jsonb
from pydantic import Field

from liki.core import Contract, DomainError, content_hash, uid, utcnow
from liki.store import Credential, Store


class ResearchObject(Contract):
    object_id: str
    object_type: Literal["hypothesis","mechanism","strategy","strategy_version","branch","experiment","portfolio_candidate"]
    campaign_id: str
    artifact_id: str
    parents: dict[str, str] = Field(default_factory=dict)


class Trial(Contract):
    trial_event_id: str
    campaign_id: str
    trial_family_id: str
    strategy_version_id: str
    trial_type: Literal["hypothesis","parameter","mechanism","dataset","seed","nuisance","metric","window","universe","sizing","portfolio","campaign_extension","allocation","forward_feedback","stopping","system_change"]
    selection_reason: str = Field(min_length=1)
    semantic_configuration: dict
    dataset_snapshot_ids: tuple[str, ...]
    metric_ids: tuple[str, ...]
    contamination_tags: tuple[str, ...] = ()
    parent_trial_event_id: str | None = None
    scientific_retry_of: str | None = None
    infrastructure_retry: bool = False
    operation_key: str


class MemoryClaim(Contract):
    memory_id: str
    claim: str = Field(min_length=1)
    claim_type: Literal["finding","counterevidence","review_verdict","hypothesis","assumption"]
    source_evidence_ids: tuple[str, ...] = Field(min_length=1)
    confidence_state: Literal["unverified","candidate","replicated","invalidated"]
    market_scope: tuple[str, ...]
    mechanism_scope: tuple[str, ...]
    regime_scope: tuple[str, ...]
    last_revalidated_at: datetime
    policy_version: str
    contamination_tags: tuple[str, ...] = ()
    known_counterevidence_ids: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()


class Research:
    def __init__(self, store: Store):
        self.store = store

    def register(self, credential: Credential, obj: ResearchObject) -> str:
        with self.store.transaction(credential) as (conn, actor):
            actor.require("research")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            self.store.artifact(conn,actor,obj.artifact_id)
            for parent in obj.parents:
                if not conn.execute("SELECT 1 FROM research_objects WHERE object_id=%s AND campaign_id=%s",(parent,obj.campaign_id)).fetchone():
                    raise DomainError("UNKNOWN_LINEAGE_PARENT")
            event=self.store.transition(conn,actor,capability="research",kind="research_object",aggregate_id=obj.object_id,expected_version=0,
                state=obj.model_dump(mode="json"),event_type="RESEARCH_OBJECT_REGISTERED",operation_key="object:"+obj.object_id,task_id=obj.campaign_id,policy_version="research-v1",artifact_ids=(obj.artifact_id,))
            conn.execute("INSERT INTO research_objects VALUES(%s,%s,%s,%s,%s,now()) ON CONFLICT DO NOTHING",(obj.object_id,obj.object_type,obj.campaign_id,obj.artifact_id,actor.principal_id))
            for parent,edge in obj.parents.items():
                conn.execute("INSERT INTO lineage_edges VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",(parent,obj.object_id,edge))
                contamination=conn.execute("SELECT DISTINCT tag FROM memory_contamination_edges WHERE descendant_id=%s",(parent,)).fetchall()
                for tag in contamination:
                    conn.execute("INSERT INTO memory_contamination_edges VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",(parent,obj.object_id,tag["tag"],event["event_id"]))
            return obj.object_id

    def trial(self, credential: Credential, trial: Trial) -> str:
        semantic=content_hash({"configuration":trial.semantic_configuration,"datasets":trial.dataset_snapshot_ids,"metrics":trial.metric_ids,"type":trial.trial_type})
        with self.store.transaction(credential) as (conn,actor):
            actor.require("research")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            obj=conn.execute("SELECT * FROM research_objects WHERE object_id=%s",(trial.strategy_version_id,)).fetchone()
            if not obj or obj["campaign_id"]!=trial.campaign_id:
                raise DomainError("INVALID_TRIAL_LINEAGE")
            if trial.infrastructure_retry:
                original=conn.execute("SELECT * FROM trial_events WHERE trial_event_id=%s",(trial.scientific_retry_of,)).fetchone()
                if not original or original["semantic_hash"]!=semantic or original["trial_family_id"]!=trial.trial_family_id or original["strategy_version_id"]!=trial.strategy_version_id:
                    raise DomainError("SCIENTIFIC_CHANGE_IS_NOT_INFRASTRUCTURE_RETRY")
            elif trial.scientific_retry_of:
                raise DomainError("RETRY_CLASSIFICATION_REQUIRED")
            tags=set(trial.contamination_tags)
            tags.update(r["tag"] for r in conn.execute("SELECT tag FROM memory_contamination_edges WHERE descendant_id=%s",(trial.strategy_version_id,)))
            event=self.store.transition(conn,actor,capability="research",kind="trial",aggregate_id=trial.trial_event_id,expected_version=0,
                state={**trial.model_dump(mode="json"),"contamination_tags":sorted(tags)},event_type="TRIAL_RECORDED",operation_key=trial.operation_key,task_id=trial.campaign_id,policy_version="trial-v1")
            conn.execute("INSERT INTO trial_events(trial_event_id,campaign_id,trial_family_id,strategy_version_id,parent_trial_event_id,trial_type,selection_reason,dataset_snapshot_ids,metric_ids,started_at,scientific_retry_of,infrastructure_retry,contamination_tags,metadata_json,operation_key,semantic_hash,event_id) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(operation_key) DO NOTHING",
                (trial.trial_event_id,trial.campaign_id,trial.trial_family_id,trial.strategy_version_id,trial.parent_trial_event_id,trial.trial_type,trial.selection_reason,list(trial.dataset_snapshot_ids),list(trial.metric_ids),trial.scientific_retry_of,trial.infrastructure_retry,sorted(tags),Jsonb(trial.semantic_configuration),trial.operation_key,semantic,event["event_id"]))
            return trial.trial_event_id

    def trial_summary(self, credential: Credential, family_id: str) -> dict:
        with self.store.transaction(credential) as (conn,actor):
            actor.require("read")
            rows=conn.execute("SELECT * FROM trial_events WHERE trial_family_id=%s ORDER BY started_at",(family_id,)).fetchall()
            campaign_ids=list({r["campaign_id"] for r in rows})
            campaign_count=conn.execute("SELECT count(*) AS n FROM trial_events WHERE campaign_id=ANY(%s) AND NOT infrastructure_retry",(campaign_ids,)).fetchone()
            assert campaign_count is not None
            campaign_trials=campaign_count["n"]
            return {"family_id":family_id,"raw_adaptive_trials":sum(not r["infrastructure_retry"] for r in rows),"campaign_trials":campaign_trials,"effective_trials":{"status":"NOT_ESTIMATED","reason":"raw conservative history retained"},"trial_event_ids":[r["trial_event_id"] for r in rows],"events":rows}

    def remember(self, credential: Credential, claim: MemoryClaim) -> str:
        if claim.last_revalidated_at.tzinfo is None or claim.last_revalidated_at>utcnow():
            raise DomainError("INVALID_MEMORY_TIMESTAMP")
        with self.store.transaction(credential) as (conn,actor):
            actor.require("research")
            evidence=[]
            for eid in claim.source_evidence_ids+claim.known_counterevidence_ids:
                row=conn.execute("SELECT * FROM evidence WHERE evidence_id=%s",(eid,)).fetchone()
                if not row:
                    raise DomainError("UNKNOWN_EVIDENCE")
                self.store.artifact(conn,actor,row["artifact_id"])
                evidence.append(row)
            if claim.confidence_state=="replicated" and not any(e["evidence_class"]=="independent_reproduction" for e in evidence):
                raise DomainError("REPLICATION_EVIDENCE_REQUIRED")
            tags=set(claim.contamination_tags)
            for item in evidence:
                tags.update(item["contamination_tags"])
            self.store.transition(conn,actor,capability="research",kind="memory",aggregate_id=claim.memory_id,expected_version=0,
                state={**claim.model_dump(mode="json"),"contamination_tags":sorted(tags)},event_type="MEMORY_RECORDED",operation_key="memory:"+claim.memory_id,task_id=claim.memory_id,policy_version=claim.policy_version,evidence_ids=claim.source_evidence_ids+claim.known_counterevidence_ids)
            conn.execute("INSERT INTO memory_claims(memory_id,claim,claim_type,source_evidence_ids,confidence_state,market_scope,mechanism_scope,regime_scope,last_revalidated_at,policy_version,contamination_tags,known_counterevidence_ids,supersedes,created_by) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (claim.memory_id,claim.claim,claim.claim_type,list(claim.source_evidence_ids),claim.confidence_state,list(claim.market_scope),list(claim.mechanism_scope),list(claim.regime_scope),claim.last_revalidated_at,claim.policy_version,sorted(tags),list(claim.known_counterevidence_ids),list(claim.supersedes),actor.principal_id))
            return claim.memory_id

    def retrieve(self, credential: Credential, *, market: str, mechanism: str, independent_review: bool, max_age_seconds: int) -> list[dict]:
        if max_age_seconds<=0:
            raise DomainError("MEMORY_AGE_POLICY_REQUIRED")
        with self.store.transaction(credential) as (conn,actor):
            actor.require("read")
            rows=conn.execute("SELECT * FROM memory_claims WHERE %s=ANY(market_scope) AND %s=ANY(mechanism_scope) AND confidence_state<>'invalidated' "
                "AND NOT EXISTS(SELECT 1 FROM memory_claims n WHERE memory_claims.memory_id=ANY(n.supersedes)) ORDER BY last_revalidated_at DESC LIMIT 100",(market,mechanism)).fetchall()
            result=[]
            for row in rows:
                if any(tag in row["contamination_tags"] for tag in ("saw_sealed_category","saw_guard_holdout")):
                    continue
                if independent_review and (row["claim_type"]=="review_verdict" or "same_model_review" in row["contamination_tags"]):
                    continue
                age=(utcnow()-row["last_revalidated_at"]).total_seconds()
                result.append({**row,"retrieval_weight":str(max(Decimal(0),Decimal(1)-Decimal(str(age))/Decimal(max_age_seconds))),"stale":age>max_age_seconds})
            return result

    def sealed_result(self, credential: Credential, *, holdout_id: str, strategy_version_id: str,
                      family_id: str, request_hash: str, category: Literal["PASS","BORDERLINE","FAIL"]) -> dict:
        with self.store.transaction(credential) as (conn,actor):
            actor.require("sealed")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            old=conn.execute("SELECT * FROM holdout_query_events WHERE holdout_id=%s AND strategy_version_id=%s",(holdout_id,strategy_version_id)).fetchone()
            if old:
                if (old["request_hash"]!=request_hash or old["trial_family_id"]!=family_id
                        or old["response_category"]!=category):
                    raise DomainError("IDEMPOTENCY_CONFLICT")
                return {"category":old["response_category"],"query_id":old["holdout_query_id"]}
            holdout=conn.execute("SELECT * FROM holdout_policies WHERE holdout_id=%s FOR UPDATE",(holdout_id,)).fetchone()
            obj=conn.execute("SELECT * FROM research_objects WHERE object_id=%s",(strategy_version_id,)).fetchone()
            if not holdout or not obj or holdout["retired"] or family_id not in holdout["allowed_family_ids"] or holdout["queries"]>=holdout["query_budget"]:
                raise DomainError("SEALED_EVALUATION_UNAVAILABLE")
            declared = conn.execute("SELECT 1 FROM trial_events WHERE strategy_version_id=%s "
                "AND campaign_id=%s AND trial_family_id=%s AND NOT infrastructure_retry",
                (strategy_version_id,obj["campaign_id"],family_id)).fetchone()
            if not declared:
                raise DomainError("SEALED_TRIAL_NOT_DECLARED")
            if conn.execute("SELECT 1 FROM holdout_query_events WHERE holdout_id=%s AND trial_family_id=%s",(holdout_id,family_id)).fetchone():
                raise DomainError("SEALED_FAMILY_ALREADY_EXPOSED")
            exposed = conn.execute(
                "WITH RECURSIVE roots(candidate,node) AS ("
                "SELECT %s::text,%s::text UNION SELECT strategy_version_id,strategy_version_id "
                "FROM holdout_query_events WHERE holdout_id=%s), "
                "ancestry(candidate,node) AS (SELECT candidate,node FROM roots UNION "
                "SELECT a.candidate,l.parent_id FROM ancestry a JOIN lineage_edges l ON l.child_id=a.node) "
                "SELECT 1 FROM ancestry current JOIN ancestry prior USING(node) "
                "WHERE current.candidate=%s AND prior.candidate<>%s LIMIT 1",
                (strategy_version_id,strategy_version_id,holdout_id,strategy_version_id,strategy_version_id),
            ).fetchone()
            if exposed:
                raise DomainError("SEALED_LINEAGE_ALREADY_EXPOSED")
            query_id=uid("HOLDOUT")
            state={"holdout_id":holdout_id,"strategy_version_id":strategy_version_id,"category":category}
            event=self.store.transition(conn,actor,capability="sealed",kind="holdout_query",aggregate_id=query_id,expected_version=0,state=state,event_type="SEALED_EXPOSURE",operation_key=f"sealed:{holdout_id}:{strategy_version_id}",task_id=obj["campaign_id"],policy_version=holdout["policy_version"])
            remaining=holdout["query_budget"]-holdout["queries"]
            conn.execute("INSERT INTO holdout_query_events(holdout_query_id,holdout_id,campaign_id,strategy_version_id,trial_family_id,request_hash,response_category,query_policy_version,response_granularity,budget_before,budget_after,researcher_exposure,event_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,%s)",
                (query_id,holdout_id,obj["campaign_id"],strategy_version_id,family_id,request_hash,category,holdout["policy_version"],holdout["output_granularity"],remaining,remaining-1,event["event_id"]))
            conn.execute("UPDATE holdout_policies SET queries=queries+1 WHERE holdout_id=%s",(holdout_id,))
            descendants=conn.execute("WITH RECURSIVE d(id) AS (SELECT %s::text UNION SELECT e.child_id FROM lineage_edges e JOIN d ON e.parent_id=d.id) SELECT id FROM d",(strategy_version_id,)).fetchall()
            for descendant in descendants:
                conn.execute("INSERT INTO memory_contamination_edges VALUES(%s,%s,'saw_sealed_category',%s) ON CONFLICT DO NOTHING",(query_id,descendant["id"],event["event_id"]))
            return {"category":category,"query_id":query_id}
