from datetime import UTC, datetime, timedelta

import pytest

from liki.core import DomainError, uid
from liki.governance import (
    AutomatedCheck,
    DriftObservation,
    Materiality,
    ModelCard,
    ModelRecord,
    ModelStatus,
    ModelType,
    ModelValidation,
)
from liki.governance_service import GovernanceService
from liki.model_risk_service import EffectiveChallenge, ModelRiskService
from tests.test_governance_service import provenance


NOW = datetime(2026, 9, 6, tzinfo=UTC)


def check(store, credentials, check_id, kind, result="PASS"):
    artifact = provenance(store, credentials["evaluator"], {
        "check_id": check_id, "check_kind": kind, "result": result, "executed_at_utc": NOW.isoformat(),
    }, "governance/automated-check-result/v1")
    return AutomatedCheck(check_id=check_id, check_kind=kind, result=result, result_artifact=artifact, executed_at=NOW)


def model(store, credentials):
    model_id = uid("cost-model")
    developer = provenance(store, credentials["governance"], {"source": "independent implementation"}, "model-risk/development/v1")
    card_artifact = provenance(store, credentials["governance"], {"card": "v1"}, "model-risk/card/v1")
    record_artifact = provenance(store, credentials["governance"], {"model_id": model_id, "version": "1"}, "governance/model-record/v1")
    record = ModelRecord(
        model_id=model_id, model_type=ModelType.COST, owner_role="governance", developer_principals=(developer.authenticated_principal,),
        developer_artifacts=(developer,), purpose="Estimate paper trading costs", allowed_uses=("paper",),
        prohibited_uses=("real money",), materiality=Materiality.MATERIAL, inputs=("book",), outputs=("cost",),
        assumptions=("liquidity is observable",), limitations=("tail events may differ",), dependencies=("venue-a",),
        validation_status="PENDING", champion_challenger_status="CHALLENGER", monitoring_plan_id="cost-monitor-v1",
        version="1", status=ModelStatus.SHADOW, development_evidence=(developer,),
        model_card=ModelCard(card_artifact=card_artifact, purpose="cost", scope="paper", assumptions=("liquidity",),
                             limitations=("tails",), dependencies=("venue-a",)), created_at=NOW, updated_at=NOW,
    )
    return record, record_artifact


def test_model_approval_requires_independent_effective_challenge_and_tracks_drift(store, credentials, database):
    governance = GovernanceService(store)
    risk = ModelRiskService(store)
    record, record_artifact = model(store, credentials)
    with store.transaction(credentials["governance"]) as (conn, actor):
        governance.register_model(conn, actor, record, record_artifact, uid("register"), "model-risk")

    evidence = provenance(store, credentials["evaluator"], {"validation": "independent"}, "model-risk/evidence/v1")
    validation_artifact = provenance(store, credentials["evaluator"], {"validation": "record"}, "governance/model-validation/v1")
    validation = ModelValidation(
        validation_id="validation-1", validator_principal="validator", validation_evidence=(evidence,),
        conceptual_soundness=check(store, credentials, "concept", "conceptual_soundness"),
        implementation_correctness=check(store, credentials, "implementation", "implementation_correctness"),
        sensitivity=check(store, credentials, "sensitivity", "sensitivity"), monitoring_thresholds=("cost error",), completed_at=NOW,
    )
    # The inventory developer is a separate authenticated governance principal in production.
    from liki.store import issue_credential
    validator_credential = issue_credential(database["test_owner_dsn"], "validator", "governance", duration=timedelta(hours=1))
    with store.transaction(validator_credential) as (conn, actor):
        governance.record_model_validation(conn, actor, record.model_id, validation, validation_artifact)

    challenge_artifact = provenance(store, credentials["evaluator"], {
        "challenge_id": "challenge-1", "model_id": record.model_id, "validation_id": validation.validation_id,
        "validator_principal": "validator",
    }, "model-risk/effective-challenge/v1")
    challenge = EffectiveChallenge(
        challenge_id="challenge-1", validation_id=validation.validation_id, challenger_model_id=None,
        challenge_artifact=challenge_artifact, validator_principal="validator", completed_at=NOW,
        checks=tuple(check(store, credentials, f"challenge-{kind}", kind) for kind in (
            "conceptual_soundness", "data_appropriateness", "implementation_correctness", "benchmark_challenger",
            "sensitivity", "outcome_analysis", "limitations_misuse",
        )),
    )
    with store.transaction(credentials["governance"]) as (conn, actor):
        risk.record_effective_challenge(conn, actor, record.model_id, challenge, uid("challenge"), "model-risk")
        approved = risk.approve(conn, actor, record.model_id, validation.validation_id, 2, uid("approve"), "model-risk")
        assert approved.status is ModelStatus.APPROVED
        assert conn.execute("SELECT count(*) AS count FROM model_evidence_links WHERE model_id=%s AND evidence_role='VALIDATION'", (record.model_id,)).fetchone()["count"] == 1
        assert risk.aggregate_dependencies(conn) == {}

    measurement = provenance(store, credentials["governance"], {"drift": 2.0}, "governance/drift-measurement/v1")
    observation = DriftObservation(observation_id="drift-1", drift_kind="outcome", measured_value=2.0, threshold=1.0,
                                   direction="ABOVE", measurement_artifact=measurement, observed_at=NOW)
    with store.transaction(credentials["governance"]) as (conn, actor):
        risk.record_drift(conn, actor, record.model_id, observation, 3, uid("drift"), "model-risk")
        assert conn.execute("SELECT status FROM model_inventory WHERE model_id=%s", (record.model_id,)).fetchone()["status"] == "WATCH"


def test_model_risk_rejects_recalibration_contamination_and_preserves_retirement(store, credentials):
    governance = GovernanceService(store)
    risk = ModelRiskService(store)
    record, record_artifact = model(store, credentials)
    with store.transaction(credentials["governance"]) as (conn, actor):
        governance.register_model(conn, actor, record, record_artifact, uid("register"), "model-risk")
    with store.transaction(credentials["governance"]) as (conn, actor):
        with pytest.raises(DomainError, match="ONLY_VALIDATION"):
            risk.link_evidence(conn, actor, record.model_id, record.development_evidence[0], "DEVELOPMENT_USED", uid("consumed"), "model-risk")
    retirement = provenance(store, credentials["governance"], {"reason": "superseded"}, "model-risk/retirement/v1")
    with store.transaction(credentials["governance"]) as (conn, actor):
        retired = risk.retire(conn, actor, record.model_id, retirement, 1, uid("retire"), "model-risk")
        assert retired.status is ModelStatus.RETIRED
        assert conn.execute("SELECT 1 FROM model_retirements WHERE model_id=%s", (record.model_id,)).fetchone()


def test_recalibration_reclassifies_prior_validation_evidence(store, credentials, database):
    governance = GovernanceService(store)
    risk = ModelRiskService(store)
    record, record_artifact = model(store, credentials)
    with store.transaction(credentials["governance"]) as (conn, actor):
        governance.register_model(conn, actor, record, record_artifact, uid("register"), "model-risk")
    validation_evidence = provenance(store, credentials["evaluator"], {"validation": "independent"}, "model-risk/evidence/v1")
    validation_artifact = provenance(store, credentials["evaluator"], {"validation": "record"}, "governance/model-validation/v1")
    validation = ModelValidation(
        validation_id=uid("validation"), validator_principal="validator", validation_evidence=(validation_evidence,),
        conceptual_soundness=check(store, credentials, "concept", "conceptual_soundness"),
        implementation_correctness=check(store, credentials, "implementation", "implementation_correctness"),
        sensitivity=check(store, credentials, "sensitivity", "sensitivity"), monitoring_thresholds=("cost error",), completed_at=NOW,
    )
    from liki.store import issue_credential
    validator_credential = issue_credential(database["test_owner_dsn"], "validator", "governance", duration=timedelta(hours=1))
    with store.transaction(validator_credential) as (conn, actor):
        governance.record_model_validation(conn, actor, record.model_id, validation, validation_artifact)
    challenge_artifact = provenance(store, credentials["evaluator"], {
        "challenge_id": "challenge-reclassify", "model_id": record.model_id,
        "validation_id": validation.validation_id, "validator_principal": "validator",
    }, "model-risk/effective-challenge/v1")
    challenge = EffectiveChallenge(
        challenge_id="challenge-reclassify", validation_id=validation.validation_id, challenger_model_id=None,
        challenge_artifact=challenge_artifact, validator_principal="validator", completed_at=NOW,
        checks=tuple(check(store, credentials, f"challenge-{kind}", kind) for kind in (
            "conceptual_soundness", "data_appropriateness", "implementation_correctness", "benchmark_challenger",
            "sensitivity", "outcome_analysis", "limitations_misuse",
        )),
    )
    with store.transaction(credentials["governance"]) as (conn, actor):
        risk.record_effective_challenge(conn, actor, record.model_id, challenge, uid("challenge"), "model-risk")
        risk.approve(conn, actor, record.model_id, validation.validation_id, 2, uid("approve"), "model-risk")
        recalibrated = risk.link_evidence(conn, actor, record.model_id, validation_evidence, "DEVELOPMENT_USED", uid("consume"), "model-risk")
        assert validation_evidence not in recalibrated.validation_evidence
        assert validation_evidence in recalibrated.recalibration_consumed_evidence
        roles = conn.execute("SELECT evidence_role FROM model_evidence_links WHERE model_id=%s AND artifact_id=%s ORDER BY evidence_role", (record.model_id, validation_evidence.artifact_id)).fetchall()
        assert [row["evidence_role"] for row in roles] == ["DEVELOPMENT_USED", "VALIDATION"]
