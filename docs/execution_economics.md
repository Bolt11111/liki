# Signed G6 execution economics

`depth-execution-economics-v1` is an execution counterfactual over the **fixed
candidate and benchmark order intents of an applied, signed G5 PASS**. It never
changes G5 fills, cash, metrics, artifacts or gate decisions. G6 PASS means
`ECONOMICALLY_VALIDATED` under the pinned protocol and assumptions—not live
execution permission, proven alpha or system acceptance.

## Supported economic contract

The supported G5 instrument is single-venue, fully funded, long-only SPOT,
unit multiplier, with quote-currency settlement. Orders are market IOC. Spot
borrowing, derivatives, margin, FX conversions, passive/queue-sensitive orders,
transfers and generic strategy-code execution do not silently receive zero-cost
models. Unsupported contracts or claims block the gate.

Maker executions are inapplicable to market IOC, not assigned a zero maker fee.
Historical taker schedules can contain explicit zero fees or signed rebates;
these are distinct from missing schedules. Funding, borrow/financing and
liquidation carry explicit, validated non-applicability declarations. Existing
derivative arithmetic is separately regression-tested, including inverse funding,
maintenance and forced-conversion fees in settlement units, but that does not
make derivative G6 available.

## Persisted causal provenance

Before pinning an evaluation snapshot, persist through the data-service/CLI:

1. The existing G5 dataset and candidate, unchanged.
2. An `execution-economics-tape-v1` raw payload and dataset manifest. The tape
   contains venue rules, fees, account-tier history, timestamped bid/ask depth,
   non-overlapping trailing traded-volume windows, latency samples and explicit
   evidence/limitation labels. Event time and client availability are separate.
3. Disjoint `execution-impact-samples-v1` calibration and validation raw sources.
   Measurements declare residual impact excluding fees, spread, depth and timing.
   Episode identities are unique; calibration precedes validation, and both
   are available before the execution tape begins.
4. A governance/evaluator-produced `execution/economics-policy-v1` artifact.
   Include it in snapshot `calibration_artifact_ids`; pin it and the execution
   dataset in `gate_input_artifact_ids["6"]`.
5. A `research/economics-plan-v1` binding candidate ID/hash, snapshot ID, code
   hash, execution dataset, policy and explicit non-applicability assumptions.
   Pin this artifact in the same G6 input list.

G6 resolves the actual applied G5 decision and verifies its report signature
against its historical snapshot and state version. It binds the G5 package and
all original input hashes, including the original instrument economic units and
matching BBO observations. A differently denominated or contradictory market
tape cannot substitute for the G5 data while retaining its instrument label.

New manifests must be normalized/schema-hash-bound, unmodified PASS datasets
with exact dataset-event raw sources and causal retrieval metadata. Repaired,
revised, incomplete, unpersisted, mismatched and future-created dependencies
block the gate. Synthetic/testnet liquidity is not economic evidence. Unit and
integration fixtures simulate these source contracts only; they are not market
research outcomes.

## Financial and execution calculations

Each size/latency/adverse-depth/impact case independently replays both the fixed
candidate and benchmark intent sequences. No case retunes signals or edits the
source orders. The grid brackets intended size with at least three distinct
positive multipliers. Every measured latency sample is assigned to every order
across deterministic rotations; interior tail spikes cannot disappear through
percentile subsampling. The protocol refuses excessive replay workloads rather
than dropping scenarios silently.

Signal computation, decision, network, acknowledgement, cancel-confirmation and
market-data delays remain separate. Submission-time timeout and message-rate
events govern new sends. Already in-flight orders are not retroactively rejected
because an acknowledgement later times out. IOC remainder cancellation is
venue-atomic; confirmation delay does not invent additional passive fills.

The venue-side historical book determines modeled execution prices. Client
availability controls information and stale-data checks, not a license to fill
at an old favorable price. Terminal marking also uses historical venue state:
a delayed feed cannot erase a known terminal loss. Missing or stale terminal
valuation blocks the result.

Depth sweeps consume actual ordered levels subject to lot sizes, displayed-depth
bounds and a separate traded-volume participation budget. Multiple orders share
each participation window. Consumed standing depth is not replenished merely
because a later public snapshot repeats it. Price levels are native ticks; order
quantities round down, retaining original and normalized quantities. Tick/lot,
quantity/notional, price-band/deviation, position, cash, trading-status, outage
and message-rate controls reject invalid executions. Both buy and sell cash
deltas must preserve fully funded solvency. Partial fills and unfilled quantities
are explicit; no-touch or passive fill guarantees are implied.

The square-root impact coefficient is derived from residual-impact divided by
square-root participation: empirical minimum, median and maximum calibration
ratios must exactly match the predeclared policy. Independent validation episodes
must fall within those bounds. A failed holdout cannot widen the same model's
bounds; it requires a new model/policy/snapshot. This is a limited model-validation
protocol, not statistical confidence or observed endogenous impact at untraded size.

Each depth fill embeds its spread, depth slippage and adverse native-tick impact
adjustment. Fees use the fill-time half-open effective schedule and account state,
rounded toward positive infinity to the declared venue fee increment (including
conservative signed rebates). Unknown account tier cannot select a hypothetical
favorable tier: the explicit conservative/base state or observed account history
is required.

### Cost treatment and independent arithmetic

| Quantity | Treatment |
|---|---|
| Fee/rebate | Additive signed cash debit/credit, once |
| Spread | Decomposition of execution price versus arrival midpoint |
| Depth slippage | Decomposition of depth price versus best quote |
| Endogenous impact | Decomposition of modeled execution price versus depth price |
| Timing | Decomposition of arrival midpoint versus decision benchmark |
| Implementation shortfall including fees | Diagnostic sum; **never subtracted again** |
| Unfilled opportunity shortfall | Diagnostic, not fabricated cash PnL |

`net_pnl` comes directly from executed consideration, fees, inventory and terminal
mark. The same filled quantities at decision prices define explanatory gross PnL;
gross minus implementation shortfall must equal net. It is not the gross PnL of
all originally requested but unfilled orders.

Primary accounting uses the existing moving-average Decimal ledger. Independent
control paths separately select effective fee/tier state, calculate latency,
allocate native depth, calculate adverse prices and signed fees, maintain cash
and inventory, and reconcile with FIFO accounting. Fault-injection tests must
block disagreements rather than reconcile already-corrupted inputs. Precision is
pinned at 50 digits with half-even arithmetic; exact cash/position comparisons
and a predeclared venue-fee-increment PnL reconciliation tolerance are recorded.
Both paths share source inputs and Python Decimal; those common-mode risks are
declared in `config/finance_models.json` and covered by hand-derived fixtures.

## Fidelity and confidence limits

F0/F1 cannot support this depth protocol. F2 is a **limited public-snapshot model**,
not observed fills, queue priority or millisecond execution accuracy. Model arrival
timestamps do not improve the underlying market-data sampling precision. The
artifact records observation gaps, sample-and-hold assumptions, source fidelity,
missing microstructure limitations and conditional scenario-range semantics.
Adverse depth and impact cases are mandatory. Results at hypothetical size are
`MODELLED_AT_SCALE`, never empirical proof of real own-flow impact.

F3 requires explicit continuous sequence ranges as well as validated status;
missing/gapped ranges block. F4/F5 cannot be claimed simply by relabeling this
aggregated-depth schema; order/account evidence needs its own protocol. Passive
or maker-sensitive strategies remain unsupported rather than using optimistic
queue assumptions. Later readiness gates must retain these limitations.

## Outputs, decisions and operation

`execution/economics-report-v1` contains the complete scenario grid, order/fill
records, cash/inventory and independent reconciliation, cost decompositions,
turnover, partial fills/rejects, latency p50/p95/p99, calibration/validation episode
identities, model/fidelity limits, all assumptions and input artifact hashes.
Capacity is a curve with requested-notional, net-return and benchmark-excess
ranges and fill/rejection measures at each size—not one fitted capacity number.

The intended-size worst cases must satisfy predeclared nonnegative net/excess
return thresholds and minimum fill ratio. Known friction or capacity failure
produces an audited `FAIL`; unknown costs, unsupported fidelity or invalid
provenance produce a signed `BLOCKED`. Reports remain diagnostic evidence even
when a candidate fails. Caller-authored reports/metrics cannot confer approval.

Use the existing authenticated CLI `verify` and `decide` actions with `gate_id: 6`.
`GET /execution-economics/{strategy_version_id}` returns the latest authorized
report/package, including blocked diagnostics. Persistence, evidence, event
history and state transition are transactional, append-only and retry-idempotent.
G7 and later gates remain separate, unimplemented signed runtimes at this checkpoint.
