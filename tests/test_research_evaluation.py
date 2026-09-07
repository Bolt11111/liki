from datetime import timedelta

import pytest

from liki.core import DomainError, uid, utcnow
from liki.evaluation import EVIDENCE_CLASSES, REQUIRED_CHECKS, EvaluationSnapshot, Evaluator, GateInput
from liki.research import Research, ResearchObject, Trial
from liki.scheduler import Scheduler
from tests.test_scheduler import campaign


def candidate(store,credentials):
    cid=campaign(Scheduler(store),credentials["research"])
    with store.transaction(credentials["research"]) as (conn,actor):
        aid=store.put_artifact(conn,actor,{"rule":"lagged-sign","version":uid("VERSION")},schema_name="strategy-v1",classification="INTERNAL",policy_version="v1")
        artifact=store.artifact(conn,actor,aid)
    obj=ResearchObject(object_id=uid("SV"),object_type="strategy_version",campaign_id=cid,artifact_id=aid)
    Research(store).register(credentials["research"],obj)
    return obj,artifact


def test_infrastructure_retry_cannot_hide_seed_or_metric_shopping(store,credentials):
    obj,_=candidate(store,credentials)
    research=Research(store)
    trial=Trial(trial_event_id=uid("TRIAL"),campaign_id=obj.campaign_id,trial_family_id=uid("FAMILY"),strategy_version_id=obj.object_id,trial_type="seed",selection_reason="predeclared",semantic_configuration={"seed":1},dataset_snapshot_ids=("dataset",),metric_ids=("net-pnl",),operation_key=uid("OP"))
    research.trial(credentials["research"],trial)
    retry=trial.model_copy(update={"trial_event_id":uid("TRIAL"),"operation_key":uid("OP"),"scientific_retry_of":trial.trial_event_id,"infrastructure_retry":True})
    research.trial(credentials["research"],retry)
    assert research.trial_summary(credentials["research"],trial.trial_family_id)["raw_adaptive_trials"]==1
    with pytest.raises(DomainError,match="SCIENTIFIC_CHANGE_IS_NOT"):
        research.trial(credentials["research"],retry.model_copy(update={"trial_event_id":uid("TRIAL"),"operation_key":uid("OP"),"semantic_configuration":{"seed":42}}))


def test_legacy_self_asserted_gate_reports_are_rejected(store,credentials):
    obj,artifact=candidate(store,credentials)
    evaluator=Evaluator(store)
    snapshot=EvaluationSnapshot(snapshot_id=uid("SNAP"),candidate_artifact_id=obj.artifact_id,candidate_hash=artifact["content_hash"],dataset_snapshot_ids=(obj.artifact_id,),feature_registry_version="v1",label_registry_version="v1",evaluator_version="v1",metric_versions={},gate_policy_versions={str(i):"v1" for i in range(14)},execution_model_version="v1",cost_model_version="v1",risk_model_version="v1",statistical_method_versions={},environment_fingerprint=store.fingerprint,inference_route_ids=(),rules_by_gate={},calibration_artifact_ids=(),minimum_forward_opportunities=10,forward_evaluation_at=utcnow()+timedelta(days=1))
    evaluator.snapshot(credentials["evaluator"],snapshot)
    def evidence(gate,checks):
        with store.transaction(credentials["evaluator"]) as (conn,actor):
            aid=store.put_artifact(conn,actor,{"snapshot_id":snapshot.snapshot_id,"checks":checks},schema_name="gate-report-v1",classification="INTERNAL",policy_version="v1")
            eid=uid("EVID")
            conn.execute("INSERT INTO evidence VALUES(%s,%s,%s,'DERIVED_VALUE','DEVELOPMENT',now(),'{}',%s,now())",(eid,aid,EVIDENCE_CLASSES[gate],actor.principal_id))
            return eid
    eid=evidence(0,{check:True for check in REQUIRED_CHECKS[0]})
    req=GateInput(strategy_version_id=obj.object_id,snapshot_id=snapshot.snapshot_id,gate_id=0,expected_version=0,evidence_ids=(eid,),metrics=(),operation_key=uid("OP"))
    with pytest.raises(DomainError,match="UNVERIFIED_GATE_EVIDENCE"):
        evaluator.gate(credentials["evaluator"],req)
    with store.transaction(credentials["auditor"]) as (conn,_):
        assert store.state(conn,"candidate",obj.object_id) is None
