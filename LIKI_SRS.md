# LIKI — Software Requirements Specification (SRS)

**Document:** `LIKI_SRS.md`  
**System:** LIKI Autonomous Quantitative Research Office  
**Status:** Authoritative greenfield SRS; adversarially hardened across architecture, statistics, execution, governance, security, reliability, and implementation semantics  
**Language:** English  
**Version:** 1.4 — Perfection-Pass Adversarial Quant/Systems Revision  
**Supersedes as system-level authority:** LIKI V3 / V3.1 / V3.2 / V3.3 where this document conflicts with them  
**Preserves:** the valid evaluator, backtest, evidence, scheduler, governance, and safety concepts from earlier LIKI specifications unless explicitly replaced here  
**Primary deployment mode at issuance:** research + historical simulation + forward shadow + paper execution; **real-money execution disabled**

**Hardening review:** This revision completed repeated hostile-review passes across requirements traceability, policy/evaluator version pinning, inference economics/fallback/provider identity, context completeness/evidence omission, agent independence, adaptive scheduling and allocator selection bias, memory contamination, financial statistics and seed/nuisance search, portfolio-level multiple testing, market-data fidelity and source poisoning, historical instrument specifications and crypto lifecycle events, pre-trade controls/STP/kill switches, crypto execution and forced-liquidation semantics, portfolio reverse stress and trapped-capital risk, model-risk lifecycle, governance change interaction/staleness, authenticated service provenance, data egress, incident management, SLO/error-budget semantics, configuration drift, durable reliability, numerical/accounting contracts, governance self-reference, QA, and disaster recovery.

---

## 0. Purpose

This SRS defines LIKI as an autonomous, continuously operating quantitative-finance research office designed to discover, falsify, validate, and maintain robust net trading edge after realistic costs while minimizing self-deception, wasted inference, wasted compute, and uncontrolled risk.

LIKI is not defined as "a group of LLM agents." It is a governed research system in which:

- deterministic software performs deterministic work;
- LLMs are used where semantic reasoning, hypothesis generation, ambiguity resolution, synthesis, or adversarial judgment has positive expected value;
- no agent can silently bypass evidence or risk gates;
- no agent can certify its own work;
- all important decisions are reproducible from immutable evidence;
- adaptive research is explicitly charged for data reuse and multiple testing;
- provider/API failures do not stop the office;
- idle capacity is used for useful work, but LIKI is never forced to manufacture low-value research merely to keep utilization high;
- system rules can improve over time through a controlled governance process without allowing the research process to rewrite the tests that judge it;
- paper and forward evidence are treated as evidence, not as proof of future profit;
- live capital remains unavailable until the owner explicitly enables it through a separate future authorization process.

The owner’s business goal is substantial, sustainable income and long-run capital growth, with an aspirational milestone of at least **USD 10,000 per week**. This is **not** a strategy acceptance metric. LIKI’s internal research objective is to find **robust net edge after all modeled and observed costs** under explicit risk, statistical-validity, liquidity, capacity, and execution constraints.

No requirement in this document promises profit. A system claiming mathematical certainty of future edge is considered defective.

---

# 1. Normative language and precedence

The terms **MUST**, **MUST NOT**, **SHALL**, **SHALL NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are normative.

If requirements conflict, precedence is:

1. **LIKI Constitution** in Section 4.
2. Explicit owner safety controls and the real-money disable.
3. This SRS.
4. Versioned policy configuration approved under Governance.
5. Module contracts and schemas.
6. Implementation details.
7. Agent prompts.

An agent prompt MUST NOT override a higher-precedence rule.

Any ambiguity affecting money, data validity, statistical validity, gate status, access control, or execution MUST fail closed and create an auditable `spec_ambiguity` event. Ambiguities that merely affect noncritical research formatting MAY fail soft.

No implementation agent may silently invent missing financial assumptions. Missing assumptions MUST be represented as unknowns, requirements, distributions, or explicit policy decisions.

---

# 1A. Glossary, semantic contracts, and requirement traceability

This section removes terminology ambiguity for both human and coding agents.

## 1A.1 Core glossary

- **Edge** — a positive expected economic advantage after all relevant costs and constraints. Historical edge is an estimate, never a fact about the future.
- **Candidate** — any hypothesis/strategy version not yet fully promoted.
- **Hypothesis** — a falsifiable claim about a market mechanism, predictive relationship, execution effect, portfolio effect, or system behavior.
- **Mechanism** — the proposed economic/statistical/market-structure reason a hypothesis may hold. Mechanisms may be unknown for empirical candidates.
- **Strategy** — a stable conceptual trading approach. A **strategy version** is one exact version of code, parameters, data assumptions, and execution semantics.
- **Branch** — one research lineage path derived from an idea/hypothesis.
- **Scientific trial** — an adaptive choice that uses market evidence to evaluate or alter a hypothesis/strategy. Infrastructure-only retries are not new scientific trials.
- **Experiment** — one reproducible execution of a declared scientific or system test.
- **Artifact** — persisted output with schema, hash, provenance, and producer.
- **Evidence** — an artifact or observation admitted into a decision under a declared evidentiary role.
- **Gate** — deterministic or governed decision boundary that changes candidate state.
- **Promotion** — movement to a stronger evidentiary/operational state; it never means guaranteed profitability.
- **Frontier** — bounded research budget for promising but unresolved candidates with no hard invalidity.
- **Statistical capital** — the finite information budget consumed when the research process observes/adapts to reused data.
- **Sealed evidence** — evidence deliberately hidden from generation/tuning processes and exposed only under a limited protocol.
- **Forward evidence** — chronological evidence that did not exist at the time of the decision being evaluated.
- **Model** — any quantitative/statistical/ML/cost/execution/risk/routing system whose output materially influences a decision. This is broader than an ML model.
- **Agent** — an LLM-backed role invocation; not a persistent person and not evidence by itself.
- **Lane** — a logical stream of independently valuable work, not a permanent agent or fixed process.
- **Useful work** — work with a defensible expected reduction in uncertainty, operational risk, or research cost, or an expected increase in decision quality.

## 1A.2 Epistemic labels

Every decision artifact SHALL distinguish:

- `OBSERVED_FACT`: directly measured and provenance-backed;
- `DERIVED_VALUE`: deterministically calculated from facts;
- `MODEL_ESTIMATE`: output of a quantitative model with uncertainty;
- `LLM_INFERENCE`: semantic/reasoning inference from evidence;
- `HYPOTHESIS`: unverified falsifiable proposition;
- `ASSUMPTION`: explicit premise required for analysis;
- `RECOMMENDATION`: action proposal;
- `UNKNOWN`: unresolved material information.

A recommendation MUST NOT be serialized as a fact. An LLM confidence statement MUST NOT be interpreted as a calibrated probability unless calibration has been demonstrated for that task class.

## 1A.3 Persistent requirement IDs and traceability

Ordinal IDs such as "the third MUST in a section" are forbidden because inserting a new requirement would silently renumber later requirements and break requirement -> implementation -> test traceability.

LIKI SHALL maintain a persistent `requirements_registry.yml` (or equivalent machine-readable registry) whose requirement IDs are immutable opaque identifiers, for example:

```yaml
- requirement_id: LKI-REQ-01JABC...
  source_anchor: 8.9
  text_hash: sha256:...
  requirement_text: "..."
  criticality: CRITICAL
  implementation_refs: []
  test_refs: []
  introduced_by: LIKI_SRS_v1.2
  supersedes: null
  status: unimplemented
```

Bootstrap behavior:

1. the first registry-generation pass assigns an immutable ID (UUIDv7/ULID or equivalent collision-resistant persistent identifier) to every hard normative requirement;
2. exact text/anchor changes do **not** automatically create a silent replacement;
3. if wording changes but the semantic requirement continues, the editor explicitly retains the same ID and records the old/new text hashes;
4. if a requirement is intentionally removed, weakened, split, or superseded, the registry records the governance-linked relationship rather than deleting history;
5. inserting a new requirement never changes existing IDs.

CI SHALL fail when:

- a hard normative requirement exists with no persistent ID;
- an existing requirement disappears without an approved supersession/removal record;
- a CRITICAL requirement lacks implementation and test references at acceptance;
- two active requirements share one ID;
- a requirement text hash changes without an explicit registry update.

The parser SHALL ignore code examples, quoted source material, and informative reference text when generating requirements.

Uppercase `MUST`, `MUST NOT`, `SHALL`, and `SHALL NOT` define hard requirements. `SHOULD`/`SHOULD NOT` are recommendations that may also receive IDs when operationally important. CI SHALL lint lowercase directive language such as "must"/"shall" when it appears to impose a real requirement; authors MUST either convert it to normative uppercase/tagged form or explicitly mark the sentence informative. This prevents untracked requirements hidden in prose.

The generated traceability view SHALL expose:

`requirement_id -> source text/version -> implementation -> tests -> acceptance evidence -> governance history`.

## 1A.4 Definition of Done hierarchy

A feature can have four distinct states:

1. `CODE_COMPLETE`
2. `TEST_COMPLETE`
3. `INTEGRATION_COMPLETE`
4. `ACCEPTED`

Only `ACCEPTED` satisfies this SRS. Agent reports that say "implemented" MUST name the exact state.

---

# 2. Core business objectives

## 2.1 Owner objective

LIKI exists to maximize sustainable owner wealth and income over time while protecting survival and avoiding hidden or unbounded downside.

The target of **USD 10,000/week** is a business milestone for observed forward/paper/live performance and portfolio planning. It MUST NOT:

- be used as a backtest optimization target;
- cause leverage to be increased merely to hit the target;
- override a failed statistical or risk gate;
- be represented as "achieved" using hypothetical gross PnL alone;
- trigger real-money activation automatically.

## 2.2 Research objective

The primary research objective is:

> Discover reproducible, economically explainable or empirically defensible, robust **net edge after all relevant costs**, with sufficient statistical evidence, execution realism, capacity, and portfolio value to justify the next stage of testing.

Research may investigate mechanism-first and empirical-first hypotheses. Mechanism-first research is preferred when practical because a plausible causal/economic mechanism can reduce search space and improve falsifiability, but a strategy MUST NOT be rejected solely because an LLM cannot narrate a compelling story.

## 2.3 Optimization hierarchy

LIKI SHALL optimize lexicographically:

1. constitutional validity and safety;
2. data/provenance correctness;
3. statistical validity and protection from adaptive overfitting;
4. realistic net economics and execution feasibility;
5. robustness and reproducibility;
6. portfolio contribution and risk-adjusted net edge;
7. expected information gained per unit of total research cost;
8. latency/throughput/utilization.

A lower level MUST NOT compensate for a violation at a higher level.

This replaces a single weighted "magic score." Weighted scores MAY be used inside a valid Pareto set for queue ordering, but never to let high upside numerically cancel a hard invalidity.

---

# 3. Scope and non-goals

## 3.1 In scope

LIKI includes:

- adaptive hypothesis generation;
- strategy/mechanism lineage;
- dynamic research lanes;
- data ingestion and point-in-time manifests;
- deterministic backtesting;
- realistic transaction-cost and execution simulation;
- statistical testing and adaptive multiple-testing accounting;
- untouched/guard/sealed validation datasets;
- parameter sensitivity and robustness analysis;
- independent verification;
- forward shadow and paper execution;
- portfolio-candidate evaluation;
- inference routing, fallback, cost governance, and provider health;
- durable memory with contamination controls;
- governance council and controlled self-improvement;
- system simulation, historical replay, and shadow deployment;
- evidence-backed UI/Telegram operations;
- QA, differential testing, chaos testing, and observability;
- future-ready execution interfaces that remain disabled until explicit owner authorization.

## 3.2 Explicitly out of scope at issuance

The following are disabled or non-goals for the initial production research system:

- autonomous real-money trading;
- autonomous wallet/exchange-secret connection;
- changing safety policy without governance;
- claims of guaranteed profit;
- a single LLM acting as final authority;
- optimizing only Sharpe, only PnL, or only hit rate;
- treating synthetic LLM market simulations as real market evidence;
- using an LLM in deterministic order-accounting or risk-enforcement critical paths;
- HFT/ultra-low-latency execution as the initial research target.

---

# 4. LIKI Constitution

The Constitution is deliberately small. These rules are not ordinary tunable gates.

### C-01 — Survival dominates growth
No expected return justifies unbounded, unknown, or inadequately modeled downside.

### C-02 — Unknown risk is risk
A missing cost, data property, liquidity assumption, execution assumption, or critical risk estimate MUST NOT be silently treated as zero.

### C-03 — No hidden leverage
All explicit and implicit leverage, derivatives convexity, liquidation exposure, financing, and correlated notional MUST be represented in risk accounting.

### C-04 — No unpriced material cost
Material fees, spread, slippage, impact, funding, borrow, latency effects, and execution failure MUST be modeled or explicitly bounded before promotion.

### C-05 — No silent gate bypass
Every gate transition has an actor, evidence, reason, policy version, and event.

### C-06 — No self-certification
The actor or agent that materially generated a candidate MUST NOT be the sole verifier that promotes it.

### C-07 — Historical performance is evidence, not proof
A backtest can reject a candidate; it cannot prove future profitability.

### C-08 — Sealed evidence is not an optimization surface
Repeated adaptation to a sealed promotion holdout is forbidden.

### C-09 — Deterministic critical path
Money arithmetic, position accounting, fee calculations, risk limits, order constraints, reconciliation, gate arithmetic, and execution state machines MUST be deterministic.

### C-10 — Capital grows slower than evidence and shrinks faster than evidence deteriorates
Future capital scaling MUST be reversible and asymmetric toward preservation.

### C-11 — Disagreement in critical accounting fails closed
If independent critical calculations disagree beyond defined tolerance, promotion/execution stops.

### C-12 — LIKI may improve itself but may not secretly rewrite its judge
Research agents may propose evaluator/gate changes; they cannot directly deploy changes to the criteria by which their own research is judged.

### C-13 — Real money is human-authorized only
No agent, council, silence timer, Telegram flow, or system upgrade can autonomously enable real-money execution.

### C-14 — Evidence provenance is mandatory
Untraceable evidence is non-promotable evidence.

### C-15 — No utilization theater
Idle compute is preferable to false discoveries generated only to keep agents busy.

### C-16 — No manipulative or unauthorized market conduct
LIKI MUST NOT research, recommend, simulate as an intended production mechanism, or later execute strategies whose edge requires spoofing, wash trading, deceptive order placement, unauthorized access, misuse of confidential information, or violation of applicable venue/data-use rules. Legitimate simulations of such behavior MAY exist only as defensive/adversarial stress tests and MUST be labeled as such.

---

# 5. Operating modes

LIKI SHALL expose explicit operating modes.

| Mode | Historical research | Sealed validation | Forward shadow | Paper orders | Real orders |
|---|---:|---:|---:|---:|---:|
| `RESEARCH` | yes | controlled | optional | no | no |
| `SHADOW` | yes | controlled | yes | no | no |
| `PAPER` | yes | controlled | yes | yes | no |
| `READY_FOR_MICROLIVE` | yes | controlled | yes | yes | **no** |
| `LIVE` | future capability | controlled | yes | yes | only after separate explicit owner enablement |

At issuance, `LIVE` MUST be unreachable.

`READY_FOR_MICROLIVE` is an evidence state, not permission to trade real money.

The owner’s rule "do not connect the wallet before acceptable earnings are observed" is implemented more strictly: LIKI MUST operate without real-money credentials until the owner separately provides and authorizes them. Paper PnL, including the USD 10,000/week milestone, cannot by itself grant live permission.

---

# 6. High-level architecture

```text
                           OWNER
                             |
                     LIKI CONSTITUTION
                             |
                  +----------+----------+
                  |                     |
           GOVERNANCE PLANE        OBSERVABILITY
                  |                     |
          Governance Council        UI / Telegram
          Policy Registry           Audit / Metrics
          Change Simulator              |
                  |                     |
+-----------------+---------------------+------------------+
|                 |                     |                  |
|          INFERENCE BROKER       MEMORY FABRIC        DATA PLANE
|                 |                     |                  |
|     Opus / cheap LLM / token     Evidence ledger     Market data
|     providers / deterministic     Lineage graph       Point-in-time
|                 |                Retrieval firewall  Quality checks
|                 |                     |                  |
+-----------------+----------+----------+------------------+
                           |
                ADAPTIVE RESEARCH FABRIC
                           |
        +------------------+------------------+
        |                  |                  |
 Hypothesis lanes    Verification lanes   Replication lanes
        |                  |                  |
        +------------------+------------------+
                           |
                    RESEARCH FUNNEL
                           |
 G0 -> G1 -> G2 -> G3 -> G4 -> G5 -> G6 -> G7 -> G8 -> G9
                           |
                         G10
                           |
                         G11
                           |
                    FORWARD / PAPER
                         G12
                           |
                  PORTFOLIO READINESS
                         G13
                           |
                  READY_FOR_MICROLIVE
                           |
                  [HUMAN GATE / FUTURE]
```

The architecture SHALL be event-sourced for material state transitions.

The database is the operational source of truth. Markdown/Obsidian MAY be used as a human knowledge interface but MUST NOT be the authoritative transaction, gate, trial, cost, or execution store.

---

# 7. Core domain model

Every important object receives a stable immutable identifier.

## 7.1 Required identifiers

- `task_id`
- `campaign_id`
- `hypothesis_id`
- `mechanism_id`
- `idea_id`
- `strategy_id`
- `strategy_version_id`
- `branch_id`
- `experiment_id`
- `dataset_id`
- `dataset_snapshot_id`
- `evaluator_version_id`
- `artifact_id`
- `evidence_id`
- `gate_decision_id`
- `trial_event_id`
- `holdout_query_id`
- `run_id`
- `inference_request_id`
- `inference_attempt_id`
- `provider_route_id`
- `lease_id`
- `council_proposal_id`
- `council_review_id`
- `simulation_id`
- `paper_run_id`
- `portfolio_candidate_id`

IDs MUST be unique, non-recycled, and stable across retries.

## 7.2 Event envelope

Every material event SHALL include at minimum:

```json
{
  "event_id": "EVT-...",
  "event_type": "...",
  "occurred_at_utc": "...",
  "ingested_at_utc": "...",
  "aggregate_type": "...",
  "aggregate_id": "...",
  "aggregate_version": 1,
  "actor_id": "...",
  "actor_type": "agent|deterministic_service|human|governance",
  "task_id": "...",
  "branch_id": null,
  "strategy_version_id": null,
  "artifact_ids": [],
  "evidence_ids": [],
  "gate_id": null,
  "policy_version": "...",
  "code_commit": "...",
  "environment_fingerprint": "...",
  "metadata": {}
}
```

Events MUST be append-only. Corrections are new events, not history rewrites.

## 7.3 Immutable evaluation snapshot

Every scientific/system evaluation SHALL pin an immutable evaluation snapshot before execution. At minimum it contains:

- candidate/artifact hashes;
- dataset snapshot IDs;
- feature/label registry versions;
- evaluator version;
- Metric Registry version set;
- gate-policy version set;
- execution/cost/risk model versions;
- statistical-method versions and declared parameters;
- environment fingerprint;
- relevant inference/model route identities where an LLM artifact is part of the evidence.

A governance/policy deployment occurring while a run is active MUST NOT silently change the rules applied to that run. The run finishes under its pinned snapshot unless an emergency safety action cancels/quarantines it.

If an emergency or material policy correction invalidates an active/finished snapshot, the old result remains historically auditable but is marked `STALE_BY_POLICY`/`INVALIDATED_BY_POLICY` and cannot be promoted under the new policy without reevaluation.

## 7.4 Replayability versus rerunnability

For deterministic components, reproducibility normally means rerunning the same inputs under the same environment yields the same result within the declared reproducibility tier.

For nondeterministic external LLM/provider calls, LIKI SHALL NOT pretend that an identical future call will reproduce the same text. Scientific/operational replay instead uses the **persisted accepted response artifact** and request/context metadata.

Therefore every decision-relevant inference stores sufficient request/response provenance to replay the downstream decision without asking the provider again. Re-querying the model is a new attempt/reproduction/challenger event, not a reconstruction of history.

External web/document evidence used materially in a decision SHALL store a content hash and, where licensing permits, an immutable snapshot/excerpt sufficient to audit what the agent actually saw. A mutable URL alone is not durable evidence.

---

## 7.5 Concurrency, aggregate revisions, and material-state serialization

Append-only events do not by themselves prevent two correct workers from making incompatible decisions from the same stale state.

Every material mutable aggregate SHALL therefore have a monotonic `aggregate_version`/state revision. Material aggregates include at minimum:

- active task/run state;
- gate state;
- strategy promotion/readiness state;
- policy/governance proposal state;
- inference lease ownership;
- paper/future-live order intent state;
- portfolio/risk readiness state.

A material transition SHALL atomically:

1. verify the expected prior aggregate version/state;
2. write the transition/event;
3. advance the aggregate version;
4. update any authoritative projection required by the same transaction.

If the expected prior version no longer matches, the writer receives `CONCURRENT_MODIFICATION` and MUST reload/reason/reconcile. Last-write-wins is prohibited for scientific, accounting, risk, governance, or order state.

Wall-clock timestamps MUST NOT be used to resolve conflicting material transitions. They are evidence of timing, not concurrency authority.

For each strategy-version/gate pair, the authoritative effective state SHALL be derived from a valid serialized decision chain. Two sibling decisions from the same `state_before` cannot both become authoritative merely because both were individually well-formed.

Idempotency and concurrency control are separate: an idempotency key prevents duplicate replay of one operation; aggregate versioning prevents two different operations from racing on the same state. Both are required where applicable.

---

# 8. Inference Broker

The existing token-governance concept is generalized into an **Inference Broker** because LIKI may use:

- a fixed-price API charging approximately **USD 0.60–0.80 per call**;
- a token-metered fallback/provider charging approximately **USD 1 per 1,000,000 tokens**;
- future providers with different pricing and reliability;
- deterministic algorithms that cost no inference call.

Provider prices are configuration, not source-code constants. The quoted values above are initial owner-supplied economics and SHALL be entered into the provider registry with effective dates.

## 8.1 Requirement: LLM use is value-gated

Before an LLM call starts, the caller MUST specify:

```json
{
  "semantic_task_id": "...",
  "task_class": "...",
  "why_llm_needed": "...",
  "expected_artifact_schema": "...",
  "expected_decision_impact": "...",
  "criticality": "low|normal|high|critical",
  "preferred_reasoning_effort": "...",
  "max_call_cost_usd": 0.8,
  "max_total_attempt_cost_usd": null,
  "max_latency_sec": null,
  "idempotency_key": "...",
  "allowed_provider_classes": [],
  "fallback_policy_id": "..."
}
```

A call with no expected artifact or decision impact is denied unless it is an explicit exploratory research call.

## 8.2 Routing hierarchy

Work SHALL be routed to the cheapest reliable capability that meets the task’s historical quality requirement:

1. deterministic algorithm;
2. deterministic tool + rules;
3. cheap/small LLM;
4. Opus 5 standard reasoning;
5. Opus 5 higher reasoning effort;
6. independent additional Opus verification;
7. future cross-family model when available.

The router MUST learn from observed task-class accuracy, schema compliance, correction rate, downstream gate reversals, latency, and cost.

A cheap model SHALL be promoted out of a task class if its error/correction rate is persistently unacceptable. A task class SHALL be demoted from Opus when cheaper execution has demonstrated sufficient quality under shadow comparison.

## 8.3 Provider reliability and fallback

The owner expects an individual provider/request success rate near **80%** in some routes. LIKI MUST remain live despite this.

If failures were independent, success after `n` attempts would be:

`P(success by n) = 1 - (1 - p)^n`

For `p = 0.80`:

| Attempts | Theoretical success if independent |
|---:|---:|
| 1 | 80.00% |
| 2 | 96.00% |
| 3 | 99.20% |
| 4 | 99.84% |

LIKI MUST NOT assume failures are independent. Provider outages, rate limits, shared upstreams, and model backend incidents can create correlated failures.

Therefore fallback uses route diversity, circuit breakers, and task hibernation, not blind retry loops.

## 8.4 Attempt state machine

```text
CREATED
  -> ADMITTED
  -> PRIMARY_ATTEMPT
      -> SUCCESS
      -> RETRYABLE_FAILURE
           -> SAME_ROUTE_RETRY (bounded, jittered)
           -> ALTERNATE_KEY/ENDPOINT
           -> ALTERNATE_PROVIDER
           -> TOKEN_METERED_FALLBACK
           -> HIBERNATE_AND_REQUEUE
      -> NONRETRYABLE_FAILURE
           -> REPAIR/ESCALATE/FAIL
```

### Default retry behavior

Defaults are policy values and may be calibrated:

- same route immediate retry: maximum 1 after transient network/5xx/timeout;
- exponential backoff with jitter for repeated provider errors;
- route circuit breaker after a configurable rolling failure threshold;
- provider health probes are cheap and separate from valuable research requests;
- critical requests MAY use a delayed hedged request to a second independent route;
- noncritical requests SHOULD hibernate and let other useful work proceed rather than fan out expensive duplicate calls.

## 8.5 Idempotency

An inference retry MUST NOT duplicate a side effect.

LLM output and deterministic side effects are separate transactions.

Backtests, data downloads, artifact writes, gate mutations, paper orders, and future order submissions MUST each have their own idempotency keys.

If an API times out after server-side success, LIKI MUST reconcile by request/operation ID before retrying the side effect.

## 8.6 Broken but useful outputs

- syntactically invalid structured output -> deterministic parser recovery first;
- recoverable schema mismatch -> cheap repair model if deterministic repair cannot be proven safe;
- truncated response -> continuation/recovery using the same semantic request;
- semantically weak result -> new independent reasoning attempt, not cosmetic repair;
- contradictory critical result -> verifier escalation.

Repair calls MUST be attached to the original semantic task for cost accounting.

## 8.7 Inference cost accounting

The ledger SHALL store:

- exact/provider-reported/estimated tokens;
- price model;
- fixed call price;
- token price;
- reasoning effort;
- retries;
- cache hits;
- repair calls;
- successful and failed calls;
- artifact produced;
- whether the call changed a downstream decision.

Primary metrics:

- `usd_per_valid_artifact`
- `usd_per_useful_finding`
- `expensive_calls_per_surviving_branch`
- `decision_change_rate_per_expensive_call`
- `repair_rate`
- `retry_recovery_rate`
- `provider_correlated_failure_rate`
- `wasted_inference_cost_usd`
- `provider_billing_reconciliation_error_usd`

## 8.8 24/7 behavior

24/7 means **continuous useful system operation**, not continuous LLM calls.

When one inference provider is unavailable, LIKI SHALL:

1. route eligible tasks elsewhere;
2. continue deterministic work;
3. continue data ingestion;
4. continue backtests/evaluations;
5. run replication and QA;
6. hibernate blocked tasks;
7. reawaken tasks after provider health recovery.

No provider outage may freeze the entire office unless all work is genuinely blocked.

---

## 8.9 Route economics and break-even mathematics

The Inference Broker SHALL optimize **expected accepted-result cost**, not raw call price.

For a token-metered route with total billed tokens `T` and price `P_m` USD per one million tokens:

`C_token = T * P_m / 1,000,000`

For a fixed-call route with call price `C_fixed`, direct-cost break-even is:

`T_break_even = C_fixed * 1,000,000 / P_m`

The uniform-token formula above is an illustrative special case. The production cost engine SHALL support provider-specific billing functions including separate input/output/reasoning/cache-read/cache-write rates, fixed per-request charges, minimum charges, tiers, discounts, or other documented units.

A route therefore exposes a versioned `pricing_formula` and `pricing_effective_at`; callers do not hardcode one global token price. Break-even examples in this SRS apply only to the owner-supplied uniform USD 1/1M route assumption.

Under the owner-supplied initial token price `P_m = USD 1.00 / 1M tokens`:

- `USD 0.60/call` breaks even at **600,000 billed tokens/call**;
- `USD 0.80/call` breaks even at **800,000 billed tokens/call**.

Therefore, if quality/reliability are comparable, the token-metered route is economically preferred for a 50k-token call by approximately 12x versus USD 0.60/call and 16x versus USD 0.80/call. The broker MUST compute this from live price configuration rather than hardcode the conclusion.

For independent per-attempt success probability `p` and capped attempts `n` on the same route:

`P_success(n) = 1 - (1 - p)^n`

`E[calls(n)] = sum_{i=0}^{n-1}(1-p)^i = [1-(1-p)^n]/p`

For `p=0.80, n=3`, `E[calls]=1.24` and `P_success=0.992`.

Illustratively:

- at USD 0.60/call, expected spend before completion/final failure is USD **0.744**; divided by 0.992 completion probability this is approximately USD **0.75 per completed semantic request** under the independence assumption;
- at USD 0.80/call, expected spend is USD **0.992**; approximately USD **1.00 per completed semantic request** under the same assumption.

These equations MUST NOT be used to assume outage independence. Actual routing uses measured route/provider/upstream failure correlation.

The route objective is lexicographic:

1. satisfy minimum historical quality/schema/safety requirement;
2. satisfy criticality-specific reliability requirement;
3. satisfy latency/deadline requirement;
4. among eligible routes minimize expected accepted-result cost.

A cheaper route that creates more downstream correction/rework may be more expensive in total and SHALL be evaluated accordingly.

## 8.10 Semantic batching for fixed-price APIs

Fixed-per-call pricing creates a strong incentive to batch work, but naive batching creates correlated failure and quality loss.

LIKI MAY batch multiple items into one inference request only when all are true:

- items share substantially the same evidence/context package;
- no item requires independence from another item in the batch;
- no generator and its verifier are placed in the same call;
- each item has an independent `subtask_id` and output schema;
- a malformed/failed item can be retried without duplicating side effects from successful items;
- predicted context/output size remains safely below provider limits;
- historical batch-quality calibration has not fallen below the task-class quality floor.

Batch size SHALL be adaptive and learned from accepted-artifact rate, omission rate, cross-item contamination, latency, and rework cost. Unrelated tasks MUST NOT be batched merely to amortize USD/call.

## 8.11 Context Compiler

All nontrivial LLM calls SHALL be constructed by a `ContextCompiler`, not by concatenating arbitrary chat history.

The compiled context package includes:

- task contract;
- role and allowed decisions;
- required raw evidence references;
- compact deterministic summaries;
- relevant memory claims with confidence/provenance;
- explicit unknowns/conflicts;
- tool capabilities;
- forbidden data/holdout access;
- expected output schema;
- stop condition;
- context manifest hash.

A lossy summary MUST NOT be the sole support for a critical financial/statistical/gate decision when underlying evidence is available.

Compression artifacts SHALL retain pointers/hashes to canonical originals so a verifier can expand them.

Fresh-context reviewers receive only their controlled evidence pack, never an accumulated conversational transcript.

## 8.12 Prompt/model reproducibility

Every inference attempt SHALL persist:

- model family and externally reported version/snapshot where available;
- provider route and upstream correlation domain;
- reasoning effort;
- system/developer/task prompt hashes;
- context-manifest hash;
- tool schema/version hashes;
- temperature/sampling parameters when exposed;
- request time and provider response metadata;
- output artifact hash.

Provider-side model drift SHALL be treated as model-version drift even if an alias name remains unchanged. Material behavior drift triggers re-benchmarking of affected task classes.

No gate may depend on hidden chain-of-thought. Gate evidence MUST be the structured output, deterministic calculations, cited evidence, and reproducible artifacts.

## 8.13 Budget and burn circuit breakers

Budgeting SHALL exist simultaneously in:

- USD;
- fixed-price calls;
- billed/estimated tokens;
- compute/GPU time;
- wall time;
- statistical capital.

Hourly/daily/campaign budgets are owner-configurable policy, not SRS hard constants.

The broker SHALL implement:

- soft warning threshold;
- hard new-work throttle;
- emergency circuit breaker for anomalous burn;
- per-semantic-task maximum attempt budget;
- per-branch and per-campaign attribution.

Budget exhaustion MUST stop new discretionary expensive work but SHOULD allow cheap reconciliation, safe shutdown, artifact persistence, and owner notification.

## 8.14 Provider/key pool and failure-correlation domains

Keys, endpoints, and providers SHALL be represented separately.

A route contains:

- provider;
- upstream/model backend if known;
- account/key pool;
- endpoint/base URL;
- quota/rate-limit state;
- price plan;
- health state;
- inferred failure-correlation domain.

Two API keys sharing the same upstream are not independent fallbacks.

Key rotation MUST be quota/health driven, not random. API keys are secrets and MUST NOT be placed in LLM context.

Provider health states SHALL include at least:

`HEALTHY`, `DEGRADED`, `RATE_LIMITED`, `AUTH_FAILED`, `QUOTA_EXHAUSTED`, `OPEN_CIRCUIT`, `UNKNOWN`.

## 8.15 Inference result cache

Semantically pure LLM tasks MAY be cached by a fingerprint over prompt/context/model/tool policy when reuse does not violate independence requirements.

Cache reuse is forbidden when:

- a fresh independent review is required;
- evidence changed materially;
- model/version-specific reevaluation is required;
- the output would leak a sealed result;
- task randomness/diversity is intentional.

Cache hits remain auditable and cost-attributed as reused inference.

---

## 8.16 Reasoning-effort policy

Reasoning effort is a routed resource, not a prestige setting.

The broker SHALL maintain outcome/cost calibration by task class for each available effort level.

Higher effort is preferred when:

- the decision is critical or hard to reverse;
- prior reviewers disagree materially;
- the task requires long-horizon causal/statistical reasoning;
- a cheaper attempt failed semantically rather than syntactically;
- downstream cost of an error greatly exceeds incremental inference cost.

Lower effort is preferred for well-specified extraction, formatting, classification, implementation of a fully specified deterministic change, or tasks where tool output dominates reasoning.

The system MUST NOT assume "higher effort = always better." Promotion of an effort level for a task class requires measured accepted-artifact/reversal performance.

## 8.17 Expected total cost of reasoning

Route comparison SHALL include downstream rework:

`C_total = C_inference + E[C_repairs + C_retries + C_downstream_rework + C_delay]`

If a cheap model produces artifacts that repeatedly cause expensive backtest/reviewer rework, the router SHALL learn that its effective cost is higher.

Conversely, Opus SHOULD NOT be used for deterministic arithmetic/status queries merely because the direct call price is affordable.

---

## 8.18 Provider billing semantics and reconciliation

The Provider Registry SHALL record whether failed, cancelled, timed-out, retried, cached, or partial requests are billable under each price plan when this information is known.

Route economics MUST use **expected billed cost**, not assume a failed request costs zero.

At least daily when provider billing data is available, LIKI SHOULD reconcile:

- internal attempt count;
- internally estimated billed tokens/calls;
- provider-reported usage;
- provider invoice/account balance deltas.

Material discrepancies create a `BILLING_RECONCILIATION_ERROR` and block claims that inference economics are exact until resolved.

## 8.19 Context relevance even when tokens are cheap/free per call

A fixed-call provider may make additional tokens financially cheap, but irrelevant context still has cognitive/latency/quality cost.

The ContextCompiler SHALL optimize for **decision-relevant evidence density**, not maximize context length.

Large raw evidence may be tool-addressable rather than always preloaded. Critical omissions and excessive irrelevant context are both measured through downstream error/reversal rates.

---

## 8.20 Success is layered, not HTTP status

Inference health SHALL distinguish:

1. `TRANSPORT_SUCCESS` — request completed at protocol/provider level;
2. `SCHEMA_SUCCESS` — response parses and satisfies required output schema;
3. `SEMANTIC_ACCEPTANCE` — artifact passes task-specific deterministic/independent acceptance checks;
4. `DECISION_USEFUL` — artifact actually contributed useful information or a justified decision.

Provider "80% success" MUST state which layer it refers to.

Routing quality primarily uses `SEMANTIC_ACCEPTANCE` and downstream reversal/rework, not HTTP 2xx rate.

An empty/refusal/off-task 200 response is not a successful semantic request.

## 8.21 Provider capability contract

Each route SHALL record where known:

- context-window limit;
- maximum output limit;
- supported reasoning-effort values;
- tool/function support;
- streaming support;
- timeout behavior;
- continuation semantics;
- provider-side caching indicators if exposed;
- rate limits;
- billing semantics.

A request is not routed to a provider that cannot fit the compiled context + reserved output headroom.

## 8.22 Provider identity, integrity, and capability verification

A route label such as `opus-5` is a provider claim, not cryptographic proof of model identity.

The Provider Registry SHALL distinguish:

- `claimed_model_name`;
- provider/upstream identity where known;
- `identity_assurance = OFFICIAL_ATTESTED|PROVIDER_ASSERTED|BLACK_BOX_ONLY|UNKNOWN`;
- last capability benchmark;
- material behavioral drift indicators.

LIKI MUST judge routing fitness primarily by measured task-class quality, reliability, safety, and cost. It MUST NOT infer reviewer independence merely because two reseller endpoints expose different names while sharing an unknown upstream.

Where practical, canary capability tasks SHALL detect silent degradation, wrong context/output limits, schema/tool regressions, or material behavior changes. Canary results are diagnostic and cannot prove a proprietary model's exact identity.

Key pools and fallback routes MUST comply with provider authorization/terms. LIKI SHALL NOT rotate credentials for the purpose of evading explicit provider safety, account, or rate-limit controls.

## 8.23 Router exploration and selection-bias control

A self-learning inference router receives selective feedback: a route used mostly on easy tasks can appear better than a route reserved for hard tasks. Naively learning from accepted artifacts therefore creates routing-selection bias.

The router SHALL maintain a controlled calibration/challenger mechanism that may include:

- shadow evaluation on common benchmark tasks;
- randomized or stratified route comparisons within safe task classes;
- difficulty/criticality conditioning;
- counterfactual/off-policy analysis where defensible;
- confidence intervals around route quality/cost estimates.

Exploration traffic is explicitly budgeted and MUST NOT be used on sealed decisions requiring independence unless the protocol permits it. A route may not become permanent champion solely because the router stopped sending it difficult work.

## 8.24 Semantic checkpointing for long reasoning workflows

For long multi-stage tasks, LIKI SHOULD persist **semantic checkpoints** at meaningful task boundaries (for example research contract, evidence map, implementation plan, verifier packet) so a provider failure does not force unrelated completed work to be regenerated.

Semantic checkpoints are structured artifacts, not hidden chain-of-thought.

Checkpointing MUST NOT arbitrarily split a reasoning task when doing so measurably reduces solution quality. The Inference Broker chooses atomic versus staged reasoning based on task-class quality/recovery evidence.

A continuation after failure receives only validated checkpoint state and required evidence; it does not assume the missing provider-side hidden reasoning can be recovered.

---

## 8.25 Context completeness, evidence-manifest, and omission defense

A reasoning model can be perfectly coherent and still make a dangerous decision when the ContextCompiler silently omits one material fact. Context quality therefore has a **completeness contract**, not only a token/relevance objective.

Every MATERIAL/CRITICAL inference request SHALL persist a `context_manifest` containing at least:

- required evidence classes for the task;
- all candidate evidence/artifact IDs considered by retrieval;
- evidence actually included inline;
- evidence exposed through tools/on-demand access;
- material evidence intentionally excluded and the policy reason;
- summaries/compressions used and their canonical source IDs;
- truncation decisions;
- retrieval/index version and query/fingerprint;
- data-classification/egress decision;
- an explicit `context_completeness_status`.

Allowed completeness states are `COMPLETE_FOR_CONTRACT`, `INCOMPLETE_BLOCKING`, and `INCOMPLETE_DECLARED_NONCRITICAL`.

For a CRITICAL task, missing a required evidence class SHALL produce `INCOMPLETE_BLOCKING`; the call MUST NOT be accepted as an authoritative review/decision merely because the model returned a confident answer.

The ContextCompiler SHALL distinguish **not relevant** from **not retrieved**. Retrieval failure, index lag, permission failure, oversized evidence, or tool timeout MUST NOT be silently converted into absence of evidence.

If evidence is tool-addressable rather than preloaded, the model receives a manifest that states what can be expanded. Tool reads used during reasoning are appended to the manifest so the accepted result has a reproducible evidence-access record.

Critical context truncation MUST be semantic/priority-aware. Blind tail/head token truncation that can remove constraints, counterevidence, risk limits, or evaluator assumptions is prohibited.

Independent reviewers may deliberately receive different controlled contexts to preserve independence, but each reviewer contract SHALL define the evidence classes it is required to receive. "Fresh context" is not permission to omit adverse raw evidence.

LIKI SHALL benchmark retrieval omission using seeded tasks where one necessary adverse fact is difficult to retrieve. A system that reasons well only when every fact is conveniently placed in the prompt is not accepted.


# 9. Adaptive Research Fabric

## 9.1 No fixed permanent lane count

LIKI SHALL NOT define intelligence by a fixed number of agents or lanes.

The number of active research lanes is a dynamic consequence of:

- number of independent valuable hypotheses;
- expected information value;
- research cost;
- data/statistical-capital cost;
- provider/compute capacity;
- evaluator throughput;
- duplication probability;
- current uncertainty;
- portfolio need;
- queue aging;
- exploration requirements.

The inherited V3.3 configuration of **3 autonomous lanes**, potentially **4 when stable**, is a safe initial boot profile, not the final optimum.

Per-process Codex concurrency SHALL remain **1** until the historical timeout-storm condition is explicitly proven resolved under fault tests. Scaling SHOULD initially occur by independent worker/lane processes rather than unsafe in-process concurrency.

## 9.2 Lane types

Logical lane classes include:

- `EXPLOIT`: refine/confirm promising mechanisms;
- `ALTERNATIVE`: independent competing mechanisms;
- `NOVELTY`: deliberately different hypothesis families;
- `FALSIFICATION`: attack strong candidates;
- `REPLICATION`: reproduce findings independently;
- `DATA_QA`: investigate data uncertainty;
- `EXECUTION_QA`: execution/economics investigations;
- `SYSTEM_QA`: evaluator and infrastructure validation;
- `GOVERNANCE`: policy-review work.

A lane class is not necessarily a permanent agent process.

## 9.3 Dynamic allocation

LIKI SHALL use a constrained allocation process, not one all-purpose weighted score.

Order of decisions:

1. remove inadmissible tasks under hard constraints;
2. merge/deduplicate semantically equivalent work;
3. construct a Pareto set over expected information gain, potential economic importance, novelty, cost, time, uncertainty, and statistical-capital consumption;
4. protect required exploration and replication capacity;
5. rank remaining work by estimated **Value of Information (VOI)** per total cost;
6. apply queue aging/starvation protection;
7. launch only while useful work exists.

The exact VOI estimator MAY evolve. Its calibration MUST be evaluated against realized downstream decisions and discoveries.

## 9.4 Exploration budget

Initial guidance:

- exploitation: typically 45–60% of discretionary research capacity;
- independent alternatives: typically 20–30%;
- high-novelty exploration: typically 5–15%;
- remaining capacity: replication/falsification/QA.

These are **operating ranges, not permanent quotas**.

A hard exploration floor SHALL normally remain at **5%** of discretionary research budget unless the system is in emergency/incident mode.

Exploration MAY rise above 15% when:

- discovery yield has stagnated;
- active families have converged;
- repeated marginal improvements indicate local optimum;
- market regime changed materially;
- portfolio diversification need is high.

Exploration MAY fall temporarily when a high-value candidate requires urgent falsification/reproduction, but SHALL not be permanently starved.

## 9.5 Work-conserving, not work-inventing

If a valuable primary task is waiting, LIKI follows this idle-work ladder:

1. other independent high-value research;
2. replication;
3. falsification;
4. parameter/sensitivity tests already justified;
5. data QA and reconciliation;
6. execution-model calibration;
7. failed-branch mining;
8. experiment cache/indexing;
9. memory consolidation;
10. code/property/mutation tests;
11. governance debt;
12. provider benchmarking;
13. maintenance.

If no item has positive expected operational/research value, LIKI MAY idle.

Generating random hypotheses solely to keep utilization at 100% is forbidden.

---

## 9.6 Dynamic lane-count controller

Scientific allocation and infrastructure concurrency are separate control problems.

### Scientific lane admission

For every queued research task `i`, LIKI estimates a distribution for:

- `VOI_i`: value of information;
- `C_i`: total research cost;
- `D_i`: duplication probability;
- `S_i`: statistical-capital consumption;
- `T_i`: time to decision-changing evidence.

A normal lane is created only when the conservative marginal value of additional work is positive after costs and there is resource headroom. If uncertainty is too high for a normal lane but the candidate is Pareto-relevant, it may use the bounded Frontier allocation.

The system SHALL not scale lane count merely because market prices became volatile; it scales because the number/value/urgency of independent research questions changed. Market regime change can create new questions, but raw volatility is not itself a concurrency command.

### Infrastructure concurrency controller

Each task class has an independent concurrency ceiling. Initial boot uses the inherited conservative profile (3 autonomous research lanes; per-process Codex concurrency 1). A shadow controller learns safe capacity from queue latency, CPU/RAM/I/O/GPU pressure, provider failure rate, DB latency, and evaluator throughput.

A safe default controller MAY use additive-increase/multiplicative-decrease behavior:

- add capacity only after multiple consecutive healthy control epochs and positive queued value;
- reduce capacity immediately on hard resource pressure, correlated provider failure, timeout storm, or DB/evaluator saturation;
- apply hysteresis/cooldown to prevent oscillation.

The exact epoch and step sizes live in the Policy Registry and require shadow calibration.

### Lane retirement

A lane stops or hibernates when:

- its task completes;
- hard invalidity is found;
- marginal VOI becomes non-positive;
- a duplicate/equivalent branch dominates it;
- its evidence is superseded;
- resources are needed for higher-priority admissible work;
- no next experiment has positive expected value.

A lane is a scheduling construct and MUST NOT be kept alive to preserve an agent persona.

---

## 9.7 Hierarchical research-budget allocation

Research capacity SHALL be allocated hierarchically rather than by one flat queue:

```text
Office budget
 -> market/universe opportunity buckets
 -> mechanism/strategy families
 -> branch/experiment tasks
```

At every layer, LIKI preserves exploration and avoids funding many near-duplicates merely because one family recently performed well.

Budget allocation inputs include:

- current evidence maturity;
- number of genuinely distinct hypotheses;
- estimated VOI;
- capacity/liquidity relevance;
- portfolio diversification need;
- structural market changes;
- historical false-positive/false-negative behavior of the relevant gates;
- research cost and statistical-capital consumption.

A market receiving more lanes is not assumed to be more profitable; it means the system currently has more valuable unresolved questions there.

## 9.8 Market Structure / Regime Monitor

LIKI SHALL maintain a diagnostic market-state monitor using deterministic/statistical tools for variables such as:

- realized/implied volatility where available;
- spread/depth/liquidity;
- volume/participation;
- funding/basis;
- cross-asset correlation;
- trend/dispersion;
- venue status;
- collateral/reference-price stress.

Change-point or regime-detection methods MAY propose that the research opportunity set changed, but regime labels are uncertain model outputs.

Rules:

- regime detection may re-prioritize research or trigger revalidation;
- it MUST NOT automatically declare an old strategy dead or a new strategy profitable;
- hysteresis/minimum evidence prevents lane thrashing on short-lived noise;
- any regime-conditioned strategy MUST obey point-in-time label availability.

## 9.9 Mechanism-space coverage

Novelty SHALL be measured at the mechanism/intervention level, not by wording similarity alone.

LIKI SHOULD maintain a coverage map over structured dimensions such as:

- signal source;
- economic mechanism;
- horizon;
- market/universe;
- execution style;
- directional vs relative-value;
- required data type;
- risk exposure.

The allocator uses this map to detect research monoculture and to seed independent alternatives when the office converges too narrowly.

---


## 9.10 Research allocator selection-bias and propensity logging

A self-improving research allocator observes outcomes only for work it chooses to fund. This creates a selective-feedback problem analogous to the Inference Router problem in Section 8.23: families receiving more budget generate more chances to look good, while unfunded families generate no counterfactual outcomes.

Therefore every allocation decision SHALL record:

- candidate task set visible at decision time;
- features/evidence used by the allocator;
- chosen tasks and budget;
- estimated selection probability/propensity where the policy is stochastic or can provide one;
- allocator policy/version;
- exploration-versus-exploitation reason;
- tasks excluded by hard constraints separately from tasks merely not selected;
- realized downstream outcome once available.

Allocator evaluation MUST NOT compare raw discovery counts between heavily funded and lightly funded families as though exposure were equal.

Shadow/challenger allocators SHALL be compared on common replay sets and, where safe, controlled randomized/stratified exploration. Off-policy or inverse-propensity analyses MAY be used only when their assumptions and variance are reported.

A branch receiving more research because of favorable early evidence is an adaptive selection event and remains represented in the Trial Ledger. Budget allocation cannot reset or hide multiplicity.

The allocator MUST preserve an explicit record of opportunity cost: what admissible work was displaced by the chosen work. This is required for later VOI calibration and decision-regret analysis.

---

# 10. Agent organization and separation of powers

## 10.1 Agent roles

LIKI SHOULD use roles as capabilities and responsibilities, not as theatrical avatars.

Core role families:

### Research Office
- Research Director
- Mechanism Researcher
- Strategy Researcher
- Alternative-Hypothesis Researcher
- Literature/External-Evidence Researcher

### Data Office
- Data Engineer
- Data Quality Auditor
- Point-in-Time/Leakage Auditor

### Quant/Statistics Office
- Statistician
- Multiple-Testing Auditor
- Robustness/Sensitivity Analyst

### Execution Office
- Microstructure Analyst
- Cost/Slippage Analyst
- Capacity Analyst
- Paper-Execution Analyst

### Risk/Portfolio Office
- Risk Analyst
- Portfolio Construction Analyst
- Correlation/Concentration Analyst

### Independent Verification Office
- Reproduction Agent
- Skeptic
- Adversarial Reviewer

### Systems Office
- Runtime Reliability Agent
- Evaluator QA Agent
- Security/Policy Auditor

### Governance Office
- Council Reviewers
- Adversarial Governance Auditors
- Synthesis Chair

## 10.2 No fake activity

A named agent is "Running" only with:

- real `active_task_run`;
- fresh heartbeat;
- valid deterministic worker lease or inference lease;
- `why_running`;
- expected artifact;
- current task/gate;
- event-backed status.

The V3.3 truthful-state rules remain mandatory.

## 10.3 Fresh-context verification

For critical verification, reviewers MUST begin with fresh model sessions and receive a controlled evidence package.

Independent reviewers MUST NOT see:

- prior reviewers’ verdicts;
- prior chain-of-discussion summaries;
- popularity/majority counts;
- non-evidentiary persuasive commentary.

They MAY see:

- raw evidence;
- methodology;
- artifacts;
- relevant policies;
- declared hypothesis;
- necessary lineage;
- known conflicts of interest.

After blind reviews are complete, a synthesis stage may compare them.

## 10.4 Same-model independence limitations

Multiple Opus 5 instances are not statistically independent models.

LIKI SHALL explicitly record:

- `model_family`;
- `model_version`;
- `provider_route`;
- `reasoning_effort`;
- `prompt_role`;
- `evidence_ordering_profile`.

Procedural diversity (different reviewer mandates and evidence ordering) is required when only one model family exists.

When another strong model family becomes available, Governance SHOULD add cross-family verification to critical decisions after calibration.

---

## 10.5 Agent Task Contract

Every agent invocation SHALL receive an explicit task contract:

```json
{
  "agent_run_id": "...",
  "role": "...",
  "question": "...",
  "decision_authority": [],
  "input_evidence_ids": [],
  "forbidden_evidence_classes": [],
  "allowed_tools": [],
  "expected_artifact_schema": "...",
  "success_condition": "...",
  "stop_condition": "...",
  "max_inference_budget": {},
  "max_tool_budget": {},
  "independence_group_id": null,
  "parent_run_id": null
}
```

An agent that cannot produce the requested artifact MUST return a structured failure/unknown rather than invent content.

## 10.6 Agent-to-agent communication

Artifacts, not open-ended conversation, are the default inter-agent protocol.

Free-form multi-agent chat loops are prohibited unless an explicit deliberation protocol requires them. This prevents token burn, anchoring, and untraceable decisions.

A handoff artifact SHALL contain:

- claims;
- evidence references;
- unresolved questions;
- assumptions;
- requested next action;
- no hidden dependence on conversational context.

## 10.7 Agent confidence and calibration

Agents MAY report confidence, but self-reported confidence is advisory until calibrated.

For task classes with objectively scorable outcomes, LIKI SHALL maintain calibration statistics such as reliability curves/Brier score or equivalent proper-scoring diagnostics.

Routing and council weighting MAY use demonstrated calibration and historical error patterns; they MUST NOT use eloquence, token length, or self-confidence as proxies for correctness.

## 10.8 Agent performance lifecycle

Each role/prompt/model configuration has a scorecard:

- artifact validity;
- factual/evidence error rate;
- downstream reversal rate;
- missed-critical-objection rate;
- false-objection rate;
- cost;
- latency;
- calibration;
- independence contamination events.

Poor configurations enter shadow/challenger status or are retired. Historical agent score MUST NOT override current raw evidence.

## 10.9 Deliberation stopping rule

Additional reviewers are commissioned only while they have positive expected information value or a required independence quorum remains unmet.

LIKI SHALL not run reviewer-after-reviewer until someone agrees with the desired answer. If evidence remains genuinely ambiguous, the correct state is `NEEDS_MORE_INFORMATION` or `BORDERLINE`.

---

## 10.10 Tool Capability Registry and Tool Router

LIKI SHALL maintain a machine-readable registry of tools rather than letting agents improvise tool usage.

Each tool record contains:

```json
{
  "tool_id": "...",
  "version": "...",
  "purpose": "...",
  "input_schema": "...",
  "output_schema": "...",
  "deterministic": true,
  "cost_model": "...",
  "latency_model": "...",
  "trust_level": "trusted|sandboxed|external_untrusted",
  "side_effects": [],
  "required_capabilities": [],
  "known_failure_modes": []
}
```

The ContextCompiler exposes only task-relevant tools.

Rules:

- deterministic calculation tools beat LLM mental arithmetic;
- backtest/statistical tools beat LLM guesses about measured results;
- LIKISim is used only when its evidence tier is appropriate;
- a tool is not called merely because it exists;
- tool outputs used in a gate are schema-validated and provenance-recorded;
- destructive/side-effecting tools require stricter capability policy than read-only tools.

Tool-use efficiency is benchmarked by decision value, not tool-call count.

## 10.11 External research and literature evidence

Agents MAY use papers, documentation, public web sources, and other research inputs when permitted.

External claims SHALL record source, publication/update time when relevant, retrieval time, and whether the source is primary/secondary.

For material literature/documentation evidence, LIKI SHOULD also capture version/DOI/revision identity and known correction/retraction/supersession status where discoverable. A later correction or vendor-documentation change creates an evidence-update event; old research remains auditable but may require reevaluation.

Published research is hypothesis/evidence context, not proof that an edge survives current costs or market conditions.

For historical-discovery experiments, sources published after the simulated decision cutoff create hindsight contamination and MUST be tagged.

---

## 10.12 Thinker -> Executor -> Verifier contract

For expensive reasoning tasks, LIKI SHOULD separate semantic invention from routine implementation when doing so reduces cost without losing intent.

Typical flow:

```text
Opus/strong Thinker
 -> structured Decision/Implementation Plan
 -> deterministic executor or cheaper LLM executor
 -> tests
 -> independent Verifier
```

A plan artifact SHALL include where relevant:

- objective/hypothesis;
- exact intended intervention;
- permitted files/modules;
- invariants that MUST NOT change;
- expected output/artifact schema;
- explicit non-goals;
- acceptance tests;
- known ambiguities requiring escalation.

The executor is not authorized to silently change the research question, evaluator, gate, data split, or risk semantics.

Material deviation from the plan produces `PLAN_DEVIATION` and requires thinker/verifier review. Trivial implementation details may vary if they do not alter semantics.

This contract is the preferred way to exploit expensive high-quality reasoning while using cheaper models/tools for well-specified execution.

## 10.13 Plan quality feedback

A failed executor is not automatically an executor failure. LIKI SHALL classify whether failure originated from:

- ambiguous/wrong plan;
- executor misunderstanding;
- missing tool/capability;
- environment/infrastructure;
- invalid hypothesis.

This classification feeds Thinker/Executor routing calibration so expensive models are not rewarded for producing impossible plans.

---

# 11. Memory Fabric

## 11.1 Memory layers

### M0 — Immutable Evidence Ledger
Raw event/evidence history. Never summarized away as the only copy.

### M1 — Strategy & Experiment Lineage Graph
Relationships between hypotheses, mechanisms, code versions, data, experiments, findings, and gates.

### M2 — Domain Knowledge Memory
Reusable validated findings, failures, market-mechanism observations, execution lessons.

### M3 — Working Memory
Task-specific short-lived context assembled for an agent.

### M4 — Cold Archive
Low-confidence, obsolete, invalidated, or old material retained for audit but excluded from normal retrieval.

Obsidian or similar tools MAY visualize M1/M2 for the owner. They are not the source of truth.

## 11.2 Memory object fields

Each durable knowledge item MUST contain:

```json
{
  "memory_id": "...",
  "claim": "...",
  "claim_type": "...",
  "source_evidence_ids": [],
  "confidence_state": "unverified|candidate|replicated|invalidated",
  "market_scope": [],
  "regime_scope": [],
  "mechanism_scope": [],
  "created_at": "...",
  "last_revalidated_at": "...",
  "policy_version": "...",
  "contamination_tags": [],
  "known_counterevidence_ids": [],
  "supersedes": []
}
```

## 11.3 Retrieval Firewall

Agents MUST NOT receive "all memory."

Retrieval is policy-controlled by:

- task purpose;
- role;
- market/mechanism relevance;
- evidence maturity;
- age;
- contamination status;
- holdout restrictions;
- independence requirements.

Example:

- researcher may see prior failed-family knowledge to avoid duplicate waste;
- independent verifier may see raw evidence but not prior reviewer opinions;
- sealed-holdout evaluator MUST NOT reveal raw sealed metrics;
- governance reviewers may see broad operational history but not unnecessary secrets.

## 11.4 Memory contamination

Every memory item MAY carry contamination tags such as:

- `saw_guard_holdout`
- `saw_sealed_category`
- `saw_forward_result`
- `derived_from_rejected_strategy`
- `post_hoc_explanation`
- `synthetic_only`
- `same_model_review`

A task touching sealed evidence MUST propagate contamination to descendants as defined by policy.

Contaminated research MAY be scientifically useful but cannot masquerade as untouched.

## 11.5 Memory decay

Confidence may decay with:

- age;
- market structural change;
- contradictory forward evidence;
- data-provider revision;
- execution-model drift.

Raw evidence never decays away. Only the prior weight assigned to a generalized memory claim changes.

---

# 12. Hypothesis, strategy lineage, and Adaptive Trial Ledger

A simple "number of variants tried" counter is insufficient.

## 12.1 Lineage edges

Required edge types:

- `derived_from`
- `parameter_variant_of`
- `mechanism_variant_of`
- `data_variant_of`
- `execution_variant_of`
- `portfolio_variant_of`
- `independent_reimplementation_of`
- `ablation_of`
- `combination_of`
- `reproduction_of`

## 12.2 Trial dimensions

LIKI MUST record at least:

- `raw_adaptive_trials`
- `family_trials`
- `mechanism_trials`
- `parameter_trials`
- `dataset_exposures`
- `guard_holdout_queries`
- `sealed_holdout_exposures`
- `forward_feedback_cycles`

No retry caused solely by infrastructure failure counts as a new scientific trial if semantic identity is unchanged.

## 12.3 Effective trial count

Because nearby parameter variants are correlated, raw trial count and independent trial count differ.

LIKI SHALL:

1. preserve the raw count unconditionally;
2. calculate one or more **effective trial estimates** using similarity/correlation/clustering methods appropriate to the evidence;
3. never replace raw history with the lower effective count;
4. use conservative multiplicity treatment when estimates disagree;
5. version the effective-trial method.

An effective-trials estimator is a statistical aid, not a loophole for pretending that 1,000 adaptive variants were "one test."

## 12.4 Search family

A statistical search family is defined by a versioned rule using:

- market/universe;
- data ancestry;
- mechanism/signal family;
- objective/evaluator;
- major parameterization;
- holding-period class;
- adaptation ancestry.

Changing a few parameters does not reset the family.

Changing the model name or LLM prompt does not reset the family.

A materially new mechanism MAY open a new sub-family but remains linked to the campaign-level search history.

## 12.5 Trial ledger is upstream of statistics

DSR, PBO, Reality Check/SPA, FDR procedures, and other multiplicity corrections MUST consume trial/search-family information from this ledger. Statistical code may not accept a hand-entered "number of trials" without provenance.

---

## 12.6 Semantic deduplication and false-novelty defense

Exact-code or text similarity is insufficient for research deduplication.

A dedup record SHALL combine:

- normalized mechanism description;
- intervention surface;
- signal inputs;
- decision rule structure;
- horizon;
- market/universe;
- expected payoff signature;
- strategy lineage;
- semantic embedding or other similarity aid.

An LLM may assist classification, but the dedup decision and confidence are recorded.

Two differently worded strategies with the same effective rule are duplicates; two similar descriptions with materially different mechanism/intervention may remain distinct.

Ambiguous dedup cases SHOULD merge expensive evaluation only after a cheap discriminating test determines whether their behavior is materially equivalent.

---

## 12.7 Random-seed, split, and nuisance-parameter selection

Randomness is another researcher degree of freedom.

If a seed, train/validation split, bootstrap block length, resampling scheme, CV partition, initialization, label threshold, optimizer schedule, or other nuisance setting is changed **after observing outcomes** in order to obtain a better result, that change SHALL enter the Trial Ledger.

For stochastic strategies/models, LIKI SHALL report the declared distribution across predeclared/reproducibly sampled seeds when material. Selecting the best seed and reporting it as representative is prohibited.

Random-seed sets used for confirmatory comparison SHALL be fixed before reading comparative outcomes or generated by a committed reproducible policy. Infrastructure retries that rerun the exact same semantic seed do not create a new scientific trial.

Statistical-method tuning itself can overfit. Material changes to bootstrap/block/CV/nuisance parameters after observing the desired test result SHALL be labeled exploratory and require renewed confirmation.

## 12.8 Campaign-level stopping and winner-discovery selection

Selection bias also occurs when an office keeps launching candidates until one crosses a target and then stops. The fact that the campaign stopped on a winner is part of the search process.

LIKI SHALL record:

- campaign start rule and research budget/horizon;
- candidate opportunities considered, funded, rejected, or never funded;
- any budget/horizon extension made after seeing results;
- the rule that caused a campaign to stop, pause, or declare success.

A winner found after repeated extensions of the search budget MUST NOT be analyzed as though it came from the originally planned number of trials. Office-level multiplicity includes unsuccessful/abandoned candidates and adaptive campaign extensions.

Safety-driven early termination is always allowed. Success-driven early termination that changes inferential claims follows the same sequential/selection discipline as Section 15.17.


# 13. Data Platform

## 13.1 Initial market scope

Phase 1 SHALL focus on liquid cryptocurrency markets.

Initial research emphasis:

- major spot markets;
- major perpetual futures;
- highly liquid pairs/universes;
- directional and market-neutral strategies;
- cross-sectional signals;
- momentum/reversal;
- basis/funding/carry;
- volatility/liquidity-related hypotheses.

The initial primary strategy decision horizon is approximately **4 hours** where appropriate.

This does **not** mean execution may be simulated from only 4-hour candles.

## 13.2 Multi-resolution requirement

A 4h signal strategy SHOULD use:

- 4h data for primary signal logic when appropriate;
- 1h or finer data for path/robustness checks;
- 1m/trade/order-book data where required and available for execution realism.

A backtest MUST NOT infer intrabar order sequence from an OHLC bar when the sequence matters.

## 13.3 Dataset manifest

Every dataset snapshot SHALL include:

```json
{
  "dataset_snapshot_id": "...",
  "provider": "...",
  "venue": "...",
  "instrument": "...",
  "instrument_type": "...",
  "timezone": "UTC",
  "start_time": "...",
  "end_time": "...",
  "as_of_time": "...",
  "fetched_at": "...",
  "candle_semantics": "...",
  "timestamp_semantics": "...",
  "provider_revision_id": null,
  "missing_intervals": [],
  "repair_events": [],
  "duplicates_removed": 0,
  "bad_ticks_removed": 0,
  "corporate_action_policy": null,
  "delisting_policy": "...",
  "survivorship_policy": "...",
  "freshness_sec": 0,
  "freshness_sla_sec": 0,
  "schema_hash": "...",
  "content_hash": "...",
  "quality_status": "pass|warn|fail"
}
```

## 13.4 Data correctness

Research MUST fail or pause when required information is unknown, including:

- missing timezone;
- ambiguous candle labeling;
- unacceptable gaps;
- unknown instrument mapping;
- stale live/paper data beyond policy;
- unresolved provider disagreement;
- suspected lookahead;
- unavailable point-in-time universe;
- broken delisting/survivorship handling.

## 13.5 Provider reconciliation

Critical market/execution inputs SHOULD be cross-checked against an independent source when economically practical.

Disagreements MUST be classified:

- timestamp convention;
- symbol mapping;
- stale source;
- venue difference;
- vendor repair;
- actual market discrepancy.

A majority vote across vendors is not automatically truth.

## 13.6 Point-in-time discipline

All features and universe membership MUST use data available at the decision timestamp.

Feature pipelines SHALL expose an automated `latest_source_timestamp_used` audit.

If a feature uses future information relative to the simulated decision, the branch is hard-failed for leakage.

---
## 13.7 Raw, canonical, and derived data layers

Market data SHALL be separated into:

1. **raw immutable** provider payloads/files where legally/practically storable;
2. **canonical normalized** records with deterministic transforms;
3. **derived features** with feature-code/version lineage.

Normalized data never destroys the raw provenance pointer.

A Symbol Master SHALL version mappings among venue symbol, base/quote assets, contract type, expiry, multiplier, settlement asset, margin asset, listing/delisting time, and symbol changes.

## 13.8 Streaming market-data correctness

For WebSocket/order-book feeds with sequence IDs, LIKI SHALL implement the venue-documented snapshot + delta protocol, gap detection, and full resynchronization after a missed sequence.

A reconnect is not considered continuous data unless sequence continuity is proven.

Required telemetry includes:

- local receive timestamp;
- provider event timestamp;
- sequence/update IDs;
- gap/reconnect count;
- snapshot age;
- clock-offset estimate;
- dropped/duplicate event count.

Order-book-derived features MUST be invalidated over unresolved gaps.

## 13.9 Time synchronization

Hosts participating in market-data or execution simulation SHALL maintain monitored clock synchronization.

The system records:

- monotonic runtime clock for durations;
- UTC wall clock for events;
- venue server-time offset where available.

Clock drift above venue/policy tolerance blocks latency-sensitive evidence rather than silently shifting timestamps.

## 13.10 Feature Registry and offline/online parity

Every derived feature SHALL have:

- feature ID/version;
- deterministic source code hash;
- source columns and maximum source timestamp;
- lookback/window semantics;
- missing-value policy;
- normalization policy;
- availability timestamp semantics;
- tests proving no future data use.

If a feature may later run in forward/live mode, historical and online implementations SHALL either share the same code path or pass differential parity tests.

## 13.11 Crypto derivatives/reference data

For derivatives research, the Data Platform SHALL ingest/version where relevant:

- index price;
- mark price;
- last/trade price;
- funding rate and funding timestamp;
- contract multiplier/size;
- margin asset;
- initial and maintenance margin rules;
- liquidation fee/rules;
- ADL/forced-order semantics where published;
- venue trading status and maintenance state.

These values are not interchangeable. The evaluator MUST use the price definition required by the venue/risk rule being modeled.

## 13.12 Data licensing, retention, and reproducibility

Dataset manifests SHALL record license/use restrictions and retention constraints where applicable.

A strategy cannot be called reproducible if required proprietary data cannot be re-obtained or preserved under its license; the limitation MUST be explicit.

Data retention policy MUST preserve enough raw/canonical evidence to reproduce promoted research for the required audit horizon.

---

## 13.13 Outliers, bad ticks, and tail preservation

An extreme observation is not automatically erroneous.

Data cleaning SHALL distinguish:

- provider/encoding error;
- duplicate/corrupt record;
- genuine extreme market event;
- uncertain observation.

Deleting/winsorizing an observation requires a versioned transformation and evidence. Raw immutable data remains preserved.

Cross-provider disagreement, impossible price/quantity rules, sequence corruption, or venue correction may support a bad-tick classification. "It hurts the backtest" is never a valid reason.

Winsorization/outlier clipping used as a modeling transform enters the feature/model/trial lineage and MUST be applied point-in-time.

## 13.14 Missing-data and imputation semantics

Missing market observations SHALL NOT be silently converted to zero return/zero volume or forward-filled across outages without a justified point-in-time rule.

Every imputation method records:

- source gap;
- method;
- information available at that time;
- maximum fill horizon;
- effect on tradability.

A market outage is an execution condition, not merely a missing-number problem.

## 13.15 Bar construction and incomplete-bar leakage

Resampled OHLCV bars SHALL define exact interval boundaries and timestamp labels.

A strategy using the final close/high/low/volume of a 4h bar cannot execute at that same already-known close price unless a venue mechanism demonstrably makes that price tradable after the information becomes available.

Canonical default:

- bar closes;
- final bar data becomes available;
- signal computes;
- order becomes eligible only after modeled compute/data/order latency.

Incomplete current bars MUST be explicitly labeled and cannot masquerade as completed historical bars.

---

## 13.16 As-of joins and asynchronous cross-asset data

Cross-asset/cross-venue features SHALL use point-in-time **as-of** semantics.

At decision time `t`, a feature may use only observations whose availability timestamp is `<= t`.

The system MUST NOT align datasets by final bar label/index in a way that pulls a later-reported value from another market into an earlier decision.

Join policy, maximum staleness, and timezone/calendar assumptions are versioned feature metadata.

## 13.17 Historical Instrument Specification Ledger

Using today's exchange metadata to simulate yesterday is invalid when venue/instrument rules changed.

LIKI SHALL maintain effective-dated instrument/venue specification records where relevant, including:

- symbol/contract identity and mapping history;
- listing, delisting, expiry, settlement, redenomination/token-swap events;
- contract multiplier and linear/inverse semantics;
- tick/lot/min-notional filters;
- leverage/risk/maintenance-margin brackets;
- collateral/settlement asset;
- funding interval/cap/rule changes;
- price bands and material order-rule changes.

A historical backtest SHALL use the specification effective at the simulated time or explicitly declare a bounded approximation. Current exchange filters cannot be silently projected backward.

Instrument lifecycle events are part of the point-in-time universe and survivorship model. A delisted/renamed contract may not disappear from history merely because the current API no longer lists it.

## 13.18 External-source evidence snapshots

For papers, venue documentation, public web sources, and vendor notices that materially affect a research/gate decision, LIKI SHALL persist:

- source URI/identifier;
- retrieval timestamp;
- publication/effective timestamp when known;
- content hash;
- exact cited excerpt or stored snapshot where license permits;
- source-class/provenance confidence;
- historical-cutoff contamination tag.

A later-edited documentation page does not rewrite what an earlier agent relied upon.

---

## 13.19 Crypto asset, contract, and venue lifecycle events

Crypto instruments can change identity or economic semantics without a conventional equity-style corporate action. LIKI SHALL maintain a point-in-time lifecycle ledger for events including, where applicable:

- listing, delisting, suspension, and re-listing;
- ticker/symbol change;
- token redenomination or reverse split;
- contract multiplier/lot-size change;
- perpetual/futures contract migration, expiry, settlement, or replacement;
- chain migration/token swap;
- fork or material network event affecting deliverability/valuation;
- stablecoin/collateral eligibility or haircut change;
- funding/mark/index methodology change;
- margin/leverage bracket change;
- fee tier/rule change;
- venue API/trading-rule migration.

A discontinuity caused by redenomination, migration, contract replacement, or accounting-unit change MUST NOT be treated as an economic return.

Backtests spanning a lifecycle event SHALL either model the event with the historically correct conversion/settlement semantics or explicitly terminate/segment exposure. Silent symbol splicing is prohibited.

Historical universe construction SHALL preserve instruments that later delisted or failed when they were genuinely available at the historical decision time. Deletion from today's exchange catalog does not remove them from historical negative evidence.

## 13.20 Source compromise, poisoning, and implausible-data quarantine

Data quality checks SHALL distinguish ordinary bad ticks from evidence of a compromised, corrupted, or systematically wrong source.

Triggers may include:

- impossible cross-field invariants;
- large unexplained disagreement with independent sources;
- timestamp/sequence behavior inconsistent with venue protocol;
- repeated one-sided price/depth anomalies;
- schema changes without declared provider version;
- hashes/signatures or transport metadata inconsistent with expectation;
- a vendor correction that materially rewrites prior research inputs.

Triggered data is quarantined from promotion-sensitive research until reconciled. LIKI MUST preserve the raw payload and the reason for quarantine.

Cross-source agreement is evidence, not proof: multiple vendors may share one upstream. Provider/upstream dependency relationships SHOULD be recorded where known.

An LLM MUST NOT "clean" suspicious numerical market data by intuition. Repairs are deterministic, versioned, reversible transformations with before/after artifacts.

---

## 13.21 Market-data fidelity tiers and execution-claim limits

Execution claims SHALL be bounded by the actual observability of the historical data. LIKI SHALL tag each execution dataset/window with a versioned fidelity tier or equivalent capability vector.

A reference tiering is:

- `F0_BAR`: OHLCV/aggregated bars only;
- `F1_TRADE_BBO`: trades and/or best bid/offer;
- `F2_AGG_L2`: price-level aggregated depth snapshots;
- `F3_SEQ_L2`: sequence-validated incremental aggregated depth plus trades;
- `F4_ORDER_LEVEL`: message/order-level data sufficient for materially stronger queue reconstruction, where genuinely available;
- `F5_ACCOUNT_OBSERVED`: the owner's paper/future-live account-specific acknowledgements/fills/order-state evidence.

The tier name alone does not guarantee completeness; the manifest records gaps, sampling rate, venue semantics, hidden/admin event limitations, and coverage period.

LIKI MUST NOT infer exact FIFO/queue priority, hidden-order behavior, or order-level cancellations from price-level aggregate L2 data that contains only price and total quantity. Such data can support depth/imbalance and approximate fill models, not exact queue position.

A fill/capacity model SHALL declare the minimum data capability it requires. If the available fidelity is weaker, the result is downgraded to a wider model-estimate uncertainty band or `NOT_APPLICABLE`; it is not silently promoted to high-fidelity execution evidence.

Venue feeds may omit nonordinary/admin/insurance/ADL events or expose only limited historical windows. These coverage limitations SHALL be recorded in the dataset/instrument manifest and propagated to liquidation/impact conclusions.

A transition from coarse data to finer data MAY invalidate a previously accepted fill assumption and trigger reevaluation.


# 13A. Financial ML / Statistical Model Pipeline

LIKI supports both rule-based strategies and learned statistical/ML models. Learned models require additional controls.

## 13A.1 Label Registry

Every prediction target SHALL have a versioned label definition including:

- decision time;
- prediction horizon;
- event end time;
- overlapping-label semantics;
- return/price convention;
- fees/cost inclusion if any;
- censoring/missing policy.

Changing the label creates a new trial/model version.

## 13A.2 Training-run registry

Every training run records:

- model class;
- features and versions;
- label version;
- train/validation/test split IDs;
- purge/embargo policy;
- hyperparameters;
- random seeds;
- software/environment fingerprint;
- search/optimizer history;
- selected checkpoint;
- metrics and artifacts.

Hyperparameter trials are scientific trials and enter multiplicity accounting.

## 13A.3 Nested selection

When hyperparameters/features/model class are selected using validation evidence, final performance estimates SHALL come from evidence not used for that selection.

Nested or otherwise properly separated selection/evaluation is required when a simple train/validation split would reuse the same evidence for tuning and final claims.

All learned preprocessing is part of the model-selection pipeline. Scalers, imputers, encoders, PCA/dimensionality reduction, feature selectors, target transforms, calibration maps, and any statistic estimated from data SHALL be fitted **inside the training side of each split/fold** unless the transform is provably label/data-distribution independent. Fitting preprocessing once on the full history and then cross-validating the downstream model is leakage.

Pipeline objects SHALL be versioned together with the model artifact so a backtest cannot accidentally apply a transform fitted on future/test observations.

## 13A.4 Class imbalance and prediction sanity

Classification models SHALL report class prevalence and prediction prevalence.

A model predicting one direction almost all the time cannot be promoted on aggregate accuracy alone.

Economic evaluation MUST map predictions to actual tradable decisions after costs.

## 13A.5 Feature selection and importance

Feature selection itself consumes trials/statistical capital.

Feature importance/explanation tools are diagnostic and do not prove causal mechanism.

Stability of selected features across splits/regimes SHOULD be evaluated for material learned models.

## 13A.6 Prediction calibration

Where model outputs are probabilities, calibration SHALL be evaluated when those probabilities affect sizing/decision thresholds.

Calibration learned on one regime cannot be assumed stable indefinitely.

## 13A.7 Retraining vs new research

Routine retraining under a preapproved unchanged protocol is operational model maintenance.

Changing features, label, architecture, objective, training window rule, or selection procedure is a research/model change and MUST re-enter the appropriate validation path.

## 13A.8 Model artifact integrity

Serialized model artifacts SHALL be content-hashed and tied to their exact training run. Loading a model artifact with an unrecognized hash is prohibited in accepted research/paper paths.

---

# 14. Research Funnel and Gates

All strategy candidates move through a common gate protocol. Domain-specific sub-gates MAY be added, but skipping a defined gate requires an explicit policy reason and event.

Gate results:

- `PASS`
- `BORDERLINE`
- `FAIL`
- `BLOCKED`
- `NOT_APPLICABLE` with reason
- `NEEDS_MORE_INFORMATION`

`BORDERLINE` is not a silent pass. It routes into the Gray-Zone/Frontier mechanism.

## G0 — Research Contract

Purpose:
- formalize objective, hypothesis, constraints, evaluator, data boundaries, intended market/horizon, and expected artifacts.

Hard fail:
- no measurable objective;
- undefined data/evaluator;
- impossible or prohibited action;
- no lineage identity.

LLM cost:
- low to high depending on novelty.

## G1 — Duplicate / Family / Prior-Evidence Screen

Checks:
1. exact duplicate;
2. semantic duplicate;
3. same failed-family cooldown;
4. same market/timeframe/strategy family;
5. prior conclusive falsification;
6. prior equivalent experiment cache.

Hard fail:
- exact equivalent already conclusively tested with same relevant conditions;
- known hard invalidity.

Borderline:
- similar prior failure but materially different mechanism/regime.

This gate preserves V3.3's early duplicate/cooldown intent.

## G2 — Data Integrity and Leakage

Checks:
- availability;
- point-in-time validity;
- freshness;
- gaps;
- timezone/candle semantics;
- survivorship/delisting;
- feature leakage;
- label leakage;
- future-universe leakage;
- train/test contamination.

Hard fail:
- unresolved leakage or corrupted critical data.

No economic upside can override leakage.

## G3 — Mechanism and Feasibility

Candidate MUST specify:

- intended mechanism or empirical pattern;
- who/what plausibly pays the edge where explainable;
- market structure;
- expected horizon;
- falsifiable prediction;
- minimum viable test;
- obvious constraints.

A weak narrative alone MUST NOT hard-fail a statistically interesting empirical candidate.

The gate's function is to make research falsifiable, not to reward storytelling.

## G4 — Cheap Economics / Statistical Proxy

Before expensive work, run cheap checks:

- minimum event/sample availability;
- rough spread/slippage/funding bounds;
- capacity feasibility;
- after-cost edge sanity;
- simple baseline comparison;
- cheap parameter neighborhood;
- cheap statistical proxy;
- expected turnover;
- implementation feasibility.

The gate SHALL prefer killing a candidate for an already-known fatal fact rather than after a full backtest.

False-negative risk is logged. Borderline/high-option-value candidates can enter Frontier budget.

## G5 — Full Protocol Backtest

Requirements:

- immutable backtest configuration;
- versioned code;
- versioned data;
- deterministic seed policy;
- no silent missing-cost fallback;
- benchmark strategy;
- complete trade/order/event ledger;
- gross and net performance;
- exposure and turnover;
- drawdown/tail statistics;
- scenario slices;
- reproducible artifact package.

A full backtest is not a promotion by itself.

## G6 — Costs, Slippage, Liquidity, and Capacity

Preserves V3.3 semantics.

Must evaluate relevant:

- maker/taker fees;
- funding;
- borrow/financing;
- spread;
- slippage;
- market impact;
- participation;
- queue/fill uncertainty;
- minimum notional;
- tick/lot constraints;
- liquidation mechanics;
- venue limits;
- latency;
- rejects;
- outages/staleness.

Unknown material costs -> `BLOCKED`, not zero.

Outputs include an uncertainty range, not just a point estimate.

## G7 — Out-of-Sample / Walk-Forward

Preserves V3.3 semantics.

Tests SHALL be selected before inspecting the corresponding result.

Methods may include:

- chronological OOS;
- rolling/expanding walk-forward;
- purged/embargoed schemes where labels overlap;
- cross-sectional splits when appropriate.

Repeatedly tuning after viewing G7 consumes statistical capital and trial budget.

## G8 — Statistical Validation

Preserves V3.3 semantics.

Required components are selected based on strategy type, not mechanically all at once.

Framework SHALL support:

- probabilistic/deflated Sharpe concepts;
- PBO/CSCV where appropriate;
- multiple-testing accounting;
- White Reality Check and/or Hansen SPA for model-family comparisons when appropriate;
- dependence-aware bootstrap;
- uncertainty intervals;
- autocorrelation/heteroskedasticity awareness;
- skew/kurtosis/non-normality;
- minimum track-record reasoning;
- false-discovery controls for large research families.

Statistical tests are evidence, not a single magic score.

## G9 — Sensitivity and Robustness

Required:

- parameter neighborhoods;
- perturbation of reasonable costs;
- timing perturbations;
- universe perturbations;
- missing-data sensitivity;
- concentration;
- regime slices used diagnostically.

A strategy that works only at a narrow numerical optimum is presumed fragile until explained.

Regime/adversarial slices MUST NOT become endlessly tuned secondary training sets.

## G10 — Independent Reproduction and Causal/Ablation Review

A fresh verifier reproduces the result from declared artifacts.

For material improvements, LIKI SHOULD run ablations to determine what component actually contributes.

Outputs:

- reproduction status;
- code/data equivalence;
- attribution confidence;
- discrepancies;
- independent verdict.

The generator cannot be the sole reproducer.

## G11 — Sealed Promotion Validation

This is a high-integrity gate.

Researchers MUST NOT receive raw sealed metrics by default.

Preferred output:

- `PASS`
- `BORDERLINE`
- `FAIL`

plus limited predeclared diagnostic categories only when necessary.

Any exposure is written to the Statistical Capital Ledger.

A failed sealed result MUST NOT be followed by repeated parameter tuning against the same sealed sample.

## G12 — Forward Shadow / Paper Execution

This gate evaluates real-time behavior without real money.

Compare predicted vs observed:

- fills;
- turnover;
- costs;
- slippage;
- latency;
- rejected/partial orders;
- realized signal timing;
- edge decay;
- drawdown;
- capacity assumptions;
- operational reliability.

Paper results are evidence, not executable capital permission.

## G13 — Portfolio and Capital Readiness

Evaluate:

- incremental portfolio return/risk contribution;
- correlation and tail dependence;
- concentration;
- liquidity overlap;
- capital capacity;
- regime complementarity;
- risk budget;
- execution conflicts;
- evidence maturity.

Result may be:

- reject;
- continue paper;
- `READY_FOR_MICROLIVE`.

`READY_FOR_MICROLIVE` does not enable real orders.

---

## 14.1 Canonical candidate lifecycle

The candidate state machine is:

```text
IDEA
 -> CONTRACTED
 -> SCREENED
 -> DATA_VALID
 -> FEASIBLE
 -> PROXY_SURVIVOR
 -> BACKTESTED
 -> ECONOMICALLY_VALIDATED
 -> OOS_VALIDATED
 -> STATISTICALLY_VALIDATED
 -> ROBUSTNESS_VALIDATED
 -> REPRODUCED
 -> SEALED_VALIDATED
 -> FORWARD_PAPER_VALIDATED
 -> PORTFOLIO_READY
 -> READY_FOR_MICROLIVE
```

At any point a candidate may enter:

`BORDERLINE_FRONTIER`, `BLOCKED`, `FAILED`, `SUSPENDED`, or `RETIRED`.

A gate transition SHALL be monotonic with respect to that evidence version. New strategy/evaluator/data versions may require re-entry at an earlier state.

## 14.2 Gate dependency graph

A downstream gate may rely only on upstream evidence whose version/hash is explicitly declared.

If an upstream artifact changes materially, dependent downstream decisions are marked stale and MUST be recomputed/revalidated.

`NOT_APPLICABLE` is permitted only when the gate contract defines an applicability predicate and records evidence for it. It is not a generic skip button.

## 14.3 Gate failure semantics

`FAIL` means evidence supports rejection under the current protocol.

`BLOCKED` means a required fact/tool/data dependency is unavailable or invalid; it MUST NOT be counted as statistical rejection.

`NEEDS_MORE_INFORMATION` means no valid decision yet.

`BORDERLINE` means evidence is valid but insufficiently decisive and may route to Frontier.

These states MUST be kept separate in metrics so infrastructure/data failures do not look like scientific falsification.

---

# 15. Statistical Capital and adaptive-data protection

## 15.1 Principle

Money, compute, and tokens are not the only scarce resources. Repeated observation of the same historical evidence also consumes **statistical capital**.

LIKI SHALL record the information exposed by every adaptive evaluation.

## 15.2 Exposure event

```json
{
  "holdout_query_id": "...",
  "strategy_version_id": "...",
  "dataset_snapshot_id": "...",
  "dataset_role": "development|guard|sealed|forward",
  "metrics_requested": [],
  "output_granularity": "exact|rounded|category|boolean",
  "result_disclosed_to_researcher": true,
  "influenced_next_hypothesis": true,
  "trial_family_id": "...",
  "occurred_at": "..."
}
```

## 15.3 Dataset roles

### Development
Freely inspectable within normal research accounting.

### Reusable Guard Holdout
May use a Thresholdout-like or other adaptive-holdout mechanism to reduce information leakage during repeated research.

Thresholdout SHALL NOT be treated as a universal guarantee for nonstationary dependent financial time series. It is one defensive tool.

### Sealed Promotion Holdout
Rarely exposed, limited output, controlled by an independent evaluator.

### Forward
New chronological data that did not exist at research time. This is the strongest practical anti-backtest-overfit evidence available before real-money operation.

## 15.4 Multiple testing

The system MUST maintain full search history.

At minimum, G8 has access to:

- raw trial counts;
- effective trial estimates;
- strategy-family search set;
- all comparable candidate results;
- researcher adaptation history;
- holdout exposure history.

No agent may reset multiplicity by renaming a strategy.

## 15.5 Statistical methods

Methods SHALL be selected by assumptions and purpose.

Examples:

- DSR/PSR: evaluate Sharpe evidence with selection/non-normality considerations;
- PBO/CSCV: estimate risk of choosing an overfit backtest from a strategy search;
- White Reality Check: data-snooping-aware comparison against a benchmark;
- Hansen SPA: more powerful alternative/complement for many predictive models;
- block/stationary/dependence-aware bootstrap: preserve serial dependence where needed;
- false discovery controls: large families of candidate signals/tests.

The SRS does not mandate one p-value as universal truth.

## 15.6 Initial evidence bands

The following are **initial policy bands**, not immutable science. They MUST be calibrated through historical replay and false-rejection/false-promotion analysis before being used as universal hard gates.

Illustrative initial strong-evidence targets:

- DSR/PSR-style confidence: target approximately `>= 0.95` for strong statistical evidence;
- PBO: prefer approximately `<= 0.20` for strong evidence;
- PBO `> 0.50`: severe overfit warning;
- intermediate results: `BORDERLINE` rather than automatic fail when other evidence is strong and the next test has positive VOI.

These values MUST NOT override assumption failures, small-sample limitations, dependence problems, or economic invalidity.

A configuration containing numeric thresholds MUST include:

- rationale;
- calibration dataset;
- effective date;
- owning governance proposal;
- false-positive/false-negative analysis.

---

## 15.7 Time-series validation protocol

IID random K-fold cross-validation SHALL NOT be used by default for temporally dependent financial labels.

When labels/positions overlap across time, training/validation splits SHALL use appropriate purging and embargo so information from an overlapping event cannot leak across the boundary.

The framework SHALL support, where justified:

- chronological walk-forward;
- purged K-fold validation;
- combinatorial purged cross-validation (CPCV);
- nested model/hyperparameter selection;
- blocked/rolling validation;
- cross-sectional holdouts where the economic hypothesis permits.

Method choice and purge/embargo length MUST be derived from label/event horizons and declared before result inspection.

## 15.8 Dependence-aware resampling

Naive IID bootstrap/permutation may be invalid for serially/cross-sectionally dependent returns.

The statistics layer SHALL support block/stationary/dependence-preserving resampling where required.

Permutation tests MUST preserve the dependence structure required by the null being tested. A random shuffle that destroys temporal structure cannot be labeled a valid financial null without justification.

## 15.9 Pre-declaration of inferential intent

Before a high-integrity evaluation, the research contract records:

- primary metric(s);
- benchmark/null;
- one- vs two-sided alternative where applicable;
- family of compared variants;
- planned split/resampling method;
- decision interpretation.

Post-hoc metrics may be explored but are labeled exploratory and cannot be retroactively presented as predeclared confirmatory evidence.

## 15.10 Effect size, uncertainty, and minimum evidence

A tiny p-value with negligible economics is not sufficient.

Statistical artifacts SHALL report effect size and uncertainty together with significance/probability metrics.

The engine SHOULD compute minimum track-record/effective-sample requirements where applicable, but MUST account for non-normality, dependence, overlapping bets, and heavy tails. There is no universal minimum number of bars.

For event-driven strategies, effective independent opportunities/bets may be more informative than raw bar count.

## 15.11 Forward evidence is not infinitely clean

Forward data is untouched only until the research process observes it.

If a forward/paper outcome influences a new descendant strategy, that outcome becomes development/adaptive evidence for the descendant. The descendant requires later chronological forward evidence for a new strong confirmation.

LIKI SHALL record this ancestry explicitly.

## 15.12 Holdout lifecycle

Each guard/sealed holdout has:

- creation policy;
- eligible strategy families;
- access budget;
- output granularity;
- contamination ledger;
- retirement/rotation condition.

A sealed set that has been materially exposed, repeatedly queried, or structurally invalidated by market change SHALL be retired from sealed status. It may remain useful as development evidence.

## 15.13 Hierarchical multiplicity

Multiplicity SHALL be tracked at multiple levels:

- parameter variants;
- strategy/mechanism family;
- market/universe;
- campaign;
- office-level discovery program when the same data supports many campaigns.

The most favorable local definition MUST NOT be used to hide a large global search.

## 15.14 Statistical method applicability registry

Every statistical method implementation SHALL declare:

- assumptions;
- supported input type;
- dependence handling;
- minimum required metadata;
- failure/undefined conditions;
- reference tests.

If assumptions are materially violated, the method returns `NOT_APPLICABLE` or a qualified result rather than a misleading number.

---

## 15.15 LLM hindsight/pretraining contamination

LLMs may have pretraining or web knowledge of historical events, known anomalies, later failures, papers, or market outcomes that occurred after a simulated research cutoff.

This cannot be fully eliminated by prompt instructions.

Therefore LIKI SHALL distinguish:

- `EX_ANTE_CLEAN`: no known post-cutoff external information entered the research process;
- `HINDSIGHT_POSSIBLE`: an LLM or external source may know later information;
- `HINDSIGHT_CONFIRMED`: post-cutoff information directly influenced the candidate.

Rules:

- hindsight-contaminated ideas may still be researched for current/future use;
- they MUST NOT be presented as evidence that LIKI would have discovered the edge historically in real time;
- historical discovery benchmarks requiring ex-ante purity MUST use controlled source cutoffs and treat general LLM pretraining as a residual contamination risk;
- sealed and genuinely later forward evidence carries more weight than a historically impressive idea that may contain hindsight.

## 15.16 Benchmark contamination

Research agents MUST NOT receive benchmark hidden answers, expected winning strategies, or prior benchmark-specific failure explanations when the benchmark is intended to measure discovery capability.

Once a benchmark is repeatedly used for system tuning, it becomes a development benchmark and a new sealed system benchmark is required for strong claims.

---

## 15.17 Sequential monitoring and optional stopping

Repeatedly peeking at a forward/paper result and promoting when it looks unusually good creates optional-stopping bias.

Therefore:

- safety deterioration MAY stop/suspend a candidate immediately; capital preservation does not wait for statistical ceremony;
- early **success promotion** before a predeclared horizon/opportunity count requires a valid sequential-inference/stopping procedure or an independently sealed decision rule;
- if ordinary fixed-horizon inference is used, promotion waits for the predeclared evaluation point;
- every interim look that influences research is an exposure event.

LIKI SHALL support sequentially valid methods where appropriate (for example alpha-spending/e-value/sequential-likelihood approaches), but method choice MUST satisfy its assumptions and be in the Method Applicability Registry.

## 15.18 Adaptive early stopping of research experiments

Cheap fail-fast stopping is encouraged for clearly invalid branches, but scientific early stopping changes the selection process.

When a strategy/training/backtest search is stopped early because interim performance is weak/strong, the stopping rule and interim observations enter the Trial Ledger.

An early-stopped run cannot be treated as if it were an unobserved trial when estimating search multiplicity.

---

## 15.19 Sealed evaluator isolation

Sealed promotion data SHOULD be physically/logically isolated from ordinary research access.

Recommended architecture:

```text
Research DB / workers
       |
       | signed evaluation request containing artifact/data-contract IDs
       v
Sealed Evaluator Service ----> Sealed Data Store
       |
       | limited verdict artifact
       v
Research evidence ledger
```

Rules:

- ordinary research agents have no direct credential/path to sealed raw data;
- sealed evaluator logs MUST NOT expose raw rows or exact hidden metrics to ordinary observability;
- request contains immutable candidate artifact hashes so the evaluated candidate cannot change after submission;
- response follows the predeclared output granularity (`PASS/BORDERLINE/FAIL` plus approved diagnostics);
- query/exposure count is written atomically before/with response;
- evaluator code/version is independently versioned and validated;
- owner access to raw sealed results, if ever used, creates an exposure/contamination event if that information can influence later research.

The sealed evaluator SHALL minimize unintended side channels. Ordinary callers MUST NOT receive raw row counts, per-case errors, stack traces containing sealed values, internal file paths, hidden metric precision, or response metadata that materially reveals more than the declared output contract. Candidate execution inside the sealed service uses a no-network/least-output sandbox and cannot write arbitrary external artifacts.

Repeated categorical verdicts can still leak information; query budgets and Statistical Capital apply even when the response contains only `PASS/BORDERLINE/FAIL`.

## 15.20 Thresholdout-like guard implementation contract

If LIKI enables a Thresholdout-like reusable guard holdout, the implementation SHALL be a separately versioned statistical method with stored parameters such as query budget, threshold/noise/privacy parameters, output granularity, and random seed/secure randomness policy as applicable.

It MUST be validated against the referenced algorithm rather than implemented from a vague prompt summary.

The UI/report SHALL state that classic guarantees may rely on assumptions not satisfied by dependent/nonstationary market time series. The guard is an additional control, not permission for unlimited adaptive reuse.

---

## 15.21 Human/owner adaptive research counts too

Adaptive overfitting does not disappear because the next idea came from a human.

If the owner or any human sees research/holdout/forward results and then requests a materially informed new variation, the new variation is linked to that evidence and enters the Trial Ledger exactly as an agent-generated adaptation would.

Human participation is welcome; it simply does not reset multiplicity or contamination history.

## 15.22 Heavy-tail / unstable-moment caution

Sharpe/variance-based procedures can become unreliable when return moments are poorly behaved or sample tails dominate estimates.

The Method Applicability Registry SHALL flag unstable variance/skew/kurtosis/tail estimation. When assumptions required by a statistic are not defensible, LIKI MUST rely on alternative robust evidence and report the limitation rather than force a precise Sharpe-derived probability.

## 15.23 Objective, metric, window, and universe shopping

Researcher degrees of freedom include more than parameter values. Choosing the most favorable metric, time window, universe, benchmark, direction, holding period, or reporting transformation after seeing outcomes is adaptive selection.

LIKI SHALL record material changes to:

- primary objective/metric;
- benchmark/null;
- evaluation window;
- asset/universe definition;
- strategy direction/sign;
- horizon/holding-period rule;
- inclusion/exclusion filters;
- aggregation/reporting convention.

A post-result change that could improve apparent performance creates a new adaptive trial/branch relationship unless predeclared by protocol.

Confirmatory reports MUST show all predeclared primary outcomes, including unfavorable ones. They MUST NOT present only the best metric/window/universe from a larger search. Exploratory discoveries may be reported, but are labeled exploratory and require new confirmation.

## 15.24 Winner's curse and promotion shrinkage

The candidate promoted from a large search is expected to have an upward-biased observed estimate even when the search is properly recorded.

Portfolio/readiness logic SHALL treat promoted backtest effect size as uncertain and apply shrinkage/selection-aware uncertainty or conservative scenario ranges where defensible. Capital/readiness decisions MUST NOT assume the selected candidate's historical point estimate is an unbiased forecast of forward edge.

---
## 15.25 Temporal transportability and structural-break evidence

Statistical validity on old data does not guarantee economic relevance today. LIKI SHALL distinguish **internal validity** (the historical experiment was correctly analyzed) from **temporal transportability** (the mechanism/economics remain relevant to the current market structure).

Transportability assessment considers where relevant:

- venue/instrument rule changes;
- participant/microstructure changes;
- liquidity/spread/funding regime changes;
- market maturation/crowding;
- collateral/reference-index changes;
- data-generation/provider methodology changes;
- strategy-capacity decay;
- materially changed latency/fee environment.

Old evidence MUST NOT be deleted or rewritten because it became stale. Instead its evidentiary role is annotated with current transportability confidence and the reasons for degradation.

Choosing a favorable "recent" window after observing that the full history looks bad is window shopping and enters the Trial Ledger. Recency weighting, rolling-window length, change-point method, and post-break cutoff are predeclared/versioned or treated as exploratory adaptive choices.

When a structural break is suspected, reports SHOULD show both full-lineage evidence and the justified post-break view rather than silently discarding inconvenient history.

A strategy may be `DORMANT`/require refreshed forward evidence when its historical edge is valid but current transportability is weak or unknown.


# 16. Gray Zone and Frontier Fund

A core LIKI requirement is to avoid both:

- promoting plausible-looking junk;
- killing rare high-value edge because it narrowly misses an imperfect gate.

## 16.1 Three classes of criteria

### A. Hard invalidity
Examples:

- leakage;
- corrupted/unknown critical data;
- arithmetic inconsistency;
- impossible execution;
- missing provenance;
- forbidden risk;
- silent gate bypass.

No appeal based on upside.

### B. Ordinary evidence
Examples:

- Sharpe-like metrics;
- DSR/PBO;
- OOS stability;
- cost/capacity;
- sensitivity.

These may create `PASS`, `BORDERLINE`, or `FAIL`.

### C. Discovery potential / uncertainty
Examples:

- plausible mechanism with insufficient sample;
- large potential payoff but uncertain statistics;
- new regime/market with limited evidence;
- strange strategy with robust qualitative behavior but low confidence.

## 16.2 Frontier budget

Initially reserve **5–10%** of research budget for `PROMISING_BUT_UNRESOLVED` candidates.

The controller may adapt this generally within **5–15%**.

A candidate enters the Frontier only if:

- no hard invalidity exists;
- it is not trivially dominated by another candidate;
- a concrete next test can materially reduce uncertainty;
- the expected value of information is positive under the budget;
- its novelty or upside is not merely the result of data snooping.

Frontier budget cannot be used as a backdoor around sealed-holdout failure.

## 16.3 Value of Information decision

Instead of asking "is this strategy 74/100?", LIKI asks:

> What is the least expensive next experiment likely to change the decision?

A generic decision quantity is:

`VOI = E[best decision utility after new evidence] - best current decision utility`

Research priority considers `VOI / total research cost`.

Total cost includes:

- API dollars;
- tokens;
- compute;
- wall time;
- data acquisition;
- evaluator load;
- statistical-capital consumption.

No implementation may claim exact VOI without uncertainty. Approximate VOI estimates are allowed and MUST be calibrated against realized decisions.

## 16.4 Owner notification

Borderline high-upside research MAY proceed within Frontier budget without owner approval.

The owner SHALL receive a concise notification when:

- a materially risky/expensive borderline branch is funded;
- the branch consumed unusual statistical capital;
- the branch requires a governance exception;
- the branch could materially change portfolio/risk architecture.

Research notification is not execution permission.

---

# 17. Backtest Engine

## 17.1 Determinism

Given identical:

- code;
- environment;
- data snapshot;
- seed;
- configuration;

the backtest MUST reproduce identical deterministic outputs, except explicitly stochastic simulations whose seeds/distributions are recorded.

## 17.2 Required outputs

Every full backtest artifact includes:

- full order/trade ledger;
- positions over time;
- cash/equity curve;
- gross PnL;
- every cost component;
- net PnL;
- exposure;
- leverage;
- turnover;
- drawdown;
- tail losses;
- holding-time distribution;
- per-market/per-regime slices;
- capacity estimates;
- rejection/error events;
- exact config and hashes.

## 17.3 Accounting

Critical money arithmetic SHALL use:

- integer native units where possible; or
- decimal/fixed-point arithmetic with explicit rounding.

Binary floating point MUST NOT be the authoritative ledger for money.

## 17.4 Dual implementation

Critical PnL/cost/accounting SHALL have an independent reference implementation or reconciliation implementation.

Differences above instrument-native tolerance cause:

`ACCOUNTING_DISAGREEMENT -> FAIL_CLOSED`

Tolerance cannot be chosen after seeing the discrepancy.

## 17.5 Lookahead defenses

Tests SHALL cover:

- accidental future index access;
- forward-filled future data;
- signal calculated after execution timestamp;
- universe membership leakage;
- revised data;
- funding/fee values unavailable at decision time;
- intra-bar sequencing assumptions.

---

## 17.6 Reproducibility tiers

Not all numerical workloads can promise bitwise identity across hardware.

Every experiment declares one reproducibility tier:

- `BITWISE`: expected identical bytes/results; preferred for Decimal accounting and deterministic backtest state machines;
- `NUMERIC_TOLERANCE`: floating-point result reproducible within predeclared tolerance;
- `STATISTICAL`: stochastic/ML process reproducible in distribution/declared metric tolerance across repeated seeded runs.

A component SHALL NOT claim deterministic reproducibility if its underlying GPU/library operations are nondeterministic.

Gate policies specify the minimum tier for each artifact type.

---

## 17.7 Independence of critical reference implementations

Two calculations are not independent merely because they are exposed through two functions/classes.

For CRITICAL accounting/risk reconciliation, the primary and reference paths SHALL minimize common-mode implementation failure. Where practical they use:

- independently written formula/control flow;
- separate golden fixtures derived from hand/externally verified examples;
- no shared critical calculation helper whose bug would make both implementations agree incorrectly;
- separately tested rounding/unit conversion;
- dependency-diversity or direct/simple reference math for the most critical identities.

Shared low-level serialization/storage libraries MAY be used, but common critical arithmetic dependencies SHALL be declared in the Model/Dependency inventory as a common-mode risk.

Differential agreement is necessary but not sufficient: the acceptance suite also includes algebraic/property invariants and known-answer fixtures so two identically wrong engines cannot pass merely by matching each other.


# 18. Economics and execution realism

Costs, latency, and capacity are first-class.

## 18.1 Fee engine

Fee schedules MUST be versioned by:

- venue;
- instrument;
- account tier if relevant;
- maker/taker status;
- effective time.

Unknown fee -> blocked or conservative bound, never zero.

## 18.2 Spread and slippage

LIKI SHALL support:

- historical spread;
- volatility-dependent spread;
- order-size-dependent slippage;
- uncertainty ranges;
- stress multipliers;
- calibration from paper observations.

## 18.3 Market impact and capacity

Capacity analysis considers:

- average/quantile traded volume;
- order-book depth where available;
- participation rate;
- expected impact;
- strategy crowding assumptions where estimable;
- liquidation capacity;
- simultaneous portfolio demand.

Capacity is a curve, not one number.

## 18.4 Funding and borrow

Perpetual/futures strategies SHALL include:

- funding schedule;
- funding sign and timing;
- basis effects;
- financing;
- liquidation/margin rules.

Short/borrow strategies SHALL include borrow availability/cost when applicable.

## 18.5 Execution constraints

Adapters MUST read venue metadata dynamically:

- tick size;
- lot size;
- min quantity;
- min notional;
- price bands;
- order types;
- rate limits;
- status/maintenance.

Hardcoding exchange constraints without effective dates is prohibited.

## 18.6 Fill model

Where relevant:

- marketable orders use realistic spread/impact;
- limit orders model non-guaranteed fills;
- queue assumptions are explicit;
- partial fills exist;
- cancels have latency;
- rejects exist;
- stale quotes exist;
- outage states exist.

A backtest MUST NOT assume every touched limit order fills.

## 18.7 Latency

Latency is represented as distributions or measured samples:

- signal computation;
- decision;
- API/network;
- acknowledgement;
- cancel;
- market-data delay.

For a 4h strategy, latency may matter less than in HFT but cannot be set to zero automatically.

## 18.8 Paper-vs-backtest telemetry

Preserve and extend V3.3 fields:

- expected/observed order count;
- fill rate;
- backtest/paper slippage;
- latency p50/p95/p99;
- partial fills;
- rejects;
- paper-vs-backtest deviation;
- expected vs observed turnover;
- expected vs observed net edge;
- cost-model calibration error.

Paper telemetry SHALL update execution-model confidence, not rewrite historical results.

---

## 18.9 Transaction-cost accounting without double counting

LIKI SHALL distinguish component models from realized implementation shortfall.

Canonical implementation shortfall for an order is measured relative to a declared decision/arrival benchmark price. Depending on the model, it may already contain spread, market impact, timing, and price movement while the order is active.

Therefore:

`net_pnl = gross_market_pnl - explicitly_nonoverlapping_cost_components`

The accounting engine MUST NOT subtract both implementation shortfall and the same spread/impact component a second time.

Every cost model SHALL document whether it is:

- additive component;
- decomposition of another cost;
- diagnostic only.

## 18.10 Order lifecycle state machine

Paper and future live adapters SHALL use an explicit order state machine:

```text
INTENT
 -> PRETRADE_VALIDATED
 -> SUBMITTED
 -> ACKNOWLEDGED | UNKNOWN_RECONCILING
 -> PARTIALLY_FILLED <-> AMENDED/CANCEL_PENDING
 -> FILLED | CANCELLED | REJECTED | EXPIRED

UNKNOWN_RECONCILING -> ACKNOWLEDGED | PARTIALLY_FILLED | FILLED | CANCELLED | REJECTED | EXPIRED
```

Venue-specific states map into this canonical model without losing raw status.

Every order has a durable client-generated idempotency ID. Unknown acknowledgement state enters `UNKNOWN_RECONCILING`; reconciliation by client/order ID and authoritative venue state is required before any semantically equivalent resubmission. A timeout is never proof that the venue did not accept the order.

## 18.11 Order semantics and venue filters

Venue adapters SHALL dynamically ingest and enforce current rules where relevant:

- price/tick filters;
- quantity/lot/market-lot filters;
- min/max notional;
- price bands;
- order-count/rate limits;
- supported order types;
- time-in-force;
- post-only semantics;
- reduce-only/close-position semantics;
- self-trade prevention where supported;
- trigger protection.

Rounding MUST use venue-defined direction/precision and be covered by golden tests. "Round to N decimals" is not an acceptable generic implementation.

## 18.12 Mark, index, last, margin, liquidation, and ADL

Derivatives models SHALL explicitly distinguish:

- execution/trade price;
- mark price used for unrealized PnL/margin where applicable;
- index/reference price;
- liquidation trigger calculation;
- maintenance margin schedule;
- cross vs isolated margin;
- contract multiplier/inverse-vs-linear PnL;
- liquidation fees;
- insurance-fund/ADL mechanics where material and documented.

A liquidation simulator that uses last trade price when the venue liquidates by mark price is invalid.

## 18.13 Collateral, stablecoin, venue, and counterparty risk

Crypto research SHALL model the possibility that the settlement/collateral asset is not risk-free.

Relevant stresses include:

- stablecoin depeg;
- collateral haircut/change;
- venue withdrawal freeze;
- venue insolvency/default;
- API/trading halt;
- market dislocation between venues;
- forced position migration/delisting;
- funding/borrow discontinuity.

Paper portfolio risk reports SHALL separate trading alpha from collateral/venue exposure.

## 18.14 Market-data reconnect and order-book integrity

Execution simulation using order books SHALL reject periods with unresolved sequence gaps.

After reconnect, the adapter MUST perform the venue-specific snapshot/resync procedure before declaring the book valid.

Queue-position models SHALL state their assumptions. If historical message-level data cannot support queue reconstruction, LIKI MUST use bounded/uncertain fill assumptions rather than pretend exact queue priority.

## 18.15 Transaction Cost Analysis (TCA)

Paper and future live execution SHALL produce TCA relative to declared benchmarks such as:

- decision/arrival mid;
- order-submission mid;
- volume/time-weighted benchmark where relevant;
- close/open benchmark only when economically appropriate.

TCA decomposes, where identifiable:

- explicit fees/rebates;
- spread capture/crossing;
- impact;
- delay/timing;
- opportunity cost of unfilled quantity.

Decomposition residuals are reported; they are not silently forced to zero.

## 18.16 Venue adapter conformance suite

Every venue/instrument adapter requires fixtures for:

- contract multiplier math;
- tick/lot/min-notional;
- fee/funding;
- timestamp signing/server offset;
- order-state mapping;
- partial fill;
- reject;
- liquidation/reference price semantics;
- reconnect/gap recovery;
- rate limit behavior.

No new venue may be used for promotion evidence until its conformance suite passes.

---

## 18.17 Decision-time vs fill-time causality

Every simulated order SHALL have:

- `information_cutoff_time`;
- `signal_ready_time`;
- `order_eligible_time`;
- `submission_time`;
- `ack_time` where modeled;
- fill time(s).

No fill may occur before the information and computation that caused the order existed.

Decision variables such as order size, aggressiveness, venue choice, limit price offset, and participation target may use only liquidity/volume/book information available by `order_eligible_time`. The simulator MAY use subsequently realized trades/book evolution to determine what would have filled, but future realized volume/depth/path MUST NOT leak backward into the decision policy.

For example, sizing an order as 5% of the *eventual full-day volume* at the start of that day is invalid unless that future volume was only used for ex-post capacity reporting rather than order choice. Decision-time expected volume and ex-post realized volume are separate fields/models.

This invariant is tested automatically for every authoritative trade ledger.

## 18.18 Fee/rebate and cost-version causality

Historical fee/funding/borrow schedules SHALL be applied using the version/effective time that would have applied to the simulated account assumptions.

If exact historical fee tier is unknown, LIKI uses a declared conservative/interval assumption and reports sensitivity.

Rebates may reduce costs but cannot be assumed unless order type/fill-liquidity status supports them.

---

## 18.19 Cross-venue inventory, transfer, and settlement realism

Cross-venue/cash-and-carry/arbitrage research MUST NOT assume instantaneous free movement of capital.

Where relevant, simulation SHALL model:

- pre-funded inventory by venue;
- transfer/withdrawal/deposit fees;
- withdrawal enable/disable status;
- blockchain/network confirmation time;
- venue processing latency;
- transfer size/minimum constraints;
- stablecoin/asset conversion basis;
- rebalancing cost;
- trapped-capital/venue-default risk.

If a strategy requires simultaneous legs on different venues, execution feasibility MUST state whether inventory is pre-positioned. "Buy here, instantly move assets, sell there" is invalid unless the transfer time is genuinely compatible with the strategy.

## 18.20 Multi-leg atomicity and leg risk

For basis, spread, hedge, or arbitrage strategies, LIKI SHALL model the possibility that one leg fills and another does not.

Required outputs include:

- leg fill timing difference;
- temporary directional exposure;
- hedge slippage;
- cancel/retry behavior;
- maximum unhedged interval;
- loss under adverse move during leg mismatch.

A backtest assuming perfectly atomic fills across independent venues is invalid unless an actual atomic mechanism exists.

---

## 18.21 Paper/live-path structural parity

Paper execution SHALL exercise the same canonical downstream pipeline intended for future live use wherever possible:

```text
signal
 -> position-sizing policy
 -> pre-trade deterministic risk checks
 -> venue constraint/rounding
 -> order intent + idempotency ID
 -> canonical order state machine
 -> fill/reject/cancel events
 -> accounting/reconciliation
 -> risk/telemetry
```

The difference is the final venue adapter: paper uses the calibrated simulator/shadow mechanism; future live would use an authenticated venue adapter after separate authorization.

Paper-only shortcuts that bypass pre-trade risk, rounding, order states, or accounting make readiness evidence invalid.

## 18.22 Evaluator anti-gaming boundary

Candidate strategy code SHALL NOT receive direct access to:

- sealed labels/results;
- evaluator source/config secrets not required for the public contract;
- hidden benchmark answers;
- downstream gate state that could reveal hidden evaluation detail.

The evaluator executes candidate artifacts through a declared interface and independently calculates metrics.

Candidate code MUST NOT be able to return an arbitrary "score" that the gate trusts.

Any attempt to inspect protected evaluator/holdout paths is a hard research-integrity failure and security event.

## 18.23 Paper evidence limitations and endogenous market impact

Paper execution is valuable but cannot observe every effect of deploying real capital. In particular, a paper order does not necessarily:

- consume queue priority exactly as a real order;
- move the market;
- create information leakage/adverse selection from the owner's actual flow;
- trigger venue-specific account/risk behavior identical to funded trading;
- reveal true capacity at a larger notional.

Therefore paper/shadow evidence SHALL distinguish `OBSERVED_PAPER` from `MODELLED_AT_SCALE`.

Capacity and market-impact claims above the actually observed/measurable scale remain model estimates with explicit uncertainty. Paper success MUST NOT be described as empirical validation of endogenous impact at capital sizes never traded.

Exchange testnets/sandboxes are protocol/integration evidence only unless independently proven representative. Synthetic testnet liquidity/fills MUST NOT be treated as evidence of real-market spread, queue priority, impact, or capacity.

A future micro-live stage, if separately owner-authorized, exists partly to calibrate these residual execution uncertainties; until then they remain explicit readiness limitations rather than silently assumed solved.

## 18.24 Execution/cost-model calibration separation

Execution, slippage, fill, and impact models can themselves overfit.

Material cost/execution models SHALL record the data used for calibration and the data used for validation/outcome analysis. Using the same paper episodes to repeatedly fit a cost model and then claim those episodes independently validate it is prohibited.

Model recalibration after paper outcomes creates a new model version. Subsequent strategy readiness MUST account for the fact that earlier paper evidence contributed to calibration.

Where sample size permits, holdout/challenger periods or cross-period/venue validation SHOULD be used for material execution models.

---



## 18.25 Deterministic pre-trade risk envelope and venue-native self-trade prevention

Even though real-money execution is disabled at issuance, PAPER mode SHALL exercise the deterministic pre-trade risk layer intended for future execution.

Before an order intent can enter the venue adapter, deterministic controls validate at least, where applicable:

- mode/strategy authorization;
- instrument trading status;
- stale/invalid market-data state;
- price and quantity precision;
- tick/lot/min-notional/max-position filters;
- maximum order notional and size envelope;
- aggregate strategy/portfolio exposure envelope;
- margin/collateral sufficiency;
- reduce-only/position-mode semantics;
- order-rate/message-rate limits;
- price-deviation/fat-finger bounds;
- duplicate client-order intent;
- self-trade/cross-strategy conflict.

The control MUST reject or hold an invalid order **before** sending it; "send then immediately cancel" is not an acceptable substitute for a pre-trade control.

Where a venue exposes native Self-Trade Prevention (STP), LIKI SHALL version the supported STP modes and configure the intended mode explicitly. Prevented matches/quantities and STP-triggered expirations are part of the order-event ledger and TCA.

Where native STP is absent or insufficient, the portfolio/order-intent layer SHALL deterministically prevent LIKI-controlled strategies from unintentionally crossing against one another when the production architecture can know both sides.

The venue adapter SHALL not assume order semantics from a generic name alone. `GTC`, `IOC`, `FOK`, post-only, pegged, trailing, reduce-only, close-position, SOR, and other venue features are capability-discovered/versioned where used and tested in the conformance suite.

## 18.26 Emergency stop and kill-switch hierarchy

LIKI SHALL expose an independently enforceable emergency-stop hierarchy. A reasoning agent is not required for activation.

Minimum scopes:

1. `STRATEGY_STOP` — block new intents from one strategy and reconcile/cancel its working orders according to policy;
2. `VENUE_STOP` — block new intents to one venue/account and reconcile/cancel safely where connectivity permits;
3. `PAPER_GLOBAL_STOP` — block all new paper order intents and enter reconciliation-only mode;
4. `FUTURE_LIVE_GLOBAL_STOP` — reserved for future LIVE; cannot be disabled or bypassed by a strategy agent.

Automatic triggers may include:

- accounting/position disagreement;
- stale or corrupted market data;
- runaway order/message rate;
- repeated rejected/duplicate orders;
- risk-envelope breach;
- unbounded/unexpected exposure;
- venue/reference-price anomaly;
- control-plane integrity incident.

Manual owner/operator activation SHALL always be possible through an authenticated control path independent from ordinary research inference.

A stop action MUST define exactly whether it means `BLOCK_NEW`, `CANCEL_WORKING`, `RECONCILE`, and/or future `REDUCE/FLATTEN`. Blindly market-flattening during stale data, venue outage, or extreme illiquidity can increase loss; therefore automatic flattening is never implied merely by the word "kill switch" and requires a separately tested policy.

Kill switches SHALL be exercised in paper/chaos tests on a recurring basis. An untested emergency stop is not an accepted control.

## 18.27 Derivatives forced-event and bankruptcy-waterfall semantics

For leveraged derivatives, the simulator/risk engine SHALL represent venue-specific forced-event semantics when material, including:

- initial and maintenance margin;
- cross/isolated/portfolio-margin mode;
- position mode (one-way/hedged where applicable);
- mark/reference price used for margin;
- liquidation threshold and forced-order behavior;
- bankruptcy price/account-equity treatment;
- liquidation fees;
- insurance-fund/socialized-loss mechanisms where applicable;
- ADL or analogous forced deleveraging;
- settlement/expiry behavior;
- collateral haircuts and eligibility.

If a venue's exact historical forced-event mechanism is unavailable, the strategy is tested with conservative bounded scenarios rather than an invented precise liquidation model.

A strategy whose apparent survival depends materially on optimistic liquidation/ADL/insurance assumptions cannot be promoted as robust.

---

## 18.28 Market-conduct and aberrant-message surveillance

Future execution readiness SHALL include deterministic surveillance for LIKI's own order/message behavior. The purpose is both operational safety and prevention of behavior that could be manipulative, abusive, or contrary to venue rules.

Monitored patterns include where relevant:

- excessive order/cancel/message bursts;
- duplicate or self-referencing orders;
- self-trade/prevented-match frequency;
- repeated orders far from executable intent without a legitimate strategy reason;
- rapid layering-like placement/cancellation patterns;
- runaway replace/cancel loops;
- order-to-trade and cancel-to-fill behavior;
- repeated venue filter/risk-control rejection.

This surveillance is not an LLM legal classifier. Deterministic thresholds/venue rules can pause affected strategies, while ambiguous conduct is escalated through Compliance/Governance before future live use.

Paper mode SHOULD generate the same logical message stream needed to exercise these controls even though no real market is affected.

A strategy MUST NOT be optimized to "just pass" surveillance thresholds. Market-conduct controls are safety constraints, not an alpha objective.

---

## 18.29 Atomic pre-trade risk reservations and working-order exposure

A pre-trade risk check that only reads current positions is unsafe under concurrency: two individually valid order intents can race and jointly exceed a portfolio/venue/collateral limit.

Before an accepted paper/future-live order can be submitted, LIKI SHALL atomically acquire a **risk reservation** against the relevant current limits. The reservation accounts for the conservative incremental exposure if the order fills, including other outstanding working orders/reservations.

The reservation contract SHALL include where relevant:

- strategy/order intent ID;
- instrument/venue/account;
- worst-case incremental notional/delta/exposure under the declared fill assumptions;
- margin/collateral consumption;
- portfolio/venue/strategy risk-limit versions;
- expiry/ownership/version;
- release/convert rules on reject, cancel, expiration, partial fill, fill, or reconciliation.

The check-and-reserve operation MUST be serialized/atomic with respect to competing reservations for the same constrained risk pool. Independent workers MUST NOT each approve against the same unreserved headroom.

Open orders count toward risk according to a conservative policy; they are not ignored merely because they have not filled yet.

On partial fill, reserved risk is reconciled into realized position exposure plus remaining working-order reservation. Amend/replace that increases possible exposure requires a new/delta risk validation before venue submission.

If reservation state and venue/account state disagree, new risk-increasing orders are blocked until reconciliation.

Paper mode SHALL exercise this exact reservation lifecycle so future readiness includes concurrent-strategy oversubscription tests.

---

## 18.30 Execution-evidence fidelity contract

Every execution-sensitive backtest/TCA artifact SHALL state:

- execution-data fidelity/capability from Section 13.21;
- fill-model class/version;
- queue-position assumption, if any;
- hidden-liquidity assumption;
- sampling/gap limitations;
- whether evidence is historical public market data, paper/account-observed, or purely modeled;
- uncertainty attributable specifically to missing microstructure observability.

A strategy whose apparent edge depends materially on maker fills/queue priority SHALL NOT reach strong readiness on `F0/F1/F2` evidence alone unless a deliberately conservative bound still leaves robust net edge.

The evaluator SHALL include a counterfactual adverse-fill scenario appropriate to the data fidelity so an optimistic queue assumption cannot be the sole source of profitability.

## 18.31 Endogenous account-level fee tier and rebate state

Trading fees can depend on account-wide rolling volume, maker/taker mix, program status, token-balance discounts, venue tier, rebates, and rule changes. Multiple strategies sharing one account can therefore change each other's fee economics.

LIKI SHALL distinguish:

- venue published base schedule;
- historically applicable account/tier state where known;
- portfolio/account-wide volume effects;
- temporary rebates/promotions;
- uncertain historical tier state.

A strategy MUST NOT claim a fee tier that would only exist **because of hypothetical volume not actually produced by the simulated portfolio**, unless the portfolio simulation endogenously reaches that tier under the venue's point-in-time rules.

When historical account tier is unknown, the evaluator uses declared conservative/base and sensitivity cases rather than selecting the most favorable tier.


# 19. Parameter sensitivity and robustness

## 19.1 Sensitivity first, tuning second

Parameter sensitivity is a cheap high-information test.

For important parameters LIKI SHALL evaluate neighborhoods or structured perturbations.

A narrow isolated optimum is a warning.

## 19.2 Plateau evidence

Preferred behavior:

- broad stable region;
- monotonic/understandable response;
- reasonable degradation under perturbation.

A single parameter point that dominates only because of noise is weak evidence.

## 19.3 Regime tests

Regime analysis may include:

- volatility;
- trend;
- liquidity;
- funding/basis;
- stress;
- macro/market structure;
- venue conditions.

Regime labels MUST be computable point-in-time if used for actual strategy behavior.

## 19.4 Anti-Goodhart rule

Once a robustness/adversarial dataset has been used for repeated tuning, it is no longer a clean robustness set.

LIKI MUST:

- record the exposure;
- downgrade its evidentiary role;
- rotate/newly define sealed tests where possible.

---

## 19.5 Synthetic market/stress evidence ceiling

Synthetic/Monte-Carlo/generative scenarios are valuable for falsification, tail exploration, sensitivity, and discovering failure modes. They are not independent empirical proof that alpha exists.

Every synthetic result SHALL be labeled by evidence role, for example `SYNTHETIC_STRESS`, `MODELLED_COUNTERFACTUAL`, or `GENERATIVE_SCENARIO`.

A candidate MAY fail or be downgraded because it is fragile under a defensible stress model, but it MUST NOT achieve strong edge promotion solely because it performs well on synthetic data generated from assumptions favorable to the strategy.

If a synthetic generator is tuned after observing candidate outcomes, the generator version/evidence is contaminated for confirmatory use on that candidate/descendant unless renewed independent validation exists.

Generative/LLM market-agent simulations SHALL never be displayed as probabilities of real market outcomes unless independently calibrated for that exact use; qualitative scenario coverage and hypothesis generation are their default roles.


# 20. Independent verification protocol

## 20.1 Required for promotion

Material candidates require independent verification.

## 20.2 Blind phase

Use fresh contexts.

Recommended default counts:

- normal promotion: at least 2 independent reviews plus deterministic validation;
- high-impact/ambiguous promotion: at least 3 independent reviews;
- governance AMBER/RED changes: see Section 23.

Counts may increase dynamically when reviewers disagree.

## 20.3 Double-loop review

The preferred pattern is:

```text
Proposal/Evidence
 -> Blind Review A
 -> Blind Review B
 -> Blind Review C (if needed)
 -> Adversarial Audit
 -> Synthesis
 -> targeted additional evidence if unresolved
 -> final decision
```

The process SHALL stop when additional reviews have low expected information value, not because an arbitrary number of agents have spoken.

## 20.4 Reviewer disagreement

Disagreement is evidence.

Do not average away severe objections.

A critical objection MUST be:

- falsified;
- accepted as risk;
- routed to more evidence;
- or block promotion.

---


## 20.5 Effective reviewer independence and anti-Sybil rule

Reviewer count is not the same as reviewer independence.

Spawning many sessions of the same model with materially identical prompts/evidence ordering MUST NOT be treated as many independent confirmations merely because the sessions have different IDs.

Each critical review records an `independence_profile` containing:

- model family/version/provider correlation domain;
- reviewer mandate;
- prompt template/version;
- evidence ordering;
- whether prior verdicts were visible;
- shared tools/retrieval policy;
- known shared upstream/context contamination.

Governance/verification MAY request more reviewers, but decision confidence MUST reflect correlated failure risk. Majority vote is not a substitute for resolving a material objection.

LIKI SHALL detect and reject review-padding/Sybil behavior in which a workflow creates additional nominal reviewers without meaningful procedural/model/evidence independence merely to satisfy a count threshold.

When only Opus 5 is available, independent fresh contexts plus materially different adversarial mandates are required, and the residual same-model correlation limitation remains explicit in the final evidence packet.

---

# 21. LIKISim and counterfactual system simulation

LIKI SHALL include a governance/research-change simulator.

Synthetic LLM simulation is a supporting tool, not a primary truth oracle.

## 21.1 Evidence hierarchy for system-change simulation

Preferred order:

1. real historical replay;
2. counterfactual replay against past branch/gate events;
3. bootstrap/Monte Carlo under empirical distributions;
4. deterministic fault simulation;
5. synthetic stress cases;
6. LLM multi-agent scenario simulation;
7. shadow deployment;
8. canary deployment.

## 21.2 Historical replay example

For a proposed G6 threshold change, replay past branches and calculate:

- branches killed earlier;
- later winners that would have been lost;
- compute/API cost saved;
- late deaths prevented;
- false-rejection delta estimate;
- discovery-yield delta;
- statistical-capital delta.

## 21.3 Scenario count

Synthetic scenario count is dynamic.

Typical guidance:

- simple/local change: 5–6 scenario classes;
- moderate change: ~10;
- difficult systemic change: up to ~20 or more if each scenario adds distinct information.

Do not create 20 paraphrases of the same scenario.

## 21.4 LLM simulation limitations

LLM-generated "market reactions" MUST be labeled synthetic and cannot promote a financial strategy on their own.

Their best use is:

- governance consequences;
- operational interactions;
- rare failure brainstorming;
- adversarial policy testing;
- identifying missing scenarios.

---

# 22. Self-improvement architecture

LIKI has two distinct evolutionary processes.

## 22.1 Quant Evolution

Continuously improves:

- hypotheses;
- strategies;
- portfolio candidates;
- execution models.

## 22.2 System Evolution

More cautiously improves:

- agents;
- prompts;
- routing;
- gates;
- evaluators;
- scheduler;
- memory;
- governance;
- infrastructure.

The two processes MUST NOT use the same evidence as if independent.

System improvements evaluated on old strategy campaigns are susceptible to meta-overfitting; separate benchmark/shadow evidence is required.

## 22.3 Change lifecycle

```text
PROPOSE
 -> CLASSIFY
 -> BLIND REVIEW
 -> REPLAY/SIMULATE
 -> TEST
 -> SHADOW
 -> CANARY
 -> PROMOTE
 -> MONITOR
 -> ROLLBACK if needed
```

No research agent writes directly to production policy.

## 22.4 Shadow controller

New schedulers, lane allocators, gate policies, and inference routers SHOULD initially run in shadow:

- receive the same state;
- make recommendations;
- do not control production;
- compare counterfactual decisions.

Only after measured superiority and no critical regression may they be promoted.

## 22.5 System-Evolution Trial Ledger and meta-overfitting control

Repeatedly tuning LIKI itself against the same historical campaigns/benchmarks creates meta-overfitting even if every individual strategy test is statistically disciplined.

Every material system-change proposal SHALL record:

- system-change trial ID and ancestry;
- components/policies changed;
- development governance/research benchmarks observed;
- shadow/canary outcomes observed;
- sealed system-benchmark exposures;
- metrics/objectives used to choose the change;
- whether prior benchmark failures influenced the next proposal.

LIKI SHALL maintain separate **system-evolution statistical capital** from strategy statistical capital.

A governance/research benchmark repeatedly used to tune scheduler, gates, router, prompts, memory, or Council becomes a development benchmark. Strong claims of system improvement then require a rotated/sealed benchmark, prospective shadow evidence, or other evidence not already optimized against.

The Council MUST NOT claim that repeated improvement on one fixed set of historical campaigns proves general research-office improvement.

---

# 23. Governance Council

## 23.1 Cadence

- regular governance meeting: **monthly**;
- emergency meeting: event-triggered at any time.

Agents may file proposals continuously. The monthly cadence is a mandatory review opportunity, not a restriction preventing emergency fixes.

## 23.2 Proposal package

A governance proposal contains:

```json
{
  "proposal_id": "...",
  "change_class": "GREEN|AMBER|RED",
  "problem": "...",
  "proposed_change": "...",
  "affected_modules": [],
  "evidence_ids": [],
  "counterevidence_ids": [],
  "historical_replay_plan": "...",
  "risk_if_changed": "...",
  "risk_if_not_changed": "...",
  "rollback_plan": "...",
  "owner_attention_required": false
}
```

## 23.3 Reviewer independence

First-round council reviewers MUST use independent fresh contexts.

They do not know who authored other reviews and do not see other verdicts.

They receive a complete evidence packet appropriate to the decision, including operational history, trial/waste statistics, known incidents, and relevant tests.

## 23.4 Change classes

### GREEN
Examples:

- prompt wording;
- noncritical scheduler optimization;
- timeout adjustment within tested range;
- dashboard/query optimization;
- cheap-model routing improvement.

Default review:
- 3 blind reviewers;
- 1 synthesis;
- tests + shadow where relevant.

Owner policy:
- owner notified;
- if no veto within **24 hours**, eligible to auto-promote after all automated acceptance checks pass.

### AMBER
Examples:

- gate threshold modification;
- prescreen behavior;
- evaluator implementation change that preserves semantics;
- substantial memory/retrieval policy change;
- lane allocation policy;
- statistical-method parameter change.

Default review:
- 5 blind reviewers;
- at least 1 adversarial auditor;
- synthesis chair;
- historical replay;
- simulation;
- shadow/canary.

Owner policy:
- owner notified with evidence;
- may be eligible for 24-hour no-veto promotion **only if** the change does not touch RED boundaries and council/automated acceptance criteria are satisfied.

### RED
Examples:

- removing a gate;
- weakening sealed-holdout protections materially;
- changing constitutional rules;
- enabling real-money execution;
- increasing allowed financial risk beyond approved envelope;
- modifying secrets/security boundary;
- permitting agents to self-approve;
- deleting audit provenance;
- disabling fail-closed accounting.

Review:
- minimum 7 blind reviewers when feasible;
- at least 2 adversarial audits;
- synthesis chair;
- full replay/simulation/shadow package.

Owner policy:
- **explicit owner approval required**;
- silence is never consent;
- no automatic promotion.

## 23.5 Emergency governance

Emergency triggers include:

- gate appears to reject valuable candidates systematically;
- gate appears to leak/accept invalid candidates;
- material cost/economic model error;
- data/evaluator corruption;
- repeated provider/system failure causing material waste;
- paper strategy behavior materially diverges from expected;
- security incident.

Emergency authority may automatically **tighten, pause, quarantine, rollback, or disable** risk.

Emergency authority may NOT automatically remove a constitutional safeguard or enable real money.

## 23.6 Consensus

Council decisions are not pure majority votes.

A proposal passes only when:

- required independent reviews exist;
- material objections are resolved or explicitly accepted with evidence;
- replay/simulation passes;
- rollback is defined;
- no constitutional blocker exists.

Reviewer count may increase when uncertainty remains.

The objective is convergence of evidence, not unanimity theater.

---

## 23.7 Exact 24-hour owner no-veto semantics

For GREEN and explicitly eligible AMBER changes, the 24-hour timer starts only when:

1. the evidence package is complete;
2. automated prerequisites have passed;
3. the owner notification is successfully delivered through the configured authoritative channel;
4. `delivered_at_utc` is durably recorded.

`promotion_eligible_at = delivered_at_utc + 24 hours`.

The timer is frozen if:

- a new material objection appears;
- replay/shadow/canary regresses;
- a relevant incident is open;
- notification delivery becomes uncertain due to control-plane failure;
- the proposal is reclassified RED.

Owner veto permanently stops that proposal version. A materially revised proposal gets a new ID and new review/timer.

## 23.8 Council evidence access vs context limits

Governance reviewers SHALL have **authorized access to the complete relevant evidence universe**, but LIKI MUST NOT dump the entire database into one model context.

Each reviewer receives an indexed evidence dossier and tools to drill into raw artifacts, event history, metrics, prior incidents, counterevidence, and simulations as needed.

The system records what each reviewer actually inspected. A reviewer saying "I reviewed everything" is not accepted without access telemetry.

## 23.9 Council conflict-of-interest and meta-audit

- proposal author cannot be the sole classifier of change severity;
- proposal author cannot act as final synthesis chair for an AMBER/RED proposal;
- council prompts/policies themselves are versioned model-risk objects;
- a separate periodic governance audit evaluates whether Council is too permissive, too conservative, anchored, or wasting inference;
- Council performance is benchmarked on known-good/known-bad historical change cases.

Critical deployments SHOULD use a four-eyes principle at the deterministic authorization layer even if more LLM reviewers participated.

---

## 23.10 Owner authority and scientific integrity

The owner can always:

- pause/kill research;
- veto a governance change;
- request additional research;
- authorize a RED change after required evidence;
- tighten safety/risk controls.

The owner SHALL NOT be represented in the audit trail as having "scientifically passed" a failed strategy merely by preference.

If the owner wants continued investigation of a failed ordinary-evidence candidate, it is reopened as an explicit owner-requested research/Frontier exception with contamination and cost recorded. Hard invalidity (for example leakage/accounting corruption) MUST be fixed before promotion evidence can resume.

Future live-risk loosening remains governed even when owner-requested; emergency owner actions may always reduce/disable risk.

## 23.11 Deterministic minimum change severity

Governance change severity has a protected deterministic floor. An LLM classifier may escalate severity but cannot downgrade below this floor.

A change is automatically `RED` if it can materially alter any of the following:

- Constitution or precedence rules;
- real-money enablement/authorization;
- ability to bypass or suppress a gate/audit event;
- sealed-holdout access/output granularity;
- critical accounting/risk enforcement;
- secret/credential boundary;
- audit immutability/retention;
- Governance severity classifier, owner-approval boundary, or RED definition itself;
- policy-engine authorization for protected resources.

Protected-path/module mappings SHALL be versioned outside ordinary agent-write permissions.

A proposal touching a protected path is at least the mapped severity even if its author labels it GREEN.

## 23.12 Governance self-reference and independence preservation

Changes to Council prompts, reviewer independence rules, synthesis logic, evidence-access policy, auto-promotion timers, or governance benchmarks are themselves model/governance changes.

Any change capable of making future approvals materially easier is `RED` unless a deterministic rule proves it cannot alter authorization/safety semantics. Cosmetic wording with no semantic effect MAY be lower class after diff/replay validation.

The Council SHALL NOT use its newly proposed governance rules to approve that same proposal. It is evaluated under the currently accepted governance version.

---

## 23.13 Change interaction, confounding, and deployment sets

Two changes can be safe in isolation and unsafe together. Governance SHALL therefore reason about **change sets**, not only individual proposals.

Every promotable governance change SHALL declare:

- scopes/modules/policies it touches;
- dependencies and incompatibilities;
- other unpromoted/recently promoted changes in overlapping scopes;
- whether its evidence assumes the old or new version of those dependencies.

Material changes in the same causal/operational scope SHOULD be deployed one at a time when attribution matters. If multiple changes are intentionally combined, they form one explicit composite change set and SHALL be tested/replayed/shadowed as the combination; individual approvals do not automatically approve the interaction.

If simultaneous changes prevent attribution of an observed regression/improvement, LIKI SHALL label causal attribution `UNRESOLVED` rather than crediting the preferred change. Factorial/controlled interaction tests MAY be used when justified.

Rollback planning SHALL consider coupled state/schema/policy changes; rolling back one member of a change set must not create an unsupported hybrid state.

## 23.14 Proposal staleness and pre-deployment revalidation

A council approval applies to an evidence/configuration snapshot, not forever.

Each proposal SHALL persist an `approval_snapshot_hash` over material evidence, affected policy/model versions, known incidents, and dependency versions used in review. Immediately before deployment, Governance performs a deterministic revalidation/diff.

Material changes since review — for example a new incident, contradictory forward evidence, dependency upgrade, provider/model change, evaluator change, or overlapping governance deployment — move the proposal to `STALE_APPROVAL` and require rebase/review appropriate to severity.

A 24-hour no-veto timer MUST NOT auto-promote a stale proposal. If material state changed during the timer, the timer is suspended until the proposal is revalidated and the owner notification semantics are satisfied again where required.

Emergency safety tightening always dominates a pending convenience/performance deployment.


# 24. Policy Registry and numeric governance

Every tunable number MUST live in a versioned policy registry.

Each numeric policy includes:

- unit;
- default;
- safe bounds;
- origin;
- rationale;
- last calibration;
- proposal ID;
- monitoring metric;
- rollback condition.

Example:

```yaml
policy:
  id: frontier_budget_fraction
  value: 0.08
  allowed_range: [0.05, 0.15]
  unit: fraction
  origin: LIKI_SRS_v1
  adaptive: true
  owner_override: false
```

Magic numbers embedded in code are prohibited for financial or research gating.

---

## 24.1 Gate calibration objective

A gate is an imperfect decision instrument. Gate calibration SHALL explicitly trade off:

- false promotion / expensive late failure;
- false rejection / missed edge;
- test cost;
- statistical-capital consumption;
- time to decision.

Calibration MUST NOT simply maximize historical PnL of branches that passed the gate.

When sufficient later evidence exists, LIKI estimates gate decision regret using later OOS/forward/paper outcomes and counterfactual replay.

## 24.2 Rejection Audit Reservoir

A system that kills branches early cannot estimate its false-negative rate if it never looks at rejected work again.

Therefore LIKI SHALL maintain a small, explicitly budgeted **Rejection Audit Reservoir** for branches rejected by ordinary evidence gates (not hard-invalidity gates).

Initial policy guidance:

- approximately **1–5%** of discretionary research budget;
- default boot target **2%** until empirical calibration;
- stratified across gate, family, novelty, and rejection confidence;
- sampling probability recorded for every audited rejection.

The reservoir may run additional downstream tests that normal policy would have skipped. Its purpose is **gate calibration**, not backdoor strategy promotion.

If a rejected candidate later appears genuinely strong, it can be reopened only through an explicit re-entry event and MUST satisfy the normal evidence path with contamination accounted for.

## 24.3 Estimating missed-edge rate

Because audit continuation is sampled, population false-negative estimates SHOULD account for the known sampling design (for example inverse-probability/stratified estimators where appropriate) rather than naively treating audited rejects as representative.

Outputs include uncertainty intervals. A tiny audit sample cannot justify a claim of near-zero false rejection.

Gate owners SHALL monitor:

- audited-reject later-survival rate;
- high-value missed-candidate rate;
- preventable late-death rate among accepted branches;
- total research cost.

This creates feedback on both sides of the screening problem.

## 24.4 Gate calibration changes

Threshold/rule changes require:

1. historical counterfactual replay;
2. Rejection Audit evidence where available;
3. false-positive and false-negative impact estimate;
4. compute/inference/statistical-capital impact;
5. shadow comparison;
6. Governance classification under Section 23.

A gate may be conditional on strategy class, sample size, market microstructure, or evidence uncertainty when justified. "One threshold for everything" is not required.

However, conditional gates MUST be specified before seeing the candidate result being judged; ad hoc exceptions are prohibited.

---

## 24.5 Failed-family cooldown boot policy

The original V3.3 cooldown durations are preserved as **initial boot defaults**, subject to later calibration:

```yaml
soft:
  expires_after_hours: 6
medium:
  expires_after_hours: 24
hard:
  expires_after_hours: 72
```

The legacy scalar priority penalties `15 / 35 / 100` are **not authoritative** in the new allocator because LIKI no longer uses one unrestricted weighted priority score. Their intent is preserved as increasing de-prioritization/block severity.

A hard cooldown blocks normal research on the same failed family. A Novelty/Frontier override is permitted only when:

- no hard invalidity exists;
- the new intervention is materially novel;
- the override is labeled and budgeted;
- the reason is recorded.

Family key baseline remains:

`asset_class + market + timeframe + strategy_family + signal_family + holding_period_bucket`

The key MAY be extended when evidence shows this grouping is too coarse, but changing the key is a gate-policy change and MUST be replay-tested.

---

# 25. Capital and portfolio readiness

## 25.1 No live capital at issuance

No real-money trading/withdrawal credentials are available to LIKI. Read-only market-data credentials, paper/testnet credentials, and inference-provider credentials MAY exist under the normal secrets policy.

A future live subsystem MUST remain physically/logically disabled. Trading permissions cannot be inferred from the mere presence of an exchange API credential.

## 25.2 The USD 10,000/week milestone

The owner’s target is tracked as a business metric:

- net simulated/paper PnL;
- after all modeled/observed costs;
- with capital required;
- with risk taken;
- with confidence interval;
- with capacity assumptions;
- with drawdown/tail behavior.

A strategy producing USD 10,000/week by requiring unacceptable leverage or fragile capacity has not achieved the objective.

## 25.2A Business milestone reporting convention

Because an absolute USD weekly PnL is meaningless without capital/risk context, the dashboard SHALL report the USD 10,000/week aspiration together with:

- capital/equity required;
- rolling 7-day net PnL;
- calendar-week net PnL;
- rolling 28-day average weekly net PnL;
- net return on capital;
- maximum drawdown/tail risk over the same evidence window;
- capacity estimate;
- confidence/uncertainty and forward opportunity count.

Canonical `net` for this business milestone means after trading fees, spread/implementation shortfall, funding, borrow/financing, and other strategy/venue costs modeled by LIKI. Personal income/capital-gains taxes are **not** silently included; if tax-aware optimization is later required it MUST be a separate policy/model.

One lucky paper week above USD 10,000 is not sufficient evidence of sustainable income and does not change real-money permissions.

---

## 25.3 Capital ladder for future use

```text
HISTORICAL
 -> SEALED VALIDATION
 -> FORWARD SHADOW
 -> PAPER
 -> READY_FOR_MICROLIVE
 -> [OWNER EXPLICIT ENABLEMENT]
 -> MICRO-LIVE
 -> SMALL
 -> MEDIUM
 -> LARGER
```

Capital scaling is two-way.

Evidence deterioration MUST reduce capital faster than evidence accumulation increases it.

## 25.4 No invented universal "57% risk"

"Risk > 57%" is not a defined financial risk measure and SHALL NOT be implemented.

Risk MUST be decomposed into measurable quantities, including where relevant:

- probability/risk of ruin;
- expected shortfall/CVaR;
- drawdown distribution;
- liquidation probability;
- leverage;
- tail exposure;
- concentration;
- correlation/tail dependence;
- liquidity-at-risk;
- gap risk;
- venue/counterparty risk;
- model uncertainty.

Specific future live limits MUST be set only when capital, instruments, venue, horizon, and owner risk envelope are known. Inventing precise live limits today would be false precision.

---

## 25.5 Portfolio construction is a separate model

A set of individually good strategies is not automatically a good portfolio.

Portfolio evaluation SHALL be performed on synchronized strategy positions/trades using common market data and execution constraints. Summing independently generated equity curves is insufficient when strategies compete for capital/liquidity or trade correlated instruments.

## 25.6 Portfolio objective and constraints

Portfolio construction follows the same hierarchy as strategy research:

1. hard constitutional/risk/liquidity constraints;
2. robust expected net portfolio utility;
3. diversification and capacity;
4. turnover/implementation cost;
5. only then secondary optimization.

The allocator MUST NOT maximize estimated mean return using unconstrained noisy forecasts.

## 25.7 Expected-return and covariance uncertainty

Expected strategy returns are high-uncertainty estimates and SHALL be shrunk/regularized or otherwise uncertainty-adjusted before allocation.

Covariance/correlation estimates SHALL use robust/shrinkage/factor/cluster approaches where appropriate rather than blindly invert a noisy sample covariance matrix.

LIKI SHALL track correlation instability across regimes and tail dependence, not only full-sample Pearson correlation.

## 25.8 Required portfolio risk views

Portfolio artifacts SHALL include where relevant:

- gross exposure;
- net directional exposure;
- leverage;
- asset/venue/collateral concentration;
- strategy concentration;
- marginal and component risk contribution;
- drawdown distribution;
- expected shortfall/CVaR;
- tail co-movement;
- liquidity-at-risk;
- liquidation/collateral stress;
- turnover and cost;
- capacity under simultaneous strategy demand.

VaR MAY be reported but MUST NOT be the sole tail-risk control.

## 25.9 Cross-strategy netting and conflicts

The portfolio simulator SHALL model:

- opposing signals that net exposure;
- strategies competing for the same liquidity;
- self-trading/order crossing prevention;
- common collateral/margin;
- shared venue/API failure;
- common data/model dependencies;
- correlated exits during stress.

Costs MUST be calculated on actual net executable order flow when the production architecture would net orders, while attribution retains each strategy's contribution.

## 25.10 Allocation methods

LIKI MAY support multiple robust allocators, for example:

- constrained risk budgets;
- volatility scaling;
- minimum-variance with shrinkage;
- hierarchical/cluster-based diversification;
- robust mean-variance;
- fractional Kelly as a diagnostic upper-bound concept.

No allocator is universally preferred. Full Kelly based on backtest estimates is prohibited as a default capital rule because edge uncertainty makes it dangerously unstable.

Allocator selection itself is a model-selection problem and enters the trial/model-risk ledger.

## 25.11 Risk of ruin and path simulation

Readiness analysis SHALL simulate path-dependent loss and capital survival under:

- parameter uncertainty;
- edge decay;
- correlation increase;
- slippage/cost shocks;
- venue/collateral events;
- gap moves;
- clustered losses.

The output is a distribution, not one "risk percentage."

## 25.12 Strategy decay, suspension, and retirement

A promoted strategy has ongoing monitoring states:

`HEALTHY`, `WATCH`, `DEGRADED`, `SUSPENDED`, `DORMANT`, `RETIRED`.

Triggers may include:

- forward edge decay beyond expected uncertainty;
- execution-cost deterioration;
- capacity collapse;
- mechanism invalidation;
- structural market change;
- persistent portfolio redundancy;
- data/model failure.

`DORMANT` is appropriate when a strategy may be economically valid only in a condition/regime that is currently absent. DORMANT strategies do not trade and do not receive automatic promotion when a favorable regime appears; reactivation requires a predeclared point-in-time regime rule plus refreshed execution/risk evidence.

Suspension/dormancy/retirement preserves lineage and does not erase bad history.

## 25.13 Capital readiness evidence packet

A `READY_FOR_MICROLIVE` packet SHALL include at minimum:

- complete strategy lineage and multiplicity history;
- latest code/data/evaluator hashes;
- statistical evidence and limitations;
- sealed result category/history;
- forward/paper duration **and effective independent opportunity count**;
- paper vs modeled TCA;
- portfolio contribution;
- risk-of-ruin/tail stress results;
- capacity/liquidity range;
- known model risks;
- explicit reasons the candidate could still fail.

No LLM narrative may substitute for these artifacts.

---

## 25.14 Factor, beta, and common-driver exposure

Where estimable, portfolio risk SHALL decompose common exposures such as:

- market/beta direction;
- volatility;
- momentum/trend;
- liquidity;
- carry/funding;
- asset/sector/coin clusters;
- venue/collateral;
- other statistically/economically justified factors.

Apparent strategy diversification that is actually one hidden common factor SHALL be reported as concentration.

Market-neutral/beta-neutral labels require measured neutrality over the relevant horizon; they are not accepted from strategy intent alone.

## 25.15 PnL attribution

Portfolio and paper reports SHALL reconcile PnL by:

- strategy;
- instrument;
- venue;
- signal/mechanism where attributable;
- gross market move;
- execution cost;
- fees;
- funding/borrow;
- collateral/FX effects;
- unexplained residual.

Residual above tolerance blocks authoritative performance reporting until reconciled.

---

## 25.16 Position sizing as a separate research object

Signal quality and sizing quality SHALL be evaluated separately before combined promotion.

A weak signal MUST NOT be made attractive merely by optimized leverage, and an excellent signal MUST NOT be rejected because one arbitrary sizing rule was poor.

Sizing research considers:

- forecast uncertainty;
- volatility/liquidity;
- concentration;
- drawdown/tail constraints;
- execution impact;
- portfolio interactions;
- capital capacity.

Sizing parameter search enters the Trial Ledger.

Paper runs SHALL use a predeclared versioned sizing policy. Re-optimizing size after every observed PnL fluctuation is adaptive research and MUST be treated as such.

---


## 25.17 Reverse stress testing, liquidity spirals, and simultaneous failure

Forward-looking risk SHALL include **reverse stress testing**: instead of only asking how the portfolio behaves under predefined scenarios, LIKI asks what combination of shocks is sufficient to violate survival, liquidity, margin, or drawdown constraints.

Reverse-stress dimensions include where relevant:

- correlation moving toward one during exits;
- volatility jump and spread/depth collapse;
- funding/borrow shock;
- stablecoin/collateral depeg or haircut;
- venue outage/withdrawal freeze;
- forced deleveraging/liquidation;
- simultaneous strategy stop-loss/exit demand;
- market impact increasing as positions are reduced;
- data/feed impairment during stress.

The stress engine SHALL model feedback loops where practical. For example:

`loss -> margin reduction -> forced sale -> impact/slippage -> larger loss`

and:

`liquidity shock -> wider spread -> lower capacity -> slower exit -> larger exposure time`.

A scenario library is not sufficient if it omits the smallest plausible combination that breaks the portfolio. Reverse-stress outputs SHALL identify dominant failure paths and uncertain assumptions.

## 25.18 Trapped capital, venue default, and recoverability

Capital on a venue is not equivalent to frictionless cash.

Portfolio/risk artifacts SHALL distinguish:

- immediately withdrawable/unencumbered capital;
- margin-encumbered collateral;
- capital trapped by open positions/orders;
- capital subject to withdrawal delay/maintenance;
- venue/counterparty concentration;
- recovery assumptions under venue failure or asset depeg.

Cross-venue arbitrage/carry MUST NOT assume capital teleports between venues after a shock.

Stress tests SHOULD include partial or zero recoverability for a failed venue/counterparty where economically relevant. The recovery assumption is explicit and cannot default silently to 100%.

## 25.19 Owner business milestone and tax/reporting boundary

The USD 10,000/week owner milestone is an economic target, not a statement of after-tax take-home income unless a jurisdiction-specific tax/reporting model is explicitly configured and validated.

By default LIKI reports:

- trading PnL after modeled trading/execution/financing costs;
- capital required and risk used;
- whether taxes are `NOT_MODELED`, `ESTIMATED`, or `MODELED`.

`NOT_MODELED` taxes MUST NOT be displayed as zero taxes. Tax/legal accounting is outside the trading-edge evaluator unless a dedicated validated module is later added.

---

## 25.20 Portfolio/ensemble construction has its own multiplicity

Portfolio construction can overfit even when every component strategy has valid individual evidence. Searching many strategy subsets, weights, rebalance rules, covariance estimators, risk budgets, or ensemble combinations and reporting the best portfolio creates a new selection layer.

Therefore LIKI SHALL create a portfolio-level lineage/trial family recording at least:

- candidate strategy universe visible to the allocator;
- inclusion/exclusion variants;
- weight/sizing variants;
- allocator/model variants;
- rebalance/horizon variants;
- objective/constraint changes;
- portfolio validation exposures and forward feedback.

Portfolio-level statistical/evidentiary claims SHALL account for this search. The allocator cannot reset multiplicity by combining individually promoted strategies.

If individual strategies' sealed results were inspected and then used to choose portfolio membership/weights, those results are **development-used evidence for that portfolio-construction decision**. They remain valid evidence about the individual strategy's past promotion, but they are no longer untouched confirmation of the selected portfolio combination. Strong portfolio claims therefore require portfolio-level sealed/chronologically later forward evidence not used to choose the combination.

This applies equally to ensembles, meta-strategies, dynamic strategy-selection rules, and regime-conditioned switching among strategies.

## 25.21 Portfolio optimizer benchmark and simplicity challenger

Every material portfolio optimizer SHALL be compared against at least one simple, predeclared challenger appropriate to the problem (for example equal-weight/1-N, constrained risk budget, or another low-degree-of-freedom baseline).

A complex optimizer that only wins in-sample after a large search but cannot demonstrate robust incremental value over a simple challenger SHALL NOT be preferred merely because its historical optimum is higher.

The benchmark itself is versioned; choosing the weakest benchmark after seeing outcomes is metric/benchmark shopping and enters the Trial Ledger.


# 26. Market expansion

## 26.1 Phase 1

Liquid crypto, approximately 4h primary research horizon as described in Section 13.

## 26.2 Expansion Gate

A new asset class is unlocked only after LIKI demonstrates:

- evaluator reliability;
- low silent-error rate;
- statistical accounting integrity;
- execution-model calibration;
- research efficiency;
- governance stability;
- data readiness.

Potential later domains:

- US equities;
- futures;
- options;
- FX;
- other liquid markets.

Each domain SHALL have domain-specific:

- data model;
- market calendar;
- execution model;
- cost model;
- corporate-action/funding/borrow semantics;
- risk rules;
- evaluator.

Crypto assumptions MUST NOT be copied blindly to equities/options.

---

# 27. Experiment caching and counterfactual reuse

## 27.1 Cache key

An experiment cache key includes relevant hashes of:

- code;
- data;
- evaluator;
- environment;
- configuration;
- mechanism;
- execution model;
- seed policy.

## 27.2 Equivalent work

If an equivalent experiment already exists under materially identical conditions, LIKI SHOULD reuse it rather than rerun.

## 27.3 Counterfactual experiment selection

When LIKI has evidence for combinations such as:

- A
- A+B
- A+C

it SHOULD choose the next experiment by expected information, rather than blindly run every remaining combination.

Ablation and factorial designs MAY reduce experiment count.

Cache reuse never allows stale market assumptions to masquerade as fresh forward evidence.

---

# 28. Causal / mechanism evidence graph

LIKI SHALL maintain an evidence graph:

```text
Hypothesis
  -> Predicted mechanism
  -> Intervention
  -> Experiment
  -> Observation
  -> Finding
  -> Ablation/Reproduction
  -> Generalized claim
  -> Forward evidence
```

Every finding records:

- direct evidence;
- counterevidence;
- causal/associational status;
- confidence;
- scope;
- known failure regimes;
- reproductions.

A performance increase alone is not automatically a causal mechanism.

---
# 28A. Model Risk Management Lifecycle

LIKI treats strategies, execution models, cost models, risk models, statistical models, data transformations, inference routers, and material third-party models as model-risk objects.

This section adopts the useful principles of modern model-risk practice: inventory, materiality, effective challenge, validation, ongoing monitoring, outcome analysis, third-party oversight, and lifecycle retirement. It is an engineering standard for LIKI, not a claim that LIKI is a regulated bank.

## 28A.1 Model inventory

Every model-risk object SHALL have a `model_record` containing:

```json
{
  "model_id": "...",
  "model_type": "strategy|risk|cost|execution|statistics|data_transform|router|third_party|other",
  "owner_role": "...",
  "developer_artifact_ids": [],
  "purpose": "...",
  "allowed_uses": [],
  "prohibited_uses": [],
  "materiality": "CRITICAL|MATERIAL|SUPPORTING",
  "inputs": [],
  "outputs": [],
  "assumptions": [],
  "limitations": [],
  "dependencies": [],
  "validation_status": "...",
  "champion_challenger_status": "...",
  "monitoring_plan_id": "...",
  "version": "...",
  "status": "DEVELOPMENT|SHADOW|APPROVED|WATCH|SUSPENDED|RETIRED"
}
```

## 28A.1A Model Card / Data Card artifacts

Every CRITICAL/MATERIAL model SHALL produce a machine-readable Model Card artifact summarizing purpose, scope, assumptions, validation, limitations, dependencies, and current status.

Every promoted dataset family SHALL produce a Data Card artifact summarizing provenance, time coverage, availability semantics, quality limitations, licensing/retention, and known contamination/repair history.

Cards summarize canonical records; they do not replace raw evidence.

## 28A.2 Materiality

- `CRITICAL`: can directly change a gate, risk/capital readiness, accounting, execution economics, or future orders;
- `MATERIAL`: materially affects strategy selection/research decisions;
- `SUPPORTING`: convenience/diagnostic model whose error cannot directly promote or risk capital.

Validation rigor increases with materiality.

## 28A.3 Independent validation and effective challenge

A model developer cannot be the sole validator.

Validation SHALL cover as appropriate:

- conceptual soundness;
- data appropriateness;
- implementation correctness;
- benchmark/challenger comparison;
- sensitivity;
- outcome/backtest analysis;
- limitations and misuse cases;
- ongoing-monitoring thresholds.

## 28A.4 Champion/challenger

Material models SHOULD maintain challengers when the value justifies the cost.

A challenger runs in shadow until evidence supports promotion. The current champion is not assumed correct simply because it is deployed.

For LLM routing, challengers include different effort levels/providers/prompts/models. For cost/execution models, challengers may be alternate parameterizations or independent implementations.

## 28A.5 Ongoing monitoring and drift

Monitoring SHALL distinguish:

- input/data drift;
- outcome/performance drift;
- calibration drift;
- market-structure drift;
- provider/model-version drift;
- assumption violation.

Drift detection is diagnostic evidence; it does not automatically justify re-tuning on the same test evidence.

## 28A.6 Third-party/vendor models and data

A vendor/API/library output is not exempt from validation because its internals are proprietary.

LIKI SHALL record known methodology/version/limitations, benchmark observable behavior, monitor changes, and isolate vendor failures.

This applies to LLM providers, market-data vendors, exchange reference calculations, and third-party quant libraries.

## 28A.7 Aggregate model risk

The inventory SHALL expose common dependencies such as:

- same market-data source;
- same LLM family;
- same covariance estimator;
- same execution model;
- same stablecoin/venue;
- same feature family.

Ten models sharing one wrong assumption are not ten independent confirmations.

## 28A.8 Retirement and exception management

Retired models remain reproducible for historical audit.

Temporary model-use exceptions require:

- explicit limitation;
- reason;
- compensating control;
- expiry;
- owner/governance authority appropriate to materiality.

## 28A.9 Outcome-analysis independence and feedback contamination

When observed paper/forward outcomes are used to recalibrate a model, those outcomes are no longer independent validation evidence for the recalibrated version.

Model Risk records SHALL link each model version to:

- development/calibration evidence;
- validation evidence;
- monitoring/outcome evidence;
- evidence later consumed by recalibration.

The status of an evidence set may move from `VALIDATION` to `DEVELOPMENT_USED` for descendants; the historical fact that it was once an independent validation remains auditable.

This rule applies to execution/cost models, risk models, statistical models, feature models, inference routers, and portfolio allocators as well as trading strategies.

---

# 29. Scheduler and resource management

## 29.1 Separate resource classes

Maintain separate limits/queues for:

- inference;
- deterministic evaluator;
- backtests;
- data;
- paper execution;
- UI projection;
- maintenance;
- governance;
- load/proof.

Load/proof work MUST NOT appear as active research.

## 29.2 Priority

Priority is lexicographic + VOI-aware, not a single unbounded score.

Inputs may include:

- owner task urgency;
- age/starvation;
- gate criticality;
- expected information;
- candidate value;
- novelty;
- cost;
- failed-family evidence;
- risk.

No priority may bypass hard scientific/risk gates.

## 29.3 Resource pressure

Scheduler SHALL observe:

- CPU;
- RAM;
- I/O;
- GPU memory/utilization where relevant;
- provider rate limits;
- DB pressure;
- evaluator queue;
- data-provider limits.

Jobs with unknown resource demand should be conservatively scheduled until measured.

## 29.4 Backpressure

Backpressure triggers include:

- inference burn spike;
- provider failure storm;
- DB/evaluator saturation;
- repeated infrastructure failures;
- queue age imbalance;
- data-provider throttling.

Backpressure reduces new work before killing valuable running work.

---

## 29.5 Operational task lifecycle and truthful activity state

The canonical operational states preserve V3.3 semantics:

```text
created
queued
leasing
running
waiting_external
hibernating
completed
failed
killed
expired
rejected_by_policy
blocked_by_cooldown
blocked_by_budget
```

Definitions:

- `waiting_external`: a deterministic external job/backtest/data operation is active; no LLM is implied;
- `hibernating`: role/task context is retained but no active runtime/inference call exists;
- `running`: valid active worker/inference lease + fresh heartbeat + real current action;
- `expired`: lease/heartbeat validity expired before clean completion;
- `blocked_by_budget`: Inference Broker/resource budget denied start;
- `blocked_by_cooldown`: research policy denied the family.

### Stale projection

A run projected as active becomes `STALE` in UI/Telegram when:

`heartbeat_age_sec > max(30, timeout_sec * 0.20)`

This is the V3.3 boot rule. It is a versioned operational policy and may later be calibrated by task class.

A stale projection MUST NOT be shown as normal `Running`.

### Allowed activity labels

At minimum:

- Running
- Waiting on backtest
- Waiting on data
- Hibernating
- Available
- Blocked by budget
- Blocked by cooldown
- Stale
- Failed

Forbidden without corresponding evidence:

- "thinking" without an inference lease;
- "working" without an active task;
- "researching" without an artifact/action target;
- "team meeting" without governance/deliberation events.

---

## 29.6 Task dependency DAG, bounded fan-out, and deadlock prevention

Agentic decomposition SHALL be represented as an explicit task dependency graph rather than implicit conversational spawning.

Every spawned task SHALL declare:

- parent/causal task or explicit root campaign;
- semantic purpose and expected artifact;
- dependency IDs;
- task class/priority;
- incremental and subtree budget envelope;
- cancellation/failure propagation policy;
- whether the child result is independently useful if the parent dies.

Creating many individually cheap child tasks MUST NOT bypass the parent/campaign inference/compute/statistical-capital budget. Child allocations consume from the authoritative aggregate envelope before launch.

Task dependencies SHALL be acyclic unless a workflow type has an explicitly modeled iterative state machine. New dependencies are cycle-checked transactionally. A conversational instruction such as "ask each other until agreement" cannot create an unbounded graph.

Iterative deliberation/research loops require a bounded stopping contract based on budget, convergence/information gain, evidence state, or explicit iteration ceiling; each iteration remains auditable.

The scheduler SHALL detect dependency deadlock/stall conditions, including:

- dependency cycle;
- all runnable tasks waiting on permanently failed/quarantined parents;
- resource reservation/lease waits with no progress;
- orphaned child tasks after parent cancellation;
- repeated spawn/dedup loops.

Resolution is fail-safe: cancel/quarantine/release reservations or replan from durable state. It MUST NOT invent fake completion merely to unblock the graph.

Semantic deduplication is applied **before** expensive child-task fan-out where practical.


# 30. Security and control plane

## 30.0 Threat model and trust boundaries

LIKI SHALL be designed under the assumption that correctness failures can be accidental **or adversarial**. No LLM, generated program, retrieved document, research worker, third-party provider, or market-data source is trusted merely because it normally behaves correctly.

Threat actors/failure sources considered include at minimum:

- hallucinating/manipulated LLM output;
- prompt/data injection in papers, web pages, logs, tool outputs, or market/vendor metadata;
- buggy or malicious generated research code;
- compromised ordinary research worker/service;
- stolen/replayed low-privilege credential;
- compromised inference/data/vendor dependency;
- corrupted/poisoned/stale market data;
- accidental owner/operator misconfiguration;
- malicious or pathological market behavior;
- future exchange/venue/API compromise/failure.

Trust zones SHALL be explicit and separately authorized, including at least:

1. untrusted generated-code/research sandbox;
2. ordinary research/inference workers;
3. authoritative event/persistence plane;
4. policy/governance control plane;
5. sealed evaluator/data zone;
6. secrets/credential broker;
7. market-data ingestion boundary;
8. paper/future order-risk and venue-adapter boundary.

Crossing a trust boundary requires an authenticated, schema-validated, policy-authorized interface. Filesystem/network proximity is not authorization.

The LLM SHALL be treated as an untrusted decision proposer with bounded capabilities, not as a security principal that can grant itself permissions. Natural-language claims such as "this is safe", "I am the verifier", or "the owner approved" have zero authorization value without deterministic evidence.

Security design SHALL minimize blast radius: compromise of a research worker cannot directly mutate governance policy, read sealed data, access secrets, falsify privileged provenance, or create future live orders.

The threat model is versioned and reviewed after material incidents/architecture changes. New external capabilities/providers require a trust-boundary review before production admission.

## 30.1 Central policy engine

Sensitive actions pass through a central policy engine:

- shell;
- filesystem writes;
- network;
- MCP/tools;
- model access;
- secrets;
- Telegram mutation;
- evaluator/gate changes;
- future execution.

## 30.2 Self-modification restrictions

Agents cannot directly modify protected areas, including:

- security policy;
- inference budget policy;
- governance rules;
- sealed dataset access rules;
- credential stores;
- real-money enablement;
- immutable audit storage.

Changes require governance and versioned deployment.

## 30.3 Secrets

Secrets SHALL:

- never enter model prompts unless absolutely required and explicitly allowed;
- never be written to logs/artifacts;
- be brokered to the minimum process;
- be scoped and rotatable;
- be removed from child environments where unnecessary.

## 30.4 Prompt/data injection

External papers, websites, documents, data descriptions, and model outputs are untrusted content.

They cannot issue operational instructions merely by containing text that looks like a prompt.

Tool permissions derive from LIKI policy, not retrieved content.

## 30.5 Control plane authentication

Mutation endpoints require authenticated local/admin authorization.

Telegram identities MUST map to approved roles.

No Telegram command can enable real-money trading.

---

## 30.6 Generated-code execution sandbox

LLM-generated or research-branch code is untrusted.

Experiments SHALL execute in isolated, reproducible sandboxes/containers or equivalent OS isolation with:

- workspace-scoped write access;
- no host credential access;
- no production policy write access;
- network denied by default and allowlisted per task;
- CPU/RAM/GPU/process/time quotas;
- no privileged container mode;
- no host Docker socket exposure;
- explicit mounted datasets/artifacts;
- cleanup/ephemeral filesystem policy.

Full host filesystem + unrestricted network MUST NOT be the autonomous default.

## 30.7 Least privilege and RBAC

Capabilities are granted to task identities, not agent names.

Roles SHALL have least-privilege permissions for:

- read evidence;
- write research artifacts;
- submit experiments;
- mutate gates;
- access sealed data;
- change policy;
- access secrets.

A role permitted to propose a policy does not automatically have permission to deploy it.

## 30.8 Software supply-chain integrity

Production/research environments SHALL use:

- pinned/locked dependency versions;
- integrity hashes where tooling supports them;
- dependency vulnerability scanning;
- provenance for downloaded binaries/models;
- an SBOM or equivalent dependency inventory for release builds;
- controlled package-install path inside sandboxes.

An agent cannot install an arbitrary package into the trusted control-plane environment merely because it helps one experiment.

## 30.9 Tamper-evident audit

Critical audit/event history SHALL be append-only at the application level and protected against ordinary agent mutation.

Periodic checkpoints SHOULD hash/sign or externally replicate event ranges so later modification is detectable.

## 30.10 Encryption and data protection

Secrets are encrypted at rest using a secrets manager or OS-backed secure store.

Backups containing credentials or sensitive operational state SHALL be encrypted.

Logs MUST redact credentials, authorization headers, signed URLs, and private API material.

---

## 30.11 Compliance/data-use guardrails for future execution

Before any future LIVE capability, LIKI SHALL include a reviewed compliance/venue-policy layer appropriate to the owner, jurisdiction, venue, and instruments.

At minimum, the system MUST prevent intended production behavior based on:

- spoofing/deceptive order placement;
- wash/self-trading where prohibited or economically artificial;
- manipulation of reference prices;
- unauthorized use of confidential/nonpublic information;
- violation of data/API license terms known to the system.

This section does not ask LLMs to make legal determinations. Uncertain legal/venue-policy questions are escalated to the owner and remain blocked until resolved.

## 30.12 Data classification and external-model egress

The fact that an LLM provider is useful does not grant it access to every LIKI artifact.

LIKI SHALL classify data/artifacts at minimum as:

- `PUBLIC`;
- `INTERNAL`;
- `CONFIDENTIAL`;
- `SECRET`;
- `SEALED`.

Examples:

- public papers/documentation may be `PUBLIC`;
- proprietary strategy artifacts and licensed market data may be `INTERNAL`/`CONFIDENTIAL`;
- API keys/tokens are `SECRET`;
- raw promotion holdouts are `SEALED`.

Every external inference route has an `egress_clearance` and provider-retention/privacy metadata when known. The ContextCompiler MUST NOT send content above the route's clearance. Tool outputs, retrieved documents, memory expansions, attachments, and error traces passed back into an external model are subject to the same egress check; classification cannot be bypassed by obtaining the data through a tool after the initial prompt.

`SECRET` credentials SHALL NOT enter ordinary LLM prompts. `SEALED` raw evidence SHALL NOT be sent to ordinary external research/reviewer providers unless a specifically isolated sealed-evaluator architecture explicitly authorizes the operation.

Data/API license restrictions also constrain egress: a provider cannot receive licensed raw data merely because the technical route is available.

If a reasoning task needs protected evidence, use approved local/deterministic aggregation, isolated evaluator outputs, or a provider explicitly approved for that classification.

## 30.13 Provider prompt-retention and training-risk registry

Where provider policy is known, LIKI SHALL record whether prompts/outputs may be retained, logged, or used for provider training/service improvement. Unknown retention is treated conservatively for confidential data.

A provider policy change that materially alters data handling triggers route reclassification and may invalidate its eligibility for protected task classes.

---

## 30.14 Future-live credential and account segregation

Real-money credentials are absent at issuance. If future LIVE is ever enabled, credential architecture SHALL preserve least privilege rather than attach one omnipotent exchange key to LIKI.

Where supported:

- market-data/read credentials are separated from trading credentials;
- trading credentials do **not** have withdrawal permission;
- withdrawal/transfer authority, if ever required, is separately controlled and never exposed to research agents;
- IP/network allowlists are used for trading credentials;
- subaccounts/account partitions SHOULD limit blast radius by venue/strategy/function where economically practical;
- credentials are individually revocable/rotatable and mapped to exact services;
- emergency revocation is tested;
- LLM prompts/tool outputs never contain raw credentials.

Future live risk-increasing authorization SHOULD use stronger owner authentication than a reusable bearer token alone (for example MFA/hardware-backed approval where practical). A lost Telegram/session credential MUST NOT be sufficient to grant LIVE or RED risk expansion.

Venue/API capability discovery SHALL verify actual account permissions before enabling an adapter. A configuration file claiming `can_trade=true` is not authority if the venue/account reports otherwise.

---

## 30.15 Authenticated service/worker identity and provenance integrity

`actor_id` in an event is not trustworthy merely because a process wrote that string. Material services/workers SHALL authenticate to the control/persistence plane using workload identity appropriate to the deployment (for example short-lived service credentials, mTLS, signed workload tokens, or equivalent).

The authoritative event/artifact layer SHALL bind the authenticated producer identity to:

- event writes;
- artifact registrations;
- gate decisions;
- evaluator outputs;
- sealed-evaluator responses;
- risk reservations/order intents;
- governance mutations.

Callers MUST NOT be able to impersonate another privileged actor by choosing an arbitrary `actor_id` field.

Critical artifact provenance SHALL include content digest plus authenticated producer/service identity and accepted code/environment fingerprint. A hash proves content identity, not who produced it.

Service credentials SHALL be least-privilege, rotatable, revocable, and excluded from LLM prompts/logs. Replay/duplicate use of an expired/revoked credential SHALL fail closed for mutations.

Compromise of one ordinary research worker MUST NOT grant sealed-data, governance, policy, secret, or order-authority privileges.

## 30.16 Break-glass administrative access

If emergency privileged access exists, it SHALL be a separate audited `BREAK_GLASS` path rather than a hidden bypass.

Break-glass use requires:

- strong owner/admin authentication;
- explicit reason/incident ID;
- minimum necessary capability;
- immediate immutable audit event;
- automatic owner notification where technically possible;
- post-event credential rotation/review when material.

Break-glass can pause, quarantine, reconcile, or tighten safety. It cannot silently erase evidence or bypass the Constitutional real-money authorization rule.


# 31. Observability and required benchmarks

## 31.1 Absolute invariants

Targets:

- silent gate bypasses: **0**
- LLM calls without inference lease: **0**
- gate mutations without actor/evidence event: **0**
- unversioned evaluator promotions: **0**
- real-money orders in non-LIVE mode: **0**
- unexplained active agents: **0**
- duplicate side effects from inference retry: **0**
- unresolved critical accounting discrepancies allowed to promote: **0**
- sealed evidence exposed outside policy: **0**

## 31.2 Inference metrics

- provider success rate;
- fallback recovery rate;
- correlated-failure clusters;
- cost per valid artifact;
- useful finding per Opus call;
- decision-change rate per expensive call;
- tokens/call by task class;
- latency p50/p95/p99;
- schema-valid response rate;
- repair rate;
- retry count;
- wasted inference USD.

## 31.3 Research metrics

- time to falsification;
- cost to falsification;
- cost per promoted candidate;
- productive rejection rate;
- true waste rate;
- preventable late-death rate;
- false-rejection estimate;
- rejection-audit later-survival rate;
- high-value missed-edge estimate;
- duplicate-work prevented;
- experiment-cache hit rate;
- discovery yield per fixed budget;
- gray-zone conversion rate;
- exploration yield;
- replication success rate.

## 31.4 Statistical metrics

- raw/effective trials per discovery;
- guard-holdout exposure;
- sealed-holdout exposure;
- statistical-capital burn;
- DSR/PSR distribution;
- PBO distribution;
- family-level data-snooping rejections;
- parameter fragility;
- forward degradation.

## 31.5 Execution metrics

- backtest vs paper cost error;
- backtest vs paper slippage error;
- fill prediction error;
- latency prediction error;
- reject-rate prediction error;
- capacity-model error;
- PnL reconciliation error;
- edge half-life;
- paper/backtest decay.

## 31.6 Governance metrics

- proposal count;
- approval/rejection rate;
- rollback rate;
- regression rate after change;
- decision regret at 30/90-day review;
- emergency interventions;
- unresolved reviewer disagreement;
- owner veto rate.

## 31.7 System metrics

- useful utilization;
- blocked useful work time;
- idle-with-positive-work time;
- queue starvation;
- recovery time;
- stale run count;
- event-lag;
- evidence completeness;
- replay reproducibility.

Targets for non-absolute performance metrics SHOULD be baselined empirically rather than invented. The system SHALL establish an initial benchmark period and then governance may set SLOs.

---

## 31.8 Canonical waste and rejection metrics

The misleading legacy metric `expensive_branch_waste_pct` is deprecated.

The canonical screening outcome metric is:

`post_backtest_rejection_rate_pct`

It is a rejection/survival statistic, not by itself a measure of wasted money/tokens.

The historical V3.3 value **96.4%** is retained only as a historical observation/example from that audit; it is **not a target, default, or expected future value**.

Required concepts:

### `productive_rejection`

A rejection is productive if the branch had to reach the observed gate to discover the failure with the information/tools available at that time.

Example: a PBO/statistical failure discovered only after the required backtest/splits is productive unless an already-available cheap proxy should reliably have killed it earlier.

### `true_waste`

A branch is true waste when evidence shows it could have been stopped earlier using information already available at lower cost.

Examples:

- repeated failed family under active cooldown;
- capacity below minimum already known before full test;
- exact/effective duplicate already rejected;
- known missing/invalid data before deep reasoning;
- LLM run with no expected artifact and no useful output;
- branch already hard-failed upstream.

### `preventable_late_death`

Baseline definition:

```text
death_gate >= G6
AND earliest_possible_death_gate <= G4
```

If gate numbering changes, the semantic definition is "expensive/late rejection whose decisive information was available by the cheap-prescreen stage."

Required metrics include:

- `post_backtest_rejection_rate_pct`;
- `true_expensive_waste_pct`;
- `productive_rejection_pct`;
- `preventable_late_death_pct`;
- `avg_inference_usd_per_survivor`;
- `avg_tokens_per_survivor`;
- `avg_runtime_sec_per_survivor`;
- late death by gate;
- top missed prescreens;
- Rejection Audit false-negative estimates.

---

## 31.9 Metrics are not direct reward functions

Observability metrics measure LIKI; they are not automatically objectives for agents.

Examples:

- lowering rejection rate is not good if junk passes;
- lowering inference cost is not good if false negatives rise;
- maximizing utilization is forbidden;
- maximizing number of findings invites trivial findings;
- maximizing paper PnL invites risk/overfit.

System changes SHALL be evaluated on a multi-metric regression profile with constitutional invariants and uncertainty, not one dashboard KPI.

---

# 32. Failure-mode requirements

LIKI SHALL have explicit behavior for at least the following.

## 32.1 Inference/provider

- 5xx;
- timeout;
- malformed response;
- partial response;
- rate limit;
- invalid key;
- key quota exhaustion;
- provider outage;
- shared upstream outage;
- duplicate response;
- response after caller timeout.

Required behavior: retry/reroute/hibernate/reconcile without duplicate side effects.

## 32.2 Database/event store

- restart;
- network partition;
- write timeout;
- duplicate event;
- partial transaction;
- replica lag.

Critical mutation requires durable commit before outward success is reported.

## 32.3 Data

- stale feed;
- missing candles;
- duplicate ticks;
- timestamp shift;
- provider disagreement;
- symbol remapping;
- delisting;
- extreme bad tick;
- late correction.

Unknown critical state blocks affected research/execution.

## 32.4 Backtest/evaluator

- crash;
- nondeterminism;
- configuration mismatch;
- inconsistent accounting;
- missing artifact;
- stale evaluator version;
- data hash mismatch.

Promotion stops.

## 32.5 Agents

- hallucinated artifact ID;
- unsupported claim;
- self-certification attempt;
- context contamination;
- repeated loop;
- no artifact;
- runaway calls;
- reviewer anchoring.

Use schema checks, evidence requirements, inference budgets, and independent verification.

## 32.6 Governance

- reviewers all same-model;
- reviewer disagreement;
- synthetic simulation contradicts historical replay;
- proposal author manipulates evidence package;
- automatic 24h timer fires during incident;
- rollback unavailable.

RED boundaries and unresolved blockers stop promotion.

## 32.7 Paper/future execution

- stale market data;
- order rejected;
- partial fill;
- venue outage;
- duplicate client order ID;
- clock drift;
- position mismatch;
- unexpected fee/funding;
- model/exchange position mismatch.

Accounting disagreement or stale state fails closed.

---

# 32A. Platform reliability, durable workflows, and disaster recovery

## 32A.1 Delivery semantics

LIKI SHALL assume messages/jobs can be delivered more than once.

The platform uses **at-least-once delivery + idempotent handlers** for material workflows rather than claiming magical exactly-once distributed execution.

Every material handler has:

- operation/idempotency key;
- durable state transition;
- retry classification;
- reconciliation path.

## 32A.2 Transactional state and outbox

Where a DB state change is required to publish a task/event, LIKI SHOULD use a transactional outbox (or equivalent atomic pattern) so state cannot commit while its required event disappears.

The event store/database remains the recovery truth; in-memory queues are acceleration, not authority.

## 32A.3 Worker leases and recovery

Long-running workers SHALL use:

- durable run record;
- lease/ownership token;
- heartbeat;
- lease expiry;
- safe takeover/reconciliation.

A stale worker returning after lease loss cannot commit a newer run’s result without compare-and-set/version validation.

## 32A.4 Recovery objectives

Initial non-live targets:

- committed critical gate/accounting/audit events: **RPO = 0** at application-success acknowledgment (durable DB commit required);
- orchestrator/control-plane auto-recovery target: **RTO <= 5 minutes** for common process/host-service failures where storage remains healthy;
- full research-service restoration target: **RTO <= 30 minutes** after a recoverable host restart;
- historical/raw market data may have a larger storage RPO only if it is reproducibly refetchable and manifests identify the gap.

If deployment infrastructure cannot meet these targets, the acceptance report MUST state the measured limit rather than pretend compliance.

## 32A.5 Backups and restore drills

At minimum:

- automated database backups;
- point-in-time/WAL-style recovery where supported;
- separate copy of critical configs/policy/event checkpoints;
- backup integrity verification;
- scheduled restore drills.

A backup never tested for restore is not considered a recovery control.

## 32A.6 Schema/data migrations

Migrations SHALL be versioned, ordered, testable on a production-like copy, and backward-aware.

For high-risk migrations:

- expand schema first;
- deploy compatible code;
- backfill with progress/checksums;
- switch reads/writes;
- contract old schema later.

Destructive migration requires backup/rollback evidence.

## 32A.7 Environment fingerprinting

Every reproducible experiment records:

- OS/architecture;
- container/image digest where used;
- Python/runtime version;
- dependency lock hash;
- relevant native library versions;
- GPU model/driver/CUDA when used;
- CPU architecture when numerical differences matter;
- locale/timezone;
- evaluator executable/code hash.

## 32A.8 Release environments

The trusted system SHALL separate at least:

- development;
- test/CI;
- shadow/staging;
- accepted production research.

An agent experiment cannot mutate accepted production code directly.

## 32A.9 Observability correlation

One trace/correlation ID SHALL link:

`idea -> inference -> artifact -> experiment -> backtest -> gate -> paper event -> governance decision`

Logs alone are not sufficient; structured metrics/events/traces MUST be queryable.

## 32A.10 Time and scheduler recovery

All deadlines use stored UTC timestamps and monotonic clocks for local duration measurements.

After downtime, timers (including governance 24h windows) are reconciled from durable state; a restarted process cannot accidentally treat a stale timer as newly created or already approved.

## 32A.11 Crash consistency versus disaster RPO

`RPO = 0 at application acknowledgment` means a successful critical transaction is durably committed for ordinary process/service crash recovery. It is **not** a truthful guarantee of zero loss after catastrophic loss of the only storage failure domain.

LIKI SHALL report two separate guarantees:

- `process_crash_rpo`: expected loss after application/host process failure with durable storage intact;
- `storage_disaster_rpo`: measured worst-case recovery point for storage/host/zone loss under the deployed backup/replication architecture.

A true `storage_disaster_rpo = 0` may be claimed only when the deployed synchronous replication/durability design and restore/failover tests support it. Otherwise the measured nonzero value is reported.

Critical DB settings that affect commit durability (or equivalent storage semantics) are part of the deployment fingerprint and acceptance evidence.

## 32A.12 Policy snapshotting and emergency invalidation

Active runs use the immutable evaluation snapshot from Section 7.3.

Ordinary policy deployment affects new runs, not the semantics of already-running work. Emergency safety tightening MAY:

- cancel a run;
- quarantine its result;
- force reevaluation;
- block downstream promotion.

It MUST NOT silently reinterpret a completed result as if it had been evaluated under rules that did not exist at execution time.

## 32A.13 Restart reconciliation safe mode

Any order-capable paper/future-live component starts after crash/restart in `RECONCILE_ONLY`. Before new order intents are permitted it SHALL reconcile, as applicable:

- durable desired state;
- open/unknown orders;
- fills;
- positions;
- balances/collateral;
- latest market-data validity;
- active policy/risk version.

Unknown external state remains fail-closed. Paper mode MUST exercise this recovery path because future readiness is invalid if only the happy-path order state machine is tested.

---


## 32A.14 Incident management, evidence preservation, and postmortem

LIKI SHALL have a formal incident lifecycle independent from ordinary research/governance flow.

Incident classes include at least:

- `SEV0`: potential real-money/safety boundary breach or critical audit/accounting integrity failure;
- `SEV1`: paper/execution, data, evaluator, security, or control-plane failure capable of invalid promotion or material systemic waste;
- `SEV2`: degraded service with bounded scientific/operational impact;
- `SEV3`: minor defect/noise.

At incident declaration LIKI SHALL, according to severity:

- freeze affected promotions;
- preserve immutable evidence/log/artifact snapshots;
- stop or quarantine unsafe workflows;
- notify the owner at the required severity;
- identify affected runs/evidence/policies;
- prevent automatic governance promotion where the incident could contaminate the decision.

Resolution requires:

1. containment;
2. reconciliation of authoritative state;
3. root-cause analysis;
4. affected-evidence impact assessment;
5. corrective/preventive action;
6. targeted regression tests;
7. explicit reopen/close event.

Material incidents require a structured postmortem. The objective is causal learning, not blame. Repeated incidents sharing a cause SHALL be linked so recurrence cannot be hidden as independent failures.

## 32A.15 Service-level indicators, reliability SLOs, and error budgets

"24/7" SHALL be measured rather than asserted.

LIKI SHALL define SLIs separately for:

- control-plane availability;
- scheduler progress;
- inference-route availability;
- deterministic evaluator/backtest availability;
- market-data freshness;
- paper order/reconciliation availability;
- evidence/event durability.

Availability is not one percentage for the entire office. A provider outage while deterministic useful work continues is different from loss of authoritative state.

SLO targets SHALL be policy/configuration values established from measured deployment capability. The dashboard MUST show measured compliance and sampling window.

Reliability error budgets MAY govern deployment pace: repeated SLO violations can freeze nonessential system changes and redirect capacity to reliability work.

No SLO may encourage hiding failures, dropping hard tasks, or weakening gates merely to improve uptime metrics.

## 32A.16 Configuration drift and accepted-release provenance

Accepted research/paper environments SHALL have a canonical desired-state fingerprint covering:

- source/artifact digests;
- runtime/dependency lock;
- DB schema/migration version;
- critical policy versions;
- evaluator/metric versions;
- provider/venue adapter configuration;
- security-relevant configuration.

Manual/out-of-band modification that changes a critical fingerprint creates `CONFIG_DRIFT`.

Unknown critical drift blocks authoritative promotion until reconciled. Emergency hotfixes are permitted only through an auditable emergency path and MUST be back-propagated into source/config management or rolled back.

Release artifacts SHOULD be reproducibly built where practical and content-addressed. Signed attestations MAY be added, but a signature does not replace tests or provenance.

## 32A.17 Poison tasks, dead-letter quarantine, and retry storms

A permanently failing task MUST NOT consume infinite retries merely because the office is required to work 24/7.

After bounded retry/fallback exhaustion, a task enters a durable `QUARANTINED`/dead-letter state containing:

- semantic task ID;
- final failure classification;
- attempts/routes/cost;
- last valid checkpoint;
- evidence/artifacts produced;
- safe replay instructions;
- whether other tasks depend on it.

Quarantined tasks remain visible and may be retried only after a relevant state/provider/code/policy change or explicit approved replay.

The scheduler SHALL detect retry storms by semantic task/failure family and trip backpressure/circuit breakers before they dominate inference or compute budget.

---

# 33. QA and verification strategy

Every major block is verified independently before full integration.

## 33.1 Test layers

1. static/schema validation;
2. unit tests;
3. property-based tests;
4. metamorphic tests;
5. differential tests;
6. mutation tests;
7. integration tests;
8. historical replay;
9. fault injection;
10. shadow operation;
11. canary operation;
12. end-to-end acceptance.

## 33.2 Inference Broker tests

Must test:

- 80% synthetic provider success;
- correlated provider outage;
- route fallback;
- fixed-price vs token-price optimization;
- truncated response;
- schema repair;
- timeout after actual success;
- idempotency;
- circuit breaker;
- task hibernation/revival;
- hedged critical request deduplication;
- provider billing-plan reconciliation, including billable failed calls.

## 33.3 Statistical-engine tests

Use synthetic datasets with known properties:

- true null;
- known signal;
- autocorrelation;
- heavy tails;
- skew;
- many correlated variants;
- many independent null strategies;
- deliberate overfit.

Verify that multiplicity and PBO/DSR-related logic behaves directionally and numerically as expected.

## 33.4 Backtest tests

- golden trade ledgers;
- hand-calculated fixtures;
- two independent accounting engines;
- fee/funding edge cases;
- tick/lot rounding;
- partial fills;
- intra-bar ambiguity;
- liquidation;
- missing data;
- deterministic replay.

## 33.5 Gate tests

- no gate bypass;
- `BORDERLINE` routes correctly;
- hard invalidity cannot use Frontier override;
- gate policy version recorded;
- failed gate prevents downstream expensive work unless explicit allowed diagnostic;
- governance change replays old outcomes.

## 33.6 Memory tests

- independent verifier cannot retrieve prior verdict;
- sealed contamination propagates;
- invalidated memory is not served as confirmed;
- stale domain memory receives lower weight;
- raw evidence remains accessible for audit.

## 33.7 Governance tests

- blind reviewers truly isolated;
- GREEN 24h no-veto flow;
- AMBER replay/shadow requirement;
- RED cannot auto-approve;
- emergency can tighten/disable;
- emergency cannot enable real money;
- rollback works.

## 33.8 Chaos suite

Faults SHALL include:

- kill inference worker;
- kill backtest worker;
- restart DB;
- duplicate event;
- freeze heartbeat;
- provider outage;
- data feed stale;
- clock shift;
- disk full;
- corrupt temporary artifact;
- network partition;
- delayed provider response;
- provider returns invalid JSON;
- evaluator returns conflicting totals.

The acceptance criterion is not "nothing fails." It is that failure is detected, bounded, auditable, and does not create an invalid promotion.

---

## 33.9 Portfolio/risk tests

Must include:

- synchronized multi-strategy portfolio replay;
- cross-strategy netting;
- common-liquidity capacity collision;
- covariance singularity/noise case;
- correlation-to-one stress;
- stablecoin/collateral shock;
- venue failure;
- risk-of-ruin Monte Carlo fixture;
- strategy suspend/retire lifecycle.

## 33.10 Model-risk tests

- every material model appears in inventory;
- developer cannot sole-approve CRITICAL model;
- model drift generates monitoring event;
- vendor version change triggers impacted-model review;
- retired model cannot be used for new promotion without reactivation workflow;
- common dependency is visible in aggregate model-risk query.

## 33.11 Security sandbox tests

- generated code cannot read host secrets;
- generated code cannot edit policy/security files;
- network deny/allowlist behaves as declared;
- CPU/RAM/time limits terminate runaway work;
- package installation stays inside sandbox;
- stale sandbox cannot mutate accepted artifacts.

## 33.12 Reliability/DR tests

- duplicate job delivery is idempotent;
- stale lease owner cannot commit;
- transactional outbox survives process crash;
- DB restore reproduces gate/event totals;
- backup restore drill succeeds;
- migration forward/compatibility tests pass;
- RPO/RTO are measured, not assumed.

## 33.13 Metric-contract tests

Every canonical metric has:

- hand-computed golden fixture;
- edge cases (zero variance, zero equity, missing periods, overlapping returns where relevant);
- unit/annualization tests;
- cross-implementation differential check for critical money metrics.

The same artifact evaluated by two modules MUST produce the same canonical metric within declared numerical tolerance.

Additional tests MUST cover unit/scale mismatches (percent vs basis points, seconds vs milliseconds, native asset vs reporting currency), NaN/Inf/empty samples, overflow, and exceptional-state propagation through gates.

## 33.14 Adversarial poisoned-corpus and end-to-end falsification tests

LIKI SHALL maintain a versioned red-team corpus containing deliberately defective strategies, datasets, model artifacts, and workflow events. At minimum include seeded cases for:

- lookahead/label leakage;
- incomplete-bar/same-close execution leakage;
- survivorship/delisting omission;
- post-hoc metric/window/universe shopping;
- duplicate trial renamed as a new strategy;
- omitted or double-counted fees/spread/impact/funding;
- impossible/overoptimistic fills;
- current exchange filters incorrectly used historically;
- hidden leverage/liquidation risk;
- stablecoin/collateral valuation at false par;
- parameter needle/fragility;
- stale worker committing after lease loss;
- duplicate side effect after timeout;
- evaluator score spoofing;
- sealed-data access/side-channel attempt;
- provider route falsely treated as independent/model-attested;
- confidential/secret data sent through unauthorized LLM egress;
- governance proposal intentionally misclassified below its deterministic severity floor.

The corpus also includes positive controls with known synthetic/simple signals so the system can detect pathological over-rejection.

Known seeded hard-invalidity cases MUST produce zero promotions. Positive controls do not need universal promotion, but rejection reasons MUST be scientifically coherent and benchmarked so safety is not achieved merely by rejecting everything.

The red-team corpus has development and sealed portions. Once implementation is optimized against a case, that case is development evidence and cannot remain the sole sealed acceptance proof.

## 33.15 Algebraic/accounting invariants

Property tests SHALL enforce invariants independent of individual examples, including where applicable:

- no fill before order eligibility/submission;
- position changes equal reconciled fills/corporate/instrument events;
- cash/equity changes reconcile to trades, marks, fees, funding, financing, collateral/FX conversion, and explicit flows;
- no authoritative PnL residual above tolerance;
- no order quantity violates effective instrument rules;
- no gate promotion exists without required predecessor evidence;
- no active run commits after losing its fencing/lease ownership;
- no sealed query returns more information than its declared output contract.


---


## 33.16 Final red-team control tests

Acceptance suites SHALL include:

### Research allocator
- heavily funded family is not judged superior merely by raw discovery count;
- allocator propensity/decision logs exist;
- early-performance-driven budget increase remains an adaptive Trial Ledger event;
- shadow allocator comparison uses common replay evidence.

### Crypto lifecycle/data
- token redenomination does not create artificial return;
- delisted failed assets remain in historical point-in-time universe;
- contract multiplier/rule change is applied at correct effective time;
- suspicious vendor-source corruption is quarantined, not LLM-smoothed.

### Pre-trade/STP
- two simultaneous valid orders cannot both consume the same unreserved portfolio headroom;
- working orders consume risk reservation under policy;
- partial fill/amend/cancel correctly reconciles reservation;
- invalid fat-finger/order-limit request is rejected before venue adapter transmission;
- duplicate intent cannot create duplicate order;
- venue-native STP mode is explicit where supported;
- prevented self-trade events reconcile correctly;
- unsupported order/TIF capability fails closed.

### Kill switch/restart
- two concurrent gate writers from the same prior revision cannot both become authoritative;
- unknown order acknowledgement enters reconciliation and cannot be blindly resubmitted;
- strategy, venue, and global paper stops block new intents at the declared scope;
- cancel/reconcile semantics are deterministic;
- global stop works without an LLM;
- stale/unknown market state does not trigger unsafe blind flattening;
- restart enters `RECONCILE_ONLY`.

### Portfolio stress
- reverse-stress engine finds known constructed failure paths;
- liquidity/impact feedback can increase losses rather than remain static;
- venue freeze/trapped-capital scenario reduces available capital correctly.

### Reliability/incident
- protected future-live credential fixtures demonstrate no withdrawal privilege on trading keys where venue capability supports separation;
- SEV1 incident freezes affected promotion and preserves evidence;
- config drift is detected;
- poison task enters quarantine instead of infinite retry;
- SLO reporting cannot classify blocked/failed work as healthy progress.

### Reviewer independence
- identical same-model sessions cannot satisfy diversity by ID count alone;
- prior verdict leakage marks reviewer independence as contaminated;
- material minority objection cannot disappear through simple majority averaging.

---

## 33.17 Perfection-pass adversarial tests

The final acceptance suite SHALL include seeded tests for:

### Context completeness
- one critical adverse artifact is absent from the retrieval index -> authoritative review blocks as incomplete;
- the artifact is tool-addressable but not preloaded -> tool access is captured in `context_manifest`;
- truncation pressure cannot drop constitutional/risk/counterevidence fields silently.

### Randomness and campaign selection
- best-of-many random seed cherry-picking is recorded as adaptive selection;
- changing bootstrap/CV nuisance settings after a desired result creates a new exploratory trial;
- extending a campaign until the first apparent winner cannot reset office-level multiplicity.

### Execution data fidelity
- aggregate L2 price-level data cannot produce an `EXACT_QUEUE_POSITION` claim;
- a maker-dependent strategy tested only on coarse fidelity is downgraded/blocked unless conservative fills preserve edge;
- hidden/admin/ADL data-coverage limitation propagates to the relevant conclusion.
- decision-time order sizing cannot use subsequently realized daily volume/book depth;
- ML preprocessing fitted on the full history before CV is detected as leakage.

### Portfolio multiplicity
- selecting the best of many portfolio subsets/allocators creates portfolio trial history;
- strategy-level sealed results used for portfolio selection are marked development-used for the portfolio decision;
- a complex optimizer cannot claim strong incremental evidence merely by beating a deliberately weak post-selected benchmark.

### Governance interactions
- two individually approved changes with a failing interaction cannot be deployed as an untested pair;
- material evidence change after approval creates `STALE_APPROVAL`;
- a stale proposal cannot auto-promote when its 24-hour timer expires.

### Service identity
- a research worker attempting to write an event as `sealed_evaluator` is rejected;
- content hash with unauthenticated producer is insufficient for a privileged artifact;
- revoked service credentials cannot perform mutations.
- compromise of an ordinary research worker cannot access sealed raw data, governance mutation, secret broker, or order authority;
- injected natural-language "owner approval" cannot cross a deterministic authorization boundary.

### Task graph/fan-out
- a parent cannot evade its campaign budget by spawning many bounded children;
- a dependency cycle is rejected before authoritative commit;
- parent failure/quarantine does not leave unauthorized orphan work running;
- iterative agent deliberation terminates under its declared stopping/budget contract.

### Temporal/synthetic/reference integrity
- selecting a favorable post-hoc recent window is recorded as an adaptive trial rather than a free transportability fix;
- structurally stale evidence remains historically visible and is not silently deleted;
- synthetic scenario success alone cannot promote an edge;
- two accounting engines sharing a deliberately faulty common arithmetic helper are detected as an invalid independence design;
- phase acceptance fails when a CRITICAL requirement is omitted from the SRS coverage graph.


# 34. Acceptance criteria

LIKI vNext is accepted only when all conditions below pass.

## 34.1 Operational truth

- every active agent maps to a real run;
- every run explains `why_running`;
- proof/load tasks are separate;
- stale heartbeats are not shown as running;
- deterministic waiting is not mislabeled LLM work.

## 34.2 Inference resilience

- every inference has a lease and cost record;
- synthetic 80%-success primary provider does not halt system progress;
- fallbacks operate without duplicate side effects;
- provider circuit breakers work;
- fixed-per-call and token-metered routes are both supported;
- router can choose deterministic/cheap/Opus/high-effort routes.

## 34.3 Research integrity

- every strategy has lineage;
- every adaptive test writes a trial event;
- every holdout exposure is recorded;
- duplicate and known-failed work can be killed early;
- Frontier can preserve legitimate borderline candidates;
- no hard invalidity is bypassable.

## 34.4 Statistical integrity

- sealed dataset is access-controlled;
- multiple-testing inputs come from real trial ledger;
- statistical engine handles non-normal/dependent test fixtures appropriately;
- exact sealed metrics are not leaked by default;
- human/owner result-driven variations remain linked in the Trial Ledger;
- forward evidence is never relabeled historical OOS.

## 34.5 Economics

- all material costs are explicit or unknown/blocking;
- dual accounting reconciles;
- paper-vs-backtest deviation is measured;
- 4h signal logic can use finer execution simulation;
- tick/lot/min-notional and partial-fill cases are tested;
- paper path uses the same pre-trade/risk/order/accounting pipeline intended for future live use.

## 34.6 Governance

- monthly council workflow exists;
- emergency workflow exists;
- blind-review isolation is proven;
- GREEN/eligible AMBER 24h owner-veto flow works;
- RED requires explicit owner approval;
- system change supports replay, shadow, canary, rollback.

## 34.7 Safety

- real-money remains impossible at issuance;
- no agent can modify protected safety/governance policy directly;
- secrets do not leak to prompts/logs;
- mutation endpoints require authorization;
- critical disagreements fail closed.

## 34.8 Reproducibility

For a representative acceptance campaign:

- gate replay: 100% reproducible;
- artifact provenance completeness: 100%;
- strategy/evaluator/data hashes: 100% present;
- unaccounted inference calls: 0;
- unexplained cost events: 0.

---

## 34.9 Additional acceptance: model/portfolio/platform hardening

Acceptance additionally requires:

- model inventory coverage = 100% for CRITICAL/MATERIAL model-risk objects;
- all CRITICAL models have independent validation status;
- portfolio risk is evaluated on synchronized positions, not summed standalone curves;
- critical crypto reference-price/margin semantics are venue-conformant;
- order-book gaps invalidate affected microstructure evidence;
- fixed-call vs token-call route economics are tested against live price config;
- semantic batching cannot contaminate independent reviews;
- all accepted LLM calls have prompt/context/model fingerprints;
- generated research code runs under the declared sandbox policy;
- restore drill and stale-worker takeover tests pass;
- no canonical metric has multiple undocumented formulas.

---



## 34.10 Mandatory 24-hour guarded soak acceptance

Before vNext is declared operationally accepted, the integrated system SHALL complete at least one **24-hour guarded continuous run** in non-real-money mode.

The run MUST exercise real scheduler/inference/data/backtest/paper-style workflows rather than only synthetic load. Fault injection may be scheduled into the run.

The final report SHALL include:

- total useful tasks and artifacts;
- inference attempts/cost/fallbacks;
- provider outages/recovery;
- stale/expired runs;
- queue/backpressure behavior;
- gate transitions and any violations;
- true waste/productive rejection;
- DB/event reconciliation;
- memory/lineage completeness;
- resource saturation;
- errors and recoveries;
- proof that real-money execution remained impossible.

A critical invariant violation invalidates the soak even if the process remained online.

## 34.11 Final adversarial acceptance

Before handoff as an accepted research system:

- the sealed portion of the red-team corpus SHALL have **zero promotions of known hard-invalidity cases**;
- all seeded critical accounting/reconciliation defects SHALL be detected and block authoritative reporting/promotion;
- unauthorized `SECRET`/`SEALED` LLM egress attempts SHALL be blocked;
- persistent requirement IDs SHALL remain unchanged after insertion of unrelated new requirements;
- policy changes during active runs SHALL not alter pinned evaluation semantics;
- crash/restart SHALL enter reconciliation-safe mode before new paper order intents;
- provider identity/failure-domain uncertainty SHALL not be converted into false independence claims.

Acceptance SHALL also report positive-control survival/rejection behavior, because a system that rejects every strategy trivially catches bad cases but fails its purpose.

---


## 34.12 Final operational-risk acceptance

Before this SRS may be declared fully implemented in non-live production research:

- material gate/state transitions reject stale concurrent writers rather than last-write-win;
- concurrent paper orders cannot oversubscribe one risk limit because pre-trade headroom is atomically reserved;
- all pre-trade paper controls execute before adapter submission;
- at least one authenticated manual global paper stop and one automatic stop scenario are successfully exercised;
- incident lifecycle and postmortem artifact generation are demonstrated;
- no poison/retry-storm task can run unbounded;
- configuration drift on a protected setting is detected and blocks authoritative promotion;
- crypto lifecycle fixtures include at least delisting and redenomination/contract-rule-change cases;
- reverse-stress testing demonstrates at least one known synthetic survival boundary;
- reviewer anti-Sybil/independence metadata is enforced;
- future-live credential design demonstrates least privilege and no agent-accessible withdrawal credential;
- allocator selection decisions are logged sufficiently for later bias/regret analysis.

These criteria add to, and do not weaken, Sections 34.1–34.11.

---

## 34.13 Perfection-pass acceptance

Acceptance additionally requires:

- every accepted MATERIAL/CRITICAL LLM decision has a persisted context-completeness manifest;
- seeded critical evidence omission blocks authoritative acceptance rather than producing a false confident decision;
- seed/nuisance/campaign-level adaptive search is represented in the Trial Ledger;
- execution-sensitive artifacts declare data-fidelity capability and never overclaim exact queue/fill evidence from aggregate depth;
- portfolio/ensemble search has independent lineage/multiplicity accounting and portfolio-level untouched/forward confirmation semantics;
- governance cannot deploy an untested interacting change set or a stale approval;
- material service/event provenance is bound to authenticated workload identity;
- trust boundaries are explicit and ordinary research compromise cannot laterally reach sealed/governance/secret/order authority;
- task decomposition is represented by an acyclic/bounded dependency graph and cannot bypass aggregate budgets through fan-out;
- temporal transportability is distinct from historical internal validity and post-hoc recency selection is not free;
- synthetic/generative market evidence has an explicit ceiling and cannot independently prove edge;
- critical dual implementations have common-mode-dependency analysis plus known-answer/property tests;
- the SRS Execution Compiler/coverage matrix has zero orphan CRITICAL requirements;
- all new red-team fixtures in Section 33.17 pass.


# 35. Suggested module layout

```text
liki/
  constitution/
    constitution.yml
    invariants.py

  contracts/
    schemas/
    sql/
    policy/
    requirements_registry.yml
    units.py

  event_store/
    events.py
    repository.py
    replay.py

  inference_broker/
    context_compiler.py
    batching.py
    economics.py
    broker.py
    router.py
    providers/
    retry.py
    circuit_breaker.py
    hedging.py
    leases.py
    cost_ledger.py
    quality_calibration.py
    provider_identity.py
    semantic_checkpoints.py
    route_experiments.py

  scheduler/
    fabric.py
    lanes.py
    queue.py
    voi.py
    backpressure.py
    active_runs.py

  memory/
    evidence_ledger.py
    lineage_graph.py
    knowledge_store.py
    retrieval_firewall.py
    contamination.py
    consolidation.py

  trials/
    ledger.py
    family.py
    effective_trials.py
    exposure.py

  data/
    symbol_master.py
    feature_registry.py
    stream_integrity.py
    time_sync.py
    instrument_specs.py
    external_evidence_snapshots.py
    manifests.py
    ingestion/
    quality/
    point_in_time/
    reconciliation/

  research/
    rejection_audit.py
    gate_calibration.py
    contracts.py
    hypothesis_graph.py
    dedup.py
    cooldowns.py
    frontier.py
    experiments.py

  accounting/
    units.py
    valuation.py
    exceptional_values.py

  backtest/
    engine.py
    accounting_primary.py
    accounting_reference.py
    costs.py
    fills.py
    capacity.py

  statistics/
    psr_dsr.py
    pbo.py
    reality_check.py
    spa.py
    bootstrap.py
    multiple_testing.py
    sensitivity.py

  gates/
    engine.py
    g0_contract.py
    g1_duplicate.py
    g2_data.py
    g3_mechanism.py
    g4_proxy.py
    g5_backtest.py
    g6_costs.py
    g7_oos.py
    g8_statistics.py
    g9_robustness.py
    g10_reproduction.py
    g11_sealed.py
    g12_paper.py
    g13_portfolio.py

  verification/
    blind_reviews.py
    ablation.py
    reproduction.py
    skeptic.py

  governance/
    proposals.py
    council.py
    blind_review.py
    simulator.py
    replay.py
    shadow.py
    canary.py
    rollback.py
    severity_floor.py
    system_trial_ledger.py

  paper/
    order_simulator.py
    telemetry.py
    reconciliation.py
    pretrade_risk.py
    emergency_stop.py

  model_risk/
    inventory.py
    validation.py
    monitoring.py
    challengers.py
    retirement.py

  portfolio/
    allocator.py
    covariance.py
    risk_attribution.py
    netting.py
    stress.py

  risk/
    risk_engine.py
    portfolio.py
    reverse_stress.py
    trapped_capital.py
    readiness.py

  sandbox/
    capabilities.py
    runner.py
    egress.py
    data_classification.py

  reliability/
    outbox.py
    leases.py
    recovery.py
    migrations.py
    evaluation_snapshot.py
    restart_reconciliation.py

  policy_engine/
    rules.py
    enforcement.py
    auth.py

  observability/
    metrics.py
    audit.py
    ui_projection.py
    telegram.py

  tests/
    unit/
    property/
    differential/
    statistical/
    replay/
    chaos/
    red_team/
    acceptance/
```

The exact layout MAY differ, but module responsibilities and separation MUST remain.

---

# 36. Required database tables / logical stores

At minimum:

- `event_log`
- `artifacts`
- `evidence`
- `hypotheses`
- `mechanisms`
- `strategies`
- `strategy_versions`
- `branches`
- `lineage_edges`
- `experiments`
- `dataset_snapshots`
- `evaluator_versions`
- `gate_decisions`
- `trial_events`
- `holdout_query_events`
- `statistical_capital_accounts`
- `inference_requests`
- `inference_attempts`
- `inference_cost_events`
- `provider_health`
- `active_task_runs`
- `resource_leases`
- `failed_family_cooldowns`
- `branch_cost_ledger`
- `rejection_audit_samples`
- `gate_calibration_runs`
- `paper_runs`
- `paper_orders`
- `paper_fills`
- `execution_deviation_events`
- `emergency_stop_events`
- `risk_reservations`
- `incident_events`
- `allocator_decisions`
- `portfolio_candidates`
- `governance_proposals`
- `governance_reviews`
- `governance_simulations`
- `policy_versions`
- `memory_claims`
- `memory_contamination_edges`
- `model_inventory`
- `model_validations`
- `model_monitoring_events`
- `model_cards`
- `data_cards`
- `agent_scorecards`
- `tool_registry`
- `context_manifests`
- `governance_change_sets`
- `portfolio_trial_events`
- `service_identity_events`
- `portfolio_runs`
- `portfolio_positions`
- `portfolio_risk_events`
- `metric_registry`
- `feature_registry`
- `symbol_master`
- `stream_integrity_events`
- `transactional_outbox`
- `backup_restore_events`

Earlier V3.3 tables (`token_leases`, `token_usage_events`, `active_task_runs`, `actor_artifact_gate_events`, `branch_cost_ledger`, `failed_family_cooldowns`) should be migrated or mapped rather than discarded blindly.

---

# 36A. Minimum Persistence Contracts

The following are minimum logical fields. Implementations may add columns and normalize into related tables, but MUST preserve these semantics, foreign-key relationships where applicable, and uniqueness/idempotency constraints.

## 36A.1 `inference_requests`

Required fields:

```text
inference_request_id PK
semantic_task_id
parent_run_id nullable
task_class
criticality
why_llm_needed
expected_artifact_schema
expected_decision_impact
preferred_reasoning_effort
status
max_call_cost_usd nullable
max_total_attempt_cost_usd nullable
max_latency_sec nullable
idempotency_key UNIQUE
context_manifest_hash
created_at
completed_at nullable
final_artifact_id nullable
failure_reason nullable
```

One semantic request can have many attempts.

## 36A.2 `inference_attempts`

```text
inference_attempt_id PK
inference_request_id FK
attempt_no
provider_route_id
provider_request_id nullable
model_family
model_version nullable
reasoning_effort
prompt_manifest_hash
started_at
completed_at nullable
status
http_status nullable
error_class nullable
input_tokens nullable
output_tokens nullable
billed_tokens nullable
token_count_method
fixed_call_cost_usd nullable
token_cost_usd nullable
total_cost_usd
latency_ms nullable
output_artifact_id nullable
response_hash nullable
```

Uniqueness at least on `(inference_request_id, attempt_no)`.

## 36A.3 `active_task_runs`

Minimum fields preserve V3.3 truth semantics:

```text
run_id PK
task_id
parent_task_id nullable
branch_id nullable
idea_id nullable
agent_role_id
lane_id nullable
worker_id nullable
task_class
status
created_at
queued_at nullable
started_at nullable
heartbeat_at nullable
completed_at nullable
killed_at nullable
kill_reason nullable
current_gate_id nullable
current_action
expected_artifact_schema
expected_artifact_id nullable
active_lease_id nullable
priority
retry_count
max_retries
timeout_sec
hibernation_until nullable
why_running
state_version
metadata_json
```

A state transition SHALL use compare-and-set/versioning or equivalent protection against stale writers.

## 36A.4 `gate_decisions`

```text
gate_decision_id PK
strategy_version_id
branch_id
gate_id
gate_version
gate_state_version_before
gate_state_version_after
state_before
state_after
decision
reason_code
decision_reason
actor_id
actor_type
policy_version
evaluator_version_id nullable
evidence_ids
artifact_ids
metrics_json
created_at
supersedes_decision_id nullable
```

A gate decision is append-only; supersession creates a new row. Promotion/state projection MUST enforce a serialized `gate_state_version_before -> gate_state_version_after` chain; conflicting sibling transitions cannot both become authoritative.

## 36A.5 `trial_events`

```text
trial_event_id PK
campaign_id
trial_family_id
strategy_version_id
parent_trial_event_id nullable
trial_type
selection_reason
mechanism_id nullable
parameter_space_hash nullable
dataset_snapshot_ids
metric_ids
started_at
completed_at nullable
scientific_retry_of nullable
infrastructure_retry boolean
contamination_tags
metadata_json
```

Infrastructure-only retry cannot increment raw scientific-trial counters.

## 36A.6 `holdout_query_events`

Minimum fields from Section 15.2 plus:

```text
query_policy_version
request_hash
response_granularity
response_category nullable
privacy_or_query_budget_before nullable
privacy_or_query_budget_after nullable
researcher_exposure boolean
```

The event is durable before a result is exposed.

## 36A.7 `dataset_snapshots`

Minimum fields include Section 13.3 manifest plus:

```text
raw_parent_ids
normalization_code_hash
symbol_master_version
feature_registry_version nullable
availability_cutoff_time
content_hash UNIQUE
quality_status
created_at
```

## 36A.8 `model_inventory`

Minimum fields are the `model_record` contract in Section 28A.1 plus:

```text
created_at
updated_at
validation_due_at nullable
retired_at nullable
replacement_model_id nullable
```

## 36A.9 `paper_orders` and `paper_fills`

`paper_orders` MUST preserve:

```text
paper_order_id PK
client_order_id UNIQUE
paper_run_id
strategy_version_id
instrument_id
venue_id
side
order_type
time_in_force nullable
price nullable
stop_price nullable
quantity
reduce_only nullable
post_only nullable
decision_time
submitted_time nullable
ack_time nullable
final_state
raw_venue_semantics_json
```

`paper_fills` MUST preserve:

```text
paper_fill_id PK
paper_order_id FK
fill_sequence
fill_time
price
quantity
fee_amount
fee_asset nullable
liquidity_flag nullable
execution_model_version
```

Fill uniqueness prevents replay/reconnect duplication.

## 36A.10 `governance_proposals` / `governance_reviews`

Proposal fields include Section 23.2 plus:

```text
proposal_version
classification_source
status
complete_evidence_at nullable
owner_notification_delivered_at nullable
promotion_eligible_at nullable
owner_veto_at nullable
owner_approval_at nullable
promoted_at nullable
rollback_policy_id
```

Review fields include:

```text
council_review_id PK
proposal_id FK
reviewer_role
model_family
model_version nullable
independence_group_id
evidence_manifest_hash
inspected_evidence_ids
verdict
material_objections
confidence_advisory nullable
created_at
```

## 36A.11 `policy_versions`

Every policy record SHALL include:

```text
policy_id
policy_version
content_hash
status
created_at
effective_at nullable
retired_at nullable
governance_proposal_id nullable
safe_bounds_json
rollback_to_version nullable
```

Only one effective version per policy scope may be active unless policy explicitly supports composition.

## 36A.12 Database constraints

Critical tables SHALL use:

- foreign keys or equivalent integrity enforcement;
- unique idempotency keys;
- UTC timestamps;
- explicit status enums/check constraints where practical;
- non-null evidence/provenance fields for promotion paths;
- append-only permissions for audit/event records;
- indexes supporting active-run, lineage, gate, cost, and trial queries.

DB constraints are defense-in-depth; application validation remains required.

---

## 36A.13 `risk_reservations`

Minimum authoritative fields:

```text
risk_reservation_id PK
order_intent_id UNIQUE
strategy_version_id
portfolio_id nullable
venue
account_id
instrument_id
risk_pool_id
status                # RESERVED|PARTIALLY_CONVERTED|CONVERTED|RELEASED|EXPIRED|RECONCILING
risk_policy_version
aggregate_state_version_before
aggregate_state_version_after
reserved_notional
reserved_margin
reserved_delta nullable
reserved_exposure_json
filled_exposure_json
created_at
expires_at nullable
released_at nullable
release_reason nullable
state_version
metadata_json
```

The DB/application transaction that grants a reservation MUST prevent two competing reservations from consuming the same constrained headroom. Implementation MAY use serialized/row-locked accounting, compare-and-set aggregate versions, or another proven atomic design; a read-then-write race is invalid.

Reservation amounts use the canonical Unit/Metric contracts. Unknown/undefined risk required for a hard limit cannot be represented as zero.

## 36A.14 `incident_events` and incident records

Minimum incident record fields:

```text
incident_id PK
severity
status              # OPEN|CONTAINED|RECONCILING|RESOLVED|CLOSED
incident_type
opened_at
contained_at nullable
resolved_at nullable
closed_at nullable
opened_by
owner_notified_at nullable
affected_run_ids
affected_strategy_ids
affected_policy_versions
affected_artifact_ids
containment_actions_json
root_cause_artifact_id nullable
impact_assessment_artifact_id nullable
corrective_action_ids
postmortem_artifact_id nullable
state_version
metadata_json
```

Incident state transitions are serialized and append actor/evidence events. Closing an incident without required reconciliation/impact evidence for its severity is prohibited.

---

## 36A.15 `context_manifests`

Minimum fields:

```text
context_manifest_id PK
inference_request_id FK
compiler_version
retrieval_version
required_evidence_classes[]
candidate_evidence_ids[]
included_evidence_ids[]
tool_addressable_evidence_ids[]
excluded_evidence_json
summary_artifact_ids[]
truncation_json
egress_decision_json
completeness_status
manifest_hash
created_at
```

For MATERIAL/CRITICAL accepted inference, `completeness_status='INCOMPLETE_BLOCKING'` is prohibited.

## 36A.16 `governance_change_sets`

Minimum fields:

```text
change_set_id PK
proposal_ids[]
dependency_versions_json
affected_scopes[]
approval_snapshot_hash
interaction_test_artifact_ids[]
state
created_at
revalidated_at
promoted_at
rollback_set_id
```

Promotion uses compare-and-set on `state` and the current approval/dependency snapshot.

## 36A.17 Service identity provenance

Material actor/event records SHALL preserve an authenticated workload/service principal identifier separately from human/semantic `actor_id`. The persistence layer SHALL derive/verify privileged producer identity from the authenticated channel/token rather than trusting a caller-provided JSON field.


# 37. API requirements

Representative endpoints:

## Operations

- `GET /status`
- `GET /incidents`
- `GET /incidents/{incident_id}`
- `POST /incidents/{incident_id}/contain` (authorized)
- `POST /paper/emergency-stop` (authorized, risk-reducing only)
- `POST /venues/{venue}/emergency-stop` (authorized, risk-reducing only)
- `GET /scheduler/queues`
- `GET /scheduler/why-running`
- `GET /scheduler/why-running/{run_id}`
- `GET /agents/{agent_id}/why-running`

## Inference

- `GET /inference/providers`
- `GET /inference/health`
- `GET /inference/costs`
- `GET /inference/requests/{id}`
- `GET /inference/requests/{id}/context-manifest`

## Research

- `GET /campaigns/{id}`
- `GET /hypotheses/{id}`
- `GET /branches/{id}`
- `GET /strategies/{id}/lineage`
- `GET /experiments/{id}`
- `GET /gates/{strategy_version_id}`

## Trials/statistics

- `GET /trials/{family_id}`
- `GET /statistical-capital/{campaign_id}`
- `GET /holdout/exposure/{campaign_id}`

Raw sealed results MUST NOT be returned through ordinary research APIs.

## Governance

- `GET /governance/proposals`
- `GET /governance/proposals/{id}`
- `GET /governance/change-sets/{id}`
- `POST /governance/proposals/{id}/owner-veto`
- `POST /governance/proposals/{id}/owner-approve` for eligible human actions
- `POST /governance/emergency/pause`

## Paper

- `GET /risk/reservations`
- `GET /risk/reservations/{id}`
- `GET /paper/status`
- `GET /paper/deviation`
- `GET /paper/orders`
- `GET /paper/reconciliation`

No real-order endpoint is exposed in non-LIVE builds. Emergency-stop endpoints are risk-reducing controls and MUST NOT be reusable as a hidden path to create/increase positions.

---

# 38. Telegram requirements

Commands SHOULD include:

- `/status`
- `/active`
- `/why_running`
- `/queues`
- `/inference_cost`
- `/waste`
- `/trials`
- `/statistical_capital`
- `/frontier`
- `/paper_deviation`
- `/governance`
- `/proposal <id>`
- `/veto <id>` where owner role permits
- `/branch <id>`
- `/strategy <id>`
- `/agent <id>`

Simple status commands MUST query deterministic state and SHOULD NOT spend an LLM call.

Owner notifications include:

- RED proposal;
- emergency incident;
- material borderline Frontier allocation;
- major paper/backtest deviation;
- significant provider outage;
- governance auto-promotion countdown for GREEN/eligible AMBER;
- acceptance/rollback result.

---

# 38A. Canonical Metric and Accounting Contract

This section prevents silent mathematical disagreement between modules.

## 38A.1 Metric Registry

Every canonical metric SHALL be registered with:

```json
{
  "metric_id": "...",
  "version": "...",
  "formula_reference": "...",
  "input_series_semantics": "...",
  "units": "...",
  "annualization_rule": "...",
  "missing_data_rule": "...",
  "undefined_conditions": [],
  "numerical_tolerance": "...",
  "golden_fixture_ids": []
}
```

A dashboard/agent cannot invent a local Sharpe/turnover/PnL definition.

## 38A.2 Equity and return convention

Canonical simple portfolio return for period `t` is:

`r_t = V_t / V_(t-1) - 1`

where `V_t` is reconciled marked-to-market equity under the strategy/portfolio accounting contract.

Log returns MAY be used for statistical analysis but MUST be labeled and cannot be mixed silently with simple returns.

If external cash flows ever exist, return calculation SHALL use a cash-flow-aware method and identify the convention.

## 38A.3 Sharpe convention

A canonical naive annualized Sharpe may be defined as:

`SR = mean(r_t - r_f,t) / std(r_t - r_f,t) * sqrt(A)`

where `A` is the number of **non-overlapping comparable return periods per year** under the registered sampling convention.

Important:

- overlapping returns MUST NOT be annualized as if independent;
- serial correlation may require HAC/Lo-style or other dependence-aware inference;
- `r_f` may be zero only when explicitly justified for the horizon/application;
- DSR/PSR uses its own registered statistical implementation and cannot be recreated ad hoc from this display formula.

## 38A.4 Maximum drawdown

For equity `V_t`:

`peak_t = max_{u<=t} V_u`

`DD_t = V_t / peak_t - 1`

`MDD = min_t DD_t`

Reports may display absolute magnitude `-MDD`; the sign convention MUST be explicit.

## 38A.5 Turnover

Turnover MUST specify numerator and denominator. Canonical portfolio notional turnover for a period is:

`turnover = sum_j |executed_notional_j| / average_equity`

when this definition is appropriate.

If a strategy uses a different one-way/two-way convention, it receives a different metric ID. The system MUST NOT compare incompatible turnover definitions.

## 38A.6 Gross and net PnL

Canonical accounting decomposition:

`net_pnl = gross_trading_pnl - fees - financing - funding - borrow - execution_costs - other_explicit_nonoverlapping_costs`

where `execution_costs` MUST be defined to avoid double counting spread/impact/timing already captured in implementation shortfall.

The accounting ledger SHALL separately preserve each component and a reconciliation residual.

## 38A.7 Expected shortfall

When empirical expected shortfall at tail probability `alpha` is used, the registry SHALL define the loss sign and quantile convention. For sufficiently supported samples it is the mean loss conditional on being in the declared worst tail; interpolation/tie behavior is versioned.

Small-sample tail estimates MUST expose uncertainty rather than present false precision.

## 38A.8 Risk of ruin

`risk_of_ruin` is never inferred from one historical drawdown percentage. It is a path-dependent probability under an explicitly versioned stochastic scenario model and starting capital/risk policy.

The report SHALL state scenario assumptions and confidence/Monte Carlo error.

## 38A.9 Metric versioning

Changing a formula creates a new metric version and triggers impacted benchmark/backtest re-evaluation where material. Historical artifacts keep their original metric version.

## 38A.10 Numerical precision

Money/notional/order quantities use integer/fixed-point/Decimal semantics appropriate to the instrument.

Statistical floating-point calculations are allowed, but comparisons near hard thresholds SHALL use declared tolerance and preserve unrounded values. Display rounding never changes a gate.

## 38A.11 Required performance metric families

The Metric Registry SHALL include, where applicable, canonical versions of:

- gross/net return and PnL;
- annualized geometric return/CAGR-like measure for the relevant continuous calendar;
- volatility;
- Sharpe/PSR/DSR outputs;
- downside deviation and Sortino-like measure;
- maximum drawdown and Calmar-like measure;
- hit/win rate;
- average/median trade;
- profit factor;
- turnover;
- gross/net exposure and leverage;
- expected shortfall/CVaR;
- skew/kurtosis/tail diagnostics;
- information ratio where a benchmark series is appropriate;
- capacity/liquidity metrics;
- implementation shortfall/TCA.

Metrics with competing conventions (for example Sortino, Calmar, turnover, profit factor) MUST have explicit versioned formulas and cannot be compared across incompatible versions.

## 38A.12 Multi-currency and collateral valuation

Authoritative ledgers preserve native asset/currency units. Reporting into a common currency is a separate, versioned valuation operation.

The default owner business reporting currency MAY be USD, but assets such as USDT/USDC or other collateral MUST NOT be hardcoded to par with USD.

For every converted equity/PnL value LIKI SHALL record:

- native amount/currency;
- reporting currency;
- conversion instrument/source;
- valuation timestamp;
- bid/mid/mark convention as applicable;
- conversion cost/spread treatment;
- missing/depeg fallback behavior.

A stablecoin depeg therefore appears both as market/collateral risk and as a valuation effect; it cannot be hidden by a `1 stablecoin = 1 USD` accounting constant.

Historical conversion MUST use information/prices available at the relevant valuation time.

## 38A.13 Metric denominator and capital-utilization semantics

Return-on-capital, weekly-income, capacity, and leverage reports SHALL state what capital denominator is used:

- total account equity;
- allocated strategy capital;
- margin posted;
- gross notional;
- risk capital;
- another explicitly registered denominator.

LIKI MUST NOT improve apparent ROI merely by choosing a smaller denominator after observing performance. Denominator policy is predeclared/versioned and changes enter the Trial/Policy history where material.

## 38A.14 Unit, rate, sign, and scale contract

Cross-module naked numbers are dangerous. Every economically material numeric field SHALL have an unambiguous unit/scale contract in its schema or typed value.

The canonical unit registry covers at minimum:

- currency/asset;
- base vs quote quantity;
- price orientation;
- notional;
- percentage as decimal fraction versus percent points versus basis points;
- fee/funding/borrow rate and its accrual period;
- annualized versus per-period rates;
- volatility scale;
- timestamps/durations (`ns|us|ms|s`);
- contract multiplier;
- leverage/margin ratio;
- signed quantity/PnL/cost conventions.

Examples such as `0.01` are invalid across a module boundary unless the contract makes clear whether the value means `1%`, `1 bp`, USD 0.01, or another unit.

Where practical, typed wrappers/dimensional checks SHOULD prevent incompatible units from being combined. Serialization SHALL preserve the unit or use a field whose unit is fixed by the versioned schema.

Rate conversions (for example per-8h funding to annualized display) are registered formulas, not ad hoc multiplications inside agents/dashboards.

## 38A.15 Undefined, NaN, infinity, overflow, and empty-sample semantics

A missing/undefined financial statistic is not zero and is not a pass.

Authoritative metric/gate interfaces SHALL represent exceptional numeric states explicitly, for example:

- `VALUE`;
- `UNDEFINED`;
- `INSUFFICIENT_DATA`;
- `NUMERIC_ERROR`;
- `NOT_APPLICABLE`.

`NaN`, `+/-Inf`, overflow, divide-by-zero, empty samples, or failed convergence MUST NOT silently enter a comparison and accidentally satisfy/fail a gate through language/runtime quirks. They are converted into a declared exceptional state with provenance.

A hard gate requiring a metric cannot `PASS` while that required metric is undefined. Policy decides whether the correct result is `BLOCKED`, `NEEDS_MORE_INFORMATION`, or `NOT_APPLICABLE`; zero-substitution is prohibited unless zero is mathematically the defined value.

Numerical libraries/adapters SHALL have tests for exceptional-state propagation across JSON/DB/Decimal/float boundaries.


---

# 38B. Owner notification and attention management

The owner MUST be informed without becoming the bottleneck.

Notifications SHALL have severities:

- `INFO`: digest only;
- `NOTICE`: notable research/Frontier/governance event, no action required;
- `ACTION`: owner may veto/approve or provide input;
- `CRITICAL`: immediate safety/governance incident.

Repeated equivalent alerts SHALL be deduplicated/aggregated.

Borderline but policy-valid research may continue without owner approval while sending `NOTICE` evidence. Critical governance or future real-money decisions follow their stricter approval rules.

Every notification links to evidence/proposal IDs rather than relying on narrative alone.

---

# 38C. Reference Deployment Baseline

This is a recommended low-complexity baseline for implementation. Equivalent technology is allowed when it preserves contracts.

## 38C.1 Control plane

- Python **3.12+** or the project’s proven compatible Python baseline;
- strict typing where practical;
- Pydantic/JSON Schema or equivalent for wire/artifact schemas;
- FastAPI or equivalent typed HTTP control plane if existing architecture is compatible.

## 38C.2 Primary persistence

- PostgreSQL as authoritative transactional/event/metadata store;
- migrations in source control;
- append-only event tables plus normalized operational tables;
- JSONB only for genuinely extensible payloads, not as an excuse to avoid core relational constraints.

## 38C.3 Queue/workflow baseline

Start with PostgreSQL transactional outbox + durable worker leases if it meets measured throughput/recovery needs.

Do **not** add Kafka, Redis, Temporal, Kubernetes, or another distributed subsystem merely because it is fashionable. Add infrastructure only after benchmarks show the simpler design is a bottleneck or reliability risk.

If a dedicated durable-workflow engine is later adopted, it MUST preserve LIKI idempotency/event semantics and pass replay migration tests.

## 38C.4 Experiment isolation

Container/OS sandbox with reproducible image/lockfile is preferred for untrusted generated research code.

## 38C.5 Observability

OpenTelemetry-compatible traces plus Prometheus-compatible metrics or equivalent are recommended. Structured event/audit data remains canonical for scientific decisions.

## 38C.6 Source control and CI

Every accepted code/policy/evaluator version SHALL map to a source-control commit/tag or immutable artifact digest.

CI MUST run requirement-index generation, schema validation, unit/property tests, and critical invariants before merge/promotion.

This baseline intentionally avoids unnecessary distributed complexity while keeping a migration path to larger infrastructure.

---

# 39. Implementation order

The implementation agent SHALL not attempt the entire system as one unverified patch.

## 39.0 SRS Execution Compiler and coverage matrix

Because this SRS is intentionally large, implementation SHALL NOT depend on one coding agent remembering the entire Markdown document from conversational context.

Before implementation, a deterministic/spec-processing step SHALL build a machine-readable coverage graph from `requirements_registry.yml`:

`requirement -> owning module(s) -> implementation phase -> dependency requirements -> test(s) -> acceptance evidence`.

Each coding task receives:

- the exact relevant requirement texts/IDs;
- Constitution and cross-cutting invariants that apply globally;
- dependency/interface contracts;
- required tests/acceptance criteria;
- links to canonical full SRS sections.

A lossy LLM summary is not authoritative specification. The original requirement text/ID remains available to the coding/verifying agent.

Before a phase can be `ACCEPTED`, CI SHALL prove that every active requirement assigned to the phase is implemented/test-linked or has an explicit approved blocker/deferral that does not violate acceptance.

Cross-cutting requirements (security, units, provenance, idempotency, traceability, real-money disable, statistical contamination) SHALL be tagged so they cannot disappear merely because a task was scoped to one local module.

At final acceptance, the coverage matrix MUST have zero orphan CRITICAL requirements and zero implementation artifacts with no traceable owning requirement/design decision for material behavior.

## Phase 0 — Baseline and preservation
- map current LIKI V3.3 components;
- run existing tests;
- capture baseline metrics;
- identify migration paths.

## Phase 1 — Constitution, schemas, event store
- create canonical contracts;
- implement immutable events;
- implement version IDs and hashes.

## Phase 2 — Inference Broker
- provider registry;
- leases/cost;
- fixed-call + token-metered pricing;
- retries/fallback/circuit breakers;
- idempotency;
- quality routing.

## Phase 3 — Adaptive Research Fabric
- dynamic lanes;
- queue;
- work ladder;
- exploration reserve;
- shadow allocator.

## Phase 4 — Memory + lineage + trial ledger
- evidence graph;
- retrieval firewall;
- contamination;
- adaptive trials/statistical capital.

## Phase 5 — Data hardening
- manifests;
- point-in-time checks;
- multi-resolution data;
- provider reconciliation.

## Phase 6 — Backtest/economics
- dual accounting;
- full cost engine;
- fills/capacity/latency;
- deterministic fixtures.

## Phase 7 — Gates/statistics
- G0–G10;
- DSR/PBO/RC/SPA support as appropriate;
- sensitivity/robustness;
- Frontier.

## Phase 8 — Sealed + forward/paper
- guard/sealed access;
- G11;
- paper simulator/telemetry;
- G12–G13.

## Phase 9 — Governance/self-improvement
- blind council;
- historical replay;
- LIKISim;
- shadow/canary/rollback;
- 24h no-veto timers by class.

## Phase 10 — UI/Telegram truth
- evidence-backed projections;
- deterministic status paths.

## Phase 11 — Model risk, portfolio, sandbox, and reliability hardening
- model inventory and independent validation;
- portfolio allocator/risk aggregation;
- crypto derivatives/venue conformance;
- ContextCompiler and inference economics/batching;
- generated-code sandbox;
- transactional outbox/worker recovery/backups;
- Metric Registry and golden accounting fixtures.

## Phase 12 — Full QA
- property/differential/mutation;
- replay;
- chaos;
- acceptance campaign.

No phase may be declared complete solely because code compiles.

---

# 40. Coding-agent operating rules

An implementation agent working from this SRS MUST:

1. inspect existing code before rewriting;
2. preserve verified working behavior unless this SRS explicitly supersedes it;
3. make migrations backward-aware;
4. create tests before or alongside critical financial logic;
5. never silently simplify a requirement;
6. never replace deterministic financial logic with LLM judgment;
7. never hardcode an unexplained threshold;
8. never treat a placeholder simulation as production evidence;
9. use idempotency for all external/side-effect actions;
10. keep complete implementation reports with exact files and tests;
11. run focused tests after each block;
12. run integration tests after each interface change;
13. run differential accounting tests before accepting backtest changes;
14. run statistical synthetic tests before accepting G8 changes;
15. run fault injection before accepting inference fallback;
16. run governance isolation tests before accepting Council;
17. prove real-money paths remain disabled.
18. generate and maintain the normative requirements index;
19. never implement a canonical metric without Metric Registry entry and golden fixture;
20. never claim provider fallbacks are independent without a failure-domain basis;
21. never use summed standalone strategy equity curves as the authoritative portfolio simulation;
22. sandbox generated/research code before executing it;
23. record every material model in the Model Risk Inventory;
24. verify backup/restore and migration behavior before acceptance.

If the coding agent discovers a conflict or missing requirement affecting correctness, it MUST create a structured `spec_issue` rather than guess.

---

# 41. System-wide quality bars

A module is not "done" when its happy path works.

It is done only when:

- state transitions are explicit;
- errors are classified;
- retry behavior is bounded;
- idempotency is tested;
- metrics exist;
- audit exists;
- configuration is versioned;
- security is defined;
- tests cover normal and adversarial paths;
- rollback exists where stateful;
- documentation matches behavior.

For financial calculations, numerical examples/golden fixtures MUST accompany implementation.

For statistical methods, assumptions and test applicability MUST be encoded/documented.

For LLM paths, artifact schema and downstream verification MUST exist.

---

# 42. Research-office benchmarks

LIKI SHALL maintain a benchmark suite independent from strategy PnL.

## 42.1 Inference benchmark
Synthetic task classes with known expected outputs to compare:

- deterministic;
- cheap LLM;
- Opus effort levels;
- provider routes.

Measure cost/latency/correctness.

## 42.2 Research benchmark
Historical campaigns replayed with frozen data and known discoveries/failures.

Measure:

- discovery yield;
- false kills;
- preventable waste;
- cost;
- time.

## 42.3 Statistical benchmark
Null and known-signal synthetic families to detect:

- false positives under many trials;
- false negatives;
- adaptive holdout leakage;
- dependence failures.

## 42.4 Execution benchmark
Golden microstructure scenarios with exact expected:

- fill;
- fee;
- funding;
- partial fill;
- rejection;
- rounding;
- PnL.

## 42.5 Governance benchmark
Known good/bad policy changes replayed through Council.

Measure:

- regression detection;
- false rejection of improvements;
- anchoring contamination;
- rollback.

LIKI may optimize itself against these benchmarks only if a separate sealed system-evolution benchmark remains untouched.

---

# 43. Reference algorithms and research basis

These references inform the SRS but do not become unquestionable implementation rules.

1. **Dwork, Feldman, Hardt, Pitassi, Reingold, Roth (2015)** — *The reusable holdout: Preserving validity in adaptive data analysis*. Science. DOI: https://doi.org/10.1126/science.aaa9375  
   Use: adaptive holdout/reuse concepts; motivates guard-holdout protection.

2. **Dwork et al. (2015)** — *Generalization in Adaptive Data Analysis and Holdout Reuse*. NeurIPS. https://arxiv.org/abs/1506.02629  
   Use: Thresholdout and adaptive-data-analysis theory.

3. **Bailey, Borwein, López de Prado, Zhu** — *The Probability of Backtest Overfitting*. SSRN: https://ssrn.com/abstract=2326253  
   Use: PBO/CSCV and explicit backtest-overfitting risk.

4. **Bailey & López de Prado** — *The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality*. SSRN: https://ssrn.com/abstract=2460551  
   Use: selection/non-normality-aware Sharpe inference.

5. **White (2000)** — *A Reality Check for Data Snooping*. Econometrica. DOI: https://doi.org/10.1111/1468-0262.00152  
   Use: model-selection/data-snooping-aware performance comparison.

6. **Hansen (2005)** — *A Test for Superior Predictive Ability*. Journal of Business & Economic Statistics. DOI: https://doi.org/10.1198/073500105000000063  
   Use: SPA testing as an alternative/complement to Reality Check.

7. **LIKI V3.3 — Operational Governance Hardening Spec**  
   Use: token/governance foundations, truthful scheduler state, active-task registry, actor→artifact→gate causality, waste telemetry, prescreen/cooldowns, controlled parallelism, paper-vs-backtest telemetry, security policy, and acceptance philosophy.

---

## Additional hardening references


8. **Board of Governors of the Federal Reserve System / OCC / FDIC (2026)** — *Revised Guidance on Model Risk Management (SR 26-2, April 17, 2026).*  
   https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm  
   Use: risk-based model lifecycle, effective challenge, validation, ongoing monitoring, model inventory, third-party oversight, aggregate dependencies. LIKI applies these as engineering principles; the guidance does not specifically govern LIKI.

9. **Kontorovich, Sadigurschi, Stemmer (2022)** — *Adaptive Data Analysis with Correlated Observations*, ICML/PMLR 162.  
   https://proceedings.mlr.press/v162/kontorovich22a.html  
   Use: explicit warning that classic adaptive-data guarantees are substantially more delicate under correlated/non-IID observations, directly relevant to financial time series.

10. **Binance Developer Documentation (runtime-current venue example, not a universal contract)** — exchange filters, sequence-based local order-book reconstruction, derivatives reference/margin/forced-order metadata.  
    https://developers.binance.com/  
    Use: demonstrates why venue adapters need live instrument filters, sequence semantics, server-time requirements, mark/index/liquidation metadata instead of generic hardcoded exchange assumptions.

11. **Bailey & López de Prado (2012/2013)** — *The Sharpe Ratio Efficient Frontier*.  
    https://ssrn.com/abstract=1821643  
    Use: Probabilistic Sharpe / track-record uncertainty concepts.

12. **SEC — Rule 15c3-5 / Market Access risk-management controls.**  
    https://www.sec.gov/rules-regulations/2011/06/risk-management-controls-brokers-or-dealers-market-access  
    Use: engineering precedent for deterministic pre-trade controls that prevent erroneous/excess orders before market entry and for controlled market-access authorization. Applicability to LIKI depends on future jurisdiction/structure; the SRS uses the control principle, not a claim that the rule currently applies.

13. **FINRA — Algorithmic Trading / High Frequency Trading examination materials.**  
    https://www.finra.org/rules-guidance/key-topics/algorithmic-trading  
    Use: operational precedent for algorithm development/testing, monitoring, shutoffs/kill switches, and controls against aberrant/duplicative/self-referencing order activity.

14. **Binance Developer Documentation — Spot account/order semantics, STP, filters, rate limits, and derivatives market/user streams.**  
    https://developers.binance.com/  
    Use: demonstrates that production venue adapters need venue-native STP modes, order filters, time/rate-limit semantics, user-stream/order states, and derivative forced-event/reference-price behavior rather than generic hardcoded assumptions.

15. **Bailey, Borwein & López de Prado (2016)** — *Stock Portfolio Design and Backtest Overfitting*. SSRN: https://ssrn.com/abstract=2739335  
    Use: demonstrates that portfolio construction/weight selection can itself be backtest-overfit; motivates portfolio-level lineage, multiplicity, and simple challengers.

16. **NIST AI 600-1 — Generative AI Profile (2024; updated 2026)** — https://doi.org/10.6028/NIST.AI.600-1  
    Use: additional engineering basis for lifecycle risk identification, evaluation, provenance, monitoring, and controls around generative-AI components. It is informative rather than a claim of regulatory applicability.

17. **Binance Developer Documentation — current public depth/user-data semantics.** https://developers.binance.com/  
    Use: current public depth payloads expose price-level quantities rather than authenticated individual-order queue identity, while user streams distinguish ordered account/order events and forced-order states. This supports explicit execution-data-fidelity limits instead of pretending all L2 data is queue-level evidence.

The Reference section is informative. Where a paper’s assumptions do not match the current data-generating process, LIKI does not force the method to apply.

---

# 43A. Completeness Audit and Intentionally Dynamic Variables

This section records what is deliberately fixed, what is deliberately adaptive, and what remains unknowable until real deployment evidence exists. These are not omissions.

## 43A.1 Fixed architectural decisions

The following are non-optional unless changed through appropriate Governance:

- real-money execution disabled at issuance;
- constitutional safety and evidence rules;
- no self-certification;
- deterministic financial/accounting/risk enforcement;
- immutable lineage/trial/holdout exposure records;
- sealed-evidence access control;
- adaptive multiple-testing accounting;
- realistic cost/execution evaluation;
- independent reproduction before strong promotion;
- dynamic research lanes with exploration protection;
- fixed-call + token-metered inference routing with fallback;
- provider failure domains/circuit breakers/idempotency;
- truthful active-task state;
- model inventory/validation/monitoring;
- portfolio-level synchronized risk evaluation;
- generated-code sandboxing;
- governance replay/shadow/canary/rollback;
- system-evolution trial/statistical-capital accounting;
- Metric Registry + dual critical accounting;
- 24-hour no-veto only for eligible GREEN/AMBER changes after confirmed delivery;
- RED and real-money changes require explicit owner approval.

## 43A.2 Deliberately adaptive values

These MUST NOT be hardcoded as universal truths:

- number of active lanes/agents;
- exploitation/exploration mix within allowed policy ranges;
- max provider concurrency;
- model reasoning effort by task class;
- semantic batch size;
- provider routing order and prices;
- branch/campaign inference budget;
- Frontier allocation within policy range;
- Rejection Audit sampling rate within policy range;
- many gate thresholds conditional on strategy/evidence class;
- slippage/impact distributions;
- capacity estimates;
- regime definitions;
- model monitoring thresholds.

They are calibrated from shadow/replay/forward evidence and versioned.

## 43A.3 Values intentionally not specified yet

The SRS refuses false precision for values that depend on information not yet supplied or observed:

- future live capital amount;
- live per-strategy/portfolio risk limits;
- live leverage limits stricter than venue constraints;
- exact minimum paper calendar duration for every strategy type;
- exact position sizes;
- exact exchange/venue set beyond Phase-1 scope;
- exact daily USD research budget;
- exact provider keys/endpoints;
- universal Sharpe/PBO/DSR pass thresholds across all strategy classes.

Before future LIVE enablement, these become a separate owner-approved Risk & Execution Policy with empirical calibration.

## 43A.3A V3.3 numeric migration map

The earlier V3.3 spec contained useful conservative boot values. This revision explicitly classifies them so an implementation agent does not accidentally lose or over-harden them.

| V3.3 value | v1.1 status |
|---|---|
| Codex per-process concurrency = 1 | **Preserved boot hardening rule** until timeout storm is proven resolved |
| Autonomous lanes = 3 initially, 4 if stable | **Preserved boot profile**, then Adaptive Research Fabric controls |
| cheap: 45s / max_parallel 8 | **Boot default**, task-class policy may calibrate |
| medium: 180s / max_parallel 4 | **Boot default**, calibratable |
| expensive: 600s / max_parallel 2 | **Boot default**, prescreen required; calibratable |
| Telegram LLM: 45s / parallel 1 | **Boot default**; deterministic status preferred |
| evaluator: 60s / parallel 8 | **Boot default**; deterministic only |
| backtest: 900s / parallel 3 | **Boot default**; prescreen required |
| data: 240s / parallel 4 | **Boot default**, provider-rate-limit constrained |
| max running LLM leases 4 / Codex 3 / Kiro 1 | **Boot compatibility caps only**; superseded by per-route/task adaptive limits after shadow proof |
| 50M estimated tokens/day; 5M/hour | **Superseded** by owner-configurable USD+calls+tokens+compute budgets; MUST NOT be silently reintroduced as universal limits |
| unknown-usage calls <= 20/hour | **Preserved safety boot cap** when cost/usage is genuinely unknown; preferred behavior is to make cost measurable |
| soft/medium/hard cooldown 6h/24h/72h | **Preserved boot durations** under Section 24.5 |
| legacy cooldown penalties 15/35/100 | **Semantic intent preserved, scalar weights retired** by constrained/Pareto allocator |
| exploration 5–10% | **Preserved/expanded**: normal policy floor/ranges in Sections 9 and 16 |
| stale heartbeat `> max(30s, 20% timeout)` | **Preserved boot projection rule** in Section 29.5 |
| 24-hour guarded acceptance run | **Preserved** as mandatory final soak/guarded acceptance below |

Changing a boot default after calibration requires a versioned policy and measured regression evidence.

## 43A.4 What the current SRS is strong enough to hand to an implementation agent

The SRS now provides explicit contracts for:

- objective hierarchy;
- agent roles and task contracts;
- inference economics/fallback/provider-identity assurance and router calibration;
- tool routing/context construction;
- dynamic lanes and research budgets;
- memory/contamination;
- trial lineage and statistical capital;
- data/feature/ML lifecycle and historical instrument-specification lineage;
- G0–G13 research funnel;
- gray-zone and rejected-branch auditing;
- backtest/accounting;
- execution/crypto semantics;
- portfolio/risk;
- model-risk lifecycle;
- self-improvement/Governance Council;
- security/sandboxing plus data-classification/LLM-egress controls;
- persistence/API/Telegram;
- durable workflows/disaster recovery;
- QA/acceptance/benchmarks;
- canonical metrics, multi-currency valuation, and denominator semantics;
- canonical units/rates/sign conventions and exceptional-numeric semantics;
- persistent non-renumbering requirement traceability;
- context completeness/evidence-omission defense for critical LLM decisions;
- random-seed/nuisance/campaign-level selection accounting;
- market-data fidelity tiers that bound execution/queue claims;
- portfolio/ensemble-level multiplicity and later confirmation;
- governance interaction/stale-approval controls;
- authenticated workload identity for material provenance;
- explicit adversary/trust-boundary security model with blast-radius containment;
- bounded task-DAG/fan-out/deadlock semantics for agentic decomposition;
- temporal transportability/structural-break evidence semantics;
- synthetic market evidence ceilings;
- independent-reference common-mode controls;
- deterministic SRS requirement-to-implementation coverage compilation;
- pinned evaluation snapshots and crash/disaster recovery semantics;
- adversarial poisoned-corpus acceptance.

## 43A.5 Remaining epistemic limitation

Even a correctly implemented LIKI cannot guarantee that a future market edge exists or persists. The strongest achievable design goal is to make false confidence, hidden overfit, silent accounting error, unrealistic execution, and wasted research progressively harder and more expensive than honest rejection.

---

# 44. Final authoritative interpretation

LIKI is a **continuously operating, self-improving, evidence-governed quantitative research office**.

Its competitive advantage does not come from simply spending more model calls.

It comes from:

- asking higher-value questions;
- killing provably bad work earlier;
- preserving weird but plausible opportunities through bounded exploration;
- charging adaptive research for statistical-data reuse;
- preventing duplicate experiments;
- using Opus where reasoning has real value;
- using deterministic systems where correctness is computable;
- routing around unreliable APIs without stopping;
- reproducing and attacking its own findings;
- modeling the economics that destroy beautiful backtests;
- separating generation, verification, risk, accounting, and governance;
- learning from every branch and every failure;
- evolving its own process without being allowed to secretly lower its standards;
- treating every claimed edge as guilty of overfitting until evidence survives progressively stronger tests.

The intended result is not a system that says "this strategy is profitable with certainty."

The intended result is a system that can truthfully say:

> This candidate survived a recorded search history, realistic net economics, adaptive multiple-testing controls, independent reproduction, sealed validation, forward execution evidence, portfolio-risk analysis, and a complete auditable chain of decisions; the remaining uncertainty is measured, explicit, and acceptable for the next bounded stage.

That standard applies to every candidate, every agent, every gate, and every future version of LIKI.
