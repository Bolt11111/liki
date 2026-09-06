from __future__ import annotations

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from liki.core import DomainError, uid
from liki.inference import (
    AgentTaskContract,
    AttemptStatus,
    Classification,
    ContextCompiler,
    Criticality,
    EvidenceItem,
    InferenceRequest,
    PricingPlan,
    ProviderRoute,
)
from liki.inference.backend import ConcurrentModification, IdempotencyConflict
from liki.inference.types import IdentityAssurance, ProviderHealth, RouteCapabilities
from liki.inference_service import InferenceService, PostgresInferenceBackend, ProviderCredentialResolver


def provider(route_id: str = "primary") -> ProviderRoute:
    return ProviderRoute(
        route_id=route_id,
        provider_class="llm",
        provider_id="test-provider",
        endpoint_id="test-endpoint",
        key_pool_id="test-pool",
        adapter="openai_chat",
        base_url="https://provider.test",
        allowed_hosts=("provider.test",),
        model="configured-model",
        claimed_model_name="configured-model",
        model_family="verified-test-family",
        model_version="configured-version",
        identity_assurance=IdentityAssurance.PROVIDER_ASSERTED,
        upstream_correlation_domain="independent-test-domain",
        egress_clearance=Classification.INTERNAL,
        retention_known=True,
        may_train_on_prompts=False,
        health=ProviderHealth.HEALTHY,
        capabilities=RouteCapabilities(context_window=100_000, max_output_tokens=1000, timeout_seconds=1),
        pricing=PricingPlan(price_plan_id="test-price", effective_at=datetime.now(UTC)),
    )


def request(key: str = "inference-service-key") -> InferenceRequest:
    return InferenceRequest(
        semantic_task_id="semantic-task",
        task_class="review",
        criticality=Criticality.NORMAL,
        why_llm_needed="semantic evidence synthesis",
        expected_artifact_schema={"type": "object", "required": ["verdict"]},
        expected_decision_impact="blocks candidate promotion",
        preferred_reasoning_effort="standard",
        idempotency_key=key.ljust(16, "x"),
        fallback_policy_id="default",
        max_total_attempt_cost_usd=Decimal("1.00"),
    )


def context(value: InferenceRequest, route: ProviderRoute):
    return ContextCompiler().compile(
        value,
        AgentTaskContract(
            agent_run_id="inference-run",
            role="skeptic",
            question="Is the evidence sufficient?",
            expected_artifact_schema=value.expected_artifact_schema,
            success_condition="return a structured verdict",
            stop_condition="return unknown when evidence is insufficient",
        ),
        route,
        (EvidenceItem(evidence_id="evidence-1", evidence_class="raw_results", classification=Classification.INTERNAL, content="raw evidence"),),
        required_evidence_classes=("raw_results",),
        retrieval_version="test-index-v1",
        retrieval_query="candidate",
    )


def backend(store, credentials, route: ProviderRoute) -> PostgresInferenceBackend:
    return PostgresInferenceBackend(store, credentials["inference"], {route.route_id: route})


def test_postgres_backend_persists_idempotent_attempt_artifact_and_reconciliation(store, credentials):
    route = provider()
    service = backend(store, credentials, route)
    submitted = request(uid("production-idempotency"))
    compiled = context(submitted, route)
    assert service.create_or_get(submitted, compiled.manifest).inference_request_id == submitted.inference_request_id
    assert service.create_or_get(submitted, compiled.manifest).inference_request_id == submitted.inference_request_id
    with pytest.raises(IdempotencyConflict):
        service.create_or_get(submitted.model_copy(update={"task_class": "different"}), compiled.manifest)

    attempt = service.claim_attempt(submitted.inference_request_id, route.route_id, 30)
    assert attempt.model_family == route.model_family
    assert attempt.model_version == route.model_version
    assert service.reserve_cost(submitted.inference_request_id, attempt.inference_attempt_id, Decimal("0.10"))
    accepted = attempt.model_copy(
        update={
            "status": AttemptStatus.SEMANTIC_ACCEPTED,
            "completed_at": datetime.now(UTC),
            "total_cost_usd": Decimal("0.02"),
            "output_artifact": {"verdict": "reject"},
            "response_hash": "sha256:response",
        }
    )
    assert service.finish_attempt(accepted)
    result = service.completed_result(submitted.inference_request_id)
    assert result is not None and result.artifact == {"verdict": "reject"}
    assert not service.reconcile_attempt_cost(submitted.inference_request_id, attempt.inference_attempt_id, Decimal("0.03"))
    assert service.mark_decision_useful(submitted.inference_request_id, attempt.inference_attempt_id, "deterministic gate consumed it")

    with store.transaction(credentials["auditor"]) as (conn, _):
        row = conn.execute("SELECT * FROM inference_attempts WHERE inference_attempt_id=%s", (attempt.inference_attempt_id,)).fetchone()
        assert row["model_family"] == route.model_family
        assert row["output_artifact_id"] is not None
        assert row["provider_reported_cost_usd"] == Decimal("0.03")
        assert row["total_cost_usd"] == Decimal("0.03")
        assert row["status"] == AttemptStatus.DECISION_USEFUL
        assert conn.execute("SELECT COUNT(*) AS count FROM context_manifests WHERE inference_request_id=%s", (submitted.inference_request_id,)).fetchone()["count"] == 1
        assert conn.execute("SELECT COUNT(*) AS count FROM event_log WHERE aggregate_type='inference_request' AND aggregate_id=%s", (submitted.inference_request_id,)).fetchone()["count"] >= 5
        assert store.audit(conn)["status"] == "VERIFIED"


def test_postgres_backend_rejects_concurrent_claim_race(store, credentials):
    route = provider("race")
    service = backend(store, credentials, route)
    submitted = request(uid("claim-race"))
    service.create_or_get(submitted, context(submitted, route).manifest)
    barrier = threading.Barrier(2)

    def claim() -> str:
        barrier.wait()
        try:
            return service.claim_attempt(submitted.inference_request_id, route.route_id, 30).inference_attempt_id
        except ConcurrentModification:
            return "blocked"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: claim(), range(2)))
    assert outcomes.count("blocked") == 1
    assert len(set(outcomes) - {"blocked"}) == 1


def test_expired_attempt_is_deduplicated_then_hibernated_and_revived(store, credentials):
    route = provider("timeout")
    service = backend(store, credentials, route)
    submitted = request(uid("crash-timeout"))
    service.create_or_get(submitted, context(submitted, route).manifest)
    attempt = service.claim_attempt(submitted.inference_request_id, route.route_id, 0.001)
    assert service.reserve_cost(submitted.inference_request_id, attempt.inference_attempt_id, Decimal("0.10"))
    time.sleep(0.02)
    late = attempt.model_copy(
        update={
            "status": AttemptStatus.SEMANTIC_ACCEPTED,
            "completed_at": datetime.now(UTC),
            "total_cost_usd": Decimal("0.10"),
            "output_artifact": {"verdict": "late"},
        }
    )
    assert not service.finish_attempt(late)
    service.hibernate(submitted.inference_request_id, "caller timeout after provider completion")
    assert service.revive(submitted.inference_request_id, "health probe recovered route")
    with store.transaction(credentials["auditor"]) as (conn, _):
        attempt_row = conn.execute("SELECT status,output_artifact_id FROM inference_attempts WHERE inference_attempt_id=%s", (attempt.inference_attempt_id,)).fetchone()
        request_row = conn.execute("SELECT status,accrued_cost_usd FROM inference_requests WHERE inference_request_id=%s", (submitted.inference_request_id,)).fetchone()
        assert attempt_row == {"status": AttemptStatus.HIBERNATED, "output_artifact_id": None}
        assert request_row == {"status": "ADMITTED", "accrued_cost_usd": Decimal("0.10")}


def test_service_constructs_only_explicitly_configured_routes_and_credentials(store, credentials, tmp_path):
    route = provider("configured")
    config = tmp_path / "providers.json"
    config.write_text(json.dumps({"routes": [route.model_dump(mode="json")]}), encoding="utf-8")
    with pytest.raises(DomainError, match="INFERENCE_PROVIDER_CONFIG_MISSING"):
        InferenceService.from_environment(store, credentials["inference"], environment={})
    service = InferenceService.from_environment(
        store,
        credentials["inference"],
        environment={"LIKI_INFERENCE_PROVIDER_CONFIG": str(config), "LIKI_INFERENCE_KEY_TEST_POOL": "secret"},
    )
    assert service.routes == (route,)
    assert asyncio.run(ProviderCredentialResolver(environment={"LIKI_INFERENCE_KEY_TEST_POOL": "secret"})(route)) == "secret"
    credential_file = tmp_path / "provider-secrets.json"
    credential_file.write_text(json.dumps({"test-pool": "file-secret"}), encoding="utf-8")
    assert asyncio.run(ProviderCredentialResolver(environment={}, credential_file=credential_file)(route)) == "file-secret"
    asyncio.run(service.aclose())
