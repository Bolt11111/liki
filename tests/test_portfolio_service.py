from datetime import UTC, datetime, timedelta
import pytest

from liki.core import DomainError, uid
from liki.portfolio import AllocationConstraints, AllocationMethod, PortfolioModel, PortfolioObservation, StrategyDefinition, StrategyHealth, StrategyStatusTransition
from liki.portfolio_service import PortfolioEvaluationRequest, PortfolioReadinessPacket, PortfolioService


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _artifact(store, credential, content, schema="test/portfolio/v1"):
    with store.transaction(credential) as (conn, actor):
        return store.put_artifact(conn, actor, content, schema_name=schema, classification="INTERNAL", policy_version="test-v1")


def _portfolio_fixture(store, credentials):
    campaign_id, candidate_id, alpha_id, beta_id = uid("campaign"), uid("portfolio"), uid("strategy"), uid("strategy")
    source_artifact = _artifact(store, credentials["research"], {"portfolio-input": "authenticated"})
    with store.transaction(credentials["research"]) as (conn, actor):
        conn.execute("INSERT INTO campaigns(campaign_id,purpose,start_rule,stopping_rule,horizon_at,usd_budget,token_budget,compute_seconds_budget,statistical_budget,created_by) VALUES(%s,'test','manual','manual',%s,0,0,0,0,%s)", (campaign_id, NOW + timedelta(days=1), actor.principal_id))
        for object_id, object_type in ((candidate_id, "portfolio_candidate"), (alpha_id, "strategy_version"), (beta_id, "strategy_version")):
            conn.execute("INSERT INTO research_objects(object_id,object_type,campaign_id,artifact_id,created_by) VALUES(%s,%s,%s,%s,%s)", (object_id, object_type, campaign_id, source_artifact, actor.principal_id))
    evidence_artifact = _artifact(store, credentials["evaluator"], {"portfolio-evidence": "validated"})
    evidence_id = uid("evidence")
    with store.transaction(credentials["evaluator"]) as (conn, actor):
        conn.execute("INSERT INTO evidence(evidence_id,artifact_id,evidence_class,epistemic_label,role,available_at,contamination_tags,admitted_by) VALUES(%s,%s,'portfolio_input','DERIVED_VALUE','VALIDATION',now(),ARRAY[]::text[],%s)", (evidence_id, evidence_artifact, actor.principal_id))
    strategies = (
        StrategyDefinition(strategy_version_id=alpha_id, asset_id="BTC", venue_id="x", capacity_fraction="0.8", liquidity_stress_loss_fraction="0.1", net_directional_fraction="1"),
        StrategyDefinition(strategy_version_id=beta_id, asset_id="ETH", venue_id="y", capacity_fraction="0.8", liquidity_stress_loss_fraction="0.1", net_directional_fraction="-1"),
    )
    observations = tuple(PortfolioObservation(observed_at=NOW + timedelta(hours=index), simple_returns={alpha_id: left, beta_id: right}, regime="normal" if index < 3 else "stress") for index, (left, right) in enumerate((("0.02", "0.01"), ("-0.01", "-0.015"), ("0.01", "-0.002"), ("-0.03", "-0.04"), ("0.012", "0.004"), ("0.005", "0.002"))))
    request = PortfolioEvaluationRequest(portfolio_evaluation_id=uid("evaluation"), portfolio_candidate_id=candidate_id, campaign_id=campaign_id, trial_family_id=uid("family"), portfolio_trial_id=uid("trial"), trial_kind="allocation", operation_key=uid("operation"), policy_version="test-v1", dataset_artifact_ids=(source_artifact,), evidence_ids=(evidence_id,), strategies=strategies, observations=observations, constraints=AllocationConstraints(gross_target="0.8", max_strategy_weight="0.6", max_asset_fraction="0.6", max_venue_fraction="0.6", max_turnover_fraction="1", max_liquidity_fraction="0.8"), model=PortfolioModel(model_id=uid("model"), version="1", allocation_method=AllocationMethod.MINIMUM_VARIANCE, covariance_shrinkage="0.2", return_shrinkage="0.5", tail_confidence="0.8", assumptions=("synchronized returns",), limitations=("historical covariance can break",)), equity="1000", attribution_tolerance="0")
    return request, source_artifact, alpha_id


def test_evaluation_binds_authenticated_lineage_trial_and_research_only_mode(store, credentials):
    service = PortfolioService(store)
    request, _, _ = _portfolio_fixture(store, credentials)
    artifact_id = service.evaluate(credentials["research"], request)
    assert service.evaluate(credentials["research"], request) == artifact_id
    with store.transaction(credentials["auditor"]) as (conn, _):
        row = conn.execute("SELECT * FROM portfolio_evaluations WHERE portfolio_evaluation_id=%s", (request.portfolio_evaluation_id,)).fetchone()
        assert row["execution_mode"] == "RESEARCH_ONLY"
        assert row["result_artifact_id"] == artifact_id
        assert conn.execute("SELECT count(*) AS count FROM portfolio_trials WHERE portfolio_evaluation_id=%s", (request.portfolio_evaluation_id,)).fetchone()["count"] == 1
    with pytest.raises(DomainError, match="capability"):
        service.evaluate(credentials["evaluator"], request.model_copy(update={"portfolio_evaluation_id": uid("blocked"), "operation_key": uid("blocked"), "portfolio_trial_id": uid("blocked")}))


def test_dormant_reactivation_requires_fresh_predeclared_evidence_and_packet_never_enables_execution(store, credentials):
    service = PortfolioService(store)
    request, source_artifact, alpha_id = _portfolio_fixture(store, credentials)
    service.evaluate(credentials["research"], request)
    dormant = StrategyStatusTransition(portfolio_id=request.portfolio_evaluation_id, strategy_version_id=alpha_id, state=StrategyHealth.DORMANT, reason="regime absent")
    service.record_strategy_status(credentials["research"], request.portfolio_evaluation_id, dormant, uid("dormant"), "test-v1")
    healthy = StrategyStatusTransition(portfolio_id=request.portfolio_evaluation_id, strategy_version_id=alpha_id, state=StrategyHealth.HEALTHY, reason="regime returned")
    with pytest.raises(DomainError, match="DORMANT_REACTIVATION"):
        service.record_strategy_status(credentials["research"], request.portfolio_evaluation_id, healthy, uid("reactivate"), "test-v1")
    packet = PortfolioReadinessPacket(portfolio_readiness_packet_id=uid("packet"), portfolio_evaluation_id=request.portfolio_evaluation_id, operation_key=uid("packet-op"), policy_version="test-v1", lineage_artifact_id=source_artifact, code_data_evaluator_artifact_ids=(source_artifact,), statistical_limitations_artifact_id=source_artifact, sealed_history_artifact_id=source_artifact, forward_paper_artifact_id=source_artifact, portfolio_contribution_artifact_id=source_artifact, tail_and_ruin_artifact_id=source_artifact, capacity_liquidity_artifact_id=source_artifact, model_risks_artifact_id=source_artifact, failure_reasons_artifact_id=source_artifact, effective_independent_opportunity_count=1)
    artifact_id = service.record_readiness_packet(credentials["research"], packet)
    with store.transaction(credentials["auditor"]) as (conn, _):
        row = conn.execute("SELECT execution_mode,packet_artifact_id FROM portfolio_readiness_packets WHERE portfolio_readiness_packet_id=%s", (packet.portfolio_readiness_packet_id,)).fetchone()
        assert row == {"execution_mode": "RESEARCH_ONLY", "packet_artifact_id": artifact_id}
