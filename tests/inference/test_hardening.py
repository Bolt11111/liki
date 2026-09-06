from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from liki.inference import (
    AgentTaskContract,
    AttemptStatus,
    Classification,
    ContextCompiler,
    ContextRejected,
    Criticality,
    EvidenceItem,
    IdempotencyConflict,
    InferenceBroker,
    InferenceRequest,
    PricingPlan,
    ProviderRoute,
    SQLiteTestInferenceBackend,
    Usage,
)
from liki.inference.types import IdentityAssurance, MemoryItem, ProviderHealth, RawProviderResponse, RouteCapabilities


def route(route_id: str, **overrides: object) -> ProviderRoute:
    values: dict[str, object] = {
        "route_id": route_id,
        "provider_class": "llm",
        "provider_id": "provider",
        "endpoint_id": f"endpoint-{route_id}",
        "key_pool_id": f"keys-{route_id}",
        "adapter": "openai_chat",
        "base_url": "https://provider.test",
        "allowed_hosts": ("provider.test",),
        "model": "configured-model",
        "claimed_model_name": "configured-model",
        "model_family": route_id,
        "identity_assurance": IdentityAssurance.PROVIDER_ASSERTED,
        "upstream_correlation_domain": route_id,
        "egress_clearance": Classification.CONFIDENTIAL,
        "retention_known": True,
        "may_train_on_prompts": False,
        "health": ProviderHealth.HEALTHY,
        "capabilities": RouteCapabilities(context_window=10_000, max_output_tokens=100, timeout_seconds=2),
        "pricing": PricingPlan(
            price_plan_id=route_id,
            effective_at=datetime.now(UTC),
            input_per_million_usd=Decimal("1"),
            output_per_million_usd=Decimal("1"),
            unknown_usage_reserve=Usage(input_tokens=20, output_tokens=20),
        ),
    }
    values.update(overrides)
    return ProviderRoute(**values)


def request(**overrides: object) -> InferenceRequest:
    values: dict[str, object] = {
        "semantic_task_id": "review-1",
        "task_class": "review",
        "criticality": Criticality.CRITICAL,
        "why_llm_needed": "adversarial semantic judgement",
        "expected_artifact_schema": {
            "type": "object",
            "required": ["verdict"],
            "properties": {"verdict": {"type": "string"}},
            "additionalProperties": False,
        },
        "expected_decision_impact": "blocks promotion",
        "preferred_reasoning_effort": "standard",
        "idempotency_key": "hardening-key-0001",
        "fallback_policy_id": "independent-only",
        "max_total_attempt_cost_usd": Decimal("1"),
    }
    values.update(overrides)
    return InferenceRequest(**values)


def contract(req: InferenceRequest, **overrides: object) -> AgentTaskContract:
    values: dict[str, object] = {
        "agent_run_id": "run-1",
        "role": "adversarial-reviewer",
        "question": "Is the claim justified?",
        "expected_artifact_schema": req.expected_artifact_schema,
        "success_condition": "a schema-valid, evidence-backed verdict",
        "stop_condition": "return unknown when evidence is insufficient",
    }
    values.update(overrides)
    return AgentTaskContract(**values)


def context(
    req: InferenceRequest,
    provider: ProviderRoute,
    *,
    task_contract: AgentTaskContract | None = None,
    **kwargs: object,
):
    return ContextCompiler().compile(
        req,
        task_contract or contract(req),
        provider,
        (
            EvidenceItem(
                evidence_id="raw",
                evidence_class="raw_results",
                classification=Classification.CONFIDENTIAL,
                content="raw result",
            ),
            EvidenceItem(
                evidence_id="adverse",
                evidence_class="adverse_facts",
                classification=Classification.CONFIDENTIAL,
                retrieval_status="NOT_RELEVANT",
                relevance_reason="no adverse facts found in this retrieval scope",
            ),
        ),
        required_evidence_classes=("raw_results",),
        retrieval_version="test-index-1",
        retrieval_query="claim",
        **kwargs,
    )


def test_critical_context_requires_declared_inputs_and_secure_fallback() -> None:
    provider = route("primary")
    req = request()
    with pytest.raises(ContextRejected, match="missing"):
        context(req, provider, task_contract=contract(req, input_evidence_ids=("missing",)))

    compiled = context(req, provider)
    unsafe_fallback = route(
        "unsafe",
        egress_clearance=Classification.CONFIDENTIAL,
        retention_known=True,
        may_train_on_prompts=True,
    )
    broker = InferenceBroker(SQLiteTestInferenceBackend(), (unsafe_fallback,), {"openai_chat": object()})
    assert broker.select_routes(req, compiled, Usage(input_tokens=10)) == []


def test_timeout_reserves_conservative_cost_and_can_be_revived() -> None:
    class SlowAdapter:
        async def invoke(self, *_: object) -> RawProviderResponse:
            await asyncio.sleep(0.01)
            return RawProviderResponse(text='{"verdict":"late"}', http_status=200)

    provider = route("slow", capabilities=RouteCapabilities(context_window=10_000, max_output_tokens=100, timeout_seconds=0.1))
    req = request(criticality=Criticality.NORMAL, idempotency_key="timeout-key-00001", max_latency_sec=0.001)
    backend = SQLiteTestInferenceBackend()
    result = asyncio.run(InferenceBroker(backend, (provider,), {"openai_chat": SlowAdapter()}).run(req, context(req, provider), estimated_usage=Usage(input_tokens=20)))
    assert result.status == AttemptStatus.HIBERNATED
    assert backend.revive(req.inference_request_id, "provider recovered")
    attempt_json = backend.connection.execute("SELECT attempt_json FROM inference_attempts").fetchone()[0]
    assert Decimal(str(json.loads(attempt_json)["total_cost_usd"])) >= Decimal("0.000040")


def test_fenced_json_recovery_and_idempotency_context_conflict() -> None:
    class FencedResponse:
        async def invoke(self, *_: object) -> RawProviderResponse:
            return RawProviderResponse(text='```json\n{"verdict":"unknown"}\n```', http_status=200)

    provider = route("fenced")
    req = request(idempotency_key="fenced-key-00001")
    compiled = context(req, provider)
    backend = SQLiteTestInferenceBackend()
    result = asyncio.run(InferenceBroker(backend, (provider,), {"openai_chat": FencedResponse()}).run(req, compiled, estimated_usage=Usage(input_tokens=1)))
    assert result.status == AttemptStatus.SEMANTIC_ACCEPTED
    attempt_id = backend.connection.execute("SELECT completed_attempt_id FROM inference_requests").fetchone()[0]
    assert InferenceBroker(backend, (provider,), {}).mark_decision_useful(req.inference_request_id, attempt_id, "gate consumed verdict")
    assert backend.completed_result(req.inference_request_id).status == AttemptStatus.DECISION_USEFUL
    with pytest.raises(IdempotencyConflict):
        backend.create_or_get(req.model_copy(update={"semantic_task_id": "other"}), compiled.manifest)


def test_deterministic_parser_recovers_one_embedded_artifact_but_not_ambiguous_prose() -> None:
    assert InferenceBroker._recover_json_object('Result follows: {"verdict":"unknown"}.') == {
        "verdict": "unknown"
    }
    assert InferenceBroker._recover_json_object('{"verdict":"a"} or {"verdict":"b"}') is None


def test_private_ip_provider_urls_are_rejected() -> None:
    with pytest.raises(ValueError, match="public HTTPS"):
        route("private", base_url="https://10.1.2.3", allowed_hosts=("10.1.2.3",))


def test_secret_and_unlicensed_memory_never_enter_context() -> None:
    provider = route("memory", egress_clearance=Classification.INTERNAL)
    req = request(criticality=Criticality.NORMAL, idempotency_key="memory-key-00001")
    memories = (
        MemoryItem(
            memory_id="secret-memory",
            claim="credential-shaped material",
            claim_type="operational",
            source_evidence_ids=("raw",),
            confidence_state="candidate",
            created_at=datetime.now(UTC),
            policy_version="policy-1",
            classification=Classification.SECRET,
        ),
        MemoryItem(
            memory_id="licensed-memory",
            claim="licensed raw content",
            claim_type="market-data",
            source_evidence_ids=("raw",),
            confidence_state="candidate",
            created_at=datetime.now(UTC),
            policy_version="policy-1",
            license_allows_external_egress=False,
        ),
    )
    compiled = ContextCompiler().compile(
        req,
        contract(req),
        provider,
        (EvidenceItem(evidence_id="raw", evidence_class="raw_results", classification=Classification.INTERNAL, content="raw"),),
        required_evidence_classes=("raw_results",),
        retrieval_version="test-index-1",
        retrieval_query="memory test",
        memories=memories,
    )
    assert compiled.manifest.excluded_memory == {
        "licensed-memory": "license_restriction",
        "secret-memory": "secret_never_in_prompt",
    }
    assert "credential-shaped" not in compiled.user_prompt
    assert "licensed raw" not in compiled.user_prompt
