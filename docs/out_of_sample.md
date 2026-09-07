# Signed G7 out-of-sample validation

`chronological-fixed-program-v1` evaluates the frozen G5 program and simple
benchmark on prospectively declared observations, with the unchanged G6 cost
policy and latency assumptions. An applied, signed G6 PASS is required. G7
creates additional evidence; it never changes G5 or G6 packages or decisions.
PASS means `OOS_VALIDATED`, not statistical significance, paper admission or
permission for real-money execution.

## Supported protocol

The current signed protocol is chronological, single-venue, fully funded,
long-only spot with market IOC execution. It performs **no fitting or model
selection**. It starts with the same cash, a flat position and cold signal
history; no development profit or position enters validation. The entire
predeclared observation grid is scored, including signal warmup. Every G6
size/latency/impact/adverse-depth scenario is retained; the worst intended-size
net return, benchmark excess and fill ratio use the original G6 thresholds.
No favorable scenario or successful slice can be selected after inspection.

This is not rolling retraining, nested hyperparameter selection, cross-sectional
validation, G8 inference or G11 sealed evaluation. Those remain separate work.
The G6 public-depth fidelity and conditional-scenario limitations still apply.

## Prospective declaration and persistence

Use the existing credential-scoped `liki.research_runtime` actions:

1. Persist the candidate, G5 plan, G6 economics policy and development execution
   dataset. Choose future quote and execution `dataset_snapshot_id` values.
2. Persist `research/oos-declaration-v1` before any validation observations.
   Its `OOSDeclaration` contract binds the candidate, evaluation snapshot, code,
   trial/family, future dataset identities, exact first timestamp, observation
   interval and number of observations. It pins SHA-256 content hashes of:
   - the G5 `BacktestPlan.model_dump(mode="json")` configuration;
   - the G6 `EconomicsPolicy.model_dump(mode="json")` policy;
   - the normalized development `ExecutionTape.model_dump(mode="json")`.
   Use `liki.core.content_hash` for these canonical hashes, not hashes of
   unnormalized input JSON. The development tape must already be persisted.
3. Record a non-infrastructure `window` trial with that declaration's exact
   `trial_event_id`, family and future dataset IDs. Its semantic configuration
   is `{"g7_declaration_hash": "<declaration artifact content_hash>"}` and its
   ordered metric IDs are `net-return`, `benchmark-excess`, `minimum-fill-ratio`.
   Scientific attempts consume the conservative raw campaign trial budget even
   if later abandoned. Changing the declaration requires a new scientific trial.
4. Only after declaration and trial registration, acquire and persist the
   future quote and execution tapes through the data-role `dataset` action.
   The quote grid must match the declared schedule exactly. Execution depth
   has that same grid plus one preceding observation, also after registration.
   The execution tape's existing `g5_dataset_artifact_id` field identifies the
   **OOS quote dataset used to generate intents**, not the historical G5 data.
5. Persist `research/oos-plan-v1` with `declaration_artifact_id`,
   `quote_dataset_artifact_id` and `execution_dataset_artifact_id`. Include these
   and the declaration in snapshot `gate_input_artifact_ids["7"]`; set
   `statistical_method_versions["oos"]` to `chronological-fixed-program-v1`.
   Pin the snapshot only after the final observations are actually available.
6. Execute and apply G0–G6 normally, then `verify` and `decide` G7.

The signed verifier checks raw and normalized hashes, raw provider and retrieval
time, exact dataset persistence-event references, source availability, venue,
instrument, currency, depth/BBO consistency, fidelity and prospective timing.
Previously persisted identical raw bytes cannot be relabelled fresh validation.
Missing intervals, repairs, revisions, future availability, changed latency,
synthetic liquidity and unknown material costs block rather than defaulting.
Software validation does not authenticate a provider's economic truth; test-only
fixtures are not evidence of real market edge, observed fills or live capacity.

## Horizons, exposure and trial accounting

The declared event horizon cannot be shorter than the candidate's research
contract horizon. All development events must end before validation, followed
by an embargo at least as long as that horizon. Validation must cover at least
one horizon. The fixed program is never fitted on either side of the split;
this conservative separation therefore excludes all overlapping development
events instead of choosing a fitted training subset.

The split library separately supports closed event intervals `[i, end_i]`.
Purged K-fold and CPCV remove training intervals intersecting **any part** of a
test event, including its extended label horizon. Each selected contiguous
group's maximum event end starts its embargo. Test and embargo index sets are
disjoint; valid gaps between disjoint test-event intervals remain eligible.
Invalid/nonintegral indices, empty groups, zero step and more than 10,000 CPCV
combinations fail explicitly. These primitives do not themselves grant G7 PASS.

The report includes snapshot-bound campaign and cross-campaign family trial
history, raw counts, remaining campaign budget and immutable event hashes.
No caller-supplied effective trial count is accepted. Effective multiplicity
remains `NOT_ESTIMATED` until a justified G8 method is integrated. Signed G7
executions are the durable exposure ledger, including blocked and failed
attempts; their evidence role is `VALIDATION` with `saw_g7_result` contamination.
Later trials on the candidate, its descendants or the same trial family inherit
that tag automatically, even across campaigns.
An exact execution retry is not a new scientific trial, and replay preserves
the trial-history cutoff at the original snapshot.

## Failure semantics and operator reads

Missing/invalid provenance, insufficient history, undeclared tuning or exhausted
trial budget produces signed `BLOCKED` evidence. Known economic losses or
insufficient executable capacity produce a signed `FAIL`, not a missing-data
excuse. Unsigned reports and caller-invented metrics cannot grant promotion.

`GET /out-of-sample/{strategy_version_id}` returns the latest signed report,
immutable package, gate decision and audit linkage through the existing
authenticated operator read model. It includes the full intent-generation and
execution-economics ledgers, split rationale, trial provenance and source hashes.

Verification lives in `tests/test_oos_gate.py`, `tests/test_oos_runtime.py` and
`tests/statistics/test_validation_adversarial.py`. Golden calculations and
independent interval-set oracles complement real CLI process restarts,
PostgreSQL transactions, signatures, HTTP reads and fail-closed source tests.
