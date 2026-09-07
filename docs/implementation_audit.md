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
