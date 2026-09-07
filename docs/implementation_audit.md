# Implementation audit — 2026-09-07

## Starting point

The clean starting checkout and fetched `origin/main` both identify
`c66949bfa54e368431403056558c10e57717678f`. The attached SRS, root SRS, and
`docs/LIKI_SRS.md` are byte-identical, SHA-256
`03a871ac73ed2515a86cc6a3a7329a6e43e0366d0dba3f68a9dde9c76b79748a`.
No previous work was replaced or reimplemented wholesale.

Baseline execution: `uv run pytest -q`: **186 passed**, two third-party
deprecation warnings, 299.06 seconds. `uv run ruff check .`: passed.
`uv run mypy liki`: nine errors in `paper_service.py`, involving unguarded
nullable projections and incorrectly typed connection/identity arguments.
The old README's claim that the latest checkpoint had not been retested was
therefore obsolete. A passing baseline suite does not close additional SRS IDs.

Starting registry: **540 requirements; 35 VERIFIED, 3 IN_PROGRESS, 502
NOT_STARTED, zero ACCEPTED**. The previous VERIFIED evidence was largely
function-level, not system acceptance. `NOT_STARTED` often means untraced,
not absent source code. Preserve these distinctions.

## Inventory and integration boundaries

This table records the starting baseline; subsequent checkpoints below supersede
only the specific boundaries they verify.

| Area | What exists and is tested | What is partial, disconnected, or missing |
|---|---|---|
| Core persistence | Authenticated PostgreSQL transactions, RLS, immutable artifacts/event chain, revision checks, migration drift checks | Whole-system aggregate coverage and independent operational acceptance remain unclosed |
| Research/scheduler | Campaign/task budgets, task dependencies and leases, research objects, trial history, sealed exposure records | No complete continuously operating research office; service methods alone are not running workers |
| Gates | Signed G0 execution and isolated G1–G4 checks at baseline | G1–G4 lacked runtime acceptance; G5–G13 explicitly unsupported by the signed runner |
| Data | Raw/manifest persistence, timing/gap controls, instrument/lifecycle adapters and tests | Authentic external acquisition/reconciliation, complete input-coverage proof, poisoned-source resistance remain unaccepted |
| Finance/statistics | Decimal accounting, reference reconciliation, cost/execution and statistical primitives, focused fixtures | Backtest/statistical outputs are not yet admitted by signed G5–G13 production executions; no financial promotion from library tests |
| Paper/portfolio | Persistent paper state, safety latches, reservations, portfolio calculations/readiness objects | Full gate admission, account-observed calibration, venue lifecycle fidelity and forward acceptance remain incomplete |
| Inference | Routing, budgets, context, provider transports and durable broker services | Controlled transports are not evidence of real provider billing or operational resilience; complete agent workflows remain disconnected |
| Governance/model risk | Persisted proposals, reviews, freezes, model records and SLO/incident services | Full evidence provenance, interaction corpus and operational acceptance remain unclosed |
| Operator/notifications | Authenticated HTTP reads, dashboard, emergency stops, Telegram webhook/outbox/delivery methods | A delivery method is not a managed delivery worker; notification severities/digests and external receipt acceptance remain incomplete |
| Reliability/DR | Encrypted backup/recovery primitives, incident/SLO tests | Mandatory real 24-hour guarded soak and comprehensive adversarial acceptance are missing |
| Traceability | Persistent IDs and coverage compiler | Original validation accepted arbitrary evidence prose and did not verify referenced test symbols or executed evidence content |

## Priority and slice boundary

1. Finish a credential-scoped persisted early-screen campaign before adding
   downstream gate implementations. Prove normal and empirical paths, signed
   revision binding, blocked recovery, fatal-cost rejection, concurrency,
   replay, and operator/audit visibility.
2. Make requirement closure evidence mechanically inspectable, not a claim
   made by editing a status field. Do not renumber or replace existing IDs.
3. Integrate deterministic G5/G6 execution using existing independent finance
   implementations and immutable provenance before extending G7/G8.

The early-screen work must not claim full G2 data validity or full G4 economic
acceptance. Timing-row completeness, authoritative family classification,
authentic observed-economics provenance, parameter neighborhoods, turnover,
statistical proxy, implementation feasibility and false-negative accounting
still require additional integrated evidence. A fixture may prove a control;
it cannot prove market edge or real-world capacity.

## External acceptance boundaries

The previous checkpoint documented Binance HTTP 451 and absent LLM/Telegram
credentials. Those are historical findings, not newly measured service health.
This audit uses isolated test databases and no external provider calls.
They do not excuse unfinished adapters, integration or local acceptance work.
The 24-hour soak cannot be replaced by accelerated clocks or a short test.

## Paper defect checkpoint

The inherited paper-service type failures are repaired without claiming new
SRS acceptance. Missing run/reservation projections now fail closed and roll
back the whole financial transaction. Unsupported derivative, multiplier and
cross-currency contracts cannot enter the spot-only paper ledger. Verification:
`uv run ruff check .`, `uv run mypy liki` (62 source files), and
`uv run pytest -q tests/test_paper_projection_integrity.py tests/test_paper_service.py`
all passed; **19 tests, 37.17 seconds**. Projection-loss tests use restrictive
database policies rather than mocked financial services. Requirement counts
remain unchanged.

## G5 integration and traceability repair

The signed runner now executes `spot-quote-protocol-v1` through the real CLI and
database boundary. It resolves exact dataset-event raw artifacts, validates
normalized/schema hashes and timing, executes a candidate-bound lagged program
and simple benchmark, and persists financial histories and a signed package.
`docs/backtest_protocol.md` defines supported scope and explicit exclusions.

The first G0–G5 process/database/API run passed **7 tests in 262.13 seconds**.
Independent adversarial review then exposed sell-side financing, executable
price-band and normalized-quantity defects; all were repaired. The independent
regressions initially produced seven failures and subsequently passed. The
final focused financial/traceability run passed **85 tests in 1.13 seconds**;
repository Ruff and all 63 source modules' Mypy checks passed.
The final complete suite passed **300 tests in 658.39 seconds**, with two
pre-existing dependency deprecation warnings and no failures or skips.

Review also found eight explicit list contracts omitted by the uppercase-only
requirement extractor, including G5 and the section 17.2 output package. The
compiler now includes explicit `Requirements`, `Must ...`, and `Every/Each ...
includes/contains/declares` list introductions. All prior 540 IDs were preserved;
the registry now contains **548** requirements. Added requirements are not
silently accepted. Neither the SRS nor its source hash changed.

The current source-bound whole-checkpoint manifest and exact accepted counts
are recorded in `docs/acceptance_traceability.md`. Existing early-gate evidence
must be renewed after the verifier changes; old immutable manifests remain
historical artifacts, not current-source proof. Full G6 cost/latency/capacity
stress is the next dependency, not a parallel unfinished branch of G5.

## G6 execution-economics checkpoint

The signed runtime now binds the applied G5 decision and immutable package to
persisted execution depth, effective venue/fee/account state, latency samples,
disjoint impact calibration/validation observations and a trusted policy.
The supported fixed-intent spot IOC protocol emits reconciled ledgers,
component costs, implementation shortfall and size/latency/depth/impact capacity
curves. Unknown material inputs block; known friction can produce an audited
FAIL. Public snapshots carry limited model confidence, not observed-fill claims.
Unsupported derivative, passive and cross-currency paths remain explicit.

Independent depth, fee and latency reference calculations plus FIFO accounting
were checked with golden fixtures and corruption injection. Adversarial review
exposed terminal-loss masking by delayed feeds, retroactive in-flight rejects,
submission-rate ordering errors and G5/G6 currency/asset mismatches. These were
fixed before acceptance. A nearby inverse-contract notional unit defect was
also corrected and regression-tested without claiming broader derivative
acceptance.

Focused financial/reference/adversarial verification passed 180 tests. The
first full run passed 493 tests and failed two stale runtime assertions that
expected unsupported G6 rather than its now-valid unsatisfied G5 dependency.
The corrected assertions also retain unsupported-G7 coverage; no financial
assertion was weakened. No evidence manifest was written from the failing run.
The complete corrected run passed **495 tests in 1449.50 seconds**, no failures
or skips, with two pre-existing dependency deprecation warnings. Ruff and Mypy
over 67 source modules passed.

`docs/acceptance/g6-economics-2026-09-07.json` binds all fourteen accepted IDs to
44 exact source/test/config hashes and the unchanged SRS hash. The registry is
**548 total: 14 ACCEPTED, 33 VERIFIED, 3 IN_PROGRESS, 498 NOT_STARTED**. G6 adds
one accepted protocol requirement and promotes two previously verified
accounting controls. Thus 47/548 (8.58%) have verification or acceptance
evidence; only 14/548 (2.55%) are accepted. This is not system acceptance.
Signed predeclared G7 OOS/walk-forward validation is the next connected slice.
