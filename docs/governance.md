# Governance domain API

`liki.governance` is a pure, immutable domain layer. The persistence owner must
store each returned record/event atomically, enforce its own aggregate-version
compare-and-set, and bind `authenticated_principal` from the authenticated
workload channel rather than request JSON.

## Parent-facing flow

1. Load the content-addressed policy with `load_governance_policy()`.
2. Build `GovernanceProposal` with provenance-backed evidence and an
   `ApprovalSnapshot`. Call `classify_proposal`; its deterministic protected-path
   floor can only be escalated by the declared class.
3. Send only `build_blind_packet(...)` to first-round reviewers. It excludes the
   author, classifier identity, and all verdicts. Persist `GovernanceReview`
   records with fresh profiles, actual inspected-artifact telemetry, and
   independent principals/groups.
4. Persist replay/test/shadow/canary artifacts as `AutomatedCheck`, a separate
   `SynthesisRecord`, owner delivery, and an optional owner decision. Call
   `evaluate_promotion(...)` using a freshly reconstructed `ApprovalSnapshot`.
   It returns `STALE_APPROVAL`, `FROZEN`, `VETOED`, or `REVIEWING` rather than
   promoting on incomplete, stale, incident-contaminated, or Sybil-padded input.
5. Persist `ChangeSet` for coupled changes. More than one proposal requires real
   passing interaction-test checks plus artifact provenance. Deploy under the *old* policy that was
   included in the approval snapshot; never let a proposal apply its own rules.

GREEN requires three independent blind reviews. AMBER requires five plus replay,
tests, shadow, and canary. RED requires seven blind reviews, two adversarial
mandates, the same lifecycle evidence, and explicit owner approval. A 24-hour
timer applies only after authoritative delivery of a complete, passing GREEN or
eligible AMBER package; an open relevant incident, stale snapshot, veto, or
unresolved material objection blocks promotion. The current build rejects every
real-money enablement proposal even with owner approval.

When constrained to correlated reviewer models, persist the residual limitation
in `SynthesisRecord`; duplicate model correlation cannot be silently presented as
independent review diversity.

Persist every lifecycle state change with `transition_proposal(...)`. It emits an
append-only, provenance-backed transition with the expected `state_version` chain;
the persistence owner must reject a stale compare-and-set. `PROMOTED` can only be
emitted when the fresh `evaluate_promotion` result is itself `PROMOTED`.

## Replay, incidents, and model risk

`run_counterfactual_replay` computes transparent counts/costs only from stored
`ReplayEvent`s; `run_labeled_stress_comparison` compares observed behavior with
provenance-backed labels. Neither is a synthetic market-performance scorer.
`SystemEvolutionTrial` separately records system-development benchmark exposure,
shadow/canary evidence, and system statistical-capital consumption.

`transition_incident` enforces the incident lifecycle and evidence required for
material closure. `assess_model_admission` rejects retired, watch, and suspended
models and requires a validator distinct from developers for material models.
`ModelRecord` prevents development/recalibration-consumed evidence from being
reused as independent validation; `find_common_dependencies` exposes common-mode
risk across inventory records. Material/critical records require a Model Card;
dataset families use `DataCard` with provenance and contamination history.

## PostgreSQL service API

`GovernanceService` methods are called *inside* `with store.transaction(token) as
(conn, actor)`. The service takes this authenticated identity rather than any
user-supplied principal string, acquires `pg_advisory_xact_lock(71403218)` before
its first read/row lock, and sends durable aggregate/event/outbox mutations through
`Store.transition`.

```python
register_policy(conn, actor, policy, policy_artifact, operation_key, effective=False)
propose(conn, actor, proposal, operation_key, policy_version)
classify(conn, actor, proposal_id, policy, expected_version, operation_key)
record_review(conn, actor, review, evidence_manifest, expected_version, operation_key, policy_version)
record_lifecycle(conn, actor, proposal_id, lifecycle, expected_version, operation_key, policy_version)
record_synthesis(conn, actor, synthesis, expected_version, operation_key, policy_version)
queue_owner_notification(conn, actor, proposal_id, channel, notification_package, expected_version, operation_key, policy_version)
record_owner_delivery(conn, actor, proposal_id, channel, expected_version, operation_key, policy_version)
decide(conn, actor, proposal_id, "APPROVE" | "VETO", reason, expected_version, operation_key, policy_version)
evaluate(conn, actor, proposal_id, expected_version, operation_key, policy_version, change_set_id=None)
record_change_set(conn, actor, change_set, expected_version, operation_key, policy_version)
activate_policy(conn, actor, policy_id, policy_version, proposal_id, expected_version, operation_key)
rollback_policy(conn, actor, policy_id, rollback_to_version, expected_version, operation_key)
declare_incident(...) / advance_incident(...)
persist_replay(conn, actor, proposal_id, replay_events, input_artifact, operation_key, policy_version)
register_model(...) / record_model_validation(...) / record_drift(...) / record_system_trial(...)
schedule_monthly(...) / schedule_emergency(...)
```

`expected_version` is the current aggregate revision read by the parent. A stale
writer raises `CONCURRENT_MODIFICATION`; repeated operation keys are idempotent.
Every provenance reference is resolved against `artifacts`, its stored digest,
registered producer identity/role/code fingerprint, and (for automated checks)
the stored result payload—not a caller assertion. The service rebuilds policy and
incident inputs from PostgreSQL immediately before `evaluate`; it never accepts a
caller-provided "current snapshot" as authoritative.

### Owner decision endpoint contract

The HTTP/Telegram adapter authenticates an owner credential and invokes the
service in that credential's transaction. It MUST NOT accept an artifact ID or
provenance object from the owner:

```text
POST /governance/proposals/{proposal_id}/decision
Authorization: Bearer <owner credential>
Content-Type: application/json

{
  "decision": "APPROVE" | "VETO",
  "reason": "non-empty human decision rationale",
  "expected_version": 17,
  "operation_key": "opaque-client-uuid-or-command-id",
  "policy_version": "current-governance-policy-version"
}
```

The server calls `GovernanceService.decide(...)`; only `role='owner'` with the
`owner_decision` capability is accepted. It creates the immutable
`governance/server-owner-decision-attestation/v1` artifact itself, binding the
authenticated owner, proposal ID/version, decision, reason, expected aggregate
version, operation key, policy version, server environment fingerprint, and one
server-generated UTC `decided_at_utc`. This grants no generic artifact-write
capability to owner credentials.

The response is the persisted `OwnerDecision` record. A retry using the same
operation key and identical authenticated request returns that exact record and
its original `decided_at`; changed actor, proposal, decision, reason, expected
version, or policy version returns `IDEMPOTENCY_CONFLICT`. A second key after a
decision is durable returns `OWNER_DECISION_ALREADY_RECORDED`.

## Delivery and incident outbox contracts

`queue_owner_notification` is the sole path that converts a review-complete owner
package into the parent-owned `telegram.notification` transactional outbox. Its
`governance/owner-notification-package/v1` artifact must contain:

```json
{
  "proposal_id": "...",
  "channel": "configured-authoritative-channel",
  "title": "Governance decision required",
  "message": "review-complete decision package"
}
```

It requires passing artifact-backed automated checks, uses a deterministic
deduplication key of `governance-owner-decision:{proposal_id}:{proposal_version}`,
and emits notification metadata on the governance event. The Telegram worker must
claim that outbox row and call its parent-owned `finish(..., receipt=<provider
message id>)` path only after confirmed provider success. That path writes the
immutable `notification_deliveries` row (`notification_id`, `outbox_id`, actual
`provider_message_id`, `delivered_at`, event ID). Unknown or expired outcomes are
`QUARANTINED`; they create no receipt.

`record_owner_delivery` accepts no caller receipt or artifact. It resolves the
queued notification metadata and requires the matching `telegram.notification`
outbox row to be `DELIVERED` with a persisted `notification_deliveries` receipt,
the authoritative recipient channel, and a UTC delivery time no earlier than the
durably recorded complete-evidence time. Only then does it persist
`OwnerDelivery` and start the 24-hour no-veto window.
