"""Pure domain rules for governance, verification, incidents, and model risk.

Persistence is deliberately absent. Callers persist these immutable records in one
transaction and use their own compare-and-set aggregate version checks.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
import json
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

if TYPE_CHECKING:
    from .policy import GovernancePolicy


NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^(sha256:)?[0-9a-f]{64}$")]


class GovernanceError(ValueError):
    """Raised when a requested transition would violate a governance invariant."""


class ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return value
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError("timestamps must be UTC")
    return value


def _canonical_hash(value: object) -> str:
    def normalize(item: object) -> object:
        if isinstance(item, BaseModel):
            return normalize(item.model_dump(mode="json"))
        if isinstance(item, StrEnum):
            return item.value
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, dict):
            return {str(key): normalize(value) for key, value in item.items()}
        if isinstance(item, tuple | list):
            return [normalize(value) for value in item]
        return item

    return "sha256:" + sha256(
        json.dumps(normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


class ChangeClass(StrEnum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class ProposalStatus(StrEnum):
    PROPOSED = "PROPOSED"
    CLASSIFIED = "CLASSIFIED"
    REVIEWING = "REVIEWING"
    REPLAYED = "REPLAYED"
    TESTED = "TESTED"
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    READY = "READY"
    PROMOTED = "PROMOTED"
    MONITORING = "MONITORING"
    ROLLED_BACK = "ROLLED_BACK"
    VETOED = "VETOED"
    FROZEN = "FROZEN"
    STALE_APPROVAL = "STALE_APPROVAL"
    REJECTED = "REJECTED"


class ReviewVerdict(StrEnum):
    SUPPORT = "SUPPORT"
    CONCERNS = "CONCERNS"
    REJECT = "REJECT"


class ObjectionDisposition(StrEnum):
    OPEN = "OPEN"
    FALSIFIED = "FALSIFIED"
    ACCEPTED_RISK = "ACCEPTED_RISK"
    MORE_EVIDENCE = "MORE_EVIDENCE"
    BLOCKED = "BLOCKED"


class ArtifactProvenance(ImmutableModel):
    """Reference accepted only when an authenticated producer and digest are present."""

    artifact_id: NonEmpty
    content_hash: Sha256
    authenticated_principal: NonEmpty
    environment_fingerprint: Sha256
    code_fingerprint: Sha256
    classification: NonEmpty = "INTERNAL"


class AutomatedCheck(ImmutableModel):
    check_id: NonEmpty
    check_kind: NonEmpty
    result: Literal["PASS", "FAIL"]
    result_artifact: ArtifactProvenance
    executed_at: datetime

    _executed_at_utc = field_validator("executed_at")(_utc)


class EvidenceReference(ImmutableModel):
    role: NonEmpty
    artifact: ArtifactProvenance


class SnapshotDependency(ImmutableModel):
    scope: NonEmpty
    version: NonEmpty
    content_hash: Sha256


class ApprovalSnapshot(ImmutableModel):
    dependencies: tuple[SnapshotDependency, ...] = Field(min_length=1)
    known_incident_ids: tuple[NonEmpty, ...] = ()
    evidence_hashes: tuple[Sha256, ...] = Field(min_length=1)
    snapshot_hash: Sha256

    @model_validator(mode="after")
    def _matches_contents(self) -> ApprovalSnapshot:
        body = {
            "dependencies": sorted(
                (item.model_dump(mode="json") for item in self.dependencies),
                key=lambda item: (item["scope"], item["version"]),
            ),
            "known_incident_ids": sorted(self.known_incident_ids),
            "evidence_hashes": sorted(self.evidence_hashes),
        }
        if self.snapshot_hash != _canonical_hash(body):
            raise ValueError("snapshot_hash does not match immutable approval inputs")
        return self


class GovernanceProposal(ImmutableModel):
    proposal_id: NonEmpty
    proposal_version: Annotated[int, Field(ge=1)]
    authored_by: NonEmpty
    declared_class: ChangeClass
    problem: NonEmpty
    proposed_change: NonEmpty
    affected_modules: tuple[NonEmpty, ...] = Field(min_length=1)
    affected_paths: tuple[NonEmpty, ...] = ()
    protected_controls: tuple[NonEmpty, ...] = ()
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    counterevidence: tuple[EvidenceReference, ...] = ()
    historical_replay_plan: NonEmpty
    risk_if_changed: NonEmpty
    risk_if_not_changed: NonEmpty
    rollback_plan: NonEmpty
    owner_attention_required: bool = False
    real_money_enablement: bool = False
    approval_snapshot: ApprovalSnapshot
    status: ProposalStatus = ProposalStatus.PROPOSED
    created_at: datetime
    classification_source: NonEmpty | None = None
    complete_evidence_at: datetime | None = None
    owner_notification_delivered_at: datetime | None = None
    promotion_eligible_at: datetime | None = None
    owner_veto_at: datetime | None = None
    owner_approval_at: datetime | None = None
    promoted_at: datetime | None = None
    rollback_policy_id: NonEmpty | None = None

    _dates_utc = field_validator(
        "created_at",
        "complete_evidence_at",
        "owner_notification_delivered_at",
        "promotion_eligible_at",
        "owner_veto_at",
        "owner_approval_at",
        "promoted_at",
    )(_utc)


class ProposalStateTransition(ImmutableModel):
    proposal_id: NonEmpty
    proposal_version: Annotated[int, Field(ge=1)]
    state_before: ProposalStatus
    state_after: ProposalStatus
    state_version_before: Annotated[int, Field(ge=1)]
    state_version_after: Annotated[int, Field(ge=2)]
    actor_principal: NonEmpty
    evidence: tuple[ArtifactProvenance, ...] = Field(min_length=1)
    created_at: datetime

    _created_at_utc = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def _serialized_version_chain(self) -> ProposalStateTransition:
        if self.state_version_after != self.state_version_before + 1:
            raise ValueError("proposal state transitions must advance one serialized version")
        return self


class Classification(ImmutableModel):
    proposal_id: NonEmpty
    policy_id: NonEmpty
    policy_version: NonEmpty
    classifier_principal: NonEmpty
    deterministic_floor: ChangeClass
    final_class: ChangeClass
    matched_controls: tuple[NonEmpty, ...]
    policy_content_hash: Sha256
    classified_at: datetime

    _classified_at_utc = field_validator("classified_at")(_utc)

    @model_validator(mode="after")
    def _cannot_downgrade_floor(self) -> Classification:
        if _severity_rank(self.final_class) < _severity_rank(self.deterministic_floor):
            raise ValueError("classification may escalate but cannot downgrade its deterministic floor")
        return self


class IndependenceProfile(ImmutableModel):
    provider_correlation_domain: NonEmpty
    model_family: NonEmpty
    model_version: NonEmpty
    reviewer_mandate: NonEmpty
    prompt_template_version: NonEmpty
    evidence_ordering: tuple[NonEmpty, ...] = Field(min_length=1)
    prior_verdicts_visible: bool = False
    shared_tools_retrieval_policy: NonEmpty
    known_shared_contamination: tuple[NonEmpty, ...] = ()
    independence_group_id: NonEmpty
    fresh_context_id: NonEmpty

    @model_validator(mode="after")
    def _blind_fresh_context(self) -> IndependenceProfile:
        if self.prior_verdicts_visible:
            raise ValueError("first-round reviewers must not see prior verdicts")
        return self

    @property
    def correlation_fingerprint(self) -> str:
        return _canonical_hash(
            {
                "provider_correlation_domain": self.provider_correlation_domain,
                "model_family": self.model_family,
                "model_version": self.model_version,
                "prompt_template_version": self.prompt_template_version,
                "evidence_ordering": self.evidence_ordering,
                "shared_tools_retrieval_policy": self.shared_tools_retrieval_policy,
                "known_shared_contamination": self.known_shared_contamination,
            }
        )


class MaterialObjection(ImmutableModel):
    objection_id: NonEmpty
    statement: NonEmpty
    disposition: ObjectionDisposition = ObjectionDisposition.OPEN
    resolution_evidence: tuple[EvidenceReference, ...] = ()

    @model_validator(mode="after")
    def _terminal_resolution_has_evidence(self) -> MaterialObjection:
        if self.disposition in {ObjectionDisposition.FALSIFIED, ObjectionDisposition.ACCEPTED_RISK}:
            if not self.resolution_evidence:
                raise ValueError("a material objection resolution requires provenance-backed evidence")
        return self


class GovernanceReview(ImmutableModel):
    council_review_id: NonEmpty
    proposal_id: NonEmpty
    reviewer_principal: NonEmpty
    profile: IndependenceProfile
    evidence_manifest_hash: Sha256
    inspected_evidence: tuple[ArtifactProvenance, ...] = Field(min_length=1)
    verdict: ReviewVerdict
    material_objections: tuple[MaterialObjection, ...] = ()
    confidence_advisory: Annotated[float | None, Field(ge=0, le=1)] = None
    created_at: datetime

    _created_at_utc = field_validator("created_at")(_utc)


class BlindReviewPacket(ImmutableModel):
    """Reviewer-safe packet: author identity and other verdicts are intentionally absent."""

    proposal_id: NonEmpty
    proposal_version: int
    change_class: ChangeClass
    problem: NonEmpty
    proposed_change: NonEmpty
    affected_modules: tuple[NonEmpty, ...]
    evidence_dossier: tuple[EvidenceReference, ...]
    counterevidence_dossier: tuple[EvidenceReference, ...]
    historical_replay_plan: NonEmpty
    risk_if_changed: NonEmpty
    risk_if_not_changed: NonEmpty
    rollback_plan: NonEmpty


class SynthesisRecord(ImmutableModel):
    proposal_id: NonEmpty
    synthesized_by: NonEmpty
    source_review_ids: tuple[NonEmpty, ...] = Field(min_length=1)
    synthesis_artifact: ArtifactProvenance
    residual_correlation_limitations: tuple[NonEmpty, ...] = ()
    created_at: datetime

    _created_at_utc = field_validator("created_at")(_utc)


class LifecycleEvidence(ImmutableModel):
    replay: tuple[AutomatedCheck, ...] = ()
    tests: tuple[AutomatedCheck, ...] = ()
    shadow: tuple[AutomatedCheck, ...] = ()
    canary: tuple[AutomatedCheck, ...] = ()

    def checks(self) -> tuple[AutomatedCheck, ...]:
        return (*self.replay, *self.tests, *self.shadow, *self.canary)

    def has_failure(self) -> bool:
        return any(item.result == "FAIL" for item in self.checks())

    def snapshot_hash(self) -> str:
        return _canonical_hash(self.model_dump(mode="json"))


class OwnerDelivery(ImmutableModel):
    authoritative_channel: NonEmpty
    notification_id: NonEmpty
    provider_message_id: NonEmpty
    delivered_at: datetime
    lifecycle_snapshot_hash: Sha256

    _delivered_at_utc = field_validator("delivered_at")(_utc)


class OwnerDecision(ImmutableModel):
    proposal_id: NonEmpty
    owner_principal: NonEmpty
    approved: bool = False
    vetoed: bool = False
    decision_artifact: ArtifactProvenance
    decided_at: datetime

    _decided_at_utc = field_validator("decided_at")(_utc)

    @model_validator(mode="after")
    def _one_decision(self) -> OwnerDecision:
        if self.approved == self.vetoed:
            raise ValueError("owner decision must be exactly one of approval or veto")
        return self


class IncidentSeverity(StrEnum):
    SEV0 = "SEV0"
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"


class IncidentStatus(StrEnum):
    OPEN = "OPEN"
    CONTAINED = "CONTAINED"
    RECONCILING = "RECONCILING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class Incident(ImmutableModel):
    incident_id: NonEmpty
    severity: IncidentSeverity
    status: IncidentStatus
    incident_type: NonEmpty
    opened_at: datetime
    opened_by: NonEmpty
    affected_modules: tuple[NonEmpty, ...] = Field(min_length=1)
    affected_run_ids: tuple[NonEmpty, ...] = ()
    affected_strategy_ids: tuple[NonEmpty, ...] = ()
    affected_policy_versions: tuple[NonEmpty, ...] = ()
    affected_artifact_ids: tuple[NonEmpty, ...] = ()
    evidence: tuple[ArtifactProvenance, ...] = Field(min_length=1)
    containment_actions: tuple[NonEmpty, ...] = ()
    contained_at: datetime | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    reconciliation_evidence: tuple[ArtifactProvenance, ...] = ()
    root_cause_artifact: ArtifactProvenance | None = None
    impact_assessment_artifact: ArtifactProvenance | None = None
    postmortem_artifact: ArtifactProvenance | None = None
    owner_notification_artifact: ArtifactProvenance | None = None
    owner_notified_at: datetime | None = None
    corrective_action_ids: tuple[NonEmpty, ...] = ()
    state_version: Annotated[int, Field(ge=1)] = 1

    _dates_utc = field_validator(
        "opened_at", "contained_at", "resolved_at", "closed_at", "owner_notified_at"
    )(_utc)

    @model_validator(mode="after")
    def _incident_evidence_is_complete(self) -> Incident:
        if self.status in {IncidentStatus.RESOLVED, IncidentStatus.CLOSED}:
            if not (self.reconciliation_evidence and self.root_cause_artifact and self.impact_assessment_artifact):
                raise ValueError("resolution requires reconciliation, root-cause, and impact evidence")
        if self.status is IncidentStatus.CLOSED:
            if self.severity in {IncidentSeverity.SEV0, IncidentSeverity.SEV1} and not self.postmortem_artifact:
                raise ValueError("material incident closure requires a structured postmortem")
        return self


class ChangeSet(ImmutableModel):
    change_set_id: NonEmpty
    proposal_ids: tuple[NonEmpty, ...] = Field(min_length=1)
    dependencies: tuple[SnapshotDependency, ...] = Field(min_length=1)
    affected_scopes: tuple[NonEmpty, ...] = Field(min_length=1)
    approval_snapshot_hash: Sha256
    interaction_test_artifacts: tuple[ArtifactProvenance, ...] = ()
    interaction_tests: tuple[AutomatedCheck, ...] = ()
    state: NonEmpty
    created_at: datetime
    revalidated_at: datetime | None = None
    promoted_at: datetime | None = None
    rollback_set_id: NonEmpty | None = None

    _dates_utc = field_validator("created_at", "revalidated_at", "promoted_at")(_utc)

    @model_validator(mode="after")
    def _composite_sets_are_tested(self) -> ChangeSet:
        if len(self.proposal_ids) > 1 and not (self.interaction_test_artifacts and self.interaction_tests):
            raise ValueError("combined governance changes require passing interaction-test evidence")
        return self


class ReplayEvent(ImmutableModel):
    """An immutable historical decision used by the deterministic counterfactual engine."""

    branch_id: NonEmpty
    actual_decision: NonEmpty
    counterfactual_decision: NonEmpty
    later_outcome: NonEmpty
    compute_cost_usd: Annotated[float, Field(ge=0)]
    statistical_capital: Annotated[float, Field(ge=0)]
    source_artifact: ArtifactProvenance


class ReplayResult(ImmutableModel):
    input_hash: Sha256
    evaluated_branches: Annotated[int, Field(ge=1)]
    killed_earlier: Annotated[int, Field(ge=0)]
    later_winners_lost: Annotated[int, Field(ge=0)]
    late_deaths_prevented: Annotated[int, Field(ge=0)]
    compute_cost_saved_usd: Annotated[float, Field(ge=0)]
    statistical_capital_delta: float


class LabeledStressScenario(ImmutableModel):
    scenario_id: NonEmpty
    scenario_class: NonEmpty
    expected_decision: NonEmpty
    observed_decision: NonEmpty
    fixture_artifact: ArtifactProvenance


class StressComparison(ImmutableModel):
    input_hash: Sha256
    scenario_classes: tuple[NonEmpty, ...]
    total: Annotated[int, Field(ge=1)]
    matched: Annotated[int, Field(ge=0)]
    mismatches: tuple[NonEmpty, ...]


class SystemBenchmarkExposure(ImmutableModel):
    benchmark_id: NonEmpty
    evidence: ArtifactProvenance
    purpose: NonEmpty
    consumed_at: datetime

    _consumed_at_utc = field_validator("consumed_at")(_utc)


class SystemEvolutionTrial(ImmutableModel):
    trial_id: NonEmpty
    ancestry_trial_id: NonEmpty | None = None
    changed_components: tuple[NonEmpty, ...] = Field(min_length=1)
    development_benchmarks: tuple[SystemBenchmarkExposure, ...] = Field(min_length=1)
    shadow_outcomes: tuple[ArtifactProvenance, ...] = ()
    canary_outcomes: tuple[ArtifactProvenance, ...] = ()
    sealed_benchmark_exposures: tuple[SystemBenchmarkExposure, ...] = ()
    selection_metrics: tuple[NonEmpty, ...] = Field(min_length=1)
    prior_failures_influenced_next_proposal: bool
    statistical_capital_charged: Annotated[float, Field(ge=0)]


class PolicyVersionRecord(ImmutableModel):
    policy_id: NonEmpty
    policy_version: NonEmpty
    content_hash: Sha256
    status: NonEmpty
    created_at: datetime
    effective_at: datetime | None = None
    retired_at: datetime | None = None
    governance_proposal_id: NonEmpty | None = None
    safe_bounds: dict[NonEmpty, object] = Field(default_factory=dict)
    rollback_to_version: NonEmpty | None = None

    _dates_utc = field_validator("created_at", "effective_at", "retired_at")(_utc)


class ModelType(StrEnum):
    STRATEGY = "strategy"
    RISK = "risk"
    COST = "cost"
    EXECUTION = "execution"
    STATISTICS = "statistics"
    DATA_TRANSFORM = "data_transform"
    ROUTER = "router"
    THIRD_PARTY = "third_party"
    OTHER = "other"


class Materiality(StrEnum):
    CRITICAL = "CRITICAL"
    MATERIAL = "MATERIAL"
    SUPPORTING = "SUPPORTING"


class ModelStatus(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    SHADOW = "SHADOW"
    APPROVED = "APPROVED"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class ModelCard(ImmutableModel):
    card_artifact: ArtifactProvenance
    purpose: NonEmpty
    scope: NonEmpty
    assumptions: tuple[NonEmpty, ...] = Field(min_length=1)
    limitations: tuple[NonEmpty, ...] = Field(min_length=1)
    dependencies: tuple[NonEmpty, ...] = Field(min_length=1)


class DataCard(ImmutableModel):
    card_artifact: ArtifactProvenance
    dataset_family: NonEmpty
    provenance: tuple[ArtifactProvenance, ...] = Field(min_length=1)
    time_coverage: NonEmpty
    availability_semantics: NonEmpty
    quality_limitations: tuple[NonEmpty, ...] = Field(min_length=1)
    licensing_retention: NonEmpty
    contamination_repair_history: tuple[NonEmpty, ...] = ()


class ModelValidation(ImmutableModel):
    validation_id: NonEmpty
    validator_principal: NonEmpty
    validation_evidence: tuple[ArtifactProvenance, ...] = Field(min_length=1)
    conceptual_soundness: AutomatedCheck
    implementation_correctness: AutomatedCheck
    sensitivity: AutomatedCheck
    monitoring_thresholds: tuple[NonEmpty, ...] = Field(min_length=1)
    challenger_evidence: tuple[ArtifactProvenance, ...] = ()
    completed_at: datetime

    _completed_at_utc = field_validator("completed_at")(_utc)


class DriftObservation(ImmutableModel):
    observation_id: NonEmpty
    drift_kind: NonEmpty
    measured_value: float
    threshold: float
    direction: str = Field(pattern="^(ABOVE|BELOW)$")
    measurement_artifact: ArtifactProvenance
    observed_at: datetime

    _observed_at_utc = field_validator("observed_at")(_utc)

    @property
    def breached(self) -> bool:
        return self.measured_value > self.threshold if self.direction == "ABOVE" else self.measured_value < self.threshold


class ModelRecord(ImmutableModel):
    model_id: NonEmpty
    model_type: ModelType
    owner_role: NonEmpty
    developer_principals: tuple[NonEmpty, ...] = Field(min_length=1)
    developer_artifacts: tuple[ArtifactProvenance, ...] = Field(min_length=1)
    purpose: NonEmpty
    allowed_uses: tuple[NonEmpty, ...] = Field(min_length=1)
    prohibited_uses: tuple[NonEmpty, ...] = Field(min_length=1)
    materiality: Materiality
    inputs: tuple[NonEmpty, ...] = Field(min_length=1)
    outputs: tuple[NonEmpty, ...] = Field(min_length=1)
    assumptions: tuple[NonEmpty, ...] = Field(min_length=1)
    limitations: tuple[NonEmpty, ...] = Field(min_length=1)
    dependencies: tuple[NonEmpty, ...] = Field(min_length=1)
    validation_status: NonEmpty
    champion_challenger_status: NonEmpty
    monitoring_plan_id: NonEmpty
    version: NonEmpty
    status: ModelStatus
    development_evidence: tuple[ArtifactProvenance, ...] = Field(min_length=1)
    validation_evidence: tuple[ArtifactProvenance, ...] = ()
    monitoring_evidence: tuple[ArtifactProvenance, ...] = ()
    recalibration_consumed_evidence: tuple[ArtifactProvenance, ...] = ()
    model_card: ModelCard | None = None
    created_at: datetime
    updated_at: datetime
    validation_due_at: datetime | None = None
    retired_at: datetime | None = None
    replacement_model_id: NonEmpty | None = None

    _dates_utc = field_validator("created_at", "updated_at", "validation_due_at", "retired_at")(_utc)

    @model_validator(mode="after")
    def _model_lifecycle_consistency(self) -> ModelRecord:
        development = {item.content_hash for item in self.development_evidence}
        validation = {item.content_hash for item in self.validation_evidence}
        consumed = {item.content_hash for item in self.recalibration_consumed_evidence}
        if development & validation:
            raise ValueError("development evidence cannot be claimed as independent validation")
        if self.status is ModelStatus.RETIRED and self.retired_at is None:
            raise ValueError("retired model requires retired_at")
        if self.status is not ModelStatus.RETIRED and self.retired_at is not None:
            raise ValueError("only retired model may have retired_at")
        if self.materiality in {Materiality.CRITICAL, Materiality.MATERIAL} and self.model_card is None:
            raise ValueError("material models require a machine-readable Model Card")
        if validation & consumed:
            raise ValueError("recalibration-consumed validation evidence is no longer independent")
        return self


class AdmissionDecision(ImmutableModel):
    admissible: bool
    reasons: tuple[NonEmpty, ...]


def _severity_rank(value: ChangeClass) -> int:
    return {ChangeClass.GREEN: 0, ChangeClass.AMBER: 1, ChangeClass.RED: 2}[value]


def build_blind_packet(proposal: GovernanceProposal, classification: Classification) -> BlindReviewPacket:
    """Return the first-round packet without author, classifier identity, or verdicts."""
    return BlindReviewPacket(
        proposal_id=proposal.proposal_id,
        proposal_version=proposal.proposal_version,
        change_class=classification.final_class,
        problem=proposal.problem,
        proposed_change=proposal.proposed_change,
        affected_modules=proposal.affected_modules,
        evidence_dossier=proposal.evidence,
        counterevidence_dossier=proposal.counterevidence,
        historical_replay_plan=proposal.historical_replay_plan,
        risk_if_changed=proposal.risk_if_changed,
        risk_if_not_changed=proposal.risk_if_not_changed,
        rollback_plan=proposal.rollback_plan,
    )


def classify_proposal(
    proposal: GovernanceProposal,
    policy: GovernancePolicy,
    classifier_principal: str,
    now: datetime,
) -> Classification:
    """Apply the protected-path floor. A classifier may only escalate it."""
    _utc(now)
    if classifier_principal == proposal.authored_by:
        raise GovernanceError("proposal author cannot be the sole severity classifier")
    floor, controls = policy.floor_for(proposal.affected_paths, proposal.protected_controls)
    if proposal.real_money_enablement:
        floor, controls = ChangeClass.RED, (*controls, "real_money_enablement")
    final = proposal.declared_class if _severity_rank(proposal.declared_class) >= _severity_rank(floor) else floor
    return Classification(
        proposal_id=proposal.proposal_id,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        classifier_principal=classifier_principal,
        deterministic_floor=floor,
        final_class=final,
        matched_controls=tuple(sorted(set(controls))),
        policy_content_hash=policy.content_hash,
        classified_at=now,
    )


def _check_unique_independence(reviews: Iterable[GovernanceReview]) -> tuple[GovernanceReview, ...]:
    values = tuple(reviews)
    groups = [review.profile.independence_group_id for review in values]
    fingerprints = [review.profile.correlation_fingerprint for review in values]
    if len(groups) != len(set(groups)):
        raise GovernanceError("review padding detected: independence groups must be unique")
    if len(fingerprints) != len(set(fingerprints)):
        raise GovernanceError("review padding detected: materially identical review profiles")
    return values


def _requirements_met(
    classification: Classification,
    proposal: GovernanceProposal,
    reviews: tuple[GovernanceReview, ...],
    lifecycle: LifecycleEvidence,
    synthesis: SynthesisRecord | None,
) -> list[str]:
    reasons: list[str] = []
    required_reviews = {ChangeClass.GREEN: 3, ChangeClass.AMBER: 5, ChangeClass.RED: 7}[classification.final_class]
    if len(reviews) < required_reviews:
        reasons.append(f"requires {required_reviews} independent blind reviews")
    if any(review.proposal_id != proposal.proposal_id for review in reviews):
        reasons.append("review proposal mismatch")
    if any(review.reviewer_principal == proposal.authored_by for review in reviews):
        reasons.append("proposal author cannot review own proposal")
    correlation_domains = [
        (review.profile.provider_correlation_domain, review.profile.model_family, review.profile.model_version)
        for review in reviews
    ]
    if len(correlation_domains) != len(set(correlation_domains)):
        if synthesis is None or not synthesis.residual_correlation_limitations:
            reasons.append("shared model correlation requires explicit synthesis disclosure")
    if not lifecycle.tests:
        reasons.append("automated acceptance checks are required before owner timing or promotion")
    if lifecycle.has_failure():
        reasons.append("lifecycle evidence contains a failed deterministic check")
    if classification.final_class in {ChangeClass.AMBER, ChangeClass.RED}:
        if synthesis is None or synthesis.synthesized_by in {
            proposal.authored_by,
            classification.classifier_principal,
        }:
            reasons.append("AMBER/RED synthesis must be separate from author and classifier")
        if not lifecycle.replay or not lifecycle.tests or not lifecycle.shadow or not lifecycle.canary:
            reasons.append("AMBER/RED requires replay, tests, shadow, and canary evidence")
    if classification.final_class is ChangeClass.RED:
        adversarial = [review for review in reviews if "adversarial" in review.profile.reviewer_mandate.lower()]
        if len(adversarial) < 2:
            reasons.append("RED requires two independent adversarial audits")
    if classification.final_class is ChangeClass.AMBER:
        adversarial = [review for review in reviews if "adversarial" in review.profile.reviewer_mandate.lower()]
        if len(adversarial) < 1:
            reasons.append("AMBER requires one independent adversarial audit")
    if any(
        objection.disposition in {ObjectionDisposition.OPEN, ObjectionDisposition.MORE_EVIDENCE, ObjectionDisposition.BLOCKED}
        for review in reviews
        for objection in review.material_objections
    ):
        reasons.append("material objections are unresolved; a majority cannot override them")
    return reasons


def evaluate_promotion(
    proposal: GovernanceProposal,
    classification: Classification,
    reviews: Iterable[GovernanceReview],
    lifecycle: LifecycleEvidence,
    current_snapshot: ApprovalSnapshot,
    now: datetime,
    *,
    synthesis: SynthesisRecord | None = None,
    owner_delivery: OwnerDelivery | None = None,
    owner_decision: OwnerDecision | None = None,
    relevant_incidents: Iterable[Incident] = (),
    change_set: ChangeSet | None = None,
) -> ProposalStatus:
    """Return READY/PROMOTED or a fail-closed state; no persistence side effects occur."""
    _utc(now)
    if classification.proposal_id != proposal.proposal_id:
        return ProposalStatus.REJECTED
    if owner_decision is not None and owner_decision.proposal_id != proposal.proposal_id:
        return ProposalStatus.REJECTED
    if proposal.status is ProposalStatus.VETOED or (owner_decision and owner_decision.vetoed):
        return ProposalStatus.VETOED
    if proposal.real_money_enablement:
        return ProposalStatus.REJECTED  # This build has no real-money execution path.
    if any(incident.status not in {IncidentStatus.RESOLVED, IncidentStatus.CLOSED} and _incident_relevant(incident, proposal) for incident in relevant_incidents):
        return ProposalStatus.FROZEN
    if mark_stale_if_snapshot_changed(proposal.approval_snapshot, current_snapshot):
        return ProposalStatus.STALE_APPROVAL
    if change_set and (
        proposal.proposal_id not in change_set.proposal_ids
        or change_set.approval_snapshot_hash != proposal.approval_snapshot.snapshot_hash
        or (
            len(change_set.proposal_ids) > 1
            and not (change_set.interaction_test_artifacts and change_set.interaction_tests)
        )
    ):
        return ProposalStatus.STALE_APPROVAL
    try:
        review_values = _check_unique_independence(reviews)
    except GovernanceError:
        return ProposalStatus.REJECTED
    if owner_delivery is not None and any(
        item.result == "FAIL" and item.executed_at >= owner_delivery.delivered_at
        for item in lifecycle.checks()
    ):
        return ProposalStatus.FROZEN
    if _requirements_met(classification, proposal, review_values, lifecycle, synthesis):
        return ProposalStatus.REVIEWING
    if classification.final_class is ChangeClass.RED:
        return ProposalStatus.PROMOTED if owner_decision and owner_decision.approved else ProposalStatus.READY
    if owner_delivery is None:
        return ProposalStatus.READY
    if proposal.complete_evidence_at is None or owner_delivery.delivered_at < proposal.complete_evidence_at:
        return ProposalStatus.READY
    if owner_delivery.lifecycle_snapshot_hash != lifecycle.snapshot_hash():
        return ProposalStatus.READY
    if any(check.executed_at > owner_delivery.delivered_at for check in lifecycle.checks()):
        return ProposalStatus.READY
    eligible_at = owner_delivery.delivered_at + timedelta(hours=24)
    if now < eligible_at:
        return ProposalStatus.READY
    return ProposalStatus.PROMOTED


def mark_stale_if_snapshot_changed(approved: ApprovalSnapshot, current: ApprovalSnapshot) -> bool:
    """Exact hash comparison catches evidence, dependency, and incident changes."""
    return approved.snapshot_hash != current.snapshot_hash


def transition_proposal(
    proposal: GovernanceProposal,
    state_version: int,
    to_status: ProposalStatus,
    actor_principal: str,
    evidence: Iterable[ArtifactProvenance],
    now: datetime,
    *,
    promotion_evaluation: ProposalStatus | None = None,
) -> ProposalStateTransition:
    """Produce the append-only transition the persistence owner must CAS-store."""
    _utc(now)
    flow = {
        ProposalStatus.PROPOSED: {ProposalStatus.CLASSIFIED},
        ProposalStatus.CLASSIFIED: {ProposalStatus.REVIEWING},
        ProposalStatus.REVIEWING: {ProposalStatus.REPLAYED},
        ProposalStatus.REPLAYED: {ProposalStatus.TESTED},
        ProposalStatus.TESTED: {ProposalStatus.SHADOW},
        ProposalStatus.SHADOW: {ProposalStatus.CANARY},
        ProposalStatus.CANARY: {ProposalStatus.READY},
        ProposalStatus.READY: {ProposalStatus.PROMOTED},
        ProposalStatus.PROMOTED: {ProposalStatus.MONITORING, ProposalStatus.ROLLED_BACK},
        ProposalStatus.MONITORING: {ProposalStatus.ROLLED_BACK},
    }
    universal = {
        ProposalStatus.FROZEN,
        ProposalStatus.STALE_APPROVAL,
        ProposalStatus.VETOED,
        ProposalStatus.REJECTED,
    }
    allowed = flow.get(proposal.status, set()) | universal
    if to_status not in allowed:
        raise GovernanceError(f"invalid proposal transition {proposal.status} -> {to_status}")
    if to_status is ProposalStatus.PROMOTED and promotion_evaluation is not ProposalStatus.PROMOTED:
        raise GovernanceError("promotion requires a fresh deterministic promotion evaluation")
    evidence_values = tuple(evidence)
    if not evidence_values:
        raise GovernanceError("every proposal transition requires provenance-backed evidence")
    return ProposalStateTransition(
        proposal_id=proposal.proposal_id,
        proposal_version=proposal.proposal_version,
        state_before=proposal.status,
        state_after=to_status,
        state_version_before=state_version,
        state_version_after=state_version + 1,
        actor_principal=actor_principal,
        evidence=evidence_values,
        created_at=now,
    )


def _incident_relevant(incident: Incident, proposal: GovernanceProposal) -> bool:
    proposal_scopes = set(proposal.affected_modules) | set(proposal.affected_paths)
    return bool(proposal_scopes & set(incident.affected_modules)) or bool(
        set(incident.affected_policy_versions)
    )


def transition_incident(
    incident: Incident,
    to_status: IncidentStatus,
    now: datetime,
    *,
    containment_action: str | None = None,
    reconciliation_evidence: Iterable[ArtifactProvenance] = (),
    root_cause_artifact: ArtifactProvenance | None = None,
    impact_assessment_artifact: ArtifactProvenance | None = None,
    postmortem_artifact: ArtifactProvenance | None = None,
) -> Incident:
    _utc(now)
    valid = {
        IncidentStatus.OPEN: {IncidentStatus.CONTAINED},
        IncidentStatus.CONTAINED: {IncidentStatus.RECONCILING},
        IncidentStatus.RECONCILING: {IncidentStatus.RESOLVED},
        IncidentStatus.RESOLVED: {IncidentStatus.CLOSED, IncidentStatus.OPEN},
        IncidentStatus.CLOSED: set(),
    }
    if to_status not in valid[incident.status]:
        raise GovernanceError(f"invalid incident transition {incident.status} -> {to_status}")
    data = incident.model_dump()
    data["status"] = to_status
    data["state_version"] = incident.state_version + 1
    if to_status is IncidentStatus.CONTAINED:
        data["contained_at"] = now
        data["containment_actions"] = (*incident.containment_actions, containment_action or "contained")
    if to_status is IncidentStatus.RESOLVED:
        data.update(
            resolved_at=now,
            reconciliation_evidence=tuple(reconciliation_evidence),
            root_cause_artifact=root_cause_artifact,
            impact_assessment_artifact=impact_assessment_artifact,
        )
    if to_status is IncidentStatus.CLOSED:
        data.update(closed_at=now, postmortem_artifact=postmortem_artifact)
    return Incident.model_validate(data)


advance_incident = transition_incident


def assess_model_admission(record: ModelRecord, validation: ModelValidation | None) -> AdmissionDecision:
    """Admission is evidence-based and deliberately rejects retired/unsupported models."""
    reasons: list[str] = []
    if record.status is ModelStatus.RETIRED:
        reasons.append("retired models cannot be admitted")
    if record.status in {ModelStatus.SUSPENDED, ModelStatus.WATCH}:
        reasons.append(f"model status {record.status} blocks admission")
    if record.materiality in {Materiality.CRITICAL, Materiality.MATERIAL}:
        if validation is None:
            reasons.append("material model requires independent validation")
        elif validation.validator_principal in record.developer_principals:
            reasons.append("developer cannot be sole independent validator")
        elif {item.content_hash for item in validation.validation_evidence} & {
            *(item.content_hash for item in record.development_evidence),
            *(item.content_hash for item in record.recalibration_consumed_evidence),
        }:
            reasons.append("development or recalibration-consumed evidence cannot validate the model")
    return AdmissionDecision(admissible=not reasons, reasons=tuple(reasons) or ("admission requirements met",))


def find_common_dependencies(records: Iterable[ModelRecord]) -> dict[str, tuple[str, ...]]:
    by_dependency: dict[str, list[str]] = {}
    for record in records:
        for dependency in record.dependencies:
            by_dependency.setdefault(dependency, []).append(record.model_id)
    return {dependency: tuple(model_ids) for dependency, model_ids in by_dependency.items() if len(model_ids) > 1}
