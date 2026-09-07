"""Authenticated, deterministic evidence checks for research gates G1 through G4.

This module deliberately does not decide a gate from an agent-supplied verdict.  It
resolves immutable artifacts through ``Store.artifact`` and reads the trial, lineage,
data-manifest, and previous-gate tables using the evaluator's authenticated
connection.  The signed verification runner owns persistence and signing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from liki.core import Contract, DomainError, content_hash
from liki.data.models import DatasetManifest, QualityStatus, ensure_optional_utc, ensure_utc
from liki.store import Identity, Store


class FamilyKey(Contract):
    asset_class: str = Field(min_length=1)
    market: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)
    strategy_family: str = Field(min_length=1)
    signal_family: str = Field(min_length=1)
    holding_period_bucket: str = Field(min_length=1)


class G1Plan(Contract):
    family_id: str = Field(min_length=1)
    family_key: FamilyKey
    trial_type: str = Field(min_length=1)
    semantic_configuration: dict[str, Any]
    dataset_snapshot_ids: tuple[str, ...] = Field(min_length=1)
    metric_ids: tuple[str, ...] = Field(min_length=1)


class FeatureTimingRow(Contract):
    feature_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    decision_time: datetime
    latest_source_timestamp_used: datetime

    _utc = field_validator("decision_time", "latest_source_timestamp_used")(ensure_utc)

    @model_validator(mode="after")
    def no_future_source(self) -> FeatureTimingRow:
        if self.latest_source_timestamp_used > self.decision_time:
            raise ValueError("feature source is later than the decision")
        return self


class LabelTimingRow(Contract):
    label_id: str = Field(min_length=1)
    decision_time: datetime
    outcome_end_time: datetime
    label_available_at: datetime

    _utc = field_validator("decision_time", "outcome_end_time", "label_available_at")(ensure_utc)

    @model_validator(mode="after")
    def label_is_future_and_available_after_outcome(self) -> LabelTimingRow:
        if self.outcome_end_time <= self.decision_time:
            raise ValueError("label outcome must end after its decision")
        if self.label_available_at < self.outcome_end_time:
            raise ValueError("label cannot be available before its outcome ends")
        return self


class UniverseMembershipRow(Contract):
    instrument_id: str = Field(min_length=1)
    effective_from: datetime
    effective_to: datetime | None = None
    source_available_at: datetime
    decision_time: datetime

    _utc = field_validator("effective_from", "source_available_at", "decision_time")(ensure_utc)
    _optional_utc = field_validator("effective_to")(ensure_optional_utc)

    @model_validator(mode="after")
    def interval_is_valid(self) -> UniverseMembershipRow:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("universe membership end must follow its start")
        if not self.effective_from <= self.decision_time or (
            self.effective_to is not None and self.decision_time >= self.effective_to
        ):
            raise ValueError("universe membership is not effective at decision time")
        if self.source_available_at > self.decision_time:
            raise ValueError("universe membership was unavailable at decision time")
        return self


class G2Plan(Contract):
    dataset_snapshot_ids: tuple[str, ...] = Field(min_length=1)
    feature_timing_artifact_id: str = Field(min_length=1)
    label_timing_artifact_id: str = Field(min_length=1)
    universe_artifact_id: str = Field(min_length=1)


class FalsifiablePrediction(Contract):
    outcome_id: str = Field(min_length=1)
    prediction: str = Field(min_length=1)
    disconfirming_outcome: str = Field(min_length=1)
    measurement_method: str = Field(min_length=1)

    @field_validator("*")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("prediction fields must not be blank")
        return value


class MinimumViableTest(Contract):
    test_id: str = Field(min_length=1)
    dataset_snapshot_ids: tuple[str, ...] = Field(min_length=1)
    sample_unit: str = Field(min_length=1)
    minimum_observations: int = Field(ge=1)
    outcome_id: str = Field(min_length=1)


class G3Plan(Contract):
    basis: Literal["MECHANISM", "EMPIRICAL"]
    mechanism: str | None = None
    payer: str | None = None
    empirical_pattern_artifact_id: str | None = None
    market_structure: str = Field(min_length=1)
    horizon_seconds: int = Field(gt=0)
    prediction: FalsifiablePrediction
    minimum_viable_test: MinimumViableTest
    constraints: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def basis_has_evidence_surface(self) -> G3Plan:
        text = (self.market_structure, *self.constraints, self.minimum_viable_test.test_id,
                self.minimum_viable_test.sample_unit, self.minimum_viable_test.outcome_id)
        if any(not value.strip() for value in text):
            raise ValueError("feasibility declarations must not be blank")
        if self.basis == "MECHANISM" and (not self.mechanism or not self.payer):
            raise ValueError("mechanism basis requires mechanism and payer")
        if self.basis == "MECHANISM" and any(
            not value.strip() for value in (self.mechanism or "", self.payer or "")
        ):
            raise ValueError("mechanism and payer must not be blank")
        if self.basis == "EMPIRICAL" and not self.empirical_pattern_artifact_id:
            raise ValueError("empirical basis requires an observed-pattern artifact")
        return self


class CostBounds(Contract):
    fee: tuple[Decimal, Decimal]
    spread: tuple[Decimal, Decimal]
    slippage: tuple[Decimal, Decimal]
    funding: tuple[Decimal, Decimal]
    borrow: tuple[Decimal, Decimal]
    impact: tuple[Decimal, Decimal]
    other: tuple[Decimal, Decimal]

    @model_validator(mode="after")
    def lower_bound_precedes_upper(self) -> CostBounds:
        if any(lower > upper for lower, upper in self.__dict__.values()):
            raise ValueError("cost lower bound exceeds upper bound")
        return self


class G4Plan(Contract):
    minimum_samples: int = Field(ge=1)
    cost_bounds: CostBounds
    capacity_limit: Decimal
    currency: str = Field(min_length=1)
    benchmark_id: str = Field(min_length=1)
    benchmark_version: str = Field(min_length=1)

    @field_validator("capacity_limit")
    @classmethod
    def positive_capacity(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("capacity limit must be positive")
        return value


class EarlyGatePlan(Contract):
    candidate_artifact_id: str = Field(min_length=1)
    candidate_hash: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    gate_id: Literal[1, 2, 3, 4]
    g1: G1Plan | None = None
    g2: G2Plan | None = None
    g3: G3Plan | None = None
    g4: G4Plan | None = None

    @model_validator(mode="after")
    def has_only_its_gate_plan(self) -> EarlyGatePlan:
        plans = {1: self.g1, 2: self.g2, 3: self.g3, 4: self.g4}
        if plans[self.gate_id] is None or any(
            plan is not None for gate_id, plan in plans.items() if gate_id != self.gate_id
        ):
            raise ValueError("early gate artifact must contain exactly one matching gate plan")
        return self


class GatePolicy(Contract):
    policy_version: str = Field(min_length=1)
    cooldown_hours: dict[Literal["soft", "medium", "hard"], int]
    default_failure_severity: Literal["soft", "medium", "hard"]
    g4_mean_after_cost_lower: Decimal | None = None
    g4_mean_excess_after_cost_lower: Decimal | None = None

    @model_validator(mode="after")
    def complete_and_gate_specific(self) -> GatePolicy:
        if set(self.cooldown_hours) != {"soft", "medium", "hard"} or any(
            value < 0 for value in self.cooldown_hours.values()
        ):
            raise ValueError("cooldown policy needs non-negative soft, medium, and hard durations")
        has_g4_policy = self.g4_mean_after_cost_lower is not None or self.g4_mean_excess_after_cost_lower is not None
        if has_g4_policy and (
            self.g4_mean_after_cost_lower is None or self.g4_mean_excess_after_cost_lower is None
        ):
            raise ValueError("G4 policy needs both after-cost lower bounds")
        return self


class CostSample(Contract):
    sample_id: str = Field(min_length=1)
    dataset_snapshot_id: str = Field(min_length=1)
    observed_at: datetime
    gross_pnl: Decimal
    fee: Decimal
    spread: Decimal
    slippage: Decimal
    funding: Decimal
    borrow: Decimal
    impact: Decimal
    other: Decimal
    currency: str = Field(min_length=1)

    _utc = field_validator("observed_at")(ensure_utc)

    @property
    def after_cost_pnl(self) -> Decimal:
        return self.gross_pnl - sum(
            (self.fee, self.spread, self.slippage, self.funding, self.borrow, self.impact, self.other),
            Decimal("0"),
        )


class BenchmarkSample(Contract):
    sample_id: str = Field(min_length=1)
    dataset_snapshot_id: str = Field(min_length=1)
    benchmark_id: str = Field(min_length=1)
    benchmark_version: str = Field(min_length=1)
    after_cost_pnl: Decimal
    currency: str = Field(min_length=1)


class CapacityObservation(Contract):
    sample_id: str = Field(min_length=1)
    requested_notional: Decimal
    executable_notional: Decimal
    planned_notional: Decimal
    currency: str = Field(min_length=1)

    @model_validator(mode="after")
    def notional_is_nonnegative(self) -> CapacityObservation:
        if min(self.requested_notional, self.executable_notional, self.planned_notional) < 0:
            raise ValueError("capacity notionals must be non-negative")
        if self.executable_notional > self.requested_notional:
            raise ValueError("executable notional cannot exceed the requested amount")
        return self


class G4Evidence(Contract):
    samples: tuple[CostSample, ...] = Field(min_length=1)
    benchmarks: tuple[BenchmarkSample, ...] = Field(min_length=1)
    capacity: tuple[CapacityObservation, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_sample_ids(self) -> G4Evidence:
        for rows in (self.samples, self.benchmarks, self.capacity):
            if len({sample.sample_id for sample in rows}) != len(rows):
                raise ValueError("sample IDs must be unique within each evidence series")
        return self


def _report(
    checks: dict[str, bool], *, hard_invalidity: bool, unknowns: list[str], metrics: dict[str, Any],
    artifacts: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "checks": checks,
        "hard_invalidity": hard_invalidity,
        "unknowns": sorted(set(unknowns)),
        # Evaluation consumes this field as a list of MetricValue dictionaries. Early gates have
        # no snapshot MetricRule values; their non-comparable diagnostics stay separately bound.
        "metrics": [],
        "derived_metrics": metrics,
        "input_artifacts": dict(sorted(artifacts.items())),
        "referenced_input_artifacts": dict(sorted(artifacts.items())),
    }


def _snapshot(snapshot: Any) -> tuple[dict[str, Any], datetime | None]:
    if isinstance(snapshot, Mapping):
        manifest = snapshot.get("manifest", snapshot)
        if isinstance(manifest, Mapping):
            created_at = snapshot.get("created_at")
            return dict(manifest), created_at if isinstance(created_at, datetime) else None
    if hasattr(snapshot, "model_dump"):
        return snapshot.model_dump(mode="json"), None
    return {}, None


def _bound_artifacts(
    store: Store, conn: Any, actor: Identity, artifact_ids: Iterable[str | Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for supplied in artifact_ids:
        artifact_id = supplied if isinstance(supplied, str) else supplied.get("artifact_id")
        if not isinstance(artifact_id, str) or artifact_id in rows:
            raise DomainError("INVALID_EARLY_GATE_INPUT_ARTIFACTS")
        row = store.artifact(conn, actor, artifact_id)
        if isinstance(supplied, Mapping) and supplied.get("content_hash") not in {None, row["content_hash"]}:
            raise DomainError("EARLY_GATE_INPUT_REBINDING")
        rows[artifact_id] = row
    return rows


def _plan(
    artifacts: Mapping[str, dict[str, Any]], *, gate_id: int, candidate_id: str, candidate_hash: str,
    snapshot_id: str, snapshot_created_at: datetime | None,
) -> tuple[EarlyGatePlan | None, list[str]]:
    candidates = [row for row in artifacts.values() if row["schema_name"] == "research/early-gate-plan-v1"]
    if len(candidates) != 1:
        return None, ["EARLY_GATE_PLAN_MISSING_OR_AMBIGUOUS"]
    row = candidates[0]
    try:
        plan = EarlyGatePlan.model_validate(row["content"])
    except ValidationError:
        return None, ["EARLY_GATE_PLAN_INVALID"]
    if (plan.gate_id != gate_id or plan.candidate_artifact_id != candidate_id
            or plan.candidate_hash != candidate_hash or plan.snapshot_id != snapshot_id):
        return None, ["EARLY_GATE_PLAN_NOT_CANDIDATE_SNAPSHOT_PINNED"]
    if snapshot_created_at is None:
        return None, ["EVALUATION_SNAPSHOT_TIMESTAMP_UNAVAILABLE"]
    if row["created_at"] >= snapshot_created_at:
        return None, ["EARLY_GATE_PLAN_DOES_NOT_PREDATE_EVALUATION"]
    return plan, []


def _policy(
    conn: Any, artifacts: Mapping[str, dict[str, Any]], *, expected_version: str,
    snapshot_created_at: datetime | None,
) -> tuple[GatePolicy | None, list[str]]:
    candidates = [row for row in artifacts.values() if row["schema_name"] == "governance/early-gate-policy-v1"]
    if len(candidates) != 1:
        return None, ["EARLY_GATE_POLICY_MISSING_OR_AMBIGUOUS"]
    try:
        policy = GatePolicy.model_validate(candidates[0]["content"])
    except ValidationError:
        return None, ["EARLY_GATE_POLICY_INVALID"]
    producer = conn.execute(
        "SELECT role FROM principals WHERE principal_id=%s", (candidates[0]["producer_id"],)
    ).fetchone()
    if not producer or producer["role"] != "governance":
        return None, ["EARLY_GATE_POLICY_NOT_GOVERNANCE_AUTHORED"]
    if snapshot_created_at is None:
        return None, ["EVALUATION_SNAPSHOT_TIMESTAMP_UNAVAILABLE"]
    if candidates[0]["created_at"] >= snapshot_created_at:
        return None, ["EARLY_GATE_POLICY_DOES_NOT_PREDATE_EVALUATION"]
    if candidates[0]["policy_version"] != expected_version or policy.policy_version != expected_version:
        return None, ["EARLY_GATE_POLICY_VERSION_MISMATCH"]
    return policy, []


def _artifact_by_id(
    artifacts: Mapping[str, dict[str, Any]], artifact_id: str, schema_name: str
) -> tuple[dict[str, Any] | None, list[str]]:
    artifact = artifacts.get(artifact_id)
    if artifact is None:
        return None, [f"REQUIRED_INPUT_ARTIFACT_NOT_BOUND:{artifact_id}"]
    if artifact["schema_name"] != schema_name:
        return None, [f"INPUT_ARTIFACT_SCHEMA_MISMATCH:{artifact_id}"]
    return artifact, []


def _gate_one(
    conn: Any, plan: G1Plan, policy: GatePolicy, *, strategy_version_id: str, candidate_hash: str
) -> tuple[dict[str, bool], bool, dict[str, Any]]:
    duplicates = conn.execute(
        "SELECT ro.object_id FROM research_objects ro JOIN artifacts a ON a.artifact_id=ro.artifact_id "
        "WHERE ro.object_id<>%s AND a.content_hash=%s", (strategy_version_id, candidate_hash)
    ).fetchall()
    exact_duplicate = bool(duplicates)
    semantic_hash = content_hash({
        "configuration": plan.semantic_configuration, "datasets": plan.dataset_snapshot_ids,
        "metrics": plan.metric_ids, "type": plan.trial_type,
    })
    declared_trial = conn.execute(
        "SELECT 1 FROM trial_events WHERE strategy_version_id=%s AND trial_family_id=%s "
        "AND semantic_hash=%s AND NOT infrastructure_retry",
        (strategy_version_id, plan.family_id, semantic_hash),
    ).fetchone() is not None
    equivalent = conn.execute(
        "SELECT trial_event_id,strategy_version_id FROM trial_events WHERE semantic_hash=%s AND strategy_version_id<>%s "
        "AND NOT infrastructure_retry", (semantic_hash, strategy_version_id)
    ).fetchall()
    family_trials = conn.execute(
        "WITH RECURSIVE ancestry(object_id) AS ("
        "SELECT %s::text UNION SELECT edge.parent_id FROM lineage_edges edge "
        "JOIN ancestry ON edge.child_id=ancestry.object_id) "
        "SELECT t.trial_event_id,t.strategy_version_id FROM trial_events t "
        "WHERE t.strategy_version_id IN (SELECT object_id FROM ancestry) OR "
        "(t.trial_family_id=%s AND t.strategy_version_id<>%s)",
        (strategy_version_id, plan.family_id, strategy_version_id),
    ).fetchall()
    failures = conn.execute(
        "SELECT g.reason_code,g.created_at,g.artifact_ids FROM gate_decisions g "
        "WHERE g.strategy_version_id=ANY(%s) AND g.decision='FAIL'",
        (list({trial["strategy_version_id"] for trial in family_trials + equivalent}
              | {duplicate["object_id"] for duplicate in duplicates}),)
    ).fetchall()
    known_hard = False
    cooldown_active = False
    for failure in failures:
        severity = "hard" if failure["reason_code"] == "HARD_INVALIDITY" else policy.default_failure_severity
        cooldown_active = cooldown_active or failure["created_at"] + timedelta(
            hours=policy.cooldown_hours[severity]
        ) > datetime.now(failure["created_at"].tzinfo)
        for artifact_id in failure["artifact_ids"]:
            artifact = conn.execute("SELECT content FROM artifacts WHERE artifact_id=%s", (artifact_id,)).fetchone()
            known_hard = known_hard or bool(artifact and artifact["content"].get("hard_invalidity"))
    checks = {
        "not_duplicate": not exact_duplicate and not equivalent,
        "family_history_checked": declared_trial,
        "cooldown_clear": not cooldown_active,
        "no_known_invalidity": not known_hard,
    }
    # A declaration/duplicate with no conclusive result is not scientific falsification.
    return checks, known_hard, {
        "family_key": plan.family_key.model_dump(mode="json"), "family_trial_count": len(family_trials),
        "equivalent_experiment_count": len(equivalent), "prior_failure_count": len(failures),
        "candidate_exact_duplicate": exact_duplicate, "semantic_hash": semantic_hash,
    }


def _gate_two(
    conn: Any, plan: G2Plan, artifacts: Mapping[str, dict[str, Any]], *, snapshot_dataset_ids: tuple[str, ...]
) -> tuple[dict[str, bool], bool, list[str], dict[str, Any]]:
    unknowns: list[str] = []
    manifests: list[DatasetManifest] = []
    hard_invalidity = False
    if plan.dataset_snapshot_ids != snapshot_dataset_ids:
        unknowns.append("G2_DATASET_SET_NOT_SNAPSHOT_PINNED")
    for artifact_id in plan.dataset_snapshot_ids:
        artifact = artifacts.get(artifact_id)
        registered = conn.execute(
            "SELECT 1 FROM dataset_manifests WHERE manifest_artifact_id=%s", (artifact_id,)
        ).fetchone()
        if artifact is None or artifact["schema_name"] != "data/dataset-manifest-v1" or not registered:
            unknowns.append(f"DATASET_MANIFEST_UNAVAILABLE:{artifact_id}")
            continue
        try:
            manifest = DatasetManifest.model_validate(artifact["content"])
        except ValidationError:
            hard_invalidity = True
            unknowns.append(f"DATASET_MANIFEST_INVALID:{artifact_id}")
            continue
        manifests.append(manifest)
        if manifest.quality_status in {QualityStatus.FAIL, QualityStatus.QUARANTINED}:
            hard_invalidity = True
    feature_artifact, errors = _artifact_by_id(artifacts, plan.feature_timing_artifact_id, "data/feature-timing-v1")
    unknowns.extend(errors)
    label_artifact, errors = _artifact_by_id(artifacts, plan.label_timing_artifact_id, "data/label-timing-v1")
    unknowns.extend(errors)
    universe_artifact, errors = _artifact_by_id(artifacts, plan.universe_artifact_id, "data/universe-membership-v1")
    unknowns.extend(errors)
    feature_rows: tuple[FeatureTimingRow, ...] = ()
    label_rows: tuple[LabelTimingRow, ...] = ()
    universe_rows: tuple[UniverseMembershipRow, ...] = ()
    try:
        if feature_artifact is not None:
            if tuple(feature_artifact["content"].get("dataset_snapshot_ids", ())) != snapshot_dataset_ids:
                unknowns.append("FEATURE_TIMING_DATASET_SET_NOT_SNAPSHOT_PINNED")
            feature_rows = tuple(FeatureTimingRow.model_validate(item) for item in feature_artifact["content"]["rows"])
        if label_artifact is not None:
            if tuple(label_artifact["content"].get("dataset_snapshot_ids", ())) != snapshot_dataset_ids:
                unknowns.append("LABEL_TIMING_DATASET_SET_NOT_SNAPSHOT_PINNED")
            label_rows = tuple(LabelTimingRow.model_validate(item) for item in label_artifact["content"]["rows"])
        if universe_artifact is not None:
            if tuple(universe_artifact["content"].get("dataset_snapshot_ids", ())) != snapshot_dataset_ids:
                unknowns.append("UNIVERSE_DATASET_SET_NOT_SNAPSHOT_PINNED")
            universe_rows = tuple(UniverseMembershipRow.model_validate(item) for item in universe_artifact["content"]["rows"])
    except (KeyError, TypeError, ValidationError):
        hard_invalidity = True
        unknowns.append("G2_TIMING_OR_UNIVERSE_ROWS_INVALID")
    if not feature_rows or not label_rows or not universe_rows:
        unknowns.append("G2_TIMING_OR_UNIVERSE_ROWS_EMPTY")
    availability = len(manifests) == len(snapshot_dataset_ids) and bool(manifests) and not unknowns
    checks = {
        "point_in_time": availability and all(m.as_of_time >= m.end_time for m in manifests)
        and all(row.latest_source_timestamp_used <= row.decision_time for row in feature_rows),
        "fresh_complete_data": availability and all(
            m.quality_status == QualityStatus.PASS and not m.missing_intervals
            and m.freshness_sec <= m.freshness_sla_sec for m in manifests
        ),
        "universe_survivorship": availability and bool(universe_rows) and all(
            row.source_available_at <= row.decision_time
            and row.effective_from <= row.decision_time
            and (row.effective_to is None or row.decision_time < row.effective_to)
            for row in universe_rows
        ),
        "no_label_leakage": availability and bool(label_rows) and all(
            row.outcome_end_time > row.decision_time and row.label_available_at >= row.outcome_end_time
            for row in label_rows
        ),
    }
    return checks, hard_invalidity, unknowns, {
        "dataset_count": len(manifests), "feature_row_count": len(feature_rows),
        "label_row_count": len(label_rows), "universe_row_count": len(universe_rows),
    }


def _gate_three(
    plan: G3Plan, artifacts: Mapping[str, dict[str, Any]], *, snapshot_dataset_ids: tuple[str, ...]
) -> tuple[dict[str, bool], list[str], dict[str, Any]]:
    unknowns: list[str] = []
    empirical_bound = True
    if plan.basis == "EMPIRICAL":
        assert plan.empirical_pattern_artifact_id is not None
        artifact = artifacts.get(plan.empirical_pattern_artifact_id)
        empirical_bound = (
            artifact is not None
            and artifact["schema_name"] == "research/empirical-pattern-v1"
            and tuple(artifact["content"].get("dataset_snapshot_ids", ())) == snapshot_dataset_ids
            and isinstance(artifact["content"].get("observations"), list)
            and bool(artifact["content"]["observations"])
            and all(isinstance(value, str) and value.strip() for value in artifact["content"]["observations"])
        )
        if not empirical_bound:
            unknowns.append("EMPIRICAL_PATTERN_ARTIFACT_NOT_BOUND")
    if plan.minimum_viable_test.dataset_snapshot_ids != snapshot_dataset_ids:
        unknowns.append("MINIMUM_TEST_DATASET_SET_NOT_SNAPSHOT_PINNED")
    checks = {
        "falsifiable_prediction": plan.prediction.outcome_id == plan.minimum_viable_test.outcome_id,
        "empirical_or_mechanism_basis": empirical_bound,
        "constraints_defined": bool(plan.constraints) and not unknowns,
    }
    return checks, unknowns, {
        "basis": plan.basis, "horizon_seconds": plan.horizon_seconds,
        "minimum_observations": plan.minimum_viable_test.minimum_observations,
    }


def _gate_four(
    plan: G4Plan, policy: GatePolicy, artifacts: Mapping[str, dict[str, Any]], *, snapshot_dataset_ids: tuple[str, ...]
) -> tuple[dict[str, bool], bool, list[str], dict[str, Any]]:
    unknowns: list[str] = []
    evidence_rows = [row for row in artifacts.values() if row["schema_name"] == "finance/cheap-economics-v1"]
    if len(evidence_rows) != 1:
        return ({check: False for check in ("sample_available", "cost_bounds", "capacity_feasible", "benchmark_compared")},
                False, ["CHEAP_ECONOMICS_EVIDENCE_MISSING_OR_AMBIGUOUS"], {})
    if policy.g4_mean_after_cost_lower is None or policy.g4_mean_excess_after_cost_lower is None:
        return ({check: False for check in ("sample_available", "cost_bounds", "capacity_feasible", "benchmark_compared")},
                False, ["G4_NUMERIC_POLICY_NOT_DECLARED"], {})
    try:
        evidence = G4Evidence.model_validate(evidence_rows[0]["content"])
    except ValidationError:
        return ({check: False for check in ("sample_available", "cost_bounds", "capacity_feasible", "benchmark_compared")},
                True, ["CHEAP_ECONOMICS_EVIDENCE_INVALID"], {})
    samples = evidence.samples
    if any(sample.dataset_snapshot_id not in snapshot_dataset_ids or sample.currency != plan.currency for sample in samples):
        unknowns.append("G4_SAMPLE_DATASET_OR_CURRENCY_MISMATCH")
    sample_ids = {sample.sample_id for sample in samples}
    benchmark_by_id = {sample.sample_id: sample for sample in evidence.benchmarks}
    capacity_by_id = {sample.sample_id: sample for sample in evidence.capacity}
    samples_by_id = {sample.sample_id: sample for sample in samples}
    bounds = plan.cost_bounds.model_dump()
    cost_bounded = all(
        bounds[name][0] <= getattr(sample, name) <= bounds[name][1]
        for sample in samples for name in bounds
    )
    capacity_feasible = all(
        observation.sample_id in sample_ids and observation.currency == plan.currency
        and observation.planned_notional <= observation.executable_notional
        and observation.planned_notional <= plan.capacity_limit
        for observation in evidence.capacity
    ) and sample_ids <= set(capacity_by_id)
    matching_benchmarks = all(
        benchmark.sample_id in sample_ids
        and benchmark.dataset_snapshot_id == samples_by_id[benchmark.sample_id].dataset_snapshot_id
        and benchmark.benchmark_id == plan.benchmark_id and benchmark.benchmark_version == plan.benchmark_version
        and benchmark.currency == plan.currency
        for benchmark in evidence.benchmarks
    ) and sample_ids <= set(benchmark_by_id)
    if not matching_benchmarks:
        unknowns.append("G4_BENCHMARK_SAMPLE_BINDING_MISMATCH")
    mean_after_cost = sum((sample.after_cost_pnl for sample in samples), Decimal("0")) / Decimal(len(samples))
    mean_excess = sum(
        (sample.after_cost_pnl - benchmark_by_id[sample.sample_id].after_cost_pnl for sample in samples if sample.sample_id in benchmark_by_id),
        Decimal("0"),
    ) / Decimal(len(samples))
    benchmark_passes = matching_benchmarks and (
        mean_after_cost >= policy.g4_mean_after_cost_lower
        and mean_excess >= policy.g4_mean_excess_after_cost_lower
    )
    checks = {
        "sample_available": len(samples) >= plan.minimum_samples and not unknowns,
        "cost_bounds": cost_bounded,
        "capacity_feasible": capacity_feasible,
        "benchmark_compared": benchmark_passes,
    }
    hard_invalidity = not cost_bounded or not capacity_feasible or (matching_benchmarks and not benchmark_passes)
    return checks, hard_invalidity, unknowns, {
        "sample_count": len(samples), "mean_after_cost_pnl": str(mean_after_cost),
        "mean_excess_after_cost_pnl": str(mean_excess), "benchmark_sample_count": len(evidence.benchmarks),
        "capacity_sample_count": len(evidence.capacity),
    }


def check_gate(
    store: Store, conn: Any, actor: Identity, snapshot: Any, obj: Mapping[str, Any], gate_id: int,
    input_artifacts: Iterable[str | Mapping[str, Any]],
) -> dict[str, Any]:
    """Return a report for G1--G4 from immutable artifacts and authenticated database state.

    ``snapshot`` must be the persisted ``evaluation_snapshots`` row (not merely its
    manifest) so the plan's creation time can be proved to predate evaluation.
    ``input_artifacts`` may carry IDs or artifact rows, but each ID is re-resolved via
    the authenticated store and its returned hash is what is reported for signing.
    """
    required = {
        1: ("not_duplicate", "family_history_checked", "cooldown_clear", "no_known_invalidity"),
        2: ("point_in_time", "fresh_complete_data", "universe_survivorship", "no_label_leakage"),
        3: ("falsifiable_prediction", "empirical_or_mechanism_basis", "constraints_defined"),
        4: ("sample_available", "cost_bounds", "capacity_feasible", "benchmark_compared"),
    }
    if gate_id not in required:
        raise DomainError("UNSUPPORTED_EARLY_GATE")
    actor.require("read")
    snapshot_manifest, snapshot_created_at = _snapshot(snapshot)
    candidate_id = obj.get("artifact_id")
    strategy_version_id = obj.get("object_id")
    if not isinstance(candidate_id, str) or not isinstance(strategy_version_id, str):
        raise DomainError("INVALID_CANDIDATE_OBJECT")
    candidate = store.artifact(conn, actor, candidate_id)
    artifacts = _bound_artifacts(store, conn, actor, input_artifacts)
    artifacts[candidate_id] = candidate
    bindings = {artifact_id: row["content_hash"] for artifact_id, row in artifacts.items()}
    plan, unknowns = _plan(
        artifacts, gate_id=gate_id, candidate_id=candidate_id, candidate_hash=candidate["content_hash"],
        snapshot_id=snapshot_manifest.get("snapshot_id", ""), snapshot_created_at=snapshot_created_at,
    )
    if plan is None:
        return _report(dict.fromkeys(required[gate_id], False), hard_invalidity=False, unknowns=unknowns,
                       metrics={}, artifacts=bindings)
    expected_policy_version = snapshot_manifest.get("gate_policy_versions", {}).get(str(gate_id))
    if gate_id in {1, 4}:
        policy, policy_unknowns = _policy(
            conn, artifacts, expected_version=expected_policy_version or "",
            snapshot_created_at=snapshot_created_at,
        )
        unknowns.extend(policy_unknowns)
        if policy is None:
            return _report(dict.fromkeys(required[gate_id], False), hard_invalidity=False, unknowns=unknowns,
                           metrics={}, artifacts=bindings)
    snapshot_dataset_ids = tuple(snapshot_manifest.get("dataset_snapshot_ids", ()))
    if gate_id == 1:
        assert plan.g1 is not None and policy is not None
        checks, hard_invalidity, metrics = _gate_one(
            conn, plan.g1, policy, strategy_version_id=strategy_version_id,
            candidate_hash=candidate["content_hash"],
        )
        if not checks["not_duplicate"] and not hard_invalidity:
            unknowns.append("EQUIVALENT_RESEARCH_NOT_CONCLUSIVELY_REJECTED")
        if not checks["family_history_checked"]:
            unknowns.append("G1_DECLARED_TRIAL_NOT_BOUND")
        if tuple(plan.g1.dataset_snapshot_ids) != snapshot_dataset_ids:
            checks["family_history_checked"] = False
            unknowns.append("G1_DATASET_SET_NOT_SNAPSHOT_PINNED")
    elif gate_id == 2:
        assert plan.g2 is not None
        checks, hard_invalidity, unknowns, metrics = _gate_two(
            conn, plan.g2, artifacts, snapshot_dataset_ids=snapshot_dataset_ids
        )
    elif gate_id == 3:
        assert plan.g3 is not None
        checks, unknowns, metrics = _gate_three(
            plan.g3, artifacts, snapshot_dataset_ids=snapshot_dataset_ids
        )
        hard_invalidity = False
    else:
        assert plan.g4 is not None and policy is not None
        checks, hard_invalidity, unknowns, metrics = _gate_four(
            plan.g4, policy, artifacts, snapshot_dataset_ids=snapshot_dataset_ids
        )
    return _report(checks, hard_invalidity=hard_invalidity, unknowns=unknowns, metrics=metrics,
                   artifacts=bindings)
