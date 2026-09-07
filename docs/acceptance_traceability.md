# Acceptance traceability — 2026-09-07

**Authority:** attached `LIKI_SRS.md` v1.4 (byte-identical to the repository
copies) and `requirements_registry.json`. This is not system acceptance.

## Current requirement matrix

| Status | Count | Meaning |
|---|---:|---|
| ACCEPTED | 8 | Atomic early-gate controls closed by real-process/database/API acceptance and source-bound execution evidence |
| VERIFIED | 35 | Earlier focused verification; not silently upgraded to acceptance |
| IN_PROGRESS | 3 | Existing Telegram status, owner notification and alert-deduplication integrations |
| NOT_STARTED | 494 | No completed atomic traceability claim; some related code exists |
| Total | 540 | Persistent IDs and normative source text unchanged |

**43/540 (7.96%) have verification or acceptance evidence. Only 8/540 (1.48%)
are ACCEPTED under the SRS Definition of Done.** Do not describe 7.96% as full
SRS acceptance or infer module completion from this count.

## Closed vertical slice

The runtime now supports authenticated campaign and artifact submission, raw
dataset persistence, research/trial registration, predeclared snapshots,
signed G0–G4 execution, serialized decisions, blocked dependency re-entry and
operator/audit reads. No external inference calls or live orders are involved.

The eight closed IDs cover:

- G3's structured feasibility declaration, including a nonblank empirical
  pattern without forcing a mechanism narrative;
- rejection of known fatal economics before a full backtest;
- monotonic evidence-versioned candidate transitions and explicit re-entry;
- BLOCKED versus FAIL semantics and separate persisted outcome counts;
- append-only, serialized gate decisions and rejection of competing siblings.

Exact requirement IDs and named test references live in the registry. The
machine-readable evidence is
`docs/acceptance/early-gates-2026-09-07.json`: **236 passed, zero failures/skips**,
460.06 seconds, two third-party deprecation warnings. It includes both empirical
and mechanism flows, real CLI restarts, missing dependencies, sample-minimum
enforcement, stale family evidence, cross-family conclusive failures, forged
metrics, role restrictions and signed-report reuse after snapshot round trips.

The evidence recorder actually executes pytest and pins source hashes before
and after execution. The requirement checker rejects stale/missing evidence,
missing test symbols, unexecuted tests and unknown statuses. Legacy VERIFIED
prose remains historical evidence, not an ACCEPTED manifest.

## Baseline and review evidence

- Starting commit: `c66949bfa54e368431403056558c10e57717678f`.
- Initial complete suite: 186 passed in 299.06 seconds; Ruff passed.
- First runtime acceptance: 48 passed in 235.63 seconds.
- After independent review: 74 gate/cross-module tests passed in 338.12 seconds.
- Final early-gate checkpoint: 236 passed; affected-module type checking and
  repository lint passed. The inherited nine paper-service type errors were
  tracked separately rather than hidden by narrowing a claimed whole-project
  typecheck result.

The prior duplicate test expected a bare trial declaration to be hard
falsification. That expectation contradicted G1's conclusive-result requirement.
It now proves pending duplicates block without rejection, while a real signed
hard-failure fixture proves conclusive rejection remains fatal across family
labels. No valid financial assertion was weakened to obtain a passing result.

## Remaining gaps and next dependency

The inventory in `docs/implementation_audit.md` distinguishes working
primitives, disconnected services, missing workflows and obsolete claims.
Do not repeat its baseline investigation without new evidence.

Full G1 canonical semantic-family classification, G2 timing/universe coverage,
and G4 observed-economics provenance, neighborhoods, turnover, statistical proxy,
implementation feasibility and false-negative accounting remain unaccepted.
G5–G13 have no signed production executions. Financial/statistical library tests
do not close those integrations. Paper/portfolio/model-risk, notification
workers, operational acceptance and the required 24-hour guarded soak remain
open. Requirements outside the eight listed in the evidence manifest were not
closed by association with shared infrastructure.

Highest-leverage subsequent feature work: an immutable persisted G5/G6 spot
backtest/execution slice using the existing independent ledger, followed by
G7/G8 with authenticated trial-ledger provenance. Do not parallelize these
interdependent core gates before the predecessor's integration is verified.

The previous checkpoint reported external Binance HTTP 451 and unavailable
LLM/Telegram credentials. These are historical external acceptance boundaries,
not newly probed service health. They do not block completing local adapters,
failure handling or the remaining integration work.
