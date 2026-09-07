from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from liki.inference import (
    AgentTaskContract,
    AttemptStatus,
    Classification,
    ContextCompiler,
    ContextRejected,
    Criticality,
    EvidenceItem,
    EvidenceRetrievalStatus,
    InferenceBroker,
    InferenceRequest,
    MemoryRetrievalFirewall,
    PricingPlan,
    PricingTier,
    ProviderRoute,
    ReviewIndependencePolicy,
    ReviewerIndependenceProfile,
    RetryPolicy,
    SQLiteTestInferenceBackend,
    TaskClassRouteMetrics,
    ToolCapability,
    Usage,
)
from liki.inference.adapters import AnthropicMessagesAdapter, OpenAIChatAdapter, ProviderTransportError
from liki.inference.types import IdentityAssurance, MemoryItem, ProviderHealth, RawProviderResponse, RouteCapabilities


async def key(_: ProviderRoute) -> str:
    return "test-secret"


async def public_dns(_: str, __: int) -> tuple[str, ...]:
    return ("8.8.8.8",)


def route(route_id: str, adapter: str = "openai_chat", domain: str | None = None, **overrides: object) -> ProviderRoute:
    values: dict[str, object] = {
        "route_id": route_id,
        "provider_class": "llm",
        "adapter": adapter,
        "base_url": "https://provider.test",
        "allowed_hosts": ("provider.test",),
        "model": "a-model",
        "claimed_model_name": "a-model",
        "model_family": route_id,
        "identity_assurance": IdentityAssurance.PROVIDER_ASSERTED,
        "upstream_correlation_domain": domain or route_id,
        "egress_clearance": Classification.INTERNAL,
        "retention_known": True,
        "may_train_on_prompts": False,
        "health": ProviderHealth.HEALTHY,
        "capabilities": RouteCapabilities(context_window=100_000, max_output_tokens=1000, timeout_seconds=3),
        "pricing": PricingPlan(price_plan_id=route_id, effective_at=datetime.now(UTC), fixed_request_usd=Decimal("0.10")),
        "observed_semantic_acceptance": 0.8,
        "observed_reliability": 0.8,
    }
    values.update(overrides)
    return ProviderRoute(**values)


def request(**overrides: object) -> InferenceRequest:
    values: dict[str, object] = {
        "semantic_task_id": "semantic-1",
        "task_class": "review",
        "criticality": Criticality.NORMAL,
        "why_llm_needed": "semantic evidence synthesis",
        "expected_artifact_schema": {"type": "object", "required": ["verdict"], "properties": {"verdict": {"type": "string"}}, "additionalProperties": False},
        "expected_decision_impact": "blocks a candidate",
        "preferred_reasoning_effort": "standard",
        "idempotency_key": "x" * 16,
        "fallback_policy_id": "default",
        "max_total_attempt_cost_usd": Decimal("5"),
    }
    values.update(overrides)
    return InferenceRequest(**values)


def contract(**overrides: object) -> AgentTaskContract:
    values: dict[str, object] = {
        "agent_run_id": "run", "role": "skeptic", "question": "Does it hold?",
        "expected_artifact_schema": request().expected_artifact_schema,
        "success_condition": "valid verdict", "stop_condition": "insufficient evidence",
    }
    values.update(overrides)
    return AgentTaskContract(**values)


def compiled(req: InferenceRequest, provider: ProviderRoute, evidence: tuple[EvidenceItem, ...] | None = None, **kwargs: object):
    return ContextCompiler().compile(
        req, contract(), provider,
        evidence or (EvidenceItem(evidence_id="raw-1", evidence_class="raw_results", classification=Classification.INTERNAL, content="evidence"),),
        required_evidence_classes=("raw_results",), retrieval_version="idx-1", retrieval_query="candidate 1", **kwargs,
    )


class Success:
    async def invoke(self, *_: object) -> RawProviderResponse:
        return RawProviderResponse(text='{"verdict":"reject"}', http_status=200)


def test_80_percent_faults_fallback_across_independent_domains() -> None:
    primary, shared_key, fallback = route("one", domain="shared"), route("two", domain="shared"), route("three")

    class FourOfFive:
        def __init__(self) -> None:
            self.calls = 0

        async def invoke(self, routed: ProviderRoute, *_: object) -> RawProviderResponse:
            from liki.inference import ProviderTransportError
            if routed.route_id == "three":
                return RawProviderResponse(text='{"verdict":"fallback"}', http_status=200)
            self.calls += 1
            if self.calls % 5:
                raise ProviderTransportError("http_503")
            return RawProviderResponse(text='{"verdict":"primary"}', http_status=200)

    flaky = FourOfFive()
    backend = SQLiteTestInferenceBackend()
    broker = InferenceBroker(backend, [primary, shared_key, fallback], {"openai_chat": flaky}, retry_policy=RetryPolicy(same_route_retries=0, circuit_failure_threshold=10))
    outcomes = []
    for index in range(5):
        req = request(idempotency_key=f"fault-{index:011d}")
        outcomes.append(asyncio.run(broker.run(req, compiled(req, primary), estimated_usage=Usage(input_tokens=20))))
    assert all(outcome.status == AttemptStatus.SEMANTIC_ACCEPTED for outcome in outcomes)
    assert sum(outcome.route_id == "three" for outcome in outcomes) == 4
    attempted_routes = {row[0] for row in backend.connection.execute("SELECT route_id FROM inference_attempts")}
    assert "two" not in attempted_routes  # A shared upstream is not fallback diversity.


def test_malformed_refusal_and_truncation_are_never_semantic_success() -> None:
    provider, alternate = route("one"), route("two")

    class Responses:
        def __init__(self) -> None:
            self.results = [
                RawProviderResponse(text="I cannot safely answer", http_status=200),
                RawProviderResponse(text='{"verdict":"ok"}', http_status=200, stop_reason="max_tokens"),
                RawProviderResponse(text="not-json", http_status=200),
            ]

        async def invoke(self, *_: object) -> RawProviderResponse:
            return self.results.pop(0)

    backend = SQLiteTestInferenceBackend()
    broker = InferenceBroker(backend, [provider, alternate], {"openai_chat": Responses()}, retry_policy=RetryPolicy(same_route_retries=0))
    req = request()
    result = asyncio.run(broker.run(req, compiled(req, provider), estimated_usage=Usage()))
    assert result.status == AttemptStatus.HIBERNATED
    errors = [row[0] for row in backend.connection.execute("SELECT json_extract(attempt_json, '$.error_class') FROM inference_attempts")]
    assert errors == ["provider_refusal", "truncated_response"]


def test_route_economics_uses_task_calibration_and_configured_tier_prices() -> None:
    fixed = route("fixed", pricing=PricingPlan(price_plan_id="fixed", effective_at=datetime.now(UTC), fixed_request_usd=Decimal("0.80")))
    token = route(
        "token",
        pricing=PricingPlan(
            price_plan_id="token", effective_at=datetime.now(UTC), input_per_million_usd=Decimal("1"),
            tiered_rates=(PricingTier(up_to_billed_tokens=100_000, input_per_million_usd=Decimal("0.5")),),
        ),
        task_metrics=(TaskClassRouteMetrics(task_class="review", semantic_acceptance=0.9, reliability=0.9, sample_count=100, benchmark_id="common"),),
    )
    req = request(min_semantic_acceptance=0.7, min_reliability=0.7)
    routes = InferenceBroker(SQLiteTestInferenceBackend(), [fixed, token], {}).select_routes(req, compiled(req, fixed), Usage(input_tokens=50_000))
    assert [item.route_id for item in routes] == ["token", "fixed"]
    assert token.pricing.cost(Usage(input_tokens=50_000), outcome=AttemptStatus.SEMANTIC_ACCEPTED) == Decimal("0.025000")


def test_reservations_fences_reconciliation_hibernation_and_revival_are_durable() -> None:
    backend = SQLiteTestInferenceBackend()
    provider = route("one")
    req = request(max_total_attempt_cost_usd=Decimal("0.15"))
    context = compiled(req, provider)
    backend.create_or_get(req, context.manifest)
    first = backend.claim_attempt(req.inference_request_id, "one", 10)
    second = backend.claim_attempt(req.inference_request_id, "one", 10)
    assert backend.reserve_cost(req.inference_request_id, first.inference_attempt_id, Decimal("0.10"))
    assert not backend.reserve_cost(req.inference_request_id, second.inference_attempt_id, Decimal("0.10"))
    accepted = second.model_copy(update={"status": AttemptStatus.SEMANTIC_ACCEPTED, "completed_at": datetime.now(UTC), "output_artifact": {"verdict": "ok"}})
    assert backend.finish_attempt(accepted)
    stale = first.model_copy(update={"status": AttemptStatus.SEMANTIC_ACCEPTED, "completed_at": datetime.now(UTC), "output_artifact": {"verdict": "stale"}})
    assert not backend.finish_attempt(stale)
    persisted_stale = backend.connection.execute(
        "SELECT attempt_json FROM inference_attempts WHERE attempt_id=?", (first.inference_attempt_id,)
    ).fetchone()[0]
    assert json.loads(persisted_stale)["status"] == AttemptStatus.HIBERNATED
    assert backend.connection.execute(
        "SELECT COUNT(*) FROM inference_events WHERE event_type='late_result_deduplicated'"
    ).fetchone()[0] == 1
    assert not backend.reconcile_attempt_cost(req.inference_request_id, second.inference_attempt_id, Decimal("0.11"))
    assert backend.connection.execute("SELECT COUNT(*) FROM inference_events WHERE event_type='BILLING_RECONCILIATION_ERROR'").fetchone()[0] == 1
    reconciled = json.loads(
        backend.connection.execute(
            "SELECT attempt_json FROM inference_attempts WHERE attempt_id=?", (second.inference_attempt_id,)
        ).fetchone()[0]
    )
    assert reconciled["provider_reported_cost_usd"] == "0.11"
    pending = request(idempotency_key="pending-task-0001")
    backend.create_or_get(pending, compiled(pending, provider).manifest)
    backend.hibernate(pending.inference_request_id, "provider_outage")
    assert backend.revive(pending.inference_request_id, "health_recovered")


def test_failed_attempt_cost_remains_in_the_semantic_budget() -> None:
    backend = SQLiteTestInferenceBackend()
    provider = route("one")
    req = request(max_total_attempt_cost_usd=Decimal("0.15"))
    backend.create_or_get(req, compiled(req, provider).manifest)
    first = backend.claim_attempt(req.inference_request_id, provider.route_id, 10)
    assert backend.reserve_cost(req.inference_request_id, first.inference_attempt_id, Decimal("0.10"))
    failed = first.model_copy(
        update={
            "status": AttemptStatus.RETRYABLE_FAILURE,
            "completed_at": datetime.now(UTC),
            "total_cost_usd": Decimal("0.10"),
        }
    )
    assert backend.finish_attempt(failed)
    second = backend.claim_attempt(req.inference_request_id, provider.route_id, 10)
    assert not backend.reserve_cost(req.inference_request_id, second.inference_attempt_id, Decimal("0.10"))


def test_critical_context_rejects_any_unavailable_material_required_evidence() -> None:
    provider = route("one", egress_clearance=Classification.INTERNAL)
    critical = request(criticality=Criticality.CRITICAL)
    evidence = (
        EvidenceItem(evidence_id="raw-visible", evidence_class="raw_results", classification=Classification.INTERNAL, content="visible"),
        EvidenceItem(evidence_id="raw-secret", evidence_class="raw_results", classification=Classification.SECRET, content="withheld"),
        EvidenceItem(evidence_id="adverse", evidence_class="adverse_facts", classification=Classification.INTERNAL, retrieval_status=EvidenceRetrievalStatus.NOT_RELEVANT, relevance_reason="no adverse evidence in declared scope"),
    )
    with pytest.raises(ContextRejected, match="raw_results"):
        compiled(critical, provider, evidence)


def test_context_rejects_unregistered_or_side_effecting_tool_access() -> None:
    provider = route("one")
    req = request()
    with pytest.raises(ContextRejected, match="unregistered"):
        ContextCompiler().compile(
            req,
            contract(allowed_tools=("not-registered",)),
            provider,
            (EvidenceItem(evidence_id="raw", evidence_class="raw_results", classification=Classification.INTERNAL, content="raw"),),
            required_evidence_classes=("raw_results",),
            retrieval_version="1",
            retrieval_query="q",
        )
    write_tool = ToolCapability(
        tool_id="write",
        version="1",
        purpose="mutation",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        deterministic=True,
        cost_model="none",
        latency_model="fast",
        trust_level="trusted",
        side_effects=("write",),
    )
    with pytest.raises(ContextRejected, match="side-effecting"):
        ContextCompiler().compile(
            req,
            contract(allowed_tools=("write",)),
            provider,
            (EvidenceItem(evidence_id="raw", evidence_class="raw_results", classification=Classification.INTERNAL, content="raw"),),
            required_evidence_classes=("raw_results",),
            retrieval_version="1",
            retrieval_query="q",
            tools=(write_tool,),
        )


def test_route_selection_can_require_a_common_calibration_benchmark() -> None:
    req = request(routing_benchmark_id="common")
    benchmarked = route(
        "benchmarked",
        task_metrics=(
            TaskClassRouteMetrics(
                task_class="review",
                semantic_acceptance=0.8,
                reliability=0.8,
                sample_count=1,
                benchmark_id="common",
            ),
        ),
    )
    incomparable = route(
        "incomparable",
        task_metrics=(
            TaskClassRouteMetrics(
                task_class="review",
                semantic_acceptance=1,
                reliability=1,
                sample_count=100,
                benchmark_id="different",
            ),
        ),
    )
    broker = InferenceBroker(SQLiteTestInferenceBackend(), (benchmarked, incomparable), {})
    assert [route.route_id for route in broker.select_routes(req, compiled(req, benchmarked), Usage())] == ["benchmarked"]
    broker = InferenceBroker(
        SQLiteTestInferenceBackend(), (benchmarked, incomparable), {"openai_chat": Success()}
    )
    assert [route.route_id for route in broker.select_routes(req, compiled(req, benchmarked), Usage())] == ["benchmarked"]


def test_context_omission_egress_tool_expansion_memory_and_review_independence() -> None:
    provider = route("one", egress_clearance=Classification.INTERNAL)
    critical = request(criticality=Criticality.CRITICAL)
    absence = EvidenceItem(evidence_id="adverse", evidence_class="adverse_facts", classification=Classification.INTERNAL, retrieval_status=EvidenceRetrievalStatus.NOT_RELEVANT, relevance_reason="search found no adverse fact")
    with pytest.raises(ContextRejected, match="critical context"):
        compiled(critical, provider, (absence,))  # raw_results remains required and absent
    secret = EvidenceItem(evidence_id="credential", evidence_class="raw_results", classification=Classification.SECRET, content="not-a-real-key")
    context = compiled(request(), provider, (secret,))
    assert context.manifest.excluded_evidence["credential"] == "secret_never_in_prompt"
    assert "not-a-real-key" not in context.user_prompt
    tool = ToolCapability(tool_id="read-evidence", version="1", purpose="read", input_schema={"type": "object"}, output_schema={"type": "object"}, deterministic=True, cost_model="none", latency_model="fast", trust_level="trusted")
    tool_contract = contract(allowed_tools=("read-evidence",))
    evidence = EvidenceItem(evidence_id="licensed", evidence_class="raw_results", classification=Classification.INTERNAL, content="licensed")
    pack = ContextCompiler().compile(request(), tool_contract, provider, (evidence,), required_evidence_classes=("raw_results",), retrieval_version="1", retrieval_query="q", tools=(tool,), tool_addressable_ids=("licensed",), token_budget=1)
    with pytest.raises(ContextRejected, match="license"):
        ContextCompiler.record_tool_expansion(pack.manifest, evidence.model_copy(update={"license_allows_external_egress": False}), provider)
    memory = MemoryItem(memory_id="m", claim="old verdict", claim_type="verdict", source_evidence_ids=("e",), confidence_state="candidate", created_at=datetime.now(UTC), policy_version="p", contamination_tags=("same_model_review",))
    assert not MemoryRetrievalFirewall().retrieve((memory,), purpose="review", role="skeptic", fresh_independent_review=True)
    profiles = [ReviewerIndependenceProfile(model_family="same", provider_correlation_domain="same", reviewer_mandate=mandate, prompt_template_version="1", evidence_ordering_profile=order, shared_tools_or_retrieval_policy="p") for mandate, order in (("attack", "reverse"), ("replicate", "forward"))]
    ReviewIndependencePolicy().validate_batch(profiles, 2)
    with pytest.raises(ContextRejected, match="review-padding"):
        ReviewIndependencePolicy().validate_batch((profiles[0], profiles[0]), 2)


def test_native_adapters_use_provider_wire_contracts_and_reject_ssrf_endpoints() -> None:
    observed: list[httpx.Request] = []

    async def handler(request_: httpx.Request) -> httpx.Response:
        observed.append(request_)
        if request_.url.path == "/v1/messages":
            return httpx.Response(200, json={"content": [{"type": "text", "text": "{}"}], "usage": {"input_tokens": 1, "output_tokens": 2}, "model": "claude", "stop_reason": "end_turn"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 2}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        asyncio.run(AnthropicMessagesAdapter(client, key, public_dns).invoke(route("anth", "anthropic_messages"), "sys", "prompt", "standard"))
        asyncio.run(OpenAIChatAdapter(client, key, public_dns).invoke(route("oai"), "sys", "prompt", "standard"))
    finally:
        asyncio.run(client.aclose())
    assert observed[0].url.path == "/v1/messages"
    assert observed[0].headers["anthropic-version"] == "2023-06-01"
    assert observed[1].url.path == "/v1/chat/completions"
    with pytest.raises(ValueError, match="public HTTPS"):
        route("bad", base_url="http://127.0.0.1", allowed_hosts=("127.0.0.1",))
    with pytest.raises(ValueError, match="isolated evaluator"):
        route("sealed", egress_clearance=Classification.SEALED)


def test_adapter_rejects_private_dns_before_resolving_a_credential() -> None:
    requested = False

    async def private_dns(_: str, __: int) -> tuple[str, ...]:
        return ("127.0.0.1",)

    async def should_not_resolve_key(_: ProviderRoute) -> str:
        nonlocal requested
        requested = True
        return "test-secret"

    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
    try:
        with pytest.raises(ProviderTransportError, match="unsafe_provider_dns_resolution"):
            asyncio.run(OpenAIChatAdapter(client, should_not_resolve_key, private_dns).invoke(route("dns"), "sys", "prompt", "standard"))
    finally:
        asyncio.run(client.aclose())
    assert not requested


def test_partial_usage_is_conservatively_reserved_and_cannot_bypass_call_limit() -> None:
    provider = route(
        "partial-usage",
        pricing=PricingPlan(
            price_plan_id="partial-usage",
            effective_at=datetime.now(UTC),
            input_per_million_usd=Decimal("1"),
            output_per_million_usd=Decimal("1"),
            unknown_usage_reserve=Usage(input_tokens=1_000, output_tokens=200),
        ),
    )
    req = request(max_call_cost_usd=Decimal("0.000200"))
    broker = InferenceBroker(SQLiteTestInferenceBackend(), (provider,), {})
    conservative_usage = broker._conservative_usage(provider, Usage(input_tokens=100))
    assert conservative_usage.input_tokens == 100
    assert conservative_usage.output_tokens == 200
    assert broker.select_routes(req, compiled(req, provider), Usage(input_tokens=100)) == []


def test_complete_provider_usage_releases_unused_pre_call_reservation() -> None:
    provider = route(
        "settlement",
        pricing=PricingPlan(
            price_plan_id="settlement",
            effective_at=datetime.now(UTC),
            input_per_million_usd=Decimal("1"),
            output_per_million_usd=Decimal("1"),
            unknown_usage_reserve=Usage(
                input_tokens=100_000,
                output_tokens=100_000,
                reasoning_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=0,
            ),
        ),
    )

    class ActualUsage:
        async def invoke(self, *_: object) -> RawProviderResponse:
            return RawProviderResponse(
                text='{"verdict":"ok"}',
                usage=Usage(
                    input_tokens=10,
                    output_tokens=20,
                    reasoning_tokens=0,
                    cache_read_tokens=0,
                    cache_write_tokens=0,
                ),
                http_status=200,
            )

    req = request(idempotency_key="actual-settlement")
    backend = SQLiteTestInferenceBackend()
    result = asyncio.run(
        InferenceBroker(backend, (provider,), {"openai_chat": ActualUsage()}).run(
            req, compiled(req, provider), estimated_usage=Usage(input_tokens=100_000),
        )
    )
    assert result.status == AttemptStatus.SEMANTIC_ACCEPTED
    total_cost = json.loads(backend.connection.execute("SELECT attempt_json FROM inference_attempts").fetchone()[0])["total_cost_usd"]
    assert Decimal(total_cost) == Decimal("0.000030")


def test_tool_expansion_updates_the_context_package_and_manifest() -> None:
    provider = route("expand")
    req = request()
    evidence = EvidenceItem(
        evidence_id="appendix",
        evidence_class="raw_results",
        classification=Classification.INTERNAL,
        content="counterexample",
    )
    tool = ToolCapability(
        tool_id="evidence-read",
        version="1",
        purpose="read evidence",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        deterministic=True,
        cost_model="none",
        latency_model="fast",
        trust_level="trusted",
    )
    initial = ContextCompiler().compile(
        req,
        contract(allowed_tools=("evidence-read",)),
        provider,
        (evidence,),
        required_evidence_classes=("raw_results",),
        retrieval_version="idx-1",
        retrieval_query="candidate 1",
        tools=(tool,),
        tool_addressable_ids=("appendix",),
        token_budget=1,
    )
    expanded = ContextCompiler.apply_tool_expansion(initial, evidence, provider)
    package = json.loads(expanded.user_prompt)
    assert expanded.manifest.tool_expansion_ids == ("appendix",)
    assert package["manifest_hash"] == expanded.manifest.manifest_hash
    assert package["tool_expansions"] == [
        {
            "evidence_id": "appendix",
            "evidence_class": "raw_results",
            "canonical_source_id": None,
            "content": "counterexample",
        }
    ]
    with pytest.raises(ContextRejected, match="already recorded"):
        ContextCompiler.apply_tool_expansion(expanded, evidence, provider)
