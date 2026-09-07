# LIKI

An evidence-governed quantitative research office built against
[`docs/LIKI_SRS.md`](docs/LIKI_SRS.md). **Real-money execution is prohibited.**

## Current status

This is a work-in-progress implementation checkpoint, not an accepted production
release. The requirement-level matrix is `requirements_registry.json`; it does
not claim full SRS acceptance. See `docs/acceptance_traceability.md` for the
current acceptance gaps and evidence boundaries.

Implemented modules include the authenticated PostgreSQL event store, research
and trial ledgers, scheduler leases, data/statistics/financial primitives,
paper execution, inference routing, governance, operator API and dashboard,
notification delivery, encrypted backups, and initial portfolio/model-risk/SLO
services. A credential-scoped command runtime now drives persisted G0–G6
screening with signed snapshot/revision-bound evidence, audited blocked-state
re-entry, and deterministic operator read models. G5 executes the supported
fully-funded spot quote protocol and its benchmark from persisted raw data.
G6 adds separate signed execution economics, independent cost/latency arithmetic
and conditional capacity ranges without changing G5 evidence. See
`docs/early_gates.md`, `docs/backtest_protocol.md` and `docs/execution_economics.md`.

Fourteen controls are `ACCEPTED` (eight early-gate, three G5, G6's supported
protocol and two integrated cost-accounting controls), backed by a 495-test
executed checkpoint and source-bound evidence; 33 other `VERIFIED` controls
retain their narrower status. The
registry now includes 548 requirements after recovering eight omitted explicit
SRS checklists without changing existing IDs. Full gate coverage, signed G7–G13
integration, remaining adversarial validation and the required guarded soak
are not complete. The registry is not a production-readiness claim.

## Local development

Python 3.12+, `uv`, and PostgreSQL are required. Review `scripts/setup.sh` before
running it: it installs development tooling and initializes local development
database roles. Runtime credentials are stored outside version control.

```sh
bash scripts/setup.sh
uv run uvicorn liki.server:create_app --factory --host 0.0.0.0 --port 3000 --reload
```

The dashboard requires a scoped operator credential. Administrative credential
issuance is available through `uv run python -m liki.manage --help`; credentials
must never be committed or placed in browser storage. External inference and
Telegram require explicitly configured credentials; there is no live-order API.

## Verification

```sh
uv run pytest
uv run ruff check .
uv run mypy liki
uv run python tools/requirements.py check
```

Integration tests create and remove uniquely named disposable PostgreSQL
databases. A passing traceability syntax check is not production acceptance.
Financial golden fixtures and independent accounting, gate forgery rejection,
workload authorization, paper safety latches, and transactional recovery have
focused tests. The G6 checkpoint passed all 495 tests, repository Ruff, all 67
source modules' Mypy checks, and evidence-aware traceability validation. This
does not replace production or full-SRS acceptance.