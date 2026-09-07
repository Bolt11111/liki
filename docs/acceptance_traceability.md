# Acceptance traceability — 2026-09-07

**Authority:** attached `LIKI_SRS.md` v1.4 (byte-identical to the repository
copies) and `requirements_registry.json`. This is not system acceptance.

## Current requirement matrix

| Status | Count | Meaning |
|---|---:|---|
| ACCEPTED | 11 | Eight early-gate controls and three supported G5 protocol requirements, closed by executed source-bound evidence |
| VERIFIED | 35 | Earlier focused verification; not silently upgraded to acceptance |
| IN_PROGRESS | 3 | Existing Telegram status, owner notification and alert-deduplication integrations |
| NOT_STARTED | 499 | No completed atomic traceability claim; related code may exist |
| Total | 548 | Existing IDs preserved; eight omitted explicit SRS list contracts recovered |

**46/548 (8.39%) have verification or acceptance evidence. Only 11/548 (2.01%)
are ACCEPTED.** These figures are not whole-system production readiness.

The previous checkpoint reported 43/540 (7.96%) with verification or acceptance
evidence and 8/540 (1.48%) ACCEPTED. Review found that the uppercase-only
extractor omitted eight explicit requirement/output checklists, including G5
and section 17.2. The compiler now retains these declarative list contracts.
No SRS text, source hash, existing requirement ID or prior evidence was erased.
The denominator correction is not eight newly requested product features.

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

## Current executed evidence

`docs/acceptance/g5-protocol-2026-09-07.json` binds all eleven accepted IDs to
the SRS hash, exact source/test hashes and **300 executed passing tests**, zero
failures/skips, 658.39 seconds. The two warnings are pre-existing dependency
deprecations. The recorder checked source hashes before and after execution.
Ruff, Mypy across all 63 source modules, and evidence-aware registry validation
also passed. The previous immutable early-gate manifest remains historical;
current entries point to the renewed manifest, not stale source hashes.

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

Signed G6–G13 execution is still unsupported. G6 historical costs, latency,
liquidity/capacity and stress integration is next; point estimates in G5 do not
close it. Generic strategy-code integration, derivatives/cross-currency and
passive execution remain outside the supported G5 protocol.

Full G1 semantic-family classification, G2 timing/universe coverage and authentic
data acquisition, G4 observed-economics provenance and additional prescreens,
paper/portfolio/model-risk admission, notification workers, operational
acceptance and the mandatory real 24-hour guarded soak remain open.

The earlier Binance HTTP 451 and missing LLM/Telegram credentials are historical
external findings, not newly measured health. They do not excuse incomplete
local adapters or integrations. Test-only market fixtures prove software
controls, not real market edge, observed liquidity, external billing or the soak.
