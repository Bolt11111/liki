from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from psycopg.types.json import Jsonb
from pydantic import Field

from liki.core import Contract, DomainError, content_hash, uid, utcnow
from liki.store import Credential, Store
from liki.verification import verify_execution

STATES=("CONTRACTED","SCREENED","DATA_VALID","FEASIBLE","PROXY_SURVIVOR","BACKTESTED","ECONOMICALLY_VALIDATED","OOS_VALIDATED","STATISTICALLY_VALIDATED","ROBUSTNESS_VALIDATED","REPRODUCED","SEALED_VALIDATED","FORWARD_PAPER_VALIDATED","PORTFOLIO_READY")
EVIDENCE_CLASSES=("research_contract","duplicate_screen","data_integrity","feasibility","cheap_economics","backtest","execution_economics","out_of_sample","statistics","robustness","independent_reproduction","sealed_verdict","forward_paper","portfolio_risk")
REQUIRED_CHECKS=(
    ("measurable_objective","data_evaluator_defined","permitted_conduct","lineage_present"),
    ("not_duplicate","family_history_checked","cooldown_clear","no_known_invalidity"),
    ("point_in_time","fresh_complete_data","universe_survivorship","no_label_leakage"),
    ("falsifiable_prediction","empirical_or_mechanism_basis","constraints_defined"),
    ("sample_available","cost_bounds","capacity_feasible","benchmark_compared"),
    ("deterministic_replay","complete_order_ledger","dual_accounting","all_costs_explicit"),
    ("historical_fees","funding_borrow_known","fill_fidelity","capacity_stress","latency_constraints"),
    ("predeclared_split","no_tuning_leakage","purge_embargo","trial_history_complete"),
    ("method_applicable","ledger_multiplicity","dependence_accounted","uncertainty_reported"),
    ("parameter_neighborhood","cost_timing_perturbations","universe_sensitivity","no_slice_tuning"),
    ("independent_reproduction","blind_reviews","objections_resolved","ablation_or_attribution"),
    ("sealed_isolation","exposure_recorded","query_budget_valid","verdict_pass"),
    ("chronological_forward","opportunity_count","tca_reconciled","operational_reliability","cost_model_independence"),
    ("synchronized_portfolio","portfolio_multiplicity","tail_reverse_stress","liquidity_capacity","simple_challenger","later_confirmation"),
)


class MetricRule(Contract):
    metric_id: str
    metric_version: str
    unit: str
    lower: Decimal | None = None
    upper: Decimal | None = None
    tolerance: Decimal = Field(ge=0)


class MetricValue(Contract):
    metric_id: str
    metric_version: str
    unit: str
    status: Literal["VALUE","UNDEFINED","INSUFFICIENT_DATA","NUMERIC_ERROR","NOT_APPLICABLE"]
    value: Decimal | None
    reason: str


class EvaluationSnapshot(Contract):
    snapshot_id: str
    candidate_artifact_id: str
    candidate_hash: str
    dataset_snapshot_ids: tuple[str, ...] = Field(min_length=1)
    feature_registry_version: str
    label_registry_version: str
    evaluator_version: str
    metric_versions: dict[str,str]
    gate_policy_versions: dict[str,str]
    execution_model_version: str
    cost_model_version: str
    risk_model_version: str
    statistical_method_versions: dict[str,str]
    environment_fingerprint: str
    inference_route_ids: tuple[str,...]
    rules_by_gate: dict[str,tuple[MetricRule,...]]
    calibration_artifact_ids: tuple[str,...]
    minimum_forward_opportunities: int = Field(ge=1)
    forward_evaluation_at: datetime
    gate_input_artifact_ids: dict[str, tuple[str, ...]] = Field(default_factory=dict)


class GateInput(Contract):
    strategy_version_id: str
    snapshot_id: str
    gate_id: int = Field(ge=0,le=13)
    expected_version: int = Field(ge=0)
    evidence_ids: tuple[str,...] = Field(min_length=1)
    metrics: tuple[MetricValue,...]
    operation_key: str


class Evaluator:
    def __init__(self,store:Store):
        self.store=store

    def snapshot(self,credential:Credential,snapshot:EvaluationSnapshot)->str:
        if snapshot.forward_evaluation_at.tzinfo is None:
            raise DomainError("NAIVE_EVALUATION_TIME")
        if set(snapshot.gate_policy_versions)!=set(map(str,range(14))):
            raise DomainError("INCOMPLETE_GATE_POLICY_SET")
        if set(snapshot.gate_input_artifact_ids) - set(map(str,range(14))):
            raise DomainError("INVALID_GATE_INPUT_BINDING")
        with self.store.transaction(credential) as (conn,actor):
            actor.require("snapshot")
            candidate=self.store.artifact(conn,actor,snapshot.candidate_artifact_id)
            if candidate["content_hash"]!=snapshot.candidate_hash:
                raise DomainError("CANDIDATE_HASH_MISMATCH")
            for artifact_id in snapshot.calibration_artifact_ids:
                calibration=self.store.artifact(conn,actor,artifact_id)
                producer=conn.execute("SELECT role FROM principals WHERE principal_id=%s",(calibration["producer_id"],)).fetchone()
                if not producer or producer["role"] not in {"governance","evaluator"}:
                    raise DomainError("UNTRUSTED_CALIBRATION")
            if any(snapshot.rules_by_gate.values()) and not snapshot.calibration_artifact_ids:
                raise DomainError("UNCALIBRATED_NUMERIC_GATES")
            for artifact_id in snapshot.dataset_snapshot_ids:
                self.store.artifact(conn,actor,artifact_id)
            for artifact_ids in snapshot.gate_input_artifact_ids.values():
                for artifact_id in artifact_ids:
                    self.store.artifact(conn,actor,artifact_id)
            body=snapshot.model_dump(mode="json")
            self.store.transition(conn,actor,capability="snapshot",kind="snapshot",aggregate_id=snapshot.snapshot_id,expected_version=0,state=body,event_type="EVALUATION_PINNED",operation_key="snapshot:"+snapshot.snapshot_id,task_id=snapshot.snapshot_id,policy_version="evaluation-v1",artifact_ids=(snapshot.candidate_artifact_id,)+snapshot.calibration_artifact_ids)
            conn.execute("INSERT INTO evaluation_snapshots VALUES(%s,%s,%s,%s,now()) ON CONFLICT DO NOTHING",(snapshot.snapshot_id,content_hash(body),Jsonb(body),actor.principal_id))
            return snapshot.snapshot_id

    def gate(self,credential:Credential,request:GateInput)->dict:
        with self.store.transaction(credential) as (conn,actor):
            actor.require("gate")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            previous_operation=conn.execute("SELECT e.metadata,g.* FROM gate_decisions g JOIN event_log e USING(event_id) WHERE e.operation_key=%s",(request.operation_key,)).fetchone()
            if previous_operation:
                if previous_operation["metadata"].get("input_hash")!=content_hash(request.model_dump(mode="json")):
                    raise DomainError("IDEMPOTENCY_CONFLICT")
                return {"gate_decision_id":previous_operation["gate_decision_id"],**previous_operation["metadata"]["state_after"],"version":previous_operation["gate_state_version_after"]}
            snapshot_row=conn.execute("SELECT * FROM evaluation_snapshots WHERE snapshot_id=%s",(request.snapshot_id,)).fetchone()
            if not snapshot_row or conn.execute("SELECT 1 FROM snapshot_invalidations WHERE snapshot_id=%s",(request.snapshot_id,)).fetchone():
                raise DomainError("STALE_EVALUATION_SNAPSHOT")
            snapshot=EvaluationSnapshot.model_validate(snapshot_row["manifest"])
            from liki.reliability_service import ReliabilityService
            if ReliabilityService(self.store).promotion_blockers(conn):
                raise DomainError("PROMOTION_FROZEN")
            obj=conn.execute("SELECT * FROM research_objects WHERE object_id=%s",(request.strategy_version_id,)).fetchone()
            if not obj or obj["artifact_id"]!=snapshot.candidate_artifact_id:
                raise DomainError("CANDIDATE_SNAPSHOT_MISMATCH")
            if actor.principal_id == obj["created_by"]:
                raise DomainError("SELF_CERTIFICATION")
            previous=self.store.state(conn,"candidate",request.strategy_version_id)
            prior: dict[str, Any]=previous["state"] if previous else {"gate_id":-1,"status":"IDEA"}
            if previous and previous["version"]!=request.expected_version:
                raise DomainError("CONCURRENT_MODIFICATION")
            if prior["status"] in {"FAILED","BLOCKED","BORDERLINE_FRONTIER","SUSPENDED"} or request.gate_id!=prior["gate_id"]+1:
                raise DomainError("GATE_DEPENDENCY_UNSATISFIED")
            if previous and prior["snapshot_id"]!=request.snapshot_id:
                raise DomainError("EVALUATION_REENTRY_REQUIRED")
            evidence=[]
            artifacts=[]
            for eid in request.evidence_ids:
                row=conn.execute("SELECT * FROM evidence WHERE evidence_id=%s",(eid,)).fetchone()
                if not row:
                    raise DomainError("UNKNOWN_EVIDENCE")
                artifact=self.store.artifact(conn,actor,row["artifact_id"])
                producer=conn.execute("SELECT role FROM principals WHERE principal_id=%s",(artifact["producer_id"],)).fetchone()
                if not producer or producer["role"] not in {"evaluator","sealed_evaluator","data","paper"}:
                    raise DomainError("UNTRUSTED_GATE_EVIDENCE")
                if row["available_at"]>utcnow() or artifact["content"].get("snapshot_id")!=request.snapshot_id:
                    raise DomainError("EVIDENCE_SNAPSHOT_MISMATCH")
                verify_execution(self.store,conn,actor,artifact,request,snapshot_row)
                evidence.append(row)
                artifacts.append(artifact)
            if not any(e["evidence_class"]==EVIDENCE_CLASSES[request.gate_id] for e in evidence):
                raise DomainError("REQUIRED_EVIDENCE_CLASS_MISSING")
            decision,reason="PASS","REQUIRED_EVIDENCE_VALID"
            reports=[a["content"] for a,e in zip(artifacts,evidence,strict=True) if e["evidence_class"]==EVIDENCE_CLASSES[request.gate_id]]
            if any(not any(report.get("checks",{}).get(check) is True for report in reports) for check in REQUIRED_CHECKS[request.gate_id]):
                decision,reason="BLOCKED","MANDATORY_DETERMINISTIC_CHECK_MISSING"
            if any(a["content"].get("hard_invalidity") for a in artifacts):
                decision,reason="FAIL","HARD_INVALIDITY"
            elif any(a["content"].get("unknowns") for a in artifacts):
                decision,reason="BLOCKED","MATERIAL_UNKNOWNS"
            elif request.gate_id>=7 and all(e["role"]=="SYNTHETIC" for e in evidence):
                decision,reason="BLOCKED","SYNTHETIC_EVIDENCE_CEILING"
            if request.gate_id>=10 and any(a["producer_id"]==obj["created_by"] for a in artifacts):
                decision,reason="BLOCKED","SELF_CERTIFICATION"
            if request.gate_id==11 and not any(e["evidence_class"]=="sealed_verdict" and e["role"]=="SEALED" for e in evidence):
                decision,reason="BLOCKED","SEALED_PROTOCOL_REQUIRED"
            if request.gate_id==12:
                opportunities=max((a["content"].get("independent_opportunities",0) for a in artifacts),default=0)
                if snapshot.forward_evaluation_at>utcnow() or opportunities<snapshot.minimum_forward_opportunities or not any(e["role"]=="FORWARD" for e in evidence):
                    decision,reason="BLOCKED","FORWARD_HORIZON_INCOMPLETE"
            values={m.metric_id:m for m in request.metrics}
            reported_values={m["metric_id"]:m for report in reports for m in report.get("metrics",[])}
            if len(values)!=len(request.metrics) or any(reported_values.get(m.metric_id)!=m.model_dump(mode="json") for m in request.metrics):
                decision,reason="BLOCKED","METRICS_NOT_BOUND_TO_EVIDENCE"
            for rule in snapshot.rules_by_gate.get(str(request.gate_id),()):
                metric=values.get(rule.metric_id)
                if metric is None or metric.status!="VALUE" or metric.value is None:
                    decision,reason="BLOCKED","REQUIRED_METRIC_UNDEFINED"
                    break
                if metric.metric_version!=rule.metric_version or metric.unit!=rule.unit:
                    decision,reason="BLOCKED","METRIC_CONTRACT_MISMATCH"
                    break
                if decision=="PASS" and ((rule.lower is not None and metric.value<rule.lower) or (rule.upper is not None and metric.value>rule.upper)):
                    decision,reason="FAIL","NUMERIC_CRITERION_FAILED"
                if decision=="PASS" and ((rule.lower is not None and abs(metric.value-rule.lower)<=rule.tolerance) or (rule.upper is not None and abs(metric.value-rule.upper)<=rule.tolerance)):
                    decision,reason="BORDERLINE","THRESHOLD_UNCERTAINTY"
            status=STATES[request.gate_id] if decision=="PASS" else {"FAIL":"FAILED","BLOCKED":"BLOCKED","BORDERLINE":"BORDERLINE_FRONTIER"}[decision]
            state={"strategy_version_id":request.strategy_version_id,"snapshot_id":request.snapshot_id,"gate_id":request.gate_id,"status":status,"decision":decision,"reason":reason}
            version=snapshot.gate_policy_versions[str(request.gate_id)]
            event=self.store.transition(conn,actor,capability="gate",kind="candidate",aggregate_id=request.strategy_version_id,expected_version=request.expected_version,state=state,event_type="GATE_DECISION",operation_key=request.operation_key,task_id=obj["campaign_id"],policy_version=version,evidence_ids=request.evidence_ids,artifact_ids=tuple(a["artifact_id"] for a in artifacts),metadata={"input_hash":content_hash(request.model_dump(mode="json"))})
            gid=uid("GATE")
            conn.execute("INSERT INTO gate_decisions(gate_decision_id,strategy_version_id,gate_id,snapshot_id,gate_version,gate_state_version_before,gate_state_version_after,state_before,state_after,decision,reason_code,decision_reason,actor_id,policy_version,evidence_ids,artifact_ids,metrics_json,event_id) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (gid,request.strategy_version_id,request.gate_id,request.snapshot_id,version,request.expected_version,request.expected_version+1,prior["status"],status,decision,reason,reason,actor.principal_id,version,list(request.evidence_ids),[a["artifact_id"] for a in artifacts],Jsonb([m.model_dump(mode="json") for m in request.metrics]),event["event_id"]))
            return {"gate_decision_id":gid,**state,"version":request.expected_version+1}
