# Acceptance traceability — 2026-09-07

**Authority:** attached `LIKI_SRS.md` v1.4 (byte-identical to the repository
copies) and `requirements_registry.json`. This is not system acceptance.

## Current requirement matrix

| Status | Count | Meaning |
|---|---:|---|
| ACCEPTED | 18 | Eight early-gate, three G5, three G6/accounting and four G7/temporal controls, closed by executed source-bound evidence |
| VERIFIED | 32 | Other earlier focused verification; not silently upgraded to acceptance |
| IN_PROGRESS | 3 | Existing Telegram status, owner notification and alert-deduplication integrations |
| NOT_STARTED | 495 | No completed atomic traceability claim; related code may exist |
| Total | 548 | Existing IDs preserved; eight omitted explicit SRS list contracts recovered |

**50/548 (9.12%) have verification or acceptance evidence. Only 18/548 (3.28%)
are ACCEPTED.** These figures are not whole-system production readiness.

Before the G5 checkpoint, the matrix reported 43/540 (7.96%) with verification or acceptance
evidence and 8/540 (1.48%) ACCEPTED. Review found that the uppercase-only
extractor omitted eight explicit requirement/output checklists, including G5
and section 17.2. The compiler now retains these declarative list contracts.
No SRS text, source hash, existing requirement ID or prior evidence was erased.
The denominator correction is not eight newly requested product features.
G6 keeps the denominator unchanged at 548; its preceding G5 checkpoint had
11 ACCEPTED and 35 additional VERIFIED entries.
G7 also keeps 548: it accepts three previously unclosed requirements and promotes
one previously VERIFIED temporal-overlap control. Its preceding G6 checkpoint
had 14 ACCEPTED and 33 additional VERIFIED entries.

## Closed integrated controls

The early-screen runtime supports authenticated campaign/artifact submission,
raw dataset persistence, research/trial registration, predeclared snapshots,
signed G0–G4 execution, serialized decisions, blocked re-entry and operator reads.
Its eight accepted IDs cover structured feasibility, empirical versus mechanism
basis, fatal economics, evidence-versioned transitions, BLOCKED versus FAIL,
separate outcome counts, append-only decisions and competing-sibling rejection.

G5 adds a supported fully-funded, long-only, single-currency spot quote protocol.
The verifier resolves exact persisted source artifacts, validates data and
configuration bindings, executes candidate and buy-and-hold programs, reconciles
cash/positions independently, and persists a signed complete backtest package.
The three accepted requirements are:

- `LKI-REQ-03b228ea-413a-44bd-9c03-b2ec213eb87c`: G5 protocol requirements;
- `LKI-REQ-48cb8404-8a40-44d6-88bd-b43dc1a5499d`: identical-input deterministic replay;
- `LKI-REQ-f7726b90-9dff-4a26-b500-df32ca5c2f48`: required full-backtest outputs.

`docs/backtest_protocol.md` defines the exact supported contract, source and
cost assumptions, failure semantics, package fields and `/backtests/{id}` read
API. G5 PASS is `BACKTESTED`, not profitability or execution permission. The
fuller accounting, data-validity and execution-realism SRS sections are not
closed by association with this protocol.

G6 adds signed fixed-intent execution counterfactuals, persisted cost calibration
and validation sources, effective fees/tiers, independent depth/fee/latency math,
liquidity budgets, native venue controls and capacity/uncertainty curves. Its
supported scope and limited public-snapshot confidence are explicit in
`docs/execution_economics.md`. The additional accepted IDs are:

- `LKI-REQ-5ee003a8-c9b4-482d-81fd-8e001ea7a773`: supported G6 protocol;
- `LKI-REQ-c3628bab-1029-4e6f-8e15-d4485d02cf7f`: component versus implementation-shortfall distinction;
- `LKI-REQ-51391458-0ea2-4508-bd10-4cd3400ca4de`: no duplicate cost deductions.

The latter two were previously VERIFIED, not new requirement coverage. Broad
venue-adapter, cost-calibration, derivative and execution-fidelity sections are
not silently closed by this bounded integration.

G7 adds prospectively registered chronological validation of the frozen G5
program with the original G6 economic policy and latency tape. Exact future
observation grids, actual availability, event-horizon separation and embargo,
raw provider/event bindings, signed lineage and conservative trial budgets are
checked before promotion. Signed results become inheritable research exposure.
The four accepted controls are:

- `LKI-REQ-5cc8c4f0-f317-4e2b-983e-5936e9c37098`: tests selected before their results;
- `LKI-REQ-d9be817a-05bf-43f4-a3eb-10a929b6352f`: no default IID random folds;
- `LKI-REQ-255add46-94c0-4b21-a180-4cde8bab0630`: full event-overlap purging and embargo;
- `LKI-REQ-0d35fa4e-ef07-40ed-b2f7-0b66078a5ab0`: predeclared horizon-derived method.

The overlap control was previously VERIFIED. `docs/out_of_sample.md` defines
the bounded fixed-program protocol. Rolling retraining, nested/cross-sectional
selection and the broad validation-methods umbrella are not accepted by association.

## Current executed evidence

`docs/acceptance/g7-oos-2026-09-07.json` binds all eighteen accepted IDs to
the SRS hash, 53 source/test/config hashes and **595 executed passing tests**, zero
failures/skips, 981.49 seconds. The two warnings are pre-existing dependency
deprecations. The recorder checked source hashes before and after execution.
Ruff, Mypy across all 69 source modules, and evidence-aware registry validation
also passed. The previous immutable early-gate manifest remains historical;
current entries point to the renewed manifest, not stale source hashes.

G7 focused verification passed 108 calculation/statistics tests and eight real
CLI/PostgreSQL/HTTP flows. Independent review exposed unfrozen development
latency assumptions and missing raw-provider binding; both were fixed and
regression-tested. Exhaustive small interval-set oracles verify both K-fold and
CPCV purging, including test labels extending beyond the test decision window.
The legacy embargo assertion was corrected to start after the actual label
horizon and strengthened to test full interval non-overlap.

G5 verification includes real OS-process CLI restarts, PostgreSQL transactions,
signed evidence and HTTP reads; hand-calculated candidate/benchmark PnL;
ambient Decimal-context independence; missing costs; raw/normalized data and
candidate/code binding failures; unsigned evidence and invented metrics;
atomic rollback; idempotency; deferred/partial order ledgers; native quantity
and price constraints; sell-side solvency; causal history; and independent fee
fault injection. The independent adversarial test suite first exposed defects,
then passed after the production fixes. Valid financial tests were not weakened.

The paper defect checkpoint separately passed 19 tests and eliminated the nine
inherited type errors. Missing projections roll back financial transactions;
unsupported contracts cannot enter the spot ledger. It claims no additional
paper-service SRS acceptance.

## Remaining dependency boundary

Signed G8–G13 execution is still unsupported. Predeclared, dependence-aware G8
statistical integration is next. G6's conditional model ranges do not prove
real-market edge or future readiness. Generic strategy-code integration,
derivatives/cross-currency and passive execution remain outside the supported
G5/G6/G7 protocols.

Full G1 semantic-family classification, G2 timing/universe coverage and authentic
data acquisition, G4 observed-economics provenance and additional prescreens,
paper/portfolio/model-risk admission, notification workers, operational
acceptance and the mandatory real 24-hour guarded soak remain open.

The earlier Binance HTTP 451 and missing LLM/Telegram credentials are historical
external findings, not newly measured health. They do not excuse incomplete
local adapters or integrations. Test-only market fixtures prove software
controls, not real market edge, observed liquidity, external billing or the soak.
