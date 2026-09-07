"""Deterministic evidence computations for governance changes.

These functions operate only on provenance-backed historical events and labeled
fixtures; they intentionally do not synthesize a score or ask an LLM to predict
market outcomes.
"""

from __future__ import annotations

from .domain import LabeledStressScenario, ReplayEvent, ReplayResult, StressComparison, _canonical_hash


def run_counterfactual_replay(events: tuple[ReplayEvent, ...]) -> ReplayResult:
    if not events:
        raise ValueError("historical replay requires at least one provenance-backed event")
    killed_earlier = sum(event.actual_decision != "KILLED" and event.counterfactual_decision == "KILLED" for event in events)
    winners_lost = sum(
        event.actual_decision != "KILLED"
        and event.counterfactual_decision == "KILLED"
        and event.later_outcome == "WINNER"
        for event in events
    )
    late_deaths = sum(
        event.actual_decision != "KILLED"
        and event.counterfactual_decision == "KILLED"
        and event.later_outcome == "LATE_DEATH"
        for event in events
    )
    saved = sum(
        event.compute_cost_usd
        for event in events
        if event.actual_decision != "KILLED" and event.counterfactual_decision == "KILLED"
    )
    capital_delta = -sum(
        event.statistical_capital
        for event in events
        if event.actual_decision != "KILLED" and event.counterfactual_decision == "KILLED"
    )
    return ReplayResult(
        input_hash=_canonical_hash(events),
        evaluated_branches=len(events),
        killed_earlier=killed_earlier,
        later_winners_lost=winners_lost,
        late_deaths_prevented=late_deaths,
        compute_cost_saved_usd=saved,
        statistical_capital_delta=capital_delta,
    )


def run_labeled_stress_comparison(scenarios: tuple[LabeledStressScenario, ...]) -> StressComparison:
    if not scenarios:
        raise ValueError("stress comparison requires labeled fixtures")
    classes = tuple(sorted({scenario.scenario_class for scenario in scenarios}))
    mismatches = tuple(
        scenario.scenario_id for scenario in scenarios if scenario.expected_decision != scenario.observed_decision
    )
    return StressComparison(
        input_hash=_canonical_hash(scenarios),
        scenario_classes=classes,
        total=len(scenarios),
        matched=len(scenarios) - len(mismatches),
        mismatches=mismatches,
    )
