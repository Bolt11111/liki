# LIKI finance engine

`liki.finance` is the deterministic financial boundary for research and paper paths. It deliberately has no venue credential or network adapter; persistence, event delivery, and authenticated venue calls belong to the parent control plane.

## Accounting and units

Authoritative cash, quantity, price, PnL, fees, and costs are `Decimal`, never floats. `Money` carries a currency; `InstrumentSpec` carries base/quote/settlement currencies, contract multiplier, fixed tick/lot/minimums, effective interval, and version. `effective_at` and `select_fee` fail closed on no or multiple matching effective contracts. `fee_amount` only accepts a selected schedule. `convert_at` requires a point-in-time quote and never implies stablecoin parity.

The primary moving-average `LedgerState` and `reference.independently_reconcile` FIFO lot path are intentionally separate control flows. They must agree on position and marked equity (realized PnL can differ in timing by lot convention). Cost components declare `ADDITIVE`, `DECOMPOSITION`, or `DIAGNOSTIC`; decompositions are rejected as authoritative costs, preventing shortfall/spread/impact double counting. `TransactionCostAnalysis` reports, rather than erases, residuals against a declared benchmark.

## Backtests and paper execution

`DeterministicBacktest` exposes prior available observations to signals and rejects revised or unavailable execution data. `OrderIntent` requires aware, ordered information, signal, eligibility, and submission timestamps. `FillModel` requires an explicit fidelity tier, latency and participation bound; the backtest rejects passive fills whose queue uncertainty is unresolved. OHLC cannot be relabeled as BBO evidence. The replay pins its Decimal context and retains deferred/partial/terminal orders and independently reconciled per-observation balances. See `docs/backtest_protocol.md` for the signed G5 integration and its deliberately bounded spot scope. Low-level model agreement is not observed venue execution evidence.

`OrderRecord` implements the canonical paper state machine. `pretrade_check` performs pure deterministic checks and returns a reservation containing the venue-direction-rounded quantity/limit. The adapter must submit those normalized reservation fields, never the unrounded intent. `PaperService` persists this lifecycle using PostgreSQL transaction locks, immutable configuration artifacts, idempotency keys, and the same `Store.transition` audit chain. `RiskEnvelope` permits `PAPER` only: there is no live path.

`emergency_stop(stop_id=..., scope=..., actions=..., actor_id=..., reason=..., activated_at=..., policy_version=..., strategy_id=..., venue=...)` produces immutable paper stop commands. It supports strategy, venue, and paper-global scopes and exact `BLOCK_NEW`, `CANCEL_WORKING`, `RECONCILE`, and explicit `REDUCE_FLATTEN` actions. `enforce_emergency_stops` is the inference-free pretrade guard. The parent must atomically read active stops with the reservation check, schedule cancellation/reconciliation work for matching active orders, and preserve commands in its audit ledger. `FUTURE_LIVE_GLOBAL_STOP` is deliberately reserved: this module has no live path.

## Derivatives, portfolio, and metrics

`DerivativePosition` separates mark valuation from execution price and has distinct linear/inverse PnL, margin, funding, haircut, and forced-event conversion. Unknown maintenance margin blocks liquidation calculation. Portfolio tools net synchronized orders before execution, expose liquidity/collateral/trapped-capital stress, and use shrinkage for noisy covariance. These numerical risk outputs are model estimates, not observed facts or evidence of alpha.

`config/metrics.json` is the canonical metric registry. `MetricResult` explicitly represents exceptional states; undefined samples never silently turn into zero. `config/finance_models.json` inventories material model assumptions and shared dependencies as common-mode risks.

## Integration contract

`PaperService.start_run()` creates a run in `RECONCILE_ONLY` and stores risk/execution configurations as immutable artifacts. `reconcile()` is required before `submit()`; restarts return to that barrier. `submit()` holds advisory lock `71403218` before reading risk/order state, normalizes the intent, reserves working risk, and writes an acknowledged canonical order. `record_fill()` checks the independent ledger on every fill, converts working risk to position exposure, and is idempotent. `cancel()` only releases remaining working risk; stops block the declared strategy, venue, or whole paper run and never blind-flatten positions. `DeterministicPaperAdapter` is local-only and has no network order method.

The parent API supplies versioned point-in-time market-data/instrument/fee manifests and calls this service under a `paper` credential. It must record dataset gaps and historic availability semantics, attach model/config hashes to backtest artifacts, and never use this library to enable real-money execution.

## Deliberate finance scope limits

The first finance implementation covers the deterministic contracts and bounded models required for a PAPER foundation; it does **not** claim full implementation of all of SRS 18.1–18.31. Open integrations include dynamic venue metadata ingestion/rate limits/STP and trigger semantics, realistic volatility/size calibrated spread-impact curves, borrow/basis and account-wide endogenous fee tiers, data-feed snapshot/resync adapters, cross-venue transfer and multi-leg lifecycle execution, account-observed TCA telemetry/calibration, portfolio-level collateral/margin mark updates, liquidation/ADL venue rules, and execution-evidence counterfactual evaluation. These must remain blocked or explicitly modeled as uncertainty until implemented; no missing input is treated as zero.
