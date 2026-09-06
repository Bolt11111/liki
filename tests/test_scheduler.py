from datetime import timedelta
from decimal import Decimal

import psycopg
import pytest

from liki.core import DomainError, uid, utcnow
from liki.scheduler import Campaign, Scheduler, Task


def campaign(scheduler,token,budget="10"):
    identifier=uid("CAM")
    scheduler.campaign(token,Campaign(campaign_id=identifier,purpose="Controlled research",start_rule="explicit",stopping_rule="fixed horizon",horizon_at=utcnow()+timedelta(days=1),usd_budget=Decimal(budget),token_budget=1000,compute_seconds_budget=60,statistical_budget=10))
    return identifier


def task(campaign_id,**changes):
    return Task(task_id=uid("TASK"),campaign_id=campaign_id,purpose="validate artifact",expected_artifact_schema="test-output-v1",task_class="maintenance",lane_class="SYSTEM_QA",handler="test",inputs={"nonce":uid("N")},budget_usd=Decimal(1),voi_lower_bound=Decimal(1),novelty=Decimal("0.2"),information_value=Decimal(1),max_retries=1,timeout_sec=60).model_copy(update=changes)


def test_budget_child_fanout_and_semantic_dedup(store,credentials):
    scheduler=Scheduler(store)
    cid=campaign(scheduler,credentials["research"])
    parent=task(cid,budget_usd=Decimal(2))
    scheduler.enqueue(credentials["research"],parent)
    assert scheduler.enqueue(credentials["research"],parent.model_copy(update={"task_id":uid("TASK"),"purpose":"renamed"}))==parent.task_id
    scheduler.enqueue(credentials["research"],task(cid,parent_task_id=parent.task_id,budget_usd=Decimal(2)))
    with pytest.raises(DomainError,match="SUBTREE_BUDGET_EXHAUSTED"):
        scheduler.enqueue(credentials["research"],task(cid,parent_task_id=parent.task_id))


def test_dependency_cycle_and_failed_parent_are_not_completion(store,credentials):
    scheduler=Scheduler(store)
    cid=campaign(scheduler,credentials["research"])
    a,b=task(cid),task(cid)
    scheduler.enqueue(credentials["research"],a)
    scheduler.enqueue(credentials["research"],b.model_copy(update={"dependencies":(a.task_id,)}))
    with pytest.raises(DomainError,match="INVALID_DEPENDENCY_DAG"):
        scheduler.add_dependency(credentials["research"],a.task_id,b.task_id)


def test_expired_owner_cannot_commit_and_task_quarantines(store,credentials,database):
    scheduler=Scheduler(store)
    cid=campaign(scheduler,credentials["research"])
    work=task(cid,max_retries=0,task_class="telegram")
    scheduler.enqueue(credentials["research"],work)
    claimed=scheduler.claim(credentials["scheduler"],"telegram")
    assert claimed is not None
    with psycopg.connect(database["test_owner_dsn"]) as conn:
        conn.execute("UPDATE resource_leases SET expires_at=now()-interval '1 second' WHERE run_id=%s",(claimed["run_id"],))
    assert scheduler.recover(credentials["scheduler"])>=1
    with pytest.raises(DomainError,match="STALE_LEASE"):
        scheduler.finish(credentials["scheduler"],claimed["run_id"],claimed["fencing_token"],artifact_id=None,failure="late")
    with store.transaction(credentials["auditor"]) as (conn,_):
        assert conn.execute("SELECT status FROM tasks WHERE task_id=%s",(claimed["task_id"],)).fetchone()["status"]=="QUARANTINED"


def test_activity_requires_fresh_lease_and_heartbeat():
    now=utcnow()
    run={"status":"running","active_lease_id":"lease","heartbeat_at":now-timedelta(seconds=31),"timeout_sec":60}
    assert Scheduler.activity(run,now)=="STALE"
    run["heartbeat_at"]=now
    assert Scheduler.activity(run,now)=="Running"
    run["lease_expires_at"]=now-timedelta(seconds=1)
    assert Scheduler.activity(run,now)=="STALE"
