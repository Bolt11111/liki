import numpy as np

from liki.statistics import (
    Applicability,
    SearchProvenance,
    block_bootstrap_mean_interval,
    leave_block_out_fragility,
    transportability_assessment,
)


def provenance() -> SearchProvenance:
    return SearchProvenance(
        ("trial-1",), "family", 1, {"correlation.v1": 1}, ("exposure-1",), {"correlation": "v1"}
    )


def test_dependence_aware_uncertainty_and_transportability_are_explicit():
    dependent = np.repeat([0.01, -0.005, 0.015, 0.0], 10)
    interval = block_bootstrap_mean_interval(
        dependent,
        block_length=4,
        replications=100,
        seed=2,
        confidence=0.95,
        provenance=provenance(),
    )
    fragility = leave_block_out_fragility(dependent, blocks=4, provenance=provenance())
    transport = transportability_assessment(
        [0.02, 0.01, -0.01, -0.02],
        ["source", "source", "target", "target"],
        source_regime="source",
        target_regime="target",
    )
    assert interval.state == Applicability.VALUE and interval.uncertainty is not None
    assert fragility.state == Applicability.VALUE and fragility.uncertainty is not None
    assert transport.effect_difference < 0
