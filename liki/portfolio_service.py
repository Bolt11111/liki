"""Authenticated persistence for deterministic, research-only portfolio analysis."""

from __future__ import annotations

from decimal import Decimal
import json
from typing import Literal

from pydantic import Field, field_validator, model_validator

from liki.core import Contract, DomainError, canonical, content_hash
from liki.finance.types import decimal
from liki.portfolio import (
    AllocationConstraints, Attribution, CapitalState, PathSimulationConfig, PortfolioModel,
    PortfolioObservation, ReverseStressConfig, Scenario, StrategyDefinition, StrategyHealth,
    analyze_portfolio, simulate_ruin,
)
from liki.store import Credential, Store

__all__ = ["PortfolioEvaluationRequest", "PortfolioReadinessPacket", "PortfolioService"]


class PortfolioEvaluationRequest(Contract):
    portfolio_evaluation_id: str = Field(min_length=1)
    portfolio_candidate_id: str = Field(min_length=1)
    campaign_id: str = Field(min_length=1)
    trial_family_id: str = Field(min_length=1)
    portfolio_trial_id: str = Field(min_length=1)
    trial_kind: Literal["universe", "allocation", "sizing", "rebalance", "objective", "constraint", "validation", "forward_feedback"]
    operation_key: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    dataset_artifact_ids: tuple[str, ...] = Field(min_length=1)
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    strategies: tuple[StrategyDefinition, ...] = Field(min_length=2)
    observations: tuple[PortfolioObservation, ...] = Field(min_length=2)
    constraints: AllocationConstraints
    model: PortfolioModel
    equity: Decimal = Field(gt=0)
    scenarios: tuple[Scenario, ...] = ()
    attributions: tuple[Attribution, ...] = ()
    attribution_tolerance: Decimal = Field(ge=0)
    prior_weights: dict[str, Decimal] | None = None
    capital_state: CapitalState | None = None
    reverse_stress: ReverseStressConfig | None = None
    simulation: PathSimulationConfig | None = None

    @field_validator("equity", "attribution_tolerance", mode="before")
    @classmethod
    def parse_decimal(cls, value: object) -> Decimal:
        return decimal(value)  # type: ignore[arg-type]

    @field_validator("prior_weights", mode="before")
    @classmethod
    def parse_prior_weights(cls, value: object) -> dict[str, Decimal] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise TypeError("prior_weights must be keyed by strategy version id")
        return {str(key): decimal(item) for key, item in value.items()}

    @model_validator(mode="after")
    def unique_identifiers(self) -> PortfolioEvaluationRequest:
        strategy_ids = [item.strategy_version_id for item in self.strategies]
        if len(strategy_ids) != len(set(strategy_ids)):
            raise ValueError("strategy version ids must be unique")
        if len({item.scenario_id for item in self.scenarios}) != len(self.scenarios):
            raise ValueError("scenario ids must be unique")
        if self.prior_weights is not None and set(self.prior_weights) != set(strategy_ids):
            raise ValueError("prior weights must cover exactly the strategy universe")
        return self


class PortfolioReadinessPacket(Contract):
    portfolio_readiness_packet_id: str = Field(min_length=1)
    portfolio_evaluation_id: str = Field(min_length=1)
    operation_key: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    lineage_artifact_id: str = Field(min_length=1)
    code_data_evaluator_artifact_ids: tuple[str, ...] = Field(min_length=1)
    statistical_limitations_artifact_id: str = Field(min_length=1)
    sealed_history_artifact_id: str = Field(min_length=1)
    forward_paper_artifact_id: str = Field(min_length=1)
    portfolio_contribution_artifact_id: str = Field(min_length=1)
    tail_and_ruin_artifact_id: str = Field(min_length=1)
    capacity_liquidity_artifact_id: str = Field(min_length=1)
    model_risks_artifact_id: str = Field(min_length=1)
    failure_reasons_artifact_id: str = Field(min_length=1)
    effective_independent_opportunity_count: int = Field(ge=1)

    def artifact_ids(self) -> tuple[str, ...]:
        return (
            self.lineage_artifact_id, *self.code_data_evaluator_artifact_ids, self.statistical_limitations_artifact_id,
            self.sealed_history_artifact_id, self.forward_paper_artifact_id, self.portfolio_contribution_artifact_id,
            self.tail_and_ruin_artifact_id, self.capacity_liquidity_artifact_id, self.model_risks_artifact_id,
            self.failure_reasons_artifact_id,
        )


class PortfolioService:
    """Stores reproducible analysis artifacts. There is deliberately no execution adapter or order API."""

    def __init__(self, store: Store):
        self.store = store

    @staticmethod
    def _previous_operation(conn: object, operation_key: str, aggregate_id: str) -> dict | None:
        event = conn.execute("SELECT * FROM event_log WHERE operation_key=%s", (operation_key,)).fetchone()  # type: ignore[attr-defined]
        if event is None:
            return None
        if event["aggregate_id"] != aggregate_id:
            raise DomainError("IDEMPOTENCY_CONFLICT")
        return event

    @staticmethod
    def _artifact_ids(request: PortfolioEvaluationRequest) -> tuple[str, ...]:
        capital_artifact = () if request.capital_state is None else (request.capital_state.valuation_artifact_id,)
        return (*request.dataset_artifact_ids, *capital_artifact)

    @staticmethod
    def _analysis_content(request: PortfolioEvaluationRequest) -> dict:
        analysis = analyze_portfolio(
            request.strategies, request.observations, request.constraints, request.model, request.equity,
            request.scenarios, request.attributions, request.attribution_tolerance, request.prior_weights,
            request.capital_state, request.reverse_stress,
        )
        content = {
            "schema_version": "portfolio-analysis-v1", "execution_mode": "RESEARCH_ONLY",
            "input": request.model_dump(mode="json", exclude={"operation_key", "portfolio_trial_id", "evidence_ids"}),
            "allocation": {"method": analysis.allocation.method.value, "weights": analysis.allocation.weights, "variance": analysis.allocation.variance},
            "simple_challenger": {"method": analysis.challenger.method.value, "weights": analysis.challenger.weights, "variance": analysis.challenger.variance},
            "regularized_expected_returns": analysis.regularized_expected_returns,
            "risk": {
                "gross_exposure": analysis.risk.gross_exposure, "net_directional_exposure": analysis.risk.net_directional_exposure,
                "leverage": analysis.risk.leverage, "strategy_concentration": analysis.risk.strategy_concentration,
                "asset_concentration": analysis.risk.asset_concentration, "venue_concentration": analysis.risk.venue_concentration,
                "component_risk": analysis.risk.component_risk,
                "expected_shortfall": analysis.risk.expected_shortfall.model_dump(mode="json"),
                "maximum_drawdown": analysis.risk.maximum_drawdown.model_dump(mode="json"),
                "tail_co_movement": {key: value.model_dump(mode="json") for key, value in analysis.risk.tail_co_movement.items()},
                "correlation_instability": {key: value.model_dump(mode="json") for key, value in analysis.risk.correlation_instability.items()},
                "liquidity_at_risk": analysis.risk.liquidity_at_risk, "capacity_shortfall": analysis.risk.capacity_shortfall,
                "turnover": analysis.risk.turnover.model_dump(mode="json"),
                "common_driver_exposure": analysis.risk.common_driver_exposure,
                "capital_state": None if analysis.risk.capital_state is None else analysis.risk.capital_state.model_dump(mode="json"),
            },
            "scenarios": analysis.scenarios, "reverse_stress": analysis.reverse_stress,
            "attribution_residual": analysis.attribution_residual,
            "authoritative_performance": analysis.authoritative_performance,
        }
        if request.simulation is not None:
            content["risk_of_ruin"] = simulate_ruin(
                request.observations, [item.strategy_version_id for item in request.strategies],
                analysis.allocation.weights, request.simulation,
            ).model_dump(mode="json")
        # psycopg's Jsonb dumper does not encode Decimal; canonical JSON preserves exact decimal strings.
        return json.loads(canonical(content))

    def evaluate(self, credential: Credential, request: PortfolioEvaluationRequest) -> str:
        input_hash = content_hash(request.model_dump(mode="json"))
        with self.store.transaction(credential) as (conn, actor):
            actor.require("research")
            conn.execute("SELECT pg_advisory_xact_lock(71403218)")
            existing = self._previous_operation(conn, request.operation_key, request.portfolio_evaluation_id)
            if existing:
                if existing["metadata"].get("input_hash") != input_hash:
                    raise DomainError("IDEMPOTENCY_CONFLICT")
                return existing["metadata"]["state_after"]["result_artifact_id"]
            campaign = conn.execute("SELECT 1 FROM campaigns WHERE campaign_id=%s", (request.campaign_id,)).fetchone()
            candidate = conn.execute("SELECT * FROM research_objects WHERE object_id=%s", (request.portfolio_candidate_id,)).fetchone()
            if not campaign or not candidate or candidate["campaign_id"] != request.campaign_id or candidate["object_type"] != "portfolio_candidate":
                raise DomainError("INVALID_PORTFOLIO_LINEAGE")
            for strategy in request.strategies:
                row = conn.execute("SELECT * FROM research_objects WHERE object_id=%s", (strategy.strategy_version_id,)).fetchone()
                if not row or row["campaign_id"] != request.campaign_id or row["object_type"] != "strategy_version":
                    raise DomainError("INVALID_PORTFOLIO_STRATEGY_LINEAGE")
            for artifact_id in self._artifact_ids(request):
                self.store.artifact(conn, actor, artifact_id)
            for evidence_id in request.evidence_ids:
                if not conn.execute("SELECT 1 FROM evidence WHERE evidence_id=%s", (evidence_id,)).fetchone():
                    raise DomainError("UNKNOWN_EVIDENCE")
            existing_model = conn.execute("SELECT * FROM portfolio_models WHERE portfolio_model_id=%s", (request.model.model_id,)).fetchone()
            if existing_model and existing_model["version"] != request.model.version:
                raise DomainError("PORTFOLIO_MODEL_ID_REUSED")
            if existing_model:
                model_artifact_id = existing_model["record_artifact_id"]
            else:
                model_content = {
                    "schema_version": "portfolio-model-v1", "model": request.model.model_dump(mode="json"),
                    "execution_mode": "RESEARCH_ONLY",
                }
                model_artifact_id = self.store.put_artifact(
                    conn, actor, model_content, schema_name="portfolio/model/v1", classification="INTERNAL",
                    policy_version=request.policy_version,
                )
                model_event = self.store.transition(
                    conn, actor, capability="research", kind="portfolio_model", aggregate_id=request.model.model_id,
                    expected_version=0, state={"model_id": request.model.model_id, "version": request.model.version, "artifact_id": model_artifact_id},
                    event_type="PORTFOLIO_MODEL_REGISTERED", operation_key=f"portfolio-model:{request.model.model_id}:{request.model.version}",
                    task_id=request.campaign_id, policy_version=request.policy_version, artifact_ids=(model_artifact_id,),
                )
                conn.execute("INSERT INTO portfolio_models(portfolio_model_id,version,model_kind,record_artifact_id,created_by,event_id) VALUES(%s,%s,'allocation',%s,%s,%s)",
                             (request.model.model_id, request.model.version, model_artifact_id, actor.principal_id, model_event["event_id"]))
            content = self._analysis_content(request)
            result_artifact_id = self.store.put_artifact(conn, actor, content, schema_name="portfolio/analysis/v1", classification="INTERNAL", policy_version=request.policy_version)
            challenger_artifact_id = self.store.put_artifact(
                conn, actor, content["simple_challenger"], schema_name="portfolio/simple-challenger/v1", classification="INTERNAL", policy_version=request.policy_version,
            )
            configuration_artifact_id = self.store.put_artifact(
                conn, actor,
                {"schema_version": "portfolio-trial-v1", "trial_kind": request.trial_kind, "trial_family_id": request.trial_family_id,
                 "candidate_universe": [item.strategy_version_id for item in request.strategies], "configuration": request.model_dump(mode="json", exclude={"observations", "evidence_ids", "operation_key"})},
                schema_name="portfolio/trial/v1", classification="INTERNAL", policy_version=request.policy_version,
            )
            state = {"portfolio_evaluation_id": request.portfolio_evaluation_id, "portfolio_candidate_id": request.portfolio_candidate_id,
                     "campaign_id": request.campaign_id, "trial_family_id": request.trial_family_id, "result_artifact_id": result_artifact_id,
                     "execution_mode": "RESEARCH_ONLY"}
            event = self.store.transition(
                conn, actor, capability="research", kind="portfolio_evaluation", aggregate_id=request.portfolio_evaluation_id,
                expected_version=0, state=state, event_type="PORTFOLIO_EVALUATED", operation_key=request.operation_key,
                task_id=request.campaign_id, policy_version=request.policy_version, evidence_ids=request.evidence_ids,
                artifact_ids=(model_artifact_id, result_artifact_id, challenger_artifact_id, configuration_artifact_id, *self._artifact_ids(request)),
                metadata={"input_hash": input_hash}, topic="portfolio.evaluated",
            )
            conn.execute(
                "INSERT INTO portfolio_evaluations(portfolio_evaluation_id,portfolio_candidate_id,campaign_id,trial_family_id,allocator_model_id,dataset_artifact_ids,strategy_version_ids,execution_mode,result_artifact_id,challenger_artifact_id,event_id,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,'RESEARCH_ONLY',%s,%s,%s,%s)",
                (request.portfolio_evaluation_id, request.portfolio_candidate_id, request.campaign_id, request.trial_family_id,
                 request.model.model_id, list(request.dataset_artifact_ids), [item.strategy_version_id for item in request.strategies],
                 result_artifact_id, challenger_artifact_id, event["event_id"], actor.principal_id),
            )
            trial_event = self.store.transition(
                conn, actor, capability="research", kind="portfolio_trial", aggregate_id=request.portfolio_trial_id,
                expected_version=0, state={"portfolio_evaluation_id": request.portfolio_evaluation_id, "trial_family_id": request.trial_family_id,
                                           "trial_kind": request.trial_kind, "configuration_artifact_id": configuration_artifact_id},
                event_type="PORTFOLIO_TRIAL_RECORDED", operation_key=f"{request.operation_key}:trial", task_id=request.campaign_id,
                policy_version=request.policy_version, artifact_ids=(configuration_artifact_id,), metadata={"semantic_hash": content_hash(content["input"])},
            )
            conn.execute(
                "INSERT INTO portfolio_trials(portfolio_trial_id,portfolio_evaluation_id,trial_family_id,trial_kind,semantic_hash,configuration_artifact_id,event_id,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (request.portfolio_trial_id, request.portfolio_evaluation_id, request.trial_family_id, request.trial_kind,
                 content_hash(content["input"]), configuration_artifact_id, trial_event["event_id"], actor.principal_id),
            )
            return result_artifact_id

    def record_strategy_status(self, credential: Credential, evaluation_id: str, transition, operation_key: str, policy_version: str) -> str:
        """Append a monitoring state; reactivation is validated against fresh, predeclared evidence."""
        from liki.portfolio import StrategyStatusTransition

        if not isinstance(transition, StrategyStatusTransition):
            raise TypeError("transition must be a StrategyStatusTransition")
        with self.store.transaction(credential) as (conn, actor):
            actor.require("research")
            row = conn.execute("SELECT * FROM portfolio_evaluations WHERE portfolio_evaluation_id=%s", (evaluation_id,)).fetchone()
            if not row or transition.portfolio_id != evaluation_id or transition.strategy_version_id not in row["strategy_version_ids"]:
                raise DomainError("UNKNOWN_PORTFOLIO_STRATEGY")
            prior = conn.execute("SELECT state FROM portfolio_strategy_status_events WHERE portfolio_evaluation_id=%s AND strategy_version_id=%s ORDER BY created_at DESC LIMIT 1", (evaluation_id, transition.strategy_version_id)).fetchone()
            if prior and prior["state"] == "RETIRED" and transition.state != StrategyHealth.RETIRED:
                raise DomainError("RETIRED_STRATEGY_CANNOT_REACTIVATE")
            if prior and prior["state"] == "DORMANT" and transition.state == StrategyHealth.HEALTHY and (
                transition.predeclared_regime_rule_artifact_id is None or not transition.refreshed_evidence_ids
            ):
                raise DomainError("DORMANT_REACTIVATION_REQUIRES_RULE_AND_EVIDENCE")
            for evidence_id in transition.refreshed_evidence_ids:
                if not conn.execute("SELECT 1 FROM evidence WHERE evidence_id=%s", (evidence_id,)).fetchone():
                    raise DomainError("UNKNOWN_EVIDENCE")
            if transition.predeclared_regime_rule_artifact_id:
                self.store.artifact(conn, actor, transition.predeclared_regime_rule_artifact_id)
            status_id = f"{evaluation_id}:{transition.strategy_version_id}:{operation_key}"
            state = transition.model_dump(mode="json")
            event = self.store.transition(conn, actor, capability="research", kind="portfolio_strategy_monitor", aggregate_id=status_id,
                                          expected_version=0, state=state, event_type="PORTFOLIO_STRATEGY_STATUS_RECORDED",
                                          operation_key=operation_key, task_id=row["campaign_id"], policy_version=policy_version,
                                          evidence_ids=transition.refreshed_evidence_ids,
                                          artifact_ids=tuple(filter(None, (transition.predeclared_regime_rule_artifact_id,))))
            conn.execute("INSERT INTO portfolio_strategy_status_events(portfolio_strategy_status_event_id,portfolio_evaluation_id,strategy_version_id,state,reason,regime_rule_artifact_id,refreshed_evidence_ids,event_id,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(portfolio_strategy_status_event_id) DO NOTHING",
                         (status_id, evaluation_id, transition.strategy_version_id, transition.state.value, transition.reason,
                          transition.predeclared_regime_rule_artifact_id, list(transition.refreshed_evidence_ids), event["event_id"], actor.principal_id))
            return status_id

    def record_readiness_packet(self, credential: Credential, packet: PortfolioReadinessPacket) -> str:
        """Persist evidence readiness only; this cannot enable or submit real-money execution."""
        with self.store.transaction(credential) as (conn, actor):
            actor.require("research")
            evaluation = conn.execute("SELECT * FROM portfolio_evaluations WHERE portfolio_evaluation_id=%s", (packet.portfolio_evaluation_id,)).fetchone()
            if not evaluation:
                raise DomainError("UNKNOWN_PORTFOLIO_EVALUATION")
            prior = self._previous_operation(conn, packet.operation_key, packet.portfolio_readiness_packet_id)
            input_hash = content_hash(packet.model_dump(mode="json"))
            if prior:
                if prior["metadata"].get("input_hash") != input_hash:
                    raise DomainError("IDEMPOTENCY_CONFLICT")
                return prior["metadata"]["state_after"]["packet_artifact_id"]
            for artifact_id in packet.artifact_ids():
                self.store.artifact(conn, actor, artifact_id)
            content = {"schema_version": "portfolio-readiness-packet-v1", "execution_mode": "RESEARCH_ONLY", "packet": packet.model_dump(mode="json")}
            artifact_id = self.store.put_artifact(conn, actor, content, schema_name="portfolio/readiness-packet/v1", classification="INTERNAL", policy_version=packet.policy_version)
            event = self.store.transition(
                conn, actor, capability="research", kind="portfolio_readiness_packet", aggregate_id=packet.portfolio_readiness_packet_id,
                expected_version=0, state={"portfolio_evaluation_id": packet.portfolio_evaluation_id, "packet_artifact_id": artifact_id,
                                           "execution_mode": "RESEARCH_ONLY"}, event_type="PORTFOLIO_READINESS_PACKET_RECORDED",
                operation_key=packet.operation_key, task_id=evaluation["campaign_id"], policy_version=packet.policy_version,
                artifact_ids=(artifact_id, *packet.artifact_ids()), metadata={"input_hash": input_hash}, topic="portfolio.readiness",
            )
            conn.execute("INSERT INTO portfolio_readiness_packets(portfolio_readiness_packet_id,portfolio_evaluation_id,packet_artifact_id,execution_mode,event_id,created_by) VALUES(%s,%s,%s,'RESEARCH_ONLY',%s,%s)",
                         (packet.portfolio_readiness_packet_id, packet.portfolio_evaluation_id, artifact_id, event["event_id"], actor.principal_id))
            return artifact_id
