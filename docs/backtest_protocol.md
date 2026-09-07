# Signed G5 spot backtest protocol

`VerificationRunner.execute(..., gate_id=5)` runs the persisted protocol, not a
researcher's supplied fills, metrics, or PASS flags. The same scoped
`liki.research_runtime` `verify` and `decide` commands drive G0 through G5.
G5 PASS means `BACKTESTED`, not economic validation or execution permission.
G6 through G13 remain unsupported by this verifier version.

## Supported contract

The first integrated protocol is `spot-quote-protocol-v1`: one venue, one
instrument, fully funded long-only spot, unit multiplier, and identical quote
and settlement currencies. The candidate's immutable `backtest_strategy` is a
strict `StrategyProgram`: `lagged-momentum-v1` or `buy-hold-v1`, native-unit
quantity, lookback, and threshold. Signal inputs are prior available quote
observations; the current quote may determine execution but cannot determine
the signal. The benchmark is a separately executed buy-and-hold program.

`research/backtest-plan-v1` contains `BacktestPlan`. It binds candidate/hash,
snapshot, dataset, protocol, code/environment hashes, explicit deterministic
seed policy, starting cash, account tier, execution/cost versions, latency,
participation bound, observation-gap limit, benchmark, tail confidence, and
named predeclared half-open scenario/regime windows. It must predate the
evaluation snapshot. There is no runtime source-code evaluation or plugin
loading from an agent-authored artifact.

## Data and cost provenance

The data role first persists a `DatasetManifest` and its raw JSON payload
through `DataService` or the runtime's `dataset` action. The payload must
validate as `QuoteReplayData` (`spot-quote-tape-v1`), including the effective
instrument specification, specification availability, historical fee schedules
and their availability, and chronological F1 bid/ask/quantity observations.
The quantity is explicitly executable base quantity at that observation, not
the future volume of an OHLC interval or fabricated queue priority.

G5 resolves raw artifacts from the **specific dataset persistence event**, not
an arbitrary same-hash artifact. It verifies retained bytes, normalized content
hash, schema hash, instrument/time/fidelity identity, quality, retrieval
chronology, fee availability, native price increments, and the maximum gap.
Revised, missing, future, ambiguous or unsupported inputs block. An authenticated
producer and content hash establish integrity, not truth of a market source;
authentic external acquisition acceptance remains separate.

All costs must be declared. Historical fees and observed spread are explicit;
spread is embedded in executable fill prices and is not subtracted again.
Additional slippage and impact are explicit nonnegative basis-point **model
estimates**, deducted as cash costs. Funding, borrow, financing, transfers and
liquidation have protocol-specific NOT_APPLICABLE declarations, not silent
numeric defaults. Unsupported contracts cannot use those declarations.
These estimates are not G6 calibration, endogenous-impact or capacity evidence.

## Replay, accounting and artifact

The replay pins Decimal precision 28 and `ROUND_HALF_EVEN`. It maintains
submitted, deferred, partial, filled, rejected and cancelled orders; latency
does not silently erase an order. Working orders share each observation's
participation allowance. Immediate-order remainders and end-of-tape orders are
explicitly cancelled. Original and normalized intents remain distinct.
Unfunded buys, shorts, unaffordable sell-side costs, invalid price bands and
unsupported fill semantics cannot mutate balances. Passive queue-sensitive
fills are not supported by the G5 protocol.

Every observation is reconciled against the independently written FIFO ledger;
historical fees also have a direct arithmetic cross-check independent of the
primary fee helper. Hand-calculated fixtures and fault injection supplement
agreement between implementations. Shared Python Decimal, financial types,
serialization and fee-schedule inputs remain declared common-mode dependencies;
this is not an independent venue execution simulator.

`backtest/protocol-report-v1` contains candidate and benchmark orders, events,
fills, cash/position/equity/reference histories, gross and net PnL, cost
decomposition/applicability, exposure, leverage, turnover, drawdown, historical
tail metric, holding durations (open lots marked censored), predeclared window
attribution, quote-based capacity estimates, rejections, exact configuration,
and transitive input hashes. Capacity estimates explicitly state their model
limitation; they are not a validated capacity curve. Metric formulas retain the
existing versioned finance-metric definitions.

The verifier executes the protocol twice and compares canonical output. It
persists the package and signed gate report atomically with execution, evidence
and audit records. Retries do not duplicate outputs; conflicting operation keys
roll back even an already-computed package. The signature binds candidate
aggregate revision, snapshot, source identity, raw data and the package hash.
Missing dependencies produce a signed BLOCKED report without a success package.

`GET /backtests/{strategy_version_id}` returns the latest execution's report and
optional package under the existing scoped read authorization. A successful
execution is not necessarily a decided gate; consult `/gates/{id}` for decisions.
Blocked executions expose their reasons with `package: null`. `/gates/outcomes`
includes G5 outcome counts.

## Evidence and limits

`tests/test_backtest_runtime.py` drives separate authenticated OS processes,
real PostgreSQL persistence, signatures, rollback, blocked dependencies, forged
reports, forged metrics, idempotency and HTTP reads. Market inputs are clearly
test-only known-answer fixtures, not claimed observations from an external
account. `tests/test_backtest_gate.py` and the independently authored
`tests/finance/test_backtest_adversarial.py` cover financial and causal controls.

Generic strategy-code sandbox integration, derivative/cross-currency protocols,
passive queues, complete data/universe acceptance, calibrated execution stress,
statistical validity, forward paper admission and the 24-hour soak are not
closed by this spot protocol. The low-level F0 helper is not accepted G5 data.
