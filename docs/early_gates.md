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

## Runtime integration

`python -m liki.research_runtime` exposes the same persisted services through
bounded, credential-scoped JSON commands. It does not invent campaigns or launch
LLM calls. Supply `--credential-file` and `--request-file`; each request is
`{"action": "...", "payload": {...}}` with a strict action-specific contract.

Actions are `campaign`, `artifact`, `dataset`, `register`, `trial`, `snapshot`,
`verify`, `decide`, `reenter`, and `audit`. Research/data/governance/evaluator
commands retain their existing separate role requirements. A command cannot
borrow another role's authority. The dataset command carries the immutable
manifest plus raw payload metadata and base64 source bytes; hashes are checked
by `DataService`, not trusted from the command.

Verifier calls additionally require `--verifier-key-id` and
`--verifier-key-file` (raw 32-byte Ed25519 private key). Credential and private
key files must be regular, non-symlink files with no group/other permissions.
Enroll only the matching public key using administrative
`python -m liki.manage enroll-verifier --principal ... --key-id ...
--public-key-file ...`. Private keys never enter the database or command output.
Enrollment is code-identity-specific; code changes require a newly enrolled key.

The deterministic verifier is now `deterministic-gates-v3`. Its signature
binds the candidate aggregate revision as well as the snapshot and immutable
input hashes. Legacy reports without this binding cannot authorize a decision.
The runner includes snapshot datasets automatically; callers must not need to
repeat them in G2 inputs. A G1 decision rechecks mutable family history under
the decision transaction lock; a stale signed screen cannot ignore a newly
recorded duplicate or rejection.

`BLOCKED` is not rejection. A declared duplicate without a conclusive hard
failure blocks rather than contributing a scientific failure. A G1 plan must
match the candidate's persisted non-infrastructure trial, dataset set, family ID
and semantic configuration. Equivalent hard failures are considered even when
another family label is supplied.

G4 retains the accepted G3 minimum viable test's observation minimum and binds
that upstream plan into its signed inputs. Ambiguous duplicate sample keys,
impossible capacity observations and cross-dataset benchmark pairing cannot
produce passing arithmetic. Known fatal economics remain `FAIL`, even if a
caller also supplies invalid or unbound metric claims.

For an unavailable dependency, `reenter` requires an expected candidate
revision, a different valid snapshot and a nonblank reason. Only a `BLOCKED`
candidate can use this route; failed candidates cannot erase rejection this
way. Re-entry appends an `EVALUATION_REENTERED` event, preserves every previous
decision, and starts again at G0. A prior signed report cannot be rebound to the
new candidate revision, even after returning to an older snapshot.

`GET /gates/outcomes` reports persisted counts grouped by gate, decision and
reason. `GET /gates/{strategy_version_id}` preserves decision history. There is
no live-execution command. G5's supported spot protocol is documented in
`docs/backtest_protocol.md`; signed G6–G13 execution remains unsupported.

## Signed execution contract

1. The authenticated verifier runner resolves the candidate, all snapshot
   dataset artifacts, the gate plan, policy, and every plan-referenced evidence
   artifact and passes their IDs to `check_gate` with the persisted snapshot row and
   research-object row.
2. Persist the report as `verified-gate-report-v1`, including
   its artifact binding map in the signed execution manifest. The existing evaluator
   reserves `metrics` for `MetricValue` records, so early-gate diagnostics such as
   sample count and Decimal-derived after-cost means are stored under
   `derived_metrics` while `metrics` remains an empty list. Do not convert unknowns
   to false booleans or discard either metrics field.
3. `Evaluation.REQUIRED_CHECKS[1:5]` defines the exact required check names.
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

Canonical semantic family classification across renamed strategies, complete
feature/universe coverage, authentic observed-economics provenance, parameter
neighborhoods, turnover, statistical proxy, implementation feasibility and
false-negative accounting are not closed by this work. An authenticated
artifact producer is not proof that a financial observation happened. The
runtime acceptance fixtures explicitly test software controls, not market edge.
