# LIKI data and statistics contracts

This module implements the deterministic contracts that sit between a persisted
Trial Ledger (owned by the parent control plane) and research decisions. It does
not grant a gate pass: callers must treat `VALUE` as evidence, not as approval.

## Data exports

- `RawPayloadStore` stores raw provider bytes content-addressably and verifies
  the digest on every read. `DatasetManifest` preserves raw hashes, UTC timing,
  freshness policy, quality, retention/licensing and fidelity limitations.
- `DatasetValidator` returns auditable gaps, duplicate, stale and lookahead
  findings. `require_usable` fails closed on failed or quarantined data; it does
  not impute missing observations.
- `SymbolMaster` resolves one effective-dated instrument specification and
  produces historically available trading universes. Lifecycle events are
  immutable records, so a rename/delisting cannot vanish from historical scope.
- `build_bars`, `asof_join`, and `FeatureResult` enforce interval-end labels,
  incomplete-bar marking, availability-time joins, and a
  `latest_source_timestamp_used` leakage audit. Offline and online consumers
  use these same functions.
- `OrderBook` implements snapshot-plus-delta sequence validation. Any missed
  update invalidates book-derived features until a new snapshot arrives.
- `BinanceMarketDataClient` uses public Spot and USDⓈ-M REST endpoints. It
  exposes 418/429 backoff instructions as `ProviderRateLimited`, paginates
  non-overlapping kline windows, snapshots dynamic filters from `exchangeInfo`,
  retains response provenance, and never disguises provider errors as data.

## Statistics exports

All public inference requires `SearchProvenance`, constructed from persisted
Trial Ledger and dataset-exposure records. No method accepts a hand-entered
number of trials. `InferencePlan` captures predeclared metric/null/family/split
intent separately from exploratory work. `MetricResult` never serializes NaN/infinity into a decision:
it returns `VALUE`, `UNDEFINED`, `INSUFFICIENT_DATA`, `NUMERIC_ERROR`, or
`NOT_APPLICABLE` with provenance and assumptions.

- `probabilistic_sharpe_ratio` and `deflated_sharpe_ratio` follow Bailey and
  López de Prado's non-normality/selection-aware formulation. DSR derives its
  reference threshold from the recorded full search distribution, keyed to every
  persisted trial record rather than an anonymous trial count.
- `probability_of_backtest_overfitting` implements CSCV PBO using all symmetric
  contiguous partitions. `white_reality_check` uses a stationary bootstrap over
  the complete searched model set. `false_discovery_rate_bh` returns the full
  discovered set under a declared FDR target.
- `purged_kfold`, `cpcv_splits`, and `walk_forward_splits` keep label horizons
  out of train/test boundaries. `sequential_z_test` requires the complete
  predeclared schedule and applies a conservative O'Brien-Fleming-shaped
  Lan-DeMets spend with Bonferroni-valid look boundaries. It does **not** claim
  exact joint-look O'Brien-Fleming calibration and is not a shortcut for
  dependent return series.

`DataService` and `migrations/003_data.sql` persist raw public provider bytes
as immutable Store artifacts before writing manifests, effective-dated
instrument specifications, or lifecycle events. Each write is tied to a
`Store.transition` event and outbox entry. Missing historical metadata resolves
to `UNKNOWN`; present-day exchange metadata cannot silently be projected to an
earlier effective date.

Source references: [Binance REST API](https://developers.binance.com/docs/binance-spot-api-docs/rest-api),
[Bailey et al., PBO](https://escholarship.org/uc/item/4w1110bb),
[Bailey & López de Prado, DSR](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf),
and [White (2000)](https://doi.org/10.1111/1468-0262.00152).

## SRS anchors covered

The following is an intentionally narrow implementation mapping. A registry
entry remains `NOT_STARTED`/unaccepted until the owning integration and its
required evidence are complete; this document does not promote it by assertion.

| Implemented contract | Registry IDs | Implementation | Direct tests |
| --- | --- | --- | --- |
| Immutable manifests, raw provenance, point-in-time records, gaps/leakage, raw/canonical/derived separation | `LKI-REQ-bd1a7341-2de4-42a2-80a7-9b6c90c00d4f`, `LKI-REQ-825ca02c-4d3e-4b0a-a2fe-f42bd9b6e9ce`, `LKI-REQ-af5ed3c5-a9e9-45de-bb0b-2f3077bbdb1e`, `LKI-REQ-c5eea68b-4285-4e38-a76b-43ae5254a127`, `LKI-REQ-fc0e3568-9f3d-4fff-9e22-2baa0d80831c` | `models.py`, `provenance.py`, `validation.py`, `data_service.py` | `test_data_integrity.py`, `test_adversarial_data.py`, `test_data_service.py` |
| Effective-dated symbol specifications, no current-to-history projection, `UNKNOWN` historical resolution | `LKI-REQ-b23c4e95-405a-4b29-92d1-8d82866d2207`, `LKI-REQ-14d83406-3371-4a27-9c6a-6c4bbfbb9642`, `LKI-REQ-dc6860c2-1a52-4bbe-94e0-2cc55e50e6e5` | `instruments.py`, `data_service.py`, `003_data.sql` | `test_data_service.py` |
| Snapshot/delta continuity, clock records, feature parity primitives, as-of joins, incomplete bars | `LKI-REQ-a3d2f88b-9164-46ea-9189-557b828f5d96`, `LKI-REQ-43f2d325-2be7-4991-ad36-2f1fa2dfaf1c`, `LKI-REQ-07117966-d9ce-460d-973c-22c8afa5577b`, `LKI-REQ-57ae9cf9-c8a8-4942-87c0-1a620fa54878`, `LKI-REQ-73fce632-80c1-4dd4-96b0-2c208a271ee7`, `LKI-REQ-ff9d06c6-78e9-404e-a42c-6d73faaa6759`, `LKI-REQ-0c516906-d798-4731-8d6e-d0593e0e438c`, `LKI-REQ-e7f33070-d394-4390-afc5-d6dda4e9794e`, `LKI-REQ-c78770fb-3920-4e08-8d85-601ea42db9b4` | `orderbook.py`, `monitoring.py`, `features.py` | `test_data_integrity.py` |
| Public Binance response parsing, dynamic metadata filters, pagination/rate errors, mark/index/funding distinction | `LKI-REQ-d668b0e3-9f25-438a-8d99-a023c6c3a761`, `LKI-REQ-cb54d722-e06e-4bcc-8776-932140af29d0` | `binance.py` | `test_binance.py`, `test_adversarial_data.py` |
| Trial-ledger provenance, PSR/DSR, CSCV PBO, White RC, FDR, temporal resampling/validation, sequential alpha control | `LKI-REQ-b69fade5-284c-49c5-ae71-5b80a24f3288`, `LKI-REQ-9ad0ba32-b52c-4af8-912d-0f4e62bbe3e9`, `LKI-REQ-28f82f3d-8918-4244-9f14-78d039adf7f2`, `LKI-REQ-d9be817a-05bf-43f4-a3eb-10a929b6352f`, `LKI-REQ-403d0c95-141b-419b-a506-48c80bca71e3`, `LKI-REQ-41b0ccb2-1a06-455e-8ede-67e19711ca0f`, `LKI-REQ-55779b57-0c52-476c-b8e9-7f65787fb799`, `LKI-REQ-8239ae88-3724-4967-bd21-f03e94376b28` | `inference.py`, `resampling.py`, `validation.py`, `robustness.py` | `test_inference.py`, `test_validation.py`, `test_adversarial_reference.py` |
| Registered simple-return/drawdown metrics and explicit exceptional states | `LKI-REQ-198d0aed-6acd-4de6-9b6f-ca4525d83e99`, `LKI-REQ-ffb2c825-8039-4712-b6c3-ae4fcf880b6c`, `LKI-REQ-2517ab08-a479-4ae2-8d8f-5927bab026e1`, `LKI-REQ-1b3cc0d1-0412-47f2-a8dd-712a7e337696`, `LKI-REQ-eed15cbf-424f-4869-8624-91686edf774f` | `metrics.py`, `inference.py`, `statistical_methods.json` | `test_inference.py`, `test_adversarial_reference.py` |

The following remain integration responsibilities for their designated parent
modules: durable database ledger writes and campaign/holdout lifecycle (`12`,
`15.1–15.3`, `15.11–15.12`, `15.18–15.21`, `15.23`); external-source snapshot
retention (`13.18`); complete venue-only derivatives/risk-rule histories
(`13.11`, `13.17–13.19`); and financial ledger/PnL, turnover, collateral, and
unit-accounting contracts (`38A.5–38A.14`). The provided contracts fail closed
when those persisted provenance records are not supplied.
