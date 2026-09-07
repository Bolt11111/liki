# Executed acceptance evidence

Each JSON manifest is produced by `python -m tools.acceptance`, which executes
pytest, rejects failures/skips/collection errors, and checks that referenced
source files did not change during the run. It records exact test node IDs,
the SRS hash, requirement IDs, source/test hashes, and the JUnit digest.
It does not copy raw logs, credentials, provider responses, or database contents.

Manifests are immutable checkpoints; use a new filename for a later run.
Requirement `ACCEPTED` records point to a manifest in `acceptance_evidence`.
`python tools/requirements.py check` rejects stale hashes, unexecuted test
references, missing test symbols, unknown status names and invalid evidence
paths. The `acceptance` action still fails until **all** SRS requirements are
accepted; passing `check` alone is not system acceptance.

The recorder provides inspectable execution provenance, not an independent
cryptographic attestation that an adversarial repository author could not forge.
Reviewers still judge whether the actual tests satisfy the cited atomic text.
Test-only market fixtures prove software controls, not real market data quality,
profitability, liquidity, production provider behavior, or the mandatory soak.
