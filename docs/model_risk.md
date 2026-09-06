# Model-risk lifecycle

`GovernanceService.register_model` remains the inventory writer. `ModelRiskService` provides the persisted lifecycle controls that follow inventory registration: immutable evidence-role links, independent effective challenge, admission to `APPROVED`, typed drift monitoring, bounded use exceptions, retirement, and dependency concentration reporting.

An approval requires both a stored independent `ModelValidation` and an `EffectiveChallenge` with passing evidence-backed checks for conceptual soundness, data appropriateness, implementation, benchmark/challenger comparison, sensitivity, outcome analysis, and limitations/misuse. Challenge artifacts are bound to the model, validation, validator, and challenge IDs. Validation evidence cannot be linked as development/recalibration evidence and later reused as independent validation. When validation evidence is consumed for recalibration, the immutable link retains the historical validation role while the active record moves it to `recalibration_consumed_evidence`.

All methods run inside an authenticated `Store.transaction`. They verify artifact provenance against database records, serialize with the governance lock, write append-only aggregate events, and are subject to workload RLS. Model-risk state writes currently require the `governance` workload role; validator evidence remains produced by evaluator workloads.

Retirement preserves the historical inventory record and requires a retirement artifact. `aggregate_dependencies` exposes active shared dependencies rather than treating correlated models as independent support.
