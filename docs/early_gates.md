# Deterministic G1–G4 checker contract

`liki.early_gate_checks.check_gate` is the pure read-side checker for G1 through
G4. It performs no writes, produces no decision, and cannot accept a caller's
boolean verdict. The signed verification runner must invoke it within the same
authenticated evaluator transaction used to create the gate-report artifact.

## Invocation and binding

```python
report = check_gate(store, conn, actor, snapshot_row, research_object_row, gate_id, input_artifacts)
```

`snapshot_row` is the persisted `evaluation_snapshots` row, not just its
manifest. This lets the checker reject a plan whose immutable artifact timestamp
does not predate `snapshot_row.created_at`. `input_artifacts` is a list of IDs or
already-read artifact rows; every ID is re-read through `Store.artifact`, and the
report contains the resulting `{artifact_id: content_hash}` under both
`input_artifacts` and `referenced_input_artifacts`. The runner must include those
bindings in its signed verifier manifest.

Every `research/early-gate-plan-v1` artifact is strict `EarlyGatePlan` content:
`candidate_artifact_id`, `candidate_hash`, `snapshot_id`, one `gate_id`, and
exactly one matching `g1`/`g2`/`g3`/`g4` block. This pinning plus the persisted
creation time prevents a candidate-specific plan from being substituted after the
evaluation snapshot is created. A `governance/early-gate-policy-v1` input is
required for G1 and G4; it must be governance-authored, predate the snapshot,
and both its artifact `policy_version` and content must equal the snapshot's
policy version for that gate. Numeric cooldown and G4 thresholds come only from
this versioned policy artifact—none are calibrated or invented by checker code.

## Required evidence artifacts

### G1 — duplicate, family, and cooldown

The G1 plan supplies the six-component `FamilyKey`, a persisted `family_id`, and
the exact `trial_type`, semantic configuration, datasets, and metrics. The
checker derives the trial semantic hash using `Research.trial`'s canonical hash
formula and queries immutable `research_objects`, `trial_events`,
`lineage_edges`-connected trial state, and `gate_decisions`. Exact candidate
duplicates, cached equivalent trials, hard-invalid reports in the same family,
and active policy-derived cooldowns are facts from those tables, never plan
flags. An equivalent experiment or known hard invalidity sets `hard_invalidity`.

### G2 — data and leakage

The plan names only snapshot-pinned dataset-manifest artifact IDs plus these
bound artifacts:

* `data/feature-timing-v1`: `{"dataset_snapshot_ids": [...], "rows": [FeatureTimingRow, ...]}`
* `data/label-timing-v1`: `{"dataset_snapshot_ids": [...], "rows": [LabelTimingRow, ...]}`
* `data/universe-membership-v1`: `{"dataset_snapshot_ids": [...], "rows": [UniverseMembershipRow, ...]}`

The checker revalidates the immutable `DatasetManifest` and confirms each ID is
registered in `dataset_manifests`. Each row artifact repeats the exact pinned
dataset set. Feature rows must have source time no later than decision time;
labels must finish after their decision and become available only after that
outcome ends; universe rows carry effective, source-available, and decision
timestamps. Failed/quarantined manifests and invalid timing rows are hard
invalidity. Missing artifacts are unknowns and therefore block the gate.

### G3 — falsifiability, not storytelling

G3 requires a structured `FalsifiablePrediction`, `MinimumViableTest`, market
structure, horizon, and nonempty constraints. A mechanism basis records a
mechanism and plausible payer. An empirical basis instead requires a separately
bound immutable observed-pattern artifact with the exact snapshot dataset set.
The checker intentionally does not
grade prose or require a mechanism narrative from a statistically interesting
empirical candidate; it only proves that a falsifiable, snapshot-pinned test was
declared before evaluation.

### G4 — observed cheap-economics evidence

G4 requires one `finance/cheap-economics-v1` artifact containing strict
`G4Evidence`: cost samples with every cost component explicit, corresponding
after-cost benchmark samples, and capacity observations. The plan declares cost
bounds, sample minimum, capacity limit, currency, and benchmark identity; the
versioned policy declares the mean after-cost and benchmark-excess lower bounds.
The checker derives after-cost PnL from gross PnL minus all components using
`Decimal`, checks each declared bound, validates capacity against observed
executable notional and the predeclared limit, and compares only matching sample
IDs to the declared baseline. Missing evidence/policy is an unknown; known cost,
capacity, or predeclared economic failures are hard invalidity.

## Parent integration steps

1. In the authenticated verifier runner, resolve the candidate, all snapshot
   dataset artifacts, the gate plan, policy, and every plan-referenced evidence
   artifact; pass their IDs to `check_gate` with the persisted snapshot row and
   research-object row.
2. Persist the returned report unchanged as `verified-gate-report-v1`, including
   its artifact binding map in the signed execution manifest. The existing evaluator
   reserves `metrics` for `MetricValue` records, so early-gate diagnostics such as
   sample count and Decimal-derived after-cost means are stored under
   `derived_metrics` while `metrics` remains an empty list. Do not convert unknowns
   to false booleans or discard either metrics field.
3. Keep `Evaluation.REQUIRED_CHECKS[1:5]` as the exact required check names.
   Gate decision logic must fail on `hard_invalidity` and block on nonempty
   `unknowns`, consistent with the existing verifier contract.

## Supported scope and deliberate limitations

The checker covers the deterministic G1–G4 conditions that existing immutable
schemas can prove. It does not claim that a textual mechanism is economically
true, infer a missing universe history, choose a numeric threshold, or convert
synthetic/testnet results into observed liquidity evidence. Those unresolved
facts remain explicit unknowns rather than favorable assumptions. It also does
not write cooldowns or gate decisions; those lifecycle writes remain with the
parent-owned evaluation and signed-runner paths.
