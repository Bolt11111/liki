"""Value-gated, fenced, schema-validating inference routing."""

from __future__ import annotations

import asyncio
import inspect
import json
import random
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from jsonschema import Draft202012Validator

from .adapters import AnthropicMessagesAdapter, OpenAIChatAdapter, ProviderTransportError
from .backend import ConcurrentModification, InferenceBackend
from .context import ContextRejected
from .types import (
    CLASSIFICATION_RANK,
    AttemptStatus,
    Classification,
    CompiledContext,
    InferenceRequest,
    InferenceResult,
    ProviderHealth,
    ProviderRoute,
    RawProviderResponse,
    TaskClassRouteMetrics,
    Usage,
    canonical_hash,
    utcnow,
)


SemanticValidator = Callable[[dict[str, Any], InferenceRequest], bool | Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    same_route_retries: int = 1
    circuit_failure_threshold: int = 3
    base_backoff_seconds: float = 0.05
    max_backoff_seconds: float = 1.0
    jitter_fraction: float = 0.25

    def delay(self, retry_number: int, random_fraction: float) -> float:
        exponential = min(self.max_backoff_seconds, self.base_backoff_seconds * (2**retry_number))
        return max(0.0, exponential * (1 + self.jitter_fraction * ((2 * random_fraction) - 1)))


class InferenceBroker:
    def __init__(
        self,
        backend: InferenceBackend,
        routes: Iterable[ProviderRoute],
        adapters: dict[str, Any],
        *,
        retry_policy: RetryPolicy | None = None,
        random_source: Callable[[], float] = random.random,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.backend = backend
        self.routes = {route.route_id: route for route in routes}
        self.adapters = adapters
        self.retry_policy = retry_policy or RetryPolicy()
        self._random = random_source
        self._sleep = sleep

    @staticmethod
    def _metrics(route: ProviderRoute, task_class: str) -> TaskClassRouteMetrics:
        return next(
            (metrics for metrics in route.task_metrics if metrics.task_class == task_class),
            TaskClassRouteMetrics(
                task_class=task_class,
                semantic_acceptance=route.observed_semantic_acceptance,
                reliability=route.observed_reliability,
            ),
        )

    @staticmethod
    def _has_required_benchmark(
        route: ProviderRoute, task_class: str, required_benchmark_id: str | None
    ) -> bool:
        if required_benchmark_id is None:
            return True
        return any(
            metrics.task_class == task_class
            and metrics.benchmark_id == required_benchmark_id
            and metrics.sample_count > 0
            for metrics in route.task_metrics
        )

    @classmethod
    def expected_cost(cls, route: ProviderRoute, estimated_usage: Usage, task_class: str = "") -> Decimal:
        direct = cls._conservative_cost(route, estimated_usage, AttemptStatus.SEMANTIC_ACCEPTED)
        metrics = cls._metrics(route, task_class)
        accepted_probability = max(metrics.semantic_acceptance * metrics.reliability, 0.01)
        rework = route.expected_rework_usd * Decimal(str(1 + metrics.correction_rate + metrics.reversal_rate))
        return direct / Decimal(str(accepted_probability)) + rework

    def select_routes(
        self,
        request: InferenceRequest,
        context: CompiledContext,
        estimated_usage: Usage,
    ) -> list[ProviderRoute]:
        prompt_tokens = max(1, (len(context.system_prompt) + len(context.user_prompt)) // 4)
        suitable: list[ProviderRoute] = []
        for route in self.routes.values():
            metrics = self._metrics(route, request.task_class)
            if request.allowed_provider_classes and route.provider_class not in request.allowed_provider_classes:
                continue
            if not self._has_required_benchmark(route, request.task_class, request.routing_benchmark_id):
                continue
            if not self._context_safe_for_route(context, route) or not route.license_approved:
                continue
            if route.health not in {ProviderHealth.HEALTHY, ProviderHealth.DEGRADED}:
                continue
            if self.backend.circuit_is_open(route.route_id):
                continue
            if prompt_tokens + route.capabilities.max_output_tokens > route.capabilities.context_window:
                continue
            if request.preferred_reasoning_effort not in {"standard", *route.capabilities.reasoning_efforts}:
                continue
            if (request.requires_tools or context.tool_capabilities) and not route.capabilities.tools_supported:
                continue
            if metrics.semantic_acceptance < max(route.quality_floor, request.min_semantic_acceptance):
                continue
            if metrics.reliability < max(route.reliability_floor, request.min_reliability):
                continue
            direct_cost = self._conservative_cost(route, estimated_usage, AttemptStatus.SEMANTIC_ACCEPTED)
            if request.max_call_cost_usd is not None and direct_cost > request.max_call_cost_usd:
                continue
            suitable.append(route)
        suitable.sort(key=lambda route: (self.expected_cost(route, estimated_usage, request.task_class), route.route_id))
        # Distinct domains are candidates for alternate-provider recovery, never duplicate votes.
        seen_domains: set[str] = set()
        diverse: list[ProviderRoute] = []
        for route in suitable:
            if route.upstream_correlation_domain not in seen_domains:
                diverse.append(route)
                seen_domains.add(route.upstream_correlation_domain)
        return diverse + [route for route in suitable if route not in diverse]

    @staticmethod
    def _context_safe_for_route(context: CompiledContext, route: ProviderRoute) -> bool:
        """Fallback may only receive a context no less protected than its original route."""
        decision = context.manifest.egress_decision
        required_rank = int(decision.get("highest_prompt_accessible_classification", 0))
        if CLASSIFICATION_RANK[route.egress_clearance] < required_rank:
            return False
        if required_rank >= CLASSIFICATION_RANK[Classification.CONFIDENTIAL]:
            return route.retention_known and route.may_train_on_prompts is False
        original_training = decision.get("may_train_on_prompts")
        return original_training is not False or route.may_train_on_prompts is False

    async def run(
        self,
        request: InferenceRequest,
        context: CompiledContext,
        *,
        estimated_usage: Usage,
        semantic_validator: SemanticValidator | None = None,
    ) -> InferenceResult:
        if context.manifest.completeness_status.value == "INCOMPLETE_BLOCKING":
            raise ContextRejected("blocking context cannot be sent to a provider")
        submitted_id = request.inference_request_id
        request = self.backend.create_or_get(request, context.manifest)
        if request.inference_request_id != submitted_id:
            completed = self.backend.completed_result(request.inference_request_id)
            if completed is not None:
                return completed
            return InferenceResult(
                request_id=request.inference_request_id,
                status=AttemptStatus.HIBERNATED,
                failure_reason="semantic_request_already_in_progress_or_hibernated",
            )
        routes = [
            route
            for route in self.select_routes(request, context, estimated_usage)
            if route.adapter in self.adapters
        ]
        if not routes:
            self.backend.hibernate(request.inference_request_id, "no_eligible_route")
            return InferenceResult(request_id=request.inference_request_id, status=AttemptStatus.HIBERNATED, failure_reason="no_eligible_route")
        used_domains: set[str] = set()
        for route in routes:
            if route.upstream_correlation_domain in used_domains:
                continue
            used_domains.add(route.upstream_correlation_domain)
            for retry_number in range(self.retry_policy.same_route_retries + 1):
                result = await self._attempt(request, context, route, estimated_usage, semantic_validator)
                if result.status in {AttemptStatus.SEMANTIC_ACCEPTED, AttemptStatus.DECISION_USEFUL}:
                    return result
                if result.status == AttemptStatus.HIBERNATED:
                    self.backend.hibernate(request.inference_request_id, result.failure_reason or "attempt_hibernated")
                    return result
                if result.status != AttemptStatus.RETRYABLE_FAILURE or retry_number == self.retry_policy.same_route_retries:
                    break
                await self._sleep(self.retry_policy.delay(retry_number, self._random()))
        self.backend.hibernate(request.inference_request_id, "all_independent_routes_failed")
        return InferenceResult(request_id=request.inference_request_id, status=AttemptStatus.HIBERNATED, failure_reason="all_independent_routes_failed")

    def revive(self, request_id: str, reason: str) -> bool:
        """Scheduler-only recovery path after route/provider/policy state changed."""
        return self.backend.revive(request_id, reason)

    def revive_route(self, route_id: str, reason: str) -> bool:
        """Health probes, not failed work, are allowed to close an open route circuit."""
        if route_id not in self.routes:
            raise ValueError("unknown inference route")
        return self.backend.revive_route(route_id, reason)

    def reconcile_provider_cost(self, request_id: str, attempt_id: str, provider_cost: Decimal) -> bool:
        """Records a billing discrepancy rather than claiming exact economics."""
        return self.backend.reconcile_attempt_cost(request_id, attempt_id, provider_cost)

    def mark_decision_useful(self, request_id: str, attempt_id: str, reason: str) -> bool:
        """Only a downstream deterministic decision may promote semantic acceptance to useful."""
        if not reason.strip():
            raise ValueError("a useful-decision reason is required")
        return self.backend.mark_decision_useful(request_id, attempt_id, reason)

    async def _attempt(
        self,
        request: InferenceRequest,
        context: CompiledContext,
        route: ProviderRoute,
        estimated_usage: Usage,
        semantic_validator: SemanticValidator | None,
    ) -> InferenceResult:
        reservation = self._conservative_cost(route, estimated_usage, AttemptStatus.SEMANTIC_ACCEPTED)
        try:
            # The lease must outlive the caller deadline long enough to durably record a timeout.
            lease_seconds = max(request.max_latency_sec or 0, route.capabilities.timeout_seconds) + 5
            attempt = self.backend.claim_attempt(request.inference_request_id, route.route_id, lease_seconds)
        except ConcurrentModification:
            return InferenceResult(request_id=request.inference_request_id, status=AttemptStatus.HIBERNATED, failure_reason="lease_superseded")
        attempt = attempt.model_copy(
            update={
                "model_family": route.model_family,
                "model_version": route.model_version,
                "upstream_correlation_domain": route.upstream_correlation_domain,
                "system_prompt_hash": canonical_hash(context.system_prompt),
                "task_prompt_hash": canonical_hash(context.user_prompt),
                "tool_schema_hash": canonical_hash(
                    [tool.model_dump(mode="json") for tool in context.tool_capabilities]
                ),
                "pricing_plan_id": route.pricing.price_plan_id,
            }
        )
        if not self.backend.reserve_cost(request.inference_request_id, attempt.inference_attempt_id, reservation):
            self.backend.finish_attempt(
                attempt.model_copy(
                    update={
                        "completed_at": utcnow(),
                        "status": AttemptStatus.HIBERNATED,
                        "error_class": "budget_exhausted",
                    }
                )
            )
            self.backend.append_event(request.inference_request_id, "inference_budget_denied", {"route_id": route.route_id})
            return InferenceResult(request_id=request.inference_request_id, status=AttemptStatus.HIBERNATED, failure_reason="budget_exhausted")
        start = time.monotonic()
        try:
            response: RawProviderResponse = await asyncio.wait_for(
                self.adapters[route.adapter].invoke(
                    route, context.system_prompt, context.user_prompt, request.preferred_reasoning_effort
                ),
                timeout=request.max_latency_sec or route.capabilities.timeout_seconds,
            )
            status, artifact, error_class = await self._validate_response(request, response, semantic_validator)
            fixed_cost, token_cost, billed_tokens = self._cost_components(
                route, response.usage, status, reservation
            )
            attempt = attempt.model_copy(
                update={
                    "completed_at": utcnow(),
                    "status": status,
                    "provider_request_id": response.provider_request_id,
                    "http_status": response.http_status,
                    "error_class": error_class,
                    "usage": response.usage,
                    "total_cost_usd": self._response_cost(route, response.usage, status, reservation),
                    "fixed_call_cost_usd": fixed_cost,
                    "token_cost_usd": token_cost,
                    "billed_tokens": billed_tokens,
                    "provider_reported_model": response.model_version,
                    "model_version": response.model_version or route.model_version,
                    "latency_ms": int((time.monotonic() - start) * 1000),
                    "output_artifact": artifact,
                    "response_hash": canonical_hash(response.text),
                }
            )
            accepted = self.backend.finish_attempt(attempt)
            if not accepted:
                self.backend.append_event(request.inference_request_id, "late_result_deduplicated", {"attempt_id": attempt.inference_attempt_id})
                return InferenceResult(request_id=request.inference_request_id, status=AttemptStatus.HIBERNATED, failure_reason="late_result_deduplicated")
            semantic_success = status in {AttemptStatus.SEMANTIC_ACCEPTED, AttemptStatus.DECISION_USEFUL}
            self.backend.record_route_outcome(route.route_id, semantic_success, self.retry_policy.circuit_failure_threshold)
            self.backend.append_event(
                request.inference_request_id,
                "inference_attempt_completed",
                {"attempt_id": attempt.inference_attempt_id, "final_status": status, "layers": ["TRANSPORT_SUCCESS", "SCHEMA_SUCCESS"] if artifact else ["TRANSPORT_SUCCESS"]},
            )
            return InferenceResult(request_id=request.inference_request_id, status=status, artifact=artifact, failure_reason=error_class, route_id=route.route_id)
        except TimeoutError:
            return self._finish_transport_failure(request, route, attempt, reservation, "caller_timeout")
        except ProviderTransportError as exc:
            return self._finish_transport_failure(request, route, attempt, reservation, exc.error_class, exc.retryable)
        except Exception:
            # Provider/parser/validator defects must release the fenced reservation durably.
            return self._finish_transport_failure(
                request, route, attempt, reservation, "adapter_or_validator_failure", False
            )

    @staticmethod
    def _response_cost(route: ProviderRoute, usage: Usage, status: AttemptStatus, reservation: Decimal) -> Decimal:
        fields = ("input_tokens", "output_tokens", "reasoning_tokens", "cache_read_tokens", "cache_write_tokens")
        if all(getattr(usage, field) is not None for field in fields):
            return route.pricing.cost(usage, outcome=status)
        return max(reservation, InferenceBroker._conservative_cost(route, usage, status))

    @staticmethod
    def _conservative_usage(route: ProviderRoute, usage: Usage) -> Usage:
        fields = ("input_tokens", "output_tokens", "reasoning_tokens", "cache_read_tokens", "cache_write_tokens")
        values = usage.model_dump()
        reserve = route.pricing.unknown_usage_reserve
        if any(values[field] is None for field in fields):
            for field in fields:
                if values[field] is None:
                    values[field] = getattr(reserve, field)
            values["token_count_method"] = "estimated_with_conservative_defaults"
        return Usage.model_validate(values)

    @classmethod
    def _conservative_cost(cls, route: ProviderRoute, usage: Usage, status: AttemptStatus) -> Decimal:
        return route.pricing.cost(cls._conservative_usage(route, usage), outcome=status)

    @classmethod
    def _cost_components(
        cls, route: ProviderRoute, usage: Usage, status: AttemptStatus, reservation: Decimal
    ) -> tuple[Decimal, Decimal, int]:
        conservative_usage = cls._conservative_usage(route, usage)
        fixed, token, billed_tokens = route.pricing.cost_components(
            conservative_usage, outcome=status
        )
        return fixed, token, billed_tokens

    def _finish_transport_failure(
        self,
        request: InferenceRequest,
        route: ProviderRoute,
        attempt: Any,
        reservation: Decimal,
        error_class: str,
        retryable: bool = True,
    ) -> InferenceResult:
        status = AttemptStatus.RETRYABLE_FAILURE if retryable else AttemptStatus.NONRETRYABLE_FAILURE
        conservative = max(
            reservation,
            self._conservative_cost(route, Usage(token_count_method="unknown_conservative"), status),
        )
        fixed_cost, token_cost, billed_tokens = self._cost_components(
            route, Usage(token_count_method="unknown_conservative"), status, reservation
        )
        attempt = attempt.model_copy(
            update={
                "completed_at": utcnow(),
                "status": status,
                "error_class": error_class,
                "total_cost_usd": conservative,
                "pricing_plan_id": route.pricing.price_plan_id,
                "fixed_call_cost_usd": fixed_cost,
                "token_cost_usd": token_cost,
                "billed_tokens": billed_tokens,
            }
        )
        if not self.backend.finish_attempt(attempt):
            self.backend.append_event(request.inference_request_id, "late_result_deduplicated", {"attempt_id": attempt.inference_attempt_id})
            return InferenceResult(request_id=request.inference_request_id, status=AttemptStatus.HIBERNATED, failure_reason="late_result_deduplicated")
        self.backend.record_route_outcome(route.route_id, False, self.retry_policy.circuit_failure_threshold)
        self.backend.append_event(request.inference_request_id, "inference_attempt_failed", {"route_id": route.route_id, "error_class": error_class})
        return InferenceResult(request_id=request.inference_request_id, status=status, failure_reason=error_class, route_id=route.route_id)

    async def _validate_response(
        self,
        request: InferenceRequest,
        response: RawProviderResponse,
        semantic_validator: SemanticValidator | None,
    ) -> tuple[AttemptStatus, dict[str, Any] | None, str | None]:
        if response.stop_reason in {"max_tokens", "length"}:
            return AttemptStatus.RETRYABLE_FAILURE, None, "truncated_response"
        text = response.text.strip()
        if not text:
            return AttemptStatus.NONRETRYABLE_FAILURE, None, "empty_response"
        if text.casefold().startswith(("i cannot", "i can't", "i'm unable", "i am unable")):
            return AttemptStatus.NONRETRYABLE_FAILURE, None, "provider_refusal"
        artifact = self._recover_json_object(text)
        if artifact is None:
            return AttemptStatus.NONRETRYABLE_FAILURE, None, "malformed_structured_output"
        errors = list(Draft202012Validator(request.expected_artifact_schema).iter_errors(artifact))
        if errors:
            return AttemptStatus.NONRETRYABLE_FAILURE, None, "schema_validation_failed"
        if semantic_validator is not None:
            verdict = semantic_validator(artifact, request)
            if inspect.isawaitable(verdict):
                verdict = await verdict
            if not verdict:
                return AttemptStatus.NONRETRYABLE_FAILURE, artifact, "semantic_validation_failed"
        return AttemptStatus.SEMANTIC_ACCEPTED, artifact, None

    @staticmethod
    def _recover_json_object(text: str) -> dict[str, Any] | None:
        """Recover only one unambiguous complete JSON object from a provider response."""
        candidates = [text]
        if text.startswith("```") and text.endswith("```"):
            lines = text.splitlines()
            candidates.append("\n".join(lines[1:-1]).strip())
        decoder = json.JSONDecoder()
        for candidate in candidates:
            try:
                value = json.loads(candidate)
            except json.JSONDecodeError:
                value = None
            if isinstance(value, dict):
                return value
        recovered: list[dict[str, Any]] = []
        for index, character in enumerate(text):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and value not in recovered:
                recovered.append(value)
        return recovered[0] if len(recovered) == 1 else None


def adapter_registry(client: Any, key_resolver: Any) -> dict[str, Any]:
    return {
        "anthropic_messages": AnthropicMessagesAdapter(client, key_resolver),
        "openai_chat": OpenAIChatAdapter(client, key_resolver),
    }
