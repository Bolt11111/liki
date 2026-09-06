"""Strict contracts for the inference broker and controlled contexts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, ROUND_UP
from enum import StrEnum
from hashlib import sha256
from ipaddress import ip_address
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


def utcnow() -> datetime:
    return datetime.now(UTC)


def canonical_hash(value: Any) -> str:
    import json

    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Criticality(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class Classification(StrEnum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    SECRET = "SECRET"
    SEALED = "SEALED"


CLASSIFICATION_RANK = {
    Classification.PUBLIC: 0,
    Classification.INTERNAL: 1,
    Classification.CONFIDENTIAL: 2,
    Classification.SECRET: 3,
    Classification.SEALED: 4,
}


class CompletenessStatus(StrEnum):
    COMPLETE = "COMPLETE_FOR_CONTRACT"
    BLOCKING = "INCOMPLETE_BLOCKING"
    DECLARED_NONCRITICAL = "INCOMPLETE_DECLARED_NONCRITICAL"


class EvidenceRetrievalStatus(StrEnum):
    RETRIEVED = "RETRIEVED"
    NOT_RETRIEVED = "NOT_RETRIEVED"
    NOT_RELEVANT = "NOT_RELEVANT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    INDEX_LAG = "INDEX_LAG"


class ProviderHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_FAILED = "AUTH_FAILED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    OPEN_CIRCUIT = "OPEN_CIRCUIT"
    UNKNOWN = "UNKNOWN"


class IdentityAssurance(StrEnum):
    OFFICIAL_ATTESTED = "OFFICIAL_ATTESTED"
    PROVIDER_ASSERTED = "PROVIDER_ASSERTED"
    BLACK_BOX_ONLY = "BLACK_BOX_ONLY"
    UNKNOWN = "UNKNOWN"


class AttemptStatus(StrEnum):
    CREATED = "CREATED"
    TRANSPORT_SUCCESS = "TRANSPORT_SUCCESS"
    SCHEMA_SUCCESS = "SCHEMA_SUCCESS"
    SEMANTIC_ACCEPTED = "SEMANTIC_ACCEPTED"
    DECISION_USEFUL = "DECISION_USEFUL"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    NONRETRYABLE_FAILURE = "NONRETRYABLE_FAILURE"
    HIBERNATED = "HIBERNATED"


class AgentTaskContract(StrictModel):
    agent_run_id: str = Field(min_length=1)
    role: str = Field(min_length=1)
    question: str = Field(min_length=1)
    decision_authority: tuple[str, ...] = ()
    input_evidence_ids: tuple[str, ...] = ()
    required_evidence_classes: tuple[str, ...] = ()
    forbidden_evidence_classes: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    expected_artifact_schema: dict[str, Any]
    success_condition: str = Field(min_length=1)
    stop_condition: str = Field(min_length=1)
    max_inference_budget: dict[str, Any] = Field(default_factory=dict)
    max_tool_budget: dict[str, Any] = Field(default_factory=dict)
    independence_group_id: str | None = None
    parent_run_id: str | None = None

    @field_validator("expected_artifact_schema")
    @classmethod
    def valid_expected_artifact_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(value)
        return value


class MemoryItem(StrictModel):
    memory_id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    claim_type: str = Field(min_length=1)
    source_evidence_ids: tuple[str, ...] = Field(min_length=1)
    confidence_state: Literal["unverified", "candidate", "replicated", "invalidated"]
    market_scope: tuple[str, ...] = ()
    regime_scope: tuple[str, ...] = ()
    mechanism_scope: tuple[str, ...] = ()
    created_at: datetime
    last_revalidated_at: datetime | None = None
    policy_version: str = Field(min_length=1)
    classification: Classification = Classification.INTERNAL
    license_allows_external_egress: bool = True
    contamination_tags: tuple[str, ...] = ()
    known_counterevidence_ids: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()


class ReviewerIndependenceProfile(StrictModel):
    model_family: str = Field(min_length=1)
    model_version: str | None = None
    provider_correlation_domain: str = Field(min_length=1)
    provider_route_id: str = "unknown"
    reasoning_effort: str = "standard"
    reviewer_mandate: str = Field(min_length=1)
    prompt_template_version: str = Field(min_length=1)
    evidence_ordering_profile: str = Field(min_length=1)
    prior_verdicts_visible: bool = False
    shared_tools_or_retrieval_policy: str = Field(min_length=1)
    shared_upstream_or_contamination: tuple[str, ...] = ()

    @property
    def procedural_fingerprint(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class ReviewIndependenceAssessment(StrictModel):
    reviewer_count: int = Field(ge=0)
    distinct_model_families: int = Field(ge=0)
    distinct_correlation_domains: int = Field(ge=0)
    residual_same_model_correlation: bool
    residual_shared_upstream_correlation: bool


class InferenceRequest(StrictModel):
    inference_request_id: str = Field(default_factory=lambda: str(uuid4()))
    semantic_task_id: str = Field(min_length=1)
    task_class: str = Field(min_length=1)
    criticality: Criticality
    why_llm_needed: str = Field(min_length=1)
    expected_artifact_schema: dict[str, Any] = Field(min_length=1)
    expected_decision_impact: str = Field(min_length=1)
    preferred_reasoning_effort: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=16, max_length=256)
    allowed_provider_classes: tuple[str, ...] = ()
    fallback_policy_id: str = Field(min_length=1)
    max_call_cost_usd: Decimal | None = Field(default=None, ge=0)
    max_total_attempt_cost_usd: Decimal | None = Field(default=None, ge=0)
    max_latency_sec: float | None = Field(default=None, gt=0)
    min_semantic_acceptance: float = Field(default=0, ge=0, le=1)
    min_reliability: float = Field(default=0, ge=0, le=1)
    routing_benchmark_id: str | None = None
    requires_tools: bool = False
    parent_run_id: str | None = None
    campaign_id: str | None = None
    branch_id: str | None = None
    exploratory: bool = False

    @model_validator(mode="after")
    def has_meaningful_output(self) -> InferenceRequest:
        if not self.expected_decision_impact and not self.exploratory:
            raise ValueError("non-exploratory requests require an expected decision impact")
        return self

    @field_validator("expected_artifact_schema")
    @classmethod
    def valid_artifact_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(value)
        return value


class EvidenceItem(StrictModel):
    evidence_id: str = Field(min_length=1)
    evidence_class: str = Field(min_length=1)
    classification: Classification
    retrieval_status: EvidenceRetrievalStatus = EvidenceRetrievalStatus.RETRIEVED
    content: str | None = None
    content_hash: str | None = None
    material: bool = True
    license_allows_external_egress: bool = True
    canonical_source_id: str | None = None
    summary_source_ids: tuple[str, ...] = ()
    relevance_reason: str | None = None

    @model_validator(mode="after")
    def retrieval_has_content(self) -> EvidenceItem:
        if self.retrieval_status == EvidenceRetrievalStatus.RETRIEVED and not self.content:
            raise ValueError("retrieved evidence requires content")
        if self.retrieval_status != EvidenceRetrievalStatus.RETRIEVED and self.content:
            raise ValueError("unretrieved evidence cannot be silently represented as content")
        if self.retrieval_status == EvidenceRetrievalStatus.NOT_RELEVANT and not self.relevance_reason:
            raise ValueError("not-relevant evidence requires an explicit relevance reason")
        return self

    @property
    def effective_content_hash(self) -> str | None:
        return self.content_hash or (canonical_hash(self.content) if self.content is not None else None)


class ToolCapability(StrictModel):
    tool_id: str
    version: str
    purpose: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    deterministic: bool
    cost_model: str
    latency_model: str
    trust_level: Literal["trusted", "sandboxed", "external_untrusted"]
    side_effects: tuple[str, ...] = ()
    required_capabilities: tuple[str, ...] = ()
    known_failure_modes: tuple[str, ...] = ()

    @field_validator("input_schema", "output_schema")
    @classmethod
    def valid_tool_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(value)
        return value


class ContextManifest(StrictModel):
    context_manifest_id: str = Field(default_factory=lambda: str(uuid4()))
    compiler_version: str = "1"
    retrieval_version: str
    required_evidence_classes: tuple[str, ...]
    candidate_evidence_ids: tuple[str, ...]
    included_evidence_ids: tuple[str, ...]
    tool_addressable_evidence_ids: tuple[str, ...]
    excluded_evidence: dict[str, str]
    summary_artifact_ids: tuple[str, ...]
    truncation: dict[str, str]
    egress_decision: dict[str, Any]
    completeness_status: CompletenessStatus
    retrieval_query_fingerprint: str
    tool_expansion_ids: tuple[str, ...] = ()
    candidate_memory_ids: tuple[str, ...] = ()
    included_memory_ids: tuple[str, ...] = ()
    excluded_memory: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def manifest_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json", exclude={"context_manifest_id", "created_at"}))


class CompiledContext(StrictModel):
    system_prompt: str
    user_prompt: str
    manifest: ContextManifest
    tool_capabilities: tuple[ToolCapability, ...]


class Usage(StrictModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    cache_read_tokens: int | None = Field(default=None, ge=0)
    cache_write_tokens: int | None = Field(default=None, ge=0)
    token_count_method: str = "provider_reported"


class PricingPlan(StrictModel):
    price_plan_id: str
    effective_at: datetime
    fixed_request_usd: Decimal = Decimal("0")
    input_per_million_usd: Decimal = Decimal("0")
    output_per_million_usd: Decimal = Decimal("0")
    reasoning_per_million_usd: Decimal = Decimal("0")
    cache_read_per_million_usd: Decimal = Decimal("0")
    cache_write_per_million_usd: Decimal = Decimal("0")
    minimum_request_usd: Decimal = Decimal("0")
    bill_failed: bool = True
    bill_timeout: bool = True
    bill_cancelled: bool = True
    bill_partial: bool = True
    pricing_formula_id: str = "per_request_plus_tokens_v1"
    unknown_usage_reserve: Usage = Field(default_factory=Usage)
    tiered_rates: tuple[PricingTier, ...] = ()

    def cost_components(self, usage: Usage, *, outcome: AttemptStatus) -> tuple[Decimal, Decimal, int]:
        """Return fixed cost, token cost, and billable token count for one attempt."""
        billable = outcome not in {AttemptStatus.NONRETRYABLE_FAILURE, AttemptStatus.RETRYABLE_FAILURE}
        if outcome == AttemptStatus.RETRYABLE_FAILURE:
            billable = self.bill_timeout
        if outcome == AttemptStatus.NONRETRYABLE_FAILURE:
            billable = self.bill_failed
        if not billable:
            return Decimal("0"), Decimal("0"), 0
        resolved_usage = usage
        if usage.token_count_method == "unknown_conservative":
            resolved_usage = self.unknown_usage_reserve
        total_tokens = sum(
            value or 0
            for value in (
                resolved_usage.input_tokens,
                resolved_usage.output_tokens,
                resolved_usage.reasoning_tokens,
                resolved_usage.cache_read_tokens,
                resolved_usage.cache_write_tokens,
            )
        )
        tier = next(
            (
                candidate
                for candidate in self.tiered_rates
                if candidate.up_to_billed_tokens is None or total_tokens <= candidate.up_to_billed_tokens
            ),
            None,
        )
        token_cost = Decimal("0")
        for tokens, rate in (
            (resolved_usage.input_tokens, tier.input_per_million_usd if tier and tier.input_per_million_usd is not None else self.input_per_million_usd),
            (resolved_usage.output_tokens, tier.output_per_million_usd if tier and tier.output_per_million_usd is not None else self.output_per_million_usd),
            (resolved_usage.reasoning_tokens, tier.reasoning_per_million_usd if tier and tier.reasoning_per_million_usd is not None else self.reasoning_per_million_usd),
            (resolved_usage.cache_read_tokens, tier.cache_read_per_million_usd if tier and tier.cache_read_per_million_usd is not None else self.cache_read_per_million_usd),
            (resolved_usage.cache_write_tokens, tier.cache_write_per_million_usd if tier and tier.cache_write_per_million_usd is not None else self.cache_write_per_million_usd),
        ):
            if tokens is not None:
                token_cost += Decimal(tokens) * rate / Decimal("1000000")
        return self.fixed_request_usd, token_cost, total_tokens

    def cost(self, usage: Usage, *, outcome: AttemptStatus) -> Decimal:
        fixed_cost, token_cost, _ = self.cost_components(usage, outcome=outcome)
        total = fixed_cost + token_cost
        return max(total, self.minimum_request_usd).quantize(Decimal("0.000001"), rounding=ROUND_UP)


class PricingTier(StrictModel):
    """Rate tier selected from total billed tokens for a single documented request."""

    up_to_billed_tokens: int | None = Field(default=None, gt=0)
    input_per_million_usd: Decimal | None = Field(default=None, ge=0)
    output_per_million_usd: Decimal | None = Field(default=None, ge=0)
    reasoning_per_million_usd: Decimal | None = Field(default=None, ge=0)
    cache_read_per_million_usd: Decimal | None = Field(default=None, ge=0)
    cache_write_per_million_usd: Decimal | None = Field(default=None, ge=0)


class RouteCapabilities(StrictModel):
    context_window: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    reasoning_efforts: tuple[str, ...] = ()
    tools_supported: bool = False
    streaming_supported: bool = False
    continuation_supported: bool = False
    timeout_seconds: float = Field(gt=0)
    rate_limit_per_minute: int | None = Field(default=None, gt=0)


class TaskClassRouteMetrics(StrictModel):
    """Calibration measured on controlled common/challenger tasks, not self-report."""

    task_class: str = Field(min_length=1)
    semantic_acceptance: float = Field(ge=0, le=1)
    reliability: float = Field(ge=0, le=1)
    correction_rate: float = Field(ge=0, le=1, default=0)
    reversal_rate: float = Field(ge=0, le=1, default=0)
    sample_count: int = Field(ge=0, default=0)
    benchmark_id: str | None = None
    benchmarked_at: datetime | None = None


class ProviderRoute(StrictModel):
    route_id: str
    provider_class: str
    provider_id: str = "owner-configured"
    endpoint_id: str = "owner-configured"
    key_pool_id: str = "owner-configured"
    adapter: Literal["anthropic_messages", "openai_chat"]
    base_url: HttpUrl
    allowed_hosts: tuple[str, ...]
    model: str
    claimed_model_name: str
    model_family: str
    model_version: str | None = None
    identity_assurance: IdentityAssurance = IdentityAssurance.UNKNOWN
    upstream_correlation_domain: str = Field(min_length=1)
    egress_clearance: Classification
    retention_known: bool = False
    may_train_on_prompts: bool | None = None
    license_approved: bool = True
    sealed_evaluator_approved: bool = False
    last_capability_benchmark_at: datetime | None = None
    behavioral_drift_detected_at: datetime | None = None
    health: ProviderHealth = ProviderHealth.UNKNOWN
    capabilities: RouteCapabilities
    pricing: PricingPlan
    quality_floor: float = Field(ge=0, le=1, default=0)
    reliability_floor: float = Field(ge=0, le=1, default=0)
    observed_semantic_acceptance: float = Field(ge=0, le=1, default=0.5)
    observed_reliability: float = Field(ge=0, le=1, default=0.5)
    expected_rework_usd: Decimal = Decimal("0")
    task_metrics: tuple[TaskClassRouteMetrics, ...] = ()

    @field_validator("base_url")
    @classmethod
    def safe_base_url(cls, value: HttpUrl) -> HttpUrl:
        host = value.host or ""
        if value.scheme != "https" or not host:
            raise ValueError("inference provider base URL must be public HTTPS")
        try:
            address = ip_address(host)
        except ValueError:
            address = None
        if host.casefold() == "localhost" or (address is not None and not address.is_global):
            raise ValueError("inference provider base URL must be public HTTPS")
        if "@" in str(value):
            raise ValueError("provider base URL cannot include user info")
        return value

    @model_validator(mode="after")
    def configured_host_only(self) -> ProviderRoute:
        host = self.base_url.host or ""
        normalized_hosts = {allowed.casefold().rstrip(".") for allowed in self.allowed_hosts}
        if not normalized_hosts or host.casefold().rstrip(".") not in normalized_hosts:
            raise ValueError("base URL host must be explicitly allowlisted")
        if not self.license_approved:
            raise ValueError("provider route has not passed license and terms review")
        if CLASSIFICATION_RANK[self.egress_clearance] >= CLASSIFICATION_RANK[Classification.CONFIDENTIAL] and not self.retention_known:
            raise ValueError("unknown retention cannot clear confidential data")
        if self.egress_clearance == Classification.SEALED and not self.sealed_evaluator_approved:
            raise ValueError("SEALED egress requires isolated evaluator approval")
        return self


class RawProviderResponse(StrictModel):
    provider_request_id: str | None = None
    text: str
    usage: Usage = Field(default_factory=Usage)
    model_version: str | None = None
    stop_reason: str | None = None
    http_status: int = Field(ge=100, le=599)


class InferenceAttempt(StrictModel):
    inference_attempt_id: str = Field(default_factory=lambda: str(uuid4()))
    inference_request_id: str
    attempt_no: int = Field(ge=1)
    provider_route_id: str
    provider_request_id: str | None = None
    lease_fence: int
    model_family: str
    model_version: str | None = None
    upstream_correlation_domain: str | None = None
    reasoning_effort: str
    prompt_manifest_hash: str
    system_prompt_hash: str | None = None
    task_prompt_hash: str | None = None
    tool_schema_hash: str | None = None
    sampling_parameters: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
    status: AttemptStatus = AttemptStatus.CREATED
    http_status: int | None = None
    error_class: str | None = None
    usage: Usage = Field(default_factory=Usage)
    pricing_plan_id: str | None = None
    fixed_call_cost_usd: Decimal | None = Field(default=None, ge=0)
    token_cost_usd: Decimal | None = Field(default=None, ge=0)
    billed_tokens: int | None = Field(default=None, ge=0)
    provider_reported_model: str | None = None
    provider_reported_cost_usd: Decimal | None = Field(default=None, ge=0)
    total_cost_usd: Decimal = Decimal("0")
    latency_ms: int | None = None
    output_artifact: dict[str, Any] | None = None
    response_hash: str | None = None


class InferenceResult(StrictModel):
    request_id: str
    status: AttemptStatus
    artifact: dict[str, Any] | None = None
    failure_reason: str | None = None
    route_id: str | None = None
