"""Controlled context construction with manifest and external-egress enforcement."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime

from .types import (
    CLASSIFICATION_RANK,
    AgentTaskContract,
    Classification,
    CompiledContext,
    CompletenessStatus,
    ContextManifest,
    Criticality,
    EvidenceItem,
    EvidenceRetrievalStatus,
    InferenceRequest,
    MemoryItem,
    ProviderRoute,
    ReviewerIndependenceProfile,
    ReviewIndependenceAssessment,
    ToolCapability,
    canonical_hash,
)


class ContextRejected(ValueError):
    """Raised before external transport when a context contract fails closed."""


class ContextCompiler:
    version = "1"

    def compile(
        self,
        request: InferenceRequest,
        contract: AgentTaskContract,
        route: ProviderRoute,
        evidence: Iterable[EvidenceItem],
        *,
        required_evidence_classes: Iterable[str],
        retrieval_version: str,
        retrieval_query: str,
        tools: Iterable[ToolCapability] = (),
        tool_addressable_ids: Iterable[str] = (),
        memories: Iterable[MemoryItem] = (),
        token_budget: int = 12000,
    ) -> CompiledContext:
        items = tuple(evidence)
        if token_budget <= 0:
            raise ContextRejected("context token budget must be positive")
        if contract.expected_artifact_schema != request.expected_artifact_schema:
            raise ContextRejected("task contract and request output schemas must match")
        if not route.license_approved:
            raise ContextRejected("route has not passed license and terms review")
        if len({item.evidence_id for item in items}) != len(items):
            raise ContextRejected("duplicate evidence IDs are not permitted in one context")
        all_tools = tuple(tools)
        addressable_ids = tuple(tool_addressable_ids)
        known_tool_ids = {tool.tool_id for tool in all_tools}
        unknown_allowed_tools = set(contract.allowed_tools) - known_tool_ids
        if unknown_allowed_tools:
            raise ContextRejected(f"task contract requests unregistered tools: {sorted(unknown_allowed_tools)}")
        unknown_addressable = set(addressable_ids) - {item.evidence_id for item in items}
        if unknown_addressable:
            raise ContextRejected(f"tool-addressable evidence was not retrieved: {sorted(unknown_addressable)}")
        exposed_tools = tuple(
            tool
            for tool in all_tools
            if tool.tool_id in contract.allowed_tools and not tool.side_effects
        )
        side_effecting_tools = {
            tool.tool_id
            for tool in all_tools
            if tool.tool_id in contract.allowed_tools and tool.side_effects
        }
        if side_effecting_tools:
            raise ContextRejected(
                f"task contract cannot expose side-effecting tools: {sorted(side_effecting_tools)}"
            )
        if addressable_ids and not exposed_tools:
            raise ContextRejected("tool-addressable evidence requires an exposed read-only tool")
        required_set = set(required_evidence_classes) | set(contract.required_evidence_classes)
        if request.criticality == Criticality.CRITICAL:
            required_set.add("adverse_facts")
        required = tuple(sorted(required_set))
        requested_addressable = set(addressable_ids)
        included: list[EvidenceItem] = []
        excluded: dict[str, str] = {}
        truncation: dict[str, str] = {}
        consumed = 0
        missing_classes: set[str] = set()
        unresolved: set[str] = set()
        for evidence_class in required:
            class_items = [item for item in items if item.evidence_class == evidence_class]
            if not class_items:
                missing_classes.add(evidence_class)
                continue
            if any(
                item.retrieval_status
                not in {EvidenceRetrievalStatus.RETRIEVED, EvidenceRetrievalStatus.NOT_RELEVANT}
                for item in class_items
            ):
                unresolved.add(evidence_class)

        declared_inputs = set(contract.input_evidence_ids)
        missing_inputs = declared_inputs - {item.evidence_id for item in items}

        for item in items:
            if item.evidence_class in contract.forbidden_evidence_classes:
                excluded[item.evidence_id] = "role_forbidden_evidence_class"
                continue
            if item.retrieval_status != EvidenceRetrievalStatus.RETRIEVED:
                excluded[item.evidence_id] = f"retrieval:{item.retrieval_status}"
                continue
            if item.classification == Classification.SECRET:
                excluded[item.evidence_id] = "secret_never_in_prompt"
                continue
            if CLASSIFICATION_RANK[item.classification] > CLASSIFICATION_RANK[route.egress_clearance]:
                excluded[item.evidence_id] = "egress_clearance"
                continue
            if not item.license_allows_external_egress:
                excluded[item.evidence_id] = "license_restriction"
                continue
            estimated_tokens = max(1, len(item.content or "") // 4)
            # Critical evidence is never silently tail-truncated. It can only be tool-addressable.
            if consumed + estimated_tokens > token_budget:
                if item.evidence_id in requested_addressable and exposed_tools:
                    excluded[item.evidence_id] = "tool_addressable_due_to_budget"
                    truncation[item.evidence_id] = "tool_addressable; canonical source retained"
                else:
                    excluded[item.evidence_id] = "token_budget"
                    truncation[item.evidence_id] = "not included; explicit manifest omission"
                continue
            included.append(item)
            consumed += estimated_tokens

        included_ids = {item.evidence_id for item in included}
        addressable = {
            item.evidence_id
            for item in items
            if item.evidence_id in requested_addressable
            and item.retrieval_status == EvidenceRetrievalStatus.RETRIEVED
            and item.evidence_class not in contract.forbidden_evidence_classes
            and item.classification != Classification.SECRET
            and CLASSIFICATION_RANK[item.classification] <= CLASSIFICATION_RANK[route.egress_clearance]
            and item.license_allows_external_egress
            and bool(exposed_tools)
        }
        classes_accessible = {
            item.evidence_class
            for item in items
            if item.evidence_id in included_ids or item.evidence_id in addressable
        }
        declared_absent = {
            item.evidence_class
            for item in items
            if item.retrieval_status == EvidenceRetrievalStatus.NOT_RELEVANT
        }
        unavailable = set(required) - classes_accessible - declared_absent
        inaccessible_material_classes = {
            item.evidence_class
            for item in items
            if item.evidence_class in required
            and item.material
            and item.retrieval_status == EvidenceRetrievalStatus.RETRIEVED
            and item.evidence_id not in included_ids | addressable
        }
        summary_only = {
            item.evidence_id
            for item in included
            if item.material
            and item.summary_source_ids
            and not set(item.summary_source_ids).intersection(included_ids | addressable)
        }
        is_critical = request.criticality == Criticality.CRITICAL
        blocking = bool(
            missing_classes
            or missing_inputs
            or unresolved
            or unavailable
            or inaccessible_material_classes
            or summary_only
        )
        if is_critical and blocking:
            completeness = CompletenessStatus.BLOCKING
        elif blocking:
            completeness = CompletenessStatus.DECLARED_NONCRITICAL
        else:
            completeness = CompletenessStatus.COMPLETE
        egress = {
            "route_id": route.route_id,
            "clearance": route.egress_clearance,
            "highest_prompt_accessible_classification": max(
                (
                    CLASSIFICATION_RANK[item.classification]
                    for item in items
                    if item.evidence_id in included_ids or item.evidence_id in addressable
                ),
                default=0,
            ),
            "retention_known": route.retention_known,
            "may_train_on_prompts": route.may_train_on_prompts,
            "route_license_approved": route.license_approved,
            "excluded_count": len(excluded),
        }
        manifest = ContextManifest(
            compiler_version=self.version,
            retrieval_version=retrieval_version,
            required_evidence_classes=required,
            candidate_evidence_ids=tuple(item.evidence_id for item in items),
            included_evidence_ids=tuple(item.evidence_id for item in included),
            tool_addressable_evidence_ids=tuple(sorted(addressable)),
            excluded_evidence=excluded,
            summary_artifact_ids=tuple(
                source for item in included for source in item.summary_source_ids
            ),
            truncation=truncation,
            egress_decision=egress,
            completeness_status=completeness,
            retrieval_query_fingerprint=canonical_hash(retrieval_query),
        )
        if is_critical and completeness == CompletenessStatus.BLOCKING:
            missing = (
                missing_classes
                | missing_inputs
                | unresolved
                | unavailable
                | inaccessible_material_classes
                | {f"summary:{item_id}" for item_id in summary_only}
            )
            raise ContextRejected(f"critical context is incomplete: {sorted(missing)}")
        memory_candidates = tuple(memories)
        memory = MemoryRetrievalFirewall().retrieve(
            memory_candidates,
            purpose=request.task_class,
            role=contract.role,
            fresh_independent_review=contract.independence_group_id is not None,
        )
        included_memory: list[MemoryItem] = []
        excluded_memory: dict[str, str] = {}
        eligible_memory_ids = {item.memory_id for item in memory}
        for memory_item in memory_candidates:
            if memory_item.memory_id not in eligible_memory_ids:
                excluded_memory[memory_item.memory_id] = "retrieval_firewall_policy"
        for memory_item in memory:
            if memory_item.classification == Classification.SECRET:
                excluded_memory[memory_item.memory_id] = "secret_never_in_prompt"
            elif CLASSIFICATION_RANK[memory_item.classification] > CLASSIFICATION_RANK[route.egress_clearance]:
                excluded_memory[memory_item.memory_id] = "egress_clearance"
            elif not memory_item.license_allows_external_egress:
                excluded_memory[memory_item.memory_id] = "license_restriction"
            else:
                included_memory.append(memory_item)
        manifest = manifest.model_copy(
            update={
                "included_memory_ids": tuple(item.memory_id for item in included_memory),
                "candidate_memory_ids": tuple(item.memory_id for item in memory_candidates),
                "excluded_memory": excluded_memory,
            }
        )
        package = {
            "task_contract": contract.model_dump(mode="json"),
            "manifest_hash": manifest.manifest_hash,
            "expected_artifact_schema": request.expected_artifact_schema,
            "unknown_evidence_classes": sorted(missing_classes | unresolved | unavailable),
            "forbidden_evidence_classes": sorted(contract.forbidden_evidence_classes),
            "evidence": [
                {
                    "evidence_id": item.evidence_id,
                    "evidence_class": item.evidence_class,
                    "canonical_source_id": item.canonical_source_id,
                    "content": item.content,
                }
                for item in included
            ],
            "memory_claims": [item.model_dump(mode="json") for item in included_memory],
            "tool_capabilities": [tool.model_dump(mode="json") for tool in exposed_tools],
        }
        return CompiledContext(
            system_prompt=(
                "Return only an artifact satisfying the supplied JSON Schema. Do not claim facts "
                "without cited evidence IDs. Return an explicit unknown when evidence is insufficient."
            ),
            user_prompt=json.dumps(package, sort_keys=True, separators=(",", ":")),
            manifest=manifest,
            tool_capabilities=exposed_tools,
        )

    @staticmethod
    def record_tool_expansion(
        manifest: ContextManifest,
        evidence: EvidenceItem,
        route: ProviderRoute,
    ) -> ContextManifest:
        evidence_id = evidence.evidence_id
        if manifest.egress_decision.get("route_id") != route.route_id:
            raise ContextRejected("tool expansion route differs from the compiled context route")
        if evidence_id not in manifest.tool_addressable_evidence_ids:
            raise ContextRejected("tool expansion was not declared in the manifest")
        if evidence_id in manifest.tool_expansion_ids:
            raise ContextRejected("tool expansion is already recorded")
        if evidence.retrieval_status != EvidenceRetrievalStatus.RETRIEVED:
            raise ContextRejected("unretrieved evidence cannot be added by tool expansion")
        if evidence.classification == Classification.SECRET:
            raise ContextRejected("SECRET evidence cannot be expanded into a prompt")
        if CLASSIFICATION_RANK[evidence.classification] > CLASSIFICATION_RANK[route.egress_clearance]:
            raise ContextRejected("tool expansion exceeds route egress clearance")
        if not evidence.license_allows_external_egress:
            raise ContextRejected("tool expansion violates evidence license")
        return manifest.model_copy(
            update={"tool_expansion_ids": tuple((*manifest.tool_expansion_ids, evidence_id))}
        )

    @classmethod
    def apply_tool_expansion(
        cls,
        context: CompiledContext,
        evidence: EvidenceItem,
        route: ProviderRoute,
    ) -> CompiledContext:
        """Attach an approved on-demand read to both the prompt and evidence manifest."""
        manifest = cls.record_tool_expansion(context.manifest, evidence, route)
        try:
            package = json.loads(context.user_prompt)
        except json.JSONDecodeError as exc:
            raise ContextRejected("compiled context package is malformed") from exc
        package["manifest_hash"] = manifest.manifest_hash
        package.setdefault("tool_expansions", []).append(
            {
                "evidence_id": evidence.evidence_id,
                "evidence_class": evidence.evidence_class,
                "canonical_source_id": evidence.canonical_source_id,
                "content": evidence.content,
            }
        )
        return context.model_copy(
            update={
                "user_prompt": json.dumps(package, sort_keys=True, separators=(",", ":")),
                "manifest": manifest,
            }
        )


class MemoryRetrievalFirewall:
    """Filters durable claims; callers never receive a whole memory layer."""

    def retrieve(
        self,
        memories: Iterable[MemoryItem],
        *,
        purpose: str,
        role: str,
        allowed_contamination: Iterable[str] = (),
        fresh_independent_review: bool = False,
        market_scope: Iterable[str] = (),
        mechanism_scope: Iterable[str] = (),
        max_age_days: int | None = None,
        now: datetime | None = None,
    ) -> tuple[MemoryItem, ...]:
        if not purpose or not role:
            raise ContextRejected("memory retrieval requires purpose and role")
        allowed = set(allowed_contamination)
        requested_markets = set(market_scope)
        requested_mechanisms = set(mechanism_scope)
        result = []
        for memory in memories:
            if memory.confidence_state == "invalidated":
                continue
            if fresh_independent_review and memory.contamination_tags:
                continue
            if set(memory.contamination_tags) - allowed:
                continue
            if requested_markets and memory.market_scope and not requested_markets.intersection(memory.market_scope):
                continue
            if requested_mechanisms and memory.mechanism_scope and not requested_mechanisms.intersection(memory.mechanism_scope):
                continue
            if max_age_days is not None and now is not None:
                age = now - (memory.last_revalidated_at or memory.created_at)
                if age.days > max_age_days:
                    continue
            result.append(memory)
        return tuple(result)


class ReviewIndependencePolicy:
    """Rejects reviewer padding that only changes a nominal session identifier."""

    def assess_batch(
        self, profiles: Iterable[ReviewerIndependenceProfile], minimum: int
    ) -> ReviewIndependenceAssessment:
        batch = tuple(profiles)
        if len(batch) < minimum:
            raise ContextRejected("independent reviewer quorum is not met")
        if any(profile.prior_verdicts_visible for profile in batch):
            raise ContextRejected("blind reviewers cannot see prior verdicts")
        fingerprints = {profile.procedural_fingerprint for profile in batch}
        if len(fingerprints) != len(batch):
            raise ContextRejected("review-padding detected: duplicate independence profile")
        profiles_by_family: dict[str, list[ReviewerIndependenceProfile]] = {}
        for profile in batch:
            profiles_by_family.setdefault(profile.model_family, []).append(profile)
        for same_model_profiles in profiles_by_family.values():
            if len(same_model_profiles) > 1 and (
                len({profile.reviewer_mandate for profile in same_model_profiles}) != len(same_model_profiles)
                or len({profile.evidence_ordering_profile for profile in same_model_profiles})
                != len(same_model_profiles)
            ):
                raise ContextRejected(
                    "same-model review requires distinct mandates and evidence ordering"
                )
        shared_contamination = (
            set.intersection(*(set(profile.shared_upstream_or_contamination) for profile in batch))
            if batch
            else set()
        )
        return ReviewIndependenceAssessment(
            reviewer_count=len(batch),
            distinct_model_families=len(profiles_by_family),
            distinct_correlation_domains=len({profile.provider_correlation_domain for profile in batch}),
            residual_same_model_correlation=any(
                len(same_model_profiles) > 1
                for same_model_profiles in profiles_by_family.values()
            ),
            residual_shared_upstream_correlation=(
                len({profile.provider_correlation_domain for profile in batch}) != len(batch)
                or bool(shared_contamination)
            ),
        )

    def validate_batch(self, profiles: Iterable[ReviewerIndependenceProfile], minimum: int) -> None:
        self.assess_batch(profiles, minimum)
