from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json

import pytest
from pydantic import ValidationError

from liki.governance import (
    ArtifactProvenance,
    AutomatedCheck,
    ChangeClass,
    GovernanceError,
    GovernanceProposal,
    GovernanceReview,
    Incident,
    IncidentSeverity,
    IncidentStatus,
    LifecycleEvidence,
    LabeledStressScenario,
    Materiality,
    ModelCard,
    ModelRecord,
    ModelStatus,
    ModelType,
    ModelValidation,
    OwnerDecision,
    OwnerDelivery,
    ProposalStatus,
    ReviewVerdict,
    SnapshotDependency,
    assess_model_admission,
    build_blind_packet,
    classify_proposal,
    evaluate_promotion,
    find_common_dependencies,
    load_governance_policy,
    run_counterfactual_replay,
    run_labeled_stress_comparison,
    transition_proposal,
)
from liki.governance.domain import (
    ApprovalSnapshot,
    ChangeSet,
    EvidenceReference,
    IndependenceProfile,
    MaterialObjection,
    ReplayEvent,
    transition_incident,
)


NOW = datetime(2026, 9, 6, tzinfo=UTC)


def digest(seed: int) -> str:
    return f"sha256:{seed:064x}"


def artifact(seed: int = 1, principal: str = "trusted-worker") -> ArtifactProvenance:
    return ArtifactProvenance(
        artifact_id=f"artifact-{seed}",
        content_hash=digest(seed),
        authenticated_principal=principal,
        environment_fingerprint=digest(900),
        code_fingerprint=digest(901),
    )


def snapshot(version: str = "1") -> ApprovalSnapshot:
    dependencies = (SnapshotDependency(scope="gate", version=version, content_hash=digest(11)),)
    body = {
        "dependencies": [item.model_dump(mode="json") for item in dependencies],
        "known_incident_ids": [],
        "evidence_hashes": [digest(12)],
    }
    content_hash = "sha256:" + sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    return ApprovalSnapshot(dependencies=dependencies, evidence_hashes=(digest(12),), snapshot_hash=content_hash)


def proposal(*, declared: ChangeClass = ChangeClass.GREEN, paths: tuple[str, ...] = ()) -> GovernanceProposal:
    return GovernanceProposal(
        proposal_id="proposal-1",
        proposal_version=1,
        authored_by="author",
        declared_class=declared,
        problem="A measured operational problem",
        proposed_change="Change a governed setting",
        affected_modules=("scheduler",),
        affected_paths=paths,
        evidence=(EvidenceReference(role="evidence", artifact=artifact(2)),),
        historical_replay_plan="Replay historical branch events",
        risk_if_changed="Could regress routing",
        risk_if_not_changed="Known waste continues",
        rollback_plan="Restore prior policy version",
        approval_snapshot=snapshot(),
        created_at=NOW,
        complete_evidence_at=NOW,
    )


def check(seed: int) -> AutomatedCheck:
    return AutomatedCheck(
        check_id=f"check-{seed}",
        check_kind="integration-test",
        result="PASS",
        result_artifact=artifact(seed),
        executed_at=NOW,
    )


def review(number: int, *, adversarial: bool = False, objection: MaterialObjection | None = None) -> GovernanceReview:
    return GovernanceReview(
        council_review_id=f"review-{number}",
        proposal_id="proposal-1",
        reviewer_principal=f"reviewer-{number}",
        profile=IndependenceProfile(
            provider_correlation_domain=f"provider-{number}",
            model_family=f"family-{number}",
            model_version="v1",
            reviewer_mandate="adversarial audit" if adversarial else "independent review",
            prompt_template_version=f"template-{number}",
            evidence_ordering=("primary", "counterevidence"),
            shared_tools_retrieval_policy="read-only-dossier",
            independence_group_id=f"group-{number}",
            fresh_context_id=f"context-{number}",
        ),
        evidence_manifest_hash=digest(30 + number),
        inspected_evidence=(artifact(100 + number),),
        verdict=ReviewVerdict.SUPPORT,
        material_objections=(objection,) if objection else (),
        created_at=NOW,
    )


def test_lawful_green_promotion_waits_for_delivered_24_hour_window() -> None:
    policy = load_governance_policy()
    item = proposal()
    classification = classify_proposal(item, policy, "classifier", NOW)
    reviews = tuple(review(number) for number in range(1, 4))
    lifecycle = LifecycleEvidence(tests=(check(41),))
    delivery = OwnerDelivery(
        authoritative_channel="owner-secure-channel",
        notification_id="notification-40",
        provider_message_id="telegram-40",
        delivered_at=NOW,
        lifecycle_snapshot_hash=lifecycle.snapshot_hash(),
    )

    assert evaluate_promotion(item, classification, reviews, lifecycle, snapshot(), NOW, owner_delivery=delivery) is ProposalStatus.READY
    assert (
        evaluate_promotion(
            item,
            classification,
            reviews,
            lifecycle,
            snapshot(),
            NOW + timedelta(hours=24),
            owner_delivery=delivery,
        )
        is ProposalStatus.PROMOTED
    )
    late_check = check(42).model_copy(update={"executed_at": NOW + timedelta(minutes=1)})
    assert (
        evaluate_promotion(
            item,
            classification,
            reviews,
            LifecycleEvidence(tests=(late_check,)),
            snapshot(),
            NOW + timedelta(hours=25),
            owner_delivery=delivery,
        )
        is ProposalStatus.READY
    )
    packet = build_blind_packet(item, classification)
    assert "authored_by" not in packet.model_fields_set
    assert "author" not in packet.model_dump_json()


def test_post_delivery_failure_freezes_and_revalidation_requires_a_new_delivery() -> None:
    policy = load_governance_policy()
    item = proposal()
    classification = classify_proposal(item, policy, "classifier", NOW)
    reviews = tuple(review(number) for number in range(1, 4))
    admitted = LifecycleEvidence(
        replay=(check(70),), tests=(check(71),), shadow=(check(72),), canary=(check(73),)
    )
    delivery = OwnerDelivery(
        authoritative_channel="owner-secure-channel",
        notification_id="notification-70",
        provider_message_id="telegram-70",
        delivered_at=NOW,
        lifecycle_snapshot_hash=admitted.snapshot_hash(),
    )
    regressed = LifecycleEvidence(
        replay=(check(70).model_copy(update={"executed_at": NOW + timedelta(minutes=1)}),),
        tests=(check(71),),
        shadow=(check(72),),
        canary=(check(73).model_copy(update={"result": "FAIL", "executed_at": NOW + timedelta(minutes=1)}),),
    )
    assert evaluate_promotion(item, classification, reviews, regressed, snapshot(), NOW + timedelta(hours=25), owner_delivery=delivery) is ProposalStatus.FROZEN

    revalidated = LifecycleEvidence(
        replay=(check(74).model_copy(update={"executed_at": NOW + timedelta(minutes=2)}),),
        tests=(check(75).model_copy(update={"executed_at": NOW + timedelta(minutes=2)}),),
        shadow=(check(76).model_copy(update={"executed_at": NOW + timedelta(minutes=2)}),),
        canary=(check(77).model_copy(update={"executed_at": NOW + timedelta(minutes=2)}),),
    )
    assert evaluate_promotion(item, classification, reviews, revalidated, snapshot(), NOW + timedelta(hours=48), owner_delivery=delivery) is ProposalStatus.READY


def test_protected_paths_and_real_money_cannot_be_downgraded_or_auto_promoted() -> None:
    policy = load_governance_policy()
    protected = proposal(paths=("liki/risk/limits.py",))
    classification = classify_proposal(protected, policy, "classifier", NOW)
    assert classification.deterministic_floor is ChangeClass.RED
    with pytest.raises(GovernanceError, match="sole severity classifier"):
        classify_proposal(protected, policy, "author", NOW)

    money = proposal()
    money = money.model_copy(update={"real_money_enablement": True})
    money_classification = classify_proposal(money, policy, "classifier", NOW)
    decisions = tuple(review(number, adversarial=number < 3) for number in range(1, 8))
    explicit_approval = OwnerDecision(
        proposal_id="proposal-1",
        owner_principal="owner",
        approved=True,
        decision_artifact=artifact(50),
        decided_at=NOW,
    )
    lifecycle = LifecycleEvidence(
        replay=(check(51),), tests=(check(52),), shadow=(check(53),), canary=(check(54),)
    )
    assert (
        evaluate_promotion(
            money,
            money_classification,
            decisions,
            lifecycle,
            snapshot(),
            NOW,
            owner_decision=explicit_approval,
        )
        is ProposalStatus.REJECTED
    )


def test_review_padding_unresolved_objections_incidents_and_stale_snapshots_fail_closed() -> None:
    policy = load_governance_policy()
    item = proposal()
    classification = classify_proposal(item, policy, "classifier", NOW)
    lifecycle = LifecycleEvidence(tests=(check(60),))
    delivery = OwnerDelivery(
        authoritative_channel="owner",
        notification_id="notification-61",
        provider_message_id="telegram-61",
        delivered_at=NOW,
        lifecycle_snapshot_hash=lifecycle.snapshot_hash(),
    )
    padded = (review(1), review(1), review(3))
    assert evaluate_promotion(item, classification, padded, lifecycle, snapshot(), NOW + timedelta(hours=25), owner_delivery=delivery) is ProposalStatus.REJECTED

    objection = MaterialObjection(objection_id="obj", statement="Need failure evidence")
    blocked = (review(1, objection=objection), review(2), review(3))
    assert evaluate_promotion(item, classification, blocked, lifecycle, snapshot(), NOW + timedelta(hours=25), owner_delivery=delivery) is ProposalStatus.REVIEWING

    incident = Incident(
        incident_id="incident-1",
        severity=IncidentSeverity.SEV1,
        status=IncidentStatus.OPEN,
        incident_type="control plane",
        opened_at=NOW,
        opened_by="operator",
        affected_modules=("scheduler",),
        evidence=(artifact(62),),
    )
    assert evaluate_promotion(item, classification, tuple(review(n) for n in range(1, 4)), lifecycle, snapshot(), NOW + timedelta(hours=25), owner_delivery=delivery, relevant_incidents=(incident,)) is ProposalStatus.FROZEN
    assert evaluate_promotion(item, classification, tuple(review(n) for n in range(1, 4)), lifecycle, snapshot("2"), NOW + timedelta(hours=25), owner_delivery=delivery) is ProposalStatus.STALE_APPROVAL


def test_immutable_contracts_replay_and_labeled_stress_reject_fake_inputs() -> None:
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        artifact()
        AutomatedCheck(check_id="bad", check_kind="test", result="PASS", result_artifact=artifact(), executed_at=datetime(2026, 1, 1))
    replay = run_counterfactual_replay(
        (
            ReplayEvent(branch_id="a", actual_decision="ADVANCE", counterfactual_decision="KILLED", later_outcome="LATE_DEATH", compute_cost_usd=3.0, statistical_capital=2.0, source_artifact=artifact(70)),
            ReplayEvent(branch_id="b", actual_decision="ADVANCE", counterfactual_decision="KILLED", later_outcome="WINNER", compute_cost_usd=5.0, statistical_capital=1.0, source_artifact=artifact(71)),
        )
    )
    assert (replay.killed_earlier, replay.later_winners_lost, replay.late_deaths_prevented, replay.compute_cost_saved_usd) == (2, 1, 1, 8.0)
    stress = run_labeled_stress_comparison(
        (
            LabeledStressScenario(scenario_id="ok", scenario_class="provider-outage", expected_decision="QUARANTINE", observed_decision="QUARANTINE", fixture_artifact=artifact(72)),
            LabeledStressScenario(scenario_id="bad", scenario_class="provider-outage", expected_decision="QUARANTINE", observed_decision="PROMOTE", fixture_artifact=artifact(73)),
        )
    )
    assert stress.mismatches == ("bad",)
    with pytest.raises(ValueError, match="requires at least one"):
        run_counterfactual_replay(())


def test_incident_and_model_risk_require_evidence_and_independence() -> None:
    open_incident = Incident(
        incident_id="i", severity=IncidentSeverity.SEV1, status=IncidentStatus.OPEN, incident_type="integrity", opened_at=NOW, opened_by="operator", affected_modules=("risk",), evidence=(artifact(80),)
    )
    contained = transition_incident(open_incident, IncidentStatus.CONTAINED, NOW)
    reconciling = transition_incident(contained, IncidentStatus.RECONCILING, NOW)
    resolved = transition_incident(reconciling, IncidentStatus.RESOLVED, NOW, reconciliation_evidence=(artifact(81),), root_cause_artifact=artifact(82), impact_assessment_artifact=artifact(83))
    closed = transition_incident(resolved, IncidentStatus.CLOSED, NOW, postmortem_artifact=artifact(84))
    assert closed.status is IncidentStatus.CLOSED

    card = ModelCard(card_artifact=artifact(85), purpose="risk", scope="portfolio", assumptions=("inputs valid",), limitations=("regime change",), dependencies=("market-data",))
    record = ModelRecord(
        model_id="risk-v1", model_type=ModelType.RISK, owner_role="risk", developer_principals=("developer",), developer_artifacts=(artifact(86),), purpose="risk", allowed_uses=("risk",), prohibited_uses=("orders",), materiality=Materiality.CRITICAL, inputs=("returns",), outputs=("limit",), assumptions=("stationary",), limitations=("tail uncertainty",), dependencies=("market-data", "covariance"), validation_status="pending", champion_challenger_status="challenger", monitoring_plan_id="monitor", version="v1", status=ModelStatus.DEVELOPMENT, development_evidence=(artifact(87),), model_card=card, created_at=NOW, updated_at=NOW
    )
    validation = ModelValidation(validation_id="validation", validator_principal="developer", validation_evidence=(artifact(88),), conceptual_soundness=check(89), implementation_correctness=check(90), sensitivity=check(91), monitoring_thresholds=("drift",), completed_at=NOW)
    assert not assess_model_admission(record, validation).admissible
    retired = record.model_copy(update={"status": ModelStatus.RETIRED, "retired_at": NOW})
    assert not assess_model_admission(retired, None).admissible
    peer = record.model_copy(update={"model_id": "risk-v2", "dependencies": ("market-data",)})
    assert find_common_dependencies((record, peer)) == {"market-data": ("risk-v1", "risk-v2")}


def test_proposal_lifecycle_is_serialized_and_cannot_promote_without_evaluation() -> None:
    item = proposal()
    classified = item.model_copy(update={"status": ProposalStatus.CLASSIFIED})
    transition = transition_proposal(item, 4, ProposalStatus.CLASSIFIED, "classifier", (artifact(95),), NOW)
    assert (transition.state_version_before, transition.state_version_after) == (4, 5)
    with pytest.raises(GovernanceError, match="invalid proposal transition"):
        transition_proposal(classified, 5, ProposalStatus.PROMOTED, "operator", (artifact(96),), NOW)
    ready = item.model_copy(update={"status": ProposalStatus.READY})
    with pytest.raises(GovernanceError, match="fresh deterministic"):
        transition_proposal(ready, 5, ProposalStatus.PROMOTED, "operator", (artifact(97),), NOW)
    assert transition_proposal(ready, 5, ProposalStatus.PROMOTED, "operator", (artifact(98),), NOW, promotion_evaluation=ProposalStatus.PROMOTED).state_after is ProposalStatus.PROMOTED


def test_amber_needs_adversarial_review_and_combined_change_set_needs_test_evidence() -> None:
    policy = load_governance_policy()
    item = proposal(declared=ChangeClass.AMBER)
    classification = classify_proposal(item, policy, "classifier", NOW)
    lifecycle = LifecycleEvidence(replay=(check(101),), tests=(check(102),), shadow=(check(103),), canary=(check(104),))
    assert evaluate_promotion(item, classification, tuple(review(n) for n in range(1, 6)), lifecycle, snapshot(), NOW) is ProposalStatus.REVIEWING
    with pytest.raises(ValidationError, match="interaction-test"):
        ChangeSet(change_set_id="set", proposal_ids=("proposal-1", "proposal-2"), dependencies=snapshot().dependencies, affected_scopes=("scheduler",), approval_snapshot_hash=snapshot().snapshot_hash, state="PROPOSED", created_at=NOW)
